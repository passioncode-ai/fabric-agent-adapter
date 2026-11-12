// The support-agent recipe's Node checks (FAA-264 item 10): checkReply answers the shared cases exactly as the Python
// recipe's check_reply (test/fixtures/support-check-reply-cases.json, asserted on that side by
// test_support_agent_recipe.py).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import { checkReply, scriptOf } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/recipes/support-agent/support-agent.mjs';

const CASES = JSON.parse(fs.readFileSync(new URL('./fixtures/support-check-reply-cases.json', import.meta.url), 'utf8')).cases;

test('checkReply answers every shared case as check_reply does', () => {
  assert.ok(CASES.length >= 30);
  for (const c of CASES) {
    assert.deepEqual(checkReply(c.draft, c.question, c.given, { maxChars: c.maxChars, sources: c.sources }), c.expected, c.name);
  }
});

test('scriptOf leaves citations and links out and breaks a tie by name', () => {
  assert.equal(scriptOf('[KB:abc] https://example.com'), null);
  assert.equal(scriptOf('ab аб'), 'latin');
});
