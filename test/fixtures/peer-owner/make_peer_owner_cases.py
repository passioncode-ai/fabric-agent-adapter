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
        "netstatNoProcess": {"kind": "netstat", "text": F.NETSTAT_NO_PROCESS},
        "procMulti": {"kind": "proc4", "text": F.PROC_NET_TCP_MULTI},
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
        {"table": "netstatMulti", "ask": "peerAt", "server": SERVER, "client": ["127.0.0.1", 59999],
         "want": {"kind": "unknown", "reason": "no-row"}},
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
