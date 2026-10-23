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
SUMMARY:Late call with Rhiannon
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
    assert titles[0] == "Late call with Rhiannon"
    assert "Already finished" not in titles and "Cancelled thing" not in titles
    assert titles[1] == "Saturday all day"
    assert titles[2] == "Weekly stand-up"                      # the recurrence on Tue 27th
    j = [bridge.event_json(e, now, False) for e in events]
    assert j[0]["label"] == "TODAY 22:00" and j[0]["title"] == "LATE CALL WITH RHIANNON"
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
    assert set(body) == {"ok", "ha", "now", "cal"}
    assert body["now"]["playing"] is False
    assert len(json.dumps(body)) < 1500   # comfortably small for the Buddy
