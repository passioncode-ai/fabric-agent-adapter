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
  const advance = async (s) => { clock.t += s; await control({ op: 'advance', seconds: s }); };
  const responder = () => new fb.Responder({ hub: new fh.HubClient(root), projectId: info.project, capabilities, credentialFile: cred,
    checkpointFile: path.join(data, 'board-checkpoint.json'), handler: async () => ({ state: 'completed' }), admit: () => null,
    observe: () => null, emit: (k) => events.push(k), service: 'example-agent', now: () => clock.t, rand: () => 0.5 });
  return { data, control, clock, events, advance, responder };
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
