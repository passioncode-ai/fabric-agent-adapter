// The Node twin of the credential detector (DEC-0044): rawValues reads a query in linear time, as the Python twin
// (fabric_secrets.raw_values) and the contract's src/secret-shape.ts do since fcdb7ccb (FAA-245).
import assert from 'node:assert/strict';
import test from 'node:test';
import { JWT_SHAPE, hasJwt, jwtSpans, rawValues, secretArgument, secretUrl, secretValue } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-secrets.mjs';

// How much longer work(large) takes than work(small): each size's fastest of three runs, measured in turn, so a
// loaded machine slows both (FAA-209's rule: a ratio of two sizes, never a wall-clock bound).
function growth(work, small, large, runs = 3) {
  const best = { [small]: Infinity, [large]: Infinity };
  for (let r = 0; r < runs; r += 1) {
    for (const size of [small, large]) {
      const started = performance.now();
      work(size);
      best[size] = Math.min(best[size], performance.now() - started);
    }
  }
  return best[large] / Math.max(best[small], 1e-6);
}

test('rawValues keeps every value of a name, in order, with + kept', () => {
  assert.deepEqual([...rawValues('a=1&b=x+y&a=2&a&=v&a=%zz')], [['a', ['1', '2', '', '%zz']], ['b', ['x+y']], ['', ['v']]]);
  assert.equal(secretUrl('https://h.example/?a=b&token=' + 'Zq7Wm4'.repeat(6)), true);
});

test('rawValues reads many pieces of one name in linear time (FAA-245)', () => {
  const queries = { 10000: 'a=b&'.repeat(10000), 40000: 'a=b&'.repeat(40000) };
  assert.equal(rawValues(queries[40000]).get('a').length, 40000);
  // four times the pieces cost about four times as much; copying the list for each piece cost sixteen
  assert.ok(growth((n) => rawValues(queries[n]), 10000, 40000) < 9);
});

// FAA-313: hasJwt and jwtSpans, the contract's one-pass JWT read (src/secret-shape.ts): JWT_SHAPE's answers, in linear
// time (the Python twins: test/test_repository_credential.py OnePassJwt).
// '@' stands for a JWT's start, put in at run time so no line of this file is shaped like a token.
const JWT_CASES = ['', '@', '@ab.cd.', '@ab.cd.ef', 'x @ab.c.d', '@a.bc.d', '@@ab.cd.e', '@ab.c.@cd.ef.g', '@ab..cd', '@ab.cd',
  'a.@ab.cd.ef.@gh.ij.kl', '@ab.cd.ef.gh', '@_-.-_.', '@ab.cd.e\\nf', '@\\u00e9b.cd.ef', '--@ab.cd.ef--'].map((c) => c.replaceAll('@', 'ey' + 'J'));

test('hasJwt and jwtSpans answer as JWT_SHAPE does (FAA-313)', () => {
  const parts = ['eyJ', 'e', 'y', 'J', 'a', '_', '-', '.', ' ', 'b'];
  let seed = 313;
  const next = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed; };
  const texts = [...JWT_CASES];
  for (let i = 0; i < 3000; i += 1) {
    let text = '';
    for (let n = next() % 15; n > 0; n -= 1) text += parts[next() % parts.length];
    texts.push(text);
  }
  for (const text of texts) {
    const want = [...text.matchAll(new RegExp(JWT_SHAPE.source, 'g'))].map((m) => [m.index, m.index + m[0].length]);
    assert.equal(hasJwt(text), JWT_SHAPE.test(text), text);
    assert.deepEqual(jwtSpans(text), want, text);
    assert.deepEqual(jwtSpans(text, true), want.slice(0, 1), text);
  }
});

test('a long run of JWT starts is read in linear time (FAA-313)', () => {
  const texts = { 4000: 'eyJ'.repeat(4000), 16000: 'eyJ'.repeat(16000) };
  for (const read of [hasJwt, secretValue, secretArgument]) {
    assert.equal(read(texts[16000]), false);
    // four times the text costs about four times as much; the regular expression cost sixteen
    assert.ok(growth((n) => read(texts[n]), 4000, 16000) < 9, read.name);
  }
});
