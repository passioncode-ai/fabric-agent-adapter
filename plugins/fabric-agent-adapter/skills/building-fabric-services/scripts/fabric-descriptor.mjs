// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
// How a service is found (fabric-service/0.1): its descriptor, peers and app descriptors (DEC-0061, DEC-0069), build identity and the well-known document.
// Part of the Node service kit (FAA-65, layer L3); the twin of fabric_descriptor.py. Node 20+, no dependency.
// Example URLs write their scheme in angle brackets: read `<https>` as `https` (FAA-212).
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { credentialName, repositoryCredential, secretArgument, secretLaunchArgument, secretUrl, secretValue } from './fabric-secrets.mjs';
import { ID, INSTANCE, LOCAL_PATH, PRIMARY_CAPABILITY, PROTOCOL, ServiceError, TASK, UNIT, expand } from './fabric-base.mjs';
import { atomicWrite, ensurePrivateDir, servicesDir } from './fabric-paths.mjs';
import { ANOTHER_ACCOUNT, SYSTEM, THIS_ACCOUNT, UNKNOWN, normHost, owner as peerOwnerOf, peer as peerOfSocket } from './fabric-peer-owner.mjs'; // L0: who listens on a port and who connected (DEC-0154 HA-2, FAA-225, FAA-227)
import { protocolsFindings } from './fabric-protocols.mjs';
import { CONNECTIONS_EXTENSION_KEY, connectionsView } from './fabric-connections.mjs';
import { ACTIONS_EXTENSION_KEY, actionsExtension, actionsExtensionRules } from './fabric-actions.mjs';
import { a2aSurfaceProblems } from './fabric-a2a.mjs';
import { ROUTES, isPlainObject } from './fabric-usage.mjs';
export { CREDENTIAL_KINDS, PEER_DATA_CLASSES, SUBSCRIPTION_RUNNERS, descriptorMemberProblems, originIdentity, peerRefusal, repositoryFromOrigin, sourceRepositoryProblem } from './fabric-descriptor-members.mjs'; // a descriptor's members, the source rule, the peer check
import { RESERVED_HOST, descriptorMemberProblems, isObj, shownMember } from './fabric-descriptor-members.mjs';

// The embedded dashboard declaration (fabric-dashboard/0.1, DEC-0036 ED-9), under the well-known
// document's `extensions`. The kit is assets/dashboard-kit; its version is the one in kit.json.
export const DASHBOARD_EXTENSION_KEY = 'https://fabric.passioncode.ai/agent-contract/extensions/dashboard/0.1';

export const DASHBOARD_KIT = 'fabric-dashboard-kit@1.1.9';

export const REFERENCE_THEMES = ['graphite', 'fabric', 'paper', 'forest', 'ocean', 'ember', 'contrast'];

export const STATUSES = ['starting', 'ready', 'degraded', 'stopping'];

export const PLACEMENTS = ['local', 'remote'];

const ORIGIN = /^http:\/\/127\.0\.0\.1:([0-9]{3,5})$/;

const REMOTE_ORIGIN = /^https:\/\/((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63})(?::([0-9]{1,5}))?$/;

// DEC-0061: `node` (Project Observatory's node supervises its children, no supervisor file); DEC-0069: `person` (an app a
// person installs and starts; its descriptor says it is installed, never that it runs).
export const MANAGERS = Object.freeze(['launchd', 'systemd', 'task-scheduler', 'node', 'person', 'none']);

/** Managers that write no launchd label or plist (DEC-0057, DEC-0061, DEC-0069). */
const NOT_LAUNCHD = Object.freeze(['systemd', 'task-scheduler', 'node', 'person']);

const AUTH_HEADER = /^[A-Za-z][A-Za-z0-9-]{0,63}$/;

export const descriptorPath = (id, instance = 'default', dir = servicesDir()) => path.join(dir, `${id}.${instance}.json`);

/**
 * A descriptor's JSON read as Python's `read_text(encoding="utf-8")` and `json.loads` read it: bytes that are no UTF-8
 * throw, and a leading byte-order mark stays and is refused by JSON.parse, never a byte replaced and kept (FAA-200 (51)).
 */
export function readDescriptorJson(file) {
  return JSON.parse(new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(fs.readFileSync(file)));
}

export function readDescriptors(dir = servicesDir()) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((n) => n.endsWith('.json')).sort().flatMap((n) => {
    try {
      const value = readDescriptorJson(path.join(dir, n));
      return isPlainObject(value) ? [[path.join(dir, n), value]] : []; // no object, no descriptor (FAA-200 (50))
    } catch {
      return [];
    }
  });
}

export function validateDescriptor(d) {
  const problems = [];
  const remote = placementOf(d) === 'remote';
  if (d.placement !== undefined && !PLACEMENTS.includes(d.placement)) problems.push('placement must be local or remote');
  // DEC-0069: an app's descriptor says it is installed, never that it runs; its live origin is in its own liveness file.
  const app = d.lifecycle?.manager === 'person';
  const required = ['protocol', 'id', 'instance', 'name', ...(app ? [] : ['origin']), 'auth', 'lifecycle', 'installedAt', 'installedBy'];
  for (const key of remote ? required : [...required, 'paths']) {
    if (!(key in d)) problems.push(`missing ${key}`);
  }
  if (problems.length) return problems;
  // FAA-200 (38): an object member is read as its type before it is indexed, so a hand-edited descriptor is named,
  // never thrown on (by this check and by every writer and probe that calls it), as the Python twin reads it.
  for (const key of ['auth', 'lifecycle', 'paths', 'commands']) {
    if (key in d && !isObj(d[key])) problems.push(`${key} must be an object`);
  }
  if (isObj(d.paths) && 'logs' in d.paths && !Array.isArray(d.paths.logs)) problems.push('paths.logs must be an array');
  if (problems.length) return problems;
  if (d.protocol !== PROTOCOL) problems.push(`protocol must be ${PROTOCOL}`);
  for (const [key, pattern] of [['id', ID], ['instance', INSTANCE]]) { // a string before its pattern (FAA-200 (9), (36))
    if (typeof d[key] !== 'string') problems.push(`${key} must be a string`);
    else if (!pattern.test(d[key])) problems.push(`${key} must match ${pattern}`);
  }
  if (remote) problems.push(...remoteOriginProblems(d.origin));
  else if (d.origin !== undefined && !ORIGIN.test(d.origin)) problems.push('origin must be http://127.0.0.1:<port>');
  if (!d.auth?.tokenFile) problems.push('auth.tokenFile is required');
  else if (!LOCAL_PATH.test(String(d.auth.tokenFile))) problems.push('auth.tokenFile must be an absolute local path (/, ~/ or a drive letter), never a relative path, never a network share');
  for (const value of [...(d.paths?.data !== undefined ? [d.paths.data] : []), ...(d.paths?.logs ?? [])]) {
    if (!LOCAL_PATH.test(String(value))) problems.push(`paths must be absolute local paths (/, ~/ or a drive letter), never a relative path, never a network share: ${JSON.stringify(value)}`);
  }
  if (!(typeof (d.auth?.header ?? 'Authorization') === 'string' && AUTH_HEADER.test(d.auth?.header ?? 'Authorization'))) problems.push(`auth.header must match ${AUTH_HEADER.source}`);
  if (!['Bearer', 'none'].includes(d.auth?.scheme ?? 'Bearer')) problems.push('auth.scheme is Bearer or none');
  if ((d.auth?.header ?? 'Authorization') !== 'Authorization' && (d.auth?.scheme ?? 'Bearer') !== 'none') {
    problems.push('a custom auth header carries the raw token: scheme must be none');
  }
  const life = d.lifecycle ?? {};
  const manager = life.manager;
  if (!MANAGERS.includes(manager)) problems.push('lifecycle.manager must be launchd, systemd, task-scheduler, node, person or none');
  // DEC-0069: `app` is the installed app of a person's descriptor, and nothing else's.
  if (manager === 'person' && life.app === undefined) problems.push("a person's app declares lifecycle.app, the installed app");
  if (life.app !== undefined && manager !== 'person') problems.push('lifecycle.app belongs to manager person only');
  if (life.app !== undefined && !LOCAL_PATH.test(String(life.app))) problems.push('lifecycle.app must be a local path');
  if (manager === 'launchd' && !(life.label && String(life.plist ?? '').endsWith('.plist'))) {
    problems.push('a launchd service declares label and plist');
  }
  if (life.plist !== undefined && !LOCAL_PATH.test(String(life.plist))) problems.push('lifecycle.plist must be a local path');
  // DEC-0057, DEC-0061, DEC-0069: a descriptor names one supervisor; launchd's label and plist never sit beside another.
  for (const field of ['label', 'plist']) {
    if (life[field] !== undefined && NOT_LAUNCHD.includes(manager)) problems.push(`lifecycle.${field} belongs to launchd, not to ${manager}`);
  }
  // DEC-0032: `unit` goes with systemd and `task` with Task Scheduler, and with nothing else.
  for (const [field, owner, pattern] of [['unit', 'systemd', UNIT], ['task', 'task-scheduler', TASK]]) {
    if (manager === owner && life[field] === undefined) problems.push(`a ${owner} service declares ${field}`);
    if (life[field] !== undefined && manager !== owner) problems.push(`lifecycle.${field} belongs to manager ${owner} only`);
    if (life[field] !== undefined && !pattern.test(String(life[field]))) problems.push(`lifecycle.${field} must match ${pattern.source}`);
  }
  if (remote) {
    if (manager !== 'none') problems.push('a remote service is supervised by its platform: lifecycle.manager must be none');
    for (const [field, of] of [['label', 'launchd'], ['plist', 'launchd'], ['unit', 'systemd'], ['task', 'Task Scheduler']]) {
      if (life[field] !== undefined) problems.push(`a remote service has no ${of} ${field}`);
    }
    if (d.commands?.update !== undefined) problems.push('a remote service declares no update command');
  }
  problems.push(...descriptorMemberProblems(d));
  for (const [name, argv] of Object.entries(d.commands ?? {})) {
    if (!['doctor', 'update'].includes(name)) problems.push(`unknown command ${shownMember(name)}`);
    else if (!Array.isArray(argv) || !argv.length || !argv.every((a) => typeof a === 'string')) problems.push(`command ${name} must be an argument array`);
    else {
      if (!LOCAL_PATH.test(argv[0])) problems.push(`command ${name} must start with an absolute or ~/ executable`);
      if (argv.some(secretLaunchArgument)) problems.push(`FAC-SEM-057: command ${name} carries a credential in an argument; a process listing shows it: have the program read it from a file it is pointed at (LC-21)`); // a URL inside an argument too (FAA-200 (28))
    }
  }
  return problems;
}

/** DEC-0019: `local` unless the descriptor says `remote`. */

/**
 * What an app that writes its own descriptor does with it on a start (DEC-0069): `keep` from a translocated copy (macOS
 * App Translocation); otherwise `write` when there is none, when it is not an app's descriptor, or when its version
 * (`installedBy.tool`) or its path (`lifecycle.app`) differs; `keep` otherwise. The contract's `appDescriptorAction`.
 */
export function appDescriptorAction(existing, tool, appPath) {
  if (appPath.includes('/AppTranslocation/')) return 'keep';
  if (!isObj(existing) || !isObj(existing.installedBy)) return 'write';
  const recorded = isObj(existing.lifecycle) ? existing.lifecycle.app : undefined;
  return existing.installedBy.tool === tool && recorded === appPath ? 'keep' : 'write';
}

/** Whether a reader treats a descriptor as stale (DEC-0069): an app's descriptor whose installed app it did not find. */
export function appDescriptorStale(descriptor, appPresent) {
  if (!isObj(descriptor) || !isObj(descriptor.lifecycle) || descriptor.lifecycle.manager !== 'person') return false;
  return !appPresent;
}

/** Whether `lifecycle.app` of an app's descriptor exists on this machine (a bundle is a folder, an executable a file). */
export function appPresent(descriptor) {
  const app = isObj(descriptor?.lifecycle) ? descriptor.lifecycle.app : undefined;
  try { return typeof app === 'string' && fs.existsSync(expand(app)); } catch { return false; }
}

/** Fabric's own descriptor (Fabric ADR-0139): `services/fabric.default.json`. */
export const FABRIC_SERVICE = Object.freeze(['fabric', 'default']);

/**
 * `present` or `absent` for Fabric's button (DEC-0040 FB-5, DEC-0069, Fabric SCN-142): present when Fabric's own
 * descriptor is registered and, for an app's descriptor, its app is still installed; a server sets `data-fabric="absent"`
 * on the button's script otherwise. The button only follows a link, so the liveness file is not read here.
 */
export function fabricButtonPresence(dir = servicesDir()) {
  let found;
  try { found = readDescriptorJson(descriptorPath(...FABRIC_SERVICE, dir)); } catch { return 'absent'; }
  if (!isObj(found) || validateDescriptor(found).length) return 'absent';
  return appDescriptorStale(found, appPresent(found)) ? 'absent' : 'present';
}

export function placementOf(d) {
  return d?.placement === 'remote' ? 'remote' : 'local';
}

/** Problems with a remote origin: https, a public DNS name, an optional port, nothing else. */
export function remoteOriginProblems(origin) {
  const m = REMOTE_ORIGIN.exec(String(origin ?? ''));
  if (!m) return ['a remote origin must be https://<dns-name>[:<port>] with no path, query or IP literal'];
  if (RESERVED_HOST.test(m[1])) return [`a remote service cannot live on the reserved name ${m[1]}`];
  if (m[2] !== undefined && (Number(m[2]) < 1 || Number(m[2]) > 65535)) return ['the origin port is out of range'];
  return [];
}

export function portOf(origin) {
  const m = ORIGIN.exec(origin);
  if (!m) throw new ServiceError(`Origin ${origin} is not http://127.0.0.1:<port>.`);
  return Number(m[1]);
}

export const NO_SOURCE_REPOSITORY = 'names no source.repository, the repository its code is built from '
  + '(https://github.com/owner/name): it links the agent to its project (FAA-198)';
const PASS_SOURCE = 'Name it in this call: source: { repository } in the descriptor writeDescriptor writes, or in '
  + 'registerRemote\'s options; one written after the call returns is too late for a new install.';

// FAA-198: why a new install of this (valid) descriptor is refused, or null: it names no source.repository and no
// descriptor of its id.instance is installed yet. An installer checks it before it writes anything else.
export const namesRepository = (d) => d?.source !== null && typeof d?.source === 'object' && !Array.isArray(d.source)
  && typeof d.source.repository === 'string' && d.source.repository !== '';

// An installed descriptor is a regular file, whatever it holds; a folder, a broken link or a path that cannot be
// examined is none.
export function sourceRefusal(d, dir = servicesDir()) {
  if (namesRepository(d)) return null;
  const instance = d?.instance ?? 'default';
  // An id or instance that is no string names no installed file, in both kits (seam reading 3).
  try { if (typeof d?.id === 'string' && typeof instance === 'string' && fs.statSync(descriptorPath(d.id, instance, dir)).isFile()) return null; } catch { /* not installed */ }
  return `Descriptor ${d?.id}.${instance} ${NO_SOURCE_REPOSITORY}. ${PASS_SOURCE}`;
}

// The child that answers portOwner: a plain listen on 127.0.0.1:<port> that succeeds means nothing holds it (the table
// is not read); one that fails asks fabric-peer-owner's listener. A child, because writeDescriptor is synchronous.
const PORT_OWNER_CHILD = `
import net from 'node:net';
const [port, url] = process.argv.slice(1);
const say = (value) => process.stdout.write(JSON.stringify(value));
const server = net.createServer();
server.once('error', async () => {
  try { const { listener } = await import(url); const who = await listener(Number(port)); say([who.kind, Number.isInteger(who.uid) ? who.uid : null]); }
  catch { say(['unknown', null]); }
});
server.listen({ port: Number(port), host: '127.0.0.1', exclusive: true }, () => server.close(() => say(null)));
`;

// How a loopback server treats the OS account of the process that connected (DEC-0154 HA-2's server side, HA-3;
// FAA-227): `refuse` (the default) closes a connection whose peer is another OS account's before reading a byte of it
// and serves the rest, labelled; `strict` also refuses a peer whose owner cannot be told and a system account other
// than root (uid 0, which can read every account's files and installs a LaunchDaemon); `off` reads no table. The twin
// of fabric_descriptor.py's PEER_CHECKS and LoopbackHTTPServer.
export const PEER_CHECKS = Object.freeze(['refuse', 'strict', 'off']);

/** Why a server refuses the peer `owner` (a fabric-peer-owner owner) under `mode`, or null to serve it: the owner's
 * kind, or for `unknown` its reason; never an address or anything the peer sent. */
export function connectionRefusal(owner, mode = 'refuse') {
  if (!PEER_CHECKS.includes(mode)) throw new ServiceError(`peerCheck must be one of ${PEER_CHECKS.join(', ')}.`);
  if (mode === 'off' || owner === null || owner === undefined) return null;
  const kind = owner.kind ?? UNKNOWN;
  if (kind === ANOTHER_ACCOUNT) return kind;
  if (mode === 'strict' && kind !== THIS_ACCOUNT) {
    if (kind === SYSTEM && owner.uid === 0) return null;
    return owner.reason || kind;
  }
  return null;
}

/** Whether a connection's peer address is a loopback one (127.0.0.0/8, ::1, or either IPv4-mapped): the only peers
 * whose owner can be another account of this computer (DEC-0154 HA-2). An address that cannot be read counts as
 * loopback, so its owner is still read from the table. The twin of fabric_descriptor.py's is_loopback_peer. */
export function isLoopbackPeer(address) {
  if (typeof address !== 'string') return true;
  const host = normHost(address);
  if (net.isIPv4(host)) return host.split('.')[0] === '127';
  if (net.isIPv6(host)) return host === '::1';
  return true;
}

const connectionOwners = new WeakMap();

/** The owner of the peer behind an HTTP request's socket (`req.socket`) a loopbackServer served, or null. */
export function connectionOwner(socket) {
  return connectionOwners.get(socket) ?? null;
}

/** A net.Server to listen on in place of `httpServer` (DEC-0154 HA-2's server side, FAA-227): each connection arrives
 * paused, its peer is told from the computer's socket table (`peer`, fabric-peer-owner's by default), and only a peer
 * `peerCheck` serves is handed to `httpServer` (never listened on itself), which then reads the request; a refused one
 * is destroyed unread, counted in `peerRefusals`, and reported to `onRefused(owner, reason)` (default: one line on
 * stderr with the owner's kind, uid and pid). Handlers find their peer's owner with `connectionOwner(req.socket)`.
 * The check applies to loopback peers only: a peer at another address (a server bound to 0.0.0.0) is no local
 * account, so its table is not read and it is served under `refuse` and `strict` alike, with no owner.
 * Close the returned server to stop accepting; `httpServer.closeAllConnections()` ends the served ones. */
export function loopbackServer(httpServer, { peerCheck = 'refuse', peer = peerOfSocket, onRefused } = {}) {
  connectionRefusal(null, peerCheck);
  const report = onRefused ?? ((who, reason) => process.stderr.write(
    `fabric: refused a loopback peer (${reason}, uid ${who?.uid ?? 'None'}, pid ${who?.pid ?? 'None'}) before reading it (DEC-0154)\n`));
  const gate = net.createServer({ pauseOnConnect: true }, async (socket) => {
    let who = null;
    if (peerCheck !== 'off' && isLoopbackPeer(socket.remoteAddress)) {
      try {
        who = await peer(socket);
      } catch (err) {
        who = peerOwnerOf(UNKNOWN, { reason: `reader: ${err?.name ?? 'Error'}` });
      }
    }
    const reason = connectionRefusal(who, peerCheck);
    if (reason !== null) {
      gate.peerRefusals += 1;
      socket.destroy();
      report(who, reason);
      return;
    }
    if (socket.destroyed) return;
    if (who !== null) connectionOwners.set(socket, who);
    httpServer.emit('connection', socket);
    socket.resume();
  });
  gate.peerRefusals = 0;
  return gate;
}

/** Who listens on 127.0.0.1:<port> now, as [kind, uid] from the kit's fabric-peer-owner, or null when nothing holds it
 * (FAA-225, DEC-0154 HA-2). */
export function portOwner(port) {
  const done = spawnSync(process.execPath, ['--input-type=module', '-e', PORT_OWNER_CHILD, String(port),
    new URL('./fabric-peer-owner.mjs', import.meta.url).href], { encoding: 'utf8', timeout: 10000 });
  try { return JSON.parse(done.stdout); } catch { return ['unknown', null]; }
}

/** Why an install may not take `port`: another OS account listens on it (FAA-225). This account, the system (launchd
 * holds a socket-activated job's socket), nobody and an unreadable table pass. The recorded port per account and its
 * claim file wait on contract DEC-0160. */
export function portListenerRefusal(port, reader = portOwner) {
  const found = reader(port);
  if (!Array.isArray(found) || found[0] !== ANOTHER_ACCOUNT) return null;
  const uid = Number.isInteger(found[1]) ? ` (uid ${found[1]})` : '';
  return `Port ${port} is listened on by another OS account${uid}: choose a port no other account holds (DEC-0154, FAA-225).`;
}

/** FAA-200 (41): the clause the rewrite warning adds when the installed descriptor names a source.repository it drops. */
export const DROPS_INSTALLED_SOURCE = 'the installed descriptor names one, which this rewrite drops';

/** Whether the installed descriptor of id.instance names a source.repository: an unreadable, absent, non-UTF-8 or
 * non-JSON file names none (FAA-200 (41)). Never throws. */
export function installedNamesRepository(id, instance, dir = servicesDir()) {
  try {
    return namesRepository(readDescriptorJson(descriptorPath(id, instance, dir)));
  } catch {
    return false;
  }
}

/** The rewrite warning of a descriptor that names no source.repository (FAA-198); with `dropped`, it names the
 * installed source.repository the rewrite drops (FAA-200 (41)). The repository itself is never in it. */
export function warnNoSource(d, dropped = false) {
  const drop = dropped ? `; ${DROPS_INSTALLED_SOURCE}` : '';
  process.emitWarning(`Descriptor ${d.id}.${d.instance} ${NO_SOURCE_REPOSITORY}${drop}; a new install is refused without it.`, { code: 'FABRIC_NO_SOURCE_REPOSITORY' });
}

/** Installer-only. Refuses a port or id.instance another descriptor claims (a port is a claim), and a port another OS
 * account listens on (FAA-225; `portOwner(port) -> [kind, uid] | null` reads it, the kit's own by default).
 * FAA-198: a new descriptor names its source.repository; rewriting one already installed without it only warns
 * (process.emitWarning, code FABRIC_NO_SOURCE_REPOSITORY, naming an installed source.repository it drops: FAA-200
 * (41)), so an installed agent's update keeps working. */
export function writeDescriptor(d, dir = servicesDir(), { portOwner: reader = portOwner, warned = false } = {}) {
  const problems = validateDescriptor(d);
  if (problems.length) throw new ServiceError(`Descriptor is invalid: ${problems.join('; ')}.`);
  const me = `${d.id}.${d.instance}`;
  const refusal = sourceRefusal(d, dir);
  if (refusal) throw new ServiceError(refusal);
  if (!namesRepository(d) && !warned) warnNoSource(d, installedNamesRepository(d.id, d.instance, dir)); // registerRemote warns itself, before its token (FAA-200 (1))
  // DEC-0019: only a local placement claims a port on this computer; DEC-0069: an app's descriptor names none.
  const port = placementOf(d) === 'remote' || d.origin === undefined ? null : portOf(d.origin);
  for (const [file, other] of readDescriptors(dir)) {
    const key = `${other.id}.${other.instance ?? 'default'}`;
    if (key === me) continue;
    if (port === null) continue; // a remote origin's port is another computer's
    let otherPort = null;
    try { otherPort = portOf(String(other.origin ?? '')); } catch { continue; }
    if (otherPort === port) throw new ServiceError(`Port ${port} is already claimed by ${key} (${file}).`);
  }
  const held = port === null ? null : portListenerRefusal(port, reader);
  if (held) throw new ServiceError(held);
  ensurePrivateDir(dir);
  const target = descriptorPath(d.id, d.instance, dir);
  atomicWrite(target, `${JSON.stringify(d, null, 2)}\n`, 0o600);
  return target;
}

export function removeDescriptor(id, instance = 'default', dir = servicesDir()) {
  try { fs.unlinkSync(descriptorPath(id, instance, dir)); return true; } catch (e) { if (e.code === 'ENOENT') return false; throw e; }
}

const THEME_ID = /^[a-z][a-z0-9-]{0,31}$/;

const KIT_REF = /^[a-z][a-z0-9-]{0,63}@(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$/;

// What makes value not a valid ED-9 declaration (service-dashboard-extension.schema.json).
export function dashboardExtensionProblems(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return ['the declaration is not an object'];
  const out = [];
  const extra = Object.keys(value).filter((k) => !['minWidth', 'appearance', 'themes', 'kit'].includes(k)).sort();
  if (extra.length) out.push(`unknown field(s): ${extra.join(', ')}`);
  const w = value.minWidth;
  if (!Number.isInteger(w)) out.push('minWidth is required and must be a whole number of CSS pixels');
  else if (w < 360 || w > 1280) out.push(`minWidth ${w} is outside 360…1280`);
  if ('appearance' in value) {
    const a = value.appearance;
    if (!Array.isArray(a) || a.length > 2 || new Set(a).size !== a.length || a.some((x) => x !== 'scheme' && x !== 'theme')) out.push('appearance is a list of distinct fields from scheme, theme');
  }
  if ('themes' in value) {
    const t = value.themes;
    if (!Array.isArray(t) || t.length < 1 || t.length > 32 || new Set(t).size !== t.length || t.some((x) => typeof x !== 'string' || !THEME_ID.test(x))) out.push('themes is 1…32 distinct theme ids matching ^[a-z][a-z0-9-]{0,31}$');
  }
  if ('kit' in value && !(typeof value.kit === 'string' && KIT_REF.test(value.kit))) out.push(`kit is name@semver, for example ${DASHBOARD_KIT}`);
  return out;
}

// The `extensions` entry a dashboard built from the kit declares (DEC-0036 ED-9). Declare it only
// when the page meets ED-1…ED-6 — check_dashboard_layout.mjs measures that.
export function dashboardExtension({ minWidth = 360, appearance = ['scheme', 'theme'], themes = REFERENCE_THEMES, kit = DASHBOARD_KIT } = {}) {
  const value = { minWidth };
  if (appearance?.length) value.appearance = [...appearance];
  if (themes?.length) value.themes = [...themes];
  if (kit) value.kit = kit;
  const problems = dashboardExtensionProblems(value);
  if (problems.length) throw new ServiceError(`Dashboard declaration: ${problems.join('; ')}.`);
  return { [DASHBOARD_EXTENSION_KEY]: value };
}

// `extensions` is kept as given (a reader ignores keys it does not know); a dashboard declaration in
// it must be valid (dashboardExtension builds one).
const PROFILE_ID = /^[a-z][a-z0-9-]{0,62}$/;

const RUNNER_KIND = /^[a-z][a-z0-9-]{1,62}$/;

const MODEL_ID = /^[a-z0-9][a-z0-9._-]{0,63}\/[a-z0-9][a-z0-9._:-]{0,127}$/;

/** DEC-0046: the well-known `configuration` — {slots, resolved} as service-well-known.schema.json types it. */
export function configurationProblems(doc) {
  if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) return ['configuration is an object'];
  const problems = Object.keys(doc).filter((k) => k !== 'slots' && k !== 'resolved').map((k) => `configuration has no member ${shownMember(k)}`);
  const { slots, resolved } = doc;
  if (!Array.isArray(slots) || slots.length > 2 || new Set(slots).size !== slots.length || !slots.every((s) => s === 'runner' || s === 'model')) problems.push('slots is a list of runner and model, each once');
  if (resolved === null || typeof resolved !== 'object' || Array.isArray(resolved)) return [...problems, 'resolved is an object'];
  const checks = {
    from: (x) => ['request', 'agent', 'binding', 'estate'].includes(x),
    runnerProfile: (x) => typeof x === 'string' && PROFILE_ID.test(x),
    modelProfile: (x) => typeof x === 'string' && PROFILE_ID.test(x),
    runnerKind: (x) => typeof x === 'string' && RUNNER_KIND.test(x),
    route: (x) => ROUTES.includes(x),
    models: (x) => Array.isArray(x) && x.length <= 16 && x.every((m) => typeof m === 'string' && MODEL_ID.test(m)),
  };
  for (const [k, v] of Object.entries(resolved)) {
    if (!Object.hasOwn(checks, k)) problems.push(`resolved has no member ${shownMember(k)}`);
    else if (!checks[k](v)) problems.push(`resolved.${k} is not valid`);
  }
  return problems;
}

// `actions` (DEC-0121 AP-1) is the service's action table, every button its dashboard, app or page offers with the tool
// that performs it and its gate, written under extensions/actions/0.1 by actionsExtension. A declaration FAC-SEM-142
// finds, passed either way, is refused: not its schema's, an id named twice, a humanStep that disagrees with the gate,
// or a tool surfaces.mcp.capabilities does not list.
// `a2a` (DEC-0122) is surfaces.a2a, where the service serves its public Agent Card (a2aSurface builds one); passed here
// or in `surfaces`, never both, and refused when it is not the schema's. A reader pinned before DEC-0122 refuses the
// member, so a service carries it only once its readers are pinned at or after it.
// FAA-244: DEC-0140 PR-1 reserves the primary responder's capability; a service never publishes it.
const reserved = (where) => `${where}: ${PRIMARY_CAPABILITY} is reserved for a Project's primary responder, a session (DEC-0140 PR-1); a service never serves it as a tool or declares it.`;

export function buildWellKnown({ id, instance, name, version, build, startedAt, status, degraded = [], surfaces, summary, updateAvailable = null, pid = process.pid, extensions, configuration, protocols, actions, a2a }) {
  if (!STATUSES.includes(status)) throw new ServiceError(`status must be one of ${STATUSES.join(', ')}.`);
  if (!surfaces?.events) throw new ServiceError('surfaces.events is required.');
  if (a2a !== undefined && a2a !== null) {
    if (Object.hasOwn(surfaces, 'a2a')) throw new ServiceError('surfaces.a2a: pass it in surfaces or as a2a, not both.');
    surfaces = { ...surfaces, a2a };
  }
  if (Object.hasOwn(surfaces, 'a2a')) {
    // DEC-0122: a host reads the member by the schema; a service never publishes one it would refuse.
    const problems = a2aSurfaceProblems(surfaces.a2a);
    if (problems.length) throw new ServiceError(`surfaces.a2a: ${problems.join('; ')}.`);
  }
  if (Array.isArray(surfaces.mcp?.capabilities) && surfaces.mcp.capabilities.includes(PRIMARY_CAPABILITY)) throw new ServiceError(reserved('surfaces.mcp.capabilities'));
  if (!(build?.commit || build?.digest)) throw new ServiceError('build needs a commit or a digest.');
  const doc = {
    protocol: PROTOCOL,
    service: { id, instance, name, version, build },
    process: { pid, startedAt },
    status: status === 'ready' && degraded.length ? 'degraded' : status,
    degraded: [...degraded],
    surfaces,
    update: { available: updateAvailable },
  };
  if (summary?.length) doc.summary = summary.slice(0, 6);
  if (actions !== undefined && actions !== null) {
    if (extensions && Object.hasOwn(extensions, ACTIONS_EXTENSION_KEY)) throw new ServiceError('Actions declaration: pass the action table or a ready declaration, not both.');
    const capabilities = Array.isArray(surfaces.mcp?.capabilities) ? surfaces.mcp.capabilities : undefined;
    extensions = { ...(extensions ?? {}), ...actionsExtension(actions, { capabilities }) };
  }
  if (extensions && Object.keys(extensions).length) {
    if (DASHBOARD_EXTENSION_KEY in extensions) {
      const problems = dashboardExtensionProblems(extensions[DASHBOARD_EXTENSION_KEY]);
      if (problems.length) throw new ServiceError(`Dashboard declaration: ${problems.join('; ')}.`);
    }
    if (Object.hasOwn(extensions, CONNECTIONS_EXTENSION_KEY)) {
      // DEC-0096: a host hides an invalid declaration (FAC-SEM-127); a service never publishes one.
      const view = connectionsView({ extensions: { [CONNECTIONS_EXTENSION_KEY]: extensions[CONNECTIONS_EXTENSION_KEY] } });
      if (view.reported) throw new ServiceError(`Connections declaration: ${view.errors.join('; ')}.`);
    }
    if (Object.hasOwn(extensions, ACTIONS_EXTENSION_KEY)) {
      // DEC-0121 AP-1: a host reports an invalid declaration (FAC-SEM-142); a service never publishes one. The tools are
      // compared with the capabilities this document's MCP surface lists.
      const findings = actionsExtensionRules({ extensions: { [ACTIONS_EXTENSION_KEY]: extensions[ACTIONS_EXTENSION_KEY] }, surfaces });
      if (findings.length) throw new ServiceError(`Actions declaration: ${findings.map((f) => f.message).join('; ')}.`);
      if ((extensions[ACTIONS_EXTENSION_KEY]?.actions ?? []).some((a) => a?.tool === PRIMARY_CAPABILITY)) throw new ServiceError(reserved("an action's tool"));
    }
    doc.extensions = { ...extensions };
  }
  if (configuration !== undefined) {
    const problems = configurationProblems(configuration);
    if (problems.length) throw new ServiceError(`configuration: ${problems.join('; ')}.`);
    doc.configuration = configuration;
  }
  if (protocols !== undefined) {
    // DEC-0067: the revisions this service accepts. The document is closed for a reader pinned before DEC-0067, so a
    // service lists them only once its hosts are pinned at or after it.
    const problems = protocolsFindings(protocols);
    if (problems.length) throw new ServiceError(`protocols: ${problems.map((f) => f.message).join('; ')}.`);
    doc.protocols = [...protocols];
  }
  return doc;
}
