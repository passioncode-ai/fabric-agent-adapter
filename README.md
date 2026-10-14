<p align="center">
  <a href="https://passioncode.ai/">
    <img src="assets/passioncode-icon-256.png" width="104" height="104" alt="PassionCode.ai passion fruit mark">
  </a>
</p>

# Fabric Agent Adapter

**Fabric Agent Adapter** makes any agent Fabric-compatible. Fabric is PassionCode.ai's
product, the CEO AI agent: you talk to Fabric, and it chooses, binds and runs the agents that
do the work. This adapter is how an agent becomes one Fabric can bind — four Agent Skills,
Python and Node reference kits and a live conformance probe for the
[Fabric Agent Contract](https://github.com/passioncode-ai/fabric-agent-contract). It also works
on its own: the skills, kits and probe need no Fabric install.

[![npm](https://img.shields.io/npm/v/%40passioncode-ai%2Ffabric-agent-adapter)](https://www.npmjs.com/package/@passioncode-ai/fabric-agent-adapter)
[![validate](https://github.com/passioncode-ai/fabric-agent-adapter/actions/workflows/validate.yml/badge.svg)](https://github.com/passioncode-ai/fabric-agent-adapter/actions/workflows/validate.yml)
[![license](https://img.shields.io/badge/license-AGPL--3.0%20or%20commercial-blue.svg)](LICENSE)

The skills are `adapting-projects-to-fabric`, `creating-fabric-agents`,
`building-fabric-services` and `working-with-fabric`.

`working-with-fabric` is for the other side: a coding agent (Claude Code, Codex, Kimi Code, Kilo, Hermes) opened in
a terminal that works in a project through Fabric. It finds Fabric (`hub.json`, its `pid`), has the machine's
lifecycle broker start it when it is down, registers `fabric-mcp` once with no secret, calls `fabric_whoami`
first, reads the project board (`com.status`, `com.list`, `com.read_ack` only what was read) and asks other
Projects only through `com.submit`, asks who is working on what and claims its task before it starts
(`fabric_work_list`, `fabric_work_claim`, Fabric 0.4.0), links tasks to backlog rows instead of copying them, and
releases at the end (`fabric_work_release`). `scripts/fabric_session.py status` prints where Fabric stands and one
next action:

```bash
python3 plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/fabric_session.py status
```

In Claude Code the plugin adds four session hooks: SessionStart puts that preamble into the session when the MCP
server `fabric` is registered (one line pointing at the broker when Fabric is down), with the machine's
Fabric-service count; Stop records each turn's facts (HEAD, files changed, lines added and removed — never content)
and the board's unread count; UserPromptSubmit adds one line only when that count rose; SessionEnd releases what the
session left claimed. Stop, UserPromptSubmit and SessionEnd act only when the running Fabric advertises
`session-hooks/1`. All are silent in a session Fabric launched, never block the session, read no token and always
exit 0. `fabric_session.py watch-mail` waits for board mail under a background watcher, and `install-host-hooks
--host codex|kimi` adds the session-start preamble to Codex or Kimi Code (a dry run unless `--apply`). The
[hooks reference](plugins/fabric-agent-adapter/skills/working-with-fabric/references/session-hooks.md) lists what
they need from Fabric; the [board reference](plugins/fabric-agent-adapter/skills/working-with-fabric/references/project-board.md)
is the board-first workflow.

`building-fabric-services` makes an agent a long-lived local service with a dashboard
that is always alive, runs as one copy, keeps its state through a reinstall and appears
in Fabric Dashboards by itself — the `fabric-service/0.1` extension. It also makes an **online** agent
or dashboard — an `https` origin on a platform — a Fabric service (the remote placement, DEC-0019): the same
four routes behind the token, a `__Host-` session cookie, and one descriptor on the operator's computer;
`scripts/sample-remote-service.mjs` is the complete example. It ships Python and
Node reference kits (`scripts/fabric_service.py`, `scripts/fabric-service.mjs`), a
complete `scripts/sample_service.py`, and `scripts/check_service.py`, a live probe. A service that answers
requests other Projects post to its Project on Fabric's project board uses the board responder
(`scripts/fabric_hub.py` and `scripts/fabric_board.py`, Node `fabric-hub.mjs` and `fabric-board.mjs`): the
`board.respond` grant, enroll, claim, accept the exact digest, complete, a checkpoint before every step, and restarts
that reconcile or take accepted work back by a transfer (the [board reference](plugins/fabric-agent-adapter/skills/building-fabric-services/references/board.md)):

```bash
python3 plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/check_service.py example-agent
```

The dashboard itself is built from the **dashboard kit** (`assets/dashboard-kit/`, `fabric-dashboard/0.1`,
contract DEC-0036): one stylesheet and one script that keep the page usable from 360 CSS px inside a host
pane beside the agent console — navigation that folds into a More menu, wide tables in their own scroll
box, sticky chrome at most 120 px — with seven WCAG AA themes (light and dark) that follow the host's
`fabric_appearance` cookie. `scripts/dashboard_kit.py install|status` copies and checks it,
`scripts/check_dashboard_layout.mjs` measures a rendered page in WebKit at 360, 480, 768 and 1280 px
(Playwright; `NOT_RUN` without it), and the probe's `dashboard.declared` checks the declaration. The
plugin's dashboard-kit hook (SessionStart) prints a single line in a repository whose dashboard has no kit or an
older one, and nothing anywhere else; the [kit reference](plugins/fabric-agent-adapter/skills/building-fabric-services/references/dashboard-kit.md)
has the upgrade steps, taken only with the operator's go-ahead.

Dashboard handoffs use the host-generated `open_link` as the primary action. The
three builder skills carry the same [consumer procedure](plugins/fabric-agent-adapter/skills/building-fabric-services/references/dashboard-links.md)
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
npx skills add passioncode-ai/fabric-agent-adapter --skill working-with-fabric
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

Or, in a coding agent opened in a project folder:

```text
Work on backlog row FAA-18 through Fabric: check who is working here, claim it, and release it when done.
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
  --schema-base https://agents.example/fabric \
  --effect none
python3 "$SKILL_DIR/scripts/adapt_project.py" check /path/to/project \
  --contract /path/to/fabric-agent-contract --json
```

Pack, sign and verify an agent as a `fabric-package/1` folder (contract DEC-0050, DEC-0051; nothing is written without
`--apply`, and the key file is the person's, never made or kept here):

```bash
npx @passioncode-ai/fabric-agent-adapter pack ./example-agent            # the digest, agentRef and every problem
npx @passioncode-ai/fabric-agent-adapter pack ./example-agent --apply
npx @passioncode-ai/fabric-agent-adapter sign ./example-agent --key ./publisher.jwk --apply
npx @passioncode-ai/fabric-agent-adapter verify ./example-agent --trust ./trust.json
```

See [the package reference](plugins/fabric-agent-adapter/skills/building-fabric-services/references/package.md).

Scaffolding is non-destructive by default. It writes only the paths declared in the
[delivery brief](docs/evidence/specs/2026-08-27-brief.md) and refuses collisions.

## Contract pin

The default pin for new bundles is [`fabric-contract.lock.json`](fabric-contract.lock.json):

- version: `0.1.0`
- commit: `1636fa97262f4a26e2086572d540c2ee701e0010`

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
This source checkout is 0.21.0. 0.20.0 is the latest published GitHub/npm release (2026-10-12; 0.7.0 and 0.11.0
were never released); 0.21.0 is published by its `v0.21.0` tag. Source delivery does not update installed skills or live sessions.

## License

Open source under the [GNU AGPL-3.0](LICENSE). A [commercial license](COMMERCIAL-LICENSE.md) is
available for use that does not meet the AGPL's terms — [passioncode.ai/business](https://passioncode.ai/business/).
Versions before 0.5.3 were released under PolyForm Noncommercial or Internal Use (v0.4.3 to
v0.5.2) and MIT (v0.4.2 and earlier); each keeps the licence it was released under.
Contributions are accepted under [CLA.md](CLA.md) ([CONTRIBUTING.md](CONTRIBUTING.md)).
