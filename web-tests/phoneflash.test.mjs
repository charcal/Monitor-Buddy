import { test } from "node:test";
import assert from "node:assert/strict";
import { checkChip, NotAPhoneBuddy, PHONE_CHIP } from "../web/js/phoneflash.js";

test("only an ESP32-S3 is accepted as a Phone Buddy", () => {
  assert.equal(PHONE_CHIP, "ESP32-S3");
  assert.doesNotThrow(() => checkChip("ESP32-S3"));
  assert.throws(() => checkChip("ESP32-C6"), (e) => e instanceof NotAPhoneBuddy && e.chip === "ESP32-C6");
});
