// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
// One copy of a service, locked before any side effect (LC-01, DEC-0057): the instance lock and the supervisor marker.
// Part of the Node service kit (FAA-65, layer L3); the twin of fabric_lock.py. Node 20+ (22+ for the Linux lock), no dependency.
//
// A lock that moves under its holder (FAA-303). Linux and Windows hold a name keyed by the lock's path (an abstract
// unix socket, a named pipe), so a folder swapped under a running copy cannot let a second copy in. macOS has no such
// name: O_EXLOCK (and the Python twin's flock) lock an inode, so after a data import swaps the data folder a second
// copy locks the new file and starts. There the holder watches its lock instead (InstanceLock#watch, started by
// holdSingleInstance): every LOCK_WATCH_SECONDS it compares the inode it locked with the file at the path, and once
// the path names another file it stops with 75 and one sentence naming the path, before writing anything more into a
// folder that is no longer the one it read. Two copies then overlap for at most one interval. A path-keyed name on
// macOS was weighed and left: it needs a file in a folder outside the data folder that the system never cleans and
// every copy can write, which Node alone cannot promise.
import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { SUPERVISOR_ENV, ServiceError } from './fabric-base.mjs';
import { atomicWrite, ensurePrivateDir } from './fabric-paths.mjs';

export const EXIT_ALREADY_RUNNING = 75;

export const LOCK_WAIT_SUPERVISED_SECONDS = 300;

export const LOCK_BACKOFF_FIRST_SECONDS = 0.5;

export const LOCK_BACKOFF_MAX_SECONDS = 30;

/**
 * How often a holder that has no path-keyed name (macOS) compares the inode it locked with the file at the lock's path
 * (FAA-303): one stat and one fstat; two copies overlap for at most this long after a folder swap.
 */
export const LOCK_WATCH_SECONDS = 2;

const O_EXLOCK = 0x20; // BSD/macOS: open(2) takes flock(LOCK_EX); absent from fs.constants

export class AlreadyRunning extends ServiceError {
  constructor(holderPid, lockPath) {
    // FAC-SEM-078: a copy that cannot learn the holder's pid says the holder is unknown.
    super(`Another copy is already running (${holderPid ? `process ${holderPid}` : 'an unknown process'} holds ${lockPath}).`);
    this.holderPid = holderPid;
    this.lockPath = lockPath;
  }
}

export class InstanceLock {
  /** How many times acquire re-opens service.lock that moved under it before it gives up (FAA-293). */
  static INODE_RETRIES = 3;

  constructor(dataDir) {
    this.path = path.join(dataDir, 'service.lock');
    this.fd = null;
    this.server = null;
    this.timer = null;
  }

  async acquire() {
    ensurePrivateDir(path.dirname(this.path));
    if (process.platform === 'darwin') {
      // FAA-293: a folder swapped under service.lock (a data import) leaves this copy holding a file that is no longer
      // at the path while another copy holds the one that is. Re-open a bounded number of times, then fail clearly.
      for (let attempt = 0; attempt < InstanceLock.INODE_RETRIES; attempt += 1) {
        if (this.acquireDarwinOnce()) return this;
      }
      throw new ServiceError(`${this.path} kept moving while it was locked (a folder swapped under the data folder?): no copy holds a file that is no longer at its path; start again once the folder is settled.`);
    }
    // Linux: an abstract unix socket; Windows: a named pipe. Each is exclusive, has no file, and dies
    // with the process. The Python kit holds the same name beside its file lock (fabric_service.lock_name).
    const name = lockName(this.path);
    if (!name) throw new ServiceError(`No instance lock on ${process.platform}: the kit supports macOS, Linux and Windows.`);
    const names = process.platform === 'linux' ? await abstractNames() : 'exact';
    if (names === 'none' || names === 'padded') {
      // Node 18 and 20 cannot bind the name the Python kit binds: 18 and early 20 make every name 108 NUL bytes (one lock
      // for every service on the machine), later 20 pads it with NUL bytes (a name no Python copy or probe sees).
      throw new ServiceError(`Node ${process.version} cannot hold the instance lock's abstract socket name on Linux; run the service on Node 22 or later.`);
    }
    this.server = net.createServer();
    await new Promise((resolve, reject) => {
      // Windows reports a held pipe as EADDRINUSE (access denied) or, when its holder capped the instances, EBUSY.
      const held = (code) => code === 'EADDRINUSE' || (process.platform === 'win32' && code === 'EBUSY');
      this.server.once('error', (error) => reject(held(error.code) ? new AlreadyRunning(readPid(this.path), this.path) : error));
      this.server.listen(name, resolve);
    });
    this.server.unref();
    try {
      atomicWrite(this.path, String(process.pid));
    } catch (error) { // as on macOS: the name is let go with the failed write, the first error standing
      const server = this.server;
      this.server = null;
      try {
        server.close();
      } catch { // nothing to add to the first error
      }
      throw error;
    }
    return this;
  }

  lockedFileIsAtPath(fd) {
    let here;
    try {
      here = fs.statSync(this.path);
    } catch (error) {
      if (error.code === 'ENOENT') return false;
      throw error;
    }
    const held = fs.fstatSync(fd);
    return here.dev === held.dev && here.ino === held.ino;
  }

  acquireDarwinOnce() {
    const flags = fs.constants.O_RDWR | fs.constants.O_CREAT | O_EXLOCK | fs.constants.O_NONBLOCK;
    try {
      this.fd = fs.openSync(this.path, flags, 0o600);
    } catch (error) {
      if (error.code === 'EAGAIN' || error.code === 'EWOULDBLOCK') throw new AlreadyRunning(readPid(this.path), this.path);
      throw error;
    }
    if (!this.lockedFileIsAtPath(this.fd)) { // another copy may hold the file at the path: re-open that one
      fs.closeSync(this.fd);
      this.fd = null;
      return false;
    }
    try {
      fs.ftruncateSync(this.fd, 0);
      fs.writeSync(this.fd, String(process.pid));
      fs.fsyncSync(this.fd);
    } catch (error) { // a full disk or an I/O error: let the lock go, or nobody can (the caller drops this object)
      const fd = this.fd;
      this.fd = null;
      try {
        fs.closeSync(fd);
      } catch { // a deferred write error (NFS) at the close: the lock still goes, the first error stands
      }
      throw error;
    }
    if (!this.lockedFileIsAtPath(this.fd)) { // swapped while the pid was written: this copy holds nothing real
      fs.closeSync(this.fd);
      this.fd = null;
      return false;
    }
    return true;
  }

  /**
   * Re-check, every `intervalSeconds` on an unref'd timer, that the file this copy locked is still the file at the path
   * (FAA-303); the first time the path names another file (a swapped folder's lock, or the one a second copy made),
   * call `onLost(lock)` once and stop watching. The default stops the process with 75 and one sentence
   * (stopLostHolder). A path that is gone or cannot be read now is read as nothing there yet and tried again next time:
   * a second copy has to make a file there to start, and the watch then sees that file. `release` ends the watch. Only
   * a lock held as a file is watched (macOS): elsewhere the descriptor is null and the path-keyed name keeps a second
   * copy out, so this is a no-op, as for a lock not held.
   */
  watch({ onLost, intervalSeconds = LOCK_WATCH_SECONDS } = {}) {
    if (this.fd === null || this.timer !== null) return this;
    const fd = this.fd;
    const react = onLost ?? stopLostHolder;
    this.timer = setInterval(() => {
      let here;
      let held;
      try {
        here = fs.statSync(this.path);
        held = fs.fstatSync(fd);
      } catch {
        return;
      }
      if (here.dev === held.dev && here.ino === held.ino) return;
      clearInterval(this.timer);
      this.timer = null;
      react(this);
    }, intervalSeconds * 1000);
    this.timer.unref();
    return this;
  }

  /**
   * Let the lock go. Never throws, so a release in a `finally` never replaces the caller's own outcome (FAA-196 (11)):
   * the descriptor and the name's server are forgotten before they are closed, so a retry never closes a descriptor
   * reused since, and a close that fails still closes the server.
   */
  release() {
    if (this.timer !== null) clearInterval(this.timer);
    const { fd, server } = this;
    this.timer = null;
    this.fd = null;
    this.server = null;
    try {
      if (fd !== null) fs.closeSync(fd);
    } catch { // the descriptor is gone either way; the kernel frees the lock with it
    } finally {
      try {
        server?.close();
      } catch { // nothing to add to the caller's own outcome
      }
    }
  }
}

/** The one sentence a holder whose lock moved under it stops with (FAA-303). */
export function lostLockMessage(lockPath) {
  return `${lockPath} is no longer the file this copy locked (the data folder moved or was swapped?): stopping, so a copy started on the folder now at that path runs alone.`;
}

/**
 * InstanceLock#watch's default: write lostLockMessage and end the process with 75 at once. Not a graceful stop: a
 * shutdown would write this copy's state into the folder now at the path, which is not the one it read; the kit's
 * journals make an abrupt stop recoverable (LC-03).
 */
export function stopLostHolder(lock) {
  try {
    fs.writeSync(2, `${lostLockMessage(lock.path)}\n`);
  } finally {
    process.exit(EXIT_ALREADY_RUNNING);
  }
}

let abstractNamesSeen = null;

/**
 * How this Node binds an abstract unix socket name on Linux, learned once by binding a random one and reading
 * /proc/net/unix: 'exact' (Node 21 and later: the name the Python kit binds and fabric_lock.lock_name_held reads),
 * 'padded' (Node 20.x: the name followed by NUL bytes to the whole sun_path) or 'none' (Node 18 and early 20: every
 * name becomes 108 NUL bytes). 'unknown' when the table cannot be read.
 */
export async function abstractNames() {
  if (abstractNamesSeen !== null) return abstractNamesSeen;
  const probe = `fabric-probe-${crypto.randomBytes(8).toString('hex')}`;
  const server = net.createServer();
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(`\0${probe}`, resolve); });
    const rows = fs.readFileSync('/proc/net/unix', 'utf8').split('\n').map((row) => row.trimEnd().split(' ').pop());
    if (rows.includes(`@${probe}`)) abstractNamesSeen = 'exact';
    else if (rows.includes(`@${probe}`.padEnd(108, '@'))) abstractNamesSeen = 'padded';
    else abstractNamesSeen = 'none';
  } catch (error) {
    // A random name already in use means every name collapses to one: another such Node holds it.
    abstractNamesSeen = error?.code === 'EADDRINUSE' ? 'none' : 'unknown';
  } finally {
    server.close();
  }
  return abstractNamesSeen;
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
export function markerArguments(argv) {
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
 * the wait runs out. `waitSeconds` overrides the choice (0 = never wait). Where the lock is held as a file (macOS)
 * the held lock is watched (InstanceLock#watch, FAA-303): a folder swapped under the running copy stops it with 75;
 * `onLost` replaces that reaction.
 */
export async function holdSingleInstance(dataDir, {
  waitSeconds, sleep = sleepSeconds, clock = () => performance.now() / 1000, exit = (code) => process.exit(code), env, argv, onLost,
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
      return (await new InstanceLock(dataDir).acquire()).watch({ onLost });
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
