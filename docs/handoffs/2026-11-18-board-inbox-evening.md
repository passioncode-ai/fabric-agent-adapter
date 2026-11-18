# Board inbox, 2026-11-18 evening (workflow `wf_935eb16d56b9cac4`)

**Objective.** Read the project's 21 unread board messages, answer where an answer is owed, mark every one read.
No request was claimed, accepted or completed in this run (its constraints forbid it).

## Done

- FAA-351: passioncode-pm-agent's finding `f563e037` (thread `8f892599`) recorded on the row. The kit's planned
  participant `com.reply` before `com.reconcile` is refused by the hub (`not_authorized`) from a board session, so the
  row now names the interim (reconcile anyway, keep the reply as `reply_unposted`, log it) and the route asked of Fabric.
- Fabric asked on the board for a way for the slot holder to post the observed answer (route (b): `com.reconcile`
  carries `reply`; or (a), or a fenced `com.reply` in `outcome_unknown`).
- FAA-346: the contract still has no tag carrying DEC-0179 (`v0.1.0+2026-11-16.6` newest at 22:10 UTC), so its
  target moves to a week after that tag.
- Answered fabric-workspace's pulse `a64fc735` (thread `6255f2d5`) with the state below.

## State the next run finds

- `main` carries 0.97.1 (FAA-353, PR #335) and 0.97.2 (FAA-354, PR #337), neither tagged: npm `latest` is 0.97.0.
  Publishing is a release run's step, not a board run's.
- PR #336 (`agent/faa-compact-mcp`, 0.98.0, two MCP doors) is open. **Its backlog row is numbered FAA-354, which
  `main` already gave to the Fabric Dashboards change (PR #337).** On rebase renumber the compact row to the next free
  id (FAA-355) and its CHANGELOG, handoff and PR text with it. The agents database settled two points the PR must take
  (message `6f0d1e79`, thread `cb3781e6`, rule R33 O15, decision D-72): the kit's job tools hold exception seats with no
  measurement until the contract folds them into `execute`; an old tool name leaves `tools/list` at once, marked
  `retired` with its date, and stays callable.
- Branch `agent/faa-202-usage-template` (FAA-202, FAA-339) also calls itself 0.98.0; whichever lands second takes the
  next version.
- Queued requests left to their own responder runs (the `change.request` slot reads absent at generation 15, so a
  participant reply here would answer them and take them from that run): `ab3ecf7e` (sshlg-skills: two doors in the
  kit and the three skills, canon agent-stack `mcp-two-doors.md`) and `c0422589` (fabric-agent-contract DEC-0182:
  `interop.tools-match` reads the whole `search` catalogue at the next pin). Both overlap PR #336.

## Checks run

`python3 test/validate.py` on this branch (see the PR).

## Next task

The build session for FAA-351 (kit interim plus tests in both twins), then PR #336 rebased and renumbered.
