# Profile selection

Load this reference when choosing or reviewing a profile for one capability.

## Decision

```text
Does a remote peer accept an outcome and own task progress, artifacts,
cancellation, and terminal state?
  yes -> A2A 1.0
  no  -> Does Fabric call a bounded remote or stdio capability?
          yes -> MCP 2026-07-28
          no  -> Does Fabric start an installed terminal process?
                  yes -> fabric-local-runner/0.1
                  no  -> unsupported until a stable surface exists
```

The protocol is selected per capability. A provider may expose several capabilities
through different profiles, but one capability cannot change profile during a pinned run.

## A2A

Use when the remote system owns an opaque autonomous task lifecycle. Require:

- HTTPS Agent Card and stable skill IDs;
- A2A `1.0` binding and authentication declaration;
- mapping for submitted, working, input-required, completed, failed, and cancelled states;
- artifact and evidence mapping;
- cancellation and safe semantic probes.

An ordinary job API may be wrapped as A2A only when the adapter faithfully owns these
task semantics. A long HTTP request alone is not proof of autonomy.

## MCP

Use when Fabric owns planning, ordering, retries, and task completion while invoking
bounded provider features. Require:

- MCP `2026-07-28` over streamable HTTP or stdio;
- exact required feature names (`tool:`, `resource:`, or `prompt:`);
- typed inputs and outputs;
- idempotency and effect declarations;
- bounded feature-level probes.

An MCP server is a capability provider, not automatically an autonomous peer.

## Local runner

Use when Fabric launches an installed process such as a coding CLI. Require:

- profile `fabric-local-runner/0.1`;
- stable `executableRef`, never a secret-bearing shell string;
- argument array and typed input mode;
- immutable result URI convention;
- signal or declared cancellation behaviour;
- heartbeat and partial-result behaviour;
- project-scoped account selection outside the manifest.

The user may choose the project's default terminal and override it per agent. Model choice
stays inside the selected agent/provider; the Fabric profile remains model-agnostic.

## Reject or defer

Return `undetermined` or blocked when:

- more than one surface exists and the requested capability is unclear;
- task lifecycle ownership is not observable;
- the only integration surface is a browser UI;
- the provider cannot supply typed input/output boundaries;
- safe non-publishing probes cannot be defined.

