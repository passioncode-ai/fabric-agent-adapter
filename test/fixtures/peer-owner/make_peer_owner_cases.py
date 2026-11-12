#!/usr/bin/env python3
"""Write `peer-owner-cases.json`: the socket tables and questions both twins of fabric_peer_owner answer (FAA-226).

The macOS netstat and Linux /proc tables come from `test/peer_owner_fixtures.py` (Project Observatory's fixtures,
vendored by commit); the Windows `netstat -ano`, `whoami /user` and owner-SID texts are written here, with their state column
localized in one table to show it is not read. Every expectation is stated by hand, never computed by the code under
test. Run from the repository root: `python3 test/fixtures/peer-owner/make_peer_owner_cases.py`.
"""
import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
F = importlib.import_module("peer_owner_fixtures")

SERVER = ["127.0.0.1", F.SERVER_PORT]

# /proc rows of a connection the server has not accept()ed yet: Linux prints its server end with uid 0 and inode 0
# (0.74.0 unit reading 3, measured on Linux 6.8). 47311 is B8CF, 50001 C351.
_HEAD = F._PROC_HEADER


def _unaccepted(listener_uid):
    return _HEAD + "".join((
        F._proc(0, "0100007F:B8CF", "00000000:0000", "0A", listener_uid, 3001),
        F._proc(1, "0100007F:B8CF", "0100007F:C351", "01", 0, 0),
        F._proc(2, "0100007F:C351", "0100007F:B8CF", "01", F.OWN_UID, 3003),
    ))


# A closed client whose row has inode 0, from a port an own listener holds on [::] (V6ONLY): the server asking `peer`
# must never read it as that listener's owner (0.74.0 unit reading 4). 50001 is C351; ::0 is all zero.
CLOSED_CLIENT = _HEAD + "".join((
    F._proc(0, "0100007F:B8CF", "00000000:0000", "0A", F.OWN_UID, 5001),
    F._proc(1, "0100007F:B8CF", "0100007F:C351", "01", F.OWN_UID, 5002),
    F._proc(2, "0100007F:C351", "0100007F:B8CF", "08", 0, 0),
    F._proc(3, "0100007F:C351", "00000000:0000", "0A", F.OWN_UID, 5004),
))

# A client another account accepted while our service was down, the listener since swapped back to ours: the accepted
# row (inode set) carries the other account's uid, and that answers, never the listener (board thread ced00f6e).
SWAPPED_LISTENER = _HEAD + "".join((
    F._proc(0, "0100007F:B8CF", "00000000:0000", "0A", F.OWN_UID, 6001),
    F._proc(1, "0100007F:B8CF", "0100007F:C351", "01", F.OTHER_UID, 6002),
    F._proc(2, "0100007F:C351", "0100007F:B8CF", "01", F.OWN_UID, 6003),
))

# A /proc read under churn that printed the accepted server row and the client row twice (Linux resumes a seq_file read
# by position; 0.74.0 seam reading 6): one socket each, so this account's, never several-rows. The same 4-tuple with two
# different owners stays unknown.
PRINTED_TWICE = _HEAD + "".join((
    F._proc(0, "0100007F:B8CF", "00000000:0000", "0A", F.OWN_UID, 7001),
    F._proc(1, "0100007F:B8CF", "0100007F:C351", "01", F.OWN_UID, 7002),
    F._proc(2, "0100007F:C351", "0100007F:B8CF", "01", F.OWN_UID, 7003),
    F._proc(3, "0100007F:B8CF", "0100007F:C351", "01", F.OWN_UID, 7002),
    F._proc(4, "0100007F:C351", "0100007F:B8CF", "01", F.OWN_UID, 7003),
))
TWO_OWNERS_ONE_TUPLE = _HEAD + "".join((
    F._proc(0, "0100007F:B8CF", "00000000:0000", "0A", F.OWN_UID, 7101),
    F._proc(1, "0100007F:B8CF", "0100007F:C351", "01", F.OWN_UID, 7102),
    F._proc(2, "0100007F:B8CF", "0100007F:C351", "01", F.OTHER_UID, 7104),
))

# A connection not accept()ed yet whose listener is gone: unknown, not-accepted.
NO_LISTENER = _HEAD + F._proc(0, "0100007F:B8CF", "0100007F:C351", "01", 0, 0)


def _two_listeners(uids):
    return _HEAD + "".join(F._proc(i, "0100007F:B8CF", "00000000:0000", "0A", uid, 4001 + i) for i, uid in enumerate(uids))
#: The reasons of a restricted table (DEC-0155 RT-1, RT-4; FAA-312), stated here, never read from the code.
NO_ROW_RESTRICTED = "table-restricted: no row for this connection"


def restricted_listener(port):
    return "table-restricted: no listener of this account on exactly 127.0.0.1:%d" % port


# A netstat whose every row is one process's (pid 4100): its listener on 127.0.0.1:47311 and a connection to it from
# itself, its wildcard on 47555 and its ::1 on 47070.
NETSTAT_OWN_ONLY = F.NETSTAT_HEADER + "".join((
    F._ns("tcp4", "127.0.0.1.47311", "*.*", "LISTEN", "Python:%d" % F.SERVER_PID),
    F._ns("tcp4", "127.0.0.1.47311", "127.0.0.1.50001", "ESTABLISHED", "Python:%d" % F.SERVER_PID),
    F._ns("tcp4", "127.0.0.1.50001", "127.0.0.1.47311", "ESTABLISHED", "Python:%d" % F.SERVER_PID),
    F._ns("tcp4", "*.47555", "*.*", "LISTEN", "Python:%d" % F.SERVER_PID),
    F._ns("tcp6", "::1.47070", "*.*", "LISTEN", "Python:%d" % F.SERVER_PID),
))

OWN = list(F.OWN_CLIENT)
FOREIGN = list(F.FOREIGN_CLIENT)

WINDOWS_HEAD = "\nActive Connections\n\n  Proto  Local Address          Foreign Address        State           PID\n"


def win(rows, states):
    return WINDOWS_HEAD + "".join("  TCP    %-22s %-22s %-15s %s\n" % (local, remote, states.get(state, state), pid)
                                  for local, remote, state, pid in rows)


WINDOWS_ROWS = [
    ("127.0.0.1:47311", "0.0.0.0:0", "LISTENING", 4100),
    ("127.0.0.1:47311", "127.0.0.1:50001", "ESTABLISHED", 4100),
    ("127.0.0.1:50001", "127.0.0.1:47311", "ESTABLISHED", 4300),
    ("127.0.0.1:47311", "127.0.0.1:50002", "ESTABLISHED", 4100),
    ("127.0.0.1:50002", "127.0.0.1:47311", "ESTABLISHED", 5200),
    ("127.0.0.1:47311", "127.0.0.1:50004", "ESTABLISHED", 4100),
    ("127.0.0.1:50004", "127.0.0.1:47311", "ESTABLISHED", 6200),
    ("127.0.0.1:50003", "127.0.0.1:47311", "TIME_WAIT", 0),
    ("0.0.0.0:445", "0.0.0.0:0", "LISTENING", 4),
    ("[::1]:47070", "[::]:0", "LISTENING", 4400),
]
GERMAN = {"LISTENING": "ABHÖREN", "ESTABLISHED": "HERGESTELLT", "TIME_WAIT": "WARTEND"}


OWN_SID = "S-1-5-21-1004336348-1177238915-682003330-1001"
OTHER_SID = "S-1-5-21-1004336348-1177238915-682003330-1002"


cases = {
    "about": "FAA-226: socket tables and the owner each question reads, for fabric_peer_owner.py and "
             "fabric-peer-owner.mjs. Written by make_peer_owner_cases.py; regenerate, never edit.",
    "ownUid": F.OWN_UID,
    # whoami /user /fo csv /nh, its name in the console's code page as a UTF-8 reader sees it (never compared)
    "whoami": '"example-pc\\\ufffd\ufffd\ufffd\ufffd","%s"\r\n' % OWN_SID,
    "tables": {
        "netstatMulti": {"kind": "netstat", "text": F.NETSTAT_MULTI_ACCOUNT},
        "netstatTimeWait": {"kind": "netstat", "text": F.NETSTAT_TIME_WAIT},
        "netstatOwnOnly": {"kind": "netstat", "text": NETSTAT_OWN_ONLY},
        "netstatNoProcess": {"kind": "netstat", "text": F.NETSTAT_NO_PROCESS},
        "procMulti": {"kind": "proc4", "text": F.PROC_NET_TCP_MULTI},
        "procUnacceptedOwn": {"kind": "proc4", "text": _unaccepted(F.OWN_UID)},
        "procUnacceptedOther": {"kind": "proc4", "text": _unaccepted(F.OTHER_UID)},
        "procTwoListenersOneOwner": {"kind": "proc4", "text": _two_listeners([F.OWN_UID, F.OWN_UID])},
        "procClosedClient": {"kind": "proc4", "text": CLOSED_CLIENT},
        "procNoListener": {"kind": "proc4", "text": NO_LISTENER},
        "procSwappedListener": {"kind": "proc4", "text": SWAPPED_LISTENER},
        "procPrintedTwice": {"kind": "proc4", "text": PRINTED_TWICE},
        "procTwoOwnersOneTuple": {"kind": "proc4", "text": TWO_OWNERS_ONE_TUPLE},
        "procTwoListenersTwoOwners": {"kind": "proc4", "text": _two_listeners([F.OWN_UID, F.OTHER_UID])},
        "proc6Multi": {"kind": "proc6", "text": F.PROC_NET_TCP6_MULTI},
        "windowsMulti": {"kind": "windows", "text": win(WINDOWS_ROWS, {})},
        "windowsGerman": {"kind": "windows", "text": win(WINDOWS_ROWS, GERMAN)},
    },
    "ps": {str(pid): text for pid, text in F.PS_UID.items()},
    # what the owner-SID PowerShell prints per pid: a SID, or nothing for a process it cannot open
    "ownerSid": {"4100": OWN_SID + "\r\n", "4300": OWN_SID + "\r\n", "4400": OWN_SID + "\r\n", "5200": "",
                 "6200": OTHER_SID + "\r\n"},
    "normHost": [["::ffff:127.0.0.1", "127.0.0.1"], ["0.0.0.0", "*"], ["::", "*"], ["localhost", "127.0.0.1"],
                 ["*", "*"], ["::1", "::1"], ["0:0:0:0:0:0:0:1", "::1"], ["[::1]", "[::1]"], ["fe80::1%en0", "fe80::1"],
                 ["127.0.0.1", "127.0.0.1"], ["example.test", "example.test"], ["::ffff:0.0.0.0", "*"]],
    "cases": [
        {"table": "netstatMulti", "ask": "listener", "port": F.SERVER_PORT,
         "want": {"kind": "this-account", "pid": F.SERVER_PID}},
        {"table": "netstatMulti", "ask": "listener", "port": 8021, "want": {"kind": "system", "pid": 1}},
        {"table": "netstatMulti", "ask": "listener", "port": 47555, "want": {"kind": "system", "pid": 300}},
        {"table": "netstatMulti", "ask": "listener", "port": 47070, "want": {"kind": "this-account", "pid": 4400}},
        {"table": "netstatMulti", "ask": "listener", "port": 1, "want": {"kind": "none"}},
        {"table": "netstatMulti", "ask": "peerAt", "server": SERVER, "client": FOREIGN,
         "want": {"kind": "another-account", "uid": F.OTHER_UID, "pid": F.FOREIGN_CLIENT_PID}},
        {"table": "netstatMulti", "ask": "peerAt", "server": SERVER, "client": OWN,
         "want": {"kind": "this-account", "pid": F.OWN_CLIENT_PID}},
        {"table": "netstatMulti", "ask": "serverEnd", "server": SERVER, "client": FOREIGN,
         "want": {"kind": "this-account", "pid": F.SERVER_PID}},
        {"table": "netstatMulti", "ask": "peerAt", "server": ["::ffff:127.0.0.1", F.SERVER_PORT],
         "client": ["::ffff:127.0.0.1", 50002], "want": {"kind": "another-account"}},
        # A macOS table that lists sockets but not this connection is restricted (DEC-0155 RT-1, FAA-312).
        {"table": "netstatMulti", "ask": "peerAt", "server": SERVER, "client": ["127.0.0.1", 59999],
         "want": {"kind": "unknown", "reason": NO_ROW_RESTRICTED}},
        # DEC-0155 RT-1 and RT-4 (FAA-312): a netstat holding no row of another process than the reader's (pid 4100)
        # is restricted: only its own exact 127.0.0.1 listener counts; its wildcard, its ::1 and a port with no row are
        # an owner that cannot be told; its own connection's rows still answer, a missing one is restricted too.
        {"table": "netstatOwnOnly", "ask": "listener", "port": F.SERVER_PORT, "ownPid": F.SERVER_PID,
         "want": {"kind": "this-account", "pid": F.SERVER_PID}},
        {"table": "netstatOwnOnly", "ask": "listener", "port": 47555, "ownPid": F.SERVER_PID,
         "want": {"kind": "unknown", "reason": restricted_listener(47555)}},
        {"table": "netstatOwnOnly", "ask": "listener", "port": 47070, "ownPid": F.SERVER_PID,
         "want": {"kind": "unknown", "reason": restricted_listener(47070)}},
        {"table": "netstatOwnOnly", "ask": "listener", "port": 1, "ownPid": F.SERVER_PID,
         "want": {"kind": "unknown", "reason": restricted_listener(1)}},
        {"table": "netstatOwnOnly", "ask": "serverEnd", "server": SERVER, "client": OWN, "ownPid": F.SERVER_PID,
         "want": {"kind": "this-account", "pid": F.SERVER_PID}},
        {"table": "netstatOwnOnly", "ask": "peerAt", "server": SERVER, "client": FOREIGN, "ownPid": F.SERVER_PID,
         "want": {"kind": "unknown", "reason": NO_ROW_RESTRICTED}},
        # The same table read by another process: rows of a process not its own, so the table reads as before.
        {"table": "netstatOwnOnly", "ask": "listener", "port": 47555, "ownPid": 4300,
         "want": {"kind": "this-account", "pid": F.SERVER_PID}},
        {"table": "netstatTimeWait", "ask": "peerAt", "server": SERVER, "client": OWN,
         "want": {"kind": "this-account", "pid": F.OWN_CLIENT_PID}},
        {"table": "netstatNoProcess", "ask": "listener", "port": F.SERVER_PORT,
         "want": {"kind": "unknown", "reason": "netstat-format: no process:pid column"}},
        {"table": "procMulti", "ask": "listener", "port": F.SERVER_PORT, "want": {"kind": "this-account", "uid": F.OWN_UID}},
        {"table": "procMulti", "ask": "listener", "port": 8021, "want": {"kind": "system", "uid": 0}},
        {"table": "procMulti", "ask": "peerAt", "server": SERVER, "client": FOREIGN,
         "want": {"kind": "another-account", "uid": F.OTHER_UID}},
        {"table": "procMulti", "ask": "serverEnd", "server": SERVER, "client": FOREIGN,
         "want": {"kind": "this-account", "uid": F.OWN_UID}},
        {"table": "proc6Multi", "ask": "peerAt", "server": ["::1", F.SERVER_PORT], "client": ["::1", 50002],
         "want": {"kind": "another-account", "uid": F.OTHER_UID}},
        {"table": "proc6Multi", "ask": "listener", "port": F.SERVER_PORT, "want": {"kind": "this-account"}},
        {"table": "procUnacceptedOwn", "ask": "serverEnd", "server": SERVER, "client": OWN,
         "want": {"kind": "this-account", "uid": F.OWN_UID}},
        {"table": "procUnacceptedOther", "ask": "serverEnd", "server": SERVER, "client": OWN,
         "want": {"kind": "another-account", "uid": F.OTHER_UID}},
        {"table": "procUnacceptedOther", "ask": "serverEnd", "server": SERVER, "client": OWN, "ownUid": 0,
         "want": {"kind": "another-account", "uid": F.OTHER_UID}},
        {"table": "procUnacceptedOwn", "ask": "serverEnd", "server": SERVER, "client": OWN, "ownUid": 0,
         "want": {"kind": "another-account", "uid": F.OWN_UID}},
        {"table": "procTwoListenersOneOwner", "ask": "listener", "port": F.SERVER_PORT, "want": {"kind": "this-account"}},
        {"table": "procClosedClient", "ask": "peerAt", "server": SERVER, "client": OWN,
         "want": {"kind": "unknown", "reason": "closed"}},
        {"table": "procSwappedListener", "ask": "serverEnd", "server": SERVER, "client": OWN,
         "want": {"kind": "another-account", "uid": F.OTHER_UID}},
        {"table": "procNoListener", "ask": "serverEnd", "server": SERVER, "client": OWN,
         "want": {"kind": "unknown", "reason": "not-accepted"}},
        {"table": "procPrintedTwice", "ask": "serverEnd", "server": SERVER, "client": OWN,
         "want": {"kind": "this-account", "uid": F.OWN_UID}},
        {"table": "procPrintedTwice", "ask": "peerAt", "server": SERVER, "client": OWN,
         "want": {"kind": "this-account", "uid": F.OWN_UID}},
        {"table": "procTwoOwnersOneTuple", "ask": "serverEnd", "server": SERVER, "client": OWN,
         "want": {"kind": "unknown", "reason": "several-rows"}},
        {"table": "procTwoListenersTwoOwners", "ask": "listener", "port": F.SERVER_PORT,
         "want": {"kind": "unknown", "reason": "several-rows"}},
        {"table": "windowsMulti", "ask": "listener", "port": F.SERVER_PORT,
         "want": {"kind": "this-account", "pid": F.SERVER_PID}, "twins": ["node"]},
        {"table": "windowsMulti", "ask": "serverEnd", "server": SERVER, "client": OWN,
         "want": {"kind": "this-account", "pid": F.SERVER_PID}, "twins": ["node"]},
        {"table": "windowsMulti", "ask": "peerAt", "server": SERVER, "client": OWN,
         "want": {"kind": "this-account", "pid": F.OWN_CLIENT_PID}, "twins": ["node"]},
        {"table": "windowsMulti", "ask": "peerAt", "server": SERVER, "client": FOREIGN,
         "want": {"kind": "unknown", "pid": F.FOREIGN_CLIENT_PID, "reason": "process-not-readable"}, "twins": ["node"]},
        {"table": "windowsMulti", "ask": "peerAt", "server": SERVER, "client": ["127.0.0.1", 50004],
         "want": {"kind": "another-account", "pid": 6200}, "twins": ["node"]},
        {"table": "windowsMulti", "ask": "peerAt", "server": SERVER, "client": ["127.0.0.1", 50003],
         "want": {"kind": "unknown", "reason": "no-row"}, "twins": ["node"]},
        {"table": "windowsMulti", "ask": "listener", "port": 445, "want": {"kind": "system", "pid": 4}, "twins": ["node"]},
        {"table": "windowsMulti", "ask": "listener", "port": 47070, "want": {"kind": "this-account", "pid": 4400},
         "twins": ["node"]},
        {"table": "windowsGerman", "ask": "listener", "port": F.SERVER_PORT,
         "want": {"kind": "this-account", "pid": F.SERVER_PID}, "twins": ["node"]},
        {"table": "windowsGerman", "ask": "peerAt", "server": SERVER, "client": ["127.0.0.1", 50003],
         "want": {"kind": "unknown", "reason": "no-row"}, "twins": ["node"]},
    ],
}

out = Path(__file__).with_name("peer-owner-cases.json")
out.write_text(json.dumps(cases, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(out)
