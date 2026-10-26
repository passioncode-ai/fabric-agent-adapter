#!/usr/bin/env node
// Vendors the operator's mandate, mandate/1 (DEC-0125, FAC-SEM-144), from the contract at the pin into
// mandate-vectors.json, every answer re-computed here by the contract's own functions so a stale copy is caught. Never
// written by hand.
//
// - fixtures/vectors/mandate.json: its `cases` (mandateCovers) and its `handOn` group (handOn: {mandate} or
//   {refused: <problem>}, DEC-0136 MD-2a), each re-answered.
// - every catalogue fixture of mandate.schema.json (positive/mandate.json, negative/mandate-*.json) with its validity
//   re-checked by the contract's validator and FAC-SEM-144's findings over it (mandateRules, kind `mandate`, checked
//   equal to what evaluateSemanticRules dispatches).
// - the action-call-mandate*.json semantic fixtures are actionDecision's and are vendored by make_actions_vectors.mjs.
//
//   tsx test/fixtures/contract/make_mandate_vectors.mjs --contract <a clean checkout of the contract at the pin>
//     --contract-src <dir with its src/*.ts staged, .js imports rewritten to .ts, beside a node_modules that holds ajv>
//     [--out test/fixtures/contract/mandate-vectors.json] [--extra test/fixtures/kit-mandate-inputs.json]
//
// With --extra, the kit's own inputs are answered by the same functions (mandateCovers, mandateProblem with
// FAC-SEM-144 and the validator, scopeWithin, effectiveScope, handOn and actionDecision) into mandate-extra-vectors.json
// beside --out, so both twins are held to the reference beyond the contract's cases. A handOn the reference refuses is
// written as {throws: <problem>}, the problem its message names. Runs under tsx, as vendor_vectors.mjs does: the
// semantic rules it loads hold TypeScript that Node's type stripping does not read.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const out = args.out ?? path.join(here, 'mandate-vectors.json');
const src = (file) => import(pathToFileURL(path.join(args['contract-src'], file)).href);
const read = (file) => JSON.parse(fs.readFileSync(path.join(args.contract, file), 'utf8'));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const { mandateCovers, mandateProblem, mandateRules, scopeWithin, effectiveScope, handOn, MANDATE_LIFETIME_SECONDS } = await src('mandate.ts');
const { actionDecision } = await src('actions.ts');
const { evaluateSemanticRules } = await src('semantic-rules.ts');
const { createValidatorSync } = await src('validator.ts');
const { SCHEMA_PREFIX } = await src('contract.ts');
const validator = createValidatorSync();
const valid = (document) => validator.getSchema(`${SCHEMA_PREFIX}schemas/mandate.schema.json`)(document) === true;
const findings = (document) => mandateRules('mandate', document).map((f) => ({ code: f.code, instancePath: f.instancePath, message: f.message }));
// The dispatcher answers a document that is not an object with FAC-SEM-000 before the rule; for an object it is the rule.
const dispatched = (document) => evaluateSemanticRules('mandate', document).map((f) => ({ code: f.code, instancePath: f.instancePath, message: f.message }));

const vectors = read('fixtures/vectors/mandate.json');
for (const c of vectors.cases) {
  if (!same(mandateCovers(c.input), c.expected)) throw new Error(`the contract's mandate case "${c.name}" no longer answers as written`);
}
const handOnAnswer = ({ mandate, callee, at, narrower }) => {
  try {
    return { mandate: handOn(mandate, callee, at, narrower) };
  } catch (error) {
    const problem = /: (mandate-[a-z-]+)$/.exec(error.message)?.[1];
    if (!problem) throw error;
    return { refused: problem };
  }
};
for (const c of vectors.handOn) {
  if (!same(handOnAnswer(c.input), c.expected)) throw new Error(`the contract's handOn case "${c.name}" no longer answers as written`);
}
const fixtures = read('fixtures/catalogue.json').filter((e) => e.schema === 'mandate.schema.json').map((e) => {
  const document = read(`fixtures/${e.path}`);
  if (valid(document) !== e.valid) throw new Error(`${e.path} is not ${e.valid ? 'valid' : 'invalid'} as the catalogue says`);
  if (!same(dispatched(document), findings(document))) throw new Error(`${e.path}: the dispatcher and mandateRules disagree`);
  return { name: e.name, valid: e.valid, document, problem: mandateProblem(document) ?? null, findings: findings(document) };
});

fs.writeFileSync(out, `${JSON.stringify({
  about: "mandate/1 (DEC-0125, DEC-0126, DEC-0136) at the pin: mandateCovers' cases and handOn's cases (fixtures/vectors/mandate.json) and every mandate.schema.json fixture as fixtures/catalogue.json lists it, with its validity, mandateProblem's answer and FAC-SEM-144's findings, each answered by the contract's functions and validator. Written by make_mandate_vectors.mjs, never by hand.",
  source: 'fixtures/vectors/mandate.json, fixtures/catalogue.json, fixtures/positive/mandate.json, fixtures/negative/mandate-*.json, src/mandate.ts, src/semantic-rules.ts',
  lifetimeSeconds: MANDATE_LIFETIME_SECONDS,
  cases: vectors.cases, handOn: vectors.handOn, fixtures,
}, null, 1)}\n`);
console.log(`${vectors.cases.length} cases, ${vectors.handOn.length} handOn, ${fixtures.length} fixtures`);

if (args.extra) {
  const extra = JSON.parse(fs.readFileSync(args.extra, 'utf8'));
  const covers = extra.covers.map(({ name, input }) => ({ name, input, expected: mandateCovers(input) }));
  const documents = extra.documents.map(({ name, mandate }) => ({ name, mandate, valid: valid(mandate), problem: mandateProblem(mandate) ?? null, findings: findings(mandate) }));
  const scopes = extra.scopes.map(({ name, child, parent }) => ({ name, child, parent, within: scopeWithin(child, parent) }));
  const effective = extra.covers.filter(({ input }) => mandateProblem(input.mandate) === undefined)
    .map(({ name, input }) => ({ name, mandate: input.mandate, scope: effectiveScope(input.mandate) }));
  const handOns = extra.handOns.map(({ name, mandate, callee, at, narrower }) => {
    try {
      return { name, mandate, callee, at, ...(narrower ? { narrower } : {}), expected: handOn(mandate, callee, at, narrower) };
    } catch (error) {
      const problem = /: (mandate-[a-z-]+)$/.exec(error.message)?.[1];
      if (!problem) throw error;
      return { name, mandate, callee, at, ...(narrower ? { narrower } : {}), throws: problem };
    }
  });
  const decisions = extra.decisions.map(({ name, input }) => ({ name, input, expected: actionDecision(input) }));
  fs.writeFileSync(path.join(path.dirname(out), 'mandate-extra-vectors.json'), `${JSON.stringify({
    about: "The kit's inputs (test/fixtures/kit-mandate-inputs.json), each answered by the contract's mandateCovers, mandateProblem with its validator and FAC-SEM-144, scopeWithin, effectiveScope, handOn and actionDecision at the pin. Never written by hand.",
    covers, documents, scopes, effective, handOns, decisions,
  }, null, 1)}\n`);
  console.log(`${covers.length} kit covers, ${documents.length} kit documents, ${scopes.length} scopes, ${effective.length} effective scopes, ${handOns.length} hand-overs, ${decisions.length} decisions`);
}
