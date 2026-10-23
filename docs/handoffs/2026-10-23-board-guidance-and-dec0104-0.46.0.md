# 2026-10-23: the board guidance (0.45.1) and the repin to DEC-0104 (0.46.0)

**Objective.** The operator: «давай доделывай все сам автономно и выбирай лучшие решения для меня и в итоге заливай
все обнови доки и новая версия». The exact next task of [the 0.45.0 handoff](2026-10-23-repin-e742016-0.45.0.md),
FAA-99, then the next dated row, FAA-102 (the contract's DEC-0104 announcement), each released.

**Done.**
- **0.45.1, FAA-99.** `working-with-fabric` teaches *When nobody answers* as the operator's rule states it and reads the
  board as DEC-0098 and DEC-0102 serve it; evals first (eight new scenarios, two rewritten, four trigger queries). PR
  [#167](https://github.com/passioncode-ai/fabric-agent-adapter/pull/167) (`656f957`), tag `v0.45.1`, npm 0.45.1.
- **0.46.0, FAA-102** ([brief](../evidence/specs/2026-10-23-faa-102-repin-0a4ce77-brief.md)). Pin `0a4ce77`;
  `jobCallerAction` answers `queue-full` `invalid`, the job store refuses to end a job with it, three new protocols in
  the register. PR [#168](https://github.com/passioncode-ai/fabric-agent-adapter/pull/168) (`ef54ebb`), tag
  `v0.46.0`, npm 0.46.0; launcher 0.2.27 ([passioncode#142](https://github.com/passioncode-ai/passioncode/pull/142)),
  installed here byte-identical to the tag (155 of 155 files). The launcher moved once, skipping a release for 0.45.1.
- Board: Fabric Inbox's probe question answered on `199b9549` (the probe holds to the contract; Inbox moved its
  protocol routes behind their own Access application); DEC-0104 answered *row* on `c451a1ce`; two upstream errors
  (Fabric's `fabric_whoami` rule tells an agent to reply "it stays queued", which under DEC-0102 ends the queue;
  agents-first.md's liveness wording) reported on `76f5043b`; 0.45.1 and 0.46.0 announced on `67c3a5e0`.

**Checks actually run.** 0.45.1: Python 1000 OK with both contract checkouts, Node 307 pass 0 fail, `validate.py` and
both `claude plugin validate --strict` exit 0, hosted validate green on the exact head `4c83dee`. 0.46.0: Python 1001
OK on 3.11 and (before the last fix) 1000 on 3.9.6, Node 308 pass 0 fail, the same validations, hosted validate green on
the exact head `d9bb596`.

**Certification.** FAA-99: three blind product readings (fail with five breaks, fail with two, pass with four risks);
every finding fixed. FAA-102: one blind unit reading, pass with five risks, all closed.

**Decisions.** FAA-102 D1: the kit does not queue yet (FAA-103). FAA-99: the requester does not cancel its own request
after an *adapted by* reply; it stays on the board for the owner until its deadline.

**Open.** FAA-87: npm trusted publishing needs one step by the operator (the machine has no npm CLI sign-in; `npm login`
opens a confirmation in the browser where the operator is signed in), then the agent runs `npm trust github`, moves the
publish step to OIDC and deletes the token after a release publishes. FAA-101, FAA-103 (on demand), FAA-98, and the
earlier open rows.

**Exact next task.** FAA-87 once the operator has run `npm login`; otherwise FAA-101 (the session test's fixed
deadline under load).
