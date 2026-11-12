// An outbound HTTP client for a service: one deadline across every attempt, bounded retries with jittered backoff,
// `Retry-After` honoured up to a cap, a response size cap, and no secret in an error. The twin of fabric_http.py:
// the same rules, the same cases (test/fixtures/kit-http-cases.json).
//
//   const response = await request('GET', 'https://api.example/v1/items', { headers: {...}, deadlineS: 20, retries: 2 });
//   response.status, response.headers['content-type'], response.json()
//
// What is retried: a status in RETRY_STATUSES or a connection error, at most `retries` times, and only when repeating
// is safe: an idempotent method or an `Idempotency-Key` header; any other request only on 429. The wait before retry n
// (from 0) is min(maxBackoffS, backoffBaseS * 2**n) * (0.5 + rand()); a `Retry-After` replaces it up to
// maxRetryAfterS. A wait past the deadline is not taken. Plain http is refused unless the host is loopback or
// `insecure`. An error names the method and the redacted URL, never a header or a body. Before a byte goes to a plain
// http loopback URL the server end of the connection is told from the socket table (DEC-0154 HA-2, FAA-226): not this
// OS account's process, or an owner that cannot be told, is an HttpError of kind foreign-user, nothing sent, not retried.
//
// The transport is injected in tests: async ({ method, url, headers, body, timeoutS, maxBytes }) =>
// { status, headers, body: Uint8Array }, throwing on a connection error (a `TimeoutError` name is a timeout) or an
// HttpError. Node 20 or newer, no dependencies. Part of the service kit (FAA-65, layer L4).
//
// Example URLs write their scheme in angle brackets: read `<https>` as `https` (FAA-212).

import http from 'node:http';
import { CheckedAgent, ListenerRefused } from './fabric-peer-owner.mjs';

export const RETRY_STATUSES = Object.freeze([408, 425, 429, 500, 502, 503, 504]);
export const IDEMPOTENT_METHODS = Object.freeze(['GET', 'HEAD', 'OPTIONS', 'PUT', 'DELETE']);
export const DEFAULT_MAX_BYTES = 8 * 1024 * 1024;
const TOKEN = /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/;

export class HttpError extends Error {
  constructor(message, { status = null, url = '', attempts = 0, retryAfterS = null, body = new Uint8Array(0),
    kind = 'http' } = {}) {
    super(message);
    this.name = 'HttpError';
    this.status = status;
    this.url = url;
    this.attempts = attempts;
    this.retryAfterS = retryAfterS;
    this.body = body.slice(0, 2048);
    this.kind = kind; // http, connection, timeout, too-large, refused, foreign-user
  }
}

export class Response {
  constructor(status, headers, body, { attempts = 1, url = '' } = {}) {
    this.status = status;
    this.headers = Object.fromEntries(Object.entries(headers).map(([k, v]) => [String(k).toLowerCase(), String(v)]));
    this.body = body;
    this.attempts = attempts;
    this.url = url;
  }

  get ok() { return this.status >= 200 && this.status < 300; }

  text() { return new TextDecoder().decode(this.body); }

  json() { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(this.body)); }
}

// The URL as it may appear in an error or a log line: scheme, host, port and path; no userinfo, query or fragment.
export function redactUrl(url) {
  let text = String(url).replace(/^[\x00-\x20]+|[\x00-\x20]+$/g, '').replace(/[\t\n\r]/g, '');
  // The user information as written goes first, as the Python twin drops it: `<https>://h\\u:pw@x/r` would print `pw` in
  // its path, a backslash being a slash to WHATWG (0.62.0 seam reading 11).
  const written = /^([A-Za-z][A-Za-z0-9+.-]*:[/\\]*)([^/?#]*)/.exec(text); // after any run of slashes (seam reading 13)
  if (written && written[2].includes('@')) text = written[1] + written[2].slice(written[2].lastIndexOf('@') + 1) + text.slice(written[0].length);
  let parts;
  try { parts = new URL(text); } catch {
    // a scheme other than a special one keeps its name, as the Python twin prints it whatever follows (unit reading 14)
    const scheme = /^([A-Za-z][A-Za-z0-9+.-]*):/.exec(text)?.[1].toLowerCase();
    return scheme && !['http', 'https', 'ws', 'wss', 'ftp'].includes(scheme) ? `${scheme}:<redacted>` : '<unparseable url>';
  }
  // Only http and https are sent; any other scheme keeps no more than its name (0.56.0 product r10).
  if (parts.protocol !== 'http:' && parts.protocol !== 'https:') return `${parts.protocol}<redacted>`;
  return `${parts.protocol}//${parts.host}${parts.pathname}`;
}

function isLoopback(host) {
  const h = host.replace(/^\[|\]$/g, '');
  if (h === 'localhost' || h.endsWith('.localhost') || h === '::1') return true;
  return /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(h);
}

// Refuse what this client never sends: another scheme, no host, credentials in the URL, plain http off loopback.
export function checkUrl(url, { insecure = false } = {}) {
  let parts;
  try { parts = new URL(String(url)); } catch {
    throw new HttpError('the URL does not parse', { url: redactUrl(url), kind: 'refused' });
  }
  if (!['http:', 'https:'].includes(parts.protocol) || !parts.hostname) {
    throw new HttpError('only http and https URLs with a host are sent', { url: redactUrl(url), kind: 'refused' });
  }
  // the user information as written, read on the text `new URL` reads (C0 and space off its ends, tab, CR and LF out),
  // so `<ht\ttps>://h\\u:pw@x/r` is refused as the Python twin refuses it (0.62.0 unit reading 12)
  const text = String(url).replace(/^[\x00-\x20]+|[\x00-\x20]+$/g, '').replace(/[\t\n\r]/g, '');
  if (parts.username || parts.password || /^[a-z][a-z0-9+.-]*:[/\\]*[^/?#]*@/i.test(text)) {
    throw new HttpError('credentials in a URL are refused: send them in a header', { url: redactUrl(url), kind: 'refused' });
  }
  if (parts.protocol === 'http:' && !insecure && !isLoopback(parts.hostname)) {
    throw new HttpError('plain http to a host that is not loopback is refused (insecure to allow)',
      { url: redactUrl(url), kind: 'refused' });
  }
}

const IMF_FIXDATE = /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), (\d\d) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{4}) (\d\d):(\d\d):(\d\d) GMT$/;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// Seconds a `Retry-After` asks for: a non-negative integer, or an IMF-fixdate read from `now` (epoch seconds),
// never below 0; null otherwise.
export function retryAfterS(value, { now } = {}) {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  if (/^[0-9]{1,10}$/.test(text)) return Number(text);
  const m = IMF_FIXDATE.exec(text);
  if (!m) return null;
  const [day, month, year, hh, mm, ss] = [Number(m[2]), MONTHS.indexOf(m[3]), Number(m[4]), Number(m[5]),
    Number(m[6]), Number(m[7])];
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  if (hh > 23 || mm > 59 || ss > 60 || day < 1 || day > lastDay || year < 1000) return null; // Date.UTC maps 0-99
  const when = Date.UTC(year, month, day, hh, mm, Math.min(ss, 59)) / 1000;
  return Math.max(0, when - (now ?? Date.now() / 1000));
}

// Compact JSON in UTF-8, NaN and Infinity refused (JSON.stringify would write null): the twin of json_bytes.
export function jsonBytes(value) {
  const text = JSON.stringify(value, (key, v) => {
    if (typeof v === 'number' && !Number.isFinite(v)) {
      throw new HttpError('the body holds a number JSON cannot write (NaN or Infinity)', { kind: 'refused' });
    }
    return v;
  });
  return new TextEncoder().encode(text);
}

export function backoffS(attempt, { baseS, maxS, rand }) {
  return Math.min(maxS, baseS * 2 ** attempt) * (0.5 + rand);
}

export function mayRetry(method, headers, status) {
  if (status !== null && !RETRY_STATUSES.includes(status)) return false;
  const safe = IDEMPOTENT_METHODS.includes(String(method).toUpperCase())
    || Object.keys(headers).some((k) => k.toLowerCase() === 'idempotency-key');
  return safe || status === 429;
}

function checkHeaders(headers) {
  const out = {};
  for (const [name, value] of Object.entries(headers)) {
    const v = String(value);
    if (!TOKEN.test(String(name))) throw new HttpError('a header name is not an HTTP token', { kind: 'refused' });
    if (/[\r\n\0]/.test(v)) throw new HttpError('a header value carries a line break or NUL', { kind: 'refused' });
    out[String(name)] = v;
  }
  return out;
}

const LOOPBACK_AGENT = new CheckedAgent();

// Plain http to a loopback host (DEC-0154 HA-2): node:http over a connection checked before a byte is written, no
// redirect followed, the body read to one byte past maxBytes. fetch cannot hand its socket to the check.
export function checkedLoopbackTransport({ method, url, headers, body, timeoutS, maxBytes, agent = LOOPBACK_AGENT }) {
  const parts = new URL(url);
  // A body goes with its Content-Length, as fetch sent it: a server that reads only Content-Length (the kit's
  // sample_service, the stdlib handlers) would read a chunked body as empty (0.74.0 seam reading 1).
  const sent = { ...headers };
  if (body && !Object.keys(sent).some((k) => k.toLowerCase() === 'content-length')) sent['Content-Length'] = String(body.length);
  return new Promise((resolve, reject) => {
    const req = http.request({ host: parts.hostname.replace(/^\[|\]$/g, ''), port: Number(parts.port || 80),
      path: parts.pathname + parts.search, method, headers: sent, agent }, (res) => {
      const chunks = [];
      let size = 0;
      res.on('data', (c) => {
        if (size <= maxBytes) { chunks.push(c); size += c.length; }
        if (size > maxBytes) res.destroy();
      });
      res.on('close', () => {
        clearTimeout(timer);
        const all = Buffer.concat(chunks);
        const got = Object.fromEntries(Object.entries(res.headers).map(([k, v]) => [k, Array.isArray(v) ? v.join(', ') : String(v)]));
        if (!res.complete && size <= maxBytes) reject(Object.assign(new Error('the answer broke off'), { name: 'ConnectionError' }));
        else resolve({ status: res.statusCode, headers: got, body: new Uint8Array(all.subarray(0, maxBytes + 1)) });
      });
    });
    const timer = setTimeout(() => req.destroy(Object.assign(new Error('timed out'), { name: 'TimeoutError' })),
      Math.max(1, Math.ceil(timeoutS * 1000)));
    req.on('error', (err) => {
      clearTimeout(timer);
      if (err instanceof ListenerRefused) {
        reject(new HttpError(`${method} ${redactUrl(url)}: foreign-user: ${err.message}`, { url: redactUrl(url), kind: 'foreign-user' }));
      } else reject(err);
    });
    if (body) req.write(body);
    req.end();
  });
}

// The default transport: fetch, no redirects followed, the body read to one byte past maxBytes; plain http to a
// loopback host goes through checkedLoopbackTransport.
export async function fetchTransport({ method, url, headers, body, timeoutS, maxBytes }) {
  const target = new URL(url);
  if (target.protocol === 'http:' && isLoopback(target.hostname)) {
    return checkedLoopbackTransport({ method, url, headers, body, timeoutS, maxBytes });
  }
  const res = await fetch(url, { method, headers, body: body ?? undefined, redirect: 'manual',
    signal: AbortSignal.timeout(Math.max(1, Math.ceil(timeoutS * 1000))) });
  const chunks = [];
  let size = 0;
  if (res.body) {
    const reader = res.body.getReader();
    try {
      while (size <= maxBytes) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        size += value.length;
      }
    } finally {
      await reader.cancel().catch(() => {});
    }
  }
  const all = new Uint8Array(size);
  let at = 0;
  for (const c of chunks) { all.set(c, at); at += c.length; }
  return { status: res.status, headers: Object.fromEntries(res.headers.entries()), body: all.slice(0, maxBytes + 1) };
}

const sleepMs = (s) => new Promise((resolve) => setTimeout(resolve, s * 1000));

export async function request(method, url, {
  headers = {}, body = null, deadlineS = 30, retries = 2, maxBytes = DEFAULT_MAX_BYTES, backoffBaseS = 0.5,
  maxBackoffS = 8, maxRetryAfterS = 30, insecure = false, transport = fetchTransport, sleep = sleepMs,
  clock = () => performance.now() / 1000, rand = Math.random,
} = {}) {
  method = String(method).toUpperCase();
  if (!TOKEN.test(method)) throw new HttpError('the method is not an HTTP token', { kind: 'refused' });
  if (!Number.isInteger(retries) || retries < 0 || retries > 10) {
    throw new HttpError('retries is an integer from 0 to 10', { kind: 'refused' });
  }
  if (!(deadlineS > 0 && maxBytes > 0)) throw new HttpError('deadlineS and maxBytes are positive', { kind: 'refused' });
  checkUrl(url, { insecure });
  const sent = checkHeaders(headers ?? {});
  let data = null;
  if (body === null || body === undefined) data = null;
  else if (body instanceof Uint8Array) data = body;
  else if (body instanceof ArrayBuffer) data = new Uint8Array(body);
  else if (typeof body === 'string') data = new TextEncoder().encode(body);
  else if (typeof body === 'object') {
    data = jsonBytes(body);
    if (!Object.keys(sent).some((k) => k.toLowerCase() === 'content-type')) sent['Content-Type'] = 'application/json';
  } else throw new HttpError('the body is bytes, a string, an object or an array', { kind: 'refused' });
  const where = redactUrl(url);
  const end = clock() + deadlineS;
  let attempt = 0;
  for (;;) {
    const left = end - clock();
    if (left <= 0) {
      throw new HttpError(`${method} ${where}: the deadline passed before an answer`,
        { url: where, attempts: attempt, kind: 'timeout' });
    }
    attempt += 1;
    let got = null;
    let failure = null;
    try {
      got = await transport({ method, url, headers: { ...sent }, body: data, timeoutS: left, maxBytes });
    } catch (err) {
      if (err instanceof HttpError) throw err;
      failure = err?.name === 'TimeoutError' || err?.name === 'AbortError'
        ? new HttpError(`${method} ${where}: timed out`, { url: where, attempts: attempt, kind: 'timeout' })
        : new HttpError(`${method} ${where}: connection error (${err?.name ?? 'Error'})`,
          { url: where, attempts: attempt, kind: 'connection' });
    }
    let answer = null;
    let wait;
    if (failure === null) {
      if (got.body.length > maxBytes) {
        throw new HttpError(`${method} ${where}: the answer is over ${maxBytes} bytes`,
          { status: got.status, url: where, attempts: attempt, kind: 'too-large' });
      }
      answer = new Response(got.status, got.headers, got.body, { attempts: attempt, url: where });
      if (!mayRetry(method, sent, answer.status) || attempt > retries) return answer;
      wait = retryAfterS(answer.headers['retry-after'] ?? null);
      if (wait !== null) {
        if (wait > maxRetryAfterS) return answer;
      } else {
        wait = backoffS(attempt - 1, { baseS: backoffBaseS, maxS: maxBackoffS, rand: rand() });
      }
    } else {
      if (!mayRetry(method, sent, null) || attempt > retries) throw failure;
      wait = backoffS(attempt - 1, { baseS: backoffBaseS, maxS: maxBackoffS, rand: rand() });
    }
    if (clock() + wait >= end) {
      if (answer !== null) return answer;
      throw failure;
    }
    await sleep(wait);
  }
}
