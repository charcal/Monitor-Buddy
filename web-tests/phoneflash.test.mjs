import { test } from "node:test";
import assert from "node:assert/strict";
import { checkChip, NotAPhoneBuddy, PHONE_CHIP, partsToWrite, NVS_START, NVS_END } from "../web/js/phoneflash.js";

test("only an ESP32-S3 is accepted as a Phone Buddy", () => {
  assert.equal(PHONE_CHIP, "ESP32-S3");
  assert.doesNotThrow(() => checkChip("ESP32-S3"));
  assert.throws(() => checkChip("ESP32-C6"), (e) => e instanceof NotAPhoneBuddy && e.chip === "ESP32-C6");
});

test("an update leaves the settings (NVS) untouched; an erase writes it all", () => {
  const image = new Uint8Array(0x20000).map((_, i) => i & 0xff);
  const fresh = partsToWrite(image, true);
  assert.equal(fresh.length, 1);
  assert.equal(fresh[0].address, 0);
  assert.equal(fresh[0].data.length, image.length);
  const update = partsToWrite(image, false);
  assert.deepEqual(update.map((p) => p.address), [0, NVS_END]);
  assert.equal(update[0].data.length, NVS_START);
  assert.equal(update[1].data.length, image.length - NVS_END);
  assert.equal(update[1].data[0], image[NVS_END]);
  // Nothing written lands inside the settings range.
  for (const p of update) assert.ok(p.address + p.data.length <= NVS_START || p.address >= NVS_END);
});
