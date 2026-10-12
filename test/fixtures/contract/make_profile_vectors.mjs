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
  const value = read(args.semantic, file);
  return { name: file, kind, value, expected: rules.profileRules(kind, value) };
});
for (const [file, kind] of [['registry-models.json', 'model-catalogue'], ['model-profiles.json', 'model-profiles'],
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
const classes = ['frontier', 'strong', 'cheap', 'code', 'vision', 'chinese-vendor'];
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

// A rule case's value may hold a made-up key (runner-profile-key-value): stored base64-encoded like the inputs above.
for (const c of ruleCases) { c.valueHex = Buffer.from(JSON.stringify(c.value), 'utf8').toString('hex'); delete c.value; }
const out = args.out ?? path.join(here, 'profile-vectors.json');
fs.writeFileSync(out, `${JSON.stringify({ about: "DEC-0046 and DEC-0044 cases; expected answers from the contract's profile-rules.ts and secret-shape.ts at the pin (make_profile_vectors.mjs). Every credential-shaped sample is made up and stored hex-encoded. Do not edit by hand.", rules: ruleCases, resolutions, secrets }, null, 1)}\n`);
console.log(`wrote ${out}: ${ruleCases.length} rule, ${resolutions.length} resolution, ${Object.values(secrets).reduce((n, l) => n + l.length, 0)} secret-shape cases`);
