// The Phone Buddy settings page: reads and saves the bridge's e-ink settings
// through the flasher's /bridge/ pass-through (casaos/Caddyfile).
import { VIEW_NAMES, viewRows, move, railRows, body, placeLabel } from "./phonesettings-model.js";
import { searchCity } from "./geocode.js";

const API = "bridge/api/";
const $ = (id) => document.getElementById(id);
let views = [];
let rail = [];
let weather = null;   // { lat, lon, label } or null

function drawWeather() {
  $("w-current").textContent = weather
    ? `Set to ${weather.label || "this place"} (${weather.lat}, ${weather.lon}).`
    : "Not set yet: the Weather screen is skipped until you pick a place.";
  $("w-labelrow").hidden = !weather;
  if (weather) $("w-label").value = weather.label;
}

async function findPlace() {
  const box = $("w-results");
  box.replaceChildren();
  const q = $("w-search").value.trim();
  if (!q) return;
  try {
    const found = await searchCity(fetch, q);
    if (!found.length) { box.textContent = "No places found. Try a nearby town."; return; }
    for (const p of found.slice(0, 6)) {
      const b = Object.assign(document.createElement("button"), {
        type: "button", className: "btn btn--secondary", textContent: p.label });
      b.addEventListener("click", () => {
        weather = { lat: p.lat, lon: p.lon, label: placeLabel(p.name) };
        box.replaceChildren();
        drawWeather();
        status("Place picked: click Save to use it.");
      });
      box.append(b);
    }
  } catch (e) {
    box.textContent = `Search failed: ${e.message}`;
  }
}

function status(text, tone = "") { $("status").textContent = text; $("status").className = tone; }

function drawViews() {
  const box = $("views");
  box.replaceChildren();
  views.forEach((v, i) => {
    const row = document.createElement("div");
    row.className = `item${v.on ? "" : " off"}`;
    const label = document.createElement("label");
    const tick = Object.assign(document.createElement("input"), { type: "checkbox", checked: v.on });
    tick.addEventListener("change", () => { views[i].on = tick.checked; drawViews(); });
    label.append(tick, VIEW_NAMES[v.id] ?? v.id);
    const up = Object.assign(document.createElement("button"), { type: "button", className: "btn btn--secondary", textContent: "↑" });
    const down = Object.assign(document.createElement("button"), { type: "button", className: "btn btn--secondary", textContent: "↓" });
    up.setAttribute("aria-label", `Move ${VIEW_NAMES[v.id]} up`);
    down.setAttribute("aria-label", `Move ${VIEW_NAMES[v.id]} down`);
    up.disabled = i === 0;
    down.disabled = i === views.length - 1;
    up.addEventListener("click", () => { views = move(views, i, -1); drawViews(); });
    down.addEventListener("click", () => { views = move(views, i, 1); drawViews(); });
    row.append(label, up, down);
    box.append(row);
  });
}

function drawRail() {
  const box = $("rail");
  box.replaceChildren();
  rail.forEach((r, i) => {
    const row = document.createElement("div");
    row.className = `item${r.on ? "" : " off"}`;
    const label = document.createElement("label");
    const tick = Object.assign(document.createElement("input"), { type: "checkbox", checked: r.on });
    tick.addEventListener("change", () => { rail[i].on = tick.checked; drawRail(); });
    label.append(tick, r.name);
    const short = Object.assign(document.createElement("input"), { type: "text", value: r.label, maxLength: 12 });
    short.setAttribute("aria-label", `Short name for ${r.name}`);
    short.addEventListener("input", () => { rail[i].label = short.value; });
    row.append(label, short);
    box.append(row);
  });
}

function drawCommute(windows) {
  $("commute-on").checked = windows.length > 0;
  const [m = ["", ""], e = ["", ""]] = windows;
  [["m-from", m[0]], ["m-to", m[1]], ["e-from", e[0]], ["e-to", e[1]]].forEach(([id, v]) => { $(id).value = v; });
  syncCommute();
}

function syncCommute() {
  const on = $("commute-on").checked;
  $("times").setAttribute("aria-disabled", String(!on));
  for (const id of ["m-from", "m-to", "e-from", "e-to"]) $(id).disabled = !on;
}

function show(s) {
  views = viewRows(s.views, s.available_views);
  rail = railRows(s.rail);
  drawViews();
  drawRail();
  document.querySelector(`input[name=theme][value=${s.theme}]`).checked = true;
  drawCommute(s.commute);
  weather = s.weather;
  drawWeather();
  $("source").textContent = s.saved
    ? "These settings are saved on the bridge and take priority over its .env file."
    : "Showing the .env file's settings. Saving here keeps them on the bridge instead.";
  $("reset").hidden = !s.saved;
}

async function previews() {
  const box = $("previews");
  box.replaceChildren();
  try {
    const first = await fetch(`${API}eink-preview?v=0&t=${Date.now()}`, { cache: "no-store" });
    const n = Number(first.headers.get("X-Views")) || 1;
    for (let i = 0; i < n; i++) {
      const fig = document.createElement("figure");
      const img = Object.assign(document.createElement("img"), {
        src: `${API}eink-preview?v=${i}&t=${Date.now()}`, alt: `Screen ${i + 1}` });
      fig.append(img, Object.assign(document.createElement("figcaption"), { textContent: `${i + 1}` }));
      box.append(fig);
    }
  } catch (e) {
    box.textContent = `Couldn't load the preview: ${e.message}`;
  }
}

async function call(method, payload) {
  const r = await fetch(`${API}eink-settings`, {
    method, cache: "no-store",
    headers: payload ? { "Content-Type": "application/json" } : {},
    body: payload ? JSON.stringify(payload) : undefined,
  });
  const json = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((json.errors || [json.error || `HTTP ${r.status}`]).join("; "));
  return json;
}

async function load() {
  try {
    show(await call("GET"));
    $("form").hidden = false;
    previews();
  } catch (e) {
    $("nobridge").hidden = false;
    $("nobridge-why").textContent = e.message;
  }
}

$("commute-on").addEventListener("change", syncCommute);
$("w-find").addEventListener("click", findPlace);
$("w-search").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); findPlace(); } });
$("w-label").addEventListener("input", () => { if (weather) weather.label = $("w-label").value; });
$("w-clear").addEventListener("click", () => { weather = null; drawWeather(); status("Place removed: click Save to confirm."); });

$("form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const payload = body({
    views, rail, weather,
    theme: document.querySelector("input[name=theme]:checked")?.value || "light",
    commute: { on: $("commute-on").checked,
      rows: [[$("m-from").value, $("m-to").value], [$("e-from").value, $("e-to").value]] },
  });
  if (!payload.views.length) { status("Tick at least one screen.", "bad"); return; }
  status("Saving…");
  try {
    show(await call("POST", payload));
    status("Saved. Press PWR on the Buddy to see it.", "ok");
    previews();
  } catch (e) {
    status(`Not saved: ${e.message}`, "bad");
  }
});

$("reset").addEventListener("click", async () => {
  if (!confirm("Forget the settings saved here and go back to the bridge's .env file?")) return;
  try {
    show(await call("POST", { reset: true }));
    status("Back to the .env file's settings.", "ok");
    previews();
  } catch (e) {
    status(`Couldn't reset: ${e.message}`, "bad");
  }
});

load();
