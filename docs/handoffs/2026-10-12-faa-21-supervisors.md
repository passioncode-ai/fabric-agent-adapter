# Handoff — FAA-21: services on Linux and Windows in both kits (0.18.0)

**Objective.** Contract DEC-0032/DEC-0033 in the Node kit, and the systemd unit and Task Scheduler task writers
in both kits (backlog FAA-21).

**Done.**

- Writers and installers, Python and Node. They produce byte-identical files
  (`test/fabric-service-supervisors.test.mjs`, last case).
- Node kit on Windows: the folders, descriptor validation at parity with the Python kit, the token ACL and a
  named-pipe instance lock.
- Lock name shared by the kits:
  - The Python kit also holds the Node kit's lock name: an abstract socket on Linux, a named pipe on Windows.
  - `check_service.py` recognises it. Before this change, the probe failed every Node service on Linux.
- `supervised()`: a copy under systemd backs off on a held lock.
- The Windows CI job now runs the Node cases and the Python supervisor cases.
- Docs: `references/lifecycle.md` (*Linux and Windows*), `SKILL.md` step 4, `protocol.md` and AGENTS.md
  lifecycle table. The eval scenario `linux-and-windows-supervision` was written first.

**Checks run.**

- macOS: the full Python and Node suites, `test/validate.py`, `claude plugin validate --strict` on both.
- Linux, in a `node:22-bookworm` container:
  - the Node platform, supervisor, service and lifecycle files (47 pass);
  - the Python service, platform, supervisor and lifecycle modules (78 pass);
  - the cross-kit lock and probe cases.
- Mutation testing: 14 planted defects in the Python writers, 23 in the Node port and 7 in the lock name and
  probe were each caught.
- Windows, in validate run [38199737609](https://github.com/passioncode-ai/fabric-agent-adapter/actions/runs/38199737609),
  all jobs green:
  - The real `schtasks` created, read back and deleted the kit's task.
  - The lock excludes across the kits in both directions, and the probe sees a live Node service.
  - The Node token ACL: written and read back, a grant to everyone refused by SID, an explicit grant dropped.
  - 41 Node cases and 23 + 50 + 14 Python cases.
- Linux: `systemd-analyze verify` accepts the unit. A planted quoted `WorkingDirectory=` fails it.

**Review and the first Windows run.**

- An independent review found 2 critical and 9 moderate defects. All are fixed with tests except one, which is
  documented.
  - The task `<Settings>` element order.
  - A quoted `WorkingDirectory=`: `systemd-analyze` refuses it.
  - `%` left unescaped in `Description`.
  - An upgrade did not restart the running service, and an install re-enabled what the operator had disabled
    (LC-14).
  - `icacls` kept explicit entries.
  - The ACL was set after the bytes were written.
  - An fd leak.
  - The probe took the lock's name.
  - Node accepted `/x` on Windows.
  - Not fixed, documented instead: a task cannot set the supervisor variable.
- The first `windows` run failed on the pipe's instance limit (`ERROR_PIPE_BUSY`). The pipe now has unlimited
  instances, as libuv's does, and 231 counts as held.
- Two later runs failed on test paths that only work on POSIX: a `Path` printed with backslashes, and an ESM
  import from `D:\…`. Both tests are fixed. The unit writer now takes the POSIX form of a `Path`.

**Decisions.**

- Node on Windows reads ACLs through Windows PowerShell 5.1 (.NET, `PSModulePath` dropped) and writes them with
  `icacls`. The path goes through the environment, never argv.
- A Task Scheduler task cannot set an environment variable, so a copy it restarts does not back off.
  `IgnoreNew` covers the scheduler's own copies.
- `loginctl enable-linger` is the operator's decision. The installer never runs it.

**Open.** Nothing from FAA-21. The next tasks are FAA-26…29, which are blocked on contract §12 and Fabric.
FAA-10…13 and FAA-04/05 are deferred or blocked as their rows say.

**Next task.** Re-pin the passioncode launcher to v0.18.0 and update the local install. Then re-read the
backlog for an unblocked row.
