// FAA-292 (DEC-0155 RT-2) and FAA-272 in the Node kit: the twin of test_fabric_socket_proof.py, held to the same cases
// (test/fixtures/peer-owner/socket-proof-cases.json). Node reads lsof where the Python twin reads libproc; the live
// cases run on macOS only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as sp from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-socket-proof.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const C = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/peer-owner/socket-proof-cases.json'), 'utf8'));
const OWN = C.ownUid;
const brief = (p) => ({ proved: p.proved, pid: p.pid, reason: p.reason });
const darwin = { platform: 'darwin', uid: OWN, euid: OWN };

test('the lsof vectors read as in Python', () => {
  for (const c of C.lsof) assert.deepEqual(sp.parseLsofSockets(c.text, c.uid), c.expect, c.name);
});

test('the questions answer as in Python', () => {
  for (const c of C.questions) {
    const got = c.ask === 'accepted' ? sp.acceptedIn(c.sockets, c.server, c.client, 'lsof') : sp.listenerIn(c.sockets, c.port, 'lsof');
    assert.deepEqual(brief(got), c.expect, c.name);
  }
});

test('off macOS and for a set-uid reader nothing is proved', async () => {
  assert.deepEqual(brief(await sp.accepted(['127.0.0.1', 47311], ['127.0.0.1', 50001], { platform: 'linux', uid: OWN, euid: OWN })),
    { proved: false, pid: null, reason: 'table-restricted: unsupported-platform' });
  const run = () => assert.fail('lsof must not run');
  assert.deepEqual(brief(await sp.ownListener(47311, { ...darwin, euid: 0, run })),
    { proved: false, pid: null, reason: 'table-restricted: setuid-context' });
});

test('lsof is asked for this account\'s sockets on the port, by state', async () => {
  const calls = [];
  const run = (text) => async (file, args) => { calls.push([file, ...args]); return text; };
  const got = await sp.accepted(['127.0.0.1', 47311], ['127.0.0.1', 50001], { ...darwin, run: run(C.lsof[0].text) });
  assert.deepEqual(brief(got), { proved: true, pid: 4100, reason: null });
  assert.equal(got.method, 'lsof');
  assert.deepEqual(calls, [[sp.LSOF, '-nP', '-a', '-u', String(OWN), '-iTCP:47311', '-sTCP:ESTABLISHED', '-F', 'pun']]);
  calls.length = 0;
  assert.deepEqual(brief(await sp.ownListener(47311, { ...darwin, run: run(C.lsof[1].text) })), { proved: true, pid: 4100, reason: null });
  assert.deepEqual(calls, [[sp.LSOF, '-nP', '-a', '-u', String(OWN), '-iTCP:47311', '-sTCP:LISTEN', '-F', 'pun']]);
});

test('a server that accepts late is waited for briefly; without the wait one read answers', async () => {
  let n = 0;
  const texts = ['', '', C.lsof[0].text];
  const run = async () => texts[Math.min(n++, 2)];
  assert.equal((await sp.accepted(['127.0.0.1', 47311], ['127.0.0.1', 50001], { ...darwin, wait: true, run })).proved, true);
  assert.equal(n, 3);
  n = 0;
  assert.deepEqual(brief(await sp.accepted(['127.0.0.1', 47311], ['127.0.0.1', 50001], { ...darwin, run: async () => { n += 1; return ''; } })),
    { proved: false, pid: null, reason: 'table-restricted' });
  assert.equal(n, 1);
});

test('a reader that fails proves nothing and names why', async () => {
  const run = async () => { throw new Error('lsof: exit 2'); };
  assert.deepEqual(brief(await sp.ownListener(47311, { ...darwin, run })), { proved: false, pid: null, reason: 'table-restricted: lsof: exit 2' });
});

test('it imports no other kit module', () => {
  const text = fs.readFileSync(path.join(here, '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-socket-proof.mjs'), 'utf8');
  assert.doesNotMatch(text, /from '\.\//);
});

test('a real connected pair of this process is proved by lsof', { skip: process.platform !== 'darwin' && 'lsof is macOS\'s' }, async () => {
  const server = net.createServer(() => {});
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  const client = net.connect({ host: '127.0.0.1', port });
  await new Promise((resolve) => client.once('connect', resolve));
  try {
    const got = await sp.accepted(['127.0.0.1', port], ['127.0.0.1', client.localPort], { wait: true });
    assert.deepEqual([got.proved, got.pid, got.method], [true, process.pid, 'lsof']);
    assert.deepEqual([(await sp.ownListener(port)).proved, (await sp.ownListener(port)).pid], [true, process.pid]);
    assert.equal((await sp.accepted(['127.0.0.1', port], ['127.0.0.1', 1])).proved, false);
  } finally {
    client.destroy();
    await new Promise((resolve) => server.close(resolve));
  }
});
