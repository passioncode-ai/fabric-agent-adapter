// DEC-0070 and DEC-0067 in the Node service kit (FAA-35, FAA-37); the twin of test_fabric_service_feed_protocols.py.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';

const V = JSON.parse(fs.readFileSync(new URL('./fixtures/contract/feed-protocols-vectors.json', import.meta.url), 'utf8'));
const paths = (findings) => findings.map((f) => f.instancePath);

test('the register, negotiateRevision and FAC-SEM-099 answer as the contract does', () => {
  assert.deepEqual(Object.fromEntries(k.PROTOCOL_REVISIONS), V.register);
  for (const c of V.negotiation) assert.deepEqual(k.negotiateRevision(c.received, c.accepted), c.expect, c.name);
  assert.deepEqual(k.negotiateRevision('fabric-service/0.1', ['bad', 7]), { fault: 'no-accepted-revisions' });
  for (const c of V.protocolLists) assert.deepEqual(paths(k.protocolsFindings(c.list, Array.isArray(c.list) ? '' : '/protocols')), paths(c.findings), String(c.list).slice(0, 40));
  const base = { id: 'example-agent', instance: 'default', name: 'Example Agent', version: '1.0.0', build: { commit: '0'.repeat(40) }, startedAt: '2026-10-13T08:00:00Z', status: 'ready', surfaces: { events: { path: '/fabric/v1/events' } } };
  assert.equal('protocols' in k.buildWellKnown(base), false);
  assert.deepEqual(k.buildWellKnown({ ...base, protocols: ['fabric-service/0.1'] }).protocols, ['fabric-service/0.1']);
  for (const bad of [['fabric-service/0.2'], ['fabric-service/0.1', 'fabric-service/0.1'], []]) assert.throws(() => k.buildWellKnown({ ...base, protocols: bad }), /protocols/);
});

test('an event\'s data within its bounds and free of credentials', () => {
  for (const f of V.fixtures.filter((x) => x.name.startsWith('service-events-page'))) {
    const problems = f.document.events.filter((e) => 'data' in e).flatMap((e) => k.feedDataProblems(e.data));
    assert.equal(problems.length === 0, f.valid, `${f.name}: ${problems}`);
  }
  for (const c of V.feedPages) assert.deepEqual(paths(k.feedDataFindings(c.page)), paths(c.findings));
  const data = { schema: 'https://example.com/schemas/note.json', value: { notes: 3, inputTokens: 1200 } };
  assert.deepEqual(k.makeEvent(1, '2026-10-13T08:00:00Z', 'job.done', 'info', 'A note was drafted.', { data }).data, data);
  for (const bad of [{ schema: 'https://example.com/s.json', value: { apiKey: 'abc' } }, { schema: 's.json', value: {} }, { value: {} }]) {
    assert.throws(() => k.makeEvent(1, '2026-10-13T08:00:00Z', 'job.done', 'info', 'A note was drafted.', { data: bad }), (e) => !String(e.message).includes('abc'));
  }
});

test('two revisions of one protocol are N and N−1 (a register with three, as the contract states the rule)', () => {
  k.PROTOCOL_REVISIONS.set('example-protocol', ['1', '2', '3']);
  try {
    assert.deepEqual(k.protocolsFindings(['example-protocol/2', 'example-protocol/3'], ''), []);
    assert.deepEqual(paths(k.protocolsFindings(['example-protocol/1', 'example-protocol/3'], '')), ['/1']);
    assert.deepEqual(k.acceptedRevisions('example-protocol'), ['example-protocol/3', 'example-protocol/2']);
  } finally {
    k.PROTOCOL_REVISIONS.delete('example-protocol');
  }
});

test('FAA-122: a value nested too deep names its place, as the Python twin does', () => {
  const cases = [[{ cited: [{ id: 'a1', coverage: 0.8 }] }, 'data.value.cited[0] is an object'], [{ counts: { by: [1, 2] } }, 'data.value.counts.by is a list'],
    [{ note: ['x'.repeat(501)] }, 'data.value.note[0] is a string over 500 characters'], [{ many: Array.from({ length: 33 }, (_, i) => i) }, 'it has 33 entries']];
  for (const [value, said] of cases) {
    const problems = k.feedDataProblems({ schema: 'urn:example:schema:day:1', value });
    assert.equal(problems.length, 1);
    assert.ok(problems[0].includes(said), problems[0]);
  }
  assert.deepEqual(k.feedDataProblems({ schema: 'urn:example:schema:day:1', value: { citedIds: ['a1', 'b2'], citedCoverage: [0.8, 0.4] } }), []);
});
