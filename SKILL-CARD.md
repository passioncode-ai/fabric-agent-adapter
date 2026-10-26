# Skill card: adapting-projects-to-fabric

| Field | Value |
|---|---|
| Version | `0.51.0` |
| Plugin | `fabric-agent-adapter` |
| Contract | Fabric Agent Contract `0.1.0` at `e6c4fc16b415eec3190dd34d924d269405359dc9` |
| Purpose | Adapt an existing stable agent/API/CLI surface into a proposed Fabric provider bundle |
| Inputs | project root, capability, lifecycle owner, stable identifiers, schema publication base |
| Outputs | provider manifest, lock, schemas, fixture, assertions, conformance report; a `fabric-provider/0.1` entry for an agent that is not a service (`fabric_provider.py`) |
| Mutations | only the seven documented target-project paths; collisions refused by default, `scaffold --dry-run` shows each diff and writes nothing; `fabric_provider.py write` writes one entry in the providers directory |
| Network | none of its own: structural mode reads local files; exact schema validation runs a local contract checkout's own `tsx` (the checkout is a public repository, fetched by the person) |
| Secrets | never accepted or emitted |

Triggers include explicit requests to connect, adapt, migrate, or check a project against
the Fabric Agent Contract. It does not trigger for generic agent construction (creating-fabric-agents), running an
agent as a Fabric service (building-fabric-services), a coding session working through Fabric (working-with-fabric),
Fabric host implementation, MCP client configuration, or whole-project audits.

The skill may recommend A2A, MCP, local runner, or `undetermined`. It cannot admit or bind
a provider because those actions require a real Fabric host/runtime.


# Skill card: creating-fabric-agents

| Field | Value |
|---|---|
| Version | `0.51.0` |
| Plugin | `fabric-agent-adapter` |
| Contract | Fabric Agent Contract `0.1.0` at `e6c4fc16b415eec3190dd34d924d269405359dc9` |
| Purpose | Design a new agent so Fabric compatibility is a property of its first commit |
| Inputs | capability, named consumer, workflow-or-agent decision, profile, effect declarations, where it runs and in which contexts, models per lane, who pays, how it learns, knowledge sources |
| Outputs | intake-grill record, knowledge pack with trap-derived fixtures, project skeleton, provider bundle via the sibling scaffolder, conformance report with the canary expectation |
| Mutations | new project files plus the sibling scaffolder's documented target paths; collisions refused by default |
| Network | not required for structural mode; a contract checkout (public repository) required for exact schema validation |
| Secrets | never accepted or emitted |

Triggers include explicit requests to create, design, or build a NEW Fabric-compatible
agent or provider. It does not trigger for adapting an existing project (adapting-projects-to-fabric), running an
agent as a Fabric service (building-fabric-services), a session working through Fabric (working-with-fabric), Fabric
host implementation, or generic agent construction.

The grill refuses to proceed without a named consumer, and the report always carries the
canary-binding expectation: checker plus budget cap until a recorded promotion.


# Skill card: building-fabric-services

| Field | Value |
|---|---|
| Version | `0.51.0` |
| Plugin | `fabric-agent-adapter` |
| Extension | `fabric-service/0.1` (DEC-0015) and `fabric-interop/0.1` (DEC-0016), Fabric Agent Contract at `e6c4fc16b415eec3190dd34d924d269405359dc9`; the remote placement (DEC-0019); the embedded dashboard `fabric-dashboard/0.1` (DEC-0036); dashboard action parity `fabric-actions/0.1` (DEC-0121); the operator's mandate `mandate/1` (DEC-0125) |
| Purpose | Build or migrate a long-lived local agent service with a dashboard that is always alive, runs once, keeps its state and is discoverable |
| Inputs | service id, port, callers and surfaces, store, notification-worthy events |
| Outputs | service code using the Python or Node kit, launchd plist, descriptor, events view, login flow, an MCP surface with jobs and trace context, an optional project-board responder (`fabric_board`, `fabric-board.mjs`), a dashboard built from the dashboard kit with its ED-9 declaration and its action table (`extensions/actions/0.1`), a signed `fabric-package/1` folder (`fabric_package`, `fabric-package.mjs`), probe and layout-probe reports |
| Mutations | the target service's files; its supervisor file when its installer runs (a launchd plist in `~/Library/LaunchAgents`, a systemd user unit, or a per-user Scheduled Task); one descriptor in the services directory |
| Network | the probe talks to `127.0.0.1:<port>` for a local service and to the service's own `https` origin for a remote placement, and over MCP calls only `tools/list` and `fabric.job.get` for a made-up id; a board responder talks only to Fabric's hub at the `http://127.0.0.1:<port>` its `hub.json` names, after checking that file's pid; the layout probe opens the dashboard in a local headless browser with a one-time login code; the kit's connectors (`fabric_http`, `fabric_openrouter`) reach the external APIs the service's author configures |
| Secrets | the service token is created 0600 and read, never printed; a board responder's binding credential lives in a 0600 file, read for each join and never logged |

Triggers include making an agent a local service, an always-on dashboard, where an agent
stores settings, connecting a service to Fabric Dashboards, answering a Project's requests on the
project board, and migrating or checking a
service against `fabric-service/0.1`. It does not trigger for cron jobs, hosted SaaS, the
provider manifest (adapting-projects-to-fabric), a new agent's design (creating-fabric-agents), a coding session
using Fabric (working-with-fabric) or the Fabric Dashboards app.

# Skill card: working-with-fabric

| Field | Value |
|---|---|
| Version | `0.51.0` |
| Plugin | `fabric-agent-adapter` |
| Fabric | the desktop app 0.4.0 or later (`fabric-mcp`, `fabric_work_list`, `fabric_work_claim`, `fabric_work_release`); older Fabric falls back to the `fabric_task_*` tools |
| Purpose | A coding agent opened outside Fabric works in a project through it: find Fabric, have the lifecycle broker start it, register `fabric-mcp` with no secret, `fabric_whoami` first, read the project board and ask other Projects only through `com.submit`, relay the operator's own decision on a service's action, or the mandate he gave another of his agents (DEC-0125), coordinate, report, link backlog rows, release |
| Inputs | the agent's folder; Fabric's `hub.json`; the agent's MCP configuration (read, not written, by the status script) |
| Outputs | `fabric_session.py status`: Fabric's state, the registrations and one next action; `watch-mail`: one line each time the board's unread count rises |
| Mutations | none by `status`; `watch-mail` renews the session's `rejoined` mark in the hooks' spool when that folder exists; the hooks write only their own log and spool in the user's cache folder (and prune their own stale spool folders even while inert); `install-host-hooks --apply` edits Codex's `hooks.json` or Kimi Code's `config.toml` after a backup, only on the person's go-ahead |
| Hooks | Claude Code: SessionStart at startup and `/clear` (preamble when `fabric` is registered and Fabric runs; one line when it is down, only in a project that uses Fabric), Stop (turn facts and the unread count), UserPromptSubmit (one line when the count rose), SessionEnd (release), the last three spooling and calling Fabric only when it advertises `session-hooks/1` (Stop and SessionEnd always prune their own stale spool); Codex and Kimi Code: the SessionStart preamble only. Silent in a session Fabric launched; never block, always exit 0 |
| Network | none of its own; Fabric is reached only through `fabric-mcp` |
| Secrets | never read: the door token and credentials stay with `fabric-mcp`; nothing secret in argv or logs |

Triggers include connecting a coding agent to Fabric, registering `fabric-mcp`, the project board (unread mail, asking
another project, replying), claiming or releasing work, and reading a `fabric_whoami` or refusal answer. It does not trigger for building or adapting agents to the Fabric
contract, Fabric's own code, or agent-sync leases.
