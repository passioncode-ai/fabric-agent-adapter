// Which OS account owns each end of a loopback TCP connection (DEC-0154 HA-2, FAA-226, layer L0); the twin of
// fabric_peer_owner.py, which is Project Observatory's peer_owner 1.1.0 vendored by commit. Node 18+, no dependency;
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
//   new CheckedAgent(opts)           an http.Agent whose every new socket is a checkedSocket: a kept-alive socket is
//                                    checked once, when it is made, since an established connection's server end
//                                    cannot change (a reading of the table costs about 35 ms here, Python's sysctl 4)
//
// `owner.kind` is this-account, another-account, system (uid 0, pid 1, Windows' pid 0 and 4 and its own accounts),
// unknown (`reason` says why) or none (listener only: nothing listens). A caller that must not leak treats everything
// but this-account as a refusal, unknown included: fail closed.
//
// HOW, ON EACH OS. Node has no ctypes, so it reads what the Python twin keeps as its fallback or reads the same files:
// - macOS: `/usr/sbin/netstat -anv -p tcp`, its process:pid column, then `ps -o uid= -p PID` for the one row a
//   question selects (Observatory measured about 20 ms over 846 sockets; it names root's listeners too). The uid is
//   read a few milliseconds after the pid: a pid reused in between would be misread, a window the Python twin's sysctl
//   reader does not have (it reads both from one record).
// - Linux: `/proc/net/tcp` and `/proc/net/tcp6`, whose uid column every account may read.
// - Windows: `netstat -ano -p TCP` and `-p TCPv6` for the owning pid (a row whose peer port is 0 listens; a connected
//   row of pid 0 is TIME_WAIT, the idle process's, never an answer; the state column is localized and not read), then
//   the owner's SID from PowerShell (`Win32_Process`'s `GetOwnerSid`), compared with this user's from
//   `whoami /user /fo csv /nh`. SIDs, never names: a name in the console's code page can decode to the same string for
//   two accounts. A process whose SID cannot be read (another account's, usually, without the right to open it) is
//   unknown.
// Every read is bounded (MAX_TABLE_BYTES, a timeout per program) and never cached across connections; only listener
// is cached, for LISTENER_TTL_MS. A TIME_WAIT row is never an answer; two live rows with the same addresses are
// unknown (several-rows), never a guess. It never reads a byte from the socket it is asked about and needs no
// privilege. The parsers are pure functions over captured text (test/fixtures/peer-owner/).

import { execFile } from 'node:child_process';
import { realpathSync } from 'node:fs';
import { open } from 'node:fs/promises';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

export const PEER_OWNER_VERSION = '1.2.0+kit.6'; // the Python twin's, Observatory's 1.2.0 with the kit's differences
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
export const LSOF = '/usr/sbin/lsof';
// The reason a socket table hides other processes' sockets from this one (FAA-267): macOS 27.2 gives an ad-hoc-signed
// runtime an empty netstat.
export const TABLE_RESTRICTED = 'table-restricted';
// A macOS table that lists sockets but not the reader's own connection (DEC-0155 RT-1, FAA-312).
export const NO_ROW_RESTRICTED = `${TABLE_RESTRICTED}: no row for this connection`;
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
    const v4 = [hi >> 8, hi & 255, lo >> 8, lo & 255].join('.');
    return v4 === '0.0.0.0' ? '*' : v4;
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
  // this process's own uid first: a client running as root owns root's listener (pid 1, launchd, stays system)
  if (mine !== null && uid === mine && pid !== 1) return owner(THIS_ACCOUNT, { uid, pid, method });
  if (uid === 0 || pid === 1) return owner(SYSTEM, { uid, pid, method });
  return owner(ANOTHER_ACCOUNT, { uid, pid, method });
}

// Windows, as the Python twin's classify_sid: the System process (pid 0 and 4) and the system's own accounts
// (LocalSystem, LocalService, NetworkService) are system, this process's SID this-account, any other SID
// another-account, a SID that could not be read unknown.
const SYSTEM_SIDS = new Set(['S-1-5-18', 'S-1-5-19', 'S-1-5-20']);
const SID = /^S-1-[0-9]+(-[0-9]+)+$/;

export function classifySid(sid, pid, { ownSid, method = 'netstat-windows' } = {}) {
  if (pid === 0 || pid === 4) return owner(SYSTEM, { pid, method });
  if (typeof sid !== 'string' || !SID.test(sid)) return owner(UNKNOWN, { pid, method, reason: 'process-not-readable' });
  if (typeof ownSid === 'string' && SID.test(ownSid) && sid === ownSid) return owner(THIS_ACCOUNT, { pid, method });
  if (SYSTEM_SIDS.has(sid)) return owner(SYSTEM, { pid, method });
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
  if (!lines.some((line) => line.trim())) throw new TableUnreadable(`${TABLE_RESTRICTED}: netstat printed nothing to this process`);
  const header = lines.findIndex((line) => line.includes('process:pid') && line.includes('Proto'));
  if (header < 0) throw new TableUnreadable('netstat-format: no process:pid column');
  const names = lines[header].split(/\s+/).filter(Boolean);
  const at = names.indexOf('process:pid');
  const leading = at - names.slice(0, at).filter((w) => w === 'Address').length;
  const trailing = names.length - at - 1;
  // The caller's own connection is in any table it can see: a header and no tcp row is the restricted table (FAA-273).
  if (!lines.slice(header + 1).some((line) => (line.split(/\s+/).filter(Boolean)[0] ?? '').startsWith('tcp'))) {
    throw new TableUnreadable(`${TABLE_RESTRICTED}: netstat printed only its header to this process`);
  }
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

// `lsof -nP -a -p PID -i4TCP -sTCP:LISTEN -Fn`: the `n` lines, 127.0.0.1:47480, *:47480 or [::1]:47480.
export function parseLsofListeners(text) {
  const found = [];
  for (const line of String(text).split(/\r?\n/)) {
    if (!line.startsWith('n') || !line.includes(':')) continue;
    const at = line.lastIndexOf(':');
    const port = line.slice(at + 1);
    if (/^[0-9]+$/.test(port)) found.push([normHost(line.slice(1, at).replace(/^\[|\]$/g, '')), Number(port)]);
  }
  return found;
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
// order and each port in network order, in hex. A connected row with inode 0 has no socket yet (not accept()ed, or
// already closed) and the kernel prints uid 0 for it: its uid is not read (null), and ownerOf takes its listener's.
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
    const listening = st === '0A';
    rows.push({ local, remote, listening, uid: !listening && tok[9] === '0' ? null : Number(tok[7]), pid: null, timeWait: st === '06' });
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

// `whoami /user /fo csv /nh`: `"<domain>\\<name>","S-1-5-..."`. The name is read in the console's code page and never
// used; the SID is ASCII. Null when no SID is there.
export function parseWhoamiSid(text) {
  const m = /"(S-1-[0-9]+(?:-[0-9]+)+)"\s*$/m.exec(String(text));
  return m ? m[1] : null;
}

// What the owner-SID script prints: one SID, or nothing when the process is gone or cannot be opened.
export function parseOwnerSid(text) {
  const t = String(text).trim();
  return SID.test(t) ? t : null;
}

// The PowerShell that prints a process's owner SID (pid an integer, checked by the caller).
export function ownerSidScript(pid) {
  return `$p = Get-CimInstance -ClassName Win32_Process -Filter 'ProcessId=${Number(pid)}'; `
    + 'if ($p) { $r = Invoke-CimMethod -InputObject $p -MethodName GetOwnerSid; if ($r.ReturnValue -eq 0) { $r.Sid } }';
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

export function method(platform = process.platform) {
  if (platform === 'darwin') return 'netstat';
  if (platform === 'linux') return 'proc';
  if (platform === 'win32') return 'netstat-windows';
  return 'none';
}

// A /proc file read to its end. Node 18's readFile stops after the first page of a file that reports size 0, about
// 4 KB, so every socket past the 26th or so read as no-row (0.74.0 seam reading 5); read until EOF, one byte past the
// cap at most.
async function readProc(name) {
  const fh = await open(name, 'r');
  const chunks = [];
  let total = 0;
  try {
    for (;;) {
      const buf = Buffer.alloc(65536);
      const { bytesRead } = await fh.read(buf, 0, buf.length, null);
      if (!bytesRead) break;
      chunks.push(buf.subarray(0, bytesRead));
      total += bytesRead;
      if (total > MAX_TABLE_BYTES) break;
    }
  } finally {
    await fh.close();
  }
  return Buffer.concat(chunks);
}

export async function readTable({ run = runProgram, platform = process.platform } = {}) {
  const how = method(platform);
  if (how === 'netstat') {
    let text;
    try {
      text = await run(NETSTAT, ['-anv', '-p', 'tcp']);
    } catch (err) {
      // A netstat that fails, exits non-zero or times out is a restricted table (DEC-0155 RT-1, FAA-312).
      throw new TableUnreadable(`${TABLE_RESTRICTED}: ${err instanceof TableUnreadable ? err.message : `netstat: ${err?.name ?? 'error'}`}`);
    }
    return { rows: parseNetstat(text), how };
  }
  if (how === 'proc') {
    const rows = [];
    for (const [name, family] of [['/proc/net/tcp', 4], ['/proc/net/tcp6', 6]]) {
      let raw;
      try {
        raw = await readProc(name);
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

let windowsSid = null;

async function windowsOwner(pid, how, run, ownSid) {
  if (pid === 0 || pid === 4) return classifySid(null, pid, { method: how });
  if (!Number.isInteger(pid) || pid < 0) return owner(UNKNOWN, { pid, method: how, reason: 'no-pid' });
  try {
    if (ownSid === undefined) {
      if (run === runProgram) ownSid = windowsSid ??= parseWhoamiSid(await run('whoami', ['/user', '/fo', 'csv', '/nh'], WINDOWS_TIMEOUT_MS));
      else ownSid = parseWhoamiSid(await run('whoami', ['/user', '/fo', 'csv', '/nh'], WINDOWS_TIMEOUT_MS));
    }
  } catch (err) {
    return owner(UNKNOWN, { pid, method: how, reason: `own-sid: ${err.message}` });
  }
  if (!ownSid) return owner(UNKNOWN, { pid, method: how, reason: 'own-sid: unreadable' });
  let sid = null;
  try {
    sid = parseOwnerSid(await run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', ownerSidScript(pid)], WINDOWS_TIMEOUT_MS));
  } catch {
    sid = null;
  }
  return classifySid(sid, pid, { ownSid, method: how });
}

// The owner of one selected row: its uid when the table carried one, else the pid's. `run`, `ownUid` and `ownSid`
// (Windows) are the tests' fixtures; by default the programs themselves and this process's own.
export async function resolve(row, how, { run = runProgram, ownUid: mine, ownSid } = {}) {
  if (how === 'netstat-windows') return windowsOwner(row.pid, how, run, ownSid);
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

// DEC-0155 RT-1 (FAA-312): a macOS table holding no row of another uid (sysctl, the Python twin's, which carries uids)
// or of another process (netstat, which carries pids) is restricted, and a missing row proves nothing. Never on Linux
// or Windows, which carry the owner on each row.
export function restricted(rows, how, { ownUid: mine, ownPid } = {}) {
  if (how === 'sysctl') {
    const own = mine ?? ownUid();
    return !rows.some((r) => r.uid !== null && r.uid !== undefined && r.uid !== own);
  }
  if (how === 'netstat') {
    const own = ownPid ?? process.pid;
    return !rows.some((r) => r.pid !== null && r.pid !== undefined && r.pid !== own);
  }
  return false;
}

// The live connected rows with exactly this local and remote address: one, or the caller cannot tell.
// A row printed twice is one socket: Linux resumes a /proc read that sockets came and went under by position, and can
// print the same row again (0.74.0 seam reading 6); rows equal in every field count once.
export function find(rows, local, remote) {
  const seen = new Set();
  return rows.filter((r) => {
    if (r.listening || r.timeWait || !same(r.local, local) || !same(r.remote, remote)) return false;
    const key = JSON.stringify(r);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

async function ownerOf(local, remote, opts = {}, server = false) {
  let table;
  let found;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      table = await (opts.read ?? readTable)(opts);
    } catch (err) {
      return owner(UNKNOWN, { method: method(), reason: err instanceof TableUnreadable ? err.message : `table: ${err.name}` });
    }
    found = find(table.rows, local, remote);
    // A /proc read under churn can skip a row or print one twice; one more read before answering unknown.
    if (table.how !== 'proc' || found.length === 1) break;
  }
  // A macOS table without the reader's own connection is restricted (DEC-0155 RT-1, FAA-312).
  if (found.length === 0) return owner(UNKNOWN, { method: table.how, reason: ['sysctl', 'netstat'].includes(table.how) ? NO_ROW_RESTRICTED : 'no-row' });
  if (found.length > 1) return owner(UNKNOWN, { method: table.how, reason: 'several-rows' });
  if (table.how === 'proc' && server && found[0].uid === null) {
    // Linux: a connection not yet accept()ed is printed with uid 0 and inode 0; it belongs to the listener on its local
    // address and dies with it, so that listener answers. An accepted connection's own row carries the uid of the
    // process that accepted it: it answers itself, so a listener swapped after another account accepted the client
    // cannot pass (Project Observatory's 1.2.0 reading, board thread ced00f6e; the contract's CT-254, released).
    // A server row its owner already closed (an orphan) also has inode 0 and reads so: no process holds it, so nothing
    // sent to it reaches anyone (0.74.0 unit reading 6).
    return oneOwner(listenersOf(table.rows, found[0].local), table.how, opts, 'not-accepted');
  }
  // A client's socket with inode 0 has already closed (0.74.0 unit reading 4): never another socket's owner.
  if (table.how === 'proc' && found[0].uid === null) return owner(UNKNOWN, { method: table.how, reason: 'closed' });
  return resolve(found[0], table.how, opts);
}

// The listeners that took a connection to `local`: on its exact address, else the wildcard.
function listenersOf(rows, local) {
  for (const host of [local[0], '*']) {
    const hits = rows.filter((r) => r.listening && r.local[0] === host && r.local[1] === local[1]);
    if (hits.length) return hits;
  }
  return [];
}

// The owner of the rows a question selected: one row, or several of one owner (SO_REUSEPORT workers, an IPv4 and an
// IPv6 socket of one process). Several owners cannot be told apart: unknown (several-rows).
async function oneOwner(found, how, opts, noneReason = null) {
  if (found.length === 0) return noneReason ? owner(UNKNOWN, { method: how, reason: noneReason }) : owner(NONE, { method: how });
  const keys = new Set(found.map((r) => `${r.uid}/${r.pid}`));
  const uids = new Set(found.map((r) => r.uid));
  if (keys.size === 1 || (!uids.has(null) && !uids.has(undefined) && uids.size === 1)) return resolve(found[0], how, opts);
  return owner(UNKNOWN, { method: how, reason: 'several-rows' });
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
// for the one that answers. On Linux a connection not yet accept()ed has no owner of its own (inode 0): its listener
// answers (the contract's CT-254, HA-2's Linux source).
export function serverEnd(socket, opts) {
  if (!socket.remoteAddress || !socket.localAddress) return Promise.resolve(owner(UNKNOWN, { reason: 'socket: not connected' }));
  return ownerOf(address(socket.remoteAddress, socket.remotePort), address(socket.localAddress, socket.localPort), opts, true);
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

// Who listens on 127.0.0.1:<port>, or on 0.0.0.0 or ::1. none when nothing does, unknown (several-rows) when sockets of
// two owners do. Cached for LISTENER_TTL_MS (never when `read`, `run`, `ownUid` or `ownSid` is given). `read` answers
// { rows, how } as readTable does; `run`, `ownUid` and `ownSid` go to resolve.
export async function listener(port, opts = {}) {
  const { read, now = () => performance.now() } = opts;
  const injected = Boolean(read || opts.run || opts.ownUid !== undefined || opts.ownSid !== undefined);
  const at = now();
  const hit = injected ? undefined : listeners.get(port);
  if (hit && at - hit[0] < LISTENER_TTL_MS) return hit[1];
  let table;
  try {
    table = await (read ?? readTable)(opts);
  } catch (err) {
    const who = owner(UNKNOWN, { method: method(), reason: err instanceof TableUnreadable ? err.message : `table: ${err.name}` });
    if (!injected) listeners.set(port, [at, who]);
    return who;
  }
  const who = restricted(table.rows, table.how, opts) ? await restrictedListener(table.rows, port, table.how, opts)
    : await oneOwner(pickListener(table.rows, port), table.how, opts);
  if (!injected) listeners.set(port, [at, who]);
  return who;
}

// DEC-0155 RT-4 (FAA-312): under a restricted table only this account's own bind on exactly 127.0.0.1 is its own; its
// wildcard or ::1 listener, root's, and a port with no row are an owner that cannot be told.
async function restrictedListener(rows, port, how, opts) {
  const who = await oneOwner(rows.filter((r) => r.listening && r.local[0] === '127.0.0.1' && r.local[1] === port), how, opts);
  if (who.kind === THIS_ACCOUNT) return who;
  return owner(UNKNOWN, { method: how, reason: `${TABLE_RESTRICTED}: no listener of this account on exactly 127.0.0.1:${port}` });
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

// macOS, when the socket table is restricted (FAA-267, DEC-0155 RT-3): whether process `pid`, this account's, listens on
// exactly 127.0.0.1:<port> (never the IPv4 wildcard, which lsof prints as it prints an IPv6-only one, nor ::1; FAA-312).
// `lsof -p` asks the process itself, which the restriction does not hide. Only a caller that started `pid` itself (a
// launchd job it installed) may vouch with it, and never a set-uid one (its real and effective uid differ, DEC-0155).
export async function pidListens(pid, port, { run = runProgram, platform = process.platform, ownUid: mine, ownEuid } = {}) {
  if (platform !== 'darwin' || !Number.isInteger(pid) || pid <= 1) return false;
  const real = mine ?? ownUid();
  const effective = ownEuid ?? (typeof process.geteuid === 'function' ? process.geteuid() : real);
  if (effective !== real) return false;
  try {
    const uid = parsePsUid(await run(PS, ['-o', 'uid=', '-p', String(pid)]));
    if (uid === null || uid !== real) return false;
    const out = await run(LSOF, ['-nP', '-a', '-p', String(pid), '-i4TCP', '-sTCP:LISTEN', '-Fn']);
    return parseLsofListeners(out).some(([host, p]) => host === '127.0.0.1' && p === port);
  } catch {
    return false;
  }
}

// A connected socket to host:port whose server end is this account's (and, with expectPid, that process's). The check
// runs on the very socket the caller then writes on, so no listener can change between the check and the request.
// Rejects with ListenerRefused (the socket destroyed, nothing written) or with the connection's own error.
export function checkedSocket(port, { host = '127.0.0.1', timeoutMs = 10000, expectPid = null, vouchPid = null, ...ask } = {}) {
  return new Promise((resolveSocket, reject) => {
    // autoSelectFamily: Node 18 connects to the first address only, and localhost resolves to ::1 first on Linux, so a
    // listener on 127.0.0.1 was never reached; Python tries every address, as Node 20 and later do by default.
    const socket = net.connect({ host, port, noDelay: true, autoSelectFamily: true }); // as a plain http.Agent's socket
    const timer = setTimeout(() => socket.destroy(Object.assign(new Error('connect timeout'), { code: 'ETIMEDOUT' })), timeoutMs);
    socket.once('error', (err) => { clearTimeout(timer); reject(err); });
    socket.once('connect', async () => {
      clearTimeout(timer);
      socket.pause();
      let who;
      try {
        who = await serverEnd(socket, ask);
      } catch (err) {
        // A reader that throws (an injected one; the readers themselves answer unknown) fails closed.
        who = owner(UNKNOWN, { method: method(), reason: `check: ${err?.name ?? 'Error'}` });
      }
      if (who.kind === UNKNOWN && String(who.reason ?? '').startsWith(TABLE_RESTRICTED) && vouchPid
        && await pidListens(vouchPid, port, ask)) {
        // The table hides other processes (FAA-267); the process this caller started holds the listener.
        who = owner(THIS_ACCOUNT, { uid: ask.ownUid ?? ownUid(), pid: vouchPid, method: 'lsof-pid' });
      }
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

// An http.Agent whose every new connection is checked before a byte is written; with keepAlive a socket is checked once,
// when it is made. A refusal reaches the request as its 'error', a ListenerRefused. Free sockets do not keep the process
// alive (Node unrefs them).
export class CheckedAgent extends http.Agent {
  constructor({ expectPid = null, vouchPid = null, ask = {}, ...options } = {}) {
    super(options);
    this.expectPid = expectPid;
    this.vouchPid = vouchPid;
    this.ask = ask;
  }

  createConnection(options, callback) {
    checkedSocket(Number(options.port), { host: options.host ?? '127.0.0.1', timeoutMs: options.timeout ?? 10000,
      expectPid: this.expectPid, vouchPid: this.vouchPid, ...this.ask }).then((socket) => callback(null, socket), (err) => callback(err));
  }
}

const USAGE = 'usage: fabric-peer-owner.mjs listener <port> [--json]\n';

// `listener <port> [--json]`: the kind of who listens on 127.0.0.1:<port>, which the dashboard link gate takes as
// listener_owner (FAA-315), or the whole owner as JSON; 2 on a usage error. `listener` and `write` are the tests'.
export async function main(argv, { listener: ask = listener, write = (text) => process.stdout.write(text) } = {}) {
  const asJson = argv.length === 3 && argv[2] === '--json';
  const port = Number(argv[1]);
  if (argv.length !== 2 + Number(asJson) || argv[0] !== 'listener' || !/^[0-9]+$/.test(argv[1] ?? '') || port < 1 || port > 65535) {
    process.stderr.write(USAGE);
    return 2;
  }
  const who = await ask(port);
  write(asJson ? `${JSON.stringify({ kind: who.kind, uid: who.uid, pid: who.pid, method: who.method, reason: who.reason })}\n` : `${who.kind}\n`);
  return 0;
}

// Whether node was started on this file, by real paths (a symlinked install folder, as check_dashboard_layout.mjs).
function startedDirectly() {
  try {
    return Boolean(process.argv[1]) && realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url));
  } catch {
    return false;
  }
}

if (startedDirectly()) {
  main(process.argv.slice(2)).then((code) => { process.exitCode = code; }, (err) => { process.stderr.write(`${err?.message ?? err}\n`); process.exitCode = 1; });
}
