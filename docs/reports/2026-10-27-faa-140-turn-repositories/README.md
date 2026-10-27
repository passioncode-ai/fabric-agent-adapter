---
report:
  id: fabric-agent-adapter/2026-10-27-faa-140-turn-repositories
  title: "What naming a turn's other repositories costs the Stop hook"
  kind: measurement
  project: fabric-agent-adapter
  domains: [hooks, performance]
  as_of: 2026-10-27
  status: active
  valid_until: 2027-04-27
  summary: >-
    The working-with-fabric Stop hook, with the FAA-140 transcript read on, took a median 247 ms
    per turn on a 4.8 MB transcript naming six other repositories, against 109 ms for 0.52.0 on
    the same transcript in the same minute (15 runs each, this Mac, load average about 30 to 45).
---

# What naming a turn's other repositories costs the Stop hook

**Question** (FAA-140, Fabric CO-367): how much longer does the Stop hook take when it reads the transcript's tail and
resolves the other repositories a turn touched?

**Answer:** a median of 247 ms against 109 ms, well inside the hook's 5 s ceiling and the 1.5 s facts budget. The raw
log is [raw/stop-hook-timing.log](raw/stop-hook-timing.log): the hook run as Claude Code runs it (a subprocess,
`python3 -S`), 15 runs per build, the floor of `python3 -S -c pass` beside each.

**Scope.** Measured at `f3765f1`, before the read was gated: since `013369d` the hook reads no transcript until a
worker has seen the running Fabric take `repositories`, so with today's Fabric the hook costs what 0.52.0 does. The
number above is the cost once Fabric takes them. Repository names are withheld from the log. Not measured: Linux and
Windows hosts, and a transcript whose Bash commands carry long unterminated quotes (bounded since `013369d` by the
64 KB cap per turn; the unit test `TurnRepositories.test_bash_text_is_split_within_a_cap_and_never_after_the_budget`
holds it under 1.5 s).
