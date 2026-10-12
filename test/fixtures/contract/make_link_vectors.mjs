#!/usr/bin/env node
// Writes fabric-links.json: `fabric://` link cases (DEC-0040, FL-1…FL-6) whose expected answers come from the
// contract's own parseFabricLink and buildFabricLink at the pin — never written by hand. The dashboard kit's
// button (FB-7) builds and checks its links with a port of them; its test reads this file.
//
//   node test/fixtures/contract/make_link_vectors.mjs --contract-src <dir with fabric-links.ts, secret-shape.ts,
//     findings.ts> --semantic <contract>/fixtures/semantic [--out test/fixtures/contract/fabric-links.json]

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const links = await import(pathToFileURL(path.join(args['contract-src'], 'fabric-links.ts')).href);
const jwt = 'eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl';
const urls = [
  'fabric://chat?service=example-agent.default&project=project-a',
  'fabric://chat?project=urn%3Aproject%3Aa',
  'fabric://CHAT?service=example-agent',
  'FABRIC://chat?service=example-agent',
  'fabric://chat?service=example-agent&access_token=abc',
  'fabric://chat?service=example-agent&note=Bearer%20abc',
  'fabric://chat?service=example-agent&service=other-agent',
  'fabric://chat?service=example-agent&session_id=abc',
  'fabric://chat?service=example-agent&token=abc',
  'fabric://chat?service=example-agent&zipcode=1',
  'fabric://chat?service=Example%20Agent',
  'fabric://chat',
  'fabric://chat/?project=project-a&utm_source=dashboard&theme=ocean#top',
  'fabric://session/new?project=..%2Fetc',
  'fabric://session/new?project=a',
  'fabric://session/new?project=a&api_key=abc',
  'fabric://session/new?project=a&code=f3a9c1',
  'fabric://session/new?project=a&runner=Claude',
  'fabric://session/new?project=urn%3Aproject%3Aa&runner=claude-code',
  'fabric://session/new?runner=codex',
  'fabric://tasks/new?project=a',
  'fabric://user@chat?service=example-agent',
  `fabric://chat?service=example-agent&ref=${jwt}`,
  `fabric://chat?service=example-agent&x=${'a'.repeat(2048)}`,
  'fabric://chat?service=example-agent&refreshToken=x',
  'fabric://chat?service=example-agent&apiKeys=x',
  'fabric://chat?service=example-agent&initialPrompt=hello',
  'fabric://chat?service=example-agent#access_token=abc',
  'fabric://chat?service=example-agent#auth-settings',
  'fabric://chat?service=example-agent&ref=Zk9y+ZXRUaGlzSXNBU2VjcmV0S2V5MTIzNDU2Nzg5MA+abc',
  'fabric://chat?service=example-agent&commit=0123456789abcdef0123456789abcdef01234567',
  'fabric://chat?service=example-agent&key=',
  'fabric://session/new?project=project-a&runner=claude-code&runner=codex',
];
for (const file of fs.readdirSync(args.semantic).filter((f) => f.startsWith('deep-link-')).sort()) {
  urls.push(JSON.parse(fs.readFileSync(path.join(args.semantic, file), 'utf8')).url);
}
const parse = urls.map((url) => ({ url, expected: links.parseFabricLink(url) }));
const builds = [
  { action: 'chat', service: 'example-agent.default', project: 'project-a' },
  { action: 'chat', service: 'example-agent' },
  { action: 'chat', project: 'urn:project:a' },
  { action: 'session.new', project: 'project-a', runner: 'claude-code' },
  { action: 'session.new', project: 'project-a' },
  { action: 'chat' },
  { action: 'chat', service: 'Example Agent' },
  { action: 'session.new', project: 'a b' },
  { action: 'session.new', project: 'Zk9yZ2V0VGhpc0lzQVNlY3JldEtleTEyMzQ1Njc4OTA' },
].map((link) => { try { return { link, expected: links.buildFabricLink(link) }; } catch (error) { return { link, throws: true }; } });
const out = args.out ?? path.join(here, 'fabric-links.json');
fs.writeFileSync(out, `${JSON.stringify({ about: "fabric:// link cases; expected answers from the contract's parseFabricLink and buildFabricLink at the pin (make_link_vectors.mjs). Do not edit by hand.", parse, build: builds }, null, 1)}\n`);
console.log(`wrote ${out}: ${parse.length} parse, ${builds.length} build cases`);
