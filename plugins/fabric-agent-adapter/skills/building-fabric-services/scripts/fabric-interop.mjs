// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
// Reference kit for the fabric-interop/0.1 extension — Node.js 20+, no dependencies.
// The Node twin of fabric_interop.py: the same rules and the same job file format, so a
// job written by one kit is read by the other. The minimal MCP dispatcher is Python-only;
// a Node service uses the official MCP SDK for the wire and these helpers for the rules.
// Normative source: fabric-agent-contract docs/specification/interop.md (DEC-0016, rulings DEC-0017).
// #region interop-kit-node — docs: plugins/fabric-agent-adapter/skills/building-fabric-services/references/interop.md#the-kit

import crypto from 'node:crypto';
import { ServiceError, nowIso } from './fabric-service.mjs';
import { PageLinkError, dashboardsLink, pageLinkFindings, parseDashboardsLink } from './fabric-page-links.mjs';

export {
  PROTOCOL,
  EXTENSION_KEY,
  MCP_REVISION,
  TERMINAL,
  CONTRACT_VERSION,
  JOB_HANDLE_SCHEMA,
  InteropError,
  UnknownJob,
  parseTraceparent,
  childTraceparent,
  traceIds,
  QUOTA_EXHAUSTED,
  QUEUE_FULL,
  OUTCOME_UNKNOWN,
  LIMIT_REACHED,
  INTEROP_NULL_USAGE,
  PROTOCOLS_READ,
  utcTime,
  quotaDataOk,
  readJobPause,
  jobCallerAction,
  intentIdempotencyKey,
  readsNullUsage,
  requestMeta,
  jobStep,
  actionGate,
  authorityConfigProblem,
  authorityDeclaration,
  authorityGateInputs,
  mandateSpend,
  keptStep,
  UNREADABLE_PROJECT,
  UNREADABLE_AGENT,
  identifiedAgent,
  actionRefusalToolResult,
  usageFindings,
  usageToward,
  jobLimitRules,
  pauseMessage,
  repeatedKeyDecision,
} from './fabric-interop-rules.mjs';
import { PROTOCOL, EXTENSION_KEY, MCP_REVISION, TERMINAL, CONTRACT_VERSION, JOB_HANDLE_SCHEMA, InteropError, UnknownJob, parseTraceparent, childTraceparent, traceIds, QUOTA_EXHAUSTED, QUEUE_FULL, OUTCOME_UNKNOWN, LIMIT_REACHED, INTEROP_NULL_USAGE, PROTOCOLS_READ, utcTime, quotaDataOk, readJobPause, jobCallerAction, intentIdempotencyKey, readsNullUsage, requestMeta, usageFindings, usageToward, jobLimitRules, pauseMessage, repeatedKeyDecision, keptStep, OUTCOMES, ENVELOPE_REQUIRED, JOB_ID, KEY, SECRET_WORDS } from './fabric-interop-rules.mjs'; // the rule layer (FAA-92)

// --- C3.1 capabilities as tools ----------------------------------------------------------
export function expectedAnnotations(effect, idempotency) {
  const hints = {};
  if (effect === 'none') hints.readOnlyHint = true;
  if (['delete', 'merge', 'deploy', 'change-policy'].includes(effect)) hints.destructiveHint = true;
  if (idempotency === 'required') hints.idempotentHint = true;
  return hints;
}

// DEC-0017: a job-backed tool serves oneOf[result envelope, job handle]; the manifest keeps the pure output schema.
export const jobToolOutputSchema = (outputSchema) => ({ type: 'object', oneOf: [{ type: 'object', required: [...ENVELOPE_REQUIRED], properties: { output: outputSchema } }, JOB_HANDLE_SCHEMA] });
export const isJobCapability = (capability) => capability.job === true || capability.extensions?.[EXTENSION_KEY]?.job === true;

// DEC-0018 (FAC-SEM-023): an outputSchema is rooted at type object; a client may reject the whole
// tools/list when one tool's outputSchema is, say, a bare oneOf.
export function requireObjectRoot(name, outputSchema) {
  if (!outputSchema || typeof outputSchema !== 'object' || outputSchema.type !== 'object') throw new InteropError(`Tool ${name}: an outputSchema must have root type "object".`);
}

export function toolForCapability(capability, inputSchema, outputSchema, title) {
  requireObjectRoot(capability.name, outputSchema);
  const served = isJobCapability(capability) ? jobToolOutputSchema(outputSchema) : outputSchema;
  const tool = { name: capability.name, inputSchema, outputSchema: served, annotations: expectedAnnotations(capability.effect, capability.idempotency) };
  if (capability.description) tool.description = capability.description;
  if (title) tool.title = title;
  return tool;
}

export function toolResult(structured, { isError = false, traceparent } = {}) {
  const result = { resultType: 'complete', content: [{ type: 'text', text: JSON.stringify(structured) }], structuredContent: structured, isError };
  if (traceparent) result._meta = { traceparent };
  return result;
}

export const unknownJobResult = (jobId, traceparent) =>
  toolResult({ error: { code: 'unknown-job', message: `No job ${jobId} here.` } }, { isError: true, traceparent });

// --- C3.2 the result envelope --------------------------------------------------------------

// The full result envelope (contract result.schema.json, DEC-0017): the shape a synchronous call returns.
export function resultEnvelope({ outcome, done, proof, scope, notVerified, output, usage, producer, artifacts = [], traceparent, id, createdAt, requestMeta }) {
  if (!OUTCOMES.includes(outcome)) throw new InteropError(`outcome must be one of ${OUTCOMES.join(', ')}.`);
  for (const [label, value] of [['done', done], ['proof', proof], ['notVerified', notVerified], ['artifacts', artifacts]]) {
    if (!Array.isArray(value)) throw new InteropError(`${label} must be a list, even when empty.`);
  }
  if (outcome === 'succeeded' && notVerified.length) throw new InteropError('A succeeded result cannot keep unverified claims (FAC-SEM-001); report partial.');
  if (!scope || typeof scope !== 'object' || !producer || typeof producer !== 'object') throw new InteropError('scope and producer must be objects.');
  const envelope = {
    id: id ?? `urn:fabric:result:${crypto.randomBytes(12).toString('hex')}`, contractVersion: CONTRACT_VERSION, outcome,
    done: [...done], proof: [...proof], scope: { ...scope }, notVerified: [...notVerified], artifacts: [...artifacts],
    createdAt: createdAt ?? nowIso(), producer: { ...producer }, output, usage: usageToward(usage, requestMeta),
  };
  if (parseTraceparent(traceparent)) envelope.trace = { traceparent };
  return envelope;
}


// --- C3.3 awaiting a choice ------------------------------------------------------------------
export function formRequest(message, properties, required) {
  for (const [field, schema] of Object.entries(properties)) {
    const words = ['title', 'description', 'format'].map((k) => schema[k] ?? '').join(' ');
    if (SECRET_WORDS.test(field) || SECRET_WORDS.test(words)) throw new InteropError(`Form mode cannot ask for ${field}: a secret goes through urlRequest.`);
    if (!['string', 'number', 'integer', 'boolean', 'array'].includes(schema.type)) throw new InteropError(`Form field ${field} must be a primitive.`);
  }
  const requestedSchema = { type: 'object', properties };
  if (required?.length) requestedSchema.required = [...required];
  return { method: 'elicitation/create', params: { mode: 'form', message, requestedSchema } };
}

export function choiceRequest(message, field, options, title) {
  const schema = { type: 'string', oneOf: options.map(([value, label]) => ({ const: value, title: label })) };
  if (title) schema.title = title;
  return formRequest(message, { [field]: schema }, [field]);
}

/**
 * URL mode: the person opens `url` out of band; for credentials and payments. A page of this service goes as its
 * open_link (`pageAnswer`, DEC-0123 PL-4); a raw loopback address and a `fabric-dashboards:` link outside the grammar
 * are refused here, when the request is built (FAC-SEM-143).
 */
export function urlRequest(message, url) {
  const needs = "A URL-mode request needs an https URL or Fabric Dashboards' open_link (DEC-0123 PL-4).";
  if (typeof url !== 'string') throw new InteropError(needs);
  const [finding] = pageLinkFindings(url, '/params/url', 'the URL-mode request');
  if (finding) throw new InteropError(finding.message);
  if (!url.startsWith('https://') && !parseDashboardsLink(url).ok) throw new InteropError(needs);
  return { method: 'elicitation/create', params: { mode: 'url', message, url } };
}

/**
 * A tool answer that hands a person one of this service's pages (DEC-0123 PL-4): `{open_link}`, the page's Fabric
 * Dashboards link, and `http_url`, its raw address, only as a diagnostic beside it (never judged as the action).
 */
export function pageAnswer(service, instance, { path, httpUrl } = {}) {
  let answer;
  try {
    answer = { open_link: dashboardsLink(service, instance, path) };
  } catch (error) {
    if (!(error instanceof PageLinkError)) throw error;
    throw new InteropError(`No open_link for ${service}.${instance}: ${error.message} (DEC-0123 PL-1).`);
  }
  if (httpUrl !== undefined && httpUrl !== null) answer.http_url = httpUrl;
  return answer;
}

// --- C3.2 jobs: the store lives in fabric-interop-jobs.mjs, the same file format as fabric_interop_jobs.JobStore -----
export { JobStore, intentDigest } from './fabric-interop-jobs.mjs';
// #endregion interop-kit-node

// --- MCP 2026-07-28 standard headers ------------------------------------------------------

export const NAMED_METHODS = { 'tools/call': 'name', 'prompts/get': 'name', 'resources/read': 'uri' };
export const HEADER_MISMATCH = -32020; // the code the official 2026-07-28 server SDK answers a header/body mismatch with

const SENTINEL = ['=?base64?', '?='];

/**
 * A body value as an HTTP header value, by MCP 2026-07-28 Streamable HTTP "Value Encoding": as it
 * is when it is printable ASCII without leading or trailing whitespace, otherwise — and for a plain
 * value that itself looks like the sentinel — `=?base64?<base64 of its UTF-8>?=`.
 */
export function encodeHeaderValue(value) {
  const s = String(value);
  const plain = /^[\x20-\x7e]*$/.test(s) && s === s.replace(/^ +| +$/g, '') && !(s.startsWith(SENTINEL[0]) && s.endsWith(SENTINEL[1]));
  if (plain) return s;
  let binary = '';
  for (const byte of new TextEncoder().encode(s)) binary += String.fromCharCode(byte);
  return SENTINEL[0] + btoa(binary) + SENTINEL[1];
}

/** The body value a header carries, decoding the Base64 sentinel; null for invalid characters or a
 *  sentinel that is not valid Base64 of UTF-8 (a server rejects both). */
export function decodeHeaderValue(value) {
  const s = String(value);
  if (s.startsWith(SENTINEL[0]) && s.endsWith(SENTINEL[1]) && s.length >= SENTINEL[0].length + SENTINEL[1].length) {
    const body = s.slice(SENTINEL[0].length, -SENTINEL[1].length);
    if (body.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(body)) return null;
    try {
      const bytes = Uint8Array.from(atob(body), (c) => c.charCodeAt(0));
      return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    } catch { return null; }
  }
  return /^[\x20-\x7e\t]*$/.test(s) ? s : null;
}

/**
 * MCP 2026-07-28 Streamable HTTP mirrors the body in `Mcp-Method` (every request and
 * notification) and `Mcp-Name` (`params.name` or `params.uri` of tools/call, prompts/get,
 * resources/read). A server MUST reject a mismatch; a request that declares 2026-07-28 must carry
 * them. Returns the problem as a sentence, or null. `headers` is a plain object (any case) or a
 * Headers instance.
 */
export function mcpHeaderProblem(message, headers) {
  if (!message || typeof message !== 'object' || !headers) return null;
  const header = (name) => {
    if (typeof headers.get === 'function') return headers.get(name) ?? null;
    const key = Object.keys(headers).find((k) => k.toLowerCase() === name.toLowerCase());
    const value = key === undefined ? undefined : headers[key];
    return value === undefined ? null : String(Array.isArray(value) ? value[0] : value);
  };
  const declared = header('MCP-Protocol-Version') === MCP_REVISION;
  const { method } = message;
  const sent = header('Mcp-Method');
  if (sent === null && declared) return `the body names method ${method} but the required Mcp-Method header is absent`;
  if (sent !== null && sent !== method) return `Mcp-Method ${sent} disagrees with the body's method ${method}`;
  const field = NAMED_METHODS[method];
  if (field) {
    const named = header('Mcp-Name');
    if (named === null && declared) return `the body carries params.${field} but the required Mcp-Name header is absent`;
    if (named !== null) {
      const decoded = decodeHeaderValue(named);
      if (decoded === null) return 'Mcp-Name is malformed: invalid characters or a broken =?base64?…?= value';
      if (decoded !== String(message.params?.[field])) return `Mcp-Name disagrees with the body's params.${field}`;
    }
  }
  return null;
}

/** The standard headers a 2026-07-28 client sends with one request. */
export function mcpRequestHeaders(method, params = {}) {
  const out = { 'MCP-Protocol-Version': MCP_REVISION, 'Mcp-Method': method };
  const field = NAMED_METHODS[method];
  if (field && params[field] !== undefined && params[field] !== null) out['Mcp-Name'] = encodeHeaderValue(params[field]);
  return out;
}
