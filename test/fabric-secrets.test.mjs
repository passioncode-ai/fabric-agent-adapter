// The Node twin of the credential detector (DEC-0044): rawValues reads a query in linear time, as the Python twin
// (fabric_secrets.raw_values) and the contract's src/secret-shape.ts do since fcdb7ccb (FAA-245).
import assert from 'node:assert/strict';
import test from 'node:test';
import { rawValues, secretUrl } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-secrets.mjs';

// How much longer work(large) takes than work(small): each size's fastest of three runs, measured in turn, so a
// loaded machine slows both (FAA-209's rule: a ratio of two sizes, never a wall-clock bound).
function growth(work, small, large, runs = 3) {
  const best = { [small]: Infinity, [large]: Infinity };
  for (let r = 0; r < runs; r += 1) {
    for (const size of [small, large]) {
      const started = performance.now();
      work(size);
      best[size] = Math.min(best[size], performance.now() - started);
    }
  }
  return best[large] / Math.max(best[small], 1e-6);
}

test('rawValues keeps every value of a name, in order, with + kept', () => {
  assert.deepEqual([...rawValues('a=1&b=x+y&a=2&a&=v&a=%zz')], [['a', ['1', '2', '', '%zz']], ['b', ['x+y']], ['', ['v']]]);
  assert.equal(secretUrl('https://h.example/?a=b&token=' + 'Zq7Wm4'.repeat(6)), true);
});

test('rawValues reads many pieces of one name in linear time (FAA-245)', () => {
  const queries = { 10000: 'a=b&'.repeat(10000), 40000: 'a=b&'.repeat(40000) };
  assert.equal(rawValues(queries[40000]).get('a').length, 40000);
  // four times the pieces cost about four times as much; copying the list for each piece cost sixteen
  assert.ok(growth((n) => rawValues(queries[n]), 10000, 40000) < 9);
});
