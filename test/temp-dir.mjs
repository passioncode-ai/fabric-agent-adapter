// Temporary directories for the Node tests (FAA-50): every one is removed when the test process exits, so a run leaves
// nothing in os.tmpdir(). A test that needs a directory to outlive its process makes its own.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const made = [];
process.on('exit', () => {
  for (const dir of made) {
    try {
      fs.rmSync(dir, { recursive: true, force: true });
    } catch {
      // A directory a child still holds open is left; nothing else is.
    }
  }
});

/** A new directory under os.tmpdir() named `<prefix>XXXXXX`, removed when this process exits. */
export function tempDir(prefix) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  made.push(dir);
  return dir;
}
