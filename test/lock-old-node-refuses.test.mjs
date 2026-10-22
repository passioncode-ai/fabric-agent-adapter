// FAA-72: Node 18 and 20 cannot bind an abstract unix socket name exactly on Linux (18 and early 20 make every name 108
// NUL bytes, so every service would share one lock; later 20 pads it, so no Python copy or probe sees it). The Node
// kit's lock refuses there with a sentence instead of holding a wrong name. Runs on such a Node (the floors job).
import assert from 'node:assert/strict';
import test from 'node:test';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';
import { abstractNames } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-lock.mjs';
import { tempDir } from './temp-dir.mjs';

const names = process.platform === 'linux' ? await abstractNames() : 'not-linux';

test('a Node that cannot bind the exact name refuses the lock with a sentence', { skip: !['none', 'padded'].includes(names) && `this Node binds names: ${names}` }, async () => {
  await assert.rejects(new k.InstanceLock(tempDir('fabric-old-node-')).acquire(),
    (e) => e instanceof k.ServiceError && !(e instanceof k.AlreadyRunning) && /Node 22 or later/.test(e.message));
});

test('a Node that binds the exact name holds the lock', { skip: names !== 'exact' && `this Node binds names: ${names}` }, async () => {
  const lock = await new k.InstanceLock(tempDir('fabric-new-node-')).acquire();
  lock.release();
});
