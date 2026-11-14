// FAA-334: the kit's gate reads levels and a place's profile by itself (DEC-0162 LV-5, LV-7; DEC-0166 AU-3). The twin
// of test_gate_levels.py for actionGate and the authority helpers (the Node kit has no McpToolServer).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import { actionGate, authorityConfigProblem, authorityDeclaration, authorityGateInputs } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-interop.mjs';
import { refusalFromAction } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-delegation.mjs';
import { AUTHORITY_EXTENSION_KEY, authorityView } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-actions.mjs';

const read = (name) => JSON.parse(fs.readFileSync(new URL(name, import.meta.url), 'utf8'));
const CASES = ['levels-vectors.json', 'standing-vectors.json'].flatMap((file) => read(`./fixtures/contract/${file}`).actions.map((c) => [file, c]));
const NAMES = new Set(['target', 'approval', 'actionDigest', 'humanStepUrl', 'now', 'self', 'effect', 'callerAgent', 'spendUsd', 'project',
  'mandateCapability', 'levels', 'actionLevel', 'context', 'tokenMem', 'tokenProf', 'standing', 'elicited', 'tier', 'caller', 'action']);
const admin = CASES.find(([, c]) => c.name === 'an administrator decides from T0')[1].input;

test('every level and profile case passes through actionGate as actionDecision answers it', () => {
  assert.equal(CASES.length, 113);
  for (const [file, c] of CASES) {
    const { decision, mandate, ...rest } = c.input;
    assert.deepEqual(Object.keys(rest).filter((k) => !NAMES.has(k)), [], `${file}: ${c.name}`);
    const meta = { ...(decision !== undefined ? { decision } : {}), ...(mandate !== undefined ? { mandate } : {}) };
    const gated = actionGate({ tier: null, caller: null, ...rest, meta });
    if (c.expected.ok === true) {
      assert.equal(gated.ok, true, `${file}: ${c.name}`);
      assert.deepEqual(gated.record, c.expected.recordAs, `${file}: ${c.name}`);
    } else {
      assert.equal(gated.ok, false, `${file}: ${c.name}`);
      assert.deepEqual(gated.refusal, refusalFromAction(c.expected), `${file}: ${c.name}`);
      assert.equal(gated.fault, c.expected.fault, `${file}: ${c.name}`);
    }
  }
});

test('the authority configuration is checked, declared without key sets and read into the gate', () => {
  for (const bad of [{}, { levels: {} }, { levels: [admin.levels] }, { actionLevels: { x: 'Owner' } }, { standing: false }, { levels: admin.levels, other: 1 }]) {
    assert.notEqual(authorityConfigProblem(bad), null, JSON.stringify(bad).slice(0, 80));
  }
  const authority = { levels: admin.levels, actionLevels: { 'approve-reply': 'admin' }, standing: true };
  assert.equal(authorityConfigProblem(authority), null);
  const declared = authorityDeclaration(authority);
  assert.deepEqual(declared.levels, Object.entries(admin.levels).map(([org, e]) => ({ org, audience: e.audience })));
  assert.ok(!JSON.stringify(declared).includes('keySet'));
  assert.equal(authorityView({ extensions: { [AUTHORITY_EXTENSION_KEY]: declared } }).valid, true);
  const mem = `sha256:${'1'.repeat(64)}`;
  assert.deepEqual(authorityGateInputs(authority, 'approve-reply', 'org:org-a', { mem }),
    { standing: true, levels: admin.levels, actionLevel: 'admin', context: 'org:org-a', tokenMem: mem });
  assert.deepEqual(authorityGateInputs({ standing: true }, 'a', 7, null), { standing: true });
  assert.deepEqual(authorityGateInputs(null, 'a', 'personal', { mem }), {});
});
