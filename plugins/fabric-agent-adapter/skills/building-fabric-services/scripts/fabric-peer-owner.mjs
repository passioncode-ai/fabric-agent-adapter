// Which OS account owns each end of a loopback TCP connection (DEC-0154 HA-2, FAA-226, layer L0); the twin of
// fabric_peer_owner.py, which is Project Observatory's peer_owner 1.1.0 vendored by commit. Node 20+, no dependency;
// nothing here imports another kit module.
//
// WHY. Loopback is one per computer, not one per OS account: every account's processes reach every listener on
// 127.0.0.1, so a loopback socket proves nothing about who is on the other end. A client about to send a credential
// to http://127.0.0.1:<port>, and a host about to call a local service healthy, first tells the owner of the server
// end of its own connection from the computer's socket table, read without privileges:
//
//   await listener(port)             who listens on 127.0.0.1:<port> (also 0.0.0.0, ::1, ::)
//   await serverEnd(socket)          for a client's connected socket: who accepted it
//   await peer(socket)               for a server's accepted socket: who connected
//   await peerAt(server, client)     the same as peer, from two [host, port] addresses
//   await checkedSocket(port, opts)  a connected net.Socket whose server end is this account's, or ListenerRefused
//                                    (the socket destroyed) before a byte is written; hand it to http.request through
//                                    `createConnection: () => socket`
//
// `owner.kind` is this-account, another-account, system (uid 0, pid 1, Windows' pid 0 and 4 and its own accounts),
// unknown (`reason` says why) or none (listener only: nothing listens). A caller that must not leak treats everything
// but this-account as a refusal, unknown included: fail closed.
//
// HOW, ON EACH OS. Node has no ctypes, so it reads what the Python twin keeps as its fallback or reads the same files:
// - macOS: `/usr/sbin/netstat -anv -p tcp`, its process:pid column, then `ps -o uid= -p PID` for the one row a
//   question selects (Observatory measured about 20 ms over 846 sockets; it names root's listeners too).
// - Linux: `/proc/net/tcp` and `/proc/net/tcp6`, whose uid column every account may read.
// - Windows: `netstat -ano -p TCP` and `-p TCPv6` for the owning pid (a row whose peer port is 0 listens; a connected
//   row of pid 0 is TIME_WAIT, the idle process's, never an answer; the state column is localized and not read), then
//   `tasklist /v /fo csv /nh /fi "PID eq N"` for its account, compared with `whoami` without case. A process tasklist
//   cannot read (`N/A`) is unknown.
// Every read is bounded (MAX_TABLE_BYTES, a timeout per program) and never cached across connections; only listener
// is cached, for LISTENER_TTL_MS. A TIME_WAIT row is never an answer; two live rows with the same addresses are
// unknown (several-rows), never a guess. It never reads a byte from the socket it is asked about and needs no
// privilege. The parsers are pure functions over captured text (test/fixtures/peer-owner/).

import { execFile } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import net from 'node:net';
import os from 'node:os';

export const PEER_OWNER_VERSION = '1.1.0';
export const THIS_ACCOUNT = 'this-account';
export const ANOTHER_ACCOUNT = 'another-account';
export const SYSTEM = 'system';
export const UNKNOWN = 'unknown';
export const NONE = 'none';
export const KINDS = Object.freeze([THIS_ACCOUNT, ANOTHER_ACCOUNT, SYSTEM, UNKNOWN, NONE]);
export const MAX_TABLE_BYTES = 4 * 1024 * 1024;
export const TIMEOUT_MS = 2000;
export const WINDOWS_TIMEOUT_MS = 5000;
export const LISTENER_TTL_MS = 1000;
export const NETSTAT = '/usr/sbin/netstat';
export const PS = '/bin/ps';
export const SERVER_NOT_OWN = 'server-not-own';
export const SERVER_UNVERIFIED = 'server-unverified';
export const SERVER_NOT_THIS_WORKSPACE = 'server-not-this-workspace';

export function owner(kind, { uid = null, pid = null, method = 'none', reason = null } = {}) {
  return Object.freeze({ kind, uid, pid, method, reason });
}

export class TableUnreadable extends Error {
  constructor(message) { super(message); this.name = 'TableUnreadable'; }
}

export class ListenerRefused extends Error {
  constructor(code, message, who = null) { super(message); this.name = 'ListenerRefused'; this.code = code; this.owner = who; }
}

// -- addresses --------------------------------------------------------------------------------------------------------

// One spelling per address: an IPv4-mapped IPv6 address is its IPv4 form, the unspecified address is `*`, localhost is
// 127.0.0.1, an IPv6 address is RFC 5952's (as the Python twin's ipaddress prints it). Anything else stays as it is.
export function normHost(host) {
  let h = String(host ?? '');
  if (h === '*' || h === '') return '*';
  if (h === 'localhost') return '127.0.0.1';
  h = h.split('%', 1)[0];
  if (net.isIPv4(h)) return h === '0.0.0.0' ? '*' : h.split('.').map((x) => String(Number(x))).join('.');
  if (!net.isIPv6(h)) return h;
  const text = new URL(`http://[${h}]/`).hostname.slice(1, -1);
  if (text === '::') return '*';
  const mapped = /^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/.exec(text);
  if (mapped) {
    const hi = parseInt(mapped[1], 16);
    const lo = parseInt(mapped[2], 16);
    return [hi >> 8, hi & 255, lo >> 8, lo & 255].join('.');
  }
  return text;
}

const address = (host, port) => [normHost(host), Number(port)];
const same = (a, b) => a[0] === b[0] && a[1] === b[1];

// -- classification ---------------------------------------------------------------------------------------------------

function ownUid() {
  return typeof process.getuid === 'function' ? process.getuid() : null;
}

export function classify(uid, pid, { method, ownUid: own } = {}) {
  if (uid === null || uid === undefined) return owner(UNKNOWN, { pid, method, reason: 'no-owner' });
  const mine = own === undefined || own === null ? ownUid() : own;
  if (uid === 0 || pid === 1) return owner(SYSTEM, { uid, pid, method });
  if (mine !== null && uid === mine) return owner(THIS_ACCOUNT, { uid, pid, method });
  return owner(ANOTHER_ACCOUNT, { uid, pid, method });
}

// Windows: pid 0 and 4 and the system's own accounts are system, this user's name this-account, a name tasklist could
// not read unknown, any other name another-account. Names compare without case (tasklist and whoami differ in it).
const WINDOWS_SYSTEM_NAMES = new Set(['nt authority\\system', 'nt authority\\local service', 'nt authority\\network service']);

export function classifyWindowsUser(user, pid, { ownUser, method = 'netstat-windows' } = {}) {
  if (pid === 0 || pid === 4) return owner(SYSTEM, { pid, method });
  const name = typeof user === 'string' ? user.trim().toLowerCase() : '';
  if (!name || name === 'n/a') return owner(UNKNOWN, { pid, method, reason: 'process-not-readable' });
  if (WINDOWS_SYSTEM_NAMES.has(name)) return owner(SYSTEM, { pid, method });
  if (typeof ownUser === 'string' && name === ownUser.trim().toLowerCase()) return owner(THIS_ACCOUNT, { pid, method });
  return owner(ANOTHER_ACCOUNT, { pid, method });
}

// -- parsers: pure functions over captured text (the fixtures) --------------------------------------------------------

function netstatAddress(text) {
  const at = text.lastIndexOf('.');
  if (at < 0) return null;
  const port = text.slice(at + 1);
  if (port !== '*' && !/^[0-9]+$/.test(port)) return null;
  return [normHost(text.slice(0, at)), port === '*' ? 0 : Number(port)];
}

// `netstat -anv -p tcp` on macOS. Process names may hold spaces, so the process:pid column is what is left between the
// leading and the trailing columns, both counted from the header; a header without process:pid is unreadable.
export function parseNetstat(text) {
  const lines = String(text).split(/\r?\n/);
  const header = lines.findIndex((line) => line.includes('process:pid') && line.includes('Proto'));
  if (header < 0) throw new TableUnreadable('netstat-format: no process:pid column');
  const names = lines[header].split(/\s+/).filter(Boolean);
  const at = names.indexOf('process:pid');
  const leading = at - names.slice(0, at).filter((w) => w === 'Address').length;
  const trailing = names.length - at - 1;
  const rows = [];
  for (const line of lines.slice(header + 1)) {
    const tok = line.split(/\s+/).filter(Boolean);
    if (tok.length < leading + trailing + 1 || !tok[0].startsWith('tcp')) continue;
    const local = netstatAddress(tok[3]);
    const remote = netstatAddress(tok[4]);
    if (!local || !remote) continue;
    const proc = tok.slice(leading, tok.length - trailing).join(' ');
    let pid = null;
    const colon = proc.lastIndexOf(':');
    if (colon >= 0 && /^[0-9]+$/.test(proc.slice(colon + 1))) pid = Number(proc.slice(colon + 1));
    rows.push({ local, remote, listening: tok[5] === 'LISTEN', uid: null, pid, timeWait: tok[5] === 'TIME_WAIT' });
  }
  return rows;
}

// `ps -o uid= -p PID`: one number, or nothing when the process is gone.
export function parsePsUid(text) {
  const t = String(text).trim();
  return /^[0-9]+$/.test(t) ? Number(t) : null;
}

function procAddress(text, family, order) {
  const [host, port] = text.split(':');
  if (port === undefined || !/^[0-9A-Fa-f]+$/.test(host) || !/^[0-9A-Fa-f]+$/.test(port)) throw new Error('address');
  let raw = Buffer.from(host, 'hex');
  if (order === 'little') {
    const out = Buffer.alloc(raw.length);
    for (let i = 0; i < raw.length; i += 4) raw.subarray(i, i + 4).reverse().copy(out, i);
    raw = out;
  }
  if (raw.length !== (family === 4 ? 4 : 16)) throw new Error('address length');
  let text4or6;
  if (family === 4) text4or6 = [...raw].join('.');
  else text4or6 = Array.from({ length: 8 }, (_, i) => raw.readUInt16BE(i * 2).toString(16)).join(':');
  return [normHost(text4or6), parseInt(port, 16)];
}

// `/proc/net/tcp` (family 4) or `/proc/net/tcp6` (6). The kernel prints each 32-bit word of an address in host byte
// order and each port in network order, in hex.
export function parseProcNetTcp(text, { family, byteorder = os.endianness() === 'LE' ? 'little' : 'big' } = {}) {
  const rows = [];
  for (const line of String(text).split(/\r?\n/).slice(1)) {
    const tok = line.split(/\s+/).filter(Boolean);
    if (tok.length < 10 || !tok[0].endsWith(':')) continue;
    let local;
    let remote;
    try {
      local = procAddress(tok[1], family, byteorder);
      remote = procAddress(tok[2], family, byteorder);
    } catch {
      continue;
    }
    if (!/^[0-9]+$/.test(tok[7])) continue;
    const st = tok[3].toUpperCase();
    rows.push({ local, remote, listening: st === '0A', uid: Number(tok[7]), pid: null, timeWait: st === '06' });
  }
  return rows;
}

function windowsAddress(text) {
  const m = /^\[(.*)\]:([0-9]+)$/.exec(text) ?? /^([^:]*):([0-9]+)$/.exec(text);
  return m ? [normHost(m[1]), Number(m[2])] : null;
}

// `netstat -ano -p TCP` (or TCPv6) on Windows: proto, local, foreign, a localized state, pid. The state is not read:
// a row whose peer port is 0 listens, and a connected row of pid 0 is TIME_WAIT (the idle process holds those).
export function parseWindowsNetstat(text) {
  const rows = [];
  for (const line of String(text).split(/\r?\n/)) {
    const tok = line.trim().split(/\s+/);
    if (tok.length < 4 || tok[0].toUpperCase() !== 'TCP') continue;
    const local = windowsAddress(tok[1]);
    const remote = windowsAddress(tok[2]);
    const last = tok[tok.length - 1];
    if (!local || !remote || !/^[0-9]+$/.test(last)) continue;
    const pid = Number(last);
    const listening = remote[1] === 0;
    rows.push({ local, remote, listening, uid: null, pid, timeWait: !listening && pid === 0 });
  }
  return rows;
}

// tasklist's CSV quotes every field.
function csvFields(line) {
  return [...line.matchAll(/"((?:[^"]|"")*)"/g)].map((m) => m[1].replace(/""/g, '"'));
}

// `tasklist /v /fo csv /nh /fi "PID eq N"`: the user name column (the seventh) of the row whose pid is N, or null.
export function parseTasklistUser(text, pid) {
  for (const line of String(text).split(/\r?\n/)) {
    const f = csvFields(line.trim());
    if (f.length >= 7 && f[1] === String(pid)) return f[6];
  }
  return null;
}

// -- readers: the live table on this host ------------------------------------------------------------------------------

// Run one program, bounded; the tests pass their own `run` with the same shape.
export function runProgram(file, args, timeout = TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    execFile(file, args, { timeout, maxBuffer: MAX_TABLE_BYTES, windowsHide: true, encoding: 'utf8' },
      (err, stdout) => {
        const base = file.split(/[\\/]/).pop();
        let why = typeof err?.code === 'number' ? `exit ${err.code}` : (err?.killed ? 'timeout' : (err?.code ?? 'error'));
        if (err?.code === 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER') why = `table over ${MAX_TABLE_BYTES} bytes`;
        if (err) reject(new TableUnreadable(`${base}: ${why}`));
        else resolve(stdout);
      });
  });
}

export function method() {
  if (process.platform === 'darwin') return 'netstat';
  if (process.platform === 'linux') return 'proc';
  if (process.platform === 'win32') return 'netstat-windows';
  return 'none';
}

export async function readTable({ run = runProgram } = {}) {
  const how = method();
  if (how === 'netstat') return { rows: parseNetstat(await run(NETSTAT, ['-anv', '-p', 'tcp'])), how };
  if (how === 'proc') {
    const rows = [];
    for (const [name, family] of [['/proc/net/tcp', 4], ['/proc/net/tcp6', 6]]) {
      let raw;
      try {
        raw = await readFile(name);
      } catch (err) {
        if (err.code === 'ENOENT') continue; // no IPv6 on this kernel
        throw new TableUnreadable(`proc: ${err.code ?? 'error'}`);
      }
      if (raw.length > MAX_TABLE_BYTES) throw new TableUnreadable(`proc: table over ${MAX_TABLE_BYTES} bytes`);
      rows.push(...parseProcNetTcp(raw.toString('latin1'), { family }));
    }
    return { rows, how };
  }
  if (how === 'netstat-windows') {
    const rows = [];
    for (const proto of ['TCP', 'TCPv6']) rows.push(...parseWindowsNetstat(await run('netstat', ['-ano', '-p', proto], WINDOWS_TIMEOUT_MS)));
    return { rows, how };
  }
  throw new TableUnreadable('unsupported-platform');
}

let windowsUser = null;

async function windowsOwner(pid, how, run, ownUser) {
  if (pid === 0 || pid === 4) return classifyWindowsUser(null, pid, { method: how });
  try {
    if (ownUser === undefined) ownUser = windowsUser ??= (await runProgram('whoami', [], WINDOWS_TIMEOUT_MS)).trim();
  } catch (err) {
    return owner(UNKNOWN, { pid, method: how, reason: `own-user: ${err.message}` });
  }
  let user = null;
  try {
    user = parseTasklistUser(await run('tasklist', ['/v', '/fo', 'csv', '/nh', '/fi', `PID eq ${pid}`], WINDOWS_TIMEOUT_MS), pid);
  } catch {
    user = null;
  }
  if (user === null) return owner(UNKNOWN, { pid, method: how, reason: 'process-gone' });
  return classifyWindowsUser(user, pid, { ownUser, method: how });
}

// The owner of one selected row: its uid when the table carried one, else the pid's. `run`, `ownUid` and `ownUser`
// (Windows) are the tests' fixtures; by default the programs themselves and this process's own.
export async function resolve(row, how, { run = runProgram, ownUid: mine, ownUser } = {}) {
  if (how === 'netstat-windows') return windowsOwner(row.pid, how, run, ownUser);
  if (row.uid !== null && row.uid !== undefined) return classify(row.uid, row.pid, { method: how, ownUid: mine });
  if (row.pid === null || row.pid <= 0) return owner(UNKNOWN, { pid: row.pid, method: how, reason: 'no-pid' });
  if (row.pid === 1) return owner(SYSTEM, { pid: 1, method: how });
  let uid;
  try {
    uid = parsePsUid(await run(PS, ['-o', 'uid=', '-p', String(row.pid)]));
  } catch (err) {
    return owner(UNKNOWN, { pid: row.pid, method: how, reason: `ps: ${err.message}` });
  }
  if (uid === null) return owner(UNKNOWN, { pid: row.pid, method: how, reason: 'process-gone' });
  return classify(uid, row.pid, { method: how, ownUid: mine });
}

// -- the questions ----------------------------------------------------------------------------------------------------

// The live connected rows with exactly this local and remote address: one, or the caller cannot tell.
export function find(rows, local, remote) {
  return rows.filter((r) => !r.listening && !r.timeWait && same(r.local, local) && same(r.remote, remote));
}

async function ownerOf(local, remote, opts = {}) {
  let table;
  try {
    table = await (opts.read ?? readTable)(opts);
  } catch (err) {
    return owner(UNKNOWN, { method: method(), reason: err instanceof TableUnreadable ? err.message : `table: ${err.name}` });
  }
  const found = find(table.rows, local, remote);
  if (found.length === 0) return owner(UNKNOWN, { method: table.how, reason: 'no-row' });
  if (found.length > 1) return owner(UNKNOWN, { method: table.how, reason: 'several-rows' });
  return resolve(found[0], table.how, opts);
}

// The owner of the CLIENT socket of the connection between `server` and `client` ([host, port] each), as a server sees
// them: the row whose local address is the client's and whose remote address is the server's.
export function peerAt(server, client, opts) {
  return ownerOf(address(client[0], client[1]), address(server[0], server[1]), opts);
}

// For a server's accepted socket: who connected. Reads nothing from the socket.
export function peer(socket, opts) {
  if (!socket.remoteAddress || !socket.localAddress) return Promise.resolve(owner(UNKNOWN, { reason: 'socket: not connected' }));
  return peerAt([socket.localAddress, socket.localPort], [socket.remoteAddress, socket.remotePort], opts);
}

// For a client's connected socket: who accepted it. The row whose local address is the server's and whose remote
// address is this socket's own, the server process's accepted socket, so a listener swapped after listen cannot pass
// for the one that answers.
export function serverEnd(socket, opts) {
  if (!socket.remoteAddress || !socket.localAddress) return Promise.resolve(owner(UNKNOWN, { reason: 'socket: not connected' }));
  return ownerOf(address(socket.remoteAddress, socket.remotePort), address(socket.localAddress, socket.localPort), opts);
}

const LISTEN_ORDER = ['127.0.0.1', '*', '::1'];
const listeners = new Map();

// The listeners a connection to 127.0.0.1:<port> reaches: those on the most specific bind that has any.
export function pickListener(rows, port) {
  for (const host of LISTEN_ORDER) {
    const hits = rows.filter((r) => r.listening && r.local[0] === host && r.local[1] === port);
    if (hits.length) return hits;
  }
  return [];
}

// Who listens on 127.0.0.1:<port>, or on 0.0.0.0 or ::1. none when nothing does, unknown (several-rows) when two sockets
// do. Cached for LISTENER_TTL_MS (a `read` given in opts is never cached). `read` answers { rows, how } as readTable
// does; `run`, `ownUid` and `ownUser` go to resolve.
export async function listener(port, opts = {}) {
  const { read, now = () => performance.now() } = opts;
  const at = now();
  const hit = read ? undefined : listeners.get(port);
  if (hit && at - hit[0] < LISTENER_TTL_MS) return hit[1];
  let found;
  let how;
  let table;
  try {
    table = await (read ?? readTable)(opts);
    how = table.how;
    found = pickListener(table.rows, port);
  } catch (err) {
    const who = owner(UNKNOWN, { method: method(), reason: err instanceof TableUnreadable ? err.message : `table: ${err.name}` });
    if (!read) listeners.set(port, [at, who]);
    return who;
  }
  let who;
  if (found.length === 0) who = owner(NONE, { method: how });
  else if (found.length > 1) who = owner(UNKNOWN, { method: how, reason: 'several-rows' });
  else who = await resolve(found[0], how, opts);
  if (!read) listeners.set(port, [at, who]);
  return who;
}

// [code, why] when a client must not send on a connection whose server end is `who`, else null.
export function refusal(who, port, expectPid = null) {
  if (who.kind === ANOTHER_ACCOUNT || who.kind === SYSTEM) return [SERVER_NOT_OWN, `the server on port ${port} belongs to ${who.kind}`];
  if (who.kind !== THIS_ACCOUNT) return [SERVER_UNVERIFIED, `the owner of the server on port ${port} could not be read (${who.reason})`];
  if (expectPid !== null && who.pid !== null && who.pid !== expectPid) {
    return [SERVER_NOT_THIS_WORKSPACE, `the server on port ${port} is pid ${who.pid}, not the expected pid ${expectPid}`];
  }
  return null;
}

// A connected socket to host:port whose server end is this account's (and, with expectPid, that process's). The check
// runs on the very socket the caller then writes on, so no listener can change between the check and the request.
// Rejects with ListenerRefused (the socket destroyed, nothing written) or with the connection's own error.
export function checkedSocket(port, { host = '127.0.0.1', timeoutMs = 10000, expectPid = null, ...ask } = {}) {
  return new Promise((resolveSocket, reject) => {
    const socket = net.connect({ host, port });
    const timer = setTimeout(() => socket.destroy(Object.assign(new Error('connect timeout'), { code: 'ETIMEDOUT' })), timeoutMs);
    socket.once('error', (err) => { clearTimeout(timer); reject(err); });
    socket.once('connect', async () => {
      clearTimeout(timer);
      socket.pause();
      const who = await serverEnd(socket, ask);
      const refused = refusal(who, port, expectPid);
      if (refused) {
        socket.destroy();
        reject(new ListenerRefused(refused[0], `${refused[1]}; nothing was sent`, who));
        return;
      }
      socket.removeAllListeners('error');
      socket.resume();
      resolveSocket(socket);
    });
  });
}
