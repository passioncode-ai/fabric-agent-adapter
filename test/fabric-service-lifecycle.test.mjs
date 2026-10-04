// The lifecycle layer of the Node kit — the same rules as test_fabric_service_lifecycle.py,
// held to the organization's lifecycle contract (LC-01, LC-03, LC-11, LC-12, LC-15).
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const kit = path.join(here, '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs');

function withTemp(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-life-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

// --- LC-03 / F8: a held lock under KeepAlive backs off in-process -----------------------

test('by hand, a held lock still exits 75 at once', async (t) => {
  const dir = withTemp(t);
  const lock = await new k.InstanceLock(dir).acquire();
  t.after(() => lock.release());
  const started = Date.now();
  const child = spawnSync(process.execPath, ['--input-type=module', '-e',
    `import * as k from ${JSON.stringify(kit)}; await k.holdSingleInstance(${JSON.stringify(dir)}); console.log('ran');`],
  { encoding: 'utf8', env: { ...process.env, [k.SUPERVISOR_ENV]: '' } });
  assert.equal(child.status, 75);
  assert.ok(Date.now() - started < 5000);
});

test('a supervised copy takes over when the holder leaves', async (t) => {
  const dir = withTemp(t);
  const holder = await new k.InstanceLock(dir).acquire();
  const slept = [];
  const sleep = async (seconds) => {
    slept.push(seconds);
    if (slept.length === 3) holder.release();
  };
  const saved = process.env[k.SUPERVISOR_ENV];
  process.env[k.SUPERVISOR_ENV] = 'launchd';
  t.after(() => { if (saved === undefined) delete process.env[k.SUPERVISOR_ENV]; else process.env[k.SUPERVISOR_ENV] = saved; });
  const lock = await k.holdSingleInstance(dir, { sleep });
  assert.equal(slept.length, 3);
  lock.release();
});

test('a supervised copy backs off, capped, then exits 75', async (t) => {
  const dir = withTemp(t);
  const holder = await new k.InstanceLock(dir).acquire();
  t.after(() => holder.release());
  let now = 0;
  const slept = [];
  const exits = [];
  await k.holdSingleInstance(dir, {
    waitSeconds: k.LOCK_WAIT_SUPERVISED_SECONDS,
    sleep: async (s) => { slept.push(s); now += s; },
    clock: () => now,
    exit: (code) => { exits.push(code); },
  });
  assert.deepEqual(exits, [75]);
  assert.deepEqual(slept.slice(0, 3), [0.5, 1, 2]);
  assert.ok(Math.max(...slept) <= 30);
  assert.ok(Math.abs(slept.reduce((a, b) => a + b, 0) - k.LOCK_WAIT_SUPERVISED_SECONDS) < 0.01);
  assert.ok(3600 / (k.LOCK_WAIT_SUPERVISED_SECONDS + 10) < 15, 'a few starts an hour, not 360');
});

test('a real supervised process waits before its exit 75', async (t) => {
  const dir = withTemp(t);
  const holder = await new k.InstanceLock(dir).acquire();
  t.after(() => holder.release());
  const started = Date.now();
  const child = spawnSync(process.execPath, ['--input-type=module', '-e',
    `import * as k from ${JSON.stringify(kit)}; await k.holdSingleInstance(${JSON.stringify(dir)}, { waitSeconds: 1.5 });`],
  { encoding: 'utf8', env: { ...process.env, [k.SUPERVISOR_ENV]: 'launchd' } });
  assert.equal(child.status, 75);
  assert.ok(Date.now() - started >= 1400);
  assert.match(child.stderr, new RegExp(String(process.pid)));
});

// --- LC-12: bounded, private logs ----------------------------------------------------------

test('LC-12 writing past the cap rotates; files 0600, directory 0700', (t) => {
  const dir = withTemp(t);
  const file = path.join(dir, 'logs', 'service.jsonl');
  const log = new k.RotatingLog(file, { maxBytes: 1000, backups: 3 });
  for (let i = 0; i < 300; i += 1) log.write('info', `line ${i} ${'x'.repeat(60)}`);
  const names = fs.readdirSync(path.dirname(file)).sort();
  assert.deepEqual(names, ['service.jsonl', 'service.jsonl.1', 'service.jsonl.2', 'service.jsonl.3']);
  for (const name of names) {
    const info = fs.statSync(path.join(path.dirname(file), name));
    assert.ok(info.size <= 1000);
    assert.equal(info.mode & 0o777, 0o600);
  }
  assert.equal(fs.statSync(path.dirname(file)).mode & 0o777, 0o700);
  const last = JSON.parse(fs.readFileSync(file, 'utf8').trim().split('\n').at(-1));
  assert.ok(last.message.startsWith('line 299 '));
  assert.equal(last.level, 'info');
  assert.match(last.at, /^\d{4}-\d\d-\d\dT/);
});

test('LC-12 defaults are 5 x 5 MB and an oversized line is cut', (t) => {
  const dir = withTemp(t);
  const log = new k.RotatingLog(path.join(dir, 'a.jsonl'));
  assert.deepEqual([log.maxBytes, log.backups], [5 * 1024 * 1024, 5]);
  const small = new k.RotatingLog(path.join(dir, 's.jsonl'), { maxBytes: 300, backups: 1 });
  small.write('error', 'y'.repeat(5000));
  for (const name of fs.readdirSync(dir)) assert.ok(fs.statSync(path.join(dir, name)).size <= 300);
});

test('LC-12 the launchd stdout file is capped at start', (t) => {
  const dir = withTemp(t);
  const file = path.join(dir, 'service.log');
  fs.writeFileSync(file, 'a'.repeat(2000));
  assert.equal(k.capStdoutLog(file, 1000), true);
  assert.equal(fs.statSync(file).size, 0);
  assert.equal(fs.statSync(`${file}.1`).size, 2000);
  fs.writeFileSync(file, 'b'.repeat(10));
  assert.equal(k.capStdoutLog(file, 1000), false);
  assert.equal(k.capStdoutLog(path.join(dir, 'absent.log')), false);
});

// --- LC-01: SIGTERM reaches exit within the deadline -----------------------------------------

const DRAIN_PROBE = (workSeconds, deadline, hang) => `
import * as k from ${JSON.stringify(kit)};
const drain = new k.Drain({ deadline: ${deadline}, grace: 0.5 });
let done;
const finished = new Promise((r) => { done = r; });
drain.install(async (drained) => {
  console.log(drained ? 'drained' : 'interrupted');
  if (${hang}) { setInterval(() => {}, 1000); await new Promise(() => {}); }
  done();
}, { onStopping: () => console.log('stopping') });
if (${workSeconds} > 0) {
  drain.work(async () => { await new Promise((r) => setTimeout(r, ${workSeconds} * 1000)); console.log('job finished'); });
}
const keep = setInterval(() => {}, 1000);
console.log('ready');
await finished;
try { await drain.work(async () => console.log('new work accepted')); } catch (e) { console.log(e instanceof k.Stopping ? 'new work refused' : String(e)); }
clearInterval(keep);
process.exit(0); // the service's own exit after the hand-over: interrupted work was persisted
`;

function runUntilSignal(workSeconds, deadline, hang = false) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ['--input-type=module', '-e', DRAIN_PROBE(workSeconds, deadline, hang)], { stdio: ['ignore', 'pipe', 'inherit'] });
    let out = '';
    let started = 0;
    const kill = setTimeout(() => { child.kill('SIGKILL'); reject(new Error('probe did not exit')); }, 15000);
    child.stdout.on('data', (chunk) => {
      out += chunk;
      if (!started && out.includes('ready')) {
        started = Date.now();
        setTimeout(() => child.kill('SIGTERM'), 200);
      }
    });
    child.on('exit', (code) => { clearTimeout(kill); resolve({ code, elapsed: Date.now() - started - 200, out }); });
  });
}

test('LC-01 an idle service exits at once and refuses new work', async () => {
  const { code, elapsed, out } = await runUntilSignal(0, 8);
  assert.equal(code, 0);
  assert.ok(elapsed < 2000, `took ${elapsed} ms`);
  assert.match(out, /stopping/);
  assert.match(out, /drained/);
  assert.match(out, /new work refused/);
});

test('LC-01 a busy service finishes its work, then exits', async () => {
  const { code, elapsed, out } = await runUntilSignal(1, 8);
  assert.equal(code, 0);
  assert.ok(elapsed < 5000, `took ${elapsed} ms`);
  assert.ok(out.indexOf('job finished') < out.indexOf('drained'));
});

test('LC-01 work past the deadline is interrupted inside it', async () => {
  const { code, elapsed, out } = await runUntilSignal(30, 1);
  assert.equal(code, 0);
  assert.ok(elapsed < 4000, `took ${elapsed} ms`);
  assert.match(out, /interrupted/);
  assert.doesNotMatch(out, /job finished/);
});

test('LC-01 a hung hand-over is cut by the hard exit', async () => {
  const { code, elapsed } = await runUntilSignal(0, 1, true);
  assert.equal(code, k.EXIT_HARD_STOP);
  assert.ok(elapsed < 4000, `took ${elapsed} ms`);
});

test('LC-01 the default drain fits the 10 s bound', () => {
  const drain = new k.Drain();
  assert.ok(drain.deadline + drain.grace <= 10);
});

// --- LC-11 / LC-15: current + previous release ---------------------------------------------

function releases(root, names) {
  names.forEach((name, i) => {
    fs.mkdirSync(path.join(root, name, 'bin'), { recursive: true });
    const stamp = 1_700_000_000 + i * 60;
    fs.utimesSync(path.join(root, name), stamp, stamp);
  });
}

test('LC-15 two builds later two releases remain', (t) => {
  const root = withTemp(t);
  releases(root, ['1.0.0-aaa', '1.1.0-bbb', '1.2.0-ccc', '1.3.0-ddd']);
  const removed = k.pruneReleases(root, { current: path.join(root, '1.3.0-ddd') });
  assert.deepEqual(fs.readdirSync(root).sort(), ['1.2.0-ccc', '1.3.0-ddd']);
  assert.deepEqual(removed.map((p) => path.basename(p)).sort(), ['1.0.0-aaa', '1.1.0-bbb']);
});

test('LC-15 a rolled-back current release is never pruned; links and files stay', (t) => {
  const root = withTemp(t);
  releases(root, ['1.0.0-aaa', '1.1.0-bbb', '1.2.0-ccc']);
  fs.symlinkSync(path.join(root, '1.0.0-aaa'), path.join(root, 'current'));
  fs.writeFileSync(path.join(root, 'receipt.json'), '{}');
  k.pruneReleases(root, { current: path.join(root, 'current') });
  assert.deepEqual(fs.readdirSync(root).sort(), ['1.0.0-aaa', '1.2.0-ccc', 'current', 'receipt.json']);
  assert.throws(() => k.pruneReleases(root, { keep: 1 }), k.ServiceError);
});
