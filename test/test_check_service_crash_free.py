#!/usr/bin/env python3
"""check_service.py reports a broken service as rule lines, never as a traceback (FAA-353, SMM Manager's board request
`26dabf75`, 2026-11-18): a token file that is not UTF-8 is `auth.token-file` FAIL and the rules after it still run; a
launchd descriptor that names no `lifecycle.plist` gets `lifecycle.plist` NOT_RUN, not `Path 'None' must be absolute`.
The kit's `read_token` refuses the bytes in both twins with the same words."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(SCRIPTS))
cs = importlib.import_module("check_service")
fs = importlib.import_module("fabric_service")


def private_file(folder: Path, name: str, data: bytes) -> Path:
    path = folder / name
    path.write_bytes(data)
    os.chmod(path, 0o600)
    return path


class TokenNotUtf8(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.token = private_file(self.dir, "token", b"\xff" * 40)

    def tearDown(self):
        self.tmp.cleanup()

    @unittest.skipIf(os.name == "nt", "the POSIX owner and mode rules come first")
    def test_the_kit_refuses_it_with_a_service_error(self):
        with self.assertRaises(fs.ServiceError) as caught:
            fs.read_token(self.token)
        self.assertIn("is not UTF-8", str(caught.exception))
        self.assertNotIn("\\xff", str(caught.exception))  # the refusal never quotes the bytes

    @unittest.skipIf(os.name == "nt", "the POSIX owner and mode rules come first")
    def test_the_node_twin_refuses_it_with_the_same_words(self):
        script = ("import * as a from %s; import * as b from %s;"
                  " try { a.readToken(process.argv[1]); console.log('read'); }"
                  " catch (e) { console.log((e instanceof b.ServiceError ? 'ServiceError' : e.name) + ': ' + e.message); }"
                  ) % (json.dumps((SCRIPTS / "fabric-auth.mjs").as_uri()), json.dumps((SCRIPTS / "fabric-base.mjs").as_uri()))
        try:
            out = subprocess.run(["node", "--input-type=module", "-e", script, str(self.token)],
                                 capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            self.skipTest("node is not on PATH")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("ServiceError", out.stdout)
        self.assertIn("is not UTF-8", out.stdout)

    @unittest.skipIf(os.name == "nt", "the POSIX owner and mode rules come first")
    def test_the_probe_fails_the_rule_and_goes_on(self):
        descriptor = {"id": "example-agent", "instance": "default", "origin": "http://127.0.0.1:9",
                      "auth": {"tokenFile": str(self.token)}}
        probe = cs.Probe(self.dir / "example-agent.default.json", descriptor, self.dir, skip_login=True)
        probe.wk = {}
        probe.request = lambda *a, **k: (401, {}, b"")
        probe.auth_rules()
        rules = {r["rule"]: r for r in probe.results}
        self.assertEqual(rules["auth.token-file"]["verdict"], "FAIL")
        self.assertIn("is not UTF-8", rules["auth.token-file"]["evidence"])
        self.assertEqual(rules["events.requires-token"]["verdict"], "PASS")
        self.assertEqual(rules["events.page"]["verdict"], "NOT_RUN")


class LaunchdWithoutPlist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def probe(self, lifecycle):
        descriptor = {"id": "example-agent", "instance": "default", "origin": "http://127.0.0.1:9",
                      "paths": {"data": str(self.dir / "data")}, "lifecycle": lifecycle}
        return cs.Probe(self.dir / "example-agent.default.json", descriptor, self.dir, skip_login=True)

    def test_no_plist_is_not_run_without_a_traceback(self):
        for lifecycle in ({"manager": "launchd", "label": "ai.example.agent"},
                          {"manager": "launchd", "label": "ai.example.agent", "plist": None},
                          {"manager": "launchd", "label": "ai.example.agent", "plist": 7},
                          {"manager": "launchd", "label": "ai.example.agent", "plist": ""}):
            with self.subTest(lifecycle=lifecycle):
                probe = self.probe(lifecycle)
                probe.lifecycle_rules()
                rules = {r["rule"]: r for r in probe.results}
                self.assertEqual(rules["lifecycle.plist"]["verdict"], "NOT_RUN")
                self.assertIn("lifecycle.plist", rules["lifecycle.plist"]["evidence"])
                self.assertNotIn("lifecycle.one-copy", rules)

    def test_a_relative_plist_is_a_fail_not_a_traceback(self):
        probe = self.probe({"manager": "launchd", "label": "ai.example.agent", "plist": "relative/agent.plist"})
        probe.lifecycle_rules()
        rules = {r["rule"]: r for r in probe.results}
        self.assertEqual(rules["lifecycle.plist"]["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
