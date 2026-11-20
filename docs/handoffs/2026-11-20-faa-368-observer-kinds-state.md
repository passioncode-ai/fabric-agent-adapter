# FAA-368: observer channel kinds and the state file (2026-11-20)

- Objective: Fabric's board request `da5a75a2` (thread `088aaa1b`), parts 1 and 2 of Fabric CO-598: channel kinds
  `agent-session`, `work-queue`, `consumer-repo`, `board-thread` in `observing-products`, and `docs/observer/state.json`
  read first by a session started in place of a dead one.
- Done (0.100.0): `observer_inventory.py` (`KINDS`, `check_state`, `state`, `state-template`),
  `references/channels.md` (the four kinds, section "The state file"), `references/cycle.md` (step 2 and 8),
  `SKILL.md` (setup steps 1, 5, 7; the consumers' audit; finish line), `references/when-to-use.md`,
  `test/test_observer_inventory.py` class `StateFile`, three scenario evals, FAA-368 in `docs/backlog.md`.
- Checks run: `python3 -m unittest discover -s test`, `python3 test/validate.py`, `node --test 'test/*.test.mjs'`,
  both `claude plugin validate --strict`. The sample's own state file (sound-engine `docs/observer/state.json`)
  checked with the new `state` command: 10 problems, all real (closed waits without their evidence, open waits
  without a watcher); left for sound-engine's observer to fix, reported in the thread.
- Decisions: wait fields accept the sample's synonyms (`watcher` for `watch`, `next` for `then`, `owner` for `source`,
  `state` for `status`) so existing state files need no rename; the project may prefix the schema
  (`<name>.observer-state/1`) and keep its own top-level fields. A `consumer-repo` read is read-only through the
  product's lint; the skill's earlier "never from their repositories" now reads "never edited".
- Open: parts 3 (the pipeline as a Fabric object) and 4 (a strategy amendment as a record) stay with Fabric in CO-598.
- Next task: the next board request addressed to fabric-agent-adapter, or FAA-367.
