// DEC-0032/DEC-0033 in the Node service kit: services on Windows and Linux (FAA-21); the twin of
// test_fabric_service_platforms.py. Cross-OS cases check the descriptor rules, the folders per OS, the
// Windows token rule on SIDs already read and the lock's name. The Windows cases run only on the
// `windows` CI job; the Linux one on the `python` job.
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';
import { tempDir } from './temp-dir.mjs';
import { abstractNames } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-lock.mjs';
// FAA-72: on Linux the lock needs a Node that binds an abstract socket name exactly (22 and later); Node 18 and 20
// refuse to hold it (fabric-lock.mjs), and lock-old-node-refuses.test.mjs holds that refusal.
const noLinuxLock = process.platform === 'linux' && (await abstractNames()) !== 'exact' && `Node ${process.version} cannot hold the Linux lock`;

const kit = path.join(path.dirname(fileURLToPath(import.meta.url)), '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts');
const python = process.platform === 'win32' ? 'python' : 'python3';
const hasPython = spawnSync(python, ['--version']).status === 0;

// The contract's fixtures at the pin (fixtures/positive/service-descriptor-task-scheduler.json, -systemd.json),
// reduced to the fields these rules read.
const TASK = {
  protocol: 'fabric-service/0.1', id: 'example-agent', instance: 'default', name: 'Example Agent', origin: 'http://127.0.0.1:47195',
  auth: { tokenFile: '~\\AppData\\Local\\example-agent\\service.token', header: 'X-Example-Token', scheme: 'none' },
  lifecycle: { manager: 'task-scheduler', task: '\\PassionCode\\example-agent.default' },
  paths: { data: 'C:\\Users\\example\\AppData\\Local\\example-agent', logs: ['C:\\Users\\example\\AppData\\Local\\example-agent\\Logs\\service.log'] },
  commands: { doctor: ['C:\\Users\\example\\AppData\\Local\\Programs\\example-agent\\example-agent.exe', 'doctor', '--json'] },
  installedAt: '2026-09-28T18:00:00Z', installedBy: 'example-agent service install 0.2.0',
};
const SYSTEMD = {
  ...structuredClone(TASK), auth: { tokenFile: '~/.local/share/example-agent/service.token' },
  lifecycle: { manager: 'systemd', unit: 'example-agent.service' }, paths: { data: '~/.local/share/example-agent', logs: [] },
  commands: { doctor: ['~/.local/bin/example-agent', 'doctor'] },
};
const changed = (base, lifecycle) => ({ ...structuredClone(base), lifecycle });
const has = (problems, text) => problems.some((p) => p.includes(text));

test('the contract positive fixtures are valid', () => {
  assert.deepEqual(k.validateDescriptor(TASK), []);
  assert.deepEqual(k.validateDescriptor(SYSTEMD), []);
});

test('a manager without its job, a job beside another manager, an unknown manager are refused', () => {
  assert.ok(has(k.validateDescriptor(changed(SYSTEMD, { manager: 'systemd' })), 'declares unit'));
  assert.ok(has(k.validateDescriptor(changed(TASK, { manager: 'task-scheduler' })), 'declares task'));
  assert.ok(has(k.validateDescriptor(changed(SYSTEMD, { manager: 'none', unit: 'example-agent.service' })), 'unit belongs to manager systemd'));
  assert.ok(has(k.validateDescriptor(changed(TASK, { manager: 'systemd', unit: 'x.service', task: '\\PassionCode\\x' })), 'task belongs to manager task-scheduler'));
  assert.ok(has(k.validateDescriptor(changed(TASK, { manager: 'windows-service' })), 'launchd, systemd, task-scheduler, node, person or none'));
  assert.ok(has(k.validateDescriptor(changed(SYSTEMD, { manager: 'systemd', unit: 'no-suffix' })), 'lifecycle.unit must match'));
});

test('a network share is never a local path', () => {
  for (const share of ['\\\\server\\share\\service.token', '\\\\?\\C:\\x\\service.token', '//server/share/t']) {
    const doc = structuredClone(TASK);
    doc.auth.tokenFile = share;
    assert.ok(has(k.validateDescriptor(doc), 'never a network share'), share);
    const logs = structuredClone(TASK);
    logs.paths.logs = [share];
    assert.ok(has(k.validateDescriptor(logs), 'never a network share'), share);
  }
  assert.throws(() => k.expand('\\\\server\\share\\x'), k.ServiceError);
});

test('on Windows an absolute path names its drive, as in the Python kit', () => {
  assert.equal(k.expand('C:\\Users\\x\\data', 'win32'), 'C:\\Users\\x\\data');
  assert.throws(() => k.expand('/x/data', 'win32'), k.ServiceError); // relative to the current drive
  assert.equal(k.expand('/x/data', 'linux'), '/x/data');
  assert.throws(() => k.expand('C:\\x', 'linux'), k.ServiceError);
});

test('a remote service carries no supervisor', () => {
  const doc = { ...structuredClone(TASK), placement: 'remote', origin: 'https://agent.example.com', lifecycle: { manager: 'none', task: '\\PassionCode\\x' } };
  delete doc.commands;
  assert.ok(has(k.validateDescriptor(doc), 'no Task Scheduler task'));
});

test('the Windows folders are under LOCALAPPDATA; the override wins everywhere', () => {
  const saved = { ...process.env };
  try {
    delete process.env.FABRIC_SERVICES_DIR;
    process.env.LOCALAPPDATA = '/fake/Local';
    assert.equal(k.servicesDir('win32'), path.join('/fake/Local', 'passioncode-fabric', 'services'));
    assert.deepEqual(k.serviceDirs('example-agent', 'win32'),
      { data: path.join('/fake/Local/example-agent'), logs: path.join('/fake/Local/example-agent/Logs'), cache: path.join('/fake/Local/example-agent/Cache') });
    // The override is a path on the system the test runs on (expand checks it there).
    const elsewhere = process.platform === 'win32' ? 'C:\\elsewhere' : '/elsewhere';
    process.env.FABRIC_SERVICES_DIR = elsewhere;
    for (const platform of ['win32', 'linux', 'darwin']) assert.equal(k.servicesDir(platform), elsewhere);
  } finally {
    for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key];
    Object.assign(process.env, saved);
  }
});

test('the Windows token rule (DEC-0057, FAC-SEM-079): every windows-token.json case answers as the contract does', () => {
  const W = JSON.parse(fs.readFileSync(new URL('./fixtures/contract/windows-token-vectors.json', import.meta.url), 'utf8'));
  assert.equal(W.cases.length, 30);
  for (const c of W.cases) {
    const got = k.windowsTokenAclProblem(c.file, W.currentUserSid);
    if (c.problem === null) { assert.equal(got, null, c.name); continue; }
    assert.equal(got?.problem, c.problem, c.name);
    if (c.at !== undefined) assert.equal(got.at, c.at, c.name);
    if (c.sid !== undefined) assert.equal(got.sid, c.sid, c.name);
  }
});

test('the ACL report: ACE types, the unsigned mask, a NULL list grants everyone, one ACE is still a list', () => {
  const user = 'S-1-5-21-1-2-3-1001';
  const report = (aces, nullDacl = false) => k.parseAclReport(JSON.stringify({ owner: user, aces, nullDacl, user }));
  assert.deepEqual(report({ type: 'AccessAllowed', sid: user, mask: 2032127 }).aces, [{ type: 'allow', sid: user, mask: 2032127 }]);
  assert.deepEqual(report([{ type: 'AccessAllowed', sid: 'S-1-1-0', mask: -2147483648 }]).aces[0].mask, 0x80000000, 'GENERIC_READ arrives signed');
  assert.deepEqual(report([{ type: 'AccessDenied', sid: 'S-1-1-0', mask: 1 }, { type: 'AccessAllowedCallbackObject', sid: user, mask: 1 }]).aces.map((a) => a.type), ['deny', 'allow-object-callback']);
  assert.deepEqual(report([], true).aces, [{ type: 'allow', sid: 'S-1-1-0', mask: 0x1f01ff }]);
  const file = (aces) => ({ isRegularFile: true, isReparsePoint: false, realPathInProfile: true, ownerSid: user, aces });
  assert.equal(k.windowsTokenAclProblem(file(report([{ type: 'AccessAllowedCallback', sid: user, mask: 1 }]).aces), user).problem, 'ace-type');
  assert.match(k.tokenFileProblem('C:/t', file(report([{ type: 'AccessAllowed', sid: 'S-1-1-0', mask: 1 }]).aces), user), /S-1-1-0/);
});

test('the lock name: an abstract socket on Linux, a named pipe on Windows, none on macOS', () => {
  assert.match(k.lockName('/home/example/.local/share/example-agent/service.lock', 'linux'), /^\0fabric-service-[0-9a-f]{32}$/);
  assert.match(k.lockName('C:\\Users\\Example\\AppData\\Local\\example-agent\\service.lock', 'win32'), /^\\\\\.\\pipe\\fabric-service-[0-9a-f]{32}$/);
  assert.equal(k.lockName('C:\\Users\\Example\\x\\service.lock', 'win32'), k.lockName('c:/users/example/x/service.lock', 'win32'));
  assert.equal(k.lockName('/Users/example/service.lock', 'darwin'), null);
});

test('the Python kit holds the same name', { skip: !hasPython && 'needs python' }, () => {
  const cases = [['/home/example/.local/share/example-agent/service.lock', 'linux'], ['C:\\Users\\Example\\AppData\\Local\\x\\service.lock', 'win32']];
  const py = spawnSync(python, ['-c', `
import json, sys
sys.path.insert(0, ${JSON.stringify(kit)})
import fabric_service as fs
print(json.dumps([fs.lock_name(p, platform) for p, platform in json.loads(sys.argv[1])]))`, JSON.stringify(cases)], { encoding: 'utf8' });
  assert.equal(py.status, 0, py.stderr);
  assert.deepEqual(JSON.parse(py.stdout), cases.map(([p, platform]) => k.lockName(p, platform)));
});

// --- on the system itself ------------------------------------------------------------------

const onLinuxOrWindows = !['linux', 'win32'].includes(process.platform) && 'needs Linux or Windows';
const temp = () => tempDir('fabric-platform-');

test('a Python copy is refused while a Node copy holds the lock, and the probe sees it', { skip: onLinuxOrWindows || noLinuxLock || (!hasPython && 'needs python') }, async () => {
  const dir = temp();
  const lock = await new k.InstanceLock(dir).acquire();
  try {
    const py = spawnSync(python, ['-c', `
import sys; from pathlib import Path
sys.path.insert(0, ${JSON.stringify(kit)})
import fabric_service as fs
print("held" if fs.lock_name_held(Path(${JSON.stringify(dir)}) / "service.lock") else "free")
try:
    fs.InstanceLock(Path(${JSON.stringify(dir)})).acquire(); print("acquired")
except fs.AlreadyRunning as e:
    print("refused", e.holder_pid)`], { encoding: 'utf8' });
    assert.equal(py.stdout.trim().split(/\r?\n/).join(' | '), `held | refused ${process.pid}`, py.stderr);
  } finally {
    lock.release();
  }
});

test('a Node copy is refused while a Python copy holds the lock', { skip: onLinuxOrWindows || noLinuxLock || (!hasPython && 'needs python') }, async () => {
  const dir = temp();
  const holder = spawn(python, ['-c', `
import sys, time; from pathlib import Path
sys.path.insert(0, ${JSON.stringify(kit)})
import fabric_service as fs
fs.InstanceLock(Path(${JSON.stringify(dir)})).acquire(); print("held", flush=True); time.sleep(60)`], { stdio: ['ignore', 'pipe', 'inherit'] });
  try {
    await new Promise((resolve) => holder.stdout.once('data', resolve));
    await assert.rejects(new k.InstanceLock(dir).acquire(), (e) => e instanceof k.AlreadyRunning && e.holderPid === holder.pid);
  } finally {
    holder.kill();
  }
});

const onWindows = process.platform !== 'win32' && 'needs Windows';

test('Windows: a second holder is refused with the pid, and the name dies with the holder', { skip: onWindows }, async () => {
  const dir = temp();
  const first = await new k.InstanceLock(dir).acquire();
  await assert.rejects(new k.InstanceLock(dir).acquire(), (e) => e instanceof k.AlreadyRunning && e.holderPid === process.pid);
  first.release();
  await new Promise((resolve) => setTimeout(resolve, 100));
  (await new k.InstanceLock(dir).acquire()).release();
});

test('Windows: a token written by the kit reads back, protected to the user, SYSTEM and Administrators', { skip: onWindows }, () => {
  const file = path.join(temp(), 'svc', 'service.token');
  const token = k.ensureToken(file);
  assert.equal(k.readToken(file), token);
  const { owner, aces, user } = k.windowsAcl(file);
  const allowed = new Set([user, ...k.WINDOWS_TRUSTED]);
  assert.ok(allowed.has(owner), owner);
  const granting = aces.filter((a) => a.type === 'allow' && a.mask).map((a) => a.sid);
  assert.ok(granting.every((sid) => allowed.has(sid)), granting.join(','));
  assert.equal(user, k.windowsUserSid());
  assert.equal(fs.readFileSync(file, 'utf8'), token);
});

test('Windows: a token shared with everyone is refused by SID', { skip: onWindows }, () => {
  const file = path.join(temp(), 'svc', 'service.token');
  k.ensureToken(file);
  assert.equal(spawnSync('icacls.exe', [file, '/grant', '*S-1-1-0:(R)']).status, 0);
  assert.throws(() => k.readToken(file), /S-1-1-0/);
});

test('Windows: protecting a file drops an explicit grant it already carried', { skip: onWindows }, () => {
  const file = path.join(temp(), 'carried.token');
  fs.writeFileSync(file, 'x'.repeat(32));
  assert.equal(spawnSync('icacls.exe', [file, '/grant', '*S-1-1-0:(R)']).status, 0);
  const granting = (acl) => acl.aces.filter((a) => a.type === 'allow' && a.mask).map((a) => a.sid);
  assert.ok(granting(k.windowsAcl(file)).includes('S-1-1-0'));
  k.windowsProtect(file, { folder: false });
  const acl = k.windowsAcl(file);
  assert.deepEqual(granting(acl).filter((sid) => sid !== acl.user && !k.WINDOWS_TRUSTED.includes(sid)), []);
});
