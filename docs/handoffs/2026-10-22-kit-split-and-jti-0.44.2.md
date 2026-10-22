# 2026-10-22: the kit split (0.44.1) and the owner-only consumed-approval file (0.44.2)

**Objective.** The operator's «дальше до конца»: the exact next task of
[the 0.44.0 handoff](2026-10-22-repin-and-connections-0.44.0.md), FAA-92, then FAA-85, each released with its
launcher.

**Done.**
- **0.44.1, FAA-92.** `fabric_interop` and `fabric_package` stood at the 1000-line ceiling. Split by responsibility in
  both twins: `fabric_interop_rules` (L3: constants, `InteropError`, trace context, the DEC-0087 job limits) and
  `fabric_package_schema` (L2: the `fabric-package.schema.json` reading). The facades re-export every name. A board
  test's race under load was fixed beside it. PR [#162](https://github.com/passioncode-ai/fabric-agent-adapter/pull/162)
  (`7098a93`), tag `v0.44.1`, npm 0.44.1; launcher 0.2.24 ([passioncode#136](https://github.com/passioncode-ai/passioncode/pull/136),
  receipts [#137](https://github.com/passioncode-ai/passioncode/pull/137)), installed here byte-identical to the tag
  (155 of 155 files).
- **0.44.2, FAA-85.** `fabric_base`, `fabric_platform` and `fabric_paths` moved from L3 to L1 in `kit.json` (no code
  moved), so `FileJtiStore` writes through the kit's private writer in both twins: owner-only, a protected ACL on
  Windows. The blind readings found the private writer itself left its temporary file on some failures in both twins;
  fixed. PR [#163](https://github.com/passioncode-ai/fabric-agent-adapter/pull/163) (`c6f2b97`), tag `v0.44.2`,
  npm 0.44.2; launcher 0.2.25 ([passioncode#138](https://github.com/passioncode-ai/passioncode/pull/138)).
- Board: 0.44.1 announced on thread `67c3a5e0`; the *When nobody answers* announcement answered *adapted* and *row*
  (FAA-99) on thread `c97280b0`.

**Checks actually run.** 0.44.1: Python 992 OK on 3.11 and 3.9.6 with both contract checkouts, Node 304 pass 0 fail,
`validate.py` and both `claude plugin validate --strict` exit 0, hosted validate on the exact head `2b24352` green on
six jobs. 0.44.2: Python 997 OK on 3.11 with both contract checkouts, Node 306 pass 0 fail, the same validations,
hosted validate on the exact head `7c0e671` green on six jobs, and the Windows-only ACL test
`test_the_consumed_approval_file_is_owner_only` reported `ok` in the hosted Windows job.

**Certification.** 0.44.1: one blind unit reading, pass, its two risks fixed in the PR. 0.44.2: three blind unit
readings (breaks: Node cleanup; fail: Python handle left open on an ACL failure; pass), each finding fixed with a
test seen failing first.

**Decisions.** FAA-85 was solved by reordering layers, not by moving code: the three modules import nothing above
them, so L1 is their honest place, and `fabric_delegation` gains one import. A copy of `fabric_delegation` made by
hand now needs `fabric_base`, `fabric_platform` and `fabric_paths` (`fabric_kit.py install` copies them).

**Open.** FAA-87 needs the operator's npmjs.com sign-in
(https://www.npmjs.com/package/@passioncode-ai/fabric-agent-adapter/access). FAA-98 (UTS46 for the Python reader's
closed side). FAA-99 (teach *When nobody answers* in `working-with-fabric`, evals first, due 2026-10-29). FAA-100
(the next repin: DEC-0101, DEC-0102 and CT-104 have landed on the contract's `main`). The earlier open rows are
unchanged.

**Exact next task.** FAA-100: repin to the contract's current `main`, reviewing all three profiles and the board
rule of DEC-0101 (a responder's fenced reply never answers a request) against `fabric_board_*` and
`working-with-fabric`; then FAA-99.
