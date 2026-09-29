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

- version: `0.1.0`
- commit: `a5a27092ba0dcc5facfbeae8b359146dfb403e9a`

The contract repository is normative. Updating the pin requires a new adapter release,
fixture review, and a complete validation run.

## License

Source-available under PolyForm Noncommercial or Internal Use; commercial license on
request (contact@passioncode.ai). SPDX:
`PolyForm-Noncommercial-1.0.0 OR LicenseRef-PolyForm-Internal-Use-1.0.0` — see
[LICENSE](LICENSE). Versions up to and including v0.4.2 (on GitHub and on npm) were
released under the MIT License and remain available under it. Contributions are accepted under
[CLA.md](CLA.md) ([CONTRIBUTING.md](CONTRIBUTING.md)).
