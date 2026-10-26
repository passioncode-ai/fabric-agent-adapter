// A service's pages as Fabric Dashboards' open_link (contract DEC-0123, PL-1 to PL-4, FAC-SEM-143; FAA-132) in the Node
// kit, the twin of test_fabric_page_links.py, held to page-link-vectors.json and page-link-extra-vectors.json.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-page-links.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (file) => JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract', file), 'utf8'));
const V = read('page-link-vectors.json');
const X = read('page-link-extra-vectors.json');
const build = ({ service, instance, path: page }) => {
  try {
    return k.dashboardsLink(service, instance, page === null ? undefined : page);
  } catch (error) {
    assert.ok(error instanceof k.PageLinkError, String(error));
    return null;
  }
};

test('the constants are the contract\'s', () => {
  assert.equal(k.MAX_PAGE_PATH_LENGTH, V.constants.MAX_PAGE_PATH_LENGTH);
  assert.equal(k.MAX_PAGE_LINK_LENGTH, V.constants.MAX_PAGE_LINK_LENGTH);
  assert.equal(k.SERVICE_ID.source, V.constants.SERVICE_ID);
  assert.equal(k.INSTANCE.source, V.constants.INSTANCE);
  assert.equal(k.ORIGIN_PATH.source, V.constants.ORIGIN_PATH);
});

test('every contract build, link and request answers as the contract does', () => {
  for (const c of V.builds) assert.equal(build(c.input), c.expected, c.name);
  for (const c of V.links) {
    assert.deepEqual(k.pageLinkRules('page-link', { url: c.input.url }), c.findings, c.name);
    assert.deepEqual(k.parseDashboardsLink(c.input.url), c.parsed, c.name);
    assert.equal(k.isLoopbackPageUrl(c.input.url), c.loopback, c.name);
  }
  for (const c of V.requests) assert.deepEqual(k.inputRequestLinkFindings(c.input), c.findings, c.name);
  assert.equal(k.pageLinkRules('estate-record', { url: 'http://127.0.0.1/' }), undefined);
});

test('every kit input (D11) answers as the reference does', () => {
  for (const c of X.builds) assert.equal(build(c.input), c.expected, c.name);
  for (const c of X.parses) assert.deepEqual(k.parseDashboardsLink(c.input.url), c.expected, c.name);
  for (const c of X.loopback) assert.equal(k.isLoopbackPageUrl(c.input.url), c.expected, JSON.stringify(c.input.url));
  for (const c of X.links) assert.deepEqual(k.pageLinkFindings(c.input.url, '/url', 'the link'), c.expected, c.name);
  for (const c of X.requests) assert.deepEqual(k.inputRequestLinkFindings(c.input), c.expected, c.name);
});

test('a refused build names every problem', () => {
  assert.throws(() => k.dashboardsLink('A', 'B', 'relative'), (error) => error instanceof k.PageLinkError
    && error.message === 'the service is not a service id; the instance is not an instance name; the path is not a path on the service origin');
});
