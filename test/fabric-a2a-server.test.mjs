// fabric-a2a-server.mjs (FAA-10), the twin of test_fabric_a2a_server.py: the card from capabilities, the A2A 1.0
// JSON-RPC binding over the interop job store, the event stream and the bounded client. The live interop test against a
// Hermes A2A endpoint is not here (blocked, FAA-10).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { A2ABinding, A2AClient, A2AError, MAX_BODY, agentCard, agentMessage, textOf } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-a2a-server.mjs';
import { agentCardFindings } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-a2a.mjs';
import { JobStore, choiceRequest, resultEnvelope } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-interop.mjs';

const ORIGIN = 'http://127.0.0.1:47000';
const CAPS = [{ name: 'notes.draft', description: 'Drafts a note.', examples: ['Draft a note about Monday.'] }];
const authorize = (headers) => ({ 'key-a': 'caller-a', 'key-b': 'caller-b' })[headers['x-example-key']] ?? null;
const made = [];
test.after(() => { for (const dir of made) fs.rmSync(dir, { recursive: true, force: true }); });

function binding() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'a2a-server-'));
  made.push(dir);
  const jobs = new JobStore(path.join(dir, 'jobs'));
  const b = new A2ABinding(jobs, (start) => {
    if (textOf(start.message).includes('hello')) return agentMessage('hi');
    start.start('notes.draft');
    return null;
  }, { skills: ['notes.draft'], authorize });
  const call = (method, params, key = 'key-a', headers = {}) => b.handle(Buffer.from(JSON.stringify({ jsonrpc: '2.0', id: 7, method, params })), { 'X-Example-Key': key, ...headers });
  const send = (text, extra = {}) => call('SendMessage', { message: { role: 'ROLE_USER', parts: [{ text }], messageId: 'm1', ...extra } });
  return { b, jobs, call, send };
}

test('a card from capabilities passes the reading side; one that takes the descriptor token is never served', () => {
  const card = agentCard({ name: 'Example Agent', description: 'Drafts notes.', version: '0.2.0', url: `${ORIGIN}/a2a/v1`, capabilities: CAPS,
    securitySchemes: { own: { apiKeySecurityScheme: { location: 'header', name: 'X-Example-Key' } } } });
  assert.equal(card.skills[0].id, 'notes.draft');
  assert.deepEqual(agentCardFindings(card, { origin: ORIGIN }), []);
  assert.throws(() => agentCard({ name: 'E', description: 'd', version: '1', url: `${ORIGIN}/a2a/v1`, capabilities: CAPS,
    securitySchemes: { t: { apiKeySecurityScheme: { location: 'header', name: 'X-Fabric-Token' } } }, descriptorHeader: 'X-Fabric-Token' }), A2AError);
  assert.throws(() => agentCard({ name: 'E', description: 'd', version: '1', url: 'http://127.0.0.1:1/a2a', capabilities: [{ name: 'bad id!' }] }), A2AError);
});

test('a reply with no task', () => {
  const { send } = binding();
  const [status, body] = send('hello');
  assert.equal(status, 200);
  assert.deepEqual(body.result.message.parts, [{ text: 'hi' }]);
  assert.ok(body.result.message.contextId.startsWith('ctx-'));
});

test('a task is a job and only its caller reads it', () => {
  const { call, send } = binding();
  const task = send('draft it', { contextId: 'ctx-1' })[1].result.task;
  assert.deepEqual([task.status.state, task.contextId], ['TASK_STATE_WORKING', 'ctx-1']);
  assert.equal(call('GetTask', { id: task.id })[1].result.id, task.id);
  assert.equal(call('GetTask', { id: task.id }, 'key-b')[1].error.code, -32001);
  assert.equal(call('GetTask', { id: `job_${'0'.repeat(24)}` })[1].error.code, -32001);
});

test('input required is answered by text or by inputResponses', () => {
  const { call, send, jobs } = binding();
  const id = send('draft it')[1].result.task.id;
  const ask = () => jobs.requestInput(id, { tone: choiceRequest('Which tone?', 'tone', [['warm', 'Warm'], ['dry', 'Dry']]) });
  ask();
  const task = call('GetTask', { id })[1].result;
  assert.equal(task.status.state, 'TASK_STATE_INPUT_REQUIRED');
  assert.ok(task.status.message.parts[0].text.includes('Which tone?'));
  assert.equal(send('warm', { taskId: id })[1].result.task.status.state, 'TASK_STATE_WORKING');
  ask();
  const message = { role: 'ROLE_USER', messageId: 'm2', taskId: id, parts: [{ data: { inputResponses: { tone: { action: 'accept', content: { tone: 'dry' } } } } }] };
  assert.equal(call('SendMessage', { message })[1].result.task.status.state, 'TASK_STATE_WORKING');
  assert.equal(send('again', { taskId: id })[1].error.code, -32602);
});

test('the result envelope is an artifact; an ended task is not cancelable; cancel and failure', () => {
  const { call, send, jobs } = binding();
  const id = send('draft it')[1].result.task.id;
  jobs.complete(id, resultEnvelope({ outcome: 'succeeded', done: [], proof: [], scope: {}, notVerified: [], output: { note: 'x' }, usage: { inputTokens: 0, outputTokens: 0, wallMs: 1 }, producer: { id: 'example-agent' } }));
  const task = call('GetTask', { id })[1].result;
  assert.equal(task.status.state, 'TASK_STATE_COMPLETED');
  assert.deepEqual(task.artifacts[0].parts[0].data.output, { note: 'x' });
  assert.equal(call('CancelTask', { id })[1].error.code, -32002);
  const other = send('draft it')[1].result.task.id;
  assert.equal(call('CancelTask', { id: other })[1].result.status.state, 'TASK_STATE_CANCELED');
  const third = send('draft it')[1].result.task.id;
  jobs.fail(third, 'upstream', 'the model did not answer');
  const status = call('GetTask', { id: third })[1].result.status;
  assert.equal(status.state, 'TASK_STATE_FAILED');
  assert.deepEqual(status.message.parts[1].data, { code: 'upstream' });
});

test('refusals', () => {
  const { b, call } = binding();
  assert.equal(b.handle(Buffer.from('{'), { 'X-Example-Key': 'key-a' })[1].error.code, -32700);
  assert.equal(call('Nope', {})[1].error.code, -32601);
  assert.equal(call('GetTask', { id: 'x' }, 'key-a', { 'A2A-Version': '0.3' })[1].error.code, -32009);
  assert.equal(call('SendMessage', { message: { parts: [] } })[1].error.code, -32602);
  assert.deepEqual(call('GetTask', { id: 'x' }, 'nobody'), [401, null]);
  assert.deepEqual(b.handle(Buffer.alloc(MAX_BODY + 1, 120), { 'X-Example-Key': 'key-a' }), [413, null]);
});

test('a stream sends the task then each change', async () => {
  const { b, jobs } = binding();
  let last = null;
  const events = b.stream({ message: { role: 'ROLE_USER', parts: [{ text: 'draft it' }], messageId: 'm1' } }, 'caller-a',
    { rid: 3, pollS: 0, deadlineS: 5, sleep: async () => { if (last) jobs.cancel(last); } });
  const first = (await events.next()).value;
  assert.ok(first.startsWith('data: ') && first.endsWith('\n\n'));
  last = JSON.parse(first.slice(6)).result.task.id;
  const update = JSON.parse((await events.next()).value.slice(6)).result.statusUpdate;
  assert.deepEqual([update.status.state, update.final], ['TASK_STATE_CANCELED', true]);
  assert.equal((await events.next()).done, true);
});

const CARD = { name: 'Peer', supportedInterfaces: [{ url: 'https://peer.example/a2a', protocolBinding: 'JSONRPC', protocolVersion: '1.0' }] };
function transport(answers, sent) {
  return async ({ method, url, headers, body }) => {
    sent.push({ method, url, headers, body: body ? JSON.parse(Buffer.from(body).toString('utf8')) : null });
    const [status, text] = answers.shift();
    return { status, headers: {}, body: new TextEncoder().encode(text) };
  };
}

test("the client reaches only the operator's origins", async () => {
  const sent = [];
  await assert.rejects(new A2AClient(['https://peer.example'], { transport: transport([], sent) }).discover('https://other.example'), A2AError);
  assert.throws(() => new A2AClient([]), A2AError);
  const card = { ...CARD, supportedInterfaces: [{ url: 'https://elsewhere.example/a2a', protocolBinding: 'JSONRPC', protocolVersion: '1.0' }] };
  await assert.rejects(new A2AClient(['https://peer.example:443'], { transport: transport([[200, JSON.stringify(card)]], sent) }).discover('https://peer.example'), A2AError);
});

test('discover, call, get and cancel with the key from the environment; a missing key and a refusal', async () => {
  const sent = [];
  const task = { id: 't1', contextId: 'c1', status: { state: 'TASK_STATE_WORKING' } };
  const answers = [[200, JSON.stringify(CARD)], ...[1, 2, 3].map((i) => [200, JSON.stringify({ jsonrpc: '2.0', id: i, result: { task } })]),
    [200, '{"jsonrpc":"2.0","id":4,"error":{"code":-32001,"message":"no"}}']];
  const client = new A2AClient(['https://peer.example'], { credentialEnv: 'EXAMPLE_PEER_KEY', transport: transport(answers, sent) });
  const found = await client.discover('https://peer.example');
  assert.equal(found.url, 'https://peer.example/a2a');
  delete process.env.EXAMPLE_PEER_KEY;
  assert.throws(() => client.headers(), A2AError);
  process.env.EXAMPLE_PEER_KEY = 'k-123';
  try {
    assert.equal((await client.call(found.url, 'draft it')).task.id, 't1');
    await client.get(found.url, 't1');
    await client.cancel(found.url, 't1');
    await assert.rejects(client.get(found.url, 't1'), (e) => e instanceof A2AError && !e.message.includes('k-123'));
  } finally {
    delete process.env.EXAMPLE_PEER_KEY;
  }
  assert.deepEqual(sent.slice(1, 4).map((s) => s.body.method), ['SendMessage', 'GetTask', 'CancelTask']);
  assert.equal(sent[1].headers.Authorization, 'Bearer k-123');
  assert.equal(sent[1].headers['A2A-Version'], '1.0');
  assert.equal(sent[1].body.params.message.role, 'ROLE_USER');
});
