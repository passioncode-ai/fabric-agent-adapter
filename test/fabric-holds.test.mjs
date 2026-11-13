// FAA-298: work a service holds by its own limits, in the Node kit; the twin of test_fabric_holds.py, held to the same
// vectors (test/fixtures/holds/waiting-vectors.json).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as h from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-holds.mjs';
import { JobStore, jobCallerAction } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-interop.mjs';
import { operatorDecision } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-actions.mjs';
import { makeEvent } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-events.mjs';
import { ServiceError } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-base.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const V = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/holds/waiting-vectors.json'), 'utf8'));
const NOW = '2026-11-12T09:00:00Z';
const decision = (words = 'raise it to 150 for today') => operatorDecision({ action: 'limit.lift', instruction: words, at: '2026-11-12T09:05:00Z' });

function book(withLog = true) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'holds-'));
  const log = [];
  const b = new h.HoldBook(path.join(dir, 'holds.json'), withLog ? { events: (e) => { log.push(e); return e; } } : {});
  return { b, log, dir, done: () => fs.rmSync(dir, { recursive: true, force: true }) };
}

test('the vectors write, refuse and read as in Python', () => {
  for (const { input: i, statusMessage } of V.write) assert.equal(h.waitingMessage(i.reason, i.since, i.until, i.message), statusMessage);
  for (const c of V.refuse) assert.throws(() => h.waitingMessage(c.reason, c.since, c.until, c.message), ServiceError);
  for (const c of V.read) assert.deepEqual(h.readWaiting(c.answer), c.waiting);
});

test('a hold is a pause every caller reads as wait', () => {
  const answer = { job: { id: 'j', status: 'working', statusMessage: h.waitingMessage('daily-quota', NOW, '2026-11-13T00:00:00Z', 'renders') } };
  assert.deepEqual(jobCallerAction(answer, NOW), { action: 'wait', notBefore: '2026-11-13T00:00:00Z' });
  const long = h.waitingMessage('money', NOW, '2026-11-13T00:00:00Z', 'x '.repeat(400));
  assert.ok([...long].length <= 500 && long.endsWith('...'));
});

test('holdJob puts a JobStore job on hold', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'holds-jobs-'));
  try {
    const store = new JobStore(dir);
    const { job } = store.create('example.render', { scene: 1 });
    h.holdJob(store, job.id, 'daily-quota', NOW, '2099-01-01T00:00:00Z', '100 of 100');
    const got = store.get(job.id);
    assert.equal(got.status, 'working');
    assert.deepEqual(h.readWaiting({ job: got }), { reason: 'daily-quota', since: NOW, until: '2099-01-01T00:00:00Z', message: '100 of 100' });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('a held job emits exactly one push naming caller, work, reason and when it frees', () => {
  const { b, log, done } = book();
  try {
    const first = b.hold({ caller: 'example-caller', work: 'the launch video', reason: 'daily-quota', until: '2026-11-13T00:00:00Z', jobId: 'j1', now: NOW });
    assert.ok(first.push);
    for (let n = 2; n < 5; n += 1) {
      assert.equal(b.hold({ caller: 'example-caller', work: 'the launch video', reason: 'daily-quota', until: '2026-11-13T00:00:00Z', jobId: `j${n}`, now: `2026-11-12T09:0${n}:00Z` }).push, null);
    }
    const pushes = log.filter((e) => e.kind === h.HOLD_EVENT_KIND);
    assert.equal(pushes.length, 1);
    assert.equal(pushes[0].notify, true);
    assert.equal(pushes[0].level, 'notice');
    for (const words of ['example-caller', 'the launch video', 'the daily quota', '2026-11-13T00:00:00Z', 'Raise the limit']) assert.ok(pushes[0].text.includes(words));
    makeEvent('1', NOW, pushes[0].kind, pushes[0].level, pushes[0].text, { subject: pushes[0].subject, notify: true });
    assert.deepEqual(b.openHolds(NOW)[0].jobs, ['j1', 'j2', 'j3', 'j4']);
  } finally { done(); }
});

test('a freed, expired or other hold pushes again; a credential is refused', () => {
  const { b, log, done } = book();
  try {
    b.hold({ caller: 'a', work: 'w', reason: 'daily-quota', until: '2026-11-12T10:00:00Z', now: NOW });
    b.hold({ caller: 'a', work: 'w', reason: 'daily-quota', until: '2026-11-13T00:00:00Z', now: '2026-11-12T11:00:00Z' });
    b.hold({ caller: 'a', work: 'w', reason: 'money', now: NOW });
    assert.ok(b.release({ reason: 'money', caller: 'a', now: NOW }));
    b.hold({ caller: 'a', work: 'w', reason: 'money', now: NOW });
    b.hold({ caller: 'b', work: 'w', reason: 'money', now: NOW });
    assert.equal(log.filter((e) => e.kind === h.HOLD_EVENT_KIND).length, 5);
    assert.throws(() => b.hold({ caller: `sk-or-v1-${'a1B2'.repeat(12)}`, work: 'w', reason: 'money', now: NOW }), ServiceError);
    assert.throws(() => b.hold({ caller: 'a', work: 'w', reason: 'rate', now: NOW }), ServiceError);
    // U+FEFF alone is whitespace in both twins; U+0085 is not (FAA-316).
    assert.throws(() => b.hold({ caller: '\ufeff', work: 'w', reason: 'money', now: NOW }), ServiceError);
    assert.ok(b.hold({ caller: '\u0085', work: 'w', reason: 'money', now: NOW }));
  } finally { done(); }
});

test('without an event log the push is returned', () => {
  const { b, done } = book(false);
  try {
    const { push } = b.hold({ caller: 'a', work: 'w', reason: 'concurrency', now: NOW });
    assert.deepEqual([push.kind, push.level, push.notify], [h.HOLD_EVENT_KIND, 'notice', true]);
    assert.ok(push.text.includes('frees by itself when a running job ends'));
  } finally { done(); }
});

test('a lift for N jobs admits N, then the limit returns', () => {
  const { b, done } = book();
  try {
    b.hold({ caller: 'a', work: 'w', reason: 'daily-quota', jobId: 'j1', now: NOW });
    const lift = b.lift({ reason: 'daily-quota', caller: 'a', jobs: 3, decision: decision('three more for a'), now: NOW });
    assert.equal(lift.decision.instruction, 'three more for a');
    assert.deepEqual(b.openHolds(NOW), []);
    const got = [0, 1, 2, 3].map(() => b.admit({ reason: 'daily-quota', caller: 'a', now: NOW }).admitted);
    assert.deepEqual(got, [true, true, true, false]);
    assert.equal(b.admit({ reason: 'daily-quota', caller: 'b', now: NOW }).admitted, false);
    assert.equal(b.lifts(NOW)[0].live, false);
  } finally { done(); }
});

test('a raised limit for today falls back when the window ends; money and one order', () => {
  const { b, done } = book();
  try {
    b.lift({ reason: 'daily-quota', limit: 150, until: '2026-11-13T00:00:00Z', decision: decision(), now: NOW });
    assert.equal(b.limit({ reason: 'daily-quota', base: 100, caller: 'a', now: '2026-11-12T23:59:59Z' }), 150);
    assert.equal(b.limit({ reason: 'daily-quota', base: 100, caller: 'a', now: '2026-11-13T00:00:00Z' }), 100);
    b.lift({ reason: 'money', usd: 5, caller: 'a', decision: decision('five dollars more'), now: NOW });
    assert.equal(b.admit({ reason: 'money', caller: 'a', costUsd: 3.5, now: NOW }).admitted, true);
    assert.equal(b.admit({ reason: 'money', caller: 'a', costUsd: 2, now: NOW }).admitted, false);
    assert.equal(b.admit({ reason: 'money', caller: 'a', costUsd: 1.5, now: NOW }).admitted, true);
    b.lift({ reason: 'concurrency', jobId: 'j9', jobs: 1, decision: decision('run this order'), now: NOW });
    assert.equal(b.admit({ reason: 'concurrency', caller: 'a', jobId: 'j8', now: NOW }).admitted, false);
    assert.equal(b.admit({ reason: 'concurrency', caller: 'a', jobId: 'j9', now: NOW }).admitted, true);
    b.lift({ reason: 'caller-share', jobs: 2, until: '2026-11-13T00:00:00Z', decision: decision(), now: NOW });
    assert.equal(b.admit({ reason: 'caller-share', caller: 'a', now: '2026-11-13T00:00:01Z' }).admitted, false);
  } finally { done(); }
});

test('a lift needs the operator\'s decision and one size', () => {
  const { b, done } = book();
  try {
    assert.throws(() => b.lift({ reason: 'money', usd: 5, decision: { by: 'agent' }, now: NOW }), ServiceError);
    assert.throws(() => b.lift({ reason: 'money', usd: 5, decision: operatorDecision({ action: 'job.approve', instruction: 'yes', at: NOW }), now: NOW }), ServiceError);
    assert.throws(() => b.lift({ reason: 'money', usd: 5, jobs: 1, decision: decision(), now: NOW }), ServiceError);
    assert.throws(() => b.lift({ reason: 'daily-quota', limit: 150, decision: decision(), now: NOW }), ServiceError);
    assert.throws(() => b.lift({ reason: 'daily-quota', jobs: 1.5, decision: decision(), now: NOW }), ServiceError);
  } finally { done(); }
});

// FAA-320: a book 0.81.0's Python twin wrote is read under both squashes; a new record under the ECMAScript one.
const LEGACY = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/holds/legacy-squash-vectors.json'), 'utf8'));
const camel = (args) => Object.fromEntries(Object.entries(args).map(([k, v]) => [k.replace(/_(.)/g, (_, c) => c.toUpperCase()), v]));

test('a 0.81.0 Python hold book is read under both squashes, as in Python', () => {
  for (const c of LEGACY.cases) {
    const { b, done } = book(false);
    try {
      fs.writeFileSync(b.file, JSON.stringify(LEGACY.book));
      const args = camel(c.args);
      if (c.call === 'hold') {
        const out = b.hold({ ...args, now: NOW });
        assert.equal(out.hold.id, c.joins);
        assert.equal(out.push, null);
      } else if (c.call === 'release') {
        const out = b.release({ ...args, now: NOW });
        assert.equal(out === null ? null : out.id, c.closes);
      } else if (c.call === 'admit') {
        assert.equal(b.admit({ ...args, now: NOW }).lift, c.lift);
      } else {
        b.lift({ ...args, decision: decision(), now: NOW });
        const lifted = JSON.parse(fs.readFileSync(b.file, 'utf8')).holds.filter((x) => x.closed === 'lifted').map((x) => x.id);
        assert.deepEqual(lifted, c.lifts);
      }
    } finally { done(); }
  }
});

test('a new hold record carries its squash', () => {
  const { b, done } = book(false);
  try {
    fs.writeFileSync(b.file, JSON.stringify(LEGACY.book));
    const out = b.hold({ caller: 'third\u001ccaller', work: 'render', reason: 'money', now: NOW });
    assert.equal(out.hold.squash, 'ecmascript');
    assert.equal(out.hold.caller, 'third\u001ccaller');
    assert.notEqual(b.hold({ caller: 'third caller', work: 'render', reason: 'money', now: NOW }).push, null);
  } finally { done(); }
});
