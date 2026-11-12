#!/usr/bin/env node
// Vendors the call queue and the load report of DEC-0104 (FAC-SEM-131, FAC-SEM-132, FAC-SEM-133) from the contract at
// the pin into load-vectors.json, every answer re-computed here by the contract's own functions in src/agent-network.ts,
// so a stale copy is caught. Never written by hand. The kits' fabric_load.py and fabric-load.mjs are held to it (FAA-289).
//
// - fixtures/vectors/agent-network.json: its `queue` (nextQueuedJob), `admit` (admitJob), `caller` (jobCallerKey) and
//   `position` (readQueuePosition) groups, each re-answered. Its directory groups are not the kit's.
// - status: queueStatusMessage over the cases below (the contract's vectors carry none).
// - fixtures/semantic/job-queue-*.json and service-load-*.json: the findings agentNetworkRules gives them (code,
//   instancePath and message); service-well-known-load-*.json: the findings loadExtensionRules gives them (code and
//   instancePath: the wording of a schema error is ajv's, not part of a vector, as in actions-vectors.json).
// - every catalogue fixture of service-load.schema.json and service-load-extension.schema.json, with its validity
//   re-checked by the contract's validator, and the kit's own hostile inputs below answered the same way.
//
// Run it under the contract's own tsx, on a clean tree of the contract at the pin (as vendor_vectors.mjs does):
//
//   git -C <contract> archive <pinned commit> | tar -x -C <tree> && ln -s <contract>/node_modules <tree>/node_modules
//   <contract>/node_modules/.bin/tsx test/fixtures/contract/make_load_vectors.mjs --contract <tree> --contract-src <tree>/src
//     [--out test/fixtures/contract/load-vectors.json]

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const out = args.out ?? path.join(here, 'load-vectors.json');
const src = (file) => import(pathToFileURL(path.join(args['contract-src'], file)).href);
const read = (file) => JSON.parse(fs.readFileSync(path.join(args.contract, file), 'utf8'));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const check = (group, c, actual, expected) => {
  if (!same(actual, expected)) throw new Error(`the contract's ${group} case "${c.name}" no longer answers as written`);
};

const net = await src('agent-network.ts');
const { EXTENSION_KEYS } = await src('extensions.ts');
const { createValidatorSync } = await src('validator.ts');
const { SCHEMA_PREFIX } = await src('contract.ts');
const validator = createValidatorSync();
const valid = (schema, document) => validator.getSchema(`${SCHEMA_PREFIX}schemas/${schema}`)(document) === true;
const KEY = EXTENSION_KEYS.load;
const nul = (value) => (value === undefined ? null : value);
const full = (findings) => findings.map(({ code, instancePath, message }) => ({ code, instancePath, message }));
const paths = (findings) => findings.map(({ code, instancePath }) => ({ code, instancePath }));

// The contract's own vectors, re-answered.
const vectors = read('fixtures/vectors/agent-network.json');
for (const c of vectors.queue) check('queue', c, nul(net.nextQueuedJob(c.queue, c.running, c.limits)), c.expected);
for (const c of vectors.admit) check('admit', c, net.admitJob(c.queue, c.running, c.job, c.limits, c.retryAfterSeconds), c.expected);
for (const c of vectors.caller) check('caller', c, nul(net.jobCallerKey(c.accepted, c.credential)), c.expected);
for (const c of vectors.position) check('position', c, nul(net.readQueuePosition(c.statusMessage)), c.expected);

// The kit's own cases, answered by the same functions.
const at = (s) => `2026-10-22T09:00:${String(s).padStart(2, '0')}Z`;
const L = { concurrency: 2, perCaller: 1, queueMax: 3 };
const queueExtra = [
  ['running that is not an array holds no slot', [{ id: 'j1', caller: 'a', at: at(1) }], { id: 'r' }, L],
  ['a running item that is not an object still holds a slot', [{ id: 'j1', caller: 'a', at: at(1) }], [7, 'x'], L],
  ['an id that is not a string is skipped', [{ id: 7, caller: 'a', at: at(1) }, { id: 'j2', caller: 'b', at: at(2) }], [], L],
  ['a caller that is not a string is skipped', [{ id: 'j1', caller: null, at: at(1) }, { id: 'j2', caller: 'b', at: at(2) }], [], L],
  ['four fraction digits are not a UTC instant', [{ id: 'j1', caller: 'a', at: '2026-10-22T09:00:01.0001Z' }, { id: 'j2', caller: 'b', at: at(2) }], [], L],
  ['three fraction digits order below the second', [{ id: 'j1', caller: 'a', at: '2026-10-22T09:00:01.500Z' }, { id: 'j2', caller: 'b', at: '2026-10-22T09:00:01.499Z' }], [], L],
  ['a day that does not exist is skipped', [{ id: 'j1', caller: 'a', at: '2026-02-30T09:00:01Z' }, { id: 'j2', caller: 'b', at: at(2) }], [], L],
  ['a leap second is skipped', [{ id: 'j1', caller: 'a', at: '2026-10-22T23:59:60Z' }, { id: 'j2', caller: 'b', at: at(2) }], [], L],
  ['an id tie breaks by UTF-16 code units, not code points', [{ id: '￿', caller: 'a', at: at(1) }, { id: '\u{1F600}', caller: 'b', at: at(1) }], [], L],
  ['fewest running wins over arrival', [{ id: 'j1', caller: 'a', at: at(1) }, { id: 'j2', caller: 'b', at: at(3) }, { id: 'j3', caller: 'c', at: at(2) }], [{ id: 'r1', caller: 'a' }, { id: 'r2', caller: 'b' }], { concurrency: 5, perCaller: 3, queueMax: 9 }],
  ['concurrency that is not an integer starts nothing', [{ id: 'j1', caller: 'a', at: at(1) }], [], { concurrency: 1.5, perCaller: 1, queueMax: 3 }],
  ['perCaller true starts nothing', [{ id: 'j1', caller: 'a', at: at(1) }], [], { concurrency: 1, perCaller: true, queueMax: 3 }],
  ['queueMax below zero starts nothing', [{ id: 'j1', caller: 'a', at: at(1) }], [], { concurrency: 1, perCaller: 1, queueMax: -1 }],
  ['limits that are not an object start nothing', [{ id: 'j1', caller: 'a', at: at(1) }], [], [2, 1, 3]],
  ['a queue that is not an array starts nothing', { id: 'j1', caller: 'a', at: at(1) }, [], L],
  ['non-object queue items are skipped', [null, 3, { id: 'j1', caller: 'a', at: at(1) }], [], L],
].map(([name, queue, running, limits]) => ({ name, queue, running, limits, expected: nul(net.nextQueuedJob(queue, running, limits)) }));

const admitExtra = [
  ['a job that is not an object is refused', [], [], 'jn', L, 30],
  ['a job without a caller is refused', [], [], { id: 'jn', at: at(9) }, L, 30],
  ['a retry-after of one second stays', [{ id: 'w1', caller: 'a', at: at(1) }], [{ id: 'r1', caller: 'a' }], { id: 'jn', caller: 'n', at: at(9) }, { concurrency: 1, perCaller: 1, queueMax: 1 }, 1],
  ['a retry-after of an hour stays', [{ id: 'w1', caller: 'a', at: at(1) }], [{ id: 'r1', caller: 'a' }], { id: 'jn', caller: 'n', at: at(9) }, { concurrency: 1, perCaller: 1, queueMax: 1 }, 3600],
  ['a fractional retry-after becomes 60', [{ id: 'w1', caller: 'a', at: at(1) }], [{ id: 'r1', caller: 'a' }], { id: 'jn', caller: 'n', at: at(9) }, { concurrency: 1, perCaller: 1, queueMax: 1 }, 1.5],
  ['a retry-after string becomes 60', [{ id: 'w1', caller: 'a', at: at(1) }], [{ id: 'r1', caller: 'a' }], { id: 'jn', caller: 'n', at: at(9) }, { concurrency: 1, perCaller: 1, queueMax: 1 }, '30'],
  ['a retry-after null becomes 60', [{ id: 'w1', caller: 'a', at: at(1) }], [{ id: 'r1', caller: 'a' }], { id: 'jn', caller: 'n', at: at(9) }, { concurrency: 1, perCaller: 1, queueMax: 1 }, null],
  ['the oldest waiter starts first and one already waits under queueMax 1: refused', [{ id: 'w1', caller: 'a', at: at(1) }], [], { id: 'jn', caller: 'n', at: at(9) }, { concurrency: 1, perCaller: 1, queueMax: 1 }, 30],
  ['the oldest waiter starts first and queueMax is 0: refused', [{ id: 'w1', caller: 'a', at: at(1) }], [], { id: 'jn', caller: 'n', at: at(9) }, { concurrency: 1, perCaller: 1, queueMax: 0 }, 30],
  ['an older newcomer would start at once', [{ id: 'w1', caller: 'a', at: at(5) }], [], { id: 'jn', caller: 'n', at: at(1) }, { concurrency: 1, perCaller: 1, queueMax: 0 }, 30],
].map(([name, queue, running, job, limits, retryAfterSeconds]) => ({ name, queue, running, job, limits, retryAfterSeconds, expected: net.admitJob(queue, running, job, limits, retryAfterSeconds) }));

const callerExtra = [
  ['a gate pass with principal null and a caller is no token', { ok: true, principal: null, caller: 'x' }, 'cred'],
  ['a chain that is not an array is no partner', { ok: true, principal: 'p', caller: 'c', chain: 'org:x' }, 'cred'],
  ['a chain of one organization is no partner', { ok: true, principal: 'p', caller: 'c', chain: ['org:x'] }, 'cred'],
  ['a chain whose last item is not a string is no partner', { ok: true, principal: 'p', caller: 'c', chain: ['w', 7] }, 'cred'],
  ['an organization with no id is still the last link', { ok: true, principal: 'p', caller: 'c', chain: ['w', 'org:'] }, 'cred'],
  ['an organization in the middle of the chain is no partner', { ok: true, principal: 'p', caller: 'c', chain: ['w', 'org:x', 'planner'] }, 'cred'],
  ['ok as a string is refused', { ok: 'true', principal: 'p', caller: 'c' }, 'cred'],
  ['a caller that is empty is refused', { ok: true, principal: 'p', caller: '' }, 'cred'],
  ['an accepted verdict that is not an object: the credential', 'verdict', 'cred'],
  ['an accepted array: the credential', ['ok'], 'cred'],
  ['a credential that is not a string', null, 7],
  ['a lone surrogate is written escaped', { ok: true, principal: '\ud800', caller: 'w ' }, 'cred'],
  ['a credential with quotes and a backslash', undefined, 'a"b\\c'],
].map(([name, accepted, credential]) => ({ name, ...(accepted === undefined ? {} : { accepted }), credential, expected: nul(net.jobCallerKey(accepted, credential)) }));

const positionExtra = [
  ['the largest length', 'queued 1 of 999999'],
  ['a length of seven digits', 'queued 1 of 1000000'],
  ['a full-width digit', 'queued １ of 3'],
  ['a trailing newline', 'queued 1 of 3\n'],
  ['a leading space', ' queued 1 of 3'],
  ['upper case', 'Queued 1 of 3'],
  ['two spaces', 'queued  1 of 3'],
  ['null', null],
].map(([name, statusMessage]) => ({ name, statusMessage, expected: nul(net.readQueuePosition(statusMessage)) }));
const position = [...vectors.position, ...positionExtra];

const status = [
  [1, 1], [1, 3], [3, 3], [0, 1], [2, 1], [999999, 999999], [1, 1000000], [1.5, 2], [1, 2.5], ['1', 2], [true, 2],
  [null, 1], [-1, 3], [2 ** 53, 2 ** 53], [1, -1],
].map(([p, l]) => ({ name: `${JSON.stringify(p)} of ${JSON.stringify(l)}`, position: p, length: l, expected: nul(net.queueStatusMessage(p, l)) }));
for (const c of status) if (c.expected !== null && !same(net.readQueuePosition(c.expected), { position: c.position, length: c.length })) throw new Error(`${c.name} does not read back`);

// Semantic fixtures.
const dir = path.join(args.contract, 'fixtures/semantic');
const rules = fs.readdirSync(dir).filter((f) => /^(job-queue|service-load|service-well-known-load)-.*\.json$/.test(f)).sort().map((file) => {
  const fixture = JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8'));
  const loadDoc = fixture.kind === 'service-well-known';
  const findings = loadDoc ? net.loadExtensionRules(fixture.input) : net.agentNetworkRules(fixture.kind, fixture.input);
  if (!Array.isArray(findings)) throw new Error(`${file}: kind ${fixture.kind} is not DEC-0104's`);
  if (!same([...new Set(findings.map((f) => f.code))].sort(), [...fixture.expect].sort())) throw new Error(`${file}: the contract's rules disagree with its expect`);
  return { name: file.replace(/\.json$/, ''), kind: fixture.kind, value: fixture.input, findings: loadDoc ? paths(findings) : full(findings) };
});

// The schemas: every catalogue fixture, and the kit's hostile inputs.
const catalogue = read('fixtures/catalogue.json');
const fromCatalogue = (schema) => catalogue.filter((e) => e.schema === schema).map((e) => ({ name: e.name, value: read(`fixtures/${e.path}`), valid: valid(schema, read(`fixtures/${e.path}`)), catalogue: e.valid }));
const declaration = read('fixtures/positive/service-load-extension.json');
const limits = declaration.limits;
const withValue = (patch) => ({ ...declaration, ...patch });
const withLimits = (patch) => withValue({ limits: { ...limits, ...patch } });
const declarationExtra = [
  ['not an object', 'load'], ['null', null], ['an array', [declaration]],
  ['no path', (({ path: _p, ...rest }) => rest)(declaration)], ['no limits', (({ limits: _l, ...rest }) => rest)(declaration)],
  ['an extra member', withValue({ note: 'x' })], ['a relative path', withValue({ path: 'load' })], ['the root path', withValue({ path: '/' })],
  ['a path with a space', withValue({ path: '/a b' })], ['a path with a no-break space', withValue({ path: '/a b' })],
  ['a path with a byte-order mark', withValue({ path: '/a﻿b' })], ['a path with a separator control', withValue({ path: '/a\u001cb' })],
  ['a path with a line separator', withValue({ path: '/a b' })], ['a path of 256 characters', withValue({ path: `/${'a'.repeat(255)}` })],
  ['a path of 257 characters', withValue({ path: `/${'a'.repeat(256)}` })], ['a path of 256 code points in astral characters', withValue({ path: `/${'\u{1F600}'.repeat(255)}` })],
  ['a path of 257 code points in astral characters', withValue({ path: `/${'\u{1F600}'.repeat(256)}` })], ['a path that is a number', withValue({ path: 7 })],
  ['windowSeconds 59', withValue({ windowSeconds: 59 })], ['windowSeconds 60', withValue({ windowSeconds: 60 })],
  ['windowSeconds 86400', withValue({ windowSeconds: 86400 })], ['windowSeconds 86401', withValue({ windowSeconds: 86401 })],
  ['windowSeconds 60.5', withValue({ windowSeconds: 60.5 })], ['windowSeconds a string', withValue({ windowSeconds: '3600' })],
  ['windowSeconds true', withValue({ windowSeconds: true })], ['limits not an object', withValue({ limits: [4, 2, 50] })],
  ['limits with an extra member', withLimits({ burst: 3 })], ['limits without queueMax', withValue({ limits: { concurrency: 4, perCaller: 2 } })],
  ['concurrency 1024', withLimits({ concurrency: 1024 })], ['concurrency 1025', withLimits({ concurrency: 1025 })],
  ['perCaller 0', withLimits({ perCaller: 0 })], ['perCaller 1.5', withLimits({ perCaller: 1.5 })],
  ['queueMax 0', withLimits({ queueMax: 0 })], ['queueMax 100000', withLimits({ queueMax: 100000 })],
  ['queueMax 100001', withLimits({ queueMax: 100001 })], ['queueMax -1', withLimits({ queueMax: -1 })],
  ['everything wrong at once', { path: '//x', windowSeconds: 1, limits: { concurrency: 0, perCaller: 0, queueMax: -1, x: 1 }, y: 2 }],
].map(([name, value]) => ({ name, value, valid: valid('service-load-extension.schema.json', value) }));
const declarations = [...fromCatalogue('service-load-extension.schema.json'), ...declarationExtra].map((c) => ({
  ...c, findings: paths(net.loadExtensionRules({ extensions: { [KEY]: c.value } })),
}));
const documents = [
  ['no extensions', {}], ['extensions not an object', { extensions: [KEY] }], ['another extension only', { extensions: { 'https://example.com/x': {} } }],
  ['the key with a valid value', { extensions: { [KEY]: declaration } }], ['the key with a null value', { extensions: { [KEY]: null } }],
].map(([name, value]) => ({ name, value, findings: paths(net.loadExtensionRules(value)) }));

const report = read('fixtures/positive/service-load.json');
const row = report.windows[0].byContext[0];
const withReport = (patch) => ({ ...report, ...patch });
const withRow = (patch) => withReport({ windows: [{ ...report.windows[0], byContext: [{ ...row, ...patch }] }] });
const minimalWindow = (i) => ({ start: new Date(Date.parse('2026-10-15T00:00:00Z') + i * 3600000).toISOString().replace('.000Z', 'Z'), byContext: [] });
const reportExtra = [
  ['not an object', []], ['the wrong type', withReport({ type: 'service-load/2' })], ['no windows', (({ windows: _w, ...rest }) => rest)(report)],
  ['windowSeconds 59', withReport({ windowSeconds: 59 })], ['windowSeconds a string', withReport({ windowSeconds: '3600' })],
  ['windows not an array', withReport({ windows: {} })], ['a window without byContext', withReport({ windows: [{ start: report.windows[0].start }] })],
  ['a window with an extra member', withReport({ windows: [{ ...report.windows[0], end: report.windows[0].start }] })],
  ['an organization without an id', withRow({ context: 'org:' })], ['a context in upper case', withRow({ context: 'Personal' })],
  ['a row without failed', withReport({ windows: [{ ...report.windows[0], byContext: [(({ failed: _f, ...rest }) => rest)(row)] }] })],
  ['a waitMs with an extra member', withRow({ waitMs: { p50: 1, p95: 2, p99: 3 } })], ['a negative p50', withRow({ waitMs: { p50: -1, p95: 2 } })],
  ['a fractional count', withRow({ completed: 1.5 })], ['a generatedAt that is no time', withReport({ generatedAt: 'now' })],
  ['a start with no day', withReport({ windows: [{ ...report.windows[0], start: '2026-02-30T09:00:00Z' }] })],
  ['168 windows', withReport({ windows: Array.from({ length: 168 }, (_, i) => minimalWindow(i)), generatedAt: '2026-10-22T11:05:00Z' })],
  ['169 windows', withReport({ windows: Array.from({ length: 169 }, (_, i) => minimalWindow(i)), generatedAt: '2026-10-22T11:05:00Z' })],
  ['65 rows in one window', withReport({ windows: [{ start: report.windows[0].start, byContext: Array.from({ length: 65 }, (_, i) => ({ ...row, context: `org:o${i}` })) }] })],
  ['equal percentiles', withRow({ waitMs: { p50: 5, p95: 5 } })], ['a run time after a failure only', withRow({ completed: 0, failed: 1 })],
  ['an unreadable windowSeconds blames every later window', { ...report, windowSeconds: 'x' }],
  ['an unreadable generatedAt flags no window as late', { ...report, generatedAt: 7 }],
  ['non-object windows are skipped and not counted', { ...report, windows: [7, ...report.windows] }],
  ['non-object rows are skipped and not counted', withReport({ windows: [{ start: report.windows[0].start, byContext: [null, row, row] }] })],
  ['percentiles that are not numbers are not compared', withRow({ waitMs: { p50: '9', p95: 1 } })],
  ['a run time with no counts at all', withRow({ completed: '0', failed: null })],
  ['a generatedAt with a space for T', withReport({ generatedAt: '2026-10-22 11:05:00Z' })],
  ['a generatedAt in lower case', withReport({ generatedAt: '2026-10-22t11:05:00z' })],
  ['a start at a leap second', withReport({ windows: [{ ...report.windows[0], start: '2026-10-21T23:59:60Z' }] })],
  ['a generatedAt without a zone', withReport({ generatedAt: '2026-10-22T11:05:00' })],
  ['an offset start in order', withReport({ windows: [{ ...report.windows[0], start: '2026-10-22T11:00:00+02:00' }, report.windows[1]] })],
].map(([name, value]) => ({ name, value, valid: valid('service-load.schema.json', value) }));
const reports = [...fromCatalogue('service-load.schema.json'), ...reportExtra].map((c) => ({ ...c, findings: full(net.agentNetworkRules('service-load', c.value ?? {}) ?? []) }));

const document = {
  about: 'The call queue and the load report of DEC-0104 at the pin: nextQueuedJob, admitJob, jobCallerKey, readQueuePosition and queueStatusMessage, FAC-SEM-131 and FAC-SEM-132 (code, instancePath, message), FAC-SEM-133 (code and instancePath), and the validity of service-load/1 and the load extension, each answered by the contract\'s functions and validator. Written by make_load_vectors.mjs, never by hand. expected is exactly what the reference returns, with null for undefined; a case without `accepted` passes none.',
  source: 'fixtures/vectors/agent-network.json, fixtures/semantic/{job-queue,service-load,service-well-known-load}-*.json, fixtures/catalogue.json, src/agent-network.ts',
  commit: '18f8d48762edc5bfb1433657cbfe1c16196df1a6',
  extensionKey: KEY,
  queue: [...vectors.queue, ...queueExtra],
  admit: [...vectors.admit, ...admitExtra],
  caller: [...vectors.caller, ...callerExtra],
  position,
  status,
  rules,
  declarations,
  documents,
  reports,
};
fs.writeFileSync(out, `${JSON.stringify(document, null, 2)}\n`);
console.log(`load-vectors.json: ${document.queue.length} queue, ${document.admit.length} admit, ${document.caller.length} caller, ${position.length} position, ${status.length} status, ${rules.length} rule, ${declarations.length} declaration, ${documents.length} document, ${reports.length} report cases`);
