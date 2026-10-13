// The Fabric hub's door, as a service agent reaches it (fabric-hub/0.1; Fabric ADR-0115 §1, ADR-0149 §4; FAA-12b).
// The twin of fabric_hub.py, same rules and the same answers; Node built-ins only.
//
// 1. Find the hub, every time: locateHub() re-reads hub.json beside Fabric's registry (macOS
//    ~/Library/Application Support/ai.passioncode.fabric, Windows %LOCALAPPDATA%\passioncode-fabric, Linux
//    $XDG_DATA_HOME/passioncode-fabric) the way Fabric's own locateHub does: a small regular file, never a link or a
//    FIFO; protocol fabric-hub/0.1; origin exactly http://127.0.0.1:<port>; MCP at /mcp; a door token file inside the
//    registry root; a pid that is alive. The port does not prove who holds it, so a binding credential is sent only
//    after this check passes, done again before each send.
// 2. Ask once, keep the credential in a file: requestBoardAccess() asks for the board.respond grant through the door;
//    pollAccess() writes the credential, shown once, to a 0600 file and answers without it. Tokens live in files and
//    headers only — never argv, a URL, a log line or an error text.
// 3. Join the board: joinBoard() calls fabric.board.join {projectId} and answers a BoardGrant (a one-session bearer
//    that fabric-board.mjs's BoardSession spends with one MCP initialize). Without a grant: HubError not_authorized
//    whose data.ask holds the fabric.access.request arguments.
//
// Fabric down: every call throws HubError with retryable true; Backoff gives the bounded, jittered wait (2 s doubling to
// 5 minutes), so nothing spins. fabric-hub/0.1 publishes no hub key; a later hub.json naming hubKey {kid, x} is
// checked with fabric-estate.mjs's hubKeyCertified when the caller passes an estate record, refused with DEC-0060's
// own detail.

import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { atomicWrite, ensurePrivateDir, readToken } from './fabric-service.mjs';
import { hubKeyCertified } from './fabric-estate.mjs';

export const HUB_PROTOCOL = 'fabric-hub/0.1';
export const MCP_PROTOCOL_VERSION = '2025-06-18';
export const READ_CAP = 64 * 1024;
const LOOPBACK_ORIGIN = /^http:\/\/127\.0\.0\.1:(\d{4,5})$/;
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const CAPABILITY = /^[a-z][a-z0-9._-]{1,127}$/;

/** A typed refusal or fault: code, one-sentence message, retryable, data (never a secret). */
export class HubError extends Error {
  constructor(code, message, retryable = false, data = {}) {
    super(message);
    this.name = 'HubError';
    this.code = code;
    this.retryable = retryable;
    this.data = data ?? {};
  }
}

/** Fabric's registry root, where hub.json lives (Fabric agentRegistry.ts#registryDirs). */
export function fabricRoot(platform = process.platform, env = process.env) {
  const home = env.HOME || env.USERPROFILE || os.homedir();
  if (platform === 'darwin') return path.join(home, 'Library/Application Support/ai.passioncode.fabric');
  if (platform === 'win32') return path.join(env.LOCALAPPDATA || path.join(home, 'AppData', 'Local'), 'passioncode-fabric');
  return path.join(env.XDG_DATA_HOME || path.join(home, '.local/share'), 'passioncode-fabric');
}

/** Whether a process with this id runs as this user (Fabric hub.ts#pidAlive): EPERM is another user's process. */
export function pidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function readSmall(file) {
  const info = fs.lstatSync(file);
  if (!info.isFile() || info.size > READ_CAP) return null;
  const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
  try {
    if (!fs.fstatSync(fd).isFile()) return null;
    const buf = Buffer.alloc(READ_CAP + 1);
    let got = 0;
    for (;;) {
      const n = fs.readSync(fd, buf, got, buf.length - got, null);
      if (n === 0) break;
      got += n;
      if (got > READ_CAP) return null;
    }
    return buf.subarray(0, got).toString('utf8');
  } finally {
    fs.closeSync(fd);
  }
}

/**
 * hub.json read the way an agent must, every call. Answers {origin, mcpUrl, doorTokenFile, pid, startedAt, features} or
 * throws HubError (not-running, retryable; not-a-hub). Reads no token. `estate` is {record, applied}: with it, a hubKey
 * the document names is checked by hubKeyCertified (DEC-0060); fabric-hub/0.1 names none.
 */
export function locateHub(root = fabricRoot(), { alive = pidAlive, estate, now } = {}) {
  const hubFile = path.join(root, 'hub.json');
  const notHub = (reason) => new HubError('not-a-hub', `Fabric's hub.json ${reason}.`);
  let text;
  try {
    text = readSmall(hubFile);
  } catch (e) {
    if (e.code === 'ENOENT') throw new HubError('not-running', 'Fabric is not running: there is no hub.json.', true);
    throw new HubError('not-a-hub', `Fabric's hub.json could not be read (${e.code ?? 'error'}).`, true);
  }
  if (text === null) throw notHub('is not a small regular file');
  let doc;
  try {
    doc = JSON.parse(text);
  } catch {
    throw notHub('is not JSON');
  }
  if (!doc || typeof doc !== 'object' || doc.protocol !== HUB_PROTOCOL) throw notHub(`does not speak ${HUB_PROTOCOL}`);
  const origin = typeof doc.origin === 'string' ? doc.origin : '';
  const m = LOOPBACK_ORIGIN.exec(origin);
  if (!m || Number(m[1]) < 1024 || Number(m[1]) > 65535) throw notHub('names an origin that is not the loopback literal');
  if (doc.mcp !== '/mcp') throw notHub('names another MCP path');
  if (!Number.isInteger(doc.pid) || doc.pid <= 0) throw notHub('names no process');
  const tokenFile = typeof doc.doorTokenFile === 'string' ? doc.doorTokenFile : '';
  let sameRoot = false;
  try {
    sameRoot = path.isAbsolute(tokenFile) && fs.realpathSync(path.dirname(tokenFile)) === fs.realpathSync(root);
  } catch {
    sameRoot = false;
  }
  if (!sameRoot) throw notHub('names a door token outside the registry root');
  if (!alive(doc.pid)) throw new HubError('not-running', `Fabric is not running: hub.json names process ${doc.pid}, which is not running.`, true);
  const features = Array.isArray(doc.features) ? doc.features.filter((f) => typeof f === 'string') : [];
  if (estate && doc.hubKey && typeof doc.hubKey === 'object') {
    const verdict = hubKeyCertified(estate.record, doc.hubKey.kid, doc.hubKey.x, now ?? Date.now() / 1000, estate.applied ?? undefined);
    if (!verdict.certified) throw new HubError('hub-key-refused', `The estate record does not certify the hub's key (${verdict.detail}).`, false, { fault: verdict.fault, detail: verdict.detail });
  }
  return { origin, mcpUrl: `${origin}/mcp`, doorTokenFile: tokenFile, pid: doc.pid, startedAt: doc.startedAt, features };
}

/** The door token hub.json names: a 0600 file of this user, never a link, 43 base64url characters. */
export function readDoorToken(location) {
  let token;
  try {
    token = readToken(location.doorTokenFile);
  } catch (e) {
    if (e.code === 'ENOENT') throw new HubError('not-running', 'Fabric is starting or stopping: its door token is not there.', true);
    throw new HubError('not-a-hub', `The door token file is not one Fabric writes (${e.message}).`);
  }
  if (!TOKEN.test(token)) throw new HubError('not-a-hub', 'The door token is not one Fabric writes.');
  return token;
}

/** A binding credential from its 0600 file: 43 base64url characters. */
export function readCredential(file) {
  let token;
  try {
    token = readToken(file);
  } catch (e) {
    if (e.code === 'ENOENT') throw new HubError('credential', `No binding credential at ${file}: ask for the grant first (requestBoardAccess).`);
    throw new HubError('credential', e.message);
  }
  if (!TOKEN.test(token)) throw new HubError('credential', `The file ${file} does not hold a Fabric binding credential.`);
  return token;
}

/**
 * One MCP request to <origin>/mcp with a bearer in the header; only http://127.0.0.1:<port>, no proxy. Answers
 * {status, headers, body} (body parsed JSON or null; an SSE answer read to its first data: line). A refused connection
 * is HubError hub-unavailable (retryable).
 */
export function postMcp(origin, body, bearer, { session, timeout = 15000, method = 'POST', protocolVersion } = {}) {
  const m = LOOPBACK_ORIGIN.exec(origin);
  if (!m) return Promise.reject(new HubError('not-a-hub', 'Only the hub\'s loopback origin is used.'));
  const payload = method === 'DELETE' ? null : Buffer.from(JSON.stringify(body));
  const headers = { authorization: `Bearer ${bearer}`, 'content-type': 'application/json', accept: 'application/json, text/event-stream', host: `127.0.0.1:${m[1]}` };
  if (session) headers['mcp-session-id'] = session;
  if (protocolVersion) headers['mcp-protocol-version'] = protocolVersion;
  if (payload) headers['content-length'] = String(payload.length);
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: Number(m[1]), path: '/mcp', method, headers, timeout, agent: false }, (res) => {
      const chunks = [];
      let size = 0;
      res.on('data', (c) => {
        size += c.length;
        if (size <= 4 * 1024 * 1024) chunks.push(c);
      });
      res.on('end', () => {
        let text = Buffer.concat(chunks).toString('utf8');
        if (String(res.headers['content-type'] ?? '').includes('text/event-stream')) {
          text = (text.split(/\r?\n/).find((l) => l.startsWith('data:')) ?? '').slice(5).trim();
        }
        let parsed = null;
        try {
          parsed = text.trim() ? JSON.parse(text) : null;
        } catch {
          parsed = null;
        }
        resolve({ status: res.statusCode, headers: res.headers, body: parsed });
      });
      res.on('error', () => reject(new HubError('hub-unavailable', 'Fabric\'s hub did not answer (the answer broke off).', true)));
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', (e) => reject(new HubError('hub-unavailable', `Fabric's hub did not answer (${e.code ?? e.message}).`, true)));
    if (payload) req.write(payload);
    req.end();
  });
}

/** A tools/call answer as an object: structuredContent, else the first text content parsed. */
export function toolAnswer({ status, body }, tool) {
  if (status === 401) throw new HubError('credential', `The hub refused the credential for ${tool}.`);
  if (status === 429 || status >= 500) throw new HubError('hub-unavailable', `Fabric's hub could not take ${tool} just now (HTTP ${status}).`, true);
  if (status !== 200 || !body || typeof body !== 'object') throw new HubError('protocol', `Fabric's hub answered ${tool} with HTTP ${status} and no MCP answer.`, true);
  if (body.error) throw new HubError('protocol', `Fabric refused ${tool}: ${String(body.error?.message ?? 'an MCP error').slice(0, 200)}`);
  const result = body.result;
  if (!result || typeof result !== 'object') throw new HubError('protocol', `Fabric's answer to ${tool} has no result.`);
  let value = result.structuredContent;
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    const text = Array.isArray(result.content) && result.content[0] && typeof result.content[0].text === 'string' ? result.content[0].text : null;
    try {
      value = text === null ? null : JSON.parse(text);
    } catch {
      value = null;
    }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new HubError('protocol', `Fabric's answer to ${tool} is not a JSON object.`);
  return value;
}

/** What fabric.board.join handed out. The bearer is a private field, kept off JSON and inspection. */
export class BoardGrant {
  #bearer;
  constructor(bearer, sessionId, projectId, capabilities, origin, pid) {
    this.#bearer = bearer;
    this.sessionId = sessionId;
    this.projectId = projectId;
    this.capabilities = [...capabilities];
    this.origin = origin;
    this.pid = pid;
  }
  bearer() {
    return this.#bearer;
  }
}

/** The grant's resource, board:<project>/<capability> (ADR-0149 §2). */
export const boardResource = (projectId, capability) => `board:${projectId}/${capability}`;

/** A Project id as Fabric's board compares it: a uuid lower-cased; other ids are opaque, compared as written (DEC-0077). */
export function normalProject(projectId) {
  if (typeof projectId !== 'string' || !UUID.test(projectId)) throw new HubError('protocol', 'fabric.board.join takes a Project id that is a uuid.');
  return projectId.toLowerCase();
}

/** The door client. Every call re-reads hub.json first. `alive` and `post` are seams for tests. */
export class HubClient {
  constructor(root = fabricRoot(), { alive = pidAlive, timeout = 15000, estate, post = postMcp } = {}) {
    Object.assign(this, { root, alive, timeout, estate, post });
    this.rpc = 0;
  }

  locate() {
    return locateHub(this.root, { alive: this.alive, estate: this.estate });
  }

  async #call(bearerOf, tool, args) {
    const location = this.locate(); // the pid check, right before the credential leaves this process
    const bearer = bearerOf(location);
    this.rpc += 1;
    const answer = await this.post(location.origin, { jsonrpc: '2.0', id: this.rpc, method: 'tools/call', params: { name: tool, arguments: args } }, bearer, { timeout: this.timeout });
    const value = toolAnswer(answer, tool);
    if (value.error && typeof value.error === 'object' && typeof value.error.code === 'string') {
      const data = value.error.data && typeof value.error.data === 'object' ? value.error.data : {};
      throw new HubError(value.error.code, String(value.error.message ?? 'refused').slice(0, 300), value.error.code === 'hub-unavailable', data);
    }
    return value;
  }

  callDoor(tool, args) {
    return this.#call(readDoorToken, tool, args);
  }

  callBinding(tool, args, credentialFile) {
    return this.#call(() => readCredential(credentialFile), tool, args);
  }

  /** Ask the operator, once, to let agentId answer capabilities for projectId (fabric.access.request, board.respond). */
  async requestBoardAccess(agentId, projectId, capabilities, reason) {
    const project = normalProject(projectId);
    const caps = [...(capabilities ?? [])];
    if (!caps.length || caps.some((c) => typeof c !== 'string' || !CAPABILITY.test(c))) throw new HubError('protocol', 'Name at least one capability, each [a-z][a-z0-9._-]{1,127}.');
    return this.callDoor('fabric.access.request', { agentId, callee: 'fabric', capabilities: ['board.respond'], resources: caps.map((c) => boardResource(project, c)), reason });
  }

  /** Read the request through the door; on Allow the credential is written to credentialFile (0600) and left out. */
  async pollAccess(requestId, pollSecret, credentialFile) {
    const answer = await this.callDoor('fabric.access.status', { requestId, pollSecret });
    const { credential, ...rest } = answer;
    if (typeof credential === 'string') {
      if (!TOKEN.test(credential)) throw new HubError('protocol', 'Fabric handed out a credential this kit does not recognise; nothing was saved.');
      ensurePrivateDir(path.dirname(credentialFile));
      atomicWrite(credentialFile, credential, 0o600);
      rest.credentialSaved = true;
    }
    return rest;
  }

  /** fabric.board.join {projectId}: a board session for one Project. */
  async joinBoard(projectId, credentialFile) {
    const project = normalProject(projectId);
    let answer;
    try {
      answer = await this.callBinding('fabric.board.join', { projectId: project }, credentialFile);
    } catch (e) {
      if (e instanceof HubError && (e.code === 'not_authorized' || e.code === 'not-authorized')) {
        throw new HubError('not_authorized', 'The operator has not let this agent answer requests for that Project: ask with fabric.access.request (callee fabric, capability board.respond, resource board:<project>/<capability>).',
          false, { ask: { callee: 'fabric', capabilities: ['board.respond'], resources: [boardResource(project, '<capability>')] } });
      }
      throw e;
    }
    const s = answer.session;
    if (!s || typeof s !== 'object' || typeof s.bearer !== 'string' || typeof s.sessionId !== 'string') throw new HubError('protocol', 'fabric.board.join answered no board session.');
    if (s.projectId !== project) throw new HubError('protocol', 'fabric.board.join answered a session for another Project.');
    const caps = Array.isArray(s.capabilities) ? s.capabilities.filter((c) => typeof c === 'string') : [];
    const location = this.locate();
    return new BoardGrant(s.bearer, s.sessionId, project, caps, location.origin, location.pid);
  }
}

/** Bounded exponential backoff with jitter: first seconds doubling to cap, ±jitter, never under floor. */
export class Backoff {
  constructor({ first = 2, cap = 300, jitter = 0.2, floor = 1, rand = Math.random } = {}) {
    Object.assign(this, { first, cap, jitter, floor, rand });
    this.attempt = 0;
  }
  next() {
    const base = Math.min(this.cap, this.first * 2 ** Math.min(this.attempt, 32));
    this.attempt += 1;
    const wait = base * (1 + this.jitter * (2 * this.rand() - 1));
    return Math.max(this.floor, Math.min(this.cap, wait));
  }
  reset() {
    this.attempt = 0;
  }
}
