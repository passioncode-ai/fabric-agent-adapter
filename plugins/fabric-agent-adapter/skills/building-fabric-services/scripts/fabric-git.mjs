// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
// Git run on a folder the way every reader in the adapter runs it (FAA-190); the twin of fabric_git.py, which says why
// each rule is there. Git comes from PATH's absolute folders only, never from a folder inside the tree it reads, and on
// Windows only as git.exe; it runs no command the folder's configuration names (core.fsmonitor empty, Git for Windows'
// core.useBuiltinFSMonitor false); a Git location the caller exports is not passed; it writes nothing (GIT_TRACE* not
// passed, trace2 targets off, GIT_OPTIONAL_LOCKS=0). The caller's own Git configuration still applies.

import { spawnSync } from 'node:child_process';
import { accessSync, constants, realpathSync, statSync } from 'node:fs';
import path from 'node:path';

export const LOCATION = Object.freeze(['GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY', 'GIT_COMMON_DIR',
  'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_NAMESPACE', 'GIT_PREFIX']);
export const NO_COMMANDS = Object.freeze(['-c', 'core.fsmonitor=', '-c', 'core.useBuiltinFSMonitor=false']);
export const TRACE_OFF = Object.freeze({ GIT_TRACE2: '0', GIT_TRACE2_EVENT: '0', GIT_TRACE2_PERF: '0' });

const windows = () => process.platform === 'win32';

function real(p) {
  let out;
  try {
    out = realpathSync.native(String(p));
  } catch {
    out = path.resolve(String(p));
  }
  return windows() ? out.toLowerCase() : out;
}

function within(folder, trees) {
  const here = real(folder);
  return trees.some((tree) => {
    const rel = path.relative(tree, here);
    return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
  });
}

function runnable(candidate) {
  try {
    if (!statSync(candidate).isFile()) return false;
    if (!windows()) accessSync(candidate, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

/** `git` from PATH's absolute folders, skipping any folder inside one of `trees` (the folders it will read). */
export function executable(trees = []) {
  const name = windows() ? 'git.exe' : 'git';
  const raw = process.env.PATH;
  // with PATH unset, POSIX's default folders; on Windows no PATH means no git (its default holds the current folder)
  const folders = raw === undefined ? (windows() ? [] : ['/bin', '/usr/bin']) : raw.split(path.delimiter);
  let realTrees = null;
  for (const folder of folders) {
    if (!folder || !path.isAbsolute(folder)) continue;
    const candidate = path.join(folder, name);
    if (!runnable(candidate)) continue;
    if (realTrees === null) realTrees = [...trees].map(real);
    if (realTrees.length && within(folder, realTrees)) continue; // the tree's own git: never run
    return candidate;
  }
  return null;
}

function dropped(name) {
  const upper = name.toUpperCase();
  return LOCATION.includes(upper) || upper.startsWith('GIT_TRACE') || upper === 'GIT_TEST_FSMONITOR';
}

/** The environment a Git call runs with: the caller's, without its Git location and traces. */
export function environment(environ = process.env) {
  const env = {};
  for (const [k, v] of Object.entries(environ)) if (v !== undefined && !dropped(k)) env[k] = v;
  return Object.assign(env, TRACE_OFF, { GIT_OPTIONAL_LOCKS: '0' });
}

/** The argument list that runs Git in `folder` (null: no git), its own folder skipped as a source of git. */
export function command(folder, args, trees = null) {
  const git = executable(trees === null ? [folder] : trees);
  if (git === null) return null;
  return [git, ...NO_COMMANDS, '-C', String(folder), ...args];
}

/** spawnSync of Git in `folder` with this module's environment; null when no git is found. */
export function run(folder, args, options = {}) {
  const { trees = null, ...rest } = options;
  const argv = command(folder, args, trees);
  if (argv === null) return null;
  return spawnSync(argv[0], argv.slice(1), { env: environment(), ...rest });
}
