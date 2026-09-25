// UI helpers that need no DOM: claim values as text.
import { test } from "node:test";
import assert from "node:assert/strict";
import { claimValue } from "../dist/ui.js";

const claim = (o) => ({ snak_type: "value", object: "", object_label: "", value: "", datatype: "", ...o });
const time = (t, precision, calendar = "http://www.wikidata.org/entity/Q1985727") =>
  claim({ datatype: "time", value: JSON.stringify({ time: t, precision, calendarmodel: calendar }) });

test("claim values read as text, in the source's own terms", () => {
  assert.equal(claimValue(claim({ snak_type: "novalue" })), "no value");
  assert.equal(claimValue(claim({ snak_type: "somevalue" })), "unknown value");
  assert.equal(claimValue(claim({ object: "wd/Q2", object_label: "Earth" })), "Earth");
  assert.equal(claimValue(time("+1905-06-30T00:00:00Z", 11)), "1905-06-30");
  assert.equal(claimValue(time("-0500-00-00T00:00:00Z", 9)), "500 BCE");
  assert.equal(claimValue(time("+1582-10-05T00:00:00Z", 11, "http://www.wikidata.org/entity/Q1985786")), "1582-10-05 (Julian)");
  assert.equal(claimValue(time("+1900-00-00T00:00:00Z", 7)), "1900 (century)");
  assert.equal(claimValue(claim({ datatype: "quantity", value: '{"amount":"+8","unit":"1"}' })), "8");
  assert.equal(claimValue(claim({ datatype: "quantity", value: '{"amount":"+42","unit":"http://www.wikidata.org/entity/Q11573"}' })), "42 Q11573");
  assert.equal(claimValue(claim({ datatype: "monolingualtext", value: '{"language":"la","text":"physica"}' })), "physica (la)");
  assert.equal(claimValue(claim({ datatype: "external-id", value: "sh85101653" })), "sh85101653");
});
