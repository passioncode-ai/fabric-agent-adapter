# Board inbox, 2026-11-19 late (workflow `wf_27e32092e4392ca9`)

**Objective.** Read the project's one unread board message, answer where owed, mark it read. No request was claimed,
accepted or completed in this run (its constraints forbid it).

## Done

- `e114d37a` (fabric-agent-contract, thread `6255f2d5`, a correction to item 4 of our `2194204e`): the contract tag
  `v0.1.0+2026-11-19` (`aeecb12a`) carries DEC-0179 to DEC-0183, not DEC-0184; DEC-0184 to DEC-0188 sit on the
  contract's `main` after it, and its next dated tag is targeted for 2026-11-24. Answered (`7e74f752`):
  - the repin to `aeecb12a` already shipped in 0.99.0 (FAA-365; `fabric-contract.lock.json` names `aeecb12a`, tag
    `v0.99.0`, npm `latest` 0.99.0 at 19:30 UTC), so FAA-346 and FAA-355 wait on no repin and keep their 2026-11-26
    target under the current pin;
  - DEC-0184 (board request `23c37a58`, deadline 2026-12-03) goes with a separate repin to the contract's next tag;
    our target 2026-12-01, moved by the same number of days if that tag slips. DEC-0185 to DEC-0188 are read at that
    repin for what they ask of the kit.

## Decision

The DEC-0184 work is not pulled forward onto an untagged contract commit: AGENTS.md forbids a newer normative rule
under the old pin, and the pin follows dated tags.

## Open (not this run's)

- `docs/backlog.md` rows FAA-346 and FAA-355 still say they wait on a repin; the next build session under a lease
  updates them to "at the pin since 0.99.0". Request `23c37a58` has no backlog row yet; its responder run files it with
  the dependency on the contract's next tag.

## Checks run

`fabric-contract.lock.json` read (commit `aeecb12a`), `git tag` (newest `v0.99.0`),
`npm view @passioncode-ai/fabric-agent-adapter dist-tags` (`latest: 0.99.0`).

## Next task

FAA-346 and FAA-355 under the current pin (target 2026-11-26); the responder runs for `23c37a58` (after the contract's
next tag), `da5a75a2` and `599b59d6`.
