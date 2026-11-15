// FAA-190: the Node twin of fabric_git.py, held to the same rules as test_fabric_git.py: git from no folder inside the
// tree it reads, both fsmonitors off, the caller's Git location and traces not passed.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import * as fg from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-git.mjs';

const posix = process.platform !== 'win32';

function withPath(value, fn) {
  const saved = process.env.PATH;
  process.env.PATH = value;
  try {
    return fn();
  } finally {
    if (saved === undefined) delete process.env.PATH; else process.env.PATH = saved;
  }
}

test('a git in a folder inside the tree it reads is skipped', { skip: !posix }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-git-'));
  try {
    const tree = path.join(tmp, 'tree');
    const inner = path.join(tree, 'node_modules', '.bin');
    const outer = path.join(tmp, 'bin');
    for (const dir of [inner, outer]) {
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, 'git'), '#!/bin/sh\nexit 0\n', { mode: 0o755 });
    }
    withPath([inner, outer, 'relative', ''].join(path.delimiter), () => {
      assert.equal(fg.executable([tree]), path.join(outer, 'git'));
      assert.equal(fg.executable(), path.join(inner, 'git'));
      assert.equal(fg.command(tree, ['status'])[0], path.join(outer, 'git'));
    });
    withPath(['relative', ''].join(path.delimiter), () => assert.equal(fg.executable([tree]), null));
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('the environment drops the location and the traces, and every call turns both fsmonitors off', () => {
  const caller = { GIT_AUTHOR_NAME: 'Example', GIT_TRACE: '/tmp/t', git_trace2_event: '/tmp/e', GIT_TEST_FSMONITOR: 'x' };
  for (const name of fg.LOCATION) caller[name] = '/elsewhere';
  const env = fg.environment(caller);
  assert.deepEqual(Object.keys(env).filter((k) => fg.LOCATION.includes(k.toUpperCase())), []);
  assert.deepEqual(Object.keys(env).filter((k) => k.toUpperCase().startsWith('GIT_TRACE')).sort(),
    ['GIT_TRACE2', 'GIT_TRACE2_EVENT', 'GIT_TRACE2_PERF']);
  assert.equal(env.GIT_TEST_FSMONITOR, undefined);
  assert.equal(env.GIT_OPTIONAL_LOCKS, '0');
  assert.equal(env.GIT_AUTHOR_NAME, 'Example');
  const argv = fg.command(os.tmpdir(), ['ls-files'], []);
  if (argv !== null) {
    assert.deepEqual(argv.slice(1), [...fg.NO_COMMANDS, '-C', os.tmpdir(), 'ls-files']);
  }
});

test('a run reads its own repository under an exported GIT_DIR', { skip: !posix || spawnSync('git', ['--version']).status !== 0 }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-git-run-'));
  const saved = process.env.GIT_DIR;
  try {
    const repo = path.join(tmp, 'repo');
    const other = path.join(tmp, 'other');
    for (const dir of [repo, other]) spawnSync('git', ['init', '-q', dir], { env: fg.environment() });
    spawnSync('git', ['-C', repo, 'config', 'remote.origin.url', 'git@github.com:example/example-agent.git'], { env: fg.environment() });
    process.env.GIT_DIR = path.join(other, '.git');
    const done = fg.run(repo, ['config', '--get', 'remote.origin.url'], { encoding: 'utf8' });
    assert.equal(done.stdout.trim(), 'git@github.com:example/example-agent.git');
  } finally {
    if (saved === undefined) delete process.env.GIT_DIR; else process.env.GIT_DIR = saved;
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
