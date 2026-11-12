# FAA-292: the accepted socket through libproc (DEC-0155 RT-2), deferred to a module of its own

Written 2026-11-12 in wave 4 of the backlog sweep (branch `agent/faa-w4b`), beside FAA-312's DEC-0155 debts. The row
stays open; this records why its code was not written in this wave and how it will be.

## Decision

The kit does not port Project Observatory's `peer_owner` 1.3.1 into `fabric_peer_owner` in this wave. RT-2 (the
server end of the connection found among this account's own descriptors) arrives as a **new L0 kit module of its
own** in both twins, with `fabric_peer_owner`'s RT-3 vouch kept as the fallback when it finds nothing or its
calibration fails:

- Python: libproc through ctypes (`proc_listpids` for this uid, `proc_pidinfo(PROC_PIDLISTFDS)`,
  `proc_pidfdinfo(PROC_PIDFDSOCKETINFO)`), calibrated on a connected pair of its own as the sysctl reader is, refused
  in a set-uid context, as Observatory's 1.3.1 does.
- Node: no ctypes and no native dependency, so the twin reads RT-2's other named source,
  `lsof -nP -iTCP:<port> -sTCP:ESTABLISHED -F pun`, matching the exact address pair and the numeric uid (Fabric's
  client does the same, DEC-0155 Compatibility). The twins then agree on answers, not on the program they run.

## Why not now

| Fact | Evidence |
|---|---|
| `fabric_peer_owner.py` is at the kit's line cap after FAA-312 and FAA-315 | `wc -l` prints 1000; `test/test_fabric_kit.py` `MAX_LINES = 1000`, and `OVERSIZE` may only grow with a row that splits the module |
| Observatory's 1.3.1 alone is 1142 lines, its libproc reader and calibration about 200 of them | `wc -l` and `grep -n '^def '` of `observatory/engine/peer_owner.py` at `a69c6fee` (sha256 `b3831e5f1026a1d93d27aa8b54926dcc62a78267b87ad51fec7461c92c9826b5`, the row's) |
| A new kit module needs `kit.json` rebuilt, which `fabric_kit.py build` refuses while `kit.json`'s version is a released tag | `fabric_kit.py build`: "kit.json's version 0.81.0 is released (tag v0.81.0): move its "version" to the next release" |
| The Node twin cannot call libproc without a native module, which the kit's Node 18+ standard-library rule forbids | `AGENTS.md`, Local rules; `fabric-peer-owner.mjs` header |

## What this wave did instead (FAA-312)

The DEC-0155 readings that need no libproc: a `netstat` that fails reads `table-restricted` (RT-1); a table holding no
row of another uid (sysctl) or process (netstat), and a macOS table without the reader's own connection, read
`table-restricted` (RT-1); under it `listener` reads this account's listener as its own only on exactly `127.0.0.1`
(RT-4); the vouch takes exactly `127.0.0.1` (RT-3) and nothing from a set-uid reader. One difference from Observatory's
`restricted()`: a netstat row with no readable pid is not taken as another process's row here (fail closed: such a
table reads restricted).

## Next task

Open the new module with the version moved: `fabric_socket_proof.py` and `fabric-socket-proof.mjs` (L0, listed before
`fabric_peer_owner` in `kit.json`), tests first over a captured `socket_fdinfo` blob and an `lsof -F pun` text, then
`server_end` and `CheckedHTTPConnection` try RT-2 before the vouch, and `PEER_OWNER_VERSION` names Observatory's
1.3.1 line. Decide there whether `fabric_peer_owner` imports the new module (it then stops being one file a project
vendors alone, which its header promises) or its callers ask both.
