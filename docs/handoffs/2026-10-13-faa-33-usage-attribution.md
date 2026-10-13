# Handoff — FAA-33: usage window, spend by project, OpenRouter attribution (0.27.0)

**Objective.** Contract DEC-0065 in both kits at pin `a046f57` (CT-18). Brief:
[specs/2026-10-13-faa-33-usage-attribution.md](../evidence/specs/2026-10-13-faa-33-usage-attribution.md).

**Done.**
- Receipts take a project and a task run; the report writes `byProject` with ids in normal form.
- `usage_findings` ports FAC-SEM-025 whole.
- `attribution_headers` is off by default.
- The probe reads routes, the window and `byProject`.
- Docs: `usage.md` (Contents added). Eval: `usage-by-project-and-attribution`. Version 0.27.0 and CHANGELOG.

**Checks run.**
- `npm test` exit 0 (Python 526 OK; Node 144, 137 pass, 0 fail).
- Both strict plugin validations pass. `check_private.py` reports 0 findings.
- 23 planted defects, all caught. Two survived at first: a runs-over-project bound masked by its neighbour, and
  backslashes after the scheme. Each now has its case.

**Open.**
- FAA-36 waits on FAA-26.
- FAA-40 lands with FAA-12b.
- `byGrant` (DEC-0061 item 6) is not written by the kits. It belongs to a service offered to others, so it goes with
  FAA-36 / FAA-26.

**Next task.**
1. Release 0.27.0.
2. Close FAA-33 on the board.
3. Repin the launcher.
4. Tell the contract.
