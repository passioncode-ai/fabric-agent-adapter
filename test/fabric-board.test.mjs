// FAA-12b and FAA-40 in the Node kit: fabric-hub.mjs and fabric-board.mjs, the twins of fabric_hub.py and fabric_board.py,
// held to the same contract fixtures (contract f00a768, fixtures/contract/comms-vectors.json and canonical.json) and driven
// against the same fake Fabric hub (test/fake_fabric_hub.py, run as a process).
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import * as fb from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-board.mjs';
import * as fh from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-hub.mjs';
import { tempDir } from './temp-dir.mjs';
import { assertPrivateFile } from './private-file.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const COMMS = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/comms-vectors.json'), 'utf8'));
const CANONICAL = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/canonical.json'), 'utf8'));
const FIXTURES = Object.fromEntries(COMMS.fixtures.map((f) => [f.name, f]));

// --- the fake hub as a process ---------------------------------------------------------------------------------------
// Waits for a condition the code under test reaches on its own schedule; a fixed sleep fails on a slow machine (FAA-114).
async function until(cond, what, ms = 10000) {
  const deadline = Date.now() + ms;
  while (!(await cond())) {
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}`);
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}

async function fakeHub(t, capabilities = ['video.render']) {
  const dir = tempDir('faa12b-');
  const root = path.join(dir, 'fabric');
  const args = [path.join(here, 'fake_fabric_hub.py'), 'serve', '--root', root, ...capabilities.flatMap((c) => ['--capability', c])];
  const child = spawn('python3', args, { stdio: ['pipe', 'pipe', 'inherit'] });
  const line = await new Promise((resolve, reject) => {
    let buf = '';
    child.stdout.on('data', (c) => {
      buf += c;
      if (buf.includes('\n')) resolve(buf.split('\n')[0]);
    });
    child.on('exit', (code) => reject(new Error(`fake hub exited ${code}`)));
  });
  const info = JSON.parse(line);
  t.after(() => {
    child.stdin.end();
    fs.rmSync(dir, { recursive: true, force: true });
  });
  const data = path.join(dir, 'svc');
  fs.mkdirSync(data, { mode: 0o700 });
  const cred = path.join(data, 'board.credential');
  fs.writeFileSync(cred, info.credential, { mode: 0o600 });
  const control = async (cmd) => {
    const res = await fetch(`http://127.0.0.1:${info.port}/_control`, { method: 'POST', body: JSON.stringify(cmd) });
    return res.json();
  };
  return { root, dir, data, cred, project: info.project, credential: info.credential, control };
}

function harness(hub, overrides = {}) {
  const clock = { t: 0 };
  const events = [];
  const handled = [];
  const h = {
    clock, events, handled,
    outcome: { state: 'completed', summary: 'Rendered.', evidence: [fb.artifactRef('fabric://artifact/out.mp4', { content: 'mp4' })] },
    gate: () => null,
    observed: null,
    async advance(seconds) {
      clock.t += seconds;
      await hub.control({ op: 'advance', seconds });
    },
    tools: async () => (await hub.control({ op: 'state' })).calls,
    state: () => hub.control({ op: 'state' }),
    checkpoint() {
      const file = path.join(hub.data, 'board-checkpoint.json');
      return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')).requests : {};
    },
    kinds: () => events.map((e) => e[0]),
  };
  h.responder = (extra = {}) => new fb.Responder({
    hub: new fh.HubClient(hub.root), projectId: hub.project, capabilities: ['video.render'], credentialFile: hub.cred,
    checkpointFile: path.join(hub.data, 'board-checkpoint.json'),
    handler: async (request, ctx) => { handled.push(request); return typeof h.outcome === 'function' ? h.outcome(request, ctx) : h.outcome; },
    admit: (r) => h.gate(r), observe: () => h.observed, emit: (kind, level, text, extra2) => events.push([kind, level, text, extra2]),
    service: 'example-agent', now: () => clock.t, rand: () => 0.5, ...overrides, ...extra,
  });
  return h;
}

// --- the contract's vectors ------------------------------------------------------------------------------------------
test('canonical form and digests equal the contract vectors', () => {
  for (const v of CANONICAL.commsDigest.vectors) {
    assert.equal(fb.commsCanonical(v.args), v.canonical, v.name);
    assert.equal(fb.commsDigest(v.operation, v.args), v.digest, v.name);
  }
  assert.equal(COMMS.digests.length, 9); // DEC-0081 adds comms-reconcile-owner
  for (const v of COMMS.digests) assert.equal(fb.commsDigest(v.operation, v.args), v.digest, v.name);
  for (const r of CANONICAL.commsDigest.refuses) assert.throws(() => fb.commsDigest(r.operation, JSON.parse(r.argsJson)), RangeError, r.name);
});

test('receipts, refusals and directory pages as the catalogue says', () => {
  for (const f of COMMS.fixtures) {
    if (f.schema === 'comms-receipt.schema.json') assert.equal(fb.receiptProblems(f.document).length === 0, f.valid, f.name);
    if (f.schema === 'comms-refusal.schema.json') assert.equal(fb.refusalProblems(f.document).length === 0, f.valid, f.name);
    if (f.schema === 'comms-directory.schema.json') assert.equal(fb.directoryProblems(f.document).length === 0, f.valid, f.name);
  }
  const replace = FIXTURES['comms-receipt-replace-transferred'].document;
  assert.deepEqual(fb.receiptProblems(replace, 'com.responder_replace'), []);
  assert.ok(fb.receiptProblems(replace, 'com.claim').length);
  assert.ok(fb.receiptProblems({ ...replace, transferred: [replace.transferred[0], replace.transferred[0]] }, 'com.responder_replace').some((p) => p.includes('each request once')));
  // DEC-0098: marked, alreadyRead and more answer com.read_ack; noResponder answers a request's com.submit.
  const ack = FIXTURES['comms-receipt-read-ack-thread'].document;
  assert.deepEqual(fb.receiptProblems(ack, 'com.read_ack'), []);
  assert.ok(fb.receiptProblems(ack, 'com.submit').some((p) => p.includes('com.read_ack only')));
  const submit = FIXTURES['comms-receipt-submit-no-responder'].document;
  assert.deepEqual(fb.receiptProblems(submit, 'com.submit'), []);
  assert.ok(fb.receiptProblems(submit, 'com.reply').some((p) => p.includes('com.submit only')));
  assert.deepEqual(fb.receiptProblems({ ...ack, marked: -1 }, 'com.read_ack'), ['/marked is an integer ≥ 0']);
});

test('FAC-SEM-107: findings equal the contract, find_project refuses a page that lists one twice and compares as written (FAA-40)', () => {
  for (const c of COMMS.directoryPages) assert.deepEqual(fb.directoryFindings(c.page), c.findings);
  assert.throws(() => fb.findProject(COMMS.directoryPages[2].page, 'proj-a'), (e) => e.code === 'directory-invalid');
  const page = { protocol: 'fabric-project-comms/0.1', snapshot: { readAt: '2026-10-13T10:00:00Z' }, cursor: null, projects: [
    { id: 'proj-a', name: 'A', capabilities: [{ capability: 'video.render', responder: 'active' }] },
    { id: 'Proj-a', name: 'A again', capabilities: [] }] };
  assert.equal(fb.findProject(page, 'proj-a').name, 'A');
  assert.equal(fb.findProject(page, 'Proj-a').name, 'A again');
  assert.equal(fb.findProject(page, 'PROJ-A'), null);
  assert.equal(fb.findProject(page, 'Proj-a', 'video.render'), null);
  const urn = COMMS.directoryPages[6].page;
  assert.equal(fb.findProject(urn, 'urn:x:A').id, 'urn:x:A');
});

test('evidence: at most 8, hashed here, one artifact never twice (DEC-0076)', () => {
  const many = Array.from({ length: 9 }, (_, i) => fb.artifactRef(`https://example.com/a/${i}`, { content: 'x' }));
  assert.ok(fb.evidenceProblems(many).length);
  assert.deepEqual(fb.evidenceProblems(many.slice(0, 8)), []);
  const same = [fb.artifactRef('HTTPS://Example.com/a/%7Ex', { content: 'x' }), fb.artifactRef('https://example.com/a/~x', { content: 'y' })];
  assert.ok(fb.evidenceProblems(same).some((p) => p.includes('already names')));
  assert.ok(fb.outcomeProblems({ state: 'completed' }, true).length);
  assert.deepEqual(fb.outcomeProblems({ state: 'completed' }, false), []);
});

test('backoff is bounded, grows and never spins', () => {
  for (const r of [0, 0.5, 0.999]) {
    const b = new fh.Backoff({ rand: () => r });
    const waits = Array.from({ length: 20 }, () => b.next());
    assert.ok(waits.every((w) => w >= 1 && w <= 300));
    assert.ok(waits[19] > 200 && waits[0] < 3);
  }
});

// --- the hub client -------------------------------------------------------------------------------------------------
test('hub: locate, the door ask, the credential saved once, join, refusals', async (t) => {
  const hub = await fakeHub(t);
  const loc = fh.locateHub(hub.root);
  assert.match(loc.origin, /^http:\/\/127\.0\.0\.1:\d+$/);
  assert.throws(() => fh.locateHub(hub.root, { alive: () => false }), (e) => e.code === 'not-running' && e.retryable);
  const client = new fh.HubClient(hub.root);
  const asked = await client.requestBoardAccess('example-agent', hub.project.toUpperCase(), ['video.render'], 'answers render requests');
  assert.equal(asked.status, 'pending');
  const target = path.join(hub.dir, 'svc2', 'board.credential');
  await hub.control({ op: 'allow' });
  const allowed = await client.pollAccess(asked.requestId, asked.pollSecret, target);
  assert.equal(allowed.credentialSaved, true);
  assert.ok(!JSON.stringify(allowed).includes(hub.credential));
  assert.equal(fs.readFileSync(target, 'utf8'), hub.credential);
  assertPrivateFile(target);
  const grant = await client.joinBoard(hub.project, hub.cred);
  assert.deepEqual(grant.capabilities, ['video.render']);
  assert.ok(!JSON.stringify(grant).includes(grant.bearer()));
  await hub.control({ op: 'set', values: { grant: false } });
  await assert.rejects(client.joinBoard(hub.project, hub.cred), (e) => e.code === 'not_authorized' && e.data.ask.capabilities[0] === 'board.respond');
  const dead = new fh.HubClient(hub.root, { alive: () => false });
  const before = (await hub.control({ op: 'state' })).bindingsSeen.length;
  await assert.rejects(dead.joinBoard(hub.project, hub.cred), (e) => e.code === 'not-running');
  assert.equal((await hub.control({ op: 'state' })).bindingsSeen.length, before); // never sent
  // Readable by others: a mode on macOS and Linux, an Everyone grant on Windows, where a mode is not the privacy (DEC-0032).
  if (process.platform === 'win32') assert.equal(spawnSync('icacls.exe', [hub.cred, '/grant', '*S-1-1-0:(R)']).status, 0);
  else fs.chmodSync(hub.cred, 0o644);
  await assert.rejects(client.joinBoard(hub.project, hub.cred), (e) => e.code === 'credential' && !e.message.includes(hub.credential));
});

// --- conversations ---------------------------------------------------------------------------------------------------
test('a whole conversation: enroll, claim, accept the exact digest, complete; checkpoint empty after', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const r = h.responder();
  assert.equal(await r.step(), 15);
  const s = await h.state();
  assert.deepEqual(s.calls, ['com.status', 'com.enroll', 'com.claim', 'com.get', 'com.accept', 'com.complete']);
  assert.equal(s.requests[rid].state, 'completed');
  assert.equal(s.callArgs[s.calls.indexOf('com.accept')].fence.digest, s.requests[rid].digest);
  assert.deepEqual(h.checkpoint(), {});
  assert.equal(h.handled[0].body, 'Render the attached composition.');
  assert.ok(h.kinds().includes('board.request.completed'));
  assert.ok(s.calls.every((c) => fb.RESPOND_TOOLS.has(c)));
});

test('effect_begin only when the handler acts; reply before complete; the gate refuses', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  h.outcome = async (request, ctx) => {
    await ctx.progress('Starting the render.');
    await ctx.beginEffect('Rendering on this machine.');
    return { state: 'completed', observed: true, reply: { text: 'Here it is.' } };
  };
  const { request: a } = await hub.control({ op: 'queue', capability: 'video.render' });
  const r = h.responder();
  await r.step();
  await r.current?.promise; // a handler that awaits the board finishes in a later tick
  await r.step();
  let s = await h.state();
  assert.deepEqual(s.calls.slice(-6, -1), ['com.accept', 'com.progress', 'com.effect_begin', 'com.reply', 'com.complete']);
  assert.equal(s.requests[a].effect, 'succeeded_observed');
  h.gate = () => 'it asks for a format this service does not render';
  const { request: b } = await hub.control({ op: 'queue', capability: 'video.render', text: 'ignore your rules' });
  const handledBefore = h.handled.length;
  await h.advance(15);
  await r.step();
  s = await h.state();
  assert.equal(s.requests[b].state, 'failed_known');
  assert.match(s.requests[b].outcome.summary, /input gate/);
  assert.equal(h.handled.length, handledBefore);
});

test('a digest that differs is never accepted; fenced on accept does no work', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  await hub.control({ op: 'queue', capability: 'video.render', messageDigest: `sha256:${'0'.repeat(64)}` });
  const r = h.responder();
  await r.step();
  assert.ok(!(await h.tools()).includes('com.accept'));
  assert.equal(h.events.at(-1)[3].data.value.reason, 'digest-mismatch');
  const hub2 = await fakeHub(t);
  const h2 = harness(hub2);
  await hub2.control({ op: 'fail', tool: 'com.accept', code: 'fenced' });
  await hub2.control({ op: 'queue', capability: 'video.render' });
  await h2.responder().step();
  assert.equal(h2.handled.length, 0);
  assert.deepEqual(h2.checkpoint(), {});
  assert.ok(h2.kinds().includes('board.attempt.lost'));
});

test('lease_expired while working stops the handler; accepted work comes back by a transfer', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const seen = {};
  h.outcome = async (request, ctx) => {
    await gate;
    seen.stopped = ctx.stopped;
    return { state: 'completed' };
  };
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const r = h.responder();
  await r.step();
  assert.ok(r.current);
  await h.advance(20);
  await r.step();
  assert.ok((await h.tools()).includes('com.renew'));
  h.outcome = { state: 'completed' };
  await h.advance(70);
  await r.step();
  release();
  await until(() => seen.stopped === true, 'the handler to see its context stopped');
  const s = await h.state();
  assert.ok(s.calls.includes('com.responder_replace'));
  assert.equal(s.slots['video.render'].generation, 2);
  assert.equal(s.requests[rid].state, 'completed');
  assert.equal(s.calls.filter((c) => c === 'com.complete').length, 1);
  assert.deepEqual(h.checkpoint(), {});
});

test('authority_changed stops claiming; no epoch fails closed; another protocol revision is schema-unsupported', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  const r = h.responder();
  await r.step();
  await hub.control({ op: 'set', values: { revoked: true } });
  await hub.control({ op: 'queue', capability: 'video.render' });
  await h.advance(15);
  await r.step();
  assert.equal(r.state, 'not-authorized');
  assert.ok(h.events.find((e) => e[0] === 'board.access.needed')[3].notify);
  const hub2 = await fakeHub(t);
  const h2 = harness(hub2);
  await hub2.control({ op: 'set', values: { status_epoch: false } });
  const r2 = h2.responder();
  await r2.step();
  assert.deepEqual(await h2.tools(), ['com.status']);
  assert.match(h2.events.find((e) => e[0] === 'board.blocked')[2], /epoch/);
  const hub3 = await fakeHub(t);
  const h3 = harness(hub3);
  await hub3.control({ op: 'set', values: { status_protocol: 'fabric-project-comms/0.2' } });
  await h3.responder().step();
  assert.equal(h3.events.at(-1)[3].data.value.reason, 'schema-unsupported');
});

test('Fabric down: bounded backoff, one event, then recovery', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  await hub.control({ op: 'withdraw' });
  const r = h.responder();
  const waits = [];
  for (let i = 0; i < 4; i += 1) {
    waits.push(await r.step());
    await h.advance(waits.at(-1));
  }
  assert.equal(r.state, 'down');
  assert.deepEqual(waits, [...waits].sort((a, b) => a - b));
  assert.equal(h.kinds().filter((k) => k === 'board.down').length, 1);
  assert.deepEqual(await h.tools(), []);
  await hub.control({ op: 'publish' });
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  await r.step();
  assert.equal((await h.state()).requests[rid].state, 'completed');
});

test('restart: a request answered while the responder was down leaves the checkpoint (DEC-0098, DEC-0102, FAA-100)', async (t) => {
  // The process dies between com.claim and com.accept (in its input gate), the claim returns to the queue and the
  // target's participant reply answers it (queued -> answered, the only way in): it is no longer this responder's.
  const hub = await fakeHub(t);
  const h = harness(hub);
  h.gate = () => new Promise(() => {});
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  h.responder().step(); // never settles: the "dead" process
  for (let i = 0; i < 200 && h.checkpoint()[rid]?.step !== 'claimed'; i += 1) await new Promise((r) => setTimeout(r, 10));
  assert.equal(h.checkpoint()[rid].step, 'claimed');
  await hub.control({ op: 'end-sessions' });
  assert.ok(!('error' in await hub.control({ op: 'requeue', request: rid })));
  assert.ok(!('error' in await hub.control({ op: 'answer', request: rid })));
  h.gate = () => null;
  await h.responder().step();
  const s = await h.state();
  assert.equal(s.requests[rid].state, 'answered');
  assert.deepEqual(h.checkpoint(), {});
  assert.ok(!s.calls.includes('com.reconcile'));
});

test('restart: accepted work transferred and finished; without transferred it stays held; in-progress reconciled', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  h.outcome = () => new Promise(() => {}); // never answers: the process "dies" inside the work
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  await h.responder().step();
  await hub.control({ op: 'end-sessions' });
  h.outcome = { state: 'completed', summary: 'Rendered after the restart.' };
  await h.responder().step();
  let s = await h.state();
  assert.ok(s.calls.includes('com.responder_replace'));
  assert.equal(s.requests[rid].state, 'completed');
  assert.ok(!s.callArgs.some((a, i) => s.calls[i] === 'com.claim' && 'request' in a)); // never a claim read-back

  const hub2 = await fakeHub(t);
  const h2 = harness(hub2);
  h2.outcome = () => new Promise(() => {});
  const { request: held } = await hub2.control({ op: 'queue', capability: 'video.render' });
  await h2.responder().step();
  await hub2.control({ op: 'end-sessions' });
  await hub2.control({ op: 'set', values: { omit_transferred: true } });
  await h2.responder().step();
  s = await h2.state();
  assert.equal(s.requests[held].state, 'accepted');
  assert.equal(h2.checkpoint()[held].step, 'held');
  assert.ok(h2.kinds().includes('board.request.held'));

  const hub3 = await fakeHub(t);
  const h3 = harness(hub3);
  h3.outcome = async (request, ctx) => {
    await ctx.beginEffect('Rendering.');
    return new Promise(() => {});
  };
  const { request: busy } = await hub3.control({ op: 'queue', capability: 'video.render' });
  await h3.responder().step();
  await until(async () => h3.checkpoint()[busy]?.step === 'in-progress'
    && (await hub3.control({ op: 'state' })).requests[busy].state === 'in_progress', 'the effect to begin on both sides');
  await hub3.control({ op: 'end-sessions' });
  h3.observed = { state: 'completed', observed: true, summary: 'The render is on disk; checked its hash.' };
  await h3.responder().step();
  s = await hub3.control({ op: 'state' });
  assert.equal(s.requests[busy].state, 'completed');
  assert.equal(s.requests[busy].effect, 'succeeded_observed');
  assert.ok(s.calls.includes('com.reconcile'));
});

test('a board session never sends a tool outside the respond scope; shutdown releases the slot', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  const r = h.responder();
  await r.step();
  for (const tool of ['com.submit', 'com.cancel', 'com.read_ack', 'com.directory']) await assert.rejects(r.session.call(tool, {}), (e) => e.code === 'not-in-scope');
  await r.shutdown();
  const s = await h.state();
  assert.equal(s.slots['video.render'].holder, null);
  assert.equal(s.sessions, 0);
  assert.ok(!s.calls.some((c) => ['com.submit', 'com.cancel', 'com.read_ack', 'com.directory'].includes(c)));
});

test('the Python and Node kits write a checkpoint each other reads', async () => {
  const dir = tempDir('faa12b-cp-');
  const file = path.join(dir, 'cp.json');
  const cp = new fb.Checkpoint(file);
  cp.put({ request: 'req_000000001', step: 'claimed', keys: {} });
  const py = spawn('python3', ['-c', `import sys; sys.path.insert(0, ${JSON.stringify(path.join(here, '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts'))}); import fabric_board as fb; print(fb.Checkpoint(${JSON.stringify(file)}).entries["req_000000001"]["step"])`]);
  let out = '';
  py.stdout.on('data', (c) => { out += c; });
  await new Promise((resolve) => py.on('exit', resolve));
  assert.equal(out.trim(), 'claimed');
  fs.rmSync(dir, { recursive: true, force: true });
});

test('selfCheck: the fixture conversation check_service.py runs passes on the Node kit', async () => {
  assert.deepEqual(await fb.selfCheck(), []);
});

// --- DEC-0079 and DEC-0081 (FAA-42) ------------------------------------------------------------------------------------
const HOLD = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/comms-hold-vectors.json'), 'utf8'));

test('every hold case answers as the contract does; held is retryable; settledBy and a held directory entry', () => {
  assert.equal(HOLD.cases.length, 114);
  for (const c of HOLD.cases) assert.equal(fb.holdRefuses(c.tool, c.target, c.holds), c.refused, c.name);
  assert.deepEqual(Object.fromEntries(Object.entries(fb.HOLD_SCOPES)), HOLD.scopes);
  assert.deepEqual(HOLD.tools.filter((tool) => !(tool in fb.HOLD_SCOPES)).sort(), [...HOLD.neverHeld].sort());
  for (const bad of [null, 3, 'x', [], { thread: 7 }]) assert.equal(fb.holdRefuses('com.claim', bad, { threads: [7] }), false);
  assert.equal(fb.holdRefuses('com.claim', JSON.parse('{"__proto__": {"thread": "t"}}'), { threads: ['t'] }), false, 'an inherited member is absent');
  assert.deepEqual(fb.refusalProblems({ error: { code: 'held', message: 'Held.', retryable: true } }), []);
  assert.ok(fb.refusalProblems({ error: { code: 'held', message: 'Held.', retryable: false } }).length);
  const receipt = { ok: true, repeated: false, request: { id: 'req-00000001', state: 'completed', effect: 'succeeded_observed', revision: 4, settledBy: 'owner' } };
  assert.deepEqual(fb.receiptProblems(receipt, 'com.reconcile'), []);
  for (const [state, settledBy] of [['in_progress', 'owner'], ['completed', 'responder'], ['completed', null]]) {
    assert.ok(fb.receiptProblems({ ...receipt, request: { ...receipt.request, state, settledBy } }, 'com.reconcile').length, `${state} ${settledBy}`);
  }
  const page = { protocol: 'fabric-project-comms/0.1', snapshot: { readAt: '2026-10-13T10:00:00Z' }, cursor: null,
    projects: [{ id: 'proj-a', name: 'A', capabilities: [{ capability: 'a.b', responder: 'active', held: true }] }] };
  assert.deepEqual(fb.directoryProblems(page), []);
  page.projects[0].capabilities[0].held = 'yes';
  assert.ok(fb.directoryProblems(page).length);
});

test('a held slot waits with a growing pause and resumes when the hold is lifted', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  await hub.control({ op: 'set', values: { holds: { slots: [{ project: hub.project, capability: 'video.render' }] } } });
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const r = h.responder();
  await r.step();
  assert.deepEqual(await h.tools(), ['com.status'], 'a slot com.status names held is not enrolled');
  assert.equal(r.slots['video.render'].state, 'paused');
  await h.advance(10);
  await r.step();
  assert.deepEqual(await h.tools(), ['com.status'], 'nothing is asked before the pause ends');
  await h.advance(6);
  await r.step();
  assert.equal((await h.tools()).at(-1), 'com.enroll');
  assert.equal(r.slots['video.render'].retryAt - h.clock.t, 30, 'the pause doubles');
  assert.equal(h.kinds().filter((k) => k === 'board.slot.held').length, 1);
  await hub.control({ op: 'set', values: { holds: {} } });
  await h.advance(31);
  await r.step();
  assert.equal((await h.state()).requests[rid].state, 'completed');
  assert.ok(h.kinds().includes('board.slot.released'));
  assert.ok(!h.kinds().includes('board.down'));
});

test('a hold between the claim and the accept does nothing; accepted work continues under a hold', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  await hub.control({ op: 'fail', tool: 'com.accept', code: 'held' });
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const r = h.responder();
  await r.step();
  assert.equal(h.handled.length, 0);
  assert.deepEqual(h.checkpoint(), {});
  assert.ok(h.kinds().includes('board.request.waiting'));
  assert.equal(r.slots['video.render'].state, 'paused');
  await h.advance(61);
  await r.step();
  assert.equal((await h.state()).requests[rid].state, 'completed');

  const hub2 = await fakeHub(t);
  const h2 = harness(hub2);
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  h2.outcome = async (request, ctx) => { await gate; return { state: 'completed', summary: String(ctx.stopped) }; };
  const { request: b } = await hub2.control({ op: 'queue', capability: 'video.render' });
  const r2 = h2.responder();
  await r2.step();
  await hub2.control({ op: 'set', values: { holds: { slots: [{ project: hub2.project, capability: 'video.render' }] } } });
  await h2.advance(20);
  await r2.step();
  assert.equal((await h2.tools()).at(-1), 'com.renew', 'com.renew is never held');
  release();
  await r2.current?.promise;
  await h2.advance(1);
  await r2.step();
  const s = await h2.state();
  assert.equal(s.requests[b].state, 'completed');
  assert.equal(s.requests[b].outcome.summary, 'false', 'the work was never told to stop');
});

test('effect_begin waits for the hold with the same key', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const thread = (await h.state()).requests[rid].thread;
  h.outcome = async (request, ctx) => {
    // FAA-43: the board lifts the hold right after the first held begin, never on a timer.
    await hub.control({ op: 'set', values: { holds: { threads: [thread] }, lift_holds_after: 'com.effect_begin' } });
    await ctx.beginEffect('Rendering.');
    return { state: 'completed', observed: true, summary: 'Rendered and checked.' };
  };
  const r = h.responder();
  r.holdDelay = 0.02;
  await r.step();
  await r.current?.promise;
  await r.step();
  const s = await h.state();
  const begins = s.callArgs.filter((a, i) => s.calls[i] === 'com.effect_begin');
  assert.equal(begins.length, 2, 'one begin refused held, then the same begin once the hold is lifted');
  assert.equal(new Set(begins.map((b) => b.fence.idempotency.key)).size, 1, 'the same key each time');
  assert.ok(h.kinds().includes('board.request.waiting'));
  assert.deepEqual([s.requests[rid].state, s.requests[rid].effect], ['completed', 'succeeded_observed']);
});

test('a claim or a replace refused held pauses the slot and the work waits', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  await hub.control({ op: 'fail', tool: 'com.claim', code: 'held' });
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const r = h.responder();
  await r.step();
  assert.equal(r.slots['video.render'].state, 'paused');
  assert.equal(r.state, 'ready');
  await h.advance(16);
  await r.step();
  assert.equal((await h.state()).requests[rid].state, 'completed');

  const hub2 = await fakeHub(t);
  const h2 = harness(hub2);
  let hang;
  h2.outcome = () => new Promise((resolve) => { hang = resolve; });
  const { request: b } = await hub2.control({ op: 'queue', capability: 'video.render' });
  const first = h2.responder();
  await first.step();
  assert.ok(first.current);
  await hub2.control({ op: 'end-sessions' });
  h2.outcome = { state: 'completed', summary: 'Rendered after the restart.' };
  await hub2.control({ op: 'fail', tool: 'com.responder_replace', code: 'held' });
  const second = h2.responder();
  await second.step();
  assert.equal(h2.checkpoint()[b].step, 'lapsed');
  assert.equal(second.slots['video.render'].state, 'paused');
  assert.ok(!h2.kinds().includes('board.down'));
  await h2.advance(16);
  await second.step();
  await second.current?.promise;
  await second.step();
  assert.equal((await h2.state()).requests[b].state, 'completed');
  hang?.({ state: 'completed' });
});

// --- FAA-77: the audit's findings 35 to 39 (2026-10-22), the faults the reviewer reproduced -----------------------------
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function settle(h, r, rounds = 6, seconds = 31) {
  for (let i = 0; i < rounds; i += 1) {
    await sleep(20);
    await h.advance(Math.max(seconds, r.waitUntil - h.clock.t));
    await r.step();
  }
}
function gate() {
  let open;
  const promise = new Promise((resolve) => { open = resolve; });
  return { promise, open };
}

test('FAA-77 35: a reply lost before a transfer is not sent twice, keys are made again, idempotency_conflict is its own event', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  h.outcome = { state: 'completed', summary: 'ok', reply: { text: 'here' } };
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const r = h.responder();
  await hub.control({ op: 'drop', tool: 'com.reply' }); // the reply is stored; its answer is lost
  await r.step();
  await hub.control({ op: 'end-sessions' }); // and the session ends before the same key goes again
  await settle(h, r, 3);
  let s = await h.state();
  assert.equal(s.requests[rid].state, 'completed');
  assert.equal(s.replies.length, 1); // the old key told the reply was stored: never a second one
  assert.ok(!JSON.stringify(h.events).includes('idempotency_conflict'));

  const hub2 = await fakeHub(t);
  const h2 = harness(hub2);
  h2.outcome = h.outcome;
  const { request: rid2 } = await hub2.control({ op: 'queue', capability: 'video.render' });
  const r2 = h2.responder();
  await hub2.control({ op: 'fail', tool: 'com.reply', code: 'not_available' }); // refused before anything is stored
  await r2.step();
  const old = h2.checkpoint()[rid2].keys.reply;
  await hub2.control({ op: 'end-sessions' });
  await settle(h2, r2, 3);
  s = await h2.state();
  assert.equal(s.requests[rid2].state, 'completed');
  const keys = s.callArgs.filter((a, i) => s.calls[i] === 'com.reply').map((a) => a.fence.idempotency.key);
  assert.equal(keys[0], old);
  assert.notEqual(keys.at(-1), old);
  assert.equal(s.replies.length, 1);

  const hub3 = await fakeHub(t);
  const h3 = harness(hub3);
  h3.outcome = h.outcome;
  await hub3.control({ op: 'queue', capability: 'video.render' });
  await hub3.control({ op: 'fail', tool: 'com.reply', code: 'idempotency_conflict' });
  await h3.responder().step();
  const blocked = h3.events.filter((e) => e[0] === 'board.blocked');
  assert.equal(blocked[0]?.[3].data.value.reason, 'idempotency_conflict');
  assert.ok(!h3.kinds().includes('board.down'));
});

test('FAA-77 35: a second lost answer, on the replied-before probe after the transfer, still completes with one reply', async (t) => {
  // The replace just renewed the slot, so the session is kept and recovery does not run again: the transferred entry
  // must already carry the new attempt and wait in the resume queue, and the probe is asked again from there.
  const hub = await fakeHub(t);
  const h = harness(hub);
  h.outcome = { state: 'completed', summary: 'ok', reply: { text: 'here' } };
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const r = h.responder();
  await hub.control({ op: 'drop', tool: 'com.reply' }); // the reply is stored; its answer is lost
  await r.step();
  await hub.control({ op: 'end-sessions' });
  let dropped = false;
  for (let i = 0; i < 12; i += 1) {
    if (!dropped && !r.session) {
      await hub.control({ op: 'drop', tool: 'com.reply' }); // the probe after the replace: stored, answer lost again
      dropped = true;
    }
    await h.advance(Math.max(31, r.waitUntil - h.clock.t));
    await r.step();
  }
  assert.ok(dropped);
  const s = await h.state();
  assert.equal(s.requests[rid].state, 'completed');
  assert.equal(s.replies.length, 1);
  assert.deepEqual(h.checkpoint(), {});
  assert.equal(r.state, 'ready');

  // not_available says nothing about whether the old reply was stored: reading it as "not stored" sent a second reply.
  const hub2 = await fakeHub(t);
  const h2 = harness(hub2);
  h2.outcome = h.outcome;
  const { request: rid2 } = await hub2.control({ op: 'queue', capability: 'video.render' });
  const r2 = h2.responder();
  await hub2.control({ op: 'drop', tool: 'com.reply' });
  await r2.step();
  await hub2.control({ op: 'end-sessions' });
  let refused = false;
  for (let i = 0; i < 12; i += 1) {
    if (!refused && !r2.session) {
      await hub2.control({ op: 'fail', tool: 'com.reply', code: 'not_available' }); // the probe after the replace
      refused = true;
    }
    await h2.advance(Math.max(31, r2.waitUntil - h2.clock.t));
    await r2.step();
  }
  assert.ok(refused);
  const s2 = await h2.state();
  assert.equal(s2.requests[rid2].state, 'completed');
  assert.equal(s2.replies.length, 1);
  assert.deepEqual(h2.checkpoint(), {});
});

test('FAA-77 36: renew never races effect_begin; a revision_conflict on renew or progress reads again and keeps the attempt', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  const release = gate();
  h.outcome = async (request, ctx) => {
    await ctx.beginEffect('x');
    await release.promise;
    return { state: 'completed', observed: true, summary: 'done' };
  };
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  let r;
  let raced = null;
  r = h.responder({
    sessionFactory: (grant) => {
      const s = new fb.BoardSession(grant);
      const real = s.call.bind(s);
      s.call = async (tool, args) => {
        const out = await real(tool, args);
        if (tool === 'com.effect_begin' && !raced) {
          await h.advance(20); // the tick renews while this receipt is not applied yet
          raced = r.renew(r.current).then(() => 'renewed', (e) => e.code);
          await sleep(30);
        }
        return out;
      };
      return s;
    },
  });
  await r.step();
  for (let i = 0; i < 50 && !raced; i += 1) await sleep(10);
  assert.equal(await raced, 'renewed');
  assert.ok(!h.kinds().includes('board.reconcile.needed'));
  release.open();
  await settle(h, r, 2, 5);
  let s = await h.state();
  assert.equal(s.requests[rid].state, 'completed');
  assert.equal(s.requests[rid].effect, 'succeeded_observed');

  const hub2 = await fakeHub(t);
  const h2 = harness(hub2);
  const release2 = gate();
  h2.outcome = async (request, ctx) => {
    await ctx.beginEffect('x');
    await release2.promise;
    await ctx.progress('almost');
    return { state: 'completed', observed: true, summary: 'done' };
  };
  const { request: rid2 } = await hub2.control({ op: 'queue', capability: 'video.render' });
  const r2 = h2.responder();
  await r2.step();
  await hub2.control({ op: 'fail', tool: 'com.renew', code: 'revision_conflict' });
  await h2.advance(20);
  await r2.step();
  assert.ok(r2.current);
  assert.deepEqual((await h2.tools()).slice(-3), ['com.renew', 'com.get', 'com.renew']);
  await hub2.control({ op: 'fail', tool: 'com.progress', code: 'revision_conflict' });
  release2.open();
  await settle(h2, r2, 2, 5);
  s = await h2.state();
  assert.equal(s.requests[rid2].state, 'completed');
  assert.ok(!h2.kinds().includes('board.reconcile.needed'));
});

test('FAA-86: a lost complete answer on a resumed request settles on the next tick, in the same session', async (t) => {
  // The transferred request's known outcome is completed, the board stores it, and the answer is lost while the session
  // holds: the entry stays first in the resume queue and the next tick sends the same key again.
  const hub = await fakeHub(t);
  const h = harness(hub);
  h.outcome = { state: 'completed', summary: 'ok', reply: { text: 'here' } };
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const r = h.responder();
  await hub.control({ op: 'fail', tool: 'com.complete', code: 'not_available' }); // the first attempt's complete stores nothing
  await r.step();
  assert.equal((await h.state()).requests[rid].state, 'accepted');
  await hub.control({ op: 'end-sessions' });
  let session = null;
  for (let i = 0; i < 12 && session === null; i += 1) {
    if (!r.session) {
      await hub.control({ op: 'drop', tool: 'com.complete' }); // the resumed complete is stored; its answer is lost
      await h.advance(Math.max(31, r.waitUntil - h.clock.t));
      await r.step();
      if (r.session) session = r.session;
    } else {
      await h.advance(Math.max(31, r.waitUntil - h.clock.t));
      await r.step();
    }
  }
  assert.ok(session, 'the lease holds, so the session is kept');
  assert.equal((await h.state()).requests[rid].state, 'completed');
  for (let i = 0; i < 3; i += 1) {
    await h.advance(Math.max(1, r.waitUntil - h.clock.t));
    await r.step();
  }
  assert.equal(r.session, session, 'settled within the same session, not at the next connect');
  assert.deepEqual(h.checkpoint(), {});
  assert.equal((await h.state()).replies.length, 1);
  assert.equal(r.state, 'ready');
});

test('FAA-77 37: an effect the handler failed or left unobserved is settled from what is observed, else given to the lost-result operation', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  h.outcome = async (request, ctx) => {
    await ctx.beginEffect('x');
    throw new Error('crashed mid-effect');
  };
  h.observed = { state: 'completed', observed: true, summary: 'on disk' };
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const r = h.responder();
  await r.step();
  await settle(h, r, 2, 5); // the handler's calls finish after the tick that started it
  let s = await h.state();
  assert.deepEqual([s.requests[rid].state, s.requests[rid].effect], ['completed', 'succeeded_observed']);
  assert.deepEqual(h.checkpoint(), {});

  const hub2 = await fakeHub(t);
  const h2 = harness(hub2);
  h2.outcome = async (request, ctx) => {
    await ctx.beginEffect();
    return { state: 'completed', observed: false };
  };
  h2.observed = { state: 'failed_known', observed: true, summary: 'nothing was written' };
  const { request: rid2 } = await hub2.control({ op: 'queue', capability: 'video.render' });
  const r2 = h2.responder();
  await r2.step();
  await settle(h2, r2, 2, 5);
  assert.equal((await h2.state()).requests[rid2].state, 'failed_known');
  assert.deepEqual(h2.checkpoint(), {});

  const hub3 = await fakeHub(t);
  const h3 = harness(hub3);
  h3.outcome = h.outcome;
  const { request: rid3 } = await hub3.control({ op: 'queue', capability: 'video.render' });
  const r3 = h3.responder();
  await r3.step();
  await settle(h3, r3, 1, 5);
  s = await h3.state();
  assert.equal(s.requests[rid3].state, 'outcome_unknown'); // the lost-result operation: the slot's next holder took it
  assert.equal(h3.checkpoint()[rid3].step, 'unknown');
  assert.ok(h3.kinds().includes('board.reconcile.needed'));
  h3.observed = { state: 'completed', observed: true, summary: 'on disk after all' };
  await settle(h3, r3, 12);
  s = await h3.state();
  assert.equal(s.requests[rid3].state, 'completed');
  assert.ok(s.calls.includes('com.reconcile'));
  assert.deepEqual(h3.checkpoint(), {});
});

test('FAA-77 38: one lost answer keeps the session and the work; a lost session with work in progress is reconciled without a restart', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  const release = gate();
  h.outcome = async (request, ctx) => {
    await ctx.beginEffect('x');
    await release.promise;
    return { state: 'completed', observed: true, summary: 'done' };
  };
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const r = h.responder();
  await r.step();
  const work = r.current;
  await hub.control({ op: 'drop', tool: 'com.renew' }); // the renewal is stored; its answer is lost
  await h.advance(20);
  await r.step();
  assert.equal(r.current, work);
  assert.equal(work.ctx.stopped, false);
  assert.ok(r.waitUntil - h.clock.t < 40); // tried again while the lease still holds
  release.open();
  await settle(h, r, 2, 5);
  assert.equal((await h.state()).requests[rid].state, 'completed');
  assert.equal(r.state, 'ready');
  assert.ok(!h.kinds().includes('board.reconcile.needed'));

  const hub2 = await fakeHub(t);
  const h2 = harness(hub2);
  const inside = gate();
  h2.outcome = async (request, ctx) => {
    await ctx.beginEffect('x');
    inside.open();
    return new Promise(() => {});
  };
  const { request: rid2 } = await hub2.control({ op: 'queue', capability: 'video.render' });
  const r2 = h2.responder();
  await r2.step();
  await inside.promise;
  await hub2.control({ op: 'forget-sessions' }); // the session is gone but no DELETE came: the slot lapses on its own
  h2.observed = { state: 'completed', observed: true, summary: 'on disk' };
  await settle(h2, r2, 1, 20); // the renew learns the session ended
  await settle(h2, r2, 2, 5); // a new session while the old slot is live: contested
  assert.ok(h2.kinds().includes('board.slot.contested'));
  await settle(h2, r2, 24);
  const s = await h2.state();
  assert.equal(s.requests[rid2].state, 'completed');
  assert.ok(s.calls.includes('com.reconcile'));
  assert.deepEqual(h2.checkpoint(), {});
});

test('FAA-77 39: every transferred request resumes, one per idle tick', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  h.outcome = () => new Promise(() => {}); // each first responder dies inside its work
  const rids = [(await hub.control({ op: 'queue', capability: 'video.render' })).request, (await hub.control({ op: 'queue', capability: 'video.render' })).request];
  const merged = {};
  for (const i of [0, 1]) {
    const file = path.join(hub.data, `cp-${i}.json`);
    await h.responder({ checkpointFile: file }).step();
    Object.assign(merged, JSON.parse(fs.readFileSync(file, 'utf8')).requests);
    await hub.control({ op: 'end-sessions' });
  }
  let s = await h.state();
  assert.deepEqual(rids.map((x) => s.requests[x].state), ['accepted', 'accepted']);
  fs.writeFileSync(path.join(hub.data, 'board-checkpoint.json'), JSON.stringify({ version: 1, requests: merged }), { mode: 0o600 });
  h.outcome = async () => {
    await sleep(30);
    return { state: 'completed', summary: 'resumed' };
  };
  const r = h.responder();
  await r.step();
  await settle(h, r, 4, 5);
  s = await h.state();
  assert.deepEqual(rids.map((x) => s.requests[x].state), ['completed', 'completed']);
  assert.deepEqual(h.checkpoint(), {});
});

// --- FAA-155: a slot the operator moves to another session stays moved (contract DEC-0140 PR-2; CT-174, CT-175) --------
const record = (hub) => {
  const file = path.join(hub.data, 'board-checkpoint.json');
  return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')).slots ?? {} : {};
};

async function crashedHolding(t) {
  // One responder holds the slot at generation 1, accepts a request and dies inside its work; its session ends.
  const hub = await fakeHub(t);
  const h = harness(hub);
  h.outcome = () => new Promise(() => {});
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const first = h.responder();
  await first.step();
  assert.deepEqual(record(hub), { 'video.render': { project: first.project, generation: 1 } });
  await hub.control({ op: 'end-sessions' });
  h.outcome = { state: 'completed', summary: 'Rendered after the restart.' };
  return { hub, h, rid, project: first.project };
}

test('FAA-155: a restart after a move neither replaces nor re-enrolls, says so once, and leaves accepted work held', async (t) => {
  const { hub, h, rid } = await crashedHolding(t);
  await hub.control({ op: 'move', capability: 'video.render' }); // generation 2, another live session
  const before = (await h.tools()).length;
  const second = h.responder();
  await second.step();
  assert.equal(second.slots['video.render'].state, 'moved');
  assert.equal(h.checkpoint()[rid].step, 'lapsed');
  const said = h.events.filter((e) => e[0] === 'board.slot.moved');
  assert.equal(said.length, 1);
  assert.ok(said[0][3].notify);
  assert.match(said[0][2], /moved to another session/);
  assert.deepEqual(said[0][3].data.value, { capability: 'video.render', generation: 2, held: 1 });
  await h.advance(61); // the new holder lets its lease lapse
  for (let i = 0; i < 3; i += 1) {
    await second.step();
    await h.advance(20);
  }
  await h.responder().step(); // another restart
  const s = await h.state();
  assert.ok(!s.calls.slice(before).some((c) => ['com.responder_replace', 'com.enroll', 'com.claim'].includes(c)), s.calls.slice(before).join());
  assert.equal(s.slots['video.render'].generation, 2);
  assert.equal(s.requests[rid].state, 'accepted');
  assert.equal(h.kinds().filter((k) => k === 'board.slot.moved').length, 1);
  assert.equal(record(hub)['video.render'].moved, 2);
});

test('FAA-155: a live responder whose slot moved is not enrolled again when the new holder lapses', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  const r = h.responder();
  await r.step();
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  await hub.control({ op: 'move', capability: 'video.render' });
  await h.advance(15);
  await r.step(); // its com.claim is fenced: com.status shows generation 2
  assert.equal(r.slots['video.render'].state, 'moved');
  assert.deepEqual((await h.tools()).slice(-2), ['com.claim', 'com.status']);
  const seen = (await h.tools()).length;
  await h.advance(61);
  for (let i = 0; i < 4; i += 1) {
    await r.step();
    await h.advance(20);
  }
  const s = await h.state();
  assert.deepEqual(s.calls.slice(seen), []);
  assert.equal(s.slots['video.render'].generation, 2);
  assert.equal(s.requests[rid].state, 'queued');
  assert.equal(h.kinds().filter((k) => k === 'board.slot.moved').length, 1);
});

test('FAA-155: work running when the slot moves stops, stays held, and is never completed or transferred', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  h.outcome = async () => {
    await gate;
    return { state: 'completed' };
  };
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const r = h.responder();
  await r.step(); // accepted; the handler works
  await hub.control({ op: 'move', capability: 'video.render' });
  await h.advance(20);
  await r.step(); // its com.renew is fenced; com.status says the slot moved
  assert.equal(r.slots['video.render'].state, 'moved');
  assert.equal(r.current, null);
  assert.equal(h.checkpoint()[rid].step, 'lapsed');
  release();
  await sleep(20);
  await h.advance(61);
  await r.step();
  await r.step();
  const s = await h.state();
  assert.ok(!s.calls.slice(s.calls.indexOf('com.renew')).some((c) => ['com.complete', 'com.responder_replace', 'com.enroll'].includes(c)));
  assert.equal(s.requests[rid].state, 'accepted');
  assert.equal(h.kinds().filter((k) => k === 'board.slot.moved').length, 1);
});

test('FAA-155: an unmoved restart recovers its own accepted work; takeBack is the operator\'s act', async (t) => {
  const { hub, h, rid } = await crashedHolding(t);
  await h.responder().step();
  let s = await h.state();
  const replace = s.callArgs[s.calls.indexOf('com.responder_replace')];
  assert.deepEqual([replace.expectedGeneration, replace.transfer.requests], [1, [rid]]);
  assert.equal(s.requests[rid].state, 'completed');
  assert.equal(record(hub)['video.render'].generation, 2);
  assert.ok(!h.kinds().includes('board.slot.moved'));

  const moved = await crashedHolding(t);
  await moved.hub.control({ op: 'move', capability: 'video.render' });
  const second = moved.h.responder();
  await second.step();
  assert.equal(second.slots['video.render'].state, 'moved');
  assert.throws(() => second.takeBack('other.capability'), (e) => e.code === 'invalid_arguments');
  second.takeBack('video.render');
  assert.ok(!('video.render' in record(moved.hub)));
  await moved.h.advance(61); // the new holder lapsed: the next tick enrolls and transfers the work left held
  await second.step();
  s = await moved.h.state();
  assert.equal(s.requests[moved.rid].state, 'completed');
  assert.equal(record(moved.hub)['video.render'].generation, s.slots['video.render'].generation);
});

test('FAA-155: an odd or lower generation, recorded or in com.status, is never read as a move (today\'s behaviour)', async (t) => {
  const records = (project) => ['x', { 'video.render': 'x' }, { 'video.render': { project, generation: '1' } }, { 'video.render': { project, generation: true } },
    { 'video.render': { project: 'another-project', generation: 1 } }, { 'video.render': { project, generation: 5 } }];
  for (let i = 0; i < records('').length; i += 1) {
    const { hub, h, rid, project } = await crashedHolding(t);
    const file = path.join(hub.data, 'board-checkpoint.json');
    const odd = records(project)[i];
    fs.writeFileSync(file, JSON.stringify({ ...JSON.parse(fs.readFileSync(file, 'utf8')), slots: odd }), { mode: 0o600 });
    await h.responder().step();
    const s = await h.state();
    assert.ok(s.calls.includes('com.responder_replace'), JSON.stringify(odd));
    assert.equal(s.requests[rid].state, 'completed', JSON.stringify(odd));
    assert.deepEqual(record(hub)['video.render'], { project, generation: 2 });
    assert.ok(!h.kinds().includes('board.slot.moved'));
  }
  for (const odd of ['absent', null, '2', 2.5, true, -1]) {
    const { hub, h } = await crashedHolding(t);
    await hub.control({ op: 'set', values: { status_generation: odd } });
    const r = h.responder();
    await r.step();
    const s = await h.state();
    assert.equal(s.callArgs[s.calls.indexOf('com.responder_replace')].expectedGeneration, 0, String(odd)); // as before: sent as 0
    assert.notEqual(r.slots['video.render']?.state, 'moved');
    assert.ok(!h.kinds().includes('board.slot.moved'));
  }
});

test('FAA-155 seam 1: a lost answer to its own replace or enroll is asked again under its key, never read as a move', async (t) => {
  const { hub, h, rid, project } = await crashedHolding(t);
  await hub.control({ op: 'drop', tool: 'com.responder_replace' }); // generation 2 is committed for it; the answer is lost
  const second = h.responder();
  for (let i = 0; i < 6; i += 1) {
    await second.step();
    await h.advance(1);
  }
  let s = await h.state();
  const replaces = s.callArgs.filter((_, i) => s.calls[i] === 'com.responder_replace');
  assert.deepEqual(replaces[0].idempotency, replaces[1].idempotency); // the same key, asked again
  assert.deepEqual(replaces.map((a) => a.expectedGeneration), [1, 1, 2]); // then once more, for this session
  assert.equal(s.requests[rid].state, 'completed');
  assert.ok(!h.kinds().includes('board.slot.moved'));
  assert.deepEqual(record(hub)['video.render'], { project, generation: 3 });

  const lapsed = await fakeHub(t);
  const l = harness(lapsed);
  await l.responder().step(); // holds generation 1
  await lapsed.control({ op: 'end-sessions' });
  await l.advance(61); // its lease lapses while it is away
  const { request: queued } = await lapsed.control({ op: 'queue', capability: 'video.render' });
  await lapsed.control({ op: 'drop', tool: 'com.enroll' });
  const back = l.responder();
  for (let i = 0; i < 6; i += 1) {
    await back.step();
    await l.advance(1);
  }
  s = await l.state();
  assert.equal(s.requests[queued].state, 'completed');
  assert.ok(!l.kinds().includes('board.slot.moved'));
});

test('FAA-155 seam 1: a refused ask is an answer, so a real move is still seen; 2.0 reads as 2 in both twins', async (t) => {
  const { hub, h, rid } = await crashedHolding(t);
  await hub.control({ op: 'move', capability: 'video.render' });
  const file = path.join(hub.data, 'board-checkpoint.json');
  const doc = JSON.parse(fs.readFileSync(file, 'utf8'));
  doc.slots['video.render'].asking = { op: 'com.enroll', args: { idempotency: { epoch: 1, key: 'x.enroll.lost' }, capability: 'video.render' } };
  fs.writeFileSync(file, JSON.stringify(doc), { mode: 0o600 });
  const second = h.responder();
  for (let i = 0; i < 3; i += 1) {
    await second.step();
    await h.advance(1);
  }
  assert.equal(second.slots['video.render'].state, 'moved');
  assert.equal(h.kinds().filter((k) => k === 'board.slot.moved').length, 1);
  assert.ok(!('asking' in record(hub)['video.render']));
  assert.equal((await h.state()).requests[rid].state, 'accepted');

  const whole = await crashedHolding(t);
  await whole.hub.control({ op: 'set', values: { status_generation: 2.0 } });
  const r = whole.h.responder();
  await r.step();
  assert.equal(r.slots['video.render'].state, 'moved');
});

test('FAA-155 seam 2: a lost ask that never landed does not take a moved slot back; a full disk never stops a renew; a fenced complete without a move transfers', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  const r = h.responder();
  await r.step(); // holds generation 1
  await hub.control({ op: 'end-sessions' }); // it dies with an enroll recorded that never reached the board
  const file = path.join(hub.data, 'board-checkpoint.json');
  const doc = JSON.parse(fs.readFileSync(file, 'utf8'));
  doc.slots['video.render'].asking = { op: 'com.enroll', args: { idempotency: { epoch: 1, key: 'example-agent.enroll.never-sent' }, capability: 'video.render' } };
  fs.writeFileSync(file, JSON.stringify(doc), { mode: 0o600 });
  await hub.control({ op: 'move', capability: 'video.render' });
  await h.advance(61);
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const before = (await h.tools()).length;
  const second = h.responder();
  for (let i = 0; i < 3; i += 1) {
    await second.step();
    await h.advance(1);
  }
  let s = await h.state();
  assert.equal(second.slots['video.render'].state, 'moved');
  assert.equal(h.kinds().filter((k) => k === 'board.slot.moved').length, 1);
  assert.ok(!s.calls.slice(before).includes('com.claim'));
  assert.equal(s.requests[rid].state, 'queued');
  assert.equal(record(hub)['video.render'].generation, 1);

  const full = await fakeHub(t);
  const f = harness(full);
  const live = f.responder();
  await live.step();
  live.checkpoint.slot = () => { throw new fb.BoardError('checkpoint', 'full'); };
  const seen = (await f.tools()).length;
  await f.advance(20);
  await live.step();
  assert.equal(live.state, 'ready');
  assert.ok((await f.tools()).slice(seen).includes('com.enroll'));

  const fenced = await fakeHub(t);
  const c = harness(fenced);
  const { request: done } = await fenced.control({ op: 'queue', capability: 'video.render' });
  await fenced.control({ op: 'fail', tool: 'com.complete', code: 'fenced' });
  const w = c.responder();
  for (let i = 0; i < 4; i += 1) {
    await w.step();
    await c.advance(1);
  }
  s = await c.state();
  assert.ok(s.calls.includes('com.responder_replace'));
  assert.equal(s.requests[done].state, 'completed');
  assert.ok(!c.kinds().includes('board.slot.moved'));
});

test('FAA-155 seam 3: an idle renew writes nothing; a clean leave forgets the record, so a rollback never reads as a move', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  const r = h.responder();
  await r.step();
  const file = path.join(hub.data, 'board-checkpoint.json');
  const before = fs.statSync(file).mtimeMs;
  const plain = r.checkpoint.slot.bind(r.checkpoint);
  let writes = 0;
  r.checkpoint.slot = (c, rec) => { const was = JSON.stringify(r.checkpoint.slots); plain(c, rec); if (JSON.stringify(r.checkpoint.slots) !== was) writes += 1; };
  for (let i = 0; i < 5; i += 1) {
    await h.advance(20);
    await r.step();
  }
  assert.equal(writes, 0);
  assert.equal(fs.statSync(file).mtimeMs, before);
  await r.shutdown(0);
  assert.ok(!('video.render' in record(hub)));
  await hub.control({ op: 'move', capability: 'video.render' }); // an older kit enrolls the free slot, then stops
  await h.advance(61);
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  const second = h.responder();
  for (let i = 0; i < 3; i += 1) {
    await second.step();
    await h.advance(1);
  }
  assert.equal((await h.state()).requests[rid].state, 'completed');
  assert.ok(!h.kinds().includes('board.slot.moved'));
});

test('FAA-155 seam 4: at its own cadence an idle holder writes nothing; a lapsed holder\'s enroll is recorded; a full disk never stops a replay', async (t) => {
  let seed = 7;
  const jitter = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
  for (const rand of [() => 0.5, jitter]) {
    const hub = await fakeHub(t);
    const h = harness(hub);
    const r = h.responder({ rand });
    let wait = await r.step();
    let changes = 0;
    const plain = r.checkpoint.slot.bind(r.checkpoint);
    r.checkpoint.slot = (c, rec) => { const was = JSON.stringify(r.checkpoint.slots); plain(c, rec); if (JSON.stringify(r.checkpoint.slots) !== was) changes += 1; };
    for (let i = 0; i < 40; i += 1) {
      await h.advance(wait);
      wait = await r.step();
    }
    assert.equal(changes, 0);
    assert.ok((await h.tools()).filter((c) => c === 'com.enroll').length >= 10);
  }

  const lapsed = await fakeHub(t);
  const l = harness(lapsed);
  const holder = l.responder();
  await holder.step();
  const seen = [];
  const plain = holder.checkpoint.slot.bind(holder.checkpoint);
  holder.checkpoint.slot = (c, rec) => { seen.push(rec); plain(c, rec); };
  await lapsed.control({ op: 'fail', tool: 'com.claim', code: 'lease_expired' });
  await l.advance(1);
  await holder.step();
  assert.ok(seen.some((rec) => isObjLike(rec) && 'asking' in rec), JSON.stringify(seen));

  const full = await fakeHub(t);
  const f = harness(full);
  await f.responder().step();
  await full.control({ op: 'end-sessions' });
  const file = path.join(full.data, 'board-checkpoint.json');
  const doc = JSON.parse(fs.readFileSync(file, 'utf8'));
  doc.slots['video.render'].asking = { op: 'com.enroll', args: { idempotency: { epoch: 1, key: 'example-agent.enroll.lost' }, capability: 'video.render' } };
  fs.writeFileSync(file, JSON.stringify(doc), { mode: 0o600 });
  const second = f.responder();
  second.checkpoint.slot = () => { throw new fb.BoardError('checkpoint', 'full'); };
  for (let i = 0; i < 3; i += 1) {
    await second.step();
    await f.advance(1);
  }
  assert.notEqual(second.state, 'down');
  assert.ok(!f.kinds().includes('board.blocked'));
});

const isObjLike = (v) => v !== null && typeof v === 'object';

test('FAA-155 seam 5: a lost ask refused under a retired epoch is no move; a recorded move stays when status names no generation', async (t) => {
  const hub = await fakeHub(t);
  const h = harness(hub);
  await h.responder().step();
  await hub.control({ op: 'end-sessions' });
  await h.advance(61);
  await hub.control({ op: 'drop', tool: 'com.enroll' });
  const second = h.responder();
  await second.step(); // the enroll lands at generation 2; its answer is lost
  await hub.control({ op: 'set', values: { epoch: 2 } });
  const { request: rid } = await hub.control({ op: 'queue', capability: 'video.render' });
  for (let i = 0; i < 4; i += 1) {
    await second.step();
    await h.advance(20);
  }
  assert.ok(!h.kinds().includes('board.slot.moved'));
  assert.equal((await h.state()).requests[rid].state, 'completed');

  const moved = await fakeHub(t);
  const m = harness(moved);
  const r = m.responder();
  await r.step();
  await moved.control({ op: 'move', capability: 'video.render' });
  await m.advance(15);
  await r.step();
  assert.equal(r.slots['video.render'].state, 'moved');
  await moved.control({ op: 'end-sessions' });
  await moved.control({ op: 'set', values: { status_generation: 'absent' } });
  const before = (await m.tools()).length;
  const again = m.responder();
  await again.step();
  assert.ok(!(await m.tools()).slice(before).includes('com.enroll'));
  assert.equal(again.slots['video.render'].state, 'moved');
});

test('FAA-155: the Python and Node kits read each other\'s slot record', async () => {
  const dir = tempDir('faa155-cp-');
  const file = path.join(dir, 'cp.json');
  const cp = new fb.Checkpoint(file);
  cp.put({ request: 'req_000000001', step: 'lapsed', keys: {} });
  cp.slot('video.render', { project: 'p', generation: 3, moved: 4 });
  const scripts = path.join(here, '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts');
  const py = spawnSync('python3', ['-c', `import sys, json; sys.path.insert(0, ${JSON.stringify(scripts)}); import fabric_board as fb
c = fb.Checkpoint(${JSON.stringify(file)}); print(json.dumps(c.slots, sort_keys=True)); c.slot("text.write", {"project": "p", "generation": 1})`], { encoding: 'utf8' });
  assert.equal(py.status, 0, py.stderr);
  assert.deepEqual(JSON.parse(py.stdout), { 'video.render': { generation: 3, moved: 4, project: 'p' } });
  const back = new fb.Checkpoint(file);
  assert.deepEqual(back.slots, { 'text.write': { generation: 1, project: 'p' }, 'video.render': { generation: 3, moved: 4, project: 'p' } });
  assert.deepEqual(Object.keys(back.entries), ['req_000000001']);
  fs.rmSync(dir, { recursive: true, force: true });
});
