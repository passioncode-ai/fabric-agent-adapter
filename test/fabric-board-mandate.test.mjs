// FAA-135 in the Node kit: the board responder reads the operator's mandate from a request of his own Project (contract
// project-comms.md, DEC-0125 MD-3), the twin of test/test_fabric_board_mandate.py, against the same fake hub process.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import * as fb from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-board.mjs';
import * as fh from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-hub.mjs';
import { handOn, operatorMandate } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-mandate.mjs';
import { tempDir } from './temp-dir.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const OTHER_PROJECT = '9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d'; // the fake hub's requester
const WALL = 1_793_700_000_000; // the responder's wall clock, in milliseconds
const AT = new Date(WALL).toISOString();
const WORDS = 'render the teaser for the launch';

const mandate = (callee = 'example-agent', source = undefined) => handOn(operatorMandate({
  task: 'task-teaser', instruction: WORDS, scope: { capabilities: ['video.render'], effects: ['draft'] }, lead: 'lead-agent', at: AT, source,
}), callee, AT);
const body = (...blocks) => `Render the teaser.\n\n${blocks.map((b) => `\`\`\`json\n${b}\n\`\`\``).join('\n\n')}\n`;

async function fakeHub(t) {
  const dir = tempDir('faa135-');
  const root = path.join(dir, 'fabric');
  const child = spawn('python3', [path.join(here, 'fake_fabric_hub.py'), 'serve', '--root', root, '--capability', 'video.render'],
    { stdio: ['pipe', 'pipe', 'inherit'] });
  const line = await new Promise((resolve, reject) => {
    let buf = '';
    child.stdout.on('data', (c) => { buf += c; if (buf.includes('\n')) resolve(buf.split('\n')[0]); });
    child.on('exit', (code) => reject(new Error(`fake hub exited ${code}`)));
  });
  const info = JSON.parse(line);
  t.after(() => { child.stdin.end(); fs.rmSync(dir, { recursive: true, force: true }); });
  const data = path.join(dir, 'svc');
  fs.mkdirSync(data, { mode: 0o700 });
  const cred = path.join(data, 'board.credential');
  fs.writeFileSync(cred, info.credential, { mode: 0o600 });
  const control = async (cmd) => (await fetch(`http://127.0.0.1:${info.port}/_control`, { method: 'POST', body: JSON.stringify(cmd) })).json();
  const events = [];
  const seen = [];
  const handler = async (request, ctx) => {
    seen.push([ctx.mandate, ctx.mandateCovers({ capability: 'video.render', effect: 'draft' }), ctx.mandateCovers({ capability: 'video.cut', effect: 'draft' })]);
    return { state: 'completed', summary: 'Rendered.' };
  };
  const options = (extra = {}) => ({ hub: new fh.HubClient(root), projectId: info.project, capabilities: ['video.render'], credentialFile: cred,
    checkpointFile: path.join(data, 'board-checkpoint.json'), handler, admit: () => null, observe: () => null,
    emit: (kind, level, text, value) => events.push([kind, level, text, value]), service: 'example-agent', now: () => 0, rand: () => 0.5,
    agentId: 'example-agent', mandateFrom: new Set([OTHER_PROJECT]), wall: () => WALL, ...extra });
  const runOne = async (text, { provenance = 'trusted', ...extra } = {}) => {
    await control({ op: 'queue', capability: 'video.render', text, provenance });
    await new fb.Responder(options(extra)).step();
    assert.equal(seen.length, 1, 'the handler ran once');
    return seen[0];
  };
  return { data, events, runOne, options };
}

test('FAA-135: a trusted request from a declared Project carries its mandate', async (t) => {
  const h = await fakeHub(t);
  const m = mandate();
  const [got, covered, outside] = await h.runOne(body(JSON.stringify(m)));
  assert.deepEqual(got, m);
  assert.deepEqual(covered, { ok: true, recordAs: { by: 'operator', via: 'mandate', task: 'task-teaser', chain: ['lead-agent', 'example-agent'] } });
  assert.equal(outside.ok, false);
  assert.equal(outside.data.detail, 'outside-mandate: capability');
});

test('FAA-135: the personal board takes any trusted sender', async (t) => {
  const h = await fakeHub(t);
  const [, covered] = await h.runOne(body(JSON.stringify(mandate())), { mandateFrom: fb.PERSONAL_BOARD });
  assert.equal(covered.ok, true);
});

for (const [name, extra] of [['no mandateFrom', { mandateFrom: null }], ['no agentId', { agentId: null }],
  ['an undeclared Project', { mandateFrom: new Set(['another-project']) }], ['an unverified sender', { provenance: 'unverified' }]]) {
  test(`FAA-135: no mandate with ${name}`, async (t) => {
    const h = await fakeHub(t);
    const [got, covered, outside] = await h.runOne(body(JSON.stringify(mandate())), extra);
    assert.equal(got, null);
    assert.equal(covered, null, 'no mandate travelled: the handler asks the operator as before');
    assert.equal(outside, null);
  });
}

for (const [name, text, code] of [['two blocks', body(JSON.stringify(mandate()), JSON.stringify(mandate())), 'mandate-blocks'],
  ['an unreadable block', body('{"kind": "mandate/1", "task": '), 'mandate-unreadable'],
  ['NaN', body(`${JSON.stringify(mandate()).slice(0, -1)}, "x": NaN}`), 'mandate-unreadable']]) {
  test(`FAA-135: ${name} is no mandate, named by its code`, async (t) => {
    const h = await fakeHub(t);
    const [got, covered] = await h.runOne(text);
    assert.equal(got, null);
    assert.equal(covered, null);
    const said = h.events.filter((e) => e[0] === 'board.request.mandate-unread');
    assert.equal(said.length, 1);
    assert.ok(said[0][2].includes(code));
    assert.ok(!JSON.stringify(h.events.map((e) => e.slice(2))).includes(WORDS), 'the operator\'s words reach no event');
  });
}

test('FAA-135: a JSON block that is no mandate is ignored', async (t) => {
  const h = await fakeHub(t);
  const [got] = await h.runOne(body('{"frames": 24}'));
  assert.equal(got, null);
  assert.deepEqual(h.events.filter((e) => e[0] === 'board.request.mandate-unread'), []);
});

test('FAA-135: a chain that does not end here is not for this call', async (t) => {
  const h = await fakeHub(t);
  const [got, covered] = await h.runOne(body(JSON.stringify(mandate('other-agent'))));
  assert.equal(got.chain.at(-1).agent, 'other-agent');
  assert.equal(covered.data.detail, 'mandate-not-for-this-call');
});

test('FAA-135: an expired mandate is refused by the wall clock', async (t) => {
  const h = await fakeHub(t);
  const [, covered] = await h.runOne(body(JSON.stringify(mandate())), { wall: () => WALL + 2 * 24 * 3600 * 1000 });
  assert.equal(covered.data.detail, 'mandate-expired');
});

test('FAA-135: the operator\'s words reach no checkpoint', async (t) => {
  const h = await fakeHub(t);
  await h.runOne(body(JSON.stringify(mandate()), JSON.stringify(mandate())));
  const file = path.join(h.data, 'board-checkpoint.json');
  assert.ok(!(fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : '').includes(WORDS));
});

test('FAA-135: a responder refuses a bad agentId or mandateFrom', async (t) => {
  const h = await fakeHub(t);
  for (const extra of [{ agentId: 'Not An Id' }, { mandateFrom: 'everyone' }, { mandateFrom: [42] }, { mandateFrom: 42 },
    { mandateFrom: new String('personal-board') }, { mandateFrom: new Map([[OTHER_PROJECT, true]]) }]) {
    assert.throws(() => new fb.Responder(h.options(extra)), fb.BoardError, JSON.stringify(extra));
  }
});

test('FAA-135: a CRLF body is read', async (t) => {
  const h = await fakeHub(t);
  const [, covered] = await h.runOne(body(JSON.stringify(mandate())).replaceAll('\n', '\r\n'));
  assert.equal(covered.ok, true);
});

test('FAA-135: a board block carries no source (OA-7): one that does has it dropped', async (t) => {
  const h = await fakeHub(t);
  const [got, covered] = await h.runOne(body(JSON.stringify(mandate('example-agent', { project: 'example-site', session: 'sess-1' }))));
  assert.equal('source' in got, false);
  assert.equal('source' in covered.recordAs, false);
});
