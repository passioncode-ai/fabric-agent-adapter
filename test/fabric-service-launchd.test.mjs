// The launchd helpers in the Node kit (lifecycle.md "Install, upgrade, uninstall", LC-14; FAA-04); the twin of the
// LaunchdInstallTests and LaunchdUninstallTests in test_fabric_service_lifecycle.py. Every call goes to a launchd
// stand-in held in this file, never the real launchctl, and every label is a throwaway (LC-14).
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';
import { instanceDirs } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-paths.mjs';
import { ForeignUserAnswer } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-supervisors.mjs';
import { tempDir } from './temp-dir.mjs';

const scripts = path.join(path.dirname(fileURLToPath(import.meta.url)), '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts');
const temp = () => tempDir('fabric-launchd-');
const label = () => `ai.passioncode.test.lifecycle-${crypto.randomBytes(4).toString('hex')}`;
const fakeKey = (prefix) => `${prefix}${'s'}${'k-'}${'q'.repeat(24)}`;
const UID = 501;
const noSleep = async () => {};

/** launchctl and plutil as the Python FAKE_LAUNCHCTL answers them; the state is this object, never launchd's. */
function fakeLaunchd({ loaded = [], overrides = {}, legacy = false, printDisabledFails = false, unloadLag = 0, lintFails = false, bootstrapFails = 0 } = {}) {
  const st = { loaded: [...loaded], overrides: { ...overrides }, pending: {}, calls: [], bootstrapFails };
  const labelOf = (target) => target.split('/').slice(2).join('/');
  st.verbs = () => st.calls.filter((c) => c[0] === 'launchctl').map((c) => c[1]);
  st.run = (argv) => {
    st.calls.push([...argv]);
    if (argv[0] === 'plutil') return lintFails ? { status: 1, stdout: 'bad plist', stderr: '' } : { status: 0, stdout: 'OK', stderr: '' };
    assert.equal(argv[0], 'launchctl', 'only launchctl and plutil are called');
    const [verb, arg, arg2] = argv.slice(1);
    const ok = (stdout = '') => ({ status: 0, stdout, stderr: '' });
    const fail = (status, stderr) => ({ status, stdout: '', stderr });
    if (verb === 'print') {
      const name = labelOf(arg);
      if (name in st.pending) {
        if (st.pending[name] <= 0) { st.loaded = st.loaded.filter((l) => l !== name); delete st.pending[name]; } else st.pending[name] -= 1;
      }
      return st.loaded.includes(name) ? ok(`${arg} = {\n\tpid = 4242\n}\n`) : fail(113, 'Could not find service in domain');
    }
    if (verb === 'print-disabled') {
      assert.equal(arg, `gui/${UID}`);
      if (printDisabledFails) return fail(1, 'Unrecognized target');
      const rows = Object.entries(st.overrides).map(([name, value]) => `\t"${name}" => ${legacy ? String(value === 'disabled') : value}`);
      return ok(`disabled services = {\n${rows.join('\n')}\n}\n\nlogin item associations = {\n}\n`);
    }
    if (verb === 'enable' || verb === 'disable') { st.overrides[labelOf(arg)] = `${verb}d`; return ok(); }
    if (verb === 'bootout') {
      const name = labelOf(arg);
      if (!st.loaded.includes(name)) return fail(3, 'Boot-out failed: 3: No such process');
      if (unloadLag) st.pending[name] = unloadLag; else st.loaded = st.loaded.filter((l) => l !== name);
      return ok();
    }
    if (verb === 'bootstrap') {
      assert.equal(arg, `gui/${UID}`);
      const name = /<key>Label<\/key>\n\t<string>([^<]+)<\/string>/.exec(fs.readFileSync(arg2, 'utf8'))[1];
      if (st.bootstrapFails > 0) { st.bootstrapFails -= 1; return fail(5, 'Bootstrap failed: 5: Input/output error'); }
      if (st.overrides[name] === 'disabled' || st.loaded.includes(name)) return fail(5, 'Bootstrap failed: 5: Input/output error');
      st.loaded.push(name);
      return ok();
    }
    return fail(64, `fake launchctl: unknown verb ${verb}`);
  };
  return st;
}

const answering = (id, instance = 'default') => async () => ({ service: { id, instance } });

function setup(t) {
  const dir = temp();
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const name = label();
  const plist = path.join(dir, `${name}.plist`);
  const body = (version = '1', extra = {}) => k.launchdPlist(name, ['/bin/echo', version], { workingDirectory: dir, stdoutPath: path.join(dir, 'service.log'), ...extra });
  return { dir, name, plist, body };
}

function install(s, fake, version = '1', extra = {}) {
  return k.launchdInstall(s.name, s.plist, s.body(version), { origin: 'http://127.0.0.1:47201', serviceId: 'example-agent', timeout: 1,
    run: fake.run, platform: 'darwin', uid: UID, fetchWellKnown: answering('example-agent'), sleep: noSleep, ...extra });
}

test('the plist carries the contract settings and the launchd marker', () => {
  const text = k.launchdPlist('ai.passioncode.example-agent.default', ['/usr/bin/node', '/opt/example agent/serve.mjs'],
    { workingDirectory: '/opt/example agent', stdoutPath: '/tmp/example.log', environment: { EXAMPLE_TOKEN_FILE: '/tmp/token' } });
  for (const pair of [['RunAtLoad', '<true/>'], ['KeepAlive', '<true/>'], ['ThrottleInterval', '<integer>10</integer>'],
    ['ExitTimeOut', '<integer>15</integer>'], ['ProcessType', '<string>Standard</string>'], ['WorkingDirectory', '<string>/opt/example agent</string>'],
    ['StandardOutPath', '<string>/tmp/example.log</string>'], ['StandardErrorPath', '<string>/tmp/example.log</string>'],
    [k.SUPERVISOR_ENV, '<string>launchd</string>'], ['EXAMPLE_TOKEN_FILE', '<string>/tmp/token</string>']]) {
    assert.match(text, new RegExp(`<key>${pair[0]}</key>\\n\\t*${pair[1]}\\n`), pair[0]);
  }
  assert.match(text, /<key>PATH<\/key>\n\t\t<string>\/usr\/local\/bin:/, 'PATH defaults to the usual directories');
  assert.match(k.launchdPlist('a.b', ['/bin/x'], { workingDirectory: '/', stdoutPath: '/l', environment: { PATH: '/only' } }), /<string>\/only<\/string>/);
  assert.match(k.launchdPlist('a.b', ['/bin/x'], { workingDirectory: '/', stdoutPath: '/l', environment: { [k.SUPERVISOR_ENV]: 'systemd' } }),
    new RegExp(`<key>${k.SUPERVISOR_ENV}</key>\\n\\t\\t<string>launchd</string>`), 'the writer writes the marker, whatever the caller passed');
});

test('the plist refuses what it cannot carry', () => {
  const refuse = (argv, extra = {}, lbl = 'a.b') => assert.throws(() => k.launchdPlist(lbl, argv, { workingDirectory: '/', stdoutPath: '/l', ...extra }), k.ServiceError, JSON.stringify([argv, extra, lbl]));
  refuse(['/bin/x'], { environment: { API_KEY: 'abc' } });
  refuse(['/bin/x'], { environment: { EXAMPLE_SECRET: 'abc' } });
  refuse(['/bin/x'], { environment: { EXAMPLE_MODE: fakeKey('') } });
  refuse(['/bin/x', fakeKey('--token=')]);
  refuse(['/bin/x', '--fabric-supervisor', 'launchd']);
  refuse(['/bin/x', 'line\nbreak']);
  refuse([]);
  refuse(['/bin/x'], { exitTimeout: 5 });
  refuse(['/bin/x'], {}, 'bad/label');
  refuse(['/bin/x'], {}, '');
  assert.throws(() => k.launchdPlist('a.b', ['/bin/x'], { stdoutPath: '/l' }), k.ServiceError);
});

test('a release folder with a space is no credential (FAA-266)', () => {
  const release = '/Users/example/Library/Application Support/example-agent/releases/e7d6275a8aae';
  const text = k.launchdPlist('a.b', ['/bin/x'], { workingDirectory: '/', stdoutPath: '/l', environment: { PYTHONPATH: release } });
  assert.ok(text.includes(`<string>${release}</string>`));
  // A base64 key whose `/` splits it into short pieces is no path: it stays a credential (0.76.0 product reading).
  const key = '2rHJkKR3HPKhvnZRjBcyYugNz2g0gTAKrWDEmg' + '/hqbs=';
  for (const value of [key, `/${key.slice(0, 20)}/${key.slice(20)}`]) {
    assert.throws(() => k.launchdPlist('a.b', ['/bin/x'], { workingDirectory: '/', stdoutPath: '/l', environment: { EXAMPLE_MODE: value } }), /credential/);
  }
});

test('the plist escapes markup', () => {
  const text = k.launchdPlist('a.b', ['/bin/echo', 'a<b>&c'], { workingDirectory: '/', stdoutPath: '/l' });
  assert.ok(text.includes('<string>a&lt;b&gt;&amp;c</string>'));
});

test('both kits write byte-identical plists', { skip: spawnSync('python3', ['--version']).status !== 0 && 'needs python3' }, () => {
  const argv = ['/usr/bin/env', 'two words', '100%', '$HOME', 'q"uote\\', 'a<b>&c', 'ünï'];
  const env = { EXAMPLE_MODE: 'a & b', EXAMPLE_TOKEN_FILE: '/tmp/t', A_FIRST: '1' };
  const py = spawnSync('python3', ['-c', `
import json, sys
from pathlib import PurePosixPath as Path  # launchd paths are POSIX on every OS the test runs on
sys.path.insert(0, ${JSON.stringify(scripts)})
import fabric_service as fs
argv, env = json.loads(sys.argv[1]), json.loads(sys.argv[2])
sys.stdout.buffer.write(fs.launchd_plist("ai.passioncode.example-agent.default", argv, working_directory=Path("/opt/x y"),
                                         stdout_path=Path("/tmp/l.log"), environment=env, exit_timeout=20))`, JSON.stringify(argv), JSON.stringify(env)]);
  assert.equal(py.status, 0, String(py.stderr));
  const node = k.launchdPlist('ai.passioncode.example-agent.default', argv, { workingDirectory: '/opt/x y', stdoutPath: '/tmp/l.log', environment: env, exitTimeout: 20 });
  assert.equal(Buffer.from(node, 'utf8').toString('hex'), py.stdout.toString('hex'));
});

test('LC-14: a first install writes, lints, enables, bootstraps and waits for the identity', async (t) => {
  const s = setup(t);
  const fake = fakeLaunchd();
  const doc = await install(s, fake);
  assert.equal(doc.service.id, 'example-agent');
  assert.deepEqual(fake.overrides, { [s.name]: 'enabled' });
  assert.ok(fake.loaded.includes(s.name));
  assert.equal(fs.readFileSync(s.plist, 'utf8'), s.body('1'));
  if (process.platform !== 'win32') assert.equal(fs.statSync(s.plist).mode & 0o777, 0o644);
  assert.deepEqual(fake.calls[0], ['plutil', '-lint', s.plist], 'the plist is linted before launchd sees it');
});

test('LC-14: an install over a disabled label rewrites the plist and stays off', async (t) => {
  const s = setup(t);
  const fake = fakeLaunchd();
  await install(s, fake, '1');
  fake.run(['launchctl', 'bootout', `gui/${UID}/${s.name}`]);
  fake.run(['launchctl', 'disable', `gui/${UID}/${s.name}`]);
  const before = fake.calls.length;
  const result = await install(s, fake, '2');
  const later = fake.calls.slice(before).map((c) => c[1]);
  assert.equal(fake.overrides[s.name], 'disabled');
  assert.ok(!fake.loaded.includes(s.name));
  assert.ok(!later.includes('enable') && !later.includes('bootstrap'), later.join(' '));
  assert.deepEqual(result, { disabled: true, label: s.name, plist: s.plist, loaded: false });
  assert.match(fs.readFileSync(s.plist, 'utf8'), /<string>2<\/string>/, 'the new release is what starts once they turn it back on');
});

test('LC-14: the legacy print-disabled format is read too', async (t) => {
  const s = setup(t);
  const fake = fakeLaunchd({ legacy: true, overrides: { } });
  fake.overrides[s.name] = 'disabled';
  const result = await install(s, fake);
  assert.equal(result.disabled, true);
  assert.ok(!fake.verbs().includes('bootstrap'));
  const enabled = fakeLaunchd({ legacy: true });
  enabled.overrides[s.name] = 'enabled';
  await install(s, enabled);
  assert.ok(!enabled.verbs().includes('enable'), 'an override the operator left enabled is not rewritten');
  assert.ok(enabled.loaded.includes(s.name));
});

test('LC-14: an unreadable override table never enables', async (t) => {
  const s = setup(t);
  const fake = fakeLaunchd({ printDisabledFails: true });
  await install(s, fake);
  assert.ok(!fake.verbs().includes('enable'));
  assert.ok(fake.loaded.includes(s.name));
});

test('LC-14: an upgrade of a running service restarts it without enable', async (t) => {
  const s = setup(t);
  const fake = fakeLaunchd();
  await install(s, fake, '1');
  const before = fake.calls.length;
  await install(s, fake, '2');
  const later = fake.calls.slice(before).map((c) => c[1]);
  assert.equal(later.filter((v) => v === 'bootout').length, 1);
  assert.equal(later.filter((v) => v === 'bootstrap').length, 1);
  assert.ok(!later.includes('enable'));
});

test('LC-14: the bootout is waited out before the bootstrap', async (t) => {
  const s = setup(t);
  const fake = fakeLaunchd({ unloadLag: 3 });
  await install(s, fake, '1');
  const before = fake.calls.length;
  await install(s, fake, '2');
  const later = fake.calls.slice(before).map((c) => c[1]);
  const bootstrap = later.indexOf('bootstrap');
  assert.ok(later.slice(later.indexOf('bootout'), bootstrap).filter((v) => v === 'print').length >= 4, later.join(' '));
  assert.ok(fake.loaded.includes(s.name));
});

test('LC-14: the operator can ask for enable explicitly', async (t) => {
  const s = setup(t);
  const fake = fakeLaunchd();
  fake.overrides[s.name] = 'disabled';
  const doc = await install(s, fake, '1', { forceEnable: true });
  assert.equal(doc.service.id, 'example-agent');
  assert.equal(fake.overrides[s.name], 'enabled');
});

test('the bootstrap retries launchd\'s EIO, then says what failed', async (t) => {
  const s = setup(t);
  const flaky = fakeLaunchd({ bootstrapFails: 4 });
  await install(s, flaky);
  assert.equal(flaky.verbs().filter((v) => v === 'bootstrap').length, 5);
  const broken = fakeLaunchd({ bootstrapFails: 5 });
  await assert.rejects(install(s, broken), /launchctl bootstrap failed: Bootstrap failed: 5/);
  assert.equal(broken.verbs().filter((v) => v === 'bootstrap').length, 5);
});

test('a plist that fails the lint never reaches launchd', async (t) => {
  const s = setup(t);
  const fake = fakeLaunchd({ lintFails: true });
  await assert.rejects(install(s, fake), /plutil -lint: bad plist/);
  assert.deepEqual(fake.verbs(), []);
});

test('a service that never answers with its identity is reported, and so is a wrong one', async (t) => {
  const s = setup(t);
  await assert.rejects(install(s, fakeLaunchd(), '1', { fetchWellKnown: async () => null, timeout: 0.05, sleep: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 10))) }),
    /did not answer as example-agent\.default/);
  await assert.rejects(install(s, fakeLaunchd(), '1', { fetchWellKnown: answering('another-agent'), timeout: 0.05, sleep: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 10))) }),
    /did not answer as example-agent\.default/);
  await assert.rejects(install(s, fakeLaunchd(), '1', { fetchWellKnown: answering('example-agent', 'second'), timeout: 0.05, sleep: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 10))) }),
    /did not answer as example-agent\.default/);
});

test('FAA-226: a listener of another OS account is never a successful install (DEC-0154 HA-2)', async (t) => {
  const s = setup(t);
  const { ForeignUserAnswer } = await import('../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-supervisors.mjs');
  const foreign = async () => new ForeignUserAnswer('foreign-user: the server on port 1 belongs to another-account; nothing was sent');
  // a service's own JSON with a foreignUser key is a document, never a refusal
  await install(s, fakeLaunchd(), '1', { fetchWellKnown: async () => ({ foreignUser: 'x', service: { id: 'example-agent', instance: 'default' } }) });
  await assert.rejects(install(s, fakeLaunchd(), '1', { fetchWellKnown: foreign, timeout: 0.05, sleep: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 10))) }),
    /is not this service's: foreign-user: .*another-account.*DEC-0154 HA-2/);
});

test('the default well-known reader polls the real origin', async (t) => {
  const s = setup(t);
  const http = await import('node:http');
  const server = http.createServer((req, res) => {
    if (req.url === '/.well-known/fabric-service') { res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ service: { id: 'example-agent', instance: 'default' } })); } else { res.statusCode = 404; res.end(); }
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  t.after(() => server.close());
  const fake = fakeLaunchd();
  const doc = await k.launchdInstall(s.name, s.plist, s.body(), { origin: `http://127.0.0.1:${server.address().port}`, serviceId: 'example-agent', timeout: 2, run: fake.run, platform: 'darwin', uid: UID, sleep: noSleep });
  assert.equal(doc.service.id, 'example-agent');
});

test('launchd is refused off macOS, and install needs the identity it waits for', async (t) => {
  const s = setup(t);
  for (const platform of ['linux', 'win32']) {
    await assert.rejects(install(s, fakeLaunchd(), '1', { platform }), /macOS only/);
    await assert.rejects(k.launchdUninstall(s.name, s.plist, { platform, run: fakeLaunchd().run }), /macOS only/);
    assert.throws(() => k.launchdLoaded(s.name, { platform }), /macOS only/);
  }
  await assert.rejects(install(s, fakeLaunchd(), '1', { serviceId: undefined }), k.ServiceError);
  await assert.rejects(install(s, fakeLaunchd(), '1', { origin: '' }), k.ServiceError);
});

test('LC-14: uninstall waits for the unload, removes the plist and clears the override', async (t) => {
  const s = setup(t);
  fs.writeFileSync(s.plist, s.body());
  const fake = fakeLaunchd({ loaded: [s.name], overrides: { [s.name]: 'disabled' }, unloadLag: 3 });
  const result = await k.launchdUninstall(s.name, s.plist, { timeout: 5, run: fake.run, platform: 'darwin', uid: UID, sleep: noSleep });
  assert.ok(!fake.loaded.includes(s.name), 'returned before launchd unloaded the job');
  assert.ok(fake.verbs().filter((v) => v === 'print').length >= 4);
  assert.equal(fs.existsSync(s.plist), false);
  assert.equal(fake.overrides[s.name], 'enabled');
  assert.deepEqual(result, { unloaded: true, plistRemoved: true, override: 'enabled', purged: [] });
  const again = await k.launchdUninstall(s.name, s.plist, { timeout: 5, run: fakeLaunchd().run, platform: 'darwin', uid: UID, sleep: noSleep });
  assert.equal(again.plistRemoved, false, 'a second uninstall is harmless');
});

test('LC-14: an uninstall that cannot unload says so and removes nothing', async (t) => {
  const s = setup(t);
  fs.writeFileSync(s.plist, s.body());
  const fake = fakeLaunchd({ loaded: [s.name], unloadLag: 10 ** 6 });
  await assert.rejects(k.launchdUninstall(s.name, s.plist, { timeout: 0.05, run: fake.run, platform: 'darwin', uid: UID, sleep: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 5))) }),
    new RegExp(s.name.replace(/\./g, '\\.')));
  assert.ok(fs.existsSync(s.plist));
  assert.ok(!fake.verbs().includes('enable'));
});

test('LC-14: purge removes data only when asked, and needs the service id', async (t) => {
  const s = setup(t);
  const home = temp();
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));
  const saved = { HOME: process.env.HOME, XDG_DATA_HOME: process.env.XDG_DATA_HOME, XDG_STATE_HOME: process.env.XDG_STATE_HOME, XDG_CACHE_HOME: process.env.XDG_CACHE_HOME };
  t.after(() => { for (const [key, value] of Object.entries(saved)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; } });
  Object.assign(process.env, { HOME: home, XDG_DATA_HOME: '', XDG_STATE_HOME: '', XDG_CACHE_HOME: '' });
  const dirs = k.serviceDirs('example-agent', 'darwin');
  for (const dir of Object.values(dirs)) { fs.mkdirSync(dir, { recursive: true }); fs.writeFileSync(path.join(dir, 'keep.txt'), 'x'); }
  const opts = { timeout: 1, run: fakeLaunchd().run, platform: 'darwin', uid: UID, sleep: noSleep };
  await k.launchdUninstall(s.name, s.plist, opts);
  assert.ok(Object.values(dirs).every((dir) => fs.existsSync(dir)), 'data must stay without purge');
  await assert.rejects(k.launchdUninstall(s.name, s.plist, { ...opts, purge: true }), /service id/);
  const outside = temp();
  t.after(() => fs.rmSync(outside, { recursive: true, force: true }));
  fs.writeFileSync(path.join(outside, 'kept.txt'), 'x');
  fs.rmSync(dirs.cache, { recursive: true });
  fs.symlinkSync(outside, dirs.cache);
  const result = await k.launchdUninstall(s.name, s.plist, { ...opts, purge: true, serviceId: 'example-agent' });
  assert.ok(Object.values(dirs).every((dir) => !fs.existsSync(dir)));
  assert.deepEqual([...result.purged].sort(), Object.values(dirs).sort());
  assert.ok(fs.existsSync(path.join(outside, 'kept.txt')), 'a symlinked folder is unlinked, never followed');
});

test('FAA-125: purging one instance removes only its folders; the personal instance purges what it always did', async (t) => {
  const s = setup(t);
  const home = temp();
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));
  const saved = { HOME: process.env.HOME, XDG_DATA_HOME: process.env.XDG_DATA_HOME, XDG_STATE_HOME: process.env.XDG_STATE_HOME, XDG_CACHE_HOME: process.env.XDG_CACHE_HOME };
  t.after(() => { for (const [key, value] of Object.entries(saved)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; } });
  Object.assign(process.env, { HOME: home, XDG_DATA_HOME: '', XDG_STATE_HOME: '', XDG_CACHE_HOME: '' });
  const personal = k.serviceDirs('example-agent', 'darwin');
  const org = instanceDirs('example-agent', 'org-acme-rehearsal', 'darwin');
  for (const dir of [...Object.values(personal), ...Object.values(org)]) { fs.mkdirSync(dir, { recursive: true }); fs.writeFileSync(path.join(dir, 'keep.txt'), 'x'); }
  const opts = { timeout: 1, run: fakeLaunchd().run, platform: 'darwin', uid: UID, sleep: noSleep, purge: true, serviceId: 'example-agent' };
  const result = await k.launchdUninstall(s.name, s.plist, { ...opts, instance: 'org-acme-rehearsal' });
  assert.ok(Object.values(org).every((dir) => !fs.existsSync(dir)));
  assert.ok(Object.values(personal).every((dir) => fs.existsSync(path.join(dir, 'keep.txt'))), 'the personal instance stays');
  assert.deepEqual([...result.purged].sort(), Object.values(org).sort());
  const again = await k.launchdUninstall(s.name, s.plist, { ...opts, instance: 'default' });
  assert.deepEqual([...again.purged].sort(), Object.values(personal).sort());
  await assert.rejects(k.launchdUninstall(s.name, s.plist, { ...opts, instance: 'Not An Instance' }), k.ServiceError);
});

test('the override reader answers as the Python one does', () => {
  const name = 'ai.passioncode.example-agent.default';
  const read = (fake) => k.launchdOverride(name, { run: fake.run, platform: 'darwin', uid: UID });
  assert.equal(read(fakeLaunchd()), null);
  assert.equal(read(fakeLaunchd({ overrides: { [name]: 'disabled' } })), 'disabled');
  assert.equal(read(fakeLaunchd({ overrides: { [name]: 'enabled' } })), 'enabled');
  assert.equal(read(fakeLaunchd({ overrides: { [name]: 'disabled' }, legacy: true })), 'disabled');
  assert.equal(read(fakeLaunchd({ overrides: { [name]: 'enabled' }, legacy: true })), 'enabled');
  assert.equal(read(fakeLaunchd({ overrides: { [`${name}.other`]: 'disabled' } })), null, 'another label is not this one');
  assert.equal(read(fakeLaunchd({ printDisabledFails: true })), 'unknown');
});

test('FAA-226: the installer reads the well-known answer on the one connection it checked, then closes it', async (t) => {
  const { wellKnownOf } = await import('../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-supervisors.mjs');
  const http = await import('node:http');
  const opened = [];
  const closed = [];
  const server = http.createServer((req, res) => res.end(JSON.stringify({ service: { id: 'example-agent', instance: 'default' } })));
  server.keepAliveTimeout = 60000; // a server that keeps idle connections open, as a stdlib Python one does
  server.on('connection', (socket) => { opened.push(socket.remotePort); socket.on('close', () => closed.push(socket.remotePort)); });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  t.after(() => server.close());
  const doc = await wellKnownOf(`http://127.0.0.1:${server.address().port}`);
  assert.equal(doc.service.id, 'example-agent');
  for (let i = 0; i < 100 && closed.length < opened.length; i += 1) await new Promise((r) => setTimeout(r, 10));
  assert.equal(opened.length, 1, 'one connection: the checked one carries the request');
  assert.deepEqual(closed, opened, 'and it is closed after the answer');
});

test('the install vouches with its own job\'s pid, which a restricted table needs (FAA-267)', async (t) => {
  const s = setup(t);
  const fake = fakeLaunchd();
  const seen = [];
  const doc = await install(s, fake, '1', { fetchWellKnown: async (origin, opts) => {
    seen.push(opts?.vouchPid);
    return seen.length === 1 ? new ForeignUserAnswer('table-restricted: netstat printed nothing to this process')
      : { service: { id: 'example-agent', instance: 'default' } };
  } });
  assert.equal(doc.service.id, 'example-agent');
  assert.deepEqual(seen, [null, 4242], 'only a restricted answer makes the job\'s pid vouch');
  assert.equal(k.launchdPid(s.name, { run: fake.run, platform: 'darwin', uid: UID }), 4242);
  assert.equal(k.launchdPid('ai.passioncode.test.absent', { run: fake.run, platform: 'darwin', uid: UID }), null);
});

test('a listener the job cannot prove is table-restricted, and the error asks for a runtime that sees the table (FAA-267)', async (t) => {
  const s = setup(t);
  const fake = fakeLaunchd();
  await assert.rejects(install(s, fake, '1', { timeout: 0.05,
    fetchWellKnown: async () => new ForeignUserAnswer('table-restricted: netstat printed nothing to this process') }),
  (err) => /could not be proved this service's: table-restricted: /.test(err.message) && /a runtime that sees them/.test(err.message));
  await assert.rejects(install(s, fake, '1', { timeout: 0.05,
    fetchWellKnown: async () => new ForeignUserAnswer('foreign-user: the server on port 47201 belongs to system') }),
  (err) => /is not this service's: foreign-user: /.test(err.message));
});

// FAA-278: a LaunchDaemon in launchd's system domain, the twin of LaunchdSystemDomainTests in
// test_fabric_service_lifecycle.py. Status and pid read without root; install and uninstall need root; the job's own
// pid proves its answer.
function systemFake({ loaded = [], bootstrapError = null, paths = {}, accounts = true } = {}) {
  const st = { loaded: [...loaded], calls: [] };
  st.run = (argv) => {
    st.calls.push([...argv]);
    if (argv[0] === 'plutil') return { status: 0, stdout: 'OK', stderr: '' };
    // The plists name a neutral account; here it maps to the uid this test runs as.
    if (argv[0] === 'id') return accounts ? { status: 0, stdout: `${process.getuid?.() ?? 501}\n`, stderr: '' } : { status: 1, stdout: '', stderr: 'no such user' };
    const [verb, arg, arg2] = argv.slice(1);
    const ok = (stdout = '') => ({ status: 0, stdout, stderr: '' });
    const name = (target) => target.split('/').pop();
    if (verb === 'print') {
      const from = paths[name(arg)] ? `\tpath = ${paths[name(arg)]}\n` : '';
      return st.loaded.includes(name(arg)) ? ok(`${arg} = {\n${from}\tpid = 4242\n}\n`) : { status: 113, stdout: '', stderr: 'Could not find service' };
    }
    if (verb === 'print-disabled') return ok('disabled services = {\n}\n');
    if (verb === 'enable') return ok();
    if (verb === 'bootout') { st.loaded = st.loaded.filter((l) => l !== name(arg)); return ok(); }
    if (verb === 'bootstrap') {
      if (bootstrapError) return { status: 5, stdout: '', stderr: bootstrapError };
      st.loaded.push(/<key>Label<\/key>\n\t<string>([^<]+)<\/string>/.exec(fs.readFileSync(arg2, 'utf8'))[1]);
      return ok();
    }
    return { status: 64, stdout: '', stderr: `unknown verb ${verb}` };
  };
  return st;
}

test('FAA-278: a plist in /Library/LaunchDaemons is the system domain', () => {
  const opts = { platform: 'darwin', uid: UID };
  assert.equal(k.launchdDomain('/Library/LaunchDaemons/a.b.plist', opts), 'system');
  assert.equal(k.launchdDomain('/tmp/a.b.plist', opts), `gui/${UID}`);
  assert.equal(k.launchdDomain(null, { ...opts, domain: 'system' }), 'system');
  assert.equal(k.launchdDomain('/Library/LaunchDaemons/a.b.plist', { ...opts, domain: 'gui' }), `gui/${UID}`);
  assert.equal(k.launchdDomain(null, opts), `gui/${UID}`, 'the default is unchanged');
  assert.throws(() => k.launchdDomain(null, { ...opts, domain: 'user' }), /domain must be gui or system/);
  assert.throws(() => k.launchdDomain(null, { domain: 'system', platform: 'linux' }), /macOS only/);
});

test('FAA-278: the plist names its user, the same bytes in both kits', { skip: spawnSync('python3', ['--version']).status !== 0 && 'needs python3' }, () => {
  const node = k.launchdPlist('a.b', ['/bin/echo'], { workingDirectory: '/', stdoutPath: '/l', userName: 'agentuser' });
  assert.ok(node.includes('<key>UserName</key>\n\t<string>agentuser</string>'));
  assert.ok(!k.launchdPlist('a.b', ['/bin/echo'], { workingDirectory: '/', stdoutPath: '/l' }).includes('UserName'));
  for (const bad of ['Root User', '', 'a'.repeat(40), 'x;y', '../x']) {
    assert.throws(() => k.launchdPlist('a.b', ['/bin/echo'], { workingDirectory: '/', stdoutPath: '/l', userName: bad }), /UserName must be/);
  }
  const py = spawnSync('python3', ['-c', `
import sys
from pathlib import PurePosixPath as Path
sys.path.insert(0, ${JSON.stringify(scripts)})
import fabric_service as fs
sys.stdout.buffer.write(fs.launchd_plist("a.b", ["/bin/echo"], working_directory=Path("/"), stdout_path=Path("/l"), user_name="agentuser"))`]);
  assert.equal(py.status, 0, String(py.stderr));
  assert.equal(Buffer.from(node, 'utf8').toString('hex'), py.stdout.toString('hex'));
});

test('FAA-278: status and pid read the system domain without root', () => {
  const fake = systemFake({ loaded: ['a.b'] });
  const opts = { run: fake.run, platform: 'darwin', uid: UID, domain: 'system' };
  assert.equal(k.launchdLoaded('a.b', opts), true);
  assert.equal(k.launchdPid('a.b', opts), 4242);
  assert.deepEqual(fake.calls[0], ['launchctl', 'print', 'system/a.b']);
  k.launchdLoaded('a.b', { run: fake.run, platform: 'darwin', uid: UID });
  assert.deepEqual(fake.calls.at(-1), ['launchctl', 'print', `gui/${UID}/a.b`], 'without a domain the gui domain, as before');
});

test('FAA-278: install and uninstall without root refuse before anything', async (t) => {
  const s = setup(t);
  const fake = systemFake();
  const common = { run: fake.run, platform: 'darwin', uid: UID, domain: 'system', euid: 501, sleep: noSleep };
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }),
    { ...common, origin: 'http://127.0.0.1:47201', serviceId: 'example-agent', timeout: 1 }),
  (err) => err.message.includes('installed by root') && err.message.includes(`launchctl bootstrap system ${s.plist}`));
  assert.equal(fs.existsSync(s.plist), false, 'nothing written');
  await assert.rejects(k.launchdUninstall(s.name, s.plist, common), (err) => err.message.includes('removed by root')
    && err.message.includes(`launchctl enable system/${s.name}`));
  assert.deepEqual(fake.calls, [], 'no launchctl call');
});

test("FAA-278: root installs, and the job's own pid proves the answer", async (t) => {
  const s = setup(t);
  const fake = systemFake();
  const seen = [];
  const doc = await k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), {
    origin: 'http://127.0.0.1:47201', serviceId: 'example-agent', timeout: 1, run: fake.run, platform: 'darwin', uid: UID,
    domain: 'system', euid: 0, sleep: noSleep,
    fetchWellKnown: async () => assert.fail('a LaunchDaemon is never read as this account'),
    fetchJobWellKnown: async (origin, { jobPid }) => { seen.push(jobPid); return { service: { id: 'example-agent', instance: 'default' } }; },
  });
  assert.equal(doc.service.id, 'example-agent');
  assert.deepEqual(seen, [4242], "launchd's pid for the job");
  assert.ok(fake.calls.some((c) => c.join(' ') === `launchctl bootstrap system ${s.plist}`));
  assert.ok(fake.calls.some((c) => c.join(' ') === `launchctl bootout system/${s.name}`));
  assert.ok(fake.calls.some((c) => c.join(' ') === 'launchctl print-disabled system'));
  await k.launchdUninstall(s.name, s.plist, { run: fake.run, platform: 'darwin', uid: UID, domain: 'system', euid: 0, sleep: noSleep });
  assert.equal(fs.existsSync(s.plist), false);
  assert.deepEqual(fake.calls.at(-1), ['launchctl', 'enable', `system/${s.name}`]);
});

test('FAA-278: root refuses an answer another process gives', async (t) => {
  const s = setup(t);
  const fake = systemFake();
  const common = { origin: 'http://127.0.0.1:47201', serviceId: 'example-agent', timeout: 0.05, run: fake.run, platform: 'darwin',
    uid: UID, domain: 'system', euid: 0, sleep: noSleep };
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), { ...common,
    fetchJobWellKnown: async () => new ForeignUserAnswer("foreign-user: the server on port 47201 is not the LaunchDaemon's pid 4242"),
  }), /is not this LaunchDaemon's: foreign-user/);
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), { ...common,
    fetchJobWellKnown: async () => new ForeignUserAnswer("table-restricted: the server on port 47201 is not the LaunchDaemon's pid 4242"),
  }), /could not be proved this LaunchDaemon's: table-restricted.*start the server with exec/);
});

test('FAA-278: a LaunchDaemon needs UserName, and its folder ignores case', async (t) => {
  const s = setup(t);
  const fake = systemFake();
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body(), { origin: 'http://127.0.0.1:47201', serviceId: 'example-agent',
    timeout: 1, run: fake.run, platform: 'darwin', uid: UID, domain: 'system', euid: 0, sleep: noSleep }), /needs UserName/);
  assert.equal(fs.existsSync(s.plist), false, 'nothing written');
  assert.deepEqual(fake.calls, []);
  assert.equal(k.launchdDomain('/library/launchdaemons/a.b.plist', { platform: 'darwin', uid: UID }), 'system');
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { environment: { UserName: 'agentuser' } }), {
    origin: 'http://127.0.0.1:47201', serviceId: 'example-agent', timeout: 1, run: fake.run, platform: 'darwin', uid: UID,
    domain: 'system', euid: 0, sleep: noSleep }), /needs UserName/, 'a UserName only in the environment is not the job\'s');
  assert.deepEqual(fake.calls, []);
});

test("FAA-278: a label another UserName holds is refused, and a job pid must be a number", async (t) => {
  const s = setup(t);
  const fake = systemFake();
  fs.writeFileSync(s.plist, s.body('1', { userName: 'otheruser' }));
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), {
    origin: 'http://127.0.0.1:47201', serviceId: 'example-agent', timeout: 1, run: fake.run, platform: 'darwin', uid: UID,
    domain: 'system', euid: 0, sleep: noSleep }), /otheruser's LaunchDaemon/);
  assert.deepEqual(fake.calls.filter((c) => c[0] !== 'id'), [['launchctl', 'print', `system/${s.name}`]], "only the label's holders read");
  assert.ok(fs.readFileSync(s.plist, 'utf8').includes('otheruser'), "the other account's plist is untouched");
  await assert.rejects(k.jobWellKnownOf('http://127.0.0.1:47201', { jobPid: null, jobUid: 501 }), /positive number/);
});

test('FAA-278: a label held by another plist is refused before anything', async (t) => {
  const s = setup(t);
  const other = path.join(s.dir, 'someone-else.plist');
  fs.writeFileSync(other, s.body('1', { userName: 'otheruser' }));
  const opts = { origin: 'http://127.0.0.1:47201', serviceId: 'example-agent', timeout: 1, platform: 'darwin', uid: UID,
    domain: 'system', euid: 0, sleep: noSleep };
  let fake = systemFake();
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), { ...opts, run: fake.run }),
    (err) => err.message.includes(`already held by ${other} (otheruser's)`));
  assert.equal(fs.existsSync(s.plist), false, 'nothing written');
  assert.ok(!fake.calls.some((c) => c[1] === 'bootout'));
  fs.rmSync(other);
  const elsewhere = temp();
  t.after(() => fs.rmSync(elsewhere, { recursive: true, force: true }));
  const loaded = path.join(elsewhere, 'loaded.plist');
  fs.writeFileSync(loaded, s.body('1', { userName: 'otheruser' }));
  fake = systemFake({ loaded: [s.name], paths: { [s.name]: loaded } });
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), { ...opts, run: fake.run }),
    (err) => err.message.includes(`already held by ${loaded}`));
  assert.equal(fs.existsSync(s.plist), false, 'nothing written');
  assert.ok(!fake.calls.some((c) => c[1] === 'bootout'));
});

test('FAA-278: root or a loose origin is refused before anything', async (t) => {
  const s = setup(t);
  const opts = { serviceId: 'example-agent', timeout: 1, platform: 'darwin', uid: UID, domain: 'system', euid: 0, sleep: noSleep };
  for (const origin of ['http://localhost:47201', 'http://127.0.0.1:47201/', 'http://127.0.0.1:0', 'http://127.0.0.1:99999', 'http://127.0.0.1:080']) {
    const fake = systemFake();
    await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), { ...opts, origin, run: fake.run }),
      /origin is http:\/\/127\.0\.0\.1:<port>/);
    assert.equal(fs.existsSync(s.plist), false, 'nothing written');
  }
  const rootFake = systemFake();
  const asRoot = (argv) => (argv[0] === 'id' ? { status: 0, stdout: '0\n', stderr: '' } : rootFake.run(argv));
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'root' }), { ...opts, origin: 'http://127.0.0.1:47201', run: asRoot }),
    /is root/);
  assert.equal(fs.existsSync(s.plist), false, 'nothing written');
});

test('FAA-278: a plist written by another tool is read whatever its indent', async (t) => {
  const s = setup(t);
  const spaced = (text) => text.replace(/\t/g, '  ');
  const opts = { origin: 'http://127.0.0.1:47201', serviceId: 'example-agent', timeout: 1, platform: 'darwin', uid: UID,
    domain: 'system', euid: 0, sleep: noSleep };
  fs.writeFileSync(s.plist, spaced(s.body('1', { userName: 'otheruser' })));
  const before = fs.readFileSync(s.plist, 'utf8');
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), { ...opts, run: systemFake().run }),
    /otheruser's LaunchDaemon/);
  assert.equal(fs.readFileSync(s.plist, 'utf8'), before, "the other account's plist is untouched");
  fs.rmSync(s.plist);
  const sibling = path.join(s.dir, 'someone-else.plist');
  fs.writeFileSync(sibling, spaced(s.body('1', { userName: 'otheruser' })));
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), { ...opts, run: systemFake().run }),
    (err) => err.message.includes(`already held by ${sibling} (otheruser's)`));
  assert.equal(fs.existsSync(s.plist), false, 'nothing written');
  // A UserName nested deeper (an environment entry) is never the job's, whatever the indent.
  const nested = spaced(s.body('1', { environment: { UserName: 'agentuser' } }));
  await assert.rejects(k.launchdInstall(s.name, s.plist, nested, { ...opts, run: systemFake().run }), /needs UserName/);
});

test('FAA-278: a numeric UserName is no account, as launchd reads it by name', async (t) => {
  const s = setup(t);
  const fake = systemFake();
  const numbered = s.body('1', { userName: 'agentuser' }).replace('<string>agentuser</string>', '<string>501</string>');
  await assert.rejects(k.launchdInstall(s.name, s.plist, numbered, { origin: 'http://127.0.0.1:47201', serviceId: 'example-agent',
    timeout: 1, run: fake.run, platform: 'darwin', uid: UID, domain: 'system', euid: 0, sleep: noSleep }), /UserName 501 is not a macOS short name/);
  assert.ok(!fake.calls.some((c) => c[0] === 'id'), 'never asked id for a uid');
  assert.equal(fs.existsSync(s.plist), false, 'nothing written');
});

test('FAA-278: a comment, CDATA or a character reference does not hide a sibling\'s label', async (t) => {
  const s = setup(t);
  const sibling = path.join(s.dir, 'someone-else.plist');
  const odd = s.body('1', { userName: 'otheruser' })
    .replace('<dict>', '<!-- an old <dict> left here --><dict>')
    .replace(`<string>${s.name}</string>`, `<string><![CDATA[${s.name}]]></string>`)
    .replace('<string>otheruser</string>', '<string>&#111;theruser</string>');
  fs.writeFileSync(sibling, odd);
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), { origin: 'http://127.0.0.1:47201',
    serviceId: 'example-agent', timeout: 1, run: systemFake().run, platform: 'darwin', uid: UID, domain: 'system', euid: 0, sleep: noSleep }),
  (err) => err.message.includes(`already held by ${sibling} (otheruser's)`));
});

test('FAA-278: a plist is read as launchd reads it: the last of a repeated key, references in key names', async (t) => {
  const s = setup(t);
  const opts = { origin: 'http://127.0.0.1:47201', serviceId: 'example-agent', timeout: 1, platform: 'darwin', uid: UID,
    domain: 'system', euid: 0, sleep: noSleep };
  // CoreFoundation keeps the last UserName: here a numeric one, which is no account; the first is never the job's.
  const twice = s.body('1', { userName: 'agentuser' }).replace('\t<string>agentuser</string>\n',
    '\t<string>agentuser</string>\n\t<key>UserName</key>\n\t<string>501</string>\n');
  let fake = systemFake();
  await assert.rejects(k.launchdInstall(s.name, s.plist, twice, { ...opts, run: fake.run }), /UserName 501 is not a macOS short name/);
  // A last value that is not a string replaces the earlier string, as CoreFoundation and plistlib read it.
  for (const last of ['<integer>1</integer>', '<true/>', '<dict/>', '<array><string>agentuser</string></array>']) {
    const replaced = s.body('1', { userName: 'agentuser' }).replace('\t<string>agentuser</string>\n',
      `\t<string>agentuser</string>\n\t<key>UserName</key>\n\t${last}\n`);
    await assert.rejects(k.launchdInstall(s.name, s.plist, replaced, { ...opts, run: systemFake().run }), /needs UserName/, last);
    assert.equal(fs.existsSync(s.plist), false, 'nothing written');
  }
  assert.equal(fs.existsSync(s.plist), false, 'nothing written');
  const sibling = path.join(s.dir, 'someone-else.plist');
  fs.writeFileSync(sibling, s.body('1', { userName: 'otheruser' }).replace('<key>Label</key>', '<key>&#76;abel</key>'));
  fake = systemFake();
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), { ...opts, run: fake.run }),
    (err) => err.message.includes(`already held by ${sibling}`));
  // A reference outside XML 1.0's Char makes the file unreadable, as expat (plistlib) finds it: no holder, no RangeError.
  // So does a Label whose last value is not a string.
  for (const odd of [`<string>&#x110000;${s.name}</string>`, `<string>&#xD800;${s.name}</string>`, `<string>${s.name}&#0;</string>`,
    `<string>${s.name}</string>\n\t<key>Label</key>\n\t<integer>1</integer>`]) {
    fs.writeFileSync(sibling, s.body('1', { userName: 'otheruser' }).replace(`<string>${s.name}</string>`, odd));
    const doc = await k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), { ...opts, run: systemFake().run,
      fetchJobWellKnown: async () => ({ service: { id: 'example-agent', instance: 'default' } }) });
    assert.equal(doc.service.id, 'example-agent', odd);
    fs.rmSync(s.plist);
  }
});

test('FAA-278: a same-path plist of another label is refused, and a refusal after bootstrap says the job stays loaded', async (t) => {
  const s = setup(t);
  const opts = { origin: 'http://127.0.0.1:47201', serviceId: 'example-agent', timeout: 0.05, platform: 'darwin', uid: UID,
    domain: 'system', euid: 0, sleep: noSleep };
  fs.writeFileSync(s.plist, s.body('1', { userName: 'agentuser' }).replace(`<string>${s.name}</string>`, '<string>other.label</string>'));
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), { ...opts, run: systemFake().run }),
    /holds launchd label other\.label/);
  fs.rmSync(s.plist);
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), { ...opts, run: systemFake().run,
    fetchJobWellKnown: async () => null }),
  (err) => err.message.includes('did not answer') && err.message.includes(`the job stays loaded and its plist starts it again at boot: as root, \`launchctl bootout system/${s.name}\` and removing ${s.plist} (or launchdUninstall) take it away`));
});

test('FAA-278: a binary sibling plist is read through plutil', { skip: process.platform !== 'darwin' && 'plutil is macOS\'s' }, async (t) => {
  const s = setup(t);
  const sibling = path.join(s.dir, 'someone-else.plist');
  fs.writeFileSync(sibling, s.body('1', { userName: 'otheruser' }));
  assert.equal(spawnSync('plutil', ['-convert', 'binary1', sibling]).status, 0);
  const fake = systemFake();
  const run = (argv) => (argv[0] === 'plutil' && argv[1] === '-convert'
    ? (({ status, stdout, stderr }) => ({ status, stdout: String(stdout), stderr: String(stderr) }))(spawnSync(argv[0], argv.slice(1)))
    : fake.run(argv));
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), { origin: 'http://127.0.0.1:47201',
    serviceId: 'example-agent', timeout: 1, run, platform: 'darwin', uid: UID, domain: 'system', euid: 0, sleep: noSleep }),
  (err) => err.message.includes(`already held by ${sibling} (otheruser's)`));
  assert.equal(fs.existsSync(s.plist), false, 'nothing written');
});

test('FAA-278: uninstall refuses a label another plist holds, and the job reader takes only a loopback origin', async (t) => {
  const s = setup(t);
  fs.writeFileSync(path.join(s.dir, 'someone-else.plist'), s.body('1', { userName: 'otheruser' }));
  const fake = systemFake({ loaded: [s.name] });
  await assert.rejects(k.launchdUninstall(s.name, s.plist, { run: fake.run, platform: 'darwin', uid: UID, domain: 'system', euid: 0, sleep: noSleep }),
    /already held by/);
  assert.ok(!fake.calls.some((c) => c[1] === 'bootout'));
  await assert.rejects(k.jobWellKnownOf('http://localhost:47201', { jobPid: 4242, jobUid: 501 }), /read only at http:\/\/127\.0\.0\.1:<port>/);
});

test('FAA-278: a UserName that is no account of this Mac is refused before anything', async (t) => {
  const s = setup(t);
  const fake = systemFake({ accounts: false });
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), {
    origin: 'http://127.0.0.1:47201', serviceId: 'example-agent', timeout: 1, run: fake.run, platform: 'darwin', uid: UID,
    domain: 'system', euid: 0, sleep: noSleep }), /is no account of this Mac/);
  assert.equal(fs.existsSync(s.plist), false, 'nothing written');
  assert.ok(!fake.calls.some((c) => c[1] === 'bootout'));
});

test("FAA-278: a refused round does not refuse the job's later answer", async (t) => {
  const s = setup(t);
  const fake = systemFake();
  let call = 0;
  const doc = await k.launchdInstall(s.name, s.plist, s.body('1', { userName: 'agentuser' }), {
    origin: 'http://127.0.0.1:47201', serviceId: 'example-agent', timeout: 5, run: fake.run, platform: 'darwin', uid: UID,
    domain: 'system', euid: 0, sleep: noSleep,
    fetchJobWellKnown: async () => (call++ === 0 ? new ForeignUserAnswer("foreign-user: not the job's pid")
      : { service: { id: 'example-agent', instance: 'default' } }),
  });
  assert.equal(doc.service.id, 'example-agent');
  assert.equal(call, 2);
});

test("FAA-278: a LaunchDaemon's purge is refused", async (t) => {
  const s = setup(t);
  const fake = systemFake();
  await assert.rejects(k.launchdUninstall(s.name, s.plist, { run: fake.run, platform: 'darwin', uid: UID, domain: 'system', euid: 0,
    purge: true, serviceId: 'example-agent', sleep: noSleep }), /belongs to its UserName/);
  assert.deepEqual(fake.calls, []);
});

test('FAA-278: a gui bootstrap without a session names the system domain', async (t) => {
  const s = setup(t);
  const opts = { origin: 'http://127.0.0.1:47201', serviceId: 'example-agent', timeout: 1, platform: 'darwin', uid: UID, sleep: noSleep };
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body(), { ...opts,
    run: systemFake({ bootstrapError: 'Bootstrap failed: 125: Domain does not support specified action' }).run }),
  (err) => err.message.includes('no GUI login session') && err.message.includes('/Library/LaunchDaemons') && err.message.includes('remove the LaunchAgent'));
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body(), { ...opts,
    run: systemFake({ bootstrapError: 'Bootstrap failed: 5: Input/output error in /tmp/125/x.plist' }).run }),
  (err) => !err.message.includes('GUI login'), '125 in a path is not the error code');
  await assert.rejects(k.launchdInstall(s.name, s.plist, s.body(), { ...opts,
    run: systemFake({ bootstrapError: 'Bootstrap failed: 5: Input/output error' }).run }),
  (err) => !err.message.includes('GUI login'));
});

test("FAA-278: jobWellKnownOf reads only what launchd's job accepted", { skip: process.platform !== 'darwin' && 'the socket table names the pid on macOS' }, async (t) => {
  const http = await import('node:http');
  const server = http.createServer((req, res) => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ service: { id: 'example-agent', instance: 'default' } })); });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const origin = `http://127.0.0.1:${server.address().port}`;
  const mine = await k.jobWellKnownOf(origin, { jobPid: process.pid, jobUid: process.getuid() });
  assert.equal(mine?.service?.id, 'example-agent');
  const otherUid = await k.jobWellKnownOf(origin, { jobPid: process.pid, jobUid: process.getuid() + 1 });
  assert.ok(otherUid instanceof ForeignUserAnswer, 'FAA-288: the job must run as its UserName');
  assert.match(otherUid.reason, /runs as uid [0-9]+, not its UserName's uid/);
  await assert.rejects(k.jobWellKnownOf(origin, { jobPid: process.pid }), /UserName's uid/);
  const other = await k.jobWellKnownOf(origin, { jobPid: 999999, jobUid: process.getuid() });
  assert.ok(other instanceof ForeignUserAnswer, String(other));
  assert.match(other.reason, /not the LaunchDaemon's pid 999999/);
});

test('FAA-257: an origin spelled localhost is read on a checked connection too, never sent unchecked', async (t) => {
  const { wellKnownOf } = await import('../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-supervisors.mjs');
  const http = await import('node:http');
  const seen = [];
  const server = http.createServer((req, res) => { seen.push(req.url); res.end(JSON.stringify({ service: { id: 'example-agent', instance: 'default' } })); });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  t.after(() => server.close());
  const port = server.address().port;
  for (const origin of [`http://127.0.0.1:${port}`, `http://localhost:${port}`]) {
    const answer = await wellKnownOf(origin, { ask: { ownUid: 424242, ownSid: 'S-1-5-21-9-9-9-424242' } });
    assert.ok(answer instanceof ForeignUserAnswer, origin);
    assert.match(answer.reason, /^foreign-user: /);
  }
  assert.deepEqual(seen, [], 'nothing reached a listener read as another account\'s');
  assert.equal((await wellKnownOf(`http://localhost:${port}`)).service.id, 'example-agent');
  const facade = await import('../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs');
  assert.equal(facade.wellKnownOf, wellKnownOf, 'the facade carries it, as the Python one carries well_known_of (FAA-259)');
});
