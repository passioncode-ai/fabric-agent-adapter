// R1 (FAA-70, findings 10, 14 and 15): the hostile inputs of test/fixtures/kit-hostile-inputs-core.json, answered by the
// Node kit. test/test_kit_hostile_core.py runs the same cases through the Python kit, so the twins cannot drift on them.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';
import * as i from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-interop.mjs';
import { tempDir } from './temp-dir.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/kit-hostile-inputs-core.json'), 'utf8'));

// {"fakeKey": prefix} becomes prefix + "sk-" + 24 "q" (a key-shaped value made here, never stored in the fixture).
const built = (value) => {
  if (value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 1 && 'fakeKey' in value) return `${value.fakeKey}${'s'}${'k-'}${'q'.repeat(24)}`;
  if (Array.isArray(value)) return value.map(built);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, v]) => [key, built(v)]));
  return value;
};

function answer(fn, args) {
  try {
    switch (fn) {
      case 'descriptor': return k.validateDescriptor({ ...structuredClone(FIXTURE.bases[args[0]]), ...args[1] }).length ? 'refused' : 'accepted';
      case 'dashboardExtension': return k.dashboardExtensionProblems({ ...Object.values(k.dashboardExtension())[0], ...args[0] }).length ? 'refused' : 'accepted';
      case 'event': k.makeEvent(1, '2026-10-01T00:00:00Z', args[0], 'info', 'A note.', args[1] === null ? {} : { traceId: args[1], spanId: args[2] }); break;
      case 'traceparent': return i.parseTraceparent(args[0]) ? 'accepted' : 'refused';
      case 'inputKey': {
        const jobs = new i.JobStore(tempDir('kit-hostile-'));
        const job = jobs.create('example.run', {}).job.id;
        jobs.requestInput(job, { [args[0]]: i.choiceRequest('Pick.', 'x', [['a', 'A']]) });
        break;
      }
      case 'systemdUnit': k.systemdUnit(args[0], args[1], { workingDirectory: '/srv/example', environment: args[2] }); break;
      case 'task': k.taskXml(args[0], args[1], { workingDirectory: 'C:\\example', user: 'EXAMPLE\\person' }); break;
      case 'launchd': k.launchdPlist(args[0], args[1], { workingDirectory: '/srv/example', stdoutPath: '/srv/example/log', environment: args[2], exitTimeout: args[3] }); break;
      case 'remoteRequest': return k.checkRemoteRequest(args[0], args[1], args[2]) ? 'refused' : 'accepted';
      default: throw new Error(`unknown fn ${fn}`);
    }
  } catch (e) {
    if (e instanceof k.ServiceError) return 'refused';
    throw e;
  }
  return 'accepted';
}

test('every hostile core case answers as the fixture says', () => {
  assert.ok(FIXTURE.cases.length >= 40);
  for (const c of FIXTURE.cases) assert.equal(answer(c.fn, built(c.args)), c.expect, c.name);
});
