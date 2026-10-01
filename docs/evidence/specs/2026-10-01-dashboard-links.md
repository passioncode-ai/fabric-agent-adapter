# Dashboard handoff rule and portable gate

Initial authorized scope (extended to release/install by the operator on 2026-10-01): retrofit the three existing Fabric skills and their generated
agent/service handoff instructions. No release, cache replacement, protocol pin
change or new globally active hook. Skills cannot force every host's final answer.

R1: hand back the resolver's open_link, not raw HTTP, for registered dashboards.
R2: absent is distinct from failed/unknown; no browser fallback on a failed host.
R3: remote viewers need a device-addressed action, not the computer's localhost.
R4: neutral examples, self-contained skill directories, byte-identical shared
reference and gate, Python stdlib; headless agents and API URLs remain unaffected.

Frozen cases: test/evals/dashboard-links/cases.json. Mechanical gate test first;
provider/model output evaluation is recorded separately, never inferred from a lint.
Use task-pipeline implementation profile and make-skill retrofit: spec/evals →
minimum prose + portable gate → repository tests → branch handoff. Sources read:
AGENTS.md, fabric-workspace knowledge, existing three skills and service refs;
Fabric Dashboards MCP link/open and canonical link ADR-0005 (v0.3.1).
Contradictions: existing CLI advice says to use the installed host but provides no
shared consumer procedure or output check. MCP registration follows the operator's
gateway policy; this change writes no machine/client configuration.
