"""Screens for Phone Buddy, the pocket e-ink version (Waveshare ESP32-S3-ePaper-1.54).

The bridge draws each screen as a 200 x 200 one-bit picture, so the device only
has to download it and copy it to the panel. Changing a layout here needs no
reflash. Everything in this module is pure: data in, picture out, so it is
tested without a network or a device.

The look follows Monitor Buddy's pages (web/js/preview.js): its 5x7 pixel font
at whole-number sizes, a small label at the top, big values, secondary text
in grey and page dots along the bottom. E-ink has no grey, so grey is a
checkerboard of the font's pixels.

    render(view, data, now, batt, page, pages, dark) -> PIL image, 200 x 200, mode "1"
    panel_bytes(image)                                -> 5000 bytes for the panel

Panel byte order (matches Waveshare's V2 driver): row by row from the top,
25 bytes a row, most significant bit is the leftmost pixel, 1 = white.
"""
from __future__ import annotations

from datetime import datetime

from PIL import Image, ImageDraw

from pixelfont import GLYPHS

W = H = 200
M = 10                 # side margin
TOP = 8                # the label row
BODY = 32              # where the main content starts
DOTS_Y = H - 9         # page dots
BOTTOM = H - 20        # content stops above the dots
INK, GREY = "ink", "grey"

VIEWS = ("news", "travel", "cal", "fpl")


# ── Drawing ───────────────────────────────────────────────

class Canvas:
    """A 200 x 200 page drawn in "ink" (0 = black on paper). `dark` swaps
    paper and ink at the end, so the drawing code never thinks about it."""

    def __init__(self):
        self.img = Image.new("1", (W, H), 1)
        self.d = ImageDraw.Draw(self.img)

    @staticmethod
    def width(text: str, size: int) -> int:
        return len(text) * 6 * size

    def text(self, x: int, y: int, text: str, size: int, tone: str = INK):
        for i, ch in enumerate(text):
            rows = GLYPHS.get(ch.upper()) or GLYPHS["?"]
            ox = x + i * 6 * size
            for r, row in enumerate(rows):
                for c, bit in enumerate(row):
                    if bit != "#":
                        continue
                    px, py = ox + c * size, y + r * size
                    if tone == GREY:
                        for yy in range(py, py + size):
                            for xx in range(px + (yy + px) % 2, px + size, 2):
                                self.img.putpixel((xx, yy), 0)
                    else:
                        self.d.rectangle((px, py, px + size - 1, py + size - 1), fill=0)

    def right(self, y: int, text: str, size: int, tone: str = INK):
        self.text(W - M - self.width(text, size), y, text, size, tone)

    def centred(self, y: int, text: str, size: int, tone: str = INK):
        self.text((W - self.width(text, size)) // 2, y, text, size, tone)

    def dot(self, cx: int, cy: int, r: int, filled: bool = True):
        box = (cx - r, cy - r, cx + r, cy + r)
        if filled:
            self.d.ellipse(box, fill=0)
        else:
            self.d.ellipse(box, outline=0, width=1)


def fit_chars(text: str, size: int, width: int) -> str:
    """`text` cut to what fits `width` at `size`."""
    return text[: max(0, width // (6 * size))]


def fit_size(text: str, width: int, biggest: int, smallest: int = 2) -> int:
    for s in range(biggest, smallest - 1, -1):
        if Canvas.width(text, s) <= width:
            return s
    return smallest


def wrap(text: str, cols: int, max_lines: int) -> list[str]:
    """Monitor Buddy's drawWrapped: word wrap to `cols`, at most `max_lines`,
    '..' when cut."""
    out, rest = [], str(text)
    while len(out) < max_lines and rest:
        rest = rest.lstrip(" ")
        take = len(rest)
        if len(rest) > cols:
            take = cols
            while take > 0 and rest[take] != " ":
                take -= 1
            if take == 0:
                take = cols
        line = rest[:take]
        if len(out) == max_lines - 1 and take < len(rest):
            line = line.rstrip()[: cols - 2] + ".."
        out.append(line.rstrip())
        rest = rest[take:]
    return out


def fits(text: str, cols: int, max_lines: int) -> bool:
    lines = wrap(text, cols, max_lines)
    return not (lines and lines[-1].endswith("..") and not text.rstrip().endswith(".."))


def label_row(c: Canvas, label: str, now: datetime):
    """The top row: the page's label, and the time it was fetched in grey."""
    clock = now.strftime("%H:%M")
    c.right(TOP, clock, 2, GREY)
    room = W - 2 * M - c.width(clock, 2) - 8
    c.text(M, TOP, fit_chars(label, 2, room), 2)


def battery(c: Canvas, pct: int):
    """A small battery in the bottom-right corner, on the dots' row."""
    x, y = W - M - 17, DOTS_Y - 4
    c.d.rectangle((x, y, x + 14, y + 8), outline=0)
    c.d.rectangle((x + 15, y + 3, x + 16, y + 5), fill=0)
    fill = round(11 * max(0, min(100, pct)) / 100)
    if fill:
        c.d.rectangle((x + 2, y + 2, x + 1 + fill, y + 6), fill=0)


def page_dots(c: Canvas, page: int, pages: int):
    """Monitor Buddy's drawPageDots: a filled dot for this page, rings for the rest."""
    if pages < 2:
        return
    gap = 14
    x0 = W // 2 - (pages - 1) * gap // 2
    for i in range(pages):
        c.dot(x0 + i * gap, DOTS_Y, 3 if i == page else 2, filled=i == page)


def message(c: Canvas, big: str, small: str = "", top: int = BODY, bottom: int = BOTTOM):
    """A centred notice: a big line or three, and a grey explanation."""
    size = 3 if fits(big, 10, 3) else 2
    lines = wrap(big, (W - 2 * M) // (6 * size), 3)
    sub = wrap(small, 15, 3) if small else []
    pitch = 8 * size + 4
    total = len(lines) * pitch + (8 + len(sub) * 20 if sub else 0)
    y = top + max(0, (bottom - top - total) // 2)
    for ln in lines:
        c.centred(y, ln, size)
        y += pitch
    y += 8
    for ln in sub:
        c.centred(y, ln, 2, GREY)
        y += 20


def not_ready(c: Canvas, data, what: str, setting: str, top: int = BODY, bottom: int = BOTTOM) -> bool:
    """Draws the right notice when `data` isn't usable; True if it did."""
    if not isinstance(data, dict):
        message(c, f"NO {what}", "", top, bottom)
        return True
    if data.get("ok"):
        return False
    if data.get("setup") is False:
        message(c, f"SET UP {what}", f"ADD {setting} TO THE BRIDGE", top, bottom)
    else:
        message(c, f"CAN'T REACH {what}", str(data.get("error") or "").upper(), top, bottom)
    return True


# ── Views ─────────────────────────────────────────────────

def news_age(mins: int) -> str:
    """Monitor Buddy's newsAge."""
    if mins < 0:
        return ""
    if mins < 2:
        return "NOW"
    if mins < 60:
        return f"{mins}M AGO"
    if mins < 1440:
        return f"{mins // 60}H AGO"
    return f"{mins // 1440}D AGO"


def view_news(c: Canvas, data, now: datetime, n: int = 0):
    """One headline, big when it's short: Monitor Buddy's News page."""
    items = (data.get("items") or []) if isinstance(data, dict) and data.get("ok") else []
    n = min(n, len(items) - 1) if items else 0
    item = items[n] if items else {}
    label_row(c, item.get("source") or "NEWS", now)
    if not_ready(c, data, "NEWS", "NEWS_FEEDS"):
        return
    if not items:
        message(c, "NO HEADLINES")
        return
    c.text(M, BODY - 4, news_age(item.get("age_min", -1)), 2, GREY)
    pos = f"{n + 1}/{len(items)}"
    c.right(BODY - 4, pos, 2, GREY)
    title = item.get("title", "")
    big = fits(title, 10, 4)
    size = 3 if big else 2
    lines = wrap(title, 10 if big else 15, 4 if big else 6)
    y = BODY + 22
    for ln in lines:
        c.text(M, y, ln, size)
        y += 8 * size + 4


def rail_rows(rail) -> list[tuple[str, str, int]]:
    if not (isinstance(rail, dict) and rail.get("ok")):
        return []
    if rail.get("all_good"):
        return [("RAIL", "GOOD", 0)]
    return [(l["name"], l["short"], l["level"]) for l in rail.get("lines", []) if l.get("level", 0) > 0][:3]


def view_travel(c: Canvas, bus, rail, now: datetime):
    """Monitor Buddy's Next bus page, with any rail problems underneath."""
    label = (bus.get("stop") if isinstance(bus, dict) else "") or "NEXT BUS"
    label_row(c, label, now)
    rows = rail_rows(rail)
    # A row is one line when the name and status fit side by side, else two.
    heights = [20 if c.width(f"{n} {st}", 2) <= W - 2 * M - 16 else 38 for n, st, _ in rows]
    rail_top = BOTTOM - sum(heights) + 2
    bus_bottom = rail_top - 6 if rows else BOTTOM
    if not not_ready(c, bus, "BUSES", "TFL_STOPS", BODY, bus_bottom):
        buses = (bus.get("rows") or [])
        if not buses:
            message(c, "NO BUSES DUE", "", BODY, bus_bottom)
        pitch = 42
        y = BODY + 2
        for r in buses[:3]:
            if y + 34 > bus_bottom:
                break
            line = str(r.get("line", ""))
            c.text(M, y + 2, line, 3 if len(line) <= 3 else 2)
            x = M + 58
            c.text(x, y, fit_chars(str(r.get("dest", "")), 2, W - M - x), 2, GREY)
            tx = x
            for j, m in enumerate((r.get("mins") or [])[:3]):
                t = "DUE" if m <= 0 else (f"{m} MIN" if j == 0 else str(m))
                if tx + c.width(t, 2) > W - M:
                    break
                c.text(tx, y + 18, t, 2)
                tx += c.width(t, 2) + 6
            y += pitch
    if rows:
        y = rail_top
        c.d.line((M, y - 5, W - M, y - 5), fill=0)
        for (name, short, level), h in zip(rows, heights):
            c.dot(M + 4, y + 6, 4, filled=level > 0)
            if level >= 2:   # severe: a square, so it reads differently from delays
                c.d.rectangle((M, y + 2, M + 8, y + 10), fill=0)
            tone = GREY if level == 0 else INK
            c.text(M + 16, y, fit_chars(name, 2, W - 2 * M - 16), 2, tone)
            c.right(y + h - 20, short, 2, tone)   # same line, or the line below
            y += h


def clock_text(epoch: int, tz) -> str:
    return datetime.fromtimestamp(epoch, tz).strftime("%H:%M")


def cal_heading(e: dict, now: datetime) -> str:
    """Monitor Buddy's calHeading: NOW UNTIL 15:00, IN 25 MIN, or the day and time."""
    t = int(now.timestamp())
    if not e.get("all_day") and e.get("start") and e.get("end"):
        if e["start"] <= t < e["end"]:
            return f"NOW UNTIL {clock_text(e['end'], now.tzinfo)}"
        mins = (e["start"] - t + 59) // 60
        if 0 < mins <= 60:
            return f"IN {mins} MIN"
    return e.get("label", "")


def view_cal(c: Canvas, data, now: datetime):
    """Monitor Buddy's Calendar page: the next event big, then two more."""
    events = []
    if isinstance(data, dict) and data.get("ok"):
        t = int(now.timestamp())
        events = [e for e in data.get("events") or [] if not e.get("end") or e["end"] > t][:3]
    label_row(c, cal_heading(events[0], now) if events else "CALENDAR", now)
    if not_ready(c, data, "CALENDAR", "CAL_ICS_URLS"):
        return
    if not events:
        message(c, "NO EVENTS", "COMING UP THIS WEEK")
        return
    y = BODY
    for ln in wrap(events[0].get("title", ""), 10, 2):
        c.text(M, y, ln, 3)
        y += 28
    y = max(y + 6, BODY + 50)
    for e in events[1:]:
        if y + 38 > BOTTOM:
            break
        day = "TMRW" if e.get("day") == "TOMORROW" else e.get("day", "")
        when = day if e.get("all_day") else (e.get("time", "") if day == "TODAY" else f"{day} {e.get('time', '')}")
        c.text(M, y, when.strip(), 2, GREY)
        c.text(M, y + 18, fit_chars(e.get("title", ""), 2, W - 2 * M), 2)
        y += 44


def format_count(n: int) -> str:
    """Monitor Buddy's formatCount: 845K, 1.2M."""
    n = max(0, int(n))
    if n < 100000:
        return str(n)
    if n < 1000000:
        return f"{n // 1000}K"
    if n < 10000000:
        tenths = n // 100000
        return f"{tenths // 10}.{tenths % 10}M"
    return f"{n // 1000000}M"


def fpl_countdown(deadline: int, now: datetime) -> str:
    """Monitor Buddy's fplCountdown: 2D 04H, or 3H 25M."""
    left = deadline - int(now.timestamp())
    d, h, m = left // 86400, left // 3600 % 24, left // 60 % 60
    return f"{d}D {h:02d}H" if d > 0 else f"{h}H {m:02d}M"


def deadline_text(epoch: int, now: datetime) -> str:
    """Kept for anything that wants plain words: IN 1H 30M, or SAT 11:00."""
    if not epoch:
        return ""
    left = epoch - int(now.timestamp())
    if left <= 0:
        return ""
    if left < 86400:
        h, m = divmod(left // 60, 60)
        return f"IN {h}H {m:02d}M" if h else f"IN {m} MIN"
    return datetime.fromtimestamp(epoch, now.tzinfo).strftime("%a %H:%M").upper()


def view_fpl(c: Canvas, data, now: datetime):
    """Monitor Buddy's Fantasy PL page: big gameweek points, or the countdown
    to the next deadline, with rank and total underneath."""
    f = data if isinstance(data, dict) else {}
    t = int(now.timestamp())
    countdown = f.get("ok") and not f.get("live") and f.get("next_gw") and (f.get("deadline") or 0) > t
    if countdown:
        label_row(c, f"GW{f['next_gw']} IN", now)   # reads "GW10 IN / 2D 04H"
    elif f.get("ok") and f.get("gw"):
        label_row(c, f"GW{f['gw']} LIVE" if f.get("live") else f"GW{f['gw']}", now)
        if f.get("live"):
            c.dot(M + c.width(f"GW{f['gw']} LIVE", 2) + 8, TOP + 6, 4)
    else:
        label_row(c, "FANTASY PL", now)
    if not_ready(c, data, "FANTASY PL", "FPL_TEAM_ID"):
        return
    if countdown:
        cd = fpl_countdown(f["deadline"], now)
        c.text(M, BODY + 4, cd, fit_size(cd, W - 2 * M, 4))
        if f.get("gw"):
            c.text(M, BODY + 44, f"GW{f['gw']} {f.get('gw_points', 0)} PTS", 2, GREY)
    elif f.get("gw"):
        pts = str(f.get("gw_points", 0))
        ps = fit_size(pts, 120, 7)
        c.text(M, BODY, pts, ps)
        c.text(M + c.width(pts, ps) + 6, BODY + 8 * ps - 16, "PTS", 2, GREY)
    else:
        message(c, "NO GAMEWEEK", "", BODY, BODY + 60)
    y = 106
    rank = format_count(f.get("rank") or 0)
    total = str(f.get("total") or 0)
    rx = W // 2 + 4
    c.text(M, y, "RANK", 2, GREY)
    c.text(M, y + 18, rank, fit_size(rank, rx - M - 6, 3))
    c.text(rx, y, "TOTAL", 2, GREY)
    c.text(rx, y + 18, total, fit_size(total, W - M - rx, 3))
    league = f.get("league") or ""
    name = league if league and league != "OVERALL" else (f.get("team") or "")
    c.text(M, y + 50, fit_chars(name, 2, W - 2 * M), 2, GREY)


# ── Entry points ──────────────────────────────────────────

def parse_views(spec: str) -> list[str]:
    """EINK_VIEWS, e.g. 'news,news:2,travel,cal,fpl'. news:2 is the second
    headline. Unknown names are dropped."""
    out = []
    for v in (spec or "").split(","):
        v = v.strip().lower()
        if v.split(":")[0] in VIEWS:
            out.append(v)
    return out or ["news", "news:2", "travel", "cal", "fpl"]


def render(view: str, data: dict, now: datetime, batt: int = -1, page: int = 0, pages: int = 1,
           dark: bool = False):
    """`data` holds the bridge's JSON for the sources this view uses:
    news -> data['news']; travel -> data['bus'], data['rail']; cal -> data['cal'];
    fpl -> data['fpl']."""
    name, _, arg = view.partition(":")
    c = Canvas()
    if name == "news":
        view_news(c, data.get("news"), now, max(0, int(arg) - 1) if arg.isdigit() else 0)
    elif name == "travel":
        view_travel(c, data.get("bus"), data.get("rail"), now)
    elif name == "cal":
        view_cal(c, data.get("cal"), now)
    elif name == "fpl":
        view_fpl(c, data.get("fpl"), now)
    else:
        label_row(c, "PHONE BUDDY", now)
        message(c, "UNKNOWN VIEW", view.upper())
    page_dots(c, page, pages)
    if batt >= 0:
        battery(c, batt)
    img = c.img
    if dark:
        from PIL import ImageChops
        img = ImageChops.invert(img.convert("L")).convert("1")
    return img


def panel_bytes(img: Image.Image) -> bytes:
    """Mode "1" packs rows MSB-first with 1 = white: exactly the panel's RAM layout."""
    img = img.convert("1") if img.mode != "1" else img
    data = img.tobytes()
    assert len(data) == W * H // 8
    return data
