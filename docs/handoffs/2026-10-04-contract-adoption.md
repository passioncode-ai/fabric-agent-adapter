<sub>ssheleg skills — task-pipeline · make-skill · agent-sync</sub>

# CO-193 adapter source handoff — 2026-10-04

## Start here

Review this packet and [the bounded spec](../evidence/specs/2026-10-04-contract-adoption.md),
then independently review the selected-lock boundary and compiled old/new schema arms.
Owner [issue #31](https://github.com/passioncode-ai/fabric-agent-adapter/issues/31) is the
communications dependency packet; Fabric owns COM status. This change implements its
CO-193 naming prerequisite only, not the future message/claim runtime.

Baseline: `46acc8bb774dbdb1e27022e566bcd0076221bea9` (origin/main).
Implementation: [`497a199c9b32039f07baf310bbf7a0c5eed3bbb5`](https://github.com/passioncode-ai/fabric-agent-adapter/commit/497a199c9b32039f07baf310bbf7a0c5eed3bbb5).
Branch: `codex/contract-pin-adoption-20261004`, existing origin
`git@github.com:passioncode-ai/fabric-agent-adapter.git`. Original checkout's untracked
`node_modules/` and `pnpm-lock.yaml` were preserved; work used an isolated worktree.

## Delivered and decisions

- Current default: contract `0.1.0` at `df55c8c54a23251342a7ee57ba95642b7eb39e61`.
  Live metadata, the canonical lock, scaffolding and all three profiles move together.
- Immutable compatibility allowlist: current revision plus previously issued
  `2ce392291c6668598d12cd38327e24696b5ca15c`. Frozen complete baseline-generated
  bundles for MCP, A2A and local-runner remain verifiable at the matching old checkout.
- Locks require the exact contract name, repository, version and full supported SHA.
  Validation uses the selected revision, rejects modified or mismatched checkouts and
  refuses forged locks before invoking the validator. Missing checkout/dependencies are
  `NOT_RUN`; they confer no admission. No automatic upgrade or downgrade.
- Default-pin scanning remains strict. Only the exact immutable allowlist declaration
  can name a legacy pin in live files; mutations, additional declarations and legacy
  mentions in other live docs fail. Dated records and baseline fixtures retain old pins.
- An underscore capability name is a declaration, not COM approval or wider authority.
  Protocol negotiation, semantic probes and binding readiness remain unverified.
- Validation workflow now has manual dispatch and the existing reusable workflow call;
  push/PR triggers were removed before pushing under the operator's CI policy. No test
  job changed and no nightly cron was invented.

Code/test entry points at the implementation commit:
[checker](https://github.com/passioncode-ai/fabric-agent-adapter/blob/497a199c9b32039f07baf310bbf7a0c5eed3bbb5/plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts/adapt_project.py),
[revision tests](https://github.com/passioncode-ai/fabric-agent-adapter/blob/497a199c9b32039f07baf310bbf7a0c5eed3bbb5/test/test_contract_revisions.py),
[pin mutation tests](https://github.com/passioncode-ai/fabric-agent-adapter/blob/497a199c9b32039f07baf310bbf7a0c5eed3bbb5/test/test_validate.py).

## Checks actually run

[Machine-readable gate receipt](../evidence/evals/contract-revisions/checks.json),
[CI-policy receipt](../evidence/evals/contract-revisions/ci-policy.json).

- `npm test` with both exact contract paths: exit 0, 200 Python tests (one skipped),
  38 Node tests, zero failures. Both compiled-schema arms ran, covering all profiles,
  accepted legacy names, underscore names, length/syntax negatives, mismatched revisions
  and forged locks. The sole skip is the existing opt-in real Claude client test.
- `python3 test/validate.py`: exit 0; negative pin/allowlist tests pass.
- Both `claude plugin validate ... --strict` commands: exit 0.
- `actionlint .github/workflows/validate.yml`: exit 0; parsed before/after workflow jobs
  are identical. Events are manual/reusable only; original workflow had no schedule.
- Baseline mutation experiment: complete legacy bundle passes baseline; a constant-only
  repin fails it. The new-default/non-object-lock tests were observed red before repair.
- make-skill: adapting and creating each 19 PASS / 0 GAP. Building has 18 PASS / one
  pre-existing house `BODY_HEADROOM` gap (4756 tokens, below the hard 5000-token budget).
  Only its metadata pin changed; no structural conformance failure is claimed as PASS.
- Observatory update check: exit 0 with no pending output, at intake and before delivery.
- Git lease run `r-52568da52` covered lock/changelog before writes; the run was recorded
  and leases released. No IDs were needed. Hooks are not claimed to protect this host.

## Source, publication and installation remain distinct

Source metadata remains 0.7.0 pending release. Live `gh release view` and `npm view`
returned v0.6.3 / 0.6.3 on 2026-10-04. Read-only inspection of all three installed
`~/.agents/skills/<skill>/SKILL.md` files returned 0.6.3 at the old revision. No install,
plugin update, session reload, tag, merge, release, deployment or live MCP configuration
was performed. No COM smoke, grants, transport or runtime claim is delivered.
Hosted CI was not dispatched and is not claimed passing.

Nightly enrollment is **UNKNOWN**: accessible org-index `check.yml` at
`44dbca21877028c7a39da7182335215f8c019589` validates only its own index, not a downstream
adapter matrix; Fabric's `nightly.yml` path returned 404. The next owner must verify the
adapter's central nightly enrollment without restoring push/PR triggers. Unmerged branch
work is outside the default-branch nightly snapshot.

## Exact next task and cold resume

Root independently reviews compatibility and CI policy, then merges by owner policy.
Before a separately authorized 0.7.0 release, resolve or explicitly track nightly enrollment,
run the release gate, publish and update the owning family pin, and record package,
installed bytes and session reload independently. Future issue #31 runtime implementation
waits for Fabric COM-01/02/03; do not infer it from naming support.

For a cold review, clone this branch, run `python3 test/validate.py`, and create clean
contract worktrees at the two supported SHAs. In each contract checkout run
`pnpm install --frozen-lockfile`; then:

```bash
FABRIC_CONTRACT_OLD=/path/to/old-contract FABRIC_CONTRACT_NEW=/path/to/new-contract npm test
claude plugin validate ./plugins/fabric-agent-adapter --strict
claude plugin validate . --strict
```

Both compiled arms explicitly skip as `NOT_RUN` unless both variables are present.
The shared status/index and cross-repository knowledge update belong to the root run;
this owner packet is not a second editable COM backlog.

---

**Made with [ssheleg skills](https://github.com/ssheleg/sshlg-skills)**

- [`task-pipeline`](https://github.com/ssheleg/task-pipeline) — bounded compatibility packet and gated delivery
- [`make-skill`](https://github.com/ssheleg/make-skill) — scoped script and metadata retrofit
- [`agent-sync`](https://github.com/ssheleg/agent-sync) — exclusive lock and changelog leases

<sub>A star on [the bundle](https://github.com/ssheleg/sshlg-skills) helps.</sub>
