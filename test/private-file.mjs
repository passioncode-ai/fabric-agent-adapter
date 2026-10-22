// A file the kit writes as private (FAA-72): on macOS and Linux its mode, on Windows its ACL (DEC-0032), where a mode
// says nothing: Node reports 0o666 or 0o444 there whatever the list grants. The Windows check is the token rule's:
// owned by the user, SYSTEM or Administrators, and every allow ACE with a non-zero mask naming one of those three.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { WINDOWS_TRUSTED, windowsAcl } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';

export function assertPrivateFile(file, mode = 0o600) {
  if (process.platform !== 'win32') {
    assert.equal(fs.statSync(file).mode & 0o777, mode, file);
    return;
  }
  const { owner, aces, user } = windowsAcl(file);
  const allowed = new Set([user, ...WINDOWS_TRUSTED]);
  assert.ok(allowed.has(owner), `${file} is owned by ${owner}`);
  const granting = aces.filter((a) => a.type === 'allow' && a.mask).map((a) => a.sid);
  assert.ok(granting.length > 0, `${file} grants nobody`);
  assert.deepEqual(granting.filter((sid) => !allowed.has(sid)), [], `${file} grants others`);
}
