# Handoff — FAA-41: repin to contract `82e1636`; contexts (DEC-0082) in both estate kits (0.33.0)

**Objective.** The RM-28 pilot needs one agent to run on a machine for the person and for each organization it serves.
Contract DEC-0082 (merged at `82e1636`, [contract PR #107](https://github.com/passioncode-ai/fabric-agent-contract/pull/107))
adds `context` to placements and secret placements, FAC-SEM-110 and FAC-SEM-111. This change ports them to
`fabric_estate.py` and `fabric-estate.mjs` and releases 0.33.0.

## Done

- **Repin** `1636fa9` → `82e1636` in every pin location (`fabric-contract.lock.json`, `adapt_project.py`, `validate.py`,
  three SKILL.md, README, SKILL-CARD, `protocol.md`). `1636fa9` stays supported (`DEC79` in `test_contract_revisions.py`).
  The contract's `main` moved on to `bf3fd6b` with no change under `src`, `fixtures` or `schemas`
  (`git diff --stat 82e1636 bf3fd6b -- src fixtures schemas` is empty), so the pin stays on the DEC-0082 merge.
- **Both kits:** contexts (`PERSONAL_CONTEXT`, `parse_context`), placement and slot keys by context, FAC-SEM-110
  (`grant_context_findings`), FAC-SEM-111 on records and installations, an org slot filled from its own machine,
  `placement_trust(…, context)`. Every rule is total on hostile JSON: raw array indexes in `instancePath`, and a value
  with its own `toString` member shown as JSON.
- **Vectors:** `test/fixtures/contract/make_estate_vectors.mjs` now takes `estate-*.json` and `grant-context-*.json`.
  It adds 19 hostile variants of the contexts fixture and 28 grant-context cases (each `grant-context-*` fixture varied
  seven ways), answered by the contract's own functions. `estate-vectors.json` holds 115 rule cases, 28 grant-context
  cases and 19 `placementTrust` cases.
- **Planted defects:** 28, 14 per kit, all caught. The first round left four survivors: a `null` context read as
  personal, the `org:<orgId>` check skipped, a leading `-`/`_` or 129 characters in an org id, and a secret of another
  context checked at installation. The cases for them are in the hostile block.
- **Docs and evals:** `references/estate-record.md` gains "Contexts: one agent for you and for an organization";
  `building-fabric-services/SKILL.md` names it; eval scenario `estate-contexts`; CHANGELOG 0.33.0; version 0.33.0 in
  every manifest.
- **FAA-43** (the flaky hold test from 0.32.0): the fake board's `lift_holds_after` lifts the hold right after the
  first held `com.effect_begin`, so both twins wait on the call, not on a 50 ms timer. 20 of 20 Python and 5 of 5 Node
  runs pass, and two planted defects are caught: a new key on the retry, and no wait on `held`.
- `main` moved to 0.32.1 (another session's lifecycle docs and FAA-43's row) while this branch was open. It is merged
  in; the only conflicts were version numbers and the CHANGELOG, kept as 0.33.0 above 0.32.1.

## Checks run

- `python3 -m unittest discover -s test`: 634 tests, OK (22 skipped), after merging `main` at 0.32.1.
- `node --test 'test/*.test.mjs'`: 202 tests, 195 pass, 7 skipped, 0 fail.
- `python3 test/validate.py`: OK.
- `claude plugin validate` (plugin and marketplace, `--strict`).

## Trap found

A mutation loop that restores a file with `mv` can leave Python running the mutant. A same-size mutant written in the
same second as the restored original has the same mtime and size, so `__pycache__` serves it. One full-suite run failed
for this reason alone. Run mutation loops with `PYTHONDONTWRITEBYTECODE=1` and clear `__pycache__` first.

## Open

- Release: PR #111 → CI → merge → tag `v0.33.0` → npm; then FAA-41 and FAA-43 → done.
- Launcher repin to adapter 0.33.0 (passioncode PC row), then `npx --yes @passioncode-ai/passioncode@latest update`.
- Workspace `knowledge/products.md` and org-index pin row move to 0.33.0 / `82e1636`.
- Live check against a Fabric that writes contexts waits on RM-28's Fabric side; nothing in this repository blocks it.

## Next task

Release 0.33.0 as above. After that, the board's next open row this agent can take.
