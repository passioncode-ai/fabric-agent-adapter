# 2026-10-25: audit, cleanup and the plan for the first organization

**Objective.** The operator: check what other sessions did, the board, the debts, worktrees and branches; delete what is
finished; gather what is open in one place; split it into hotfixes, the first organization's plan, later plans and
backlog; then grill what is missing.

**Done.**
- Audit and plan: [docs/reports/2026-10-25-audit-and-plan/README.md](../reports/2026-10-25-audit-and-plan/README.md).
- Cleanup: 34 merged remote branches deleted; the abandoned clone `fabric-agent-adapter-review-access` removed (its
  commits are in `main` through PR #33); the expired lease `AUTO-PROJECT-REGISTRATION` deleted; 31 board messages read
  and marked.
- Rows FAA-117 to FAA-122 filed from the board's requests and findings.

**Open.** P0: FAA-119, FAA-120. P1: FAA-117, FAA-118, FAA-121, FAA-87 (human gate). The 9 Fabric tasks in `review`
wait for the operator to close them. The operator's questions are in section 5 of the report.

**Checks actually run.** `python3 test/validate.py`; no code changed.

**Decisions (operator, 2026-10-25).** The first organization is the RM-28 pilot pair; integration is an estate release
the adapter coordinates (FAA-124, board thread `0144d916`); kit labels by data attributes plus Russian by `lang`
(FAA-119); the adapter proposes `surfaces.a2a` (FAA-123). FAA-121 sent (thread `c06f2991`, 17 rows).

**Waits.** Answers on threads `0144d916` (fabric, fabric-dashboards, fabric-agent-contract) and `c06f2991` (contract);
the next session reads them with `com.list {unread: true}`. FAA-87: the operator's `npm login`.

**Exact next task.** FAA-119 and FAA-120 as 0.49.3, then FAA-121, then FAA-117 with FAA-118 as 0.50.0.
