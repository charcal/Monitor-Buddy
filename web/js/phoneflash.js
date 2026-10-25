// Flashing Phone Buddy (Waveshare ESP32-S3-ePaper-1.54 V2) with the vendored
// esptool-js. Like flashImage in flasher.js, but for an ESP32-S3 and without
// Monitor Buddy's board check: nothing is erased or written on another chip.
import { ESPLoader, Transport } from "../vendor/esptool-js/bundle.js";
import { FlashError, resetToFirmware } from "./flasher.js";

export const PHONE_CHIP = "ESP32-S3";

// Not a Phone Buddy: another chip than the ESP32-S3 (a Monitor Buddy is an ESP32-C6).
export class NotAPhoneBuddy extends Error {
  constructor(chip) {
    super(`the chip is ${chip}, not ${PHONE_CHIP}`);
    this.name = "NotAPhoneBuddy";
    this.chip = chip;
  }
}

// The Buddy keeps its Wi-Fi networks, bridge address and key in the NVS
// partition (huge_app.csv: 0x9000, 0x5000 long). The release image is one
// merged file from 0x0, so it covers that range with blank padding. An update
// writes everything except it, so the settings survive.
export const NVS_START = 0x9000;
export const NVS_END = 0xe000;

// The pieces to write: the whole image for a fresh install (`erase`), else the
// image in two parts around the settings.
export function partsToWrite(image, erase) {
  if (erase || image.length <= NVS_END) return [{ data: image, address: 0 }];
  return [{ data: image.slice(0, NVS_START), address: 0 },
    { data: image.slice(NVS_END), address: NVS_END }];
}

export function checkChip(chipName) {
  if (chipName !== PHONE_CHIP) throw new NotAPhoneBuddy(chipName);
}

// Writes `image` (a merged firmware image) at address 0. `serialPort` must be
// CLOSED: esptool-js opens it. opts: { erase, onProgress(0..1), onStage(stage), log(text) };
// stages "connect", "erase", "write", "reset". Throws FlashError(stage, cause).
export async function flashPhone(serialPort, image, { erase = false, onProgress, onStage, log } = {}) {
  const say = (text) => { if (log) log(String(text)); };
  let stage = "connect";
  const enter = (name) => { stage = name; if (onStage) onStage(name); };
  let transport = null;
  try {
    enter("connect");
    const terminal = { clean() {}, write: say, writeLine: say };
    transport = new Transport(serialPort);
    const loader = new ESPLoader({ transport, baudrate: 115200, terminal });
    await loader.main("default_reset");
    checkChip(loader.chip.CHIP_NAME);
    if (erase) {
      enter("erase");
      await loader.eraseFlash();
    }
    enter("write");
    await loader.writeFlash({
      fileArray: partsToWrite(image, erase),
      flashMode: "keep", flashFreq: "keep", flashSize: "keep",
      eraseAll: false, compress: true,
      reportProgress: (i, written, total) => {
        // Two parts on an update: the first is small, so weight by size.
        if (!onProgress || total <= 0) return;
        const parts = partsToWrite(image, erase);
        const before = parts.slice(0, i).reduce((n, p) => n + p.data.length, 0);
        const all = parts.reduce((n, p) => n + p.data.length, 0);
        onProgress(Math.min(1, (before + (written / total) * parts[i].data.length) / all));
      },
    });
    enter("reset");
    say("Restarting the Buddy");
    await resetToFirmware(transport.device ?? serialPort);
  } catch (e) {
    if (transport && e instanceof NotAPhoneBuddy) {
      try { await resetToFirmware(transport.device ?? serialPort); } catch { /* the port is gone */ }
    }
    if (transport) { try { await transport.disconnect(); } catch { /* leave it */ } }
    throw new FlashError(stage, e);
  }
  try { await transport.disconnect(); } catch { /* it re-enumerates after the restart */ }
}
