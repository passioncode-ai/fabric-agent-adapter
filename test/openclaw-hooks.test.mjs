import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import plugin, { createPlugin } from '../plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/hosts/openclaw/index.mjs';

function register(reader, config) {
  const hooks = [];
  createPlugin(reader).register({ config, on: (...args) => hooks.push(args) });
  assert.equal(hooks.length, 1);
  assert.equal(hooks[0][0], 'before_prompt_build');
  return hooks[0][1];
}

test('OpenClaw native entry and manifests agree without conversation or tool hooks', () => {
  const base = new URL('../plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/hosts/openclaw/', import.meta.url);
  const manifest = JSON.parse(fs.readFileSync(new URL('openclaw.plugin.json', base)));
  const metadata = JSON.parse(fs.readFileSync(new URL('package.json', base)));
  assert.equal(manifest.id, plugin.id);
  assert.equal(manifest.activation.onStartup, true);
  assert.deepEqual(metadata.openclaw.extensions, ['./index.mjs']);
  assert.equal(manifest.configSchema.additionalProperties, false);
});

test('OpenClaw passes host workspace only and contributes context without replacing prompt', async () => {
  const calls = [];
  const handler = register(async (...args) => { calls.push(args); return 'Fabric context'; });
  const event = Object.freeze({ messages: Object.freeze(['private conversation']), prompt: 'user prompt' });
  let checked = 0;
  const result = await handler(event, { workspaceDir: '/example/project', hookInvocation: { assertActive() { checked++; } } });
  assert.deepEqual(calls, [['openclaw', '/example/project', {}]]);
  assert.deepEqual(result, { prependContext: 'Fabric context' });
  assert.equal(checked, 1);
  assert.equal(event.prompt, 'user prompt');
});

test('OpenClaw skips malformed or missing workspace without invoking helper', async () => {
  let calls = 0;
  const handler = register(async () => { calls++; return ''; });
  for (const ctx of [undefined, null, {}, { workspaceDir: '' }, { workspaceDir: '  ' }, { workspaceDir: 3 }]) {
    assert.equal(await handler({}, ctx), undefined);
  }
  assert.equal(calls, 0);
});

test('OpenClaw failure and empty helper output are harmless', async () => {
  for (const reader of [async () => { throw new Error('private failure'); }, async () => '', async () => ' ', async () => null]) {
    assert.equal(await register(reader)({}, { workspaceDir: '/example/project' }), undefined);
  }
});

test('OpenClaw discards a result whose host invocation has expired', async () => {
  const handler = register(async () => 'stale context');
  assert.equal(await handler({}, {
    workspaceDir: '/example/project',
    hookInvocation: { assertActive() { throw new Error('expired'); } },
  }), undefined);
});

test('OpenClaw rereads each current workspace without retaining another session context', async () => {
  const handler = register(async (_host, cwd) => cwd);
  assert.deepEqual(await handler({}, { workspaceDir: '/example/first' }), { prependContext: '/example/first' });
  assert.deepEqual(await handler({}, { workspaceDir: '/example/second' }), { prependContext: '/example/second' });
});

test('OpenClaw forwards only enabled named MCP registration as a boolean', async () => {
  for (const name of ['fabric', 'fabric-mcp']) {
    const calls = [];
    const config = { mcp: { servers: { [name]: { command: 'fabric-mcp', env: { TOKEN: 'test-secret' } } } } };
    const handler = register(async (...args) => { calls.push(args); return 'context'; }, config);
    await handler({}, { workspaceDir: '/example/project' });
    assert.deepEqual(calls, [['openclaw', '/example/project', { fabricRegistered: true }]]);
    assert.equal(JSON.stringify(calls).includes('test-secret'), false);
    config.mcp.servers[name].enabled = false;
    await handler({}, { workspaceDir: '/example/project' });
    assert.deepEqual(calls[1][2], {});
  }
});

test('OpenClaw malformed, disabled and unrelated MCP entries do not imply Fabric registration', async () => {
  for (const servers of [null, [], { fabric: true }, { fabric: {} }, { fabric: { command: '' } },
    { fabric: { url: 'https://example.invalid/mcp', enabled: false } }, { other: { command: 'fabric-mcp' } }]) {
    const calls = [];
    const handler = register(async (_host, _cwd, options) => { calls.push(options); return ''; }, { mcp: { servers } });
    await handler({}, { workspaceDir: '/example/project' });
    assert.deepEqual(calls, [{}]);
  }
});

test('OpenClaw runs the helper once per workspace and registration, not per prompt (FAA-69)', async () => {
  const calls = [];
  let fail = true;
  const handler = register(async (...args) => {
    calls.push(args);
    if (fail) { fail = false; throw new Error('first run fails'); }
    return 'context for ' + args[1];
  });
  assert.equal(await handler({}, { workspaceDir: '/example/one' }), undefined, 'a failure is not kept');
  for (let n = 0; n < 3; n++) {
    assert.deepEqual(await handler({}, { workspaceDir: '/example/one' }), { prependContext: 'context for /example/one' });
  }
  assert.deepEqual(await handler({}, { workspaceDir: '/example/two' }), { prependContext: 'context for /example/two' });
  assert.deepEqual(calls.map(c => c[1]), ['/example/one', '/example/one', '/example/two']);
});
