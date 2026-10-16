#!/usr/bin/env python3
"""Optional real OpenClaw loader regression; no install, model, Gateway or account.

python3 test/native/openclaw_hooks.py /path/to/openclaw
python3 test/native/openclaw_hooks.py /path/to/npm-prefix

Requires OpenClaw 2026.10.4 or a compatible runtime and its supported Node.
Uses disposable state/config/workspace and prints only sanitized assertions.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / 'plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/hosts/openclaw'


def runtime_command(value):
    path = Path(value).expanduser().resolve()
    if path.is_dir():
        candidates = [path / 'node_modules/openclaw/openclaw.mjs', path / 'openclaw.mjs']
        path = next((candidate for candidate in candidates if candidate.is_file()), path)
    if not path.is_file():
        raise ValueError('runtime executable or npm prefix not found')
    if path.suffix == '.mjs':
        node = shutil.which('node')
        if not node:
            raise ValueError('Node is required for the supplied runtime')
        return [node, str(path)]
    return [str(path)]


def run(command, env, cwd, timeout):
    child = subprocess.Popen(command, env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=os.name == 'posix')
    try:
        stdout, _stderr = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == 'posix':
            os.killpg(child.pid, signal.SIGKILL)
        else:
            child.kill()
        child.communicate()
        raise RuntimeError('native loader exceeded the bounded probe timeout') from None
    if child.returncode:
        raise RuntimeError(f'native loader exited {child.returncode}; raw diagnostics withheld')
    if len(stdout.encode('utf-8')) > 2 * 1024 * 1024:
        raise RuntimeError('native loader output exceeded probe limit')
    return stdout


def inspect(command, env, workspace, timeout):
    data = json.loads(run(command + ['plugins', 'inspect', 'fabric-agent-adapter',
                                    '--runtime', '--json'], env, workspace, timeout))
    if not isinstance(data, dict):
        raise RuntimeError('native loader did not return an object')
    plugin = data.get('plugin', {})
    if plugin.get('status') != 'loaded' or plugin.get('imported') is not True:
        raise RuntimeError('plugin was not imported and loaded')
    if data.get('services') or data.get('tools') or data.get('httpRouteCount'):
        raise RuntimeError('context plugin unexpectedly registered active capabilities')
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime', help='OpenClaw executable, openclaw.mjs, or installed npm prefix')
    parser.add_argument('--timeout', type=int, default=90, help='per-command deadline, 1–180 seconds')
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 180:
        parser.error('--timeout must be between 1 and 180')
    command = runtime_command(args.runtime)
    with tempfile.TemporaryDirectory(prefix='fabric-openclaw-native-') as folder:
        probe = Path(folder)
        state, workspace = probe / 'state', probe / 'workspace'
        state.mkdir(); workspace.mkdir()
        config_path = state / 'openclaw.json'
        env = {key: value for key, value in os.environ.items()
               if key in {'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'SYSTEMROOT', 'WINDIR'}}
        env.update(OPENCLAW_STATE_DIR=str(state), OPENCLAW_CONFIG_PATH=str(config_path),
                   OPENCLAW_NO_RESPAWN='1')
        base = {
            'agents': {'defaults': {'workspace': str(workspace)}},
            'plugins': {
                'enabled': True,
                'allow': ['fabric-agent-adapter'],
                'load': {'paths': [str(PLUGIN)]},
                'entries': {'fabric-agent-adapter': {'enabled': True, 'hooks': {
                    'allowConversationAccess': True, 'allowPromptInjection': True,
                }}},
            },
        }
        version = run(command + ['--version'], env, workspace, args.timeout).strip()
        if not version.startswith('OpenClaw ') or len(version) > 200:
            raise RuntimeError('unexpected runtime version output')
        receipts = []
        for label, overrides in [
            ('enabled', {}),
            ('conversation_access_denied', {'allowConversationAccess': False}),
            ('prompt_injection_denied', {'allowPromptInjection': False}),
        ]:
            config = json.loads(json.dumps(base))
            config['plugins']['entries']['fabric-agent-adapter']['hooks'].update(overrides)
            config_path.write_text(json.dumps(config), encoding='utf-8')
            result = inspect(command, env, workspace, args.timeout)
            hooks = [entry.get('name') for entry in result.get('typedHooks', [])]
            expected = ['before_prompt_build'] if label == 'enabled' else []
            if hooks != expected:
                raise RuntimeError(f'{label}: native registered hooks differ from contract')
            diagnostics = result.get('diagnostics', [])
            if label == 'enabled' and diagnostics:
                raise RuntimeError('enabled: unexpected native diagnostics')
            if overrides and not any('blocked' in str(item.get('message', '')).lower()
                                     for item in diagnostics):
                raise RuntimeError(f'{label}: missing explicit native blocked diagnostic')
            for key, expected_policy in overrides.items():
                if result.get('policy', {}).get(key) is not expected_policy:
                    raise RuntimeError(f'{label}: native permission policy differs')
            receipts.append({'case': label, 'loaded': True, 'typedHooks': hooks, 'passed': True})
        print(json.dumps({'runtime': version, 'checks': receipts,
                          'model_calls': 0, 'gateway_started': False}, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('OpenClaw native probe failed: ' + (str(exc) if isinstance(exc, RuntimeError)
                                                else type(exc).__name__))
        raise SystemExit(1)
