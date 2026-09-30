"""The sample service as a real MCP client sees it: the installed Claude Code CLI.

Opt-in (FABRIC_REAL_CLIENT=1, and `claude` on PATH). SDK-level tests cannot see what a real
client refuses: Claude Code 2.1.285 opens with `initialize`, which the kit once answered with
-32601, and a client may refuse a whole tools/list over one outputSchema. The CLI runs in a
throwaway directory with --strict-mcp-config and a temporary config (mode 600, the token in a
header); it is stopped as soon as it has printed its init event, before any model call. The
operator's own Claude Code configuration is never read or written.
"""

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(os.environ.get("FABRIC_REAL_CLIENT") == "1" and shutil.which("claude"), "opt-in: FABRIC_REAL_CLIENT=1 and claude on PATH")
class RealClientTests(unittest.TestCase):
    def test_claude_code_connects_and_lists_every_sample_tool(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            data, services, work = base / "data", base / "services", base / "work"
            work.mkdir()
            port = free_port()
            service = subprocess.Popen([sys.executable, str(SCRIPTS / "sample_service.py"), "serve", "--port", str(port),
                                        "--data-dir", str(data)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.time() + 10
                while time.time() < deadline:
                    try:
                        urllib.request.urlopen("http://127.0.0.1:%d/.well-known/fabric-service" % port, timeout=0.5)
                        break
                    except OSError:
                        time.sleep(0.1)
                subprocess.run([sys.executable, str(SCRIPTS / "sample_service.py"), "register", "--port", str(port),
                                "--data-dir", str(data), "--services-dir", str(services)], check=True, capture_output=True)
                config = work / "mcp.json"
                fd = os.open(str(config), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as handle:
                    json.dump({"mcpServers": {"sample": {"type": "http", "url": "http://127.0.0.1:%d/mcp" % port,
                               "headers": {"Authorization": "Bearer " + (data / "service.token").read_text().strip()}}}}, handle)
                cli = subprocess.Popen(["claude", "-p", "Reply with the single word OK.", "--strict-mcp-config",
                                        "--mcp-config", str(config), "--output-format", "stream-json", "--verbose", "--max-turns", "1"],
                                       cwd=str(work), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                init = None
                try:
                    for line in cli.stdout:
                        try:
                            message = json.loads(line)
                        except ValueError:
                            continue
                        if message.get("type") == "system" and message.get("subtype") == "init":
                            init = message
                            break
                finally:
                    cli.terminate()
                    cli.wait(20)
                    cli.stdout.close()
            finally:
                service.terminate()
                service.wait(10)
            self.assertIsNotNone(init, "the CLI printed no init event")
            status = {s["name"]: s["status"] for s in init.get("mcp_servers", [])}
            self.assertEqual(status.get("sample"), "connected")
            tools = sorted(t for t in init.get("tools", []) if t.startswith("mcp__sample__"))
            self.assertEqual(tools, ["mcp__sample__fabric_job_cancel", "mcp__sample__fabric_job_get",
                                     "mcp__sample__sample_draft", "mcp__sample__sample_echo"])


if __name__ == "__main__":
    unittest.main()
