// This OS account's own TCP sockets, read from its own processes (layer L0; DEC-0155 RT-2, FAA-292; FAA-272); the twin
// of fabric_socket_proof.py. Node 18+, no dependency; nothing here imports another kit module.
//
// macOS 27.2 shows an ad-hoc-signed runtime (Homebrew's Node) only its own sockets, so fabric-peer-owner reads such a
// table as table-restricted and cannot tell who accepted a connection. The question can still be asked of this
// account's own processes, which the restriction leaves readable: whether one of them holds the very socket that
// accepted the connection (RT-2, the accepted-socket proof), or a listener bound exactly to 127.0.0.1:<port> (HA-2's
// macOS row, FAA-272). Another account's process is not listed, so a proof only ever says "this account's" or "not
// proved"; never another account's, the system's or nobody's.
//
//   await accepted(server, client, { wait })   the socket at `server` connected to `client` is in one of this
//                                              account's processes (`wait`: read again for ACCEPT_WAIT_MS until the
//                                              server has called accept())
//   await ownListener(port)                    a listener of this account on exactly 127.0.0.1:<port>
//
// Node has no ctypes, so the twin reads RT-2's other named source, `lsof -nP -a -u <uid> -iTCP:<port> -sTCP:<state>
// -F pun`, matching the exact address pair and the numeric uid, where the Python twin reads the same records through
// libproc (lsof only when libproc is unavailable). The twins agree on answers, not on the program they run (DEC-0155
// Compatibility); test/fixtures/peer-owner/socket-proof-cases.json holds both. The proof is "a process of this uid
// holds the descriptor", weaker than a table's so_uid: a socket passed with SCM_RIGHTS to a process of this uid reads
// as this account's, which a caller that knows the server's pid closes with expectPid. One socket several of this
// account's processes hold is proved with pid null, reason several-processes. A process whose real and effective uids
// differ is refused (setuid-context). Reasons: table-restricted (read, nothing of this account matches) or
// `table-restricted: <detail>` (the proof could not be read). Bounded by TIMEOUT_MS and MAX_OUTPUT_BYTES.

import { execFile } from 'node:child_process';
import net from 'node:net';

export const TABLE_RESTRICTED = 'table-restricted';
export const LSOF_METHOD = 'lsof';
export const LSOF = '/usr/sbin/lsof';
export const TIMEOUT_MS = 2000;
export const ACCEPT_WAIT_MS = 500;
export const MAX_OUTPUT_BYTES = 4 * 1024 * 1024;

const proof = (proved, pid, method, reason) => Object.freeze({ proved, pid, method, reason });
const digits = (text) => /^[0-9]+$/.test(text);

// One spelling per address, as fabric-peer-owner's normHost (the same rule, kept here so this module stands alone): an
// IPv4-mapped IPv6 address is its IPv4 form, the unspecified address `*`, an IPv6 address RFC 5952's.
function host(text) {
  let h = String(text ?? '').replace(/^\[(.*)\]$/, '$1');
  if (h === '*' || h === '') return '*';
  if (h === 'localhost') return '127.0.0.1';
  h = h.split('%', 1)[0];
  if (net.isIPv4(h)) return h === '0.0.0.0' ? '*' : h.split('.').map((x) => String(Number(x))).join('.');
  if (!net.isIPv6(h)) return h;
  const t = new URL(`http://[${h}]/`).hostname.slice(1, -1);
  if (t === '::') return '*';
  const mapped = /^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/.exec(t);
  if (!mapped) return t;
  const hi = parseInt(mapped[1], 16);
  const lo = parseInt(mapped[2], 16);
  const v4 = [hi >> 8, hi & 255, lo >> 8, lo & 255].join('.');
  return v4 === '0.0.0.0' ? '*' : v4;
}

function lsofAddress(text) {
  const at = text.lastIndexOf(':');
  if (at < 0) return null;
  const port = text.slice(at + 1);
  if (!digits(port) || Number(port) > 65535) return null;
  return [host(text.slice(0, at)), Number(port)];
}

// `lsof -nP -a -u <uid> -iTCP:<port> -sTCP:<state> -F pun`: the `n` lines of every process block whose `u` line is
// exactly `uid` (a block of another uid, or with no uid, is not read). A name with `->` is a connection, one without a
// listener. The same socket listed by several processes (one address pair) is one socket with pid null.
export function parseLsofSockets(text, uid) {
  const found = new Map();
  let pid = null;
  let owner = null;
  for (const line of String(text).split(/\r?\n/)) {
    const tag = line.slice(0, 1);
    const value = line.slice(1);
    if (tag === 'p') {
      pid = digits(value) ? Number(value) : null;
      owner = null;
    } else if (tag === 'u') {
      owner = digits(value) ? Number(value) : null;
    } else if (tag === 'n' && pid !== null && owner === uid) {
      const arrow = value.indexOf('->');
      const local = lsofAddress(arrow < 0 ? value : value.slice(0, arrow));
      const remote = arrow < 0 ? ['*', 0] : lsofAddress(value.slice(arrow + 2));
      if (!local || !remote) continue;
      const key = JSON.stringify([local, remote, arrow < 0]);
      if (!found.has(key)) found.set(key, { local, remote, listening: arrow < 0, pids: [] });
      found.get(key).pids.push(pid);
    }
  }
  return [...found.values()].map(({ local, remote, listening, pids }) => ({
    local, remote, listening, pid: new Set(pids).size === 1 ? pids[0] : null,
  }));
}

const same = (a, b) => a[0] === b[0] && a[1] === b[1];

function proved(hits, how) {
  if (hits.length === 0) return proof(false, null, how, TABLE_RESTRICTED);
  const pids = new Set(hits.map((s) => s.pid));
  if (pids.size === 1 && !pids.has(null)) return proof(true, hits[0].pid, how, null);
  return proof(true, null, how, 'several-processes');
}

// RT-2 over this account's sockets: the one at `server` connected to `client`; two with that pair are several-rows.
export function acceptedIn(sockets, server, client, how) {
  const hits = sockets.filter((s) => !s.listening && same(s.local, server) && same(s.remote, client));
  if (hits.length > 1) return proof(false, null, how, 'several-rows');
  return proved(hits, how);
}

// FAA-272 over this account's sockets: a listener bound exactly to 127.0.0.1:<port> (DEC-0155 RT-4: our wildcard or
// ::1 listener, and root's, cannot be told from a hidden one).
export function listenerIn(sockets, port, how) {
  return proved(sockets.filter((s) => s.listening && same(s.local, ['127.0.0.1', port])), how);
}

class ProofUnreadable extends Error {}

// One bounded run of lsof; its exit 1 with nothing printed is "no socket matched", not a failure.
export function runLsof(file, args, timeout = TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    execFile(file, args, { timeout, maxBuffer: MAX_OUTPUT_BYTES, encoding: 'utf8' }, (err, stdout) => {
      if (!err) return resolve(stdout);
      if (err.code === 1 && !String(stdout ?? '').trim()) return resolve('');
      const why = typeof err.code === 'number' ? `exit ${err.code}` : (err.killed ? 'timeout' : (err.code ?? 'error'));
      reject(new ProofUnreadable(`lsof: ${err.code === 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER' ? `output over ${MAX_OUTPUT_BYTES} bytes` : why}`));
    });
  });
}

// The reader a question uses: lsof on macOS, none elsewhere.
export const method = (platform = process.platform) => (platform === 'darwin' ? LSOF_METHOD : 'none');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function ask(port, state, pick, waitMs, { platform = process.platform, uid, euid, run = runLsof, now = () => Date.now() } = {}) {
  const start = now();
  if (platform !== 'darwin') return proof(false, null, 'none', `${TABLE_RESTRICTED}: unsupported-platform`);
  const real = uid ?? process.getuid();
  const effective = euid ?? (typeof process.geteuid === 'function' ? process.geteuid() : real);
  if (real !== effective) return proof(false, null, LSOF_METHOD, `${TABLE_RESTRICTED}: setuid-context`);
  let pause = 5;
  for (;;) {
    let have;
    try {
      have = parseLsofSockets(await run(LSOF, ['-nP', '-a', '-u', String(real), `-iTCP:${port}`, `-sTCP:${state}`, '-F', 'pun']), real);
    } catch (err) {
      return proof(false, null, LSOF_METHOD, `${TABLE_RESTRICTED}: ${err?.message ?? 'lsof: error'}`);
    }
    const answer = pick(have);
    if (answer.proved || now() + pause > start + Math.min(waitMs, TIMEOUT_MS)) return answer;
    await sleep(pause);
    pause = Math.min(pause * 2, 50);
  }
}

// RT-2: whether the socket at `server` connected to `client` ([host, port] each) is in one of this account's processes.
// `wait`: read again for ACCEPT_WAIT_MS, since the server's accepted socket exists only once it calls accept().
// `platform`, `uid`, `euid`, `run` and `now` are the tests'.
export function accepted(server, client, { wait = false, ...opts } = {}) {
  const s = [host(server[0]), Number(server[1])];
  const c = [host(client[0]), Number(client[1])];
  return ask(s[1], 'ESTABLISHED', (have) => acceptedIn(have, s, c, LSOF_METHOD), wait ? ACCEPT_WAIT_MS : 0, opts);
}

// FAA-272: whether one of this account's processes listens on exactly 127.0.0.1:<port>.
export function ownListener(port, opts = {}) {
  return ask(Number(port), 'LISTEN', (have) => listenerIn(have, Number(port), LSOF_METHOD), 0, opts);
}
