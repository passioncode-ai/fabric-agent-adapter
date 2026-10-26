#!/usr/bin/env node
// Vendors DEC-0123's page links (PL-1 to PL-4, FAC-SEM-143) from the contract at the pin into page-link-vectors.json,
// every answer re-computed here by the contract's own functions so a stale copy is caught. Never written by hand.
//
// - fixtures/vectors/page-links.json: `builds` (dashboardsLink, null where it refuses), `links` (the kind page-link,
//   pageLinkRules) and `requests` (the kind interop-input-requests, inputRequestLinkFindings), each checked against the
//   contract's own `expected` and written with the findings' codes, instance paths and messages; each link also with
//   parseDashboardsLink's answer and isLoopbackPageUrl's.
// - the grammar's constants (MAX_PAGE_PATH_LENGTH, MAX_PAGE_LINK_LENGTH and the SERVICE_ID, INSTANCE and ORIGIN_PATH
//   patterns as JavaScript writes them).
//
//   node test/fixtures/contract/make_page_link_vectors.mjs --contract <a clean checkout of the contract at the pin>
//     --contract-src <dir with its src/*.ts staged, .js imports rewritten to .ts>
//     [--out test/fixtures/contract/page-link-vectors.json] [--extra test/fixtures/kit-page-link-inputs.json]
//
// With --extra, the kit's own inputs (decision D11 of the 0.51.0 brief: the WHATWG URL points the Python port reads by
// hand) are answered by the same functions into page-link-extra-vectors.json beside --out. "@SK@" in an input stands for
// a provider-key-shaped sample built here from parts, so no key-shaped literal sits in the inputs. Needs Node 24 or later
// (type stripping).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const out = args.out ?? path.join(here, 'page-link-vectors.json');
const src = (file) => import(pathToFileURL(path.join(args['contract-src'], file)).href);
const read = (file) => JSON.parse(fs.readFileSync(path.join(args.contract, file), 'utf8'));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const rules = await src('page-link-rules.ts');
const { dashboardsLink, parseDashboardsLink, isLoopbackPageUrl, pageLinkRules, inputRequestLinkFindings } = rules;
const build = ({ service, instance, path: page }) => {
  try {
    return dashboardsLink(service, instance, page === null ? undefined : page);
  } catch {
    return null;
  }
};
const findings = (list) => list.map((f) => ({ code: f.code, instancePath: f.instancePath, message: f.message }));
const link = (url) => findings(pageLinkRules('page-link', { url }) ?? []);
const request = (value) => findings(inputRequestLinkFindings(value));
const paths = (list) => list.map((f) => f.instancePath);

const vectors = read('fixtures/vectors/page-links.json');
const builds = vectors.builds.map((c) => {
  const got = build(c.input);
  if (got !== c.expected) throw new Error(`the contract's build "${c.name}" no longer answers as written`);
  return c;
});
const links = vectors.links.map((c) => {
  const got = link(c.input.url);
  if (!same(paths(got), c.expected)) throw new Error(`the contract's link "${c.name}" no longer answers as written`);
  if (got.some((f) => f.code !== 'FAC-SEM-143')) throw new Error(`the contract's link "${c.name}" reports another code`);
  return { ...c, findings: got, parsed: parseDashboardsLink(c.input.url), loopback: isLoopbackPageUrl(c.input.url) };
});
const requests = vectors.requests.map((c) => {
  const got = request(c.input);
  if (!same(paths(got), c.expected)) throw new Error(`the contract's request "${c.name}" no longer answers as written`);
  return { ...c, findings: got };
});
const constants = {
  MAX_PAGE_PATH_LENGTH: rules.MAX_PAGE_PATH_LENGTH, MAX_PAGE_LINK_LENGTH: rules.MAX_PAGE_LINK_LENGTH,
  SERVICE_ID: rules.SERVICE_ID.source, INSTANCE: rules.INSTANCE.source, ORIGIN_PATH: rules.ORIGIN_PATH.source,
};
fs.writeFileSync(out, `${JSON.stringify({
  about: "DEC-0123 (PL-1 to PL-4, FAC-SEM-143) at the pin: fixtures/vectors/page-links.json's builds, links and requests, each re-answered by the contract's dashboardsLink, pageLinkRules ('page-link') and inputRequestLinkFindings, with the findings' codes, instance paths and messages, and for each link parseDashboardsLink's and isLoopbackPageUrl's answers. Written by make_page_link_vectors.mjs, never by hand.",
  source: 'fixtures/vectors/page-links.json, src/page-link-rules.ts', constants, builds, links, requests,
}, null, 1)}\n`);
console.log(`${builds.length} builds, ${links.length} links, ${requests.length} requests`);

if (args.extra) {
  const SK = ['sk', '-', 'A1'.repeat(12)].join('');
  const expand = (value) => (typeof value === 'string' ? value.replaceAll('@SK@', SK)
    : Array.isArray(value) ? value.map(expand)
      : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([k, v]) => [k, expand(v)])) : value);
  const extra = expand(JSON.parse(fs.readFileSync(args.extra, 'utf8')));
  const extraBuilds = extra.builds.map(({ name, input }) => ({ name, input, expected: build(input) }));
  const parses = extra.parses.map(({ name, input }) => ({ name, input, expected: parseDashboardsLink(input.url) }));
  const loopback = extra.loopback.map(({ input }) => ({ input, expected: isLoopbackPageUrl(input.url) }));
  const extraLinks = extra.links.map(({ name, input }) => ({ name, input, expected: link(input.url) }));
  const extraRequests = extra.requests.map(({ name, input }) => ({ name, input, expected: request(input) }));
  fs.writeFileSync(path.join(path.dirname(out), 'page-link-extra-vectors.json'), `${JSON.stringify({
    about: "The kit's inputs (test/fixtures/kit-page-link-inputs.json, \"@SK@\" expanded), each answered by the contract's dashboardsLink (null where it refuses), parseDashboardsLink, isLoopbackPageUrl, pageLinkRules ('page-link', findings with code, instance path and message) and inputRequestLinkFindings at the pin. Never written by hand.",
    builds: extraBuilds, parses, loopback, links: extraLinks, requests: extraRequests,
  }, null, 1)}\n`);
  console.log(`${extraBuilds.length} kit builds, ${parses.length} kit parses, ${loopback.length} kit loopback cases, ${extraLinks.length} kit links, ${extraRequests.length} kit requests`);
}
