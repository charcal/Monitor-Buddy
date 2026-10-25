"""Screens for Phone Buddy, the pocket e-ink version (Waveshare ESP32-S3-ePaper-1.54).

The bridge draws each screen as a 200 x 200 one-bit picture, so the device only
has to download it and copy it to the panel. Changing a layout here needs no
reflash. Everything in this module is pure: data in, picture out, so it is
tested without a network or a device.

    render(view, data, now, batt, page, pages) -> PIL image, 200 x 200, mode "1"
    panel_bytes(image)                          -> 5000 bytes for the panel

Panel byte order (matches Waveshare's V2 driver): row by row from the top,
25 bytes a row, most significant bit is the leftmost pixel, 1 = white.
"""
from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

W = H = 200
HEADER = 24            # black title bar
FOOTER = 14            # page dots; the device draws OFFLINE over this band
BODY_TOP = HEADER + 4
BODY_BOTTOM = H - FOOTER - 2
PAD = 6
BLACK, WHITE = 0, 1

TITLES = {"news": "HEADLINES", "travel": "TRAVEL", "cal": "CALENDAR", "fpl": "FANTASY PL"}

FONT_DIRS = [os.environ.get("EINK_FONT_DIR", ""), "/usr/share/fonts/truetype/dejavu",
             "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF"]


@lru_cache(maxsize=64)
def font(size: int, mono: bool = False) -> ImageFont.ImageFont:
    name = "DejaVuSansMono-Bold.ttf" if mono else "DejaVuSans-Bold.ttf"
    for d in FONT_DIRS:
        path = os.path.join(d, name) if d else ""
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)   # Pillow's own font, if DejaVu is missing


# ── Text helpers ──────────────────────────────────────────

def text_w(f, s: str) -> float:
    return f.getlength(s)


def wrap(f, text: str, width: int) -> list[str]:
    """Greedy word wrap; a word too long for a line is cut to fit."""
    lines, line = [], ""
    for word in text.split():
        while text_w(f, word) > width:   # very long word: cut it
            cut = len(word)
            while cut > 1 and text_w(f, word[:cut]) > width:
                cut -= 1
            if line:
                lines.append(line)
                line = ""
            lines.append(word[:cut])
            word = word[cut:]
        trial = f"{line} {word}".strip()
        if text_w(f, trial) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def ellipsize(f, s: str, width: int) -> str:
    if text_w(f, s) <= width:
        return s
    while s and text_w(f, s.rstrip() + "...") > width:
        s = s[:-1]
    return s.rstrip() + "..."


def fit(text: str, width: int, max_lines: int, sizes=(18, 17, 16, 15, 14, 13)):
    """The largest size at which `text` wraps into `max_lines`; at the smallest
    size the last line is cut with '...'. Returns (font, lines)."""
    for size in sizes:
        f = font(size)
        lines = wrap(f, text, width)
        if len(lines) <= max_lines:
            return f, lines
    f = font(sizes[-1])
    lines = wrap(f, text, width)[:max_lines]
    lines[-1] = ellipsize(f, lines[-1] + " ...", width) if lines else ""
    return f, lines


def line_h(f) -> int:
    a, d = f.getmetrics()
    return a + d - 1


def draw_lines(d, x, y, f, lines, fill=BLACK) -> int:
    for ln in lines:
        d.text((x, y), ln, font=f, fill=fill)
        y += line_h(f)
    return y


def centre(d, y, s, f, fill=BLACK):
    d.text(((W - text_w(f, s)) / 2, y), s, font=f, fill=fill)


# ── Frame: header, footer ─────────────────────────────────

def battery(d, x, y, pct: int):
    """A 16 x 9 battery with a nub, filled to `pct`."""
    d.rectangle((x, y, x + 15, y + 8), outline=WHITE)
    d.rectangle((x + 16, y + 3, x + 17, y + 5), fill=WHITE)
    fillw = round(12 * max(0, min(100, pct)) / 100)
    if fillw:
        d.rectangle((x + 2, y + 2, x + 1 + fillw, y + 6), fill=WHITE)


def frame(title: str, now: datetime, batt: int, page: int, pages: int):
    img = Image.new("1", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W - 1, HEADER - 1), fill=BLACK)
    hf = font(14)
    d.text((PAD, 4), title, font=hf, fill=WHITE)
    clock = now.strftime("%H:%M")
    cx = W - PAD - text_w(hf, clock)
    d.text((cx, 4), clock, font=hf, fill=WHITE)
    if batt >= 0:
        battery(d, int(cx) - 24, 7, batt)
    # Page dots, so you know where you are in the cycle.
    if pages > 1:
        gap = 11
        x0 = (W - (pages - 1) * gap) / 2
        y = H - FOOTER / 2 - 1
        for i in range(pages):
            x = x0 + i * gap
            if i == page:
                d.ellipse((x - 3, y - 3, x + 3, y + 3), fill=BLACK)
            else:
                d.ellipse((x - 2, y - 2, x + 2, y + 2), outline=BLACK)
    return img, d


def message(d, big: str, small: str = "", top: int = BODY_TOP, bottom: int = BODY_BOTTOM):
    """A centred notice in the body: setup needed, nothing on, can't reach..."""
    f, lines = fit(big, W - 2 * PAD, 3, (20, 18, 16, 14))
    sf, slines = fit(small, W - 2 * PAD, 3, (12, 11)) if small else (font(12), [])
    total = len(lines) * line_h(f) + (6 + len(slines) * line_h(sf) if slines else 0)
    y = top + max(0, (bottom - top - total) // 2)
    for ln in lines:
        centre(d, y, ln, f)
        y += line_h(f)
    y += 6
    for ln in slines:
        centre(d, y, ln, sf)
        y += line_h(sf)


def not_ready(d, data: dict, what: str, setting: str,
              top: int = BODY_TOP, bottom: int = BODY_BOTTOM) -> bool:
    """Draws the right notice when `data` isn't usable; True if it did."""
    if not isinstance(data, dict):
        message(d, f"NO {what}", "", top, bottom)
        return True
    if data.get("ok"):
        return False
    if data.get("setup") is False:
        message(d, f"SET UP {what}", f"ADD {setting} TO THE BRIDGE'S .ENV", top, bottom)
    else:
        message(d, f"CAN'T REACH {what}", str(data.get("error") or "").upper(), top, bottom)
    return True


# ── Views ─────────────────────────────────────────────────

def age_text(mins: int) -> str:
    if mins < 0:
        return ""
    if mins < 1:
        return "JUST NOW"
    if mins < 60:
        return f"{mins} MIN AGO"
    if mins < 48 * 60:
        return f"{mins // 60} HR AGO"
    return f"{mins // 1440} DAYS AGO"


def view_news(d, data: dict, start: int = 0):
    if not_ready(d, data, "NEWS", "NEWS_FEEDS"):
        return
    items = (data.get("items") or [])[start:start + 2]
    if not items:
        message(d, "NO HEADLINES")
        return
    meta_f = font(11)
    block = (BODY_BOTTOM - BODY_TOP) // len(items)
    y = BODY_TOP
    for n, item in enumerate(items):
        meta = " · ".join(x for x in (item.get("source", ""), age_text(item.get("age_min", -1))) if x)
        d.text((PAD, y), meta, font=meta_f, fill=BLACK)
        room = block - line_h(meta_f) - 3
        sizes = (18, 17, 16, 15, 14, 13, 12)
        max_lines = max(1, room // line_h(font(12)))
        f, lines = None, []
        for size in sizes:   # biggest size whose wrapped lines fit the block's height
            f, lines = fit(item.get("title", ""), W - 2 * PAD, max_lines, (size,))
            if len(lines) * line_h(f) <= room and not lines[-1].endswith("..."):
                break
        draw_lines(d, PAD, y + line_h(meta_f) + 2, f, lines)
        y += block
        if n < len(items) - 1:
            d.line((PAD, y - 3, W - PAD, y - 3), fill=BLACK)


def mins_text(mins: list[int]) -> str:
    parts = ["DUE" if m == 0 else str(m) for m in mins]
    return ", ".join(parts) + ("" if parts == ["DUE"] else " MIN")


def view_travel(d, bus: dict, rail: dict):
    y = BODY_TOP
    rail_rows = []
    if isinstance(rail, dict) and rail.get("ok"):
        if rail.get("all_good"):
            rail_rows = [("RAIL", "GOOD SERVICE", 0)]
        else:
            rail_rows = [(l["name"], l["short"], l["level"]) for l in rail.get("lines", [])
                         if l.get("level", 0) > 0][:3]
    rail_h = len(rail_rows) * 17 + (4 if rail_rows else 0)
    bus_bottom = BODY_BOTTOM - rail_h

    if isinstance(bus, dict) and bus.get("ok") and bus.get("rows"):
        rows = bus["rows"][:3]
        row_h = min(40, (bus_bottom - y) // len(rows))
        route_f, dest_f, time_f = font(16), font(11), font(15)
        for r in rows:
            line = r.get("line", "")
            bw = max(36, int(text_w(route_f, line)) + 8)
            d.rectangle((PAD, y + 2, PAD + bw, y + 24), fill=BLACK)
            d.text((PAD + (bw - text_w(route_f, line)) / 2, y + 4), line, font=route_f, fill=WHITE)
            x = PAD + bw + 6
            d.text((x, y + 1), ellipsize(dest_f, r.get("dest", ""), W - PAD - x), font=dest_f, fill=BLACK)
            d.text((x, y + 13), ellipsize(time_f, mins_text(r.get("mins", [])), W - PAD - x),
                   font=time_f, fill=BLACK)
            y += row_h
    elif isinstance(bus, dict) and bus.get("ok"):
        f = font(15)
        centre(d, (BODY_TOP + bus_bottom) // 2 - 10, "NO BUSES DUE", f)
    else:   # the rail rows stay visible even when the bus side needs attention
        not_ready(d, bus, "BUSES", "TFL_STOPS", BODY_TOP, bus_bottom)

    if rail_rows:
        ry = BODY_BOTTOM - rail_h + 4
        d.line((PAD, ry - 3, W - PAD, ry - 3), fill=BLACK)
        f = font(12)
        for name, short, level in rail_rows:
            if level >= 2:   # severe: white on black so it jumps out
                d.rectangle((PAD - 2, ry - 1, W - PAD + 1, ry + 14), fill=BLACK)
                ink = WHITE
            else:
                ink = BLACK
            d.text((PAD, ry), ellipsize(f, name, 100), font=f, fill=ink)
            d.text((W - PAD - text_w(f, short), ry), short, font=f, fill=ink)
            ry += 17


def view_cal(d, data: dict):
    if not_ready(d, data, "CALENDAR", "CAL_ICS_URLS"):
        return
    events = (data.get("events") or [])[:3]
    if not events:
        message(d, "NOTHING ON", "NO EVENTS IN THE NEXT FEW DAYS")
        return
    label_f = font(11)
    block = (BODY_BOTTOM - BODY_TOP) // len(events)
    y = BODY_TOP
    for e in events:
        label = e.get("label", "")
        lw = int(text_w(label_f, label)) + 6
        d.rectangle((PAD, y, PAD + lw, y + 13), fill=BLACK)
        d.text((PAD + 3, y + 1), label, font=label_f, fill=WHITE)
        room = block - 18
        max_lines = max(1, room // line_h(font(13)))
        f, lines = fit(e.get("title", ""), W - 2 * PAD, min(2, max_lines), (17, 16, 15, 14, 13))
        draw_lines(d, PAD, y + 16, f, lines)
        y += block


def deadline_text(epoch: int, now: datetime) -> str:
    if not epoch:
        return ""
    when = datetime.fromtimestamp(epoch, now.tzinfo)
    left = epoch - int(now.timestamp())
    if left <= 0:
        return ""
    if left < 86400:
        h, m = divmod(left // 60, 60)
        return f"IN {h}H {m:02d}M" if h else f"IN {m} MIN"
    return when.strftime("%a %H:%M").upper()


def view_fpl(d, data: dict, now: datetime):
    if not_ready(d, data, "FANTASY PL", "FPL_TEAM_ID"):
        return
    small, mid = font(11), font(14)
    y = BODY_TOP
    team = data.get("team", "")
    if team:
        centre(d, y, ellipsize(small, team, W - 2 * PAD), small)
        y += 14
    gw = data.get("gw") or 0
    label = f"GAMEWEEK {gw}" + (" · LIVE" if data.get("live") else "") if gw else "SEASON NOT STARTED"
    centre(d, y, label, small)
    y += 12
    big = font(40)
    pts = str(data.get("gw_points", 0))
    centre(d, y, pts, big)
    y += line_h(big) - 2
    centre(d, y, "POINTS", small)
    y += 15
    rows = [("TOTAL", f"{data.get('total', 0):,}"),
            ("RANK" if data.get("league") == "OVERALL" else ellipsize(mid, data.get("league", "RANK"), 130),
             f"{data.get('rank', 0):,}")]
    dl = deadline_text(data.get("deadline", 0), now)
    if dl and data.get("next_gw"):
        rows.append((f"GW{data['next_gw']} DEADLINE", dl))
    for k, v in rows:
        if y + line_h(mid) > BODY_BOTTOM:
            break
        f = small if "DEADLINE" in k else mid
        d.text((PAD, y + (3 if f is small else 0)), k, font=small if f is small else f, fill=BLACK)
        d.text((W - PAD - text_w(mid, v), y), v, font=mid, fill=BLACK)
        y += line_h(mid) + 1


# ── Entry points ──────────────────────────────────────────

def parse_views(spec: str) -> list[str]:
    """EINK_VIEWS, e.g. 'news,news:2,travel,cal,fpl'. Unknown names are dropped."""
    out = []
    for v in (spec or "").split(","):
        v = v.strip().lower()
        if v.split(":")[0] in TITLES:
            out.append(v)
    return out or ["news", "travel", "cal", "fpl"]


def render(view: str, data: dict, now: datetime, batt: int = -1, page: int = 0, pages: int = 1):
    """`data` holds the bridge's JSON for the sources this view uses:
    news -> data['news']; travel -> data['bus'], data['rail']; cal -> data['cal'];
    fpl -> data['fpl']."""
    name, _, arg = view.partition(":")
    img, d = frame(TITLES.get(name, name.upper()), now, batt, page, pages)
    if name == "news":
        view_news(d, data.get("news"), int(arg) if arg.isdigit() else 0)
    elif name == "travel":
        view_travel(d, data.get("bus"), data.get("rail"))
    elif name == "cal":
        view_cal(d, data.get("cal"))
    elif name == "fpl":
        view_fpl(d, data.get("fpl"), now)
    else:
        message(d, "UNKNOWN VIEW", view.upper())
    return img


def panel_bytes(img: Image.Image) -> bytes:
    """Mode "1" packs rows MSB-first with 1 = white: exactly the panel's RAM layout."""
    img = img.convert("1") if img.mode != "1" else img
    data = img.tobytes()
    assert len(data) == W * H // 8
    return data
