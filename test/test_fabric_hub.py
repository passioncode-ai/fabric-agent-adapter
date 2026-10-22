"""FAA-12b: the hub door client (`fabric_hub.py`) against a fake Fabric hub: hub.json read the way Fabric's `locateHub`
reads it, every call; the door token and the binding credential from 0600 files and never anywhere else; the
board.respond ask; `fabric.board.join`; typed errors; bounded backoff."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"))
fh = importlib.import_module("fabric_hub")
from fake_fabric_hub import FakeHub, PROJECT  # noqa: E402

VECTORS = json.loads((HERE / "fixtures/contract/hub-key-vectors.json").read_text(encoding="utf-8"))


class HubTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "fabric"
        self.hub = FakeHub(self.root)
        self.cred = Path(self.tmp.name) / "svc" / "board.credential"
        self.cred.parent.mkdir(mode=0o700)
        self.cred.write_text(self.hub.credential)
        os.chmod(self.cred, 0o600)
        self.client = fh.HubClient(self.root)

    def tearDown(self) -> None:
        self.hub.close()
        self.tmp.cleanup()


class LocateTests(HubTestCase):
    def test_reads_the_published_hub(self):
        location = fh.locate_hub(self.root)
        self.assertEqual(location["origin"], "http://127.0.0.1:%d" % self.hub.port)
        self.assertEqual(location["mcpUrl"], location["origin"] + "/mcp")
        self.assertEqual(location["pid"], os.getpid())
        self.assertNotIn(self.hub.door, json.dumps(location))  # locating reads no token

    def test_no_hub_json_is_not_running_and_retryable(self):
        self.hub.withdraw()
        with self.assertRaises(fh.HubError) as cm:
            fh.locate_hub(self.root)
        self.assertEqual((cm.exception.code, cm.exception.retryable), ("not-running", True))

    def test_a_dead_pid_is_not_running(self):
        with self.assertRaises(fh.HubError) as cm:
            fh.locate_hub(self.root, alive=lambda pid: False)
        self.assertEqual(cm.exception.code, "not-running")
        self.assertIn("not running", str(cm.exception))

    def test_refuses_what_is_not_fabrics_hub(self):
        cases = [
            {"protocol": "fabric-hub/0.2"},
            {"origin": "http://localhost:%d" % self.hub.port},
            {"origin": "http://127.0.0.2:%d" % self.hub.port},
            {"origin": "http://127.0.0.1:80"},
            {"origin": "http://127.0.0.1:\u0664\u0660\u0660\u0660"},  # non-ASCII digits are not a port (FAA-78)
            {"mcp": "/other"},
            {"pid": 0},
            {"pid": True},
            {"doorTokenFile": "/tmp/elsewhere/hub-door-token"},
            {"doorTokenFile": "hub-door-token"},
        ]
        for override in cases:
            with self.subTest(override=override):
                rest = dict(override)
                self.hub.publish(rest.pop("pid", os.getpid()), **rest)
                with self.assertRaises(fh.HubError) as cm:
                    fh.locate_hub(self.root)
                self.assertEqual(cm.exception.code, "not-a-hub")

    def test_a_symlinked_or_oversized_hub_json_is_refused(self):
        target = Path(self.tmp.name) / "elsewhere.json"
        target.write_text((self.root / "hub.json").read_text())
        (self.root / "hub.json").unlink()
        (self.root / "hub.json").symlink_to(target)
        with self.assertRaises(fh.HubError) as cm:
            fh.locate_hub(self.root)
        self.assertEqual(cm.exception.code, "not-a-hub")
        (self.root / "hub.json").unlink()
        (self.root / "hub.json").write_text(" " * (fh.READ_CAP + 1))
        with self.assertRaises(fh.HubError):
            fh.locate_hub(self.root)

    def test_fabric_root_per_platform(self):
        env = {"HOME": "/h", "LOCALAPPDATA": "C:/L", "XDG_DATA_HOME": "/x"}
        self.assertEqual(fh.fabric_root("darwin", env), Path("/h/Library/Application Support/ai.passioncode.fabric"))
        self.assertEqual(fh.fabric_root("win32", env), Path("C:/L/passioncode-fabric"))
        self.assertEqual(fh.fabric_root("linux", env), Path("/x/passioncode-fabric"))
        self.assertEqual(fh.fabric_root("linux", {"HOME": "/h"}), Path("/h/.local/share/passioncode-fabric"))


class TokenTests(HubTestCase):
    def test_door_token_is_read_from_its_0600_file_only(self):
        self.assertEqual(fh.read_door_token(fh.locate_hub(self.root)), self.hub.door)
        os.chmod(self.root / "hub-door-token", 0o644)
        with self.assertRaises(fh.HubError) as cm:
            fh.read_door_token(fh.locate_hub(self.root))
        self.assertNotIn(self.hub.door, str(cm.exception))

    def test_credential_file_rules(self):
        self.assertEqual(fh.read_credential(self.cred), self.hub.credential)
        os.chmod(self.cred, 0o640)
        with self.assertRaises(fh.HubError) as cm:
            fh.read_credential(self.cred)
        self.assertEqual(cm.exception.code, "credential")
        self.assertNotIn(self.hub.credential, str(cm.exception))
        with self.assertRaises(fh.HubError) as cm:
            fh.read_credential(Path(self.tmp.name) / "missing")
        self.assertIn("request_board_access", str(cm.exception))

    def test_board_grant_repr_hides_the_bearer(self):
        grant = self.client.join_board(PROJECT, self.cred)
        self.assertNotIn(grant.bearer(), repr(grant))
        self.assertEqual(len(grant.bearer()), 43)


class AccessTests(HubTestCase):
    def test_ask_poll_and_save_the_credential_once(self):
        asked = self.client.request_board_access("example-agent", PROJECT.upper(), ["video.render"], "answers render requests")
        self.assertEqual(asked["status"], "pending")
        tool, args = self.hub.door_calls[-1]
        self.assertEqual(tool, "fabric.access.request")
        self.assertEqual(args, {"agentId": "example-agent", "callee": "fabric", "capabilities": ["board.respond"],
                                "resources": ["board:%s/video.render" % PROJECT], "reason": "answers render requests"})
        target = Path(self.tmp.name) / "svc2" / "board.credential"
        pending = self.client.poll_access(asked["requestId"], asked["pollSecret"], target)
        self.assertEqual(pending["status"], "pending")
        self.assertFalse(target.exists())
        self.hub.control({"op": "allow"})
        allowed = self.client.poll_access(asked["requestId"], asked["pollSecret"], target)
        self.assertEqual((allowed["status"], allowed["credentialSaved"]), ("allowed", True))
        self.assertNotIn("credential", allowed)
        self.assertNotIn(self.hub.credential, json.dumps(allowed))
        self.assertEqual(target.read_text(), self.hub.credential)
        self.assertEqual(os.stat(target).st_mode & 0o777, 0o600)

    def test_ask_refuses_a_bad_capability_or_project_before_sending(self):
        for project, caps in ((PROJECT, []), (PROJECT, ["Video"]), ("proj-x", ["video.render"])):
            with self.assertRaises(fh.HubError):
                self.client.request_board_access("example-agent", project, caps, "x")
        self.assertEqual(self.hub.door_calls, [])


class JoinTests(HubTestCase):
    def test_join_answers_a_board_grant(self):
        grant = self.client.join_board(PROJECT.upper(), self.cred)
        self.assertEqual((grant.project_id, grant.capabilities, grant.origin), (PROJECT, ["video.render"], "http://127.0.0.1:%d" % self.hub.port))
        self.assertEqual(self.hub.bindings_seen, ["fabric.board.join"])

    def test_no_grant_is_actionable(self):
        self.hub.grant = False
        with self.assertRaises(fh.HubError) as cm:
            self.client.join_board(PROJECT, self.cred)
        self.assertEqual(cm.exception.code, "not_authorized")
        self.assertEqual(cm.exception.data["ask"]["capabilities"], ["board.respond"])
        self.assertIn("board.respond", str(cm.exception))

    def test_the_credential_is_never_sent_when_the_pid_is_dead(self):
        client = fh.HubClient(self.root, alive=lambda pid: False)
        with self.assertRaises(fh.HubError) as cm:
            client.join_board(PROJECT, self.cred)
        self.assertEqual(cm.exception.code, "not-running")
        self.assertEqual(self.hub.bindings_seen, [])

    def test_hub_json_is_read_again_before_each_send(self):
        self.client.join_board(PROJECT, self.cred)
        self.hub.publish(os.getpid(), origin="http://localhost:%d" % self.hub.port)
        with self.assertRaises(fh.HubError) as cm:
            self.client.join_board(PROJECT, self.cred)
        self.assertEqual(cm.exception.code, "not-a-hub")
        self.assertEqual(self.hub.bindings_seen, ["fabric.board.join"])

    def test_hub_down_is_retryable(self):
        self.hub.down = True
        with self.assertRaises(fh.HubError) as cm:
            self.client.join_board(PROJECT, self.cred)
        self.assertEqual((cm.exception.code, cm.exception.retryable), ("hub-unavailable", True))
        self.hub.close()
        self.hub.down = False
        with self.assertRaises(fh.HubError) as cm:
            self.client.join_board(PROJECT, self.cred)
        self.assertEqual((cm.exception.code, cm.exception.retryable), ("hub-unavailable", True))
        self.hub = FakeHub(self.root)  # for tearDown

    def test_a_join_for_another_project_is_refused(self):
        def post(origin, body, bearer, **kw):
            return 200, {}, {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"session": {
                "bearer": "b" * 43, "sessionId": "s-1", "projectId": "00000000-0000-4000-8000-000000000000", "capabilities": []}}}}
        with self.assertRaises(fh.HubError) as cm:
            fh.HubClient(self.root, post=post).join_board(PROJECT, self.cred)
        self.assertEqual(cm.exception.code, "protocol")


class HubKeyTests(HubTestCase):
    """DEC-0060: a hub.json that names hubKey is checked against an estate record when the caller gives one."""

    def _case(self, certified: bool):
        return next(c for c in VECTORS["cases"] if bool(c["expected"].get("certified")) is certified and c.get("applied") is None
                    and "extraRevocations" not in c)

    def test_no_hub_key_means_nothing_to_check(self):
        case = self._case(True)
        fh.locate_hub(self.root, estate={"record": case["record"], "applied": None}, now=case["at"])

    def test_certified_and_refused_keys(self):
        good = self._case(True)
        self.hub.publish(os.getpid(), hubKey={"kid": good["kid"], "x": good["x"]})
        at = good["at"] if isinstance(good["at"], (int, float)) else None
        if at is None:
            self.skipTest("the vector's clock is not epoch seconds")
        fh.locate_hub(self.root, estate={"record": good["record"], "applied": None}, now=at)
        bad = self._case(False)
        self.hub.publish(os.getpid(), hubKey={"kid": bad["kid"], "x": bad["x"]})
        with self.assertRaises(fh.HubError) as cm:
            fh.locate_hub(self.root, estate={"record": bad["record"], "applied": None},
                          now=bad["at"] if isinstance(bad["at"], (int, float)) else 0)
        self.assertEqual(cm.exception.code, "hub-key-refused")
        self.assertEqual(cm.exception.data["detail"], bad["expected"]["detail"])

    def test_a_null_or_missing_applied_means_none_known_and_a_present_one_is_checked(self):
        """As fabric-hub.mjs reads `estate.applied ?? undefined`: null and absent are "no applied revision known"
        (fabric_hub maps None to fabric_estate._MISSING, since hub_key_certified refuses an explicit None, D3)."""
        good = self._case(True)
        self.hub.publish(os.getpid(), hubKey={"kid": good["kid"], "x": good["x"]})
        fh.locate_hub(self.root, estate={"record": good["record"]}, now=good["at"])
        fh.locate_hub(self.root, estate={"record": good["record"], "applied": None}, now=good["at"])
        with self.assertRaises(fh.HubError) as cm:
            fh.locate_hub(self.root, estate={"record": good["record"], "applied": {"revision": good["record"]["revision"] + 1}},
                          now=good["at"])
        self.assertEqual(cm.exception.data["detail"], "estate-rolled-back")


class BackoffTests(unittest.TestCase):
    def test_bounded_growing_never_spinning(self):
        for r in (0.0, 0.5, 0.999):
            b = fh.Backoff(rand=lambda: r)
            waits = [b.next() for _ in range(20)]
            self.assertTrue(all(1.0 <= w <= 300.0 for w in waits), waits)
            self.assertLess(waits[0], 3.0)
            self.assertGreater(waits[-1], 200.0)
        b = fh.Backoff(rand=lambda: 0.5)
        b.next(); b.next()
        b.reset()
        self.assertEqual(b.next(), 2.0)


if __name__ == "__main__":
    unittest.main()
