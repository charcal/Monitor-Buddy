// The Phone Buddy flasher page (phone.html): pick a release from
// firmware/phone.json (mirrored by casaos/sync), connect over Web Serial,
// install. Phone Buddy is set up from a phone afterwards, so no settings here.
import { fetchImage, DownloadError, ImageMismatch } from "./flasher.js";
import { parseManifest, offered } from "./releases.js";
import { flashPhone, NotAPhoneBuddy } from "./phoneflash.js";

const ESPRESSIF_VID = 0x303a;
const $ = (id) => document.getElementById(id);
const status = (text, tone = "") => { $("status").textContent = text; $("status").className = tone; };
const log = (text) => { const el = $("log"); el.textContent += `${text}\n`; el.scrollTop = el.scrollHeight; };
const STAGES = { connect: "Connecting to the Buddy…", erase: "Erasing the board (about 20 seconds)…",
  write: "Installing…", reset: "Restarting the Buddy…" };

let releases = [];

function chosen() {
  return releases.find((e) => e.version === $("version").value) ?? null;
}

function showNotes() {
  const e = chosen();
  $("notes").hidden = !e?.notes;
  if (e?.notes) $("notes").href = e.notes;
}

async function load() {
  if (!("serial" in navigator)) {
    $("unsupported").hidden = false;
    $("install").hidden = true;
    return;
  }
  try {
    const r = await fetch("firmware/phone.json", { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const beta = new URLSearchParams(location.search).has("beta");
    releases = offered(parseManifest(await r.json()), beta);
  } catch (e) {
    log(`firmware/phone.json: ${e.message}`);
    releases = [];
  }
  if (!releases.length) {
    status("No Phone Buddy firmware is published yet. Publish a release on GitHub, then wait for the sync (or restart it).", "bad");
    return;
  }
  for (const [i, e] of releases.entries()) {
    const label = `${e.version}${e.prerelease ? " (test)" : ""}${i === 0 ? " — newest" : ""}${e.date ? `, ${e.date}` : ""}`;
    $("version").append(new Option(label, e.version));
  }
  showNotes();
  $("go").disabled = false;
}

async function install() {
  const entry = chosen();
  if (!entry) return;
  let port;
  try {
    port = await navigator.serial.requestPort({ filters: [{ usbVendorId: ESPRESSIF_VID }] });
  } catch {
    return;   // no port picked
  }
  $("go").disabled = true;
  $("log").textContent = "";
  const bar = $("bar");
  bar.hidden = false;
  bar.value = 0;
  try {
    status("Downloading the firmware…");
    const image = await fetchImage(entry, new URL(".", location.href));
    log(`Firmware ${entry.version}: ${image.length} bytes, checked`);
    await flashPhone(port, image, {
      erase: $("erase").checked,
      log,
      onStage: (s) => {
        status(STAGES[s] ?? s);
        if (s === "erase") bar.removeAttribute("value");
        if (s === "write") bar.value = 0;
      },
      onProgress: (x) => { bar.value = Math.round(x * 100); status(`Installing… ${Math.round(x * 100)}%`); },
    });
    bar.value = 100;
    status($("erase").checked
      ? "Done. The Buddy restarts and shows SETUP: join the Phone-Buddy Wi-Fi from your phone to set it up."
      : "Done. The Buddy restarts with its settings kept and fetches a screen.", "ok");
  } catch (e) {
    bar.hidden = true;
    const cause = e?.cause ?? e;
    log(`${e?.name}: ${e?.message}`);
    if (cause instanceof NotAPhoneBuddy) {
      status(`That board is an ${cause.chip}, not a Phone Buddy. Nothing was changed. A Monitor Buddy (ESP32-C6) is flashed from the main flasher.`, "bad");
    } else if (e instanceof DownloadError || e instanceof ImageMismatch) {
      status(`Couldn't get the firmware: ${e.message}. Nothing was written.`, "bad");
    } else if (e?.stage === "connect") {
      status("Couldn't connect to the Buddy. Try the steps below: another cable, or hold BOOT while plugging in.", "bad");
    } else {
      status(`Installing stopped while ${e?.stage ?? "working"}: ${cause?.message ?? cause}. Try again; if the Buddy won't start, tick "Erase the board first".`, "bad");
    }
  } finally {
    $("go").disabled = false;
  }
}

$("version").addEventListener("change", showNotes);
$("go").addEventListener("click", install);
load();
