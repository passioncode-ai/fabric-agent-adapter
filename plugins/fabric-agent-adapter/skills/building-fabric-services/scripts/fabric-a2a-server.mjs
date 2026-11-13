// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
// The serving side and a bounded client of A2A 1.0 (FAA-10, DEC-0122): an Agent Card built from the service's
// capabilities (agentCard, checked by agentCardFindings before it is served), the JSON-RPC binding (A2ABinding:
// SendMessage, SendStreamingMessage, GetTask, CancelTask) mapped onto the interop job store (a task is a job, a choice
// stop is TASK_STATE_INPUT_REQUIRED, the result envelope an artifact), and A2AClient (discover, call, get, cancel)
// that reaches a peer only on an origin the operator allowed, its credential read from the environment use_secret.py
// run fills. The interface never takes the descriptor's token (DEC-0122 item 3).
// Part of the Node service kit (layer L4); the twin of fabric_a2a_server.py. Node 20+, no dependency.
import crypto from 'node:crypto';
import { A2A_PROTOCOL_VERSION, A2A_SURFACE_PATH, agentCardFindings } from './fabric-a2a.mjs';
import { ServiceError } from './fabric-base.mjs';
import { InteropError, UnknownJob } from './fabric-interop-rules.mjs';
import { request as httpRequest } from './fabric-http.mjs';

export const JSONRPC_BINDING = 'JSONRPC';
export const PARSE_ERROR = -32700;
export const INVALID_REQUEST = -32600;
export const METHOD_NOT_FOUND = -32601;
export const INVALID_PARAMS = -32602;
export const INTERNAL_ERROR = -32603;
export const TASK_NOT_FOUND = -32001;
export const TASK_NOT_CANCELABLE = -32002;
export const UNSUPPORTED_OPERATION = -32004;
export const CONTENT_TYPE_NOT_SUPPORTED = -32005;
export const VERSION_NOT_SUPPORTED = -32009;
export const TASK_STATES = Object.freeze({ working: 'TASK_STATE_WORKING', input_required: 'TASK_STATE_INPUT_REQUIRED', completed: 'TASK_STATE_COMPLETED', failed: 'TASK_STATE_FAILED', cancelled: 'TASK_STATE_CANCELED' });
export const TERMINAL_STATES = Object.freeze(['TASK_STATE_COMPLETED', 'TASK_STATE_FAILED', 'TASK_STATE_CANCELED', 'TASK_STATE_REJECTED']);
export const MAX_BODY = 1024 * 1024;
const SKILL_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const STOPS = [...TERMINAL_STATES, 'TASK_STATE_INPUT_REQUIRED'];
const hex = (n) => crypto.randomBytes(n).toString('hex');

/** A refused A2A call or card; the message never carries a credential. */
export class A2AError extends ServiceError {}

export function skillFromCapability(capability) {
  const name = capability?.name;
  if (typeof name !== 'string' || !SKILL_ID.test(name)) throw new A2AError("a skill's id is the capability's name: letters, digits, '.', '_' or '-', at most 64");
  const skill = { id: name, name: capability.title || name, description: capability.description || name, tags: [...(capability.tags || [name.split('.')[0]])] };
  for (const key of ['examples', 'inputModes', 'outputModes']) if (capability[key]?.length) skill[key] = [...capability[key]];
  return skill;
}

export function agentCard({ name, description, version, url, capabilities, securitySchemes, streaming = false, extensions, remote = false, descriptorHeader = 'Authorization' }) {
  const match = /^(https?:\/\/[^/?#]+)/.exec(url ?? '');
  const card = {
    name, description, version,
    supportedInterfaces: [{ url, protocolBinding: JSONRPC_BINDING, protocolVersion: A2A_PROTOCOL_VERSION }],
    capabilities: { streaming: Boolean(streaming), pushNotifications: false },
    defaultInputModes: ['text/plain', 'application/json'], defaultOutputModes: ['text/plain', 'application/json'],
    skills: capabilities.map(skillFromCapability),
  };
  if (extensions?.length) card.capabilities.extensions = extensions.map((e) => ({ ...e, required: false }));
  if (securitySchemes) card.securitySchemes = securitySchemes;
  const findings = agentCardFindings(card, { origin: match ? match[1] : undefined, remote, descriptorHeader });
  if (findings.length) throw new A2AError(`the card is not served: ${findings.map((f) => f.message).join('; ')}`);
  return card;
}

export const textOf = (message) => (Array.isArray(message?.parts) ? message.parts : []).filter((p) => typeof p?.text === 'string').map((p) => p.text).join('\n');
export const dataOf = (message) => (Array.isArray(message?.parts) ? message.parts : []).filter((p) => p && typeof p === 'object' && 'data' in p).map((p) => p.data);

export function agentMessage(text, { taskId, contextId, data } = {}) {
  const parts = [{ text }];
  if (data !== undefined) parts.push({ data });
  const message = { role: 'ROLE_AGENT', parts, messageId: `msg-${hex(8)}` };
  if (taskId) message.taskId = taskId;
  if (contextId) message.contextId = contextId;
  return message;
}

/** What a message handler gets: the message, its caller and start(skill), which makes the job that is the task. */
export class TaskStart {
  constructor(binding, message, caller, contextId) { Object.assign(this, { binding, message, caller, contextId, taskId: null }); }
  start(skill) {
    if (!this.binding.skills.has(skill)) throw new A2AError(`no skill ${skill} on this card`);
    const handle = this.binding.jobs.create(`a2a.${skill}`, { a2a: { message: this.message, contextId: this.contextId, caller: this.caller } });
    this.taskId = handle.job.id;
    return this.taskId;
  }
}

class NotCancelable extends Error {}
class BadParams extends Error {}

const result = (id, value) => ({ jsonrpc: '2.0', id, result: value });
const error = (id, code, message) => ({ jsonrpc: '2.0', id, error: { code, message } });
const event = (id, value) => `data: ${JSON.stringify(result(id, value))}\n\n`;

function textAnswer(requests, text) {
  const keys = Object.keys(requests ?? {});
  if (keys.length !== 1 || !text) return null;
  const props = Object.keys(requests[keys[0]]?.params?.requestedSchema?.properties ?? {});
  return props.length === 1 ? { [keys[0]]: { action: 'accept', content: { [props[0]]: text } } } : null;
}

/** The A2A Task an interop job reads as. */
export function taskOf(job, contextId) {
  const status = { state: TASK_STATES[job.status] ?? 'TASK_STATE_UNSPECIFIED', timestamp: job.updatedAt ?? '' };
  if (job.status === 'input_required') {
    const questions = Object.values(job.inputRequests ?? {}).map((r) => r?.params?.message).filter((q) => typeof q === 'string');
    status.message = agentMessage(job.statusMessage || questions.join('; ') || 'an answer is needed', { taskId: job.id, contextId, data: { inputRequests: job.inputRequests } });
  } else if (job.status === 'failed') {
    status.message = agentMessage(String(job.error?.message || 'the task failed'), { taskId: job.id, contextId, data: { code: job.error?.code } });
  } else if (job.statusMessage) {
    status.message = agentMessage(job.statusMessage, { taskId: job.id, contextId });
  }
  const task = { id: job.id, contextId, status };
  if (job.status === 'completed') task.artifacts = [{ artifactId: 'result', name: 'result', parts: [{ data: job.result }] }];
  return task;
}

/** The JSON-RPC binding over the interop job store; see fabric_a2a_server.A2ABinding. */
export class A2ABinding {
  constructor(jobs, handler, { skills, authorize, clock = () => Date.now() / 1000 }) {
    Object.assign(this, { jobs, handler, skills: new Set(skills), authorize, clock });
  }

  task(jobId, caller) {
    const a2a = this.jobs.load(jobId).private?.input?.a2a;
    if (!a2a || typeof a2a !== 'object' || (a2a.caller ?? null) !== (caller ?? null)) throw new UnknownJob(jobId);
    return taskOf(this.jobs.get(jobId), a2a.contextId);
  }

  handle(body, headers = {}) {
    const lowered = Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]));
    const caller = this.authorize(lowered);
    if (caller === null || caller === undefined) return [401, null];
    if (body instanceof Uint8Array) {
      if (body.length > MAX_BODY) return [413, null];
      try { body = JSON.parse(Buffer.from(body).toString('utf8')); } catch { return [200, error(null, PARSE_ERROR, 'the body is not JSON')]; }
    }
    if (!body || typeof body !== 'object' || Array.isArray(body) || body.jsonrpc !== '2.0' || typeof body.method !== 'string') {
      return [200, error(body && typeof body === 'object' && !Array.isArray(body) ? body.id : null, INVALID_REQUEST, 'not a JSON-RPC 2.0 request')];
    }
    const rid = body.id;
    const version = lowered['a2a-version'];
    if (version !== undefined && String(version).trim() !== A2A_PROTOCOL_VERSION) return [200, error(rid, VERSION_NOT_SUPPORTED, `this agent speaks A2A ${A2A_PROTOCOL_VERSION}`)];
    const params = body.params;
    if (!params || typeof params !== 'object' || Array.isArray(params)) return [200, error(rid, INVALID_PARAMS, 'params is an object')];
    try {
      if (body.method === 'SendStreamingMessage') return [200, error(rid, UNSUPPORTED_OPERATION, 'streaming is served by stream() as text/event-stream')];
      if (body.method === 'SendMessage') return [200, result(rid, this.send(params, caller))];
      if (body.method === 'GetTask') return [200, result(rid, this.task(String(params.id), caller))];
      if (body.method === 'CancelTask') return [200, result(rid, this.cancel(String(params.id), caller))];
    } catch (e) {
      if (e instanceof UnknownJob) return [200, error(rid, TASK_NOT_FOUND, 'no such task')];
      if (e instanceof NotCancelable) return [200, error(rid, TASK_NOT_CANCELABLE, 'the task has ended')];
      if (e instanceof BadParams) return [200, error(rid, INVALID_PARAMS, e.message)];
      if (e instanceof A2AError || e instanceof InteropError) return [200, error(rid, INTERNAL_ERROR, `the agent could not take the message: ${e.message}`)];
      throw e;
    }
    return [200, error(rid, METHOD_NOT_FOUND, `no method ${body.method.slice(0, 64)} here`)];
  }

  send(params, caller) {
    const message = params.message;
    if (!message || typeof message !== 'object' || !Array.isArray(message.parts) || !message.parts.length) throw new BadParams('params.message is a message with parts');
    if (typeof message.taskId === 'string' && message.taskId) return { task: this.continueTask(message.taskId, message, caller) };
    const contextId = typeof message.contextId === 'string' ? message.contextId : `ctx-${hex(8)}`;
    const start = new TaskStart(this, message, caller, contextId);
    const reply = this.handler(start);
    if (start.taskId !== null) return { task: this.task(start.taskId, caller) };
    if (!reply || typeof reply !== 'object') throw new A2AError('the handler neither replied nor started a task');
    return { message: { ...reply, contextId } };
  }

  continueTask(taskId, message, caller) {
    const task = this.task(taskId, caller);
    if (task.status.state !== 'TASK_STATE_INPUT_REQUIRED') throw new BadParams('the task waits for no answer');
    const job = this.jobs.get(taskId);
    let responses = dataOf(message).find((d) => d && typeof d === 'object' && d.inputResponses && typeof d.inputResponses === 'object' && !Array.isArray(d.inputResponses))?.inputResponses ?? null;
    if (responses === null) responses = textAnswer(job.inputRequests ?? {}, textOf(message));
    if (!responses || !Object.keys(this.jobs.answer(taskId, responses) ?? {}).length) throw new BadParams("the answer names none of the task's questions");
    return this.task(taskId, caller);
  }

  cancel(taskId, caller) {
    const task = this.task(taskId, caller);
    if (TERMINAL_STATES.includes(task.status.state)) throw new NotCancelable();
    this.jobs.cancel(taskId);
    return this.task(taskId, caller);
  }

  async *stream(params, caller, { rid = null, pollS = 1, deadlineS = 300, sleep = (s) => new Promise((r) => setTimeout(r, s * 1000)) } = {}) {
    const first = this.send(params, caller);
    yield event(rid, first);
    if (!first.task) return;
    let task = first.task;
    const end = this.clock() + deadlineS;
    while (!STOPS.includes(task.status.state) && this.clock() < end) {
      await sleep(pollS);
      const now = this.task(task.id, caller);
      if (now.status.state !== task.status.state || JSON.stringify(now.artifacts) !== JSON.stringify(task.artifacts)) {
        yield event(rid, { statusUpdate: { taskId: now.id, contextId: now.contextId, status: now.status, final: STOPS.includes(now.status.state) } });
      }
      task = now;
    }
  }
}

/** scheme://host[:port] of a URL, lower-cased, a default port dropped. */
export function originOf(url) {
  const match = /^(https?):\/\/([^/?#]+)/i.exec(url ?? '');
  if (!match || match[2].includes('@')) throw new A2AError("a peer's address is an http(s) origin with no userinfo");
  const scheme = match[1].toLowerCase();
  let host = match[2].toLowerCase();
  const port = host.split(':').pop();
  if (((scheme === 'https' && port === '443') || (scheme === 'http' && port === '80')) && host.includes(':') && !host.endsWith(']')) host = host.slice(0, host.lastIndexOf(':'));
  return `${scheme}://${host}`;
}

/** A bounded A2A 1.0 client; see fabric_a2a_server.A2AClient. */
export class A2AClient {
  constructor(allowOrigins, { credentialEnv, header = 'Authorization', scheme = 'Bearer', deadlineS = 30, maxBytes = MAX_BODY, transport, insecure = false } = {}) {
    this.allowed = new Set(allowOrigins.map(originOf));
    if (!this.allowed.size) throw new A2AError("a client needs the operator's list of peer origins");
    Object.assign(this, { credentialEnv, header, scheme, deadlineS, maxBytes, transport, insecure, ids: 0 });
  }

  check(url) { if (!this.allowed.has(originOf(url))) throw new A2AError(`${originOf(url)} is not on the operator's list of A2A peers`); }

  headers() {
    const headers = { 'A2A-Version': A2A_PROTOCOL_VERSION, Accept: 'application/json' };
    if (this.credentialEnv) {
      const value = process.env[this.credentialEnv];
      if (!value) throw new A2AError(`${this.credentialEnv} is empty: run the caller under use_secret.py run, which places the key`);
      headers[this.header] = this.scheme ? `${this.scheme} ${value}` : value;
    }
    return headers;
  }

  options(extra) { return { deadlineS: this.deadlineS, maxBytes: this.maxBytes, insecure: this.insecure, ...(this.transport ? { transport: this.transport } : {}), ...extra }; }

  async discover(origin) {
    const url = originOf(origin) + A2A_SURFACE_PATH;
    this.check(url);
    const response = await httpRequest('GET', url, this.options({ headers: { Accept: 'application/json' } }));
    if (response.status !== 200) throw new A2AError(`the peer answered HTTP ${response.status} for its card`);
    let card;
    try { card = response.json(); } catch { throw new A2AError("the peer's card is not JSON"); }
    if (!card || typeof card !== 'object' || Array.isArray(card)) throw new A2AError("the peer's card is not a JSON object");
    for (const i of card.supportedInterfaces ?? []) {
      if (i && i.protocolBinding === JSONRPC_BINDING && i.protocolVersion === A2A_PROTOCOL_VERSION && typeof i.url === 'string') {
        this.check(i.url);
        return { card, url: i.url };
      }
    }
    throw new A2AError(`the peer's card names no A2A ${A2A_PROTOCOL_VERSION} JSON-RPC interface`);
  }

  async rpc(url, method, params) {
    this.check(url);
    this.ids += 1;
    const response = await httpRequest('POST', url, this.options({ headers: this.headers(), body: { jsonrpc: '2.0', id: this.ids, method, params }, retries: 0 }));
    if (response.status !== 200) throw new A2AError(`the peer answered HTTP ${response.status} to ${method}`);
    let answer = null;
    try { answer = response.json(); } catch { /* answered below */ }
    if (!answer || typeof answer !== 'object' || Array.isArray(answer)) throw new A2AError(`the peer's answer to ${method} is not a JSON-RPC response`);
    if ('error' in answer) throw new A2AError(`the peer refused ${method}: ${answer.error?.code} ${String(answer.error?.message).slice(0, 200)}`);
    return answer.result;
  }

  call(url, text, { data, taskId, contextId } = {}) {
    const parts = [{ text }];
    if (data !== undefined) parts.push({ data });
    const message = { role: 'ROLE_USER', parts, messageId: `msg-${hex(8)}` };
    if (taskId) message.taskId = taskId;
    if (contextId) message.contextId = contextId;
    return this.rpc(url, 'SendMessage', { message });
  }

  get(url, taskId) { return this.rpc(url, 'GetTask', { id: taskId }); }
  cancel(url, taskId) { return this.rpc(url, 'CancelTask', { id: taskId }); }
}
