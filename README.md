# Fabric Agent Adapter

Private, portable Agent Skill for adapting an existing agent project to the
[Fabric Agent Contract](https://github.com/passioncode-ai/fabric-agent-contract).

It helps an agent author:

- inspect the project's stable integration surfaces without executing it;
- choose A2A `1.0`, MCP `2026-07-28`, or `fabric-local-runner/0.1` per capability;
- scaffold a version-pinned provider manifest, schemas, safe fixture, probes, and
  conformance report;
- distinguish structural validation from live protocol negotiation, semantic
  admission, and project binding.

The skill never treats generated files as admission. Fabric contract `0.1.0` does not
yet ship the host registry/runtime needed to connect and authorize a live provider.

## Install

The repository is private, so authenticate GitHub access first.

Generic Agent Skills clients:

```bash
npx skills add passioncode-ai/fabric-agent-adapter --skill adapting-projects-to-fabric
npx skills add passioncode-ai/fabric-agent-adapter --skill creating-fabric-agents
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

## Contract pin

- version: `0.1.0`
- commit: `20a818e648a4c09a60df0126d11626922e8b9094`

The contract repository is normative. Updating the pin requires a new adapter release,
fixture review, and a complete validation run.

