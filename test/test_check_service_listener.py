#!/usr/bin/env python3
"""check_service.py's `listener.owner` (FAA-226, the contract's DEC-0154 HA-2): a local service is read only when this
OS account's process holds its port. `down`, then `foreign-user`, then everything the listener answers; a refused
listener gets no request at all, the token included."""
from __future__ import annotations

import http.server
import importlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(SCRIPTS))
cs = importlib.import_module("check_service")
po = importlib.import_module("fabric_peer_owner")


class Served(unittest.TestCase):
    def setUp(self):
        self.seen = []
        outer = self

        class WellKnown(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.seen.append((self.path, self.headers.get("Authorization")))
                body = json.dumps({"service": {"id": "example-agent", "instance": "default"}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), WellKnown)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.port = self.server.server_address[1]
        self.tmp = tempfile.TemporaryDirectory()
        self.descriptor = {"id": "example-agent", "instance": "default", "origin": "http://127.0.0.1:%d" % self.port}
        path = Path(self.tmp.name) / "example-agent.default.json"
        path.write_text(json.dumps(self.descriptor))
        self.probe = cs.Probe(path, self.descriptor, Path(self.tmp.name), skip_login=True)
        po._LISTENERS.clear()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()
        po._LISTENERS.clear()

    def verdict(self):
        return next(r for r in self.probe.results if r["rule"] == "listener.owner")

    def test_this_accounts_listener_passes_from_the_real_table(self):
        self.assertTrue(self.probe.listener_rule())
        self.assertEqual(self.verdict()["verdict"], "PASS")

    def test_another_account_root_or_an_unknown_owner_fails_as_foreign_user(self):
        for owner in (po.Owner(po.ANOTHER_ACCOUNT, 502, 9, "x"), po.Owner(po.SYSTEM, 0, 1, "x"),
                      po.Owner(po.UNKNOWN, None, None, "x", "no-row")):
            with self.subTest(kind=owner.kind):
                self.probe.results.clear()
                with mock.patch.object(po, "listener", return_value=owner):
                    self.assertFalse(self.probe.listener_rule())
                got = self.verdict()
                self.assertEqual(got["verdict"], "FAIL")
                self.assertTrue(got["evidence"].startswith("foreign-user: 127.0.0.1:%d" % self.port), got["evidence"])

    def test_nothing_listening_is_not_run_and_the_well_known_rule_reports_down(self):
        with mock.patch.object(po, "listener", return_value=po.Owner(po.NONE, method="x")):
            self.assertTrue(self.probe.listener_rule())
        self.assertEqual(self.verdict()["verdict"], "NOT_RUN")

    def test_a_foreign_user_port_is_never_read(self):
        """run() stops after the FAIL: no rule reads the port, so the server sees no request and no token."""
        with mock.patch.object(po, "listener", return_value=po.Owner(po.ANOTHER_ACCOUNT, 502, 9, "x")), \
                mock.patch.object(cs.Probe, "descriptor_rules", lambda self: None), \
                mock.patch.object(cs.Probe, "lifecycle_rules", lambda self: None):
            results = self.probe.run()
        self.assertEqual([r["rule"] for r in results], ["listener.owner"])
        self.assertEqual(self.seen, [])

    def test_a_listener_swapped_after_the_rule_is_refused_on_the_connection(self):
        """The rule reads the port's listener; every request checks its own connection again (CheckedHTTPConnection),
        and a refusal there is a ConnectionError naming foreign-user, with nothing sent."""
        with mock.patch.object(po, "server_end", return_value=po.Owner(po.ANOTHER_ACCOUNT, 502, 9, "x")):
            with self.assertRaises(cs.ForeignUser) as caught:
                self.probe.request("GET", "/.well-known/fabric-service", {"Authorization": "Bearer synthetic"})
        self.assertIn("foreign-user", str(caught.exception))
        self.assertIsInstance(caught.exception, ConnectionError)
        self.assertEqual(self.seen, [])
        self.assertEqual(self.probe.request("GET", "/.well-known/fabric-service")[0], 200)


if __name__ == "__main__":
    unittest.main()
