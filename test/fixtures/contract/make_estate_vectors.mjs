#!/usr/bin/env node
// Writes estate-vectors.json: estate-record/1 (DEC-0055) cases whose expected answers come from the contract's own
// functions at the pin — verifyEstateRecord, estateRecordRules (FAC-SEM-072…076), estateRecordDigest, estateChallenge,
// placementTrust (src/estate-record-rules.ts), verifyAssertion and credentialKey (src/webauthn.ts) and isValidP256Key
// (src/p256.ts) — never written by hand. The kits' fabric_estate.py and fabric-estate.mjs are held to them.
//
//   node test/fixtures/contract/make_estate_vectors.mjs --contract-src <dir with the staged .ts sources>
//     --vectors <fixtures/vectors/estate-record.json> --semantic <dir of the fixtures/semantic/estate-*.json and grant-context-*.json files>
//     --positive <dir with estate-record-first.json, estate-record-second.json, estate-record-organizations.json,
//     fabric-package-agent.json>
//     --machine-call <fixtures/vectors/machine-call.json> [--out test/fixtures/contract/estate-vectors.json]
//
// Needs Node 24 or later (type stripping); the staged sources import each other as .ts. The contract's vectors carry
// the private test keys that made their signatures; they are dropped here: the kits verify and never sign.

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const src = (file) => import(pathToFileURL(path.join(args['contract-src'], file)).href);
const estate = await src('estate-record-rules.ts');
const contextRules = await src('context-rules.ts');
const webauthn = await src('webauthn.ts');
const p256 = await src('p256.ts');
const read = (file) => JSON.parse(fs.readFileSync(file, 'utf8'));
const clone = (v) => JSON.parse(JSON.stringify(v));
const contract = read(args.vectors);

// verifyEstateRecord: the contract's own cases, re-answered here so a stale copy is caught.
const verify = contract.cases.map((c) => {
  const trust = { ...c.trust, at: c.trust.at === null || c.trust.at === undefined ? c.trust.at : new Date(c.trust.at) };
  const answer = estate.verifyEstateRecord(c.record, trust);
  if (JSON.stringify(answer) !== JSON.stringify(c.expected)) throw new Error(`the contract's vector "${c.name}" no longer answers as written`);
  return { name: c.name, record: c.record, trust: c.trust, expected: answer };
});

// FAC-SEM-137 (DEC-0107) on the verify path (FAA-112): the delta anchor varied on the contract's own EdDSA revision 2
// checked against its parent. The revision is re-signed with the vectors' EdDSA test seed (Ed25519 is deterministic),
// and every verdict is the contract's verifyEstateRecord; a case that should pass and does not stops the generator.
{
  const base = contract.cases.find((c) => c.name.startsWith('revision 2, signed by a passkey its parent lists (EdDSA)'));
  const seed = Buffer.from(contract.keys.passkeyEdDSA.seed, 'hex');
  const key = crypto.createPrivateKey({ key: Buffer.concat([Buffer.from('302e020100300506032b657004220420', 'hex'), seed]), format: 'der', type: 'pkcs8' });
  const b64url = (bytes) => Buffer.from(bytes).toString('base64url');
  const resign = (record) => {
    record.digest = estate.estateRecordDigest(record);
    const client = JSON.parse(Buffer.from(record.signature.clientDataJSON, 'base64url').toString('utf8'));
    const clientData = Buffer.from(JSON.stringify({ ...client, challenge: b64url(estate.estateChallenge(record.digest)) }), 'utf8');
    const authData = Buffer.from(record.signature.authenticatorData, 'base64url');
    const signed = Buffer.concat([authData, crypto.createHash('sha256').update(clientData).digest()]);
    record.signature = { ...record.signature, clientDataJSON: b64url(clientData), sig: b64url(crypto.sign(null, signed, key)) };
    return record;
  };
  const anchor = (sequence, c) => ({ sequence, sha256: c.repeat(64) });
  for (const [name, before, after, passes] of [
    ['the delta anchor moves forward', anchor(5, 'a'), anchor(6, 'b'), true],
    ['the same delta anchor kept', anchor(5, 'a'), anchor(5, 'a'), true],
    ['a delta anchor first appears', undefined, anchor(1, 'a'), true],
    ['the delta anchor moves back', anchor(6, 'b'), anchor(5, 'a'), false],
    ['the delta anchor dropped', anchor(5, 'a'), undefined, false],
    ['the same sequence under another hash', anchor(5, 'a'), anchor(5, 'b'), false],
  ]) {
    const parent = clone(base.trust.parent);
    const record = clone(base.record);
    if (before) parent.deltaAnchor = before;
    if (after) record.deltaAnchor = after;
    parent.digest = estate.estateRecordDigest(parent);
    record.parent = parent.digest;
    resign(record);
    const trust = { ...base.trust, parent };
    const expected = estate.verifyEstateRecord(record, { ...trust, at: new Date(trust.at) });
    if (expected.ok !== passes) throw new Error(`anchor on the verify path, "${name}": the contract answers ${JSON.stringify(expected)}`);
    verify.push({ name: `anchor: ${name} (EdDSA, re-signed revision 2)`, record, trust, expected });
  }
}

// estateRecordRules: every estate semantic fixture, through the contract's own rules.
const rules = fs.readdirSync(args.semantic).filter((f) => f.startsWith('estate-') && f.endsWith('.json')).sort().map((file) => {
  const fixture = read(path.join(args.semantic, file));
  const expected = estate.estateRecordRules(fixture.kind, fixture.input);
  const codes = [...new Set(expected.map((f) => f.code))].sort();
  if (JSON.stringify(codes) !== JSON.stringify([...fixture.expect].sort())) throw new Error(`${file}: the rules answer ${codes}, the fixture expects ${fixture.expect}`);
  return { name: file, kind: fixture.kind, value: fixture.input, expected };
});
const first = read(path.join(args.positive, 'estate-record-first.json'));
const second = read(path.join(args.positive, 'estate-record-second.json'));
const agentPkg = read(path.join(args.positive, 'fabric-package-agent.json'));
for (const [name, kind, value] of [['positive/estate-record-first', 'estate-record', first], ['positive/estate-record-second', 'estate-record', second],
  ['positive revision first → second', 'estate-record-revision', { parent: first, next: second }],
  ['positive placement', 'estate-placement', { record: first, machine: first.machines[0].id, package: agentPkg }],
  // DEC-0090: a partner's package installed in a context its key's scope names, and in one it does not (FAC-SEM-122).
  ['a partner placement in its scoped context', 'estate-placement', { record: read(path.join(args.semantic, 'estate-partner-key-ok.json')).input, machine: 'm-4c1e',
    package: { ...agentPkg, agentRef: 'urn:fabric:agent:acme:setup-desk' }, context: 'org:org_7kq2m4xw' }],
  ['a partner placement outside its scoped context', 'estate-placement', { record: read(path.join(args.semantic, 'estate-partner-key-other-context.json')).input, machine: 'm-4c1e',
    package: { ...agentPkg, agentRef: 'urn:fabric:agent:acme:setup-desk' }, context: 'org:org_3fh9p1zc' }],
  ['a kind the rules do not know', 'estate-something', first],
  ['a hub key of the wrong length', 'estate-record', (() => { const r = clone(first); r.machines[0].hubKey.x = 'AAAA'; return r; })()],
  ['dates in lower case', 'estate-record', (() => { const r = clone(first); r.issuedAt = r.issuedAt.replace('T', 't').replace('Z', 'z'); return r; })()],
  ['dates with an offset', 'estate-record', (() => { const r = clone(first); r.issuedAt = '2026-10-12T11:00:00.5+02:00'; return r; })()],
  ['a leap second', 'estate-record', (() => { const r = clone(first); r.validUntil = r.validUntil.replace(':00Z', ':60Z'); return r; })()],
  ['a space for T', 'estate-record', (() => { const r = clone(first); r.issuedAt = r.issuedAt.replace('T', ' '); return r; })()],
  ['a day that does not exist', 'estate-record', (() => { const r = clone(first); r.issuedAt = '2026-02-30T09:00:00Z'; return r; })()],
  ['revision chain over non-objects', 'estate-record-revision', { parent: 'x', next: 7 }],
  ['placement with nothing in it', 'estate-placement', {}],
  ['a full-width digit in a date', 'estate-record', (() => { const r = clone(first); r.issuedAt = `\uff12${r.issuedAt.slice(1)}`; return r; })()],
  ...['\uff11', '\ufeff1', '0b1', '0o7', '0x1f', [1], ['2'], [], {}, '  3  ', '\u00a07', '-0x10', 'Infinity', '-Infinity', '1e2', '.5', '5.', '1e', 'infinity', null, true, '\u06611', '\u001c1']
    .map((revision) => [`Number() of a parent revision ${JSON.stringify(revision)}`, 'estate-record-revision', { parent: { ...clone(first), revision }, next: clone(second) }])]) {
  rules.push({ name, kind, value, expected: estate.estateRecordRules(kind, value) });
}

// DEC-0076: a grant's id is a URI, so grants and `grant` revocations are keyed by its normal form. The semantic fixtures
// write ids in normal form, so these respell one (`urn` and the NID upper-cased) and take the contract's own answer: a
// byte comparison passes them, a normal-form one does not; changing the NSS's case keeps them two grants.
const twice = read(path.join(args.semantic, 'estate-grant-twice.json')).input;
const respell = (id) => String(id).replace(/^urn:([^:]+)/i, (_, nid) => `URN:${nid.toUpperCase()}`);
for (const [name, value] of [
  ['a grant listed twice under two spellings (DEC-0076)', (() => { const r = clone(twice); r.shareGrants[1].meta.id = respell(r.shareGrants[1].meta.id); return r; })()],
  ['two grants whose ids differ in the NSS case are two (DEC-0076)', (() => { const r = clone(twice); r.shareGrants[1].meta.id = r.shareGrants[1].meta.id.toUpperCase().replace(/^URN:GRANT:ESTATE:/, 'urn:grant:estate:'); return r; })()],
  ['a grant revoked under another spelling while still listed (DEC-0076)', (() => { const r = clone(twice); r.shareGrants.pop(); r.revocations = [{ kind: 'grant', ref: respell(r.shareGrants[0].meta.id), revokedAt: r.issuedAt }]; return r; })()],
  ['a grant revoked twice under two spellings (DEC-0076)', (() => { const r = clone(twice); const id = r.shareGrants[0].meta.id; r.shareGrants = []; r.revocations = [{ kind: 'grant', ref: id, revokedAt: r.issuedAt }, { kind: 'grant', ref: respell(id), revokedAt: r.issuedAt }]; return r; })()],
]) rules.push({ name, kind: 'estate-record', value, expected: estate.estateRecordRules('estate-record', value) });

// DEC-0082's fix rounds made every rule total on hostile JSON: an instancePath names an item by its index as written
// (a non-object before it does not shift it), and a member whose own `toString` is data reads as its JSON. Each case is
// the contexts fixture broken one way, answered by the contract's rules.
{
  const base = read(path.join(args.semantic, 'estate-contexts-ok.json')).input;
  const hostile = { toString: 1 };
  const broken = (name, edit, kind = 'estate-record') => {
    const value = edit(clone(base));
    rules.push({ name: `hostile: ${name}`, kind, value, expected: estate.estateRecordRules(kind, value) });
  };
  broken('a non-object before the machines, then a machine listed twice', (r) => { r.machines = [3, ...r.machines, clone(r.machines[0])]; return r; });
  broken('a non-object before the placements, then one placed twice in its context', (r) => { const p = r.machines[0].packages; r.machines[0].packages = [null, ...p, clone(p[0])]; return r; });
  broken('a non-object before the share grants, then a personal external grant', (r) => { r.shareGrants = ['x', ...(r.shareGrants ?? []).map((g) => ({ ...g, context: 'personal' }))]; return r; });
  broken('a non-object before the revocations, then a grant revoked and still listed', (r) => { r.revocations = [7, { kind: 'grant', ref: r.shareGrants?.[0]?.meta?.id ?? 'urn:x' }]; return r; });
  broken('a non-object before the secrets, then a slot placed twice', (r) => { const s = r.machines[0].secrets ?? []; r.machines[0].secrets = [false, ...s, ...(s[0] ? [clone(s[0])] : [])]; return r; });
  broken('a placement whose agentRef has its own toString, placed twice', (r) => { const p = r.machines[0].packages; p[0].agentRef = hostile; p.push(clone(p[0])); return r; });
  broken('a placement whose context has its own toString', (r) => { r.machines[0].packages[0].context = hostile; return r; });
  broken('a secret whose slot has its own toString, placed twice', (r) => { const s = r.machines[0].secrets ?? []; if (s[0]) { s[0].slot = hostile; s.push(clone(s[0])); } return r; });
  broken('a revocation whose kind has its own toString, revoked twice', (r) => { r.revocations = [{ kind: hostile, ref: 'x' }, { kind: hostile, ref: 'x' }]; return r; });
  broken('a machine id with its own toString, listed twice', (r) => { r.machines[0].id = hostile; r.machines.push(clone(r.machines[0])); return r; });
  broken('an installation on a machine named by an object', (r) => ({ record: r, machine: hostile, package: agentPkg }), 'estate-placement');
  const orgGrant = (r) => r.shareGrants.find((g) => typeof g.context === 'string');
  broken('a placement whose context is null names no grant', (r) => { const p = r.machines[0].packages[0]; p.context = null; delete p.grant; return r; });
  broken('a placement in the context Personal under a grant of the record', (r) => { const p = r.machines[0].packages[1]; p.context = 'Personal'; return r; });
  for (const org of ['-x', '_x', 'x'.repeat(129), '']) {
    broken(`a placement in org:${org.length > 8 ? 'x*' + org.length : org} under a grant for that context`, (r) => { const g = orgGrant(r); g.context = `org:${org}`; const p = r.machines[0].packages[1]; p.context = g.context; p.grant = g.meta.id; return r; });
  }
  broken('an installation in the personal context beside an undeclared slot of the same agent in an organization context', (r) => {
    const m = r.machines[0];
    m.packages.push({ agentRef: agentPkg.agentRef, digest: agentPkg.digest, publisherKid: m.packages[0].publisherKid });
    (m.secrets ??= []).push({ agentRef: agentPkg.agentRef, slot: 'UNDECLARED_PERSONAL', from: m.id }, { agentRef: agentPkg.agentRef, slot: 'UNDECLARED_ORG', from: m.id, context: orgGrant(r).context });
    return { record: r, machine: m.id, package: agentPkg };
  }, 'estate-placement');
  broken('an installation in an organization context', (r) => ({ record: r, machine: r.machines[0].id, package: agentPkg, context: (r.machines[0].packages.find((p) => p.context) ?? {}).context }), 'estate-placement');
}

// FAC-SEM-134 (DEC-0106): a machine's profile, varied on the profile fixture the contract writes as passing, and
// answered by the contract's rules: a hub key of any value (null too) beside a member or view profile, non-objects in
// a view machine's lists (they place nothing), a secret with no `from` beside a view machine with no id, a profile that
// is not a string.
{
  const fixture = (file) => read(path.join(args.semantic, file)).input;
  const varied = (name, file, edit) => { const value = edit(clone(fixture(file))); rules.push({ name: `profile: ${name}`, kind: 'estate-record', value, expected: estate.estateRecordRules('estate-record', value) }); };
  const ok = 'estate-profile-ok.json';
  const fromView = 'estate-profile-secret-from-view.json';
  const view = (r) => r.machines.find((m) => m.profile === 'view');
  const member = (r) => r.machines.find((m) => m.profile === 'member');
  varied('a member machine with a null hub key', ok, (r) => { member(r).hubKey = null; return r; });
  varied('a view machine with a hub key of zero', fromView, (r) => { view(r).hubKey = 0; return r; });
  varied('a view machine whose packages and secrets hold only non-objects', fromView, (r) => { view(r).packages = [1, null, 'x']; view(r).secrets = [false]; return r; });
  varied('a view machine with no id beside a secret with no from', fromView, (r) => { delete view(r).id; for (const m of r.machines) for (const x of m.secrets ?? []) delete x.from; return r; });
  varied('a secret from a view machine named by an equal string', fromView, (r) => r);
  varied('a profile written as full', ok, (r) => { r.machines[0].profile = 'full'; return r; });
  // FAA-107: a view machine's id of another JSON type against each secret's `from`: the contract's Set matches by
  // SameValueZero (1 and 1.0 alike, an object only itself, true never 1).
  for (const [id, from] of [[null, null], [null, 'x'], [1, 1.0], [1, '1'], [true, 1], [true, true], [{}, {}], [[], []], [0, -0]]) {
    varied(`a view machine with id ${JSON.stringify(id)} and a secret from ${JSON.stringify(from)}`, fromView, (r) => {
      view(r).id = id;
      for (const m of r.machines) for (const x of m.secrets ?? []) x.from = from;
      return r;
    });
  }
  for (const profile of ['Full', 'VIEW', '', null, 1, ['view'], { toString: 1 }]) varied(`a profile of ${JSON.stringify(profile)}`, ok, (r) => { r.machines[1].profile = profile; return r; });
  varied('a non-object before the machines', fromView, (r) => { r.machines = [7, ...r.machines]; return r; });
}

// FAC-SEM-137 (DEC-0107): the delta anchor varied on the revision the contract writes as passing, answered by its rules.
// A parent anchor the reader cannot read is no anchor; a next anchor it cannot read is a dropped one.
{
  const kept = read(path.join(args.semantic, 'estate-revision-anchor-kept.json')).input;
  const hash = (c) => c.repeat(64);
  const anchored = (name, edit) => { const value = edit(clone(kept)); rules.push({ name: `anchor: ${name}`, kind: 'estate-record-revision', value, expected: estate.estateRecordRules('estate-record-revision', value) }); };
  anchored('the same anchor kept', (v) => { v.next.deltaAnchor = clone(v.parent.deltaAnchor); return v; });
  anchored('the same sequence, the hash in upper case', (v) => { v.next.deltaAnchor = { sequence: v.parent.deltaAnchor.sequence, sha256: v.parent.deltaAnchor.sha256.toUpperCase() }; return v; });
  for (const [what, anchor] of [['a string sequence', { sequence: '6', sha256: hash('6') }], ['sequence 0', { sequence: 0, sha256: hash('6') }],
    ['sequence 2^53', { sequence: 9007199254740992, sha256: hash('6') }], ['a 63-character hash', { sequence: 6, sha256: hash('6').slice(1) }],
    ['a hash with a newline', { sequence: 6, sha256: `${hash('6')}\n` }], ['null', null], ['an array', [6, hash('6')]], ['no sha256', { sequence: 6 }]]) {
    anchored(`a next anchor with ${what}`, (v) => { v.next.deltaAnchor = anchor; return v; });
    anchored(`a parent anchor with ${what}`, (v) => { v.parent.deltaAnchor = anchor; v.next.deltaAnchor = { sequence: 1, sha256: hash('1') }; return v; });
  }
  anchored('no anchor before, one after', (v) => { delete v.parent.deltaAnchor; return v; });
  anchored('next is not an object', (v) => ({ parent: v.parent, next: 7 }));
}
// DEC-0128: context hub keys and organization pins (FAC-SEM-073, 076, 114, 134, 147), varied on the positive record the
// contract writes with two organizations pinned and one context key, answered by its rules (as test/context-keys.test.ts
// varies it), with the hostile shapes a reader must survive.
{
  const orgs = read(path.join(args.positive, 'estate-record-organizations.json'));
  rules.push({ name: 'positive/estate-record-organizations', kind: 'estate-record', value: orgs, expected: estate.estateRecordRules('estate-record', orgs) });
  const ORG = 'org:org_3fh9p1zc';
  const hubMachine = orgs.machines.find((machine) => machine.hubKey);
  const CONTEXT_KEY = hubMachine.contextHubKeys[0].key;
  const PERSONAL_KEY = hubMachine.hubKey;
  const redigest = (record) => ({ ...record, digest: estate.estateRecordDigest(record) });
  const onHub = (change) => redigest({ ...clone(orgs), machines: clone(orgs.machines).map((machine) => (machine.id === hubMachine.id ? change(machine) : machine)) });
  // Answered on the value as JSON carries it: an object shared between two members would be one object to a Set here and
  // two to a reader of the vectors.
  const record = (name, built) => { const value = clone(built); rules.push({ name: `context: ${name}`, kind: 'estate-record', value, expected: estate.estateRecordRules('estate-record', value) }); };
  record('an estate id the issuer does not contain', redigest({ ...clone(orgs), estate: 'e' }));
  record('an estate id in upper case inside the issuer', redigest({ ...clone(orgs), estate: 'C7D2A91F' }));
  record('an estate id of seven characters inside the issuer', redigest({ ...clone(orgs), estate: 'C7D2A91' }));
  record('an estate id that is the issuer prefix', redigest({ ...clone(orgs), estate: 'urn:fabric:context' }));
  record('a member machine with a context key and no hub key', onHub((machine) => { const { hubKey: _drop, ...rest } = machine; return { ...rest, profile: 'member' }; }));
  record('a view machine with a context key', onHub((machine) => ({ ...machine, profile: 'view' })));
  record('a context twice on one machine', onHub((machine) => ({ ...machine, contextHubKeys: [{ context: ORG, key: CONTEXT_KEY }, { context: ORG, key: { ...CONTEXT_KEY, kid: 'hub-ctx-a-2', x: 'Q2T0QOvPprzOcLfCCzIP1Ef2bIRiTqgZQB8uwN3qqUA' } }] })));
  record('a context key reusing the personal public key', onHub((machine) => ({ ...machine, contextHubKeys: [{ context: ORG, key: { ...CONTEXT_KEY, x: PERSONAL_KEY.x } }] })));
  record('a context key reusing the personal kid', onHub((machine) => ({ ...machine, contextHubKeys: [{ context: ORG, key: { ...CONTEXT_KEY, kid: PERSONAL_KEY.kid } }] })));
  record('a context key of small order', onHub((machine) => ({ ...machine, contextHubKeys: [{ context: ORG, key: { ...CONTEXT_KEY, x: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' } }] })));
  record('a context key of the wrong length', onHub((machine) => ({ ...machine, contextHubKeys: [{ context: ORG, key: { ...CONTEXT_KEY, x: 'AAAA' } }] })));
  record('a context key that is not an object', onHub((machine) => ({ ...machine, contextHubKeys: [{ context: ORG, key: 'none' }] })));
  record('a context key on a machine without the personal hub key', onHub((machine) => { const { hubKey: _drop, ...rest } = machine; return rest; }));
  record('a context the record does not pin', onHub((machine) => ({ ...machine, contextHubKeys: [{ context: 'org:nobody', key: CONTEXT_KEY }] })));
  record('a context key whose kid is revoked while listed', redigest({ ...clone(orgs), revocations: [{ kind: 'hub-key', ref: CONTEXT_KEY.kid, revokedAt: orgs.issuedAt }] }));
  record('a context key with no kid and a hub-key revocation with no ref', (() => {
    const { kid: _kid, ...noKid } = CONTEXT_KEY;
    const r = onHub((machine) => ({ ...machine, contextHubKeys: [{ context: ORG, key: noKid }] }));
    r.revocations = [{ kind: 'hub-key', revokedAt: orgs.issuedAt }];
    return redigest(r);
  })());
  record('an organization pinned twice', redigest({ ...clone(orgs), organizations: [...clone(orgs.organizations), clone(orgs.organizations[0])] }));
  record('a context issuer used twice', redigest({ ...clone(orgs), organizations: orgs.organizations.map((pin) => ({ ...pin, iss: orgs.organizations[0].iss })) }));
  record('a root of small order', redigest({ ...clone(orgs), organizations: orgs.organizations.map((pin, i) => (i === 0 ? { ...pin, root: { ...pin.root, x: 'AQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' } } : pin)) }));
  // Hostile shapes: non-objects among the pins and the context keys, members of other JSON types, a toString of data.
  const hostile = { toString: 1 };
  record('hostile: non-objects before the pins, then a pin twice', redigest({ ...clone(orgs), organizations: [3, null, ...clone(orgs.organizations), clone(orgs.organizations[1])] }));
  record('hostile: organizations that is not an array', redigest({ ...clone(orgs), organizations: { org: ORG } }));
  record('hostile: a pin whose org has its own toString, twice', redigest({ ...clone(orgs), organizations: [{ ...clone(orgs.organizations[0]), org: hostile }, { ...clone(orgs.organizations[1]), org: hostile }] }));
  record('hostile: a pin whose iss and root are other types', redigest({ ...clone(orgs), organizations: [{ ...clone(orgs.organizations[0]), iss: 7, root: 'x' }, { ...clone(orgs.organizations[1]), iss: null, root: { x: 1 } }] }));
  record('hostile: a pin with no org beside a context key with no context', (() => { const r = onHub((machine) => ({ ...machine, contextHubKeys: [{ key: CONTEXT_KEY }] })); delete r.organizations[0].org; return redigest(r); })());
  record('hostile: non-objects before the context keys, then a context twice', onHub((machine) => ({ ...machine, contextHubKeys: [7, 'x', { context: ORG, key: CONTEXT_KEY }, { context: ORG, key: { ...CONTEXT_KEY, kid: 'k-2', x: 'Q2T0QOvPprzOcLfCCzIP1Ef2bIRiTqgZQB8uwN3qqUA' } }] })));
  record('hostile: contextHubKeys that is not an array', onHub((machine) => ({ ...machine, contextHubKeys: { context: ORG, key: CONTEXT_KEY } })));
  record('hostile: a context key whose kid and context have their own toString', onHub((machine) => ({ ...machine, contextHubKeys: [{ context: hostile, key: { ...CONTEXT_KEY, kid: hostile } }, { context: hostile, key: { ...CONTEXT_KEY, kid: hostile, x: 'Q2T0QOvPprzOcLfCCzIP1Ef2bIRiTqgZQB8uwN3qqUA' } }] })));
  record('hostile: a context key whose x is a number', onHub((machine) => ({ ...machine, contextHubKeys: [{ context: ORG, key: { ...CONTEXT_KEY, x: 5 } }] })));
  record('hostile: an estate id of another type', redigest({ ...clone(orgs), estate: 12345678 }));
  // FAC-SEM-114 across two revisions: a context key dropped, replaced, moved to another context, or its machine removed.
  const parent = orgs;
  const revision = (name, change, revocations = [], machines = undefined) => {
    const next = redigest({ ...clone(parent), revision: parent.revision + 1, parent: parent.digest, revocations: [...clone(parent.revocations ?? []), ...revocations],
      machines: machines ?? clone(parent.machines).map((machine) => (machine.id === hubMachine.id ? change(machine) : machine)) });
    const value = clone({ parent, next });
    rules.push({ name: `context revision: ${name}`, kind: 'estate-record-revision', value, expected: estate.estateRecordRules('estate-record-revision', value) });
  };
  const revokedAt = parent.issuedAt;
  revision('the context key kept', (machine) => machine);
  revision('the context key dropped', (machine) => ({ ...machine, contextHubKeys: [] }));
  revision('the context key dropped and revoked', (machine) => ({ ...machine, contextHubKeys: [] }), [{ kind: 'hub-key', ref: CONTEXT_KEY.kid, revokedAt }]);
  revision('the context key replaced under the same kid', (machine) => ({ ...machine, contextHubKeys: [{ context: ORG, key: { ...CONTEXT_KEY, x: 'Q2T0QOvPprzOcLfCCzIP1Ef2bIRiTqgZQB8uwN3qqUA' } }] }));
  revision('the context key moved to the other pinned organization', (machine) => ({ ...machine, contextHubKeys: [{ context: 'org:org_7kq2m4xw', key: CONTEXT_KEY }] }));
  revision('the context key list made a non-array', (machine) => ({ ...machine, contextHubKeys: 'none' }));
  const withoutHub = clone(parent.machines).filter((machine) => machine.id !== hubMachine.id);
  const removal = [{ kind: 'machine', ref: hubMachine.id, revokedAt }, { kind: 'hub-key', ref: PERSONAL_KEY.kid, revokedAt }];
  revision('the hub machine removed, its context key not revoked', null, removal, withoutHub);
  revision('the hub machine removed with its context key revoked', null, [...removal, { kind: 'hub-key', ref: CONTEXT_KEY.kid, revokedAt }], withoutHub);
  revision('a parent context key that is not an object', null, [], clone(parent.machines));
  rules[rules.length - 1].value.parent = (() => { const p = clone(parent); p.machines.find((m) => m.id === hubMachine.id).contextHubKeys = [{ context: ORG, key: 'k' }, 3]; return p; })();
  rules[rules.length - 1].expected = estate.estateRecordRules('estate-record-revision', rules[rules.length - 1].value);
}

const deltaAnchor = [{ deltaAnchor: { sequence: 1, sha256: 'a'.repeat(64) } }, { deltaAnchor: { sequence: 1.5, sha256: 'a'.repeat(64) } }, { deltaAnchor: { sequence: 1, sha256: 'A'.repeat(64) } },
  { deltaAnchor: { sequence: -1, sha256: 'a'.repeat(64) } }, { deltaAnchor: 'x' }, {}, null, 'record', [{ deltaAnchor: { sequence: 1, sha256: 'a'.repeat(64) } }],
  { deltaAnchor: { sequence: 1, sha256: 'a'.repeat(64), extra: true } }].map((record) => ({ record, expected: estate.deltaAnchorOf(record) ?? null }));

// machineProfile (DEC-0106): the contract's own cases from machine-call.json, re-answered here, and hostile inputs.
const machineCall = read(args['machine-call']);
const machineProfile = machineCall.profile.map((c) => {
  const record = 'record' in c ? c.record : machineCall.record;
  const answer = estate.machineProfile(record, c.machineId) ?? null;
  if (JSON.stringify(answer) !== JSON.stringify(c.expect)) throw new Error(`the contract's profile vector "${c.name}" no longer answers as written`);
  return { name: c.name, record, machineId: c.machineId, expected: answer };
});
for (const [name, record, machineId] of [
  ['a record that is not an object', 'x', 'm-a'], ['a record that is an array', [machineCall.record], 'm-a'], ['an id that is not a string', machineCall.record, 7],
  ['an id that is null', machineCall.record, null], ['machines that is not an array', { ...machineCall.record, machines: { 'm-a': {} } }, 'm-a'],
  ['a machine whose profile is an object', { ...machineCall.record, machines: [{ id: 'm-a', profile: { toString: 1 } }] }, 'm-a'],
  ['a machine whose profile is null', { ...machineCall.record, machines: [{ id: 'm-a', profile: null }] }, 'm-a'],
  ['a non-object before the machine', { ...machineCall.record, machines: [null, { id: 'm-a', profile: 'view' }] }, 'm-a'],
]) machineProfile.push({ name: `hostile: ${name}`, record, machineId, expected: estate.machineProfile(record, machineId) ?? null });

// FAC-SEM-110 on a grant of its own (kind `grant`): the grant-context-*.json fixtures and that grant varied one way,
// answered by the contract's grantContextFindings at the document root.
const grantContext = fs.readdirSync(args.semantic).filter((f) => f.startsWith('grant-context-') && f.endsWith('.json')).sort().flatMap((file) => {
  const fixture = read(path.join(args.semantic, file));
  const vary = (name, edit) => { const value = edit(clone(fixture.input)); return { name: `${file}: ${name}`, value, expected: contextRules.grantContextFindings(value, '') }; };
  return [
    vary('as written', (g) => g),
    vary('context org:example-org', (g) => ({ ...g, context: 'org:example-org' })),
    vary('context left out', (g) => { delete g.context; return g; }),
    vary('context Personal', (g) => ({ ...g, context: 'Personal' })),
    vary('a principal inside the estate in the personal context', (g) => ({ ...g, principalKind: 'internal', context: 'personal' })),
    vary('a context with its own toString', (g) => ({ ...g, context: { toString: 1 } })),
    vary('not an object', () => ['personal']),
  ];
});

// The digest, the challenge and placementTrust.
const digests = [first, second].map((record) => ({ record, digest: estate.estateRecordDigest(record), challenge: estate.estateChallenge(estate.estateRecordDigest(record)).toString('hex'),
  challengeInput: estate.estateChallengeInput(estate.estateRecordDigest(record)).toString('utf8') }));
const placement = first.machines[0].packages?.[0];
const trusts = [
  { record: first, machine: first.machines[0].id, agentRef: placement?.agentRef, expected: estate.placementTrust(first, first.machines[0].id, placement?.agentRef) ?? null },
  { record: first, machine: first.machines[0].id, agentRef: 'agent:nobody', expected: estate.placementTrust(first, first.machines[0].id, 'agent:nobody') ?? null },
  { record: first, machine: 'm-none', agentRef: placement?.agentRef, expected: estate.placementTrust(first, 'm-none', placement?.agentRef) ?? null },
];
// DEC-0082: placementTrust takes the placement's context (`personal` when not given). The contexts fixture places one agent
// in the personal context and in an organization's; each context answers its own placement, and a context with none answers null.
const contexts = read(path.join(args.semantic, 'estate-contexts-ok.json')).input;
for (const machine of contexts.machines ?? []) {
  for (const p of machine.packages ?? []) {
    for (const context of [p.context ?? 'personal', 'personal', 'org:nobody', 'Personal']) {
      trusts.push({ record: contexts, machine: machine.id, agentRef: p.agentRef, context, expected: estate.placementTrust(contexts, machine.id, p.agentRef, context) ?? null });
    }
  }
}

// DEC-0090: a partner's publisher key is trusted only in the organization contexts its scope names; every other context
// of the same placement answers no publisher key, and a context with no placement still answers null.
for (const file of ['estate-partner-key-ok.json', 'estate-partner-key-other-context.json', 'estate-partner-key-personal.json']) {
  const record = read(path.join(args.semantic, file)).input;
  for (const machine of record.machines ?? []) {
    for (const p of machine.packages ?? []) {
      for (const context of [p.context ?? 'personal', 'personal', 'org:nobody']) {
        trusts.push({ record, machine: machine.id, agentRef: p.agentRef, context, expected: estate.placementTrust(record, machine.id, p.agentRef, context) ?? null });
      }
    }
  }
}

// isValidP256Key over the record's own P-256 device keys and their breakages.
const P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffffn;
const hex = (n) => n.toString(16).padStart(64, '0');
const p256Cases = [];
for (const machine of [...first.machines, ...second.machines]) {
  for (const key of machine.deviceKeys ?? []) {
    if (key.alg !== 'es256') continue;
    const raw = Buffer.from(key.publicKey, 'base64');
    const variants = {
      [`${key.kid} as listed`]: raw,
      [`${key.kid} with y + 1`]: Buffer.concat([raw.subarray(0, 33), Buffer.from(hex(BigInt(`0x${raw.subarray(33).toString('hex')}`) + 1n), 'hex').subarray(-32)]),
      [`${key.kid} compressed prefix`]: Buffer.concat([Buffer.from([2]), raw.subarray(1)]),
      [`${key.kid} cut short`]: raw.subarray(0, 64),
      [`${key.kid} x = p`]: Buffer.concat([Buffer.from([4]), Buffer.from(hex(P), 'hex'), raw.subarray(33)]),
    };
    for (const [name, bytes] of Object.entries(variants)) p256Cases.push({ name, raw: bytes.toString('hex'), expected: p256.isValidP256Key(bytes) });
  }
}

// credentialKey over the vectors' authorities and their breakages (the verdict, never the KeyObject).
const keyVerdict = (pk, alg) => { const r = webauthn.credentialKey(pk, alg); return 'problem' in r ? { problem: r.problem } : { ok: true }; };
const es = contract.keys.passkeyEs256.authority;
const ed = contract.keys.passkeyEdDSA.authority;
const credentialKeys = [
  ['ES256 as pinned', es.publicKey, 'ES256'], ['EdDSA as pinned', ed.publicKey, 'EdDSA'],
  ['ES256 with a private part', { ...es.publicKey, d: 'AA' }, 'ES256'], ['ES256 x not canonical', { ...es.publicKey, x: `${es.publicKey.x.slice(0, -1)}${es.publicKey.x.slice(-1) === 'k' ? 'l' : 'k'}` }, 'ES256'],
  ['ES256 on another curve', { ...es.publicKey, crv: 'P-384' }, 'ES256'], ['EdDSA key under ES256', ed.publicKey, 'ES256'],
  ['an algorithm the contract does not admit', es.publicKey, 'RS256'], ['EdDSA small order', contract.keys.smallOrder?.publicKey ?? { kty: 'OKP', crv: 'Ed25519', x: 'AQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' }, 'EdDSA'],
].map(([name, publicKey, alg]) => ({ name, publicKey, alg, expected: keyVerdict(publicKey, alg) }));

const keys = Object.fromEntries(Object.entries(contract.keys).map(([name, entry]) => {
  const { privateJwk: _private, seed: _seed, ...kept } = entry;
  return [name, kept];
}));
const out = args.out ?? path.join(here, 'estate-vectors.json');
fs.writeFileSync(out, `${JSON.stringify({
  $comment: 'Generated by make_estate_vectors.mjs from the contract pin\'s src/estate-record-rules.ts, src/webauthn.ts and src/p256.ts and its fixtures (vectors/estate-record.json, the profile cases of vectors/machine-call.json, semantic/estate-*.json, grant-context-*.json); do not edit by hand. The private test keys are dropped.',
  keys, digests, verify, rules, grantContext, placementTrust: trusts, machineProfile, deltaAnchor, p256: p256Cases, credentialKeys,
}, null, 2)}\n`);
console.log(`wrote ${verify.length} verify cases, ${rules.length} rule cases (${rules.reduce((n, c) => n + (c.expected?.length ?? 0), 0)} findings), ${p256Cases.length} P-256 cases, ${credentialKeys.length} key cases to ${out}`);
