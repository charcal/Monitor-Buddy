import { test } from "node:test";
import assert from "node:assert/strict";
import { viewRows, move, railRows, body, placeLabel } from "../web/js/phonesettings-model.js";

const ALL = ["news", "news:2", "news:3", "travel", "cal", "fpl"];

test("screens: chosen ones first in their order, the rest unticked", () => {
  const rows = viewRows(["travel", "news"], ALL);
  assert.deepEqual(rows.map((r) => [r.id, r.on]),
    [["travel", true], ["news", true], ["news:2", false], ["news:3", false], ["cal", false], ["fpl", false]]);
  assert.deepEqual(move(rows, 1, -1).slice(0, 2).map((r) => r.id), ["news", "travel"]);
  assert.equal(move(rows, 0, -1), rows);   // can't go above the top
});

test("rail: known lines with their saved short names, plus unknown saved lines", () => {
  const rows = railRows([{ id: "elizabeth", label: "ELIZ" }, { id: "mildmay", label: "MILD" }]);
  const eliz = rows.find((r) => r.id === "elizabeth");
  assert.ok(eliz.on && eliz.label === "ELIZ");
  assert.equal(rows.find((r) => r.id === "dlr").on, false);
  assert.ok(rows.some((r) => r.id === "mildmay" && r.on));
});

test("the body the bridge expects", () => {
  const b = body({
    views: viewRows(["travel", "news"], ALL), theme: "dark",
    rail: [{ id: "elizabeth", on: true, label: " eliz " }, { id: "dlr", on: false, label: "DLR" }],
    commute: { on: true, rows: [["07:00", "09:00"], ["", ""]] },
  });
  assert.deepEqual(b, { views: ["travel", "news"], theme: "dark",
    rail: [{ id: "elizabeth", label: "ELIZ" }], commute: [["07:00", "09:00"]], weather: null });
  const off = body({ views: viewRows(["news"], ALL), theme: "light", rail: [], commute: { on: false, rows: [] } });
  assert.equal(off.commute, "off");
});

test("weather place: label from the name, null when unset", () => {
  assert.equal(placeLabel("Shooters Hill"), "SHOOTERS HILL");
  assert.equal(placeLabel("A very long place name indeed"), "A VERY LONG PLA");
  const b = body({ views: viewRows(["weather"], ["weather"]), theme: "light", rail: [], commute: { on: false, rows: [] },
    weather: { lat: "51.4700", lon: "0.0780", label: "Somewhere" } });
  assert.deepEqual(b.weather, { lat: "51.4700", lon: "0.0780", label: "SOMEWHERE" });
});
