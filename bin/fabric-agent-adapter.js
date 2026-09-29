#!/usr/bin/env node
/*
 * fabric-agent-adapter installer CLI.
 *
 * Installs every skill this plugin ships into the shared agents hub
 * ~/.agents/skills/<name> (read by Codex, Cursor, Gemini, OpenCode and others).
 * Claude Code gets the skills through the plugin, never through a plain copy:
 * a copy in ~/.claude/skills shadows the plugin and serves its frozen version
 * forever. Idempotent; an existing install is skipped unless --force.
 * Zero dependencies.
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
      plain copy into ~/.claude/skills — refused while the plugin is installed
  npx @passioncode-ai/fabric-agent-adapter --prune-shadow
      remove plain ~/.claude/skills copies that shadow the installed plugin
  npx @passioncode-ai/fabric-agent-adapter --help

Claude Code (recommended):
  claude plugin marketplace add ${REPO}
  claude plugin install ${PLUGIN_ID}
Every PassionCode.ai skill for every agent at once:
  npx @passioncode-ai/passioncode@latest update`);
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
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
    console.error(`error: no skills found under ${skillRoot} — corrupted package?`);
    return 1;
  }
  const home = os.homedir();
  const hasPlugin = pluginInstalled(home);

  if (prune) {
    if (!hasPlugin) {
      console.error(`error: the ${PLUGIN_ID} plugin is not installed, so a copy in ~/.claude/skills is not a shadow — nothing removed.`);
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
  for (const name of names) {
    const dest = path.join(destRoot, name);
    if (fs.existsSync(dest) && !force) {
      console.log(`skip: ${name} already installed at ${dest} (rerun with --force to overwrite)`);
      continue;
    }
    fs.rmSync(dest, { recursive: true, force: true });
    copyDir(path.join(skillRoot, name), dest);
    console.log(`Installed ${name} -> ${dest}`);
  }
  if (target === 'agents' && !hasPlugin) {
    console.log(`Claude Code reads plugins, not the hub:\n  claude plugin marketplace add ${REPO} && claude plugin install ${PLUGIN_ID}`);
  }
  console.log('Restart your agent — skills load at session start.');
  return 0;
}

process.exit(main(process.argv));
