"""FAA-125 (organization row N-11): one instance per context, the Python kit (fabric_context.py).

A service started for a context runs as that context's one instance on this machine: its own instance name, folders,
descriptor and instance lock; a second copy for the same context exits 75; an organization's instance runs only under a
placement of the estate record that names an unrevoked share grant for that context, inside the grant's window; a data
folder never changes context. Brief: docs/evidence/specs/2026-10-26-faa-128-125-repin-a3a66eb-brief.md (N-11 design,
D14 to D20). The cases are shared with test/fabric-context.test.mjs (test/fixtures/kit-context-cases.json)."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fabric_base  # noqa: E402
import fabric_context as fc  # noqa: E402
import fabric_descriptor  # noqa: E402
import fabric_estate  # noqa: E402
import fabric_lock  # noqa: E402
import fabric_paths  # noqa: E402
import fabric_share  # noqa: E402
import fabric_time  # noqa: E402

CASES = json.loads((ROOT / "test/fixtures/kit-context-cases.json").read_text(encoding="utf-8"))
SERVICE = CASES["service"]
RECORD = CASES["record"]
A = "urn:agent:example-agent"
NO_SUPERVISOR = {"env": {}, "argv": [], "wait_seconds": 0}


def at_seconds(text):
    return fabric_time.parse_rfc3339_ms(text) / 1000.0


class TempHome(unittest.TestCase):
    """HOME, the XDG roots and the services directory in a temporary folder: nothing touches the operator's."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        self.services = Path(self._tmp.name) / "services"
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home),
                                             "LOCALAPPDATA": str(self.home / "AppData" / "Local"),
                                             "XDG_DATA_HOME": "", "XDG_STATE_HOME": "", "XDG_CACHE_HOME": "",
                                             "FABRIC_SERVICES_DIR": str(self.services)})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def created(self):
        return sorted(str(p.relative_to(self._tmp.name)) for p in Path(self._tmp.name).rglob("*"))


class Names(unittest.TestCase):
    def test_every_name(self):
        for context, expected in CASES["names"]:
            with self.subTest(context=context[:40]):
                name = fc.context_instance_name(context)
                self.assertEqual(name, expected)
                self.assertRegex(name, fabric_base._INSTANCE, "a descriptor's instance")

    def test_the_personal_instance_is_a_parameter(self):
        self.assertEqual(fc.context_instance_name("personal", personal_instance="main"), "main")
        self.assertEqual(fc.context_instance_name("org:acme", personal_instance="main"), "org-acme")

    def test_a_readable_name_never_looks_hashed(self):
        hashed = [n for _, n in CASES["names"] if n.startswith("org-") and fc._HASHED_TAIL.search(n)]
        readable = [n for c, n in CASES["names"] if c.startswith("org:") and n == "org-" + c[4:]]
        self.assertTrue(hashed and readable)
        self.assertEqual([n for n in readable if fc._HASHED_TAIL.search(n)], [])

    def test_a_context_that_is_none_is_refused(self):
        for value in ("Personal", "ORG:x", "org:", "org:-x", "personal\n", 5, None):
            with self.subTest(value=value), self.assertRaises(fc.ContextRefused) as caught:
                fc.context_instance_name(value)
            self.assertEqual(caught.exception.code, "context-invalid")
            self.assertIsInstance(caught.exception, fabric_base.ServiceError)


class Cases(TempHome):
    def answer(self, case):
        return fc.context_instance(SERVICE, case["context"], record=RECORD if case["record"] else None,
                                   machine_id=case["machine"], agent_ref=case["agentRef"], at=at_seconds(case["at"]),
                                   personal_instance=case.get("personalInstance", "default"))

    def test_every_case(self):
        for case in CASES["cases"]:
            with self.subTest(case["name"]):
                if "refused" in case:
                    with self.assertRaises(fc.ContextRefused) as caught:
                        self.answer(case)
                    self.assertEqual(caught.exception.code, case["refused"])
                    continue
                info = self.answer(case)
                self.assertEqual(info["instance"], case["instance"])
                self.assertEqual(info["kind"], case["kind"])
                self.assertEqual(info["context"], case["context"])
                self.assertEqual(info["key"], "%s.%s" % (SERVICE, case["instance"]))
                self.assertEqual(info.get("grant"), case.get("grant"))
                self.assertEqual(info["dirs"], fabric_paths.instance_dirs(SERVICE, case["instance"]))
                self.assertEqual(info["descriptorPath"], fabric_descriptor.descriptor_path(SERVICE, case["instance"]))
                if case["kind"] == "org":
                    self.assertEqual(info["org"], case["context"][4:])
                self.assertNotIn("machines", json.dumps(info, default=str), "the answer never carries the record")
        self.assertEqual(self.created(), ["home"], "context_instance is pure: no folder, file or lock")

    def test_the_clock_defaults_to_now(self):
        info = fc.context_instance(SERVICE, "org:open-ended", record=RECORD, machine_id="machine-a", agent_ref=A)
        self.assertEqual(info["instance"], "org-open-ended")
        with self.assertRaises(fc.ContextRefused) as caught:
            fc.context_instance(SERVICE, "org:acme-rehearsal", record=RECORD, machine_id="machine-a", agent_ref=A,
                                at="not a clock")
        self.assertEqual(caught.exception.code, "grant-window")


class Dirs(TempHome):
    def test_the_personal_instance_keeps_the_services_folders(self):
        for platform in ("darwin", "linux", "win32"):
            with self.subTest(platform), mock.patch.object(sys, "platform", platform):
                self.assertEqual(fabric_paths.instance_dirs(SERVICE), fabric_paths.service_dirs(SERVICE))
                self.assertEqual(fabric_paths.instance_dirs(SERVICE, "default"), fabric_paths.service_dirs(SERVICE))

    def test_an_organizations_folders_are_siblings_named_as_its_descriptor(self):
        name = "%s.org-acme-rehearsal" % SERVICE
        local = self.home / "AppData" / "Local"
        expected = {
            "darwin": {"data": self.home / "Library/Application Support" / name, "logs": self.home / "Library/Logs" / name,
                       "cache": self.home / "Library/Caches" / name},
            "linux": {"data": self.home / ".local/share" / name, "logs": self.home / ".local/state" / name / "logs",
                      "cache": self.home / ".cache" / name},
            "win32": {"data": local / name, "logs": local / name / "Logs", "cache": local / name / "Cache"},
        }
        for platform, dirs in expected.items():
            with self.subTest(platform), mock.patch.object(sys, "platform", platform):
                got = fabric_paths.instance_dirs(SERVICE, "org-acme-rehearsal")
                self.assertEqual(got, dirs)
                personal = fabric_paths.service_dirs(SERVICE)
                for key in got:
                    self.assertNotEqual(got[key], personal[key])
                    self.assertFalse(str(got[key]).startswith(str(personal[key]) + os.sep), "never inside the personal tree")

    def test_the_instance_is_checked(self):
        for bad in ("Org", "", "a" * 33, "../x", "default.x"):
            with self.subTest(bad), self.assertRaises(fabric_base.ServiceError):
                fabric_paths.instance_dirs(SERVICE, bad)
        with self.assertRaises(fabric_base.ServiceError):
            fabric_paths.instance_dirs("Bad Id", "default")


class Hold(TempHome):
    def hold(self, context, **kwargs):
        options = dict(NO_SUPERVISOR, **kwargs)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            try:
                return fc.hold_context_instance(SERVICE, context, **options), err.getvalue(), None
            except SystemExit as exc:
                return None, err.getvalue(), exc.code

    def test_the_constants(self):
        self.assertEqual(fc.EXIT_CONTEXT_REFUSED, 78)
        self.assertEqual(fc.CONTEXT_MARKER, "fabric-context.json")

    def test_the_personal_instance_holds_the_services_lock_and_marks_its_folder(self):
        (info, lock), _, code = self.hold("personal")
        self.addCleanup(lock.release)
        self.assertIsNone(code)
        data = fabric_paths.service_dirs(SERVICE)["data"]
        self.assertEqual(lock.path, data / "service.lock", "an existing install keeps its lock (D15)")
        marker = data / "fabric-context.json"
        self.assertEqual(json.loads(marker.read_text(encoding="utf-8")),
                         {"service": SERVICE, "instance": "default", "context": "personal"})
        if os.name != "nt":
            self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
        self.assertEqual(info["instance"], "default")

    def test_a_second_copy_for_the_same_context_exits_75(self):
        (_, lock), _, _ = self.hold("personal")
        self.addCleanup(lock.release)
        held, err, code = self.hold("personal")
        self.assertIsNone(held)
        self.assertEqual(code, fabric_lock.EXIT_ALREADY_RUNNING)
        self.assertIn("already running", err)

    def test_two_contexts_run_side_by_side(self):
        (_, personal), _, _ = self.hold("personal")
        self.addCleanup(personal.release)
        org, err, code = self.hold("org:acme-rehearsal", record=RECORD, machine_id="machine-a", agent_ref=A,
                                   at=at_seconds("2026-10-26T12:00:00Z"))
        self.assertIsNone(code, err)
        info, lock = org
        self.addCleanup(lock.release)
        self.assertNotEqual(lock.path, personal.path)
        self.assertEqual(lock.path, fabric_paths.instance_dirs(SERVICE, "org-acme-rehearsal")["data"] / "service.lock")
        self.assertEqual(json.loads((lock.path.parent / "fabric-context.json").read_text(encoding="utf-8"))["context"],
                         "org:acme-rehearsal")

    def test_a_refusal_exits_78_and_creates_nothing(self):
        for context, kwargs, code in (
                ("org:acme-rehearsal", {}, "record-required"),
                ("org:revoked-org", {"record": RECORD, "machine_id": "machine-a", "agent_ref": A}, "grant-refused"),
                ("org:window-org", {"record": RECORD, "machine_id": "machine-a", "agent_ref": A,
                                    "at": at_seconds("2026-10-26T12:00:00Z")}, "grant-window"),
                ("Personal", {}, "context-invalid")):
            with self.subTest(code):
                held, err, exit_code = self.hold(context, **kwargs)
                self.assertIsNone(held)
                self.assertEqual(exit_code, 78)
                self.assertIn(code, err)
                self.assertEqual(len(err.strip().splitlines()), 1, "one sentence")
                self.assertNotIn("urn:fabric:share", err, "never a grant value")
                self.assertNotIn("machine-a", err, "never a record value")
        self.assertEqual(self.created(), ["home"], "nothing created before a refusal")

    def test_a_folder_never_changes_context(self):
        data = fabric_paths.service_dirs(SERVICE)["data"]
        data.mkdir(parents=True)
        (data / "fabric-context.json").write_text(json.dumps({"service": SERVICE, "instance": "default",
                                                               "context": "org:other"}), encoding="utf-8")
        held, err, code = self.hold("personal")
        self.assertIsNone(held)
        self.assertEqual(code, 78)
        self.assertIn("context-mismatch", err)
        fabric_lock.InstanceLock(data).acquire().release()  # the lock was released before the exit

    def test_an_unreadable_marker_is_refused(self):
        data = fabric_paths.service_dirs(SERVICE)["data"]
        data.mkdir(parents=True)
        (data / "fabric-context.json").write_text("not json", encoding="utf-8")
        held, err, code = self.hold("personal")
        self.assertEqual(code, 78)
        self.assertIn("context-mismatch", err)

    def test_an_equal_marker_is_kept(self):
        (_, lock), _, _ = self.hold("personal")
        marker = lock.path.parent / "fabric-context.json"
        before = marker.read_bytes(), marker.stat().st_mtime_ns
        lock.release()
        (_, again), _, code = self.hold("personal")
        self.addCleanup(again.release)
        self.assertIsNone(code)
        self.assertEqual((marker.read_bytes(), marker.stat().st_mtime_ns), before)


class ShareAndEstate(unittest.TestCase):
    def test_instance_share_grant_answers_and_never_raises(self):
        at = fabric_time.parse_rfc3339_ms("2026-10-26T12:00:00Z")
        for record in (None, [], {"machines": "x"}, {"machines": [{"id": "machine-a", "packages": [None, 3]}]}):
            with self.subTest(record=record):
                self.assertEqual(fabric_share.instance_share_grant(record, "machine-a", A, "org:acme-rehearsal", at)["code"],
                                 "placement-missing")
        ok = fabric_share.instance_share_grant(RECORD, "machine-a", A, "org:acme-rehearsal", at)
        self.assertEqual(ok, {"ok": True, "grant": {"id": "urn:fabric:share:" + "1" * 32,
                                                    "startsAt": "2026-10-01T00:00:00Z", "expiresAt": "2026-12-01T00:00:00Z"}})
        revoked = fabric_share.instance_share_grant(RECORD, "machine-a", A, "org:revoked-org", at)
        self.assertEqual(revoked["code"], "grant-refused")
        self.assertIn("revokes", revoked["detail"])

    def test_placement_grant_findings_is_public(self):
        placement = {"agentRef": A, "context": "org:revoked-org", "grant": "urn:fabric:share:" + "3" * 32}
        findings = fabric_estate.placement_grant_findings(RECORD, placement)
        self.assertEqual([f["code"] for f in findings], ["FAC-SEM-111"])
        self.assertEqual(findings[0]["instancePath"], "/grant")
        self.assertEqual(fabric_estate.placement_grant_findings(RECORD, {"agentRef": A}), [])
        self.assertEqual(fabric_estate.placement_grant_findings(None, None), [], "answers, never raises")


if __name__ == "__main__":
    unittest.main()
