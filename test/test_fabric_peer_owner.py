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

SERVER = ("127.0.0.1", F.SERVER_PORT)


class FakeSocket:
    def __init__(self, name, peer):
        self.name, self.peer = name, peer

    def getsockname(self):
        return self.name

    def getpeername(self):
        return self.peer


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
        with self.table():
            owner = P.peer(FakeSocket(SERVER, ("127.0.0.1", 59999)))
        self.assertEqual((owner.kind, owner.reason), (P.UNKNOWN, "no-row"))

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


@unittest.skipUnless(sys.platform == "darwin" or sys.platform.startswith("linux"), "a POSIX socket table")
class Live(unittest.TestCase):
    """A real loopback pair in this process: both ends are this account's, on the primary method."""

    def test_both_ends_of_a_real_pair_are_this_account(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        client = socket.create_connection(listener.getsockname())
        accepted, _ = listener.accept()
        try:
            want = "sysctl" if sys.platform == "darwin" else "proc"
            self.assertEqual(P.method(), want, "the macOS record layout failed calibration on this host")
            for owner in (P.peer(accepted), P.server_end(client), P.listener(listener.getsockname()[1])):
                self.assertEqual((owner.kind, owner.uid, owner.method), (P.THIS_ACCOUNT, os.getuid(), want))
            if sys.platform == "darwin":
                self.assertEqual(P.peer(accepted).pid, os.getpid())
        finally:
            for s in (client, accepted, listener):
                s.close()

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
        # sys.stdlib_module_names is 3.10's; on the kit's 3.9 floor the module's own list stands in.
        stdlib = set(getattr(sys, "stdlib_module_names", ())) or {
            "ctypes", "http", "ipaddress", "os", "socket", "struct", "subprocess", "sys", "threading", "time", "typing"}
        self.assertTrue(names <= stdlib, names - stdlib)

    def test_the_uid_is_read_in_one_function(self):
        # The engine's OS boundary (tests/test_osprivacy.py, STANDALONE_UID) lets this vendorable file
        # read the uid itself, and only in `_posix_uid`.
        tree = ast.parse((SCRIPTS / "fabric_peer_owner.py").read_text(encoding="utf-8"))
        readers = {fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
                   for node in ast.walk(fn) if isinstance(node, ast.Attribute) and node.attr == "getuid"}
        self.assertEqual(readers, {"_posix_uid"})

    def test_names_and_version(self):
        self.assertRegex(P.PEER_OWNER_VERSION, r"^\d+\.\d+\.\d+$")
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
            with self.subTest(i=i, table=case["table"], ask=case["ask"]):
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


if __name__ == "__main__":
    unittest.main()
