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

// What `ps -o uid= -p PID`, `whoami /user /fo csv /nh` and the owner-SID PowerShell print for the fixtures' pids.
async function fixtureRun(file, args) {
  if (file === 'whoami') return CASES.whoami;
  const pid = file.endsWith('ps') ? args[args.length - 1] : /ProcessId=([0-9]+)/.exec(args.join(' '))?.[1];
  const table = file.endsWith('ps') ? CASES.ps : CASES.ownerSid;
  if (table[pid] === undefined) throw new po.TableUnreadable(`${file}: exit 1`);
  return table[pid];
}

function opts(table) {
  return { read: async () => parsed(table), run: fixtureRun, ownUid: CASES.ownUid };
}

const fakeSocket = (client, server) => ({ localAddress: client[0], localPort: client[1], remoteAddress: server[0], remotePort: server[1] });

test('every shared case reads the owner the Python twin reads', async () => {
  let ran = 0;
  for (const [i, c] of CASES.cases.entries()) {
    if (!(c.twins ?? ['python', 'node']).includes('node')) continue;
    const table = CASES.tables[c.table];
    let o = { ...opts(table), ...(c.ownUid !== undefined ? { ownUid: c.ownUid } : {}), ...(c.ownPid !== undefined ? { ownPid: c.ownPid } : {}) };
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

test('both twins report one version', () => {
  const py = fs.readFileSync(new URL('../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_peer_owner.py', import.meta.url), 'utf8');
  assert.equal(po.PEER_OWNER_VERSION, /^PEER_OWNER_VERSION = "([^"]+)"/m.exec(py)[1]);
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
  assert.equal(po.parseWhoamiSid(CASES.whoami), 'S-1-5-21-1004336348-1177238915-682003330-1001');
  assert.equal(po.parseWhoamiSid('INFO: something else\r\n'), null);
  assert.equal(po.parseOwnerSid(CASES.ownerSid['6200']), 'S-1-5-21-1004336348-1177238915-682003330-1002');
  assert.equal(po.parseOwnerSid(''), null);
  assert.equal(po.parseOwnerSid('Access denied'), null);
  assert.match(po.ownerSidScript(4100), /ProcessId=4100'/);
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
  // a client running as root owns root's listener; launchd's pid 1 stays system (0.74.0 seam reading 2)
  assert.equal(po.classify(0, 300, { method: 'x', ownUid: 0 }).kind, po.THIS_ACCOUNT);
  assert.equal(po.classify(0, 1, { method: 'x', ownUid: 0 }).kind, po.SYSTEM);
  assert.equal(po.classifySid('S-1-5-18', 50, { ownSid: 'S-1-5-18' }).kind, po.THIS_ACCOUNT);
  const own = 'S-1-5-21-1-2-3-1001';
  assert.equal(po.classifySid(own, 50, { ownSid: own }).kind, po.THIS_ACCOUNT);
  assert.equal(po.classifySid('S-1-5-21-1-2-3-1002', 50, { ownSid: own }).kind, po.ANOTHER_ACCOUNT);
  assert.equal(po.classifySid('S-1-5-18', 50, { ownSid: own }).kind, po.SYSTEM);
  assert.equal(po.classifySid(null, 4, { ownSid: own }).kind, po.SYSTEM);
  assert.equal(po.classifySid(null, 50, { ownSid: own }).reason, 'process-not-readable');
  // Two Cyrillic names in cp866 ('иван', 'олег') decode to one string as UTF-8. Only SIDs are compared, so a name
  // never stands for an account, and a garbled one never reads as this account.
  const ivan = Buffer.from([0xA8, 0xA2, 0xA0, 0xAD]).toString('utf8');
  const oleg = Buffer.from([0xAE, 0xAB, 0xA5, 0xA3]).toString('utf8');
  assert.equal(ivan, oleg);
  assert.equal(po.classifySid(ivan, 50, { ownSid: oleg }).kind, po.UNKNOWN);
  assert.equal(po.classifySid(own, 50, { ownSid: ivan }).kind, po.ANOTHER_ACCOUNT);
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
    [{ ownUid: 424242, ownSid: 'S-1-5-21-9-9-9-424242' }, po.SERVER_NOT_OWN],
    // Every row owned by uid 0: the server reads system.
    [{ read: async () => ({ rows: (await po.readTable()).rows.map((r) => ({ ...r, uid: 0 })), how: 'proc' }), ownUid: 424242 }, po.SERVER_NOT_OWN],
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
  const connections = [];
  server.on('connection', (s) => connections.push(s.remotePort));
  t.after(() => server.close());
  const socket = await po.checkedSocket(port);
  const checkedPort = socket.localPort;
  // No `agent` option: with `agent: false` Node ignores createConnection and dials a second, unchecked connection
  // (0.74.0 unit reading 2).
  const status = await new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path: '/', createConnection: () => socket,
      headers: { Authorization: 'Bearer synthetic', Connection: 'close' } }, (res) => { res.resume(); res.on('end', () => resolve(res.statusCode)); });
    req.on('error', reject);
    req.end();
  });
  assert.equal(status, 204);
  assert.deepEqual(received, ['Bearer synthetic']);
  assert.deepEqual(connections, [checkedPort], 'one connection, the checked one, carried the bearer');
  socket.destroy();
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

test('a connection not yet accepted reads its listener\'s owner (0.74.0 unit reading 3)', { skip: !['darwin', 'linux'].includes(process.platform) }, async (t) => {
  // A listening socket nobody calls accept() on: Linux prints such a connection's server end with uid 0, inode 0.
  const { spawn } = await import('node:child_process');
  const holder = spawn('python3', ['-c', "import socket,time\ns=socket.socket()\ns.bind(('127.0.0.1',0))\ns.listen(8)\n"
    + "print(s.getsockname()[1],flush=True)\ntime.sleep(60)"], { stdio: ['ignore', 'pipe', 'inherit'] });
  t.after(() => holder.kill());
  const port = await new Promise((r) => holder.stdout.once('data', (d) => r(Number(String(d).trim()))));
  for (let i = 0; i < 5; i += 1) {
    const socket = await po.checkedSocket(port);
    socket.destroy();
  }
});

test('a connection past the first page of /proc/net/tcp is found (0.74.0 seam reading 5, Node 18)', { skip: !['darwin', 'linux'].includes(process.platform) }, async (t) => {
  // Node 18's readFile returned only the first ~4 KB of a /proc file: every socket past the 26th or so read no-row.
  const server = net.createServer(() => {});
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const clients = [];
  t.after(() => { for (const c of clients) c.destroy(); server.close(); });
  for (let i = 0; i < 60; i += 1) {
    clients.push(await new Promise((r) => { const s = net.connect(server.address().port, '127.0.0.1', () => r(s)); }));
  }
  const who = await po.serverEnd(clients[clients.length - 1]);
  assert.deepEqual([who.kind, who.uid], [po.THIS_ACCOUNT, process.getuid()]);
});

test('a caller option named server never turns peerAt into a server-end reading (0.74.0 seam reading 5)', async () => {
  const c = CASES.cases.find((x) => x.table === 'procClosedClient' && x.ask === 'peerAt');
  assert.ok(c, 'the shared cases hold a closed client');
  const who = await po.peerAt(c.server, c.client, { ...opts(CASES.tables.procClosedClient), server: {} });
  assert.deepEqual([who.kind, who.reason], [po.UNKNOWN, 'closed']);
});

test('a /proc read that missed the row is read once more; netstat is taken as it comes (0.74.0 seam reading 6)', async () => {
  const empty = { rows: [], how: 'proc' };
  const whole = parsed(CASES.tables.procPrintedTwice);
  const c = CASES.cases.find((x) => x.table === 'procPrintedTwice' && x.ask === 'serverEnd');
  let reads = 0;
  const once = { ...opts(CASES.tables.procPrintedTwice), read: async () => (reads++ === 0 ? empty : whole) };
  const who = await po.serverEnd(fakeSocket(c.client, c.server), once);
  assert.deepEqual([who.kind, reads], [po.THIS_ACCOUNT, 2]);
  let netstatReads = 0;
  const netstat = { ...opts(CASES.tables.netstatMulti), read: async () => { netstatReads += 1; return { rows: [], how: 'netstat' }; } };
  assert.equal((await po.serverEnd(fakeSocket(c.client, c.server), netstat)).reason, po.NO_ROW_RESTRICTED);
  assert.equal(netstatReads, 1);
});

test('a real own listener reads this-account on Windows too', { skip: process.platform !== 'win32' }, async (t) => {
  const server = net.createServer(() => {});
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  t.after(() => server.close());
  const who = await po.listener(server.address().port);
  assert.deepEqual([who.kind, who.pid, who.method], [po.THIS_ACCOUNT, process.pid, 'netstat-windows']);
});

test('the hub client sends no bearer to a door another account holds, and does to its own', async (t) => {
  const { postMcp, HubError } = await import('../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-hub.mjs');
  const { server, received, port } = await recorder();
  t.after(() => server.close());
  const origin = `http://127.0.0.1:${port}`;
  for (const ask of [{ ownUid: 424242, ownSid: 'S-1-5-21-9-9-9-424242' }, { read: async () => { throw new po.TableUnreadable('netstat: exit 1'); } }]) {
    const agent = new po.CheckedAgent({ ask });
    t.after(() => agent.destroy());
    await assert.rejects(postMcp(origin, { jsonrpc: '2.0', id: 1, method: 'ping' }, 'synthetic', { agent }),
      (err) => err instanceof HubError && err.code === 'foreign-user' && err.retryable === true);
  }
  assert.deepEqual(received, []);
  const answer = await postMcp(origin, { jsonrpc: '2.0', id: 1, method: 'ping' }, 'synthetic');
  assert.equal(answer.status, 204);
  assert.deepEqual(received, ['Bearer synthetic']);
});

test('only ASCII digits are numbers, and a header-only netstat is a restricted table (FAA-273 items 3 and 4)', () => {
  assert.deepEqual(po.parseLsofListeners('n127.0.0.1:\u0664\u0667\u0664\u0668\u0660\nn*:5\u00b2\nn*:80\n'), [['*', 80]]);
  assert.equal(po.parsePsUid('\u0665\u0660\u0661'), null);
  assert.equal(po.parsePsUid('\uff15\uff10\uff11'), null);
  assert.equal(po.parsePsUid(' 501\n'), 501);
  const header = 'Active Internet connections (including servers)\n'
    + 'Proto Recv-Q Send-Q  Local Address          Foreign Address        (state)      rhiwat  shiwat    pid   epid  state  options  gencnt  flags  flags1 usscnt rtncnt fltrs process:pid\n';
  assert.throws(() => po.parseNetstat(header), (err) => err instanceof po.TableUnreadable && err.message.startsWith(po.TABLE_RESTRICTED));
});

test('a restricted table answers table-restricted, and a vouched pid that listens passes (FAA-267)', async (t) => {
  assert.throws(() => po.parseNetstat(''), (err) => err instanceof po.TableUnreadable && err.message.startsWith(po.TABLE_RESTRICTED));
  assert.deepEqual(po.parseLsofListeners('p78564\nf4\nn127.0.0.1:47480\nn*:5000\nn[::1]:7\nnoise\n'),
    [['127.0.0.1', 47480], ['*', 5000], ['::1', 7]]);
  const { server, received, port } = await recorder();
  t.after(() => server.close());
  const restricted = { read: async () => { throw new po.TableUnreadable(`${po.TABLE_RESTRICTED}: netstat printed nothing to this process`); } };
  const lsof = (listens) => async (file) => (file === po.PS ? '501\n' : `p4242\nn127.0.0.1:${listens}\n`);
  // No vouch: unknown, fail closed.
  await assert.rejects(po.checkedSocket(port, restricted), (err) => err instanceof po.ListenerRefused && err.code === po.SERVER_UNVERIFIED);
  // A vouched pid that does not listen on this port: still refused.
  await assert.rejects(po.checkedSocket(port, { ...restricted, vouchPid: 4242, platform: 'darwin', ownUid: 501, ownEuid: 501, run: lsof(port + 1) }),
    (err) => err instanceof po.ListenerRefused && err.code === po.SERVER_UNVERIFIED);
  // A vouched pid of another account: refused.
  await assert.rejects(po.checkedSocket(port, { ...restricted, vouchPid: 4242, platform: 'darwin', ownUid: 502, ownEuid: 502, run: lsof(port) }),
    (err) => err instanceof po.ListenerRefused && err.code === po.SERVER_UNVERIFIED);
  // This account's vouched pid holds the listener: the socket is handed over.
  const socket = await po.checkedSocket(port, { ...restricted, vouchPid: 4242, platform: 'darwin', ownUid: 501, ownEuid: 501, run: lsof(port) });
  socket.destroy();
  assert.deepEqual(received, []);
});

test('a vouch is an integer pid of this account, and lsof is asked for IPv4 alone (FAA-267)', async () => {
  const calls = [];
  let listens = 'p4242\nf4\nn127.0.0.1:80\n';
  const run = async (file, args) => { calls.push(args); return file === po.PS ? '501\n' : listens; };
  for (const pid of ['4242', true, null, 1, 0, -5]) {
    assert.equal(await po.pidListens(pid, 80, { run, platform: 'darwin', ownUid: 501, ownEuid: 501 }), false, String(pid));
  }
  assert.equal(await po.pidListens(4242, 80, { run, platform: 'darwin', ownUid: 501, ownEuid: 501 }), true);
  assert.equal(await po.pidListens(4242, 81, { run, platform: 'darwin', ownUid: 501, ownEuid: 501 }), false);
  assert.equal(await po.pidListens(4242, 80, { run, platform: 'linux', ownUid: 501, ownEuid: 501 }), false);
  // FAA-312, DEC-0155 RT-3: only a listen on exactly 127.0.0.1 is vouched for, never the IPv4 wildcard nor ::1.
  for (const text of ['p4242\nf4\nn*:80\n', 'p4242\nf4\nn[::1]:80\n']) {
    listens = text;
    assert.equal(await po.pidListens(4242, 80, { run, platform: 'darwin', ownUid: 501, ownEuid: 501 }), false, text);
  }
  listens = 'p4242\nf4\nn127.0.0.1:80\n';
  // DEC-0155: a reader whose real and effective uid differ vouches for nothing.
  assert.equal(await po.pidListens(4242, 80, { run, platform: 'darwin', ownUid: 501, ownEuid: 0 }), false);
  assert.ok(calls.at(-1).includes('-i4TCP') && !calls.at(-1).includes('-iTCP'), calls.at(-1).join(' '));
});

test('a netstat that fails is a restricted table (FAA-312, DEC-0155 RT-1)', async () => {
  for (const failure of ['netstat: exit 1', 'netstat: timeout', 'netstat: ENOENT']) {
    const run = async (file) => { if (file === po.NETSTAT) throw new po.TableUnreadable(failure); return '501\n'; };
    await assert.rejects(po.readTable({ run, platform: 'darwin' }), (err) => err instanceof po.TableUnreadable
      && err.message === `${po.TABLE_RESTRICTED}: ${failure}`);
  }
  // A Linux or Windows reader never reads its table so.
  assert.equal(po.restricted([], 'proc'), false);
  assert.equal(po.restricted([], 'netstat-windows'), false);
});

test('a table of this process alone is restricted (FAA-312, DEC-0155 RT-1)', () => {
  const row = (pid) => ({ local: ['127.0.0.1', 47311], remote: ['*', 0], listening: true, uid: null, pid, timeWait: false });
  assert.equal(po.restricted([row(77)], 'netstat', { ownPid: 77 }), true);
  assert.equal(po.restricted([row(77), row(78)], 'netstat', { ownPid: 77 }), false);
  assert.equal(po.restricted([row(null)], 'netstat', { ownPid: 77 }), true);
  assert.equal(po.restricted([], 'netstat', { ownPid: 77 }), true);
  assert.equal(po.restricted([row(78)], 'netstat'), process.pid === 78);
});

test('the CLI prints the listener\'s kind (FAA-315)', async () => {
  const { execFileSync, spawnSync } = await import('node:child_process');
  const { fileURLToPath } = await import('node:url');
  const script = fileURLToPath(new URL('../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-peer-owner.mjs', import.meta.url));
  const server = net.createServer(() => {});
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  try {
    const kind = execFileSync(process.execPath, [script, 'listener', String(server.address().port)],
      { encoding: 'utf8' }).trim();
    assert.ok(po.KINDS.includes(kind), kind);
    if (process.platform !== 'darwin') assert.equal(kind, po.THIS_ACCOUNT);
    const json = JSON.parse(execFileSync(process.execPath, [script, 'listener',
      String(server.address().port), '--json'], { encoding: 'utf8' }));
    assert.equal(json.kind, kind);
  } finally {
    server.close();
  }
  for (const args of [[], ['listener'], ['listener', 'x'], ['listener', '0'], ['listener', '65536'], ['peer', '1']]) {
    const done = spawnSync(process.execPath, [script, ...args], { encoding: 'utf8' });
    assert.equal(done.status, 2, args.join(' '));
    assert.match(done.stderr, /usage/);
  }
  const out = [];
  assert.equal(await po.main(['listener', '47311'], { listener: async () => po.owner(po.NONE), write: (t) => out.push(t) }), 0);
  assert.deepEqual(out, ['none\n']);
});
