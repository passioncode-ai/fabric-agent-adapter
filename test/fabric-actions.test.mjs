// fabric-actions.mjs: fabric-actions/0.1 (DEC-0121, FAC-SEM-142), the twin of test_fabric_actions.py. Every case of
// the contract's actions vectors, its action-call and well-known semantic fixtures and its decision and
// service-actions-extension fixtures (vendored, re-answered by the contract's functions), and the kit's own inputs
// answered by the same functions, are read here as the contract reads them.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import {
  ACTIONS_EXTENSION_KEY as KEY, actionCallRules, actionDecision, actionRules, actionsExtension, actionsExtensionRules, actionsView, decisionShape,
} from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-actions.mjs';
import { ServiceError } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-base.mjs';

const read = (name) => JSON.parse(fs.readFileSync(new URL(name, import.meta.url), 'utf8'));
const V = read('./fixtures/contract/actions-vectors.json');
const EXTRA = read('./fixtures/contract/actions-extra-vectors.json');
const INPUTS = read('./fixtures/kit-actions-inputs.json');
const NOW = '2026-10-24T09:30:00Z';
const RELAYED = { id: 'approve-reply', title: 'Approve the reply', tool: 'reviews.approve', gate: 'relayed' };
const NONE = { id: 'retry-job', title: 'Retry', tool: 'jobs.retry', gate: 'none' };
const HUMAN = { id: 'connect-store', title: 'Do it yourself', tool: 'accounts.connect', gate: 'human', humanStep: 'consent' };
const DECISION = { by: 'operator', via: 'relayed-instruction', action: 'approve-reply', instruction: 'approve the reply to the review from Anna', at: NOW };
const paths = (findings) => findings.map((f) => f.instancePath);
const viewOf = (view) => Object.fromEntries(['declared', 'valid', 'actions'].filter((k) => k in view).map((k) => [k, view[k]]));
const call = (extra = {}) => actionDecision({ action: RELAYED, tier: 'T0', caller: 'agent:claude-code', now: NOW, decision: DECISION, ...extra });

test('every case answers as the contract does', () => {
  assert.equal(V.cases.length, 65);
  for (const c of V.cases) assert.deepEqual(actionDecision(c.input), c.expected, c.name);
});

test('every declaration is found where the contract finds it', () => {
  assert.equal(V.declarations.length, 11);
  for (const c of V.declarations) {
    const findings = actionsExtensionRules(c.input);
    assert.deepEqual(paths(findings), c.findings, c.name);
    assert.ok(findings.every((f) => f.code === 'FAC-SEM-142' && f.message), c.name);
  }
});

test('the action-call fixtures', () => {
  assert.equal(V.actionCalls.length, 10);
  for (const c of V.actionCalls) {
    assert.deepEqual(actionDecision(c.inputs), c.expected, c.name);
    const value = { ...c.inputs, answer: c.answer };
    assert.deepEqual(paths(actionRules('action-call', value)), c.findings, c.name);
    assert.deepEqual(paths(actionCallRules(value)), c.findings, c.name);
  }
  assert.equal(actionRules('service-well-known', {}), undefined);
});

test('the well-known fixtures', () => {
  assert.equal(V.wellKnowns.length, 7);
  for (const c of V.wellKnowns) {
    assert.deepEqual(viewOf(actionsView(c.document)), c.view, c.name);
    assert.deepEqual(paths(actionsExtensionRules(c.document)), c.findings, c.name);
  }
});

test('the decision and extension fixtures', () => {
  assert.equal(V.fixtures.length, 14);
  for (const c of V.fixtures) {
    if (c.schema === 'decision.schema.json') assert.equal(decisionShape(c.document), c.valid, c.name);
    else if (c.schema === 'service-actions-extension.schema.json') {
      const view = actionsView({ extensions: { [KEY]: c.document } });
      assert.equal(view.declared, true, c.name);
      assert.equal(view.valid, c.valid, c.name);
      assert.equal(Boolean(view.errors?.length), !c.valid, c.name);
    } else {
      assert.equal(actionsView(c.document).valid, true, c.name);
      assert.deepEqual(actionsExtensionRules(c.document), [], c.name);
    }
  }
});

test('every kit input answers as the contract does', () => {
  assert.equal(EXTRA.decisions.length, INPUTS.decisions.length);
  assert.equal(EXTRA.documents.length, INPUTS.wellKnowns.length);
  assert.equal(EXTRA.shapes.length, INPUTS.decisionShapes.length);
  for (const c of EXTRA.decisions) assert.deepEqual(actionDecision(c.input), c.expected, c.name);
  for (const c of EXTRA.documents) {
    assert.deepEqual(viewOf(actionsView(c.document)), c.view, c.name);
    assert.deepEqual(paths(actionsExtensionRules(c.document)), c.findings, c.name);
  }
  for (const c of EXTRA.shapes) assert.equal(decisionShape(c.document), c.valid, c.name);
});

test('inputs that are not objects are the service\'s fault', () => {
  for (const value of [undefined, null, [], 'x', 7, Number.NaN, true, { action: null }]) assert.deepEqual(actionDecision(value), { fault: 'action-invalid' });
});

test('NaN and Infinity', () => {
  assert.deepEqual(call({ now: Number.NaN }), { fault: 'now-unreadable' });
  assert.deepEqual(call({ decision: { ...DECISION, at: Number.NaN } }), { ok: false, code: 'decision-invalid' });
  assert.deepEqual(call({ decision: { ...DECISION, at: Infinity } }), { ok: false, code: 'decision-invalid' });
  assert.deepEqual(call({ tier: Number.NaN }), { fault: 'digest-missing' });
  assert.deepEqual(call({ action: { ...RELAYED, title: Number.NaN } }), { fault: 'action-invalid' });
  assert.equal(decisionShape({ ...DECISION, instruction: Number.NaN }), false);
});

test('true is not one', () => {
  assert.equal(call({ elicited: 1, decision: null }).code, 'decision-invalid');
  assert.equal(call({ elicited: true, decision: null }).recordAs.via, 'elicitation');
  assert.equal(call({ tier: 'T2', approval: { ok: 1, approver: 'a' }, actionDigest: `sha256:${'0'.repeat(64)}` }).code, 'approval-required');
});

test('huge strings answer quickly', () => {
  const big = 'a'.repeat(5_000_000);
  const started = Date.now();
  assert.deepEqual(call({ action: { ...RELAYED, id: big } }), { fault: 'action-invalid' });
  assert.deepEqual(call({ action: { ...RELAYED, title: big } }), { fault: 'action-invalid' });
  assert.equal(call({ decision: { ...DECISION, instruction: big } }).code, 'decision-invalid');
  assert.equal(call({ decision: { ...DECISION, at: big } }).code, 'decision-invalid');
  assert.deepEqual(call({ now: big }), { fault: 'now-unreadable' });
  assert.deepEqual(call({ tier: 'T2', actionDigest: `sha256:${'a'.repeat(5_000_000)}` }), { fault: 'digest-missing' });
  assert.ok(Date.now() - started < 5000);
});

test('patterns match the whole string', () => {
  for (const [member, value] of [['id', 'approve-reply\n'], ['tool', 'reviews.approve\n'], ['id', '\napprove'], ['tool', 'reviews.approve\r'], ['gate', 'relayed\n']]) {
    assert.deepEqual(call({ action: { ...RELAYED, [member]: value } }), { fault: 'action-invalid' }, `${member} ${JSON.stringify(value)}`);
  }
  assert.equal(call({ decision: { ...DECISION, action: 'approve-reply\n' } }).code, 'decision-invalid');
  assert.deepEqual(call({ tier: 'T2', actionDigest: `sha256:${'a'.repeat(64)}\n` }), { fault: 'digest-missing' });
});

test('lengths count code points', () => {
  const smile = '\u{1F600}';
  assert.equal(decisionShape({ ...DECISION, instruction: smile.repeat(500) }), true);
  assert.equal(decisionShape({ ...DECISION, instruction: smile.repeat(501) }), false);
  assert.equal(call({ action: { ...RELAYED, title: smile.repeat(80) } }).ok, true);
  assert.deepEqual(call({ action: { ...RELAYED, title: smile.repeat(81) } }), { fault: 'action-invalid' });
});

test('prototype member names are ordinary members, and inherited members are not members', () => {
  // A JSON text's "__proto__" is an own member: refused as an extra member, as the contract's validator refuses it.
  assert.deepEqual(call({ action: JSON.parse(`{"__proto__":{},${JSON.stringify(RELAYED).slice(1)}`) }), { fault: 'action-invalid' });
  assert.equal(call({ decision: JSON.parse(`{"__proto__":{"by":"operator"},${JSON.stringify(DECISION).slice(1)}`) }).code, 'decision-invalid');
  assert.equal(call({ decision: { ...DECISION, constructor: 'x' } }).code, 'decision-invalid');
  assert.deepEqual(actionsView(JSON.parse(`{"extensions":{"__proto__":{"${KEY}":{"actions":[]}}}}`)), { declared: false });
  // A member a prototype carries is not the object's own: a decision whose fields are all inherited is refused, and an
  // inherited extension key is not declared. Plain JSON never carries one; the kit reads own members only.
  assert.equal(call({ decision: Object.create(DECISION) }).code, 'decision-invalid');
  assert.deepEqual(call({ action: Object.create(RELAYED) }), { fault: 'action-invalid' });
  assert.deepEqual(actionsView({ extensions: Object.create({ [KEY]: { actions: [RELAYED] } }) }), { declared: false });
  // An object with no prototype is still an object.
  assert.equal(call({ action: Object.assign(Object.create(null), RELAYED), decision: Object.assign(Object.create(null), DECISION) }).ok, true);
  // Absent and undefined are the same, as the validator reads them.
  assert.equal(call({ action: { ...RELAYED, humanStep: undefined } }).ok, true);
});

test('at is read strictly (D5)', () => {
  for (const at of ['2026-10-24 09:30:00Z', '2016-12-31T23:59:60Z']) {
    assert.equal(decisionShape({ ...DECISION, at }), false, at);
    assert.deepEqual(call({ decision: { ...DECISION, at } }), { ok: false, code: 'decision-invalid' }, at);
  }
});

test('an absent decision is not a null one', () => {
  const value = { action: RELAYED, tier: 'T0', caller: 'agent:claude-code', now: NOW };
  assert.deepEqual(actionDecision(value), { ok: false, code: 'operator-decision-required' });
  assert.deepEqual(actionDecision({ ...value, decision: undefined }), { ok: false, code: 'operator-decision-required' });
  assert.deepEqual(actionDecision({ ...value, decision: null }), { ok: false, code: 'decision-invalid' });
});

test('the readers never throw', () => {
  const junk = [undefined, null, [], 'x', 7, Number.NaN, { extensions: null }, { extensions: { [KEY]: null } }, { extensions: { [KEY]: undefined } },
    { extensions: { [KEY]: { actions: [null, 1, 'x', [], { id: Number.NaN }] } } },
    { surfaces: { mcp: { capabilities: [Number.NaN, null] } }, extensions: { [KEY]: { actions: [RELAYED] } } }];
  for (const value of junk) {
    actionsView(value);
    actionsExtensionRules(value);
    actionCallRules(value);
  }
  for (const value of [undefined, null, [], 'x', Number.NaN, {}, { by: 'operator' }]) assert.equal(decisionShape(value), false);
});

test('the answer is a fresh object', () => {
  const answer = call();
  answer.recordAs.by = 'someone';
  assert.equal(call().recordAs.by, 'operator');
});

test('a valid table round-trips through the reader', () => {
  const table = [NONE, RELAYED, HUMAN];
  const capabilities = ['jobs.retry', 'reviews.approve', 'accounts.connect'];
  const entry = actionsExtension(table, { capabilities });
  assert.deepEqual(Object.keys(entry), [KEY]);
  assert.deepEqual(entry[KEY], { actions: table });
  assert.deepEqual(actionsView({ extensions: entry }), { declared: true, valid: true, actions: table });
  assert.deepEqual(actionsExtensionRules({ surfaces: { mcp: { capabilities } }, extensions: entry }), []);
  assert.deepEqual(actionsExtension(table), entry);
});

test('the builder copies its input', () => {
  const table = [{ ...RELAYED }];
  const entry = actionsExtension(table);
  entry[KEY].actions[0].title = 'changed';
  assert.equal(table[0].title, 'Approve the reply');
});

test('a declaration a reader would report is refused', () => {
  const { humanStep, ...noStep } = HUMAN;
  const bad = [
    [[RELAYED], ['jobs.retry']], [[], undefined], [[RELAYED, { ...NONE, id: 'approve-reply' }], undefined],
    [[{ ...HUMAN, humanStep: null }], undefined], [[noStep], undefined], [[{ ...RELAYED, humanStep: 'consent' }], undefined],
    [[{ ...RELAYED, gate: 'page' }], undefined], [['approve-reply'], undefined],
    [Array.from({ length: 129 }, (_, i) => ({ ...RELAYED, id: `a${i}` })), undefined],
  ];
  for (const [table, capabilities] of bad) assert.throws(() => actionsExtension(table, { capabilities }), ServiceError, JSON.stringify(table).slice(0, 60));
  for (const table of [undefined, null, 'x', { actions: [] }, RELAYED]) assert.throws(() => actionsExtension(table), ServiceError);
  assert.throws(() => actionsExtension([RELAYED], { capabilities: 'reviews.approve' }), ServiceError);
  assert.equal(humanStep, 'consent');
});
