// FAA-65: every name a kit module exported at v0.39.1 is still exported by that module (the twin of test_kit_api.py).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const snapshot = JSON.parse(fs.readFileSync(new URL('./fixtures/kit-api/kit-api-0.39.1.json', import.meta.url), 'utf8'));
const where = (name) => new URL(`../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/${name}.mjs`, import.meta.url);

test('every 0.39.1 export is still exported', async () => {
  assert.ok(Object.values(snapshot.node).flat().length > 300);
  for (const [module, names] of Object.entries(snapshot.node)) {
    const mod = await import(where(module));
    assert.deepEqual(names.filter((n) => !(n in mod)), [], `${module} lost exports it had at v0.39.1`);
  }
});
