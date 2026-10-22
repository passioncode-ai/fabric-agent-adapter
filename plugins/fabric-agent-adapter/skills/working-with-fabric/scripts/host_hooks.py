#!/usr/bin/env python3
# #region native-host-context — docs: plugins/fabric-agent-adapter/skills/working-with-fabric/references/native-host-hooks.md
"""Install bounded native context bridges. Dry-run by default; no model/service calls.

OpenCode/Pi load a managed shim. Hermes loads a managed plugin wrapper and needs
its native `hermes plugins enable fabric-agent-adapter` opt-in separately.
OpenClaw loads the bundled plugin through its native configuration. Removal
keeps unrelated settings and disables only this entry; existing allow/deny policy
is never loosened. JSON5 configuration is refused, not rewritten as guessed JSON.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('_fabric_hook_install_common', BASE / 'fabric_session.py')
fs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fs)
MARKER = 'fabric-agent-adapter managed host hook v1'
IDENTITY = 'fabric-agent-adapter'


def destination(host, env):
    home = fs._home(env)
    if host == 'opencode':
        return Path(env.get('XDG_CONFIG_HOME') or home / '.config') / 'opencode/plugins/fabric-agent-adapter.js'
    if host == 'pi':
        return Path(env.get('PI_CODING_AGENT_DIR') or home / '.pi/agent') / 'extensions/fabric-agent-adapter.js'
    if host == 'hermes':
        return Path(env.get('HERMES_HOME') or home / '.hermes') / 'plugins/fabric-agent-adapter'
    return Path(env.get('OPENCLAW_CONFIG_PATH') or Path(env.get('OPENCLAW_STATE_DIR') or home / '.openclaw') / 'openclaw.json')


def _object(parent, key):
    if key not in parent: parent[key] = {}
    if not isinstance(parent[key], dict): raise fs.Refused('unexpected object shape at ' + key)
    return parent[key]


def _list(parent, key):
    if key not in parent: parent[key] = []
    if not isinstance(parent[key], list) or not all(isinstance(x, str) for x in parent[key]):
        raise fs.Refused('unexpected string-list shape at ' + key)
    return parent[key]


def openclaw_edit(data, script, remove):
    try:
        doc = json.loads(data.decode('utf-8')) if data else {}
    except (ValueError, UnicodeError):
        raise fs.Refused('OpenClaw config is not strict JSON; use the native config CLI for JSON5')
    if not isinstance(doc, dict): raise fs.Refused('OpenClaw config must be an object')
    target = str(script.parent / 'hosts/openclaw')
    def ours(value):
        if value == target:
            return True
        if not value.replace('\\', '/').endswith('/working-with-fabric/scripts/hosts/openclaw'):
            return False
        if remove and not Path(value).expanduser().exists():
            return True  # our layout, its folder gone (FAA-90): no manifest left to read, and a dead load path
        try:
            manifest = fs.read_small(Path(value).expanduser() / 'openclaw.plugin.json')
            return isinstance(manifest, str) and json.loads(manifest).get('id') == IDENTITY
        except (ValueError, AttributeError):
            return False
    if remove:
        existing = doc.get('plugins', {})
        if isinstance(existing, dict):
            existing_entries = existing.get('entries', {})
            existing_load = existing.get('load', {})
            existing_paths = existing_load.get('paths', []) if isinstance(existing_load, dict) else []
            has_entry = isinstance(existing_entries, dict) and IDENTITY in existing_entries
            has_path = isinstance(existing_paths, list) and any(isinstance(p, str) and ours(p) for p in existing_paths)
            if not has_entry and not has_path:
                return data
    plugins = _object(doc, 'plugins')
    if not remove and (plugins.get('enabled') is False or IDENTITY in _list(plugins, 'deny')):
        raise fs.Refused('existing OpenClaw plugin policy disables this adapter; policy was preserved')
    entries = _object(plugins, 'entries')
    entry = _object(entries, IDENTITY)
    hooks = _object(entry, 'hooks')
    if not remove and (entry.get('enabled') is False or any(hooks.get(k) is False for k in ('allowConversationAccess','allowPromptInjection'))):
        raise fs.Refused('existing OpenClaw entry denies this hook; policy was preserved')
    load = _object(plugins, 'load')
    paths = _list(load, 'paths')
    kept = [p for p in paths if not ours(p)]
    load['paths'] = kept if remove else kept + [target]
    entry['enabled'] = not remove
    if remove and set(entry) <= {'enabled','hooks'} and hooks == {'allowConversationAccess':True,'allowPromptInjection':True}:
        del entries[IDENTITY]
    if not remove:
        hooks.update(allowConversationAccess=True, allowPromptInjection=True)
        if 'allow' in plugins:
            allow = _list(plugins, 'allow')
            if IDENTITY not in allow: allow.append(IDENTITY)
    return (json.dumps(doc, indent=2) + '\n').encode()


def plan(host, path, script, remove):
    """Return [(path, expected bytes, desired bytes|None)] before any mutation."""
    if host == 'openclaw':
        old = fs._read_bytes(path)
        if remove and old is None: return []
        return [(path, old, openclaw_edit(old, script, remove))]
    if host == 'hermes':
        if path.is_symlink(): raise fs.Refused('plugin directory is a symlink; nothing was changed')
        if remove:
            # Removal reads nothing from the source skill: its hosts/ folder may be gone (FAA-69).
            desired = dict.fromkeys((path/'__init__.py', path/'plugin.yaml'), '')
            return _changes(desired, remove)
        module = str(script.parent / 'hosts/hermes/__init__.py')
        loader = ('# ' + MARKER + '\nimport importlib.util\n'
                  '_spec = importlib.util.spec_from_file_location("_fabric_native_hermes", ' + repr(module) + ')\n'
                  '_module = importlib.util.module_from_spec(_spec)\n_spec.loader.exec_module(_module)\nregister = _module.register\n')
        manifest = '# ' + MARKER + '\n' + (script.parent / 'hosts/hermes/plugin.yaml').read_text()
        desired = {path/'__init__.py':loader, path/'plugin.yaml':manifest}
    else:
        module = (script.parent / ('hosts/' + host + '/fabric.mjs')).as_uri()
        desired = {path: '// ' + MARKER + '\nexport { default } from ' + json.dumps(module) + ';\n'}
    return _changes(desired, remove)


def _changes(desired, remove):
    changes = []
    for target, text in desired.items():
        old = fs._read_bytes(target)
        if old is not None and MARKER.encode() not in old.split(b'\n', 1)[0]:
            raise fs.Refused('destination is not an adapter-managed file: ' + str(target))
        changes.append((target, old, None if remove else text.encode()))
    return changes


def plan_digest(changes):
    return hashlib.sha256(json.dumps([(str(p),fs._digest(old)) for p,old,_ in changes]).encode()).hexdigest()


def main(argv=None, env=None, out=print, err=print):
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', choices=['hermes','opencode','openclaw','pi'], required=True)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--apply',action='store_true');mode.add_argument('--remove',action='store_true');mode.add_argument('--dry-run',action='store_true')
    parser.add_argument('--config');parser.add_argument('--script');parser.add_argument('--expect-sha256')
    args=parser.parse_args(argv)
    try:
        script=Path(args.script).expanduser().absolute() if args.script else BASE/'fabric_session.py'
        # Removal needs no helper: the skill it was installed from may be gone (FAA-69).
        if not args.remove and not script.is_file(): raise fs.Refused('shared helper is missing')
        if not args.remove:
            required = {'hermes':['hosts/hermes/__init__.py','hosts/hermes/plugin.yaml'],
                        'opencode':['hosts/context.mjs','hosts/opencode/fabric.mjs'],
                        'pi':['hosts/context.mjs','hosts/pi/fabric.mjs'],
                        'openclaw':['hosts/context.mjs','hosts/openclaw/index.mjs','hosts/openclaw/package.json','hosts/openclaw/openclaw.plugin.json']}[args.host]
            required += ['fabric_session_env.py','fabric_session_mcp.py','fabric_session_mail.py','fabric_session_hosts.py','fabric_session_cli.py']  # the helper's own modules (FAA-65)
            if any(not (script.parent/p).is_file() for p in required):
                raise fs.Refused('native adapter source is missing; update the complete skill before installing hooks')
        path=Path(args.config).expanduser().absolute() if args.config else destination(args.host,env)
        changes=plan(args.host,path,script,args.remove)
        digest=plan_digest(changes)
        if args.expect_sha256 and digest != args.expect_sha256: raise fs.Refused('configuration changed since the plan')
        out('host=%s sha256=%s action=%s' % (args.host,digest,'remove' if args.remove else 'install'))
        for p,old,new in changes: out('%s %s' % ('unchanged' if old==new else 'would change',p))
        if args.apply or args.remove:
            # Preflight every destination before changing even the first one.
            if any(fs._read_bytes(p) != old for p,old,_ in changes): raise fs.Refused('destination changed during planning')
            for p,old,new in changes:
                if old==new: continue
                if new is None:
                    if fs._read_bytes(p) != old: raise fs.Refused('destination changed during removal')
                    if old is not None: p.unlink()
                else: fs._replace_file(p,new,old)
            if args.host=='hermes' and args.remove:
                # A foreign addition in this directory is preserved.
                try:path.rmdir()
                except OSError:pass
            out('native loader files updated; existing sessions must reload to use them')
        else: out('dry run; no files changed. Apply with --apply --expect-sha256 ' + digest)
        if args.host=='hermes':
            out('native activation: hermes plugins %s fabric-agent-adapter' % ('disable' if args.remove else 'enable'))
        return 0
    except (fs.Refused,OSError,ValueError) as exc:
        # Refused has only our shape diagnostics; parser failures never echo config bytes.
        err('host-hooks: refused: ' + (str(exc) if isinstance(exc,fs.Refused) else type(exc).__name__))
        return 1

if __name__=='__main__':raise SystemExit(main())
# #endregion native-host-context
