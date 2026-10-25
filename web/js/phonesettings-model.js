// Pure helpers for the Phone Buddy settings page (phone-settings.html):
// the bridge's /api/eink-settings JSON in, the page's rows out, and back.

export const VIEW_NAMES = {
  news: "Headline 1", "news:2": "Headline 2", "news:3": "Headline 3", weather: "Weather",
  travel: "Travel (buses and rail)", cal: "Calendar", fpl: "Fantasy PL", bins: "Bin day",
};

// TfL line ids offered as tick boxes; any other saved line is listed too.
export const RAIL_LINES = [
  { id: "elizabeth", name: "Elizabeth line", short: "ELIZ" },
  { id: "dlr", name: "DLR", short: "DLR" },
  { id: "southeastern", name: "Southeastern", short: "SE" },
  { id: "jubilee", name: "Jubilee", short: "JUB" },
  { id: "thameslink", name: "Thameslink", short: "TLINK" },
  { id: "northern", name: "Northern", short: "NORTH" },
];

// The chosen screens in their order, then the rest unticked.
export function viewRows(views, available) {
  const on = views.filter((v) => available.includes(v));
  return [...on.map((id) => ({ id, on: true })),
    ...available.filter((v) => !on.includes(v)).map((id) => ({ id, on: false }))];
}

export function move(rows, index, delta) {
  const j = index + delta;
  if (j < 0 || j >= rows.length) return rows;
  const out = rows.slice();
  [out[index], out[j]] = [out[j], out[index]];
  return out;
}

// Rail tick boxes: the known lines (ticked when saved), plus saved unknown ones.
export function railRows(saved) {
  const byId = new Map(saved.map((r) => [r.id, r]));
  const rows = RAIL_LINES.map((l) => ({ id: l.id, name: l.name, on: byId.has(l.id),
    label: byId.get(l.id)?.label || l.short }));
  for (const r of saved) if (!RAIL_LINES.some((l) => l.id === r.id)) rows.push({ id: r.id, name: r.id, on: true, label: r.label });
  return rows;
}

// The POST body. commute: { on, rows: [[from, to], ...] }; empty rows are skipped.
// The label the Buddy shows for a place: its name, upper case, cut to 15.
export function placeLabel(name) {
  return String(name || "").toUpperCase().slice(0, 15).trim();
}

export function body({ views, theme, rail, commute, weather = null }) {
  const windows = commute.on ? commute.rows.filter(([a, b]) => a && b) : [];
  return {
    views: views.filter((v) => v.on).map((v) => v.id),
    theme,
    rail: rail.filter((r) => r.on).map((r) => ({ id: r.id, label: String(r.label || "").trim().toUpperCase() })),
    commute: windows.length ? windows : "off",
    weather: weather && weather.lat && weather.lon
      ? { lat: weather.lat, lon: weather.lon, label: placeLabel(weather.label) } : null,
  };
}
