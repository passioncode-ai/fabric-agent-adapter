// One instance per context (FAA-125, organization row N-11; contract DEC-0082, "One instance per context on a machine"):
// from a context, `personal` or `org:<orgId>`, the service instance, its folders, descriptor and instance lock.
// Part of the Node service kit (layer L3, after fabric-descriptor); the twin of fabric_context.py, answer for answer
// (test/fixtures/kit-context-cases.json). Node built-ins only. The facade fabric-service.mjs does not re-export it.
// A refusal exits 78 (EX_CONFIG) with nothing created; a second copy for the same context exits 75 as holdSingleInstance does.
// An organization's instance whose context the record does not pin (`organizations`, DEC-0127) still starts: the helper
// checks the placement and its share grant, not the pin (decision D5 of 0.52.0). Its tokens are refused instead:
// hubKeyCertified reads a context's hub keys only while the record pins that organization (DL-14a, DEC-0128), so the
// service passes `estateContext: context` to its delegation gate. A refusal at start would stop every organization
// instance on today's records, which pin none until every reader is pinned at or after DEC-0127.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { INSTANCE, ServiceError } from './fabric-base.mjs';
import { descriptorPath } from './fabric-descriptor.mjs';
import { parseContext } from './fabric-estate.mjs';
import { InstanceLock, holdSingleInstance } from './fabric-lock.mjs';
import { atomicWrite, instanceDirs, servicesDir } from './fabric-paths.mjs';
import { instanceShareGrant } from './fabric-share.mjs';
import { clockMs } from './fabric-time.mjs';

/** EX_CONFIG: the context is refused; 75 stays "already running" (EXIT_ALREADY_RUNNING). */
export const EXIT_CONTEXT_REFUSED = 78;
export const CONTEXT_MARKER = 'fabric-context.json';
const READABLE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const HASHED_TAIL = /-[0-9a-f]{10}$/;
const READABLE_MAX = 28;
const SLUG_MAX = 17;
/** What each refusal tells the person; the sentence never carries a record or grant value. */
const REASONS = Object.freeze({
  'context-invalid': 'the context is neither personal nor org:<orgId> as written',
  'record-required': "an organization's instance needs this machine's estate record, its machine id and its agentRef",
  'placement-missing': 'the estate record places no such agent on this machine in that context',
  'grant-refused': 'its placement names no unrevoked share grant for that context (FAC-SEM-111)',
  'grant-window': "now is outside its share grant's window",
  'context-mismatch': `its data folder belongs to another context or instance (${CONTEXT_MARKER})`,
});

/** A context this machine does not run; `code` is one of REASONS' keys. */
export class ContextRefused extends ServiceError {
  constructor(code, detail = '') {
    super(`${code}: ${detail || REASONS[code]}.`);
    this.code = code;
    this.detail = detail;
  }
}

const shown = (context) => (parseContext(context) ? context : 'a context that is neither personal nor org:<orgId>');

/**
 * The instance name of `context` (brief D15): `personal` is `personalInstance` (`default`); `org:<orgId>` is
 * `org-<orgId>` when readable (lower-case words joined by single hyphens, at most 28 characters, not ending in a hyphen
 * and 10 hex digits), else `org-<slug>-<first 10 hex digits of sha256(orgId)>`. Throws ContextRefused.
 */
export function contextInstanceName(context, { personalInstance = 'default' } = {}) {
  const parsed = parseContext(context);
  if (!parsed) throw new ContextRefused('context-invalid');
  if (parsed.kind === 'personal') {
    if (typeof personalInstance !== 'string' || !INSTANCE.test(personalInstance) || personalInstance.startsWith('org-')) {
      throw new ContextRefused('context-invalid', `the personal instance ${JSON.stringify(personalInstance)} is no instance name outside org-`);
    }
    return personalInstance;
  }
  const { org } = parsed;
  if (READABLE.test(org) && org.length <= READABLE_MAX && !HASHED_TAIL.test(org)) return `org-${org}`;
  const trim = (text) => text.replace(/^-+|-+$/g, '');
  const slug = trim(trim(org.toLowerCase().replace(/[^a-z0-9]+/g, '-')).slice(0, SLUG_MAX)) || 'x';
  return `org-${slug}-${crypto.createHash('sha256').update(org, 'utf8').digest('hex').slice(0, 10)}`;
}

/**
 * What `context` runs as on this machine; pure (no folder, file or lock). Answers {context, kind, org?, instance, key,
 * dirs: {data, logs, cache}, descriptorPath, grant?: {id, startsAt?, expiresAt?}}, never the record. `record` is the
 * verified revision this machine applied; `machineId` and `agentRef` come from whoever installed the instance; `at` is
 * the clock (a Date or epoch seconds; now when undefined). Throws ContextRefused.
 */
export function contextInstance(id, context, {
  record, machineId, agentRef, at, personalInstance = 'default', servicesDirectory, platform = process.platform,
} = {}) {
  const instance = contextInstanceName(context, { personalInstance });
  const parsed = parseContext(context);
  const answer = {
    context, kind: parsed.kind, instance, key: `${id}.${instance}`, dirs: instanceDirs(id, instance, platform),
    descriptorPath: descriptorPath(id, instance, servicesDirectory ?? servicesDir(platform)),
  };
  const havePlace = record !== null && typeof record === 'object' && !Array.isArray(record) && typeof machineId === 'string' && typeof agentRef === 'string';
  const atMs = at === undefined || at === null ? Date.now() : clockMs(at);
  if (parsed.kind === 'personal') {
    if (havePlace) { // brief D20: a personal placement that names a grant is refused; no placement is no refusal
      const checked = instanceShareGrant(record, machineId, agentRef, context, atMs);
      if (!checked.ok && checked.code === 'grant-refused') throw new ContextRefused('grant-refused', checked.detail);
    }
    return answer;
  }
  answer.org = parsed.org;
  if (!havePlace) throw new ContextRefused('record-required');
  const checked = instanceShareGrant(record, machineId, agentRef, context, atMs);
  if (!checked.ok) throw new ContextRefused(checked.code, checked.detail);
  answer.grant = checked.grant;
  return answer;
}

function markerMatches(file, expected) {
  let text;
  try {
    text = fs.readFileSync(file, 'utf8');
  } catch (error) {
    return error.code === 'ENOENT' ? undefined : false;
  }
  let found;
  try { found = JSON.parse(text); } catch { return false; }
  return found !== null && typeof found === 'object' && Object.entries(expected).every(([key, value]) => found[key] === value);
}

/**
 * Run as `context`'s one instance, before any side effect (brief D17): contextInstance (a refusal writes one sentence
 * naming the code and exits 78, nothing created); then holdSingleInstance on the instance's data folder (its markers,
 * its supervised wait, its exit 75); then `<data>/fabric-context.json`: absent, written (0600, atomic); equal, kept;
 * another context or instance, or unreadable, releases the lock and exits 78 (`context-mismatch`). Resolves to the
 * instance with its held `lock`; `exit` is injectable as holdSingleInstance has it, and its answer is returned.
 */
export async function holdContextInstance(id, context, {
  record, machineId, agentRef, at, personalInstance = 'default', servicesDirectory, platform = process.platform,
  waitSeconds, sleep, clock, exit = (code) => process.exit(code), env, argv,
} = {}) {
  const refuse = (code) => {
    process.stderr.write(`${id} will not run for ${shown(context)} (${code}): ${REASONS[code]}.\n`);
    return exit(EXIT_CONTEXT_REFUSED);
  };
  let info;
  try {
    info = contextInstance(id, context, { record, machineId, agentRef, at, personalInstance, servicesDirectory, platform });
  } catch (error) {
    if (error instanceof ContextRefused) return refuse(error.code);
    throw error;
  }
  const lock = await holdSingleInstance(info.dirs.data, {
    waitSeconds, exit, ...(sleep ? { sleep } : {}), ...(clock ? { clock } : {}), ...(env === undefined ? {} : { env }), ...(argv === undefined ? {} : { argv }),
  });
  if (!(lock instanceof InstanceLock)) return lock; // an injected exit answered 75
  const expected = { service: id, instance: info.instance, context };
  const marker = path.join(info.dirs.data, CONTEXT_MARKER);
  let matches;
  try {
    matches = markerMatches(marker, expected);
    if (matches === undefined) atomicWrite(marker, `${JSON.stringify(expected, null, 1)}\n`, 0o600);
  } catch (error) {
    lock.release();
    throw error;
  }
  if (matches === false) {
    lock.release();
    return refuse('context-mismatch');
  }
  return { ...info, lock };
}
