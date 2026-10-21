// FAA-65: the public date API of fabric-time.mjs, on the cases fabric_time.py reads too.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import * as ft from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-time.mjs';

const CASES = JSON.parse(fs.readFileSync(new URL('./fixtures/kit-time-cases.json', import.meta.url), 'utf8'));
const nanNull = (x) => (Number.isNaN(x) ? null : x);

test('parse, UTC dates, days, formatting and windows', () => {
  for (const [text, expected] of CASES.parse) assert.equal(nanNull(ft.parseRfc3339Ms(text)), expected, String(text));
  for (const [text, expected] of CASES.utcDate) assert.equal(nanNull(ft.utcDateMs(text)), expected, String(text));
  for (const [ms, day] of CASES.utcDay) assert.equal(ft.utcDay(ms), day);
  for (const [ms, text] of CASES.format) {
    assert.equal(ft.formatRfc3339(ms), text);
    assert.equal(ft.parseRfc3339Ms(text), ms, 'format and parse round-trip');
  }
  for (const [today, days, window] of CASES.window) assert.deepEqual(ft.dayWindow(today, days), window);
  assert.throws(() => ft.utcDay(Number.NaN), RangeError);
});

test('the clock', () => {
  assert.equal(ft.clockMs(new Date(Date.UTC(2026, 9, 21, 9))), 1792573200000);
  assert.equal(ft.clockMs(1792573200), 1792573200000);
  for (const bad of [true, '1792573200', null, Infinity]) assert.ok(Number.isNaN(ft.clockMs(bad)), String(bad));
  assert.equal(ft.nowMs(() => 1792573200500), 1792573200500);
});
