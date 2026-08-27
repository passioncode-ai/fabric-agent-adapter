# Provider bundle

Load this reference before scaffolding files or implementing the adapter mapping.

## Files

| Path | Responsibility |
|---|---|
| `fabric-agent.json` | versioned provider identity, capabilities, effects, profile, and probes |
| `fabric-contract.lock.json` | normative repository, contract version, immutable commit, selected profile |
| `fabric/schemas/capability-input.schema.json` | provider-specific input boundary |
| `fabric/schemas/capability-output.schema.json` | provider-specific output boundary |
| `fabric/fixtures/admission-input.json` | bounded repeatable probe input |
| `fabric/probes/assertions.md` | semantic and safety properties checked by admission |
| `fabric/FABRIC-CONFORMANCE.md` | receipts and explicit unverified gates |

The layout packages an implementation; it does not replace the normative contract.

## Manifest mapping

For every capability, establish:

- a stable provider URI, monotonic revision, immutable content hash, author, and identity method;
- a stable capability URI and semantic name independent of implementation or model;
- absolute, immutable input/output schema URIs;
- the real side-effect class and idempotency behaviour;
- every accepted data class;
- exactly one profile and exact revision;
- safe input fixture, output schema, timeout, effect ceiling, and semantic assertions.

Do not include tokens, passwords, cookies, account IDs selected from an ambient shell, raw
environment dumps, or chain-of-thought. A future project binding supplies allowlisted
secret references, account pools, grants, data policy, coordination, and checker policy.

## Implementation seam

| Existing project | Adapter responsibility |
|---|---|
| Native MCP | map stable features directly and preserve MCP errors/cancellation |
| Native A2A | declare the Agent Card/skills and normalize artifacts/evidence |
| Terminal CLI | create typed input/result adapters and stable executable identity |
| Bounded HTTP API | wrap operations with MCP while Fabric owns the loop |
| Autonomous job API | map job lifecycle and artifacts to A2A tasks |
| Browser-only app | first add a supported stable API or CLI |

Completed and stopped invocations ultimately map to the Fabric result envelope: atomic
`done` claims, resolvable `proof`, pinned `scope`, `notVerified`, and immutable artifacts.
Provider-specific output schemas do not remove that normalization obligation.

## Normative paths at the pinned commit

Read these from `fabric-agent-contract` rather than copying them here:

- `schemas/manifest.schema.json`
- `schemas/result.schema.json`
- `schemas/binding.schema.json`
- `docs/specification/profiles.md`
- `docs/specification/results-and-evidence.md`
- `docs/specification/registry.md`
- `docs/specification/versioning.md`
- `fixtures/positive/manifest-{mcp,a2a,local}.json`

