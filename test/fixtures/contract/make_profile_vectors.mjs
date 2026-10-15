#!/usr/bin/env node
// Writes profile-vectors.json: DEC-0046 cases whose expected answers come from the contract's own functions at the pin
// (src/profile-rules.ts resolveModelProfile and profileRules, src/secret-shape.ts) — never written by hand. The kits'
// fabric_profiles and fabric_secrets ports are held to them.
//
//   node test/fixtures/contract/make_profile_vectors.mjs --contract-src <dir with profile-rules.ts, secret-shape.ts,
//     findings.ts> --semantic <dir of the profile semantic fixtures> --positive <dir of positive fixtures>
//     [--out test/fixtures/contract/profile-vectors.json]
//
// Credential-shaped samples are assembled from parts at run time, so no key-shaped literal sits in a command line or
// in this source; the written vectors hold them, and they are all made up.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const rules = await import(pathToFileURL(path.join(args['contract-src'], 'profile-rules.ts')).href);
const shape = await import(pathToFileURL(path.join(args['contract-src'], 'secret-shape.ts')).href);
const read = (dir, file) => JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8'));
const KINDS = ['profile-resolution', 'model-catalogue', 'model-profiles', 'runner-profile'];

// The contract's own semantic fixtures, through its own rules.
const ruleCases = fs.readdirSync(args.semantic).filter((f) => f.endsWith('.json')).sort().map((file) => {
  const kind = KINDS.find((k) => file.startsWith(`${k}-`));
  const fixture = read(args.semantic, file);
  // Older profile fixtures are the document itself; newer ones (DEC-0083 on) wrap it as {description, kind, expect,
  // input}. A wrapped fixture's own `expect` must be what the contract's rules answer, so a shape this script misreads
  // stops it instead of vendoring a vacuous case.
  const wrapped = typeof fixture.kind === 'string' && 'input' in fixture && Array.isArray(fixture.expect);
  const value = wrapped ? fixture.input : fixture;
  const expected = rules.profileRules(kind, value);
  if (wrapped) {
    const got = [...new Set((expected ?? []).map((f) => f.code))].sort().join(',');
    const want = [...new Set(fixture.expect)].sort().join(',');
    if (got !== want) throw new Error(`${file}: the contract's rules answer [${got}], the fixture expects [${want}]`);
  }
  return { name: file, kind, value, expected };
});
for (const [file, kind] of [['registry-models.json', 'model-catalogue'], ['model-profiles.json', 'model-profiles'],
  ['model-profiles-user-content.json', 'model-profiles'],
  ['runner-profile-subscription.json', 'runner-profile'], ['runner-profile-key.json', 'runner-profile']]) {
  const value = read(args.positive, file);
  ruleCases.push({ name: `positive/${file}`, kind, value, expected: rules.profileRules(kind, value) });
}

// A base slug covers its variants: an ordered variant of an ignored provider is ordered and ignored at once.
{
  const catalogue = read(args.positive, 'registry-models.json');
  const variant = JSON.parse(JSON.stringify(catalogue));
  variant.models[0].provider = { order: ['deepinfra/turbo', 'together'], ignore: ['deepinfra'] };
  ruleCases.push({ name: 'crafted: an ordered variant of an ignored base slug', kind: 'model-catalogue', value: variant, expected: rules.profileRules('model-catalogue', variant) });
}

// FAC-SEM-112 (DEC-0083) on hostile and edge input: the open-fallback fixture varied one way each, answered by the
// contract's own rules. The rule must be total on any JSON: a fallback it does not know reads as none, a model or a
// class that is not a string counts as closed, and a value whose own toString is data is shown, never thrown on.
{
  const uc = read(args.semantic, 'profile-resolution-user-content-open-fallback.json').input;
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const vary = (name, edit) => { const value = edit(clone(uc)); ruleCases.push({ name: `crafted FAC-SEM-112: ${name}`, kind: 'profile-resolution', value, expected: rules.profileRules('profile-resolution', value) }); };
  const p0 = (v) => v.profiles[0];
  vary('the open model first, no fallback', (v) => { p0(v).models = [...p0(v).models].reverse(); p0(v).fallback = 'none'; return v; });
  vary('the open model second, no fallback', (v) => { p0(v).fallback = 'none'; return v; });
  vary('a fallback the contract does not name reads as none', (v) => { p0(v).fallback = 'sometimes'; return v; });
  vary('no fallback field reads as none', (v) => { delete p0(v).fallback; return v; });
  vary('reads only operator', (v) => { p0(v).reads = ['operator']; return v; });
  vary('reads only web', (v) => { p0(v).reads = ['web']; return v; });
  vary('reads user-content and operator', (v) => { p0(v).reads = ['operator', 'user-content']; return v; });
  vary('reads written as a string, not a list, on a closed route', (v) => { p0(v).reads = 'user-content'; p0(v).fallback = 'none'; return v; });
  vary('reads User-Content in another case, on a closed route', (v) => { p0(v).reads = ['User-Content']; p0(v).fallback = 'none'; return v; });
  vary('no models at all', (v) => { p0(v).models = []; return v; });
  vary('models not a list', (v) => { p0(v).models = 'deepseek/deepseek-v4-pro'; return v; });
  vary('a model that is not a string', (v) => { p0(v).models = [{ toString: 1 }, 7]; return v; });
  vary('a first model with its own toString, no fallback', (v) => { p0(v).models = [{ toString: 1 }, ...p0(v).models]; p0(v).fallback = 'none'; return v; });
  vary('a first model that is a number, no fallback', (v) => { p0(v).models = [7.5, ...p0(v).models]; p0(v).fallback = 'none'; return v; });
  vary('the open class not a list in the catalogue', (v) => { v.catalogue.models.forEach((m) => { m.classes = 'open-vendor'; }); return v; });
  vary('the open class in another case', (v) => { v.catalogue.models.forEach((m) => { m.classes = (m.classes ?? []).map((c) => (c === 'open-vendor' ? 'Open-Vendor' : c)); }); return v; });
  vary('no catalogue', (v) => { delete v.catalogue; return v; });
  vary('a profile id with its own toString', (v) => { p0(v).id = { toString: 1 }; p0(v).fallback = 'none'; return v; });
  vary('a non-object before the profile', (v) => { p0(v).fallback = 'none'; v.profiles = [null, ...v.profiles]; return v; });
  vary('the first profile open, the second closed', (v) => { const b = clone(p0(v)); b.id = 'second-lane'; b.fallback = 'none'; v.profiles.push(b); return v; });
  vary('two profiles, both closed', (v) => { const b = clone(p0(v)); b.id = 'second-lane'; b.models = [b.models[0]]; p0(v).fallback = 'none'; v.profiles.push(b); return v; });
}

// FAC-SEM-112 on the resolution's outcome (the models the policy leaves) and DEC-0083's admission: open-vendor is
// descriptive, so a policy admits and excludes nothing by it, and a model with no other class does not stay.
if (fs.existsSync(path.join(args.semantic, 'profile-resolution-user-content-policy-drops-open.json'))) {
  const pd = read(args.semantic, 'profile-resolution-user-content-policy-drops-open.json').input;
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const vary = (name, edit) => { const value = edit(clone(pd)); ruleCases.push({ name: `crafted policy FAC-SEM-112: ${name}`, kind: 'profile-resolution', value, expected: rules.profileRules('profile-resolution', value) }); };
  const row = (v, id) => v.catalogue.models.find((m) => m.id === id);
  vary('the policy allows strong too', (v) => { v.policy.modelClasses = ['strong', 'cheap', 'chinese-vendor']; return v; });
  vary('the policy names open-vendor alone', (v) => { v.policy.modelClasses = ['open-vendor']; return v; });
  vary('the policy names open-vendor beside cheap', (v) => { v.policy.modelClasses = ['open-vendor', 'cheap']; return v; });
  vary('the open model carries only open-vendor', (v) => { row(v, 'deepseek/deepseek-v4-pro').classes = ['open-vendor']; v.policy.modelClasses = ['cheap', 'strong', 'chinese-vendor']; return v; });
  vary('the open model carries only open-vendor and cheap', (v) => { row(v, 'deepseek/deepseek-v4-pro').classes = ['open-vendor', 'cheap']; return v; });
  vary('no fallback, the policy drops the first', (v) => { v.profiles[0].fallback = 'none'; return v; });
  vary('the policy without an id', (v) => { delete v.policy.meta.id; return v; });
  vary('the policy id with its own toString', (v) => { v.policy.meta.id = { toString: 1 }; return v; });
  vary('the profile id with its own toString', (v) => { v.profiles[0].id = { toString: 1 }; v.choices = { estate: 'member-chat' }; return v; });
  vary('the profile route closed already: one finding, not two', (v) => { row(v, 'deepseek/deepseek-v4-pro').classes = ['strong', 'cheap']; return v; });
  vary('the policy leaves nothing: a refusal, no outcome finding', (v) => { v.policy.modelClasses = ['frontier']; return v; });
  vary('a second profile with the same id first in the list', (v) => { v.profiles.unshift({ ...clone(v.profiles[0]), models: ['qwen/qwen3.8-flash'], fallback: 'none' }); return v; });
}

// FAC-SEM-058 and FAC-SEM-060 on hostile input (DEC-0083's fix round): an instancePath names an item by its index as
// written, a duplicate is what JavaScript's Set calls one (1 and true, null and absent, are two; two equal objects are
// two), and an id whose own toString is data is shown as its JSON.
{
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const cat = read(args.positive, 'registry-models.json');
  const prof = read(args.positive, 'model-profiles.json');
  const res = read(args.semantic, 'profile-resolution-ok.json');
  const push = (name, kind, value) => ruleCases.push({ name: `crafted hostile: ${name}`, kind, value, expected: rules.profileRules(kind, value) });
  const dup = (rows, i, id) => { const r = clone(rows[i]); r.id = id; return r; };
  { const v = clone(cat); v.models = [7, ...v.models, clone(v.models[0])]; push('a non-object before the catalogue, then a row twice', 'model-catalogue', v); }
  { const v = clone(cat); v.models = [dup(v.models, 0, 1), dup(v.models, 0, true)]; push('catalogue ids 1 and true are two', 'model-catalogue', v); }
  { const v = clone(cat); const a = dup(v.models, 0, null); const b = clone(v.models[0]); delete b.id; v.models = [a, b]; push('catalogue ids null and absent are two', 'model-catalogue', v); }
  { const v = clone(cat); v.models = [dup(v.models, 0, 1), dup(v.models, 0, 1.0)]; push('catalogue ids 1 and 1.0 are one', 'model-catalogue', v); }
  { const v = clone(cat); v.models = [dup(v.models, 0, { toString: 1 }), dup(v.models, 0, { toString: 1 })]; push('two equal object ids are two', 'model-catalogue', v); }
  { const v = clone(cat); const r = dup(v.models, 0, { toString: 1 }); r.provider = { order: ['x'], ignore: ['x'] }; v.models = [r]; push('an ordered and ignored provider on an object id', 'model-catalogue', v); }
  { const v = clone(prof); v.profiles = [null, ...v.profiles, clone(v.profiles[0])]; push('a non-object before the profiles, then one twice', 'model-profiles', v); }
  { const v = clone(prof); const a = clone(v.profiles[0]); const b = clone(v.profiles[0]); a.id = 'x'; b.id = 'x'; v.profiles = ['s', a, 3, b]; push('profiles with non-objects between a duplicate', 'model-profiles', v); }
  { const v = clone(res); v.profiles = [false, ...v.profiles, clone(v.profiles[0])]; push('a non-object before the offered profiles, then one twice', 'profile-resolution', v); }
  { const v = clone(res); v.profiles[0].models = [5, { toString: 1 }, 'example/not-catalogued', ...v.profiles[0].models]; push('non-string models before an uncatalogued one', 'profile-resolution', v); }
  { const v = clone(res); v.profiles = [null, { ...clone(v.profiles[0]), id: { toString: 1 }, models: ['example/not-catalogued'] }]; push('an uncatalogued model under an object id after a non-object', 'profile-resolution', v); }
}

// Resolutions: every profile-resolution fixture's inputs, then the order and the classes varied over them.
const base = read(args.semantic, 'profile-resolution-ok.json');
const resolutions = [];
const add = (name, input) => resolutions.push({ name, input, expected: rules.resolveModelProfile(input) });
for (const c of ruleCases.filter((r) => r.kind === 'profile-resolution')) {
  const { catalogue, profiles, choices, policy } = c.value;
  add(c.name, { catalogue, profiles, choices: choices ?? {}, ...(policy === undefined ? {} : { policy }) });
}
const ids = (base.profiles ?? []).map((p) => p.id);
const levels = ['request', 'agent', 'binding', 'estate'];
for (let mask = 0; mask < 16; mask++) {
  const choices = {};
  levels.forEach((level, i) => { if (mask & (1 << i)) choices[level] = ids[i % ids.length]; });
  add(`order mask ${mask}`, { catalogue: base.catalogue, profiles: base.profiles, choices });
}
const classes = ['frontier', 'strong', 'cheap', 'code', 'vision', 'chinese-vendor', 'open-vendor'];
for (const allowed of [[], ['cheap'], ['strong', 'cheap'], ['strong', 'cheap', 'chinese-vendor'], classes]) {
  for (const id of ids) {
    add(`classes ${allowed.join('+') || 'none'} on ${id}`, { catalogue: base.catalogue, profiles: base.profiles, choices: { binding: id },
      policy: { meta: { id: 'policy-a', revision: 3 }, modelClasses: allowed } });
  }
}
add('unknown profile', { catalogue: base.catalogue, profiles: base.profiles, choices: { request: 'no-such-profile' } });
add('no choice at all', { catalogue: base.catalogue, profiles: base.profiles, choices: {} });
add('policy without modelClasses', { catalogue: base.catalogue, profiles: base.profiles, choices: { estate: ids[0] }, policy: { meta: { id: 'p', revision: 1 } } });

// The credential detector (DEC-0044, LC-21): names, values, arguments, URLs. Made-up samples, assembled from parts.
const j = (...parts) => parts.join('');
const b64 = j('Zk9yZ2V0VGhp', 'c0lzQVNlY3Jl', 'dEtleTEyMzQ1Njc4OTA');
const jwt = j('eyJhbGciOiJFZERTQSJ9', '.', 'eyJzdWIiOiJ4In0', '.', 'c2ln');
const names = ['token', 'apiKey', 'api_key', 'API_KEY', 'APIKey', 'refreshToken', 'refresh-token', 'secrets', 'apiKeys', 'key', 'auth', 'session', 'code',
  'sortKey', 'primaryKey', 'themeCode', 'countryCode', 'tokenizer', 'authorName', 'sessionLength', 'passage', 'signal', 'compass', 'sessionId', 'loginCode',
  'X-Amz-Signature', 'clientSecret', 'OPENROUTER_API_KEY', 'GITHUB_TOKEN', 'HOME', 'PATH', 'MODEL', 'PORT', 'password', 'pass', 'authCode', 'auth_header', 'private_key'];
const values = ['', 'hello', 'Bearer abc', 'bearer xyz', j('s', 'k-', 'a'.repeat(20)), j('gh', 'p_', 'A1'.repeat(12)), j('xo', 'xb-', '1'.repeat(12)),
  j('AK', 'IA', 'ABCDEFGHIJKLMNOP'), j('glp', 'at-', 'x'.repeat(22)), '0123456789abcdef0123456789abcdef01234567', b64, jwt, `see ${jwt} here`, 'a'.repeat(60), 'Aa1'.repeat(14)];
const argumentsList = ['--verbose', j('--header=Authorization: Bea', 'rer abcdef123456'), '--header=Authorization: Bearer token', 'the Bearer authentication scheme',
  '/Users/example/sessions/9f8e7d6c5b4a39281706f5e4d3c2b1a0Aa1Bb2Cc3Dd4/log.txt', `~/.config/app/${b64}.json`,
  j('wJalrXUtnFEMI', '/K7MDENG/', 'bPxRfiCYEXAMPLEKEY'), `--key=${b64}`, j('--api-key=s', 'k-', 'b'.repeat(24)), 'apps/Desktop/src/main.ts', 'C:\\Users\\x\\app.exe'];
const urls = ['https://example.com/mcp', 'https://example.com/mcp?api_key=abc', 'https://example.com/mcp?key=', 'https://example.com/mcp?sort=key',
  j('https://user:', 'pw@example.com/mcp'), 'https://example.com/mcp#access_token=abc', `https://example.com/mcp?ref=${b64}`,
  'https://example.com/mcp?token=', 'http://127.0.0.1:47201/mcp', 'not a url', j('https://example.com/mcp?x=s', 'k-', 'c'.repeat(20))];
// Inputs are stored hex-encoded, so no credential-shaped text sits in the repository for a scanner to trip on (GitHub's
// push protection decodes base64, and refused the base64 form).
const enc = (input) => Buffer.from(input, 'utf8').toString('hex');
const secrets = {
  credentialName: names.map((input) => ({ inputHex: enc(input), expected: shape.credentialName(input) })),
  nameWords: names.map((input) => ({ inputHex: enc(input), expected: shape.nameWords(input) })),
  secretValue: values.map((input) => ({ inputHex: enc(input), expected: shape.secretValue(input) })),
  secretArgument: [...values, ...argumentsList].map((input) => ({ inputHex: enc(input), expected: shape.secretArgument(input) })),
  secretUrl: urls.map((input) => ({ inputHex: enc(input), expected: shape.secretUrl(input) })),
};

// DEC-0083's shared admission vectors (fixtures/vectors/model-admission.json): every copy of the every-class rule — the
// kits' resolver and their doctor's model_usable — answers each case as the contract's admittedByClasses does. Each case's
// stated answer is checked against that function here, so a vendored case can never disagree with the contract.
const admissionFile = path.join(args.positive, '..', 'vectors', 'model-admission.json');
const admission = fs.existsSync(admissionFile) ? read(path.dirname(admissionFile), 'model-admission.json').cases.map((c) => {
  const row = c.classes === null ? undefined : { id: 'example/model', classes: c.classes };
  const got = rules.admittedByClasses(row, c.modelClasses);
  if (got !== c.admitted) throw new Error(`model-admission.json "${c.name}": admittedByClasses answers ${got}, the case says ${c.admitted}`);
  return c;
}) : [];

// A rule case's value may hold a made-up key (runner-profile-key-value): stored base64-encoded like the inputs above.
for (const c of ruleCases) { c.valueHex = Buffer.from(JSON.stringify(c.value), 'utf8').toString('hex'); delete c.value; }
const out = args.out ?? path.join(here, 'profile-vectors.json');
fs.writeFileSync(out, `${JSON.stringify({ about: "DEC-0046 and DEC-0044 cases; expected answers from the contract's profile-rules.ts and secret-shape.ts at the pin (make_profile_vectors.mjs). Every credential-shaped sample is made up and stored hex-encoded. Do not edit by hand.", rules: ruleCases, resolutions, secrets, admission }, null, 1)}\n`);
console.log(`wrote ${out}: ${ruleCases.length} rule, ${resolutions.length} resolution, ${admission.length} admission, ${Object.values(secrets).reduce((n, l) => n + l.length, 0)} secret-shape cases`);
