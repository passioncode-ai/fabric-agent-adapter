// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
// A service descriptor's members (fabric-service/0.1; DEC-0061, DEC-0069, FAA-120): installedBy, runner, peer and source,
// read as the schema shapes them, the source.repository rule and a git origin's identity (DEC-0089 item 2), and the
// host's peer check. Every function answers by a rule and touches no file; fabric-descriptor.mjs re-exports every public
// name here. Part of the Node service kit (split from fabric-descriptor.mjs; layer L3); the twin of
// fabric_descriptor_members.py. No dependency.
// Example URLs write their scheme in angle brackets: read `<https>` as `https` (FAA-212).
import { repositoryCredential, secretArgument } from './fabric-secrets.mjs';

export const RESERVED_HOST = /(^|\.)(localhost|local|internal|home\.arpa|lan|localdomain)$/;

export const HIERARCHICAL = /^[A-Za-z][A-Za-z0-9+.-]*:\/\//;

/** Why a value is no `source.repository` the kit takes, or null: validateDescriptor's reading (FAA-198). */
export function sourceRepositoryProblem(repository) {
  if (!(typeof repository === 'string' && SOURCE_URI.test(repository.replace(IP_LITERAL, '$1h')))) return 'source.repository is a URI (RFC 3986), such as https://github.com/owner/name';
  if (URI_PASSWORD.test(repository)) return 'source.repository carries no password: it names the repository, never a credential'; // before the host
  if (repository.includes('@') && !HIERARCHICAL.test(repository)) return 'source.repository with a user is a URL with an authority (https://user@host/path), never an scp form'; // readings 7, before the authority (0.86.0)
  if (!authorityOk(repository)) return 'source.repository names a host, and a port of digits up to 65535 when it has one';
  if (repositoryCredential(repository)) return "FAC-SEM-086: /source/repository holds a value shaped like a credential; it names a repository: write the repository's name in lower case if it is one"; // its name is no key (seam 6)
  return null;
}

const ORIGIN_SCHEMES = ['http', 'https', 'ssh', 'git', 'git+ssh', 'git+https']; // normalizeOrigin's (DEC-0089 item 2)
const asciiLower = (value) => value.replace(/[A-Z]/g, (letter) => letter.toLowerCase());

/** A remote's repository identity `host/path`, or null: the contract's normalizeOrigin (DEC-0089 item 2), held to its
 * origin vectors (test/fixtures/contract/origin-vectors.json). Never throws. */
export function originIdentity(raw) {
  if (typeof raw !== 'string' || [...raw.slice(0, 8193)].length > 4096) return null;
  const value = raw.trim();
  let host;
  let path;
  const scheme = /^([a-z][a-z0-9+.-]*):\/\//i.exec(value);
  if (scheme) {
    if (!ORIGIN_SCHEMES.includes(scheme[1].toLowerCase())) return null;
    const rest = value.slice(scheme[0].length).split(/[?#]/)[0];
    const slash = rest.indexOf('/');
    if (slash < 0) return null;
    host = rest.slice(0, slash);
    path = rest.slice(slash + 1);
  } else {
    if (value.startsWith('/') || /^[A-Za-z]:[\\/]/.test(value) || value.startsWith('.')) return null;
    const scp = /^(?:[^@/\s]+@)?([^:/\s]+):([^\s]+)$/.exec(value);
    if (!scp) return null;
    host = scp[1];
    path = scp[2].split(/[?#]/)[0];
  }
  host = asciiLower(host.slice(host.lastIndexOf('@') + 1).replace(/:[0-9]*$/, ''));
  let [start, end] = [0, path.length]; // the outer `/` trimmed in linear time, as the contract's trimSlashes
  while (start < end && path[start] === '/') start += 1;
  while (end > start && path[end - 1] === '/') end -= 1;
  path = asciiLower(path.slice(start, end));
  if (path.endsWith('.git')) path = path.slice(0, -4);
  const segments = path.split('/');
  if (!/^[a-z0-9.-]+$/.test(host) || !host.includes('.') || segments.length < 2 || segments.some((segment) => segment === '' || /\s/.test(segment))) return null;
  return `${host}/${segments.join('/')}`;
}

/** An installer's git origin (scp form included) as the `https://host/owner/name` source.repository takes, or null
 * (no identity, or one the kit's rules refuse: no URI, a key's shape); no credential of it travels (FAA-200 (45)). */
export function repositoryFromOrigin(origin) {
  const identity = originIdentity(origin);
  const repository = identity === null ? null : `https://${identity}`;
  return repository === null || sourceRepositoryProblem(repository) ? null : repository;
}

/** The organization edition's data classes, least sensitive first (DEC-0061, DEC-0053). */
export const PEER_DATA_CLASSES = Object.freeze(['public', 'internal', 'confidential', 'restricted']);

/** The kind of a runner's sign-in, never a credential's value (DEC-0061). */
export const CREDENTIAL_KINDS = Object.freeze(['subscription', 'key', 'platform-metered', 'none']);

/** A subscription runs only in its vendor's runner (DEC-0046): runner kind → login. */
export const SUBSCRIPTION_RUNNERS = Object.freeze({ 'claude-code': 'claude', 'kimi-code': 'kimi', codex: 'chatgpt' });

const PEER_ENDPOINT = /^https:\/\/((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63})(:([1-9][0-9]{0,3}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5]))?(\/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*)?$/;

// FAA-120: source.repository is the schema's common `uri`: RFC 3986 characters only (unreserved, reserved and %HH),
// the same in both twins; an authority, when there is one, names a host and a port of digits up to 65535, as Fabric's
// `new URL` reads it. A user:password@ in it is a credential, never the name of a repository.
const SOURCE_URI = /^[A-Za-z][A-Za-z0-9+.-]*:(?:[A-Za-z0-9._~:/?#@!$&'()*+,;=-]|%[0-9A-Fa-f]{2})+$/;
// Brackets belong to an IP-literal host only (RFC 3986 3.2.2); the literal is set aside before the character check.
const IP_LITERAL = /^([A-Za-z][A-Za-z0-9+.-]*:\/\/(?:[^/?#@[\]]*@)?)\[[0-9A-Fa-f:.vV]+\]/;
// A special scheme's authority starts after any run of slashes, none included, as `new URL` reads it, so
// <https>:github.com:99999/o/r is read for its port too (FAA-200 (56)); any other scheme has one only after `//`.
// A special scheme's repository is written with exactly two slashes: `new URL` also reads <https>:github.com/o/r and
// <https>:////github.com/o/r, which no repository-match rule joins to a checkout (the Python twin's rule).
const URI_AUTHORITY = /^(?:([Hh][Tt][Tt][Pp][Ss]?|[Ww][Ss][Ss]?|[Ff][Tt][Pp]):(\/*)|[A-Za-z][A-Za-z0-9+.-]*:\/\/)(?:[^/?#@]*@)?(\[[^\]]*\]|[^/?#:]*)(?::([^/?#]*))?/;
function authorityOk(uri) {
  const m = URI_AUTHORITY.exec(uri);
  if (!m) return true;
  const [, special, slashes, host, port] = m;
  if (!host || !(port === undefined || port === '' || (/^[0-9]{1,5}$/.test(port) && Number(port) <= 65535))) return false;
  return !special || (slashes === '//' && specialHostOk(host));
}
// The WHATWG URL standard's IPv4 number parser: decimal, 0x hexadecimal or 0-led octal; null on failure.
function ipv4Number(part) {
  let radix = 10;
  if (/^0[xX]/.test(part)) { part = part.slice(2); radix = 16; } else if (part.length > 1 && part[0] === '0') { part = part.slice(1); radix = 8; }
  if (part === '') return 0;
  const digits = { 10: /^[0-9]+$/, 16: /^[0-9a-fA-F]+$/, 8: /^[0-7]+$/ }[radix];
  return digits.test(part) ? parseInt(part, radix) : null;
}
// FAA-200 (37): a special scheme's host as `new URL` would accept it, read by the same rules as the Python twin's
// _special_host_ok: never percent-encoded, a bracketed host an IPv6 address, a host ending in a number a whole IPv4.
function specialHostOk(host) {
  if (host.includes('%')) return false;
  if (host.startsWith('[')) {
    if (!host.endsWith(']')) return false;
    try { return new URL(`http://${host}/`).hostname !== ''; } catch { return false; }
  }
  let parts = host.split('.');
  if (parts.length > 1 && parts[parts.length - 1] === '') parts = parts.slice(0, -1);
  const last = parts[parts.length - 1];
  if (!(last !== '' && (/^[0-9]+$/.test(last) || ipv4Number(last) !== null))) return true;
  const numbers = parts.map((p) => (p === '' ? null : ipv4Number(p)));
  if (parts.length > 4 || numbers.includes(null)) return false;
  return numbers.slice(0, -1).every((n) => n <= 255) && numbers[numbers.length - 1] < 256 ** (5 - numbers.length);
}
// A special scheme reads a user:password@ after any run of slashes, none included, as `new URL` does (0.56.0 seam r7).
// To the last @, a user name may hold one; any other scheme keeps a backslash in the user information (seam r8).
// The user part stops at its first colon: the same verdict in linear time, where a user part that may hold colons
// backtracked quadratically on a run of them (FAA-200 (44)).
const URI_PASSWORD = /^(?:(?:[Hh][Tt][Tt][Pp][Ss]?|[Ww][Ss][Ss]?|[Ff][Tt][Pp]):[/\\]*[^/\\?#:]*:[^/\\?#]*@|(?![Hh][Tt][Tt][Pp][Ss]?:|[Ww][Ss][Ss]?:|[Ff][Tt][Pp]:)[A-Za-z][A-Za-z0-9+.-]*:\/\/[^/?#:]*:[^/?#]*@)/;
const RESIDENCY = /^(A[B-Z]|[B-PR-WY][A-Z]|Q[A-L]|Z[A-Y])$/;

const RUNNER_KIND_NAME = /^[a-z][a-z0-9-]{1,62}$/;

export const isObj = (v) => typeof v === 'object' && v !== null && !Array.isArray(v);

const textOfLength = (v, low = 1, high = 200) => typeof v === 'string' && v.length >= low && v.length <= high;

/** A JSON Pointer token (RFC 6901 §4). */
const pointer = (name) => String(name).replace(/~/g, '~0').replace(/\//g, '~1');
/** A member name as a problem prints it: `<redacted>` when it is shaped like a credential (FAA-200 (39), fabric_descriptor._shown_member). */
export const shownMember = (name) => (secretArgument(String(name)) ? '<redacted>' : String(name));

/**
 * DEC-0061 and DEC-0069 on a descriptor's `installedBy`, `runner` and `peer`, as the schema shapes them, with FAC-SEM-085
 * (a peer on a reserved name) and FAC-SEM-086 (a credential-shaped value in `runner` or `installedBy`, named by its
 * place, never its value).
 */
export function descriptorMemberProblems(d) {
  const problems = [];
  const life = isObj(d.lifecycle) ? d.lifecycle : {};
  const by = d.installedBy;
  const places = [];
  if (typeof by === 'string') {
    if (!textOfLength(by)) problems.push('installedBy is the installer and its version, 1 to 200 characters');
    places.push(['/installedBy', by]);
  } else if (isObj(by)) {
    for (const k of Object.keys(by)) if (!['by', 'role', 'tool'].includes(k)) problems.push(`installedBy has no member ${shownMember(k)}`);
    if (!['person', 'node', 'organization'].includes(by.by)) problems.push('installedBy.by is person, node or organization');
    if (by.by === 'person' && !['operator', 'administrator'].includes(by.role)) problems.push('installedBy.role is operator or administrator for a person');
    if (by.by !== 'person' && 'role' in by) problems.push('installedBy.role belongs to a person only');
    if (!textOfLength(by.tool)) problems.push('installedBy.tool is the installer and its version, 1 to 200 characters');
    for (const [k, v] of Object.entries(by)) places.push([`/installedBy/${pointer(shownMember(k))}`, v]);
  } else problems.push("installedBy is the installer's name or {by, role?, tool}");
  if (life.manager === 'person' && !(isObj(by) && by.by === 'person')) problems.push("an app's descriptor names who installed it as a person: installedBy {by: person, role, tool} (DEC-0069)");
  let runner = d.runner;
  if ('runner' in d) {
    if (!isObj(runner)) { problems.push('runner is {kind?, credentialKind}'); runner = {}; }
    for (const k of Object.keys(runner)) if (!['kind', 'credentialKind'].includes(k)) problems.push(`runner has no member ${shownMember(k)}`);
    if (!CREDENTIAL_KINDS.includes(runner.credentialKind)) problems.push('runner.credentialKind is subscription, key, platform-metered or none');
    if ('kind' in runner && !(typeof runner.kind === 'string' && RUNNER_KIND_NAME.test(runner.kind))) problems.push("runner.kind is a runner kind's name");
    if (runner.credentialKind === 'subscription' && !(typeof runner.kind === 'string' && Object.hasOwn(SUBSCRIPTION_RUNNERS, runner.kind))) problems.push("a subscription runs only in its vendor's runner: runner.kind claude-code, kimi-code or codex");
    for (const [k, v] of Object.entries(runner)) places.push([`/runner/${pointer(shownMember(k))}`, v]);
  }
  if ('source' in d) {
    const source = isObj(d.source) ? d.source : {};
    if (!isObj(d.source)) problems.push('source is {repository?}');
    for (const k of Object.keys(source)) if (k !== 'repository') problems.push(`source has no member ${shownMember(k)}`);
    const problem = 'repository' in source ? sourceRepositoryProblem(source.repository) : null;
    if (problem) problems.push(problem);
  }
  if ('peer' in d) {
    let peer = d.peer;
    if (!isObj(peer)) { problems.push('peer is {endpoint, custody, residency, maxDataClass}'); peer = {}; }
    for (const k of Object.keys(peer)) if (!['endpoint', 'custody', 'residency', 'maxDataClass'].includes(k)) problems.push(`peer has no member ${shownMember(k)}`);
    const m = typeof peer.endpoint === 'string' && peer.endpoint.length <= 2048 ? PEER_ENDPOINT.exec(peer.endpoint) : null;
    if (!m) problems.push('peer.endpoint is https://<dns-name>[:<port>][/<path>], no query, fragment, userinfo or IP literal');
    else if (RESERVED_HOST.test(m[1])) problems.push(`FAC-SEM-085: a service offered to others cannot be reached at the reserved name ${m[1]}`);
    if (!['organization-managed', 'personal', 'processor-hosted'].includes(peer.custody)) problems.push('peer.custody is organization-managed, personal or processor-hosted'); // processor-hosted: DEC-0099
    const r = peer.residency;
    if (!Array.isArray(r) || r.length < 1 || r.length > 32 || new Set(r.map((x) => JSON.stringify(x))).size !== r.length || !r.every((x) => typeof x === 'string' && RESIDENCY.test(x))) {
      problems.push('peer.residency is 1 to 32 distinct ISO 3166-1 alpha-2 codes in upper case, EU admitted, no user-assigned code');
    }
    if (!PEER_DATA_CLASSES.includes(peer.maxDataClass)) problems.push('peer.maxDataClass is public, internal, confidential or restricted');
    if (!('runner' in d)) problems.push('a service offered to others declares runner (DEC-0061)');
    else if (isObj(runner) && runner.credentialKind === 'subscription') problems.push('a service offered to others never runs on a subscription (DEC-0061)');
  }
  for (const [place, value] of places) {
    // places are /installedBy and /runner alone: /source/repository has its own check above (FAA-200 (57))
    if (typeof value === 'string' && secretArgument(value)) problems.push(`FAC-SEM-086: ${place} holds a value shaped like a credential; it names a kind, a role or an installer`);
  }
  return problems;
}

/**
 * The host's check before it routes a request from anyone but the service's operator (DEC-0061, FAC-SEM-088):
 * `not-offered`, `peer-invalid`, `data-class-unknown` or `above-max-data-class`; null when it may. The contract's `peerRefusal`.
 */
export function peerRefusal(descriptor, dataClass) {
  if (!isObj(descriptor) || !isObj(descriptor.peer)) return 'not-offered';
  const max = typeof descriptor.peer.maxDataClass === 'string' ? PEER_DATA_CLASSES.indexOf(descriptor.peer.maxDataClass) : -1;
  if (max < 0) return 'peer-invalid';
  const asked = typeof dataClass === 'string' ? PEER_DATA_CLASSES.indexOf(dataClass) : -1;
  if (asked < 0) return 'data-class-unknown';
  return asked > max ? 'above-max-data-class' : null;
}
