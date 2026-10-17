// The systemd unit and the Task Scheduler task in the Node kit (contract DEC-0032, service.md "Supervisor"; FAA-21);
// the twin of test_fabric_service_supervisors.py. Install and uninstall run against a recorder, never the real
// systemctl or schtasks (LC-14). The last case holds the two kits to byte-identical files.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';
import { tempDir } from './temp-dir.mjs';

const scripts = path.join(path.dirname(fileURLToPath(import.meta.url)), '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts');
const temp = () => tempDir('fabric-supervisor-');
const fakeKey = (prefix) => `${prefix}${'s'}${'k-'}${'q'.repeat(24)}`;

// Stands in for systemctl and schtasks: fails a call naming a word in `fail`, prints `out[word]` for one naming it.
function recorder(fail = [], out = {}) {
  const calls = [];
  const run = (argv) => {
    calls.push([...argv]);
    const failed = argv.some((word) => fail.includes(word));
    const printed = Object.entries(out).find(([word]) => argv.includes(word))?.[1] ?? '';
    return { status: failed ? 1 : 0, stdout: printed, stderr: failed ? 'refused' : '' };
  };
  return { calls, run };
}

const UNIT = 'example-agent.default.service';
const unit = (extra = {}) => k.systemdUnit(UNIT, ['/usr/bin/node', '/opt/example agent/serve.mjs', '--port', '47201'],
  { workingDirectory: '/opt/example agent', description: 'Example Agent', ...extra });

test('the systemd unit carries the contract settings', () => {
  const text = unit();
  for (const line of ['Restart=always', 'RestartSec=10', 'TimeoutStopSec=15', 'WantedBy=default.target', 'Description=Example Agent',
    'WorkingDirectory=/opt/example agent', 'Environment="FABRIC_SERVICE_SUPERVISOR=systemd"']) {
    assert.ok(text.includes(`${line}\n`), line);
  }
  assert.ok(text.includes('ExecStart="/usr/bin/node" "/opt/example agent/serve.mjs" "--port" "47201"\n'));
});

test('systemd specifiers and variables are escaped', () => {
  const text = k.systemdUnit('x.service', ['/bin/echo', '100%', '$HOME', 'say "hi"\\'], { workingDirectory: '/tmp' });
  assert.ok(text.includes('ExecStart="/bin/echo" "100%%" "$$HOME" "say \\"hi\\"\\\\"'), text);
});

test('the systemd unit refuses what it cannot carry', () => {
  const refuse = (fn) => assert.throws(fn, k.ServiceError);
  refuse(() => k.systemdUnit('bad name', ['/bin/x'], { workingDirectory: '/tmp' }));
  refuse(() => k.systemdUnit('x.service', ['relative/x'], { workingDirectory: '/tmp' }));
  refuse(() => k.systemdUnit('x.service', ['/bin/x', 'line\nbreak'], { workingDirectory: '/tmp' }));
  refuse(() => k.systemdUnit('x.service', ['/bin/x'], { workingDirectory: '/tmp', environment: { API_KEY: 'abc' } }));
  refuse(() => k.systemdUnit('x.service', ['/bin/x', fakeKey('--key=')], { workingDirectory: '/tmp' }));
  refuse(() => unit({ stopTimeout: 5 })); // must outlast the 8 s drain (DRAIN_SECONDS)
  refuse(() => unit({ description: 'Example\nExecStartPre=/bin/sh' }));
  refuse(() => unit({ environment: { 'BAD NAME': 'x' } }));
  refuse(() => k.systemdUnit('x.service', ['/bin/x'], { workingDirectory: 'relative' }));
});

test('the working directory is not quoted, and specifiers stay literal', () => {
  // Quoted, systemd takes the quotes as part of the path and refuses the unit ("path is not absolute").
  const text = k.systemdUnit('x.service', ['/bin/x'], { workingDirectory: '/srv/100% x', description: 'at 100% %h' });
  assert.ok(text.includes('WorkingDirectory=/srv/100%% x\n'), text);
  assert.ok(text.includes('Description=at 100%% %%h\n'), text);
});

test('systemd install enables and (re)starts it, keeps a disabled unit off; uninstall disables and removes it', () => {
  const dir = path.join(temp(), 'systemd/user');
  const reload = ['systemctl', '--user', 'daemon-reload'];
  const enable = ['systemctl', '--user', 'enable', UNIT];
  const restart = ['systemctl', '--user', 'restart', UNIT];
  const isEnabled = ['systemctl', '--user', 'is-enabled', UNIT];
  let r = recorder();
  const file = k.systemdInstall(UNIT, unit(), { unitDir: dir, run: r.run, platform: 'linux' });
  assert.equal(file, path.join(dir, UNIT));
  assert.equal(fs.readFileSync(file, 'utf8'), unit());
  assert.deepEqual(r.calls, [reload, enable, restart], 'a first install enables and starts it');
  r = recorder([], { 'is-enabled': 'enabled\n' });
  k.systemdInstall(UNIT, unit({ description: 'v2' }), { unitDir: dir, run: r.run, platform: 'linux' });
  assert.deepEqual(r.calls, [isEnabled, reload, enable, restart], 'an upgrade restarts what runs');
  r = recorder([], { 'is-enabled': 'disabled\n' });
  k.systemdInstall(UNIT, unit({ description: 'v3' }), { unitDir: dir, run: r.run, platform: 'linux' });
  assert.deepEqual(r.calls, [isEnabled, reload], 'the operator switched it off: it stays off (LC-14)');
  assert.ok(fs.readFileSync(file, 'utf8').includes('Description=v3'));
  r = recorder([], { 'is-enabled': 'disabled\n' });
  k.systemdInstall(UNIT, unit(), { unitDir: dir, run: r.run, platform: 'linux', forceEnable: true });
  assert.deepEqual(r.calls, [isEnabled, reload, enable, restart]);
  r = recorder();
  k.systemdUninstall(UNIT, { unitDir: dir, run: r.run, platform: 'linux' });
  assert.equal(fs.existsSync(file), false);
  assert.deepEqual(r.calls, [['systemctl', '--user', 'disable', '--now', UNIT], ['systemctl', '--user', 'daemon-reload']]);
});

test('a failed enable is reported, and systemd is refused off Linux', () => {
  assert.throws(() => k.systemdInstall('x.service', unit(), { unitDir: temp(), run: recorder(['enable']).run, platform: 'linux' }), k.ServiceError);
  assert.throws(() => k.systemdInstall('x.service', unit(), { unitDir: temp(), run: recorder().run, platform: 'darwin' }), /Linux only/);
});

const TASK = '\\PassionCode\\example-agent.default';
const task = (extra = {}) => k.taskXml(TASK, ['C:\\Program Files\\nodejs\\node.exe', 'C:\\Example App\\serve.mjs', '--port', '47201'],
  { workingDirectory: 'C:\\Example App', description: 'Example Agent', user: 'HOST\\person', ...extra });
const element = (text, name) => (text.match(new RegExp(`<${name}>([^<]*)</${name}>`)) ?? [])[1];

test('the task carries the contract settings', () => {
  const text = task();
  assert.ok(text.startsWith('<?xml version="1.0" encoding="UTF-16"?>\n<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'));
  assert.equal(element(text, 'URI'), '\\PassionCode\\example-agent.default');
  assert.ok(text.includes('<LogonTrigger><Enabled>true</Enabled><UserId>HOST\\person</UserId></LogonTrigger>'));
  assert.equal(element(text, 'LogonType'), 'InteractiveToken');
  assert.equal(element(text, 'RunLevel'), 'LeastPrivilege');
  assert.equal(element(text, 'ExecutionTimeLimit'), 'PT0S');
  assert.equal(element(text, 'Interval'), 'PT1M');
  assert.equal(element(text, 'MultipleInstancesPolicy'), 'IgnoreNew');
  assert.equal(element(text, 'Command'), 'C:\\Program Files\\nodejs\\node.exe');
  // the raw XML: quotes escaped. DEC-0057: a task's action has no environment, so the marker is an argument.
  assert.equal(element(text, 'Arguments'), '&quot;C:\\Example App\\serve.mjs&quot; --port 47201 --fabric-supervisor task-scheduler');
  assert.equal(element(text, 'WorkingDirectory'), 'C:\\Example App');
});

test('the task XML is escaped', () => {
  const text = k.taskXml('\\PassionCode\\x', ['C:\\x.exe', 'a<b&c'], { workingDirectory: 'C:\\w', description: 'A & <B>', user: 'H\\u' });
  assert.equal(element(text, 'Description'), 'A &amp; &lt;B&gt;');
  assert.equal(element(text, 'Arguments'), 'a&lt;b&amp;c --fabric-supervisor task-scheduler');
});

test('the task refuses what it cannot carry', () => {
  const saved = process.env.USERNAME;
  process.env.USERNAME = '';
  try {
    for (const bad of [{ task: 'no-leading-backslash' }, { argv: ['relative.exe'] }, { argv: ['C:\\x.exe', fakeKey('--token=')] },
      { argv: ['C:\\x.exe', 'a\x01b'] }, { cwd: 'C:\\w\n' }, { user: '' }]) {
      assert.throws(() => k.taskXml(bad.task ?? '\\PassionCode\\x', bad.argv ?? ['C:\\x.exe'], { workingDirectory: bad.cwd ?? 'C:\\w', user: bad.user ?? 'H\\u' }),
        k.ServiceError, JSON.stringify(bad));
    }
  } finally {
    if (saved === undefined) delete process.env.USERNAME; else process.env.USERNAME = saved;
  }
});

test('the task settings are in the order Task Scheduler exports them', () => {
  const settings = task().match(/<Settings>([\s\S]*)<\/Settings>/)[1];
  assert.deepEqual([...settings.matchAll(/^ {4}<([A-Za-z]+)>/gm)].map((m) => m[1]),
    ['MultipleInstancesPolicy', 'DisallowStartIfOnBatteries', 'StopIfGoingOnBatteries', 'StartWhenAvailable', 'Enabled', 'ExecutionTimeLimit', 'RestartOnFailure']);
});

test('task install creates the task from a UTF-16 file it then removes, (re)starts it, keeps a disabled task off; uninstall ends and deletes it', () => {
  let r = recorder(['/Query']);
  let seen = null;
  const run = (argv) => {
    if (argv[1] === '/Create') seen = fs.readFileSync(argv[argv.indexOf('/XML') + 1]);
    return r.run(argv);
  };
  k.taskInstall(TASK, task(), { run, platform: 'win32' });
  const steps = () => r.calls.map((c) => c.slice(0, 2));
  assert.deepEqual(steps(), [['schtasks', '/Query'], ['schtasks', '/Create'], ['schtasks', '/Run']], 'a first install creates and runs it');
  const create = r.calls[1];
  assert.deepEqual(create.slice(2, 4), ['/TN', TASK]);
  assert.ok(create.includes('/F'));
  assert.deepEqual([...seen.subarray(0, 2)], [0xff, 0xfe]);
  assert.equal(seen.subarray(2).toString('utf16le'), task());
  assert.equal(fs.existsSync(create[create.indexOf('/XML') + 1]), false, 'the task file is removed once the task exists');
  const disabled = task().replace('<Enabled>true</Enabled>\n    <ExecutionTimeLimit>', '<Enabled>false</Enabled>\n    <ExecutionTimeLimit>');
  assert.notEqual(disabled, task());
  r = recorder([], { '/Query': task() });
  k.taskInstall(TASK, task(), { run: r.run, platform: 'win32' });
  assert.deepEqual(steps(), [['schtasks', '/Query'], ['schtasks', '/Create'], ['schtasks', '/End'], ['schtasks', '/Run']], 'an upgrade restarts what runs');
  r = recorder([], { '/Query': disabled });
  k.taskInstall(TASK, task(), { run: r.run, platform: 'win32' });
  assert.deepEqual(steps(), [['schtasks', '/Query'], ['schtasks', '/Create'], ['schtasks', '/Change']], 'the operator switched it off: it stays off (LC-14)');
  assert.ok(r.calls[2].includes('/DISABLE'));
  r = recorder([], { '/Query': disabled });
  k.taskInstall(TASK, task(), { run: r.run, platform: 'win32', forceEnable: true });
  assert.deepEqual(steps().slice(-2), [['schtasks', '/End'], ['schtasks', '/Run']]);
  r = recorder();
  k.taskUninstall(TASK, { run: r.run, platform: 'win32' });
  assert.deepEqual(r.calls.map((c) => c.slice(0, 2)), [['schtasks', '/End'], ['schtasks', '/Delete']]);
  assert.throws(() => k.taskInstall('\\PassionCode\\x', task(), { run: recorder().run, platform: 'linux' }), /Windows only/);
  assert.throws(() => k.taskInstall('\\PassionCode\\x', task(), { run: recorder(['/Create']).run, platform: 'win32' }), k.ServiceError);
});

test('the Windows command line quotes the way the C runtime parses it', () => {
  assert.equal(k.windowsCommandLine(['plain', 'two words', 'a"b', 'c\\ d\\', '', 'x\\\\"y']), 'plain "two words" a\\"b "c\\ d\\\\" "" x\\\\\\\\\\"y');
});

test('both kits write byte-identical unit and task files', { skip: spawnSync('python3', ['--version']).status !== 0 && 'needs python3' }, () => {
  const argv = ['/usr/bin/env', 'two words', '100%', '$HOME', 'q"uote\\', 'C:\\x y\\'];
  const py = spawnSync('python3', ['-c', `
import json, sys
from pathlib import Path
sys.path.insert(0, ${JSON.stringify(scripts)})
import fabric_service as fs
argv = json.loads(sys.argv[1])
print(json.dumps([fs.systemd_unit("example-agent.default.service", argv, working_directory=Path("/opt/x"), description="Ex & <y>",
                                  environment={"EXAMPLE_MODE": "a b"}, stop_timeout=20),
                  fs.task_xml("\\\\PassionCode\\\\example-agent.default", ["C:\\\\x.exe"] + argv[1:], working_directory="C:\\\\w x",
                              description="Ex & <y>", user="H\\\\u")]))`, JSON.stringify(argv)], { encoding: 'utf8' });
  assert.equal(py.status, 0, py.stderr);
  const [pyUnit, pyTask] = JSON.parse(py.stdout);
  assert.equal(k.systemdUnit('example-agent.default.service', argv, { workingDirectory: '/opt/x', description: 'Ex & <y>', environment: { EXAMPLE_MODE: 'a b' }, stopTimeout: 20 }), pyUnit);
  assert.equal(k.taskXml('\\PassionCode\\example-agent.default', ['C:\\x.exe', ...argv.slice(1)], { workingDirectory: 'C:\\w x', description: 'Ex & <y>', user: 'H\\u' }), pyTask);
});

test('a copy systemd restarts backs off on a held lock; a hand start does not', async (t) => {
  const saved = process.env[k.SUPERVISOR_ENV];
  t.after(() => { if (saved === undefined) delete process.env[k.SUPERVISOR_ENV]; else process.env[k.SUPERVISOR_ENV] = saved; });
  const dir = temp();
  let holder = await new k.InstanceLock(dir).acquire();
  const slept = [];
  process.env[k.SUPERVISOR_ENV] = 'systemd';
  assert.equal(k.supervised(), true);
  // On Windows a closed pipe may linger a tick, so the copy may back off more than once before it takes over.
  (await k.holdSingleInstance(dir, { sleep: async (s) => { slept.push(s); holder.release(); await new Promise((r) => setTimeout(r, 50)); } })).release();
  assert.equal(slept[0], k.LOCK_BACKOFF_FIRST_SECONDS);
  const waited = slept.length;
  holder = await new k.InstanceLock(dir).acquire();
  process.env[k.SUPERVISOR_ENV] = 'cron';
  assert.equal(k.supervised(), false);
  const exits = [];
  await k.holdSingleInstance(dir, { sleep: async (s) => slept.push(s), exit: (code) => exits.push(code) });
  holder.release();
  assert.deepEqual(exits, [k.EXIT_ALREADY_RUNNING]);
  assert.equal(slept.length, waited, 'a hand start never waits');
});

// ---- DEC-0057 (CT-01, FAA-32): the supervisor marker, held to the contract's service-supervisor.json ----

const SUP = JSON.parse(fs.readFileSync(new URL('./fixtures/contract/supervisor-vectors.json', import.meta.url), 'utf8'));

/** FAC-SEM-078 (the contract's lockOutcomeRules, ported for this test): the instance paths a record of a start breaks. */
function lockOutcomeFindings(record) {
  const out = [];
  const marker = k.supervisorMarker({ env: record.start.env ?? {}, argv: record.start.argv ?? [] });
  if (record.sideEffects !== undefined && !Array.isArray(record.sideEffects)) out.push('/sideEffects');
  (Array.isArray(record.sideEffects) ? record.sideEffects : []).forEach((_, i) => out.push(`/sideEffects/${i}`));
  const count = (v, integer) => typeof v === 'number' && Number.isFinite(v) && v >= 0 && (!integer || Number.isInteger(v));
  const attemptsOk = count(record.attempts, true);
  const waitedOk = count(record.waitedMs, false);
  if (!attemptsOk) out.push('/attempts');
  if (!waitedOk) out.push('/waitedMs');
  if (marker.kind === 'conflict') {
    if (attemptsOk && record.attempts !== 0) out.push('/attempts');
    if (waitedOk && record.waitedMs !== 0) out.push('/waitedMs');
  } else if (marker.kind === 'manual') {
    if (attemptsOk && record.attempts !== 1) out.push('/attempts');
    if (waitedOk && record.waitedMs !== 0) out.push('/waitedMs');
  } else {
    if (attemptsOk && record.attempts < 1) out.push('/attempts');
    if (waitedOk && record.waitedMs > SUP.lockWaitMaxMs) out.push('/waitedMs');
  }
  const outcome = record.outcome;
  if (typeof outcome !== 'object' || outcome === null) return [...out, '/outcome'];
  if (outcome.acquired === true) return marker.kind === 'conflict' ? [...out, '/outcome/acquired'] : out;
  if (outcome.exitStatus !== SUP.exitStatus) out.push('/outcome/exitStatus');
  const message = typeof outcome.message === 'string' ? outcome.message : '';
  if (marker.kind === 'conflict') {
    const names = { environment: k.SUPERVISOR_ENV, argument: k.SUPERVISOR_ARG };
    if (!marker.forms.every((f) => message.includes(names[f]))) out.push('/outcome/message');
  } else if (record.holderPid === null) {
    if (!/\bunknown\b/i.test(message)) out.push('/outcome/message');
  } else if (!new RegExp(`(?<!\\d)${record.holderPid}(?!\\d)`).test(message)) out.push('/outcome/message');
  return out;
}

test('every marker case answers as the contract does', () => {
  assert.equal(SUP.cases.length, 22);
  assert.deepEqual([...k.SUPERVISORS], SUP.managers);
  for (const c of SUP.cases) {
    const marker = k.supervisorMarker({ env: c.env, argv: c.argv });
    assert.deepEqual(marker.kind === 'supervised' ? { kind: marker.kind, manager: marker.manager } : { kind: marker.kind }, c.marker, c.name);
    assert.equal(k.lockWaitBudgetSeconds(marker) * 1000, c.waitBudgetMs, c.name);
  }
});

test('the rule port reads the contract\'s FAC-SEM-078 records as it does', () => {
  assert.equal(SUP.lockRecords.length, 11);
  for (const item of SUP.lockRecords) assert.deepEqual(lockOutcomeFindings(item.record), item.codes, item.name);
});

async function startAgainstHeldLock(env, argv, { holderPidKnown = true } = {}) {
  const dir = temp();
  const holder = await new k.InstanceLock(dir).acquire();
  if (!holderPidKnown) fs.writeFileSync(path.join(dir, 'service.lock'), '');
  const before = fs.readdirSync(dir).sort();
  let attempts = 0;
  let now = 0;
  const real = k.InstanceLock.prototype.acquire;
  k.InstanceLock.prototype.acquire = function counting() { attempts += 1; return real.call(this); };
  const written = [];
  const write = process.stderr.write;
  process.stderr.write = (chunk) => { written.push(String(chunk)); return true; };
  let outcome;
  try {
    const exits = [];
    const lock = await k.holdSingleInstance(dir, { sleep: async (s) => { now += s; }, clock: () => now, exit: (code) => exits.push(code), env, argv });
    if (exits.length) outcome = { exitStatus: exits[0], message: written.join('').trim().split('\n').at(-1) };
    else { lock.release(); outcome = { acquired: true }; }
  } finally {
    k.InstanceLock.prototype.acquire = real;
    process.stderr.write = write;
    holder.release();
  }
  const after = fs.readdirSync(dir).sort();
  return { start: { env, argv }, holderPid: holderPidKnown ? process.pid : null, attempts, waitedMs: now * 1000,
    sideEffects: after.filter((name) => !before.includes(name)), outcome };
}

test('the kit\'s starts against a held lock conform (FAC-SEM-078)', async () => {
  const exe = '/opt/example-agent/bin/example-agent';
  const starts = [
    ['by hand', {}, [exe, 'serve'], true],
    ['the node, by the variable', { [k.SUPERVISOR_ENV]: 'node' }, [exe, 'serve'], true],
    ['a task, by the argument', {}, [exe, 'serve', '--fabric-supervisor', 'task-scheduler'], true],
    ['the holder unknown', {}, [exe, 'serve'], false],
    ['markers that disagree', { [k.SUPERVISOR_ENV]: 'launchd' }, [exe, '--fabric-supervisor=task-scheduler'], true],
    ['two arguments that disagree', {}, [exe, '--fabric-supervisor', 'systemd', '--fabric-supervisor=node'], true],
    ['a bare argument beside the variable', { [k.SUPERVISOR_ENV]: 'systemd' }, [exe, '--fabric-supervisor', '--verbose'], true],
  ];
  for (const [name, env, argv, known] of starts) {
    const record = await startAgainstHeldLock(env, argv, { holderPidKnown: known });
    assert.deepEqual(lockOutcomeFindings(record), [], `${name}: ${JSON.stringify(record)}`);
    assert.equal(record.outcome.exitStatus, 75, name);
    const kind = k.supervisorMarker({ env, argv }).kind;
    if (kind === 'conflict') assert.equal(record.attempts, 0, name);
    if (kind === 'manual') assert.equal(record.attempts, 1, name);
    if (kind === 'supervised') {
      assert.equal(record.waitedMs, k.LOCK_WAIT_SUPERVISED_SECONDS * 1000, name);
      assert.ok(record.attempts > 1, name);
    }
  }
});

test('the writers carry the marker and refuse one passed in', () => {
  const text = k.taskXml('\\PassionCode\\x', ['C:\\x.exe', 'serve', '--', '--fabric-supervisor', 'systemd'], { workingDirectory: 'C:\\w', user: 'H\\u' });
  assert.equal(element(text, 'Arguments'), 'serve --fabric-supervisor task-scheduler -- --fabric-supervisor systemd', 'before any --');
  for (const writer of [
    (argv) => k.taskXml('\\PassionCode\\x', ['C:\\x.exe', ...argv], { workingDirectory: 'C:\\w', user: 'H\\u' }),
    (argv) => k.systemdUnit('x.service', ['/bin/x', ...argv], { workingDirectory: '/w' }),
  ]) {
    for (const argv of [['--fabric-supervisor', 'node'], ['--fabric-supervisor=launchd'], ['--fabric-supervisor']]) assert.throws(() => writer(argv), /written by the supervisor file's writer/, argv.join(' '));
  }
  const unit = k.systemdUnit('x.service', ['/bin/x'], { workingDirectory: '/w', environment: { [k.SUPERVISOR_ENV]: 'launchd' } });
  assert.match(unit.replace(/"/g, ''), new RegExp(`Environment=${k.SUPERVISOR_ENV}=systemd`));
  assert.doesNotMatch(unit, /launchd/, "the unit's writer assigns the marker unconditionally");
});

test('DEC-0057: the descriptor names one supervisor and never a share; every killing fixture is refused for its reason', () => {
  const reasons = {"bad-task": "lifecycle.task must match", "bad-unit": "lifecycle.unit must match", "systemd-with-plist": "plist belongs to launchd", "task-scheduler-with-label": "label belongs to launchd", "task-without-task-scheduler": "lifecycle.task belongs to", "unc-forward-slash": "never a network share", "windows-service-manager": "lifecycle.manager must be"};
  const { negatives } = JSON.parse(fs.readFileSync(new URL('./fixtures/contract/descriptor-negatives.json', import.meta.url), 'utf8'));
  assert.deepEqual(negatives.map((n) => n.name).sort(), Object.keys(reasons).sort());
  for (const item of negatives) assert.ok(k.validateDescriptor(item.descriptor).join(' ').includes(reasons[item.name]), item.name);
});
