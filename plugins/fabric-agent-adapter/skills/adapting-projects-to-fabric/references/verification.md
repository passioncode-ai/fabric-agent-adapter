# Verification and verdicts

Load this reference before interpreting checks or writing a conformance claim.

## Independent gates

| Gate | PASS requires | Does not prove |
|---|---|---|
| Local structure | expected files parse, lock matches, revision fields are exact, no forbidden secret-like fields | normative JSON Schema validity |
| Declaration shape | pinned contract validator accepts the real manifest | endpoint identity, reachability, or behaviour |
| Protocol negotiation | live provider accepts the exact MCP/A2A/local-runner revision and identity checks | semantic correctness |
| Semantic probes | bounded fixtures produce typed outputs and satisfy meaning/evidence assertions | authorization for a project |
| Binding readiness | admitted capability can be pinned with project context, pool, grants, policies, and checker | that a binding has been activated |

Use only `PASS`, `FAIL`, `NOT_RUN`, and `NOT_VERIFIED`:

- `NOT_RUN`: the check exists but its required tool, checkout, endpoint, or credential was unavailable.
- `NOT_VERIFIED`: no implemented verifier/runtime currently exists for the claim.
- Never relabel either as a warning-level pass.

## Receipts

A receipt names what ran and what identity was tested:

- command and exit code;
- contract commit and schema ID;
- provider revision/content hash;
- endpoint or executable identity;
- fixture and immutable result/artifact URI;
- assertion results and unverified surfaces;
- admission and binding revisions when they exist.

Transport logs without semantic assertions are insufficient. A prose statement without a
resolvable receipt remains unverified.

## Degraded operation

If the pinned contract checkout or its dependencies are absent:

1. run local structure only;
2. retain declaration shape as `NOT_RUN`;
3. name the exact pinned checkout and command needed;
4. continue implementation only as a draft.

If the Fabric host/admission runtime is absent, protocol, semantics, and binding remain
`NOT_VERIFIED`. Deliver the provider bundle and adapter tests, but do not claim it is
connected or admitted.

## Replacement and rollback

Any manifest change produces a new provider revision and content hash. It must receive a
new admission decision and a new project-binding revision. Existing runs stay pinned.
Rollback creates another binding revision based on known-good immutable inputs; it never
rewrites history.

