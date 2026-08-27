# Skill card: adapting-projects-to-fabric

| Field | Value |
|---|---|
| Version | `0.1.0` |
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

