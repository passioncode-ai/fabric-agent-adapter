# Documentation map

Where each kind of truth about this repository lives, and what checks it. One home per fact; other pages link to it.

| Truth | Home | Checked by |
|---|---|---|
| What the repository is, commands, local rules, lifecycle footprint | [AGENTS.md](../AGENTS.md) | `test/validate.py` (pin, licence, em dash) |
| How a person installs and uses it | [README.md](../README.md) | the MCP quick start, run with a real client |
| What changed in each release | [CHANGELOG.md](../CHANGELOG.md) (guarded, agent-sync lease) | `test/validate.py` (versions in sync) |
| What each skill tells an agent to do | `plugins/fabric-agent-adapter/skills/*/SKILL.md` | `test/validate.py` (front matter, under 500 lines), `claude plugin validate --strict` |
| How a skill's subject works in depth | `plugins/fabric-agent-adapter/skills/*/references/*.md` | `test/validate.py` (links, em dash) |
| The service kit's modules, layers, install and dates API | [kit-modules.md](../plugins/fabric-agent-adapter/skills/building-fabric-services/references/kit-modules.md) and `scripts/kit.json` | `test/test_fabric_kit.py` (manifest current, layering, every module documented, sizes) |
| The connectors' rules | [connectors.md](../plugins/fabric-agent-adapter/skills/building-fabric-services/references/connectors.md) | the shared cases `test/fixtures/kit-http-cases.json`, `kit-openrouter-cases.json`, run by both twins |
| A recipe on the kit | `plugins/fabric-agent-adapter/skills/building-fabric-services/recipes/*/README.md` | the recipe's tests (`test/test_support_agent_recipe.py`) |
| Expected agent behaviour per skill | `test/evals/<skill>/triggers.json`, `scenarios.json` | read before instructional prose changes (AGENTS.md) |
| Tasks, their status and closure receipts | [backlog.md](backlog.md) (guarded), declared in [backlog-sources.json](backlog-sources.json) | the workspace backlog sync |
| Why a change was made, how it was verified | `docs/evidence/` (briefs, designs, reports), `docs/handoffs/<date>-<topic>.md` | written in the change itself |
| Which registers are guarded and how | [AGENT_SYNC.md](AGENT_SYNC.md) (generated, never edited by hand) | `agent_sync.py setup` |
| The contract pin | `fabric-contract.lock.json` (guarded) | `test/validate.py` fails any other revision named in a live file |
