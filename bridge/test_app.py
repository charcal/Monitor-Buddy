"""Tests for buddy-bridge. Run: python -m pytest bridge -q"""
import importlib
import json
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(__file__))


@pytest.fixture()
def bridge(monkeypatch, tmp_path):
    for k in list(os.environ):
        if k.startswith(("HA_", "PLEX_", "JELLYFIN_", "SPOTIFY_", "CAL_", "NOWPLAYING_", "BUDDY_")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TZ", "Europe/London")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import app as mod
    return importlib.reload(mod)


class Resp:
    def __init__(self, body=None, status=200, content=b""):
        self._body, self.status_code, self.content = body, status, content
        self.ok = status < 400

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


def test_clean_makes_drawable_ascii(bridge):
    assert bridge.clean("Beyoncé – Halo") == "BEYONCE - HALO"
    assert bridge.clean("  lots   of\tspace ") == "LOTS OF SPACE"
    assert bridge.clean("emoji 🎵 gone") == "EMOJI GONE"
    long = bridge.clean("The quick brown fox jumps over the lazy dog again and again", 20)
    assert len(long) <= 20 and not long.endswith(" ")


def test_ha_values(bridge):
    v = bridge.ha_value
    assert v({"entity_id": "sensor.t", "state": "21.437", "attributes": {"unit_of_measurement": "°C"}}) == ("21.4", "C")
    assert v({"entity_id": "sensor.p", "state": "1234.5", "attributes": {"unit_of_measurement": "W"}}) == ("1235", "W")
    assert v({"entity_id": "binary_sensor.d", "state": "on", "attributes": {"device_class": "door"}}) == ("OPEN", "")
    assert v({"entity_id": "binary_sensor.m", "state": "off", "attributes": {"device_class": "motion"}}) == ("CLEAR", "")
    assert v({"entity_id": "lock.front", "state": "locked"}) == ("LOCKED", "")
    assert v({"entity_id": "sensor.x", "state": "unavailable"}) == ("--", "")
    assert v({"entity_id": "sensor.mode", "state": "eco_mode"}) == ("ECO MODE", "")


def test_ha_fetch(bridge, monkeypatch):
    monkeypatch.setenv("HA_URL", "http://ha:8123/")
    monkeypatch.setenv("HA_TOKEN", "t")
    monkeypatch.setenv("HA_ENTITIES", "sensor.living=Living room, sensor.power, sensor.nope=Gone, sensor.extra")
    states = {
        "sensor.living": {"entity_id": "sensor.living", "state": "20.5", "attributes": {"unit_of_measurement": "°C"}},
        "sensor.power": {"entity_id": "sensor.power", "state": "350", "attributes": {"unit_of_measurement": "W", "friendly_name": "House power"}},
    }
    seen = []

    def get(url, **kw):
        seen.append(kw["headers"]["Authorization"])
        ent = url.rsplit("/", 1)[1]
        return Resp(states[ent]) if ent in states else Resp(status=404)

    monkeypatch.setattr(bridge.session, "get", get)
    out = bridge.fetch_ha()
    assert out["ok"] and len(out["items"]) == 3          # capped at 3
    assert out["items"][0] == {"label": "LIVING ROOM", "value": "20.5", "unit": "C"}
    assert out["items"][1]["label"] == "HOUSE POWER"
    assert out["items"][2]["value"] == "?"
    assert seen[0] == "Bearer t"


def test_ha_not_configured(bridge):
    assert bridge.fetch_ha() == {"ok": False, "setup": False, "error": "not configured", "items": []}


def test_now_prefers_playing_over_paused(bridge, monkeypatch):
    monkeypatch.setenv("PLEX_URL", "http://plex:32400")
    monkeypatch.setenv("PLEX_TOKEN", "x")
    monkeypatch.setenv("JELLYFIN_URL", "http://jf:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "y")
    plex = {"MediaContainer": {"Metadata": [{
        "type": "episode", "title": "Pilot", "grandparentTitle": "Taskmaster", "parentIndex": 1, "index": 1,
        "viewOffset": 60000, "duration": 2700000, "Player": {"state": "paused"}, "User": {"title": "cal"}}]}}
    jelly = [{"UserName": "cal", "NowPlayingItem": {"Type": "Audio", "Name": "Halo", "Artists": ["Beyoncé"],
              "RunTimeTicks": 2610000000}, "PlayState": {"PositionTicks": 300000000, "IsPaused": False}}]

    def get(url, **kw):
        return Resp(plex) if "plex" in url else Resp(jelly)

    monkeypatch.setattr(bridge.session, "get", get)
    out = bridge.fetch_now()
    assert out["source"] == "JELLYFIN" and out["playing"] and out["artist"] == "BEYONCE"
    assert out["position_s"] == 30 and out["duration_s"] == 261

    monkeypatch.setenv("NOWPLAYING_ORDER", "plex")
    out = bridge.fetch_now()
    assert out["source"] == "PLEX" and out["paused"] and not out["playing"]
    assert out["artist"] == "TASKMASTER S1E1" and out["title"] == "PILOT"


def test_now_nothing_and_errors(bridge, monkeypatch):
    assert bridge.fetch_now()["playing"] is False
    monkeypatch.setenv("PLEX_URL", "http://plex:32400")
    monkeypatch.setenv("PLEX_TOKEN", "x")
    monkeypatch.setenv("NOWPLAYING_ORDER", "plex")
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(bridge.session, "get", boom)
    out = bridge.fetch_now()
    assert out["ok"] is False and "plex" in out["error"]


ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:test
BEGIN:VEVENT
UID:1
DTSTART;TZID=Europe/London:20261023T090000
DTEND;TZID=Europe/London:20261023T100000
SUMMARY:Already finished
END:VEVENT
BEGIN:VEVENT
UID:2
DTSTART;TZID=Europe/London:20261023T220000
DTEND;TZID=Europe/London:20261023T230000
SUMMARY:Late call with the team
END:VEVENT
BEGIN:VEVENT
UID:3
DTSTART;VALUE=DATE:20261024
DTEND;VALUE=DATE:20261025
SUMMARY:Saturday all day
END:VEVENT
BEGIN:VEVENT
UID:4
DTSTART;TZID=Europe/London:20261020T083000
DTEND;TZID=Europe/London:20261020T090000
RRULE:FREQ=WEEKLY;BYDAY=TU
SUMMARY:Weekly stand-up
END:VEVENT
BEGIN:VEVENT
UID:5
DTSTART;TZID=Europe/London:20261023T230000
DTEND;TZID=Europe/London:20261023T233000
STATUS:CANCELLED
SUMMARY:Cancelled thing
END:VEVENT
END:VCALENDAR
"""


def test_calendar_events(bridge):
    now = datetime(2026, 10, 23, 21, 30, tzinfo=bridge.TZ)   # a Friday
    events = bridge.calendar_events([ICS], now, 7)
    titles = [e["title"] for e in events]
    assert titles[0] == "Late call with the team"
    assert "Already finished" not in titles and "Cancelled thing" not in titles
    assert titles[1] == "Saturday all day"
    assert titles[2] == "Weekly stand-up"                      # the recurrence on Tue 27th
    j = [bridge.event_json(e, now, False) for e in events]
    assert j[0]["label"] == "TODAY 22:00" and j[0]["title"] == "LATE CALL WITH THE TEAM"
    assert j[1]["label"] == "TOMORROW ALL DAY" and j[1]["all_day"]
    assert j[2]["label"] == "TUE 08:30"
    assert bridge.event_json(events[0], now, True)["time"] == "10:00PM"


def test_api_key_guard(bridge, monkeypatch):
    monkeypatch.setenv("BUDDY_KEY", "s3cret")
    import importlib
    mod = importlib.reload(bridge)
    c = mod.app.test_client()
    assert c.get("/health").status_code == 200
    assert c.get("/api/ha").status_code == 401
    r = c.get("/api/ha", headers={"X-Buddy-Key": "s3cret"})
    assert r.status_code == 200 and r.get_json()["error"] == "not configured"
    assert c.get("/api/summary?key=s3cret").status_code == 200


def test_summary_shape(bridge):
    c = bridge.app.test_client()
    body = c.get("/api/summary").get_json()
    assert set(body) == {"ok", "ha", "now", "cal", "bus", "fpl", "mister", "news"}
    assert body["now"]["playing"] is False
    assert len(json.dumps(body)) < 3000   # comfortably small for the Buddy


# ── Next bus ──────────────────────────────────────────────

def test_bus_rows_group_and_sort(bridge, monkeypatch):
    monkeypatch.setenv("TFL_STOPS", "52184=Shooters Hill, 490012345E")
    monkeypatch.setenv("TFL_LINES", "89,244")
    calls = []
    arrivals = {
        "490099999W": [{"lineName": "89", "destinationName": "Lewisham", "timeToStation": 700},
                       {"lineName": "89", "destinationName": "Lewisham", "timeToStation": 150},
                       {"lineName": "486", "destinationName": "Bexleyheath", "timeToStation": 30}],
        "490012345E": [{"lineName": "244", "destinationName": "Queen Elizabeth Hospital", "timeToStation": 45},
                       {"lineName": "89", "destinationName": "Lewisham", "timeToStation": 1300},
                       {"lineName": "89", "destinationName": "Lewisham", "timeToStation": 1900}],
    }

    def get(url, **kw):
        calls.append(url)
        if url.endswith("/StopPoint/Sms/52184"):
            return Resp({"naptanId": "490099999W"})
        return Resp(arrivals[url.split("/")[-2]])

    monkeypatch.setattr(bridge.session, "get", get)
    out = bridge.fetch_bus()
    assert out["ok"] and out["stop"] == "SHOOTERS HILL"
    assert out["rows"][0] == {"line": "244", "dest": "QUEEN ELIZABETH", "mins": [0]}
    assert out["rows"][1] == {"line": "89", "dest": "LEWISHAM", "mins": [2, 11, 21]}   # capped at 3 times
    assert all(r["line"] != "486" for r in out["rows"])                                  # filtered by TFL_LINES
    bridge.fetch_bus()
    assert sum("/Sms/" in c for c in calls) == 1                                          # the code is looked up once


def test_bus_not_configured_and_errors(bridge, monkeypatch):
    assert bridge.fetch_bus()["setup"] is False
    monkeypatch.setenv("TFL_STOPS", "490012345E")
    monkeypatch.setattr(bridge.session, "get", lambda *a, **k: Resp(status=503))
    out = bridge.fetch_bus()
    assert out["ok"] is False and out["setup"] is True


# ── Fantasy Premier League ────────────────────────────────

def fpl_fake(monkeypatch, bridge, *, finished, data_checked):
    data = {
        "bootstrap-static/": {"events": [
            {"id": 8, "is_current": False, "finished": True, "data_checked": True},
            {"id": 9, "is_current": True, "finished": finished, "data_checked": data_checked},
            {"id": 10, "is_next": True, "deadline_time": "2026-10-31T18:30:00Z"}]},
        "entry/1234567/": {"name": "Cal's Calamity XI", "summary_overall_points": 512,
                           "summary_overall_rank": 845210, "summary_event_points": 48,
                           "leagues": {"classic": [{"id": 314, "name": "Overall", "entry_rank": 845210},
                                                   {"id": 797425, "name": "The Office League", "entry_rank": 3}]}},
        "entry/1234567/event/9/picks/": {"entry_history": {"event_transfers_cost": 4},
                                         "picks": [{"element": 1, "multiplier": 2}, {"element": 2, "multiplier": 1},
                                                   {"element": 3, "multiplier": 0}]},
        "event/9/live/": {"elements": [{"id": 1, "stats": {"total_points": 9}}, {"id": 2, "stats": {"total_points": 6}},
                                       {"id": 3, "stats": {"total_points": 15}}]},
    }
    monkeypatch.setattr(bridge.session, "get", lambda url, **k: Resp(data[url.split("/api/", 1)[1]]))


def test_fpl_live_gameweek(bridge, monkeypatch):
    monkeypatch.setenv("FPL_TEAM_ID", "1234567")
    fpl_fake(monkeypatch, bridge, finished=False, data_checked=False)
    out = bridge.fetch_fpl()
    assert out["team"] == "CAL'S CALAMITY XI"
    assert out["gw"] == 9 and out["live"] is True
    assert out["gw_points"] == 9 * 2 + 6 - 4          # captain doubled, bench ignored, hit taken
    assert out["next_gw"] == 10 and out["deadline"] == int(datetime(2026, 10, 31, 18, 30, tzinfo=__import__("datetime").timezone.utc).timestamp())
    assert out["rank"] == 845210 and out["total"] == 512


def test_fpl_between_gameweeks(bridge, monkeypatch):
    monkeypatch.setenv("FPL_TEAM_ID", "1234567")
    fpl_fake(monkeypatch, bridge, finished=True, data_checked=True)
    out = bridge.fetch_fpl()
    assert out["live"] is False and out["gw_points"] == 48


def test_fpl_not_configured(bridge, monkeypatch):
    assert bridge.fetch_fpl()["setup"] is False
    monkeypatch.setenv("FPL_TEAM_ID", "my team")
    assert bridge.fetch_fpl()["setup"] is False


# ── MiSTer (Zaparoo) ──────────────────────────────────────

def test_mister_playing_idle_and_off(bridge, monkeypatch):
    monkeypatch.setenv("MISTER_URL", "http://mister:7497/")
    sent = []

    def post(url, json=None, **kw):
        sent.append((url, json["method"]))
        return Resp({"jsonrpc": "2.0", "id": json["id"], "result": {"database": {}, "active": [
            {"slot": "background", "systemName": "Music", "mediaName": "x", "started": "2026-10-23T21:00:00Z"},
            {"systemId": "SNES", "systemName": "Super Nintendo", "mediaName": "Super Metroid (Europe)",
             "mediaPath": "/media/fat/games/SNES/Super Metroid.sfc", "started": "2026-10-23T21:10:00Z"}]}})

    monkeypatch.setattr(bridge.session, "post", post)
    out = bridge.fetch_mister()
    assert sent[0] == ("http://mister:7497/api/v0.1", "media")
    assert out["playing"] and out["system"] == "SUPER NINTENDO" and out["game"] == "SUPER METROID (EUROPE)"
    assert out["started"] == 1792789800

    monkeypatch.setattr(bridge.session, "post", lambda *a, **k: Resp({"result": {"active": []}}))
    assert bridge.fetch_mister()["playing"] is False

    import requests

    def off(*a, **k):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(bridge.session, "post", off)
    out = bridge.fetch_mister()
    assert out["ok"] and out["online"] is False and out["playing"] is False


def test_bus_routes_per_stop(bridge, monkeypatch):
    monkeypatch.setenv("TFL_STOPS", "490009803W:89=Memorial Hospital, 490006969N:244")
    monkeypatch.setenv("TFL_LINES", "")
    arrivals = {
        "490009803W": [{"lineName": "89", "destinationName": "Lewisham", "timeToStation": 200},
                       {"lineName": "244", "destinationName": "Queen Elizabeth Hospital", "timeToStation": 60},
                       {"lineName": "486", "destinationName": "North Greenwich", "timeToStation": 90}],
        "490006969N": [{"lineName": "244", "destinationName": "Woolwich", "timeToStation": 400}],
    }
    monkeypatch.setattr(bridge.session, "get", lambda url, **k: Resp(arrivals[url.split("/")[-2]]))
    out = bridge.fetch_bus()
    assert out["stop"] == "MEMORIAL HOSPITAL"
    assert [(r["line"], r["dest"]) for r in out["rows"]] == [("89", "LEWISHAM"), ("244", "WOOLWICH")]


def test_fpl_rank_from_league(bridge, monkeypatch):
    monkeypatch.setenv("FPL_TEAM_ID", "1234567")
    monkeypatch.setenv("FPL_LEAGUE_ID", "797425")
    fpl_fake(monkeypatch, bridge, finished=True, data_checked=True)
    out = bridge.fetch_fpl()
    assert out["rank"] == 3 and out["league"] == "THE OFFICE LEAGUE"
    monkeypatch.setenv("FPL_LEAGUE_ID", "999")          # not one of your leagues: overall rank
    bridge.cache._data.clear()
    out = bridge.fetch_fpl()
    assert out["rank"] == 845210 and out["league"] == "OVERALL"



RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>BBC News</title>
<item><title>Older story</title><pubDate>Sat, 24 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>Breaking: something happened – live</title><pubDate>Sat, 24 Oct 2026 10:30:00 GMT</pubDate></item>
<item><title>Duplicate</title><pubDate>Sat, 24 Oct 2026 09:00:00 GMT</pubDate></item>
</channel></rss>""".encode()

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>The Verge</title>
<entry><title>A gadget</title><updated>2026-10-24T10:00:00Z</updated></entry>
<entry><title>Duplicate</title><updated>2026-10-24T09:30:00Z</updated></entry>
</feed>"""


def test_news_merges_feeds_newest_first(bridge, monkeypatch):
    from datetime import timezone
    monkeypatch.setenv("NEWS_FEEDS", "https://bbc.example/rss.xml=BBC, https://verge.example/atom?a=1")
    monkeypatch.setattr(bridge.time, "time", lambda: datetime(2026, 10, 24, 11, 0, tzinfo=timezone.utc).timestamp())
    feeds = {"https://bbc.example/rss.xml": RSS, "https://verge.example/atom?a=1": ATOM}
    monkeypatch.setattr(bridge.session, "get", lambda url, **k: Resp(content=feeds[url]))
    out = bridge.fetch_news()
    titles = [i["title"] for i in out["items"]]
    assert titles == ["BREAKING: SOMETHING HAPPENED - LIVE", "A GADGET", "DUPLICATE", "OLDER STORY"]
    assert out["items"][0] == {"title": "BREAKING: SOMETHING HAPPENED - LIVE", "source": "BBC", "age_min": 30}
    assert out["items"][1]["source"] == "THE VERGE"       # the feed's own title when no label


def test_news_default_feed_and_errors(bridge, monkeypatch):
    asked = []

    def get(url, **k):
        asked.append(url)
        return Resp(status=503)

    monkeypatch.setattr(bridge.session, "get", get)
    out = bridge.fetch_news()
    assert asked == ["https://feeds.bbci.co.uk/news/rss.xml"]
    assert out["ok"] is False and out["setup"] is True
