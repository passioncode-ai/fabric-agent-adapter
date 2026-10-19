// Share grants into an organization and their registrations (contract DEC-0086), the Node kit; the twin of
// fabric_share.py, answer for answer (test/fixtures/contract/share-vectors.json). Node built-ins only.
// FAC-SEM-117 (a share grant's id, window and agentRef, with parent), FAC-SEM-118 (a share-registration/1 document) and
// FAC-SEM-045's DEC-0086 clause (a grant.usage carries its grant's own org: context). Deriving, deciding and joining
// registrations belong to the sharer's node and the organization server, not to this kit. Every function answers and
// never throws on malformed input. Normative source: the contract's src/share-registration.ts.
// #region share-kit-node, docs: plugins/fabric-agent-adapter/skills/building-fabric-services/references/estate-record.md#share-grants-into-an-organization

import { estateTime, grantContextFindings } from './fabric-estate.mjs';
import { sameIdentifier } from './fabric-identifiers.mjs';

export const SHARE_REGISTRATION_TYPE = 'share-registration/1';
export const SHARE_REGISTRATION_RECEIPT_TYPE = 'share-registration-receipt/1';
export const SHARE_GRANT_ID = /^urn:fabric:share:(?!0{32}$)[0-9a-f]{32}$/;
export const ORG_CONTEXT = /^org:[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
const INSTANT = /^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-5][0-9](?:\.[0-9]{1,3})?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})$/;
const SUB_MILLISECOND = /:[0-9]{2}\.[0-9]{4,}/;

const isObject = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);
const isString = (value) => typeof value === 'string';
const list = (value) => (Array.isArray(value) ? value.filter(isObject) : []);
const indexed = (value) => (Array.isArray(value) ? value.flatMap((item, index) => (isObject(item) ? [[item, index]] : [])) : []);
const show = (value) => {
  if (typeof value === 'string') return value;
  try { return String(value); } catch { return JSON.stringify(value) ?? typeof value; }
};
const finding = (code, instancePath, message) => ({ code, instancePath, message });
const isOrg = (value) => isString(value) && value.startsWith('org:');

export const isShareGrantId = (value) => isString(value) && SHARE_GRANT_ID.test(value);
export const isOrgContext = (value) => isString(value) && ORG_CONTEXT.test(value);

/** FAC-SEM-117 on one grant: an organization's share grant has a share grant id and a millisecond window. */
export function shareGrantIdFindings(grant, at) {
  if (!isObject(grant) || !isOrg(grant.context)) return [];
  const findings = [];
  const id = isObject(grant.meta) ? grant.meta.id : undefined;
  if (!isShareGrantId(id)) findings.push(finding('FAC-SEM-117', `${at}/meta/id`, 'a share grant into an organization is named urn:fabric:share: and 32 lower-case hex digits from a CSPRNG, never a name, an address or an estate id'));
  for (const name of ['startsAt', 'expiresAt']) {
    if (isString(grant[name]) && SUB_MILLISECOND.test(grant[name])) findings.push(finding('FAC-SEM-117', `${at}/${name}`, 'a share grant into an organization carries its window with at most three fraction digits'));
  }
  return findings;
}

/** Kind grant as the contract's contextRules answers it: FAC-SEM-110 (DEC-0082), then FAC-SEM-117 (DEC-0086). */
export const grantFindings = (grant, at = '') => [...grantContextFindings(grant, at), ...shareGrantIdFindings(grant, at)];

function agentsUnder(record, context, id) {
  const placements = list(record.machines).flatMap((machine) => list(machine.packages));
  return new Set(placements.filter((p) => p.context === context && isString(id) && sameIdentifier(p.grant, id)).map((p) => show(p.agentRef)));
}

/** FAC-SEM-117 on a record {record, parent?}: id and window, one agentRef, and the same agentRef as in parent. */
export function orgShareGrantsFindings(value) {
  const record = isObject(value) && isObject(value.record) ? value.record : {};
  const parent = isObject(value) && isObject(value.parent) ? value.parent : undefined;
  const findings = [];
  for (const [grant, index] of indexed(record.shareGrants)) {
    const at = `/record/shareGrants/${index}`;
    findings.push(...shareGrantIdFindings(grant, at));
    if (!isOrg(grant.context)) continue;
    const id = isObject(grant.meta) ? grant.meta.id : undefined;
    const refs = agentsUnder(record, grant.context, id);
    if (refs.size > 1) findings.push(finding('FAC-SEM-117', at, `the placements naming this grant run ${refs.size} agents: a share grant into an organization runs one agentRef`));
    if (!parent) continue;
    const before = list(parent.shareGrants).find((old) => old.context === grant.context && isObject(old.meta) && isString(id) && sameIdentifier(old.meta.id, id));
    const earlier = before ? agentsUnder(parent, before.context, id) : new Set();
    if (earlier.size > 0 && [...refs].some((ref) => !earlier.has(ref))) {
      findings.push(finding('FAC-SEM-117', at, 'this grant ran another agent in the earlier revision given as parent: a share grant into an organization keeps its agentRef; move the share by revoking it and minting a new id'));
    }
  }
  return findings;
}

const time = (value) => (isString(value) && INSTANT.test(value) ? estateTime(value) : Number.NaN);

/** FAC-SEM-118 on one share-registration/1 document. */
export function registrationFindings(value) {
  if (!isObject(value) || value.type !== SHARE_REGISTRATION_TYPE) return [];
  const names = value.state === 'active' ? ['startsAt', 'expiresAt'] : ['withdrawnAt'];
  const unreadable = names.filter((name) => !Number.isFinite(time(value[name])));
  const findings = unreadable.map((name) => finding('FAC-SEM-118', `/${name}`, 'an instant is an RFC 3339 date-time with an offset, on a day that exists, with at most three fraction digits'));
  if (value.state === 'active' && !unreadable.length && time(value.startsAt) >= time(value.expiresAt)) findings.push(finding('FAC-SEM-118', '/expiresAt', "an active registration's window ends after it starts"));
  return findings;
}

/** FAC-SEM-045's DEC-0086 clause on {binding, batch}: a grant.usage carries org: and the certificate's org.id as written. */
export function grantUsageContextFindings(value) {
  const binding = isObject(value) && isObject(value.binding) ? value.binding : {};
  const org = isObject(binding.org) ? binding.org.id : undefined;
  const batch = isObject(value) && isObject(value.batch) ? value.batch : {};
  const findings = [];
  list(batch.events).forEach((event, i) => {
    if (event.kind !== 'grant.usage') return;
    const context = isObject(event.data) ? event.data.context : undefined;
    if (typeof org !== 'string' || context !== `org:${org}`) findings.push(finding('FAC-SEM-045', `/batch/events/${i}/data/context`, "a grant's usage carries its grant's own context, org: and the client certificate's org.id; another organization's is refused as attribution"));
  });
  return findings;
}

/** Kinds grant, org-share-grants, share-registration and device-attribution (045's grant.usage clause); undefined otherwise. */
export function shareRules(kind, value) {
  if (kind === 'grant') return grantFindings(value, '');
  if (kind === 'org-share-grants') return orgShareGrantsFindings(value);
  if (kind === 'share-registration') return registrationFindings(value);
  if (kind === 'device-attribution') return grantUsageContextFindings(value);
  return undefined;
}
// #endregion share-kit-node
