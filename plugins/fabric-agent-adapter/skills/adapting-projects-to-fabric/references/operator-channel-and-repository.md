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

1. create a bot with @BotFather;
2. put its token into the operator's secret store (Project Observatory where it is installed) under
   the name the agent reads (for example `EXAMPLE_AGENT_TELEGRAM_BOT_TOKEN`), never into a chat, a
   file or the bundle;
3. run the agent's link command;
4. type the code it shows in the chat with the bot.

In a group shared with other bots the channel follows OC-14 to OC-17 (DEC-0035): it stays silent
unless addressed (`/command@ThisBot`, a reply to its own message or a press of its own button; a
bare `/command` in a group is not addressed), and a channel nobody receives on is `degraded`
(`receiver-missing`). Say so in the proposal when the operator means to bind a shared group.

Record the answer (`accepted`, `declined` or `later`) in the agent's state and in its conformance
report, and do not ask again; an agent that serves `surfaces.operatorChannel` also shows it as
`proposal` in its status document. Creating the bot, storing the token and enabling the channel
are the operator's action: never create the bot, ask for or store the token's value, or enable the
channel yourself. The default pin carries DEC-0034 and DEC-0035: a served status document is
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

org-index `scripts/check_format.py` reports 0 findings for it before it is called done. An agent
someone builds for themselves is not a PassionCode.ai repository: its licence is its owner's
choice, nothing about it is published or listed by the organization, and none of these files is
required of it, though the verified MCP quick start is still how anyone learns to drive it.
