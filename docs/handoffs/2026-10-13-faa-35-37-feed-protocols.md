# Handoff — FAA-35 + FAA-37: feed event `data` and `protocols` (0.26.0)

**Objective.** Contract DEC-0070 and DEC-0067 in both kits at pin `a046f57` (CT-18). Brief:
[specs/2026-10-13-faa-35-37-feed-data-protocols.md](../evidence/specs/2026-10-13-faa-35-37-feed-data-protocols.md).

**Done.**
- An event's `data` with its bounds and FAC-SEM-101.
- The protocol register, `negotiate_revision`, FAC-SEM-099, and `protocols` in the well-known document.
- The probe rules `well-known.protocols` and `events.data`.
- Docs: `protocol.md`. Eval: `feed-data-and-protocols`. Version 0.26.0 and CHANGELOG.

**Checks run.**
- `npm test` exit 0 (Python 519 OK; Node 142, 135 pass, 0 fail).
- Both strict plugin validations pass. `check_private.py` reports 0 findings.
- 20 planted defects, all caught. Four survived at first: duplicates, the outer name, and N/N−1 in both kits. Each now
  has its case.

**Open.**
- FAA-33: OpenRouter attribution and the usage-report amendments.
- FAA-36: the consumer agent in `pack`, which waits on FAA-26.
- FAA-40: DEC-0077, which waits on FAA-12b.

**Next task.**
1. Release 0.26.0.
2. Close FAA-35 and FAA-37 on the board.
3. Repin the launcher.
4. Tell the contract.
5. Then take FAA-33.
