// FAA-268: the dashboard-only recipe's Node installer, the twin of install.py (test/test_recipe_dashboard_only.py
// compares the two). A repeat changes nothing and answers the same line; a refused install writes nothing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const recipe = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'plugins', 'fabric-agent-adapter', 'skills',
  'building-fabric-services', 'recipes', 'dashboard-only');
const REPO = 'https://github.com/example/dashboard';

function scratch(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dashboard-only-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return { services: path.join(dir, 'services'), folder: path.join(dir, 'folder'), dir };
}

const run = (s, ...extra) => spawnSync(process.execPath, [path.join(recipe, 'install.mjs'), '--id', 'example-dashboard',
  '--folder', s.folder, '--services-dir', s.services, ...extra], { encoding: 'utf8', timeout: 60000 });

test('a repeat changes nothing and answers the same line', (t) => {
  const s = scratch(t);
  const first = run(s, '--repository', REPO);
  assert.equal(first.status, 0, first.stderr);
  const lines = first.stdout.trim().split('\n');
  const line = JSON.parse(lines.at(-1));
  assert.deepEqual(Object.keys(line), ['descriptor', 'key', 'port']);
  assert.equal(line.key, 'example-dashboard.default');
  const before = [fs.readFileSync(line.descriptor, 'utf8'), fs.statSync(line.descriptor).mtimeMs];
  const second = run(s, '--json');
  assert.equal(second.status, 0, second.stderr);
  assert.deepEqual(second.stdout.trim().split('\n'), [lines.at(-1)]);
  assert.deepEqual([fs.readFileSync(line.descriptor, 'utf8'), fs.statSync(line.descriptor).mtimeMs], before);
  const d = JSON.parse(before[0]);
  assert.equal(d.origin, `http://127.0.0.1:${line.port}`);
  assert.equal(d.installedBy.tool, 'dashboard-only install 0.1.0');
  if (process.platform !== 'win32') assert.equal(fs.statSync(path.join(s.folder, 'service.token')).mode & 0o777, 0o600);
});

test('a refused install writes nothing, and usage is exit 2', (t) => {
  const s = scratch(t);
  const refused = run(s);
  assert.equal(refused.status, 1);
  assert.match(refused.stderr, /source\.repository/);
  assert.equal(fs.existsSync(s.folder), false);
  assert.equal(run(s, '--repository', REPO).status, 0);
  const other = spawnSync(process.execPath, [path.join(recipe, 'install.mjs'), '--id', 'example-dashboard', '--folder',
    path.join(s.dir, 'elsewhere'), '--services-dir', s.services], { encoding: 'utf8' });
  assert.equal(other.status, 1);
  assert.match(other.stderr, /is installed with the folder/);
  assert.equal(run(s, '--nope').status, 2);
  assert.equal(spawnSync(process.execPath, [path.join(recipe, 'install.mjs')], { encoding: 'utf8' }).status, 2);
});

test('a port another descriptor claims is refused by the kit', (t) => {
  const s = scratch(t);
  fs.mkdirSync(s.services, { recursive: true });
  fs.writeFileSync(path.join(s.services, 'other.default.json'), JSON.stringify({ id: 'other', instance: 'default', origin: 'http://127.0.0.1:47999' }));
  const refused = run(s, '--repository', REPO, '--port', '47999');
  assert.equal(refused.status, 1);
  assert.match(refused.stderr, /already claimed by other\.default/);
  assert.equal(fs.existsSync(s.folder), false);
  assert.deepEqual(fs.readdirSync(s.services), ['other.default.json']);
});
