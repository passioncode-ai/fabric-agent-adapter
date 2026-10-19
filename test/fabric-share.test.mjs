// Share grants into an organization and their registrations (contract DEC-0086; FAA-54) in the Node kit, the twin of
// test_fabric_share.py, held to the contract's cases as share-vectors.json vendors them.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-share.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const V = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/share-vectors.json'), 'utf8'));
const SCHEMA = JSON.parse(fs.readFileSync(path.join(here, '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/share-registration.schema.json'), 'utf8'));

test('every grant id and org context case', () => {
  for (const c of V.grantId) assert.equal(k.isShareGrantId(c.value), c.ok, c.name);
  for (const c of V.orgContext) assert.equal(k.isOrgContext(c.value), c.ok, String(c.value));
});

test('every rule and attribution case answers as the contract does', () => {
  for (const c of V.rules) assert.deepEqual(k.shareRules(c.kind, c.value), c.expected, c.name);
  for (const c of V.attribution) assert.deepEqual(k.shareRules('device-attribution', c.value), c.expected, c.name);
  assert.equal(k.shareRules('estate-record', {}), undefined);
});

test('the vendored schema agrees with the kit', () => {
  assert.equal(SCHEMA.$defs.shareGrantId.pattern, k.SHARE_GRANT_ID.source);
  assert.equal(SCHEMA.$defs.orgContextId.pattern, k.ORG_CONTEXT.source);
});
