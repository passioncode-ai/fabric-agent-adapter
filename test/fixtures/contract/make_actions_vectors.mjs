#!/usr/bin/env node
// Vendors fabric-actions/0.1 (DEC-0121, FAC-SEM-142) from the contract at the pin into actions-vectors.json, every answer
// re-computed here by the contract's own functions so a stale copy is caught. Never written by hand.
//
// - fixtures/vectors/actions.json: its `cases` (actionDecision) and `declarations` (the instance paths of
//   actionsExtensionRules' findings), each re-answered.
// - fixtures/semantic/action-call-*.json: the inputs, the service's `answer`, the answer actionDecision gives and the
//   instance paths of actionRules('action-call') over them.
// - fixtures/semantic/service-well-known-actions-*.json: the document, actionsView's declared/valid/actions and the
//   instance paths of actionsExtensionRules over it.
// - every catalogue fixture of decision.schema.json and service-actions-extension.schema.json, and
//   positive/service-well-known-actions.json, with its validity re-checked by the contract's validator.
//
//   node test/fixtures/contract/make_actions_vectors.mjs --contract <a clean checkout of the contract at the pin>
//     --contract-src <dir with its src/*.ts staged, .js imports rewritten to .ts, beside a node_modules that holds ajv>
//     [--out test/fixtures/contract/actions-vectors.json] [--extra test/fixtures/kit-actions-inputs.json]
//
// With --extra, the kit's own inputs are answered by the same functions into actions-extra-vectors.json beside --out,
// so both twins are held to the reference beyond the contract's cases. Needs Node 24 or later (type stripping). The
// wording of actionsView's `errors` is not part of a vector (decision D6 of the 0.50.0 brief).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const out = args.out ?? path.join(here, 'actions-vectors.json');
const src = (file) => import(pathToFileURL(path.join(args['contract-src'], file)).href);
const read = (file) => JSON.parse(fs.readFileSync(path.join(args.contract, file), 'utf8'));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const { actionDecision, actionsView, actionsExtensionRules, actionRules } = await src('actions.ts');
const { createValidatorSync } = await src('validator.ts');
const { SCHEMA_PREFIX } = await src('contract.ts');
const validator = createValidatorSync();
const valid = (schema, document) => validator.getSchema(`${SCHEMA_PREFIX}schemas/${schema}`)(document) === true;
const paths = (findings) => findings.map((f) => f.instancePath);
const view = (document) => {
  const { declared, valid: ok, actions } = actionsView(document);
  return ok === undefined ? { declared } : (actions === undefined ? { declared, valid: ok } : { declared, valid: ok, actions });
};

const vectors = read('fixtures/vectors/actions.json');
for (const c of vectors.cases) {
  if (!same(actionDecision(c.input), c.expected)) throw new Error(`the contract's actions case "${c.name}" no longer answers as written`);
}
for (const c of vectors.declarations) {
  if (!same(paths(actionsExtensionRules(c.input)), c.findings)) throw new Error(`the contract's declaration "${c.name}" no longer answers as written`);
}

const semanticDir = path.join(args.contract, 'fixtures/semantic');
const semanticFiles = (pattern) => fs.readdirSync(semanticDir).filter((f) => pattern.test(f)).sort();
const actionCalls = semanticFiles(/^action-call-.*\.json$/).map((file) => {
  const fixture = read(`fixtures/semantic/${file}`);
  const { answer, ...inputs } = fixture.input;
  const findings = actionRules('action-call', fixture.input);
  if (!same([...new Set(findings.map((f) => f.code))], fixture.expect)) throw new Error(`${file}: the findings are not the fixture's expect`);
  return { name: file.replace(/\.json$/, ''), description: fixture.description, inputs, answer, expected: actionDecision(inputs), findings: paths(findings) };
});
const wellKnowns = semanticFiles(/^service-well-known-actions-.*\.json$/).map((file) => {
  const fixture = read(`fixtures/semantic/${file}`);
  const findings = actionsExtensionRules(fixture.input);
  if (same(findings.length > 0, fixture.expect.includes('FAC-SEM-142')) === false) throw new Error(`${file}: FAC-SEM-142 is not the fixture's expect`);
  return { name: file.replace(/\.json$/, ''), description: fixture.description, document: fixture.input, view: view(fixture.input), findings: paths(findings) };
});

const SCHEMAS = ['decision.schema.json', 'service-actions-extension.schema.json'];
const fixtures = read('fixtures/catalogue.json')
  .filter((e) => SCHEMAS.includes(e.schema) || e.path === 'positive/service-well-known-actions.json')
  .map((e) => {
    const document = read(`fixtures/${e.path}`);
    if (valid(e.schema, document) !== e.valid) throw new Error(`${e.path} is not ${e.valid ? 'valid' : 'invalid'} as the catalogue says`);
    return { name: e.name, schema: e.schema, valid: e.valid, document };
  });

fs.writeFileSync(out, `${JSON.stringify({
  about: "fabric-actions/0.1 (DEC-0121) at the pin: actionDecision's cases, FAC-SEM-142 over declarations (instance paths), the action-call and service-well-known-actions semantic fixtures, and every decision and service-actions-extension fixture as fixtures/catalogue.json lists it, each answered by the contract's functions and validator. Written by make_actions_vectors.mjs, never by hand.",
  source: 'fixtures/vectors/actions.json, fixtures/semantic/action-call-*.json, fixtures/semantic/service-well-known-actions-*.json, fixtures/catalogue.json, src/actions.ts',
  cases: vectors.cases, declarations: vectors.declarations, actionCalls, wellKnowns, fixtures,
}, null, 1)}\n`);
console.log(`${vectors.cases.length} cases, ${vectors.declarations.length} declarations, ${actionCalls.length} action calls, ${wellKnowns.length} well-known documents, ${fixtures.length} fixtures`);

if (args.extra) {
  const extra = JSON.parse(fs.readFileSync(args.extra, 'utf8'));
  const decisions = extra.decisions.map(({ name, input }) => ({ name, input, expected: actionDecision(input) }));
  const documents = extra.wellKnowns.map(({ name, document }) => ({ name, document, view: view(document), findings: paths(actionsExtensionRules(document)) }));
  const shapes = extra.decisionShapes.map(({ name, document }) => ({ name, document, valid: valid('decision.schema.json', document) }));
  fs.writeFileSync(path.join(path.dirname(out), 'actions-extra-vectors.json'), `${JSON.stringify({
    about: "The kit's inputs (test/fixtures/kit-actions-inputs.json), each answered by the contract's actionDecision, actionsView, actionsExtensionRules and its validator at the pin. Never written by hand.",
    decisions, documents, shapes,
  }, null, 1)}\n`);
  console.log(`${decisions.length} kit decisions, ${documents.length} kit documents, ${shapes.length} kit decision shapes`);
}
