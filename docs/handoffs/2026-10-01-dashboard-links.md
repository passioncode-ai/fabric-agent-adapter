# Dashboard handoff rule implementation

Objective: registered Fabric dashboards use the host-provided deep link across
producer and consumer agents. All three skills now link the same self-contained
reference and carry a byte-identical Python output gate. The service skill also
routes explicit dashboard handoff/open requests. CLI guidance no longer treats an
installed host failure as browser fallback. See the
[spec](../evidence/specs/2026-10-01-dashboard-links.md) and
[reference](../../plugins/fabric-agent-adapter/skills/building-fabric-services/references/dashboard-links.md).

## Evidence

- `npm test`: validator, 135 Python tests (1 opt-in skip), 15 Node tests passed.
  A further malformed-input test was added and focused tests passed; final counts
  are in the check receipt.
- `FABRIC_REAL_CLIENT=1 python3 -m unittest discover -s test -p test_real_client.py -v`:
  the previously skipped Claude Code handshake/tool discovery test passed separately.
- Both `claude plugin validate` checks passed with `--strict`.
- Frozen CLI fixtures reject installed-host raw HTTP, failed-host fallback, another
  instance and a phone-localhost action. Mutation replacing absent with available
  is detected: [receipt](../evidence/evals/dashboard-links/mutation.json).
- [Model arms](../evidence/evals/dashboard-links/model-arms.json): three supplied-context
  cases on Claude Code and Codex, baseline versus the new reference. Both baseline
  answers proposed browser fallback after installed-host failure; both current arms
  refused it. This is bounded output evidence, not a general accuracy estimate.
  Codex emitted skills-budget/unstable-feature warnings; automatic routing remains
  NOT_RUN. Claude baseline emitted multiple fenced arrays, a format failure.
- `python3 test/evals/dashboard-links/run_model_arms.py` repeats model arms using
  existing CLI accounts (opt-in, potentially billed); no production tool actions.
  The first harness run failed writing its receipt; corrected reruns are recorded,
  not retroactively labelled a successful harness run.

## Boundaries and next task

No version bump, tag, npm publish or installed-skill/cache replacement. Published
0.5.5 remains unchanged. The gate validates structured actions with trusted host
context; it is not a host hook, discovery, authentication, transport or a scan of
all free-form final answers. A generated managed renderer must actually call it.
A headless provider needs no dashboard. No Fabric contract revision change.

Next: review/merge with the Dashboards strict-open branch, release the adapter via
its normal version-sync checks, install through the owning installer, then measure
actual skill activation and managed-renderer enforcement in target sessions.
A remote chat relay and lifecycle broker still need their own implementation.

Route: task-pipeline implementation profile; make-skill scoped retrofit (no
release); building-fabric-services contract. AGENTS.md and knowledge rules read.
No shared guarded registry edits here, no leases required. Local-only: account
state, model CLI sessions/config, temporary MCP credentials and dependency trees.
No test service retained. Dated eval artifacts use neutral public examples only.
