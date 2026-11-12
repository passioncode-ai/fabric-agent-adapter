// FAA-227 (DEC-0154 HA-2's server side, HA-3): the Node twin of LoopbackHTTPServer's peer check. loopbackServer hands
// a connection to the HTTP server only after its peer's owner is told; another OS account's peer is destroyed unread.
// The owner is faked; the connection is real.
import assert from 'node:assert/strict';
import http from 'node:http';
import test from 'node:test';
import * as d from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-descriptor.mjs';
import * as po from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-peer-owner.mjs';

const owner = (kind, uid = null, pid = null, reason = null) => po.owner(kind, { uid, pid, method: 'test', reason });

async function serving(peer, opts = {}, fn) {
  const calls = [];
  const app = http.createServer((req, res) => { calls.push(d.connectionOwner(req.socket)); res.end('ok'); });
  const refused = [];
  const gate = d.loopbackServer(app, { peer: typeof peer === 'function' ? peer : async () => peer, onRefused: (who, why) => refused.push([who, why]), ...opts });
  await new Promise((resolve) => gate.listen({ port: 0, host: '127.0.0.1' }, resolve));
  try {
    return await fn(gate.address().port, calls, refused, gate);
  } finally {
    app.closeAllConnections?.();
    await new Promise((resolve) => gate.close(resolve));
  }
}

function get(port) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: '127.0.0.1', port, path: '/', agent: false }, (res) => { res.resume(); res.on('end', () => resolve(res.statusCode)); });
    req.on('error', reject);
  });
}

test('the verdicts are the Python twin\'s', () => {
  assert.equal(d.connectionRefusal(owner(po.ANOTHER_ACCOUNT, 502)), po.ANOTHER_ACCOUNT);
  for (const kind of [po.THIS_ACCOUNT, po.SYSTEM, po.UNKNOWN]) assert.equal(d.connectionRefusal(owner(kind)), null, kind);
  assert.equal(d.connectionRefusal(owner(po.SYSTEM, 0, 1), 'strict'), null);
  assert.equal(d.connectionRefusal(owner(po.SYSTEM, null, 4), 'strict'), po.SYSTEM);
  assert.equal(d.connectionRefusal(owner(po.UNKNOWN, null, null, 'table-restricted'), 'strict'), 'table-restricted');
  assert.equal(d.connectionRefusal(owner(po.ANOTHER_ACCOUNT), 'off'), null);
  assert.throws(() => d.connectionRefusal(null, 'label'), /peerCheck must be one of/);
  assert.throws(() => d.loopbackServer(http.createServer(), { peerCheck: 'maybe' }), /peerCheck must be one of/);
  assert.deepEqual([...d.PEER_CHECKS], ['refuse', 'strict', 'off']);
});

test('another account\'s peer is destroyed before the HTTP server reads it', async () => {
  await serving(owner(po.ANOTHER_ACCOUNT, 502, 77), {}, async (port, calls, refused, gate) => {
    await assert.rejects(get(port));
    assert.deepEqual(calls, []);
    assert.equal(gate.peerRefusals, 1);
    assert.equal(refused[0][1], po.ANOTHER_ACCOUNT);
  });
});

test('this account\'s peer is served and labelled', async () => {
  const mine = owner(po.THIS_ACCOUNT, 501, 9);
  await serving(mine, {}, async (port, calls) => {
    assert.equal(await get(port), 200);
    assert.deepEqual(calls, [mine]);
  });
});

test('an unknown owner is served by default and refused when strict', async () => {
  const unknown = owner(po.UNKNOWN, null, null, 'table-restricted');
  await serving(unknown, {}, async (port, calls) => {
    assert.equal(await get(port), 200);
    assert.deepEqual(calls, [unknown]);
  });
  await serving(unknown, { peerCheck: 'strict' }, async (port, calls, refused) => {
    await assert.rejects(get(port));
    assert.deepEqual(calls, []);
    assert.equal(refused[0][1], 'table-restricted');
  });
});

test('a reader that throws is an unknown owner, never a crash; off never reads', async () => {
  await serving(async () => { throw new Error('table'); }, {}, async (port, calls) => {
    assert.equal(await get(port), 200);
    assert.equal(calls[0].kind, po.UNKNOWN);
    assert.equal(calls[0].reason, 'reader: Error');
  });
  await serving(async () => { throw new Error('read under off'); }, { peerCheck: 'off' }, async (port, calls) => {
    assert.equal(await get(port), 200);
    assert.deepEqual(calls, [null]);
  });
});

test('the default reader is the socket table: this process is never another account', async () => {
  const app = http.createServer((req, res) => { res.end(String(d.connectionOwner(req.socket)?.kind)); });
  const gate = d.loopbackServer(app);
  await new Promise((resolve) => gate.listen({ port: 0, host: '127.0.0.1' }, resolve));
  try {
    const body = await new Promise((resolve, reject) => {
      http.get({ host: '127.0.0.1', port: gate.address().port, agent: false }, (res) => {
        let text = ''; res.on('data', (c) => { text += c; }); res.on('end', () => resolve(text));
      }).on('error', reject);
    });
    assert.ok([po.THIS_ACCOUNT, po.UNKNOWN].includes(body), body);
  } finally {
    app.closeAllConnections?.();
    await new Promise((resolve) => gate.close(resolve));
  }
});
