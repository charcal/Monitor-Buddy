#!/usr/bin/env python3
"""Keeps the self-hosted flasher in step with your GitHub fork.

Every SYNC_MINUTES it:
  1. downloads the fork's source at FLASHER_REF (default main),
  2. builds the site from its web/ folder the way GitHub Pages does,
     using the fork's own tools/pages_site.py (asset stamping, manifest format),
  3. mirrors the monitor-buddy-<version>.bin of every release from 1.2.0 on
     into firmware/ and writes firmware/releases.json,
  4. writes site.json (the repo, and the bridge address the Buddy should use),
  5. switches /site/current to the new build in one step.

Nothing is rebuilt when neither the commit nor the releases changed.
Standard library only.

Environment:
  GITHUB_REPO        owner/name of your fork (required)
  FLASHER_REF        branch or tag to serve the flasher from (default main)
  SYNC_MINUTES       how often to check (default 30)
  GITHUB_TOKEN       optional; raises GitHub's rate limit, and needed for a private fork
  BRIDGE_DEVICE_URL  the bridge address offered to the Buddy, e.g. http://192.168.86.48:8787
  SITE_DIR           where builds go (default /site); Caddy serves SITE_DIR/current
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = os.environ.get("GITHUB_REPO", "").strip()
REF = os.environ.get("FLASHER_REF", "main").strip() or "main"
MINUTES = max(5, int(os.environ.get("SYNC_MINUTES", "30") or 30))
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
BRIDGE_DEVICE_URL = os.environ.get("BRIDGE_DEVICE_URL", "").strip()
SITE = Path(os.environ.get("SITE_DIR", "/site"))
GITHUB_API = os.environ.get("GITHUB_API", "https://api.github.com").rstrip("/")             # for tests
GITHUB_RAW = os.environ.get("GITHUB_RAW", "https://raw.githubusercontent.com").rstrip("/")   # for tests
CACHE = SITE / ".cache"          # downloaded firmware, by tag; survives rebuilds
STATE = SITE / ".state.json"     # what the current build was made from
KEEP_BUILDS = 2


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def get(url: str, *, api: bool = False, accept: str | None = None) -> bytes:
    headers = {"User-Agent": "monitor-buddy-sync"}
    if accept:
        headers["Accept"] = accept
    elif api:
        headers["Accept"] = "application/vnd.github+json"
    if TOKEN and (url.startswith(GITHUB_API) or "codeload.github.com" in url):
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def api(path: str):
    return json.loads(get(f"{GITHUB_API}/repos/{REPO}/{path}", api=True))


def extract(tar_bytes: bytes, dest: Path) -> Path:
    """The repo tarball into dest; returns its single top folder."""
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
        tf.extractall(dest, filter="data")    # refuses absolute paths, .. and devices
    tops = [p for p in dest.iterdir() if p.is_dir()]
    if len(tops) != 1:
        raise RuntimeError("unexpected tarball layout")
    return tops[0]


def load_pages_site(src: Path):
    """The fork's own tools/pages_site.py, so this site matches its Pages site."""
    os.environ["GITHUB_REPOSITORY"] = REPO
    sys.path.insert(0, str(src / "tools"))
    try:
        sys.modules.pop("pages_site", None)
        import pages_site   # noqa: PLC0415
        return pages_site
    finally:
        sys.path.pop(0)


def firmware_for(ps, tag: str, release: dict) -> bytes | None:
    name = ps.asset_name(tag[1:])
    asset = next((a for a in release.get("assets", []) if a.get("name") == name), None)
    if asset is None:
        log(f"skipping {tag}: no {name} attached")
        return None
    cached = CACHE / tag / name
    digest = (asset.get("digest") or "").lower()
    if cached.is_file():
        data = cached.read_bytes()
        if len(data) == asset.get("size") and (not digest.startswith("sha256:")
                                                or digest[7:] == hashlib.sha256(data).hexdigest()):
            return data
    log(f"downloading {tag}/{name}")
    data = get(asset["browser_download_url"], accept="application/octet-stream")
    if digest.startswith("sha256:") and digest[7:] != hashlib.sha256(data).hexdigest():
        raise RuntimeError(f"{tag}: {name} does not match the release's sha256 digest")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


def cfg_version(ps, tag: str) -> int:
    cached = CACHE / tag / "cfg_v"
    if cached.is_file():
        return int(cached.read_text())
    header = get(f"{GITHUB_RAW}/{REPO}/{tag}/lib/settings/settings.h").decode()
    v = ps.parse_cfg_v(header)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(str(v))
    return v


def build(sha: str, releases: list[dict]) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="src-", dir=SITE))
    try:
        log(f"building the site from {REPO}@{sha[:10]}")
        src = extract(get(f"{GITHUB_API}/repos/{REPO}/tarball/{sha}", api=True), tmp)
        ps = load_pages_site(src)
        out = SITE / f"build-{int(time.time())}"
        shutil.copytree(src / "web", out)
        version = ps.site_version(out)
        log(f"site version {version}: {ps.stamp_assets(out, version)} code URLs stamped")

        rows = [{"tagName": r["tag_name"], "isPrerelease": r["prerelease"], "isDraft": r["draft"],
                 "publishedAt": r.get("published_at") or r.get("created_at") or ""} for r in releases]
        by_tag = {r["tag_name"]: r for r in releases}
        entries = []
        for tag, row in ps.select(rows):
            data = firmware_for(ps, tag, by_tag[tag])
            if data is None:
                continue
            dest = out / "firmware" / tag
            dest.mkdir(parents=True, exist_ok=True)
            (dest / ps.asset_name(tag[1:])).write_bytes(data)
            entries.append(ps.release_entry(tag, row["publishedAt"], row["isPrerelease"], data,
                                            cfg_version(ps, tag)))
        (out / "firmware").mkdir(exist_ok=True)
        (out / "firmware" / "releases.json").write_text(json.dumps(ps.build_manifest(entries), indent=1))
        (out / "site.json").write_text(json.dumps({"repo": REPO, "ref": REF, "commit": sha,
                                                   "bridge_device_url": BRIDGE_DEVICE_URL}, indent=1))
        log(f"{len(entries)} firmware release(s) mirrored")
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def publish(out: Path) -> None:
    """Point SITE/current at `out` in one step, then drop older builds."""
    link = SITE / "current"
    tmp_link = SITE / ".current.tmp"
    if tmp_link.is_symlink() or tmp_link.exists():
        tmp_link.unlink()
    tmp_link.symlink_to(out.name)
    os.replace(tmp_link, link)
    builds = sorted(p for p in SITE.glob("build-*") if p.is_dir())
    for old in builds[:-KEEP_BUILDS]:
        shutil.rmtree(old, ignore_errors=True)


def once() -> None:
    sha = api(f"commits/{REF}")["sha"]
    releases = api("releases?per_page=100")
    fingerprint = {"sha": sha, "bridge": BRIDGE_DEVICE_URL,
                   "releases": sorted((r["tag_name"], r["prerelease"], r["draft"],
                                       tuple(sorted((a["name"], a.get("size")) for a in r.get("assets", []))))
                                      for r in releases)}
    fingerprint = json.loads(json.dumps(fingerprint))   # tuples -> lists, as stored
    try:
        previous = json.loads(STATE.read_text())
    except (OSError, ValueError):
        previous = None
    if previous == fingerprint and (SITE / "current").exists():
        log("up to date")
        return
    publish(build(sha, releases))
    STATE.write_text(json.dumps(fingerprint))
    log("published")


def main() -> int:
    if not REPO or "/" not in REPO:
        log("set GITHUB_REPO to owner/name of your Monitor-Buddy fork")
        return 2
    SITE.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            once()
        except (urllib.error.URLError, OSError, RuntimeError, ValueError, KeyError) as e:
            log(f"sync failed, keeping the current site: {type(e).__name__}: {e}")
        if os.environ.get("SYNC_ONCE"):
            return 0
        time.sleep(MINUTES * 60)


if __name__ == "__main__":
    sys.exit(main())
