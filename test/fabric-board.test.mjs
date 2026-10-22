// FAA-12b and FAA-40 in the Node kit: fabric-hub.mjs and fabric-board.mjs, the twins of fabric_hub.py and fabric_board.py,
// held to the same contract fixtures (contract f00a768, fixtures/contract/comms-vectors.json and canonical.json) and driven
// against the same fake Fabric hub (test/fake_fabric_hub.py, run as a process).
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import * as fb from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-board.mjs';
import * as fh from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-hub.mjs';
import { tempDir } from './temp-dir.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const COMMS = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/comms-vectors.json'), 'utf8'));
const CANONICAL = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/canonical.json'), 'utf8'));
const FIXTURES = Object.fromEntries(COMMS.fixtures.map((f) => [f.name, f]));

// --- the fake hub as a process ---------------------------------------------------------------------------------------
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
  assert.equal(fs.statSync(target).mode & 0o777, 0o600);
  const grant = await client.joinBoard(hub.project, hub.cred);
  assert.deepEqual(grant.capabilities, ['video.render']);
  assert.ok(!JSON.stringify(grant).includes(grant.bearer()));
  await hub.control({ op: 'set', values: { grant: false } });
  await assert.rejects(client.joinBoard(hub.project, hub.cred), (e) => e.code === 'not_authorized' && e.data.ask.capabilities[0] === 'board.respond');
  const dead = new fh.HubClient(hub.root, { alive: () => false });
  const before = (await hub.control({ op: 'state' })).bindingsSeen.length;
  await assert.rejects(dead.joinBoard(hub.project, hub.cred), (e) => e.code === 'not-running');
  assert.equal((await hub.control({ op: 'state' })).bindingsSeen.length, before); // never sent
  fs.chmodSync(hub.cred, 0o644);
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
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(seen.stopped, true);
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
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(h3.checkpoint()[busy].step, 'in-progress');
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
