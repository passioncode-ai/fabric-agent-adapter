#!/usr/bin/env node
// Vendors the contract's fixtures/vectors/connections.json (DEC-0096, fabric-connections/0.1), every case re-answered
// here by the contract's own connectionsView so a stale copy is caught. Never written by hand.
//
//   node test/fixtures/contract/make_connections_vectors.mjs --contract <a clean checkout of the contract at the pin>
//     --contract-src <dir with its src/*.ts staged, .js imports rewritten to .ts, beside a node_modules that holds ajv>
//     [--out test/fixtures/contract/connections-vectors.json] [--extra test/fixtures/kit-connections-inputs.json]
//
// With --extra, the kit's own inputs are answered by the same connectionsView into connections-extra-vectors.json beside
// --out, so both twins are held to the reference beyond the contract's cases.
//
// Needs Node 24 or later (type stripping). The reference's `errors` wording is not part of a vector.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const out = args.out ?? path.join(here, 'connections-vectors.json');
const { connectionsView } = await import(pathToFileURL(path.join(args['contract-src'], 'connections.ts')).href);
const vectors = JSON.parse(fs.readFileSync(path.join(args.contract, 'fixtures/vectors/connections.json'), 'utf8'));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
for (const c of vectors.cases) {
  // A case names only the members it holds the reader to (a reported case leaves `connections` out).
  const view = connectionsView(c.input);
  const answer = Object.fromEntries(Object.keys(c.expected).map((key) => [key, view[key]]));
  if (!same(answer, c.expected)) throw new Error(`the contract's connections case "${c.name}" no longer answers as written`);
}
fs.writeFileSync(out, `${JSON.stringify({ ...vectors, source: 'fixtures/vectors/connections.json' }, null, 2)}\n`);

if (args.extra) {
  const extra = JSON.parse(fs.readFileSync(args.extra, 'utf8'));
  const cases = extra.inputs.map((input) => {
    const { declared, reported, connections } = connectionsView(input);
    return { input, expected: { declared, reported, connections } };
  });
  fs.writeFileSync(path.join(path.dirname(out), 'connections-extra-vectors.json'),
    `${JSON.stringify({ about: 'The kit\'s inputs (test/fixtures/kit-connections-inputs.json), each answered by the contract\'s connectionsView at the pin. Never written by hand.', cases }, null, 1)}\n`);
}
