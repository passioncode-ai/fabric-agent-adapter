import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, mkdir, writeFile, copyFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readContext } from '../plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/hosts/context.mjs';

const source = new URL('../plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/hosts/', import.meta.url);
async function fixture(t, python = "print('[fabric-agent-adapter] fixture context')") {
  const root = await mkdtemp(join(tmpdir(), 'fabric-host-test-'));
  t.after(() => rm(root, {recursive:true, force:true}));
  await mkdir(join(root, 'hosts/opencode'), {recursive:true});
  await mkdir(join(root, 'hosts/pi'), {recursive:true});
  for (const path of ['context.mjs', 'opencode/fabric.mjs', 'pi/fabric.mjs']) {
    await copyFile(new URL(path, source), join(root, 'hosts', path));
  }
  await writeFile(join(root, 'fabric_session.py'), python);
  return {root, script:join(root,'fabric_session.py'), load: host => import(pathToFileURL(join(root,'hosts',host,'fabric.mjs')).href)};
}

test('helper sends only cwd and affirmative registration as JSON without shell interpolation', async t => {
  const f = await fixture(t, "import json,sys\np=json.load(sys.stdin)\nassert sys.argv[1:]==['hook','session-start','--host','pi']\nassert p=={'cwd':'/example/$safe path','fabric_registered':True}\nprint('context')");
  assert.equal(await readContext('pi','/example/$safe path',{script:f.script,fabricRegistered:true}), 'context');
});
test('helper ignores nonzero stdout, missing executable and missing script', async t => {
  const f = await fixture(t, "import sys\nprint('untrusted')\nsys.exit(1)");
  assert.equal(await readContext('pi','/example',{script:f.script}), '');
  assert.equal(await readContext('pi','/example',{python:join(f.root,'missing')}), '');
  assert.equal(await readContext('pi','/example',{script:join(f.root,'missing')}), '');
});
test('helper bounds hung and oversized child output', async t => {
  const f = await fixture(t, 'import time\ntime.sleep(10)');
  const start=Date.now();
  assert.equal(await readContext('pi','/example',{script:f.script,timeoutMs:50}), '');
  assert.ok(Date.now()-start<2000);
  await writeFile(f.script,"print('x'*100000)");
  assert.equal(await readContext('opencode','/example',{script:f.script}), '');
});
test('helper rejects invalid host, cwd, and nontext/control output', async t => {
  const f = await fixture(t, "print('bad\\x1b[31m')");
  assert.equal(await readContext('pi','/example',{script:f.script}), '');
  assert.equal(await readContext('unknown','/example',{script:f.script}), '');
  assert.equal(await readContext('pi',null,{script:f.script}), '');
});
test('OpenCode preserves other system context and does not duplicate', async t => {
  const f=await fixture(t); const mod=await f.load('opencode');
  assert.deepEqual(Object.keys(mod),['default']);
  const hook=await mod.default({directory:f.root});
  const output={system:['existing']};
  await hook['experimental.chat.system.transform']({},output);
  await hook['experimental.chat.system.transform']({},output);
  assert.deepEqual(output.system,['existing','[fabric-agent-adapter] fixture context']);
});
test('OpenCode malformed host output and missing context are harmless', async t => {
  const f=await fixture(t,'raise RuntimeError("fixture failure")');
  const hooks=await (await f.load('opencode')).default({directory:f.root});
  await hooks['experimental.chat.system.transform']({},{});
  const output={system:['existing']};
  await hooks['experimental.chat.system.transform']({},output);
  assert.deepEqual(output.system,['existing']);
});
async function piHandler(f, tools) {
  const handlers=new Map(); const mod=await f.load('pi');
  assert.deepEqual(Object.keys(mod),['default']);
  mod.default({on:(event,handler)=>handlers.set(event,handler),getAllTools:()=>tools});
  assert.deepEqual([...handlers.keys()],['before_agent_start']);
  return handlers.get('before_agent_start');
}
test('Pi uses one structured section without replacing other sections', async t => {
  const f=await fixture(t); const handler=await piHandler(f);
  const event={systemPrompt:'base',systemPromptOptions:{sections:{other:'kept'}}};
  await handler(event,{cwd:f.root}); await handler(event,{cwd:f.root});
  assert.deepEqual(event.systemPromptOptions.sections,{other:'kept',fabric_agent_adapter:'[fabric-agent-adapter] fixture context'});
  assert.equal(event.systemPrompt,'base');
});
test('Pi preserves earlier forced prompt and appends context once', async t => {
  const f=await fixture(t); const handler=await piHandler(f);
  const event={systemPrompt:'base',systemPromptOptions:{forceSystemPrompt:'forced',sections:{}}};
  await handler(event,{cwd:f.root}); await handler(event,{cwd:f.root});
  assert.equal(event.systemPromptOptions.forceSystemPrompt,'forced\n\n[fabric-agent-adapter] fixture context');
});
test('Pi legacy prompt result preserves text and suppresses repeated injection', async t => {
  const f=await fixture(t); const handler=await piHandler(f);
  const result=await handler({systemPrompt:'base'},{cwd:f.root});
  assert.equal(result.systemPrompt,'base\n\n[fabric-agent-adapter] fixture context');
  assert.equal(await handler({systemPrompt:result.systemPrompt},{cwd:f.root}),undefined);
});
test('Pi context failure leaves prompt untouched', async t => {
  const f=await fixture(t,'raise RuntimeError("fixture failure")'); const handler=await piHandler(f);
  const event={systemPrompt:'base',systemPromptOptions:{sections:{other:'kept'}}};
  assert.equal(await handler(event,{cwd:f.root}),undefined);
  assert.deepEqual(event.systemPromptOptions.sections,{other:'kept'});
});
test('service-only context is also deduplicated without a preamble marker', async t => {
  const f=await fixture(t,"print('Fabric on this machine: fixture services')");
  const hooks=await (await f.load('opencode')).default({directory:f.root});
  const output={system:['existing']};
  await hooks['experimental.chat.system.transform']({},output);
  await hooks['experimental.chat.system.transform']({},output);
  assert.equal(output.system.length,2);
  const handler=await piHandler(f);
  const result=await handler({systemPrompt:'base'},{cwd:f.root});
  assert.equal(await handler({systemPrompt:result.systemPrompt},{cwd:f.root}),undefined);
  const event={systemPrompt:'base',systemPromptOptions:{forceSystemPrompt:'forced',sections:{}}};
  await handler(event,{cwd:f.root});await handler(event,{cwd:f.root});
  assert.equal(event.systemPromptOptions.forceSystemPrompt,'forced\n\nFabric on this machine: fixture services');
});
const registrationProbe = "import json,sys\np=json.load(sys.stdin)\nprint('[fabric-agent-adapter] registered='+str(p.get('fabric_registered') is True))";
test('OpenCode registration follows resolved config and excludes disabled or malformed servers', async t => {
  const f=await fixture(t,registrationProbe);
  const hooks=await (await f.load('opencode')).default({directory:f.root});
  for (const [entry,expected] of [
    [{type:'local',command:['fabric-mcp'],enabled:true},true],
    [{type:'remote',url:'http://127.0.0.1/example'},true],
    [{type:'local',command:['fabric-mcp'],enabled:false},false],
    [{type:'local',command:[]},false],
    [undefined,false],
  ]) {
    await hooks.config({mcp:{fabric:entry}});
    const output={system:[]};await hooks['experimental.chat.system.transform']({},output);
    assert.deepEqual(output.system,['[fabric-agent-adapter] registered='+ (expected?'True':'False')]);
  }
});
test('Pi registration uses exact callable tool names only', async t => {
  const f=await fixture(t,registrationProbe);
  for(const [tools,expected] of [
    [[{name:'fabric_whoami'}],true],
    [[{name:'mcp__fabric__fabric_whoami'}],true],
    [[{name:'mcp__fabric__fabric_whoami',exposure:'hidden'}],false],
    [[{name:'other_fabric_whoami'},{name:'mcp__other__fabric_whoami'}],false],
    [[],false],[undefined,false],
  ]) {
    const handler=await piHandler(f,tools);
    const event={systemPrompt:'base',systemPromptOptions:{sections:{}}};
    await handler(event,{cwd:f.root});
    assert.equal(event.systemPromptOptions.sections.fabric_agent_adapter,'[fabric-agent-adapter] registered='+ (expected?'True':'False'));
  }
});

// Optional real host loaders. No provider, credentials, ambient plugins or MCPs.
test('native Pi loader accepts adapter and injects fixture context', {skip:!process.env.FAA_PI_LOADER}, async t => {
  const f=await fixture(t);
  const {loadExtensions}=await import(pathToFileURL(process.env.FAA_PI_LOADER).href);
  const shim=join(f.root,'fabric-agent-adapter.js');
  await writeFile(shim,`export { default } from ${JSON.stringify(pathToFileURL(join(f.root,'hosts/pi/fabric.mjs')).href)};\n`);
  const loaded=await loadExtensions([shim],f.root);
  assert.deepEqual(loaded.errors,[]);
  assert.equal(loaded.extensions.length,1);
  const handlers=loaded.extensions[0].handlers.get('before_agent_start');
  assert.equal(handlers.length,1);
  const event={systemPrompt:'base',systemPromptOptions:{sections:{existing:'kept'}}};
  await handlers[0](event,{cwd:f.root});
  assert.equal(event.systemPromptOptions.sections.fabric_agent_adapter,'[fabric-agent-adapter] fixture context');
});
test('native OpenCode initializes shim without a provider request', {skip:!process.env.FAA_OPENCODE_BIN}, async t => {
  const f=await fixture(t);
  const config=join(f.root,'config/opencode');
  await mkdir(join(config,'plugins'),{recursive:true});
  await mkdir(join(config,'node_modules'));
  // The pure-JS adapter imports no SDK. Satisfy bootstrap's dependency declaration
  // check without installing an unused package or contacting a registry.
  await writeFile(join(config,'package.json'),JSON.stringify({dependencies:{'@opencode-ai/plugin':'1.19.0'}}));
  await writeFile(join(config,'package-lock.json'),JSON.stringify({lockfileVersion:3,packages:{'':{dependencies:{'@opencode-ai/plugin':'1.19.0'}}}}));
  const receipt=join(f.root,'native-receipt.json');
  await writeFile(join(config,'plugins/fabric-agent-adapter.js'),`export { default } from ${JSON.stringify(pathToFileURL(join(f.root,'hosts/opencode/fabric.mjs')).href)};\n`);
  await writeFile(join(config,'plugins/fabric-probe.js'),`import factory from ${JSON.stringify(pathToFileURL(join(f.root,'hosts/opencode/fabric.mjs')).href)};
import {writeFileSync} from 'node:fs';
export default async function(input) {
  const hooks=await factory(input);
  return {...hooks,config:async()=>{
    const output={system:['existing']};
    await hooks['experimental.chat.system.transform']({},output);
    await hooks['experimental.chat.system.transform']({},output);
    writeFileSync(${JSON.stringify(receipt)},JSON.stringify(output));
  }};
}`);
  const env={PATH:process.env.PATH,HOME:join(f.root,'home'),XDG_CONFIG_HOME:join(f.root,'config'),
    XDG_DATA_HOME:join(f.root,'data'),XDG_CACHE_HOME:join(f.root,'cache'),XDG_STATE_HOME:join(f.root,'state'),
    OPENCODE_DISABLE_DEFAULT_PLUGINS:'1',OPENCODE_DISABLE_AUTOUPDATE:'1',OPENCODE_DISABLE_MODELS_FETCH:'1',
    OPENCODE_DISABLE_PROJECT_CONFIG:'1',OPENCODE_DISABLE_PRUNE:'1',
    OPENCODE_CONFIG_CONTENT:'{"mcp":{},"provider":{},"share":"disabled"}'};
  await mkdir(env.HOME);
  const result=await promisify(execFile)(process.env.FAA_OPENCODE_BIN,['debug','config','--print-logs'],{cwd:f.root,env,timeout:35000,maxBuffer:1024*1024});
  assert.doesNotMatch(result.stderr,/failed to load plugin|Failed to load plugin/);
  const {readFile}=await import('node:fs/promises');
  assert.deepEqual(JSON.parse(await readFile(receipt,'utf8')),{system:['existing','[fabric-agent-adapter] fixture context']});
});
