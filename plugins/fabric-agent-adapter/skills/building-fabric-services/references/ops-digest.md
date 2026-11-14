# Operations digests: a service's own hourly and daily counts

The contract's DEC-0153 ([ops-digest.md at the pin](https://github.com/passioncode-ai/fabric-agent-contract/blob/91c031c464695ae9661c12f97ce1e5dc3cb5448c/docs/specification/ops-digest.md))
asks every product to count its own operations log and keep two kinds of lines on its own machine: one
`ops.digest.hourly@1` line for each hour it observed itself running in, an empty one included, and one
`ops.digest.daily@1` line for each closed UTC day that has hourly lines. No model reads the log; the fold is
arithmetic. The kit's module is `fabric_ops_digest.py` and its Node twin `fabric-ops-digest.mjs` (FAA-206 part 2).

## Use it

```python
from fabric_ops_digest import OpsDigest, ops_digest_extension, outcome_of

digests = OpsDigest(paths["data"] / "digests")   # a folder inside the data folder, made 0700
digests.start()                                   # writes the hour the last run kept, folds missed days
digests.record("mcp.tools/call", "ok")            # each record of the log, before the log samples it (OD-3)
digests.record("board.tick", outcome_of(word, {"timeout": "failed", "denied": "unknown"}))
digests.tick()                                    # once a minute or so: an hour with a tick is written, empty if quiet
digests.flush()                                   # now and then: writes a closed hour and a closed day
digests.stop()                                    # at the drain: keeps the open hour for the next run
```

Node: `new OpsDigest(dir)`, then `start()`, `record(op, outcome)`, `tick()`, `flush()`, `stop()`; `outcomeOf`,
`opsDigestExtension`.

- **Names (OD-2).** `op` names the operation, never a value of it: a lower-case letter, then letters, digits and `_`
  in segments joined by `.`, `:`, `/` or `-`, at most 64 characters (`board.tick`, `mcp.tools/list`). A name the
  grammar refuses, or one shaped like a credential or holding a home folder (FAC-SEM-167), raises `OpsDigestError` at
  `record`, so no line every reader skips is ever written. The error names the place, never the value.
- **Outcomes (OD-3).** `ok` and `failed` count as themselves, every other word as `unknown`. A log with its own words
  maps them with `outcome_of(word, mapping)` and publishes that map in its own documentation; a setup answer (a
  missing slot, DEC-0149), a refusal or a skip is `unknown`, never `failed`, so an unfinished setup makes no rise.
- **The overflow name.** A day keeps at most 4095 named operations; the rest are counted under `ops.overflow` (pass
  `overflow=` to choose another and publish it with the outcome map).
- **Hours (OD-1).** An hour is written when it closes. Hours the service did not observe (a laptop asleep) are never
  filled. The hour the service stops in is kept in `kept-hour.json` and written at the next run, compared with the
  hour before only when that one is the last written; a restart within the same hour resumes it, so no hour has two
  lines.
- **Days (OD-5).** Each closed UTC day with hourly lines gets one daily line, at the next run if the service was not
  running when the day closed (catch-up).
- **Files (OD-6).** `hourly-YYYY-MM.jsonl` and `daily-YYYY-MM.jsonl`, one JSON line each, files 0600 in a 0700
  folder. `read_digests(folder, kind)` reads them as a reader does: a bad line skipped, the first line of an hour or a
  day kept.
- **Rises (OD-4, OD-8).** A rise is at least 10 failures in an hour and at least twice the hour before's (none counts
  as one); it is in the hourly line's `risen`. A service that shows findings shows each rise of its newest closed hour
  with the operation, the failures and the hour before's, never as the cause of a failure.
- **Nothing but counts (OD-7).** No log line, path, identifier or text ever enters a digest.

## Tell a collector where the daily lines are (OD-9)

A local descriptor that names `paths.data` declares the folder under its `extensions`:

```python
descriptor["extensions"] = ops_digest_extension([{"dir": "digests", "source": "app"}])
```

`ops_digest_extension` checks the grammar of `dir` (relative to the data folder, forward slashes, no `.`, `..`, `:`,
`~` or drive), home folders and credential shapes, and that each `dir` and `source` is named once. The contract's
FAC-SEM-168 (its caseless fold of `dir` among other things) stays the authority; a remote descriptor never carries the
key. A collector in the same OS account reads the daily lines and sends them on unchanged; who collects and how is
Project Observatory's, not the kit's.

## The retro after work

A host that hands sessions the `retro-after-work` obligation counts each ask as one record of the operation
`retro-after-work` (RW-4): `ok` when it saw a lesson or an `insight/1` line written, `failed` when such a write was
refused, `unknown` otherwise. working-with-fabric's hooks remind a Claude Code session; the error classes the hooks
would count wait on FAA-202.

## Checks

`fold_hour` and `fold_day` are the contract's reference folds, run in `test/test_fabric_ops_digest.py` and
`test/fabric-ops-digest.test.mjs` against the contract's vectors (`test/fixtures/ops-digest/vectors.json`);
`ops_digest_rules` is FAC-SEM-166 and FAC-SEM-167, run against the contract's positive and semantic fixtures
(`test/fixtures/ops-digest/rules.json`).
