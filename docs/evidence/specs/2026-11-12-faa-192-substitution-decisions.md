# FAA-192 items 14 and 27: the adapter's substitutions, recorded as decisions

Date: 2026-11-12. Row: FAA-192 (docs/backlog.md), items (14) and (27), from 0.59.0's product readings r2 and r5.
The row asked for these to be recorded on board thread `d3c8ff24`; that thread is not readable by this project
(`com.list` answers `not_authorized`), so they are recorded here, in the repository that made them, and the row
cites this file.

## Decision 1 (item 14): the release check

- **The operator's words** name `org-transfer-audit` as the release check, "aimed at Heroku".
- **What the adapter ships instead:** `adapting-projects-to-fabric/scripts/fabric_source_check.py`, which reads a
  project's source tree for its own instance data (keys, home paths, hosts) by path, line and column, never the
  value, and reads no Git history; plus three placement exceptions (a service placed on another machine, a cloud
  instance, a template copy) that the check names instead of failing.
- **Why:** the adapter is a public package that runs on any host, not only Heroku; a history audit belongs to the
  host that holds the history (a transfer between accounts), while the source check runs where the agent is built.
  The two are complementary: an organization that moves a repository between accounts still runs its own
  `org-transfer-audit` on the move.
- **Reversible:** a later Fabric or Observatory release check can call `fabric_source_check.py check --json` as one
  of its steps.

## Decision 2 (item 27): where an agent keeps its data

- **The operator's words** name an `<agent>-data` folder or repository beside the agent.
- **What the adapter ships instead:** the kit's folders (`fabric_paths`: the per-user data folder of the platform,
  and a durable store the service names) and, for records that must survive a machine, a store the service
  declares; a sibling `../<agent>-data` stays allowed when the project declares it.
- **Why:** a relative sibling folder depends on an unstated base and two copies of one agent would share it
  (item 4 of the same row), against "a copy never connects to the other copy's data"; the platform folder is per
  user and per instance.
- **Reversible:** a project that wants the sibling folder declares it in its `fabric.source.json` slots.
