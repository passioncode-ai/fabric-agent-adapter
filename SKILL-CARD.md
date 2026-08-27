# Skill card: adapting-projects-to-fabric

| Field | Value |
|---|---|
| Version | `0.3.1` |
| Plugin | `fabric-agent-adapter` |
| Contract | Fabric Agent Contract `0.1.0` at `20a818e648a4c09a60df0126d11626922e8b9094` |
| Purpose | Adapt an existing stable agent/API/CLI surface into a proposed Fabric provider bundle |
| Inputs | project root, capability, lifecycle owner, stable identifiers, schema publication base |
| Outputs | provider manifest, lock, schemas, fixture, assertions, conformance report |
| Mutations | only the seven documented target-project paths; collisions refused by default |
| Network | not required for structural mode; private contract checkout required for exact schema validation |
| Secrets | never accepted or emitted |

Triggers include explicit requests to connect, adapt, migrate, or check a project against
the Fabric Agent Contract. It does not trigger for generic agent construction, Fabric host
implementation, MCP client configuration, or whole-project audits.

The skill may recommend A2A, MCP, local runner, or `undetermined`. It cannot admit or bind
a provider because those actions require a real Fabric host/runtime.


# Skill card: creating-fabric-agents

| Field | Value |
|---|---|
| Version | `0.3.1` |
| Plugin | `fabric-agent-adapter` |
| Contract | Fabric Agent Contract `0.1.0` at `20a818e648a4c09a60df0126d11626922e8b9094` |
| Purpose | Design a new agent so Fabric compatibility is a property of its first commit |
| Inputs | capability, named consumer, workflow-or-agent decision, profile, effect and tenancy declarations, knowledge sources |
| Outputs | intake-grill record, knowledge pack with trap-derived fixtures, project skeleton, provider bundle via the sibling scaffolder, conformance report with the canary expectation |
| Mutations | new project files plus the sibling scaffolder's documented target paths; collisions refused by default |
| Network | not required for structural mode; private contract checkout required for exact schema validation |
| Secrets | never accepted or emitted |

Triggers include explicit requests to create, design, or build a NEW Fabric-compatible
agent or provider. It does not trigger for adapting an existing project (the sibling
skill), Fabric host implementation, or generic agent construction.

The grill refuses to proceed without a named consumer, and the report always carries the
canary-binding expectation: checker plus budget cap until a recorded promotion.
