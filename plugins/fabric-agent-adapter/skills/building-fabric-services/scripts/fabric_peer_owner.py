"""peer_owner: which OS account owns each end of a loopback TCP connection.

    peer_owner 1.2.0+kit.6: Observatory's peer_owner 1.2.0 (passioncode-ai/project-observatory-dashboard,
    `observatory/engine/peer_owner.py`, first vendored at f86f0622, read against 2180235c; the same licence), the kit's
    `fabric_peer_owner` (layer L0; DEC-0154 HA-2, FAA-226, FAA-258). Observatory's 1.3.x (this account's own sockets
    through libproc, DEC-0155 RT-2) is not in it (FAA-292). The kit's differences: `Owner` and `Row` are NamedTuples
    (a dataclass with postponed annotations needs its module in sys.modules, and a service may load a kit file by
    path); `Optional[X]` for `X | None` (the kit's floor is Python 3.9); `classify` / `classify_sid` ask for this
    process's own uid or SID first (a client running as root or SYSTEM owns root's listener); on Linux `server_end`
    reads an accepted connection's own row and, for one not accept()ed yet (uid 0, inode 0), the listener on its local
    address (CT-254; reasons `not-accepted`, `several-rows`, `closed`), `peer` reads a client row with inode 0 as
    unknown, several rows of one owner are that owner, a row printed twice counts once, and a `/proc` question that
    finds no row or several reads once more; ctypes is imported where used. On macOS (kit.2 to kit.4, FAA-267,
    FAA-273): the sysctl calibration also requires a child process's listener, an empty or header-only netstat is
    `TABLE_RESTRICTED`, a caller may vouch for a listener with a pid it started (`pid_listens`,
    `CheckedHTTPConnection(vouch_pid=...)`), the child's port is read under one deadline with `selectors`, a number is
    ASCII digits only. DEC-0155 (kit.6, FAA-312): a netstat that fails, a table with no row of another uid (sysctl) or process
    (netstat) and a missing connection row read as `table-restricted` (RT-1); a restricted table's listener is this
    account's only on exactly 127.0.0.1 (RT-4); the vouch takes exactly 127.0.0.1 (RT-3), never from a set-uid
    reader. `main` is the CLI, `listener <port>` (FAA-315). /proc carries a socket's creator, so a listener root created
    and handed to another account (systemd socket activation, User=) reads as root's. Standard library only, no other
    kit module. Tests: `test/test_fabric_peer_owner.py`; the Node twin is `fabric-peer-owner.mjs` (no ctypes).

WHY. Loopback is one per machine, not one per OS account. On a host with several accounts, every account's processes
reach every service any account listens with on 127.0.0.1, and a loopback socket proves nothing about who is on the
other end. This module answers that question from the host's socket table, read without privileges:

    listener(port) -> Owner       who listens on 127.0.0.1:<port> (also 0.0.0.0, ::1, ::)
    server_end(sock) -> Owner     for a client's connected socket: who accepted it
    peer(sock) -> Owner           for a server's accepted socket: who connected
    peer_at(server, client)       the same as `peer`, from two (host, port) addresses
    own_connection(port, ...)     a CheckedHTTPConnection, connected: every connect, the first and
                                  any reconnect http.client makes after `Connection: close`, checks
                                  that the server end is this account's, or raises ListenerRefused
                                  before a byte of the request is sent

`Owner.kind` is one of:

    this-account      the socket belongs to the account running this process
    another-account   another OS account's
    system            uid 0, pid 1 (launchd holds the sockets of socket-activated jobs) or, on
                      Windows, the system's own accounts and processes
    unknown           the owner could not be told; `reason` says why
    none              `listener` only: nothing listens on that port

A caller that must not leak (a client about to send a bearer, a server on a multi-account host about to read a request)
treats everything but `this-account` as a refusal, `unknown` included: fail closed.

HOW, ON EACH OS. Every read is bounded (MAX_TABLE_BYTES of table, TIMEOUT_SECONDS) and the answer is never cached across
connections; only `listener` is cached, for LISTENER_TTL. A TIME_WAIT row is a connection already closed and is never an
answer; two live rows with the same addresses are `unknown` (`several-rows`), never a guess.

- macOS, primary (`sysctl`): `sysctl net.inet.tcp.pcblist_n` through ctypes, the record list `netstat` itself reads.
  Each connection is an `xinpcb_n` (addresses and ports) followed by an `xsocket_n` that carries `so_uid` and
  `so_last_pid` (XNU `bsd/netinet/in_pcb.h` and `bsd/sys/socketvar.h`, both under `#pragma pack(4)`); the two are
  paired by the pcb handle (`xi_inpp` equals `so_pcb`). Measured on macOS 26: about 4 ms for 770 sockets, every pid
  equal to the one `netstat` printed. The `xtcpcb_n` record that follows gives the TCP state (`t_state`), so listeners
  and TIME_WAIT rows are told apart. The layout is not an API, so the first read in a process calibrates it: it opens
  a connected pair of its own (listen, connect, accept) and the listener and both ends of the pair must read back with
  their exact addresses, this process's uid and its pid. A layout that fails calibration is not used again in that
  process.
- macOS 27.2 shows an ad-hoc-signed interpreter (a Homebrew Python) only its own sockets: the calibration also
  requires a child's listener, and a restricted table (DEC-0155 RT-1) is `unknown` with a reason beginning
  `table-restricted`, never another account's. A caller that started the server (an installer, its launchd job) may
  vouch with that pid: `lsof -p PID` asks the process, which the restriction leaves readable (RT-3).
- macOS, fallback (`netstat`): `/usr/sbin/netstat -anv -p tcp`, its `process:pid` column, then `ps -o uid= -p PID` for
  the owner of the one row a question needs. Measured: about 20 ms over 846 sockets, and it names the pids of root's
  listeners, which `lsof` run by an ordinary account cannot see. Another local service implemented the same check this
  way; it is kept as the documented fallback for a macOS whose record layout the calibration refuses.
- Linux (`proc`): `/proc/net/tcp` and `/proc/net/tcp6`, whose `uid` column every account may read (also under
  `hidepid=2`, which hides `/proc/<pid>` and not this file). No pid: that is only readable for this account's own
  processes, and the decision needs the uid alone.
- Windows (`iphlpapi`): `GetExtendedTcpTable(TCP_TABLE_OWNER_PID_ALL)` gives each row's owning pid;
  `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`, `OpenProcessToken(TOKEN_QUERY)` and
  `GetTokenInformation(TokenUser)` give its account SID, compared with this process's. A process that cannot be opened
  (another account's, usually) is `unknown`, never `another-account`: the caller refuses either way, and the reason
  says which it was. `Owner.uid` is None there.
- Anything else: `unknown`, reason `unsupported-platform`.

`LOCAL_PEERCRED`, `getpeereid` and Linux `SO_PEERCRED` answer this question for Unix-domain sockets only, not for TCP,
which is why a socket table is read here at all.

WHAT IT NEVER DOES. It never reads a byte from the socket it is asked about, never resolves a name, never sends
anything, and never needs a privilege. It reports the process names `netstat` prints only as far as the pid behind them.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from typing import NamedTuple, Optional, Tuple

# This file's own version, for projects that copy it; not the engine's (that is configuration.VERSION).
PEER_OWNER_VERSION = "1.2.0+kit.6"  # Observatory's 1.2.0 with the kit's differences above

THIS_ACCOUNT = "this-account"
ANOTHER_ACCOUNT = "another-account"
SYSTEM = "system"
UNKNOWN = "unknown"
NONE = "none"
KINDS = (THIS_ACCOUNT, ANOTHER_ACCOUNT, SYSTEM, UNKNOWN, NONE)

#: The most table bytes one read accepts: 1 MB held about 1,200 sockets at `pcblist_n`'s 860 bytes each, which a busy
#: developer machine passes; 4 MiB holds about 6,800 at 616 bytes measured on macOS 26 (FAA-260).
MAX_TABLE_BYTES = 4 * 1024 * 1024
#: Every subprocess this module starts is stopped after this many seconds.
TIMEOUT_SECONDS = 2.0
#: `listener(port)` answers from a read at most this old (a doctor asks several times in a row).
LISTENER_TTL = 1.0

NETSTAT = "/usr/sbin/netstat"
PS = "/bin/ps"
LSOF = "/usr/sbin/lsof"

#: The reason a socket table hides other processes' sockets from this one (FAA-267: macOS 27.2 shows an ad-hoc-signed
#: interpreter, such as a Homebrew Python, only its own sockets through sysctl and nothing through netstat).
TABLE_RESTRICTED = "table-restricted"
#: A macOS table that lists sockets but not the reader's own connection (DEC-0155 RT-1, FAA-312).
NO_ROW_RESTRICTED = TABLE_RESTRICTED + ": no row for this connection"

#: Client codes of `own_connection` (ListenerRefused.code).
SERVER_NOT_OWN = "server-not-own"
SERVER_UNVERIFIED = "server-unverified"
SERVER_NOT_THIS_WORKSPACE = "server-not-this-workspace"


# The fields carry real types, not postponed strings: a NamedTuple's generated __new__ resolves its annotations in a
# namespace without builtins, where `int | None` as a string is unresolvable (and a TypeError on Python 3.9).
_OwnerFields = NamedTuple("_OwnerFields", [("kind", str), ("uid", Optional[int]), ("pid", Optional[int]),
                                           ("method", str), ("reason", Optional[str])])
_OwnerFields.__new__.__defaults__ = (None, None, "none", None)
_RowFields = NamedTuple("_RowFields", [("local", Tuple[str, int]), ("remote", Tuple[str, int]), ("listening", bool),
                                       ("uid", Optional[int]), ("pid", Optional[int]), ("time_wait", bool)])
_RowFields.__new__.__defaults__ = (None, None, False)


class Owner(_OwnerFields):
    """Who owns one end of a connection, or a listener. `reason` says why when `kind` is unknown."""
    __slots__ = ()

    def as_dict(self) -> dict:
        return dict(self._asdict())


class Row(_RowFields):
    """One TCP socket of the host's table; `uid` is None where it carries none (netstat, Windows): read from `pid`."""
    __slots__ = ()


class TableUnreadable(Exception):
    """The socket table could not be read; the message is the reason, never a socket's content."""


class ListenerRefused(Exception):
    """`own_connection` refused the server end; nothing was sent on the connection."""

    def __init__(self, code: str, message: str, owner: Optional[Owner] = None) -> None:
        super().__init__(message)
        self.code = code
        self.owner = owner


# -- addresses --------------------------------------------------------------------------------------------------------

def norm_host(host: str) -> str:
    """One spelling per address: an IPv4-mapped IPv6 address is its IPv4 form, `*` is the wildcard, `localhost` is
    127.0.0.1. Anything unparseable is returned unchanged (and matches only itself)."""
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
    if ip.is_unspecified:
        return "*"
    return str(ip)


def _address(addr) -> tuple[str, int]:
    """A socket address (2-tuple for IPv4, 4-tuple for IPv6) as a normalized (host, port)."""
    return norm_host(str(addr[0])), int(addr[1])


# -- classification ---------------------------------------------------------------------------------------------------

def _posix_uid() -> Optional[int]:
    """This process's uid, or None where the OS has none (Windows compares SIDs). The one place this module reads it:
    vendored without its project's OS layer, it reads it here, on POSIX only (an engine boundary test names it)."""
    return os.getuid() if hasattr(os, "getuid") else None


def _own_pid() -> int:
    """This process's pid: a netstat that shows no other process's row is a restricted table (DEC-0155 RT-1)."""
    return os.getpid()


def _set_uid() -> bool:
    """Real and effective uid differ: such a reader uses none of DEC-0155's proofs (RT-2 to RT-5), the vouch included."""
    return hasattr(os, "geteuid") and os.geteuid() != _posix_uid()


def classify(uid: Optional[int], pid: Optional[int], *, method: str, own_uid: Optional[int] = None) -> Owner:
    """`this-account` for this process's uid, `system` for uid 0 or pid 1, else `another-account`. A client that runs
    as root itself reads root's listener as its own account's (the kit's order; the vendored file put uid 0 first)."""
    if uid is None:
        return Owner(UNKNOWN, None, pid, method, "no-owner")
    if own_uid is None:
        own_uid = _posix_uid()
    if own_uid is not None and uid == own_uid and pid != 1:
        return Owner(THIS_ACCOUNT, uid, pid, method)
    if uid == 0 or pid == 1:
        return Owner(SYSTEM, uid, pid, method)
    return Owner(ANOTHER_ACCOUNT, uid, pid, method)


# -- parsers: pure functions over captured text or bytes (the tests' fixtures) ---------------------------------------

def _ascii_digits(text: str) -> bool:
    """`[0-9]+` as the Node twin reads a number; `str.isdigit` also takes `٤` and `²` (FAA-273 item 4)."""
    return text != "" and text.isascii() and text.isdigit()


def parse_netstat(text: str) -> list[Row]:
    """`netstat -anv -p tcp` on macOS. Process names may hold spaces ("Some App:123"), so the
    `process:pid` column is what is left between the leading and the trailing columns, both
    counted from the header. A header without `process:pid` (an older macOS) is unreadable."""
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        raise TableUnreadable(f"{TABLE_RESTRICTED}: netstat printed nothing to this process")
    header = next((i for i, line in enumerate(lines) if "process:pid" in line and "Proto" in line), None)
    if header is None:
        raise TableUnreadable("netstat-format: no process:pid column")
    names = lines[header].split()
    at = names.index("process:pid")
    # "Local Address" and "Foreign Address" are two header words each and one data column each.
    leading = at - sum(1 for w in names[:at] if w == "Address")
    trailing = len(names) - at - 1
    if not any(line.split()[:1] and line.split()[0].startswith("tcp") for line in lines[header + 1:]):
        # The caller's own connection is in any table it can see: a header and no tcp row is the restricted table
        # (FAA-273 item 3), not `no-row`.
        raise TableUnreadable(f"{TABLE_RESTRICTED}: netstat printed only its header to this process")
    rows: list[Row] = []
    for line in lines[header + 1:]:
        tok = line.split()
        if len(tok) < leading + trailing + 1 or not tok[0].startswith("tcp"):
            continue
        local = _netstat_address(tok[3])
        remote = _netstat_address(tok[4])
        if local is None or remote is None:
            continue
        process = " ".join(tok[leading:len(tok) - trailing])
        pid = None
        if ":" in process:
            tail = process.rsplit(":", 1)[1]
            pid = int(tail) if _ascii_digits(tail) else None
        rows.append(Row(local, remote, tok[5] == "LISTEN", None, pid, tok[5] == "TIME_WAIT"))
    return rows


def _netstat_address(text: str) -> Optional[tuple[str, int]]:
    """`127.0.0.1.47311`, `::1.47070`, `*.47555`, `*.*`: the port after the last dot. A long IPv6
    address is cut short by netstat, which only ever matters off loopback."""
    if "." not in text:
        return None
    host, port = text.rsplit(".", 1)
    try:
        return norm_host(host), (0 if port == "*" else int(port))
    except ValueError:
        return None


def parse_lsof_listeners(text: str) -> list[tuple[str, int]]:
    """`lsof -nP -a -p PID -i4TCP -sTCP:LISTEN -Fn`: the `n` lines, `127.0.0.1:47480`, `*:47480` or `[::1]:47480`."""
    found: list[tuple[str, int]] = []
    for line in text.splitlines():
        if not line.startswith("n") or ":" not in line:
            continue
        host, port = line[1:].rsplit(":", 1)
        if _ascii_digits(port):
            found.append((norm_host(host.strip("[]")), int(port)))
    return found


def parse_ps_uid(text: str) -> Optional[int]:
    """`ps -o uid= -p PID`: one number, or nothing when the process is gone."""
    text = text.strip()
    return int(text) if _ascii_digits(text) else None


def parse_proc_net_tcp(text: str, *, family: int, byteorder: Optional[str] = None) -> list[Row]:
    """`/proc/net/tcp` (family AF_INET) or `/proc/net/tcp6` (AF_INET6). The kernel prints each 32-bit word of an address
    in host byte order and each port in network order, in hex. A connected row with inode 0 has no socket yet (a
    connection the server has not accept()ed, or one already closed): the kernel prints uid 0 for it, so its uid is not
    read (None); `_owner_of` reads a server end not yet accepted as its listener's and a closed client as unknown (the
    kit's addition, 0.74.0 unit readings 3 and 4)."""
    order = byteorder or sys.byteorder
    rows: list[Row] = []
    for line in text.splitlines()[1:]:
        tok = line.split()
        if len(tok) < 10 or not tok[0].endswith(":"):
            continue
        try:
            local = _proc_address(tok[1], family, order)
            remote = _proc_address(tok[2], family, order)
            uid = int(tok[7])
        except ValueError:
            continue
        listening, time_wait = tok[3].upper() == "0A", tok[3].upper() == "06"
        if not listening and tok[9] == "0":
            uid = None
        rows.append(Row(local, remote, listening, uid, None, time_wait))
    return rows


def _proc_address(text: str, family: int, order: str) -> tuple[str, int]:
    host, port = text.split(":")
    raw = bytes.fromhex(host)
    if order == "little":
        raw = b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
    want = 4 if family == socket.AF_INET else 16
    if len(raw) != want:
        raise ValueError("address length")
    return norm_host(socket.inet_ntop(family, raw)), int(port, 16)


#: XNU's export records (`#pragma pack(4)`): kinds and the offsets this module reads.
XSO_SOCKET = 0x001
XSO_INPCB = 0x010
XSO_TCPCB = 0x020
_TCP_STATE = 36                   # xtcpcb_n.t_state: TCPS_LISTEN 1, TCPS_TIME_WAIT 10
_TCP_MIN = 40
_TCPS_LISTEN = 1
_TCPS_TIME_WAIT = 10
_INP_HANDLE = slice(8, 16)        # xinpcb_n.xi_inpp
_INP_PORTS = 16                   # inp_fport, inp_lport, network order
_INP_VFLAG = 44                   # inp_vflag: INP_IPV4 0x1, INP_IPV6 0x2
_INP_FOREIGN = 48                 # 16 bytes; an IPv4 address in its last 4 (in_addr_4in6)
_INP_LOCAL = 64
_INP_MIN = 80
_SO_PCB = slice(28, 36)           # xsocket_n.so_pcb, equal to the inpcb's xi_inpp
_SO_UID = 64                      # so_uid, then so_last_pid
_SO_MIN = 72


def parse_pcblist_n(blob: bytes) -> list[Row]:
    """The `net.inet.tcp.pcblist_n` record list: an `xinpgen` header, then for each socket a run
    of records each starting with (length, kind) and padded to 8 bytes, ended by a second
    `xinpgen`. Records of other kinds (socket buffers, stats, the tcpcb) are skipped by length."""
    if len(blob) < 8:
        raise TableUnreadable("pcblist_n: short table")
    first = struct.unpack_from("<I", blob, 0)[0]
    if first < 8 or first > 64:
        raise TableUnreadable("pcblist_n: unknown header")
    off = (first + 7) & ~7
    pcbs: dict[bytes, tuple] = {}
    owners: dict[bytes, tuple[int, int]] = {}
    states: dict[bytes, int] = {}
    current: Optional[bytes] = None                                    # the inpcb the records that follow belong to
    while off + 8 <= len(blob):
        length, kind = struct.unpack_from("<II", blob, off)
        if length < 8:
            break
        if length == first and off + length >= len(blob) - 8:
            break                                                   # the closing xinpgen
        if off + length > len(blob):
            raise TableUnreadable("pcblist_n: a record runs past the table")
        if kind == XSO_INPCB and length >= _INP_MIN:
            rec = blob[off:off + length]
            fport, lport = struct.unpack_from(">HH", rec, _INP_PORTS)
            if rec[_INP_VFLAG] & 0x1:
                foreign = socket.inet_ntop(socket.AF_INET, rec[_INP_FOREIGN + 12:_INP_FOREIGN + 16])
                local = socket.inet_ntop(socket.AF_INET, rec[_INP_LOCAL + 12:_INP_LOCAL + 16])
            else:
                foreign = socket.inet_ntop(socket.AF_INET6, rec[_INP_FOREIGN:_INP_FOREIGN + 16])
                local = socket.inet_ntop(socket.AF_INET6, rec[_INP_LOCAL:_INP_LOCAL + 16])
            current = bytes(rec[_INP_HANDLE])
            pcbs[current] = (norm_host(local), lport, norm_host(foreign), fport)
        elif kind == XSO_SOCKET and length >= _SO_MIN:
            uid, pid = struct.unpack_from("<Ii", blob, off + _SO_UID)
            owners[bytes(blob[off + _SO_PCB.start:off + _SO_PCB.stop])] = (uid, pid)
        elif kind == XSO_TCPCB and length >= _TCP_MIN and current is not None:
            states[current] = struct.unpack_from("<i", blob, off + _TCP_STATE)[0]
        off += (length + 7) & ~7
    rows = []
    for handle, (local, lport, foreign, fport) in pcbs.items():
        uid, pid = owners.get(handle, (None, None))
        state = states.get(handle)
        # Without a tcpcb, a listener is the row with no peer: foreign port 0, foreign address the wildcard.
        listening = state == _TCPS_LISTEN if state is not None else (fport == 0 and foreign == "*")
        rows.append(Row((local, lport), (foreign, fport), listening, uid, pid, state == _TCPS_TIME_WAIT))
    return rows


#: Windows' MIB rows (iphlpapi): sizes and the LISTEN and TIME_WAIT states.
_MIB_TCP_STATE_LISTEN = 2
_MIB_TCP_STATE_TIME_WAIT = 11


def parse_windows_tcp_table(blob: bytes, family: int) -> list[Row]:
    """A `GetExtendedTcpTable(..., TCP_TABLE_OWNER_PID_ALL)` buffer: a DWORD count, then
    MIB_TCPROW_OWNER_PID (24 bytes) or MIB_TCP6ROW_OWNER_PID (56 bytes) rows. Addresses are in
    network order in memory; a port is the low 16 bits of its DWORD, in network order."""
    if len(blob) < 4:
        raise TableUnreadable("iphlpapi: short table")
    count = struct.unpack_from("<I", blob, 0)[0]
    size, base = (24, 4) if family == socket.AF_INET else (56, 4)
    rows = []
    for i in range(count):
        at = base + i * size
        if at + size > len(blob):
            break
        if family == socket.AF_INET:
            state = struct.unpack_from("<I", blob, at)[0]
            local = socket.inet_ntop(family, blob[at + 4:at + 8])
            lport = struct.unpack_from(">H", blob, at + 8)[0]
            remote = socket.inet_ntop(family, blob[at + 12:at + 16])
            rport = struct.unpack_from(">H", blob, at + 16)[0]
            pid = struct.unpack_from("<I", blob, at + 20)[0]
        else:
            local = socket.inet_ntop(family, blob[at:at + 16])
            lport = struct.unpack_from(">H", blob, at + 20)[0]
            remote = socket.inet_ntop(family, blob[at + 24:at + 40])
            rport = struct.unpack_from(">H", blob, at + 44)[0]
            state = struct.unpack_from("<I", blob, at + 48)[0]
            pid = struct.unpack_from("<I", blob, at + 52)[0]
        rows.append(Row((norm_host(local), lport), (norm_host(remote), rport),
                        state == _MIB_TCP_STATE_LISTEN, None, pid, state == _MIB_TCP_STATE_TIME_WAIT))
    return rows


# -- readers: the live table on this host ------------------------------------------------------------------------------

_LOCK = threading.Lock()
#: macOS: None until the first read calibrates the sysctl layout, then True or False for this process.
_SYSCTL_OK: list = [None]


def _run(argv: list[str]) -> str:
    try:
        done = subprocess.run(argv, capture_output=True, timeout=TIMEOUT_SECONDS, check=False,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TableUnreadable(f"{os.path.basename(argv[0])}: {type(exc).__name__}") from None
    if done.returncode != 0:
        raise TableUnreadable(f"{os.path.basename(argv[0])}: exit {done.returncode}")
    if len(done.stdout) > MAX_TABLE_BYTES:
        raise TableUnreadable(f"{os.path.basename(argv[0])}: table over {MAX_TABLE_BYTES} bytes")
    return done.stdout.decode("utf-8", "replace")


def _sysctl_blob(name: bytes = b"net.inet.tcp.pcblist_n") -> bytes:
    try:
        import ctypes
        import ctypes.util
    except ImportError:                                              # a CPython built without libffi: netstat reads
        raise TableUnreadable("sysctl: no ctypes") from None
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    except OSError as exc:
        raise TableUnreadable(f"sysctl: libc: {type(exc).__name__}") from None
    fn = libc.sysctlbyname
    fn.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p,
                   ctypes.c_size_t]
    fn.restype = ctypes.c_int
    for _attempt in range(3):
        need = ctypes.c_size_t(0)
        if fn(name, None, ctypes.byref(need), None, 0) != 0:
            raise TableUnreadable(f"sysctl: errno {ctypes.get_errno()}")
        size = min(int(need.value * 1.25) + 4096, MAX_TABLE_BYTES)
        if need.value > MAX_TABLE_BYTES:
            raise TableUnreadable(f"sysctl: table over {MAX_TABLE_BYTES} bytes")
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(size)
        if fn(name, buf, ctypes.byref(got), None, 0) == 0:
            return buf.raw[:got.value]
        if ctypes.get_errno() != 12:                                 # ENOMEM: the table grew, ask again
            raise TableUnreadable(f"sysctl: errno {ctypes.get_errno()}")
    raise TableUnreadable("sysctl: the table kept growing")


def calibration_holds(rows: list[Row], server: tuple[str, int], client: tuple[str, int], *,
                      uid: int, pid: int) -> bool:
    """The listener and both ends of one connected pair, each exactly once, live, with their exact
    addresses and this uid and pid: what a layout must read back to be trusted."""
    def one(local, remote, listening):
        hits = [r for r in rows if r.local == local and r.remote == remote and r.listening == listening
                and not r.time_wait]
        return len(hits) == 1 and hits[0].uid == uid and hits[0].pid == pid
    return (one(server, ("*", 0), True) and one(server, client, False) and one(client, server, False))


_CHILD_LISTENER = ("import socket,sys\ns=socket.socket();s.bind(('127.0.0.1',0));s.listen(1)\n"
                   "print(s.getsockname()[1],flush=True);sys.stdin.read()")


def _child_line(child: "subprocess.Popen[bytes]", deadline: float) -> Optional[bytes]:
    """The child's first line, or None when no newline came by `deadline`. It waits with `selectors` (kqueue on
    macOS: no FD_SETSIZE ceiling at fd 1024, which `select.select` refuses) and reads what is there, so a partial line
    from an interpreter that then waits cannot hold the caller past the deadline (FAA-273 item 13, and the `selectors`
    half of item 11)."""
    import selectors  # POSIX: this reader runs on macOS alone
    got = b""
    try:
        with selectors.DefaultSelector() as sel:
            sel.register(child.stdout, selectors.EVENT_READ)
            while b"\n" not in got and len(got) < 64:
                left = deadline - time.monotonic()
                if left <= 0 or not sel.select(left):
                    return None
                chunk = os.read(child.stdout.fileno(), 64)
                if not chunk:
                    return None
                got += chunk
    except (OSError, ValueError):
        return None
    return got.split(b"\n", 1)[0] if b"\n" in got else None


def _child_listener_seen(rows_of) -> Optional[bool]:
    """Whether the table shows a listener of a child process of this one: False when it does not (the table shows
    this process alone, FAA-267), None when no child could be started (a frozen or embedded host has no interpreter to
    start), or it gave no port line within TIMEOUT_SECONDS (silence, a partial or non-numeric line, an early exit, a
    pipe that cannot be read). The calibration trusts only True."""
    if not sys.executable or getattr(sys, "frozen", False):
        return None
    try:
        child = subprocess.Popen([sys.executable, "-I", "-c", _CHILD_LISTENER], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    deadline = time.monotonic() + TIMEOUT_SECONDS
    port = None
    try:
        line = _child_line(child, deadline)
        if line is None or not _ascii_digits(line.strip()):
            return None
        port = int(line.strip())
        try:
            return any(r.listening and r.local == ("127.0.0.1", port) and r.pid == child.pid for r in rows_of())
        except (TableUnreadable, OSError, struct.error, ValueError):
            return False
    finally:
        # One deadline for the whole check: a child that gave no port is killed at once, and one that did gets what is
        # left of the deadline to exit on its closed stdin before it is killed.
        try:
            child.stdin.close()
            if port is None:
                child.kill()
            child.wait(timeout=max(0.0, deadline - time.monotonic()))
        except (OSError, subprocess.TimeoutExpired):
            child.kill()
            child.wait()
        child.stdout.close()


def _calibrate_sysctl() -> bool:
    """Open a connected pair of this process's own (listen, connect, accept) and read it back
    (`calibration_holds`), then require a child process's listener in the table too: a table that shows this process
    alone (FAA-267) would pass the first check and find nobody else. A layout that does not hold is never trusted in
    this process, and `netstat` answers instead."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client = accepted = None
    try:
        probe.bind(("127.0.0.1", 0))
        probe.listen(1)
        client = socket.create_connection(probe.getsockname(), timeout=TIMEOUT_SECONDS)
        accepted, _ = probe.accept()
        rows = parse_pcblist_n(_sysctl_blob())
        if not calibration_holds(rows, _address(probe.getsockname()), _address(client.getsockname()),
                                 uid=_posix_uid(), pid=os.getpid()):
            return False
        return _child_listener_seen(lambda: parse_pcblist_n(_sysctl_blob())) is True
    except (TableUnreadable, OSError, struct.error, ValueError):
        return False
    finally:
        for s in (client, accepted, probe):
            if s is not None:
                s.close()


def method() -> str:
    """The method the next read on this host uses: sysctl, netstat, proc, iphlpapi or none."""
    if sys.platform == "darwin":
        with _LOCK:
            if _SYSCTL_OK[0] is None:
                _SYSCTL_OK[0] = _calibrate_sysctl()
            return "sysctl" if _SYSCTL_OK[0] else "netstat"
    if sys.platform.startswith("linux"):
        return "proc"
    if sys.platform == "win32":
        return "iphlpapi"
    return "none"


def read_table() -> tuple[list[Row], str]:
    """The host's TCP sockets and the method that read them; TableUnreadable with the reason."""
    how = method()
    if how == "sysctl":
        try:
            return parse_pcblist_n(_sysctl_blob()), how
        except (TableUnreadable, struct.error, ValueError):
            how = "netstat"                                          # this read only; calibration stands
    if how == "netstat":
        try:
            text = _run([NETSTAT, "-anv", "-p", "tcp"])
        except TableUnreadable as exc:
            # A netstat that fails, exits non-zero or times out is a restricted table (DEC-0155 RT-1, FAA-312).
            raise TableUnreadable(f"{TABLE_RESTRICTED}: {exc}") from None
        return parse_netstat(text), how
    if how == "proc":
        rows: list[Row] = []
        for name, family in (("/proc/net/tcp", socket.AF_INET), ("/proc/net/tcp6", socket.AF_INET6)):
            try:
                with open(name, "rb") as fh:
                    raw = fh.read(MAX_TABLE_BYTES + 1)
            except FileNotFoundError:
                continue                                             # no IPv6 on this kernel
            except OSError as exc:
                raise TableUnreadable(f"proc: {type(exc).__name__}") from None
            if len(raw) > MAX_TABLE_BYTES:
                raise TableUnreadable(f"proc: table over {MAX_TABLE_BYTES} bytes")
            rows += parse_proc_net_tcp(raw.decode("ascii", "replace"), family=family)
        return rows, how
    if how == "iphlpapi":
        return _windows_table(), how
    raise TableUnreadable("unsupported-platform")


def resolve(row: Row, how: str) -> Owner:
    """The owner of one selected row: its uid when the table carried one, else the pid's."""
    if sys.platform == "win32" and how == "iphlpapi":
        return _windows_owner(row.pid, how)
    if row.uid is not None:
        return classify(row.uid, row.pid, method=how)
    if row.pid is None or row.pid <= 0:
        return Owner(UNKNOWN, None, row.pid, how, "no-pid")
    if row.pid == 1:
        return Owner(SYSTEM, None, 1, how)
    try:
        uid = parse_ps_uid(_run([PS, "-o", "uid=", "-p", str(row.pid)]))
    except TableUnreadable as exc:
        return Owner(UNKNOWN, None, row.pid, how, f"ps: {exc}")
    if uid is None:
        return Owner(UNKNOWN, None, row.pid, how, "process-gone")
    return classify(uid, row.pid, method=how)


# -- Windows ----------------------------------------------------------------------------------------------------------

def _windows_table() -> list[Row]:  # pragma: no cover - exercised on Windows only
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        raise TableUnreadable("iphlpapi: no ctypes") from None
    iphlpapi = ctypes.WinDLL("iphlpapi")
    fn = iphlpapi.GetExtendedTcpTable
    fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL, wintypes.ULONG,
                   ctypes.c_int, wintypes.ULONG]
    fn.restype = wintypes.DWORD
    rows: list[Row] = []
    for family in (socket.AF_INET, socket.AF_INET6):
        size = wintypes.DWORD(0)
        fn(None, ctypes.byref(size), False, family, 5, 0)            # 5: TCP_TABLE_OWNER_PID_ALL
        for _attempt in range(3):
            if size.value > MAX_TABLE_BYTES:
                raise TableUnreadable(f"iphlpapi: table over {MAX_TABLE_BYTES} bytes")
            buf = ctypes.create_string_buffer(max(size.value, 4))
            code = fn(buf, ctypes.byref(size), False, family, 5, 0)
            if code == 0:
                rows += parse_windows_tcp_table(buf.raw[:size.value], family)
                break
            if code != 122:                                          # ERROR_INSUFFICIENT_BUFFER
                raise TableUnreadable(f"iphlpapi: error {code}")
        else:
            raise TableUnreadable("iphlpapi: the table kept growing")
    return rows


#: Accounts of the system itself: LocalSystem, LocalService, NetworkService.
_SYSTEM_SIDS = frozenset({"S-1-5-18", "S-1-5-19", "S-1-5-20"})


def _windows_sid(pid: Optional[int]) -> str:  # pragma: no cover - exercised on Windows only
    """The account SID of a process (None: this one). Raises OSError when it cannot be read."""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        raise OSError("no ctypes") from None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD)]
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    if pid is None:
        process, close = kernel32.GetCurrentProcess(), False
    else:
        process = kernel32.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
        close = True
        if not process:
            raise OSError(ctypes.get_last_error(), "OpenProcess")
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(process, 0x0008, ctypes.byref(token)):   # TOKEN_QUERY
            raise OSError(ctypes.get_last_error(), "OpenProcessToken")
        try:
            size = wintypes.DWORD(0)
            advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))   # TokenUser
            buf = ctypes.create_string_buffer(max(size.value, 1))
            if not advapi32.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
                raise OSError(ctypes.get_last_error(), "GetTokenInformation")
            sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]            # TOKEN_USER.User.Sid
            text = wintypes.LPWSTR()
            if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
                raise OSError(ctypes.get_last_error(), "ConvertSidToStringSidW")
            try:
                return str(text.value)
            finally:
                kernel32.LocalFree(text)
        finally:
            kernel32.CloseHandle(token)
    finally:
        if close:
            kernel32.CloseHandle(process)


def classify_sid(sid: Optional[str], pid: Optional[int], *, own_sid: str, method: str = "iphlpapi") -> Owner:
    """Windows: the System process and the system's own accounts are `system`, this process's
    SID `this-account`, any other SID `another-account`, an unreadable one `unknown`."""
    if pid in (0, 4):
        return Owner(SYSTEM, None, pid, method)
    if sid is None:
        return Owner(UNKNOWN, None, pid, method, "process-not-readable")
    if sid == own_sid:
        return Owner(THIS_ACCOUNT, None, pid, method)  # before the system SIDs: a client running as SYSTEM
    if sid in _SYSTEM_SIDS:
        return Owner(SYSTEM, None, pid, method)
    return Owner(ANOTHER_ACCOUNT, None, pid, method)


def _windows_owner(pid: Optional[int], how: str) -> Owner:  # pragma: no cover - exercised on Windows only
    try:
        own = _windows_sid(None)
    except OSError as exc:
        return Owner(UNKNOWN, None, pid, how, f"own-sid: {exc.args[-1] if exc.args else type(exc).__name__}")
    if pid in (0, 4):
        return classify_sid(None, pid, own_sid=own, method=how)
    try:
        sid = _windows_sid(pid)
    except OSError:
        sid = None
    return classify_sid(sid, pid, own_sid=own, method=how)


# -- the questions ----------------------------------------------------------------------------------------------------

def restricted(rows: list[Row], how: str, *, own_uid: Optional[int] = None, own_pid: Optional[int] = None) -> bool:
    """DEC-0155 RT-1 (FAA-312): a macOS table holding no row of another uid (sysctl, which carries uids) or of another
    process (netstat, which carries pids) is restricted, and a missing row proves nothing. Never on Linux or Windows."""
    if how == "sysctl":
        own = _posix_uid() if own_uid is None else own_uid
        return not any(row.uid is not None and row.uid != own for row in rows)
    if how == "netstat":
        own = _own_pid() if own_pid is None else own_pid
        return not any(row.pid is not None and row.pid != own for row in rows)
    return False


def find(rows: list[Row], local: tuple[str, int], remote: tuple[str, int]) -> list[Row]:
    """The live connected rows with exactly this local and remote address: one, or the caller
    cannot tell. A TIME_WAIT row is a connection already closed and is left out. A row printed twice is one
    socket: Linux resumes a `/proc` read that sockets came and went under by position, and can print the same
    row again (0.74.0 seam reading 6); rows equal in every field count once."""
    return list(dict.fromkeys(row for row in rows
                              if not row.listening and not row.time_wait and row.local == local
                              and row.remote == remote))


def _owner_of(local: tuple[str, int], remote: tuple[str, int], server: bool = False) -> Owner:
    for _ in range(2):
        try:
            rows, how = read_table()
        except TableUnreadable as exc:
            return Owner(UNKNOWN, None, None, method(), str(exc))
        found = find(rows, local, remote)
        if how != "proc" or len(found) == 1:
            break
        # A /proc read under churn can skip a row or print one twice; one more read before answering unknown.
    if not found:  # a macOS table without the reader's own connection is restricted (DEC-0155 RT-1)
        return Owner(UNKNOWN, None, None, how, NO_ROW_RESTRICTED if how in ("sysctl", "netstat") else "no-row")
    if len(found) > 1:
        return Owner(UNKNOWN, None, None, how, "several-rows")
    if how == "proc" and server and found[0].uid is None:
        # Linux: a connection not accept()ed yet (uid 0, inode 0) belongs to the listener on its local address (exact,
        # else the wildcard) and dies with it (inet_csk_listen_stop); an accepted one's own row carries the accepting
        # process's uid (sock_graft), so a listener swapped after another account accepted cannot pass (Observatory's
        # 1.2.0, board thread ced00f6e; CT-254). An orphaned server row reads so too: nothing sent to it reaches anyone.
        return _one_owner(_listeners_of(rows, found[0].local), how, "not-accepted")
    if how == "proc" and found[0].uid is None:
        # A client's socket with inode 0 has already closed (0.74.0 unit reading 4): never another socket's owner.
        return Owner(UNKNOWN, None, None, how, "closed")
    return resolve(found[0], how)


def _listeners_of(rows: list[Row], local: tuple[str, int]) -> list[Row]:
    """The listeners that took a connection to `local`: on its exact address, else the wildcard."""
    for host in (local[0], "*"):
        hits = [row for row in rows if row.listening and row.local == (host, local[1])]
        if hits:
            return hits
    return []


def _one_owner(found: list[Row], how: str, none_reason: Optional[str] = None) -> Owner:
    """The owner of the rows a question selected: one row, or several of one owner (SO_REUSEPORT workers, an IPv4 and
    an IPv6 socket of one process). Several owners cannot be told apart: unknown (several-rows)."""
    if not found:
        return Owner(UNKNOWN, None, None, how, none_reason) if none_reason else Owner(NONE, None, None, how)
    keys = {(row.uid, row.pid) for row in found}
    uids = {row.uid for row in found}
    if len(keys) == 1 or (None not in uids and len(uids) == 1):
        return resolve(found[0], how)
    return Owner(UNKNOWN, None, None, how, "several-rows")


def peer_at(server: tuple, client: tuple) -> Owner:
    """The owner of the CLIENT socket of the connection between `server` and `client`, as a server sees them (its own
    address, the peer's): the row whose local address is the client's and whose remote address is the server's."""
    return _owner_of(_address(client), _address(server))


def peer(sock: socket.socket) -> Owner:
    """For a server's accepted socket: who connected. Reads nothing from `sock`."""
    try:
        server, client = sock.getsockname(), sock.getpeername()
    except OSError as exc:
        return Owner(UNKNOWN, None, None, "none", f"socket: {type(exc).__name__}")
    return peer_at(server, client)


def server_end(sock: socket.socket) -> Owner:
    """For a client's connected socket: who accepted it. The row whose local address is the server's and whose remote
    address is this socket's own, which is the server process's accepted socket, so a listener swapped after `listen`
    cannot pass for the one that answers. On Linux a connection not yet accept()ed has no owner of its own (inode 0):
    its listener answers (the contract's CT-254, HA-2's Linux source)."""
    try:
        own, server = sock.getsockname(), sock.getpeername()
    except OSError as exc:
        return Owner(UNKNOWN, None, None, "none", f"socket: {type(exc).__name__}")
    return _owner_of(_address(server), _address(own), server=True)


#: port -> (time.monotonic() of the read, the Owner)
_LISTENERS: dict[int, tuple[float, Owner]] = {}

#: The binds that shadow a connection to 127.0.0.1, most specific first.
_LISTEN_ORDER = ("127.0.0.1", "*", "::1")


def pick_listener(rows: list[Row], port: int) -> list[Row]:
    """The listeners a connection to 127.0.0.1:<port> reaches: those on the most specific bind
    that has any. More than one (a port reused by two sockets) cannot be told apart."""
    for host in _LISTEN_ORDER:
        hits = [row for row in rows if row.listening and row.local == (host, port)]
        if hits:
            return hits
    return []


def listener(port: int) -> Owner:
    """Who listens on 127.0.0.1:<port>, or on 0.0.0.0 or ::1, which take the same connections. `none` when nothing does,
    `unknown` (`several-rows`) when sockets of two owners do. Cached for LISTENER_TTL seconds."""
    now = time.monotonic()
    hit = _LISTENERS.get(port)
    if hit is not None and now - hit[0] < LISTENER_TTL:
        return hit[1]
    try:
        rows, how = read_table()
    except TableUnreadable as exc:
        owner = Owner(UNKNOWN, None, None, method(), str(exc))
    else:
        owner = _restricted_listener(rows, port, how) if restricted(rows, how) else _one_owner(pick_listener(rows, port), how)
    _LISTENERS[port] = (now, owner)
    return owner


def _restricted_listener(rows: list[Row], port: int, how: str) -> Owner:
    """DEC-0155 RT-4 (FAA-312): under a restricted table only this account's own bind on exactly 127.0.0.1 is its own."""
    owner = _one_owner([row for row in rows if row.listening and row.local == ("127.0.0.1", port)], how)
    reason = f"{TABLE_RESTRICTED}: no listener of this account on exactly 127.0.0.1:{port}"
    return owner if owner.kind == THIS_ACCOUNT else Owner(UNKNOWN, None, None, how, reason)


def refusal(owner: Owner, port: int, expect_pid: Optional[int] = None) -> Optional[tuple[str, str]]:
    """(code, why) when a client must not send on a connection whose server end is `owner`."""
    if owner.kind in (ANOTHER_ACCOUNT, SYSTEM):
        return SERVER_NOT_OWN, f"the server on port {port} belongs to {owner.kind}"
    if owner.kind != THIS_ACCOUNT:
        return SERVER_UNVERIFIED, f"the owner of the server on port {port} could not be read ({owner.reason})"
    if expect_pid is not None and owner.pid is not None and owner.pid != expect_pid:
        return SERVER_NOT_THIS_WORKSPACE, (f"the server on port {port} is pid {owner.pid}, "
                                           f"not the expected pid {expect_pid}")
    return None


def pid_listens(pid: int, port: int) -> bool:
    """macOS, when the socket table is restricted (FAA-267, DEC-0155 RT-3): whether process `pid`, this account's,
    listens on exactly 127.0.0.1:<port> (never the IPv4 wildcard, which `lsof` prints as it prints an IPv6-only one, nor
    ::1; FAA-312). `lsof -p` asks the process itself (libproc), which the restriction does not hide. Only a caller that
    started `pid` itself (a launchd job it installed) may vouch with it, and never a set-uid one."""
    if sys.platform != "darwin" or not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1 or _set_uid():
        return False
    try:
        uid = parse_ps_uid(_run([PS, "-o", "uid=", "-p", str(pid)]))
        if uid is None or uid != _posix_uid():
            return False
        out = _run([LSOF, "-nP", "-a", "-p", str(pid), "-i4TCP", "-sTCP:LISTEN", "-Fn"])
    except TableUnreadable:
        return False
    return any(host == "127.0.0.1" and p == port for host, p in parse_lsof_listeners(out))


class CheckedHTTPConnection(http.client.HTTPConnection):
    """An `http.client.HTTPConnection` whose every `connect()` checks the server end before returning: `http.client`
    connects again by itself (`auto_open`) after `Connection: close` or a close, and that connection may reach another
    listener. A refused connect closes the socket and raises ListenerRefused before any byte of a request is sent."""

    def __init__(self, host: str, port: int, *, expect_pid: Optional[int] = None, timeout: float = 10.0,
                 vouch_pid: Optional[int] = None) -> None:
        super().__init__(host, port, timeout=timeout)
        self.expect_pid = expect_pid
        self.vouch_pid = vouch_pid

    def set_tunnel(self, *args, **kwargs):  # noqa: D401 - a tunnel would put a proxy's socket under the check
        raise ListenerRefused(SERVER_UNVERIFIED, "a tunnel would check the proxy, not the server; nothing was sent")

    def connect(self) -> None:
        super().connect()
        owner = server_end(self.sock)
        if (owner.kind == UNKNOWN and (owner.reason or "").startswith(TABLE_RESTRICTED) and getattr(self, "vouch_pid", None)
                and pid_listens(self.vouch_pid, self.port)):
            # The table hides other processes (FAA-267); the process this caller started holds the listener.
            owner = Owner(THIS_ACCOUNT, _posix_uid(), self.vouch_pid, "lsof-pid")
        refused = refusal(owner, self.port, self.expect_pid)
        if refused is not None:
            self.close()
            raise ListenerRefused(refused[0], f"{refused[1]}; nothing was sent", owner)


def own_connection(port: int, *, expect_pid: Optional[int] = None, timeout: float = 10.0,
                   host: str = "127.0.0.1", vouch_pid: Optional[int] = None) -> CheckedHTTPConnection:
    """A `CheckedHTTPConnection` to `host:port`, connected, whose server end is this account's (and, with `expect_pid`,
    that process's). The check runs on the very connection the caller then sends on, so no listener can change between
    the check and the request, and again on every reconnect `http.client` makes. No proxy is consulted. Raises
    ListenerRefused after closing the connection:

        server-not-own             another account's or the system's process accepted it
        server-unverified          its owner could not be told (nothing is sent: fail closed)
        server-not-this-workspace  this account's process, but not the pid expected

    `vouch_pid`, as on `CheckedHTTPConnection` and the Node twin's `checkedSocket`: a pid the caller started (FAA-267)."""
    conn = CheckedHTTPConnection(host, port, expect_pid=expect_pid, timeout=timeout, vouch_pid=vouch_pid)
    conn.connect()
    return conn


def main(argv: Optional[list] = None) -> int:
    """`listener <port> [--json]`: the kind of who listens on 127.0.0.1:<port>, which the dashboard link gate takes as
    `listener_owner` (FAA-315), or the whole owner as JSON; exit 2 on a usage error."""
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = args[2:] == ["--json"]
    if len(args) != 2 + as_json or args[0] != "listener" or not _ascii_digits(args[1]) or not 0 < int(args[1]) < 65536:
        print("usage: fabric_peer_owner.py listener <port> [--json]", file=sys.stderr)
        return 2
    owner = listener(int(args[1]))
    print(json.dumps(owner.as_dict()) if as_json else owner.kind)
    return 0


if __name__ == "__main__":
    sys.exit(main())
