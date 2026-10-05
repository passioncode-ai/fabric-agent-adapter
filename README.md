<p align="center">
  <a href="https://passioncode.ai/">
    <img src="assets/passioncode-icon-256.png" width="104" height="104" alt="PassionCode.ai passion fruit mark">
  </a>
</p>

# Fabric Agent Adapter

**Fabric Agent Adapter** makes any agent Fabric-compatible. Fabric is PassionCode.ai's
product, the CEO AI agent: you talk to Fabric, and it chooses, binds and runs the agents that
do the work. This adapter is how an agent becomes one Fabric can bind — three Agent Skills,
Python and Node reference kits and a live conformance probe for the
[Fabric Agent Contract](https://github.com/passioncode-ai/fabric-agent-contract). It also works
on its own: the skills, kits and probe need no Fabric install.

[![npm](https://img.shields.io/npm/v/%40passioncode-ai%2Ffabric-agent-adapter)](https://www.npmjs.com/package/@passioncode-ai/fabric-agent-adapter)
[![validate](https://github.com/passioncode-ai/fabric-agent-adapter/actions/workflows/validate.yml/badge.svg)](https://github.com/passioncode-ai/fabric-agent-adapter/actions/workflows/validate.yml)
[![license](https://img.shields.io/badge/license-AGPL--3.0%20or%20commercial-blue.svg)](LICENSE)

The skills are `adapting-projects-to-fabric`, `creating-fabric-agents` and
`building-fabric-services`.

`building-fabric-services` makes an agent a long-lived local service with a dashboard
that is always alive, runs as one copy, keeps its state through a reinstall and appears
in Fabric Dashboards by itself — the `fabric-service/0.1` extension. It also makes an **online** agent
or dashboard — an `https` origin on a platform — a Fabric service (the remote placement, DEC-0019): the same
four routes behind the token, a `__Host-` session cookie, and one descriptor on the operator's computer;
`scripts/sample-remote-service.mjs` is the complete example. It ships Python and
Node reference kits (`scripts/fabric_service.py`, `scripts/fabric-service.mjs`), a
complete `scripts/sample_service.py`, and `scripts/check_service.py`, a live probe:

```bash
python3 plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/check_service.py example-agent
```

Dashboard handoffs use the host-generated `open_link` as the primary action. The
three skills carry the same [consumer procedure](plugins/fabric-agent-adapter/skills/building-fabric-services/references/dashboard-links.md)
and a portable `scripts/check_dashboard_link.py` gate for generated renderers.
It rejects primary HTTP when the host is available, failed-host browser fallback,
and local links addressed to another device. A skill install alone does not filter
every provider's final answer; the renderer must invoke the gate with trusted host
context. This checkout contains the change; published package 0.5.6 does not.

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

## Quick start for a new teammate

### Install

With the [PassionCode.ai launcher](https://github.com/passioncode-ai/passioncode) the adapter
comes with every other PassionCode.ai skill — `npx @passioncode-ai/passioncode@latest update`,
then restart your agents. Alone, without any account:

```bash
npx @passioncode-ai/fabric-agent-adapter        # installs every skill into the agents hub ~/.agents/skills
npx @passioncode-ai/fabric-agent-adapter --prune-shadow   # remove ~/.claude/skills copies that shadow the plugin
```

Claude Code plugin marketplace:

```text
/plugin marketplace add passioncode-ai/fabric-agent-adapter
/plugin install fabric-agent-adapter@fabric-agent-adapter
```

Generic Agent Skills clients:

```bash
npx skills add passioncode-ai/fabric-agent-adapter --skill adapting-projects-to-fabric
npx skills add passioncode-ai/fabric-agent-adapter --skill creating-fabric-agents
npx skills add passioncode-ai/fabric-agent-adapter --skill building-fabric-services
```

### Configure

Nothing: no account, no key, no environment variable. A service built with the kit creates
its own token file (mode 600) in its data directory.

### MCP

The adapter is not an MCP server; it builds them. Its sample service serves every capability
as the MCP tool of its name (`fabric-interop/0.1`), so the proof is a real client calling one.
With Python 3.9+ and the Claude Code CLI, in a throwaway directory and a temporary MCP config
(your own Claude Code configuration is not read or written):

```bash
KIT=plugins/fabric-agent-adapter/skills/building-fabric-services/scripts   # or ~/.agents/skills/building-fabric-services/scripts
DATA=$(mktemp -d); SERVICES=$(mktemp -d); WORK=$(mktemp -d)
python3 "$KIT/sample_service.py" serve --port 47190 --data-dir "$DATA" &
python3 "$KIT/sample_service.py" register --port 47190 --data-dir "$DATA" --services-dir "$SERVICES"
python3 "$KIT/check_service.py" sample --services-dir "$SERVICES"   # exit 0: no FAIL
# Register the service for one client run; the token goes in a header, never in argv.
python3 - "$DATA/service.token" "$WORK/mcp.json" <<'EOF'
import json, os, sys
token = open(sys.argv[1]).read().strip()
with os.fdopen(os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
    json.dump({"mcpServers": {"sample": {"type": "http", "url": "http://127.0.0.1:47190/mcp",
               "headers": {"Authorization": "Bearer " + token}}}}, f)
EOF
(cd "$WORK" && claude -p "Call the tool mcp__sample__sample_echo with text 'ping' and reply with only the text it returns." \
  --strict-mcp-config --mcp-config "$WORK/mcp.json" --allowedTools mcp__sample__sample_echo --max-turns 3 < /dev/null)
# -> ping
kill %1
```

Verified 2026-10-01 from the published npm package 0.5.4 (`npx` into a throwaway hub, `KIT`
pointing at the installed skill) with Claude Code 2.1.286: the probe reported 27 rules, 0 FAIL;
the CLI connected to the sample over streamable HTTP, called `sample.echo` and printed `ping`. The probe prints one line per rule —
`PASS`, `FAIL` or `NOT_RUN` with its evidence — and exits 1 on any `FAIL`; run it against your
own service by its id once its installer has written the descriptor.
`FABRIC_REAL_CLIENT=1 python3 -m unittest discover -s test -p test_real_client.py` repeats the connection check
(every sample tool listed, no model call) in the test suite.

### Develop

There is no build step and no dependency beyond Python 3.9+ and Node.js:

```bash
npm test                     # validate.py, the Python unit tests, the Node kit tests
python3 -m unittest discover -s test -v
python3 test/validate.py
claude plugin validate ./plugins/fabric-agent-adapter --strict
claude plugin validate . --strict
```

`test/validate.py` reads every SKILL.md front matter as strictly as a YAML parser does; an
unquoted value holding `: ` fails it. `python3 test/validate.py --frontmatter <SKILL.md ...>`
checks copies installed elsewhere, such as `~/.agents/skills/*/SKILL.md`. Start in
[AGENTS.md](AGENTS.md); contributions follow [CONTRIBUTING.md](CONTRIBUTING.md).

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

## Contract pin

The default pin for new bundles is [`fabric-contract.lock.json`](fabric-contract.lock.json):

- version: `0.1.0`
- commit: `23f9fda4c05f8a3852246ee98d4f2adf74ed0875`

Every other mention of the default contract revision — this section, the skills' metadata, the
skill card, `adapt_project.py` — must equal it; `python3 test/validate.py` fails a tree
where one does not. The sole live legacy exception is the immutable
`SUPPORTED_CONTRACT_COMMITS` declaration in the scaffolder: previously issued bundles
keep their selected legacy lock and require that exact clean contract checkout. The
checker validates the lock's contract, repository, version and supported full SHA before
running its selected schema. Unknown locks, modified checkouts and revision mismatches fail.
Missing checkouts or dependencies are `NOT_RUN`, never admission.

There is no automatic upgrade or downgrade. An intentional migration requires review of
the whole bundle and validation against the new selected schema; editing a lock alone
does not prove runtime compatibility. Underscore names such as `receive_project_message`
are declarations only: they confer no COM grant or authority. Legacy revisions cannot
validate those names. The contract repository is normative. Updating the default pin
requires fixture review, complete validation and a new adapter release before propagation.

To run both compiled-schema integration arms, install the frozen dependencies in separate
clean checkouts at the supported revisions, then run:

```bash
FABRIC_CONTRACT_OLD=/path/to/legacy-contract FABRIC_CONTRACT_NEW=/path/to/current-contract \
  python3 -m unittest discover -s test -p test_contract_revisions.py -v
```

Without both environment variables, those tests explicitly skip as `NOT_RUN`.
This source checkout is 0.8.0 pending release (0.7.0 was never released); the verified published GitHub/npm version
on 2026-10-04 is 0.6.3. Source delivery does not update installed skills or live sessions.

## License

Open source under the [GNU AGPL-3.0](LICENSE). A [commercial license](COMMERCIAL-LICENSE.md) is
available for use that does not meet the AGPL's terms — contact@passioncode.ai.
Versions before 0.5.3 were released under PolyForm Noncommercial or Internal Use (v0.4.3 to
v0.5.2) and MIT (v0.4.2 and earlier); each keeps the licence it was released under.
Contributions are accepted under [CLA.md](CLA.md) ([CONTRIBUTING.md](CONTRIBUTING.md)).
