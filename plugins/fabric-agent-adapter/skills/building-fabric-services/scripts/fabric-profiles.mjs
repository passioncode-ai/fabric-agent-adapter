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
 *
 * `probe` is the contract's closed probe result for a walk (DEC-0026): `not-installed`, `not-responding` (the version
 * probe did not answer, failed or did not match), `not-connected` (signed out by the `auth` probe), or null when the
 * runner can serve. The twin of fabric_profiles.runner_check.
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
  const out = { kind, installed: false, binary: null, version: null, signedIn: null, probe: 'not-installed', problems: [] };
  const binary = binaries.map((name) => which(name, searchPath)).find(Boolean) ?? null;
  if (!binary) { out.problems.push(`${kind} is not installed: none of ${binaries.join(', ')} is on PATH`); return out; }
  Object.assign(out, { installed: true, binary, probe: 'not-responding' });
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
  const signed = authArgv ? probe(authArgv) : null;
  if (signed) { out.signedIn = signed.status === 0; if (!out.signedIn) out.problems.push(`${kind} is installed but not signed in`); }
  // The walk's order (runners.md): installed, then responding, then connected. The doctor still reports every problem.
  if (out.version === null || (authArgv && !signed)) out.probe = 'not-responding';
  else if (out.signedIn === false) out.probe = 'not-connected';
  else out.probe = null;
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

// ---- runner routes (DEC-0026, DEC-0029; FAC-SEM-028…034) ----
// The contract's routeRules (src/route-rules.ts), finding for finding: code, path and message. The twin of
// fabric_profiles.route_problems.

/** The closed probe results a walk records for a candidate it passed over (runner-route-event.schema.json). */
export const PROBE_RESULTS = Object.freeze(['not-catalogued', 'not-admitted', 'not-installed', 'not-responding', 'not-connected', 'no-held-session', 'quota-unknown', 'refused', 'spawn-failed']);

const routeCandidates = (value) => (Array.isArray(value?.candidates) ? value.candidates.filter(isObject) : []);
const objectAt = (value, key) => (isObject(value?.[key]) ? value[key] : {});
const refKey = (ref) => (isObject(ref) ? `${String(ref.id)}@${String(ref.revision)}#${String(ref.contentHash)}` : '');
const sameRef = (a, b) => refKey(a) !== '' && refKey(a) === refKey(b);

function runnerRoute(value) {
  const findings = [];
  const kinds = new Set();
  routeCandidates(value).forEach((candidate, index) => {
    const kind = String(candidate.runnerKind);
    if (kinds.has(kind)) findings.push(finding('FAC-SEM-028', `/candidates/${index}/runnerKind`, `runner kind ${kind} appears in the route more than once`));
    kinds.add(kind);
    const session = objectAt(candidate, 'session');
    if (session.attach === 'never' && session.spawn === 'never') findings.push(finding('FAC-SEM-029', `/candidates/${index}/session`, `candidate ${kind} can never run: attach and spawn are both "never"`));
  });
  return findings;
}

function routeBundle(value) {
  const route = objectAt(value, 'route');
  const admissions = Array.isArray(value.admissions) ? value.admissions.filter(isObject) : [];
  const admitted = new Set(admissions.filter((a) => a.state === 'admitted' && a.capability === route.capability).map((a) => refKey(a.provider)));
  const findings = [];
  routeCandidates(route).forEach((candidate, index) => {
    const key = refKey(candidate.provider);
    if (!admitted.has(key)) findings.push(finding('FAC-SEM-030', `/route/candidates/${index}/provider`, `candidate ${String(candidate.runnerKind)} names provider ${key}, which is not a revision admitted for ${String(route.capability)}`));
  });
  if (isObject(value.binding)) {
    const binding = value.binding;
    const disagree = (where, message) => findings.push(finding('FAC-SEM-032', `/binding/${where}`, message));
    if (binding.project !== route.project) disagree('project', `the binding is for ${String(binding.project)}, the route for ${String(route.project)}`);
    if (binding.capability !== route.capability) disagree('capability', `the binding binds ${String(binding.capability)}, the route orders ${String(route.capability)}`);
    if (binding.profileKind !== 'local-runner') disagree('profileKind', `a runner route serves the local-runner profile, not ${String(binding.profileKind)}`);
    if (!routeCandidates(route).some((c) => sameRef(c.provider, binding.provider))) disagree('provider', `the binding's provider ${refKey(binding.provider)} is not a candidate of the route`);
    if (binding.runnerRoute !== undefined && !sameRef(binding.runnerRoute, route.meta)) disagree('runnerRoute', `the binding pins ${refKey(binding.runnerRoute)}, not this route ${refKey(route.meta)}`);
  }
  if (Array.isArray(value.catalogue)) {
    const byKind = new Map(value.catalogue.filter(isObject).map((entry) => [String(entry.kind), entry]));
    routeCandidates(route).forEach((candidate, index) => {
      const kind = String(candidate.runnerKind);
      const entry = byKind.get(kind);
      if (!entry) { findings.push(finding('FAC-SEM-033', `/route/candidates/${index}/runnerKind`, `runner kind ${kind} has no entry in the host's catalogue`)); return; }
      if (candidate.drive !== undefined && !Object.hasOwn(objectAt(entry, 'drives'), String(candidate.drive))) findings.push(finding('FAC-SEM-033', `/route/candidates/${index}/drive`, `the catalogue entry for ${kind} offers no drive ${String(candidate.drive)}`));
    });
  }
  return findings;
}

function routeEvent(value) {
  const route = objectAt(value, 'route');
  const event = objectAt(value, 'event');
  const list = routeCandidates(route);
  const findings = [];
  const wrong = (where, message) => findings.push(finding('FAC-SEM-034', `/event${where}`, message));
  if (!sameRef(event.route, route.meta)) wrong('/route', `the event names route ${refKey(event.route)}, not ${refKey(route.meta)}`);
  if (event.project !== route.project) wrong('/project', `the event is for ${String(event.project)}, the route for ${String(route.project)}`);
  if (event.capability !== route.capability) wrong('/capability', `the event names ${String(event.capability)}, the route orders ${String(route.capability)}`);
  const indexOf = (ref) => (typeof ref.index === 'number' && Number.isInteger(ref.index) ? ref.index : -1);
  const candidateAt = (ref, where) => {
    const index = indexOf(ref);
    const candidate = index >= 0 ? list[index] : undefined;
    if (!candidate || candidate.runnerKind !== ref.runnerKind || (ref.provider !== undefined && !sameRef(candidate.provider, ref.provider))) {
      wrong(where, `candidate ${String(ref.index)} (${String(ref.runnerKind)}) is not that position of the route`);
      return undefined;
    }
    return candidate;
  };
  const probes = Array.isArray(event.probes) ? event.probes.filter(isObject) : [];
  probes.forEach((probe, position) => {
    const candidate = candidateAt(probe, `/probes/${position}`);
    if (candidate && probe.result === 'no-held-session' && objectAt(candidate, 'session').spawn !== 'never') wrong(`/probes/${position}/result`, `${String(probe.runnerKind)} may spawn, so finding no held session does not pass it over`);
    if (candidate && probe.result === 'spawn-failed' && objectAt(candidate, 'session').spawn !== 'allowed') wrong(`/probes/${position}/result`, `${String(probe.runnerKind)} has spawn: never, so it cannot have failed to spawn`);
  });
  const expectProbes = (count) => {
    const indexes = probes.map(indexOf);
    const expected = Array.from({ length: Math.max(count, 0) }, (_, index) => index);
    if (indexes.length !== expected.length || indexes.some((index, position) => index !== expected[position])) {
      wrong('/probes', `the walk must record candidates ${expected.join(', ') || 'none'} in order; it records ${indexes.join(', ') || 'none'}`);
    }
  };
  if (event.kind === 'runner-exhausted') {
    expectProbes(list.length);
    if (event.answer === 'held' && route.exhausted !== 'hold') wrong('/answer', 'the route does not declare exhausted: hold, so an exhausted walk answers capability-unavailable');
    return findings;
  }
  const selected = objectAt(event, 'selected');
  const chosen = candidateAt(selected, '/selected');
  if (chosen) {
    const session = objectAt(chosen, 'session');
    if (selected.session === 'attached' && session.attach !== 'preferred') wrong('/selected/session', `${String(selected.runnerKind)} has attach: never, so the host cannot attach it`);
    if (selected.session === 'spawned' && session.spawn !== 'allowed') wrong('/selected/session', `${String(selected.runnerKind)} has spawn: never, so the host cannot spawn it`);
    if (chosen.drive !== undefined && selected.drive !== undefined && selected.drive !== chosen.drive) wrong('/selected/drive', `the route runs ${String(selected.runnerKind)} through ${String(chosen.drive)}, not ${String(selected.drive)}`);
    if (event.sticky === true) {
      // A sticky relaunch keeps the conversation's runner and walks nothing above it.
      if (route.recovery === 'reprobe') wrong('/sticky', 'a route with recovery: reprobe walks from the top at every launch');
      if (event.conversation === undefined) wrong('/sticky', 'only a conversation can keep its runner');
      expectProbes(0);
    } else expectProbes(indexOf(selected));
  }
  if (event.kind === 'runner-switched') {
    const from = objectAt(event, 'from');
    candidateAt(from, '/from');
    if (indexOf(from) === indexOf(selected)) wrong('/from', 'a switch moves to another candidate');
    if (event.reason === 'preferred-available') {
      if (route.recovery !== 'reprobe') wrong('/reason', 'only a route with recovery: reprobe moves a conversation back to a preferred runner');
      if (!(indexOf(selected) < indexOf(from))) wrong('/reason', 'preferred-available moves to a higher-preference candidate');
    }
  }
  return findings;
}

/**
 * The contract's routeRules: findings for a `runner-route` (FAC-SEM-028, 029), a `route-bundle` `{route, admissions,
 * binding?, catalogue?}` (030, 032, 033) or a `route-event` `{route, event}` (034); undefined for another kind or a
 * value that is not an object.
 */
export function routeProblems(kind, value) {
  if (!isObject(value)) return undefined;
  return { 'runner-route': runnerRoute, 'route-bundle': routeBundle, 'route-event': routeEvent }[kind]?.(value);
}
