// DEC-0019 — the remote placement in the Node kit: an online agent or dashboard at an https
// origin. The last test drives the shipped sample over real TLS, as a host would meet it.
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import https from 'node:https';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const scripts = path.join(here, '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts');
const temp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-remote-'));
const remote = (over = {}) => ({
  protocol: k.PROTOCOL, id: 'example-agent', instance: 'default', name: 'Example Agent', placement: 'remote',
  origin: 'https://agent.example.com', auth: { tokenFile: '/tmp/x/t.token' }, lifecycle: { manager: 'none' },
  installedAt: k.nowIso(), installedBy: 'test', ...over,
});

test('a remote descriptor validates without paths; local still needs them', () => {
  assert.deepEqual(k.validateDescriptor(remote()), []);
  const local = { ...remote(), placement: undefined, origin: 'http://127.0.0.1:47300' };
  assert.ok(k.validateDescriptor(local).includes('missing paths'));
});

test('a remote origin is https on a public name — nothing else', () => {
  for (const origin of ['http://agent.example.com', 'https://203.0.113.7', 'https://agent.example.com/x', 'https://u:p@agent.example.com', 'http://127.0.0.1:47300']) {
    assert.ok(k.validateDescriptor(remote({ origin })).length, origin);
  }
  for (const origin of ['https://agent.localhost', 'https://box.local', 'https://api.internal']) {
    assert.match(k.validateDescriptor(remote({ origin })).join(' '), /reserved name/, origin);
  }
  assert.deepEqual(k.validateDescriptor(remote({ origin: 'https://agent.example.com:8443' })), []);
});

test('a remote descriptor carries nothing of launchd and no update', () => {
  assert.ok(k.validateDescriptor(remote({ lifecycle: { manager: 'launchd', label: 'a.b.c', plist: '/x.plist' } })).length);
  assert.ok(k.validateDescriptor(remote({ lifecycle: { manager: 'none', label: 'a.b.c' } })).length);
  assert.ok(k.validateDescriptor(remote({ commands: { update: ['/usr/bin/true'] } })).length);
  assert.deepEqual(k.validateDescriptor(remote({ commands: { doctor: ['/usr/bin/true'] } })), []);
});

test('the remote request guard', () => {
  const o = 'https://agent.example.com';
  assert.equal(k.checkRemoteRequest(o, 'agent.example.com', undefined, undefined, undefined), null);
  assert.equal(k.checkRemoteRequest(o, 'agent.example.com', undefined, undefined, 'https'), null);
  assert.match(k.checkRemoteRequest(o, 'evil.example.com', undefined, undefined, 'https'), /Host/);
  assert.match(k.checkRemoteRequest(o, 'agent.example.com', undefined, undefined, 'http'), /https only/);
  assert.match(k.checkRemoteRequest(o, 'agent.example.com', 'https://evil.example.com', undefined, 'https'), /Origin/);
  assert.match(k.checkRemoteRequest(o, 'agent.example.com', undefined, 'cross-site', 'https'), /Cross-site/);
  assert.match(k.checkRemoteRequest('https://agent.example.com:8443', 'agent.example.com', undefined, undefined, undefined), /Host/);
});

test('the well-known document of a remote service is behind the token', () => {
  const token = 'x'.repeat(32);
  assert.equal(k.wellKnownAllowed('local', undefined, token), true);
  assert.equal(k.wellKnownAllowed('remote', undefined, token), false);
  assert.equal(k.wellKnownAllowed('remote', 'Bearer wrong', token), false);
  assert.equal(k.wellKnownAllowed('remote', `Bearer ${token}`, token), true);
});

test('login codes in memory with a platform key: single use, sessions survive a restart, codes do not', () => {
  const key = Buffer.alloc(32, 7);
  const a = new k.LoginCodes(null, 120, { store: new k.MemoryCodeStore(), key });
  const code = new URL(a.issue().url, 'https://x.example.com').searchParams.get('code');
  const session = a.redeem(code);
  assert.ok(session && a.sessionValid(session));
  assert.equal(a.redeem(code), null, 'a code is single-use');
  const b = new k.LoginCodes(null, 120, { store: new k.MemoryCodeStore(), key });
  assert.ok(b.sessionValid(session), 'the platform key keeps sessions across a deploy');
  const c = a.issue().url.split('=')[1];
  assert.equal(b.redeem(c), null, 'a restart forgets codes, so none can be replayed');
  assert.throws(() => new k.LoginCodes(null, 120, { store: new k.MemoryCodeStore(), key: Buffer.alloc(8) }), /32 bytes/);
  assert.throws(() => new k.LoginCodes(null), /needs \{ store, key \}/);
});

test('the remote session cookie is __Host-, Secure, HttpOnly, Strict, Path=/ and has no Domain', () => {
  const h = k.remoteSessionCookieHeader('v');
  assert.match(h, /^__Host-fabric_session=v; /);
  for (const part of ['Path=/', 'Secure', 'HttpOnly', 'SameSite=Strict']) assert.ok(h.includes(part), part);
  assert.ok(!/Domain=/i.test(h));
});

test('registerRemote writes a 0600 token and a descriptor that claims no port', () => {
  const dir = path.join(temp(), 'services');
  const local = { protocol: k.PROTOCOL, id: 'maker', instance: 'default', name: 'Maker', origin: 'http://127.0.0.1:8443', auth: { tokenFile: '/tmp/m.token' }, lifecycle: { manager: 'none' }, paths: { data: '/tmp/m', logs: [] }, installedAt: k.nowIso(), installedBy: 'test' };
  k.writeDescriptor(local, dir);
  const file = k.registerRemote({ id: 'example-agent', name: 'Example Agent', origin: 'https://agent.example.com:8443', token: 't'.repeat(40), dir });
  const d = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.equal(d.placement, 'remote');
  assert.equal(fs.statSync(d.auth.tokenFile).mode & 0o777, 0o600);
  assert.equal(fs.readFileSync(d.auth.tokenFile, 'utf8'), 't'.repeat(40));
  assert.throws(() => k.registerRemote({ id: 'other', name: 'O', origin: 'https://o.example.com', token: 'short', dir }), /16 characters/);
  const later = { ...local, id: 'later', origin: 'http://127.0.0.1:8443' };
  assert.throws(() => k.writeDescriptor(later, dir), /already claimed by maker/, 'a local port is still a claim between local services');
  const third = { ...local, id: 'third', origin: 'http://127.0.0.1:47301' };
  assert.ok(k.writeDescriptor(third, dir), 'a remote descriptor in the directory blocks no local port');
});

const haveOpenssl = spawnSync('openssl', ['version']).status === 0;

test('the sample online service over real TLS, met the way a host meets it', { skip: !haveOpenssl && 'openssl not available' }, async () => {
  const dir = temp();
  const cert = path.join(dir, 'cert.pem'), keyFile = path.join(dir, 'key.pem');
  const gen = spawnSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=agent.example.com',
    '-addext', 'subjectAltName=DNS:agent.example.com', '-keyout', keyFile, '-out', cert], { encoding: 'utf8' });
  assert.equal(gen.status, 0, gen.stderr);
  const token = 'r'.repeat(40);
  fs.writeFileSync(path.join(dir, 'token'), token, { mode: 0o600 });
  fs.writeFileSync(path.join(dir, 'session.key'), Buffer.alloc(32, 3), { mode: 0o600 });
  const port = 47000 + Math.floor(Math.random() * 1500);
  const origin = `https://agent.example.com:${port}`;
  const child = spawn(process.execPath, [path.join(scripts, 'sample-remote-service.mjs'), '--origin', origin, '--port', String(port),
    '--token-file', path.join(dir, 'token'), '--session-key-file', path.join(dir, 'session.key'), '--tls-cert', cert, '--tls-key', keyFile], { stdio: ['ignore', 'pipe', 'pipe'] });
  let out = '';
  child.stdout.on('data', (b) => { out += b; });
  child.stderr.on('data', (b) => { out += b; });
  const ask = (method, p, headers = {}) => new Promise((resolve, reject) => {
    const req = https.request({ host: '127.0.0.1', port, servername: 'agent.example.com', ca: fs.readFileSync(cert), method, path: p, headers: { Host: `agent.example.com:${port}`, ...headers }, timeout: 3000 }, (res) => {
      let body = ''; res.on('data', (c) => { body += c; }); res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body }));
    });
    req.on('error', reject); req.end();
  });
  try {
    for (let i = 0; i < 50 && !out.includes('example agent on'); i++) await new Promise((r) => setTimeout(r, 100));
    assert.ok(out.includes('example agent on'), `the sample did not start: ${out}`);
    const anon = await ask('GET', '/.well-known/fabric-service');
    assert.equal(anon.status, 401);
    assert.equal(anon.body, '', 'a refused well-known request discloses nothing');
    const wk = await ask('GET', '/.well-known/fabric-service', { Authorization: `Bearer ${token}` });
    assert.equal(wk.status, 200);
    assert.equal(JSON.parse(wk.body).service.id, 'example-agent');
    assert.equal((await ask('GET', '/.well-known/fabric-service', { Authorization: `Bearer ${token}`, Host: 'evil.example.com' })).status, 403);
    assert.equal((await ask('GET', '/fabric/v1/events', { Authorization: `Bearer ${token}`, 'Sec-Fetch-Site': 'cross-site' })).status, 403);
    assert.equal((await ask('GET', '/fabric/v1/events')).status, 401);
    const lc = await ask('POST', '/fabric/v1/login-code', { Authorization: `Bearer ${token}` });
    assert.equal(lc.status, 200);
    const loginPath = JSON.parse(lc.body).url;
    const first = await ask('GET', loginPath);
    assert.equal(first.status, 302);
    const cookie = first.headers['set-cookie'][0];
    assert.match(cookie, /^__Host-fabric_session=.+; Path=\/; Secure; HttpOnly; SameSite=Strict/);
    assert.equal((await ask('GET', loginPath)).status, 403, 'the login link is single-use');
    assert.equal((await ask('GET', '/', { Cookie: cookie.split(';')[0] })).status, 200);
    assert.equal((await ask('GET', '/')).status, 401);
  } finally {
    child.kill('SIGTERM');
  }
});
