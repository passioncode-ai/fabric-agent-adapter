// fabric-package/1 in the Node kit (contract DEC-0050, DEC-0051, DEC-0071, DEC-0074; FAA-27a), the twin of
// test_fabric_package.py: the contract's vectors as package-vectors.json vendors them, pack / sign / verify on real
// folders, and both kits writing the same bytes. The keys are the contract's published test keys.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-package.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const scripts = path.join(here, '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts');
const VECTORS = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/package-vectors.json'), 'utf8'));
const V = VECTORS.vectors;
const PEM_LABEL = `PRIVATE ${'KEY'}`; // split, so no scanner mistakes this test for a key
const hasPython = spawnSync('python3', ['--version']).status === 0;

function tempDir(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-package-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

/** The vector agent's folder, with its author's draft: what pack fills in (agentRef, files, digest) left out. */
function writeAgent(root, extra = {}) {
  for (const [p, text] of Object.entries(V.folder.files)) {
    fs.mkdirSync(path.dirname(path.join(root, p)), { recursive: true });
    fs.writeFileSync(path.join(root, p), text);
  }
  const { agentRef: _a, files: _f, digest: _d, signatures: _s, ...draft } = structuredClone(V.digest.package);
  Object.assign(draft, extra);
  fs.writeFileSync(path.join(root, k.PACKAGE_FILE), `${JSON.stringify(draft, null, 2)}\n`);
  return draft;
}

function keyFile(dir, name = 'publisher', { mode = 0o600, ...extra } = {}) {
  const key = V.keys[name];
  const file = path.join(dir, `${name}.jwk`);
  fs.writeFileSync(file, JSON.stringify({ ...key.jwk, d: Buffer.from(key.seed, 'hex').toString('base64url'), ...extra }));
  fs.chmodSync(file, mode);
  return file;
}

const readPkg = (root) => JSON.parse(fs.readFileSync(path.join(root, k.PACKAGE_FILE), 'utf8'));

test('the digest, the signing input and agentRef are the vectors\'', () => {
  assert.equal(k.packageDigest(V.digest.package), V.digest.expected);
  assert.equal(k.packageSigningInput(V.signingInput.digest, V.signingInput.role).toString('utf8'), V.signingInput.utf8);
  assert.equal(k.agentRefOf('example', 'inbox-digest'), V.digest.package.agentRef);
});

test('the folder check answers the vector folder', () => {
  const files = new Map(Object.entries(V.folder.files).map(([p, text]) => [p, Buffer.from(text, 'utf8')]));
  assert.deepEqual(k.checkPackageFolder(V.digest.package, files), V.folder.expected);
});

test('every verifier case answers as the contract does', () => {
  for (const c of V.cases) assert.deepEqual(k.verifyPackage(c.package, c.trust, c.options ?? {}), c.expected, c.name);
});

test('the signer reproduces every vector signature from its seed', () => {
  const seeds = new Map(Object.values(V.keys).filter((key) => key.seed).map((key) => [key.jwk.kid, Buffer.from(key.seed, 'hex')]));
  for (const key of Object.values(V.keys).filter((x) => x.seed)) assert.equal(k.ed25519PublicKey(Buffer.from(key.seed, 'hex')).toString('base64url'), key.jwk.x);
  let checked = 0;
  for (const c of V.cases.filter((x) => x.expected.ok === true)) {
    for (const entry of c.package.signatures ?? []) {
      if (!seeds.has(entry.kid)) continue;
      assert.equal(k.ed25519Sign(seeds.get(entry.kid), k.packageSigningInput(c.package.digest, entry.role)).toString('base64url'), entry.sig, c.name);
      checked += 1;
    }
  }
  assert.ok(checked >= 3);
});

test('the schema answers every fixture as the catalogue lists it', () => {
  for (const f of VECTORS.fixtures) assert.equal(k.schemaProblems(f.document).length === 0, f.valid, `${f.name}: ${JSON.stringify(k.schemaProblems(f.document))}`);
});

test('the rules answer every semantic fixture, and no positive one', () => {
  for (const f of VECTORS.semantic) assert.deepEqual(k.packageFindings(f.document).map(({ code, instancePath }) => ({ code, instancePath })), f.findings, f.name);
  for (const f of VECTORS.fixtures.filter((x) => x.valid)) assert.deepEqual(k.packageFindings(f.document), [], f.name);
});

test('consumer placement names each missing role and tool', () => {
  const consumer = VECTORS.fixtures.find((f) => f.name === 'fabric-package-consumer-agent').document;
  const roles = consumer.requires.mcp.map((r) => r.role);
  assert.deepEqual(k.consumerPlacement(consumer, undefined), roles.map((role) => ({ problem: 'missing-role', role })));
  const full = new Map(consumer.requires.mcp.map((r) => [r.role, [...r.tools]]));
  assert.deepEqual(k.consumerPlacement(consumer, full), []);
  const first = consumer.requires.mcp[0];
  assert.deepEqual(k.consumerPlacement(consumer, new Map([...full, [first.role, first.tools.slice(1)]])), [{ problem: 'missing-tool', role: first.role, tool: first.tools[0] }]);
});

test('pack rebuilds the vector package byte for byte, and a dry run writes nothing', (t) => {
  const root = path.join(tempDir(t), 'inbox-digest');
  fs.mkdirSync(root);
  writeAgent(root);
  const before = fs.readFileSync(path.join(root, k.PACKAGE_FILE));
  const answer = k.pack(root);
  assert.ok(answer.ok, JSON.stringify(answer.problems));
  assert.equal(answer.applied, false);
  assert.deepEqual(fs.readFileSync(path.join(root, k.PACKAGE_FILE)), before);
  const { signatures: _s, ...expected } = V.digest.package;
  assert.deepEqual(answer.package, expected);
  assert.deepEqual(Object.keys(answer.package), Object.keys(expected), "the author's order, agentRef after publisher, files and digest last");
  assert.equal(answer.agentRef, 'urn:fabric:agent:example:inbox-digest');
  assert.ok(k.pack(root, { apply: true }).applied);
  assert.equal(fs.readFileSync(path.join(root, k.PACKAGE_FILE), 'utf8'), `${JSON.stringify(expected, null, 2)}\n`);
  assert.equal(k.pack(root).digest, V.digest.expected, 'packing a packed folder again is stable');
});

test('pack refuses what must not ship', (t) => {
  const root = tempDir(t);
  writeAgent(root);
  for (const name of ['.env', '.env.local', 'deploy.pem', 'signing.key', 'id_ed25519', '.npmrc', '.DS_Store', 'x.pyc']) {
    fs.writeFileSync(path.join(root, name), 'x');
    assert.throws(() => k.pack(root), (e) => e instanceof k.PackageError && e.message.includes(name), name);
    fs.rmSync(path.join(root, name));
  }
  fs.writeFileSync(path.join(root, '.env.example'), 'EXAMPLE_TOKEN_FILE=\n');
  assert.ok(k.pack(root).package.files.some((f) => f.path === '.env.example'));
  fs.rmSync(path.join(root, '.env.example'));
  for (const junk of ['.git', '__pycache__']) {
    fs.mkdirSync(path.join(root, 'bin', junk));
    assert.throws(() => k.pack(root), new RegExp(`bin/${junk.replace('.', '\\.')}`));
    fs.rmdirSync(path.join(root, 'bin', junk));
  }
  fs.symlinkSync('/etc/hosts', path.join(root, 'hosts'));
  assert.throws(() => k.pack(root), /symlink/);
  fs.rmSync(path.join(root, 'hosts'));
  assert.ok(k.pack(root).ok);
  assert.throws(() => k.pack(path.join(root, 'nowhere')), /not a folder/);
  fs.writeFileSync(path.join(root, k.PACKAGE_FILE), '{"schema": "fabric-package/1", "schema": "x"}');
  assert.throws(() => k.pack(root), /twice/);
  fs.rmSync(path.join(root, k.PACKAGE_FILE));
  assert.throws(() => k.pack(root), /first/);
});

test('pack names every problem and writes nothing', (t) => {
  const root = tempDir(t);
  writeAgent(root);
  fs.writeFileSync(path.join(root, k.PLUGIN_MANIFEST), JSON.stringify({ name: 'inbox-digest', version: '9.9.9' }));
  const answer = k.pack(root, { apply: true });
  assert.equal(answer.ok, false);
  assert.equal(answer.applied, false);
  assert.deepEqual(answer.problems.find((p) => p.rule === 'folder'), { rule: 'folder', problem: 'plugin-manifest', instancePath: k.PLUGIN_MANIFEST, message: 'plugin-manifest' });
  assert.ok(!fs.readFileSync(path.join(root, k.PACKAGE_FILE), 'utf8').includes('"digest": "sha256:'));
  writeAgent(root, { version: '1.2' });
  assert.ok(k.pack(root).problems.some((p) => p.rule === 'schema' && p.instancePath === '/version'));
  writeAgent(root, { secrets: [{ name: 'INBOX_TOKEN', purpose: 'reads the mailbox' }, { name: 'INBOX_TOKEN', purpose: 'again' }] });
  assert.ok(k.pack(root).problems.some((p) => p.rule === 'FAC-SEM-065'));
});

test('pack refuses a chosen agentRef and a stale receipt, and drops old signatures', (t) => {
  const root = tempDir(t);
  writeAgent(root, { agentRef: 'urn:fabric:agent:example:other' });
  assert.throws(() => k.pack(root), /urn:fabric:agent:example:inbox-digest/);
  writeAgent(root, { agentRef: 'urn:fabric:agent:example:inbox-digest' });
  assert.ok(k.pack(root).ok, 'the derived value written by hand is accepted');
  writeAgent(root);
  fs.writeFileSync(path.join(root, 'evals/suite.json'), '{"cases": []}\n');
  const stale = k.pack(root);
  assert.equal(stale.ok, false);
  assert.ok(stale.problems.some((p) => p.instancePath === '/evals/receipt/suite'));
  assert.ok(stale.notes.some((n) => n.includes('run it again')));
  writeAgent(root, { signatures: [{ role: 'publisher', alg: 'EdDSA', kid: 'x', sig: 'AA' }] });
  fs.writeFileSync(path.join(root, 'evals/suite.json'), V.folder.files['evals/suite.json']);
  const dropped = k.pack(root);
  assert.ok(!('signatures' in dropped.package));
  assert.ok(dropped.notes.some((n) => n.includes('dropped 1 signature')));
});

test('files are listed in UTF-16 order, and a file added after packing is caught', (t) => {
  const root = tempDir(t);
  writeAgent(root);
  const names = ['a.md', 'a/x.md', '\u{1F600}.md', '\uFF5E.md'];
  for (const name of names) {
    fs.mkdirSync(path.dirname(path.join(root, name)), { recursive: true });
    fs.writeFileSync(path.join(root, name), 'x\n');
  }
  const paths = k.pack(root).package.files.map((f) => f.path);
  assert.deepEqual(paths.filter((p) => names.includes(p)), names, 'RFC 8785 order: UTF-16 code units');
  assert.deepEqual(paths, [...paths].sort());
  assert.ok(k.pack(root, { apply: true }).applied);
  fs.writeFileSync(path.join(root, 'added.md'), 'added after packing\n');
  assert.ok(k.verify(root, { publisher: [] }).problems.some((p) => p.problem === 'file-unlisted' && p.instancePath === 'added.md'));
});

test('the schema counts code points', () => {
  const pkg = structuredClone(VECTORS.fixtures.find((f) => f.name === 'fabric-package-agent').document);
  pkg.resultSignal.says = '\u{1F600}'.repeat(120);
  assert.deepEqual(k.schemaProblems(pkg), [], '120 astral characters are 120, not 240');
  pkg.resultSignal.says += 'x';
  assert.deepEqual(k.schemaProblems(pkg).map((p) => p.instancePath), ['/resultSignal/says']);
});

test('sign then verify, a countersignature, re-signing, and a folder changed after signing', (t) => {
  const dir = tempDir(t);
  const root = path.join(dir, 'pkg');
  fs.mkdirSync(root);
  writeAgent(root);
  k.pack(root, { apply: true });
  assert.ok(k.sign(root, keyFile(dir)).ok);
  assert.ok(!('signatures' in readPkg(root)), 'a dry run writes nothing');
  const signed = k.sign(root, keyFile(dir), { apply: true });
  const pub = V.keys.publisher.jwk;
  assert.deepEqual(signed.publicKey, { ...pub, use: 'sig' });
  const alone = V.cases.find((c) => c.name.startsWith('a publisher signature alone'));
  assert.deepEqual(signed.signature, alone.package.signatures[0], "the signature is the vector's own");
  assert.ok(k.verify(root, { publisher: [pub] }).ok);
  assert.ok(k.sign(root, keyFile(dir, 'organization'), { role: 'organization', apply: true }).ok);
  const full = { publisher: [pub], organization: [V.keys.organization.jwk] };
  const verdict = k.verify(root, full, { countersigned: true });
  assert.ok(verdict.ok, JSON.stringify(verdict));
  assert.deepEqual(verdict.verdict.signers.map((s) => s.role), ['publisher', 'organization']);
  k.sign(root, keyFile(dir), { apply: true });
  k.sign(root, keyFile(dir, 'organization'), { role: 'organization', apply: true });
  assert.deepEqual(readPkg(root).signatures.map((s) => s.role), ['publisher', 'organization'], 'one publisher signature, the same organization key replaced');
  fs.writeFileSync(path.join(root, 'bin/serve.mjs'), '// changed after signing\n');
  const changed = k.verify(root, full);
  assert.equal(changed.ok, false);
  assert.ok(changed.problems.some((p) => p.problem === 'file-digest'));
  const refused = k.sign(root, keyFile(dir));
  assert.equal(refused.ok, false, 'a folder that no longer matches its package is not signed');
});

test("a partner's setup is an org skill set that requires its agents, signed by the partner's key (FAA-55)", (t) => {
  const dir = tempDir(t);
  const root = path.join(dir, 'acme-setup');
  const files = {
    '.claude-plugin/plugin.json': `${JSON.stringify({ name: 'acme-setup', version: '1.0.0' })}\n`,
    'skills/house-style/SKILL.md': '---\nname: house-style\ndescription: How this company writes.\n---\n',
  };
  for (const [p, text] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(root, p)), { recursive: true });
    fs.writeFileSync(path.join(root, p), text);
  }
  const agents = [{ publisher: 'example', id: 'inbox-digest', range: '^1.0.0' }, { publisher: 'example', id: 'invoice-reader', range: '^2.1.0' }];
  const draft = { schema: 'fabric-package/1', kind: 'skill-set', id: 'acme-setup', version: '1.0.0', publisher: 'example', licence: 'LicenseRef-Partner', layer: 'org', runners: ['claude-code'], skills: ['house-style'], requires: { packages: agents } };
  fs.writeFileSync(path.join(root, k.PACKAGE_FILE), `${JSON.stringify(draft, null, 2)}\n`);
  const packed = k.pack(root, { apply: true });
  assert.ok(packed.ok, JSON.stringify(packed.problems));
  assert.ok(!('agentRef' in packed.package), 'a skill set names no agent of its own');
  assert.deepEqual(packed.package.requires.packages, agents, 'the agents it sets up, by publisher, id and range');
  assert.ok(k.sign(root, keyFile(dir), { apply: true }).ok);
  const partner = V.keys.publisher.jwk;
  assert.ok(k.verify(root, { publisher: [partner] }).ok);
  assert.equal(k.verify(root, { publisher: [V.keys.organization.jwk] }).ok, false, 'a machine that pins another publisher key refuses the setup');
  fs.writeFileSync(path.join(root, 'skills/house-style/SKILL.md'), 'changed after signing\n');
  assert.equal(k.verify(root, { publisher: [partner] }).ok, false, "a changed skill breaks the setup's signature");
});

test('the key file: mode, kid, x, alg, PEM, and a key openssl makes', (t) => {
  const dir = tempDir(t);
  const root = path.join(dir, 'pkg');
  fs.mkdirSync(root);
  writeAgent(root);
  k.pack(root, { apply: true });
  if (process.platform !== 'win32') assert.throws(() => k.sign(root, keyFile(dir, 'publisher', { mode: 0o644 })), /chmod 600/);
  assert.throws(() => k.sign(root, keyFile(dir), { kid: 'another' }), /disagrees/);
  assert.throws(() => k.sign(root, keyFile(dir, 'publisher', { x: V.keys.stranger.jwk.x })), /not the public key/);
  assert.throws(() => k.sign(root, keyFile(dir, 'publisher', { alg: 'ES256' })), /EdDSA/);
  assert.throws(() => k.sign(root, path.join(dir, 'absent.jwk')), /Cannot read/);
  const der = Buffer.concat([Buffer.from('302e020100300506032b657004220420', 'hex'), Buffer.from(V.keys.publisher.seed, 'hex')]);
  const pem = path.join(dir, 'key.pem');
  fs.writeFileSync(pem, `-----BEGIN ${PEM_LABEL}-----\n${der.toString('base64')}\n-----END ${PEM_LABEL}-----\n`);
  fs.chmodSync(pem, 0o600);
  assert.throws(() => k.sign(root, pem), /--kid/);
  assert.equal(k.sign(root, pem, { kid: V.keys.publisher.jwk.kid }).signature.sig, k.sign(root, keyFile(dir)).signature.sig);
  if (spawnSync('openssl', ['version']).status === 0) {
    const made = path.join(dir, 'made.pem');
    assert.equal(spawnSync('openssl', ['genpkey', '-algorithm', 'ed25519', '-out', made]).status, 0);
    fs.chmodSync(made, 0o600);
    const answer = k.sign(root, made, { kid: 'example-2026' });
    assert.ok(k.verifyPackage({ ...readPkg(root), signatures: [answer.signature] }, { publisher: [answer.publicKey] }).ok, 'a key openssl made verifies');
  }
});

test('the command line answers JSON and exits 0, 1 or 2', (t) => {
  const dir = tempDir(t);
  const root = path.join(dir, 'pkg');
  fs.mkdirSync(root);
  writeAgent(root);
  const run = (...args) => spawnSync(process.execPath, [path.join(scripts, 'fabric-package.mjs'), ...args], { encoding: 'utf8' });
  const out = run('pack', root);
  assert.equal(out.status, 0, out.stdout + out.stderr);
  assert.equal(JSON.parse(out.stdout).digest, V.digest.expected);
  assert.equal(run('pack', root, '--apply').status, 0);
  const signed = run('sign', root, '--key', keyFile(dir), '--apply');
  assert.equal(signed.status, 0, signed.stdout);
  const trust = path.join(dir, 'trust.json');
  fs.writeFileSync(trust, JSON.stringify({ publisher: [V.keys.publisher.jwk] }));
  assert.equal(run('verify', root, '--trust', trust).status, 0);
  const refused = run('verify', root, '--trust', trust, '--countersigned');
  assert.equal(refused.status, 1);
  assert.equal(JSON.parse(refused.stdout).verdict.problem, 'no-countersignature');
  const missing = run('pack', path.join(dir, 'nowhere'));
  assert.equal(missing.status, 1);
  assert.match(JSON.parse(missing.stdout).error, /not a folder/);
  assert.equal(run('pack').status, 2);
  assert.equal(run('sign', root).status, 2);
  const priv = Buffer.from(V.keys.publisher.seed, 'hex').toString('base64url');
  for (const r of [out, signed, refused]) assert.ok(!(r.stdout + r.stderr).includes(priv), 'the private key never reaches the output');
});

test('both kits pack and sign the same folder to the same bytes', { skip: !hasPython && 'needs python3' }, (t) => {
  const dir = tempDir(t);
  const extras = { allowedToolsCeiling: ['Read', 'mcp__inbox-digest__*', 'ünï <&>'], costPresets: [{ id: 'quick', capability: 'digest.write', label: 'Quick — «быстро»', maxUsd: 0.05, default: true }, { id: 'thorough', capability: 'digest.write', label: 'Thorough', maxUsd: 1 }] };
  const make = (name) => {
    const root = path.join(dir, name);
    fs.mkdirSync(root);
    writeAgent(root, extras);
    const provider = JSON.parse(V.folder.files['fabric-agent.json']);
    provider.costPresets = extras.costPresets;
    fs.writeFileSync(path.join(root, 'fabric-agent.json'), `${JSON.stringify(provider, null, 2)}\n`);
    fs.writeFileSync(path.join(root, 'docs ä.md'), '# notes\n');
    return root;
  };
  const node = make('node');
  const py = make('py');
  const key = keyFile(dir);
  assert.ok(k.pack(node, { apply: true }).ok);
  assert.ok(k.sign(node, key, { apply: true }).ok);
  const tool = path.join(scripts, 'fabric_package.py');
  for (const args of [['pack', py, '--apply'], ['sign', py, '--key', key, '--apply']]) {
    const r = spawnSync('python3', [tool, ...args], { encoding: 'utf8' });
    assert.equal(r.status, 0, r.stdout + r.stderr);
  }
  assert.equal(fs.readFileSync(path.join(py, k.PACKAGE_FILE), 'utf8'), fs.readFileSync(path.join(node, k.PACKAGE_FILE), 'utf8'));
  const pyDry = spawnSync('python3', [tool, 'pack', py], { encoding: 'utf8' });
  const { package: _p, ...nodeDry } = k.pack(node);
  const { package: _q, ...pyAnswer } = JSON.parse(pyDry.stdout);
  assert.deepEqual(pyAnswer, nodeDry, 'the same answer, notes and problems included');
  const pyRefusal = spawnSync('python3', [tool, 'pack', path.join(dir, 'nowhere')], { encoding: 'utf8' });
  const lines = [];
  k.main(['pack', path.join(dir, 'nowhere')], (line) => lines.push(line));
  assert.equal(pyRefusal.stdout.trim(), lines.join('\n'));
});
