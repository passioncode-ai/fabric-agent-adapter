// The estate ceremonies' headless join (contract DEC-0084; FAA-54) in the Node kit, the twin of
// test_fabric_ceremonies.py, held to the contract's cases as ceremony-vectors.json vendors them.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-ceremonies.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const V = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/ceremony-vectors.json'), 'utf8'));

test('every verify case and join input answers as the contract does', () => {
  for (const c of V.verify) {
    assert.deepEqual(k.verifyEnrollToken(c.token, { record: c.record ?? V.record, genesis: V.genesis, at: new Date(c.at) }), c.answer, c.name);
    assert.equal(k.enrollJoinInput(c.token) ?? null, c.joinInput, c.name);
  }
});

test('every FAC-SEM-113 case answers as the contract does', () => {
  for (const c of V.rules) assert.deepEqual(k.enrollTokenRules(c.kind, c.value), c.expected, c.name);
  assert.equal(k.enrollTokenRules('estate-record', {}), undefined);
});

test('hostile input never throws', () => {
  for (const value of [null, 0, 'x', [], {}, { schema: 'enroll-token/1', statement: [], signature: {} }]) {
    assert.equal(k.verifyEnrollToken(value, { record: V.record, genesis: V.genesis, at: new Date(0) }).ok, false);
    assert.equal(k.enrollJoinInput(value), undefined);
    k.enrollTokenRules('enroll-token', value);
  }
});

test('every redeem case answers as the contract does (FAA-57)', () => {
  for (const c of V.redeem) assert.deepEqual(k.redeemEnrollToken(c.token, c.machineKey, c.proof, new Map(c.ledger)), c.answer, c.name);
  assert.deepEqual(k.redeemEnrollToken(V.verify[0].token, {}, '', []), { ok: false, problem: 'malformed' });
});

test('every pairing case answers as the contract does (FAA-57)', () => {
  const P = V.pairing;
  const runs = {
    commits: (c) => k.pairingCommit(c.side),
    reveals: (c) => k.checkReveal(c.commit, c.reveal, c.expected ?? undefined),
    codes: (c) => k.comparisonCode(c.new, c.trusted),
    checkedCodes: (c) => k.checkedComparisonCode(c.newCommit, c.new, c.trustedCommit, c.trusted),
    fingerprints: (c) => k.estateFingerprint(c.digest),
    rendezvous: (c) => k.rendezvousVerdict(c.openedAt, c.messages, new Date(c.at)),
    join: (c) => k.joinListed(c.record, c.new, c.trusted, c.genesis),
    ownKeys: (c) => k.ownKeysDecision(c.record, c.machine, c.held),
  };
  for (const [group, run] of Object.entries(runs)) {
    assert.ok(P[group].length > 0, group);
    for (const c of P[group]) assert.deepEqual(run(c), c.answer, `${group}: ${c.name}`);
  }
});
