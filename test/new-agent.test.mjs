// The npm CLI's `new` (FAA-270): one command creates an agent project with the contract built in, through the skill's
// own new_agent.py; the last stdout line is JSON, a repeat changes nothing and a folder holding other files is refused.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { tempDir } from './temp-dir.mjs';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const cli = path.join(root, 'bin', 'fabric-agent-adapter.js');
const python = process.platform === 'win32' ? ['py', ['-3']] : ['python3', []];
const hasPython = spawnSync(python[0], [...python[1], '--version']).status === 0;
const run = (...args) => spawnSync(process.execPath, [cli, 'new', ...args], { encoding: 'utf8', timeout: 120_000 });
const last = (out) => JSON.parse(out.trim().split('\n').at(-1));

test('new makes an agent project, answers JSON last and repeats without a change', { skip: !hasPython && 'needs Python 3' }, () => {
  const folder = path.join(tempDir('new-agent-'), 'example-agent');
  const made = run(folder, '--id', 'example-agent');
  assert.equal(made.status, 0, made.stderr);
  const answer = last(made.stdout);
  assert.equal(answer.id, 'example-agent');
  assert.equal(answer.repeated, false);
  for (const file of ['fabric-agent.json', 'fabric-contract.lock.json', 'fabric.source.json', 'src/placement.py']) {
    assert.ok(answer.created.includes(file), file);
    assert.ok(fs.statSync(path.join(folder, file)).isFile(), file);
  }
  const source = JSON.parse(fs.readFileSync(path.join(folder, 'fabric.source.json'), 'utf8'));
  assert.equal(source.format, 'fabric-source/1');
  const lock = JSON.parse(fs.readFileSync(path.join(folder, 'fabric-contract.lock.json'), 'utf8'));
  const pin = JSON.parse(fs.readFileSync(path.join(root, 'fabric-contract.lock.json'), 'utf8'));
  assert.equal(lock.commit, pin.commit);
  const again = run(folder, '--id', 'example-agent', '--json');
  assert.equal(again.status, 0, again.stderr);
  assert.deepEqual(last(again.stdout), { ...answer, created: [], repeated: true });
  const other = run(folder, '--id', 'other-agent');
  assert.equal(other.status, 1);
  assert.match(other.stderr, /not empty/);
});
