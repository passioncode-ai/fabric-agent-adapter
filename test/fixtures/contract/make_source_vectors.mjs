#!/usr/bin/env node
// Vendors the agent source rules of DEC-0149 (fabric-source/1, FAC-SEM-156 to 160) from the contract at the pin into
// source-vectors.json, every answer re-computed here by the contract's own functions in src/source-rules.ts, so a
// stale copy is caught. Never written by hand. The adapter's port, fabric_source_tree.py, is held to it (FAA-261).
//
// - fixtures/vectors/source-tree.json: its `constants`, its `tree` cases (sourceTreeProblems) and its `patches` cases
//   (patchPathsAllowed), each re-answered and checked against the answer the contract wrote.
// - fixtures/semantic/source-manifest-*.json and source-package-*.json: the findings sourceRules gives them (code and
//   instancePath; the wording is the contract's, not part of a vector).
//
// Run it under the contract's own tsx, on a clean tree of the contract at the pin (as vendor_vectors.mjs does):
//
//   git -C <contract> archive <pinned commit> | tar -x -C <tree> && ln -s <contract>/node_modules <tree>/node_modules
//   <contract>/node_modules/.bin/tsx test/fixtures/contract/make_source_vectors.mjs --contract <tree> --contract-src <tree>/src
//     [--out test/fixtures/contract/source-vectors.json]

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const out = args.out ?? path.join(here, 'source-vectors.json');
const pin = JSON.parse(fs.readFileSync(path.join(here, '../../../fabric-contract.lock.json'), 'utf8')).commit;
const src = (file) => import(pathToFileURL(path.join(args['contract-src'], file)).href);
const read = (file) => JSON.parse(fs.readFileSync(path.join(args.contract, file), 'utf8'));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const rules = await src('source-rules.ts');
const vectors = read('fixtures/vectors/source-tree.json');
const tree = vectors.tree.map((c) => {
  const expected = rules.sourceTreeProblems(c.input);
  if (!same(expected, c.expected)) throw new Error(`the contract's tree case "${c.name}" no longer answers as written`);
  return { name: c.name, input: c.input, expected };
});
const patches = vectors.patches.map((c) => {
  const expected = rules.patchPathsAllowed(c.input.manifest, c.input.paths);
  if (!same(expected, c.expected)) throw new Error(`the contract's patch case "${c.name}" no longer answers as written`);
  return { name: c.name, input: c.input, expected };
});
const semantic = (prefix, kind) => fs.readdirSync(path.join(args.contract, 'fixtures/semantic')).filter((f) => f.startsWith(prefix)).sort().map((f) => {
  const fixture = read(`fixtures/semantic/${f}`);
  const findings = rules.sourceRules(kind, fixture.input).map((x) => ({ code: x.code, instancePath: x.instancePath }));
  if (!same(findings.map((x) => x.code), fixture.expect)) throw new Error(`the contract's fixture ${f} no longer answers as it expects`);
  return { name: f, input: fixture.input, expected: findings };
});
const doc = {
  about: `The agent source rules of DEC-0149 at the pin, each answered by the contract's src/source-rules.ts: constants (the block a port holds equal), tree (sourceTreeProblems, as fixtures/vectors/source-tree.json documents it), patches (patchPathsAllowed), manifest (sourceRules('source-manifest'): FAC-SEM-156 and FAC-SEM-157, code and instancePath) and package (sourceRules('source-package'): FAC-SEM-160). Written by make_source_vectors.mjs, never by hand. The contract's own description of the tree cases: ${vectors.about}`,
  contract: pin,
  constants: vectors.constants,
  manifest: vectors.manifest,
  tree,
  patches,
  manifests: semantic('source-manifest-', 'source-manifest'),
  packages: semantic('source-package-', 'source-package'),
};
fs.writeFileSync(out, `${JSON.stringify(doc, null, 2)}\n`);
console.log(`wrote ${path.relative(process.cwd(), out)}: ${tree.length} tree, ${patches.length} patch, ${doc.manifests.length} manifest and ${doc.packages.length} package cases`);
