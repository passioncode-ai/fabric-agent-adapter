<p align="center">
  <a href="https://passioncode.ai/">
    <img src="assets/passioncode-icon-256.png" width="104" height="104" alt="PassionCode.ai passion fruit mark">
  </a>
</p>

# Fabric Agent Adapter

> **PassionCode.ai — The agent-agnostic operating system for AI-native teams.**

**From vibe coding to passion coding.** PassionCode.ai moves the control point from
managing agents one by one to operating Projects. Fabric Agent Adapter is the portable
on-ramp: it helps an existing repository become a compatible, replaceable Provider
without moving the Project onto one proprietary agent runtime.

[![npm](https://img.shields.io/npm/v/%40passioncode-ai%2Ffabric-agent-adapter)](https://www.npmjs.com/package/@passioncode-ai/fabric-agent-adapter)
[![validate](https://github.com/passioncode-ai/fabric-agent-adapter/actions/workflows/validate.yml/badge.svg)](https://github.com/passioncode-ai/fabric-agent-adapter/actions/workflows/validate.yml)
[![license](https://img.shields.io/badge/license-source--available-blue.svg)](LICENSE)

Portable Agent Skills that make any agent Fabric-compatible, for the
[Fabric Agent Contract](https://github.com/passioncode-ai/fabric-agent-contract):
`adapting-projects-to-fabric`, `creating-fabric-agents` and
`building-fabric-services`.

`building-fabric-services` makes an agent a long-lived local service with a dashboard
that is always alive, runs as one copy, keeps its state through a reinstall and appears
in Fabric Dashboards by itself — the `fabric-service/0.1` extension. It ships Python and
Node reference kits (`scripts/fabric_service.py`, `scripts/fabric-service.mjs`), a
complete `scripts/sample_service.py`, and `scripts/check_service.py`, a live probe:

```bash
python3 plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/check_service.py example-agent
```

Services and agents that other agents call follow `fabric-interop/0.1`: each capability
is the MCP tool of its name, long work is a job with a stable id (`fabric.job.get`,
`fabric.job.cancel`), a question for a person is an elicitation, and every call carries
one W3C trace. The kits ship the helpers (`scripts/fabric_interop.py`,
`scripts/fabric-interop.mjs`), the sample service serves a job end to end, and the probe
checks the interop rules. An agent that is not a service is announced with a provider
entry: `adapting-projects-to-fabric/scripts/fabric_provider.py`.

For provider bundles the adapting skill helps an agent author:

- inspect the project's stable integration surfaces without executing it;
- choose A2A `1.0`, MCP `2026-07-28`, or `fabric-local-runner/0.1` per capability;
- scaffold a version-pinned provider manifest, schemas, safe fixture, probes, and
  conformance report;
- distinguish structural validation from live protocol negotiation, semantic
  admission, and project binding.

The skill never treats generated files as admission. Fabric contract `0.1.0` does not
yet ship the host registry/runtime needed to connect and authorize a live provider.

## Install

The repository and the npm package are public; neither path needs an account.

npm — no GitHub access required:

```bash
npx @passioncode-ai/fabric-agent-adapter        # installs every skill into the agents hub ~/.agents/skills
npx @passioncode-ai/fabric-agent-adapter --prune-shadow   # remove ~/.claude/skills copies that shadow the plugin
```

Generic Agent Skills clients:

```bash
npx skills add passioncode-ai/fabric-agent-adapter --skill adapting-projects-to-fabric
npx skills add passioncode-ai/fabric-agent-adapter --skill creating-fabric-agents
npx skills add passioncode-ai/fabric-agent-adapter --skill building-fabric-services
```

Claude Code plugin marketplace:

```text
/plugin marketplace add passioncode-ai/fabric-agent-adapter
/plugin install fabric-agent-adapter@fabric-agent-adapter
```

## Use

Ask the agent explicitly:

```text
Adapt this project for Fabric compatibility. Inspect it, choose the profile per
capability, scaffold the provider bundle, and report every conformance gate.
```

Or, for an agent that must keep running with a dashboard:

```text
Make this agent a local service with an always-on dashboard, following fabric-service/0.1.
```

Or, for an agent that does not exist yet:

```text
Create a new fabric-compatible agent for <capability>; its consumer is <who calls it>.
```

Or run the deterministic helper directly:

```bash
SKILL_DIR=plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric
python3 "$SKILL_DIR/scripts/adapt_project.py" inspect /path/to/project --json
python3 "$SKILL_DIR/scripts/adapt_project.py" scaffold /path/to/project \
  --profile mcp \
  --provider-id https://agents.example/providers/demo \
  --provider-name "Demo provider" \
  --capability-id https://agents.example/capabilities/demo \
  --capability-name demo.run \
  --schema-base https://agents.example/fabric
python3 "$SKILL_DIR/scripts/adapt_project.py" check /path/to/project \
  --contract /path/to/fabric-agent-contract --json
```

Scaffolding is non-destructive by default. It writes only the paths declared in the
[delivery brief](docs/evidence/specs/2026-08-27-brief.md) and refuses collisions.

## Verify one service (newcomer path)

After installing (above), with Python 3.9+ and no other dependency:

```bash
KIT=plugins/fabric-agent-adapter/skills/building-fabric-services/scripts   # or ~/.agents/skills/building-fabric-services/scripts
DATA=$(mktemp -d); SERVICES=$(mktemp -d)
python3 "$KIT/sample_service.py" serve --port 47190 --data-dir "$DATA" &
python3 "$KIT/sample_service.py" register --port 47190 --data-dir "$DATA" --services-dir "$SERVICES"
python3 "$KIT/check_service.py" sample --services-dir "$SERVICES"   # exit 0: no FAIL
kill %1
```

The probe prints one line per rule — `PASS`, `FAIL` or `NOT_RUN` with its evidence — and
exits 1 on any `FAIL`. Run it against your own service by its id once its installer has
written the descriptor.

## Validate this repository

```bash
python3 -m unittest discover -s test -v
python3 test/validate.py
claude plugin validate ./plugins/fabric-agent-adapter --strict
claude plugin validate . --strict
```

`test/validate.py` reads every SKILL.md front matter as strictly as a YAML parser does; an
unquoted value holding `: ` fails it. `python3 test/validate.py --frontmatter <SKILL.md ...>`
checks copies installed elsewhere, such as `~/.agents/skills/*/SKILL.md`.

## Contract pin

The one pin is [`fabric-contract.lock.json`](fabric-contract.lock.json):

- version: `0.1.0`
- commit: `a22dea359ba04b8fe549abe81a5131552cb90eff`

Every other mention of the contract revision — this section, the skills' metadata, the
skill card, `adapt_project.py` — must equal it; `python3 test/validate.py` fails a tree
where one does not. The contract repository is normative. Updating the pin requires a
new adapter release, fixture review, and a complete validation run.

## License

Source-available under PolyForm Noncommercial or Internal Use; commercial license on
request (contact@passioncode.ai). SPDX:
`PolyForm-Noncommercial-1.0.0 OR LicenseRef-PolyForm-Internal-Use-1.0.0` — see
[LICENSE](LICENSE). Versions up to and including v0.4.2 (on GitHub and on npm) were
released under the MIT License and remain available under it. Contributions are accepted under
[CLA.md](CLA.md) ([CONTRIBUTING.md](CONTRIBUTING.md)).
