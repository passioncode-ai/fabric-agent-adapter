// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
// Who an instance serves, how it keeps data apart and the space it runs in: fabric-instance-facts/0.1, the extension keyed
// extensions/instance-facts/0.1 (DEC-0173, FAC-SEM-180). Declared by the service, never verified.
// instanceFacts(descriptor, wellKnown) is the contract's instanceFacts (IF-5); instanceFactsRules(kind, value) its
// instanceFactsRules for service-descriptor, service-well-known and service-observation ({descriptor, wellKnown}). Both
// never throw. Held to test/fixtures/contract/instance-facts-vectors.json. Part of the Node service kit (FAA-342, layer
// L3); the twin of fabric_instance_facts.py. Node 18+, no dependency.
import { isObject, show } from './fabric-jsvalue.mjs';
import { secretArgument } from './fabric-secrets.mjs';

export const INSTANCE_FACTS_EXTENSION_KEY = 'https://fabric.passioncode.ai/agent-contract/extensions/instance-facts/0.1';
export const AUDIENCES = Object.freeze(['operator', 'organization', 'public']);
export const ENTRIES = Object.freeze(['host-signin', 'own-signin', 'none']);
export const TENANCY_MODES = Object.freeze(['single', 'per-organization', 'shared']);
export const SPACE_KINDS = Object.freeze(['user', 'container', 'vm', 'system']);
const ACCOUNT = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/u;

/** [field, member, name inside the member], in the order the contract reads them. */
const FIELDS = Object.freeze([['audience', 'access', 'audience'], ['entry', 'access', 'entry'], ['mode', 'tenancy', 'mode'], ['kind', 'space', 'kind'], ['account', 'space', 'account']]);
const MEMBER_OF = Object.freeze({ audience: 'access/audience', entry: 'access/entry', mode: 'tenancy/mode', kind: 'space/kind', account: 'space/account' });
const own = (value, key) => isObject(value) && Object.hasOwn(value, key);

/** The contract's serviceKey: `<id>.<instance>`, an absent (or null) instance read as `default`. */
const serviceKey = (value) => `${show(own(value, 'id') ? value.id : undefined)}.${show(own(value, 'instance') && value.instance !== null ? value.instance : 'default')}`;

function answersAsAnother(descriptor, wellKnown) {
  if (!isObject(descriptor) || !isObject(wellKnown)) return false;
  return serviceKey(descriptor) !== serviceKey(isObject(wellKnown.service) ? wellKnown.service : {});
}

const SHAPES = {
  access: [{ audience: AUDIENCES, entry: ENTRIES }, undefined],
  tenancy: [{ mode: TENANCY_MODES }, 'mode'],
  space: [{ kind: SPACE_KINDS, account: null }, 'kind'],
};

function memberOk(value, allowed, required) {
  if (!isObject(value)) return false;
  if (required !== undefined && !Object.hasOwn(value, required)) return false;
  return Object.keys(value).every((key) => {
    if (!Object.hasOwn(allowed, key)) return false;
    const member = value[key];
    if (key === 'account') return typeof member === 'string' && ACCOUNT.test(member);
    return typeof member === 'string' && allowed[key].includes(member);
  });
}

/** service-instance-facts-extension.schema.json at the pin, by hand. */
export function schemaOk(value) {
  if (!isObject(value)) return false;
  return Object.keys(value).every((key) => Object.hasOwn(SHAPES, key) && memberOk(value[key], ...SHAPES[key]));
}

function declaredIn(document) {
  const extensions = isObject(document) && isObject(document.extensions) ? document.extensions : undefined;
  if (extensions === undefined || !Object.hasOwn(extensions, INSTANCE_FACTS_EXTENSION_KEY)) return { present: false, valid: true, values: {} };
  const value = extensions[INSTANCE_FACTS_EXTENSION_KEY];
  if (!schemaOk(value)) return { present: true, valid: false, values: {} };
  const values = {};
  for (const [field, member, name] of FIELDS) {
    const holder = value[member];
    if (isObject(holder) && Object.hasOwn(holder, name)) values[field] = holder[name];
  }
  return { present: true, valid: true, values };
}

function settingOf(descriptor, wellKnown) {
  const setting = {};
  if (isObject(descriptor)) {
    setting.peer = isObject(descriptor.peer);
    setting.local = descriptor.placement !== 'remote'; // an absent placement is local (DEC-0019)
    setting.subscription = isObject(descriptor.runner) && descriptor.runner.credentialKind === 'subscription';
  }
  if (isObject(wellKnown) && isObject(wellKnown.surfaces) && isObject(wellKnown.surfaces.dashboard) && typeof wellKnown.surfaces.dashboard.login === 'boolean') {
    setting.login = wellKnown.surfaces.dashboard.login;
  }
  return setting;
}

function refusal(field, value, document, setting) {
  if (field === 'audience') {
    if (value === 'operator' && setting.peer === true) return 'operator beside peer: a service offered to others serves more than its operator';
    if (value === 'organization' && setting.peer === false && setting.local === true) return 'organization on a local placement needs peer: a host routes others only to a service that declares it (DEC-0061)';
    if (value === 'public' && setting.local === true) return 'public is a remote placement\'s: a local origin is reached from outside the computer only through peer, which no hub routes to anyone at large';
    if (value === 'public' && setting.subscription === true) return 'public beside a subscription runner: a service others reach never runs on the operator\'s subscription (DEC-0046, DEC-0061 item 3)';
    // DEC-0174: an organization's members reaching a remote surface with their own keys still run on its runner.
    if (value === 'organization' && setting.subscription === true) return 'organization beside a subscription runner: a subscription serves only its owner\'s own sessions, never an organization\'s members (DEC-0061, DEC-0174)';
  }
  if (field === 'entry' && setting.login !== undefined && (value === 'host-signin') !== setting.login) {
    return setting.login ? 'the dashboard requires a host\'s login code (surfaces.dashboard.login)' : 'the dashboard takes no host\'s login code (surfaces.dashboard.login is false)';
  }
  if (field === 'mode' && value === 'shared' && setting.local === true) return 'shared is a remote service\'s: a local placement names one context and at most one grant (DEC-0082 item 4)';
  if (field === 'mode' && (value === 'shared' || value === 'per-organization') && setting.subscription === true) return `${value} beside a subscription runner: an instance holding others' data serves more than its owner's own sessions (DEC-0061, DEC-0174)`;
  if (field === 'kind' && value === 'system' && setting.local === true) return 'system is a remote placement\'s: a local service runs under a counted OS account (DEC-0154)';
  if (field === 'account') {
    if (document === 'wellKnown' && setting.local === true) return 'a local service\'s well-known document is read by every counted OS account on the computer; the label stays in its descriptor (IF-4)';
    if (typeof value === 'string' && secretArgument(value)) return 'the label is shaped like a credential; it names a space, never a credential';
  }
  return undefined;
}

/** The reference reading (IF-5). Either document may be undefined or null (not read). Never throws. */
export function instanceFacts(descriptor, given) {
  const foreign = answersAsAnother(descriptor, given);
  const wellKnown = foreign ? undefined : given;
  const setting = settingOf(descriptor, wellKnown);
  const sources = [['wellKnown', declaredIn(wellKnown)], ['descriptor', declaredIn(descriptor)]];
  const view = { declared: false, facts: {}, refused: [], foreign, invalid: sources.filter(([, read]) => !read.valid).map(([document]) => document) };
  const declaresAny = sources.some(([, read]) => Object.keys(read.values).length > 0);
  for (const [field] of FIELDS) {
    let decided = false;
    for (const [document, read] of sources) {
      if (!Object.hasOwn(read.values, field)) continue;
      const value = read.values[field];
      const reason = refusal(field, value, document, setting);
      if (reason !== undefined) { view.refused.push({ document, field, reason }); continue; }
      if (!decided) view.facts[field] = value;
      decided = true;
    }
  }
  if (setting.login === true && declaresAny) view.facts.entry = 'host-signin';
  view.declared = Object.keys(view.facts).length > 0;
  return view;
}

const pointerToken = (token) => token.replace(/~/g, '~0').replace(/\//g, '~1');
const at = (document, field) => `${document === undefined ? '' : `/${document}`}/extensions/${pointerToken(INSTANCE_FACTS_EXTENSION_KEY)}${field === undefined ? '' : `/${MEMBER_OF[field]}`}`;

/** FAC-SEM-180 (IF-6) as {code, instancePath, message}, per the contract's kinds; [] for any other kind. */
export function instanceFactsRules(kind, value) {
  if (!isObject(value)) return [];
  let view;
  let prefix;
  if (kind === 'service-descriptor') { view = instanceFacts(value, undefined); prefix = () => undefined; }
  else if (kind === 'service-well-known') { view = instanceFacts(undefined, value); prefix = () => undefined; }
  else if (kind === 'service-observation') {
    const pair = instanceFacts(value.descriptor, value.wellKnown);
    if (pair.foreign) return [];
    const alone = [...instanceFacts(value.descriptor, undefined).refused, ...instanceFacts(undefined, value.wellKnown).refused];
    const seen = (r) => alone.some((o) => o.document === r.document && o.field === r.field && o.reason === r.reason);
    view = { ...pair, invalid: [], refused: pair.refused.filter((r) => !seen(r)) };
    prefix = (document) => document;
  } else return [];
  return [
    ...view.invalid.map((document) => ({ code: 'FAC-SEM-180', instancePath: at(prefix(document)), message: 'the instance facts fail their schema; a host reads none of them from this document (DEC-0173)' })),
    ...view.refused.map((r) => ({ code: 'FAC-SEM-180', instancePath: at(prefix(r.document), r.field), message: `${r.reason}; a host reads this fact as not declared (DEC-0173 IF-6)` })),
  ];
}
