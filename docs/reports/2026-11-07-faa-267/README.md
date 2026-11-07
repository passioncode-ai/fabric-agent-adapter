# FAA-267: the listener-owner check on a restricted macOS socket table

report: fabric-agent-adapter / 2026-11-07 / faa-267

## What was measured

A host agent ran these, with a pre-release build of 0.76.0 (`6e0903b0`, a branch commit since rebased), on its own Mac (macOS 27.2, a per-user account, the service under its own launchd job) and
relayed the output on 2026-11-07 (14:07, 14:11 and 14:25 UTC). The account, host and agent names are left out; the
numbers and messages are as relayed.

1. **The false refusal, kit 0.74.0.** `launchd_install` of a service that was running (`launchctl` state running,
   `lsof`: `Python <pid> <account> 127.0.0.1:47480 LISTEN`, the well-known answering `ready`) raised
   `foreign-user: the owner of the server on port 47480 could not be read (no-row); nothing was sent (DEC-0154 HA-2)`.
   The same release refused `PYTHONPATH` holding the release folder under Application Support as "shaped like a
   credential" (FAA-266).
2. **The process answers for itself.** From Homebrew Python 3.15 on the same account, `launchctl print
   gui/<uid>/<label>` gave `state = running, pid = 78564`, and `/usr/sbin/lsof -nP -a -p 78564 -iTCP -sTCP:LISTEN`
   exited 0 with `TCP 127.0.0.1:47480 (LISTEN)`.
3. **The fix in place** (the two changed modules dropped into a release copy):
   - `launchd_install` from `/opt/homebrew/bin/python3` returned 0 with the well-known `ready`.
   - A root listener (`/usr/bin/python3 -m http.server 47999 --bind 127.0.0.1`, `lsof`: `Python <pid> root`):
     under Homebrew 3.15.0 (method `netstat`) refused with and without a vouch, the reason
     `table-restricted: netstat printed nothing to this process`; under `/usr/bin/python3` 3.9.6 (method `sysctl`)
     refused as `the server on port 47999 belongs to system`.
   - The service's own port: under Homebrew with the job's pid as the vouch, `ready`; without it, refused as
     `table-restricted`; under `/usr/bin/python3`, `ready` either way.
   - `method()`: `netstat` under Homebrew Python 3.15.0, `sysctl` under Apple's Python 3.9.6 (Command Line Tools).

The relayed note that the reason read `foreign-user: ... (table-restricted: ...)` is why 0.76.0 makes the installer's
refusal start with `table-restricted` itself.

## The released form on macOS 27.2

The same host agent installed the released kit (`v0.76.0`, `feefe522`) with `fabric_kit.py install` (the changed
modules: peer_owner, service, supervisors), rebuilt its service from a clean release and installed it with
`launchd_install` under Homebrew Python 3.15: ready, no false HA-2 refusal (`no-row`), `degraded` empty (relayed
2026-11-07 19:54 UTC, board thread `eefa7959`, finding `f18994d1`).

## What was not measured

- A Homebrew Node on macOS 27.2 (the Node twin always reads `netstat`; it is ad-hoc-signed too).
- The released form's parts one by one on macOS 27.2 (the IPv4-only lsof, the bounded calibration child, the pid read
  only after a `table-restricted` answer): the install above passed with all of them, but no rerun named which path
  (sysctl or netstat, vouched or not) answered; unit tests on an unrestricted host (Darwin 25.6) cover each.
- The cost of the calibration child on macOS 27.2. On an unrestricted Mac (Darwin 25.6, load average 60 to 100) the
  0.76.0 readings measured the first owner check per Python process at 48 to 97 ms under Homebrew 3.14 and 128 to
  198 ms under Apple's 3.9, against about 28 ms for 0.75.0; later checks 7 to 11 ms (FAA-273 item 17).

## FAA-266: the environment value check, measured on this repository

60,000 random base64 keys (20,000 each of 32, 48 and 64 bytes, `random.Random(2026)`), run from the worktree with
`S=plugins/fabric-agent-adapter/skills/building-fabric-services/scripts` on 2026-11-07:

```
python3 -I -c "import sys,base64,random;sys.path.insert(0,'$S');import fabric_secrets as s,fabric_supervisors as f
r=random.Random(2026);keys=[base64.b64encode(bytes(r.getrandbits(8) for _ in range(n))).decode() for n in (32,48,64) for _ in range(20000)]
print(len(keys),'keys: secret_value',sum(map(s.secret_value,keys)),'secret_argument',sum(map(s.secret_argument,keys)),'_secret_env_value',sum(map(f._secret_env_value,keys)))"
60000 keys: secret_value 59987 secret_argument 59313 _secret_env_value 59980
```

The path-aware detector alone would let 687 keys through an environment value; the rule 0.76.0 ships (path-aware only
for a value that reads as a path) lets 20 through, against the strict detector's 13.
