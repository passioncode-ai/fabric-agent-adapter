// DeepSeek Harness (dsh) Cordis plugin (FAA-370): a root agent's start gets the helper's context as one injected user
// message, a resumed agent nothing, and a failure never escapes the listener dsh awaits before the first turn.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, mkdir, writeFile, copyFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const source = new URL('../plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/hosts/', import.meta.url);

async function fixture(t, python) {
  const root = await mkdtemp(join(tmpdir(), 'fabric-dsh-test-'));
  t.after(() => rm(root, {recursive: true, force: true}));
  await mkdir(join(root, 'hosts/deepseek-harness'), {recursive: true});
  await copyFile(new URL('context.mjs', source), join(root, 'hosts/context.mjs'));
  await copyFile(new URL('deepseek-harness/fabric.mjs', source), join(root, 'hosts/deepseek-harness/fabric.mjs'));
  await writeFile(join(root, 'fabric_session.py'), python);
  const mod = await import(pathToFileURL(join(root, 'hosts/deepseek-harness/fabric.mjs')).href + '?' + Math.random());
  return {root, mod};
}

function host(cwd) {
  const listeners = {};
  const ctx = {
    on: (name, fn) => { listeners[name] = fn; },
    workingDirectory: {ensure: async () => cwd},
  };
  const injected = [];
  const agent = {inject: (message) => injected.push(message)};
  return {ctx, listeners, agent, injected};
}

test('the plugin exports what a Cordis plugin needs', async t => {
  const {mod} = await fixture(t, "print('x')");
  assert.equal(mod.name, 'fabric-agent-adapter');
  assert.deepEqual(mod.inject, ['workingDirectory']);
  assert.equal(typeof mod.apply, 'function');
});

test('a started root agent gets the context once, as a user message, with the helper told its host and cwd', async t => {
  const {root, mod} = await fixture(t,
    "import json,sys\np=json.load(sys.stdin)\nassert sys.argv[1:]==['hook','session-start','--host','deepseek-harness']\n" +
    "print('[fabric-agent-adapter] for '+p['cwd'])");
  const h = host(root);
  mod.apply(h.ctx);
  await h.listeners['agent/created']({agent: h.agent, source: 'startup'});
  assert.equal(h.injected.length, 1);
  assert.equal(h.injected[0].role, 'user');
  assert.deepEqual(h.injected[0].content, [{type: 'text', text: '[fabric-agent-adapter] for ' + root}]);
  assert.deepEqual(h.injected[0].source, {kind: 'fabric-agent-adapter'});
  assert.ok(Object.isFrozen(h.injected[0]));
});

test('a resumed agent, an empty answer and a failing helper inject nothing and throw nothing', async t => {
  for (const [python, source] of [["print('ctx')", 'resume'], ["", 'startup'], ["raise SystemExit(1)", 'startup']]) {
    const {root, mod} = await fixture(t, python);
    const h = host(root);
    mod.apply(h.ctx);
    await h.listeners['agent/created']({agent: h.agent, source});
    assert.equal(h.injected.length, 0, `${source} with ${JSON.stringify(python)}`);
  }
});

test('a host without a working directory or an agent without inject is harmless', async t => {
  const {mod} = await fixture(t, "print('ctx')");
  const listeners = {};
  mod.apply({on: (n, fn) => { listeners[n] = fn; }});
  await listeners['agent/created']({agent: {inject: () => { throw new Error('must not be called'); }}, source: 'startup'});
  await listeners['agent/created']({agent: {}, source: 'startup'});
  await listeners['agent/created'](undefined);
});

test('registration is read from the home layer: a dsh-mcp-client row named fabric, nothing else', async t => {
  const {root, mod} = await fixture(t, "print('x')");
  const home = join(root, 'dsh');
  await mkdir(home);
  assert.equal(await mod.fabricRegistered({DSH_HOME: home}), false, 'no layer');
  await writeFile(join(home, 'cordis.patch.yml'),
    "- insert:\n    - id: fabric-mcp\n      name: '@deepseek-ai/dsh-mcp-client'\n      config:\n        serverName: fabric\n");
  assert.equal(await mod.fabricRegistered({DSH_HOME: home}), true);
  await writeFile(join(home, 'cordis.patch.yml'),
    "- insert:\n    - id: other\n      name: '@deepseek-ai/dsh-mcp-client'\n      config:\n        serverName: fabric-dashboards\n");
  assert.equal(await mod.fabricRegistered({DSH_HOME: home}), false, 'another server name');
});
