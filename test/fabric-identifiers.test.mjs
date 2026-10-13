// DEC-0076 identifier equality in the Node kit (FAA-39); the twin of test_fabric_identifiers.py, held to the contract's
// fixtures/vectors/identifiers.json (fixtures/contract/identifier-vectors.json).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import { normalIdentifier, sameIdentifier } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-identifiers.mjs';

const V = JSON.parse(fs.readFileSync(new URL('./fixtures/contract/identifier-vectors.json', import.meta.url), 'utf8'));

test('normal forms, same and different, and no lax port\'s mistake', () => {
  assert.equal(V.normal.length, 33);
  for (const c of V.normal) assert.equal(normalIdentifier(c.input), c.expected, c.name);
  for (const [a, b] of V.same) assert.equal(sameIdentifier(a, b), true, `${a} ${b}`);
  for (const [a, b] of V.different) assert.equal(sameIdentifier(a, b), false, `${a} ${b}`);
  for (const c of V.laxPorts) { assert.equal(normalIdentifier(c.input), c.expected, c.name); assert.notEqual(normalIdentifier(c.input), c.wrong, c.name); }
});

test('values that are not strings are compared as they are', () => {
  assert.equal(normalIdentifier(7), undefined);
  assert.equal(sameIdentifier(null, null), true);
  assert.equal(sameIdentifier('1', 1), false);
  assert.equal(sameIdentifier({}, {}), false);
});
