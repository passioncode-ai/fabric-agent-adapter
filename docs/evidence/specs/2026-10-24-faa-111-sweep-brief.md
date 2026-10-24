# Brief: FAA-111, the sweep of 2026-10-24 as 0.49.0

**Request:** the operator, 2026-10-24: «давай доделаем, проверим на ошибки и баги, испарвим недоделки и обновим доки».
Route: task-pipeline (stage 0 found no material unknown: the operator's standing «выбирай лучшие решения для меня»
decides the open choices below).

## Source ledger

| Source | What it says |
|---|---|
| `docs/backlog.md` open rows | doable now: FAA-60 (the session-start preamble in unrelated folders), FAA-88 (trigger evals not run for three skills), FAA-89 (watch-mail delays Stop-hook delivery); blocked on others: FAA-10, 26 to 29, 44, 63, 87 (the operator's `npm login`); deferred by decision: FAA-103, FAA-106; features, not unfinished work: FAA-66, FAA-67; FAA-98 below |
| handoffs 2026-10-23 and 2026-10-24 | each release's own unit reading ran; no seam or product reading covered 0.47.0 to 0.48.3 together |
| `docs/evidence/retrospectives/` | bump the version before `fabric_kit.py build`; re-run a timing test alone before calling it red; dispatch the hosted suite before the tag |
| `docs/DOCMAP.md` | the homes of each fact this sweep touches |

Contradictions: none found between the sources.

## Requirements

| REQ | What | Verified by |
|---|---|---|
| REQ-1 | Blind seam and product readings of `v0.46.1..v0.48.3`; every finding fixed or filed | the two tier reports; each fix's test seen failing first |
| REQ-2 | FAA-89: a `watch-mail` look that finds spooled turns delivers them through its own rejoin | `test_a_look_delivers_the_spooled_turns_in_the_same_rejoin` (red before) |
| REQ-3 | FAA-60: the preamble follows `project_uses_fabric`; elsewhere a one-line pointer at `fabric_whoami` | `test_a_pointer_when_running_in_a_project_without_a_sign` (red before), the scenario `pointer-in-a-project-without-fabric-signs` written first |
| REQ-4 | FAA-88: the trigger evals of the three unrun skills, recorded under `docs/evidence/evals/` | `run_evals.py` exit codes and pass rates |
| REQ-5 | The docs say what the code does | `test/validate.py`; the product reading's findings closed |
| REQ-6 | Release 0.49.0, the launcher moved | the release run, npm, the installed bytes |

## Decisions

| Id | Decision | Source |
|---|---|---|
| D1 | FAA-60: a pointer, not silence. A user-scope registration reaches every folder, and a project Fabric serves may carry no contract file; one line at `fabric_whoami` hides nothing and drops about 650 characters from every unrelated session start | the row's own constraint ("without hiding the board") |
| D2 | FAA-89: deliver, not only document. The worker's `deliver` already rejoins once, drains the spool and writes `board.json`; the look reuses it and reads the count from that file, so one rejoin serves both and the once-a-minute budget holds | the row's second option |
| D3 | FAA-98 stays open: a faithful UTS46 port is hundreds of kilobytes of Unicode tables in a standard-library-only kit, and today's gap fails closed (a host is hidden, never a credential exposed) | decision D5 of the 0.44.0 brief |
| D4 | The no-token probe reads "the document or a part of it" by shape: a `protocol` of the extension, a `service` object with an `id`, a `process` object with a `pid`; a proxy's own `service` string passes | the product reading of 0.48.3 |
| D5 | Version 0.49.0: the session start says something new in unrelated folders, and `watch-mail` delivers turns | the README's pin rule |
