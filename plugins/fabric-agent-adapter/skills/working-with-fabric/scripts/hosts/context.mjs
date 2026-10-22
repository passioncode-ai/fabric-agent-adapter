// #region native-host-context — docs: plugins/fabric-agent-adapter/skills/working-with-fabric/references/native-host-hooks.md
// Shared, non-resident bridge. A context hook never enrolls or calls a model.
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(new URL('../fabric_session.py', import.meta.url));
const hosts = new Set(['opencode', 'pi', 'openclaw']);
const cap = 64 * 1024;

// Resolves the helper's context, '' when it answered none (or nothing usable), and null when the run failed: an error,
// a nonzero exit, a timeout, output over the cap, a missing python3 or script. A caller treats null as no context;
// onceEach keeps no null, so the next request runs the helper again.
export async function readContext(host, cwd, options = {}) {
  if (!hosts.has(host) || typeof cwd !== 'string' || !cwd || cwd.includes('\0')) return '';
  const payload = {cwd};
  if (options.fabricRegistered === true) payload.fabric_registered = true;
  const input = JSON.stringify(payload);
  if (Buffer.byteLength(input) > cap) return '';
  const timeout = Number.isFinite(options.timeoutMs)
    ? Math.max(1, Math.min(4000, options.timeoutMs)) : 4000;
  return new Promise(resolve => {
    try {
      const child = execFile(options.python || 'python3',
        ['-S', options.script || scriptPath, 'hook', 'session-start', '--host', host],
        {timeout, killSignal:'SIGKILL', maxBuffer:cap, encoding:'utf8', windowsHide:true},
        (error, stdout) => {
          if (error || typeof stdout !== 'string') return resolve(null);
          if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(stdout)) return resolve('');
          resolve(stdout.trim());
        });
      // A missing executable or early exit may close stdin before it is written.
      child.stdin?.on('error', () => {});
      child.stdin?.end(input);
    } catch { resolve(null); }
  });
}

// One helper run per host, workspace and registration in this process (FAA-69): OpenCode and OpenClaw ask on every
// request, and the answer does not change within a process. A failed run (a rejection, or null from readContext) is
// not kept, so the next request asks again.
const cacheCap = 64;
export function onceEach(reader = readContext) {
  const answers = new Map();
  return (host, cwd, options = {}) => {
    const key = JSON.stringify([host, cwd, options.fabricRegistered === true]);
    if (!answers.has(key)) {
      if (answers.size >= cacheCap) answers.delete(answers.keys().next().value);
      const pending = Promise.resolve().then(() => reader(host, cwd, options));
      answers.set(key, pending);
      const forget = () => { if (answers.get(key) === pending) answers.delete(key); };
      pending.then((value) => { if (value === null || value === undefined) forget(); }, forget);
    }
    return answers.get(key);
  };
}
// #endregion native-host-context
