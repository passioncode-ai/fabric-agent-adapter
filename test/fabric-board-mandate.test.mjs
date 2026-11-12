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
import { makeEvent } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-events.mjs';
import { PERSONAL_BOARD as _PB, covers, mandateOptions, readMandate, BoardRequest } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-board-link.mjs';
import util from 'node:util';
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
    const file = path.join(data, 'board-checkpoint.json');
    seen.checkpoint = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : ''; // during the work (product reading 5)
    seen.ctx = JSON.stringify(ctx);
    seen.push([ctx.mandate, ctx.mandateCovers({ capability: 'video.render', effect: 'draft' }), ctx.mandateCovers({ capability: 'video.cut', effect: 'draft' })]);
    return { state: 'completed', summary: 'Rendered.' };
  };
  const options = (extra = {}) => ({ hub: new fh.HubClient(root), projectId: info.project, capabilities: ['video.render'], credentialFile: cred,
    checkpointFile: path.join(data, 'board-checkpoint.json'), handler, admit: () => null, observe: () => null,
    emit: (kind, level, text, value) => events.push([kind, level, text, value]), service: 'example-agent', now: () => 0, rand: () => 0.5,
    agentId: 'example-agent', mandateFrom: new Set([OTHER_PROJECT]), wall: () => WALL, ...extra });
  const runOne = async (text, { provenance = 'trusted', ...extra } = {}) => {
    seen.request = (await control({ op: 'queue', capability: 'video.render', text, provenance })).request;
    await new fb.Responder(options(extra)).step();
    assert.equal(seen.length, 1, 'the handler ran once');
    return seen[0];
  };
  return { data, events, runOne, options, seen, control };
}

test('FAA-135: a trusted request from a declared Project carries its mandate', async (t) => {
  const h = await fakeHub(t);
  const m = mandate();
  const [got, covered, outside] = await h.runOne(body(JSON.stringify(m)));
  assert.deepEqual(got, m);
  assert.deepEqual(covered, { ok: true, recordAs: { by: 'operator', via: 'mandate', task: 'task-teaser', chain: ['lead-agent', 'example-agent'], caller: OTHER_PROJECT } });
  assert.equal(outside.ok, false);
  assert.equal(outside.data.detail, 'outside-mandate: capability');
});

test('FAA-135: identifyAgent binds the sender\'s agent id; null binds nothing, anything else fails closed', async (t) => {
  const heard = [];
  const cases = [[(sender) => { heard.push(sender); return 'lead-agent'; }, 'ok'], [() => null, 'ok'], [() => undefined, 'ok'],
    [() => 'other-agent', 'mandate-not-for-this-call'], [() => 'Lead Agent', 'mandate-not-for-this-call'],
    [() => { throw new Error('the agent registry is down'); }, 'mandate-not-for-this-call']];
  for (const [identifyAgent, want] of cases) {
    const h = await fakeHub(t);
    const [got, covered] = await h.runOne(body(JSON.stringify(mandate())), { identifyAgent });
    assert.notEqual(got, null);
    assert.equal(covered.ok ? 'ok' : covered.data.detail, want, String(identifyAgent));
  }
  assert.equal(heard[0].project, OTHER_PROJECT);
  assert.deepEqual([heard[0].principal.kind, heard[0].principal.provenance], ['agent', 'trusted']);
  const asked = [];
  const h = await fakeHub(t);
  const [none] = await h.runOne(body('{"frames": 24}'), { identifyAgent: (sender) => { asked.push(sender); return 'lead-agent'; } });
  assert.equal(none, null);
  assert.deepEqual(asked, [], 'asked only when a mandate travelled');
  assert.throws(() => new fb.Responder(h.options({ identifyAgent: 'lead-agent' })), (e) => e.code === 'invalid_arguments');
});

// FAA-196 (1): the resume path (a transferred request run again from a fresh com.get) reads the mandate as the first
// path does, and none from a message read back under another digest or address, said by its code alone.
async function resumed(t, tamper) {
  const h = await fakeHub(t);
  const { request } = await h.control({ op: 'queue', capability: 'video.render', text: body(JSON.stringify(mandate())), provenance: 'trusted' });
  await new fb.Responder(h.options({ handler: () => new Promise(() => {}) })).step(); // dies inside the work
  await h.control({ op: 'end-sessions' });
  const second = new fb.Responder(h.options());
  if (tamper) {
    const call = second.call.bind(second);
    second.call = async (tool, args) => {
      const answer = await call(tool, args);
      if (tool === 'com.get') tamper(answer);
      return answer;
    };
  }
  await second.step();
  assert.equal(h.seen.length, 1, 'the handler ran again on the resume path');
  assert.ok(request);
  return { h, got: h.seen[0] };
}

test('FAA-196 (1): a resumed request reads its mandate as the first path does', async (t) => {
  const { h, got: [m, covered] } = await resumed(t);
  assert.deepEqual(m, mandate());
  assert.equal(covered.ok, true);
  assert.deepEqual(h.events.filter((e) => e[0] === 'board.request.mandate_unread'), []);
});

test('FAA-196 (1): a resumed request read back under another digest or address carries no mandate', async (t) => {
  for (const [tamper, reason] of [[(a) => { a.digest = `sha256:${'0'.repeat(64)}`; }, 'digest-mismatch'],
    [(a) => { a.request = { ...a.request, capability: 'video.cut' }; }, 'not-addressed']]) {
    const { h, got: [m, covered] } = await resumed(t, tamper);
    assert.equal(m, null);
    assert.equal(covered, null);
    assert.deepEqual(h.events.filter((e) => e[0] === 'board.request.mandate_unread').map((e) => e[3].data.value.reason), [reason]);
  }
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
    const said = h.events.filter((e) => e[0] === 'board.request.mandate_unread');
    assert.equal(said.length, 1);
    assert.ok(said[0][2].includes(code));
    assert.deepEqual(said[0][3].data.value, { request: h.seen.request, reason: code }, 'the data survives FAC-SEM-101: its reason is under `reason`');
    assert.ok(!JSON.stringify(h.events.map((e) => e.slice(2))).includes(WORDS), 'the operator\'s words reach no event');
  });
}

for (const order of ['after', 'before']) {
  test(`FAA-135: a broken block ${order} a mandate cancels nothing`, async (t) => {
    const h = await fakeHub(t);
    const m = mandate();
    const blocks = order === 'after' ? [JSON.stringify(m), '{"frames": '] : ['{"frames": ', JSON.stringify(m)];
    const [got, covered] = await h.runOne(body(...blocks));
    assert.deepEqual(got, m);
    assert.equal(covered.ok, true);
    assert.deepEqual(h.events.filter((e) => e[0] === 'board.request.mandate_unread'), []);
  });
}

test('FAA-135: a JSON block that is no mandate is ignored', async (t) => {
  const h = await fakeHub(t);
  const [got] = await h.runOne(body('{"frames": 24}'));
  assert.equal(got, null);
  assert.deepEqual(h.events.filter((e) => e[0] === 'board.request.mandate_unread'), []);
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

test('FAA-135: the warning is a kind the event feed takes (0.61.0 seam reading 1)', async (t) => {
  const h = await fakeHub(t);
  await h.runOne(body(JSON.stringify(mandate()), JSON.stringify(mandate())));
  const said = h.events.find((e) => e[0] === 'board.request.mandate_unread');
  assert.doesNotThrow(() => makeEvent(1, AT, said[0], said[1], said[2], { data: said[3].data }));
});

test('FAA-135: a declared Project matches in any case; a read mandate reaches no context JSON', async (t) => {
  const h = await fakeHub(t);
  const [, covered] = await h.runOne(body(JSON.stringify(mandate())), { mandateFrom: new Set([OTHER_PROJECT.toUpperCase()]) });
  assert.equal(covered.ok, true);
  assert.ok(!h.seen.ctx.includes(WORDS), 'JSON.stringify(ctx) never carries the operator\'s words');
});

for (const [name, text] of [['an opener mid-line', (m) => `Here it is: \`\`\`json\n${m}\n\`\`\`\n`],
  ['a four-backtick fence', (m) => `\`\`\`\`json\n${m}\n\`\`\`\`\n`], ['a closer on the content line', (m) => `\`\`\`json\n${m}\`\`\`\n`],
  ['text after the closer', (m) => `\`\`\`json\n${m}\n\`\`\`x\n`], ['a lone CR before the opener', (m) => `x\r\`\`\`json\n${m}\n\`\`\`\n`],
  ['U+2028 before the opener', (m) => `x\u2028\`\`\`json\n${m}\n\`\`\`\n`], ['U+2029 after the closer', (m) => `\`\`\`json\n${m}\n\`\`\`\u2029\n`],
  ['an opener with a suffix', (m) => `\`\`\`jsonc\n${m}\n\`\`\`\n`], ['an opener with a word after it', (m) => `\`\`\`json x\n${m}\n\`\`\`\n`],
  ['an indented fence', (m) => `  \`\`\`json\n${m}\n  \`\`\`\n`], ['a tab before the opener', (m) => `\t\`\`\`json\n${m}\n\`\`\`\n`],
  ['an upper-case tag', (m) => `\`\`\`JSON\n${m}\n\`\`\`\n`], ['a tilde fence', (m) => `~~~json\n${m}\n~~~\n`],
  ['a fence inside a list item', (m) => `- the mandate:\n  \`\`\`json\n  ${m}\n  \`\`\`\n`]]) {
  test(`FAA-135: ${name} is no mandate block (0.61.0 readings 2)`, () => {
    const request = new BoardRequest({ body: { text: text(JSON.stringify(mandate())) }, request: { id: 'r' },
      sender: { project: OTHER_PROJECT, principal: { provenance: 'trusted' } } }, 'video.render');
    assert.equal(readMandate(request, mandateOptions('example-agent', new Set([OTHER_PROJECT])), 'example-agent').mandate, null);
  });
}

test('FAA-135: a uuid matches in any case, any other id as written', () => {
  const request = new BoardRequest({ body: { text: body(JSON.stringify(mandate())) }, request: { id: 'r' },
    sender: { project: OTHER_PROJECT.toUpperCase(), principal: { provenance: 'trusted' } } }, 'video.render');
  assert.notEqual(readMandate(request, mandateOptions('example-agent', new Set([OTHER_PROJECT])), 'example-agent').mandate, null);
  request.sender = { project: 'team-a', principal: { provenance: 'trusted' } };
  assert.equal(readMandate(request, mandateOptions('example-agent', new Set(['Team-A'])), 'example-agent').mandate, null);
  assert.notEqual(readMandate(request, mandateOptions('example-agent', new Set(['team-a'])), 'example-agent').mandate, null);
});

test('FAA-135: a spend or project that does not read is refused (FAA-139; 0.61.0 seam reading 14)', () => {
  const m = handOn(operatorMandate({ task: 'task-teaser', instruction: WORDS, lead: 'lead-agent', at: AT,
    scope: { capabilities: ['video.render'], effects: ['draft'], perCallMaxUsd: 5, projects: ['site-a'] } }), 'example-agent', AT);
  const detail = (call) => {
    const got = covers(m, { capability: 'video.render', effect: 'draft', ...call }, 'example-agent', () => WALL, OTHER_PROJECT);
    return got.ok ? 'ok' : got.data.detail;
  };
  assert.equal(detail({ spendUsd: 3, project: 'site-a' }), 'ok');
  for (const spendUsd of [null, NaN, Infinity, '3', true, [1], 10n, 50]) {
    assert.equal(detail({ spendUsd, project: 'site-a' }), 'outside-mandate: spend', String(spendUsd));
  }
  for (const project of [5, ['site-a'], {}, null]) assert.equal(detail({ spendUsd: 3, project }), 'outside-mandate: project', String(project));
  assert.equal(detail({ spendUsd: 3 }), 'ok', 'a call that names no project leaves `project` out');
  assert.equal(detail({ spendUsd: 3, project: undefined }), 'ok', 'an own undefined is no member, as member() reads');
  const direct = (call) => {
    const got = covers(m, call, 'example-agent', () => WALL, OTHER_PROJECT);
    return got.ok ? 'ok' : got.data.detail;
  };
  assert.equal(direct(Object.assign(Object.create({ spendUsd: 3 }), { capability: 'video.render', effect: 'draft', project: 'site-a' })),
    'outside-mandate: spend', 'an inherited spend is not read, as member() reads');
  class Call {
    constructor() { Object.assign(this, { capability: 'video.render', effect: 'draft', spendUsd: 3 }); }
    get project() { return 'site-b'; }
  }
  assert.equal(direct(new Call()), 'outside-mandate: project', 'a project from a getter is read, as the contract reads it');
  assert.equal(direct(Object.assign(Object.create({ project: 'site-b' }), { capability: 'video.render', effect: 'draft', spendUsd: 3 })),
    'outside-mandate: project', 'an inherited project is read');
  const acts = handOn(operatorMandate({ task: 'task-teaser', instruction: WORDS, lead: 'lead-agent', at: AT,
    scope: { actions: ['approve'], effects: ['draft'] } }), 'example-agent', AT);
  const act = (call) => {
    const got = covers(acts, call, 'example-agent', () => WALL, OTHER_PROJECT);
    return got.ok ? 'ok' : got.data.detail;
  };
  assert.equal(act({ action: 'approve', effect: 'draft' }), 'ok');
  class Act { constructor() { this.effect = 'draft'; } get action() { return 'other'; } }
  const hidden = { effect: 'draft' };
  Object.defineProperty(hidden, 'action', { value: 'other', enumerable: false });
  for (const [name, call] of [['a getter', new Act()], ['an inherited', Object.assign(Object.create({ action: 'other' }), { effect: 'draft' })],
    ['a non-enumerable', hidden]]) {
    assert.equal(act(call), 'outside-mandate: action', `${name} action is read`);
  }
  // A Proxy is read as the contract reads it, through get alone (0.61.0 seam reading 17).
  const defaults = (target, extra) => new Proxy(target, { get: (o, k) => (k in o ? o[k] : extra[k]) });
  assert.equal(direct(defaults({ capability: 'video.render', effect: 'draft', spendUsd: 3 }, { project: 'site-b' })), 'outside-mandate: project');
  assert.equal(act(defaults({ effect: 'draft' }, { action: 'other' })), 'outside-mandate: action');
  const hiding = new Proxy({ capability: 'video.render', effect: 'draft', spendUsd: 3, project: 'site-b' }, { has: (o, k) => k !== 'project' });
  assert.equal(direct(hiding), 'outside-mandate: project');
  const unrelated = { capability: 'video.render', effect: 'draft', spendUsd: 3, project: 'site-a', get note() { throw new Error('never read'); } };
  assert.equal(direct(unrelated), 'ok', 'a member mandateCovers does not read is never touched');
  const counts = {};
  const countedCall = {};
  for (const [key, value] of Object.entries({ capability: 'video.render', action: 'a', effect: 'draft', spendUsd: 3, project: 'site-a' })) {
    Object.defineProperty(countedCall, key, { enumerable: true, get: () => { counts[key] = (counts[key] ?? 0) + 1; return value; } });
  }
  direct(countedCall);
  assert.deepEqual(counts, { capability: 1, action: 1, effect: 1, spendUsd: 1, project: 1 }, 'each member read once');
  let reads = 0;
  const counted = { capability: 'video.render', effect: 'draft', project: 'site-a', get spendUsd() { reads += 1; return 3; } };
  assert.equal(direct(counted), 'ok');
  assert.equal(reads, 1, 'the spend is read once');
  const call = { capability: 'video.render', effect: 'draft', spendUsd: NaN, project: 5 };
  const kept = { ...call };
  covers(m, call, 'example-agent', () => WALL, OTHER_PROJECT);
  assert.deepEqual(call, kept, "covers reads the handler's call, never changes it");
});

test('FAA-135: a clock that does not read answers now-unreadable', () => {
  for (const clock of [NaN, null, Infinity, 1e18, -1e18, 1e300, true, '1762300800000']) {
    assert.deepEqual(covers(mandate(), { capability: 'video.render', effect: 'draft' }, 'example-agent', () => clock), { fault: 'now-unreadable' });
  }
});

test('FAA-135: a sender without a project is never read, even on the personal board', () => {
  for (const sender of [{ principal: { provenance: 'trusted' } }, { project: 42, principal: { provenance: 'trusted' } }, { project: '', principal: { provenance: 'trusted' } }]) {
    const request = new BoardRequest({ body: { text: body(JSON.stringify(mandate())) }, request: { id: 'r' }, sender }, 'video.render');
    assert.deepEqual(readMandate(request, _PB, 'example-agent'), { mandate: null, unread: null });
  }
});

test('FAA-135: a closing fence may carry trailing spaces', () => {
  const request = new BoardRequest({ body: { text: `\`\`\`json  \n${JSON.stringify(mandate())}\n\`\`\`  \t\n` }, request: { id: 'r' },
    sender: { project: OTHER_PROJECT, principal: { provenance: 'trusted' } } }, 'video.render');
  assert.notEqual(readMandate(request, _PB, 'example-agent').mandate, null);
});

test('FAA-135: reading is linear in the body (0.61.0 readings 3)', () => {
  const cost = (size, shape) => {
    const text = shape === 'unclosed' ? '```json\n```x\n'.repeat(size).slice(0, size) : `${'```json\n'.repeat(size / 8)}\`\`\`\n`;
    const request = new BoardRequest({ body: { text }, request: { id: 'r' },
      sender: { project: OTHER_PROJECT, principal: { provenance: 'trusted' } } }, 'video.render');
    let best = Infinity;
    for (let k = 0; k < 5; k += 1) { // CPU time, never the wall clock, so a loaded machine cannot break the ratio (FAA-196 (23))
      const start = process.cpuUsage();
      readMandate(request, _PB, 'example-agent');
      const used = process.cpuUsage(start);
      best = Math.min(best, (used.user + used.system) / 1000);
    }
    return best;
  };
  for (const shape of ['unclosed', 'nested']) { // nested: every inner opener closed by the same fence (unit reading 4)
    const small = cost(65536, shape);
    const large = cost(4 * 65536, shape);
    assert.ok(large / Math.max(small, 0.001) < 10, `${shape}: linear is about 4, quadratic about 16 (${small} ms, ${large} ms)`);
  }
});

test('FAA-135: util.inspect of a context or a request prints no mandate and no body', () => {
  const ctx = new fb.WorkContext({}, {}, mandate(), OTHER_PROJECT);
  assert.ok(!util.inspect(ctx).includes(WORDS));
  const request = new BoardRequest({ body: { text: WORDS }, request: { id: 'r' } }, 'video.render');
  assert.ok(!util.inspect(request).includes(WORDS));
});

test('FAA-135: the operator\'s words reach no checkpoint during the work', async (t) => {
  const h = await fakeHub(t);
  const [got] = await h.runOne(body(JSON.stringify(mandate())));
  assert.notEqual(got, null, 'a mandate was read');
  assert.ok(h.seen.checkpoint, 'the request\'s entry is in the checkpoint while it is worked');
  assert.ok(!h.seen.checkpoint.includes(WORDS));
});
