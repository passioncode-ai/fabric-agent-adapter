# The operator channel and the repository standard

Shared by `adapting-projects-to-fabric` and `creating-fabric-agents`; the two copies are byte-identical
(`test/test_shared_references.py`). "The agent" is the provider being adapted or created.

## The operator channel

If the agent has a human stop (a choice, an approval, a confirmation) or emits `notify: true`
events, propose its **operator channel** to the operator once, at the step that links here. The
channel is the agent's own messenger channel, first Telegram, that sends those events and answers
its stops with buttons: `fabric-operator-channel/0.1` (contract DEC-0034,
`docs/specification/operator-channel.md`), whose rule OC-11 this follows. Give the operator's four
steps:

1. create a bot with @BotFather (for an agent that answers people on Telegram, a bot of its own, never
   the bot that answers people: the contract's channel-agent.md);
2. put its token into the operator's secret store (Project Observatory where it is installed) under
   the name the agent reads (for example `EXAMPLE_AGENT_OPERATOR_BOT_TOKEN`), never into a chat, a
   file or the bundle;
3. run the agent's link command;
4. type the code it shows in the chat with the bot.

In a group shared with other bots the channel follows OC-14 to OC-17 (DEC-0035): it stays silent
unless addressed (`/command@ThisBot`, a reply to its own message or a press of its own button; a
bare `/command` in a group is not addressed), and a channel nobody receives on is `degraded`
(`receiver-missing`). Say so in the proposal when the operator means to bind a shared group.

Where the estate runs a messaging gateway service the operator chose for sending (one service every
agent sends through, holding its own grants and allowlist), the channel sends through that gateway
and does not call the messenger itself; the agent's own bot above is the contract's form (DEC-0034,
OC-11) and the form used where no such gateway runs. A bot token read by polling (Telegram
`getUpdates`) has exactly one poller across every machine: a second poller on the same token gets
`409 Conflict` and the two take each other's updates. Check placement before polling: the instance
on the machine the estate's placement record names for the agent polls, an instance on any other
machine does not poll and reports `degraded` with the reason (`poller-elsewhere`), and a test starts a
second instance placed elsewhere and sees it stay off the token.

Record the answer (`accepted`, `declined` or `later`) in the agent's state and in its conformance
report, and do not ask again; an agent that serves `surfaces.operatorChannel` also shows it as
`proposal` in its status document. Creating the bot and putting its token into the secret store
stay the person's (a `secret` step, contract DEC-0121 AP-4): never create the bot, or ask for or
store the token's value. Enabling the channel, and removing a webhook found on its token, are the
operator's decision, taken by them on the agent's page or relayed to its agent in their own words
with `_meta.decision` (OC-1, OC-2, DEC-0121 AP-2), including a relay from another of their agents
that carries their words verbatim, when and where they said them and the scope (DEC-0126 OA-2,
OA-3; its `source` sent only to an agent whose well-known `protocols` list `operator-source/1`,
OA-7); never enable it on your own account. The default
pin carries DEC-0034 and DEC-0035: a served status document is
checked against the pinned `schemas/operator-channel-status.schema.json`; the channel's runtime
rules have no probe rule here yet, so report them `NOT_RUN`. An agent with neither stops nor notify
events skips this.

## The repository standard

For a PassionCode.ai repository, the agent's repository follows the organization's
[repository standard](https://github.com/passioncode-ai/fabric-workspace/blob/main/knowledge/repository-standard.md)
(`knowledge/repository-standard.md` in the organization's knowledge base; a clone has it at
`fabric-workspace/knowledge/`) from its first commit:

- `LICENSE`, `COMMERCIAL-LICENSE.md` and `CLA.md` copied byte for byte from the knowledge base's
  `templates/`, and `AGPL-3.0-only OR LicenseRef-PassionCode-Commercial` in every manifest and
  every SKILL.md `license:`; `SECURITY.md` when the repository is public;
- a README whose first heading is the full name, with `## Quick start for a new teammate`
  (Install; Configure, key names only; MCP, the registration command and one proving tool call,
  verified with a real client in a temporary config; Develop) and `## License`;
- an `AGENTS.md` that opens with the template's *Read first* block and closes with *After work*,
  and a `CLAUDE.md` whose first line is `@AGENTS.md`.

Whoever owns the repository, an agent with a page gets the dashboard rule block in its `AGENTS.md`
(pages open only in Fabric Dashboards; the block is in `references/dashboard-links.md`); the agent runs the
adapter's link gate (`scripts/check_dashboard_link.py` from the skill's own directory, agent-side, never a copy in the
project or a step of its CI), and the project's own test pins the gate's negative fixture (the same reference).

org-index `scripts/check_format.py` reports 0 findings for it before it is called done. An agent
someone builds for themselves is not a PassionCode.ai repository: its licence is its owner's
choice, nothing about it is published or listed by the organization, and none of these files is
required of it, except that an agent built new carries a `LICENSE` naming the copyright holder (all rights reserved
unless the owner gives other terms), as does a new private agent built for a client; files the adapter copies in (the service kit, the dashboard kit) keep their own
licence, `AGPL-3.0-only OR LicenseRef-PassionCode-Commercial` ([COMMERCIAL-LICENSE.md](https://github.com/passioncode-ai/fabric-agent-adapter/blob/main/COMMERCIAL-LICENSE.md)).
The verified MCP quick start is still how anyone learns to drive it.
