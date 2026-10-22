// Hostile inputs the two package twins must answer alike (FAA-78, findings 40 to 43): the cases in
// fixtures/kit-hostile-inputs-package.json, which test_kit_hostile_package.py runs through fabric_package.py. Also the
// folder walk's failure paths (finding 41) and a file swapped for a link (finding 42).
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-package.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const CASES = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/kit-hostile-inputs-package.json'), 'utf8'));
const V = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/package-vectors.json'), 'utf8')).vectors;

function tempDir(t, prefix = 'fabric-hostile-') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  const reopen = (folder) => { // a test may leave a folder unreadable; open every one again before removing them
    fs.chmodSync(folder, 0o700);
    for (const entry of fs.readdirSync(folder, { withFileTypes: true })) if (entry.isDirectory()) reopen(path.join(folder, entry.name));
  };
  t.after(() => {
    reopen(dir);
    fs.rmSync(dir, { recursive: true, force: true });
  });
  return dir;
}

function setPointer(doc, pointer, value) {
  const parts = pointer.split('/').slice(1).map((p) => p.replace(/~1/g, '/').replace(/~0/g, '~'));
  let target = doc;
  for (const part of parts.slice(0, -1)) target = target[part];
  Object.defineProperty(target, parts.at(-1), { value, enumerable: true, writable: true, configurable: true });
}

const refused = (pkg) => [...k.schemaProblems(pkg), ...k.pathProblems(pkg)];

function writeAgent(root) {
  for (const [p, text] of Object.entries(V.folder.files)) {
    fs.mkdirSync(path.dirname(path.join(root, p)), { recursive: true });
    fs.writeFileSync(path.join(root, p), text);
  }
  const { agentRef: _a, files: _f, digest: _d, signatures: _s, ...draft } = structuredClone(V.digest.package);
  return draft;
}

/** The bytes of fabric.package.json for a document case, built as the Python twin builds them. */
function documentBytes(draft, c) {
  const doc = structuredClone(draft);
  if (c.member) doc.service[c.member] = '@@RAW@@';
  if (c.nest) doc.x = '@@NEST@@';
  let text = JSON.stringify(doc, null, 2);
  for (const [key, value] of Object.entries(c.addTopLevel ?? {})) {
    text = `${text.slice(0, text.lastIndexOf('}')).trimEnd()},\n  ${JSON.stringify(key)}: ${JSON.stringify(value)}\n}`;
  }
  let bytes = Buffer.from(text, 'utf8');
  if (c.member) {
    const at = bytes.indexOf('@@RAW@@');
    bytes = Buffer.concat([bytes.subarray(0, at), Buffer.from(c.rawHex, 'hex'), bytes.subarray(at + 7)]);
  }
  if (c.nest) {
    const at = bytes.indexOf('"@@NEST@@"');
    bytes = Buffer.concat([bytes.subarray(0, at), Buffer.from('['.repeat(c.nest) + ']'.repeat(c.nest)), bytes.subarray(at + 10)]);
  }
  return bytes;
}

test('every path case: the kit refuses what the schema pattern misses after U+2028 and U+2029', () => {
  for (const c of CASES.paths) {
    assert.equal(k.pathProblem(c.path) !== null, c.refused, c.name);
    const pkg = structuredClone(V.digest.package);
    pkg.files[0].path = c.path;
    assert.equal(k.pathProblems(pkg).some((p) => p.instancePath === '/files/0/path'), c.refused, c.name);
    assert.equal(refused(pkg).length > 0, c.refused, c.name);
  }
});

test('the path rule reads every path the schema types as a path', () => {
  const pkg = structuredClone(V.digest.package);
  const bad = 'a /../x';
  pkg.provider = bad;
  pkg.evals.suite = bad;
  pkg.state[0].path = bad;
  pkg.dependencies[0].path = bad;
  assert.deepEqual(k.pathProblems(pkg).map((p) => p.instancePath).sort(), ['/dependencies/0/path', '/evals/suite', '/provider', '/state/0/path']);
});

test('every schema case', () => {
  for (const c of CASES.schema) {
    const pkg = structuredClone(V.digest.package);
    for (const [pointer, value] of Object.entries(c.set)) setPointer(pkg, pointer, value);
    assert.equal(refused(pkg).length > 0, c.refused, `${c.name}: ${JSON.stringify(refused(pkg))}`);
  }
});

test('every document case: pack answers a refusal, a problem or the same digest as the Python twin', (t) => {
  const dir = tempDir(t);
  for (const c of CASES.documents) {
    const root = path.join(dir, c.name);
    fs.mkdirSync(root);
    const draft = writeAgent(root);
    fs.writeFileSync(path.join(root, k.PACKAGE_FILE), documentBytes(draft, c));
    if (c.answer === 'error') {
      assert.throws(() => k.pack(root), k.PackageError, c.name);
      continue;
    }
    const answer = k.pack(root);
    if (c.answer === 'ok') {
      assert.equal(answer.ok, true, `${c.name}: ${JSON.stringify(answer.problems)}`);
      if (c.digest) assert.equal(answer.digest, c.digest, c.name);
    } else {
      assert.ok(answer.problems.some((p) => p.instancePath === c.instancePath), `${c.name}: ${JSON.stringify(answer.problems)}`);
    }
  }
});

test('the command line answers a refusal, not a stack trace', (t) => {
  const root = tempDir(t);
  const draft = writeAgent(root);
  fs.writeFileSync(path.join(root, k.PACKAGE_FILE), documentBytes(draft, { nest: 200000 }));
  const lines = [];
  assert.equal(k.main(['pack', root], (line) => lines.push(line)), 1);
  assert.deepEqual(JSON.parse(lines[0]), { ok: false, error: 'fabric.package.json nests deeper than 256 levels.' });
});

test('API callers get malformed, never a RangeError', () => {
  let deep = [];
  for (let i = 0; i < 100000; i += 1) deep = [deep];
  const pkg = { ...structuredClone(V.digest.package), x: deep };
  assert.deepEqual(k.verifyPackage(pkg, {}), { ok: false, problem: 'malformed' });
  assert.ok(k.packageFindings(pkg).some((f) => f.instancePath === '/digest'));
});

test('compose turns a digest it cannot compute into a PackageError', () => {
  let deep = [];
  for (let i = 0; i < 100000; i += 1) deep = [deep];
  assert.throws(() => k.compose({ ...structuredClone(V.digest.package), x: deep }, new Map([['a', Buffer.from('a')]])), k.PackageError);
});

test('every key file case', (t) => {
  const dir = tempDir(t, 'fabric-hostile-key-');
  const key = V.keys.publisher;
  for (const c of CASES.keyFiles) {
    const file = path.join(dir, `${c.name}.jwk`);
    fs.writeFileSync(file, c.prefix + JSON.stringify({ ...key.jwk, d: Buffer.from(key.seed, 'hex').toString('base64url') }), { mode: 0o600 });
    if (c.ok) {
      const got = k.readSigningKey(file);
      assert.deepEqual([got.seed.toString('hex'), got.kid], [key.seed, key.jwk.kid], c.name);
    } else {
      assert.throws(() => k.readSigningKey(file), k.PackageError, c.name);
    }
  }
});

test('a trust file that is not UTF-8 is refused, not read leniently', (t) => {
  const root = tempDir(t);
  writeAgent(root);
  const trust = path.join(root, '..', `${path.basename(root)}-trust.json`);
  fs.writeFileSync(trust, Buffer.concat([Buffer.from('{"publisher": ["'), Buffer.from('ff', 'hex'), Buffer.from('"]}')]));
  t.after(() => fs.rmSync(trust, { force: true }));
  const lines = [];
  assert.equal(k.main(['verify', root, '--trust', trust], (line) => lines.push(line)), 1);
  assert.match(JSON.parse(lines[0]).error, /is not JSON/);
});

const posixUser = process.platform !== 'win32' && process.getuid?.() !== 0;

test('an unreadable folder is refused by name, not a crash', { skip: !posixUser }, (t) => {
  const root = tempDir(t);
  writeAgent(root);
  const hidden = path.join(root, 'hidden');
  fs.mkdirSync(hidden);
  fs.writeFileSync(path.join(hidden, 'unsigned.js'), 'payload');
  fs.chmodSync(hidden, 0);
  assert.throws(() => k.readFolder(root), (error) => error instanceof k.PackageError && /hidden/.test(error.message) && /EACCES/.test(error.message));
});

test('an unreadable file is refused by name, not a crash', { skip: !posixUser }, (t) => {
  const root = tempDir(t);
  writeAgent(root);
  fs.chmodSync(path.join(root, 'bin/serve.mjs'), 0);
  assert.throws(() => k.readFolder(root), (error) => error instanceof k.PackageError && error.message.includes('bin/serve.mjs'));
});

test('a file swapped for a link after the listing is never read through', { skip: !posixUser }, (t) => {
  const root = tempDir(t);
  writeAgent(root);
  const outside = path.join(root, '..', `${path.basename(root)}-outside.txt`);
  fs.writeFileSync(outside, 'outside bytes');
  t.after(() => fs.rmSync(outside, { force: true }));
  const target = path.join(root, 'bin/serve.mjs');
  const realOpen = fs.openSync;
  let swapped = false;
  fs.openSync = (file, ...rest) => {
    if (!swapped && String(file).endsWith('serve.mjs')) {
      fs.unlinkSync(target);
      fs.symlinkSync(outside, target);
      swapped = true;
    }
    return realOpen(file, ...rest);
  };
  try {
    assert.throws(() => k.readFolder(root), (error) => error instanceof k.PackageError && error.message.includes('bin/serve.mjs (a symlink)'));
  } finally {
    fs.openSync = realOpen;
  }
  assert.equal(swapped, true);
});

test('a pipe is refused without blocking', { skip: !posixUser }, (t) => {
  const root = tempDir(t);
  writeAgent(root);
  assert.equal(spawnSync('mkfifo', [path.join(root, 'pipe')]).status, 0);
  assert.throws(() => k.readFolder(root), (error) => error instanceof k.PackageError && error.message.includes('pipe (not a regular file)'));
});
