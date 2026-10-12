// Runner and model profiles in the kit (Fabric Agent Contract DEC-0046, Fabric ADR-0147). A port of the contract's
// `src/profile-rules.ts` at the pin — resolveModelProfile and the FAC-SEM-058…060 checks — held to the contract's own
// answers by test/fixtures/contract/profile-vectors.json; plus the doctor's runner and model checks (runners.md C2) and
// the well-known `configuration` with its summary tiles ("Runner & model"). No dependencies.

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { secretValue } from './fabric-secrets.mjs';
import { configurationProblems } from './fabric-service.mjs';

export const RESOLUTION_ORDER = Object.freeze(['request', 'agent', 'binding', 'estate']);
/** The vendor login each subscription is, and the one runner kind it runs in (DEC-0046, ADR-0147 decision 2). */
export const SUBSCRIPTION_RUNNER = Object.freeze({ claude: 'claude-code', kimi: 'kimi-code', chatgpt: 'codex' });
export const MAX_PROBE_MS = 5000;
const BARE_BINARY = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

export class ProfileError extends Error {}

const isObject = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);
const list = (value) => (Array.isArray(value) ? value.filter(isObject) : []);
const strings = (value) => (Array.isArray(value) ? value.filter((item) => typeof item === 'string') : []);
const jsonEqual = (a, b) => JSON.stringify(sortKeys(a)) === JSON.stringify(sortKeys(b));
function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (isObject(value)) return Object.fromEntries(Object.keys(value).sort().map((k) => [k, sortKeys(value[k])]));
  return value;
}

/** FAC-SEM-060: the request's profile, else the agent's, else the binding's or project's, else the estate default. */
export function resolveModelProfile({ catalogue, profiles, choices = {}, policy } = {}) {
  const level = RESOLUTION_ORDER.find((name) => typeof choices?.[name] === 'string');
  if (level === undefined) return { refused: 'no-profile' };
  const id = choices[level];
  const profile = list(profiles).find((item) => item.id === id);
  if (!profile) return { refused: 'unknown-profile', profile: id };
  const models = strings(profile.models);
  if (!isObject(policy) || !Array.isArray(policy.modelClasses)) return { from: level, profile: id, models };
  const allowed = new Set(strings(policy.modelClasses));
  const rows = new Map(list(isObject(catalogue) ? catalogue.models : undefined).map((row) => [row.id, row]));
  const within = models.filter((model) => { const row = rows.get(model); return row !== undefined && strings(row.classes).every((name) => allowed.has(name)); });
  if (within.length) return { from: level, profile: id, models: within };
  const meta = isObject(policy.meta) ? policy.meta : {};
  return { refused: 'model-classes-empty', profile: id, policy: { id: String(meta.id), revision: Number(meta.revision) } };
}

const finding = (code, instancePath, message) => ({ code, instancePath, message });

function modelCatalogue(value) {
  const findings = [];
  const seen = new Set();
  list(value.models).forEach((row, index) => {
    if (seen.has(row.id)) findings.push(finding('FAC-SEM-058', `/models/${index}/id`, `model ${String(row.id)} is catalogued more than once`));
    seen.add(row.id);
    const routing = isObject(row.provider) ? row.provider : {};
    const ignored = new Set(strings(routing.ignore));
    for (const slug of strings(routing.order)) {
      if (ignored.has(slug) || ignored.has(slug.split('/')[0])) findings.push(finding('FAC-SEM-058', `/models/${index}/provider`, `model ${String(row.id)} both orders and ignores provider ${slug}`));
    }
  });
  return findings;
}

function modelProfiles(value) {
  const findings = [];
  const seen = new Set();
  list(value.profiles).forEach((profile, index) => {
    if (seen.has(profile.id)) findings.push(finding('FAC-SEM-058', `/profiles/${index}/id`, `model profile ${String(profile.id)} is declared more than once`));
    seen.add(profile.id);
  });
  return findings;
}

function runnerProfile(value) {
  const findings = [];
  if (value.route === 'subscription' && isObject(value.subscription)) {
    const login = String(value.subscription.login);
    const runner = Object.hasOwn(SUBSCRIPTION_RUNNER, login) ? SUBSCRIPTION_RUNNER[login] : undefined;
    if (runner !== value.runnerKind) findings.push(finding('FAC-SEM-059', '/runnerKind', `a ${login} subscription runs only in ${runner ?? "its vendor's runner"}, not in ${String(value.runnerKind)}; another runner takes the key route`));
  }
  if (value.route === 'key' && isObject(value.key)) {
    if (value.key.modelAllowList !== value.modelProfile) findings.push(finding('FAC-SEM-059', '/key/modelAllowList', `the key admits the models of ${String(value.key.modelAllowList)}, but the profile runs ${String(value.modelProfile)}`));
    if (typeof value.key.ref === 'string' && secretValue(value.key.ref)) findings.push(finding('FAC-SEM-059', '/key/ref', 'the key is named by its secret reference, never by its value'));
  }
  return findings;
}

function profileResolution(value) {
  const findings = [];
  const catalogued = new Set(list(isObject(value.catalogue) ? value.catalogue.models : undefined).map((row) => row.id));
  const ids = new Set();
  list(value.profiles).forEach((profile, i) => {
    if (ids.has(profile.id)) findings.push(finding('FAC-SEM-060', `/profiles/${i}/id`, `profile id ${String(profile.id)} is offered more than once to one resolution`));
    ids.add(profile.id);
    strings(profile.models).forEach((model, j) => {
      if (!catalogued.has(model)) findings.push(finding('FAC-SEM-060', `/profiles/${i}/models/${j}`, `profile ${String(profile.id)} names ${model}, which the catalogue does not hold`));
    });
  });
  const choices = isObject(value.choices) ? value.choices : {};
  const expected = resolveModelProfile({ catalogue: value.catalogue, profiles: value.profiles, choices, policy: value.policy });
  if (value.resolved === undefined || !jsonEqual(value.resolved, expected)) findings.push(finding('FAC-SEM-060', '/resolved', `the resolution is ${JSON.stringify(expected)}`));
  return findings;
}

/** The contract's profileRules: findings for a model-catalogue, model-profiles, runner-profile or profile-resolution; else undefined. */
export function profileProblems(kind, value) {
  return { 'model-catalogue': modelCatalogue, 'model-profiles': modelProfiles, 'runner-profile': runnerProfile, 'profile-resolution': profileResolution }[kind]?.(value);
}

// ---- the doctor's checks ----

const argvOf = (value, label) => {
  if (!Array.isArray(value) || !value.every((a) => typeof a === 'string')) throw new ProfileError(`${label} is an argument array, never a shell string`);
  return [...value];
};

function which(name, searchPath) {
  for (const dir of String(searchPath ?? '').split(path.delimiter).filter(Boolean)) {
    const candidate = path.join(dir, name);
    try { fs.accessSync(candidate, fs.constants.X_OK); if (fs.statSync(candidate).isFile()) return candidate; } catch { /* next */ }
  }
  return null;
}

/**
 * runners.md C2: is the catalogued runner installed, which version answers, and is it signed in. Only a bare
 * catalogued binary on PATH is run, only with the catalogued version (and auth) argv, without a shell, within its
 * timeout (at most 5 s). An entry outside these rules is refused and nothing runs.
 */
export function runnerCheck(entry, { searchPath = process.env.PATH, run = spawnSync } = {}) {
  const { kind, binaries } = entry ?? {};
  if (!Array.isArray(binaries) || !binaries.length || !binaries.every((b) => typeof b === 'string' && BARE_BINARY.test(b) && !b.includes('..'))) throw new ProfileError('binaries are bare executable names, never paths');
  const version = isObject(entry.version) ? entry.version : {};
  const versionArgv = argvOf(version.argv, 'version.argv');
  if (typeof version.pattern !== 'string') throw new ProfileError('version.pattern is a regular expression');
  const timeoutMs = version.timeoutMs ?? MAX_PROBE_MS;
  if (!Number.isInteger(timeoutMs) || timeoutMs <= 0 || timeoutMs > MAX_PROBE_MS) throw new ProfileError(`version.timeoutMs is at most ${MAX_PROBE_MS}`);
  const authArgv = 'auth' in entry ? argvOf(entry.auth, 'auth') : null;
  const out = { kind, installed: false, binary: null, version: null, signedIn: null, problems: [] };
  const binary = binaries.map((name) => which(name, searchPath)).find(Boolean) ?? null;
  if (!binary) { out.problems.push(`${kind} is not installed: none of ${binaries.join(', ')} is on PATH`); return out; }
  Object.assign(out, { installed: true, binary });
  const probe = (argv) => {
    const result = run(binary, argv, { encoding: 'utf8', timeout: timeoutMs, shell: false });
    if (result.error?.code === 'ETIMEDOUT' || result.signal === 'SIGTERM') { out.problems.push(`${kind} ${argv.join(' ')} did not answer within ${timeoutMs} ms`); return null; }
    if (result.error) { out.problems.push(`${kind} could not be run: ${result.error.code ?? result.error.name}`); return null; }
    return result;
  };
  const answered = probe(versionArgv);
  if (answered) {
    const re = new RegExp(version.pattern);
    const match = re.exec(answered.stdout ?? '') ?? re.exec(answered.stderr ?? '');
    if (match && match.length > 1) out.version = match[1];
    else out.problems.push(`${kind} answered, but its version did not match the catalogue's pattern`);
  }
  if (authArgv) {
    const signed = probe(authArgv);
    if (signed) { out.signedIn = signed.status === 0; if (!out.signedIn) out.problems.push(`${kind} is installed but not signed in`); }
  }
  return out;
}

/** Problems with running `model` here: not in the catalogue, or a class the project's policy does not allow. */
export function modelUsable(model, catalogue, policy) {
  const rows = new Map(list(isObject(catalogue) ? catalogue.models : undefined).map((row) => [row.id, row]));
  if (!rows.has(model)) return [`model ${model} is not in the model catalogue`];
  if (isObject(policy) && Array.isArray(policy.modelClasses)) {
    const allowed = new Set(strings(policy.modelClasses));
    const outside = strings(rows.get(model).classes).filter((c) => !allowed.has(c));
    if (outside.length) return [`model ${model} has class ${outside.join(', ')}, which policy ${String((isObject(policy.meta) ? policy.meta : {}).id)} does not allow`];
  }
  return [];
}

// ---- the well-known `configuration` and its tiles ----

/** The well-known `configuration` (DEC-0046): read-only; a change is made in Fabric and reaches the agent through its binding. */
export function configuration(slots, resolution, runnerProfileDoc) {
  if ('refused' in resolution) throw new ProfileError(`the resolution was refused (${resolution.refused}); a refused resolution is not a configuration`);
  const resolved = { from: resolution.from };
  if (runnerProfileDoc) Object.assign(resolved, { runnerProfile: runnerProfileDoc.id, runnerKind: runnerProfileDoc.runnerKind, route: runnerProfileDoc.route });
  Object.assign(resolved, { modelProfile: resolution.profile, models: [...(resolution.models ?? [])] });
  const doc = { slots: [...slots], resolved: Object.fromEntries(Object.entries(resolved).filter(([, v]) => v !== undefined && v !== null)) };
  const problems = configurationProblems(doc);
  if (problems.length) throw new ProfileError(problems.join('; '));
  return doc;
}

/** Summary tiles for the well-known document and the dashboard — "Runner & model". */
export function configurationSummary(doc) {
  const resolved = doc?.resolved ?? {};
  const tiles = [];
  if (resolved.runnerKind) tiles.push({ label: 'Runner', value: [resolved.runnerKind, resolved.route].filter(Boolean).join(' · ') });
  if (resolved.modelProfile) tiles.push({ label: 'Model', value: [resolved.modelProfile, (resolved.models ?? [])[0]].filter(Boolean).join(' · ') });
  return tiles;
}
