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
