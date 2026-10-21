// Reference kit for the fabric-service/0.1 local service extension — Node.js 20+, no dependencies.
// The Node twin of fabric_service.py: same rules, same file formats, interoperable locks.
// Normative source: fabric-agent-contract docs/specification/service.md (DEC-0015; the remote
// placement — an online agent or dashboard at an https origin — DEC-0019; the usage report DEC-0021).

import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { normalIdentifier } from './fabric-identifiers.mjs';
import { credentialName, secretArgument, secretUrl, secretValue } from './fabric-secrets.mjs';

export const PROTOCOL = 'fabric-service/0.1';
export const EXTENSION_KEY = 'https://fabric.passioncode.ai/agent-contract/extensions/service/0.1';
// The embedded dashboard declaration (fabric-dashboard/0.1, DEC-0036 ED-9), under the well-known
// document's `extensions`. The kit is assets/dashboard-kit; its version is the one in kit.json.
export const DASHBOARD_EXTENSION_KEY = 'https://fabric.passioncode.ai/agent-contract/extensions/dashboard/0.1';
export const DASHBOARD_KIT = 'fabric-dashboard-kit@1.1.1';
export const REFERENCE_THEMES = ['graphite', 'fabric', 'paper', 'forest', 'ocean', 'ember', 'contrast'];
export const EXIT_ALREADY_RUNNING = 75;
// Lifecycle rules: references/lifecycle.md (the rule for this kit's users; it implements the public
// contract's service specification, Lifecycle), the same values as fabric_service.py.
// A launchd-supervised copy that finds the lock held backs off in-process before its exit 75 (LC-03).
export const SUPERVISOR_ENV = 'FABRIC_SERVICE_SUPERVISOR';
export const LOCK_WAIT_SUPERVISED_SECONDS = 300;
export const LOCK_BACKOFF_FIRST_SECONDS = 0.5;
export const LOCK_BACKOFF_MAX_SECONDS = 30;
// LC-01: SIGTERM reaches exit in at most 10 s with work in flight — drain 8 s, hard exit 2 s later.
export const DRAIN_SECONDS = 8;
export const DRAIN_GRACE_SECONDS = 2;
export const EXIT_HARD_STOP = 70;
// LC-12: logs rotate by size, 5 x 5 MB by default.
export const LOG_MAX_BYTES = 5 * 1024 * 1024;
export const LOG_BACKUPS = 5;
export const LEVELS = ['info', 'notice', 'warning', 'error'];
export const STATUSES = ['starting', 'ready', 'degraded', 'stopping'];
export const EVENTS_DEFAULT_LIMIT = 50;
export const EVENTS_MAX_LIMIT = 200;
export const SESSION_COOKIE = 'fabric_session';
// DEC-0019: a remote placement's cookie is host-bound and HTTPS-only.
export const REMOTE_SESSION_COOKIE = '__Host-fabric_session';
export const PLACEMENTS = ['local', 'remote'];

const ID = /^[a-z][a-z0-9-]{1,62}$/;
const INSTANCE = /^[a-z][a-z0-9-]{0,31}$/;
const KIND = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){0,5}$/;
const ORIGIN = /^http:\/\/127\.0\.0\.1:([0-9]{3,5})$/;
const REMOTE_ORIGIN = /^https:\/\/((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63})(?::([0-9]{1,5}))?$/;
const RESERVED_HOST = /(^|\.)(localhost|local|internal|home\.arpa|lan|localdomain)$/;
const CODE = /^[A-Za-z0-9_-]{16,256}$/;
const TRACE_ID = /^(?!0{32}$)[0-9a-f]{32}$/;
const SPAN_ID = /^(?!0{16}$)[0-9a-f]{16}$/;
const O_EXLOCK = 0x20; // BSD/macOS: open(2) takes flock(LOCK_EX); absent from fs.constants
// DEC-0032: a local path starts with ~/ (or ~\ on Windows), / (never //) or a drive letter; a network share never does.
// DEC-0057: `//server/…` and `/\\server…` are shares on Windows too, so a leading slash is followed by neither.
const LOCAL_PATH = /^(~[\\/]|\/(?![\\/])|[A-Za-z]:[\\/])/;
// DEC-0061: `node` (Project Observatory's node supervises its children, no supervisor file); DEC-0069: `person` (an app a
// person installs and starts; its descriptor says it is installed, never that it runs).
export const MANAGERS = Object.freeze(['launchd', 'systemd', 'task-scheduler', 'node', 'person', 'none']);
/** Managers that write no launchd label or plist (DEC-0057, DEC-0061, DEC-0069). */
const NOT_LAUNCHD = Object.freeze(['systemd', 'task-scheduler', 'node', 'person']);
const AUTH_HEADER = /^[A-Za-z][A-Za-z0-9-]{0,63}$/;
const UNIT = /^[A-Za-z0-9][A-Za-z0-9:_.@-]{0,250}\.service$/;
const TASK = /^\\[A-Za-z0-9 ._\\-]{1,254}$/;
export const WINDOWS_TRUSTED = Object.freeze(['S-1-5-18', 'S-1-5-32-544']);
export const DEFAULT_EXIT_TIMEOUT = 15;

export class ServiceError extends Error {}
export class AlreadyRunning extends ServiceError {
  constructor(holderPid, lockPath) {
    // FAC-SEM-078: a copy that cannot learn the holder's pid says the holder is unknown.
    super(`Another copy is already running (${holderPid ? `process ${holderPid}` : 'an unknown process'} holds ${lockPath}).`);
    this.holderPid = holderPid;
    this.lockPath = lockPath;
  }
}

export const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');

/** Paths in a descriptor may start with ~/ (or ~\\ on Windows); everything else must be absolute,
 * and a network share is never a local path (DEC-0032). */
export function expand(p, platform = process.platform) {
  if (!LOCAL_PATH.test(String(p))) throw new ServiceError(`Path ${p} must be absolute or start with ~/.`);
  const out = /^~[\\/]/.test(p) ? path.join(os.homedir(), p.slice(2)) : p;
  // On Windows an absolute path names its drive: `/x` is relative to the current drive (the Python kit refuses it too).
  const absolute = platform === 'win32' ? /^[A-Za-z]:[\\/]/.test(out) : path.posix.isAbsolute(out);
  if (!absolute) throw new ServiceError(`Path ${p} must be absolute or start with ~/.`);
  return out;
}

// DEC-0032: LOCALAPPDATA, not APPDATA, so token files never roam with the profile.
const localAppData = () => process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');

export function servicesDir(platform = process.platform) {
  if (process.env.FABRIC_SERVICES_DIR) return expand(process.env.FABRIC_SERVICES_DIR);
  const home = os.homedir();
  if (platform === 'darwin') return path.join(home, 'Library/Application Support/ai.passioncode.fabric/services');
  if (platform === 'win32') return path.join(localAppData(), 'passioncode-fabric', 'services');
  return path.join(process.env.XDG_DATA_HOME || path.join(home, '.local/share'), 'passioncode-fabric/services');
}

export function serviceDirs(id, platform = process.platform) {
  if (!ID.test(id)) throw new ServiceError(`Service id ${id} must match ${ID}.`);
  const home = os.homedir();
  if (platform === 'darwin') {
    return {
      data: path.join(home, 'Library/Application Support', id),
      logs: path.join(home, 'Library/Logs', id),
      cache: path.join(home, 'Library/Caches', id),
    };
  }
  if (platform === 'win32') {
    const data = path.join(localAppData(), id);
    return { data, logs: path.join(data, 'Logs'), cache: path.join(data, 'Cache') };
  }
  return {
    data: path.join(process.env.XDG_DATA_HOME || path.join(home, '.local/share'), id),
    logs: path.join(process.env.XDG_STATE_HOME || path.join(home, '.local/state'), id, 'logs'),
    cache: path.join(process.env.XDG_CACHE_HOME || path.join(home, '.cache'), id),
  };
}

export function ensurePrivateDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
  if (process.platform === 'win32') windowsProtect(dir, { folder: true });
  else fs.chmodSync(dir, 0o700);
  return dir;
}

export function atomicWrite(file, data, mode = 0o600) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = path.join(path.dirname(file), `.${path.basename(file)}.${process.pid}.${crypto.randomBytes(4).toString('hex')}`);
  const fd = fs.openSync(tmp, 'wx', mode);
  try {
    // On Windows the file's ACL is its privacy (DEC-0032): set explicitly and protected — before the bytes go in —
    // so it does not depend on what the folder hands down. A rename keeps it.
    if (process.platform === 'win32') windowsProtect(tmp, { folder: false });
    fs.writeSync(fd, data);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  try {
    if (process.platform !== 'win32') fs.chmodSync(tmp, mode);
    fs.renameSync(tmp, file);
  } catch (error) {
    fs.rmSync(tmp, { force: true });
    throw error;
  }
}

// --- one copy: taken BEFORE any side effect --------------------------------------

export class InstanceLock {
  constructor(dataDir) {
    this.path = path.join(dataDir, 'service.lock');
    this.fd = null;
    this.server = null;
  }

  async acquire() {
    ensurePrivateDir(path.dirname(this.path));
    if (process.platform === 'darwin') {
      const flags = fs.constants.O_RDWR | fs.constants.O_CREAT | O_EXLOCK | fs.constants.O_NONBLOCK;
      try {
        this.fd = fs.openSync(this.path, flags, 0o600);
      } catch (error) {
        if (error.code === 'EAGAIN' || error.code === 'EWOULDBLOCK') throw new AlreadyRunning(readPid(this.path), this.path);
        throw error;
      }
      fs.ftruncateSync(this.fd, 0);
      fs.writeSync(this.fd, String(process.pid));
      fs.fsyncSync(this.fd);
      return this;
    }
    // Linux: an abstract unix socket; Windows: a named pipe. Each is exclusive, has no file, and dies
    // with the process. The Python kit holds the same name beside its file lock (fabric_service.lock_name).
    const name = lockName(this.path);
    if (!name) throw new ServiceError(`No instance lock on ${process.platform}: the kit supports macOS, Linux and Windows.`);
    this.server = net.createServer();
    await new Promise((resolve, reject) => {
      // Windows reports a held pipe as EADDRINUSE (access denied) or, when its holder capped the instances, EBUSY.
      const held = (code) => code === 'EADDRINUSE' || (process.platform === 'win32' && code === 'EBUSY');
      this.server.once('error', (error) => reject(held(error.code) ? new AlreadyRunning(readPid(this.path), this.path) : error));
      this.server.listen(name, resolve);
    });
    this.server.unref();
    atomicWrite(this.path, String(process.pid));
    return this;
  }

  release() {
    if (this.fd !== null) fs.closeSync(this.fd);
    if (this.server) this.server.close();
    this.fd = null;
    this.server = null;
  }
}

/** The name the lock is held under on Linux (abstract socket) and Windows (named pipe); null on macOS. */
export function lockName(lockPath, platform = process.platform) {
  const digest = (text) => crypto.createHash('sha256').update(text).digest('hex').slice(0, 32);
  if (platform === 'linux') return `\0fabric-service-${digest(path.posix.resolve(lockPath))}`;
  // Windows paths compare without case: C:\Users and c:\users are one lock.
  if (platform === 'win32') return `\\\\.\\pipe\\fabric-service-${digest(path.win32.resolve(lockPath).toLowerCase())}`;
  return null;
}

function readPid(file) {
  try {
    const text = fs.readFileSync(file, 'utf8').trim();
    return /^\d+$/.test(text) ? Number(text) : null;
  } catch {
    return null;
  }
}

/** The managers a supervisor marker may name (DEC-0057): the three systems' supervisors and Project Observatory's node. */
export const SUPERVISORS = Object.freeze(['launchd', 'systemd', 'task-scheduler', 'node']);
/** The argument form of the marker, for a supervisor whose start carries no environment (a Scheduled Task's action). */
export const SUPERVISOR_ARG = '--fabric-supervisor';

/**
 * The marker values an argument vector carries after the executable and before `--`. A bare `--fabric-supervisor`
 * followed by nothing, by `--` or by another `--…` flag is a marker with an empty value and consumes nothing.
 */
function markerArguments(argv) {
  const values = [];
  if (!Array.isArray(argv)) return values;
  for (let index = 1; index < argv.length; index += 1) {
    const item = argv[index];
    if (item === '--') break;
    if (item === SUPERVISOR_ARG) {
      const next = argv[index + 1];
      if (typeof next === 'string' && !next.startsWith('--')) {
        values.push(next);
        index += 1;
      } else {
        values.push('');
      }
    } else if (typeof item === 'string' && item.startsWith(`${SUPERVISOR_ARG}=`)) {
      values.push(item.slice(SUPERVISOR_ARG.length + 1));
    }
  }
  return values;
}

/**
 * How this copy was started (DEC-0057), from `FABRIC_SERVICE_SUPERVISOR=<manager>` and `--fabric-supervisor <manager>` /
 * `--fabric-supervisor=<manager>` (`env` and `argv` default to this process's; `argv[0]` is the executable or script):
 * `{kind: 'supervised', manager, forms}` when every marker present names the same manager of SUPERVISORS;
 * `{kind: 'conflict', values, forms}` when they disagree (an empty or bare argument beside a variable disagrees with it):
 * the copy exits 75 at once, before it takes the lock; `{kind: 'manual', forms, unreadable?}` with no marker (only an
 * empty variable counts as none) or one that names no manager. Never inferred from the parent process. The contract's
 * `supervisorMarker`.
 */
export function supervisorMarker({ env = process.env, argv = process.argv.slice(1) } = {}) {
  const variable = env?.[SUPERVISOR_ENV];
  const fromEnv = typeof variable === 'string' && variable !== '' ? [variable] : [];
  const fromArgs = markerArguments(argv);
  const forms = [...(fromEnv.length ? ['environment'] : []), ...(fromArgs.length ? ['argument'] : [])];
  const values = [...new Set([...fromEnv, ...fromArgs])];
  if (values.length > 1) return { kind: 'conflict', values, forms };
  if (values.length === 0) return { kind: 'manual', forms };
  return SUPERVISORS.includes(values[0]) ? { kind: 'supervised', manager: values[0], forms } : { kind: 'manual', unreadable: values[0], forms };
}

/** How long a copy started so may wait for the lock, in seconds: 300 when supervised, else not at all. */
export const lockWaitBudgetSeconds = (marker) => (marker?.kind === 'supervised' ? LOCK_WAIT_SUPERVISED_SECONDS : 0);

/** The one sentence a copy whose markers disagree exits with, naming the markers present. */
export function markerConflictMessage(marker) {
  const shown = marker.values.map((v) => JSON.stringify(v)).join(', ');
  return marker.forms.length === 2
    ? `${SUPERVISOR_ENV} and ${SUPERVISOR_ARG} disagree (${shown}); not starting unsupervised.`
    : `${SUPERVISOR_ARG} is given with different values (${shown}); not starting unsupervised.`;
}

/** True when a supervisor that restarts on exit started this process and said so with the marker. */
export const supervised = (start) => supervisorMarker(start).kind === 'supervised';
/** True when launchd started this process from a plist that says so (FABRIC_SERVICE_SUPERVISOR=launchd). */
export const supervisedByLaunchd = (start) => supervisorMarker(start).manager === 'launchd';

const sleepSeconds = (s) => new Promise((resolve) => setTimeout(resolve, s * 1000));

/**
 * Take the lock or exit 75 with one sentence naming the holder (DEC-0057, FAC-SEM-078). Markers that
 * disagree exit 75 before the lock. Started by hand, a held lock exits 75 at once. Under a
 * supervisor that restarts on exit (launchd's KeepAlive) an immediate exit is a respawn every ThrottleInterval,
 * forever; so a supervised copy first backs off in-process (0.5 s doubling to 30 s,
 * LOCK_WAIT_SUPERVISED_SECONDS in all), takes over if the holder leaves, and exits 75 only when
 * the wait runs out. `waitSeconds` overrides the choice (0 = never wait).
 */
export async function holdSingleInstance(dataDir, {
  waitSeconds, sleep = sleepSeconds, clock = () => performance.now() / 1000, exit = (code) => process.exit(code), env, argv,
} = {}) {
  // DEC-0057: markers that disagree exit 75 at once, before the lock, naming them.
  const marker = supervisorMarker({ ...(env === undefined ? {} : { env }), ...(argv === undefined ? {} : { argv }) });
  if (marker.kind === 'conflict') {
    process.stderr.write(`${markerConflictMessage(marker)}\n`);
    return exit(EXIT_ALREADY_RUNNING);
  }
  const wait = waitSeconds ?? lockWaitBudgetSeconds(marker);
  const deadline = clock() + Math.max(0, wait);
  let delay = LOCK_BACKOFF_FIRST_SECONDS;
  let announced = false;
  for (;;) {
    try {
      return await new InstanceLock(dataDir).acquire();
    } catch (error) {
      if (!(error instanceof AlreadyRunning)) throw error;
      const remaining = deadline - clock();
      if (remaining <= 0) {
        process.stderr.write(`${error.message}\n`);
        return exit(EXIT_ALREADY_RUNNING);
      }
      if (!announced) {
        process.stderr.write(`${error.message} Waiting up to ${Math.round(remaining)} s for it to exit.\n`);
        announced = true;
      }
      await sleep(Math.min(delay, remaining));
      delay = Math.min(delay * 2, LOCK_BACKOFF_MAX_SECONDS);
    }
  }
}

// --- token and network guard ------------------------------------------------------

export function ensureToken(file) {
  if (fs.existsSync(file)) return readToken(file);
  ensurePrivateDir(path.dirname(file));
  const token = crypto.randomBytes(32).toString('base64url');
  atomicWrite(file, token, 0o600);
  return token;
}

/**
 * Refuse a symlink, a file owned by someone else, or one others can read. On Windows the rule is
 * service.md "Windows token files" (DEC-0032, DEC-0033, DEC-0057): windowsTokenAclProblem over the
 * file's flags, owner and ACEs; a refusal names the SID, never the contents.
 */
export function readToken(file) {
  const info = fs.lstatSync(file);
  if (info.isSymbolicLink()) throw new ServiceError(`Token file ${file} is a symlink; refusing it.`);
  if (process.platform === 'win32') {
    const problem = windowsTokenProblem(file, info);
    if (problem) throw new ServiceError(problem);
  } else {
    if (typeof process.getuid === 'function' && info.uid !== process.getuid()) throw new ServiceError(`Token file ${file} belongs to another user.`);
    if (info.mode & 0o077) throw new ServiceError(`Token file ${file} is readable by others; set mode 0600.`);
  }
  const token = fs.readFileSync(file, 'utf8').trim();
  if (token.length < 16) throw new ServiceError(`Token file ${file} holds no usable token.`);
  return token;
}

// --- Windows ACLs (DEC-0032) ------------------------------------------------------
// Node has no ACL API. Windows PowerShell (5.1, present on every Windows) reads the list through .NET
// and icacls writes it; both get the path through the environment, never argv, and print no contents.

export const SYSTEM_SID = 'S-1-5-18';
export const ADMINISTRATORS_SID = 'S-1-5-32-544';
/** A string SID: revision 1, an identifier authority and up to 15 sub-authorities of 32 bits each. */
const SID_TEXT = /^S-1-\d{1,15}(-\d{1,10}){0,15}$/i;
/** A readable SID in upper case (SIDs compare case-insensitively on their S), or undefined. */
const sidOf = (value) => (typeof value === 'string' && SID_TEXT.test(value) && value.split('-').slice(3).every((part) => Number(part) <= 0xffffffff) ? value.toUpperCase() : undefined);

/**
 * service.md "Windows token files" (DEC-0032, DEC-0033, DEC-0057, FAC-SEM-079) on what a reader has read: `file` is
 * `{isRegularFile, isReparsePoint, realPathInProfile, ownerSid, aces: [{type, sid, mask}]}`, the mask the ACE's unsigned
 * 32-bit access mask. The first refusal `{problem, at, sid?, message}`, or null when the file may be read: a regular
 * file, not a reparse point, inside the profile; owned by the user, SYSTEM or Administrators; every allow ACE with a
 * non-zero mask naming one of those three; deny ACEs ignored; any other ACE type refused; anything unreadable refused.
 * The contract's `windowsTokenAclProblem`; a refusal names the SID, never the contents.
 */
export function windowsTokenAclProblem(file, currentUserSid) {
  const refuse = (problem, at, message, sid) => (sid === undefined ? { problem, at, message } : { problem, at, sid, message });
  const user = sidOf(currentUserSid);
  if (user === undefined) return refuse('unreadable', '/currentUserSid', "the current user's SID is unreadable");
  if (typeof file !== 'object' || file === null || Array.isArray(file)) return refuse('unreadable', '/file', "the token file's metadata is unreadable");
  for (const flag of ['isRegularFile', 'isReparsePoint', 'realPathInProfile']) {
    if (typeof file[flag] !== 'boolean') return refuse('unreadable', `/file/${flag}`, `${flag} is unreadable`);
  }
  if (file.isReparsePoint) return refuse('reparse-point', '/file/isReparsePoint', 'the token file is a reparse point (a symlink or a junction)');
  if (!file.isRegularFile) return refuse('not-regular-file', '/file/isRegularFile', 'the token file is not a regular file');
  if (!file.realPathInProfile) return refuse('outside-profile', '/file/realPathInProfile', "the token file's real path lies outside the user's profile");
  const trusted = new Set([user, SYSTEM_SID, ADMINISTRATORS_SID]);
  const owner = sidOf(file.ownerSid);
  if (owner === undefined) return refuse('unreadable', '/file/ownerSid', 'the owner SID is unreadable');
  if (!trusted.has(owner)) return refuse('owner', '/file/ownerSid', `the token file is owned by ${owner}, not by the current user, SYSTEM or Administrators`, owner);
  if (!Array.isArray(file.aces)) return refuse('unreadable', '/file/aces', 'the ACL is unreadable');
  for (const [index, ace] of file.aces.entries()) {
    const at = `/file/aces/${index}`;
    if (typeof ace !== 'object' || ace === null || Array.isArray(ace)) return refuse('unreadable', at, `ACE ${index} is unreadable`);
    if (typeof ace.type !== 'string') return refuse('unreadable', `${at}/type`, `ACE ${index} has an unreadable type`);
    const trustee = sidOf(ace.sid);
    if (trustee === undefined) return refuse('unreadable', `${at}/sid`, `ACE ${index} names an unreadable SID`);
    if (typeof ace.mask !== 'number' || !Number.isInteger(ace.mask) || ace.mask < 0 || ace.mask > 0xffffffff) return refuse('unreadable', `${at}/mask`, `ACE ${index} has an unreadable access mask`);
    if (ace.type === 'deny') continue;
    if (ace.type !== 'allow') return refuse('ace-type', `${at}/type`, `ACE ${index} for ${trustee} is of a type the rule does not read`, trustee);
    if (ace.mask === 0) continue;
    if (!trusted.has(trustee)) return refuse('ace-sid', `${at}/sid`, `the token file grants access to ${trustee}; only the current user, SYSTEM and Administrators may hold any`, trustee);
  }
  return null;
}

/** windowsTokenAclProblem as one sentence naming the file and the refusal, or null. */
export function tokenFileProblem(file, metadata, user) {
  const problem = windowsTokenAclProblem(metadata, user);
  return problem ? `Token file ${file} refused: ${problem.message}.` : null;
}

// The raw descriptor, through .NET: every ACE's type, its trustee's SID and its access mask as read (a signed int;
// parseAclReport converts it to the unsigned mask). An inherit-only ACE applies to children only and is left out.
const ACL_SCRIPT = [
  "$ErrorActionPreference = 'Stop'",
  '$acl = [System.IO.File]::GetAccessControl($env:FABRIC_ACL_PATH)',
  "$raw = New-Object System.Security.AccessControl.RawSecurityDescriptor($acl.GetSecurityDescriptorSddlForm('Owner, Access'))",
  '$dacl = $raw.DiscretionaryAcl',
  "$aces = @(if ($dacl) { $dacl | Where-Object { -not ([int]$_.AceFlags -band 8) } | ForEach-Object { @{ type = [string]$_.AceType; sid = $(if ($_.SecurityIdentifier) { $_.SecurityIdentifier.Value } else { '' }); mask = [int64]$_.AccessMask } } })",
  '$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value',
  '[Console]::Out.Write((ConvertTo-Json -Compress -Depth 4 @{ owner = $raw.Owner.Value; aces = $aces; nullDacl = [bool](-not $dacl); user = $user }))',
].join('; ');

function windowsHelper(command, args, extraEnv = {}) {
  // No PSModulePath: the script uses .NET only, and a module path inherited from PowerShell 7 makes
  // Windows PowerShell load the wrong modules.
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => k.toLowerCase() !== 'psmodulepath'));
  const result = spawnSync(command, args, { env: { ...env, ...extraEnv }, encoding: 'utf8', windowsHide: true, timeout: 30_000 });
  if (result.error || result.status !== 0) {
    throw new ServiceError(`${command} failed: ${(result.error?.message || result.stderr || result.stdout || '').trim().slice(0, 200)}`);
  }
  return result.stdout;
}

/** .NET's AceType names as the rule's ACE type: allow and deny are read, every other type is refused (DEC-0057). */
const ACE_TYPES = { AccessAllowed: 'allow', AccessDenied: 'deny', AccessAllowedObject: 'allow-object', AccessDeniedObject: 'deny-object',
  AccessAllowedCallback: 'allow-callback', AccessDeniedCallback: 'deny-callback', AccessAllowedCallbackObject: 'allow-object-callback',
  AccessDeniedCallbackObject: 'deny-object-callback' };

/**
 * The ACL report PowerShell prints, as (owner SID, ACEs `{type, sid, mask}`, current user). The mask arrives signed
 * (GENERIC_READ 0x80000000 is negative in .NET) and is read as the unsigned 32-bit mask; a NULL DACL grants everyone
 * everything and is read as an allow ACE for Everyone (S-1-1-0).
 */
export function parseAclReport(text) {
  const report = JSON.parse(text);
  const aces = report.nullDacl ? [{ type: 'allow', sid: 'S-1-1-0', mask: 0x1f01ff }]
    : [].concat(report.aces ?? []).map((ace) => ({ type: ACE_TYPES[ace.type] ?? String(ace.type), sid: ace.sid, mask: Number.isInteger(ace.mask) ? ace.mask >>> 0 : ace.mask }));
  return { owner: report.owner ?? '', aces, user: report.user };
}

/** (owner SID, the ACEs on the file itself, the current user's SID). */
export function windowsAcl(file) {
  return parseAclReport(windowsHelper('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', ACL_SCRIPT], { FABRIC_ACL_PATH: file }));
}

let userSid = null;
export function windowsUserSid() {
  if (!userSid) {
    const line = windowsHelper('whoami.exe', ['/user', '/fo', 'csv', '/nh']).trim();
    userSid = (line.match(/"(S-1-[0-9-]+)"\s*$/) ?? [])[1];
    if (!userSid) throw new ServiceError('whoami /user printed no SID.');
  }
  return userSid;
}

/**
 * A protected list (inheritance off): this user, SYSTEM, Administrators, full control; a folder hands it down.
 * `/reset` first drops any explicit entry already there (`/inheritance:r` keeps those), so the three are all that remain.
 */
export function windowsProtect(target, { folder }) {
  const grant = folder ? '(OI)(CI)F' : 'F';
  windowsHelper('icacls.exe', [target, '/reset']);
  windowsHelper('icacls.exe', [target, '/inheritance:r', '/grant:r', ...[windowsUserSid(), ...WINDOWS_TRUSTED].map((sid) => `*${sid}:${grant}`)]);
}

function windowsTokenProblem(file, info) {
  const profile = fs.realpathSync.native(process.env.USERPROFILE || os.homedir()).toLowerCase();
  const real = fs.realpathSync.native(file).toLowerCase();
  const inside = path.win32.relative(profile, real);
  const { owner, aces, user } = windowsAcl(file);
  return tokenFileProblem(file, {
    isRegularFile: info.isFile(), isReparsePoint: info.isSymbolicLink(),
    realPathInProfile: Boolean(inside) && !inside.startsWith('..') && !path.win32.isAbsolute(inside), ownerSid: owner, aces,
  }, user);
}

export function tokenMatches(presented, token, scheme = 'Bearer') {
  if (!presented) return false;
  let value = presented;
  if (scheme === 'Bearer') {
    if (!presented.startsWith('Bearer ')) return false;
    value = presented.slice(7);
  }
  const a = Buffer.from(value.trim());
  const b = Buffer.from(token);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

export function checkRequest(port, host, origin, secFetchSite) {
  const hosts = new Set([`127.0.0.1:${port}`, `localhost:${port}`, `[::1]:${port}`]);
  if (!hosts.has(host)) return `Host ${host} is not this service.`;
  if (origin !== undefined && origin !== null && ![...hosts].some((h) => origin === `http://${h}`)) return `Origin ${origin} is not this service.`;
  if (secFetchSite === 'cross-site') return 'Cross-site requests are refused.';
  return null;
}

// --- descriptor (installer only) -----------------------------------------------------

export const descriptorPath = (id, instance = 'default', dir = servicesDir()) => path.join(dir, `${id}.${instance}.json`);

export function readDescriptors(dir = servicesDir()) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((n) => n.endsWith('.json')).sort().flatMap((n) => {
    try {
      return [[path.join(dir, n), JSON.parse(fs.readFileSync(path.join(dir, n), 'utf8'))]];
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
  if (d.protocol !== PROTOCOL) problems.push(`protocol must be ${PROTOCOL}`);
  if (!ID.test(d.id)) problems.push(`id must match ${ID}`);
  if (!INSTANCE.test(d.instance)) problems.push(`instance must match ${INSTANCE}`);
  if (remote) problems.push(...remoteOriginProblems(d.origin));
  else if (d.origin !== undefined && !ORIGIN.test(d.origin)) problems.push('origin must be http://127.0.0.1:<port>');
  if (!d.auth?.tokenFile) problems.push('auth.tokenFile is required');
  else if (!LOCAL_PATH.test(String(d.auth.tokenFile))) problems.push('auth.tokenFile must be a local path, never a network share');
  for (const value of [...(d.paths?.data !== undefined ? [d.paths.data] : []), ...(d.paths?.logs ?? [])]) {
    if (!LOCAL_PATH.test(String(value))) problems.push(`paths must be local paths, never a network share: ${JSON.stringify(value)}`);
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
    if (!['doctor', 'update'].includes(name)) problems.push(`unknown command ${name}`);
    else if (!Array.isArray(argv) || !argv.length || !argv.every((a) => typeof a === 'string')) problems.push(`command ${name} must be an argument array`);
    else if (!LOCAL_PATH.test(argv[0])) problems.push(`command ${name} must start with an absolute or ~/ executable`);
  }
  return problems;
}

/** DEC-0019: `local` unless the descriptor says `remote`. */
// --- DEC-0061 and DEC-0069: who installed it, how its model calls sign in, offered to others, an app's own descriptor ---

/** The organization edition's data classes, least sensitive first (DEC-0061, DEC-0053). */
export const PEER_DATA_CLASSES = Object.freeze(['public', 'internal', 'confidential', 'restricted']);
/** The kind of a runner's sign-in, never a credential's value (DEC-0061). */
export const CREDENTIAL_KINDS = Object.freeze(['subscription', 'key', 'platform-metered', 'none']);
/** A subscription runs only in its vendor's runner (DEC-0046): runner kind → login. */
export const SUBSCRIPTION_RUNNERS = Object.freeze({ 'claude-code': 'claude', 'kimi-code': 'kimi', codex: 'chatgpt' });
const PEER_ENDPOINT = /^https:\/\/((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63})(:([1-9][0-9]{0,3}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5]))?(\/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*)?$/;
const RESIDENCY = /^(A[B-Z]|[B-PR-WY][A-Z]|Q[A-L]|Z[A-Y])$/;
const RUNNER_KIND_NAME = /^[a-z][a-z0-9-]{1,62}$/;
const isObj = (v) => typeof v === 'object' && v !== null && !Array.isArray(v);
const text = (v, low = 1, high = 200) => typeof v === 'string' && v.length >= low && v.length <= high;
/** A JSON Pointer token (RFC 6901 §4). */
const pointer = (name) => String(name).replace(/~/g, '~0').replace(/\//g, '~1');

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
    if (!text(by)) problems.push('installedBy is the installer and its version, 1 to 200 characters');
    places.push(['/installedBy', by]);
  } else if (isObj(by)) {
    for (const k of Object.keys(by)) if (!['by', 'role', 'tool'].includes(k)) problems.push(`installedBy has no member ${k}`);
    if (!['person', 'node', 'organization'].includes(by.by)) problems.push('installedBy.by is person, node or organization');
    if (by.by === 'person' && !['operator', 'administrator'].includes(by.role)) problems.push('installedBy.role is operator or administrator for a person');
    if (by.by !== 'person' && 'role' in by) problems.push('installedBy.role belongs to a person only');
    if (!text(by.tool)) problems.push('installedBy.tool is the installer and its version, 1 to 200 characters');
    for (const [k, v] of Object.entries(by)) places.push([`/installedBy/${pointer(k)}`, v]);
  } else problems.push("installedBy is the installer's name or {by, role?, tool}");
  if (life.manager === 'person' && !(isObj(by) && by.by === 'person')) problems.push("an app's descriptor names who installed it as a person: installedBy {by: person, role, tool} (DEC-0069)");
  let runner = d.runner;
  if ('runner' in d) {
    if (!isObj(runner)) { problems.push('runner is {kind?, credentialKind}'); runner = {}; }
    for (const k of Object.keys(runner)) if (!['kind', 'credentialKind'].includes(k)) problems.push(`runner has no member ${k}`);
    if (!CREDENTIAL_KINDS.includes(runner.credentialKind)) problems.push('runner.credentialKind is subscription, key, platform-metered or none');
    if ('kind' in runner && !(typeof runner.kind === 'string' && RUNNER_KIND_NAME.test(runner.kind))) problems.push("runner.kind is a runner kind's name");
    if (runner.credentialKind === 'subscription' && !Object.hasOwn(SUBSCRIPTION_RUNNERS, runner.kind)) problems.push("a subscription runs only in its vendor's runner: runner.kind claude-code, kimi-code or codex");
    for (const [k, v] of Object.entries(runner)) places.push([`/runner/${pointer(k)}`, v]);
  }
  if ('peer' in d) {
    let peer = d.peer;
    if (!isObj(peer)) { problems.push('peer is {endpoint, custody, residency, maxDataClass}'); peer = {}; }
    for (const k of Object.keys(peer)) if (!['endpoint', 'custody', 'residency', 'maxDataClass'].includes(k)) problems.push(`peer has no member ${k}`);
    const m = typeof peer.endpoint === 'string' && peer.endpoint.length <= 2048 ? PEER_ENDPOINT.exec(peer.endpoint) : null;
    if (!m) problems.push('peer.endpoint is https://<dns-name>[:<port>][/<path>], no query, fragment, userinfo or IP literal');
    else if (RESERVED_HOST.test(m[1])) problems.push(`FAC-SEM-085: a service offered to others cannot be reached at the reserved name ${m[1]}`);
    if (!['organization-managed', 'personal'].includes(peer.custody)) problems.push('peer.custody is organization-managed or personal');
    const r = peer.residency;
    if (!Array.isArray(r) || r.length < 1 || r.length > 32 || new Set(r.map((x) => JSON.stringify(x))).size !== r.length || !r.every((x) => typeof x === 'string' && RESIDENCY.test(x))) {
      problems.push('peer.residency is 1 to 32 distinct ISO 3166-1 alpha-2 codes in upper case, EU admitted, no user-assigned code');
    }
    if (!PEER_DATA_CLASSES.includes(peer.maxDataClass)) problems.push('peer.maxDataClass is public, internal, confidential or restricted');
    if (!('runner' in d)) problems.push('a service offered to others declares runner (DEC-0061)');
    else if (isObj(runner) && runner.credentialKind === 'subscription') problems.push('a service offered to others never runs on a subscription (DEC-0061)');
  }
  for (const [place, value] of places) {
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
  try { found = JSON.parse(fs.readFileSync(descriptorPath(...FABRIC_SERVICE, dir), 'utf8')); } catch { return 'absent'; }
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

export function writeDescriptor(d, dir = servicesDir()) {
  const problems = validateDescriptor(d);
  if (problems.length) throw new ServiceError(`Descriptor is invalid: ${problems.join('; ')}.`);
  const me = `${d.id}.${d.instance}`;
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
  ensurePrivateDir(dir);
  const target = descriptorPath(d.id, d.instance, dir);
  atomicWrite(target, `${JSON.stringify(d, null, 2)}\n`, 0o600);
  return target;
}

export function removeDescriptor(id, instance = 'default', dir = servicesDir()) {
  try { fs.unlinkSync(descriptorPath(id, instance, dir)); return true; } catch (e) { if (e.code === 'ENOENT') return false; throw e; }
}

// --- well-known and events ------------------------------------------------------------

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
export const ROUTES = Object.freeze(['subscription', 'key']);
/** A usage row's route (DEC-0046, DEC-0061): beside a configuration's two, the hosting platform's own metered models. */
export const USAGE_ROUTES = Object.freeze([...ROUTES, 'platform-metered']);

/** DEC-0046: the well-known `configuration` — {slots, resolved} as service-well-known.schema.json types it. */
export function configurationProblems(doc) {
  if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) return ['configuration is an object'];
  const problems = Object.keys(doc).filter((k) => k !== 'slots' && k !== 'resolved').map((k) => `configuration has no member ${k}`);
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
    if (!Object.hasOwn(checks, k)) problems.push(`resolved has no member ${k}`);
    else if (!checks[k](v)) problems.push(`resolved.${k} is not valid`);
  }
  return problems;
}

export function buildWellKnown({ id, instance, name, version, build, startedAt, status, degraded = [], surfaces, summary, updateAvailable = null, pid = process.pid, extensions, configuration, protocols }) {
  if (!STATUSES.includes(status)) throw new ServiceError(`status must be one of ${STATUSES.join(', ')}.`);
  if (!surfaces?.events) throw new ServiceError('surfaces.events is required.');
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
  if (extensions && Object.keys(extensions).length) {
    if (DASHBOARD_EXTENSION_KEY in extensions) {
      const problems = dashboardExtensionProblems(extensions[DASHBOARD_EXTENSION_KEY]);
      if (problems.length) throw new ServiceError(`Dashboard declaration: ${problems.join('; ')}.`);
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

// An event about traced work carries traceId and spanId together (fabric-interop/0.1 C3.4 c);
// traceIds(traceparent) in fabric-interop.mjs gives both.
// --- DEC-0067: protocol revisions; DEC-0070: an event's machine-readable data ---------------------------------------

/** Each contract protocol's published revisions, oldest first (the contract's `PROTOCOL_REVISIONS`); a test holds it equal to the contract's. */
export const PROTOCOL_REVISIONS = new Map(Object.entries({
  'access-log': ['1'], approval: ['1'], 'activity-summary': ['1'], 'coding-agents': ['1'], 'enroll-token': ['1'], entitlement: ['1'], 'entitlement-key-set': ['1'], 'estate-record': ['1'], 'execution-packet': ['1'],
  'fabric-activity': ['0.1'], 'fabric-dashboard': ['0.1'], 'fabric-delegation': ['0.1'], 'fabric-device': ['0.1'],
  'fabric-interop': ['0.1', '0.2'], 'fabric-local-channel': ['0.1'], 'fabric-local-runner': ['0.1'], 'fabric-operator-channel': ['0.1'],
  'fabric-package': ['1'], 'fabric-project-comms': ['0.1'], 'fabric-proposal': ['1'], 'fabric-provider': ['0.1'], 'fabric-relay': ['0.1'],
  'fabric-secret-envelope': ['1'], 'fabric-service': ['0.1'], 'fabric-settings-backup': ['1'], heartbeat: ['1'], 'learning-note': ['1'],
  memory: ['0.1'], 'pairing-message': ['1'], pipeline: ['0.1'], 'revocation-delta': ['1'], 'session-handoff': ['1'],
  'share-registration': ['1'], 'share-registration-receipt': ['1'], 'support-quality-daily': ['1'], 'window-lease': ['1'],
}));
export const MAX_PROTOCOLS = 64;
const REVISION = /^([a-z][a-z0-9.-]{0,63})\/([0-9]{1,4}(?:\.[0-9]{1,4}){0,2})$/;

/** `<name>/<revision>` split, or undefined. */
export function parseRevision(value) {
  const m = typeof value === 'string' ? REVISION.exec(value) : null;
  return m ? { name: m[1], revision: m[2] } : undefined;
}

/** The revisions a receiver implementing `name` up to `newest` accepts: N and, when the register has one, N−1. */
export function acceptedRevisions(name, newest) {
  const known = PROTOCOL_REVISIONS.get(name);
  if (!known?.length) return [];
  const top = newest === undefined ? known.length - 1 : known.indexOf(newest);
  if (top < 0) return [];
  return known.slice(Math.max(0, top - 1), top + 1).reverse().map((r) => `${name}/${r}`);
}

/**
 * A receiver's answer to a document naming `received` (DEC-0067, the contract's `negotiateRevision`): `{ok: true}`, the
 * `schema-unsupported` refusal naming what was received (at most 80 characters) and the accepted revisions of that
 * protocol (all of them when it names none the receiver reads), or `{fault: 'no-accepted-revisions'}`.
 */
export function negotiateRevision(received, accepted) {
  const usable = [...new Set((Array.isArray(accepted) ? accepted : []).filter((e) => parseRevision(e) !== undefined))].slice(0, MAX_PROTOCOLS);
  if (!usable.length) return { fault: 'no-accepted-revisions' };
  if (typeof received === 'string' && usable.includes(received)) return { ok: true };
  const parsed = parseRevision(received);
  const same = parsed ? usable.filter((e) => parseRevision(e)?.name === parsed.name) : [];
  return { error: { code: 'schema-unsupported', message: 'this receiver does not read that protocol revision',
    data: { protocol: typeof received === 'string' ? Array.from(received).slice(0, 80).join('') : '', accepted: same.length ? same : usable } } };
}

/** FAC-SEM-099 (DEC-0067): 1 to 64 entries, each once; at most N and N−1 of one protocol, consecutive in the register. */
export function protocolsFindings(protocols, prefix = '/protocols') {
  const flag = (instancePath, message) => ({ code: 'FAC-SEM-099', instancePath, message });
  if (!Array.isArray(protocols)) return [flag(prefix, 'protocols is a list of protocol revisions')];
  if (protocols.length === 0 || protocols.length > MAX_PROTOCOLS) return [flag(prefix, `protocols lists 1 to ${MAX_PROTOCOLS} revisions`)];
  const findings = [];
  const byName = new Map();
  const seen = new Set();
  protocols.forEach((entry, i) => {
    const at = `${prefix}/${i}`;
    const parsed = parseRevision(entry);
    if (!parsed) { findings.push(flag(at, 'a protocol revision is <name>/<revision>, such as fabric-service/0.1')); return; }
    if (seen.has(entry)) { findings.push(flag(at, 'each protocol revision once')); return; }
    seen.add(entry);
    const known = PROTOCOL_REVISIONS.get(parsed.name);
    if (known && !known.includes(parsed.revision)) { findings.push(flag(at, `${parsed.name} has no published revision ${parsed.revision}`)); return; }
    const indices = byName.get(parsed.name) ?? [];
    indices.push(known ? known.indexOf(parsed.revision) : -1);
    byName.set(parsed.name, indices);
    if (indices.length > 2) findings.push(flag(at, 'at most 2 revisions of one protocol: N and N−1'));
    else if (known && indices.length === 2 && Math.abs(indices[0] - indices[1]) !== 1) findings.push(flag(at, 'two revisions of one protocol are N and N−1, consecutive in the register'));
  });
  return findings;
}

const SCHEMA_URI = /^[A-Za-z][A-Za-z0-9+.-]*:\S+$/;
const scalar = (v) => v === null || typeof v === 'boolean' || (typeof v === 'number' && Number.isFinite(v)) || (typeof v === 'string' && Array.from(v).length <= 500);
const isPlain = (v) => typeof v === 'object' && v !== null && !Array.isArray(v);
const pointerToken = (name) => String(name).replace(/~/g, '~0').replace(/\//g, '~1');

/** FAC-SEM-101 over an events page (the contract's `feedDataFindings`): no credential's name or shape in an event's data. */
export function feedDataFindings(page) {
  const findings = [];
  const check = (named, member, at) => {
    if (typeof member !== 'string') return;
    if (named) findings.push({ code: 'FAC-SEM-101', instancePath: at, message: "an event's data puts no string under a credential's name" });
    else if (secretValue(member) || secretUrl(member)) findings.push({ code: 'FAC-SEM-101', instancePath: at, message: "an event's data carries no value shaped like a credential" });
  };
  (Array.isArray(page?.events) ? page.events : []).forEach((event, i) => {
    if (!isPlain(event) || !isPlain(event.data) || !isPlain(event.data.value)) return;
    for (const [key, member] of Object.entries(event.data.value)) {
      const at = `/events/${i}/data/value/${pointerToken(key)}`;
      const named = credentialName(key);
      check(named, member, at);
      if (Array.isArray(member)) member.forEach((item, j) => check(named, item, `${at}/${j}`));
      else if (isPlain(member)) for (const [inner, leaf] of Object.entries(member)) check(named || credentialName(inner), leaf, `${at}/${pointerToken(inner)}`);
    }
  });
  return findings;
}

/** DEC-0070's `data {schema, value}` as the schema bounds it, then FAC-SEM-101. */
export function feedDataProblems(data) {
  if (!isPlain(data) || Object.keys(data).length !== 2 || !('schema' in data) || !('value' in data)) return ['data is {schema, value}'];
  const problems = [];
  if (!(typeof data.schema === 'string' && SCHEMA_URI.test(data.schema))) problems.push('data.schema is the absolute URI of a payload schema the service publishes');
  const value = data.value;
  if (!isPlain(value) || Object.keys(value).length > 32) return [...problems, 'data.value is an object of at most 32 members'];
  for (const [key, member] of Object.entries(value)) {
    if (scalar(member)) continue;
    if (Array.isArray(member) && member.length <= 32 && member.every(scalar)) continue;
    if (isPlain(member) && Object.keys(member).length <= 32 && Object.values(member).every(scalar)) continue;
    problems.push(`data.value.${key} is a scalar (a string of at most 500 characters), a list of at most 32 scalars or an object of at most 32 scalar members`);
  }
  if (problems.length) return problems;
  return feedDataFindings({ events: [{ data }] }).map((f) => `FAC-SEM-101: ${f.instancePath.replace('/events/0', '')} ${f.message}`);
}

/** One activity event. `data` (DEC-0070) adds machine-readable fields, `{schema, value}`, never a secret: refused here, so no feed carries one. */
export function makeEvent(id, at, kind, level, text, { subject, link, notify, traceId, spanId, data } = {}) {
  if (!LEVELS.includes(level)) throw new ServiceError(`level must be one of ${LEVELS.join(', ')}.`);
  if (!KIND.test(kind)) throw new ServiceError(`kind ${kind} must be dotted lowercase.`);
  const sentence = String(text).split(/\s+/).filter(Boolean).join(' ');
  if (!sentence) throw new ServiceError('An event needs a sentence.');
  if (link !== undefined && (!link.startsWith('/') || link.startsWith('//'))) throw new ServiceError('link must be a path on this service.');
  if ((traceId === undefined) !== (spanId === undefined)) throw new ServiceError('An event carries traceId and spanId together, or neither.');
  if (traceId !== undefined && !(TRACE_ID.test(traceId) && SPAN_ID.test(spanId))) throw new ServiceError('traceId is 32 and spanId 16 lowercase hex characters, not all zeros.');
  const event = { id: String(id), at, kind, level, text: sentence.slice(0, 500) };
  if (subject) event.subject = subject;
  if (link) event.link = link;
  if (notify) event.notify = true;
  if (traceId !== undefined) Object.assign(event, { traceId, spanId });
  if (data !== undefined) {
    const problems = feedDataProblems(data);
    if (problems.length) throw new ServiceError(`Event data: ${problems.join('; ')}.`);
    event.data = { schema: data.schema, value: data.value };
  }
  return event;
}

export function parseLimit(raw) {
  if (raw === undefined || raw === null || raw === '') return EVENTS_DEFAULT_LIMIT;
  const n = Number(raw);
  if (!Number.isInteger(n)) throw new ServiceError('limit must be an integer.');
  return Math.max(1, Math.min(EVENTS_MAX_LIMIT, n));
}

// fetch(after, limit) returns events with ids greater than `after`, ascending
// (or the newest `limit`, ascending, when after is null) — a view over the log you already keep.
export async function eventsPage(fetch, after, limit) {
  const events = (await fetch(after ?? null, limit)).slice(0, limit);
  return { events, cursor: events.length ? events.at(-1).id : (after ?? null) };
}

// --- usage report (DEC-0021) -------------------------------------------------------------

export const USAGE_PATH = '/fabric/v1/usage';
export const USAGE_DAYS = 31;
export const COST_BASES = ['provider', 'price-list', 'unknown'];
const PROVIDER = /^[a-z][a-z0-9._-]{0,63}$/;
const COUNTS = ['inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens'];

/**
 * One model call, from the provider's own usage numbers. No prompt, output or caller.
 * `costUsd` null means it cannot be priced: the report counts it as unpriced, never as $0.
 */
/**
 * One model call. `projectId` (a URI, kept in its normal form, DEC-0076) and `taskRunId` (the service's own run id) attribute
 * it to the project the service ran it for (DEC-0065); they never name a caller, session or person.
 */
// tokensMeasured: false marks a call whose token counts are a lower bound or unknown (DEC-0091): the report counts it
// in unmeasuredCalls and its token totals are a lower bound.
export function makeUsageReceipt(provider, model, { inputTokens, outputTokens, cacheReadTokens = 0, cacheWriteTokens = 0, costUsd = null, costBasis, at, route, projectId, taskRunId, tokensMeasured = true } = {}) {
  if (!PROVIDER.test(provider ?? '')) throw new ServiceError('provider must be a lowercase name such as anthropic or openrouter.');
  model = String(model ?? '').trim();
  if (!model || model.length > 128) throw new ServiceError('model must be 1 to 128 characters.');
  const counts = { inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens };
  for (const [name, value] of Object.entries(counts)) if (!Number.isInteger(value) || value < 0) throw new ServiceError(`${name} must be a non-negative integer.`);
  if (costUsd !== null && (typeof costUsd !== 'number' || !Number.isFinite(costUsd) || costUsd < 0)) throw new ServiceError('costUsd must be a non-negative number or null.');
  const basis = costBasis ?? (costUsd === null ? 'unknown' : 'provider');
  if (!COST_BASES.includes(basis) || (costUsd === null) !== (basis === 'unknown')) throw new ServiceError('costBasis is provider or price-list with a cost, unknown without one.');
  if (route !== undefined && !USAGE_ROUTES.includes(route)) throw new ServiceError('route is subscription, key or platform-metered (DEC-0046, DEC-0061).');
  if (tokensMeasured !== true && tokensMeasured !== false) throw new ServiceError('tokensMeasured is true or false.');
  if (taskRunId !== undefined && projectId === undefined) throw new ServiceError('a task run belongs to a project: give projectId with taskRunId.');
  if (projectId !== undefined && !(typeof projectId === 'string' && /^[A-Za-z][A-Za-z0-9+.-]*:\S+$/.test(projectId))) throw new ServiceError('projectId is the URI of the project the service ran the call for.');
  if (taskRunId !== undefined && !(typeof taskRunId === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(taskRunId))) throw new ServiceError("taskRunId is the service's own run id: ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$.");
  return { at: at ?? nowIso(), provider, model, ...counts, costUsd, costBasis: basis, ...(tokensMeasured ? {} : { tokensMeasured: false }), ...(route === undefined ? {} : { route }),
    ...(projectId === undefined ? {} : { projectId: normalIdentifier(projectId) }), ...(taskRunId === undefined ? {} : { taskRunId }) };
}

/** DEC-0065's `byProject`: the window's calls by project (normal form, DEC-0076), each task run once within it. */
function byProject(receipts, first, last) {
  const projects = new Map();
  const add = (row, r) => { row.calls += 1; if (r.costUsd === null || r.costUsd === undefined) row.unpricedCalls += 1; else row.cost += r.costUsd; };
  for (const r of receipts) {
    const date = String(r.at ?? '').slice(0, 10);
    if (date < first || date > last || !r.projectId) continue;
    if (!projects.has(r.projectId)) projects.set(r.projectId, { projectId: r.projectId, calls: 0, unpricedCalls: 0, cost: 0, runs: new Map() });
    const row = projects.get(r.projectId);
    add(row, r);
    if (r.taskRunId) {
      if (!row.runs.has(r.taskRunId)) row.runs.set(r.taskRunId, { taskRunId: r.taskRunId, calls: 0, unpricedCalls: 0, cost: 0 });
      add(row.runs.get(r.taskRunId), r);
    }
  }
  const close = ({ cost, ...rest }) => ({ ...rest, costUsd: rest.calls && rest.unpricedCalls === rest.calls ? null : Math.round(cost * 1e6) / 1e6 });
  return [...projects.keys()].sort().map((key) => {
    const { runs, ...row } = projects.get(key);
    const taskRuns = [...runs.keys()].sort().map((id) => close(runs.get(id)));
    return { ...close(row), ...(taskRuns.length ? { taskRuns } : {}) };
  });
}

const utcDate = (ms) => new Date(ms).toISOString().slice(0, 10);
const emptyRow = (extra = {}) => ({ ...extra, calls: 0, unpricedCalls: 0, inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0, cost: 0 });
function closeRow(row) {
  const { cost, ...rest } = row;
  return { ...rest, costUsd: rest.calls && rest.unpricedCalls === rest.calls ? null : Math.round(cost * 1e6) / 1e6 };
}

/**
 * The service-usage.schema.json answer: the last 31 UTC days, oldest first, per provider and
 * model; days without calls are omitted. A row whose calls are all unpriced costs null; totals
 * are the sums of the model rows (FAC-SEM-025).
 */
// --- FAC-SEM-025 whole (DEC-0021, DEC-0065, CT-40, DEC-0076): the contract's `usageRules` --------------------------------

const usageCount = (v) => (Number.isSafeInteger(v) && v >= 0 ? v : 0);
const usageCost = (v) => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : 0);
const exceeds = (a, b) => a - b > 0.000001 + 1e-9 * Math.max(Math.abs(a), Math.abs(b));
const usd = (v) => String(Math.round(v * 1e6) / 1e6);
const usageList = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === 'object' && x !== null && !Array.isArray(x)) : []);
const RFC3339_TIME = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$/;
function strictTime(value) {
  const m = typeof value === 'string' ? RFC3339_TIME.exec(value) : null;
  if (!m) return NaN;
  const [y, mo, d, h, mi, s] = m.slice(1, 7).map(Number);
  const date = new Date(0);
  date.setUTCFullYear(y, mo - 1, d);
  if (date.getUTCMonth() !== mo - 1 || date.getUTCDate() !== d || h > 23 || mi > 59 || s > 59) return NaN;
  return Date.parse(value);
}
function utcDateMs(value) {
  const m = typeof value === 'string' ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(value) : null;
  if (!m) return NaN;
  const [y, mo, d] = m.slice(1).map(Number);
  const ms = Date.UTC(y, mo - 1, d);
  const date = new Date(ms);
  return date.getUTCFullYear() === y && date.getUTCMonth() === mo - 1 && date.getUTCDate() === d ? ms : NaN;
}
function pricedRow(row, at) {
  const calls = usageCount(row.calls), unpriced = usageCount(row.unpricedCalls);
  const flag = (p, message) => [{ code: 'FAC-SEM-025', instancePath: p, message }];
  if (unpriced > calls) return flag(`${at}/unpricedCalls`, 'more unpriced calls than calls');
  // DEC-0091: calls whose token count is unknown are some of the calls, never more.
  if (usageCount(row.unmeasuredCalls) > calls) return flag(`${at}/unmeasuredCalls`, 'more calls with unknown tokens than calls');
  if (calls > 0 && unpriced === calls && row.costUsd !== null) return flag(`${at}/costUsd`, 'every call is unpriced, so the cost is unknown (null), not a number');
  if (unpriced < calls && row.costUsd === null) return flag(`${at}/costUsd`, 'priced calls carry a cost; null is only for a row with no priced call');
  return [];
}

/**
 * FAC-SEM-025 over a usage report, in the contract's order (`src/usage-rules.ts`): the arithmetic, the window (every
 * date exists, not after `generatedAt`'s UTC date, at most 30 days before it) and the project attribution (each project
 * once by its normal form, each task run once; calls, priced calls and known costs bounded). Never throws.
 */
/** The contract's `toNumber` (src/findings.ts): `Number()` without its throw on an object such as {"toString": 1}. */
function toNumber(value) {
  try {
    return Number(value);
  } catch {
    return Number.NaN;
  }
}

/** The contract's `show`: `String()`, or the value's JSON where `String()` would throw. */
function show(value) {
  if (typeof value === 'string') return value;
  try {
    return String(value);
  } catch {
    return JSON.stringify(value) ?? typeof value;
  }
}

export function usageFindings(report) {
  const value = typeof report === 'object' && report !== null && !Array.isArray(report) ? report : {};
  const findings = [];
  const flag = (instancePath, message) => findings.push({ code: 'FAC-SEM-025', instancePath, message });
  const days = usageList(value.days);
  let previous = '';
  days.forEach((day, i) => {
    const at = `/days/${i}`;
    const date = show(day.date ?? '');
    if (date <= previous) flag(`${at}/date`, `days must run forward without a repeat (${date} after ${previous})`);
    previous = date;
    findings.push(...pricedRow(day, at));
    const models = usageList(day.byModel);
    models.forEach((m, j) => findings.push(...pricedRow(m, `${at}/byModel/${j}`)));
    if (!models.length) {
      const spent = ['calls', 'inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens'].some((f) => toNumber(day[f] ?? 0) > 0) || toNumber(day.costUsd ?? 0) > 0;
      if (spent) flag(`${at}/byModel`, 'a day with calls, tokens or cost names the models they belong to');
      return;
    }
    for (const field of ['calls', 'unpricedCalls', 'unmeasuredCalls', 'inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens']) {
      const sum = models.reduce((n, m) => n + toNumber(m[field] ?? 0), 0);
      if (toNumber(day[field] ?? 0) !== sum) flag(`${at}/${field}`, `the day's ${field} is not the sum of its models (${show(day[field] ?? 0)} ≠ ${sum})`);
    }
    const known = models.map((m) => (typeof m.costUsd === 'number' ? m.costUsd : null)).filter((x) => x !== null).reduce((n, x) => n + x, 0);
    // The contract's !close(day, known): Infinity or NaN is never close, so it is a finding.
    if (typeof day.costUsd === 'number' && !(Math.abs(day.costUsd - known) <= 0.000001 + 1e-9 * Math.max(Math.abs(day.costUsd), Math.abs(known)))) flag(`${at}/costUsd`, "the day's cost is not the sum of its models' known costs");
  });
  if (days.length) {
    const generated = strictTime(value.generatedAt);
    if (Number.isNaN(generated)) flag('/generatedAt', 'generatedAt is an RFC 3339 date-time with an offset, so the window can be read');
    else {
      const today = Math.floor(generated / 86_400_000) * 86_400_000;
      const oldest = today - 30 * 86_400_000;
      days.forEach((day, i) => {
        const date = utcDateMs(day.date);
        if (Number.isNaN(date)) flag(`/days/${i}/date`, "a day's date exists in its month");
        else if (date > today) flag(`/days/${i}/date`, 'a day is not after the UTC date of generatedAt');
        else if (date < oldest) flag(`/days/${i}/date`, 'a day is within the last 31 UTC days of generatedAt');
      });
    }
  }
  if (Array.isArray(value.byProject)) {
    const seen = new Map();
    let projectCalls = 0, projectCost = 0;
    value.byProject.forEach((project, p) => {
      if (typeof project !== 'object' || project === null || Array.isArray(project)) return;
      const at = `/byProject/${p}`;
      const normal = normalIdentifier(project.projectId);
      if (normal !== undefined) {
        if (seen.has(normal)) flag(`${at}/projectId`, `each project is one row: ${show(project.projectId)} names the project ${seen.get(normal)} already names`);
        else seen.set(normal, show(project.projectId));
      }
      projectCalls += usageCount(project.calls);
      projectCost += usageCost(project.costUsd);
      findings.push(...pricedRow(project, at));
      const runs = new Set();
      let runCalls = 0, runCost = 0, runPriced = 0;
      usageList(project.taskRuns).forEach((run, r) => {
        if (typeof run.taskRunId === 'string') {
          if (runs.has(run.taskRunId)) flag(`${at}/taskRuns/${r}/taskRunId`, 'each task run is one row within its project');
          runs.add(run.taskRunId);
        }
        runCalls += usageCount(run.calls);
        runCost += usageCost(run.costUsd);
        runPriced += Math.max(0, usageCount(run.calls) - usageCount(run.unpricedCalls));
        findings.push(...pricedRow(run, `${at}/taskRuns/${r}`));
      });
      const projectPriced = Math.max(0, usageCount(project.calls) - usageCount(project.unpricedCalls));
      if (runCalls > usageCount(project.calls)) flag(`${at}/taskRuns`, `a project's task runs hold more calls than the project (${runCalls} > ${usageCount(project.calls)})`);
      else if (runPriced > projectPriced) flag(`${at}/taskRuns`, `a project's task runs hold more priced calls than the project (${runPriced} > ${projectPriced})`);
      else if (usageCost(project.costUsd) === project.costUsd && exceeds(runCost, usageCost(project.costUsd))) flag(`${at}/taskRuns`, `a project's task runs cost more than the project (${usd(runCost)} > ${usd(usageCost(project.costUsd))})`);
    });
    const dayCalls = days.reduce((n, d) => n + usageCount(d.calls), 0);
    if (projectCalls > dayCalls) flag('/byProject', `the projects hold more calls than the days (${projectCalls} > ${dayCalls})`);
    const dayCost = days.reduce((n, d) => n + usageCost(d.costUsd), 0);
    if (exceeds(projectCost, dayCost)) flag('/byProject', `the projects cost more than the days (${usd(projectCost)} > ${usd(dayCost)})`);
  }
  return findings;
}

// --- OpenRouter attribution (DEC-0065): the contract's `attributionHeaders`, off by default ------------------------------

export const OPENROUTER_CATEGORIES = Object.freeze(['cli-agent', 'ide-extension', 'cloud-agent', 'programming-app', 'native-app-builder',
  'creative-writing', 'video-gen', 'image-gen', 'audio-gen', 'writing-assistant', 'general-chat', 'personal-agent', 'legal', 'roleplay', 'game']);
const ATTR_PRODUCT = /^[a-z][a-z0-9-]{0,62}$/;
const ATTR_TITLE = /^[\x21-\x7e](?:[\x20-\x7e]{0,98}[\x21-\x7e])?$/;
const ATTRIBUTION_HEADER_NAMES = new Set(['http-referer', 'referer', 'x-openrouter-title', 'x-title', 'x-openrouter-categories']);

/** FAC-SEM-098: a product's setting names a product slug, a printable title and at most two recognized categories. */
export function attributionSettingFindings(value) {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return [{ code: 'FAC-SEM-098', instancePath: '', message: 'an attribution setting is an object' }];
  const findings = [];
  const flag = (instancePath, message) => findings.push({ code: 'FAC-SEM-098', instancePath, message });
  if (typeof value.product !== 'string' || !ATTR_PRODUCT.test(value.product)) flag('/product', 'the product is a lower-case slug, the last segment of its product page');
  if (typeof value.title !== 'string' || !ATTR_TITLE.test(value.title)) flag('/title', "the title is the product's full name: printable ASCII, 1 to 100 characters, no space at either end");
  if (value.categories !== undefined) {
    if (!Array.isArray(value.categories)) flag('/categories', 'categories are a list');
    else {
      if (value.categories.length > 2) flag('/categories', 'at most 2 categories per request');
      const seen = new Set();
      value.categories.forEach((c, i) => {
        if (typeof c !== 'string' || !OPENROUTER_CATEGORIES.includes(c)) flag(`/categories/${i}`, 'a category is one OpenRouter recognizes; it drops others without an error');
        else if (seen.has(c)) flag(`/categories/${i}`, 'each category once');
        else seen.add(c);
      });
    }
  }
  return findings;
}

function isOpenRouter(url) {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && u.hostname === 'openrouter.ai' && u.port === '' && u.username === '' && u.password === '';
  } catch {
    return false;
  }
}

/**
 * The headers a product adds to one request (DEC-0065, the contract's `attributionHeaders`), or none with the reason:
 * `no-setting` (off by default), `invalid-setting`, `not-openrouter`, `forwarded`, `user-set`. Only `HTTP-Referer`,
 * `X-OpenRouter-Title` and `X-OpenRouter-Categories`; it never reads, moves or returns a key.
 */
export function attributionHeaders(setting, given) {
  const request = typeof given === 'object' && given !== null ? given : {};
  if (setting === undefined || setting === null) return { headers: {}, none: 'no-setting' };
  if (attributionSettingFindings(setting).length) return { headers: {}, none: 'invalid-setting' };
  if (typeof request.url !== 'string' || !isOpenRouter(request.url)) return { headers: {}, none: 'not-openrouter' };
  if (request.originated !== true) return { headers: {}, none: 'forwarded' };
  const present = typeof request.headers === 'object' && request.headers !== null ? Object.keys(request.headers).map((n) => n.toLowerCase()) : [];
  if (present.some((n) => ATTRIBUTION_HEADER_NAMES.has(n))) return { headers: {}, none: 'user-set' };
  const headers = { 'HTTP-Referer': `https://passioncode.ai/${setting.product}/`, 'X-OpenRouter-Title': setting.title };
  if (setting.categories?.length) headers['X-OpenRouter-Categories'] = setting.categories.join(',');
  return { headers };
}

/**
 * `budgets` (DEC-0027) lists every spending limit the service applies, enforced or not. A machine limit with a
 * calendar `period` and no `spentUsd` is counted here from the receipts, the way `budget` is, so the two never
 * disagree; a per-order limit (`per_job`, `approval`) gets `spentUsd: null`; every other limit states its own spend.
 * A report whose limits break FAC-SEM-031 is refused (`usageLimitProblems`).
 */
export function usageReport(receipts, { id, instance = 'default', now = Date.now(), budget, budgets } = {}) {
  receipts = Array.from(receipts); // read twice: the days, then a rolling window
  const first = utcDate(now - (USAGE_DAYS - 1) * 86_400_000), last = utcDate(now);
  const days = new Map();
  for (const r of receipts) {
    const date = String(r.at ?? '').slice(0, 10);
    if (date < first || date > last) continue;
    const rows = days.get(date) ?? new Map();
    days.set(date, rows);
    const k = `${r.provider}\u0000${r.model}\u0000${r.route ?? ''}`;
    // DEC-0046: rows of one model on two routes stay apart.
    const row = rows.get(k) ?? emptyRow({ provider: r.provider, model: r.model, ...(r.route ? { route: r.route } : {}), bases: new Set() });
    rows.set(k, row);
    row.calls += 1;
    for (const c of COUNTS) row[c] += Number(r[c] ?? 0);
    if (r.costUsd === null || r.costUsd === undefined) row.unpricedCalls += 1; else row.cost += r.costUsd;
    if (r.tokensMeasured === false) row.unmeasuredCalls = (row.unmeasuredCalls ?? 0) + 1; // absent is 0 (DEC-0091)
    row.bases.add(r.costBasis ?? 'unknown');
  }
  const outDays = [...days.keys()].sort().map((date) => {
    const models = [...days.get(date).values()]
      .map(({ bases, ...row }) => closeRow({ ...row, costBasis: bases.size === 1 ? [...bases][0] : 'mixed' }))
      .sort((a, b) => (`${a.provider}\u0000${a.model}\u0000${a.route ?? ''}` < `${b.provider}\u0000${b.model}\u0000${b.route ?? ''}` ? -1 : 1));
    const day = emptyRow({ date });
    for (const m of models) {
      for (const c of ['calls', 'unpricedCalls', ...COUNTS]) day[c] += m[c];
      if (m.unmeasuredCalls) day.unmeasuredCalls = (day.unmeasuredCalls ?? 0) + m.unmeasuredCalls;
      day.cost += m.costUsd ?? 0;
    }
    return { ...closeRow(day), byModel: models };
  });
  const report = { protocol: PROTOCOL, service: { id, instance }, generatedAt: new Date(now).toISOString().replace(/\.\d{3}Z$/, 'Z'), currency: 'USD', days: outDays };
  const projects = byProject(receipts, first, last);
  if (projects.length) report.byProject = projects;
  if (budget !== undefined) {
    if (!['day', 'month'].includes(budget?.period) || typeof budget.limitUsd !== 'number' || !(budget.limitUsd > 0)) throw new ServiceError('budget is {period: day|month, limitUsd > 0}.');
    report.budget = { period: budget.period, limitUsd: budget.limitUsd, spentUsd: spentIn(outDays, budget.period, last) };
  }
  if (budgets !== undefined) {
    report.budgets = budgets.map((given) => {
      if (!isPlainObject(given)) throw new ServiceError('Each limit in budgets is an object.');
      const limit = { ...given };
      if (!('spentUsd' in limit)) {
        if (PER_ORDER_KINDS.includes(limit.kind)) limit.spentUsd = null;
        else if (limit.scope === 'machine' && ['day', 'month'].includes(limit.period)) limit.spentUsd = spentIn(outDays, limit.period, last);
        else if (limit.scope === 'machine' && isNumber(limit.windowSeconds)) limit.spentUsd = spentSince(receipts, now - limit.windowSeconds * 1000, now);
      }
      return limit;
    });
    const problems = usageLimitProblems(report);
    if (problems.length) throw new ServiceError(`The report's limits are not coherent: ${problems.join('; ')}`);
  }
  return report;
}

/** Spend in a rolling window, from the receipts' own times; null when every call in it is unpriced. */
function spentSince(receipts, start, end) {
  const iso = (ms) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
  const lo = iso(start), hi = iso(end);
  const inside = [...receipts].filter((r) => String(r.at ?? '') > lo && String(r.at ?? '') <= hi);
  if (inside.length && inside.every((r) => r.costUsd === null || r.costUsd === undefined)) return null;
  return Math.round(inside.reduce((n, r) => n + (r.costUsd ?? 0), 0) * 1e6) / 1e6;
}

/** Spend in the current UTC day or month; null when every call in it is unpriced. */
function spentIn(outDays, period, last) {
  const prefix = period === 'day' ? last : last.slice(0, 7);
  const window = outDays.filter((d) => d.date.startsWith(prefix));
  const unknown = window.length > 0 && window.every((d) => d.costUsd === null);
  return unknown ? null : Math.round(window.reduce((n, d) => n + (d.costUsd ?? 0), 0) * 1e6) / 1e6;
}

// --- every spending limit (DEC-0027, FAC-SEM-031) --------------------------------------------

export const LIMIT_SCOPES = Object.freeze(['machine', 'project', 'pool', 'job']);
export const PER_ORDER_KINDS = Object.freeze(['per_job', 'approval']);
const LIMIT_ID = /^[a-z0-9][a-z0-9._:-]{0,63}$/;
const LIMIT_KIND = /^[a-z][a-z0-9_]{0,31}$/;
const LIMIT_FIELDS = ['id', 'scope', 'subject', 'kind', 'period', 'windowSeconds', 'since', 'limitUsd', 'spentUsd', 'enforced', 'tripped'];
const TIMESTAMP = /^([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]+)?([Zz]|[+-]([0-9]{2}):([0-9]{2}))$/;

/** A JSON Schema `date-time` (RFC 3339): a real calendar date and time, `Z` or an offset. */
export function isTimestamp(value) {
  const m = typeof value === 'string' ? value.match(TIMESTAMP) : null;
  if (!m) return false;
  const [year, month, day, hour, minute, second] = m.slice(1, 7).map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  const calendar = date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
  const offset = m[9] === undefined || (Number(m[9]) <= 23 && Number(m[10]) <= 59);
  return calendar && hour <= 23 && minute <= 59 && second <= 60 && offset;
}
const isNumber = (v) => typeof v === 'number' && Number.isFinite(v);
const isPlainObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

/**
 * The `budgets` of a usage report against `service-usage.schema.json` `$defs/limit` and FAC-SEM-031 — the twin of
 * fabric_service.usage_limit_problems. A breach is not a problem, and an unknown kind is never refused.
 */
export function usageLimitProblems(report) {
  const problems = [];
  const limits = report?.budgets;
  if (limits === undefined) return problems;
  if (!Array.isArray(limits) || limits.length > 64) return ['budgets is a list of at most 64 limits'];
  const seen = new Set();
  limits.forEach((limit, i) => {
    const at = `/budgets/${i}`;
    if (!isPlainObject(limit)) { problems.push(`${at} is not an object`); return; }
    for (const key of Object.keys(limit)) if (!LIMIT_FIELDS.includes(key)) problems.push(`${at}/${key} is not a limit field`);
    for (const key of ['id', 'scope', 'kind', 'limitUsd', 'spentUsd', 'enforced']) if (!(key in limit)) problems.push(`${at} is missing ${key}`);
    if ('id' in limit && !(typeof limit.id === 'string' && LIMIT_ID.test(limit.id))) problems.push(`${at}/id must match ${LIMIT_ID.source}`);
    if ('scope' in limit && !LIMIT_SCOPES.includes(limit.scope)) problems.push(`${at}/scope must be one of ${LIMIT_SCOPES.join(', ')}`);
    if ('subject' in limit && !(typeof limit.subject === 'string' && limit.subject.length >= 1 && limit.subject.length <= 128)) problems.push(`${at}/subject is 1 to 128 characters`);
    if ('kind' in limit && !(typeof limit.kind === 'string' && LIMIT_KIND.test(limit.kind))) problems.push(`${at}/kind must match ${LIMIT_KIND.source}`);
    if ('period' in limit && !['day', 'month'].includes(limit.period)) problems.push(`${at}/period is day or month`);
    if ('windowSeconds' in limit && !(Number.isInteger(limit.windowSeconds) && limit.windowSeconds >= 1)) problems.push(`${at}/windowSeconds is a whole number of seconds, at least 1`);
    if ('since' in limit && !isTimestamp(limit.since)) problems.push(`${at}/since is a UTC timestamp`);
    if ('limitUsd' in limit && !(limit.limitUsd === null || (isNumber(limit.limitUsd) && limit.limitUsd > 0))) problems.push(`${at}/limitUsd is a dollar amount above zero, or null`);
    if ('spentUsd' in limit && !(limit.spentUsd === null || (isNumber(limit.spentUsd) && limit.spentUsd >= 0))) problems.push(`${at}/spentUsd is a dollar amount, zero or more, or null`);
    for (const key of ['enforced', 'tripped']) if (key in limit && typeof limit[key] !== 'boolean') problems.push(`${at}/${key} is true or false`);

    const flag = (where, message) => problems.push(`FAC-SEM-031 ${at}/${where}: ${message}`);
    const id = String(limit.id ?? '');
    if (seen.has(id)) flag('id', `limit id ${id} appears twice`);
    seen.add(id);
    const named = limit.scope === 'project' || limit.scope === 'pool';
    if (named && !('subject' in limit)) flag('subject', `a ${limit.scope} limit names its ${limit.scope} in subject`);
    if (!named && 'subject' in limit) flag('subject', `a ${limit.scope} limit has no subject`);
    const windows = ['period', 'windowSeconds', 'since'].filter((f) => f in limit);
    if (windows.length > 1) flag(windows[1], `a limit has one window, not ${windows.join(' and ')}`);
    const kind = String(limit.kind ?? '');
    const seconds = isNumber(limit.windowSeconds) ? limit.windowSeconds : null;
    if (PER_ORDER_KINDS.includes(kind)) {
      if (windows.length) flag(windows[0], `${kind} bounds one order and has no window`);
      if (limit.spentUsd !== null) flag('spentUsd', `${kind} bounds one order, so nothing is spent against it (null)`);
    } else if (kind === 'daily') {
      if (!(limit.period === 'day' || seconds === 86400)) flag('period', 'a daily limit counts the UTC day (period day) or the last 24 hours (windowSeconds 86400)');
    } else if (kind === 'monthly') {
      if (!(limit.period === 'month' || (seconds !== null && seconds >= 28 * 86400 && seconds <= 31 * 86400))) flag('period', 'a monthly limit counts the UTC month (period month) or a rolling 28–31 days (windowSeconds)');
    } else if (kind === 'velocity') {
      if (seconds === null) flag('windowSeconds', 'a velocity limit counts a rolling window (windowSeconds)');
    } else if (kind === 'pool' || kind === 'emergency') {
      if (!windows.length) flag('period', `a ${kind} limit names the window it counts (period, windowSeconds or since)`);
    }
    const known = PER_ORDER_KINDS.includes(kind) || ['daily', 'monthly', 'pool', 'emergency'].includes(kind);
    if (known && 'limitUsd' in limit && limit.limitUsd === null) flag('limitUsd', `a ${kind} limit is a dollar amount; only a relative limit (velocity) may leave it null`);
    if (limit.tripped === true && limit.enforced !== true) flag('tripped', 'a limit that is not enforced cannot have stopped work');
  });
  const budget = report.budget;
  if (isPlainObject(budget) && limits.length) {
    const kind = budget.period === 'day' ? 'daily' : 'monthly';
    const same = (x, y) => (x === null || y === null ? x === y : isNumber(x) && isNumber(y) && Math.abs(x - y) <= 0.000001);
    const twin = limits.some((l) => isPlainObject(l) && l.scope === 'machine' && l.enforced === true && l.kind === kind && l.period === budget.period && same(l.limitUsd, budget.limitUsd) && same(l.spentUsd, budget.spentUsd));
    if (!twin) problems.push(`FAC-SEM-031 /budget: budget repeats one enforced machine ${kind} limit with period ${budget.period} in budgets[], so old and new readers agree`);
  }
  return problems;
}

// --- the feed client (DEC-0025, FAC-SEM-036) -------------------------------------------------

/**
 * The one header a client sends the service token in, as the descriptor's `auth` declares it: `header` defaults
 * to Authorization and `scheme` to Bearer; `none` carries the raw token. Never assume `Authorization: Bearer`.
 */
export function tokenHeader(auth, token) {
  const declared = isPlainObject(auth) ? auth : {};
  const name = typeof declared.header === 'string' ? declared.header : 'Authorization';
  const scheme = typeof declared.scheme === 'string' ? declared.scheme : 'Bearer';
  return { name, value: scheme === 'none' ? token : `Bearer ${token}` };
}

// --- settings backups (DEC-0025, FAC-SEM-035) ------------------------------------------------
// The twins of fabric_service.make_settings_backup and the rest; both kits write byte-identical files.

export const SETTINGS_BACKUP_FORMAT = 'fabric-settings-backup/1';
export const SETTINGS_BACKUP_KEEP = 14;
export const SETTINGS_BACKUP_MAX_AGE_SECONDS = 24 * 60 * 60;
const TABLE = /^[a-z][a-z0-9_]{0,62}$/;
const SECRET_TABLE = /^((.+_)?(account_connections?|account_connection_drafts?|tokens?|secrets?|credentials?|passwords?|login_codes?)|(operator_)?sessions?)$/;
const COLUMN = /^[A-Za-z_][A-Za-z0-9_]{0,62}$/;
const SECRET_COLUMN = /^(?:.+_)?(?:[Tt]oken|[Ss]ecret|[Pp]assword|[Pp]assphrase|[Aa]pi_?[Kk]ey|[Pp]rivate_[Kk]ey|[Cc]ookie|[Ll]ogin_[Cc]ode|[Oo]tp|[Cc]redential)s?$/;
const REASON = /^[a-z][a-z0-9_.-]{0,63}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;
const URI = /^[A-Za-z][A-Za-z0-9+.-]*:\S*$/;
const MAX_CELL_CHARS = 1048576;
const MAX_ROW_VALUES = 512;
const STALE_TEMP_MS = 60 * 60 * 1000;
const BACKUP_NAME = /^settings-[0-9]{8}T[0-9]{12}Z\.json$/;

function byCodePoint(a, b) {
  const x = Array.from(a), y = Array.from(b);
  for (let i = 0; i < Math.min(x.length, y.length); i += 1) {
    const d = x[i].codePointAt(0) - y[i].codePointAt(0);
    if (d !== 0) return d;
  }
  return x.length - y.length;
}

/**
 * The settings canonical form (DEC-0025, DEC-0043): keys sorted by code point at every level, `", "` and `": "`,
 * strings escaped as JSON requires and nothing else, integers in decimal — Python's
 * `json.dumps(value, sort_keys=True, ensure_ascii=False)`. Refuses a fraction, an unsafe integer and non-JSON.
 */
/** CT-25 (DEC-0052): a lone surrogate in a string or a key has no canonical form — Python cannot encode it as UTF-8. */
function settingsString(text) {
  if (/\p{Surrogate}/u.test(text)) throw new ServiceError('a lone surrogate has no canonical form');
  return JSON.stringify(text);
}

export function settingsCanonicalJson(value) {
  if (value === null) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) throw new ServiceError(`${value} has no canonical form: a settings backup stores a fraction as its decimal string`);
    return String(value);
  }
  if (typeof value === 'string') return settingsString(value);
  if (Array.isArray(value)) return `[${value.map(settingsCanonicalJson).join(', ')}]`;
  if (isPlainObject(value) && [Object.prototype, null].includes(Object.getPrototypeOf(value))) {
    return `{${Object.keys(value).sort(byCodePoint).map((key) => `${settingsString(key)}: ${settingsCanonicalJson(value[key])}`).join(', ')}}`;
  }
  throw new ServiceError(`${typeof value} is not a JSON value`);
}

/** The `sha256` a settings backup carries: SHA-256 of the UTF-8 canonical JSON of `tables`. */
export const settingsBackupDigest = (tables) => crypto.createHash('sha256').update(settingsCanonicalJson(tables), 'utf8').digest('hex');

/** Why a reader refuses this settings backup: its shape and FAC-SEM-035. Empty means intact. */
export function settingsBackupProblems(doc) {
  if (!isPlainObject(doc)) return ['a settings backup is a JSON object'];
  const problems = [];
  if (doc.format !== SETTINGS_BACKUP_FORMAT) problems.push(`format must be ${SETTINGS_BACKUP_FORMAT}, not ${JSON.stringify(doc.format ?? null)}: a reader refuses a format it does not know`);
  for (const key of ['format', 'service', 'created_at', 'reason', 'sha256', 'counts', 'tables']) if (!(key in doc)) problems.push(`missing ${key}`);
  for (const key of Object.keys(doc)) if (!['format', 'service', 'created_at', 'reason', 'sha256', 'counts', 'tables', 'extensions'].includes(key)) problems.push(`${key} is not a settings backup field`);
  if ('extensions' in doc) {
    if (!isPlainObject(doc.extensions)) problems.push('extensions is an object');
    else for (const key of Object.keys(doc.extensions)) if (!URI.test(key)) problems.push(`extensions key ${JSON.stringify(key)} is not a URI`);
  }
  if ('service' in doc) {
    const s = doc.service;
    if (!isPlainObject(s) || Object.keys(s).sort().join() !== 'id,instance,schema,version') problems.push('service is {id, instance, version, schema}');
    else {
      if (!ID.test(String(s.id))) problems.push(`service.id must match ${ID.source}`);
      if (!INSTANCE.test(String(s.instance))) problems.push(`service.instance must match ${INSTANCE.source}`);
      if (!(typeof s.version === 'string' && s.version.length <= 64)) problems.push('service.version is a string of at most 64 characters');
      if (!((Number.isInteger(s.schema) && s.schema >= 0) || (typeof s.schema === 'string' && s.schema.length >= 1 && s.schema.length <= 64))) problems.push('service.schema is a whole number or a short string');
    }
  }
  if ('created_at' in doc && !isTimestamp(doc.created_at)) problems.push('created_at is a UTC timestamp');
  if ('reason' in doc && !(typeof doc.reason === 'string' && REASON.test(doc.reason))) problems.push(`reason must match ${REASON.source}`);
  if ('sha256' in doc && !(typeof doc.sha256 === 'string' && SHA256.test(doc.sha256))) problems.push('sha256 is 64 lowercase hex digits');
  const tables = isPlainObject(doc.tables) ? doc.tables : {};
  const counts = isPlainObject(doc.counts) ? doc.counts : {};
  if ('tables' in doc && !isPlainObject(doc.tables)) problems.push('tables is an object');
  if ('counts' in doc && !isPlainObject(doc.counts)) problems.push('counts is an object');
  let canonical = true;
  for (const name of [...Object.keys(tables), ...Object.keys(counts).filter((n) => !Object.hasOwn(tables, n))]) {
    if (LONE_SURROGATE.test(name)) canonical = false;
    if (!TABLE.test(name) || SECRET_TABLE.test(name)) problems.push(`table ${name} is never backed up: it can only hold connections, tokens, secrets, credentials, passwords, login codes or sessions (or its name is not a table name)`);
  }
  for (const [name, count] of Object.entries(counts)) if (!(Number.isInteger(count) && count >= 0)) problems.push(`counts.${name} is a whole number`);
  for (const [name, table] of Object.entries(tables)) {
    if (!isPlainObject(table) || Object.keys(table).sort().join() !== 'columns,rows') { problems.push(`tables.${name} is {columns, rows}`); continue; }
    let columns = table.columns;
    if (!(Array.isArray(columns) && columns.length >= 1 && columns.length <= 512 && new Set(columns.map(String)).size === columns.length)) {
      problems.push(`tables.${name}.columns is 1 to 512 distinct names`);
      if (!Array.isArray(columns)) columns = [];
    }
    for (const column of columns) {
      if (!(typeof column === 'string' && COLUMN.test(column)) || SECRET_COLUMN.test(String(column))) problems.push(`column ${name}.${column} is refused: its name says it holds a credential value (name the secret, never store it: secret_name, token_slot)`);
    }
    if (!Array.isArray(table.rows)) { problems.push(`tables.${name}.rows is a list`); continue; }
    table.rows.forEach((row, i) => {
      const at = `/tables/${name}/rows/${i}`;
      if (!Array.isArray(row)) { problems.push(`${at} is a list of values`); return; }
      if (row.length !== columns.length) problems.push(`FAC-SEM-035 ${at}: row has ${row.length} values for ${columns.length} columns`);
      if (row.length > MAX_ROW_VALUES) problems.push(`${at} holds more than ${MAX_ROW_VALUES} values`);
      row.forEach((cell, j) => {
        if (typeof cell === 'number' && !Number.isSafeInteger(cell)) {
          canonical = false;
          problems.push(`FAC-SEM-035 ${at}/${j}: a fraction or an unsafe integer has no canonical form; store it as a string`);
        } else if (typeof cell === 'string' && cell.length > MAX_CELL_CHARS) {
          problems.push(`${at}/${j} is longer than ${MAX_CELL_CHARS} characters`);
        } else if (typeof cell === 'string' && LONE_SURROGATE.test(cell)) {
          canonical = false;
          problems.push(`FAC-SEM-035 ${at}/${j}: a string with a lone surrogate cannot be encoded as UTF-8`);
        } else if (!(cell === null || ['boolean', 'number', 'string'].includes(typeof cell))) {
          canonical = false;
          problems.push(`${at}/${j} is not a JSON scalar`);
        }
      });
    });
    if (counts[name] !== table.rows.length) problems.push(`FAC-SEM-035 /counts/${name}: counts says ${counts[name] ?? 'nothing'} for ${table.rows.length} rows`);
  }
  for (const name of Object.keys(counts)) if (!Object.hasOwn(tables, name)) problems.push(`FAC-SEM-035 /counts/${name}: counts names ${name}, which the backup does not carry`);
  if (canonical && isPlainObject(doc.tables)) {
    let digest = null;
    try {
      digest = settingsBackupDigest(tables);
    } catch (error) {
      problems.push(`FAC-SEM-035 /tables: the tables have no canonical form (${error.message})`);
    }
    if (digest !== null && doc.sha256 !== digest) problems.push('FAC-SEM-035 /sha256: the checksum does not match the tables: the file is damaged and a reader refuses it');
  }
  return problems;
}

/** Where every service keeps its settings backups — outside its data directory (DEC-0025). */
export function settingsBackupRoot(platform = process.platform) {
  if (platform === 'darwin') return path.join(os.homedir(), 'Library/Application Support/PassionCode');
  if (platform === 'win32') return path.join(process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming'), 'PassionCode');
  return path.join(process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config'), 'PassionCode');
}

export function settingsBackupDir(id, instance = 'default', root = settingsBackupRoot()) {
  if (!ID.test(id)) throw new ServiceError(`Service id ${id} must match ${ID}.`);
  if (!INSTANCE.test(instance)) throw new ServiceError(`instance must match ${INSTANCE}`);
  return path.join(root, 'settings-backups', id, instance);
}

const microStamp = (ms) => `${new Date(ms).toISOString().slice(0, 23)}000Z`;

/** A snapshot of the operator's decisions and bindings (the tables on the service's allow-list). Refuses a file a reader would refuse. */
export function makeSettingsBackup({ id, instance = 'default', version, schema, tables, reason, now = Date.now() }) {
  const doc = {
    format: SETTINGS_BACKUP_FORMAT, service: { id, instance, version, schema }, created_at: microStamp(now), reason, sha256: '',
    counts: Object.fromEntries(Object.entries(tables).map(([name, table]) => [name, (table?.rows ?? []).length])), tables,
  };
  try {
    doc.sha256 = settingsBackupDigest(tables);
  } catch (error) {
    throw new ServiceError(`This snapshot has no canonical form: ${error.message}`);
  }
  const problems = settingsBackupProblems(doc);
  if (problems.length) throw new ServiceError(`This snapshot would be refused: ${problems.join('; ')}`);
  return doc;
}

const backupName = (doc) => `settings-${doc.created_at.replace(/[-:]/g, '').replace(/\.(\d+)Z$/, (_, f) => `${(f + '000000').slice(0, 6)}Z`)}.json`;

/** The snapshot files, newest first. */
export function settingsBackups(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((n) => BACKUP_NAME.test(n)).sort().reverse().map((n) => path.join(dir, n));
}

/** The first number written with a fraction or an exponent outside a string (`1.0`, `1e2`); JSON.parse would read
 *  `1.0` as the integer 1, where the Python reader — and the canonical form — sees a fraction. */
function fractionLexeme(text) {
  let inString = false;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (inString) {
      if (c === '\\') i += 1;
      else if (c === '"') inString = false;
    } else if (c === '"') {
      inString = true;
    } else if (c === '-' || (c >= '0' && c <= '9')) {
      const lexeme = text.slice(i).match(/^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?/)[0];
      if (/[.eE]/.test(lexeme)) return lexeme;
      i += lexeme.length - 1;
    }
  }
  return null;
}

/** A snapshot a reader may trust, or ServiceError naming why it is refused (FAC-SEM-035). */
export function readSettingsBackup(file) {
  let doc;
  try {
    const text = new TextDecoder('utf-8', { fatal: true }).decode(fs.readFileSync(file));
    const fraction = fractionLexeme(text);
    if (fraction) throw new Error(`${fraction} is not an integer: a fraction is stored as its decimal string`);
    doc = JSON.parse(text);
  } catch (error) {
    throw new ServiceError(`Settings backup ${file} cannot be read: ${error.message}`);
  }
  const problems = settingsBackupProblems(doc);
  if (problems.length) throw new ServiceError(`Settings backup ${file} is refused: ${problems.join('; ')}`);
  return doc;
}

/**
 * Write a snapshot: atomically, 0600 in a 0700 directory, named by its time. A temporary file an interrupted write
 * left is removed first; a snapshot whose checksum equals the newest file's is not written again (null). After a
 * write, all but the `keep` newest are removed (at least 14).
 */
export function writeSettingsBackup(doc, dir, { keep = SETTINGS_BACKUP_KEEP } = {}) {
  const problems = settingsBackupProblems(doc);
  if (problems.length) throw new ServiceError(`This snapshot would be refused: ${problems.join('; ')}`);
  ensurePrivateDir(dir);
  // Only a temporary file an interrupted write left: one a concurrent writer is still filling is younger.
  for (const left of fs.readdirSync(dir)) {
    const at = path.join(dir, left);
    try {
      if (left.startsWith('.settings-') && fs.statSync(at).mtimeMs < Date.now() - STALE_TEMP_MS) fs.rmSync(at, { force: true });
    } catch { /* gone meanwhile */ }
  }
  const existing = settingsBackups(dir);
  if (existing.length) {
    try {
      if (readSettingsBackup(existing[0]).sha256 === doc.sha256) return null;
    } catch { /* a damaged newest file is no reason to skip a good snapshot */ }
  }
  const file = path.join(dir, backupName(doc));
  atomicWrite(file, `${JSON.stringify(doc, null, 2)}\n`, 0o600);
  // The newest by name, but never the one just written: a clock that stepped back must not delete it.
  for (const old of settingsBackups(dir).filter((f) => f !== file).slice(Math.max(keep, SETTINGS_BACKUP_KEEP) - 1)) fs.rmSync(old, { force: true });
  return file;
}

/** True when there is no snapshot or the newest is older than 24 hours. */
export function backupDue(dir, now = Date.now()) {
  const newest = settingsBackups(dir)[0];
  if (!newest) return true;
  const m = path.basename(newest).match(/^settings-(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(\d{3})\d{3}Z\.json$/);
  // A name no calendar has: take a fresh snapshot rather than trust it (Date.UTC would roll it over).
  if (!isTimestamp(`${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}Z`)) return true;
  const at = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6], +m[7]);
  return (now - at) / 1000 > SETTINGS_BACKUP_MAX_AGE_SECONDS;
}

/** The source of an automatic restore: the newest intact snapshot with content; damaged ones are returned with the reason. */
export function newestIntactBackup(dir) {
  const skipped = [];
  for (const file of settingsBackups(dir)) {
    let doc;
    try {
      doc = readSettingsBackup(file);
    } catch (error) {
      skipped.push({ file, reason: error.message });
      continue;
    }
    if (Object.values(doc.counts).some((n) => n > 0)) return { file, doc, skipped };
  }
  return { file: null, doc: null, skipped };
}

/**
 * What restoring `doc` would do — it adds and never overwrites (DEC-0025). `current[table]` is `{columns, key,
 * required, existing}` (existing primary keys as arrays). The twin of fabric_service.restore_plan.
 */
export function restorePlan(doc, current) {
  const problems = settingsBackupProblems(doc);
  if (problems.length) throw new ServiceError(`A damaged snapshot is never restored: ${problems.join('; ')}`);
  const plan = { source: { created_at: doc.created_at, sha256: doc.sha256 }, tables: {}, unknownTables: [] };
  for (const [name, table] of Object.entries(doc.tables)) {
    const now = current[name];
    if (!now) { plan.unknownTables.push(name); continue; }
    const columns = now.columns ?? [], key = now.key ?? [], required = now.required ?? [];
    const existing = new Set((now.existing ?? []).map((k) => JSON.stringify([...k])));
    const shared = table.columns.filter((c) => columns.includes(c));
    const missing = required.filter((c) => !table.columns.includes(c));
    const entry = {
      insert: [], present: 0, droppedColumns: table.columns.filter((c) => !columns.includes(c)),
      defaultedColumns: columns.filter((c) => !table.columns.includes(c)), missingRequired: missing, refused: [],
    };
    const planned = new Set();
    for (const row of table.rows) {
      const values = Object.fromEntries(table.columns.map((c, i) => [c, row[i]]));
      const ident = key.map((c) => values[c] ?? null);
      if (key.some((c) => !table.columns.includes(c))) entry.refused.push({ key: ident, reason: 'the primary key is not in the snapshot' });
      else if (planned.has(JSON.stringify(ident))) entry.refused.push({ key: ident, reason: 'the snapshot holds this key twice' });
      else if (existing.has(JSON.stringify(ident))) entry.present += 1;
      else if (missing.length) entry.refused.push({ key: ident, reason: `required column ${missing.join(', ')} is not in the snapshot` });
      else {
        planned.add(JSON.stringify(ident));
        entry.insert.push(Object.fromEntries(shared.map((c) => [c, values[c]])));
      }
    }
    plan.tables[name] = entry;
  }
  return plan;
}

/** Usage receipts for services that keep none yet: append-only JSON lines, 0600, pruned to the window (LC-12).
 *  One writer process (the service holds its instance lock); every method is synchronous, so calls never interleave. */
export class JsonlUsageLedger {
  constructor(file) { this.file = file; }

  record(receipt) {
    ensurePrivateDir(path.dirname(this.file));
    const fd = fs.openSync(this.file, 'a+', 0o600);
    try {
      const { size } = fs.fstatSync(fd);
      const last = Buffer.alloc(1);
      // A killed writer left a torn line: never glue a receipt to it.
      const lead = size && fs.readSync(fd, last, 0, 1, size - 1) === 1 && last[0] !== 0x0a ? '\n' : '';
      fs.writeSync(fd, lead + JSON.stringify(receipt) + '\n');
    } finally {
      fs.closeSync(fd);
    }
  }

  receipts() {
    if (!fs.existsSync(this.file)) return [];
    const out = [];
    for (const line of fs.readFileSync(this.file, 'utf8').split('\n')) {
      if (!line) continue;
      try { out.push(JSON.parse(line)); } catch { /* a torn last line from a killed writer is skipped */ }
    }
    return out;
  }

  prune(now = Date.now()) {
    const first = utcDate(now - (USAGE_DAYS - 1) * 86_400_000);
    const all = this.receipts();
    const kept = all.filter((r) => String(r.at ?? '').slice(0, 10) >= first);
    if (kept.length !== all.length) atomicWrite(this.file, kept.map((r) => JSON.stringify(r) + '\n').join(''));
    return all.length - kept.length;
  }

  report(options) { return usageReport(this.receipts(), options); }
}

// --- logs (LC-12) ------------------------------------------------------------------------

/**
 * One structured log: JSON lines rotated by size (5 x 5 MB by default), files 0600 in a 0700
 * directory. `service.jsonl` -> `.1` ... `.<backups>`; the oldest falls off. Never pass a token,
 * a cookie, a login code or a request body that may carry one.
 */
export class RotatingLog {
  constructor(file, { maxBytes = LOG_MAX_BYTES, backups = LOG_BACKUPS } = {}) {
    if (maxBytes < 256 || backups < 1) throw new ServiceError('A rotating log needs maxBytes >= 256 and at least one backup.');
    this.file = file;
    this.maxBytes = maxBytes;
    this.backups = backups;
  }

  line(record) {
    let data = Buffer.from(`${JSON.stringify(record)}\n`);
    if (data.length <= this.maxBytes) return data;
    const cut = { ...record, truncated: true };
    let message = String(record.message ?? '');
    while (message) {
      message = message.slice(0, Math.floor(message.length / 2));
      cut.message = message;
      data = Buffer.from(`${JSON.stringify(cut)}\n`);
      if (data.length <= this.maxBytes) return data;
    }
    return Buffer.from(`${JSON.stringify({ at: record.at, level: record.level, message: '', truncated: true })}\n`);
  }

  write(level, message, fields = {}) {
    const data = this.line({ at: nowIso(), level: String(level), message: String(message), ...fields });
    ensurePrivateDir(path.dirname(this.file));
    let size = 0;
    try { size = fs.statSync(this.file).size; } catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (size && size + data.length > this.maxBytes) this.rotate();
    const fd = fs.openSync(this.file, 'a', 0o600);
    try { fs.writeSync(fd, data); } finally { fs.closeSync(fd); }
  }

  rotate() {
    for (let i = this.backups - 1; i > 0; i -= 1) {
      if (fs.existsSync(`${this.file}.${i}`)) fs.renameSync(`${this.file}.${i}`, `${this.file}.${i + 1}`);
    }
    fs.renameSync(this.file, `${this.file}.1`);
  }
}

/**
 * Call once at start: a launchd stdout file over `maxBytes` is copied to `<file>.1` and truncated
 * in place (launchd holds it open for append, so a rename would leave it writing to the old name).
 */
export function capStdoutLog(file, maxBytes = LOG_MAX_BYTES) {
  let size;
  try { size = fs.statSync(file).size; } catch (error) { if (error.code === 'ENOENT') return false; throw error; }
  if (size <= maxBytes) return false;
  fs.copyFileSync(file, `${file}.1`);
  fs.chmodSync(`${file}.1`, 0o600);
  fs.truncateSync(file, 0);
  return true;
}

// --- shutdown (LC-01) ----------------------------------------------------------------------

export class Stopping extends ServiceError {}

/**
 * SIGTERM/SIGINT: stop taking new work, drain in-flight work until `deadline` seconds, then hand
 * over with `onStop(drained)`. A hand-over that never settles is cut by a hard exit
 * (EXIT_HARD_STOP) `grace` seconds later.
 *
 *   const drain = new Drain().install((drained) => server.close(() => process.exit(0)),
 *     { onStopping: () => log.append('service.stopping', 'info', 'Stopping.') });
 *   await drain.work(async () => { ... });   // rejects with Stopping once a stop has begun
 */
export class Drain {
  constructor({ deadline = DRAIN_SECONDS, grace = DRAIN_GRACE_SECONDS } = {}) {
    this.deadline = deadline;
    this.grace = grace;
    this.inflight = 0;
    this.stopping = false;
    this.waiters = new Set();
  }

  async work(fn) {
    if (this.stopping) throw new Stopping('The service is stopping and takes no new work.');
    this.inflight += 1;
    try {
      return await fn();
    } finally {
      this.inflight -= 1;
      if (this.inflight === 0) for (const wake of this.waiters) wake();
    }
  }

  /** Refuse new work from now on; false when a stop had already begun. */
  requestStop() {
    if (this.stopping) return false;
    this.stopping = true;
    return true;
  }

  /** Resolves true when in-flight work finished inside `timeoutSeconds`, false otherwise. */
  wait(timeoutSeconds) {
    if (this.inflight === 0) return Promise.resolve(true);
    return new Promise((resolve) => {
      const wake = () => { clearTimeout(timer); this.waiters.delete(wake); resolve(true); };
      const timer = setTimeout(() => { this.waiters.delete(wake); resolve(false); }, timeoutSeconds * 1000);
      this.waiters.add(wake);
    });
  }

  install(onStop, { onStopping, signals = ['SIGTERM', 'SIGINT'] } = {}) {
    const handler = () => {
      if (!this.requestStop()) return; // a second signal changes nothing: the hard exit holds the deadline
      setTimeout(() => process.exit(EXIT_HARD_STOP), (this.deadline + this.grace) * 1000).unref();
      (async () => {
        try { await onStopping?.(); } catch (error) { process.stderr.write(`${error?.stack ?? error}\n`); }
        await onStop(await this.wait(this.deadline));
      })();
    };
    for (const signal of signals) process.on(signal, handler);
    return this;
  }
}

// --- releases (LC-11, LC-15) -----------------------------------------------------------------

/**
 * Keep the release the job runs and the one before it; remove older release directories, newest
 * first by modification time. `current` (a release or a symlink to one) is never removed, even
 * after a rollback. Symlinks and files are left alone. Returns the removed paths.
 */
export function pruneReleases(releasesDir, { keep = 2, current } = {}) {
  if (keep < 2) throw new ServiceError('keep at least the current release and the one before it (keep >= 2).');
  if (!fs.existsSync(releasesDir)) return [];
  const releases = fs.readdirSync(releasesDir, { withFileTypes: true })
    .filter((e) => e.isDirectory() && !e.isSymbolicLink())
    .map((e) => path.join(releasesDir, e.name))
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
  const keepers = [];
  if (current) {
    const resolved = fs.realpathSync(current);
    keepers.push(...releases.filter((p) => fs.realpathSync(p) === resolved));
  }
  for (const release of releases) {
    if (keepers.length >= keep) break;
    if (!keepers.includes(release)) keepers.push(release);
  }
  const removed = releases.filter((p) => !keepers.includes(p));
  for (const release of removed) fs.rmSync(release, { recursive: true, force: true });
  return removed;
}

// --- operator login -------------------------------------------------------------------

/** DEC-0039 (service.md "The session's lifetime"): the longest a service may keep an operator session. */
export const OPERATOR_SESSION_IDLE_SECONDS = 12 * 60 * 60;
export const OPERATOR_SESSION_MAX_SECONDS = 7 * 24 * 60 * 60;

// Compare bytes, not UTF-16 units: a non-ASCII value of the right length must be a refusal, not a RangeError.
const safeEqual = (a, b) => {
  const x = Buffer.from(String(a)), y = Buffer.from(String(b));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
};
const sessionBound = (value, longest) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new ServiceError('a session bound must be a finite number of seconds.');
  return Math.min(Math.trunc(value), longest);
};

// Single-use login codes, and operator sessions with the DEC-0039 lifetime: a session ends 12 h after its
// last use, 7 days after the code was redeemed, on logout, and when the descriptor token rotates. The server
// enforces all four: the cookie carries a signed claim (session id, sign-in time, token revision) and the
// code store keeps a record per session (last use, logout). Rotating the key with revokeAll() ends every one.
export class LoginCodes {
  // `stateDir` — a local service keeps codes, sessions and the session key in files. An online service
  // (DEC-0019) usually has no durable disk: pass `stateDir = null` with `{ store, key }` — `store` like
  // `new MemoryCodeStore()` and `key` a Buffer from a platform secret. A memory store forgets codes AND
  // sessions on a restart, so a deploy signs the operator out (the host signs in again on the page's 401);
  // pass a durable store to keep sessions. `token` is the descriptor token, or a function returning the
  // current one: a session begun under one token is refused once it rotates. A service MAY shorten
  // `idleSeconds` or `maxSeconds`, never lengthen them.
  constructor(stateDir, ttlSeconds = 120, { store = null, key = null, token = null,
    idleSeconds = OPERATOR_SESSION_IDLE_SECONDS, maxSeconds = OPERATOR_SESSION_MAX_SECONDS, clock = () => Date.now() / 1000 } = {}) {
    this.ttl = Math.min(ttlSeconds, 120);
    this.idleSeconds = sessionBound(idleSeconds, OPERATOR_SESSION_IDLE_SECONDS);
    this.maxSeconds = sessionBound(maxSeconds, OPERATOR_SESSION_MAX_SECONDS);
    this.store = store;
    this.fixedKey = key;
    this.token = token;
    this.clock = clock;
    if (stateDir) {
      this.dir = ensurePrivateDir(stateDir);
      this.keyPath = path.join(this.dir, 'session.key');
      this.codesPath = path.join(this.dir, 'login-codes.json');
    } else if (!store || !key) {
      throw new ServiceError('LoginCodes without a state directory needs { store, key }.');
    }
    if (key && Buffer.from(key).length < 32) throw new ServiceError('the session key must be at least 32 bytes.');
  }

  key() {
    if (this.fixedKey) return Buffer.from(this.fixedKey);
    if (!fs.existsSync(this.keyPath)) atomicWrite(this.keyPath, crypto.randomBytes(32), 0o600);
    return fs.readFileSync(this.keyPath);
  }

  load() {
    if (this.store) return this.store.load();
    try { return JSON.parse(fs.readFileSync(this.codesPath, 'utf8')); } catch { return {}; }
  }

  save(codes) {
    const horizon = this.clock() - 3600;
    const kept = Object.fromEntries(Object.entries(codes).filter(([, v]) => (v.expires ?? 0) > horizon));
    if (this.store) { this.store.save(kept); return; }
    atomicWrite(this.codesPath, JSON.stringify(kept), 0o600);
  }

  issue() {
    const code = crypto.randomBytes(24).toString('base64url');
    const expires = this.clock() + this.ttl;
    const codes = this.load();
    codes[crypto.createHash('sha256').update(code).digest('hex')] = { expires, used: false };
    this.save(codes);
    return { url: `/fabric/v1/login?code=${code}`, expiresAt: new Date(expires * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z') };
  }

  // The code is recorded as used BEFORE it is honoured, and burned even when expired.
  redeem(code) {
    if (!code || !CODE.test(code)) return null;
    const digest = crypto.createHash('sha256').update(code).digest('hex');
    const codes = this.load();
    const entry = codes[digest];
    if (!entry || entry.used) return null;
    entry.used = true;
    this.save(codes);
    const now = this.clock();
    if (entry.expires < now) return null;
    const session = crypto.randomBytes(18).toString('base64url');
    const signedInAt = Math.trunc(now);
    codes[LoginCodes.recordKey(session)] = { expires: signedInAt + this.maxSeconds, signedInAt, lastUsedAt: now };
    this.save(codes);
    const claim = `v2.${session}.${signedInAt}.${this.tokenRevision()}`;
    return `${claim}.${this.mac(claim)}`;
  }

  /** True while the session is live; a use within the bounds refreshes the idle bound. */
  sessionValid(value) {
    const parsed = this.parse(value);
    if (!parsed) return false;
    const [session, signedInAt] = parsed;
    const now = this.clock();
    if (now >= signedInAt + this.maxSeconds) return false;
    const codes = this.load();
    const record = codes[LoginCodes.recordKey(session)];
    if (!record || record.signedInAt !== signedInAt || record.loggedOutAt != null) return false;
    const last = Number(record.lastUsedAt ?? 0);
    if (now >= last + this.idleSeconds) return false;
    if (now - last >= Math.min(60, Math.max(1, Math.trunc(this.idleSeconds / 10)))) {
      record.lastUsedAt = now;
      this.save(codes);
    }
    return true;
  }

  /** End this session on the server; clear the browser's copy with expiredSessionCookieHeader(). */
  logout(value) {
    const parsed = this.parse(value);
    if (!parsed) return false;
    const codes = this.load();
    const record = codes[LoginCodes.recordKey(parsed[0])];
    if (!record || record.signedInAt !== parsed[1] || record.loggedOutAt != null) return false;
    record.loggedOutAt = this.clock();
    this.save(codes);
    return true;
  }

  parse(value) {
    if (typeof value !== 'string' || !/^[\x21-\x7e]*$/.test(value)) return null;
    const parts = value.split('.');
    if (parts.length !== 5 || parts[0] !== 'v2' || !parts[1] || !/^\d+$/.test(parts[2])) return null;
    if (!safeEqual(parts[4], this.mac(parts.slice(0, 4).join('.')))) return null;
    if (!safeEqual(parts[3], this.tokenRevision())) return null;
    return [parts[1], Number(parts[2])];
  }

  mac(claim) { return crypto.createHmac('sha256', this.key()).update(claim).digest('hex'); }

  tokenRevision() {
    const token = typeof this.token === 'function' ? this.token() : this.token;
    if (!token) return '-';
    return crypto.createHmac('sha256', this.key()).update(`token-revision\0${token}`).digest('hex').slice(0, 16);
  }

  static recordKey(session) { return `s:${crypto.createHash('sha256').update(session).digest('hex')}`; }

  revokeAll() {
    if (this.fixedKey) throw new ServiceError('a platform-held session key is rotated on the platform, not here.');
    atomicWrite(this.keyPath, crypto.randomBytes(32), 0o600);
  }
}

/** DEC-0019: a code store held in memory — for an online service with no durable disk. */
export class MemoryCodeStore {
  constructor() { this.codes = {}; }
  load() { return JSON.parse(JSON.stringify(this.codes)); }
  save(codes) { this.codes = JSON.parse(JSON.stringify(codes)); }
}

/** The cookie lives no longer than the absolute bound (DEC-0039); the server ends it sooner. */
export const sessionCookieHeader = (value, maxAge = OPERATOR_SESSION_MAX_SECONDS) => `${SESSION_COOKIE}=${value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${maxAge}`;
/** DEC-0019: the remote cookie — `__Host-` name, Secure, no Domain, Path=/. */
export const remoteSessionCookieHeader = (value, maxAge = OPERATOR_SESSION_MAX_SECONDS) => `${REMOTE_SESSION_COOKIE}=${value}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=${maxAge}`;
/** The header that clears the browser's session cookie, sent with a logout. */
export const expiredSessionCookieHeader = (remote = false) => (remote ? remoteSessionCookieHeader : sessionCookieHeader)('', 0);

/**
 * DEC-0019: the request guard of an online service. `origin` is the service's own origin
 * (`https://agent.example.com`). `forwardedProto` is the platform-set scheme where TLS ends
 * before the process (`x-forwarded-proto`); pass `undefined` when the process terminates TLS.
 * Returns the refusal sentence, or null.
 */
export function checkRemoteRequest(origin, host, requestOrigin, secFetchSite, forwardedProto) {
  const own = new URL(origin);
  if (String(host ?? '').toLowerCase() !== own.host) return `Host ${host} is not this service.`;
  if (forwardedProto !== undefined && forwardedProto !== null && String(forwardedProto).split(',')[0].trim() !== 'https') return 'This service answers over https only.';
  if (requestOrigin !== undefined && requestOrigin !== null && requestOrigin !== own.origin) return `Origin ${requestOrigin} is not this service.`;
  if (secFetchSite === 'cross-site') return 'Cross-site requests are refused.';
  return null;
}

/**
 * DEC-0019: may this request read the well-known document? A local service answers anyone (the
 * loopback guard already ran); a remote one only the bearer of the service token. A `false`
 * answer is a `401` with an EMPTY body — nothing about the service is disclosed.
 */
export function wellKnownAllowed(placement, authorization, token, scheme = 'Bearer') {
  return placement !== 'remote' || tokenMatches(authorization, token, scheme);
}

/** The token directory a host-side installer uses for remote services on this computer. */
export function remoteTokenFile(id, instance = 'default', dir = servicesDir()) {
  return path.join(path.dirname(dir), 'tokens', `${id}.${instance}.token`);
}

/**
 * DEC-0019, installer side: register an online service on THIS computer. Writes the token file
 * (0600, never printed) and the descriptor; the same token must be set on the hosting platform as
 * a secret. Returns the descriptor path. `token` is read from the caller — a file or stdin —
 * never from an argument vector.
 */
/**
 * DEC-0019, installer side: register an online service on THIS computer — the token file (0600, never printed) and the
 * descriptor. DEC-0061: `installedBy` defaults to `{by: 'person', role: 'operator', tool: 'fabric-service register-remote'}`
 * (a person runs this); `runner` (`{kind?, credentialKind}`) says how its model calls sign in, as a kind and never a
 * credential; `peer` (`{endpoint, custody, residency, maxDataClass}`) offers it to others and needs `runner`.
 */
export function registerRemote({ id, instance = 'default', name, summary, origin, token, doctor, dir = servicesDir(),
  installedBy = { by: 'person', role: 'operator', tool: 'fabric-service register-remote' }, runner, peer }) {
  if (!token || String(token).trim().length < 16) throw new ServiceError('the service token must be at least 16 characters.');
  const tokenFile = remoteTokenFile(id, instance, dir);
  const d = {
    protocol: PROTOCOL, id, instance, name, ...(summary ? { summary } : {}), placement: 'remote', origin,
    auth: { tokenFile }, lifecycle: { manager: 'none' }, ...(doctor ? { commands: { doctor } } : {}),
    installedAt: nowIso(), installedBy, ...(runner ? { runner: { ...runner } } : {}), ...(peer ? { peer: { ...peer } } : {}),
  };
  const problems = validateDescriptor(d);
  if (problems.length) throw new ServiceError(`Descriptor is invalid: ${problems.join('; ')}.`);
  ensurePrivateDir(path.dirname(tokenFile));
  atomicWrite(tokenFile, String(token).trim(), 0o600);
  return writeDescriptor(d, dir);
}

export function cookieValue(header, name = SESSION_COOKIE) {
  for (const part of String(header ?? '').split(';')) {
    const [k, ...rest] = part.trim().split('=');
    if (k === name) return rest.join('=');
  }
  return null;
}

// --- systemd and Task Scheduler (DEC-0032, service.md "Supervisor") -------------------------
// The twins of fabric_service.systemd_unit / task_xml and their install and uninstall. `run(argv)`
// returns spawnSync's {status, stdout, stderr}; the tests pass a recorder instead of the real tools.

const defaultRun = (argv) => spawnSync(argv[0], argv.slice(1), { encoding: 'utf8', windowsHide: true });

function plain(value, what) {
  // A supervisor file is line- and XML-structured: no control character in anything written into it.
  if (/[\x00-\x1f\x7f]/.test(value)) throw new ServiceError(`${what} holds a control character (a line break, a tab, a NUL); a supervisor file cannot carry it.`);
  return value;
}

/** The supervisor file's writer writes the marker itself; one already in the arguments could only disagree with it. */
function noMarkerArgument(argv) {
  if (markerArguments(argv).length) throw new ServiceError(`${SUPERVISOR_ARG} is written by the supervisor file's writer; leave it out of the program arguments.`);
}

function noSecretInSupervisorFile(argv, environment) {
  // No supervisor file carries a secret (service.md): not in an argument, an environment name or its value.
  for (const arg of argv) {
    if (secretArgument(arg)) throw new ServiceError('An argument carries a credential; a supervisor file never does (read it from the token file or a secret reference).');
  }
  for (const [name, value] of Object.entries(environment ?? {})) {
    if (credentialName(name) || secretValue(String(value))) throw new ServiceError(`Environment ${name} looks like a credential; a supervisor file never carries one.`);
  }
}

function check(result, what) {
  if (result?.status !== 0) throw new ServiceError(`${what} failed: ${String(result?.stderr || result?.stdout || result?.error?.message || '').trim().slice(0, 200)}`);
}

const systemdQuote = (value) => `"${plain(value, 'An argument').replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/%/g, '%%').replace(/\$/g, '$$$$')}"`;

/**
 * A systemd user unit (DEC-0032): Restart=always, RestartSec=10, TimeoutStopSec above the drain time,
 * WantedBy=default.target. The service is told who supervises it (FABRIC_SERVICE_SUPERVISOR=systemd).
 */
export function systemdUnit(unit, programArguments, { workingDirectory, environment = {}, description, stopTimeout = DEFAULT_EXIT_TIMEOUT } = {}) {
  if (!UNIT.test(unit)) throw new ServiceError(`unit must match ${UNIT.source}`);
  const argv = programArguments.map(String);
  if (!argv.length || !argv[0].startsWith('/')) throw new ServiceError('A systemd unit starts an absolute executable.');
  if (!(stopTimeout > DRAIN_SECONDS)) throw new ServiceError(`TimeoutStopSec must outlast the ${DRAIN_SECONDS} s drain.`);
  const env = { ...environment };
  for (const name of Object.keys(env)) if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) throw new ServiceError(`Environment name ${JSON.stringify(name)} is not a variable name.`);
  noSecretInSupervisorFile(argv, env);
  noMarkerArgument(programArguments.map(String));
  env[SUPERVISOR_ENV] = 'systemd'; // the unit's writer writes the marker, whatever the caller passed
  const cwd = plain(String(workingDirectory), 'The working directory');
  if (!cwd.startsWith('/')) throw new ServiceError("A systemd unit's working directory is absolute.");
  return [
    '[Unit]', `Description=${plain(description ?? unit, 'The description').replace(/%/g, '%%')}`, '',
    '[Service]', 'Type=simple', `ExecStart=${argv.map(systemdQuote).join(' ')}`,
    // Not quoted: systemd reads WorkingDirectory= as the rest of the line, quotes included.
    `WorkingDirectory=${cwd.replace(/%/g, '%%')}`,
    ...Object.keys(env).sort().map((k) => `Environment=${systemdQuote(`${k}=${env[k]}`)}`),
    'Restart=always', 'RestartSec=10', `TimeoutStopSec=${Math.trunc(stopTimeout)}`, 'KillMode=mixed', '',
    '[Install]', 'WantedBy=default.target', '',
  ].join('\n');
}

const systemdDir = () => path.join(process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config'), 'systemd', 'user');

/**
 * Write the user unit, enable it so it comes back after a login, and (re)start it so the new unit is what runs.
 * The operator's intent wins (LC-14): a unit already installed and disabled stays off — the file is rewritten, so the
 * new version is what starts once they enable it — unless `forceEnable` (the operator asked for it on).
 */
export function systemdInstall(unit, text, { unitDir = systemdDir(), run = defaultRun, platform = process.platform, forceEnable = false } = {}) {
  if (platform !== 'linux') throw new ServiceError('systemd is the supervisor on Linux only.');
  if (!UNIT.test(unit)) throw new ServiceError(`unit must match ${UNIT.source}`);
  fs.mkdirSync(unitDir, { recursive: true });
  const file = path.join(unitDir, unit);
  const state = fs.existsSync(file) ? String(run(['systemctl', '--user', 'is-enabled', unit])?.stdout ?? '').trim() : '';
  atomicWrite(file, text, 0o644);
  check(run(['systemctl', '--user', 'daemon-reload']), 'systemctl --user daemon-reload');
  if (state === 'disabled' && !forceEnable) return file;
  check(run(['systemctl', '--user', 'enable', unit]), 'systemctl --user enable');
  check(run(['systemctl', '--user', 'restart', unit]), 'systemctl --user restart');
  return file;
}

/** Stop it and keep it off across logins (`disable --now`), then remove the unit. */
export function systemdUninstall(unit, { unitDir = systemdDir(), run = defaultRun, platform = process.platform } = {}) {
  if (platform !== 'linux') throw new ServiceError('systemd is the supervisor on Linux only.');
  if (!UNIT.test(unit)) throw new ServiceError(`unit must match ${UNIT.source}`);
  run(['systemctl', '--user', 'disable', '--now', unit]);
  fs.rmSync(path.join(unitDir, unit), { force: true });
  check(run(['systemctl', '--user', 'daemon-reload']), 'systemctl --user daemon-reload');
}

/** One command line from arguments, quoted the way the Microsoft C runtime parses it (Python's list2cmdline). */
export function windowsCommandLine(args) {
  return args.map((arg) => {
    const quote = arg === '' || /[ \t]/.test(arg);
    let out = quote ? '"' : '';
    let slashes = 0;
    for (const c of arg) {
      if (c === '\\') { slashes += 1; continue; }
      if (c === '"') { out += '\\'.repeat(slashes * 2 + 1) + '"'; slashes = 0; continue; }
      out += '\\'.repeat(slashes) + c;
      slashes = 0;
    }
    return out + '\\'.repeat(quote ? slashes * 2 : slashes) + (quote ? '"' : '');
  }).join(' ');
}

const xml = (text) => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/**
 * A per-user Scheduled Task (DEC-0032): a logon trigger, restart on failure every minute, no execution
 * time limit, run only when the user is logged on, created without administrator rights.
 */
export function taskXml(task, programArguments, { workingDirectory, description, user } = {}) {
  if (!TASK.test(task)) throw new ServiceError(`task must match ${TASK.source}`);
  const argv = programArguments.map(String);
  if (!argv.length || !/^[A-Za-z]:[\\/]/.test(argv[0])) throw new ServiceError('A task starts a drive-absolute executable (C:\\...).');
  for (const arg of argv) plain(arg, 'An argument');
  plain(String(workingDirectory), 'The working directory');
  plain(description ?? task, 'The description');
  noSecretInSupervisorFile(argv, {});
  noMarkerArgument(argv);
  // A task's Exec action carries no environment, so the marker is an argument (DEC-0057), before any `--`.
  const cut = argv.includes('--') ? argv.indexOf('--') : argv.length;
  argv.splice(cut, 0, SUPERVISOR_ARG, 'task-scheduler');
  const who = user ?? (process.env.USERNAME ? `${process.env.USERDOMAIN ?? ''}\\${process.env.USERNAME}` : '');
  if (!who) throw new ServiceError('Name the user the task runs as (DOMAIN\\user); USERNAME is not set.');
  plain(who, 'The user');
  return `<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>${xml(description ?? task)}</Description><URI>${xml(task)}</URI></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>${xml(who)}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>${xml(who)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec><Command>${xml(argv[0])}</Command><Arguments>${xml(windowsCommandLine(argv.slice(1)))}</Arguments><WorkingDirectory>${xml(workingDirectory)}</WorkingDirectory></Exec></Actions>
</Task>
`;
}

const TASK_DISABLED = /<Settings>(?:(?!<\/Settings>)[\s\S])*<Enabled>false<\/Enabled>/;

/**
 * Create (or replace) the task from its XML without administrator rights, then (re)start it so the new definition
 * is what runs. A task already installed and disabled stays off (LC-14) unless `forceEnable`.
 */
export function taskInstall(task, xmlText, { run = defaultRun, platform = process.platform, forceEnable = false } = {}) {
  if (platform !== 'win32') throw new ServiceError('Task Scheduler is the supervisor on Windows only.');
  const query = run(['schtasks', '/Query', '/TN', task, '/XML']);
  const existed = query?.status === 0;
  const keepOff = existed && !forceEnable && TASK_DISABLED.test(String(query?.stdout ?? ''));
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-task-'));
  const file = path.join(dir, 'task.xml');
  try {
    // schtasks reads the encoding the declaration names: UTF-16 little-endian with its byte order mark.
    fs.writeFileSync(file, Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from(xmlText, 'utf16le')]));
    check(run(['schtasks', '/Create', '/TN', task, '/XML', file, '/F']), 'schtasks /Create');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
  if (keepOff) {
    check(run(['schtasks', '/Change', '/TN', task, '/DISABLE']), 'schtasks /Change /DISABLE');
    return;
  }
  if (existed) run(['schtasks', '/End', '/TN', task]);
  check(run(['schtasks', '/Run', '/TN', task]), 'schtasks /Run');
}

/** End the running task, then delete it. */
export function taskUninstall(task, { run = defaultRun, platform = process.platform } = {}) {
  if (platform !== 'win32') throw new ServiceError('Task Scheduler is the supervisor on Windows only.');
  run(['schtasks', '/End', '/TN', task]);
  check(run(['schtasks', '/Delete', '/TN', task, '/F']), 'schtasks /Delete');
}

// --- launchd (macOS; lifecycle.md "Install, upgrade, uninstall", LC-14; FAA-04) ------------------------------------
// The twins of fabric_service.launchd_plist / launchd_loaded / launchd_override / launchd_install / launchd_uninstall.
// `run(argv)` returns spawnSync's {status, stdout, stderr}; the tests pass a launchd stand-in, never the real launchctl.

const LABEL = /^[A-Za-z0-9][A-Za-z0-9._-]{0,250}$/;
const DEFAULT_PATH = '/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin';
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function launchdLabel(label) {
  if (!LABEL.test(String(label))) throw new ServiceError(`label must match ${LABEL.source}`);
  return String(label);
}

function plistValue(value, depth) {
  // plistlib.dumps's layout, byte for byte: one tab per level, keys sorted, & < > escaped, empty containers self-closed.
  const pad = '\t'.repeat(depth);
  if (value === true || value === false) return `${pad}<${value}/>\n`;
  if (Number.isInteger(value)) return `${pad}<integer>${value}</integer>\n`;
  if (typeof value === 'string') return `${pad}<string>${plain(value, 'A plist string').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</string>\n`;
  if (Array.isArray(value)) return value.length ? `${pad}<array>\n${value.map((v) => plistValue(v, depth + 1)).join('')}${pad}</array>\n` : `${pad}<array/>\n`;
  const keys = Object.keys(value).sort();
  if (!keys.length) return `${pad}<dict/>\n`;
  const inner = keys.map((k) => `${pad}\t<key>${plain(k, 'A plist key').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</key>\n${plistValue(value[k], depth + 1)}`).join('');
  return `${pad}<dict>\n${inner}${pad}</dict>\n`;
}

/**
 * The launchd job: RunAtLoad + KeepAlive true + ThrottleInterval 10, ProcessType Standard, ExitTimeOut above the drain.
 * FABRIC_SERVICE_SUPERVISOR=launchd tells the lock to back off instead of exiting into a respawn loop (DEC-0057).
 * No secret is written: an environment name ending TOKEN/SECRET/PASSWORD/KEY (a `*_FILE` path is fine), a value or an
 * argument shaped like a credential is refused. Returns the XML text, the same bytes Python's plistlib writes.
 */
export function launchdPlist(label, programArguments, { workingDirectory, stdoutPath, environment = {}, exitTimeout = DEFAULT_EXIT_TIMEOUT } = {}) {
  launchdLabel(label);
  const argv = programArguments.map(String);
  if (!argv.length) throw new ServiceError('A launchd job starts a program; ProgramArguments is empty.');
  if (!(exitTimeout > DRAIN_SECONDS)) throw new ServiceError(`ExitTimeOut must outlast the ${DRAIN_SECONDS} s drain.`);
  if (workingDirectory === undefined || stdoutPath === undefined) throw new ServiceError('A launchd job names its working directory and its log file.');
  const env = { ...environment };
  for (const [name, value] of Object.entries(env)) {
    if (/(TOKEN|SECRET|PASSWORD|KEY)$/.test(name) && !name.endsWith('_FILE')) throw new ServiceError(`Environment variable ${name} looks like a secret; pass a *_FILE path instead.`);
    if (secretValue(String(value))) throw new ServiceError(`Environment ${name} holds a value shaped like a credential; a plist never carries one.`);
  }
  for (const arg of argv) {
    if (secretArgument(arg)) throw new ServiceError('An argument carries a credential; a plist never does (read it from the token file or a secret reference).');
  }
  noMarkerArgument(argv);
  if (env.PATH === undefined) env.PATH = DEFAULT_PATH;
  env[SUPERVISOR_ENV] = 'launchd'; // the plist's writer writes the marker, whatever the caller passed
  const job = {
    Label: label,
    ProgramArguments: argv,
    WorkingDirectory: String(workingDirectory),
    RunAtLoad: true,
    KeepAlive: true,
    ThrottleInterval: 10,
    ExitTimeOut: Math.trunc(exitTimeout),
    // Standard, never Background: macOS starves a Background job under load and every host then reports an outage.
    ProcessType: 'Standard',
    StandardOutPath: String(stdoutPath),
    StandardErrorPath: String(stdoutPath),
    EnvironmentVariables: env,
  };
  return '<?xml version="1.0" encoding="UTF-8"?>\n'
    + '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
    + `<plist version="1.0">\n${plistValue(job, 0)}</plist>\n`;
}

function launchdDomain(platform, uid) {
  // DEC-0032: launchd is macOS's supervisor; Linux has systemd and Windows Task Scheduler.
  if (platform !== 'darwin') throw new ServiceError('launchd is the supervisor on macOS only; use systemdInstall on Linux and taskInstall on Windows.');
  return `gui/${uid ?? process.getuid()}`;
}

/** True when launchd has the job loaded (`launchctl print gui/<uid>/<label>` answers). */
export function launchdLoaded(label, { run = defaultRun, platform = process.platform, uid } = {}) {
  return run(['launchctl', 'print', `${launchdDomain(platform, uid)}/${launchdLabel(label)}`])?.status === 0;
}

const OVERRIDE_ROW = /^\s*"([^"]+)"\s*=>\s*(\S+)\s*$/;

/**
 * The operator's launchd override for `label`: 'disabled', 'enabled', null when none is recorded (a first install), or
 * 'unknown' when the table cannot be read. macOS 14+ prints `=> disabled|enabled`, older releases `=> true|false`.
 */
export function launchdOverride(label, { run = defaultRun, platform = process.platform, uid } = {}) {
  const result = run(['launchctl', 'print-disabled', launchdDomain(platform, uid)]);
  if (result?.status !== 0) return 'unknown';
  for (const line of String(result.stdout ?? '').split('\n')) {
    const match = OVERRIDE_ROW.exec(line);
    if (match && match[1] === label) return ['disabled', 'true'].includes(match[2]) ? 'disabled' : 'enabled';
  }
  return null;
}

async function wellKnownOf(origin) {
  try {
    const response = await fetch(`${origin}/.well-known/fabric-service`, { signal: AbortSignal.timeout(2000) });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

/**
 * Write and lint the plist, bootout and WAIT for the unload, bootstrap (retrying launchd's EIO 5 times), then poll the
 * well-known document until it answers with this identity; resolves to that document.
 *
 * The operator's intent wins (LC-14): only a first install (no override recorded) enables the label. A label the
 * operator disabled stays disabled and unloaded — the plist is still rewritten, so the new release is what starts once
 * they turn it back on — and the answer is {disabled: true, label, plist, loaded}. `forceEnable` is for an operator
 * who asked for the service to be switched on.
 */
export async function launchdInstall(label, plistPath, plistText, { origin, serviceId, instance = 'default', timeout = 40, forceEnable = false,
  run = defaultRun, platform = process.platform, uid, fetchWellKnown = wellKnownOf, sleep = pause } = {}) {
  const domain = launchdDomain(platform, uid);
  launchdLabel(label);
  if (!origin || !serviceId) throw new ServiceError('launchdInstall needs the origin and the service id it waits to see answer.');
  const opts = { run, platform, uid };
  atomicWrite(plistPath, plistText, 0o644);
  const lint = run(['plutil', '-lint', String(plistPath)]);
  if (lint?.status !== 0) throw new ServiceError(`plist failed plutil -lint: ${String(lint?.stdout || lint?.stderr || '').trim().slice(0, 200)}`);
  const target = `${domain}/${label}`;
  const override = launchdOverride(label, opts);
  if (forceEnable || override === null) run(['launchctl', 'enable', target]);
  else if (override === 'disabled') return { disabled: true, label, plist: String(plistPath), loaded: launchdLoaded(label, opts) };
  run(['launchctl', 'bootout', target]);
  const unloaded = Date.now() + 15_000;
  while (launchdLoaded(label, opts) && Date.now() < unloaded) await sleep(250);
  let last = '';
  for (let attempt = 0; ; attempt += 1) {
    const result = run(['launchctl', 'bootstrap', domain, String(plistPath)]);
    if (result?.status === 0) break;
    last = String(result?.stderr || result?.stdout || '').trim();
    if (attempt === 4) throw new ServiceError(`launchctl bootstrap failed: ${last.slice(0, 200)}`);
    await sleep(1000);
  }
  const deadline = Date.now() + timeout * 1000;
  while (Date.now() < deadline) {
    const doc = await fetchWellKnown(origin);
    if (doc?.service?.id === serviceId && doc?.service?.instance === instance) return doc;
    await sleep(500);
  }
  throw new ServiceError(`${origin} did not answer as ${serviceId}.${instance} within ${timeout} s; read its log.`);
}

/**
 * Symmetric with launchdInstall (LC-14): bootout and WAIT until the job is gone, remove the plist, and reset the
 * override to enabled — launchctl has no verb that deletes an override, and a leftover `disabled` would keep a later
 * fresh install off. Data stays unless `purge` (then `serviceId` names whose data, logs and cache go). A job still
 * loaded at `timeout` seconds throws, leaving the plist and the data in place.
 */
export async function launchdUninstall(label, plistPath, { timeout = 30, purge = false, serviceId, run = defaultRun, platform = process.platform, uid, sleep = pause } = {}) {
  const domain = launchdDomain(platform, uid);
  launchdLabel(label);
  if (purge && !serviceId) throw new ServiceError('purge needs the service id whose data, logs and cache to remove.');
  const dirs = purge ? serviceDirs(serviceId, platform) : {};
  const opts = { run, platform, uid };
  const target = `${domain}/${label}`;
  run(['launchctl', 'bootout', target]);
  const deadline = Date.now() + timeout * 1000;
  while (launchdLoaded(label, opts)) {
    if (Date.now() >= deadline) throw new ServiceError(`launchd job ${label} is still loaded ${timeout} s after bootout; nothing was removed.`);
    await sleep(100);
  }
  let plistRemoved = true;
  try {
    fs.unlinkSync(plistPath);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    plistRemoved = false;
  }
  run(['launchctl', 'enable', target]);
  const purged = [];
  for (const dir of Object.values(dirs)) {
    try { fs.lstatSync(dir); } catch { continue; }
    fs.rmSync(dir, { recursive: true, force: true }); // a symlinked folder: the link goes, never what it points at
    purged.push(dir);
  }
  return { unloaded: true, plistRemoved, override: 'enabled', purged };
}
