#!/usr/bin/env node
// Install a dashboard-only fabric-service/0.1 service (FAA-268): the twin of install.py, the same flags, the same
// descriptor bytes (but installedAt) and the same last stdout line. Read install.py's docstring for the rules.
//   node install.mjs --id <id> --folder <folder> [--instance default] [--name NAME] [--repository URI]
//                    [--port N] [--label LABEL --plist PLIST] [--services-dir DIR] [--json]
// Exit codes: 0 installed or already installed, 1 refused (the reason on stderr), 2 usage.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';

const here = path.dirname(fileURLToPath(import.meta.url));
const beside = path.join(here, 'fabric-service.mjs'); // the kit installed beside it, else the adapter's repository
const k = await import(pathToFileURL(fs.existsSync(beside) ? beside : path.join(here, '..', '..', 'scripts', 'fabric-service.mjs')).href);

export const VERSION = '0.1.0';
export const TOOL = `dashboard-only install ${VERSION}`;
export const PORT_FIRST = 47300;
export const PORT_LAST = 47999;
const ATTEMPTS = 8;

function claimedPorts(services, me) {
  const ports = new Set();
  for (const [, other] of k.readDescriptors(services)) {
    if (`${other.id}.${other.instance ?? 'default'}` === me || other.placement === 'remote') continue;
    try { ports.add(k.portOf(String(other.origin ?? ''))); } catch { /* an app names no port */ }
  }
  return ports;
}

function freeNow(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.listen({ host: '127.0.0.1', port, exclusive: true }, () => server.close(() => resolve(true)));
  });
}

async function candidates(services, me, wanted) {
  if (wanted !== undefined) return [wanted];
  const taken = claimedPorts(services, me);
  const out = [];
  for (let p = PORT_FIRST; p <= PORT_LAST && out.length < ATTEMPTS; p += 1) {
    if (!taken.has(p) && await freeNow(p)) out.push(p);
  }
  return out;
}

function gitOrigin(folder) {
  try {
    const url = execFileSync('git', ['-C', folder, 'config', '--get', 'remote.origin.url'],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 5000 }).trim();
    if (!url.startsWith('https://')) return null;
    return url.endsWith('.git') ? url.slice(0, -4) : url;
  } catch { return null; }
}

// As Python's Path.resolve(): the longest existing ancestor with its links resolved, then the rest as written.
function resolved(p) {
  let head = path.resolve(p);
  const rest = [];
  while (!fs.existsSync(head) && path.dirname(head) !== head) { rest.unshift(path.basename(head)); head = path.dirname(head); }
  return path.join(fs.realpathSync(head), ...rest);
}

// The line install.py prints: json.dumps(result, ensure_ascii=False), key order descriptor, key, port.
export const line = (r) => `{"descriptor": ${JSON.stringify(r.descriptor)}, "key": ${JSON.stringify(r.key)}, "port": ${r.port}}`;

function answer(file, d) {
  return { descriptor: file, key: `${d.id}.${d.instance}`, port: k.portOf(d.origin) };
}

function build(a, folder, port, repository) {
  const d = {
    protocol: k.PROTOCOL, id: a.id, instance: a.instance, name: a.name || a.id,
    summary: 'A dashboard-only service: no capabilities, no provider keys.',
    origin: `http://127.0.0.1:${port}`,
    auth: { tokenFile: path.join(folder, 'service.token') },
    lifecycle: a.label ? { manager: 'launchd', label: a.label, plist: a.plist } : { manager: 'none' },
    paths: { data: folder, logs: [] },
    installedAt: k.nowIso(),
    installedBy: { by: 'person', role: 'operator', tool: TOOL },
  };
  if (repository) d.source = { repository };
  return d;
}

export async function install(a) {
  const services = a.servicesDir ? k.expand(a.servicesDir) : k.servicesDir();
  const folder = resolved(k.expand(a.folder));
  const me = `${a.id}.${a.instance}`;
  const installed = k.descriptorPath(a.id, a.instance, services);
  if (fs.existsSync(installed) && fs.statSync(installed).isFile()) {
    let current;
    try { current = JSON.parse(fs.readFileSync(installed, 'utf8')); } catch (err) {
      throw new k.ServiceError(`The installed descriptor ${installed} cannot be read (${err.message}); nothing was written.`);
    }
    const by = current?.installedBy;
    if (!(by && typeof by === 'object' && String(by.tool ?? '').startsWith('dashboard-only install'))) {
      throw new k.ServiceError(`${me} is installed by another installer (${installed}); nothing was written.`);
    }
    if (String(current.paths?.data ?? '') !== folder) {
      throw new k.ServiceError(`${me} is installed with the folder ${current.paths?.data}, not ${folder}; nothing was written.`);
    }
    return { result: answer(installed, current), already: true };
  }
  if (a.label && !a.plist) throw new k.ServiceError("--label needs --plist, the launchd job's plist path.");
  const repository = a.repository || gitOrigin(folder);
  const ports = await candidates(services, me, a.port);
  if (!ports.length) throw new k.ServiceError(`No free port in ${PORT_FIRST}-${PORT_LAST} that no other descriptor claims.`);
  let last = null;
  for (const port of ports) {
    const d = build(a, folder, port, repository);
    const problems = k.validateDescriptor(d);
    const refusal = problems.length ? `Descriptor is invalid: ${problems.join('; ')}.` : k.sourceRefusal(d, services);
    if (refusal) throw new k.ServiceError(refusal); // before any side effect
    let file;
    try { // the descriptor first: a port claim the kit refuses leaves no folder and no token behind
      file = k.writeDescriptor(d, services);
    } catch (err) {
      if (!String(err.message).includes('already claimed') || a.port !== undefined) throw err;
      last = err;
      continue;
    }
    try {
      k.ensurePrivateDir(folder);
      k.ensureToken(path.join(folder, 'service.token')); // 0600, never printed
    } catch (err) {
      k.removeDescriptor(a.id, a.instance, services); // no descriptor names a token that is not there
      throw err;
    }
    return { result: answer(file, d), already: false };
  }
  throw last;
}

async function main(argv) {
  let a;
  try {
    const { values } = parseArgs({ args: argv, strict: true, options: {
      id: { type: 'string' }, folder: { type: 'string' }, instance: { type: 'string', default: 'default' },
      name: { type: 'string' }, repository: { type: 'string' }, port: { type: 'string' }, label: { type: 'string' },
      plist: { type: 'string' }, 'services-dir': { type: 'string' }, json: { type: 'boolean', default: false } } });
    if (!values.id || !values.folder) throw new Error('--id and --folder are required');
    if (values.port !== undefined && !/^[0-9]{1,5}$/.test(values.port)) throw new Error('--port is a number');
    a = { ...values, servicesDir: values['services-dir'], port: values.port === undefined ? undefined : Number(values.port) };
  } catch (err) {
    process.stderr.write(`usage: node install.mjs --id <id> --folder <folder> [--json] (${err.message})\n`);
    return 2;
  }
  try {
    const { result, already } = await install(a);
    if (!a.json) process.stdout.write(`${already ? 'Already installed:' : 'Installed'} ${result.key} on port ${result.port}: ${result.descriptor}\n`);
    process.stdout.write(`${line(result)}\n`);
    return 0;
  } catch (err) {
    process.stderr.write(`${err.message}\n`);
    return 1;
  }
}

// Through a symlinked folder too (board thread b42e16b7): argv[1] is the link, import.meta.url the resolved file.
const invoked = (() => { try { return fs.realpathSync(process.argv[1] ?? ''); } catch { return null; } })();
if (invoked === fileURLToPath(import.meta.url)) {
  process.exitCode = await main(process.argv.slice(2));
}
