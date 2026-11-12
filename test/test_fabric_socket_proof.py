#!/usr/bin/env python3
"""fabric_socket_proof.py (FAA-292, DEC-0155 RT-2; FAA-272): this OS account's own sockets, and the two proofs read
from them: the server end of a connection accepted in one of this account's processes, and this account's listener on
exactly 127.0.0.1. The parsers and the proofs are held to `test/fixtures/peer-owner/socket-proof-cases.json`, which
the Node twin (`fabric-socket-proof.test.mjs`) answers too; the live cases run on macOS only.
"""
from __future__ import annotations

import importlib
import json
import os
import pathlib
import socket
import struct
import sys
import threading
import time
import unittest

TEST = pathlib.Path(__file__).resolve().parent
SCRIPTS = TEST.parent / "plugins" / "fabric-agent-adapter" / "skills" / "building-fabric-services" / "scripts"
sys.path.insert(0, str(SCRIPTS))
SP = importlib.import_module("fabric_socket_proof")
CASES = json.loads((TEST / "fixtures" / "peer-owner" / "socket-proof-cases.json").read_text(encoding="utf-8"))
OWN = CASES["ownUid"]


def sockets(items):
    return [SP.Socket(tuple(s["local"]), tuple(s["remote"]), s["listening"], s["pid"]) for s in items]


def proof(p):
    return {"proved": p.proved, "pid": p.pid, "reason": p.reason}


class Records(unittest.TestCase):
    def test_each_captured_record_reads_back(self):
        for rec in CASES["records"]:
            with self.subTest(rec=rec["name"]):
                got = SP.parse_socket_fdinfo(bytes.fromhex(rec["hex"]))
                want = rec["expect"]
                if want is None:
                    self.assertIsNone(got)
                else:
                    self.assertEqual(got, (tuple(want["local"]), tuple(want["remote"]), want["state"],
                                           int(want["handle"], 16)))

    def test_a_short_record_is_unreadable(self):
        with self.assertRaises(SP.ProofUnreadable):
            SP.parse_socket_fdinfo(bytes.fromhex(CASES["records"][0]["hex"])[:-1])

    def test_the_records_of_this_account_as_sockets(self):
        found = []
        for rec, pid in zip(CASES["records"], CASES["recordSockets"]["pids"]):
            parsed = SP.parse_socket_fdinfo(bytes.fromhex(rec["hex"]))
            if parsed is not None:
                found.append((pid,) + parsed)
        self.assertEqual(SP.own_sockets(found), sockets(CASES["recordSockets"]["expect"]))

    def test_closed_and_time_wait_sockets_are_left_out_and_a_shared_socket_has_no_pid(self):
        local, remote = ("127.0.0.1", 47311), ("127.0.0.1", 50001)
        rows = [(4100, local, remote, 0, 1), (4100, local, ("127.0.0.1", 50002), 10, 2),
                (4100, local, ("127.0.0.1", 50003), 4, 3), (4101, local, ("127.0.0.1", 50003), 4, 3)]
        self.assertEqual(SP.own_sockets(rows), [SP.Socket(local, ("127.0.0.1", 50003), False, None)])


class Lsof(unittest.TestCase):
    def test_the_vectors(self):
        for case in CASES["lsof"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(SP.parse_lsof_sockets(case["text"], case["uid"]), sockets(case["expect"]))


class Questions(unittest.TestCase):
    def test_the_vectors(self):
        for case in CASES["questions"]:
            with self.subTest(case=case["name"]):
                have = sockets(case["sockets"])
                if case["ask"] == "accepted":
                    got = SP.accepted_in(have, tuple(case["server"]), tuple(case["client"]), "lsof")
                else:
                    got = SP.listener_in(have, case["port"], "lsof")
                self.assertEqual(proof(got), case["expect"])


class Readers(unittest.TestCase):
    """The proofs as a caller asks them, with the platform, the uids and the programs injected."""

    def lsof_runner(self, text, calls):
        def run(argv):
            calls.append(list(argv))
            return text
        return run

    def test_off_macos_nothing_is_proved(self):
        got = SP.accepted(("127.0.0.1", 47311), ("127.0.0.1", 50001), platform="linux", uid=OWN, euid=OWN)
        self.assertEqual(proof(got), {"proved": False, "pid": None, "reason": "table-restricted: unsupported-platform"})

    def test_a_set_uid_reader_proves_nothing(self):
        got = SP.own_listener(47311, platform="darwin", uid=OWN, euid=0, how="lsof", run=lambda argv: self.fail(argv))
        self.assertEqual(proof(got), {"proved": False, "pid": None, "reason": "table-restricted: setuid-context"})

    def test_the_lsof_reader_asks_for_this_account_s_sockets_on_the_port(self):
        calls = []
        text = CASES["lsof"][0]["text"]
        got = SP.accepted(("127.0.0.1", 47311), ("127.0.0.1", 50001), platform="darwin", uid=OWN, euid=OWN, how="lsof",
                          run=self.lsof_runner(text, calls))
        self.assertEqual(proof(got), {"proved": True, "pid": 4100, "reason": None})
        self.assertEqual(got.method, "lsof")
        self.assertEqual(calls, [[SP.LSOF, "-nP", "-a", "-u", str(OWN), "-iTCP:47311", "-sTCP:ESTABLISHED", "-F", "pun"]])
        calls.clear()
        got = SP.own_listener(47311, platform="darwin", uid=OWN, euid=OWN, how="lsof",
                              run=self.lsof_runner(CASES["lsof"][1]["text"], calls))
        self.assertEqual(proof(got), {"proved": True, "pid": 4100, "reason": None})
        self.assertEqual(calls, [[SP.LSOF, "-nP", "-a", "-u", str(OWN), "-iTCP:47311", "-sTCP:LISTEN", "-F", "pun"]])

    def test_a_server_that_accepts_late_is_waited_for_briefly(self):
        texts = ["", "", CASES["lsof"][0]["text"]]
        calls = []

        def run(argv):
            calls.append(argv)
            return texts[min(len(calls) - 1, 2)]
        got = SP.accepted(("127.0.0.1", 47311), ("127.0.0.1", 50001), wait=True, platform="darwin", uid=OWN,
                          euid=OWN, how="lsof", run=run)
        self.assertTrue(got.proved)
        self.assertEqual(len(calls), 3)

    def test_without_the_wait_one_read_answers(self):
        calls = []
        got = SP.accepted(("127.0.0.1", 47311), ("127.0.0.1", 50001), platform="darwin", uid=OWN, euid=OWN,
                          how="lsof", run=self.lsof_runner("", calls))
        self.assertEqual(proof(got), {"proved": False, "pid": None, "reason": "table-restricted"})
        self.assertEqual(len(calls), 1)

    def test_a_reader_that_fails_proves_nothing_and_names_why(self):
        def run(argv):
            raise SP.ProofUnreadable("lsof: exit 2")
        got = SP.own_listener(47311, platform="darwin", uid=OWN, euid=OWN, how="lsof", run=run)
        self.assertEqual(proof(got), {"proved": False, "pid": None, "reason": "table-restricted: lsof: exit 2"})


class Calibration(unittest.TestCase):
    def setUp(self):
        self.saved = list(SP._LIBPROC_OK)
        self.addCleanup(lambda: SP._LIBPROC_OK.__setitem__(0, self.saved[0]))

    def test_a_calibration_that_could_not_read_is_not_kept(self):
        SP._LIBPROC_OK[0] = None
        original = SP._calibrate_libproc
        try:
            SP._calibrate_libproc = lambda: None
            self.assertEqual(SP.method(platform="darwin"), "lsof")
            self.assertIsNone(SP._LIBPROC_OK[0], "an unread calibration is asked again next time")
            SP._calibrate_libproc = lambda: False
            self.assertEqual(SP.method(platform="darwin"), "lsof")
            self.assertIs(SP._LIBPROC_OK[0], False, "a layout that failed is never used again in this process")
        finally:
            SP._calibrate_libproc = original


@unittest.skipUnless(sys.platform == "darwin", "libproc and lsof are macOS's")
class Live(unittest.TestCase):
    """A real connected pair of this process: both proofs read it back, by libproc and by lsof."""

    def pair(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(4)
        client = socket.create_connection(server.getsockname(), timeout=2)
        accepted, _ = server.accept()
        self.addCleanup(lambda: [s.close() for s in (client, accepted, server)])
        return server.getsockname(), client.getsockname()[:2]

    def test_both_methods_prove_this_process_s_own_server_end(self):
        server, client = self.pair()
        for how in ("libproc", "lsof"):
            with self.subTest(how=how):
                if how == "libproc" and SP.method() != "libproc":
                    self.skipTest("libproc did not pass its calibration in this process")
                got = SP.accepted(server, client, how=how)
                self.assertEqual((got.proved, got.pid, got.method), (True, os.getpid(), how))
                got = SP.own_listener(server[1], how=how)
                self.assertEqual((got.proved, got.pid), (True, os.getpid()))

    def test_another_connection_is_not_proved(self):
        server, _client = self.pair()
        got = SP.accepted(server, ("127.0.0.1", 1), wait=True)
        self.assertFalse(got.proved)
        self.assertTrue(got.reason.startswith("table-restricted"))

    def test_a_late_accept_is_waited_for(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(4)
        client = socket.create_connection(server.getsockname(), timeout=2)
        held = []
        later = threading.Timer(0.1, lambda: held.append(server.accept()[0]))
        later.start()
        try:
            started = time.monotonic()
            got = SP.accepted(server.getsockname(), client.getsockname()[:2], wait=True)
            self.assertTrue(got.proved, got)
            self.assertLess(time.monotonic() - started, SP.TIMEOUT_SECONDS)
        finally:
            later.join()
            for s in held + [client, server]:
                s.close()


class Module(unittest.TestCase):
    def test_it_imports_no_other_kit_module(self):
        text = (SCRIPTS / "fabric_socket_proof.py").read_text(encoding="utf-8")
        self.assertNotIn("import fabric_", text)
        self.assertNotIn("from fabric_", text)

    def test_the_record_layout_is_xnu_s(self):
        self.assertEqual(SP.SOCKET_FDINFO_SIZE, 792)
        self.assertEqual(struct.calcsize("<iI"), 8)


if __name__ == "__main__":
    unittest.main()
