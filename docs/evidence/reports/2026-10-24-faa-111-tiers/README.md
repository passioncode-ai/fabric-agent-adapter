# FAA-111: what became of each finding

The [seam](seam.md) and [product](product.md) readings of `v0.46.1..v0.48.3`, and the [unit](unit.md) reading of
0.49.0's own changes, 2026-10-24. Every finding is fixed in
0.49.0 with a test seen failing first, documented, or filed as a backlog row ([brief](../../specs/2026-10-24-faa-111-sweep-brief.md)).

| Tier | Finding | Became |
|---|---|---|
| seam | A resumed board handler could run twice (0.48.2's `_resume_next` kept the head while resuming) | fixed: the head is taken before the resume and put back only when the resume raises (both twins); `test_a_resumed_handler_that_settles_inside_the_resume_runs_once` |
| seam | The OpenRouter ceiling and `totals()` counted a `subscription` receipt's estimate as spent | fixed: money only (both twins); `test_a_subscription_estimate_is_not_spent_against_the_ceiling`, the `totals` cases |
| seam | A service stating its own `spentUsd` on the twin of `budget` is refused once the numbers differ | documented: `references/usage.md` |
| seam | One malformed receipt makes a window's `spentUsd` `null` | documented as intended (unknown, never guessed): `references/usage.md` |
| seam | `guard_verdict` passed any 403, whatever its body | fixed: a 403 that carries the well-known document fails; `test_a_403_that_carries_the_document_does_not_pass` |
| seam | No `verify` vector carries a `deltaAnchor` (FAC-SEM-137 on the verdict path) | filed: FAA-112 |
| seam | Python estate lookups that mirror a Node `Set` and do not use `set_has` | filed: FAA-113 |
| seam | `auth.token-file` now comes before `well-known.requires-token` in the probe's results | noted in the 0.49.0 CHANGELOG entry |
| product | `remote-placement.md` named one false FAIL of the no-token check; there were three | fixed: `_carries_document` reads the document's shape (D4); the doc lists the two that remain |
| product | `usage.md` gave no word on old and new kits side by side | documented: `references/usage.md`, `references/profiles.md` |
| product | Three em dashes in the FAA-107 row | fixed in `docs/backlog.md` |
| product | The FAA-84 row did not say 0.48.3 shipped it | fixed in `docs/backlog.md` |
| product | The FAA-91 row read open at its own tag | no change: receipts land one commit after a release, by pattern |
| product, not examined | `protocol.md` listed a receipt's `route` without `platform-metered` | fixed in `references/protocol.md` |
| product, evidence | The em dash gate did not read the recipes' README | fixed: `test/validate.py` scans `*/recipes/*/README.md` |
| unit | A resumed request whose effect began was put back to resume when the nested replace lost its answer | fixed: put back only while no effect began (both twins); `test_a_request_whose_effect_began_is_not_put_back_to_resume` |
| unit | `totals([])` moved from `null` to `0` with no test | kept (no call spent nothing) and pinned in both twins |
| unit | `_deliver_and_count` took a negative count; a fresh `board.json` that did not parse read as `down`; a delivered session end read as `down` with the wrong reason | fixed: `test_the_count_after_delivering_is_read_strictly` |
