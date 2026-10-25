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
      fileArray: [{ data: image, address: 0 }],
      flashMode: "keep", flashFreq: "keep", flashSize: "keep",
      eraseAll: false, compress: true,
      reportProgress: (_f, written, total) => { if (onProgress) onProgress(total > 0 ? Math.min(1, written / total) : 0); },
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
