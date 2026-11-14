// Authority levels (DEC-0162) and a place's standing mandate (DEC-0166) in the Node kit, held to the contract's own
// vectors at the pin (test/fixtures/contract/make_levels_vectors.mjs). The twin of test_fabric_levels.py.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import { levelRules, levelShortOf, orgMembershipSigningInput, verifyOrgMembership } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-levels.mjs';
import { actionDecision } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-actions.mjs';
import { mandateRules } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-mandate.mjs';
import { sha256 } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-crypto.mjs';

const read = (name) => JSON.parse(fs.readFileSync(new URL(name, import.meta.url), 'utf8'));
const LEVELS = read('./fixtures/contract/levels-vectors.json');
const STANDING = read('./fixtures/contract/standing-vectors.json');
const PIN = read('../fabric-contract.lock.json').commit;
const resolved = (c) => [
  typeof c.membership === 'string' ? LEVELS.memberships[c.membership] : c.membership,
  { ...c.trust, now: Date.parse(c.trust.now), ...(c.trust.keySet === 'keySet' ? { keySet: LEVELS.keySet } : {}) },
];

test('the vectors are the pin\'s', () => {
  assert.deepEqual([LEVELS.commit, STANDING.commit], [PIN, PIN]);
  assert.deepEqual([LEVELS.verify.length, LEVELS.actions.length, LEVELS.mandates.length], [6, 64, 23]);
  assert.deepEqual([STANDING.actions.length, STANDING.documents.length], [49, 11]);
});

test('the membership verifier', () => {
  for (const c of LEVELS.verify) assert.deepEqual(verifyOrgMembership(...resolved(c)), c.expected, c.name);
  for (const [name, membership] of Object.entries(LEVELS.memberships)) {
    assert.equal(`sha256:${sha256(orgMembershipSigningInput(membership)).toString('hex')}`, LEVELS.digests[name], name);
  }
});

test('a level decision and a level mandate', () => {
  for (const group of ['actions', 'mandates']) for (const c of LEVELS[group]) assert.deepEqual(actionDecision(c.input), c.expected, `${group}: ${c.name}`);
});

test('a standing mandate and the document rules', () => {
  for (const c of STANDING.actions) assert.deepEqual(actionDecision(c.input), c.expected, c.name);
  for (const c of STANDING.documents) {
    const findings = mandateRules('mandate', c.mandate);
    assert.deepEqual(findings.map((f) => `${f.code} ${f.instancePath}`), c.findings, c.name);
    assert.ok(findings.every((f) => f.message), c.name);
  }
});

test('the edges', () => {
  const owner = structuredClone(LEVELS.actions.find((c) => c.expected.ok === true));
  owner.input.decision.membership.revision += 1;
  const answer = actionDecision(owner.input);
  assert.deepEqual([answer.code, answer.data.detail], ['decision-invalid', 'level-membership: bad-signature']);
  const [membership, trust] = resolved(LEVELS.verify.find((c) => c.membership === 'architect'));
  assert.deepEqual(verifyOrgMembership(membership, { ...trust, levels: false }), { ok: false, problem: 'malformed' });
  const base = LEVELS.actions.find((c) => c.expected.ok === true).input;
  assert.deepEqual(actionDecision({ ...base, levels: [{ org: 'org:org-a' }] }), { fault: 'levels-invalid' });
  assert.deepEqual(actionDecision({ ...base, actionLevel: 'root' }), { fault: 'action-level-invalid' });
  for (const value of [null, 1, 'x', [], { type: 'org-membership/2' }]) {
    assert.equal(verifyOrgMembership(value, { now: 0, org: 'org:a', audience: 'a', keySet: {} }).ok, false);
  }
  assert.equal(levelRules('other', {}), undefined);
  assert.equal(levelShortOf('member', 'operator', true), 'level-insufficient: operator');
});
