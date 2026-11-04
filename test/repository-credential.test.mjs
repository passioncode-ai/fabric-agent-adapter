// 0.62.0 readings 7 and 8: the Node twin of test_repository_credential.py, on the same vectors.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { repositoryCredential } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-secrets.mjs';

const vectors = JSON.parse(fs.readFileSync(new URL('./repository_vectors.json', import.meta.url), 'utf8'));
const KEY = `ghp_${'Fx9k'.repeat(9)}`; // made up at run time: shaped like a key, never one

test('repositoryCredential reads the shared vectors as Python does', () => {
  for (const value of vectors.credential) assert.equal(repositoryCredential(value.replace('KEY', KEY)), true, value);
  for (const value of vectors.name) assert.equal(repositoryCredential(value), false, value);
});
