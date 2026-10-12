---
report:
  id: fabric-agent-adapter/2026-10-13-faa-38-windows-exit75
  title: "The Task Scheduler does not restart a task whose action exits 75"
  kind: measurement
  project: fabric-agent-adapter
  domains: [lifecycle, windows]
  as_of: 2026-10-13
  status: active
  valid_until: 2027-04-13
  summary: >-
    A per-user Scheduled Task written by the kit's task_xml and installed by task_install
    (RestartOnFailure every minute, IgnoreNew, InteractiveToken), whose action exits 75,
    started once and was not restarted in 260 s: Last Result 75, status Ready. The receipt
    contract CT-18 and service.md One copy wait on (FAA-38).
---

# The Task Scheduler does not restart a task whose action exits 75

**Question** (contract CT-18; service.md *One copy*, DEC-0057 *Why*): does the Task Scheduler's `RestartOnFailure`
count an action that exits 75 as a failure and restart it?

**Answer: no.** On `windows-latest`, a task installed exactly as the kit writes one ran once, exited 75, and was not
restarted within 260 s — four restart intervals of one minute.

| Measured | Value |
|---|---|
| Run | [38318280259](https://github.com/passioncode-ai/fabric-agent-adapter/actions/runs/38318280259), workflow `windows-restart-receipt.yml` at `9e5486b`, 2026-10-12 22:43–22:48 UTC |
| Task | `\PassionCode\faa38-receipt-398761ae`, from `task_xml` + `task_install` (logon trigger, `InteractiveToken`, `LeastPrivilege`, `RestartOnFailure` `PT1M` × 999, `IgnoreNew`) |
| Action | the runner's Python 3.13 running a probe that appends one line per start and exits 75 |
| Starts in 260 s | 1 (at 0 s) |
| The action's arguments | `serve --fabric-supervisor task-scheduler` — the marker `task_xml` writes (FAA-32) arrived |
| `Last Result` / `Status` | `75` / `Ready` |
| Task removed afterwards | yes |

Raw receipt: [raw/windows-restart-receipt.json](raw/windows-restart-receipt.json). The script:
[test/windows_restart_receipt.py](../../../test/windows_restart_receipt.py).

## What it means

- `RestartOnFailure` restarts a task that fails to **start**, not one whose action ends with a non-zero code. A Task
  Scheduler copy that exits 75 stays down until its next trigger (the next logon), so for that supervisor the
  in-process wait is the only recovery: a marked copy (`--fabric-supervisor task-scheduler`, written since 0.23.0)
  waits up to 300 s for the holder and takes the lock when it leaves.
- A copy that still exits 75 after the wait leaves the service down until the next logon. That is the conforming
  outcome under DEC-0057 (two copies are the defect to remove), and the reason a Windows host shows the holder `ready`
  and nothing for the waiting copy.

## Limits

One run, one Windows image (`windows-latest`, 2026-10-12), an interactive-token task under the runner's account. A
task with another principal (S4U, SYSTEM) is not measured; DEC-0057 leaves those undecided.
