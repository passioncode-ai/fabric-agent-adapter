#!/usr/bin/env python3
"""FAA-227 (DEC-0154 HA-2's server side, HA-3): the kit's LoopbackHTTPServer tells who connected before its handler
reads a byte, and closes a peer of another OS account unread. The peer's owner is faked; the connection is real."""
from __future__ import annotations

import http.client
import http.server
import importlib
import io
import pathlib
import socket
import sys
import threading
import unittest
from contextlib import redirect_stderr

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "fabric-agent-adapter" / "skills" / \
    "building-fabric-services" / "scripts"
sys.path.insert(0, str(SCRIPTS))
D = importlib.import_module("fabric_descriptor")
P = importlib.import_module("fabric_peer_owner")


def owner(kind, uid=None, pid=None, reason=None):
    return P.Owner(kind, uid, pid, "test", reason)


class Seen(http.server.BaseHTTPRequestHandler):
    calls = []

    def do_GET(self):
        Seen.calls.append(self.server.peer_owner())
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class Serving:
    def __init__(self, who, mode=None):
        reader = (lambda sock: who) if not callable(who) else who

        class Server(D.LoopbackHTTPServer):
            peer_reader = staticmethod(reader)

        self.server = Server(("127.0.0.1", 0), Seen, **({} if mode is None else {"peer_check": mode}))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        Seen.calls = []
        self.thread.start()
        return self.server

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def get(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        conn.request("GET", "/")
        return conn.getresponse().status
    finally:
        conn.close()


class Verdicts(unittest.TestCase):
    def test_refuse_closes_only_another_account(self):
        self.assertEqual(D.connection_refusal(owner(P.ANOTHER_ACCOUNT, 502)), P.ANOTHER_ACCOUNT)
        for kind in (P.THIS_ACCOUNT, P.SYSTEM, P.UNKNOWN):
            self.assertIsNone(D.connection_refusal(owner(kind)), kind)

    def test_strict_refuses_all_but_this_account_and_root(self):
        self.assertIsNone(D.connection_refusal(owner(P.THIS_ACCOUNT, 501), "strict"))
        self.assertIsNone(D.connection_refusal(owner(P.SYSTEM, 0, 1), "strict"))
        self.assertEqual(D.connection_refusal(owner(P.SYSTEM, None, 4), "strict"), P.SYSTEM)
        self.assertEqual(D.connection_refusal(owner(P.UNKNOWN, reason="table-restricted"), "strict"), "table-restricted")
        self.assertEqual(D.connection_refusal(owner(P.ANOTHER_ACCOUNT, 502), "strict"), P.ANOTHER_ACCOUNT)

    def test_off_reads_nothing_and_an_unknown_mode_is_refused(self):
        self.assertIsNone(D.connection_refusal(owner(P.ANOTHER_ACCOUNT), "off"))
        with self.assertRaises(ValueError):
            D.connection_refusal(None, "label")
        with self.assertRaises(ValueError):
            D.LoopbackHTTPServer(("127.0.0.1", 0), Seen, peer_check="maybe")


class Live(unittest.TestCase):
    def test_another_accounts_peer_is_closed_before_the_handler_runs(self):
        err = io.StringIO()
        with Serving(owner(P.ANOTHER_ACCOUNT, 502, 77)) as server, redirect_stderr(err):
            with self.assertRaises((http.client.HTTPException, ConnectionError, OSError)):
                get(server)
        self.assertEqual(Seen.calls, [])
        self.assertEqual(server.peer_refusals, 1)
        line = err.getvalue()
        self.assertIn("another-account, uid 502, pid 77", line)
        self.assertNotIn("GET", line)

    def test_this_accounts_peer_is_served_and_labelled(self):
        mine = owner(P.THIS_ACCOUNT, 501, 9)
        with Serving(mine) as server:
            self.assertEqual(get(server), 200)
        self.assertEqual(Seen.calls, [mine])
        self.assertEqual(server.peer_refusals, 0)

    def test_an_unknown_owner_is_served_by_default_and_refused_when_strict(self):
        unknown = owner(P.UNKNOWN, reason="table-restricted")
        with Serving(unknown) as server:
            self.assertEqual(get(server), 200)
        self.assertEqual(Seen.calls, [unknown])
        with redirect_stderr(io.StringIO()), Serving(unknown, "strict") as server:
            with self.assertRaises((http.client.HTTPException, ConnectionError, OSError)):
                get(server)
        self.assertEqual(Seen.calls, [])

    def test_a_reader_that_raises_is_an_unknown_owner_never_a_crash(self):
        def boom(sock):
            raise RuntimeError("table")
        with Serving(boom) as server:
            self.assertEqual(get(server), 200)
        self.assertEqual(Seen.calls[0].kind, P.UNKNOWN)
        self.assertEqual(Seen.calls[0].reason, "reader: RuntimeError")

    def test_off_never_reads_the_table(self):
        def boom(sock):
            raise AssertionError("read under off")
        with Serving(boom, "off") as server:
            self.assertEqual(get(server), 200)
        self.assertEqual(Seen.calls, [None])

    def test_the_default_reader_is_the_socket_table(self):
        # A real connection of this process: the owner the table gives is this account's, or unknown where the table is
        # restricted (an ad-hoc-signed interpreter on macOS); never another account's, so it is served either way.
        with Serving(D.LoopbackHTTPServer.peer_reader) as server:
            self.assertEqual(get(server), 200)
        self.assertIn(Seen.calls[0].kind, (P.THIS_ACCOUNT, P.UNKNOWN))


if __name__ == "__main__":
    unittest.main()
