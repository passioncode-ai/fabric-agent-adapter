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

## What was not measured

- A Homebrew Node on macOS 27.2 (the Node twin always reads `netstat`; it is ad-hoc-signed too).
- The release's final form: the lsof call asks for IPv4 alone (`-i4TCP`) and a calibration child that does not answer
  within the timeout proves nothing; both are covered by unit tests on an unrestricted host (Darwin 25.6), not by a
  rerun on macOS 27.2.
- That the installer reads the job's pid only after a `table-restricted` answer (`ccbe22b0`): the measured build read
  it on every poll. Unit tests cover the new order.
- The cost of the calibration child per process. Its time was read only on an unrestricted Mac under load, with no
  record kept, so no figure is given here.
