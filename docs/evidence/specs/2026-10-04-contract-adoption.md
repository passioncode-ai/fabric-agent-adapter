# CO-193 adapter adoption — bounded source packet

Owner: [issue #31](https://github.com/passioncode-ai/fabric-agent-adapter/issues/31).
Baseline: `46acc8bb774dbdb1e27022e566bcd0076221bea9` (origin/main).
Shared prerequisite: Fabric Agent Contract `df55c8c54a23251342a7ee57ba95642b7eb39e61`,
[merged PR #9](https://github.com/passioncode-ai/fabric-agent-contract/pull/9).

## Requirements and decisions

| Requirement | Evidence gate |
| --- | --- |
| New bundles select df55; all three profiles use its schema | compiled-schema integration tests |
| Complete bundles emitted by baseline remain verifiable at 2ce392 | frozen baseline fixtures, matching old checkout |
| Immutable supported pair only; exact contract/repository/version/SHA lock | negative lock tests |
| Selected lock requires identical clean checkout, never fallback | wrong checkout, dirty schema and missing dependency tests |
| Old accepted names work at both revisions; underscore names at df55 only | compiled validators and invalid-name negatives |
| Default-pin consistency stays strict, legacy exception only allowlist declaration | validator mutation tests |
| No admission or COM authority implied | readiness regression test, unchanged live gates |

No automatic upgrade or downgrade: retaining a legacy bundle retains its exact lock. An
intentional upgrade requires a separately reviewed bundle and current schema validation;
changing a lock alone proves neither runtime compatibility nor admission. Replacing an
underscore-bearing current bundle with a legacy lock fails the legacy schema.

## Route and delivery

Use task-pipeline for intake/spec, TDD, gates and handoff; make-skill retrofit only for scoped
scripts/metadata; agent-sync for lock/changelog leases. Installed skill sources read:
`task-pipeline/task-pipeline/1.87.1/skills/task-pipeline/SKILL.md`,
`make-skill/make-skill/0.29.0/skills/make-skill/SKILL.md`,
`agent-sync/agent-sync/1.21.4/skills/agent-sync/SKILL.md` (plugin cache).
Tool inventory: `npx sshlg-skills toolkit --for 'Backward-compatible contract revision adoption in Fabric agent adapter skill and plugin'`.
Mechanical adapting-skill baseline: make-skill auditor 19 PASS, 0 GAP. Registry leases:
`fabric-contract.lock.json`, `CHANGELOG.md`, run `r-52568da52`.
The operator packet supplies scope and authorization; no unanswered intake dependency.

Sequence: freeze baseline fixture → add failing revision tests → implement strict revision
selection → update live defaults and evals → owner gates → source handoff → push draft PR.
Inherited model; no model switch, delegation, installation or release. Repository source
version remains 0.7.0, pending release; published 0.6.3 is separately checked at closeout.
Root owns the shared communications spine, cross-repository index and independent review.
