# Operator channel proposal in the creating and adapting skills (FAA-15)

Branch `agent/operator-channel-proposal-20261010`, cut from `origin/main` at `b46cedf`. Objective:
make the two skills that create or adapt a Fabric agent propose the agent's operator channel to
its operator once. The channel is contract `fabric-operator-channel/0.1`, DEC-0034, rule OC-11,
in [contract PR #25](https://github.com/passioncode-ai/fabric-agent-contract/pull/25).

## Completed

- `creating-fabric-agents` step 6 and `adapting-projects-to-fabric` step 8: an agent with human
  stops or `notify: true` events gets one proposal. The step lists the operator's four steps
  (@BotFather, the token into the secret store by name, the link command, the code in the chat)
  and records `accepted`, `declined` or `later`. The skills never create a bot, store a token or
  enable the channel themselves. Both completion formats report the answer.
- Scenario evals `operator-channel-proposal` in `test/evals/creating-fabric-agents/` and
  `test/evals/adapting-projects-to-fabric/`, written before the prose.
- `CHANGELOG.md` *Unreleased*, `docs/backlog.md` FAA-15.

## Decisions

- **The default contract pin is not moved.** The repository rule says a newer normative rule is
  not copied in while the old pin stays in metadata. So the skills cite DEC-0034 by path and id,
  say it is newer than the pin, and keep channel conformance `NOT_RUN`. Moving the pin to the
  merge of contract PR #25 is the release step, FAA-15's open part. It is not done here.

## Checks run

See the PR body for the exact commands and their final lines: `npm test`, and
`claude plugin validate --strict` for the plugin and the marketplace.

## Next task

Merge contract PR #25 first. Then review and merge this PR. Then, as FAA-15's open part, move
`fabric-contract.lock.json` and every pin mention to the contract merge commit (the FAA-14
procedure: the old default joins `SUPPORTED_CONTRACT_COMMITS`, and both compiled-schema arms are
run), change "newer than the default pin" in both steps into a pinned reference, and release.
