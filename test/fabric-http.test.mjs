// FAA-65 REQ-06: fabric-http.mjs, on the cases fabric_http.py reads too, plus the default transport against a server on
// loopback (no test leaves this machine).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import test from 'node:test';
import * as fh from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-http.mjs';

const CASES = JSON.parse(fs.readFileSync(new URL('./fixtures/kit-http-cases.json', import.meta.url), 'utf8'));

function scripted(steps, seen) {
  const left = [...steps];
  return async ({ method, url, headers, body, timeoutS }) => {
    seen.push({ method, url, headers, body, timeoutS });
    const step = left.shift();
    if (step.error === 'connection') throw Object.assign(new Error('reset'), { name: 'TypeError' });
    if (step.error === 'timeout') throw Object.assign(new Error('slow'), { name: 'TimeoutError' });
    return { status: step.status, headers: step.headers ?? {}, body: new TextEncoder().encode(step.body ?? '') };
  };
}

async function run(c, seen = [], extra = {}) {
  const sleeps = [];
  let now = 0;
  try {
    const answer = await fh.request(c.method, c.url ?? 'https://api.example/v1/items', {
      headers: c.headers ?? {}, body: c.body ?? null, retries: c.retries ?? 2, deadlineS: c.deadlineS ?? 30,
      maxBytes: c.maxBytes ?? fh.DEFAULT_MAX_BYTES, maxRetryAfterS: c.maxRetryAfterS ?? 30,
      transport: scripted(c.steps, seen), sleep: async (s) => { sleeps.push(s); now += s; }, clock: () => now,
      rand: () => 0.5, ...extra,
    });
    return { status: answer.status, attempts: answer.attempts, sleeps };
  } catch (err) {
    if (!(err instanceof fh.HttpError)) throw err;
    return { error: err.kind, attempts: err.attempts, sleeps, message: err.message };
  }
}

test('the shared cases', async () => {
  for (const [url, expected] of CASES.redact) assert.equal(fh.redactUrl(url), expected, url);
  for (const [url, insecure, refused] of CASES.checkUrl) {
    if (refused) {
      assert.throws(() => fh.checkUrl(url, { insecure }), (e) => e.kind === 'refused' && !`${e.message}${e.url}`.includes('pass@'), url);
    } else {
      fh.checkUrl(url, { insecure });
    }
  }
  for (const [value, now, expected] of CASES.retryAfter) assert.equal(fh.retryAfterS(value, { now }), expected, String(value));
  for (const [method, headers, status, expected] of CASES.mayRetry) assert.equal(fh.mayRetry(method, headers, status), expected);
  for (const [attempt, baseS, maxS, rand, expected] of CASES.backoff) assert.equal(fh.backoffS(attempt, { baseS, maxS, rand }), expected);
  for (const c of CASES.scenarios) {
    const got = await run(c);
    delete got.message;
    assert.deepEqual(got, c.expect, c.name);
  }
});

test('no secret in an error', async () => {
  const got = await run({ method: 'GET', url: 'https://api.example/v1?api_key=sk-or-v1-SECRET',
    headers: { Authorization: 'Bearer sk-or-v1-SECRET' }, retries: 0, steps: [{ error: 'connection' }] });
  assert.equal(got.error, 'connection');
  assert.ok(!got.message.includes('SECRET'));
  assert.ok(got.message.includes('https://api.example/v1'));
});

test('one deadline across attempts, JSON bodies, refusals', async () => {
  const seen = [];
  await run({ method: 'GET', deadlineS: 10, retries: 3, steps: [{ status: 503 }, { status: 503 }, { status: 200 }] }, seen);
  assert.deepEqual(seen.map((s) => s.timeoutS), [10, 9.5, 8.5]);
  const posted = [];
  await run({ method: 'POST', body: { q: 'é' }, steps: [{ status: 200 }] }, posted);
  assert.equal(new TextDecoder().decode(posted[0].body), '{"q":"é"}');
  assert.equal(posted[0].headers['Content-Type'], 'application/json');
  for (const headers of [{ 'X-A': '1\r\nX-B: 2' }, { 'Bad Name': '1' }, { 'X-A': 'a\0' }]) {
    await assert.rejects(fh.request('GET', 'https://api.example/', { headers, transport: scripted([], []) }), fh.HttpError);
  }
  for (const opts of [{ retries: -1 }, { retries: 11 }, { retries: true }, { deadlineS: 0 }, { maxBytes: 0 }]) {
    await assert.rejects(fh.request('GET', 'https://api.example/', { transport: scripted([], []), ...opts }), fh.HttpError);
  }
  const answer = new fh.Response(200, { 'Content-Type': 'application/json' }, new TextEncoder().encode('{"a":[1]}'));
  assert.ok(answer.ok);
  assert.deepEqual(answer.json(), { a: [1] });
});

test('the default transport: answers, redirects and the cap', async () => {
  const server = http.createServer((req, res) => {
    if (req.url === '/big') { res.writeHead(200, { 'Content-Length': '100' }); res.end('x'.repeat(100)); return; }
    if (req.url === '/redirect') { res.writeHead(302, { Location: 'http://127.0.0.1:1/elsewhere' }); res.end(); return; }
    if (req.url === '/missing') { res.writeHead(404); res.end('no'); return; }
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ auth: req.headers.authorization }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const ok = await fh.request('GET', `${base}/ok`, { headers: { Authorization: 'Bearer t' }, deadlineS: 10 });
    assert.deepEqual(ok.json(), { auth: 'Bearer t' });
    assert.equal((await fh.request('GET', `${base}/missing`, { deadlineS: 10 })).status, 404);
    assert.equal((await fh.request('GET', `${base}/redirect`, { deadlineS: 10, retries: 0 })).status, 302);
    await assert.rejects(fh.request('GET', `${base}/big`, { deadlineS: 10, maxBytes: 10 }), (e) => e.kind === 'too-large');
    await assert.rejects(fh.request('GET', 'http://127.0.0.1:1/', { deadlineS: 5, retries: 0 }), (e) => e.kind === 'connection');
  } finally {
    server.close();
  }
});

test('bodies and transport bugs, as the Python twin', async () => {
  for (const [value, text] of CASES.jsonBody) assert.equal(new TextDecoder().decode(fh.jsonBytes(value)), text);
  for (const [value, text] of CASES.textBody) assert.equal(new TextDecoder().decode(new TextEncoder().encode(value)), text);
  for (const bad of [Number.NaN, Infinity]) {
    await assert.rejects(fh.request('POST', 'https://api.example/', { body: { n: bad }, transport: scripted([], []) }), (e) => e.kind === 'refused');
  }
  await assert.rejects(fh.request('GET', 'https://api.example/', { transport: async () => { throw new RangeError('bug'); }, retries: 0 }),
    (e) => e.kind === 'connection');
  const seen = [];
  await run({ method: 'POST', body: new TextEncoder().encode('ab').buffer, steps: [{ status: 200 }] }, seen);
  assert.equal(new TextDecoder().decode(seen[0].body), 'ab');
  await run({ method: 'GET', headers: null, steps: [{ status: 200 }] });
});
