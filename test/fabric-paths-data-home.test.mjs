// FAA-192 (16), the twin of test_fabric_paths_data_home.py: FABRIC_DATA_HOME holds a kit service's data folder on a
// durable volume; logs and cache stay; a relative value is refused; unset changes nothing.
import assert from 'node:assert/strict';
import path from 'node:path';
import test from 'node:test';
import { instanceDirs, serviceDirs } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-paths.mjs';
import { ServiceError } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-base.mjs';

const withEnv = (value, fn) => {
  const before = process.env.FABRIC_DATA_HOME;
  if (value === undefined) delete process.env.FABRIC_DATA_HOME; else process.env.FABRIC_DATA_HOME = value;
  try { return fn(); } finally { if (before === undefined) delete process.env.FABRIC_DATA_HOME; else process.env.FABRIC_DATA_HOME = before; }
};

test('unset changes nothing', () => withEnv(undefined, () => assert.equal(path.basename(serviceDirs('example-agent').data), 'example-agent')));

test('an absolute folder holds the data and each instance', () => {
  const volume = path.join(path.parse(process.cwd()).root, 'mnt', 'durable');
  withEnv(volume, () => {
    const dirs = serviceDirs('example-agent');
    assert.equal(dirs.data, path.join(volume, 'example-agent'));
    assert.notEqual(path.dirname(dirs.logs), volume);
    assert.equal(instanceDirs('example-agent', 'acme').data, path.join(volume, 'example-agent.acme'));
  });
});

test('a relative value is refused', () => withEnv('data', () => assert.throws(() => serviceDirs('example-agent'), ServiceError)));
