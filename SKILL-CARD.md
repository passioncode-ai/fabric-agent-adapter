# Skill card: adapting-projects-to-fabric

| Field | Value |
|---|---|
| Version | `0.8.3` |
| Plugin | `fabric-agent-adapter` |
| Contract | Fabric Agent Contract `0.1.0` at `52da526d7cc1e063d74c5b520dbc03d0ace15246` |
| Purpose | Adapt an existing stable agent/API/CLI surface into a proposed Fabric provider bundle |
| Inputs | project root, capability, lifecycle owner, stable identifiers, schema publication base |
| Outputs | provider manifest, lock, schemas, fixture, assertions, conformance report; a `fabric-provider/0.1` entry for an agent that is not a service (`fabric_provider.py`) |
| Mutations | only the seven documented target-project paths; collisions refused by default; `fabric_provider.py write` writes one entry in the providers directory |
| Network | not required for structural mode; a contract checkout (public repository) required for exact schema validation |
| Secrets | never accepted or emitted |

Triggers include explicit requests to connect, adapt, migrate, or check a project against
the Fabric Agent Contract. It does not trigger for generic agent construction, Fabric host
implementation, MCP client configuration, or whole-project audits.

The skill may recommend A2A, MCP, local runner, or `undetermined`. It cannot admit or bind
a provider because those actions require a real Fabric host/runtime.


# Skill card: creating-fabric-agents

| Field | Value |
|---|---|
| Version | `0.8.3` |
| Plugin | `fabric-agent-adapter` |
| Contract | Fabric Agent Contract `0.1.0` at `52da526d7cc1e063d74c5b520dbc03d0ace15246` |
| Purpose | Design a new agent so Fabric compatibility is a property of its first commit |
| Inputs | capability, named consumer, workflow-or-agent decision, profile, effect and tenancy declarations, knowledge sources |
| Outputs | intake-grill record, knowledge pack with trap-derived fixtures, project skeleton, provider bundle via the sibling scaffolder, conformance report with the canary expectation |
| Mutations | new project files plus the sibling scaffolder's documented target paths; collisions refused by default |
| Network | not required for structural mode; a contract checkout (public repository) required for exact schema validation |
| Secrets | never accepted or emitted |

Triggers include explicit requests to create, design, or build a NEW Fabric-compatible
agent or provider. It does not trigger for adapting an existing project (the sibling
skill), Fabric host implementation, or generic agent construction.

The grill refuses to proceed without a named consumer, and the report always carries the
canary-binding expectation: checker plus budget cap until a recorded promotion.


# Skill card: building-fabric-services

| Field | Value |
|---|---|
| Version | `0.8.3` |
| Plugin | `fabric-agent-adapter` |
| Extension | `fabric-service/0.1` (DEC-0015) and `fabric-interop/0.1` (DEC-0016), Fabric Agent Contract at `52da526d7cc1e063d74c5b520dbc03d0ace15246`; the remote placement (DEC-0019) |
| Purpose | Build or migrate a long-lived local agent service with a dashboard that is always alive, runs once, keeps its state and is discoverable |
| Inputs | service id, port, callers and surfaces, store, notification-worthy events |
| Outputs | service code using the Python or Node kit, launchd plist, descriptor, events view, login flow, an MCP surface with jobs and trace context, probe report |
| Mutations | the target service's files; the plist in `~/Library/LaunchAgents`; one descriptor in the services directory |
| Network | loopback only; the probe talks to `127.0.0.1:<port>`, and over MCP calls only `tools/list` and `fabric.job.get` for a made-up id |
| Secrets | the service token is created 0600 and read, never printed |

Triggers include making an agent a local service, an always-on dashboard, where an agent
stores settings, connecting a service to Fabric Dashboards, and migrating or checking a
service against `fabric-service/0.1`. It does not trigger for cron jobs, hosted SaaS, the
provider manifest (the adapting skill) or the Fabric Dashboards app.
