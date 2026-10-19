#!/usr/bin/env node
// Writes job-limit-vectors.json: jobs under limits and uncertain effects (DEC-0087, FAC-SEM-119/120), the contract's
// fixtures/vectors/job-limits.json and every fixtures/semantic/job-limits-*.json, each case answered again here by the
// contract's own functions in src/job-limits.ts (readJobPause, jobCallerAction, intentIdempotencyKey, readsNullUsage,
// usageFindings, jobLimitRules), so a stale copy is caught. Never written by hand. The kits' fabric_interop.py and
// fabric-interop.mjs are held to it.
//
//   node test/fixtures/contract/make_job_limit_vectors.mjs --contract <a clean checkout of the contract at the pin>
//     --contract-src <dir with its src/*.ts staged, .js imports rewritten to .ts> [--out test/fixtures/contract]
//
// Needs Node 24 or later (type stripping).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const out = args.out ?? here;
const limits = await import(pathToFileURL(path.join(args['contract-src'], 'job-limits.ts')).href);
const read = (file) => JSON.parse(fs.readFileSync(path.join(args.contract, file), 'utf8'));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const check = (group, c, actual, expected) => {
  if (!same(actual, expected)) throw new Error(`the contract's ${group} case "${c.name}" no longer answers as written`);
};

const vectors = read('fixtures/vectors/job-limits.json');
for (const c of vectors.pause) check('pause', c, limits.readJobPause(c.answer), c.expected);
for (const c of vectors.caller) check('caller', c, limits.jobCallerAction(c.answer, 'now' in c ? c.now : undefined), c.expected);
for (const c of vectors.key) check('key', c, limits.intentIdempotencyKey(c.intent) ?? null, c.expected);
for (const c of vectors.usage) check('usage', c, limits.usageFindings(c.usage, '').map((f) => `${f.code} ${f.instancePath}`), c.findings);
for (const c of vectors.reader) check('reader', c, limits.readsNullUsage(c.meta), c.expected);

// The semantic fixtures: kinds interop-job, usage and job-caller through jobLimitRules; kind result through the usage
// rule semanticRules adds for it (the other result rules are not DEC-0087's).
const dir = path.join(args.contract, 'fixtures/semantic');
const rules = fs.readdirSync(dir).filter((f) => f.startsWith('job-limits-') && f.endsWith('.json')).sort().map((file) => {
  const fixture = JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8'));
  const findings = fixture.kind === 'result' ? limits.usageFindings(fixture.input.usage, '/usage') : limits.jobLimitRules(fixture.kind, fixture.input);
  if (!Array.isArray(findings)) throw new Error(`${file}: kind ${fixture.kind} is not DEC-0087's`);
  if (!same([...new Set(findings.map((f) => f.code))].sort(), [...fixture.expect].sort())) throw new Error(`${file}: the contract's rules disagree with its expect`);
  return { name: file.replace(/\.json$/, ''), kind: fixture.kind, value: fixture.input, findings };
});

const document = { about: vectors.about, source: 'fixtures/vectors/job-limits.json and fixtures/semantic/job-limits-*.json', pause: vectors.pause, caller: vectors.caller, key: vectors.key, usage: vectors.usage, reader: vectors.reader, rules };
fs.writeFileSync(path.join(out, 'job-limit-vectors.json'), `${JSON.stringify(document, null, 2)}\n`);
console.log(`job-limit-vectors.json: ${vectors.pause.length} pause, ${vectors.caller.length} caller, ${vectors.key.length} key, ${vectors.usage.length} usage, ${vectors.reader.length} reader, ${rules.length} rule cases`);
