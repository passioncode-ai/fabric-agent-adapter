// fabric-ops-digest.mjs (FAA-206 part 2), the twin of test_fabric_ops_digest.py: the contract's reference folds on its
// vectors, FAC-SEM-166 and FAC-SEM-167 on its fixtures, and the files OpsDigest keeps (an hour written when it closes,
// the stop hour kept for the next run, no hour filled across a sleep, each closed day folded once, files 0600).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  OPS_DIGEST_EXTENSION, OpsDigest, OpsDigestError, foldDay, foldHour, hasHomePath, isRise, opsDigestExtension, opsDigestRules,
  outcomeOf, readDigests,
} from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-ops-digest.mjs';

const VECTORS = JSON.parse(fs.readFileSync(new URL('./fixtures/ops-digest/vectors.json', import.meta.url), 'utf8'));
const SAMPLE_KEY = 'sk-proj-' + 'Ab12Cd34Ef56Gh78Ij90'; // a provider-key shape, built here so no file holds one
const RULES = JSON.parse(fs.readFileSync(new URL('./fixtures/ops-digest/rules.json', import.meta.url), 'utf8').replaceAll('@SK@', SAMPLE_KEY));
const H = 3_600_000;
const T0 = Date.UTC(2026, 10, 5);
const made = [];
const tmp = () => { const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ops-digest-')); made.push(root); return path.join(root, 'digests'); };
test.after(() => { for (const root of made) fs.rmSync(root, { recursive: true, force: true }); });
const lines = (folder, name) => {
  const file = path.join(folder, name);
  return fs.existsSync(file) ? fs.readFileSync(file, 'utf8').split('\n').filter(Boolean).map((x) => JSON.parse(x)) : [];
};

test('the hour vectors', () => {
  assert.equal(VECTORS.hour.length, 11);
  for (const v of VECTORS.hour) assert.deepEqual(foldHour(v.input.counts, v.input.from, v.input.previous), v.expected, v.name);
});

test('the day vectors', () => {
  assert.equal(VECTORS.day.length, 4);
  for (const v of VECTORS.day) assert.deepEqual(foldDay(v.input.day, v.input.hourly), v.expected, v.name);
});

test('a refused name writes no hour and never names the value', () => {
  for (const op of [SAMPLE_KEY, 'users/jdoe/x', 'Board.tick', 'a..b', 'x'.repeat(65)]) {
    assert.throws(() => foldHour([{ op, ok: 1, failed: 0, unknown: 0 }], '2026-11-04T17:00:00Z', null),
      (e) => e instanceof OpsDigestError && !e.message.includes(SAMPLE_KEY));
  }
});

test('bad inputs throw as the reference does', () => {
  assert.throws(() => foldHour([], '2026-02-30T00:00:00Z', null), OpsDigestError);
  assert.throws(() => foldHour([], '9999-12-31T23:00:00Z', null), OpsDigestError);
  assert.throws(() => foldHour([{ op: 'a', ok: -1, failed: 0, unknown: 0 }], '2026-11-04T17:00:00Z', null), OpsDigestError);
  assert.throws(() => foldHour([{ op: 'a', ok: true, failed: 0, unknown: 0 }], '2026-11-04T17:00:00Z', null), OpsDigestError);
  assert.throws(() => foldHour(Array(2).fill({ op: 'a', ok: 2 ** 53 - 1, failed: 0, unknown: 0 }), '2026-11-04T17:00:00Z', null), OpsDigestError);
  assert.throws(() => foldDay('2026-13-01', []), OpsDigestError);
  assert.equal(foldDay('2026-11-04', []), null);
});

test('the home detector reads as the contract', () => {
  for (const v of ['api.users/list', 'api.get_users/list', 'api.my_users/list', 'ui.home/open', 'x.-Users-a', '~/x', 'a ~b/c']) assert.equal(hasHomePath(v), true, v);
  for (const v of ['api.user/list', 'api.get_user/list', 'my-users-list', 'user-digests', 'a/~1/x']) assert.equal(hasHomePath(v), false, v);
});

test('rises', () => {
  assert.ok(isRise(10, 0) && isRise(10, 5));
  assert.ok(!isRise(10, 6) && !isRise(9, 0));
});

test('the contract fixtures', () => {
  assert.equal(RULES.fixtures.length, 17);
  for (const f of RULES.fixtures) {
    const findings = opsDigestRules(f.kind, f.input);
    assert.deepEqual([...new Set(findings.map((x) => x.code))].sort(), [...new Set(f.expect)].sort(), f.name);
    for (const x of findings) assert.ok(!x.message.includes(SAMPLE_KEY));
  }
  assert.equal(opsDigestRules('service-descriptor', {}), undefined);
});

test('an hour is written when it closes, an observed empty hour too', () => {
  const folder = tmp();
  const d = new OpsDigest(folder);
  d.start(T0 + 60000);
  for (let i = 0; i < 12; i += 1) d.record('board.tick', 'failed', T0 + 120000);
  d.record('board.tick', 'ok', T0 + 130000);
  d.record('mcp.tools/list', 'refused', T0 + 140000);
  assert.deepEqual(lines(folder, 'hourly-2026-11.jsonl'), []);
  d.tick(T0 + H + 5);
  d.tick(T0 + 2 * H + 5);
  const hours = lines(folder, 'hourly-2026-11.jsonl');
  assert.deepEqual(hours.map((h) => h.from), ['2026-11-05T00:00:00.000Z', '2026-11-05T01:00:00.000Z']);
  assert.deepEqual(hours[0].ops, [{ op: 'board.tick', ok: 1, failed: 12, unknown: 0 }, { op: 'mcp.tools/list', ok: 0, failed: 0, unknown: 1 }]);
  assert.deepEqual(hours[0].risen, [{ op: 'board.tick', failed: 12, previous: 0 }]);
  assert.deepEqual(hours[1].ops, []);
  for (const h of hours) assert.deepEqual(opsDigestRules('ops-digest-hourly', h), []);
});

test('no hour is filled across a sleep', () => {
  const folder = tmp();
  const d = new OpsDigest(folder);
  d.start(T0);
  d.record('a', 'ok', T0 + 1);
  d.record('a', 'ok', T0 + 5 * H + 1);
  d.tick(T0 + 6 * H);
  assert.deepEqual(lines(folder, 'hourly-2026-11.jsonl').map((h) => h.from.slice(11, 13)), ['00', '05']);
});

test('the stop hour is kept and written at the next run against the hour before', () => {
  const folder = tmp();
  const d = new OpsDigest(folder);
  d.start(T0);
  for (let i = 0; i < 4; i += 1) d.record('job.run', 'failed', T0 + 10);
  d.tick(T0 + H + 10);
  for (let i = 0; i < 20; i += 1) d.record('job.run', 'failed', T0 + H + 20);
  d.stop(T0 + H + 30);
  assert.equal(lines(folder, 'hourly-2026-11.jsonl').length, 1);
  const again = new OpsDigest(folder);
  assert.equal(again.start(T0 + 3 * H).hours, 1);
  const hours = lines(folder, 'hourly-2026-11.jsonl');
  assert.equal(hours[1].from, '2026-11-05T01:00:00.000Z');
  assert.deepEqual(hours[1].risen, [{ op: 'job.run', failed: 20, previous: 4 }]);
  assert.equal(fs.existsSync(path.join(folder, 'kept-hour.json')), false);
});

test('a restart in the same hour resumes it and never writes two lines', () => {
  const folder = tmp();
  const d = new OpsDigest(folder);
  d.start(T0);
  d.record('a', 'ok', T0 + 1);
  d.stop(T0 + 2);
  const again = new OpsDigest(folder);
  again.start(T0 + 3);
  again.record('a', 'ok', T0 + 4);
  again.tick(T0 + H + 1);
  const hours = lines(folder, 'hourly-2026-11.jsonl');
  assert.equal(hours.length, 1);
  assert.deepEqual(hours[0].ops, [{ op: 'a', ok: 2, failed: 0, unknown: 0 }]);
});

test('each closed day is folded once, a missed day at the next run', () => {
  const folder = tmp();
  const d = new OpsDigest(folder);
  d.start(T0 + 22 * H);
  d.record('a', 'ok', T0 + 22 * H);
  d.record('a', 'failed', T0 + 23 * H);
  d.stop(T0 + 23 * H + 1);
  assert.deepEqual(lines(folder, 'daily-2026-11.jsonl'), []);
  const again = new OpsDigest(folder);
  assert.deepEqual(again.start(T0 + 50 * H), { hours: 1, days: 1 });
  again.flush(T0 + 51 * H);
  const days = lines(folder, 'daily-2026-11.jsonl');
  assert.equal(days.length, 1);
  assert.equal(days[0].day, '2026-11-05');
  assert.equal(days[0].hours, 2);
  assert.deepEqual(days[0].total, { ok: 1, failed: 1, unknown: 0 });
  assert.deepEqual(opsDigestRules('ops-digest-daily', days[0]), []);
});

test('files are 0600 in a 0700 folder', { skip: process.platform === 'win32' && 'file modes are POSIX; Windows keeps the folder ACL' }, () => {
  const folder = tmp();
  const d = new OpsDigest(folder);
  d.start(T0);
  d.tick(T0 + H);
  assert.equal(fs.statSync(folder).mode & 0o777, 0o700);
  assert.equal(fs.statSync(path.join(folder, 'hourly-2026-11.jsonl')).mode & 0o777, 0o600);
});

test('a refused name is refused at record and the day caps at 4095 names', () => {
  const folder = tmp();
  const d = new OpsDigest(folder);
  d.start(T0);
  assert.throws(() => d.record(SAMPLE_KEY, 'ok', T0), (e) => e instanceof OpsDigestError && !e.message.includes(SAMPLE_KEY));
  for (let i = 0; i < 4100; i += 1) d.record(`op.n${i}`, 'ok', T0);
  d.tick(T0 + H);
  const ops = lines(folder, 'hourly-2026-11.jsonl')[0].ops;
  assert.equal(ops.length, 4096);
  assert.ok(ops.some((c) => c.op === 'ops.overflow' && c.ok === 5));
});

test('a reader skips bad lines and keeps the first of an hour', () => {
  const folder = tmp();
  fs.mkdirSync(folder, { recursive: true });
  const good = foldHour([{ op: 'a', ok: 1, failed: 0, unknown: 0 }], '2026-11-05T00:00:00Z', null);
  const second = foldHour([{ op: 'a', ok: 9, failed: 0, unknown: 0 }], '2026-11-05T00:00:00Z', null);
  fs.writeFileSync(path.join(folder, 'hourly-2026-11.jsonl'), `not json\n${JSON.stringify({ ...good, extra: 1 })}\n${JSON.stringify(good)}\n${JSON.stringify(second)}\n`);
  assert.deepEqual(readDigests(folder, 'hourly'), [good]);
  assert.throws(() => new OpsDigest(tmp()).record('a', 'ok', T0), OpsDigestError);
});

test('the declaration and its refusals; outcome words', () => {
  assert.deepEqual(opsDigestExtension(), { [OPS_DIGEST_EXTENSION]: [{ dir: 'digests', source: 'app' }] });
  for (const bad of [[], [{ dir: '/abs', source: 'app' }], [{ dir: 'users/alice', source: 'app' }], [{ dir: 'a/../b', source: 'app' }],
    [{ dir: 'a', source: 'App' }], [{ dir: 'a', source: 'app' }, { dir: 'A', source: 'web' }],
    [{ dir: 'ApplicationSupport/MyProduct/Digests2026', source: 'app' }]]) {
    assert.throws(() => opsDigestExtension(bad), OpsDigestError, JSON.stringify(bad));
  }
  assert.deepEqual(['ok', 'failed', 'timeout', 'denied', 'skip', 3].map((w) => outcomeOf(w, { denied: 'unknown', timeout: 'failed' })),
    ['ok', 'failed', 'failed', 'unknown', 'unknown', 'unknown']);
});
