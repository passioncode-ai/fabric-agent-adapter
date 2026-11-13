#!/usr/bin/env python3
"""fabric_peer_owner.py (FAA-226, DEC-0154 HA-2): who owns each end of a loopback connection.

Project Observatory's tests of the same file at commit f86f0622 (its `tests/test_peer_owner.py`, without the host
accounts it also covers), pointed at the kit's copy: the parsers over captured-format fixtures
(`peer_owner_fixtures.py`), the selection over a faked table, and one live case per platform over a real loopback
pair. `SharedCases` runs the questions the Node twin answers too (`test/fixtures/peer-owner/peer-owner-cases.json`).
"""
from __future__ import annotations

import ast
import http.server
import importlib
import json
import os
import pathlib
import socket
import sys
import threading
import unittest
from unittest import mock

TEST = pathlib.Path(__file__).resolve().parent
SCRIPTS = TEST.parent / "plugins" / "fabric-agent-adapter" / "skills" / "building-fabric-services" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TEST))
P = importlib.import_module("fabric_peer_owner")
import peer_owner_fixtures as F  # noqa: E402

# The tables these tests fake are not this host's: the accepted-socket proof (fabric_socket_proof, FAA-292) would read
# this host's own processes, so it is off unless a test asks for it (AcceptedSocketProof).
P._PROOF[0] = False

SERVER = ("127.0.0.1", F.SERVER_PORT)


class FakeSocket:
    def __init__(self, name, peer):
        self.name, self.peer = name, peer

    def getsockname(self):
        return self.name

    def getpeername(self):
        return self.peer


def struct_error():
    import struct
    return struct.error("unpack requires a buffer")


def ps_from_fixture(argv):
    return F.PS_UID[int(argv[-1])]


class Parsers(unittest.TestCase):
    def test_netstat_rows_with_spaced_process_names(self):
        rows = P.parse_netstat(F.NETSTAT_MULTI_ACCOUNT)
        self.assertEqual(len(rows), 9)
        client = [r for r in rows if r.local == F.OWN_CLIENT][0]
        self.assertEqual((client.pid, client.uid, client.listening), (F.OWN_CLIENT_PID, None, False))
        listeners = {r.local: r.pid for r in rows if r.listening}
        self.assertEqual(listeners, {SERVER: F.SERVER_PID, ("::1", 47070): 4400, ("127.0.0.1", 8021): 1,
                                     ("*", 47555): 300})

    def test_netstat_without_the_process_column_is_unreadable(self):
        with self.assertRaises(P.TableUnreadable):
            P.parse_netstat(F.NETSTAT_NO_PROCESS)

    def test_ps_uid(self):
        self.assertEqual(P.parse_ps_uid(F.PS_UID[F.FOREIGN_CLIENT_PID]), F.OTHER_UID)
        self.assertIsNone(P.parse_ps_uid(""))

    def test_proc_net_tcp_carries_each_rows_uid(self):
        rows = P.parse_proc_net_tcp(F.PROC_NET_TCP_MULTI, family=socket.AF_INET, byteorder="little")
        by = {(r.local, r.remote): r for r in rows}
        self.assertEqual(by[(F.FOREIGN_CLIENT, SERVER)].uid, F.OTHER_UID)
        self.assertEqual(by[(F.OWN_CLIENT, SERVER)].uid, F.OWN_UID)
        self.assertTrue(by[(SERVER, ("*", 0))].listening)
        self.assertEqual(by[(("127.0.0.1", 8021), ("*", 0))].uid, 0)

    def test_proc_net_tcp6(self):
        rows = P.parse_proc_net_tcp(F.PROC_NET_TCP6_MULTI, family=socket.AF_INET6, byteorder="little")
        self.assertIn((("::1", 50002), ("::1", F.SERVER_PORT), F.OTHER_UID),
                      [(r.local, r.remote, r.uid) for r in rows])

    def test_pcblist_n_pairs_each_socket_with_its_owner(self):
        rows = P.parse_pcblist_n(F.pcblist_n(F.PCBLIST_MULTI_ROWS))
        got = sorted((r.local, r.remote, r.uid, r.pid, r.listening, r.time_wait) for r in rows)
        want = sorted((tuple(l), ("*", 0) if r == ("*", 0) else tuple(r), u, p, r == ("*", 0), False)
                      for l, r, u, p in F.PCBLIST_MULTI_ROWS)
        self.assertEqual(got, want)

    def test_pcblist_n_reads_the_tcp_state(self):
        rows = P.parse_pcblist_n(F.pcblist_n([(F.OWN_CLIENT, SERVER, 0, 0, F.TCPS_TIME_WAIT),
                                              (("127.0.0.1", 47999), ("*", 0), 501, 9, F.TCPS_ESTABLISHED)]))
        self.assertEqual([(r.time_wait, r.listening) for r in rows], [(True, False), (False, False)])

    def test_pcblist_n_refuses_an_unknown_header(self):
        with self.assertRaises(P.TableUnreadable):
            P.parse_pcblist_n(b"\xff" * 64)

    def test_pcblist_n_refuses_a_record_past_the_end(self):
        blob = F.pcblist_n(F.PCBLIST_MULTI_ROWS[:1])
        with self.assertRaises(P.TableUnreadable):
            P.parse_pcblist_n(blob[:24 + 60])                          # the first xinpcb_n cut short

    def test_calibration_needs_the_listener_and_both_ends_exactly(self):
        rows = P.parse_pcblist_n(F.pcblist_n([(SERVER, ("*", 0), 501, 7), (SERVER, F.OWN_CLIENT, 501, 7),
                                              (F.OWN_CLIENT, SERVER, 501, 7)]))
        self.assertTrue(P.calibration_holds(rows, SERVER, F.OWN_CLIENT, uid=501, pid=7))
        self.assertFalse(P.calibration_holds(rows, SERVER, F.OWN_CLIENT, uid=501, pid=8))
        self.assertFalse(P.calibration_holds(rows[:2], SERVER, F.OWN_CLIENT, uid=501, pid=7))
        self.assertFalse(P.calibration_holds(rows + rows[2:], SERVER, F.OWN_CLIENT, uid=501, pid=7))

    def test_windows_tables(self):
        rows = P.parse_windows_tcp_table(F.windows_table(F.WINDOWS_MULTI_ROWS, socket.AF_INET), socket.AF_INET)
        self.assertEqual([(r.local, r.remote, r.listening, r.pid) for r in rows],
                         [(SERVER, ("*", 0), True, F.SERVER_PID), (SERVER, F.FOREIGN_CLIENT, False, F.SERVER_PID),
                          (F.FOREIGN_CLIENT, SERVER, False, F.FOREIGN_CLIENT_PID)])
        v6 = [(("::1", 47311), ("::", 0), True, 7), (("::1", 50003), ("::1", 47311), False, 8)]
        rows6 = P.parse_windows_tcp_table(F.windows_table(v6, socket.AF_INET6), socket.AF_INET6)
        self.assertEqual([(r.local, r.remote, r.listening, r.pid) for r in rows6],
                         [(("::1", 47311), ("*", 0), True, 7), (("::1", 50003), ("::1", 47311), False, 8)])

    def test_addresses_have_one_spelling(self):
        self.assertEqual(P.norm_host("::ffff:127.0.0.1"), "127.0.0.1")
        self.assertEqual(P.norm_host("0.0.0.0"), "*")
        self.assertEqual(P.norm_host("::"), "*")
        self.assertEqual(P.norm_host("localhost"), "127.0.0.1")


class Classification(unittest.TestCase):
    def test_pid_one_and_uid_zero_are_system(self):
        self.assertEqual(P.classify(0, 300, method="x", own_uid=501).kind, P.SYSTEM)
        self.assertEqual(P.classify(501, 1, method="x", own_uid=501).kind, P.SYSTEM)
        self.assertEqual(P.classify(501, 9, method="x", own_uid=501).kind, P.THIS_ACCOUNT)
        self.assertEqual(P.classify(502, 9, method="x", own_uid=501).kind, P.ANOTHER_ACCOUNT)

    def test_a_client_running_as_root_or_system_owns_roots_listener(self):
        """0.74.0 seam reading 2: a kit client running as root (a container's default) reads root's listener as its
        own account's; launchd's pid 1 stays system, and a user client still reads root as system."""
        self.assertEqual(P.classify(0, 300, method="x", own_uid=0).kind, P.THIS_ACCOUNT)
        self.assertEqual(P.classify(0, 1, method="x", own_uid=0).kind, P.SYSTEM)
        self.assertEqual(P.classify(0, 300, method="x", own_uid=501).kind, P.SYSTEM)
        self.assertEqual(P.classify_sid("S-1-5-18", 50, own_sid="S-1-5-18").kind, P.THIS_ACCOUNT)
        self.assertEqual(P.classify_sid("S-1-5-18", 50, own_sid="S-1-5-21-1-2-3-1001").kind, P.SYSTEM)

    def test_windows_sids(self):
        own = "S-1-5-21-1-2-3-1001"
        self.assertEqual(P.classify_sid(own, 50, own_sid=own).kind, P.THIS_ACCOUNT)
        self.assertEqual(P.classify_sid("S-1-5-21-1-2-3-1002", 50, own_sid=own).kind, P.ANOTHER_ACCOUNT)
        self.assertEqual(P.classify_sid("S-1-5-18", 50, own_sid=own).kind, P.SYSTEM)
        self.assertEqual(P.classify_sid(None, 4, own_sid=own).kind, P.SYSTEM)
        unknown = P.classify_sid(None, 50, own_sid=own)
        self.assertEqual((unknown.kind, unknown.reason), (P.UNKNOWN, "process-not-readable"))


class Selection(unittest.TestCase):
    """The question picks the right row of a table that holds both ends of every connection."""

    def table(self, text=F.NETSTAT_MULTI_ACCOUNT):
        return mock.patch.object(P, "read_table", return_value=(P.parse_netstat(text), "netstat"))

    def setUp(self):
        self.own_uid = mock.patch.object(P.os, "getuid", return_value=F.OWN_UID, create=True)
        self.own_uid.start()
        self.ps = mock.patch.object(P, "_run", side_effect=ps_from_fixture)
        self.ps.start()
        P._LISTENERS.clear()

    def tearDown(self):
        self.ps.stop()
        self.own_uid.stop()
        P._LISTENERS.clear()

    def test_peer_picks_the_client_socket(self):
        with self.table():
            foreign = P.peer(FakeSocket(SERVER, F.FOREIGN_CLIENT))
            own = P.peer(FakeSocket(SERVER, F.OWN_CLIENT))
        self.assertEqual((foreign.kind, foreign.uid, foreign.pid),
                         (P.ANOTHER_ACCOUNT, F.OTHER_UID, F.FOREIGN_CLIENT_PID))
        self.assertEqual((own.kind, own.pid), (P.THIS_ACCOUNT, F.OWN_CLIENT_PID))

    def test_server_end_picks_the_accepted_socket_not_the_listener(self):
        with self.table():
            owner = P.server_end(FakeSocket(F.FOREIGN_CLIENT, SERVER))
        self.assertEqual((owner.kind, owner.pid), (P.THIS_ACCOUNT, F.SERVER_PID))

    def test_peer_at_takes_ipv4_mapped_addresses(self):
        with self.table():
            owner = P.peer_at(("::ffff:127.0.0.1", F.SERVER_PORT, 0, 0), ("::ffff:127.0.0.1", 50002, 0, 0))
        self.assertEqual(owner.kind, P.ANOTHER_ACCOUNT)

    def test_a_time_wait_row_is_never_the_answer(self):
        with self.table(F.NETSTAT_TIME_WAIT):
            owner = P.peer(FakeSocket(SERVER, F.OWN_CLIENT))
        self.assertEqual((owner.kind, owner.pid), (P.THIS_ACCOUNT, F.OWN_CLIENT_PID))

    def test_two_live_rows_are_unknown(self):
        rows = [P.Row(F.FOREIGN_CLIENT, SERVER, False, 501, 1), P.Row(F.FOREIGN_CLIENT, SERVER, False, 502, 2)]
        with mock.patch.object(P, "read_table", return_value=(rows, "sysctl")):
            owner = P.peer(FakeSocket(SERVER, F.FOREIGN_CLIENT))
        self.assertEqual((owner.kind, owner.reason), (P.UNKNOWN, "several-rows"))

    def test_two_listeners_are_unknown(self):
        rows = [P.Row(SERVER, ("*", 0), True, 501, 1), P.Row(SERVER, ("*", 0), True, 502, 2)]
        with mock.patch.object(P, "read_table", return_value=(rows, "sysctl")):
            owner = P.listener(F.SERVER_PORT)
        self.assertEqual((owner.kind, owner.reason), (P.UNKNOWN, "several-rows"))

    def test_no_row_is_unknown(self):
        # A macOS table that lists sockets but not this connection is a restricted one (DEC-0155 RT-1, FAA-312).
        with self.table():
            owner = P.peer(FakeSocket(SERVER, ("127.0.0.1", 59999)))
        self.assertEqual((owner.kind, owner.reason), (P.UNKNOWN, P.NO_ROW_RESTRICTED))

    def test_a_proc_read_that_missed_the_row_is_read_once_more(self):
        """0.74.0 seam reading 6: a /proc read under churn can skip a row; one more read before answering unknown.
        netstat and sysctl reads are taken as they come."""
        empty = F._PROC_HEADER
        whole = F._PROC_HEADER + F._proc(0, "0100007F:B8CF", "0100007F:C351", "01", F.OWN_UID, 8001)
        reads = [(P.parse_proc_net_tcp(text, family=socket.AF_INET, byteorder="little"), "proc") for text in (empty, whole)]
        with mock.patch.object(P, "read_table", side_effect=reads) as read:
            owner = P.server_end(FakeSocket(("127.0.0.1", 50001), SERVER))
        self.assertEqual((owner.kind, read.call_count), (P.THIS_ACCOUNT, 2))
        with mock.patch.object(P, "read_table", return_value=([], "netstat")) as read:
            self.assertEqual(P.server_end(FakeSocket(("127.0.0.1", 50001), SERVER)).reason, P.NO_ROW_RESTRICTED)
        self.assertEqual(read.call_count, 1)

    def test_unreadable_table_is_unknown_with_a_reason(self):
        with mock.patch.object(P, "read_table", side_effect=P.TableUnreadable("netstat: exit 1")):
            owner = P.peer(FakeSocket(SERVER, F.FOREIGN_CLIENT))
        self.assertEqual((owner.kind, owner.reason), (P.UNKNOWN, "netstat: exit 1"))

    def test_a_gone_process_is_unknown(self):
        rows = [P.Row(F.FOREIGN_CLIENT, SERVER, False, None, 9999)]
        with mock.patch.object(P, "read_table", return_value=(rows, "netstat")):
            owner = P.peer(FakeSocket(SERVER, F.FOREIGN_CLIENT))
        self.assertEqual((owner.kind, owner.reason), (P.UNKNOWN, "process-gone"))

    def test_launchd_socket_is_system_without_a_ps(self):
        with self.table():
            owner = P.listener(8021)
        self.assertEqual(owner.kind, P.SYSTEM)

    def test_listener_prefers_the_exact_bind_then_the_wildcard_then_none(self):
        with self.table():
            self.assertEqual(P.listener(F.SERVER_PORT).pid, F.SERVER_PID)
            self.assertEqual(P.listener(47555).kind, P.SYSTEM)          # root's 0.0.0.0 listener
            self.assertEqual(P.listener(47070).kind, P.THIS_ACCOUNT)    # ::1
            self.assertEqual(P.listener(1).kind, P.NONE)

    def test_listener_is_cached_briefly(self):
        with self.table() as read:
            P.listener(F.SERVER_PORT)
            P.listener(F.SERVER_PORT)
        self.assertEqual(read.call_count, 1)


class OwnConnection(unittest.TestCase):
    """The client check: refused before a byte of the request is sent."""

    def setUp(self):
        self.received = []
        outer = self

        class Recorder(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):  # noqa: N802
                outer.received.append(self.headers.get("Authorization"))
                self.send_response(204)
                self.send_header("Connection", "close")                 # http.client reconnects by itself
                self.end_headers()
                self.close_connection = True

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def send(self, owner, expect_pid=None):
        with mock.patch.object(P, "server_end", return_value=owner):
            conn = P.own_connection(self.port, expect_pid=expect_pid, timeout=3)
        conn.request("GET", "/", headers={"Authorization": "Bearer synthetic"})
        status = conn.getresponse().status
        conn.close()
        return status

    def test_refusals_send_nothing(self):
        cases = [(P.Owner(P.ANOTHER_ACCOUNT, 502, 9, "x"), None, P.SERVER_NOT_OWN),
                 (P.Owner(P.SYSTEM, 0, 1, "x"), None, P.SERVER_NOT_OWN),
                 (P.Owner(P.UNKNOWN, None, None, "x", "no-row"), None, P.SERVER_UNVERIFIED),
                 (P.Owner(P.THIS_ACCOUNT, 501, 9, "x"), 10, P.SERVER_NOT_THIS_WORKSPACE)]
        for owner, pid, code in cases:
            with self.subTest(code=code, kind=owner.kind):
                with self.assertRaises(P.ListenerRefused) as caught:
                    self.send(owner, pid)
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.received, [])

    def test_this_accounts_server_gets_the_request(self):
        self.assertEqual(self.send(P.Owner(P.THIS_ACCOUNT, 501, 9, "x"), 9), 204)
        self.assertEqual(self.received, ["Bearer synthetic"])

    def test_the_reconnect_after_connection_close_is_checked_again(self):
        """The server answers `Connection: close`; http.client's next request opens a new connection
        by itself (auto_open), and that one reaches another account's listener: refused, unsent."""
        ends = [P.Owner(P.THIS_ACCOUNT, 501, 9, "x"), P.Owner(P.ANOTHER_ACCOUNT, 502, 10, "x")]
        with mock.patch.object(P, "server_end", side_effect=ends) as checked:
            conn = P.own_connection(self.port, timeout=3)
            conn.request("GET", "/", headers={"Authorization": "Bearer synthetic"})
            self.assertEqual(conn.getresponse().status, 204)
            with self.assertRaises(P.ListenerRefused) as caught:
                conn.request("GET", "/", headers={"Authorization": "Bearer synthetic"})
            conn.close()
        self.assertEqual(caught.exception.code, P.SERVER_NOT_OWN)
        self.assertEqual(checked.call_count, 2)
        self.assertEqual(self.received, ["Bearer synthetic"])


@unittest.skipUnless(sys.platform == "win32", "the Windows socket table")
class LiveWindows(unittest.TestCase):
    """0.74.0 seam reading 8: the iphlpapi table and the token SID on a real pair (the Windows CI job runs this file)."""

    def test_both_ends_of_a_real_pair_and_the_listener_are_this_account(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        client = socket.create_connection(listener.getsockname())
        accepted, _ = listener.accept()
        try:
            self.assertEqual(P.method(), "iphlpapi")
            for owner in (P.peer(accepted), P.server_end(client), P.listener(listener.getsockname()[1])):
                self.assertEqual((owner.kind, owner.pid, owner.method), (P.THIS_ACCOUNT, os.getpid(), "iphlpapi"))
        finally:
            for s in (accepted, client, listener):
                s.close()


@unittest.skipUnless(sys.platform == "darwin" or sys.platform.startswith("linux"), "a POSIX socket table")
class Live(unittest.TestCase):
    """A real loopback pair in this process: both ends are this account's, on the primary method."""

    def test_both_ends_of_a_real_pair_are_this_account(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        client = socket.create_connection(listener.getsockname())
        accepted, _ = listener.accept()
        self.addCleanup(P._PROOF.__setitem__, 0, False)
        P._PROOF[0] = None  # this host's own processes: a restricted table proves this pair through RT-2 (FAA-292)
        try:
            want = "sysctl" if sys.platform == "darwin" else "proc"
            if sys.platform == "darwin" and P._SYSCTL_OK[0] is not True:
                # FAA-273 item 24: a cold runner's calibration child may miss the 2 s deadline; calibrate once more with
                # room, so the test reads the layout, not the runner's load.
                with mock.patch.object(P, "TIMEOUT_SECONDS", 15.0):
                    P._SYSCTL_OK[0] = None
                    P.method()
            if sys.platform == "darwin" and P.method() != "sysctl":
                # macOS 27.2 under an ad-hoc-signed interpreter: the table is restricted, and this account's own
                # processes prove the pair (FAA-273 item 14).
                want = ("libproc", "lsof")
            else:
                self.assertEqual(P.method(), want, "the record layout failed calibration on this host")
                want = (want,)
            for owner in (P.peer(accepted), P.server_end(client), P.listener(listener.getsockname()[1])):
                self.assertEqual((owner.kind, owner.uid), (P.THIS_ACCOUNT, os.getuid()), owner)
                self.assertIn(owner.method, want)
            if sys.platform == "darwin":
                self.assertEqual(P.peer(accepted).pid, os.getpid())
        finally:
            for s in (client, accepted, listener):
                s.close()

    def test_a_connection_not_yet_accepted_reads_its_listeners_owner(self):
        """0.74.0 unit reading 3: Linux prints a connection the server has not accept()ed with uid 0 and inode 0; it
        reads as its listener's owner (this account here), never as root's."""
        if sys.platform == "darwin" and P.method() != "sysctl":
            self.skipTest("a restricted table proves an accepted socket only (DEC-0155 RT-2), and none is accepted here")
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        clients = []
        try:
            for _ in range(5):
                client = socket.create_connection(listener.getsockname())
                clients.append(client)
                owner = P.server_end(client)  # never accepted
                self.assertEqual(owner.kind, P.THIS_ACCOUNT, owner)
        finally:
            for s in clients + [listener]:
                s.close()

    @unittest.skipUnless(sys.platform == "darwin", "launchd's socket-activated listeners are macOS's")
    def test_a_real_listener_of_another_account_is_not_this_one(self):
        """The contract's conformance row asks for a listener of a second OS account; every Mac has one: launchd (pid 1,
        root) holds socket-activated ports. The first such listener on 127.0.0.1 reads system, and a refusal."""
        rows, how = P.read_table()
        held = sorted(r.local[1] for r in rows if r.listening and r.local[0] == "127.0.0.1" and r.pid == 1)
        if not held:
            self.skipTest("no launchd-held loopback listener on this Mac")
        P._LISTENERS.clear()
        owner = P.listener(held[0])
        self.assertEqual(owner.kind, P.SYSTEM)
        self.assertEqual(P.refusal(owner, held[0])[0], P.SERVER_NOT_OWN)

    @unittest.skipUnless(sys.platform == "darwin", "the fallback is macOS's")
    def test_the_netstat_fallback_agrees(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        client = socket.create_connection(listener.getsockname())
        accepted, _ = listener.accept()
        try:
            with mock.patch.object(P, "method", return_value="netstat"):
                owner = P.peer(accepted)
            self.assertEqual((owner.kind, owner.pid, owner.method), (P.THIS_ACCOUNT, os.getpid(), "netstat"))
        finally:
            for s in (client, accepted, listener):
                s.close()


class SelfContained(unittest.TestCase):
    """Other projects vendor peer_owner.py by commit: standard library only, a version in its header."""

    def test_imports_only_the_standard_library(self):
        tree = ast.parse((SCRIPTS / "fabric_peer_owner.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
        names.discard("__future__")
        # The one kit module it may ask, beside it and optional (FAA-292): without it the file stands alone.
        names.discard("fabric_socket_proof")
        self.assertIn("except ImportError:\n        _PROOF[0], proof = False, None", (SCRIPTS / "fabric_peer_owner.py").read_text())
        # sys.stdlib_module_names is 3.10's; on the kit's 3.9 floor the module's own list stands in.
        stdlib = set(getattr(sys, "stdlib_module_names", ())) or {
            "ctypes", "http", "ipaddress", "json", "os", "select", "selectors", "socket", "struct", "subprocess", "sys", "threading", "time",
            "typing"}
        self.assertTrue(names <= stdlib, names - stdlib)

    @unittest.skipIf(sys.platform == "win32", "the Windows kit sets token-file ACLs through ctypes (fabric_platform)")
    def test_the_kit_imports_without_ctypes(self):
        """0.74.0 seam reading 6: a CPython built without libffi still imports every kit module that reaches this one;
        the owner check then reads netstat on macOS, or fails closed."""
        import subprocess
        code = ("import sys; sys.modules['_ctypes'] = None; sys.path.insert(0, sys.argv[1]); "
                "import fabric_peer_owner, fabric_service, fabric_http, fabric_hub; print('ok')")
        done = subprocess.run([sys.executable, "-I", "-c", code, str(SCRIPTS)], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.stdout.strip(), "ok", done.stderr)

    def test_the_uid_is_read_in_one_function(self):
        # The engine's OS boundary (tests/test_osprivacy.py, STANDALONE_UID) lets this vendorable file
        # read the uid itself, and only in `_posix_uid`.
        tree = ast.parse((SCRIPTS / "fabric_peer_owner.py").read_text(encoding="utf-8"))
        readers = {fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
                   for node in ast.walk(fn) if isinstance(node, ast.Attribute) and node.attr == "getuid"}
        self.assertEqual(readers, {"_posix_uid"})

    def test_names_and_version(self):
        # Observatory's version with the kit's suffix: the kit's classify order and /proc reading differ (0.74.0)
        self.assertRegex(P.PEER_OWNER_VERSION, r"^\d+\.\d+\.\d+\+kit\.\d+$")
        self.assertIn(f"peer_owner {P.PEER_OWNER_VERSION}", P.__doc__)
        for name in ("listener", "server_end", "peer", "Owner", "own_connection"):
            self.assertTrue(callable(getattr(P, name)), name)
        self.assertEqual(P.KINDS, ("this-account", "another-account", "system", "unknown", "none"))


class KitInstaller(unittest.TestCase):
    """service.md's Install row (DEC-0154): the installer's poll reads a loopback well-known answer only on a connection
    whose server end is this OS account's; another account's listener is foreign-user, never this service's answer."""

    def test_the_installers_read_of_the_well_known_answer(self):
        sup = importlib.import_module("fabric_supervisors")

        class WellKnown(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = b'{"service": {"id": "example-agent", "instance": "default"}}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), WellKnown)
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        origin = "http://127.0.0.1:%d" % server.server_address[1]
        try:
            self.assertEqual(sup.fetch_well_known(origin)["service"]["id"], "example-agent")
            with mock.patch.object(P, "server_end", return_value=P.Owner(P.ANOTHER_ACCOUNT, 502, 9, "x")):
                doc, why = sup._read_well_known(origin)
                self.assertIsNone(sup.fetch_well_known(origin))
            self.assertIsNone(doc)
            self.assertRegex(why, r"^foreign-user: the server on port \d+ belongs to another-account")
        finally:
            server.shutdown()
            server.server_close()

    def test_a_loopback_origin_with_the_default_port_is_never_read_unchecked(self):
        """The 0.79.0 seam reading: an origin with no port (http's 80) or an explicit :80 goes on a checked connection in
        both twins, never through urllib."""
        sup = importlib.import_module("fabric_supervisors")
        with mock.patch.object(sup.urllib.request, "urlopen", side_effect=AssertionError("read unchecked")):
            for origin in ("http://127.0.0.1:80", "http://127.0.0.1", "http://localhost:80"):
                with self.subTest(origin=origin):
                    sup._read_well_known(origin, timeout=0.5)

    def test_every_loopback_spelling_a_url_parser_reads_takes_the_checked_path(self):
        """FAA-326: the supervisors read the kit's one loopback rule (fabric_socket_proof.loopback_host), so 127.1,
        2130706433 and a name under .localhost, which Node reads as loopback, go on a checked connection too."""
        sup = importlib.import_module("fabric_supervisors")
        hosts = []

        class Recorder:
            def __init__(self, host, port, **kw):
                hosts.append(host)

            def request(self, *a, **kw):
                raise OSError("not sent")

            def close(self):
                pass

        with mock.patch.object(sup.urllib.request, "urlopen", side_effect=AssertionError("read unchecked")), \
                mock.patch.object(sup._po, "CheckedHTTPConnection", Recorder):
            for origin in ("http://127.1:8080", "http://2130706433:8080", "http://example.localhost:8080",
                           "http://0x7f.1:8080"):
                with self.subTest(origin=origin):
                    self.assertEqual(sup._read_well_known(origin, timeout=0.5), (None, None))
        self.assertEqual(len(hosts), 4, hosts)
        with mock.patch.object(sup.urllib.request, "urlopen", side_effect=OSError("down")) as unchecked:
            sup._read_well_known("http://example.com:8080", timeout=0.5)  # not loopback: the plain way, as before
        self.assertEqual(unchecked.call_count, 1)

    def test_down_and_foreign_user_are_told_apart_at_every_loopback_spelling(self):
        """FAA-259: well_known_of answers None when nothing answers and a ForeignUserAnswer when another account's
        listener holds the port, as the Node wellKnownOf does; FAA-257: an origin spelled localhost, or another
        loopback address, is read on a checked connection too, never sent unchecked."""
        sup = importlib.import_module("fabric_supervisors")
        seen = []

        class WellKnown(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                seen.append(self.path)
                body = b'{"service": {"id": "example-agent", "instance": "default"}}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), WellKnown)
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        port = server.server_address[1]
        try:
            for origin in ("http://127.0.0.1:%d" % port, "http://localhost:%d" % port):
                with self.subTest(origin=origin):
                    self.assertEqual(sup.well_known_of(origin)["service"]["id"], "example-agent")
                    before = len(seen)
                    with mock.patch.object(P, "server_end", return_value=P.Owner(P.ANOTHER_ACCOUNT, 502, 9, "x")):
                        answer = sup.well_known_of(origin)
                    self.assertIsInstance(answer, sup.ForeignUserAnswer)
                    self.assertTrue(answer.reason.startswith("foreign-user: "), answer.reason)
                    self.assertEqual(len(seen), before, "nothing reached another account's listener")
        finally:
            server.shutdown()
            server.server_close()
        self.assertIsNone(sup.well_known_of("http://127.0.0.1:%d" % port, timeout=0.5), "down is None")
        self.assertIs(sup.ForeignUserAnswer, importlib.import_module("fabric_service").ForeignUserAnswer)
        self.assertIs(sup.well_known_of, importlib.import_module("fabric_service").well_known_of)

    def test_a_restricted_table_takes_the_installers_own_job_as_proof(self):
        """FAA-267: macOS 27.2 shows an ad-hoc-signed interpreter only its own sockets. The table's answer is
        table-restricted, never foreign-user, and the launchd job the installer started vouches with its pid."""
        sup = importlib.import_module("fabric_supervisors")

        class WellKnown(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = b'{"service": {"id": "example-agent", "instance": "default"}}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), WellKnown)
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        origin = "http://127.0.0.1:%d" % server.server_address[1]
        restricted = P.Owner(P.UNKNOWN, None, None, "netstat", P.TABLE_RESTRICTED + ": netstat printed nothing")
        try:
            with mock.patch.object(P, "server_end", return_value=restricted):
                doc, why = sup._read_well_known(origin)
                self.assertIsNone(doc)
                self.assertTrue(why.startswith(P.TABLE_RESTRICTED + ": "), why)
                with mock.patch.object(P, "pid_listens", return_value=False):
                    self.assertIsNone(sup._read_well_known(origin, vouch_pid=4242)[0])
                with mock.patch.object(P, "pid_listens", return_value=True) as listens:
                    doc, why = sup._read_well_known(origin, vouch_pid=4242)
                self.assertEqual(doc["service"]["id"], "example-agent")
                self.assertIsNone(why)
                listens.assert_called_with(4242, server.server_address[1])
            with mock.patch.object(P, "server_end", return_value=P.Owner(P.ANOTHER_ACCOUNT, 502, 9, "x")), \
                    mock.patch.object(P, "pid_listens", return_value=True):
                self.assertIsNone(sup._read_well_known(origin, vouch_pid=4242)[0], "a readable table is never overridden")
        finally:
            server.shutdown()
            server.server_close()


class WholeVouchChain(unittest.TestCase):
    """FAA-273 item 1: the installer's read of its own job's answer under a restricted table, only the table mocked: the
    real `ps` and `lsof` vouch for the pid, and the accepted-socket proof (FAA-292) proves it before any vouch."""

    def setUp(self):
        if sys.platform != "darwin" or not os.path.exists(P.LSOF):
            self.skipTest("ps and lsof on macOS")
        self.addCleanup(P._PROOF.__setitem__, 0, False)

        class WellKnown(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = b'{"service": {"id": "example-agent", "instance": "default"}}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), WellKnown)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.sup = importlib.import_module("fabric_supervisors")
        self.restricted = mock.patch.object(P, "read_table", side_effect=P.TableUnreadable(
            P.TABLE_RESTRICTED + ": netstat printed nothing to this process"))

    def test_the_vouch_reads_the_real_process(self):
        P._PROOF[0] = False
        with self.restricted:
            doc, why = self.sup._read_well_known(self.origin, timeout=5, vouch_pid=os.getpid())
            self.assertEqual((doc or {}).get("service", {}).get("id"), "example-agent", why)
            self.assertIsNone(self.sup._read_well_known(self.origin, timeout=5)[0], "no vouch, no proof: refused")
            other = __import__("subprocess").Popen(["/bin/sleep", "30"])
            try:
                doc, why = self.sup._read_well_known(self.origin, timeout=5, vouch_pid=other.pid)
            finally:
                other.kill()
                other.wait()
            self.assertIsNone(doc)
            self.assertTrue(why.startswith(P.TABLE_RESTRICTED), why)

    def test_the_accepted_socket_proves_it_before_any_vouch(self):
        P._PROOF[0] = None
        with self.restricted, mock.patch.object(P, "pid_listens", side_effect=AssertionError("no vouch needed")):
            doc, why = self.sup._read_well_known(self.origin, timeout=5, vouch_pid=4242)
        self.assertEqual((doc or {}).get("service", {}).get("id"), "example-agent", why)


class RestrictedTable(unittest.TestCase):
    """FAA-267: a socket table that shows this process alone."""

    def test_an_empty_netstat_is_table_restricted(self):
        for text in ("", "\n \n"):
            with self.assertRaises(P.TableUnreadable) as caught:
                P.parse_netstat(text)
            self.assertTrue(str(caught.exception).startswith(P.TABLE_RESTRICTED))

    def test_lsof_listeners(self):
        self.assertEqual(P.parse_lsof_listeners("p78564\nf4\nn127.0.0.1:47480\nn*:5000\nn[::1]:7\nnoise\n"),
                         [("127.0.0.1", 47480), ("*", 5000), ("::1", 7)])

    def test_only_ascii_digits_are_numbers(self):
        """FAA-273 (4): `str.isdigit` takes `٤٧٤٨٠` and `²`, which Node's [0-9] refuses; the twins read alike."""
        self.assertEqual(P.parse_lsof_listeners("n127.0.0.1:\u0664\u0667\u0664\u0668\u0660\nn*:5\u00b2\nn*:80\n"), [("*", 80)])
        self.assertIsNone(P.parse_ps_uid("\u0665\u0660\u0661"))
        self.assertIsNone(P.parse_ps_uid("\uff15\uff10\uff11"))
        self.assertEqual(P.parse_ps_uid(" 501\n"), 501)

    def test_a_header_only_netstat_is_a_restricted_table(self):
        """FAA-273 (3): the caller's own connection is in any table it can see, so a netstat with its header and no tcp
        row is the restricted table, not `no-row`."""
        header = ("Active Internet connections (including servers)\n"
                  "Proto Recv-Q Send-Q  Local Address          Foreign Address        (state)      rhiwat  shiwat    pid   epid  state  options  gencnt  flags  flags1 usscnt rtncnt fltrs process:pid\n")
        with self.assertRaises(P.TableUnreadable) as caught:
            P.parse_netstat(header)
        self.assertTrue(str(caught.exception).startswith(P.TABLE_RESTRICTED))

    def test_a_table_without_the_childs_listener_fails_calibration(self):
        # The child check runs on macOS alone; elsewhere a pipe cannot be waited on, and that proves nothing (None).
        expected = (False,) if sys.platform != "win32" else (False, None)
        with mock.patch.object(P, "TIMEOUT_SECONDS", 15.0):  # a real interpreter on a loaded host; not the deadline test
            self.assertIn(P._child_listener_seen(lambda: []), expected)
            if sys.executable:
                self.assertIn(P._child_listener_seen(lambda: [P.Row(("127.0.0.1", 1), ("*", 0), True, 501, 1, False)]),
                              expected)

    @unittest.skipIf(sys.platform == "win32", "a shell script as the interpreter")
    def test_a_child_that_never_answers_proves_nothing_and_does_not_hang(self):
        import tempfile
        import time
        with tempfile.TemporaryDirectory() as d:
            fake = os.path.join(d, "python3")
            with open(fake, "w") as f:
                f.write("#!/bin/sh\nexec sleep 30\n")
            os.chmod(fake, 0o755)
            with mock.patch.object(sys, "executable", fake), mock.patch.object(P, "TIMEOUT_SECONDS", 0.3):
                start = time.monotonic()
                self.assertIsNone(P._child_listener_seen(lambda: []))
                self.assertLess(time.monotonic() - start, 5)
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertIsNone(P._child_listener_seen(lambda: []), "a frozen host has no interpreter to start")

    @unittest.skipIf(sys.platform == "win32", "a shell script as the interpreter")
    def test_a_child_that_prints_a_partial_line_and_waits_proves_nothing_in_time(self):
        """FAA-273 item 13: readline after the first byte waited for the child's newline without a deadline; and a
        child that answered (a banner, or a port) then ignored its closed stdin got a second TIMEOUT_SECONDS."""
        import tempfile
        import time
        # (answer, expected, deadline): a no-port child must give up within its one deadline (the old code took 30 s);
        # a port-bearing child gets a wide deadline, since the fake shell can stall on a loaded host, and a late port
        # must end with the deadline (the old second wait made it 3.6 s + 6 s).
        cases = (("printf '> '", None, 3.0), ("printf 'Python banner\\n'", None, 3.0), ("printf '> '; exit 0", None, 3.0),
                 ("printf '%080d' 0", None, 3.0), ("printf '12345\\n'", False, 6.0),
                 ("sleep 3.6; printf '12345\\n'", False, 6.0))
        for answer, expected, deadline in cases:
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as d:
                fake = os.path.join(d, "python3")
                with open(fake, "w") as f:
                    f.write("#!/bin/sh\n%s\nexec sleep 30\n" % answer)
                os.chmod(fake, 0o755)
                with mock.patch.object(sys, "executable", fake), mock.patch.object(P, "TIMEOUT_SECONDS", deadline):
                    start = time.monotonic()
                    self.assertEqual(P._child_listener_seen(lambda: []), expected)
                    self.assertLess(time.monotonic() - start, deadline + 1.5, "one deadline, never a second wait")

    @unittest.skipIf(sys.platform == "win32", "a shell script as the interpreter")
    def test_a_pipe_that_cannot_be_read_and_a_table_that_fails_after_the_port(self):
        """FAA-277 item 7: `_child_line`'s read error proves nothing (None), and a table that fails once the child gave its
        port is no child seen (False); neither waits past its one deadline."""
        import tempfile
        import time
        with tempfile.TemporaryDirectory() as d:
            fake = os.path.join(d, "python3")
            with open(fake, "w") as f:
                f.write("#!/bin/sh\nprintf '12345\\n'\nexec cat >/dev/null\n")  # gone once its stdin closes
            os.chmod(fake, 0o755)
            with mock.patch.object(sys, "executable", fake), mock.patch.object(P, "TIMEOUT_SECONDS", 6.0):
                class Unreadable:  # this module's os alone: subprocess reads its own pipes with the real one
                    def __getattr__(self, name):
                        return getattr(os, name)

                    def read(self, fd, n):
                        raise OSError(5, "EIO")
                with mock.patch.object(P, "os", Unreadable()), mock.patch.object(P, "_child_line", wraps=P._child_line) as line:
                    started = time.monotonic()
                    self.assertIsNone(P._child_listener_seen(lambda: []))
                    self.assertLess(time.monotonic() - started, 7.5)
                    self.assertEqual(line.call_count, 1, "the child started and its pipe was read")
                for failure in (P.TableUnreadable("sysctl: errno 1"), OSError("EPERM"), struct_error()):
                    with self.subTest(failure=type(failure).__name__):
                        def rows_of():
                            raise failure
                        started = time.monotonic()
                        self.assertIs(P._child_listener_seen(rows_of), False)
                        self.assertLess(time.monotonic() - started, 7.5)

    @unittest.skipUnless(sys.platform == "darwin", "the child check runs on macOS")
    def test_a_process_holding_more_than_1024_files_still_sees_its_child(self):
        """FAA-273 item 11: select.select refuses an fd at or above FD_SETSIZE; the wait must not."""
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        want = 1300
        if hard != resource.RLIM_INFINITY and hard < want:
            self.skipTest("the hard limit on open files is below %d" % want)
        resource.setrlimit(resource.RLIMIT_NOFILE, (max(soft, want), hard))
        self.addCleanup(resource.setrlimit, resource.RLIMIT_NOFILE, (soft, hard))
        held = []
        try:
            while len(held) < 1100:
                held.append(os.open(os.devnull, os.O_RDONLY))
            seen = []
            with mock.patch.object(P, "TIMEOUT_SECONDS", 15.0):  # a real interpreter on a loaded host
                self.assertIsNotNone(P._child_listener_seen(lambda: seen.append(1) or []))
            self.assertEqual(seen, [1], "the child answered and the table was read")
        finally:
            for fd in held:
                os.close(fd)

    @unittest.skipUnless(sys.platform == "darwin", "sysctl on macOS")
    def test_sysctl_is_trusted_only_when_the_child_is_seen(self):
        with mock.patch.object(P, "_child_listener_seen", return_value=None):
            self.assertFalse(P._calibrate_sysctl(), "a child that could not be started proves nothing")
        with mock.patch.object(P, "_child_listener_seen", return_value=False):
            self.assertFalse(P._calibrate_sysctl())

    def test_own_connection_takes_the_vouch_as_the_node_twin_does(self):
        restricted = P.Owner(P.UNKNOWN, None, None, "netstat", P.TABLE_RESTRICTED + ": netstat printed nothing")
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(8)
        port = server.getsockname()[1]
        try:
            with mock.patch.object(P, "server_end", return_value=restricted):
                with self.assertRaises(P.ListenerRefused):
                    P.own_connection(port, timeout=2)
                with mock.patch.object(P, "pid_listens", return_value=True) as listens:
                    P.own_connection(port, timeout=2, vouch_pid=4242).close()
                listens.assert_called_with(4242, port)
        finally:
            server.close()

    @unittest.skipIf(sys.platform == "win32", "ps and lsof")
    def test_a_vouch_is_an_integer_pid_and_asks_lsof_for_ipv4_alone(self):
        for pid in ("4242", True, None, 1, 0, -5):
            self.assertFalse(P.pid_listens(pid, 80), pid)
        calls = []
        listens = {"text": "p4242\nf4\nn127.0.0.1:80\n"}

        def run(argv):
            calls.append(argv)
            return "%d\n" % os.getuid() if argv[0] == P.PS else listens["text"]

        with mock.patch.object(P, "_run", side_effect=run), mock.patch.object(P.sys, "platform", "darwin"):
            self.assertTrue(P.pid_listens(4242, 80))
            self.assertFalse(P.pid_listens(4242, 81))
            # FAA-312, DEC-0155 RT-3: only a listen on exactly 127.0.0.1 is vouched for, never the IPv4 wildcard
            # (`lsof` prints an IPv6-only wildcard as `*:<port>` too, and another account's 127.0.0.1 bind can stand
            # beside it) nor ::1.
            for text in ("p4242\nf4\nn*:80\n", "p4242\nf4\nn[::1]:80\n"):
                listens["text"] = text
                self.assertFalse(P.pid_listens(4242, 80), text)
        self.assertIn("-i4TCP", calls[-1])
        self.assertNotIn("-iTCP", calls[-1])

    @unittest.skipIf(sys.platform == "win32", "ps and lsof")
    def test_a_set_uid_reader_vouches_for_nothing(self):
        """DEC-0155: a reader whose real and effective uid differ uses none of the proofs RT-2 to RT-5."""
        run = lambda argv: "%d\n" % os.getuid() if argv[0] == P.PS else "p4242\nf4\nn127.0.0.1:80\n"  # noqa: E731
        with mock.patch.object(P, "_run", side_effect=run), mock.patch.object(P.sys, "platform", "darwin"):
            self.assertTrue(P.pid_listens(4242, 80))
            with mock.patch.object(P.os, "geteuid", return_value=os.getuid() + 1, create=True):
                self.assertFalse(P.pid_listens(4242, 80))

    def test_a_netstat_that_fails_is_a_restricted_table(self):
        """FAA-312, DEC-0155 RT-1: a netstat that exits non-zero, cannot start or times out is a restricted table, so
        its reason begins table-restricted and a caller's vouch applies; before, `netstat: exit N` skipped the vouch."""
        for failure in ("netstat: exit 1", "netstat: TimeoutExpired", "netstat: FileNotFoundError"):
            with self.subTest(failure=failure), mock.patch.object(P, "method", return_value="netstat"), \
                    mock.patch.object(P, "_run", side_effect=P.TableUnreadable(failure)):
                with self.assertRaises(P.TableUnreadable) as caught:
                    P.read_table()
                self.assertEqual(str(caught.exception), "%s: %s" % (P.TABLE_RESTRICTED, failure))
                P._LISTENERS.clear()
                owner = P.listener(47311)
                self.assertEqual((owner.kind, owner.reason), (P.UNKNOWN, "%s: %s" % (P.TABLE_RESTRICTED, failure)))
                self.assertEqual(P.server_end(FakeSocket(F.OWN_CLIENT, SERVER)).reason, owner.reason)
        P._LISTENERS.clear()

    def test_a_table_of_this_account_alone_is_restricted(self):
        """FAA-312, DEC-0155 RT-1: a macOS table holding no row of another uid (sysctl) or of another process (netstat)
        proves nothing by a missing row. Linux and Windows carry the owner on each row and are never read so."""
        own = [P.Row(SERVER, ("*", 0), True, 501, 4100), P.Row(F.OWN_CLIENT, SERVER, False, 501, 4300)]
        other_uid = own + [P.Row(("127.0.0.1", 8021), ("*", 0), True, 0, 1)]
        self.assertTrue(P.restricted(own, "sysctl", own_uid=501))
        self.assertFalse(P.restricted(other_uid, "sysctl", own_uid=501))
        self.assertTrue(P.restricted([], "sysctl", own_uid=501))
        self.assertTrue(P.restricted([P.Row(SERVER, ("*", 0), True, None, 77)], "netstat", own_pid=77))
        self.assertFalse(P.restricted([P.Row(SERVER, ("*", 0), True, None, 78)], "netstat", own_pid=77))
        self.assertTrue(P.restricted([P.Row(SERVER, ("*", 0), True, None, None)], "netstat", own_pid=77))
        self.assertTrue(P.restricted([], "netstat", own_pid=77))
        for how in ("proc", "iphlpapi", "netstat-windows", "none"):
            self.assertFalse(P.restricted([], how, own_uid=501, own_pid=77), how)

    def test_under_a_restricted_table_only_an_exact_127_0_0_1_listener_of_this_account_counts(self):
        """FAA-312, DEC-0155 RT-4: under a restricted table this account's wildcard or ::1 listener, and a port with no
        row, read as table-restricted; its own bind on exactly 127.0.0.1 is its own."""
        rows = [P.Row(SERVER, ("*", 0), True, 501, 4100), P.Row(("*", 47555), ("*", 0), True, 501, 4100),
                P.Row(("::1", 47070), ("*", 0), True, 501, 4100)]
        with mock.patch.object(P.os, "getuid", return_value=501, create=True), \
                mock.patch.object(P, "read_table", return_value=(rows, "sysctl")):
            P._LISTENERS.clear()
            self.assertEqual((P.listener(F.SERVER_PORT).kind, P.listener(F.SERVER_PORT).pid), (P.THIS_ACCOUNT, 4100))
            for port in (47555, 47070, 1):
                owner = P.listener(port)
                self.assertEqual(owner.kind, P.UNKNOWN, port)
                self.assertTrue(owner.reason.startswith(P.TABLE_RESTRICTED + ": "), owner.reason)
            # the same rows beside another uid's: a readable table decides, as before
            with mock.patch.object(P, "read_table", return_value=(rows + [P.Row(("127.0.0.1", 8021), ("*", 0), True, 0, 1)],
                                                                    "sysctl")):
                P._LISTENERS.clear()
                self.assertEqual(P.listener(47555).kind, P.THIS_ACCOUNT)
                self.assertEqual(P.listener(1).kind, P.NONE)
        P._LISTENERS.clear()

    def test_a_missing_row_in_a_macos_table_is_restricted(self):
        """FAA-312, DEC-0155 RT-1: a macOS table that lists sockets but not the reader's own connection proves nothing;
        on Linux the reason stays no-row."""
        rows = [P.Row(SERVER, ("*", 0), True, 502, 4100), P.Row(("127.0.0.1", 8021), ("*", 0), True, 0, 1)]
        for how in ("sysctl", "netstat"):
            with mock.patch.object(P, "read_table", return_value=(rows, how)):
                owner = P.server_end(FakeSocket(F.OWN_CLIENT, SERVER))
            self.assertEqual((owner.kind, owner.reason), (P.UNKNOWN, P.NO_ROW_RESTRICTED), how)
            self.assertTrue(P.NO_ROW_RESTRICTED.startswith(P.TABLE_RESTRICTED + ": "))
        with mock.patch.object(P, "read_table", return_value=(rows, "proc")):
            self.assertEqual(P.server_end(FakeSocket(F.OWN_CLIENT, SERVER)).reason, "no-row")

    def test_the_cli_prints_the_listeners_kind(self):
        """FAA-315: `fabric_peer_owner.py listener <port>` prints the kind the dashboard link gate takes as
        listener_owner, and the owner as JSON with --json; a bad port is a usage error."""
        import contextlib
        import io
        mine = P.Owner(P.THIS_ACCOUNT, 501, 4100, "sysctl")
        for argv, owner, want, code in ((["listener", "47311"], mine, "this-account\n", 0),
                                        (["listener", "1"], P.Owner(P.NONE, None, None, "sysctl"), "none\n", 0),
                                        (["listener", "47311", "--json"], mine, None, 0)):
            out = io.StringIO()
            with self.subTest(argv=argv), mock.patch.object(P, "listener", return_value=owner) as asked, \
                    contextlib.redirect_stdout(out):
                self.assertEqual(P.main(argv), code)
                asked.assert_called_once_with(int(argv[1]))
            if want is not None:
                self.assertEqual(out.getvalue(), want)
            else:
                self.assertEqual(json.loads(out.getvalue()), {"kind": "this-account", "uid": 501, "pid": 4100,
                                                              "method": "sysctl", "reason": None})
        for argv in ([], ["listener"], ["listener", "x"], ["listener", "0"], ["listener", "65536"], ["peer", "1"]):
            err = io.StringIO()
            with self.subTest(argv=argv), contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(P.main(argv), 2)
            self.assertIn("usage", err.getvalue())

    def test_the_cli_runs_as_a_script(self):
        import subprocess
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        try:
            done = subprocess.run([sys.executable, str(SCRIPTS / "fabric_peer_owner.py"), "listener",
                                   str(sock.getsockname()[1])], capture_output=True, text=True, timeout=60)
        finally:
            sock.close()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(done.stdout.strip(), P.KINDS)
        if sys.platform.startswith("linux") or sys.platform == "win32":
            self.assertEqual(done.stdout.strip(), P.THIS_ACCOUNT)

    @unittest.skipIf(sys.platform == "win32", "launchd")
    def test_launchd_pid(self):
        import subprocess
        sup = importlib.import_module("fabric_supervisors")
        done = lambda code, out: subprocess.CompletedProcess(["launchctl"], code, out, "")  # noqa: E731
        with mock.patch.object(sup, "_launchctl", return_value=done(0, "gui/501/a.b = {\n\tstate = running\n\tpid = 4242\n}\n")):
            self.assertEqual(sup.launchd_pid("a.b"), 4242)
        with mock.patch.object(sup, "_launchctl", return_value=done(0, "gui/501/a.b = {\n\tstate = waiting\n}\n")):
            self.assertIsNone(sup.launchd_pid("a.b"))
        with mock.patch.object(sup, "_launchctl", return_value=done(113, "")):
            self.assertIsNone(sup.launchd_pid("a.b"))
        # FAA-273 (2) and (4): a launchctl that hangs is a pid not read, never a TimeoutExpired out of an install's
        # poll; a pid in other digits is no pid, as Node's [0-9] reads it.
        with mock.patch.object(sup, "_launchctl", side_effect=subprocess.TimeoutExpired(["launchctl"], 30)):
            self.assertIsNone(sup.launchd_pid("a.b"))
        with mock.patch.object(sup, "_launchctl", return_value=done(0, "gui/501/a.b = {\n\tpid = \u0664\u0662\n}\n")):
            self.assertIsNone(sup.launchd_pid("a.b"))

    @unittest.skipUnless(sys.platform == "darwin" and os.path.exists(P.LSOF), "lsof on macOS")
    def test_pid_listens_on_a_real_child(self):
        import subprocess
        child = subprocess.Popen([sys.executable, "-I", "-c", P._CHILD_LISTENER], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE)
        try:
            port = int(child.stdout.readline())
            self.assertTrue(P.pid_listens(child.pid, port))
            self.assertFalse(P.pid_listens(child.pid, port + 1 if port < 65535 else port - 1))
            self.assertFalse(P.pid_listens(1, port))
        finally:
            child.stdin.close()
            child.wait(timeout=5)
            child.stdout.close()


class SharedCases(unittest.TestCase):
    """The questions both twins answer over the same tables (the Node twin: test/fabric-peer-owner.test.mjs)."""

    CASES = json.loads((TEST / "fixtures" / "peer-owner" / "peer-owner-cases.json").read_text(encoding="utf-8"))

    def rows(self, table):
        kind, text = table["kind"], table["text"]
        if kind == "netstat":
            return P.parse_netstat(text), "netstat"
        family = socket.AF_INET if kind == "proc4" else socket.AF_INET6
        return P.parse_proc_net_tcp(text, family=family, byteorder="little"), "proc"

    def setUp(self):
        self.own_uid = mock.patch.object(P.os, "getuid", return_value=self.CASES["ownUid"], create=True)
        self.own_uid.start()
        self.ps = mock.patch.object(P, "_run", side_effect=lambda argv: self.CASES["ps"][argv[-1]])
        self.ps.start()
        P._LISTENERS.clear()

    def tearDown(self):
        self.ps.stop()
        self.own_uid.stop()
        P._LISTENERS.clear()

    def test_every_shared_case(self):
        ran = 0
        for i, case in enumerate(self.CASES["cases"]):
            if "python" not in case.get("twins", ["python", "node"]):
                continue
            table = self.CASES["tables"][case["table"]]
            with self.subTest(i=i, table=case["table"], ask=case["ask"]), \
                    mock.patch.object(P.os, "getuid", return_value=case.get("ownUid", self.CASES["ownUid"]), create=True), \
                    mock.patch.object(P.os, "getpid", return_value=case.get("ownPid", os.getpid())):
                P._LISTENERS.clear()
                try:
                    read = mock.patch.object(P, "read_table", return_value=self.rows(table))
                except P.TableUnreadable as exc:
                    read = mock.patch.object(P, "read_table", side_effect=P.TableUnreadable(str(exc)))
                with read:
                    if case["ask"] == "listener":
                        got = P.listener(case["port"])
                    elif case["ask"] == "peerAt":
                        got = P.peer_at(tuple(case["server"]), tuple(case["client"]))
                    else:
                        got = P.server_end(FakeSocket(tuple(case["client"]), tuple(case["server"])))
                self.assertEqual({k: getattr(got, k) for k in case["want"]}, case["want"])
                ran += 1
        self.assertGreaterEqual(ran, 18)

    def test_addresses_have_the_same_spelling_in_both_twins(self):
        for raw, want in self.CASES["normHost"]:
            with self.subTest(raw=raw):
                self.assertEqual(P.norm_host(raw), want)



class FakeProof:
    """A fabric_socket_proof that answers what a test says and records what it was asked."""

    def __init__(self, proved=True, pid=4100, method="libproc", reason=None):
        self.answer, self.asked = (proved, pid, method, reason), []

    def _proof(self, *args, **kwargs):
        return importlib.import_module("fabric_socket_proof").Proof(*self.answer)

    def accepted(self, *args, **kwargs):
        self.asked.append(("accepted", args, kwargs))
        return self._proof()

    def own_listener(self, *args, **kwargs):
        self.asked.append(("own_listener", args, kwargs))
        return self._proof()


class AcceptedSocketProof(unittest.TestCase):
    """FAA-292 (DEC-0155 RT-2) and FAA-272: on a restricted macOS table, the server end or listener this account's own
    processes hold is this account's; anything else keeps the table's answer, and without fabric_socket_proof beside it
    the file answers as before."""

    RESTRICTED = P.TableUnreadable(P.TABLE_RESTRICTED + ": netstat printed nothing to this process")

    def setUp(self):
        P._LISTENERS.clear()
        self.addCleanup(P._LISTENERS.clear)
        self.addCleanup(P._PROOF.__setitem__, 0, False)

    def ask(self, proof, question, platform="darwin", table=None):
        P._PROOF[0] = proof
        read = mock.patch.object(P, "read_table", side_effect=table or self.RESTRICTED)
        with read, mock.patch.object(P.sys, "platform", platform), mock.patch.object(P, "method", return_value="netstat"):
            return question()

    def test_a_server_end_held_by_this_account_s_process_is_this_account_s(self):
        proof = FakeProof()
        got = self.ask(proof, lambda: P.server_end(FakeSocket(("127.0.0.1", 50001), SERVER)))
        self.assertEqual((got.kind, got.pid, got.method, got.reason), (P.THIS_ACCOUNT, 4100, "libproc", None))
        self.assertEqual(proof.asked, [("accepted", (SERVER, ("127.0.0.1", 50001)), {"wait": True})])

    def test_a_peer_and_a_listener_are_proved_the_same_way(self):
        proof = FakeProof(pid=None, reason="several-processes")
        got = self.ask(proof, lambda: P.peer_at(SERVER, ("127.0.0.1", 50001)))
        self.assertEqual((got.kind, got.pid, got.reason), (P.THIS_ACCOUNT, None, "several-processes"))
        got = self.ask(proof, lambda: P.listener(F.SERVER_PORT))
        self.assertEqual(got.kind, P.THIS_ACCOUNT)
        self.assertEqual([q[0] for q in proof.asked], ["accepted", "own_listener"])
        self.assertEqual(proof.asked[0][1:], ((("127.0.0.1", 50001), SERVER), {"wait": False}))

    def test_nothing_proved_keeps_the_restricted_answer(self):
        got = self.ask(FakeProof(proved=False, pid=None, reason=P.TABLE_RESTRICTED),
                       lambda: P.server_end(FakeSocket(("127.0.0.1", 50001), SERVER)))
        self.assertEqual((got.kind, got.reason), (P.UNKNOWN, str(self.RESTRICTED)))

    def test_without_the_module_the_file_stands_alone(self):
        got = self.ask(False, lambda: P.server_end(FakeSocket(("127.0.0.1", 50001), SERVER)))
        self.assertEqual((got.kind, got.reason), (P.UNKNOWN, str(self.RESTRICTED)))

    def test_it_is_asked_only_about_a_restricted_macos_table(self):
        proof = FakeProof()
        for platform, table in (("linux", self.RESTRICTED), ("darwin", P.TableUnreadable("proc: PermissionError"))):
            got = self.ask(proof, lambda: P.server_end(FakeSocket(("127.0.0.1", 50001), SERVER)), platform, table)
            self.assertEqual(got.kind, P.UNKNOWN)
        self.assertEqual(proof.asked, [])

    def test_a_proof_that_raises_keeps_the_restricted_answer(self):
        class Broken(FakeProof):
            def accepted(self, *args, **kwargs):
                raise RuntimeError("boom")
        got = self.ask(Broken(), lambda: P.server_end(FakeSocket(("127.0.0.1", 50001), SERVER)))
        self.assertEqual(got.kind, P.UNKNOWN)

    def test_the_proof_comes_before_the_vouch(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(8)
        self.addCleanup(server.close)
        P._PROOF[0] = FakeProof(pid=None, reason="several-processes")
        with mock.patch.object(P, "read_table", side_effect=self.RESTRICTED), \
                mock.patch.object(P.sys, "platform", "darwin"), mock.patch.object(P, "method", return_value="netstat"), \
                mock.patch.object(P, "pid_listens", return_value=False) as listens:
            P.own_connection(server.getsockname()[1], timeout=2, vouch_pid=4242).close()
        listens.assert_not_called()

    def test_the_module_is_found_beside_this_file(self):
        P._PROOF[0] = None
        with mock.patch.object(P.sys, "platform", "linux"):  # not asked: only found
            P._proved("accepted", SERVER, SERVER, fallback=P.Owner(P.UNKNOWN, None, None, "netstat", P.TABLE_RESTRICTED))
        self.assertIsNone(P._PROOF[0], "found lazily, only for a restricted macOS answer")
        with mock.patch.object(P.sys, "platform", "darwin"):
            P._proved("own_listener", 1, fallback=P.Owner(P.UNKNOWN, None, None, "netstat", P.TABLE_RESTRICTED))
        self.assertEqual(getattr(P._PROOF[0], "__name__", None), "fabric_socket_proof")

    def test_the_sibling_is_loaded_by_path_and_sys_path_is_unchanged(self):
        """FAA-327: a forced restricted read loads fabric_socket_proof beside this file by its path: sys.path stays as
        it was, and a module of the same name elsewhere (first in sys.modules or on sys.path) is never the one asked."""
        import types
        P._PROOF[0] = None
        before = list(sys.path)
        foreign = types.ModuleType("fabric_socket_proof")
        foreign.__file__ = str(TEST / "elsewhere" / "fabric_socket_proof.py")
        foreign.accepted = foreign.own_listener = mock.Mock(side_effect=AssertionError("a foreign module was asked"))
        restricted = P.Owner(P.UNKNOWN, None, None, "netstat", P.TABLE_RESTRICTED)
        with mock.patch.dict(sys.modules, {"fabric_socket_proof": foreign}), mock.patch.object(P.sys, "platform", "darwin"), \
                mock.patch.object(P.sys, "path", list(sys.path)) as path:
            P._proved("own_listener", 1, fallback=restricted)
            self.assertEqual(path, before, "sys.path untouched")
        self.assertEqual(sys.path, before)
        self.assertEqual(os.path.abspath(P._PROOF[0].__file__), str(SCRIPTS / "fabric_socket_proof.py"))
        self.assertIsNot(P._PROOF[0], foreign)

    def test_vendored_alone_the_table_answer_stands(self):
        """FAA-327: a fabric_peer_owner.py copied with no fabric_socket_proof beside it asks nothing and keeps the
        restricted answer, sys.path untouched, as before."""
        import importlib.util
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            alone = os.path.join(tmp, "peer_owner_alone.py")
            shutil.copy(SCRIPTS / "fabric_peer_owner.py", alone)
            spec = importlib.util.spec_from_file_location("peer_owner_alone", alone)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            before = list(sys.path)
            restricted = module.Owner(module.UNKNOWN, None, None, "netstat", module.TABLE_RESTRICTED)
            with mock.patch.object(module.sys, "platform", "darwin"):
                self.assertEqual(module._proved("own_listener", 1, fallback=restricted), restricted)
            self.assertIs(module._PROOF[0], False)
            self.assertEqual(sys.path, before)

    @unittest.skipUnless(sys.platform == "darwin", "this account's own processes, through libproc or lsof")
    def test_live_a_restricted_table_still_proves_this_process_s_own_server(self):
        """FAA-273 item 14: a listener in the caller's own process is proved again under a restricted table."""
        P._PROOF[0] = None
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(8)
        self.addCleanup(server.close)
        taken = []
        accepting = threading.Thread(target=lambda: taken.append(server.accept()[0]))
        accepting.start()
        try:
            with mock.patch.object(P, "read_table", side_effect=self.RESTRICTED):
                conn = P.own_connection(server.getsockname()[1], timeout=2)
                conn.close()
                self.assertEqual(P.listener(server.getsockname()[1]).kind, P.THIS_ACCOUNT)
        finally:
            accepting.join(5)
            for s in taken:
                s.close()


class VouchAddressFamily(unittest.TestCase):
    """FAA-273 item 12: the vouch proves a listener on exactly 127.0.0.1, so it is taken only for a connection that
    reached 127.0.0.1; one a caller spelled `::1` or `localhost` that reached ::1 is never vouched for."""

    def test_a_connection_to_ipv6_loopback_is_never_vouched_for(self):
        try:
            server = socket.socket(socket.AF_INET6)
            server.bind(("::1", 0))
        except OSError:
            self.skipTest("no IPv6 loopback on this host")
        server.listen(8)
        self.addCleanup(server.close)
        restricted = P.Owner(P.UNKNOWN, None, None, "netstat", P.TABLE_RESTRICTED + ": netstat printed nothing")
        with mock.patch.object(P, "server_end", return_value=restricted), \
                mock.patch.object(P, "pid_listens", return_value=True) as listens:
            with self.assertRaises(P.ListenerRefused):
                P.own_connection(server.getsockname()[1], host="::1", timeout=2, vouch_pid=4242)
        listens.assert_not_called()


class PidListensOwner(unittest.TestCase):
    """FAA-286 (1): one lsof reader for the vouch and the LaunchDaemon's job, with an owner parameter."""

    @unittest.skipIf(sys.platform == "win32", "ps and lsof")
    def test_the_owner_is_this_account_by_default_another_uid_or_none(self):
        uids = {"4242": os.getuid(), "4343": 0}

        def run(argv):
            return "%d\n" % uids[argv[-1]] if argv[0] == P.PS else "p%s\nf4\nn127.0.0.1:80\n" % argv[4]
        with mock.patch.object(P, "_run", side_effect=run), mock.patch.object(P.sys, "platform", "darwin"):
            self.assertTrue(P.pid_listens(4242, 80))
            self.assertFalse(P.pid_listens(4343, 80), "root's job is not this account's")
            self.assertTrue(P.pid_listens(4343, 80, owner=0))
            self.assertFalse(P.pid_listens(4242, 80, owner=0))
            self.assertTrue(P.pid_listens(4343, 80, owner=None), "the caller checks the uid itself")
            self.assertFalse(P.pid_listens(4343, 81, owner=None))
        for bad in ("0", True, -1, 1.5):
            with self.assertRaises(ValueError):
                P.pid_listens(4242, 80, owner=bad)


if __name__ == "__main__":
    unittest.main()
