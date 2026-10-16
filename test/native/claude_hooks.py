"""Optional no-model Claude SDK initialization probe with an isolated owned hook."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile


def probe(binary):
    with tempfile.TemporaryDirectory(prefix="fabric-claude-native-") as directory:
        home = Path(directory)
        config = home / "config"
        config.mkdir()
        hook = home / "fixture.py"
        marker = home / "hook-called.json"
        hook.write_text('import json,sys\nfrom pathlib import Path\n'
                        'payload=json.load(sys.stdin)\n'
                        'Path(' + repr(str(marker)) + ').write_text(json.dumps({"event":payload.get("hook_event_name")}))\n'
                        'print(json.dumps({"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"Fabric native fixture"}}))\n')
        settings = home / "settings.json"
        settings.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command",
            "command": shlex.quote(sys.executable) + " -S " + shlex.quote(str(hook)), "timeout": 4}]}]}}))
        env = {key: value for key, value in os.environ.items() if key in ("PATH", "TMPDIR", "SYSTEMROOT")}
        env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(config), ANTHROPIC_BASE_URL="http://127.0.0.1:9",
                   CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1")
        request = {"type": "control_request", "request_id": "fixture-initialize", "request": {"subtype": "initialize"}}
        command = [binary, "--print", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                   "--include-hook-events", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                   "--setting-sources", "", "--settings", str(settings), "--no-session-persistence", "--no-chrome"]
        result = subprocess.run(command, cwd=home, env=env, input=json.dumps(request) + "\n", text=True,
                                capture_output=True, timeout=30)
        events = []
        for line in result.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        lifecycle = [{key: event.get(key) for key in ("type", "subtype", "hook_event", "outcome", "exit_code")
                      if key in event} for event in events if str(event.get("subtype", "")).startswith("hook_")]
        receipt = {"exit_code": result.returncode, "hook_called": marker.exists(), "hook_events": lifecycle,
                   "control_response": any(event.get("type") == "control_response" for event in events),
                   "user_turns": 0, "model_calls": 0,
                   "event_types": sorted({str(event.get("type", "")) for event in events})}
        receipt["accepted"] = result.returncode == 0 and marker.exists() and receipt["control_response"] and any(
            event.get("subtype") == "hook_response" and event.get("hook_event") == "SessionStart"
            and event.get("outcome") == "success" and event.get("exit_code") == 0 for event in lifecycle)
        if marker.exists():
            receipt["hook_input"] = json.loads(marker.read_text())
        return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude", default=shutil.which("claude"))
    args = parser.parse_args()
    if not args.claude:
        parser.error("Claude executable not found; pass --claude")
    receipt = probe(args.claude)
    print(json.dumps(receipt, sort_keys=True))
    if not receipt["accepted"]:
        raise SystemExit(1)
