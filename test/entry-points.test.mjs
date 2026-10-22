// A kit script started through a symlinked folder still runs its command line (board thread b42e16b7): the launcher
// installs the plugin under ~/.passioncode/current, a link, and a script that compared import.meta.url (resolved)
// with process.argv[1] (the link) printed nothing and exited 0, so a check that measured nothing read as passed.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scripts = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'plugins', 'fabric-agent-adapter', 'skills',
  'building-fabric-services', 'scripts');

function linked(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'entry-points-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const current = path.join(dir, 'current');
  try {
    fs.symlinkSync(scripts, current, 'dir');
  } catch (err) {
    t.skip(`this host cannot make a symlink: ${err.code}`);
    return null;
  }
  return current;
}

const run = (script, ...args) => spawnSync(process.execPath, [script, ...args], { encoding: 'utf8', timeout: 60_000 });

test('check_dashboard_layout.mjs runs through a symlinked folder', (t) => {
  const current = linked(t);
  if (!current) return;
  const r = run(path.join(current, 'check_dashboard_layout.mjs'));
  assert.equal(r.status, 2, 'a usage error, not a silent exit 0: ' + r.stdout + r.stderr);
  assert.notEqual(r.stdout + r.stderr, '');
});

test('fabric-package.mjs runs through a symlinked folder', (t) => {
  const current = linked(t);
  if (!current) return;
  const r = run(path.join(current, 'fabric-package.mjs'), 'pack', path.join(os.tmpdir(), 'no-such-folder-entry-points'));
  assert.equal(r.status, 1, 'the refusal, not a silent exit 0: ' + r.stdout + r.stderr);
});

test('a layout report with no rule in it is not a pass', () => {
  const source = `import { report } from ${JSON.stringify(path.join(scripts, 'check_dashboard_layout.mjs'))};
process.exitCode = report([], { json: true }, 'x') === 0 ? 9 : 0;`;
  const r = spawnSync(process.execPath, ['--input-type=module', '-e', source], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stdout + r.stderr);
});
