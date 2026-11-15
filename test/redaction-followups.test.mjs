// FAA-200 follow-ups (39), (33), (15), (28): the Node twin of test_redaction_followups.py. Every key-shaped value is
// made up and built here at run time, never written whole.
import assert from 'node:assert/strict';
import test from 'node:test';
import * as fh from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-http.mjs';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';
import { secretLaunchArgument } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-secrets.mjs';

const KEY = `ghp_${'Fx9k'.repeat(9)}`; // made up: shaped like a key, never one
const AKIA = `AKIA${'QX7Z'.repeat(4)}`; // made up
const SK_RUN = `sk-${'Ab1d'.repeat(10)}`; // made up, a key DEC-0151 reads
const descriptor = (extra = {}) => ({
  protocol: k.PROTOCOL, id: 'sample', instance: 'default', name: 'Sample', origin: 'http://127.0.0.1:47210',
  auth: { tokenFile: '/tmp/x/service.token' }, lifecycle: { manager: 'none' }, paths: { data: '/tmp/x', logs: [] },
  installedAt: k.nowIso(), installedBy: 'test', source: { repository: 'https://github.com/example-org/example-agent' }, ...extra,
});

test('a key-shaped scheme is redacted, never printed (FAA-200 (33))', () => {
  for (const value of [`${AKIA}:x@h.example/r`, `${SK_RUN}://h.example:99/r`, ` ${AKIA}://h.example/r`]) {
    assert.ok(fh.redactUrl(value) === '<redacted>:<redacted>', 'a key-shaped scheme is printed');
  }
  assert.equal(fh.redactUrl('ssh://h.example/r'), 'ssh:<redacted>', 'a scheme with no key shape keeps its name');
  assert.throws(() => fh.checkUrl(`${SK_RUN}://h.example/r`), (e) => !`${e.message}${e.url}`.toLowerCase().includes(SK_RUN.toLowerCase()));
});

test('a user holding a question mark or a hash is unparseable (FAA-200 (15))', () => {
  assert.equal(fh.redactUrl('https://tok?en@host.example/o/r'), '<unparseable url>');
  assert.equal(fh.redactUrl('https://tok#en@host.example/o/r'), '<unparseable url>');
  assert.equal(fh.redactUrl('https://host.example/o/r?next=a@b.example'), 'https://host.example/o/r', 'after the path');
});

test('no descriptor problem names a key-shaped member (FAA-200 (39))', () => {
  const cases = [
    descriptor({ installedBy: { by: 'node', tool: 'x 1', [KEY]: 'y' } }),
    descriptor({ runner: { credentialKind: 'none', [KEY]: 'y' } }),
    descriptor({ source: { repository: 'https://github.com/example-org/example-agent', [KEY]: 'y' } }),
    descriptor({ peer: { endpoint: 'https://agent.example.com', custody: 'personal', residency: ['DE'], maxDataClass: 'public', [KEY]: 'y' }, runner: { credentialKind: 'none' } }),
    descriptor({ commands: { [KEY]: ['/bin/x'] } }),
  ];
  for (const value of cases) {
    const problems = k.validateDescriptor(value);
    const text = problems.join('; ');
    assert.ok(problems.length);
    assert.ok(!text.includes(KEY), 'a key-shaped member name is printed');
    assert.ok(text.includes('<redacted>'), 'no <redacted> in the problems');
  }
  assert.ok(k.validateDescriptor(descriptor({ source: { repository: 'https://github.com/example-org/example-agent', branch: 'main' } })).includes('source has no member branch'));
});

test('a URL inside a launch argument is read as a URL (FAA-200 (28))', () => {
  const credentialUrl = `https://${'u:'}${'fixture9pw'}@h.example/r`;
  assert.equal(secretLaunchArgument(`--remote=${credentialUrl}`), true);
  assert.equal(secretLaunchArgument(KEY), true);
  assert.equal(secretLaunchArgument('--remote=https://h.example/r'), false);
  assert.equal(secretLaunchArgument('--port=47201'), false);
  const problems = k.validateDescriptor(descriptor({ commands: { doctor: ['/bin/x', `--remote=${credentialUrl}`] } }));
  assert.ok(problems.some((p) => p.includes('FAC-SEM-057') && p.includes('doctor')), problems.join('; '));
  assert.ok(!problems.join(' ').includes('fixture9pw'));
  assert.deepEqual(k.validateDescriptor(descriptor({ commands: { doctor: ['/bin/x', '--remote=https://h.example/r'] } })), []);
});
