// OpenRouter chat completions for a service: its own key, a spend ceiling checked before every attempt, a usage receipt
// for every answered call, and a fallback model of another vendor. The twin of fabric_openrouter.py: the same rules, the
// same cases (test/fixtures/kit-openrouter-cases.json); the rules are written out in that file's docstring.
//
//   const client = new Client({ ceilingUsd: 2, ledger: new JsonlUsageLedger(file), prices: pricesFromCatalog(catalog) });
//   const answer = await client.chat([{ role: 'user', content: '...' }],
//     { model: 'deepseek/deepseek-v4.1-flash', fallback: 'qwen/qwen3.8-flash', maxTokens: 800 });
//   answer.content, answer.receipt.costUsd
//
// The key is read from the environment variable `keyEnv` names when a call is made, sent only in the Authorization
// header, never in an error. Before every attempt the window's spend (ledger receipts of the UTC day or month, plus
// calls in flight) plus this attempt's worst case (one token per two UTF-8 bytes of the messages as JSON, maxTokens of
// output, at the model's price) must stay within the ceiling. A 200 records one receipt; stop or tool_calls with
// content is an answer; error is retried on the model; length, content_filter and empty go to the fallback; 408, 429,
// 5xx and connection errors are retried within one deadline; 401, 402 and 403 stop at once. Attribution is off unless a
// setting is given (FAC-SEM-098). Node 20 or newer, no dependencies. Part of the service kit (FAA-65, layer L4).

import * as http from './fabric-http.mjs';
import { isObject } from './fabric-jsvalue.mjs';
import * as time from './fabric-time.mjs';
import { attributionHeaders, makeUsageReceipt } from './fabric-usage.mjs';

export const BASE_URL = 'https://openrouter.ai/api/v1';
export const ANSWERED = Object.freeze(['stop', 'tool_calls']);
const STOP_AT_ONCE = { 401: 'auth', 402: 'payment', 403: 'auth' };
const RESERVED_PARAMS = ['model', 'messages', 'max_tokens', 'max_completion_tokens', 'maxTokens', 'stream', 'usage'];
// Params that change what a call is billed for (other models, plugins, web search): the ceiling could not bound them.
const UNBOUNDED_PARAMS = ['models', 'route', 'plugins', 'web_search_options', 'n'];

export class OpenRouterError extends Error {
  constructor(message, { kind, attempts = [] } = {}) {
    super(message);
    this.name = 'OpenRouterError';
    this.kind = kind; // config, unpriced, ceiling, auth, payment, failed
    this.attempts = [...attempts];
  }
}

export const vendor = (model) => (String(model).includes('/') ? String(model).split('/', 1)[0] : '');

const DECIMAL = /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?$/;

// A catalog price (a plain decimal string such as "0.000001", or a number) or null: blank, hex, a list, negative or
// not finite are null, exactly as fabric_openrouter.py reads them.
function price(value) {
  let n;
  if (typeof value === 'string') n = DECIMAL.test(value) ? Number(value) : Number.NaN;
  else if (typeof value === 'number') n = value;
  else return null;
  return Number.isFinite(n) && n >= 0 ? n : null;
}

const count = (v) => (Number.isSafeInteger(v) && v >= 0 ? v : null); // as fabric_openrouter.py: 0 to 2**53 - 1

// Every message's content is text: a string, null, or parts that are all {type: 'text'}. An image, audio or file part is
// billed in ways a byte count cannot bound, so the client does not send it.
function textOnly(messages) {
  return messages.every((m) => isObject(m) && (m.content === null || m.content === undefined || typeof m.content === 'string'
    || (Array.isArray(m.content) && m.content.every((p) => isObject(p) && p.type === 'text'))));
}

// {model: {prompt, completion, request}} in USD per token (per request) from GET /api/v1/models; a model without a
// readable prompt or completion price is left out, so the client refuses it rather than guessing.
export function pricesFromCatalog(catalog) {
  const out = {};
  const rows = isObject(catalog) && Array.isArray(catalog.data) ? catalog.data : [];
  for (const row of rows) {
    if (!isObject(row) || typeof row.id !== 'string') continue;
    const pricing = isObject(row.pricing) ? row.pricing : {};
    const prompt = price(pricing.prompt);
    const completion = price(pricing.completion);
    if (prompt === null || completion === null) continue;
    out[row.id] = { prompt, completion, request: price(pricing.request) ?? 0 };
  }
  return out;
}

// One token per two UTF-8 bytes of what is sent as compact JSON: the messages and every param, all billed as input.
export const promptTokensBound = (value) => Math.ceil(http.jsonBytes(value).length / 2);

function checkAttribution(projectId, taskRunId) {
  try {
    makeUsageReceipt('openrouter', 'check', { inputTokens: 0, outputTokens: 0, projectId, taskRunId });
  } catch (err) {
    throw new OpenRouterError(err.message, { kind: 'config' });
  }
}

const CHAT_PATH = '/chat/completions';
// A control, a space or a format character (Unicode Cc, Z, Cf), the combining grapheme joiner, the Hangul fillers
// and the variation selectors: nothing an endpoint's path ends in.
const BAD_PATH_END = /[\p{Cc}\p{Z}\p{Cf}\p{Variation_Selector}\u034f\u115f\u1160\u3164\uffa0]/u;

// Whether the base's path, as `new URL` sends `${base}/chat/completions`, ends (trailing slashes aside) in such a
// character written as itself: `new URL` percent-encodes it into the path and every call would fail. Read from the
// URL as sent, so a backslash, a missing `//` or a dot segment cannot hide it; an ending the base already
// percent-encodes is sent as written, as on Python (each `%` is read as `%25`, so only what `new URL` encoded is
// decoded). 0.56.0 seam r20 to r24, unit r21 to r24, product r24; Python refuses such a character in check_url.
function sentPathEndsBadly(base) {
  let path;
  try {
    path = new URL(`${base.replaceAll('%', '%25')}${CHAT_PATH}`).pathname;
  } catch {
    return true;
  }
  if (!path.endsWith(CHAT_PATH)) return true; // not composed as chat() composes it: refuse rather than guess
  path = path.slice(0, -CHAT_PATH.length).replace(/\/+$/, '');
  const encoded = /(?:%[0-9A-Fa-f]{2})+$/.exec(path)?.[0];
  const last = encoded ? [...decodeURIComponent(encoded)].pop() : path.slice(-1); // `new URL` writes UTF-8
  return last !== undefined && last !== '' && BAD_PATH_END.test(last);
}

export class Client {
  constructor({ ceilingUsd, ledger, prices, keyEnv = 'OPENROUTER_API_KEY', window = 'day', baseUrl = BASE_URL,
    attribution = null, projectId, unmeasuredCallUsd = null, deadlineS = 120, retries = 1, env = process.env,
    transport, sleep, clock = () => performance.now() / 1000, now = () => Date.now() / 1000, rand = Math.random } = {}) {
    if (typeof ceilingUsd !== 'number' || !Number.isFinite(ceilingUsd) || ceilingUsd < 0) {
      throw new OpenRouterError('ceilingUsd is a finite number of dollars, 0 or more', { kind: 'config' });
    }
    if (!['day', 'month'].includes(window)) throw new OpenRouterError('window is day or month (UTC)', { kind: 'config' });
    if (!ledger || typeof ledger.record !== 'function' || typeof ledger.receipts !== 'function') {
      throw new OpenRouterError('ledger has record(receipt) and receipts(), as JsonlUsageLedger', { kind: 'config' });
    }
    if (!Number.isInteger(retries) || retries < 0 || retries > 5) {
      throw new OpenRouterError('retries is an integer from 0 to 5', { kind: 'config' });
    }
    http.checkUrl(baseUrl);
    if (/[?#]/.test(baseUrl)) { // `/chat/completions` would land in it (0.56.0 unit r19, FAA-187 (17))
      throw new OpenRouterError('the base URL holds no query or fragment', { kind: 'config' });
    }
    checkAttribution(projectId, undefined);
    Object.assign(this, { ceilingUsd, ledger, keyEnv, window, attribution, projectId, unmeasuredCallUsd, deadlineS, retries });
    this.prices = Object.fromEntries(Object.entries(prices ?? {}).map(([k, v]) => [k, { ...v }]));
    // The base URL as checkUrl read it: `new URL` removes tabs and line breaks anywhere and trims C0 controls and
    // spaces from its ends, so `.../v1/ ` and `.../v1\n/` are composed as `.../v1/chat/completions`, as `new URL`
    // composed them in 0.55.0 (0.56.0 product r20, unit r22, seam r22; the Python twin refuses what urllib cannot send).
    this.baseUrl = baseUrl.replace(/[\t\n\r]/g, '').replace(/^[\x00-\x20]+|[\x00-\x20]+$/g, '').replace(/\/+$/, '');
    if (sentPathEndsBadly(this.baseUrl)) {
      throw new OpenRouterError("the base URL's path ends in a space, a control or an invisible character", { kind: 'config' });
    }
    this.env = env;
    this.transport = transport;
    this.sleep = sleep ?? ((s) => new Promise((resolve) => setTimeout(resolve, s * 1000)));
    this.clock = clock;
    this.now = now;
    this.rand = rand;
    this.inFlight = 0;
    this.unmeasuredWorst = new Map(); // `${at} ${model}` of an unmeasured receipt -> that attempt's worst case
  }

  priced(model) {
    const p = this.prices[model];
    if (!isObject(p)) return null;
    const prompt = price(p.prompt);
    const completion = price(p.completion);
    if (prompt === null || completion === null) return null;
    return { prompt, completion, request: price(p.request) ?? 0 };
  }

  worstCaseUsd(model, messages, maxTokens, params = {}) {
    const p = this.priced(model);
    if (p === null) return null;
    return promptTokensBound({ ...params, messages }) * p.prompt + maxTokens * p.completion + p.request;
  }

  inWindow(at, today) {
    const ms = time.parseRfc3339Ms(at);
    if (Number.isNaN(ms)) return false;
    const day = time.utcDay(ms);
    return this.window === 'day' ? day === today : day.slice(0, 7) === today.slice(0, 7);
  }

  spentUsd({ unmeasuredUsd = 0 } = {}) {
    const today = time.utcDay(this.now() * 1000);
    let total = 0;
    for (const r of this.ledger.receipts()) {
      if (!isObject(r) || !this.inWindow(r.at, today)) continue;
      if (r.route === 'subscription') continue; // an estimate at list price, never money spent (DEC-0110)
      if (typeof r.costUsd === 'number' && price(r.costUsd) !== null) total += r.costUsd;
      else total += this.unmeasuredWorst.get(`${r.at} ${r.model}`) ?? unmeasuredUsd; // known here, else unmeasuredUsd
    }
    return total;
  }

  reserve(model, messages, maxTokens, params) {
    const worst = this.worstCaseUsd(model, messages, maxTokens, params);
    if (worst === null) {
      throw new OpenRouterError(`${model} has no price: its spend cannot be bounded, so it is not called`, { kind: 'unpriced' });
    }
    const unmeasured = this.unmeasuredCallUsd === null ? worst : Number(this.unmeasuredCallUsd);
    const spent = this.spentUsd({ unmeasuredUsd: unmeasured }) + this.inFlight;
    if (spent + worst > this.ceilingUsd) {
      throw new OpenRouterError(`the ${this.window} ceiling of $${this.ceilingUsd.toFixed(4)} would be passed: spent `
        + `$${spent.toFixed(4)}, this attempt up to $${worst.toFixed(4)}`, { kind: 'ceiling' });
    }
    this.inFlight += worst; // synchronous with the check: no other call can pass between them
    return worst;
  }

  release(amount) { this.inFlight = Math.max(0, this.inFlight - amount); }

  receipt(asked, body, taskRunId, worst) {
    const served = typeof body.model === 'string' && body.model.trim() ? body.model : asked;
    const usage = isObject(body.usage) ? body.usage : null;
    const common = { at: time.formatRfc3339(Math.trunc(this.now() * 1000)), route: 'key', projectId: this.projectId, taskRunId };
    const prompt = usage ? count(usage.prompt_tokens) : null;
    const completion = usage ? count(usage.completion_tokens) : null;
    if (prompt === null || completion === null) {
      const unmeasured = makeUsageReceipt('openrouter', served.slice(0, 128), { inputTokens: 0, outputTokens: 0, tokensMeasured: false, ...common });
      this.rememberUnmeasured(unmeasured, worst);
      return unmeasured;
    }
    const details = isObject(usage.prompt_tokens_details) ? usage.prompt_tokens_details : {};
    const cached = count(details.cached_tokens) ?? 0;
    const written = count(details.cache_write_tokens) ?? 0;
    let cost = typeof usage.cost === 'number' ? price(usage.cost) : null;
    let basis = 'provider';
    if (cost === null) {
      const p = this.priced(served) ?? this.priced(asked);
      if (p) { cost = prompt * p.prompt + completion * p.completion; basis = 'price-list'; }
    }
    return makeUsageReceipt('openrouter', served.slice(0, 128), {
      inputTokens: Math.max(0, prompt - cached - written), outputTokens: completion, cacheReadTokens: cached,
      cacheWriteTokens: written, costUsd: cost, costBasis: cost === null ? undefined : basis, ...common,
    });
  }

  // A receipt for an attempt that may have been billed with no usage to read: no tokens, no cost.
  unmeasured(asked, taskRunId, worst) {
    const receipt = makeUsageReceipt('openrouter', asked.slice(0, 128), { inputTokens: 0, outputTokens: 0, tokensMeasured: false,
      at: time.formatRfc3339(Math.trunc(this.now() * 1000)), route: 'key', projectId: this.projectId, taskRunId });
    this.rememberUnmeasured(receipt, worst);
    return receipt;
  }

  rememberUnmeasured(receipt, worst) {
    const key = `${receipt.at} ${receipt.model}`;
    this.unmeasuredWorst.set(key, (this.unmeasuredWorst.get(key) ?? 0) + worst);
  }

  key() {
    const key = this.env[this.keyEnv] ?? '';
    if (!key || /[\r\n\0 ]/.test(key)) throw new OpenRouterError(`no usable key in the environment variable ${this.keyEnv}`, { kind: 'config' });
    return key;
  }

  headers(key) {
    const headers = { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' };
    if (this.attribution !== null) {
      Object.assign(headers, attributionHeaders(this.attribution, { url: this.baseUrl, originated: true, headers: {} }).headers);
    }
    return headers;
  }

  async chat(messages, { model, fallback, maxTokens, taskRunId, ...params } = {}) {
    if (!Array.isArray(messages) || messages.length === 0) throw new OpenRouterError('messages is a non-empty list', { kind: 'config' });
    if (!textOnly(messages)) {
      throw new OpenRouterError('only text content is sent: an image, audio or file part has a cost the ceiling cannot bound', { kind: 'config' });
    }
    if (!vendor(model) || !vendor(fallback) || vendor(model) === vendor(fallback)) {
      throw new OpenRouterError(`the fallback is a model of another vendor than ${model}`, { kind: 'config' });
    }
    if (!Number.isInteger(maxTokens) || maxTokens < 1 || maxTokens > 200_000) {
      throw new OpenRouterError('maxTokens is an integer from 1 to 200000', { kind: 'config' });
    }
    checkAttribution(this.projectId, taskRunId); // before anything is sent: a billed call keeps its receipt
    const clash = Object.keys(params).filter((k) => RESERVED_PARAMS.includes(k));
    if (clash.length) throw new OpenRouterError(`the client sets ${clash.sort().join(', ')} itself`, { kind: 'config' });
    const unbounded = Object.keys(params).filter((k) => UNBOUNDED_PARAMS.includes(k));
    if (unbounded.length) {
      throw new OpenRouterError(`${unbounded.sort().join(', ')} change what a call is billed for; the ceiling cannot bound them`, { kind: 'config' });
    }
    try {
      promptTokensBound({ ...params, messages });
    } catch {
      throw new OpenRouterError('the request holds a number JSON cannot write (NaN or Infinity)', { kind: 'config' });
    }
    const headers = this.headers(this.key());
    const url = `${this.baseUrl}/chat/completions`;
    const end = this.clock() + this.deadlineS;
    const attempts = [];
    for (const current of [model, fallback]) {
      const body = { model: current, messages, max_tokens: maxTokens, usage: { include: true }, ...params };
      for (let tried = 0; tried <= this.retries; tried += 1) {
        const left = end - this.clock();
        if (left <= 0) throw new OpenRouterError(`the deadline passed after ${attempts.length} attempts`, { kind: 'failed', attempts });
        let held;
        try {
          held = this.reserve(current, messages, maxTokens, params);
        } catch (err) {
          err.attempts = [...attempts];
          throw err;
        }
        let result;
        try {
          result = await this.attempt(url, headers, body, left, current, taskRunId, held);
        } finally {
          this.release(held);
        }
        attempts.push({ model: current, status: result.status, outcome: result.outcome });
        if (result.answer) return { ...result.answer, attempts };
        if (Object.values(STOP_AT_ONCE).includes(result.outcome)) {
          throw new OpenRouterError(`OpenRouter refused the key or the request (${result.status})`, { kind: result.outcome, attempts });
        }
        if (!['retry', 'error'].includes(result.outcome) || tried === this.retries) break;
        const wait = result.wait ?? http.backoffS(tried, { baseS: 0.5, maxS: 8, rand: this.rand() });
        if (this.clock() + wait >= end) break;
        await this.sleep(wait);
      }
    }
    throw new OpenRouterError(`no answer from ${model} or ${fallback}`, { kind: 'failed', attempts });
  }

  async attempt(url, headers, body, left, asked, taskRunId, worst) {
    let response;
    try {
      response = await http.request('POST', url, { headers, body, deadlineS: left, retries: 0, transport: this.transport, clock: this.clock });
    } catch (err) {
      if (!(err instanceof http.HttpError)) throw err;
      if (['timeout', 'connection'].includes(err.kind) || (err.kind === 'too-large' && err.status === 200)) {
        // may have been billed (a cut connection looks like a refused one from here): counted, never as $0
        this.ledger.record(this.unmeasured(asked, taskRunId, worst));
      }
      return { outcome: ['connection', 'timeout'].includes(err.kind) ? 'retry' : 'refused', status: err.status };
    }
    const { status } = response;
    if (STOP_AT_ONCE[status]) return { outcome: STOP_AT_ONCE[status], status };
    if (status !== 200) {
      if (http.RETRY_STATUSES.includes(status)) return { outcome: 'retry', status, wait: http.retryAfterS(response.headers['retry-after'] ?? null) };
      return { outcome: 'refused', status };
    }
    let parsed = null;
    try { parsed = response.json(); } catch { /* read as no answer below */ }
    if (!isObject(parsed)) {
      this.ledger.record(this.unmeasured(asked, taskRunId, worst));
      return { outcome: 'bad-answer', status };
    }
    let receipt;
    try {
      receipt = this.receipt(asked, parsed, taskRunId, worst);
    } catch {
      this.ledger.record(this.unmeasured(asked, taskRunId, worst)); // a billed answer it cannot read still counts
      return { outcome: 'bad-answer', status };
    }
    this.ledger.record(receipt);
    const choice = Array.isArray(parsed.choices) && isObject(parsed.choices[0]) ? parsed.choices[0] : {};
    const message = isObject(choice.message) ? choice.message : {};
    const finish = choice.finish_reason;
    const content = typeof message.content === 'string' ? message.content : '';
    const tools = Array.isArray(message.tool_calls) ? message.tool_calls : [];
    if (finish === 'error' || isObject(parsed.error)) return { outcome: 'error', status };
    if (finish === 'length') return { outcome: 'length', status };
    if (finish === 'content_filter') return { outcome: 'filtered', status };
    if (!ANSWERED.includes(finish) || !(content.trim() || tools.length)) return { outcome: 'empty', status };
    return { outcome: 'answered', status, answer: { content, message, model: receipt.model, finishReason: finish, receipt } };
  }
}

// Calls, money spent and unpriced calls over receipts. A subscription receipt's cost is an estimate, never money
// (DEC-0110): spentUsd is null only when calls off a subscription exist and none is priced, 0 when all were on one.
export function totals(receipts) {
  let calls = 0;
  let priced = 0;
  let paid = 0;
  let paidPriced = 0;
  let spent = 0;
  for (const r of receipts) {
    calls += 1;
    const onSubscription = r.route === 'subscription';
    if (!onSubscription) paid += 1;
    if (typeof r.costUsd === 'number' && price(r.costUsd) !== null) {
      priced += 1;
      if (!onSubscription) { paidPriced += 1; spent += r.costUsd; }
    }
  }
  return { calls, spentUsd: paid && !paidPriced ? null : spent, unpricedCalls: calls - priced };
}
