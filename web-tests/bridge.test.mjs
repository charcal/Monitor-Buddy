// The bridge pages, the bridge check and the settings added in version 2.
import { test } from "node:test";
import assert from "node:assert/strict";
import { pageList, calHeading, sampleCal, SAMPLE_HA, fplCountdown } from "../web/js/preview.js";
import { checkBridge, BRIDGE_PATH } from "../web/js/checks.js";
import { bridgeMessage, previewPageFor, redactLog, DEFAULTS } from "../web/js/form.js";
import { parseConfigH } from "../web/js/configh.js";
import { readFileSync } from "node:fs";

const zones = JSON.parse(readFileSync(new URL("../web/vendor/posix_tz_db/zones.json", import.meta.url), "utf8"));
const on = { ...DEFAULTS, pages: { ...DEFAULTS.pages } };

test("the bridge pages hide while bridge_url is empty, like buildPageList", () => {
  const bridgePages = ["ha", "now", "cal", "bus", "fpl", "mister"];
  assert.deepEqual(pageList({ ...on, bridge_url: "" }).filter((p) => bridgePages.includes(p)), []);
  const withBridge = pageList({ ...on, bridge_url: "http://10.0.0.2:8787" });
  assert.deepEqual(withBridge.slice(-6), bridgePages);
  const noNow = pageList({ ...on, bridge_url: "http://10.0.0.2:8787", pages: { ...on.pages, now: false } });
  assert.ok(!noNow.includes("now") && noNow.includes("cal"));
});

test("calHeading: NOW UNTIL, IN n MIN, else the bridge's label", () => {
  const now = new Date(2026, 9, 23, 13, 50, 0);
  const t = Math.floor(now.getTime() / 1000);
  const ev = (start, end, extra = {}) => ({ start, end, all_day: false, label: "TOMORROW 09:30", ...extra });
  assert.equal(calHeading(ev(t - 600, t + 2400), now, false), "NOW UNTIL 14:30");
  assert.equal(calHeading(ev(t - 600, t + 2400), now, true), "NOW UNTIL 2:30PM");
  assert.equal(calHeading(ev(t + 25 * 60, t + 3600), now, false), "IN 25 MIN");
  assert.equal(calHeading(ev(t + 61 * 60, t + 7200), now, false), "TOMORROW 09:30");
  assert.equal(calHeading(ev(t - 600, t + 2400, { all_day: true, label: "TODAY ALL DAY" }), now, false), "TODAY ALL DAY");
});

test("sample events follow the clock format", () => {
  const now = new Date(2026, 9, 23, 13, 50, 0);
  assert.match(sampleCal(now, false)[1].label, /^TOMORROW 14:00$/);
  assert.match(sampleCal(now, true)[1].label, /^TOMORROW 2:00PM$/);
  assert.equal(SAMPLE_HA.length, 3);
});

const res = (status, body, ok = status < 400) => ({ status, ok, json: async () => body });

test("checkBridge statuses", async () => {
  let asked = null;
  const summary = { ok: true, ha: { ok: true, items: [{}, {}] }, now: { ok: true, playing: true, source: "PLEX" }, cal: { ok: true, events: [{}] } };
  const ok = await checkBridge(async (url, opts) => { asked = { url, opts }; return res(200, summary); }, "k1", true);
  assert.equal(ok.status, "ok");
  assert.equal(asked.url, `${BRIDGE_PATH}?fmt=12`);
  assert.equal(asked.opts.headers["X-Buddy-Key"], "k1");
  assert.equal((await checkBridge(async () => res(401, {}))).status, "bad_key");
  assert.equal((await checkBridge(async () => res(404, {}))).status, "not_here");
  // A plain web server's HTML page where the bridge should be.
  assert.equal((await checkBridge(async () => ({ status: 200, ok: true, json: async () => { throw new SyntaxError("html"); } }))).status, "not_here");
  assert.equal((await checkBridge(async () => { throw new TypeError("offline"); })).status, "network");
});

test("bridgeMessage sums up the three pages", () => {
  const msg = bridgeMessage({ status: "ok", summary: {
    ha: { ok: true, items: [{}, {}] }, now: { ok: true, playing: true, source: "PLEX" }, cal: { ok: true, events: [{}] } } });
  assert.equal(msg, "OK — 2 Home Assistant values, playing on PLEX, 1 upcoming event");
  const off = bridgeMessage({ status: "ok", summary: {
    ha: { ok: false, setup: false }, now: { ok: true, playing: false }, cal: { ok: false, setup: true } } });
  assert.equal(off, "OK — Home Assistant not set up, nothing playing, calendar feed not answering");
  assert.match(bridgeMessage({ status: "bad_key" }), /BUDDY_KEY/);
});

test("bridge settings jump the preview to a bridge page that is shown", () => {
  const cfg = { ...on, bridge_url: "http://10.0.0.2:8787" };
  assert.equal(previewPageFor("bridge_url", cfg), "now");
  assert.equal(previewPageFor("check.bridge", { ...cfg, pages: { ...cfg.pages, now: false } }), "ha");
  assert.equal(previewPageFor("bridge_url", { ...on, bridge_url: "" }), "stay");
  assert.equal(previewPageFor("clock_format", cfg), "clock");
});

test("the bridge key never reaches the log", () => {
  assert.equal(redactLog('{"bridge_key":"s3cret","x":1}'), '{"bridge_key":"<redacted>","x":1}');
});

test("config.h import reads the version 2 defines, and an old file doesn't list them as missing", () => {
  const text = `#define BRIDGE_URL "http://192.168.86.48:8787"\n#define PAGE_SECS 15\n#define AUTO_PAGE false\n`
    + `#define CLOCK_FORMAT "12h"\n#define NIGHT_FROM 22\n#define NIGHT_TO 6\n#define NIGHT_LEVEL 0\n#define SHOW_CAL false\n`;
  const r = parseConfigH(text, zones);
  assert.equal(r.config.bridge_url, "http://192.168.86.48:8787");
  assert.equal(r.config.page_secs, 15);
  assert.equal(r.config.auto_page, false);
  assert.equal(r.config.night_from, 22);
  assert.equal(r.config.pages.cal, false);
  const old = parseConfigH('#define THEME 1\n', zones);
  assert.ok(!old.defaulted.includes("bridge_url") && old.defaulted.includes("ticker"));
});

test("bridgeMessage adds bus, FPL and MiSTer when the bridge reports them", () => {
  const base = { ha: { ok: true, items: [] }, now: { ok: true }, cal: { ok: true, events: [] } };
  const msg = bridgeMessage({ status: "ok", summary: { ...base,
    bus: { ok: true, rows: [{}, {}] }, fpl: { ok: true, gw_points: 48 },
    mister: { ok: true, online: true, playing: true, game: "SUPER METROID" } } });
  assert.match(msg, /2 bus routes due, FPL 48 pts, MiSTer running SUPER METROID$/);
  const off = bridgeMessage({ status: "ok", summary: { ...base,
    bus: { ok: false, setup: false }, fpl: { ok: false, setup: false }, mister: { ok: true, online: false } } });
  assert.match(off, /buses not set up, FPL not set up, MiSTer off$/);
  // An older bridge without the new pages: no extra parts.
  assert.doesNotMatch(bridgeMessage({ status: "ok", summary: base }), /bus|FPL|MiSTer/);
});

test("fplCountdown: days and hours, then hours and minutes", () => {
  const now = new Date(2026, 9, 23, 12, 0, 0);
  const t = Math.floor(now.getTime() / 1000);
  assert.equal(fplCountdown(t + 2 * 86400 + 4 * 3600 + 600, now), "2D 04H");
  assert.equal(fplCountdown(t + 3 * 3600 + 25 * 60, now), "3H 25M");
});
