// FAA-65 REQ-07: fabric-openrouter.mjs, on the cases fabric_openrouter.py reads too. No test opens the network or holds
// a real key.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import * as fo from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-openrouter.mjs';
import { makeUsageReceipt } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-usage.mjs';

const CASES = JSON.parse(fs.readFileSync(new URL('./fixtures/kit-openrouter-cases.json', import.meta.url), 'utf8'));
const NOW = 1792584000; // 2026-10-21T12:00:00Z
const KEY = 'sk-or-v1-test-only-not-a-key';
const MESSAGES = [{ role: 'user', content: 'hi' }];

class Ledger {
  constructor(rows = []) { this.rows = [...rows]; }
  record(r) { this.rows.push(r); }
  receipts() { return [...this.rows]; }
}

function scripted(steps, seen) {
  const left = [...steps];
  return async ({ url, headers, body }) => {
    seen.push({ url, headers, body: JSON.parse(new TextDecoder().decode(body)) });
    const step = left.shift();
    if (step.error === 'timeout') throw Object.assign(new Error('slow'), { name: 'TimeoutError' });
    if (step.error === 'connection') throw Object.assign(new Error('refused'), { name: 'TypeError' });
    const raw = step.raw ?? JSON.stringify(step.body ?? {});
    return { status: step.status, headers: step.headers ?? {}, body: new TextEncoder().encode(raw) };
  };
}

function client(c, seen, ledger, extra = {}) {
  const sleeps = [];
  let now = 0;
  const cl = new fo.Client({ ceilingUsd: c.ceilingUsd ?? 1, ledger, prices: { ...CASES.prices, ...(c.prices ?? {}) },
    env: c.noKey ? {} : { OPENROUTER_API_KEY: KEY }, transport: scripted(c.steps ?? [], seen),
    sleep: async (s) => { sleeps.push(s); now += s; }, clock: () => now, now: () => NOW, rand: () => 0.5, ...extra });
  return { cl, sleeps };
}

async function run(c) {
  const seen = [];
  const ledger = new Ledger(c.ledger ?? []);
  const { cl, sleeps } = client(c, seen, ledger);
  let got;
  try {
    const a = await cl.chat(c.messages ?? MESSAGES, { model: c.model ?? 'a/one', fallback: c.fallback ?? 'b/two', maxTokens: 100, ...(c.params ?? {}) });
    got = { content: a.content, model: a.model, outcomes: a.attempts.map((x) => x.outcome), sleeps };
  } catch (err) {
    if (!(err instanceof fo.OpenRouterError)) throw err;
    got = { error: err.kind, outcomes: err.attempts.map((x) => x.outcome), message: err.message };
  }
  return { got, ledger, seen };
}

test('the prompt bound and the catalog', () => {
  for (const [messages, expected] of CASES.promptBound) assert.equal(fo.promptTokensBound(messages), expected);
  assert.deepEqual(fo.pricesFromCatalog(CASES.catalog.in), CASES.catalog.out);
  assert.deepEqual(fo.pricesFromCatalog(null), {});
});

test('the shared scenarios', async () => {
  for (const c of CASES.scenarios) {
    const { got, ledger } = await run(c);
    const { receipts, receiptCount, ...expect } = c.expect;
    delete got.message;
    assert.deepEqual(got, expect, c.name);
    if (receipts) {
      assert.equal(ledger.rows.length, receipts.length, c.name);
      receipts.forEach((wanted, i) => {
        const actual = ledger.rows[i];
        for (const [key, value] of Object.entries(wanted)) {
          if (key === 'costUsd' && value !== null) assert.ok(Math.abs(actual[key] - value) < 1e-12, `${c.name} ${key}`);
          else assert.deepEqual(actual[key], value, `${c.name} ${key}`);
        }
        const rebuilt = makeUsageReceipt(actual.provider, actual.model, { inputTokens: actual.inputTokens,
          outputTokens: actual.outputTokens, cacheReadTokens: actual.cacheReadTokens, cacheWriteTokens: actual.cacheWriteTokens,
          costUsd: actual.costUsd, costBasis: actual.costBasis, at: actual.at, route: actual.route,
          tokensMeasured: actual.tokensMeasured ?? true });
        assert.deepEqual(rebuilt, actual, 'a receipt the kit itself would build');
      });
    }
    if (receiptCount !== undefined) assert.equal(ledger.rows.length, receiptCount, c.name);
  }
});

test('the request, no key in an error, attribution off by default', async () => {
  const { got, seen } = await run({ steps: [{ status: 503 }, { status: 503 }, { status: 400 }] });
  assert.equal(got.error, 'failed');
  assert.ok(!got.message.includes(KEY));
  assert.equal(seen[0].url, 'https://openrouter.ai/api/v1/chat/completions');
  assert.equal(seen[0].headers.Authorization, `Bearer ${KEY}`);
  assert.deepEqual(seen[0].body, { model: 'a/one', messages: MESSAGES, max_tokens: 100, usage: { include: true } });
  assert.equal(seen[2].body.model, 'b/two');
  for (const h of Object.keys(seen[0].headers)) assert.ok(!['http-referer', 'x-openrouter-title', 'x-title'].includes(h.toLowerCase()));
  const attributed = [];
  const { cl } = client({ steps: [{ status: 200, body: { choices: [{ finish_reason: 'stop', message: { content: 'x' } }] } }] },
    attributed, new Ledger(), { attribution: { product: 'example-agent', title: 'Example Agent', categories: ['cloud-agent'] } });
  await cl.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 100 });
  assert.equal(attributed[0].headers['HTTP-Referer'], 'https://passioncode.ai/example-agent/');
});

test('params, refusals and receipts that name a project', async () => {
  const seen = [];
  const ok = { status: 200, body: { choices: [{ finish_reason: 'stop', message: { content: 'x' } }] } };
  const { cl } = client({ steps: [ok] }, seen, new Ledger());
  await cl.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 100, temperature: 0, reasoning: { effort: 'low' } });
  assert.equal(seen[0].body.temperature, 0);
  await assert.rejects(cl.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 100, taskRunId: 'run-1' }),
    (e) => e.kind === 'config' && seen.length === 1);
  for (const bad of [{ stream: true }, { usage: {} }, { max_tokens: 5 }]) {
    await assert.rejects(cl.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 100, ...bad }), fo.OpenRouterError);
  }
  for (const opts of [{ maxTokens: 0 }, { maxTokens: 1.5 }, { fallback: 'nofallback' }]) {
    await assert.rejects(cl.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 100, ...opts }), fo.OpenRouterError);
  }
  await assert.rejects(cl.chat([], { model: 'a/one', fallback: 'b/two', maxTokens: 100 }), fo.OpenRouterError);
  const ledger = new Ledger();
  const named = client({ steps: [ok] }, [], ledger, { projectId: 'urn:example:project' }).cl;
  await named.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 100, taskRunId: 'run-1' });
  assert.equal(ledger.rows[0].projectId, 'urn:example:project');
  assert.equal(ledger.rows[0].taskRunId, 'run-1');
});

test('unmeasured calls, calls in flight and the month window count toward the ceiling', async () => {
  const unmeasured = { at: '2026-10-21T01:00:00Z', provider: 'openrouter', model: 'a/one', inputTokens: 0, outputTokens: 0,
    cacheReadTokens: 0, cacheWriteTokens: 0, costUsd: null, costBasis: 'unknown', tokensMeasured: false };
  assert.equal((await run({ ceilingUsd: 0.002, ledger: [unmeasured], steps: [] })).got.error, 'ceiling');
  const ok = { status: 200, body: { choices: [{ finish_reason: 'stop', message: { content: 'x' } }] } };
  const free = client({ ceilingUsd: 0.002, steps: [ok] }, [], new Ledger([unmeasured]), { unmeasuredCallUsd: 0 }).cl;
  assert.equal((await free.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 100 })).content, 'x');

  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const slow = new fo.Client({ ceilingUsd: 0.0015, ledger: new Ledger(), prices: CASES.prices, env: { OPENROUTER_API_KEY: KEY },
    now: () => NOW, transport: async () => { await gate; return { status: 200, headers: {}, body: new TextEncoder().encode(JSON.stringify(ok.body)) }; } });
  const first = slow.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 100 });
  await assert.rejects(slow.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 100 }), (e) => e.kind === 'ceiling');
  release();
  assert.equal((await first).content, 'x');
  assert.equal(slow.inFlight, 0);

  const old = { at: '2026-10-02T01:00:00Z', costUsd: 0.0015 };
  assert.equal((await run({ ceilingUsd: 0.002, ledger: [old], steps: [ok] })).got.content, 'x');
  const monthly = client({ ceilingUsd: 0.002 }, [], new Ledger([old]), { window: 'month' }).cl;
  await assert.rejects(monthly.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 100 }), (e) => e.kind === 'ceiling');
});

test('config refusals and totals', () => {
  for (const opts of [{ ceilingUsd: -1 }, { ceilingUsd: Number.NaN }, { ceilingUsd: true }, { window: 'week' }, { retries: 9 },
    { ledger: {} }, { baseUrl: 'http://openrouter.ai/api/v1' }]) {
    assert.throws(() => new fo.Client({ ceilingUsd: 1, ledger: new Ledger(), prices: {}, ...opts }), Error, JSON.stringify(opts));
  }
  assert.deepEqual(fo.totals([{ costUsd: 0.5 }, { costUsd: null }, { costUsd: 0.25 }]), { calls: 3, spentUsd: 0.75, unpricedCalls: 1 });
  assert.deepEqual(fo.totals([{ costUsd: null }]), { calls: 1, spentUsd: null, unpricedCalls: 1 });
  assert.deepEqual(fo.totals([]), { calls: 0, spentUsd: 0, unpricedCalls: 0 }); // no call spent nothing
  // DEC-0110 (the seam reading of 0.48.3): a subscription's cost is an estimate, never money spent.
  assert.deepEqual(fo.totals([{ costUsd: 2, route: 'subscription' }, { costUsd: 0.5, route: 'key' }]), { calls: 2, spentUsd: 0.5, unpricedCalls: 0 });
  assert.deepEqual(fo.totals([{ costUsd: 2, route: 'subscription' }]), { calls: 1, spentUsd: 0, unpricedCalls: 0 });
  assert.deepEqual(fo.totals([{ costUsd: 2, route: 'subscription' }, { costUsd: null }]), { calls: 2, spentUsd: null, unpricedCalls: 1 });
});

test('a base URL ending in a line break or a space is composed without it', () => {
  // 0.56.0 product r20: checkUrl reads the base with its ends trimmed, so the base composed must be that one.
  for (const baseUrl of ['https://openrouter.ai/api/v1\n', 'https://openrouter.ai/api/v1/ ', 'https://openrouter.ai/api/v1/\r\n',
    'https://openrouter.ai/api/v1\n/', 'https://openrouter.ai/api/v1\t/']) { // `new URL` removes a tab or line break anywhere
    const c = new fo.Client({ ceilingUsd: 1, ledger: new Ledger(), prices: {}, baseUrl });
    assert.equal(c.baseUrl, 'https://openrouter.ai/api/v1', JSON.stringify(baseUrl));
  }
  // unit r23: only the path is read, as `new URL` sends it: a host `new URL` reads (U+200B dropped by IDNA) and a
  // path with a letter outside ASCII are kept.
  // seam r24, unit r24: an ending the base already percent-encodes is sent as written, as on Python.
  for (const baseUrl of ['https://openrouter.ai\u200b', 'https://gw.example/caf\u00e9/v1', 'HTTPS://openrouter.ai/api/v1/.',
    'https://gw.example/v1%C2%A0', 'https://gw.example/v1%20', 'https://gw.example/v1%FF%61', 'https://gw.example/v1%E9',
    'https://openrouter.ai/api/v1\\']) {
    assert.doesNotThrow(() => new fo.Client({ ceilingUsd: 1, ledger: new Ledger(), prices: {}, baseUrl }), JSON.stringify(baseUrl));
  }
  // 0.56.0 unit r19, seam r20: a query or fragment would take `/chat/completions`; a Unicode space at the end stays
  // in the path. Both are refused when the client is built.
  for (const baseUrl of ['https://openrouter.ai/api/v1?x=1', 'https://openrouter.ai/api/v1#f', 'https://openrouter.ai/api/v1\u00a0',
    'https://openrouter.ai/api/v1\u3000', 'https://openrouter.ai/api/v1\u00a0\n', 'https://openrouter.ai/api/v1\u00a0/',
    'https://openrouter.ai/api/v1\u3000/', 'https://openrouter.ai/api/v1\u0085', 'https://openrouter.ai/api/v1\u200b',
    'https://openrouter.ai/api/v1\u180e', 'https://openrouter.ai/api/v1\u2060', 'https://openrouter.ai/api/v1 /',
    // product r24, seam r23: DEL and C1, and forms `new URL` reads with a backslash, no `//` or a dot segment.
    'https://openrouter.ai/api/v1\x7f', 'https://openrouter.ai/api/v1\x80', 'https://openrouter.ai/api/v1\x9f/',
    'https:openrouter.ai/api/v1\u00a0', 'https://openrouter.ai\\api\\v1\u00a0', 'https://openrouter.ai/api/v1\u00a0\\',
    'https://openrouter.ai/api/v1\u00a0/.', 'https://openrouter.ai/api/v1\u200e', 'https://openrouter.ai/api/v1\u00ad',
    'https://openrouter.ai/api/v1\u3164', 'https://openrouter.ai/api/v1\ufe0f', 'https://openrouter.ai/api/v1\u180b',
    'https://openrouter.ai/api/v1\u{e0100}', 'https://openrouter.ai/api/v1\u00a0\\']) {
    assert.throws(() => new fo.Client({ ceilingUsd: 1, ledger: new Ledger(), prices: {}, baseUrl }), (e) => e.kind === 'config', JSON.stringify(baseUrl));
  }
});

test('unencodable requests and answers over the cap', async () => {
  const seen = [];
  const { cl } = client({ steps: [] }, seen, new Ledger());
  await assert.rejects(cl.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 100, temperature: Number.NaN }),
    (e) => e.kind === 'config' && seen.length === 0);
  const ledger = new Ledger();
  const huge = new Uint8Array(8 * 1024 * 1024 + 1);
  const steps = [() => ({ status: 200, headers: {}, body: huge }),
    () => ({ status: 200, headers: {}, body: new TextEncoder().encode(JSON.stringify({ choices: [{ finish_reason: 'stop', message: { content: 'b' } }] })) })];
  const capped = new fo.Client({ ceilingUsd: 1, ledger, prices: CASES.prices, env: { OPENROUTER_API_KEY: KEY }, now: () => NOW,
    transport: async () => steps.shift()() });
  const got = await capped.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 100 });
  assert.deepEqual(got.attempts.map((a) => a.outcome), ['refused', 'answered']);
  assert.equal(ledger.rows[0].tokensMeasured, false);
  assert.equal(ledger.rows[0].costUsd, null);
});

test('an unmeasured attempt counts at its own worst case', async () => {
  const { cl } = client({ ceilingUsd: 0.0021, steps: [{ error: 'timeout' }] }, [], new Ledger(), { retries: 0 });
  await assert.rejects(cl.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 200 }));
  await assert.rejects(cl.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 10 }), (e) => e.kind === 'ceiling');
});

test('an answer without usage counts at its own worst case', async () => {
  const prices = { 'a/one': { prompt: 0.000001, completion: 0.001 }, 'b/two': { prompt: 0.000002, completion: 0.002 } };
  const ok = new TextEncoder().encode(JSON.stringify({ choices: [{ finish_reason: 'stop', message: { content: 'x' } }] }));
  const cl = new fo.Client({ ceilingUsd: 1, ledger: new Ledger(), prices, env: { OPENROUTER_API_KEY: KEY }, now: () => NOW,
    transport: async () => ({ status: 200, headers: {}, body: ok }) });
  await cl.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 900 });
  await assert.rejects(cl.chat(MESSAGES, { model: 'a/one', fallback: 'b/two', maxTokens: 200 }), (e) => e.kind === 'ceiling');
});
