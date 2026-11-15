# Impact map: Fabric Agent Contract `v0.1.0+2026-11-14.2` (`ced7b292`) to `v0.1.0+2026-11-15` (`2462c90b`), FAA-337

Written 2026-11-15 with the repin. `kit/` is `plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/`.

## 1. Source ledger

| Fact | Evidence |
|---|---|
| New pin `2462c90b4108e56d35be6a275d9043059c95d5d0` = tag `v0.1.0+2026-11-15` | the contract's board message `af7e6811` (thread `b2eef40c`); `git -C fabric-agent-contract rev-parse 2462c90b` |
| 61 files, +4637 / -88; `src/` changes in `actions.ts`, `entitlement.ts`, new `org-instance.ts`, `protocol-revisions.ts`, `semantic-kinds.ts`, `semantic-rules.ts`, `signing-challenges.ts` | `git diff --stat ced7b292 2462c90b` |
| New decisions DEC-0168 (CT-299, `entitlement/2`), DEC-0169 (CT-311, read parity, `FAC-SEM-176`), DEC-0170 (CT-314, `org-instance/1`) | the same message; `docs/DECISIONS.md` |
| `contractVersion` stays `0.1.0`; `ced7b292` stays supported | each decision's Compatibility paragraph; `SUPPORTED_CONTRACT_COMMITS` |

## 2. Per decision

| Decision | What it decides | Kit reader | Verdict |
|---|---|---|---|
| DEC-0168: `entitlement/2` with `allowances` (`FAC-SEM-175`) | `src/entitlement.ts`, `schemas/entitlement-2.schema.json` | the protocol table only (`entitlement` `1` and `2`); the kit issues and verifies no entitlement | adopted as a known revision; signing and verification are the platform's and the verifiers' |
| DEC-0169 RP-1, RP-2: read parity and the design order | `docs/specification/service.md` | `references/agent-surface.md` AS-1 to AS-6 (0.88.0, cited since 0.90.1) | adopted |
| DEC-0169 RP-3: `FAC-SEM-176` | `src/actions.ts` `agentSurfaceRules`, four `service-well-known-agent-surface-*` fixtures | `kit/fabric_actions.py` `agent_surface_rules`, `kit/fabric-actions.mjs` `agentSurfaceRules`; the probe's `dashboard.agent-surface` (0.90.1) | adopted; `actions-vectors.json` `agentSurfaces` (4); `build_well_known` does not refuse it yet, so a service's update never fails on a rule its next pin brings (the probe reports it) |
| DEC-0170: `org-instance/1` (`FAC-SEM-177`) | `src/org-instance.ts` | the protocol table only (`org-instance` `1`) | adopted as a known revision; the statement is the organization server's and the platform's |

## 3. Vectors regenerated on a clean tree of the pin

`vendor_vectors.mjs` (`feed-protocols-vectors.json`: the register), `make_actions_vectors.mjs` with `--extra`
(`actions-vectors.json`: `agentSurfaces`), and `make_levels_vectors.mjs`, `make_load_vectors.mjs`,
`make_source_vectors.mjs`, `make_channel_agent_vectors.mjs` (each only its recorded commit changed).
