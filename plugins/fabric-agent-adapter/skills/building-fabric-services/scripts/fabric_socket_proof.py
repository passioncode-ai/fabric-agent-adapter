"""fabric_socket_proof: this OS account's own TCP sockets, read from its own processes (layer L0; DEC-0155 RT-2,
FAA-292; FAA-272).

macOS 27.2 shows an ad-hoc-signed interpreter (a Homebrew or uv CPython) only its own sockets in the host's socket
table, so `fabric_peer_owner` reads such a table as `table-restricted` and cannot tell who accepted a connection. The
question can still be asked of this account's own processes, which the restriction leaves readable: whether one of them
holds the very socket that accepted the connection (RT-2, the accepted-socket proof), or a listener bound exactly to
127.0.0.1:<port> (HA-2's macOS row, FAA-272). Another account's process answers EPERM and is skipped, so a proof only
ever says "this account's" or "not proved"; never another account's, the system's or nobody's.

    accepted(server, client, wait=...) -> Proof   the socket at `server` connected to `client` is in one of this
                                                  account's processes (`wait`: read again for ACCEPT_WAIT_SECONDS
                                                  until the server has called accept())
    own_listener(port) -> Proof                   a listener of this account on exactly 127.0.0.1:<port>

Two readers, chosen by `method()`:

- `libproc` (Python's): `proc_listpids(PROC_UID_ONLY)`, `proc_pidinfo(PROC_PIDLISTFDS)` and
  `proc_pidfdinfo(PROC_PIDFDSOCKETINFO)` through ctypes, the records `lsof` itself reads, without a subprocess:
  Project Observatory's `peer_owner` 1.3.1 reader (sha256 `b3831e5f...`, FAA-292). The `socket_fdinfo` layout is not
  an API, so the first read in a process calibrates it on a connected pair of its own, as the sysctl reader does; a
  layout that fails is never used again in this process, and a calibration that could not read at all is asked again.
- `lsof` (the Node twin's, and Python's when libproc is unavailable or uncalibrated): `lsof -nP -a -u <uid>
  -iTCP:<port> -sTCP:<state> -F pun`, the exact address pair and the numeric uid. The twins agree on answers, not on
  the program they run (DEC-0155 Compatibility); `test/fixtures/peer-owner/socket-proof-cases.json` holds both.

The proof is weaker than a table's `so_uid`: "a process of this uid holds the descriptor", not "the socket's
credential is this uid". A socket another account accepted and passed with SCM_RIGHTS to a process of this uid would
read as this account's; a caller that knows the server's pid closes that with `expect_pid`. One socket several of this
account's processes hold (an inherited descriptor) is proved with pid None, reason `several-processes`. A process whose
real and effective uids differ is refused (`setuid-context`): XNU lists and checks processes by the effective uid.
Reasons, as DEC-0155 RT-1 spells them: `table-restricted` (read, and no socket of this account matches) or
`table-restricted: <detail>` (the proof could not be read). Bounded by MAX_PIDS, MAX_FDS and TIMEOUT_SECONDS; nothing
is cached across questions but the calibration verdict. Standard library only, no other kit module. Tests:
`test/test_fabric_socket_proof.py`; the Node twin is `fabric-socket-proof.mjs`.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from typing import Callable, List, NamedTuple, Optional, Tuple

TABLE_RESTRICTED = "table-restricted"
LIBPROC = "libproc"
LSOF_METHOD = "lsof"
LSOF = "/usr/sbin/lsof"
#: Every read of one question is over within this many seconds (the accept wait included).
TIMEOUT_SECONDS = 2.0
#: How long `accepted(..., wait=True)` reads again for a server that has not called accept() yet.
ACCEPT_WAIT_SECONDS = 0.5
MAX_PIDS = 16384
MAX_FDS = 65536
MAX_OUTPUT_BYTES = 4 * 1024 * 1024

#: macOS `sys/proc_info.h`: selectors and the `struct socket_fdinfo` offsets read here. The struct is 792 bytes:
#: `proc_fileinfo` (24), then `socket_info`, whose `soi_so` is the kernel's socket (the same in every process that
#: holds it) and whose `soi_proto.pri_tcp` starts with an `in_sockinfo` (ports as ints holding a network-order port,
#: `insi_vflag`, the foreign and local `in4in6_addr`) and carries `tcpsi_state`.
PROC_UID_ONLY = 4
PROC_PIDLISTFDS = 1
PROX_FDTYPE_SOCKET = 2
PROC_PIDFDSOCKETINFO = 3
SOCKINFO_TCP = 2
SOCKET_FDINFO_SIZE = 792
_SOI = 24                         # socket_fdinfo.psi
_SOI_SO = _SOI + 136              # socket_info.soi_so
_SOI_KIND = _SOI + 232            # socket_info.soi_kind
_INI = _SOI + 240                 # soi_proto.pri_tcp.tcpsi_ini
_INI_VFLAG = _INI + 24            # INI_IPV4 0x1, INI_IPV6 0x2
_INI_FOREIGN = _INI + 32
_INI_LOCAL = _INI + 48
_TCPSI_STATE = _INI + 80          # TSI_S_CLOSED 0, TSI_S_LISTEN 1, TSI_S_TIME_WAIT 10
_TSI_S_CLOSED = 0
_TSI_S_LISTEN = 1
_TSI_S_TIME_WAIT = 10

Address = Tuple[str, int]
# Real types, not postponed strings (as fabric_peer_owner's Owner): a NamedTuple's generated __new__ resolves its
# annotations in a namespace of its own, where `Address` is no name.
_SocketFields = NamedTuple("_SocketFields", [("local", Tuple[str, int]), ("remote", Tuple[str, int]),
                                             ("listening", bool), ("pid", Optional[int])])
_ProofFields = NamedTuple("_ProofFields", [("proved", bool), ("pid", Optional[int]), ("method", str),
                                           ("reason", Optional[str])])


class Socket(_SocketFields):
    """One TCP socket of this account: `pid` is None when several of its processes hold it."""
    __slots__ = ()


class Proof(_ProofFields):
    """Whether this account's process holds the socket asked about; `reason` says why not, or `several-processes`."""
    __slots__ = ()


class ProofUnreadable(Exception):
    """This account's sockets could not be read; the message is the reason, never a socket's content."""


def _host(host: str) -> str:
    """One spelling per address, as fabric_peer_owner.norm_host (the same rule, kept here so this module stands alone):
    an IPv4-mapped IPv6 address is its IPv4 form, an unspecified one `*`, `localhost` 127.0.0.1, and `[...]` loses its
    brackets. Anything unparseable is returned unchanged (and matches only itself)."""
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if host in ("*", ""):
        return "*"
    if host == "localhost":
        return "127.0.0.1"
    host = host.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return "*" if ip.is_unspecified else str(ip)


def _digits(text: str) -> bool:
    """`[0-9]+`, as the Node twin reads a number (`str.isdigit` also takes `٤`)."""
    return text != "" and text.isascii() and text.isdigit()


# -- parsers: pure functions over captured records and text (test/fixtures/peer-owner/socket-proof-cases.json) -------

def parse_socket_fdinfo(blob: bytes) -> Optional[Tuple[Address, Address, int, int]]:
    """One `proc_pidfdinfo(PROC_PIDFDSOCKETINFO)` record: (local, remote, TCP state, socket handle) for a TCP socket,
    None for any other kind. A short record is unreadable."""
    if len(blob) < SOCKET_FDINFO_SIZE:
        raise ProofUnreadable("libproc: short socket record")
    if struct.unpack_from("<i", blob, _SOI_KIND)[0] != SOCKINFO_TCP:
        return None
    fport, lport = struct.unpack_from(">H", blob, _INI)[0], struct.unpack_from(">H", blob, _INI + 4)[0]
    family, at = (socket.AF_INET, 12) if blob[_INI_VFLAG] & 0x1 else (socket.AF_INET6, 0)
    size = 4 if family == socket.AF_INET else 16
    foreign = socket.inet_ntop(family, bytes(blob[_INI_FOREIGN + at:_INI_FOREIGN + at + size]))
    local = socket.inet_ntop(family, bytes(blob[_INI_LOCAL + at:_INI_LOCAL + at + size]))
    state = struct.unpack_from("<i", blob, _TCPSI_STATE)[0]
    return (_host(local), lport), (_host(foreign), fport), state, struct.unpack_from("<Q", blob, _SOI_SO)[0]


def own_sockets(records: List[Tuple[int, Address, Address, int, int]]) -> List[Socket]:
    """Sockets from this account's records (pid, local, remote, state, handle): one per handle, pid None when several
    processes hold it. Closed and TIME_WAIT sockets are left out."""
    by_handle: dict = {}
    for pid, local, remote, state, handle in records:
        if state in (_TSI_S_CLOSED, _TSI_S_TIME_WAIT):
            continue
        by_handle.setdefault(handle, (local, remote, state, []))[3].append(pid)
    return [Socket(local, remote, state == _TSI_S_LISTEN, pids[0] if len(set(pids)) == 1 else None)
            for local, remote, state, pids in by_handle.values()]


def _lsof_address(text: str) -> Optional[Address]:
    """`127.0.0.1:47311`, `[::1]:47070` or `*:47312`: the port after the last colon, ASCII digits only."""
    host, sep, port = text.rpartition(":")
    if not sep or not _digits(port) or int(port) > 65535:
        return None
    return _host(host), int(port)


def parse_lsof_sockets(text: str, uid: int) -> List[Socket]:
    """`lsof -nP -a -u <uid> -iTCP:<port> -sTCP:<state> -F pun`: the `n` lines of every process block whose `u` line is
    exactly `uid` (a block of another uid, or with no uid, is not read). A name with `->` is a connection, one without a
    listener. The same socket listed by several processes (one address pair: TCP holds one connection per pair) is one
    socket with pid None."""
    found: dict = {}
    pid = owner = None
    for line in text.splitlines():
        tag, value = line[:1], line[1:]
        if tag == "p":
            pid, owner = (int(value) if _digits(value) else None), None
        elif tag == "u":
            owner = int(value) if _digits(value) else None
        elif tag == "n" and pid is not None and owner == uid:
            local_text, arrow, remote_text = value.partition("->")
            local = _lsof_address(local_text)
            remote = _lsof_address(remote_text) if arrow else ("*", 0)
            if local is None or remote is None:
                continue
            key = (local, remote, not arrow)
            found.setdefault(key, []).append(pid)
    return [Socket(local, remote, listening, pids[0] if len(set(pids)) == 1 else None)
            for (local, remote, listening), pids in found.items()]


def _proved(hits: List[Socket], how: str) -> Proof:
    if not hits:
        return Proof(False, None, how, TABLE_RESTRICTED)
    pids = {s.pid for s in hits}
    if len(pids) == 1 and None not in pids:
        return Proof(True, pids.pop(), how, None)
    return Proof(True, None, how, "several-processes")


def accepted_in(sockets: List[Socket], server: Address, client: Address, how: str) -> Proof:
    """RT-2 over this account's sockets: the one at `server` connected to `client`. Two different sockets with that
    address pair cannot be told apart (`several-rows`)."""
    hits = [s for s in sockets if not s.listening and s.local == server and s.remote == client]
    if len(hits) > 1:
        return Proof(False, None, how, "several-rows")
    return _proved(hits, how)


def listener_in(sockets: List[Socket], port: int, how: str) -> Proof:
    """FAA-272 over this account's sockets: a listener bound exactly to 127.0.0.1:<port>. XNU refuses another ordinary
    account that bind beside ours (`in_pcbbind`); our wildcard or ::1 listener, and root's, cannot be told from a
    hidden one, so they prove nothing (DEC-0155 RT-4)."""
    return _proved([s for s in sockets if s.listening and s.local == ("127.0.0.1", port)], how)


# -- readers ----------------------------------------------------------------------------------------------------------

_LOCK = threading.Lock()
#: None until a calibration of the libproc layout reaches a verdict in this process, then True or False.
_LIBPROC_OK: list = [None]


def _run(argv: List[str]) -> str:
    """One bounded run of lsof; its exit 1 with nothing printed is "no socket matched", not a failure."""
    try:
        done = subprocess.run(argv, capture_output=True, timeout=TIMEOUT_SECONDS, check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProofUnreadable("lsof: %s" % type(exc).__name__) from None
    if done.returncode == 1 and not done.stdout.strip():
        return ""
    if done.returncode != 0:
        raise ProofUnreadable("lsof: exit %d" % done.returncode)
    if len(done.stdout) > MAX_OUTPUT_BYTES:
        raise ProofUnreadable("lsof: output over %d bytes" % MAX_OUTPUT_BYTES)
    return done.stdout.decode("utf-8", "replace")


def _libproc_records(uid: int, deadline: float) -> List[Tuple[int, Address, Address, int, int]]:
    """This uid's processes' TCP sockets, as (pid, local, remote, state, handle). A process that cannot be read (gone,
    or EPERM) is skipped: it can only lose an answer, never make one."""
    try:
        import ctypes
        lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        lib.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidfdinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    except (ImportError, OSError, TypeError, AttributeError) as exc:
        raise ProofUnreadable("libproc: %s" % type(exc).__name__) from None
    for fn in (lib.proc_listpids, lib.proc_pidinfo, lib.proc_pidfdinfo):
        fn.restype = ctypes.c_int
    need = lib.proc_listpids(PROC_UID_ONLY, uid, None, 0)
    if need <= 0:
        raise ProofUnreadable("libproc: errno %d" % ctypes.get_errno())
    pids = (ctypes.c_int * min(need // 4 + 64, MAX_PIDS))()
    got = lib.proc_listpids(PROC_UID_ONLY, uid, pids, ctypes.sizeof(pids))
    if got <= 0:
        raise ProofUnreadable("libproc: errno %d" % ctypes.get_errno())
    if got // 4 >= MAX_PIDS:
        raise ProofUnreadable("libproc: over %d processes" % MAX_PIDS)
    record = ctypes.create_string_buffer(SOCKET_FDINFO_SIZE)
    out = []
    for pid in pids[:got // 4]:
        if pid <= 0:
            continue
        if time.monotonic() > deadline:
            raise ProofUnreadable("libproc: deadline")
        size = lib.proc_pidinfo(pid, PROC_PIDLISTFDS, 0, None, 0)
        if size <= 0:
            continue
        fds = ctypes.create_string_buffer(min(size + 32 * 8, MAX_FDS * 8))
        size = lib.proc_pidinfo(pid, PROC_PIDLISTFDS, 0, fds, len(fds))
        for i in range(max(size, 0) // 8):
            fd, kind = struct.unpack_from("<iI", fds, i * 8)
            if kind != PROX_FDTYPE_SOCKET:
                continue
            if lib.proc_pidfdinfo(pid, fd, PROC_PIDFDSOCKETINFO, record, SOCKET_FDINFO_SIZE) != SOCKET_FDINFO_SIZE:
                continue
            parsed = parse_socket_fdinfo(record.raw)
            if parsed is not None:
                out.append((pid,) + parsed)
    return out


def _calibrate_libproc() -> Optional[bool]:
    """Whether the `socket_fdinfo` layout reads back a connected pair of this process's own (the listener and both
    ends, each once, with their exact addresses and this pid); None when libproc could not be read at all, which the
    caller does not keep (FAA-273 item 11: an unread calibration is not a verdict)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client = taken = None
    try:
        probe.bind(("127.0.0.1", 0))
        probe.listen(1)
        client = socket.create_connection(probe.getsockname(), timeout=TIMEOUT_SECONDS)
        taken, _ = probe.accept()
        server, near = probe.getsockname()[:2], client.getsockname()[:2]
        have = own_sockets(_libproc_records(os.getuid(), time.monotonic() + TIMEOUT_SECONDS))
        me = os.getpid()
        return all(len(hits) == 1 and hits[0].pid == me for hits in (
            [s for s in have if s.listening and s.local == server],
            [s for s in have if not s.listening and s.local == server and s.remote == near],
            [s for s in have if not s.listening and s.local == near and s.remote == server]))
    except (ProofUnreadable, OSError, struct.error, ValueError):
        return None
    finally:
        for s in (client, taken, probe):
            if s is not None:
                s.close()


def method(platform: Optional[str] = None) -> str:
    """The reader the next question uses: libproc once its layout passed calibration, else lsof; none off macOS."""
    if (platform or sys.platform) != "darwin":
        return "none"
    with _LOCK:
        if _LIBPROC_OK[0] is None:
            _LIBPROC_OK[0] = _calibrate_libproc()
        return LIBPROC if _LIBPROC_OK[0] else LSOF_METHOD


def _ask(port: int, state: str, pick: Callable[[List[Socket], str], Proof], wait: float, platform: Optional[str],
         uid: Optional[int], euid: Optional[int], how: Optional[str], run: Optional[Callable[[List[str]], str]]) -> Proof:
    start = time.monotonic()
    if (platform or sys.platform) != "darwin":
        return Proof(False, None, "none", "%s: unsupported-platform" % TABLE_RESTRICTED)
    uid = os.getuid() if uid is None else uid
    euid = os.geteuid() if euid is None else euid
    if uid != euid:
        return Proof(False, None, how or "none", "%s: setuid-context" % TABLE_RESTRICTED)
    how = how or method(platform)
    pause = 0.005
    while True:
        try:
            if how == LIBPROC:
                have = own_sockets(_libproc_records(uid, start + TIMEOUT_SECONDS))
            else:
                argv = [LSOF, "-nP", "-a", "-u", str(uid), "-iTCP:%d" % port, "-sTCP:%s" % state, "-F", "pun"]
                have = parse_lsof_sockets((run or _run)(argv), uid)
        except ProofUnreadable as exc:
            return Proof(False, None, how, "%s: %s" % (TABLE_RESTRICTED, exc))
        answer = pick(have, how)
        if answer.proved or time.monotonic() + pause > start + min(wait, TIMEOUT_SECONDS):
            return answer
        time.sleep(pause)
        pause = min(pause * 2, 0.05)


def accepted(server: Address, client: Address, *, wait: bool = False, platform: Optional[str] = None,
             uid: Optional[int] = None, euid: Optional[int] = None, how: Optional[str] = None,
             run: Optional[Callable[[List[str]], str]] = None) -> Proof:
    """RT-2: whether the socket at `server` connected to `client` (a client's own connection, seen from the server's
    side) is in one of this account's processes. `wait`: a server end is read again for ACCEPT_WAIT_SECONDS, since a
    client asks right after connect() and the server's accepted socket exists only once it calls accept().
    `platform`, `uid`, `euid`, `how` and `run` are the tests'."""
    server, client = (_host(str(server[0])), int(server[1])), (_host(str(client[0])), int(client[1]))
    return _ask(server[1], "ESTABLISHED", lambda have, how_: accepted_in(have, server, client, how_),
                ACCEPT_WAIT_SECONDS if wait else 0.0, platform, uid, euid, how, run)


def own_listener(port: int, *, platform: Optional[str] = None, uid: Optional[int] = None, euid: Optional[int] = None,
                 how: Optional[str] = None, run: Optional[Callable[[List[str]], str]] = None) -> Proof:
    """FAA-272: whether one of this account's processes listens on exactly 127.0.0.1:<port>."""
    return _ask(int(port), "LISTEN", lambda have, how_: listener_in(have, int(port), how_), 0.0, platform, uid, euid,
                how, run)
