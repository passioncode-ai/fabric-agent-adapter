#!/usr/bin/env node
// Vendors extensions/channel-agent/0.1 (DEC-0150, FAC-SEM-162 to 165) from the contract at the pin, byte for byte:
// fixtures/vectors/channel-agent.json as channel-agent-vectors.json and schemas/service-channel-agent-extension.schema.json
// under its own name, here and beside the probe (building-fabric-services/scripts, which reads it at run time). Before it
// writes, every declaration is answered again by the contract's channelAgentRules (and channelAgentView where the vector
// carries `view`), so a stale copy is caught. channel-agent.source.json records the commit and each file's sha256, which
// test/test_check_service_channel_agent.py holds to fabric-contract.lock.json and to the bytes. Never written by hand.
//
//   node test/fixtures/contract/make_channel_agent_vectors.mjs --contract <a clean checkout of the contract at the pin>
//     --contract-src <dir with its src/*.ts staged, .js imports rewritten to .ts, beside a node_modules that holds ajv>
//     [--out test/fixtures/contract]
//
// Needs Node 24 or later (type stripping).

import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const out = args.out ?? here;
const scripts = path.join(here, '../../../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts');
const src = (file) => import(pathToFileURL(path.join(args['contract-src'], file)).href);
const raw = (file) => fs.readFileSync(path.join(args.contract, file));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const pin = JSON.parse(fs.readFileSync(path.join(here, '../../../fabric-contract.lock.json'), 'utf8')).commit;
const head = execFileSync('git', ['-C', args.contract, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
if (head !== pin) throw new Error(`the contract checkout is at ${head}, the pin is ${pin}`);

const { channelAgentRules, channelAgentView } = await src('channel-agent.ts');
const vectorsBytes = raw('fixtures/vectors/channel-agent.json');
const schemaBytes = raw('schemas/service-channel-agent-extension.schema.json');
const vectors = JSON.parse(vectorsBytes.toString('utf8'));
for (const d of vectors.declarations) {
  const input = d.input !== undefined ? d.input : JSON.parse(d.inputText);
  const findings = channelAgentRules(input, d.site).map(({ code, instancePath }) => ({ code, instancePath }));
  if (!same(findings, d.findings)) throw new Error(`the contract's declaration "${d.name}" no longer answers as written`);
  if (d.view !== undefined) {
    const view = channelAgentView(input, d.site);
    if (!same(Object.fromEntries(Object.keys(d.view).map((k) => [k, view[k]])), d.view)) throw new Error(`the view of "${d.name}" no longer answers as written`);
  }
}

const sha = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');
fs.writeFileSync(path.join(out, 'channel-agent-vectors.json'), vectorsBytes);
fs.writeFileSync(path.join(out, 'service-channel-agent-extension.schema.json'), schemaBytes);
fs.writeFileSync(path.join(scripts, 'service-channel-agent-extension.schema.json'), schemaBytes);
fs.writeFileSync(path.join(out, 'channel-agent.source.json'), `${JSON.stringify({
  about: 'extensions/channel-agent/0.1 (DEC-0150) vendored byte for byte by make_channel_agent_vectors.mjs, each declaration answered again by the contract at the commit. Never written by hand.',
  commit: pin,
  files: {
    'channel-agent-vectors.json': { source: 'fixtures/vectors/channel-agent.json', sha256: sha(vectorsBytes) },
    'service-channel-agent-extension.schema.json': { source: 'schemas/service-channel-agent-extension.schema.json', sha256: sha(schemaBytes) },
  },
}, null, 2)}\n`);
console.log(`${vectors.declarations.length} declarations, the schema, at ${pin}`);
