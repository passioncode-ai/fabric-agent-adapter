"""Hermes prompt-section bridge: bounded, silent, no model invocation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/hosts/hermes/__init__.py"
spec = importlib.util.spec_from_file_location("fabric_hermes_host", PLUGIN)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class Context:
    def __init__(self, script=None):
        self.script = script
        self.sections = []

    def get_config(self, key, default=None):
        assert key == "session_script"
        return self.script if self.script is not None else default

    def register_system_prompt_section(self, *args, **kwargs):
        self.sections.append((args, kwargs))


class HermesHostTests(unittest.TestCase):
    def test_registers_one_native_frozen_section(self):
        ctx = Context()
        host.register(ctx)
        self.assertEqual(len(ctx.sections), 1)
        args, options = ctx.sections[0]
        self.assertEqual(args[0], "fabric.context")
        self.assertTrue(callable(args[1]))
        self.assertEqual(options, {"position": "after_memory", "max_chars": 4000})

    def test_helper_protocol_and_no_shell(self):
        with patch.object(host, "_capture", return_value=b"context\n") as capture:
            self.assertEqual(host.context_for_session({"cwd": "/tmp/example"}), "context")
        args, kwargs = capture.call_args
        self.assertEqual(args[0][1:], ["-S", str(PLUGIN.parents[2] / "fabric_session.py"), "hook", "session-start", "--host", "hermes"])
        self.assertEqual(json.loads(args[1]), {"cwd": "/tmp/example", "fabric_registered": False})
        self.assertEqual(host.TIMEOUT_SECONDS, 4)
        with patch.object(host.subprocess, "Popen", side_effect=OSError) as spawn:
            with self.assertRaises(OSError):
                host._capture(["absent-helper"], b"{}")
        self.assertNotIn("shell", spawn.call_args.kwargs)
        self.assertEqual(spawn.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_configured_helper_supports_standalone_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "helper.py"
            script.write_text("print('native context')\n")
            ctx = Context(str(script))
            host.register(ctx)
            self.assertEqual(ctx.sections[0][0][1]({"cwd": directory}), "native context")

    def test_a_helper_that_never_reads_its_input_still_answers(self):
        """FAA-51: the helper exits before the payload is written; the broken pipe is not a failure. The race is
        likely, not certain (the input is capped at MAX_INPUT_BYTES), so the call repeats; the code before the fix
        failed it in 2 of 3 runs."""
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "helper.py"
            script.write_text("import sys\nsys.stdout.write('native context')\n")
            payload = b"x" * min(host.MAX_INPUT_BYTES, 1 << 20)
            for _ in range(5):
                self.assertEqual(host._capture([sys.executable, "-S", str(script)], payload), b"native context")

    def test_missing_helper_and_relative_override_are_silent(self):
        with patch.object(host, "_capture") as run:
            self.assertEqual(host.context_for_session({}, "/absent/fabric.py"), "")
            self.assertEqual(host.context_for_session({}, "relative.py"), "")
            run.assert_not_called()

    def test_bad_session_metadata_is_silent(self):
        with patch.object(host, "_capture") as run:
            for info in (None, [], {"cwd": []}, {"cwd": "bad\x00cwd"}, {"cwd": "x" * 4097}):
                self.assertEqual(host.context_for_session(info), "")
            run.assert_not_called()

    def test_failed_or_malformed_result_is_silent(self):
        for result in (None, b"x" * 4001, b"bad\x00context", b"\x1b[31mcontext", b"\xff"):
            with self.subTest(result=result is None), patch.object(host, "_capture", return_value=result):
                self.assertEqual(host.context_for_session({}), "")

    def test_timeout_os_and_decode_errors_are_silent(self):
        for error in (subprocess.TimeoutExpired("helper", 4), OSError("private diagnostic"),
                      UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")):
            with self.subTest(error=type(error).__name__), patch.object(host, "_capture", side_effect=error):
                self.assertEqual(host.context_for_session({}), "")

    def test_noisy_and_hanging_children_are_killed_with_bounded_capture(self):
        for body in ("import os\nwhile True: os.write(1,b'x'*16384)\n", "import time\ntime.sleep(20)\n",
                     "import sys\nprint('private diagnostic'); sys.exit(1)\n"):
            with tempfile.TemporaryDirectory() as directory, patch.object(host, "TIMEOUT_SECONDS", 0.3):
                script = Path(directory) / "fixture.py"
                script.write_text(body)
                started = time.monotonic()
                self.assertEqual(host.context_for_session({}, str(script)), "")
                self.assertLess(time.monotonic() - started, 2)

    def test_oversized_input_never_spawns(self):
        with patch.object(host.subprocess, "Popen") as spawn:
            self.assertIsNone(host._capture(["unused"], b"x" * (host.MAX_INPUT_BYTES + 1)))
        spawn.assert_not_called()

    def test_unavailable_native_api_does_not_raise(self):
        host.register(object())

    def test_registration_is_only_a_boolean_and_honors_disable(self):
        for config, expected in (({}, False), ({"mcp_servers": {"fabric": {}}}, True),
                                 ({"mcp_servers": {"fabric": {"enabled": False}}}, False),
                                 ({"mcp_servers": {"fabric": {"enabled": "false"}}}, False),
                                 ({"mcp_servers": {"fabric": {"enabled": "true"}}}, True),
                                 ({"mcp_servers": {"fabric": {"enabled": []}}}, False),
                                 ({"mcp_servers": {"fabric": "invalid"}}, False)):
            self.assertIs(host.fabric_registered(config), expected)
        with patch.object(host, "fabric_registered", return_value=True), patch.object(
                host, "_capture", return_value=b"context") as run:
            host.context_for_session({"cwd": "/tmp/example"})
        self.assertEqual(json.loads(run.call_args.args[1]),
                         {"cwd": "/tmp/example", "fabric_registered": True})


if __name__ == "__main__":
    unittest.main()
