#!/usr/bin/env node
// A key-delivery door template (FAA-238), the twin of door.py: the same flags, the same exit codes, the same one line
// on stdout. Read door.py's docstring for the rules. Node 20+, no dependency.
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

export const ENVELOPE = 'fabric-credential-envelope/1';
const MAX_ANSWER = 65536;
const RETRIES = 2;
const TRANSPORT_EXIT = 75;
const TIME = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z$/;
const B64URL = /^[A-Za-z0-9_-]+$/;
const SIG = /^[A-Za-z0-9_-]{86}$/;
const KEM = /^[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}#kem$/;
const SIGNER = /^[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}(?:#sig)?$/;
const CONTEXT = /^(?:personal|org:[A-Za-z0-9][A-Za-z0-9_-]{0,127})$/;
const AGENT_REF = /^urn:fabric:agent:[a-z][a-z0-9]*(?:-[a-z0-9]+)*:[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/;
const SLOT = /^[A-Z][A-Z0-9_]{0,63}$/;
const SLUG = /^[a-z][a-z0-9-]{1,62}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const REQUIRED = ['type', 'alg', 'suite', 'recipient', 'signer', 'context', 'agentRef', 'slot', 'provider', 'sequence', 'iat', 'exp', 'enc'];
const ORG_ONLY = ['requestId', 'credentialExpiresAt'];

export class Refusal extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
class Transport extends Error {}

const when = (t) => Date.parse(t) / 1000;
const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const str = (v, re) => typeof v === 'string' && re.test(v);

export function envelopeProblems(envelope, want) {
  if (!isObject(envelope) || Object.keys(envelope).sort().join() !== 'ct,header,sig') return ['not {header, ct, sig}'];
  const h = envelope.header;
  if (!isObject(h)) return ['header is not an object'];
  let out = REQUIRED.filter((k) => !(k in h)).map((k) => `header misses ${k}`);
  out = out.concat(Object.keys(h).filter((k) => !REQUIRED.includes(k) && !ORG_ONLY.includes(k)).sort().map((k) => `header has no member ${k}`));
  if (out.length) return out;
  const checks = [['type', h.type === ENVELOPE], ['suite', JSON.stringify(h.suite) === '[16,1,1]'],
    ['recipient', str(h.recipient, KEM)], ['signer', str(h.signer, SIGNER)], ['context', str(h.context, CONTEXT)],
    ['agentRef', str(h.agentRef, AGENT_REF) && h.agentRef.length <= 146], ['slot', str(h.slot, SLOT)],
    ['provider', str(h.provider, SLUG)], ['sequence', Number.isInteger(h.sequence) && h.sequence >= 1 && h.sequence <= 9007199254740991],
    ['iat', str(h.iat, TIME)], ['exp', str(h.exp, TIME)], ['enc', str(h.enc, B64URL)],
    ['ct', str(envelope.ct, B64URL)], ['sig', str(envelope.sig, SIG)]];
  out = checks.filter(([, ok]) => !ok).map(([name]) => `${name} does not read`);
  if (out.length) return out;
  const org = h.context !== 'personal';
  if (h.alg !== (org ? 'EdDSA' : 'ES256')) out.push("alg is EdDSA in an organization's context, ES256 in the personal one");
  if (org && !ORG_ONLY.every((k) => k in h)) out.push("an organization's envelope names requestId and credentialExpiresAt");
  if (!org && ORG_ONLY.some((k) => k in h)) out.push('a personal envelope names no requestId or credentialExpiresAt');
  if (org && 'requestId' in h && !str(h.requestId, UUID)) out.push('requestId does not read');
  const iat = when(h.iat);
  const exp = when(h.exp);
  if (!(exp - iat > 0 && exp - iat <= 24 * 3600)) out.push('exp is after iat and at most 24 hours later');
  if (org && 'credentialExpiresAt' in h) {
    const end = h.credentialExpiresAt;
    if (!(str(end, TIME) && iat < when(end) && when(end) <= iat + 30 * 86400)) out.push('credentialExpiresAt is after iat and at most 30 days later');
  }
  for (const key of ['recipient', 'context', 'agentRef', 'slot', 'provider', 'requestId']) {
    if (key in want && h[key] !== want[key]) out.push(`header ${key} is not the one asked for`);
  }
  return out;
}

export const scrub = (text, value) => (value ? text.split(value).join('[value hidden]') : text);

function runChild(argv, payload, timeoutS) {
  const done = spawnSync(argv[0], argv.slice(1), { input: payload, timeout: timeoutS * 1000, maxBuffer: 4 * MAX_ANSWER });
  if (done.error?.code === 'ETIMEDOUT') throw new Transport(`${argv[0]} did not answer in ${timeoutS} s`);
  if (done.error?.code === 'ENOBUFS') return [done.status ?? 1, Buffer.alloc(0)];
  if (done.error) throw new Refusal(2, `${argv[0]} cannot be run: ${done.error.code ?? done.error.message}`);
  if (done.stdout.length > MAX_ANSWER) return [done.status, Buffer.alloc(0)];
  return [done.status, done.stdout];
}

function parse(buf, code, message) {
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(buf)); } catch { throw new Refusal(code, message); }
}

export const commandIssuer = (argv, timeoutS) => (request) => {
  const [code, out] = runChild(argv, JSON.stringify(request), timeoutS);
  if (code === TRANSPORT_EXIT) throw new Transport('the issuer could not be reached');
  if (code !== 0) throw new Refusal(3, `the issuer refused (exit ${code})`);
  return parse(out, 4, "the issuer's answer is not JSON");
};

export const commandSealer = (argv, timeoutS) => (value, header) => {
  let code; let out;
  try { [code, out] = runChild(argv, JSON.stringify({ value, header }), timeoutS); } catch (err) {
    if (err instanceof Transport) throw new Refusal(5, 'the sealer did not answer');
    throw err;
  }
  if (code !== 0) throw new Refusal(5, `the sealer refused (exit ${code})`);
  return parse(out, 5, "the sealer's answer is not JSON");
};

export function deliver(want, issue, seal, { sleep = (s) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, s * 1000) } = {}) {
  const request = {};
  for (const k of ['slot', 'provider', 'agentRef', 'context', 'requestId']) if (k in want) request[k] = want[k];
  let answer;
  for (let attempt = 0; ; attempt += 1) {
    try { answer = issue(request); break; } catch (err) {
      if (!(err instanceof Transport)) throw err;
      if (attempt === RETRIES) throw new Refusal(1, `transport failure after ${RETRIES + 1} tries: ${err.message}`);
      sleep(attempt + 1);
    }
  }
  if (isObject(answer) && isObject(answer.refused)) {
    const code = answer.refused.code;
    throw new Refusal(3, `the issuer refused: ${str(code, SLUG) ? code : 'no code'}`);
  }
  const value = isObject(answer) ? answer.value : undefined;
  if (typeof value !== 'string' || !value.trim() || /[\r\n]/.test(value)) throw new Refusal(4, "the issuer's answer holds no key");
  const header = { type: ENVELOPE, recipient: want.recipient, context: want.context, agentRef: want.agentRef, slot: want.slot, provider: want.provider };
  if (want.context !== 'personal') {
    header.requestId = want.requestId;
    if (typeof answer.credentialExpiresAt === 'string') header.credentialExpiresAt = answer.credentialExpiresAt;
  }
  const envelope = seal(value, header);
  let problems = envelopeProblems(envelope, want);
  const line = JSON.stringify(envelope);
  if (!problems.length && line.includes(value)) problems = ['the envelope carries the value in clear'];
  if (problems.length) throw new Refusal(5, `the sealed envelope is refused: ${problems.map((p) => scrub(p, value)).join('; ')}`);
  return line;
}

function split(command) { // shlex.split's POSIX subset: quotes and backslashes
  const out = []; let cur = ''; let quote = null; let any = false;
  for (let i = 0; i < command.length; i += 1) {
    const c = command[i];
    if (quote === "'") { if (c === "'") quote = null; else cur += c; continue; }
    if (quote === '"') { if (c === '"') quote = null; else if (c === '\\' && i + 1 < command.length && '"\\$`'.includes(command[i + 1])) cur += command[++i]; else cur += c; continue; }
    if (c === "'" || c === '"') { quote = c; any = true; } else if (c === '\\' && i + 1 < command.length) { cur += command[++i]; any = true; } else if (/\s/.test(c)) { if (any) out.push(cur); cur = ''; any = false; } else { cur += c; any = true; }
  }
  if (quote) throw new Error('No closing quotation');
  if (any) out.push(cur);
  return out;
}

export function main(argv) {
  let v;
  try {
    v = parseArgs({ args: argv, strict: true, options: Object.fromEntries(['slot', 'provider', 'agent-ref', 'recipient', 'context',
      'issuer-command', 'seal-command', 'request-id', 'timeout'].map((k) => [k, { type: 'string' }])) }).values;
  } catch (err) {
    process.stderr.write(`door.mjs: usage: ${err.message}\n`);
    return 2;
  }
  const usage = [];
  for (const k of ['slot', 'provider', 'agent-ref', 'recipient', 'context', 'issuer-command', 'seal-command']) if (v[k] === undefined) usage.push(`--${k} is required`);
  if (usage.length) { process.stderr.write(`door.mjs: usage: ${usage.join(', ')}\n`); return 2; }
  const want = { slot: v.slot, provider: v.provider, agentRef: v['agent-ref'], recipient: v.recipient, context: v.context };
  for (const [name, re, value] of [['--slot', SLOT, v.slot], ['--provider', SLUG, v.provider], ['--agent-ref', AGENT_REF, v['agent-ref']],
    ['--recipient', KEM, v.recipient], ['--context', CONTEXT, v.context]]) if (!re.test(value)) usage.push(name);
  if (v.context !== 'personal') {
    if (!str(v['request-id'], UUID)) usage.push("--request-id (an organization's context answers a credential-request/1)");
    want.requestId = v['request-id'];
  } else if (v['request-id']) usage.push('--request-id (a personal envelope names none)');
  const timeout = v.timeout === undefined ? 60 : Number(v.timeout);
  if (!(timeout > 0)) usage.push('--timeout');
  let issuer = []; let sealer = [];
  try { issuer = split(v['issuer-command']); sealer = split(v['seal-command']); } catch (err) { usage.push(`a command that does not split: ${err.message}`); }
  if (usage.length || !issuer.length || !sealer.length) {
    process.stderr.write(`door.mjs: usage: ${(usage.length ? usage : ['an empty command']).join(', ')}\n`);
    return 2;
  }
  try {
    process.stdout.write(`${deliver(want, commandIssuer(issuer, timeout), commandSealer(sealer, timeout))}\n`);
    return 0;
  } catch (err) {
    if (!(err instanceof Refusal)) throw err;
    process.stderr.write(`door.mjs: ${err.message}\n`);
    return err.code;
  }
}

const invoked = (() => { try { return fs.realpathSync(process.argv[1] ?? ''); } catch { return null; } })();
if (invoked === fileURLToPath(import.meta.url)) process.exitCode = main(process.argv.slice(2));
