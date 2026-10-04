<sub>ssheleg skills — task-pipeline · project-reports</sub>

# Contract adoption review integration — 2026-10-04

## Entry and scope

Objective: preserve the independent review packet in the owning repository after the
accepted CO-193 source merge. This is a documentation-only delivery from current main;
no product code, version, release workflow, installed skill, local MCP configuration,
wiki page or generated report index is changed.

Read the [independent report](../reports/2026-10-04-contract-adoption-review/README.md),
[implementation handoff](2026-10-04-contract-adoption.md) and
[post-rejection owner receipt](../evidence/evals/contract-revisions/post-rejection.json).
The imported report retains its original rejection and appended exact-SHA acceptance;
its taxonomy fallback to `fabric-agent-contract` is explained in its unchanged body.

## Exact merge and review receipts

| Receipt | Identity and evidence |
| --- | --- |
| Accepted source | `cb77ff78406e0dd7bdc4f67bdd104a0d108d2c46` |
| Main merge | `c5be1e9b095503b99815b38d4106b5a493112379` |
| Merge event | [PR #32](https://github.com/passioncode-ai/fabric-agent-adapter/pull/32), `2026-10-04T12:08:56Z` |
| Imported reviewer packet | `5f88fb4e1fb28a546407db786995be382232623e` |
| Reviewer verdict | [Appended ACCEPT](../reports/2026-10-04-contract-adoption-review/README.md#appended-independent-recheck--2026-10-04), bounded to accepted source |
| Independent replay | 27/27 expected outcomes, including the three original suffix negatives producing exit 1 |
| Independent owner gate | 208 Python tests, one opt-in real-client skip, 38 Node tests; strict plugin/marketplace checks pass |
| Four compiled surfaces | 40 valid/invalid capability-name cases in the unchanged reviewer packet |

Source links at the accepted object:
[static pin checker](https://github.com/passioncode-ai/fabric-agent-adapter/blob/cb77ff78406e0dd7bdc4f67bdd104a0d108d2c46/test/validate.py),
[selected revision checker](https://github.com/passioncode-ai/fabric-agent-adapter/blob/cb77ff78406e0dd7bdc4f67bdd104a0d108d2c46/plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts/adapt_project.py).

## Checks actually run for this delivery

- `git fetch origin` and `git rev-parse origin/main`: current main is the merge above.
- `gh pr view 32 --json state,mergedAt,mergeCommit,headRefOid`: MERGED with the accepted
  head, merge object and timestamp above.
- `git restore --source=5f88fb4e1fb28a546407db786995be382232623e --worktree --staged -- docs/reports/2026-10-04-contract-adoption-review` imports only the reviewer-owned packet.
- `git diff --exit-code 5f88fb4e1fb28a546407db786995be382232623e -- docs/reports/2026-10-04-contract-adoption-review`: exit 0; all packet bytes unchanged.
- `reports.py check docs/reports/2026-10-04-contract-adoption-review`: one report, zero errors.
- `python3 test/validate.py`: exit 0. This delivery does not rerun the full runtime suite;
  the exact accepted implementation's full owner and independent receipts are linked above.
- Observatory update check: exit 0, no pending output. No guarded register is modified,
  no IDs are allocated, and no leases are needed for this evidence-only file set.
- `gh release view` and `npm view @passioncode-ai/fabric-agent-adapter version` on this cut:
  latest published GitHub/npm remain v0.6.3 / 0.6.3. Source metadata on main is 0.7.0.

## Concrete partial completion and remaining work

CO-193 naming adoption is merged source: new bundles use df55, old issued bundles keep
their explicit immutable supported revision and matching checkout, forged/default-drift
and mismatch negatives fail. This is only a prerequisite of [owner issue #31](https://github.com/passioncode-ai/fabric-agent-adapter/issues/31),
which stays open. Consumer registration/replacement, cursor catch-up, claim/ack/reply,
checkpoint and shutdown helpers, server generation/grant handling and the real Claude→Codex
smoke remain unimplemented in this owner packet. Declaring a COM capability name grants
no runtime permission or admission.

**Nightly enrollment remains UNKNOWN.** The validation workflow permits manual dispatch
and reusable release validation, with no push/PR trigger. Accessible scheduled org-index
workflows validate that index only; no central adapter caller was verified. This is an owner
follow-up, not hosted CI success. Do not restore push/PR triggers or invent a DST-incorrect
schedule. Unexecuted real-client and live acceptance boundaries remain explicit.

## Exact next task

Root integrates this review-only branch under owner policy, then performs the single final
cross-repository report-index/wiki synchronization. This run does not perform that sync.

Before a separately authorized 0.7.0 release, the release owner must:

1. Resolve and record adapter nightly caller enrollment, or retain its explicit blocker.
2. Recheck exact release-source SHA, versions and manifest pins; run `npm test` with both
   clean contract checkouts and frozen dependencies, plus both strict plugin checks.
3. Review the 0.7.0 lifecycle changes already on main alongside this naming prerequisite;
   track the pre-existing building-skill soft token headroom finding without claiming a
   structural failure or an unexecuted live-client check passed.
4. Verify owner release configuration/authorization and GitHub/npm publication receipts
   at the intended tag; source merge alone is not that authorization or a release.
5. After authorized publication, update the owning family pin and separately verify package
   bytes, actual installed skills and a session reload/acknowledgment. Currently inspected
   installed metadata remains 0.6.3 at the old contract pin; no installation occurred here.

COM implementation follows the canonical Fabric COM-01/02/03 contract and issue #31;
this report import creates no independent editable COM backlog and closes no runtime task.

---

**Made with [ssheleg skills](https://github.com/ssheleg/sshlg-skills)**

- [`task-pipeline`](https://github.com/ssheleg/task-pipeline) — source-only review packet delivery
- `project-reports` — unchanged report header validation — not a skill this family ships

<sub>A star on [the bundle](https://github.com/ssheleg/sshlg-skills) helps.</sub>
