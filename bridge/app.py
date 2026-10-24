"""buddy-bridge: the home-server side of Monitor Buddy's Home, Now playing and
Calendar pages.

The Buddy is a small ESP32-C6 with no PSRAM, so everything heavy happens here:
Home Assistant tokens, Plex / Jellyfin / Spotify sessions and calendar (ICS)
parsing with recurring events. The Buddy gets short, display-ready JSON: plain
upper-case ASCII that its 5x7 font can draw, already cut to fit.

    GET /health            liveness, no key needed
    GET /api/ha            up to 3 Home Assistant values
    GET /api/now           what's playing on Plex, Jellyfin or Spotify
    GET /api/cal           the next few calendar events (?fmt=12 for 12-hour times)
    GET /api/bus           next buses at your stops (TfL)
    GET /api/fpl           Fantasy Premier League points, rank and deadline
    GET /api/mister        what's running on the MiSTer (Zaparoo)
    GET /api/summary       all of them at once, for the web flasher's Check button
    GET /spotify/login     one-time Spotify sign-in (stores a refresh token in /data)

Everything is configured with environment variables; see .env.example.
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, redirect, request
from unidecode import unidecode

# ── Configuration ─────────────────────────────────────────

def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_list(name: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,\n]", env(name)) if p.strip()]


TZ = ZoneInfo(env("TZ", "Europe/London") or "UTC")
BUDDY_KEY = env("BUDDY_KEY")
DATA_DIR = Path(env("DATA_DIR", "/data"))
PUBLIC_URL = env("PUBLIC_URL").rstrip("/")   # e.g. https://cal-mini.local:8443/bridge
HTTP_TIMEOUT = float(env("HTTP_TIMEOUT", "6") or 6)

# The Buddy's screen is 320 px wide; size-2 text is 12 px a character.
TITLE_MAX = 40
LABEL_MAX = 14
VALUE_MAX = 10

app = Flask(__name__)
app.json.sort_keys = False

# ── Text for a 5x7 font ───────────────────────────────────

_ALLOWED = re.compile(r"[^A-Z0-9 .,:;!?'&()/+\-%$#*@=_]")


def clean(text, limit: int = TITLE_MAX) -> str:
    """Plain upper-case ASCII the Buddy can draw: accents become letters
    (BEYONCÉ -> BEYONCE), anything else unusual is dropped, runs of spaces
    collapse, and long text is cut on a word boundary where possible."""
    s = re.sub(r"\s+", " ", unidecode(str(text or "")).upper())
    s = re.sub(r" +", " ", _ALLOWED.sub("", s)).strip()
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0]
    return (cut if len(cut) >= limit * 0.6 else s[:limit]).rstrip(" ,.;:-")


# ── A small TTL cache, so the Buddy can poll freely ────────

class TTLCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, tuple[float, object]] = {}

    def get(self, key: str, ttl: float, fn):
        now = time.monotonic()
        with self._lock:
            hit = self._data.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        value = fn()
        with self._lock:
            self._data[key] = (time.monotonic(), value)
        return value


cache = TTLCache()
session = requests.Session()
session.headers["User-Agent"] = "buddy-bridge/1.0"


# ── Home Assistant ────────────────────────────────────────

UNIT_MAP = {"°C": "C", "°F": "F", "℃": "C", "℉": "F", "µg/m³": "UG", "m³": "M3", "ppm": "PPM"}
OPENING = {"door", "window", "garage_door", "opening", "garage"}
PRESENCE = {"motion", "occupancy", "presence", "moving"}


def ha_entities() -> list[tuple[str, str]]:
    """HA_ENTITIES = "sensor.living_temp=Living, sensor.power, lock.front=Door"
    -> [(entity_id, label or "")], at most 3."""
    out = []
    for part in env_list("HA_ENTITIES")[:3]:
        entity, _, label = part.partition("=")
        out.append((entity.strip(), label.strip()))
    return out


def format_number(raw: str) -> str | None:
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")):
        return None
    if abs(n) >= 100 or n == int(n):
        return str(int(math.copysign(math.floor(abs(n) + 0.5), n)))   # half up, not banker's
    return f"{n:.1f}"


def ha_value(state: dict) -> tuple[str, str]:
    """(value, unit) for one entity state, both display-ready."""
    entity = state.get("entity_id", "")
    domain = entity.split(".", 1)[0]
    raw = str(state.get("state", ""))
    attrs = state.get("attributes") or {}
    if raw in ("unavailable", "unknown", ""):
        return "--", ""
    if domain == "binary_sensor" or raw in ("on", "off"):
        cls = attrs.get("device_class", "")
        on = raw == "on"
        if cls in OPENING:
            return ("OPEN" if on else "CLOSED"), ""
        if cls in PRESENCE:
            return ("DETECTED" if on else "CLEAR"), ""
        return ("ON" if on else "OFF"), ""
    if domain == "lock":
        return clean(raw, VALUE_MAX), ""
    num = format_number(raw)
    if num is not None:
        unit = str(attrs.get("unit_of_measurement", "") or "")
        unit = UNIT_MAP.get(unit, unit)
        return num, clean(unit, 4)
    return clean(raw.replace("_", " "), VALUE_MAX), ""


def fetch_ha() -> dict:
    url, token, entities = env("HA_URL").rstrip("/"), env("HA_TOKEN"), ha_entities()
    if not (url and token and entities):
        return {"ok": False, "setup": False, "error": "not configured", "items": []}
    items = []
    for entity, label in entities:
        try:
            r = session.get(f"{url}/api/states/{entity}", timeout=HTTP_TIMEOUT,
                            headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 404:
                items.append({"label": clean(label or entity.split(".")[-1], LABEL_MAX), "value": "?", "unit": ""})
                continue
            r.raise_for_status()
            state = r.json()
        except requests.RequestException as e:
            return {"ok": False, "setup": True, "error": f"home assistant: {type(e).__name__}", "items": []}
        name = label or (state.get("attributes") or {}).get("friendly_name") or entity.split(".")[-1]
        value, unit = ha_value(state)
        items.append({"label": clean(name, LABEL_MAX), "value": value, "unit": unit})
    return {"ok": True, "setup": True, "items": items}


# ── Now playing ───────────────────────────────────────────

NOTHING = {"ok": True, "playing": False, "paused": False, "source": "", "title": "",
           "artist": "", "position_s": 0, "duration_s": 0}


def track(source, title, artist, position_s, duration_s, paused):
    return {"ok": True, "playing": not paused, "paused": bool(paused), "source": source,
            "title": clean(title), "artist": clean(artist),
            "position_s": max(0, int(position_s or 0)), "duration_s": max(0, int(duration_s or 0))}


def episode_tag(season, episode) -> str:
    if season is None or episode is None:
        return ""
    return f" S{int(season)}E{int(episode)}"


def from_plex() -> list[dict]:
    url, token, user = env("PLEX_URL").rstrip("/"), env("PLEX_TOKEN"), env("PLEX_USER").lower()
    if not (url and token):
        return []
    r = session.get(f"{url}/status/sessions", timeout=HTTP_TIMEOUT,
                    headers={"Accept": "application/json", "X-Plex-Token": token})
    r.raise_for_status()
    out = []
    for m in (r.json().get("MediaContainer") or {}).get("Metadata") or []:
        if user and str((m.get("User") or {}).get("title", "")).lower() != user:
            continue
        kind = m.get("type")
        if kind == "track":
            title, artist = m.get("title"), m.get("grandparentTitle") or m.get("originalTitle")
        elif kind == "episode":
            title = m.get("title")
            artist = (m.get("grandparentTitle") or "") + episode_tag(m.get("parentIndex"), m.get("index"))
        else:
            title, artist = m.get("title"), m.get("year") or kind
        state = (m.get("Player") or {}).get("state", "playing")
        out.append(track("PLEX", title, artist, (m.get("viewOffset") or 0) / 1000,
                         (m.get("duration") or 0) / 1000, state == "paused"))
    return out


def from_jellyfin() -> list[dict]:
    url, key, user = env("JELLYFIN_URL").rstrip("/"), env("JELLYFIN_API_KEY"), env("JELLYFIN_USER").lower()
    if not (url and key):
        return []
    r = session.get(f"{url}/Sessions", timeout=HTTP_TIMEOUT,
                    headers={"Authorization": f'MediaBrowser Token="{key}"'})
    r.raise_for_status()
    out = []
    for s in r.json():
        item = s.get("NowPlayingItem")
        if not item:
            continue
        if user and str(s.get("UserName", "")).lower() != user:
            continue
        kind = item.get("Type")
        if kind == "Audio":
            artist = ", ".join(item.get("Artists") or []) or item.get("AlbumArtist")
            title = item.get("Name")
        elif kind == "Episode":
            title = item.get("Name")
            artist = (item.get("SeriesName") or "") + episode_tag(item.get("ParentIndexNumber"), item.get("IndexNumber"))
        else:
            title, artist = item.get("Name"), item.get("ProductionYear") or kind
        play = s.get("PlayState") or {}
        out.append(track("JELLYFIN", title, artist, (play.get("PositionTicks") or 0) / 1e7,
                         (item.get("RunTimeTicks") or 0) / 1e7, play.get("IsPaused")))
    return out


# Spotify: a refresh token from /spotify/login, kept in DATA_DIR.
SPOTIFY_FILE = DATA_DIR / "spotify.json"
_spotify_lock = threading.Lock()
_spotify_access = {"token": "", "expires": 0.0}


def spotify_redirect_uri() -> str:
    return f"{PUBLIC_URL}/spotify/callback" if PUBLIC_URL else request.url_root.rstrip("/") + "/spotify/callback"


def spotify_basic() -> str:
    raw = f"{env('SPOTIFY_CLIENT_ID')}:{env('SPOTIFY_CLIENT_SECRET')}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def spotify_refresh_token() -> str:
    try:
        return json.loads(SPOTIFY_FILE.read_text()).get("refresh_token", "")
    except (OSError, ValueError):
        return ""


def spotify_access_token() -> str:
    with _spotify_lock:
        if _spotify_access["token"] and time.time() < _spotify_access["expires"] - 60:
            return _spotify_access["token"]
        refresh = spotify_refresh_token()
        if not refresh:
            return ""
        r = session.post("https://accounts.spotify.com/api/token", timeout=HTTP_TIMEOUT,
                         headers={"Authorization": spotify_basic()},
                         data={"grant_type": "refresh_token", "refresh_token": refresh})
        r.raise_for_status()
        body = r.json()
        if body.get("refresh_token"):   # Spotify may rotate it
            save_spotify(body["refresh_token"])
        _spotify_access.update(token=body["access_token"], expires=time.time() + body.get("expires_in", 3600))
        return _spotify_access["token"]


def save_spotify(refresh_token: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SPOTIFY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"refresh_token": refresh_token}))
    tmp.replace(SPOTIFY_FILE)


def from_spotify() -> list[dict]:
    if not (env("SPOTIFY_CLIENT_ID") and env("SPOTIFY_CLIENT_SECRET")):
        return []
    token = spotify_access_token()
    if not token:
        return []
    r = session.get("https://api.spotify.com/v1/me/player/currently-playing?additional_types=episode",
                    timeout=HTTP_TIMEOUT, headers={"Authorization": f"Bearer {token}"})
    if r.status_code == 204:
        return []
    r.raise_for_status()
    body = r.json()
    item = body.get("item")
    if not item:
        return []
    if item.get("type") == "episode":
        artist = (item.get("show") or {}).get("name")
    else:
        artist = ", ".join(a.get("name", "") for a in item.get("artists") or [])
    return [track("SPOTIFY", item.get("name"), artist, (body.get("progress_ms") or 0) / 1000,
                  (item.get("duration_ms") or 0) / 1000, not body.get("is_playing"))]


SOURCES = {"plex": from_plex, "jellyfin": from_jellyfin, "spotify": from_spotify}


def now_sources() -> list[str]:
    order = [s.lower() for s in env_list("NOWPLAYING_ORDER")] or ["plex", "jellyfin", "spotify"]
    return [s for s in order if s in SOURCES]


def fetch_now() -> dict:
    found, errors = [], []
    for name in now_sources():
        try:
            found.extend(SOURCES[name]())
        except (requests.RequestException, ValueError, KeyError) as e:
            errors.append(f"{name}: {type(e).__name__}")
    playing = [t for t in found if t["playing"]]
    paused = [t for t in found if t["paused"]]
    best = (playing or paused or [None])[0]
    if best:
        return best
    if errors and len(errors) == len(now_sources()):
        return {**NOTHING, "ok": False, "error": "; ".join(errors)}
    return dict(NOTHING)


# ── Calendar ──────────────────────────────────────────────

def _fetch_ics(url: str) -> bytes:
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    r = session.get(url, timeout=HTTP_TIMEOUT * 2)
    r.raise_for_status()
    return r.content


def _as_local(value, all_day_end: bool = False) -> datetime:
    """An ICS DTSTART/DTEND value as an aware local datetime. A floating time is
    taken as local; an all-day date is local midnight."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=TZ)
    raise ValueError("not a date")


def calendar_events(ics_blobs: list[bytes], now: datetime, days: int) -> list[dict]:
    import icalendar
    import recurring_ical_events

    window_end = now + timedelta(days=days)
    events = []
    for blob in ics_blobs:
        cal = icalendar.Calendar.from_ical(blob)
        for ev in recurring_ical_events.of(cal).between(now - timedelta(days=1), window_end):
            if str(ev.get("STATUS", "")).upper() == "CANCELLED":
                continue
            if str(ev.get("TRANSP", "")).upper() == "TRANSPARENT" and env("CAL_SKIP_FREE", "") == "1":
                continue
            start_raw = ev.get("DTSTART").dt
            all_day = not isinstance(start_raw, datetime)
            start = _as_local(start_raw)
            end_prop = ev.get("DTEND")
            if end_prop is not None:
                end = _as_local(end_prop.dt)
            elif ev.get("DURATION") is not None:
                end = start + ev.get("DURATION").dt
            else:
                end = start + (timedelta(days=1) if all_day else timedelta(0))
            if end <= now:
                continue
            events.append({"start": start, "end": end, "all_day": all_day,
                           "title": str(ev.get("SUMMARY", "") or "(no title)")})
    events.sort(key=lambda e: (e["start"], not e["all_day"]))
    return events


def day_word(d: date, today: date) -> str:
    if d == today:
        return "TODAY"
    if d == today + timedelta(days=1):
        return "TOMORROW"
    if d < today + timedelta(days=7):
        return d.strftime("%a").upper()
    return d.strftime("%d %b").upper().lstrip("0")


def clock_text(t: datetime, h12: bool) -> str:
    if not h12:
        return t.strftime("%H:%M")
    return f"{t.hour % 12 or 12}:{t.minute:02d}{'AM' if t.hour < 12 else 'PM'}"


def event_json(e: dict, now: datetime, h12: bool) -> dict:
    today = now.date()
    if e["all_day"]:
        day = "TODAY" if e["start"] <= now < e["end"] else day_word(e["start"].date(), today)
        time_s = ""
        label = f"{day} ALL DAY"
    else:
        day = day_word(e["start"].date(), today)
        time_s = clock_text(e["start"], h12)
        label = f"{day} {time_s}"
    return {"title": clean(e["title"]), "label": clean(label, 20), "day": day, "time": time_s,
            "start": int(e["start"].timestamp()), "end": int(e["end"].timestamp()),
            "all_day": e["all_day"]}


def fetch_cal(h12: bool = False) -> dict:
    urls = env_list("CAL_ICS_URLS")
    if not urls:
        return {"ok": False, "setup": False, "error": "not configured", "events": []}
    blobs, errors = [], []
    for u in urls:
        try:
            blobs.append(cache.get(f"ics:{u}", 300, lambda u=u: _fetch_ics(u)))
        except requests.RequestException as e:
            errors.append(type(e).__name__)
    if not blobs:
        return {"ok": False, "setup": True, "error": f"calendar: {', '.join(errors)}", "events": []}
    now = datetime.now(TZ)
    try:
        events = calendar_events(blobs, now, int(env("CAL_DAYS", "7") or 7))
    except Exception as e:   # a malformed feed must not take the page down
        return {"ok": False, "setup": True, "error": f"calendar: {type(e).__name__}", "events": []}
    limit = max(1, min(3, int(env("CAL_MAX", "3") or 3)))
    return {"ok": True, "setup": True, "now": int(now.timestamp()),
            "events": [event_json(e, now, h12) for e in events[:limit]]}


# ── Next bus (TfL) ────────────────────────────────────────
# TFL_STOPS: stops as NaPTAN ids (490000123N) or the 5-digit code on the stop's
# sign (52184), each optionally =Label. TFL_LINES limits the routes shown.

TFL_API = "https://api.tfl.gov.uk"
BUS_ROWS = 3
BUS_TIMES = 3


def tfl_params() -> dict:
    key = env("TFL_APP_KEY")
    return {"app_key": key} if key else {}


def tfl_stop_id(code: str) -> str:
    """A NaPTAN id as is; a 5-digit SMS code looked up once, then cached."""
    if not re.fullmatch(r"\d{5}", code):
        return code

    def lookup():
        r = session.get(f"{TFL_API}/StopPoint/Sms/{code}", params=tfl_params(), timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        body = r.json()
        found = body.get("naptanId") or body.get("id")
        if not found:
            raise ValueError(f"no stop for code {code}")
        return found

    return cache.get(f"tfl-sms:{code}", 7 * 86400, lookup)


def bus_rows(arrivals: list[dict], lines: set[str]) -> list[dict]:
    """Arrivals from one or more stops -> rows of (line, destination) with
    their next few times in minutes, soonest row first."""
    groups: dict[tuple[str, str], list[int]] = {}
    for a in arrivals:
        line = str(a.get("lineName") or a.get("lineId") or "").upper()
        if lines and line not in lines:
            continue
        secs = a.get("timeToStation")
        if not isinstance(secs, (int, float)):
            continue
        dest = clean(a.get("destinationName") or a.get("towards") or "", 16)
        groups.setdefault((line, dest), []).append(max(0, int(secs // 60)))
    rows = [{"line": clean(line, 4), "dest": dest, "mins": sorted(mins)[:BUS_TIMES]}
            for (line, dest), mins in groups.items()]
    rows.sort(key=lambda r: (r["mins"][0], r["line"]))
    return rows[:BUS_ROWS]


def fetch_bus() -> dict:
    stops = env_list("TFL_STOPS")
    if not stops:
        return {"ok": False, "setup": False, "error": "not configured", "rows": []}
    lines = {l.upper() for l in env_list("TFL_LINES")}
    arrivals, label = [], ""
    for entry in stops[:3]:
        # "490009803W:89=Memorial Hospital": stop, optional routes for this
        # stop only (89+N89), optional label.
        code, _, name = entry.partition("=")
        code, _, own = code.partition(":")
        own_lines = {l.strip().upper() for l in own.split("+") if l.strip()}
        label = label or name.strip()
        try:
            stop = tfl_stop_id(code.strip())
            r = session.get(f"{TFL_API}/StopPoint/{stop}/Arrivals", params=tfl_params(), timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            arrivals.extend(a for a in r.json() if not own_lines
                            or str(a.get("lineName") or a.get("lineId") or "").upper() in own_lines)
        except (requests.RequestException, ValueError) as e:
            return {"ok": False, "setup": True, "error": f"tfl: {type(e).__name__}", "rows": []}
    return {"ok": True, "setup": True, "stop": clean(label, 20), "at": int(time.time()),
            "rows": bus_rows(arrivals, lines)}


# ── Fantasy Premier League ────────────────────────────────
# FPL_TEAM_ID: the number in your Points page address,
# fantasy.premierleague.com/entry/1234567/event/9 -> 1234567.
# FPL_LEAGUE_ID (optional): a classic league to take the rank from,
# fantasy.premierleague.com/leagues/797425/standings/c -> 797425.

FPL_API = "https://fantasy.premierleague.com/api"


def fpl_get(path: str, ttl: float):
    def load():
        r = session.get(f"{FPL_API}/{path}", timeout=HTTP_TIMEOUT * 2,
                        headers={"User-Agent": "Mozilla/5.0 buddy-bridge"})
        r.raise_for_status()
        return r.json()
    return cache.get(f"fpl:{path}", ttl, load)


def fpl_epoch(iso: str | None) -> int:
    if not iso:
        return 0
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def fpl_live_points(picks: dict, live: dict) -> int:
    """Gameweek points so far: each starter's live points times its multiplier
    (captain 2, triple captain 3, bench 0), minus transfer hits."""
    points = {e["id"]: (e.get("stats") or {}).get("total_points", 0) for e in live.get("elements", [])}
    total = sum(points.get(p["element"], 0) * p.get("multiplier", 0) for p in picks.get("picks", []))
    return total - ((picks.get("entry_history") or {}).get("event_transfers_cost") or 0)


def fetch_fpl() -> dict:
    team = env("FPL_TEAM_ID")
    if not team.isdigit():
        return {"ok": False, "setup": False, "error": "not configured"}
    boot = fpl_get("bootstrap-static/", 600)
    events = boot.get("events", [])
    current = next((e for e in events if e.get("is_current")), None)
    upcoming = next((e for e in events if e.get("is_next")), None)
    entry = fpl_get(f"entry/{team}/", 300)
    out = {"ok": True, "setup": True, "team": clean(entry.get("name", ""), 20),
           "total": entry.get("summary_overall_points") or 0,
           "rank": entry.get("summary_overall_rank") or 0,
           "gw": 0, "gw_points": 0, "live": False, "next_gw": 0, "deadline": 0,
           "league": "OVERALL"}
    # FPL_LEAGUE_ID: show your rank in that classic league instead. The entry
    # already lists your leagues with your rank in each, so no extra request.
    league_id = env("FPL_LEAGUE_ID")
    if league_id.isdigit():
        league = next((l for l in (entry.get("leagues") or {}).get("classic", [])
                       if str(l.get("id")) == league_id), None)
        if league and league.get("entry_rank"):
            out["rank"] = league["entry_rank"]
            out["league"] = clean(league.get("name", ""), 20)
    if upcoming:
        out["next_gw"] = upcoming["id"]
        out["deadline"] = fpl_epoch(upcoming.get("deadline_time"))
    if current:
        gw = current["id"]
        out["gw"] = gw
        out["gw_points"] = entry.get("summary_event_points") or 0
        # Matches still to settle: count live points from the players' stats.
        if not current.get("data_checked"):
            try:
                picks = fpl_get(f"entry/{team}/event/{gw}/picks/", 600)
                live = fpl_get(f"event/{gw}/live/", 60)
                out["gw_points"] = fpl_live_points(picks, live)
                out["live"] = not current.get("finished", False)
            except requests.RequestException:
                pass   # fall back to the entry summary
    return out


# ── MiSTer now playing (Zaparoo Core) ─────────────────────
# MISTER_URL: the MiSTer running Zaparoo, e.g. http://192.168.86.60:7497

def fetch_mister() -> dict:
    url = env("MISTER_URL").rstrip("/")
    if not url:
        return {"ok": False, "setup": False, "error": "not configured"}
    try:
        r = session.post(f"{url}/api/v0.1", timeout=HTTP_TIMEOUT,
                         json={"jsonrpc": "2.0", "id": secrets.token_hex(4), "method": "media"})
        r.raise_for_status()
        body = r.json()
    except requests.ConnectionError:
        # Switched off or asleep: a normal state, not an error.
        return {"ok": True, "setup": True, "online": False, "playing": False,
                "system": "", "game": "", "started": 0}
    if "error" in body:
        return {"ok": False, "setup": True, "error": "zaparoo: " + clean((body["error"] or {}).get("message", "error"), 30)}
    active = [a for a in ((body.get("result") or {}).get("active") or [])
              if a.get("slot", "primary") == "primary"]
    if not active:
        return {"ok": True, "setup": True, "online": True, "playing": False,
                "system": "", "game": "", "started": 0}
    a = active[0]
    started = 0
    try:
        started = int(datetime.fromisoformat(str(a.get("started", "")).replace("Z", "+00:00")).timestamp())
    except ValueError:
        pass
    return {"ok": True, "setup": True, "online": True, "playing": True,
            "system": clean(a.get("systemName") or a.get("systemId"), 20),
            "game": clean(a.get("mediaName") or a.get("mediaPath", "").rsplit("/", 1)[-1]),
            "started": started}


# ── HTTP ──────────────────────────────────────────────────

def authorised() -> bool:
    if not BUDDY_KEY:
        return True
    given = request.headers.get("X-Buddy-Key") or request.args.get("key", "")
    return secrets.compare_digest(given, BUDDY_KEY)


@app.before_request
def guard():
    if request.path.startswith("/api/") and not authorised():
        return jsonify({"ok": False, "error": "bad key"}), 401
    return None


@app.after_request
def no_store(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _safe(fn):
    try:
        return fn()
    except Exception as e:   # never send the Buddy an HTML error page
        app.logger.exception("fetch failed")
        return {"ok": False, "error": type(e).__name__}


@app.get("/health")
def health():
    return {"ok": True, "service": "buddy-bridge", "key": bool(BUDDY_KEY),
            "ha": bool(env("HA_URL") and env("HA_TOKEN") and ha_entities()),
            "now": [s for s in now_sources() if _source_configured(s)],
            "cal": len(env_list("CAL_ICS_URLS")),
            "spotify_linked": bool(spotify_refresh_token()),
            "bus": len(env_list("TFL_STOPS")), "fpl": env("FPL_TEAM_ID").isdigit(),
            "mister": bool(env("MISTER_URL"))}


def _source_configured(name: str) -> bool:
    return {"plex": bool(env("PLEX_URL") and env("PLEX_TOKEN")),
            "jellyfin": bool(env("JELLYFIN_URL") and env("JELLYFIN_API_KEY")),
            "spotify": bool(env("SPOTIFY_CLIENT_ID") and env("SPOTIFY_CLIENT_SECRET"))}.get(name, False)


@app.get("/api/ha")
def api_ha():
    return jsonify(cache.get("ha", 20, lambda: _safe(fetch_ha)))


@app.get("/api/now")
def api_now():
    return jsonify(cache.get("now", 3, lambda: _safe(fetch_now)))


@app.get("/api/cal")
def api_cal():
    h12 = request.args.get("fmt") == "12"
    return jsonify(cache.get(f"cal:{h12}", 60, lambda: _safe(lambda: fetch_cal(h12))))


@app.get("/api/bus")
def api_bus():
    return jsonify(cache.get("bus", 15, lambda: _safe(fetch_bus)))


@app.get("/api/fpl")
def api_fpl():
    return jsonify(cache.get("fpl", 60, lambda: _safe(fetch_fpl)))


@app.get("/api/mister")
def api_mister():
    return jsonify(cache.get("mister", 5, lambda: _safe(fetch_mister)))


@app.get("/api/summary")
def api_summary():
    h12 = request.args.get("fmt") == "12"
    return jsonify({"ok": True,
                    "ha": cache.get("ha", 20, lambda: _safe(fetch_ha)),
                    "now": cache.get("now", 3, lambda: _safe(fetch_now)),
                    "cal": cache.get(f"cal:{h12}", 60, lambda: _safe(lambda: fetch_cal(h12))),
                    "bus": cache.get("bus", 15, lambda: _safe(fetch_bus)),
                    "fpl": cache.get("fpl", 60, lambda: _safe(fetch_fpl)),
                    "mister": cache.get("mister", 5, lambda: _safe(fetch_mister))})


_spotify_states: dict[str, float] = {}


@app.get("/spotify/login")
def spotify_login():
    if not (env("SPOTIFY_CLIENT_ID") and env("SPOTIFY_CLIENT_SECRET")):
        return "Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET first.", 400
    state = secrets.token_urlsafe(16)
    _spotify_states[state] = time.time()
    q = urlencode({"client_id": env("SPOTIFY_CLIENT_ID"), "response_type": "code",
                   "redirect_uri": spotify_redirect_uri(), "state": state,
                   "scope": "user-read-currently-playing user-read-playback-state"})
    return redirect(f"https://accounts.spotify.com/authorize?{q}")


@app.get("/spotify/callback")
def spotify_callback():
    state = request.args.get("state", "")
    if time.time() - _spotify_states.pop(state, 0) > 600:
        return "That sign-in link expired. Open /spotify/login again.", 400
    if request.args.get("error"):
        return f"Spotify said: {request.args['error']}", 400
    r = session.post("https://accounts.spotify.com/api/token", timeout=HTTP_TIMEOUT,
                     headers={"Authorization": spotify_basic()},
                     data={"grant_type": "authorization_code", "code": request.args.get("code", ""),
                           "redirect_uri": spotify_redirect_uri()})
    if not r.ok:
        return f"Spotify refused the sign-in ({r.status_code}).", 400
    save_spotify(r.json()["refresh_token"])
    _spotify_access.update(token="", expires=0)
    return "Spotify is linked. You can close this tab; the Buddy's Now playing page will pick it up."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(env("PORT", "8787") or 8787))
