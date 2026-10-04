---
report:
  id: fabric-agent-contract/2026-10-04-contract-adoption-review
  title: "Fabric Agent Adapter immutable contract adoption: independent review"
  kind: review
  project: fabric-agent-contract
  domains: [engineering]
  as_of: 2026-10-04
  status: active
  valid_until: 2026-10-11
  summary: >-
    The adapter candidate preserves exact-revision schema selection for issued and new
    bundles, and the compiled current schemas accept underscore capability names.
    Changes are required: the distribution validator accepts dynamic suffixes on
    the reviewed commit, repository and version declarations. Nightly CI enrollment
    remains unverified; source acceptance does not establish release or installation.
  sources:
    - name: "Reviewed adapter candidate"
      url: "https://github.com/passioncode-ai/fabric-agent-adapter/tree/05b8451cc7acd64112078395866cc35b5d217fb1"
      read_at: 2026-10-04
    - name: "Independent replay and receipts"
      path: raw/independent-checks.log
      read_at: 2026-10-04
  produced_by: {agent: codex, task: contract-adoption-review}
  supersedes: []
  consumers: [fabric]
---

<sub>ssheleg skills — working-in-passioncode · task-pipeline · make-skill</sub>

# Independent review

## Verdict and scope

**CHANGES** for [adapter PR 32 candidate](https://github.com/passioncode-ai/fabric-agent-adapter/tree/05b8451cc7acd64112078395866cc35b5d217fb1).
This is a source and compiled-schema judgment, formed before reading the author's proof.
Only this report and its raw receipts are reviewer-owned changes. The parent owns normal
integration after an accepted recheck. No release, installation, live provider admission,
user configuration change or hosted suite dispatch was performed.

The report lives in the adapter repository that owns this question. Its taxonomy project
is `fabric-agent-contract` because the report tool rejected `fabric-agent-adapter` as absent
from the wiki project registry; this metadata fallback creates no second source report.

## Blocking finding R1

The [pin validator](https://github.com/passioncode-ai/fabric-agent-adapter/blob/05b8451cc7acd64112078395866cc35b5d217fb1/test/validate.py#L446)
counts AST name stores, then reads only the initial quoted prefix through an unanchored
regular expression (lines 452–456). It does not verify the assignment value's complete AST.
Thus each sole declaration can append a dynamic suffix and still pass the whole CLI:

| Mutation to the declaration | Observed `python3 test/validate.py` | Required |
|---|---|---|
| `CONTRACT_COMMIT` literal followed by ` + "bad"` | exit 0, distribution valid | reject |
| `CONTRACT_VERSION` literal followed by ` + "bad"` | exit 0, distribution valid | reject |
| `CONTRACT_REPOSITORY` literal followed by ` + "/forged"` | exit 0, distribution valid | reject |

This makes the advertised immutable declaration gate unsound: a passing distribution can
write a non-reviewed commit, a forged repository or a non-reviewed schema version into new
bundles. The reviewer planted each defect in a throwaway copy, without modifying the
candidate. Evidence and the runnable reproduction are [raw/independent-checks.log](raw/independent-checks.log)
and [raw/replay.log](raw/replay.log). The root and author received this finding immediately.

Required correction: validate direct top-level single-name assignments with exact literal
values, plus the exact supported tuple AST; reject alternate writes and dynamic expressions.
Retain negative CLI tests for these three suffixes and the existing reassignment mutations.

## Passed source and compilation checks

[Adapter check selection](https://github.com/passioncode-ai/fabric-agent-adapter/blob/05b8451cc7acd64112078395866cc35b5d217fb1/plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts/adapt_project.py#L425)
checks contract identity, repository, version and the immutable supported SHA before invoking
compiled validation. The selected checkout HEAD must equal the issued bundle lock, its tracked
and untracked schema checkout must be clean, and dependencies must exist. Unavailable checks
remain NOT_RUN. A schema-invalid manifest fails; validator execution failure is not a PASS.

Independent detached contract worktrees came from the exact old and current Git objects;
frozen-lockfile dependency installation exited 0 in each. Their full identities are recorded
in [raw/independent-checks.log](raw/independent-checks.log). The contract remote main resolved
to the current reviewed default on this cut.

- All three complete legacy fixture profiles pass the legacy compiled schema.
- Newly generated MCP, A2A and local-runner bundles with `receive_project_message` pass the
  current compiled schema. Generated placeholders remain unready for admission.
- Old-lock/new-checkout and new-lock/old-checkout combinations fail for each profile;
  no auto-upgrade, auto-downgrade or unknown-revision fallback occurs.
- Unknown SHA, wrong repository, wrong version and wrong contract identity each fail for
  every profile before shape validation.
- Current compiled manifest, interop-agent-call, service-well-known and pipeline surfaces
  passed 40 independently constructed valid/invalid name cases, including underscore names,
  unchanged dotted names, two-character minimum, 128-character boundary, leading underscore,
  uppercase, spaces, one character, 129 characters and numeric type. See [raw/four-surfaces.log](raw/four-surfaces.log).

The independent replay has 24 passing behavior checks and the three failing validator
expectations in R1. It is rerunnable as:

```sh
python3 docs/reports/2026-10-04-contract-adoption-review/raw/replay.log \
  . "$FABRIC_CONTRACT_OLD" "$FABRIC_CONTRACT_NEW"
```

## Local gate, CI and release boundaries

The candidate `npm test` with both exact contract checkout environment variables exited 0:
201 Python tests, one intentionally skipped real-client test, and 38 passing Node tests.
Both `claude plugin validate ./plugins/fabric-agent-adapter --strict` and
`claude plugin validate . --strict` exited 0. The real-client test is opt-in and was not
executed. Full summarized receipts are [raw/gates.log](raw/gates.log).

The validation workflow removes push/pull-request triggers and retains workflow_call and
workflow_dispatch, consistent with the organization nightly policy. Existing release validation
continues to call it. **Nightly enrollment remains UNKNOWN**: remote adapter workflow inventory
contained only release and validate; the remote org-index scheduled check performs index and
org-index tests, not adapter validation. This is no claim that central enrollment exists or
that hosted CI passed. No full hosted suite was dispatched.

Candidate metadata is **0.7.0 source, unreleased**. Live npm reports 0.6.3, GitHub latest release
is v0.6.3, and the installed skill metadata inspected reports 0.6.3. This report neither
publishes nor upgrades an installation.

## Handoff and exact next task

Objective: independently judge immutable contract adoption and compiled schema selection.
Completed: isolated candidate review, exact old/new dependencies, independent behavior and
mutation checks, local repository/plugin gates, workflow and registry readback.
Decision: request R1 correction; preserve nightly caller uncertainty as an explicit limit.
Open: recheck the author's exact pushed fix; root integration remains gated on acceptance.
Prerequisites: both supported contract objects and frozen dependencies; ordinary Git read/push
access. Original untracked dependency files were preserved. Reviewer worktrees are resumable
and retain no live service or hosted job.

**Next task:** read the author's new exact SHA, inspect its validator diff, run the independent
replay against that object, append the new source verdict with receipts, then let the parent
perform integration under repository policy. Do not release or install from this report.

## Actual skills used

`working-in-passioncode` grounded repository, privacy and nightly CI policy. `task-pipeline`
provided the bounded scope/evidence/dependencies/resume discipline for this report; the parent
packet supplied its intake and no separate implementation/deploy cycle was created.
`make-skill` supplied the plugin and validator construction checks. `project-reports` supplied
the source-owned report header and generated index workflow. No UI or design skill was used.

---

**Made with [ssheleg skills](https://github.com/ssheleg/sshlg-skills)**

- `working-in-passioncode` — repository and nightly CI policy — not a skill this family ships
- [`task-pipeline`](https://github.com/ssheleg/task-pipeline) — bounded independent review and durable handoff
- [`make-skill`](https://github.com/ssheleg/make-skill) — plugin and validator review

<sub>A star on [the bundle](https://github.com/ssheleg/sshlg-skills) helps.</sub>
