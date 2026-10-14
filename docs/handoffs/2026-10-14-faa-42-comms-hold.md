# Handoff — FAA-42: repin to contract `1636fa9`; holds and the owner's settlement in the board kits (0.32.0)

## Objective

Contract CT-42 asks the adapter's kits to adopt three decisions:

- **DEC-0079, the operator's hold:** retry `held` with backoff, keep accepted work going, and read `held` in
  `com.status` and the directory.
- **DEC-0080, findings:** send and read structured findings.
- **DEC-0081, the owner's settlement:** read `settledBy`.

At the old pin (`f00a768`), a Fabric serving DEC-0079 or DEC-0081 would have blocked the responder: it refused `held`
and `settledBy` as shapes the contract does not name.

## Done

- **Repin** to `1636fa9`, with `f00a768` still supported. Vectors re-vendored; only `comms-vectors.json` changed.
  `comms-hold-vectors.json` is new.
- **`fabric_board.py` / `fabric-board.mjs`:**
  - `held` (retryable) and `settledBy` are read; directory and status `held` are read.
  - `hold_refuses` / `holdRefuses` port the contract's matrix.
  - The responder pauses a held slot with a doubling wait, never stops accepted work, and waits in `effect_begin`
    with the same key.
- **Fake board** (`test/fake_fabric_hub.py`): models holds from its own records.
- **Docs:** `references/board.md` and `working-with-fabric/references/project-board.md` (`held`, findings,
  `settledBy`).

## Not done

- **FAC-SEM-108 (a finding's shape):** no kit validates findings. The responder never sends `com.submit`, and coding
  agents send through Fabric's own `com.submit`, which checks findings. Recorded in FAA-42's row.
- **Live smoke against a Fabric serving DEC-0079:** NOT_RUN. No disposable Fabric serving it is available here; the
  fake board stands in.

## Checks run

- Python: the full suite.
- Node: the full suite.
- `validate.py`.
- `claude plugin validate --strict`, both targets.
- Privacy check.
- 30 planted defects, all caught.

The release PR lists the exact counts.

## Next task

Release 0.32.0, close FAA-42 with its receipts, and repin the launcher. FAA-41 waits on DEC-0082, contract PR #107.
