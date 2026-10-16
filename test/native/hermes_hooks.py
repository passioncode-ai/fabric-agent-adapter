"""Optional no-model native loader probe: --python /path/to/hermes/runtime/python3."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def probe(python):
    source = Path(__file__).resolve().parents[2] / "plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/hosts/hermes"
    with tempfile.TemporaryDirectory(prefix="fabric-hermes-native-") as directory:
        home = Path(directory)
        target = home / "plugins/fabric-agent-adapter"
        target.parent.mkdir()
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
        helper = home / "fixture_helper.py"
        helper.write_text(
            'import json,sys\np=json.load(sys.stdin)\n'
            'assert p=={"cwd":"/tmp/example-project","fabric_registered":True}\n'
            'assert sys.argv[1:]==["hook","session-start","--host","hermes"]\n'
            'print("Fabric fixture context")\n'
        )
        config = {"plugins": {"enabled": ["fabric-agent-adapter"], "entries": {
            "fabric-agent-adapter": {"settings": {"session_script": str(helper)}}}},
            "mcp_servers": {"fabric": {"enabled": True, "command": "unused-fixture-command"}}}
        (home / "config.yaml").write_text(json.dumps(config))
        (home / "empty-bundled").mkdir()
        env = {key: value for key, value in os.environ.items() if key in ("PATH", "TMPDIR", "SYSTEMROOT")}
        env.update(HOME=str(home), HERMES_HOME=str(home), HERMES_BUNDLED_PLUGINS=str(home / "empty-bundled"),
                   HERMES_ENABLE_PROJECT_PLUGINS="0", PYTHONDONTWRITEBYTECODE="1")
        code = '''import json
from hermes_cli import __version__, __release_date__
from hermes_cli.plugins import PluginManager
manager=PluginManager(); manager.discover_and_load()
sections=manager.render_system_prompt_sections({"cwd":"/tmp/example-project"})
assert len(sections)==1 and sections[0].content=="Fabric fixture context"
assert any(p["name"]=="fabric-agent-adapter" and p["enabled"] for p in manager.list_plugins())
manager.unload(); assert not manager.render_system_prompt_sections({})
print(json.dumps({"version":__version__,"release":__release_date__,"native_discovery":True,"prompt_section_render":True,"native_registration_bool":True,"unload":True,"model_calls":0}))
'''
        result = subprocess.run([python, "-c", code], cwd=home, env=env, text=True,
                                capture_output=True, timeout=45)
        if result.returncode:
            raise RuntimeError("Hermes native loader probe failed (exit %s)" % result.returncode)
        receipt = json.loads(result.stdout)
        receipt["stderr_empty"] = not bool(result.stderr)
        return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    args = parser.parse_args()
    print(json.dumps(probe(args.python), sort_keys=True))
