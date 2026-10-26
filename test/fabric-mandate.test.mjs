// fabric-mandate.mjs: the operator's mandate, mandate/1 (DEC-0125, FAC-SEM-144), the twin of test_fabric_mandate.py.
// Every case of the contract's mandate vectors and its mandate.schema.json fixtures (vendored, re-answered by the
// contract's functions), and the kit's own inputs answered by the same functions, are read here as the contract reads
// them.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import {
  MANDATE_INVALID, MANDATE_LIFETIME_SECONDS, OUTSIDE_MANDATE, effectClosure, effectiveScope, handOn, mandateCovers, mandateProblem, mandateRules,
  mandateShape, operatorMandate, scopeWithin,
} from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-mandate.mjs';
import { actionDecision } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-actions.mjs';
import { ServiceError } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-base.mjs';
import { effectClosure as delegationClosure } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-delegation.mjs';

const read = (name) => JSON.parse(fs.readFileSync(new URL(name, import.meta.url), 'utf8'));
const V = read('./fixtures/contract/mandate-vectors.json');
const EXTRA = read('./fixtures/contract/mandate-extra-vectors.json');
const POSITIVE = V.fixtures.find((f) => f.valid).document;
const SCOPE = { capabilities: ['research.run'], effects: ['charge', 'draft'], projects: ['example-site'] };
// Documents whose `at` the contract's ajv-formats date-time admits and the kit's shape refuses, as decisionShape does
// (0.50.0 brief D5, this brief D26): both readings answer mandate-malformed, so only mandateShape's answer differs.
const STRICT_TIME_APART = new Set(['at with an offset without a colon', 'at with a space for T']);

test('every contract case', () => {
  assert.equal(V.cases.length, 37);
  for (const c of V.cases) assert.deepEqual(mandateCovers(c.input), c.expected, c.name);
});

test('every catalogue fixture', () => {
  assert.equal(V.fixtures.length, 3);
  for (const f of V.fixtures) {
    assert.equal(mandateShape(f.document), f.valid, f.name);
    assert.equal(mandateProblem(f.document) ?? null, f.problem, f.name);
    assert.deepEqual(mandateRules('mandate', f.document), f.findings, f.name);
  }
});

test('the lifetime and the codes', () => {
  assert.equal(MANDATE_LIFETIME_SECONDS, V.lifetimeSeconds);
  assert.deepEqual([OUTSIDE_MANDATE, MANDATE_INVALID], ['operator-decision-required', 'decision-invalid']);
  assert.equal(mandateRules('decision', POSITIVE), undefined);
});

test('every kit cover', () => {
  assert.equal(EXTRA.covers.length, 106);
  for (const c of EXTRA.covers) assert.deepEqual(mandateCovers(c.input), c.expected, c.name);
});

test('every kit document', () => {
  assert.deepEqual(new Set(EXTRA.documents.filter((c) => mandateShape(c.mandate) !== c.valid).map((c) => c.name)), STRICT_TIME_APART);
  for (const c of EXTRA.documents) {
    assert.equal(mandateShape(c.mandate), c.valid && !STRICT_TIME_APART.has(c.name), c.name);
    assert.equal(mandateProblem(c.mandate) ?? null, c.problem, c.name);
    assert.deepEqual(mandateRules('mandate', c.mandate), c.findings, c.name);
  }
});

test('every scope pair and the scope in force', () => {
  for (const c of EXTRA.scopes) assert.equal(scopeWithin(c.child, c.parent), c.within, c.name);
  assert.ok(EXTRA.effective.length > 50);
  for (const c of EXTRA.effective) assert.deepEqual(effectiveScope(c.mandate), c.scope, c.name);
});

test('every hand-over', () => {
  for (const c of EXTRA.handOns) {
    if ('throws' in c) {
      assert.throws(() => handOn(c.mandate, c.callee, c.at, c.narrower), (error) => error instanceof ServiceError && error.message.endsWith(c.throws), c.name);
    } else {
      assert.deepEqual(handOn(c.mandate, c.callee, c.at, c.narrower), c.expected, c.name);
    }
  }
});

test('every action decision with a mandate', () => {
  assert.equal(EXTRA.decisions.length, 22);
  for (const c of EXTRA.decisions) assert.deepEqual(actionDecision(c.input), c.expected, c.name);
});

test('never throws on what it reads', () => {
  const base = { mandate: POSITIVE, tier: 'T0', now: '2026-10-26T12:00:00Z', self: 'example-researcher' };
  for (const value of [null, [], 'x', 7, { call: null }, { call: [] }, { call: 'x' }, base,
    { ...base, call: { capability: { x: 1 }, effect: [1], action: {}, project: [], spendUsd: { a: 1 } } }]) {
    assert.equal(typeof mandateCovers(value), 'object');
  }
  for (const value of [null, [], 'x', { kind: 'mandate/1', scope: { effects: [{}] } }, { chain: [{ agent: [] }] }]) {
    assert.equal(mandateProblem(value), 'mandate-malformed');
  }
  // The reference reads call.capability of an absent call and throws; the kit reads it as an empty call.
  assert.deepEqual(mandateCovers(base), { ok: false, code: 'operator-decision-required', data: { detail: 'outside-mandate: capability' } });
  const before = JSON.stringify(POSITIVE);
  handOn(POSITIVE, 'example-writer', '2026-10-26T10:06:00Z', { capabilities: ['research.run'], effects: ['draft'], projects: ['example-site'] });
  effectiveScope(POSITIVE);
  assert.equal(JSON.stringify(POSITIVE), before);
});

test('operatorMandate states the operator\'s words', () => {
  const mandate = operatorMandate({ task: 'FAA-131', instruction: 'adopt the mandate in both kits', scope: SCOPE, lead: 'example-developer', at: '2026-10-26T10:00:00Z' });
  assert.equal(mandateProblem(mandate), undefined);
  assert.deepEqual(mandate.chain, [{ agent: 'example-developer', at: '2026-10-26T10:00:00Z' }]);
  assert.equal(mandate.expiresAt, '2026-10-27T10:00:00.000Z');
  const clocked = operatorMandate({ task: 't', instruction: 'do it', scope: SCOPE, lead: 'example-developer', clock: () => 1793000000000 });
  assert.equal(clocked.at, '2026-10-26T07:33:20.000Z');
  for (const extra of [{ instruction: '' }, { instruction: 'x'.repeat(501) }, { lead: 'Example' }, { scope: { effects: [] } },
    { expiresAt: '2026-11-03T10:00:01Z' }, { at: '2026-10-26 10:00:00Z' }]) {
    assert.throws(() => operatorMandate({ task: 't', instruction: 'do it', scope: SCOPE, lead: 'example-developer', at: '2026-10-26T10:00:00Z', ...extra }), ServiceError, JSON.stringify(extra));
  }
});

test('a lead hands on narrowed and the callee takes it', () => {
  const mandate = operatorMandate({ task: 't', instruction: 'run the research', scope: SCOPE, lead: 'example-developer', at: '2026-10-26T10:00:00Z' });
  const handed = handOn(mandate, 'example-researcher', '2026-10-26T10:05:00Z', { capabilities: ['research.run'], effects: ['charge'], projects: ['example-site'], perCallMaxUsd: 20 });
  const answer = mandateCovers({ mandate: handed, tier: 'T0', now: '2026-10-26T12:00:00Z', self: 'example-researcher', callerAgent: 'example-developer', call: { capability: 'research.run', effect: 'charge', spendUsd: 21 } });
  assert.deepEqual(answer.data, { detail: 'outside-mandate: spend', estimateUsd: 21, perCallMaxUsd: 20 });
});

test('effectClosure is defined once', () => {
  assert.deepEqual([...effectClosure(['charge'])].sort(), ['charge', 'draft', 'none']);
  assert.deepEqual([...effectClosure(['none'])], ['none']);
  assert.equal(delegationClosure, effectClosure);
});
