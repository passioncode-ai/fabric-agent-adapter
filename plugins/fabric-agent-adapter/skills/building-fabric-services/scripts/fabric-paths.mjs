// Where a service's things live (fabric-service/0.1): the services directory, its data, config, logs and run dirs per OS, private dirs, atomic writes.
// Part of the Node service kit (FAA-65, layer L1); the twin of fabric_paths.py. Node 20+, no dependency.
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ID, ServiceError, expand } from './fabric-base.mjs';
import { windowsProtect } from './fabric-platform.mjs';

// DEC-0032: LOCALAPPDATA, not APPDATA, so token files never roam with the profile.
const localAppData = () => process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');

export function servicesDir(platform = process.platform) {
  if (process.env.FABRIC_SERVICES_DIR) return expand(process.env.FABRIC_SERVICES_DIR);
  const home = os.homedir();
  if (platform === 'darwin') return path.join(home, 'Library/Application Support/ai.passioncode.fabric/services');
  if (platform === 'win32') return path.join(localAppData(), 'passioncode-fabric', 'services');
  return path.join(process.env.XDG_DATA_HOME || path.join(home, '.local/share'), 'passioncode-fabric/services');
}

export function serviceDirs(id, platform = process.platform) {
  if (!ID.test(id)) throw new ServiceError(`Service id ${id} must match ${ID}.`);
  const home = os.homedir();
  if (platform === 'darwin') {
    return {
      data: path.join(home, 'Library/Application Support', id),
      logs: path.join(home, 'Library/Logs', id),
      cache: path.join(home, 'Library/Caches', id),
    };
  }
  if (platform === 'win32') {
    const data = path.join(localAppData(), id);
    return { data, logs: path.join(data, 'Logs'), cache: path.join(data, 'Cache') };
  }
  return {
    data: path.join(process.env.XDG_DATA_HOME || path.join(home, '.local/share'), id),
    logs: path.join(process.env.XDG_STATE_HOME || path.join(home, '.local/state'), id, 'logs'),
    cache: path.join(process.env.XDG_CACHE_HOME || path.join(home, '.cache'), id),
  };
}

export function ensurePrivateDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
  if (process.platform === 'win32') windowsProtect(dir, { folder: true });
  else fs.chmodSync(dir, 0o700);
  return dir;
}

export function atomicWrite(file, data, mode = 0o600) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = path.join(path.dirname(file), `.${path.basename(file)}.${process.pid}.${crypto.randomBytes(4).toString('hex')}`);
  const fd = fs.openSync(tmp, 'wx', mode);
  try {
    try {
      // On Windows the file's ACL is its privacy (DEC-0032): set explicitly and protected — before the bytes go in —
      // so it does not depend on what the folder hands down. A rename keeps it.
      if (process.platform === 'win32') windowsProtect(tmp, { folder: false });
      fs.writeSync(fd, data);
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
    if (process.platform !== 'win32') fs.chmodSync(tmp, mode);
    fs.renameSync(tmp, file);
  } catch (error) {
    fs.rmSync(tmp, { force: true }); // whatever failed, no half-written file is left beside the real one (FAA-85)
    throw error;
  }
}
