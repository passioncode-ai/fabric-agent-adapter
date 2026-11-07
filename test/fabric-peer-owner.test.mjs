// FAA-226 (DEC-0154 HA-2): fabric-peer-owner.mjs, the Node twin of fabric_peer_owner.py, on the tables and questions
// the Python twin reads too (test/fixtures/peer-owner/peer-owner-cases.json), a real loopback pair, and a checked
// socket that refuses before a byte is written.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import test from 'node:test';
import * as po from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-peer-owner.mjs';

const CASES = JSON.parse(fs.readFileSync(new URL('./fixtures/peer-owner/peer-owner-cases.json', import.meta.url), 'utf8'));

function parsed(table) {
  if (table.kind === 'netstat') return { rows: po.parseNetstat(table.text), how: 'netstat' };
  if (table.kind === 'windows') return { rows: po.parseWindowsNetstat(table.text), how: 'netstat-windows' };
  return { rows: po.parseProcNetTcp(table.text, { family: table.kind === 'proc4' ? 4 : 6, byteorder: 'little' }), how: 'proc' };
}

// What `ps -o uid= -p PID` and `tasklist ... /fi "PID eq N"` print for the fixtures' pids.
async function fixtureRun(file, args) {
  const pid = file.endsWith('ps') ? args[args.length - 1] : /PID eq ([0-9]+)/.exec(args.join(' '))?.[1];
  const table = file.endsWith('ps') ? CASES.ps : CASES.tasklist;
  if (table[pid] === undefined) throw new po.TableUnreadable(`${file}: exit 1`);
  return table[pid];
}

function opts(table) {
  return { read: async () => parsed(table), run: fixtureRun, ownUid: CASES.ownUid, ownUser: CASES.ownUser };
}

const fakeSocket = (client, server) => ({ localAddress: client[0], localPort: client[1], remoteAddress: server[0], remotePort: server[1] });

test('every shared case reads the owner the Python twin reads', async () => {
  let ran = 0;
  for (const [i, c] of CASES.cases.entries()) {
    if (!(c.twins ?? ['python', 'node']).includes('node')) continue;
    const table = CASES.tables[c.table];
    let o = opts(table);
    try {
      parsed(table);
    } catch (err) {
      o = { ...o, read: async () => { throw err; } };
    }
    let got;
    if (c.ask === 'listener') got = await po.listener(c.port, o);
    else if (c.ask === 'peerAt') got = await po.peerAt(c.server, c.client, o);
    else got = await po.serverEnd(fakeSocket(c.client, c.server), o);
    assert.deepEqual(Object.fromEntries(Object.keys(c.want).map((k) => [k, got[k]])), c.want, `case ${i} ${c.table} ${c.ask}`);
    ran += 1;
  }
  assert.ok(ran >= 28, `ran ${ran}`);
});

test('addresses have the same spelling in both twins', () => {
  for (const [raw, want] of CASES.normHost) assert.equal(po.normHost(raw), want, raw);
});

test('the parsers', () => {
  const rows = po.parseNetstat(CASES.tables.netstatMulti.text);
  assert.equal(rows.length, 9);
  assert.deepEqual(rows.filter((r) => r.listening).map((r) => [r.local, r.pid]),
    [[['127.0.0.1', 47311], 4100], [['::1', 47070], 4400], [['127.0.0.1', 8021], 1], [['*', 47555], 300]]);
  assert.throws(() => po.parseNetstat(CASES.tables.netstatNoProcess.text), po.TableUnreadable);
  assert.equal(po.parsePsUid('  502\n'), 502);
  assert.equal(po.parsePsUid(''), null);
  const win = po.parseWindowsNetstat(CASES.tables.windowsGerman.text);
  assert.equal(win.length, 10);
  assert.deepEqual(win.filter((r) => r.timeWait).map((r) => r.local), [['127.0.0.1', 50003]]);
  assert.equal(po.parseTasklistUser(CASES.tasklist['6200'], 6200), 'EXAMPLE-PC\\other');
  assert.equal(po.parseTasklistUser(CASES.tasklist['6200'], 6201), null);
  assert.equal(po.parseTasklistUser('INFO: No tasks are running which match the specified criteria.\r\n', 7), null);
});

test('two live rows, two listeners, a gone process and an unreadable table are unknown', async () => {
  const two = { read: async () => ({ how: 'proc', rows: [
    { local: ['127.0.0.1', 50002], remote: ['127.0.0.1', 47311], listening: false, uid: 501, pid: null, timeWait: false },
    { local: ['127.0.0.1', 50002], remote: ['127.0.0.1', 47311], listening: false, uid: 502, pid: null, timeWait: false },
    { local: ['127.0.0.1', 47311], remote: ['*', 0], listening: true, uid: 501, pid: null, timeWait: false },
    { local: ['127.0.0.1', 47311], remote: ['*', 0], listening: true, uid: 502, pid: null, timeWait: false },
  ] }), ownUid: 501 };
  assert.equal((await po.peerAt(['127.0.0.1', 47311], ['127.0.0.1', 50002], two)).reason, 'several-rows');
  assert.equal((await po.listener(47311, two)).reason, 'several-rows');
  const gone = { read: async () => ({ how: 'netstat', rows: [
    { local: ['127.0.0.1', 50002], remote: ['127.0.0.1', 47311], listening: false, uid: null, pid: 9999, timeWait: false }] }),
  run: fixtureRun, ownUid: 501 };
  const who = await po.peerAt(['127.0.0.1', 47311], ['127.0.0.1', 50002], gone);
  assert.deepEqual([who.kind, who.reason], ['unknown', 'process-gone']);
  const broken = { read: async () => { throw new po.TableUnreadable('netstat: exit 1'); } };
  assert.deepEqual(await po.listener(47311, broken), po.owner('unknown', { method: po.method(), reason: 'netstat: exit 1' }));
});

test('classification and refusals', () => {
  assert.equal(po.classify(0, 300, { method: 'x', ownUid: 501 }).kind, po.SYSTEM);
  assert.equal(po.classify(501, 1, { method: 'x', ownUid: 501 }).kind, po.SYSTEM);
  assert.equal(po.classify(501, 9, { method: 'x', ownUid: 501 }).kind, po.THIS_ACCOUNT);
  assert.equal(po.classify(502, 9, { method: 'x', ownUid: 501 }).kind, po.ANOTHER_ACCOUNT);
  assert.equal(po.classifyWindowsUser('NT AUTHORITY\\SYSTEM', 700, { ownUser: 'pc\\me' }).kind, po.SYSTEM);
  assert.equal(po.classifyWindowsUser('PC\\Me', 700, { ownUser: 'pc\\me' }).kind, po.THIS_ACCOUNT);
  assert.equal(po.refusal(po.owner(po.ANOTHER_ACCOUNT), 1)[0], po.SERVER_NOT_OWN);
  assert.equal(po.refusal(po.owner(po.SYSTEM), 1)[0], po.SERVER_NOT_OWN);
  assert.equal(po.refusal(po.owner(po.UNKNOWN, { reason: 'no-row' }), 1)[0], po.SERVER_UNVERIFIED);
  assert.equal(po.refusal(po.owner(po.NONE), 1)[0], po.SERVER_UNVERIFIED);
  assert.equal(po.refusal(po.owner(po.THIS_ACCOUNT, { pid: 9 }), 1, 10)[0], po.SERVER_NOT_THIS_WORKSPACE);
  assert.equal(po.refusal(po.owner(po.THIS_ACCOUNT, { pid: 9 }), 1, 9), null);
  assert.deepEqual(po.KINDS, ['this-account', 'another-account', 'system', 'unknown', 'none']);
});

async function recorder() {
  const received = [];
  const server = http.createServer((req, res) => { received.push(req.headers.authorization ?? null); res.writeHead(204).end(); });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  return { server, received, port: server.address().port };
}

test('a checked socket refuses another account\'s server before a byte is written', async (t) => {
  const { server, received, port } = await recorder();
  t.after(() => server.close());
  const refused = [
    // The live table, read as if this process were another account: its own server reads another-account.
    [{ ownUid: 424242, ownUser: 'example-pc\\nobody' }, po.SERVER_NOT_OWN],
    // Every row owned by uid 0: the server reads system.
    [{ read: async () => ({ rows: (await po.readTable()).rows.map((r) => ({ ...r, uid: 0 })), how: 'proc' }) }, po.SERVER_NOT_OWN],
    // A table that cannot be read: unknown, fail closed.
    [{ read: async () => { throw new po.TableUnreadable('netstat: exit 1'); } }, po.SERVER_UNVERIFIED],
  ];
  for (const [ask, code] of refused) {
    await assert.rejects(po.checkedSocket(port, ask), (err) => err instanceof po.ListenerRefused && err.code === code, code);
  }
  assert.deepEqual(received, []);
});

test('this account\'s server gets the request on the checked socket', async (t) => {
  const { server, received, port } = await recorder();
  t.after(() => server.close());
  const socket = await po.checkedSocket(port);
  const status = await new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path: '/', agent: false, createConnection: () => socket,
      headers: { Authorization: 'Bearer synthetic' } }, (res) => { res.resume(); res.on('end', () => resolve(res.statusCode)); });
    req.on('error', reject);
    req.end();
  });
  assert.equal(status, 204);
  assert.deepEqual(received, ['Bearer synthetic']);
});

test('both ends of a real pair and the listener are this account', { skip: !['darwin', 'linux'].includes(process.platform) }, async (t) => {
  const accepted = [];
  const server = net.createServer((s) => accepted.push(s));
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const client = net.connect(server.address().port, '127.0.0.1');
  await new Promise((r) => client.once('connect', r));
  while (!accepted.length) await new Promise((r) => setTimeout(r, 5));
  t.after(() => { client.destroy(); accepted[0].destroy(); server.close(); });
  const want = process.platform === 'darwin' ? 'netstat' : 'proc';
  for (const who of [await po.peer(accepted[0]), await po.serverEnd(client), await po.listener(server.address().port)]) {
    assert.deepEqual([who.kind, who.uid, who.method], [po.THIS_ACCOUNT, process.getuid(), want]);
  }
  if (process.platform === 'darwin') assert.equal((await po.peer(accepted[0])).pid, process.pid);
});

test('a real own listener reads this-account on Windows too', { skip: process.platform !== 'win32' }, async (t) => {
  const server = net.createServer(() => {});
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  t.after(() => server.close());
  const who = await po.listener(server.address().port);
  assert.deepEqual([who.kind, who.pid, who.method], [po.THIS_ACCOUNT, process.pid, 'netstat-windows']);
});
