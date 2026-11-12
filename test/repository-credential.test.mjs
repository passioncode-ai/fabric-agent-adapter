// 0.62.0 readings 7 and 8: the Node twin of test_repository_credential.py, on the same vectors.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { repositoryCredential, repositoryPassword } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-secrets.mjs';

const vectors = JSON.parse(fs.readFileSync(new URL('./repository_vectors.json', import.meta.url), 'utf8'));
const KEY = `ghp_${'Fx9k'.repeat(9)}`; // made up at run time: shaped like a key, never one
const LETTERS = { // made up, no digit
  SKSTRONG: `sk-${'Ab1d'.repeat(10)}`, SKLETTERS: `sk-${'AbCd'.repeat(10)}`, GHLETTERS: `ghp_${'AbCd'.repeat(9)}`, AKLETTERS: `AKIA${'ABCD'.repeat(4)}`,
  SKUPPER: `SK-${'AbCd'.repeat(10)}`, JWTLETTERS: ['eyJabcd', 'eyJefgh', 'ijkl'].join('.'), RUN40: 'AbCd'.repeat(10),
  SKNAME: `sk-${'learn-tutorial-notebooks'}`, SKWORD: `sk-${'dictionary-extension'}`,
  GHREST: `hp_${'AbCd'.repeat(6)}`, SKREST: `k-${'Ab1d'.repeat(4)}`, GLREST: `lpat-${'AbCd'.repeat(6)}`, // a real-looking name a key's shape starts (FAA-200 (24))
};
const made = (value) => Object.entries(LETTERS).reduce((text, [mark, key]) => text.replaceAll(mark, key), value).replaceAll('KEY', KEY);

test('repositoryCredential reads the shared vectors as Python does', () => {
  for (const value of vectors.credential) assert.equal(repositoryCredential(made(value)), true, value);
  for (const value of vectors.name) assert.equal(repositoryCredential(made(value)), false, value);
  for (const value of vectors.password) assert.equal(repositoryPassword(value), true, value); // read alone (readings 12)
  for (const value of vectors.no_password) assert.equal(repositoryPassword(value), false, value);
});
