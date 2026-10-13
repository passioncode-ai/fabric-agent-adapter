// DEC-0065 in the Node service kit (FAA-33); the twin of test_fabric_service_usage_attribution.py.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';

const V = JSON.parse(fs.readFileSync(new URL('./fixtures/contract/usage-attribution-vectors.json', import.meta.url), 'utf8'));
const NOW = Date.UTC(2026, 9, 13, 12);
const receipt = (extra = {}) => k.makeUsageReceipt('openrouter', 'example-model', { inputTokens: 10, outputTokens: 5, at: '2026-10-13T09:00:00Z', ...extra });

test('attribution and FAC-SEM-025 answer as the contract does', () => {
  assert.equal(V.attribution.length, 34);
  for (const c of V.attribution) assert.deepEqual(k.attributionHeaders(c.setting, c.request), c.expect, c.name);
  assert.equal(V.usage.length, 21);
  for (const c of V.usage) assert.deepEqual(k.usageFindings(c.report).map((f) => [f.code, f.instancePath]), c.findings.map((f) => [f.code, f.instancePath]), c.name);
});

test('the report writes byProject in normal form and passes FAC-SEM-025', () => {
  const receipts = [receipt({ costUsd: 0.5, projectId: 'urn:project:a', taskRunId: 'run-1' }), receipt({ costUsd: 0.25, projectId: 'URN:PROJECT:a', taskRunId: 'run-1' }),
    receipt({ projectId: 'urn:project:a', taskRunId: 'run-2' }), receipt({ costUsd: 1, projectId: 'urn:project:b' }), receipt({ costUsd: 2 })];
  const report = k.usageReport(receipts, { id: 'example-agent', now: NOW });
  assert.deepEqual(report.byProject.map((p) => p.projectId), ['urn:project:a', 'urn:project:b']);
  const a = report.byProject[0];
  assert.deepEqual([a.calls, a.unpricedCalls, a.costUsd], [3, 1, 0.75]);
  assert.deepEqual(a.taskRuns.map((r) => [r.taskRunId, r.calls, r.costUsd]), [['run-1', 2, 0.75], ['run-2', 1, null]]);
  assert.deepEqual(k.usageFindings(report), []);
  assert.equal('byProject' in k.usageReport([receipt({ costUsd: 1 })], { id: 'example-agent', now: NOW }), false);
  for (const bad of [{ projectId: 'no uri' }, { taskRunId: 'run-1' }, { projectId: 'urn:project:a', taskRunId: '-bad' }]) assert.throws(() => receipt(bad));
});
