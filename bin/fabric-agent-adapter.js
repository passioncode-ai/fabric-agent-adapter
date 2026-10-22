#!/usr/bin/env node
/*
 * fabric-agent-adapter installer CLI.
 *
 * Installs every skill this plugin ships into the shared agents hub
 * ~/.agents/skills/<name> (read by Codex, Cursor, Gemini, OpenCode and others).
 * Claude Code gets the skills through the plugin, never through a plain copy:
 * a copy in ~/.claude/skills shadows the plugin and serves its frozen version
 * forever. Idempotent; an existing install is skipped unless --force. Each skill is
 * copied into a sibling temporary folder and renamed into place, so a failure
 * leaves the old copy or nothing, never half of each. Zero dependencies.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

const ROOT = path.resolve(__dirname, '..');
const REPO = 'passioncode-ai/fabric-agent-adapter';
const PLUGIN_ID = 'fabric-agent-adapter@fabric-agent-adapter';

function usage() {
  console.log(`fabric-agent-adapter installer

Usage:
  npx @passioncode-ai/fabric-agent-adapter [--force]
      install every skill into the agents hub ~/.agents/skills
  npx @passioncode-ai/fabric-agent-adapter --target claude [--force]
      plain copy into ~/.claude/skills (refused while the plugin is installed)
  npx @passioncode-ai/fabric-agent-adapter --prune-shadow
      remove plain ~/.claude/skills copies that shadow the installed plugin
  npx @passioncode-ai/fabric-agent-adapter --help

Packages (fabric-package/1):
  npx @passioncode-ai/fabric-agent-adapter pack <folder> [--apply]
      list the folder's files, derive agentRef, compute the digest, check it
  npx @passioncode-ai/fabric-agent-adapter sign <folder> --key <file> [--kid <kid>] [--role publisher|organization] [--apply]
      add an Ed25519 signature from a private key file (never made or kept here)
  npx @passioncode-ai/fabric-agent-adapter verify <folder> --trust <trust.json> [--countersigned]
      check the folder and its signatures against the keys you pin

Claude Code (recommended):
  claude plugin marketplace add ${REPO}
  claude plugin install ${PLUGIN_ID}
Every PassionCode.ai skill for every agent at once:
  npx @passioncode-ai/passioncode@latest update`);
}

// Bytecode a checkout's own runs left behind is not part of a skill.
function bytecode(name) { return name === '__pycache__' || name.endsWith('.pyc'); }

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (bytecode(entry.name)) continue;
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

// The same files with the same bytes: what "already installed" means.
function sameTree(src, dest) {
  let a;
  let b;
  try {
    a = fs.readdirSync(src, { withFileTypes: true }).filter((e) => !bytecode(e.name));
    // The same filter on both sides: an installed skill whose Python ran has its own __pycache__.
    b = fs.readdirSync(dest, { withFileTypes: true }).filter((e) => !bytecode(e.name));
  } catch {
    return false;
  }
  if (a.length !== b.length) return false;
  const there = new Map(b.map((e) => [e.name, e]));
  return a.every((e) => {
    const d = there.get(e.name);
    if (!d || e.isDirectory() !== d.isDirectory() || d.isSymbolicLink()) return false;
    const s = path.join(src, e.name);
    const t = path.join(dest, e.name);
    if (e.isDirectory()) return sameTree(s, t);
    try { return fs.readFileSync(s).equals(fs.readFileSync(t)); } catch { return false; }
  });
}

// Copy beside, then rename over: the old copy stays until the new one is whole.
function installSkill(src, dest) {
  const stamp = `${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
  const temp = path.join(path.dirname(dest), `.${path.basename(dest)}.installing-${stamp}`);
  const old = path.join(path.dirname(dest), `.${path.basename(dest)}.replaced-${stamp}`);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  try {
    copyDir(src, temp);
    if (fs.existsSync(dest)) {
      fs.renameSync(dest, old);
      try {
        fs.renameSync(temp, dest);
      } catch (err) {
        fs.renameSync(old, dest);
        throw err;
      }
      fs.rmSync(old, { recursive: true, force: true });
    } else {
      fs.renameSync(temp, dest);
    }
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

// A link in the hub belongs to whoever made it: 'launcher' for the PassionCode launcher's
// ~/.passioncode/... links, 'other' for any other link, null for a directory or nothing.
function linkOwner(dest) {
  let info;
  try { info = fs.lstatSync(dest); } catch { return null; }
  if (!info.isSymbolicLink()) return null;
  return fs.readlinkSync(dest).split(path.sep).includes('.passioncode') ? 'launcher' : 'other';
}

function pluginInstalled(home) {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(home, '.claude/plugins/installed_plugins.json'), 'utf8'));
    const records = (data.plugins || {})[PLUGIN_ID] || [];
    return records.some((r) => r.installPath && fs.existsSync(path.join(r.installPath, 'skills')));
  } catch {
    return false;
  }
}

function skillNames() {
  const skillRoot = path.join(ROOT, 'plugins/fabric-agent-adapter/skills');
  if (!fs.existsSync(skillRoot)) return { skillRoot, names: [] };
  // Iterate rather than name one skill: a skill added to the plugin must not
  // require an installer change to reach anybody.
  const names = fs.readdirSync(skillRoot, { withFileTypes: true }).filter((e) => e.isDirectory()).map((e) => e.name).sort();
  return { skillRoot, names };
}

function pruneShadows(home, names) {
  let removed = 0;
  for (const name of names) {
    const shadow = path.join(home, '.claude', 'skills', name);
    let info;
    try { info = fs.lstatSync(shadow); } catch { continue; }
    const backup = path.join(home, '.claude', 'skills-shadow-backup', `${name}-${Date.now()}`);
    fs.mkdirSync(path.dirname(backup), { recursive: true });
    fs.renameSync(shadow, backup);
    console.log(`Removed shadowing ${info.isSymbolicLink() ? 'link' : 'copy'} ${shadow} (kept at ${backup})`);
    removed += 1;
  }
  if (!removed) console.log('No shadowing copies found.');
}

function main(argv) {
  const args = argv.slice(2);
  if (args.includes('--help') || args.includes('-h')) {
    usage();
    return 0;
  }
  const force = args.includes('--force');
  const prune = args.includes('--prune-shadow');
  let target = 'agents';
  const known = new Set(['--force', '--prune-shadow']);
  const unknown = [];
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === '--target') {
      target = args[i + 1];
      i += 1;
    } else if (!known.has(args[i])) unknown.push(args[i]);
  }
  if (unknown.length || !['agents', 'claude'].includes(target)) {
    console.error(`unknown argument(s): ${unknown.concat(['agents', 'claude'].includes(target) ? [] : [`--target ${target}`]).join(' ')}`);
    usage();
    return 2;
  }

  const { skillRoot, names } = skillNames();
  if (!names.length) {
    console.error(`error: no skills found under ${skillRoot}; corrupted package?`);
    return 1;
  }
  const home = os.homedir();
  const hasPlugin = pluginInstalled(home);

  if (prune) {
    if (!hasPlugin) {
      console.error(`error: the ${PLUGIN_ID} plugin is not installed, so a copy in ~/.claude/skills is not a shadow; nothing removed.`);
      return 1;
    }
    pruneShadows(home, names);
    return 0;
  }
  if (target === 'claude' && hasPlugin) {
    console.error(`error: the ${PLUGIN_ID} plugin is installed; a plain copy in ~/.claude/skills would shadow it. Update the plugin instead:\n  claude plugin marketplace update fabric-agent-adapter && claude plugin update ${PLUGIN_ID}`);
    return 1;
  }

  const destRoot = target === 'claude' ? path.join(home, '.claude', 'skills') : path.join(home, '.agents', 'skills');
  const failed = [];
  for (const name of names) {
    const dest = path.join(destRoot, name);
    const owner = linkOwner(dest);
    if (owner) {
      // One owner per artefact on disk: a plain copy over someone else's link freezes the skill
      // at this version, and its owner stops updating it. --force does not override this.
      console.log(owner === 'launcher'
        ? `skip: ${name} at ${dest} is managed by the PassionCode launcher; update it with: npx @passioncode-ai/passioncode@latest update`
        : `skip: ${name} at ${dest} is a link managed elsewhere; remove the link first to install a copy here`);
      continue;
    }
    const src = path.join(skillRoot, name);
    if (fs.existsSync(dest) && !force) {
      console.log(sameTree(src, dest)
        ? `up to date: ${name} at ${dest}`
        : `skip: ${name} at ${dest} differs from this version (rerun with --force to replace it)`);
      continue;
    }
    try {
      installSkill(src, dest);
      console.log(`Installed ${name} -> ${dest}`);
    } catch (err) {
      failed.push(name);
      console.error(`error: ${name} was not installed (${err.code || 'error'}: ${err.message}); ${fs.existsSync(dest) ? 'the copy that was there is unchanged' : 'nothing was left at ' + dest}`);
    }
  }
  if (failed.length) {
    console.error(`error: ${failed.length} of ${names.length} skill(s) failed: ${failed.join(', ')}`);
    return 1;
  }
  if (target === 'agents' && !hasPlugin) {
    console.log(`Claude Code reads plugins, not the hub:\n  claude plugin marketplace add ${REPO} && claude plugin install ${PLUGIN_ID}`);
  }
  console.log('Restart your agent: skills load at session start.');
  return 0;
}

const PACKAGE_COMMANDS = ['pack', 'sign', 'verify'];
if (PACKAGE_COMMANDS.includes(process.argv[2])) {
  // The package commands live in the kit (fabric-package.mjs), one implementation for the skill and this CLI.
  const kit = path.join(ROOT, 'plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-package.mjs');
  import(require('url').pathToFileURL(kit).href).then((m) => { process.exitCode = m.main(process.argv.slice(2)); });
} else {
  process.exit(main(process.argv));
}
