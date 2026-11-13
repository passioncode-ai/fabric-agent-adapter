// 0.56.0 seam r2: a slot moved while the service was down is read as moved, even when recovery stopped early or the
// session was dropped at connect, and the kit never takes it back on its own (Node twin of test_fabric_board.py's
// MovesSurviveRecovery and LeaveKeepsUnconfirmedRecords).
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import * as fb from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-board.mjs';
import * as fh from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-hub.mjs';
import { ListenerRefused, TABLE_RESTRICTED } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-peer-owner.mjs';
import { tempDir } from './temp-dir.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));

async function fakeHub(t, capabilities) {
  const dir = tempDir('faa056-');
  const root = path.join(dir, 'fabric');
  const child = spawn('python3', [path.join(here, 'fake_fabric_hub.py'), 'serve', '--root', root, ...capabilities.flatMap((c) => ['--capability', c])],
    { stdio: ['pipe', 'pipe', 'inherit'] });
  const line = await new Promise((resolve, reject) => {
    let buf = '';
    child.stdout.on('data', (c) => { buf += c; if (buf.includes('\n')) resolve(buf.split('\n')[0]); });
    child.on('exit', (code) => reject(new Error(`fake hub exited ${code}`)));
  });
  const info = JSON.parse(line);
  t.after(() => child.stdin.end());
  const data = path.join(dir, 'svc');
  fs.mkdirSync(data, { mode: 0o700 });
  const cred = path.join(data, 'board.credential');
  fs.writeFileSync(cred, info.credential, { mode: 0o600 });
  const control = async (cmd) => (await fetch(`http://127.0.0.1:${info.port}/_control`, { method: 'POST', body: JSON.stringify(cmd) })).json();
  const clock = { t: 0 };
  const events = [];
  const gate = { admit: () => null };
  const advance = async (s) => { clock.t += s; await control({ op: 'advance', seconds: s }); };
  const options = () => ({ hub: new fh.HubClient(root), projectId: info.project, capabilities, credentialFile: cred,
    checkpointFile: path.join(data, 'board-checkpoint.json'), handler: async () => ({ state: 'completed' }), admit: (r) => gate.admit(r),
    observe: () => null, emit: (k) => events.push(k), service: 'example-agent', now: () => clock.t, rand: () => 0.5 });
  const responder = () => new fb.Responder(options());
  return { data, control, clock, events, advance, responder, options, gate };
}

test('0.56.0 seam r2: a moved slot skipped by recovery is not enrolled by the retry tick', async (t) => {
  const CAPS = ['a.one', 'b.two', 'c.three'];
  const h = await fakeHub(t, CAPS);
  const r1 = h.responder();
  await r1.step();
  assert.ok(CAPS.every((c) => r1.slots[c].state === 'held'));
  r1.session = null; // the process dies: no DELETE, the records stay
  await h.advance(61);
  await h.control({ op: 'move', capability: 'c.three' });
  await h.control({ op: 'drop', tool: 'com.enroll', capability: 'b.two' }); // recovery stops at b.two
  const r2 = h.responder();
  await r2.step();
  await h.advance(61); // the new holder of c.three lets its lease lapse
  for (let i = 0; i < 12; i += 1) { await r2.step(); await h.advance(20); }
  assert.equal(r2.slots['c.three']?.state, 'moved');
  assert.equal(h.events.filter((k) => k === 'board.slot.moved').length, 1);
});

for (const code of ['capacity_exceeded', 'no-epoch']) {
  test(`0.56.0 seam r2: a move while down survives a fault at connect (${code})`, async (t) => {
    const h = await fakeHub(t, ['video.render']);
    const r1 = h.responder();
    await r1.step();
    r1.session = null;
    await h.advance(61);
    await h.control({ op: 'move', capability: 'video.render' });
    await h.control({ op: 'fail', tool: 'com.status', code });
    const r2 = h.responder();
    await r2.step(); // com.status refused while connecting: the session is dropped with a DELETE
    const record = JSON.parse(fs.readFileSync(path.join(h.data, 'board-checkpoint.json'), 'utf8')).slots ?? {};
    assert.ok('video.render' in record, 'the unconfirmed record stays');
    for (let i = 0; i < 3; i += 1) { await h.advance(Math.max(1, r2.waitUntil - h.clock.t + 0.1)); await r2.step(); }
    await h.advance(61);
    for (let i = 0; i < 6; i += 1) { await r2.step(); await h.advance(20); }
    assert.equal(r2.slots['video.render']?.state, 'moved');
  });
}

test('0.56.0 seam r3: a slot paused under a hold is left cleanly; a standby taking it is no move', async (t) => {
  const h = await fakeHub(t, ['video.render']);
  const r = h.responder();
  await r.step();
  await h.control({ op: 'set', values: { holds: { slots: [{ project: r.project, capability: 'video.render' }] } } });
  await h.advance(31);
  r.waitUntil = 0;
  await r.step(); // the renewing enroll is refused `held`: paused
  assert.equal(r.slots['video.render'].state, 'paused');
  await r.shutdown(0.1);
  const record = JSON.parse(fs.readFileSync(path.join(h.data, 'board-checkpoint.json'), 'utf8')).slots ?? {};
  assert.ok(!('video.render' in record));
  await h.control({ op: 'set', values: { holds: {} } });
  await h.control({ op: 'move', capability: 'video.render' });
  await h.advance(61);
  const r2 = h.responder();
  await r2.step();
  assert.equal(r2.slots['video.render'].state, 'held');
  assert.ok(!h.events.includes('board.slot.moved'));
});

test('0.56.0 seam r3: leave forgets a record at or below the confirmed generation; held is required', () => {
  const cp = new fb.Checkpoint(path.join(tempDir('faa056l-'), 'leave.json'));
  for (const [c, g] of [['a', 1], ['b', 2], ['c', 3], ['d', 1]]) cp.slot(c, { project: 'p', generation: g });
  cp.leave('p', { a: 2, b: 2, c: 2 });
  assert.deepEqual(Object.keys(cp.slots).sort(), ['c', 'd']);
  assert.throws(() => cp.leave('p'), TypeError);
});

test('0.56.0 seam r3: two contested capabilities are each said once', async (t) => {
  const CAPS = ['video.render', 'video.cut'];
  const h = await fakeHub(t, CAPS);
  const other = new fb.Responder({ ...h.options(), checkpointFile: path.join(h.data, 'other-checkpoint.json'), emit: () => {} });
  await other.step();
  const me = h.responder();
  await me.step();
  for (let i = 0; i < 6; i += 1) {
    await h.advance(30);
    other.waitUntil = 0; me.waitUntil = 0;
    await other.step(); await me.step();
  }
  assert.equal(h.events.filter((k) => k === 'board.slot.contested').length, 2);
});

test('0.56.0 seam r4: a suspect slot keeps its record at a clean stop', async (t) => {
  const h = await fakeHub(t, ['video.render']);
  const r = h.responder();
  await r.step();
  await h.advance(15);
  await h.control({ op: 'queue', capability: 'video.render' });
  h.gate.admit = async () => { await h.control({ op: 'move', capability: 'video.render' }); return null; };
  r.waitUntil = 0;
  await r.step();
  h.gate.admit = () => null;
  assert.ok(r.suspect.has('video.render'));
  await r.shutdown(0.1);
  assert.ok('video.render' in (JSON.parse(fs.readFileSync(path.join(h.data, 'board-checkpoint.json'), 'utf8')).slots ?? {}));
  const r2 = h.responder();
  await r2.step();
  assert.equal(r2.slots['video.render'].state, 'moved');
});

test('0.56.0 seam r4: a move during a hold is read before the next ask', async (t) => {
  const h = await fakeHub(t, ['video.render']);
  const r = h.responder();
  await r.step();
  await h.control({ op: 'set', values: { holds: { slots: [{ project: r.project, capability: 'video.render' }] } } });
  await h.advance(31);
  r.waitUntil = 0;
  await r.step();
  assert.equal(r.slots['video.render'].state, 'paused');
  await h.control({ op: 'move', capability: 'video.render' });
  await h.advance(20);
  r.waitUntil = 0;
  await r.step();
  assert.equal(r.slots['video.render'].state, 'moved');
  assert.ok(h.events.includes('board.slot.moved'));
});

test('0.56.0 unit r6: the retry branch reads a move before it enrolls', async (t) => {
  const CAPS = ['video.render', 'video.cut'];
  const h = await fakeHub(t, CAPS);
  const r1 = h.responder();
  await r1.step();
  r1.session = null; // the process dies: no DELETE, the records stay
  await h.advance(61);
  await h.control({ op: 'refuse', tool: 'com.enroll', capability: 'video.cut', code: 'capacity_exceeded' });
  const r2 = h.responder();
  await r2.step();
  assert.equal(r2.slots['video.cut'].state, 'retry');
  await h.control({ op: 'unrefuse', tool: 'com.enroll', capability: 'video.cut' });
  await h.control({ op: 'move', capability: 'video.cut' });
  await h.advance(61); // the standby lets its lease lapse
  for (let i = 0; i < 8; i += 1) {
    await h.advance(Math.max(1, (r2.slots['video.cut'].retryAt ?? r2.slots['video.cut'].retry_at ?? 0) - h.clock.t));
    r2.waitUntil = 0;
    await r2.step();
  }
  assert.equal(r2.slots['video.cut']?.state, 'moved');
  assert.equal(h.events.filter((k) => k === 'board.slot.moved').length, 1);
});

test('0.56.0 seam r6: close reads only an integer 2xx status as a release, as Python does', async () => {
  const grant = { origin: 'http://127.0.0.1:1', bearer: () => 'x' };
  for (const [answer, want] of [[null, false], [{}, false], [{ status: '200' }, false], [{ status: 200.5 }, false],
    [{ status: 200 }, true], [{ status: 204 }, true], [{ status: 404 }, false]]) {
    const s = new fb.BoardSession(grant, { post: async () => answer });
    s.mcpSession = 's-1';
    assert.equal(await s.close(), want, JSON.stringify(answer));
    assert.equal(s.mcpSession, null);
  }
});

test('0.56.0 seam r7: a close timeout not above 0 is the session\'s own, as in Python', async () => {
  const grant = { origin: 'http://127.0.0.1:1', bearer: () => 'x' };
  const sent = [];
  const s = new fb.BoardSession(grant, { post: async (_o, _b, _t, opts) => { sent.push(opts.timeout); return { status: 200 }; } });
  for (const timeout of [0, -1, 2500]) { s.mcpSession = 's-1'; assert.equal(await s.close(timeout), true); }
  assert.deepEqual(sent, [15000, 15000, 2500]);
});

test('0.56.0 seam r8: a constructor timeout not above 0 is the default, as in Python', () => {
  for (const timeout of [0, -1]) assert.equal(new fb.BoardSession({}, { timeout }).timeout, 15000);
});

test('FAA-252: a hub port another OS account holds is foreign-user, never unreachable; board.down says so', async (t) => {
  const grant = { origin: 'http://127.0.0.1:1', bearer: () => 'x' };
  const refused = async () => { throw new fh.HubError('foreign-user', 'The hub\'s port is not held by this OS account\'s process; nothing was sent.', true); };
  const s = new fb.BoardSession(grant, { post: refused });
  await assert.rejects(s.open(), (e) => e.code === 'foreign-user' && e.retryable === true && !/may have been stored/.test(e.message));
  s.mcpSession = 's-1';
  await assert.rejects(s.call('com.status', {}), (e) => e.code === 'foreign-user');
  const { SESSION_CODES } = await import('../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-board-slots.mjs');
  assert.ok(SESSION_CODES.has('foreign-user'));
  const events = [];
  const r = Object.create(fb.Responder.prototype);
  Object.assign(r, { state: 'running', slots: {}, backoff: { next: () => 1 }, now: () => 0, leaseLeft: () => 0, emit: (...e) => events.push(e), dropSession: async () => {} });
  await fb.Responder.prototype.fault.call(r, new fb.BoardError('foreign-user', 'nothing was sent', true));
  const down = events.filter((e) => e[0] === 'board.down').at(-1);
  assert.equal(down[3].reason, 'foreign-user');
  assert.match(down[2], /another OS account/);
});

test('FAA-272: a hub refusal keeps the owner\'s reason; a restricted table is not retryable', () => {
  const owner = (kind, reason = null) => ({ kind, uid: null, pid: null, method: 'netstat', reason });
  for (const [who, reason, retryable] of [
    [owner('unknown', `${TABLE_RESTRICTED}: this runtime sees no other process's sockets`), TABLE_RESTRICTED, false],
    [owner('unknown', 'no-row'), 'no-row', true],
    [owner('another-account'), 'another-account', true],
  ]) {
    const e = fh.listenerRefusal(new ListenerRefused('server-unverified', 'refused', who));
    assert.deepEqual([e.code, e.retryable, e.data.reason], ['foreign-user', retryable, reason], reason);
    assert.ok(e.message.includes(reason), e.message);
    assert.ok(e.message.includes(who.kind), e.message);
  }
});

// FAA-194 (5): each moved slot read its own com.status once a renewal; a tick now reads it once for all of them.
test('FAA-194 (5): moved slots share one com.status read a tick', async (t) => {
  const h = await fakeHub(t, ['video.render', 'video.cut']);
  const r = h.responder();
  await r.step();
  await h.control({ op: 'move', capability: 'video.render' });
  await h.control({ op: 'move', capability: 'video.cut' });
  await h.advance(20);
  await r.step();
  assert.deepEqual(Object.fromEntries(Object.entries(r.slots).map(([c, s]) => [c, s.state])), { 'video.render': 'moved', 'video.cut': 'moved' });
  for (let k = 0; k < 3; k += 1) {
    const before = (await h.control({ op: 'state' })).calls.length;
    await h.advance(20);
    await r.step();
    const calls = (await h.control({ op: 'state' })).calls.slice(before);
    assert.equal(calls.filter((c) => c === 'com.status').length, 1, calls.join(', '));
  }
});

// FAA-187 (21): a notify event names the page that resolves it; the responder takes a link per kind from the service.
test('FAA-187 (21): a notify notice carries the link the service gives for its kind', async (t) => {
  const h = await fakeHub(t, ['video.render']);
  const seen = [];
  const r = new fb.Responder({ ...h.options(), links: { 'board.slot.moved': '/#board' }, emit: (kind, level, text, extra) => seen.push([kind, extra]) });
  await r.step();
  await h.control({ op: 'move', capability: 'video.render' });
  await h.advance(20);
  await r.step();
  const moved = seen.filter(([kind]) => kind === 'board.slot.moved');
  assert.equal(moved.length, 1);
  assert.deepEqual([moved[0][1].notify, moved[0][1].link], [true, '/#board']);
  assert.ok(seen.every(([kind, extra]) => kind === 'board.slot.moved' || !('link' in extra)));
  for (const bad of [{ 'board.slot.moved': 'https://elsewhere.example/x' }, { 'board.slot.moved': 7 }, ['board.slot.moved'], 'x']) {
    assert.throws(() => new fb.Responder({ ...h.options(), links: bad }), (e) => e.code === 'invalid_arguments', JSON.stringify(bad));
  }
});

// FAA-194 (8): a move back says the slot is this service's again.
test('FAA-194 (8): a move back is said', async (t) => {
  const h = await fakeHub(t, ['video.render', 'video.cut']);
  const r = h.responder();
  await r.step();
  const mine = (await h.control({ op: 'state' })).slots['video.cut'].holder;
  await h.control({ op: 'move', capability: 'video.cut' });
  await h.advance(20);
  await r.step();
  await h.control({ op: 'move', capability: 'video.cut', to: mine });
  await h.advance(20);
  await r.step();
  assert.equal(h.events.filter((k) => k === 'board.slot.returned').length, 1, h.events.join(', '));
});

// FAA-194 (11): the Node twin of test_a_move_back_waits_while_other_work_runs: no move-back claim while work runs.
test('FAA-194 (11): a move back waits while other work runs', async (t) => {
  const h = await fakeHub(t, ['video.render', 'video.cut']);
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  t.after(() => release());
  const r = new fb.Responder({ ...h.options(), handler: async (request) => {
    if (request.capability === 'video.cut') await gate;
    return { state: 'completed' };
  } });
  await r.step();
  const mine = (await h.control({ op: 'state' })).slots['video.render'].holder;
  await h.control({ op: 'move', capability: 'video.render' });
  await h.advance(20);
  await r.step();
  const { request: cut } = await h.control({ op: 'queue', capability: 'video.cut' });
  await h.advance(20);
  await r.step(); // video.cut is claimed and runs
  assert.ok(r.current);
  await h.control({ op: 'move', capability: 'video.render', to: mine });
  const { request: render } = await h.control({ op: 'queue', capability: 'video.render' });
  const before = (await h.control({ op: 'state' })).calls.length;
  await h.advance(20);
  await r.step();
  const state = await h.control({ op: 'state' });
  const claims = state.calls.slice(before).filter((c, k) => c === 'com.claim' && state.callArgs[before + k]?.capability === 'video.render');
  assert.deepEqual(claims, [], 'no move-back claim while other work runs');
  assert.equal(r.slots['video.render'].state, 'moved');
  release();
  for (let k = 0; k < 4; k += 1) {
    await new Promise((resolve) => setTimeout(resolve, 50));
    await h.advance(20);
    await r.step();
  }
  const done = await h.control({ op: 'state' });
  assert.equal(done.requests[cut].state, 'completed');
  assert.equal(done.requests[render].state, 'completed');
});
