# Brief: FAA-102, repin to contract `0a4ce77` as 0.46.0

**Request:** the operator, 2026-10-23: «давай доделывай все сам автономно и выбирай лучшие решения для меня и в итоге
заливай все обнови доки и новая версия». The next open row with a date is FAA-102, the contract's DEC-0104 announcement
on board thread `c451a1ce` (answered *row*, due 2026-10-27). Route: task-pipeline; a repin is a compatibility change.

## Source ledger

| Source | What it says |
|---|---|
| contract `e742016..0a4ce77` (`git log`, `git diff -- schemas src`) | DEC-0104 (the agent network's S4: a directory, a call queue on `fabric.job.*`, a load report; CT-84, CT-108): `QUEUE_FULL` in `src/job-limits.ts` and `jobCallerAction` answers a job `queue-full` ended `invalid`; `agent-directory/1`, `fabric-load/0.1` (named only), `service-load/1` in `src/protocol-revisions.ts`; the `load` extension key in `src/extensions.ts` |
| `docs/specification/agent-network.md` (the duties table) | the kits at the re-pin: `jobCallerAction`, the register, and for a kit-built node that queues `jobCallerKey`, the `caller` vectors and `unknown-job` for another caller's job |
| board thread `c451a1ce` | the contract's announcement of DEC-0104 and its asks |

## Requirements

| REQ | What | Verified by |
|---|---|---|
| REQ-1 | The pin is `0a4ce77` in every live file; `e742016` is supported | `python3 test/validate.py`; `test_contract_revisions` with both checkouts installed |
| REQ-2 | Every vendored vector regenerated from the contract's functions at the pin | the generators exit 0; the diff holds only `job-limit-vectors.json` (one case) and `feed-protocols-vectors.json` (three protocols) |
| REQ-3 | `job_caller_action` / `jobCallerAction` answer a job `queue-full` ended `invalid` | `test_job_limits` and its Node twin, red on the regenerated vectors before the change |
| REQ-4 | Both protocol registers equal the contract's | `test_the_register_is_the_contracts` and its Node twin, red before |

## Decisions

| Id | Decision | Source |
|---|---|---|
| D1 | The kit does not queue in this release: no load extension, no `fabric.job.list`, no `jobCallerKey`. The duties for "a kit-built node that queues" apply only to such a node, and the line that every adopter runs `fixtures/vectors/agent-network.json` is read for the kits as the vectors their row names (the `caller` vectors, a node that queues). Building one, with a caller-side reader of a `queue-full` start refusal, waits for an agent that needs it (FAA-103). The job store refuses to end a job with `queue-full`, which the pinned schema forbids (the first blind reading) | `agent-network.md`, duties table and the adopters' line |
| D2 | No kit module keeps a list of extension keys (each module names its own key), so the contract's sixth key needs no edit | `grep -rn "extensions/" scripts` |
| D3 | `QUEUE_FULL` is exported beside `QUOTA_EXHAUSTED` from the rule layer and both facades, so a caller can name the code | the kit's own constant pattern |
| D4 | The launcher moves once, to 0.46.0, skipping a separate release for 0.45.1 hours earlier | the operator's "choose the best solutions"; one release is enough |
| D5 | Version 0.46.0: the kit admits new values | the README's pin rule |
