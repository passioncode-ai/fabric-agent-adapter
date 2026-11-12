---
report: faa-124-pilot-rehearsal
project: fabric-agent-adapter
date: 2026-11-03
status: final
sources:
  - docs/reports/2026-10-25-audit-and-plan/README.md
  - docs/backlog.md (FAA-124)
---

# FAA-124: a rehearsal of the RM-28 pilot check on 0.59.0

The plan's step 4 ([audit and plan §4](../2026-10-25-audit-and-plan/README.md)) checks a personal agent end to end:
packed, signed, shared into both organizations on the organization platform with an `org:<id>` placement, its dashboard opened from Fabric
Dashboards, and an action approved through `_meta.decision`. The check is due 2026-11-07. This rehearsal ran every
part that can run on this machine today, with the published adapter (`npx @passioncode-ai/fabric-agent-adapter@latest`,
0.59.0), on a clean copy of a personal agent's repository (`git archive` of its `HEAD`), so nothing in the agent's own
checkout or service changed.

## Results

| Step | Result | Evidence |
|---|---|---|
| Pack | passes after three author fixes (below); 11119 files | `pack --apply`: `ok: true`, digest `sha256:b72b56d9…177d` |
| Sign (publisher) | passes | `sign --key <throwaway Ed25519 PEM, mode 600> --kid rehearsal-2026-11-03 --role publisher --apply`: `ok: true`; the key was deleted after the run |
| Verify | passes; refuses what it must | `verify --trust trust.json`: exit 0, one publisher signer; `--countersigned`: exit 1, `no-countersignature`; a README changed after signing: exit 1, `file-digest`; restored: exit 0 |
| Evals receipt | 61 passed, 0 failed, on the agent's MCP and observation-contract tests | `pytest` over its three MCP and observation-contract test files at 2026-11-03T11:18:24Z; the full suite (about 3600 tests) needs hours on this machine's load, so the receipt names this subset, which a real release does not |
| `org:<id>` placement | refuses, as it must, because no estate record exists here | the 0.59.0 kit's `context_instance`: `personal` answers `<id>.default`; `org:example-org` with no record answers `record-required`; with an empty record, `placement-missing` (FAC-SEM-074) |
| Shared into both organizations on the organization platform | **blocked** | this machine holds no estate record (the Fabric support folder has `enrollments`, `hub.json`, `services`, `tokens`, no record); organizations and their records arrive with Fabric's organization slice and the organization platform (2026-11-21, `knowledge/integration.md`, I2-4) |
| Dashboard from Fabric Dashboards | passes | `link`: `fabric-dashboards://service/<id>.<instance>?path=%2Fdashboard`; `open` with `fallback=never`: `opened_in: fabric-dashboards`, `accepted_by_os` (OS dispatch, not page readiness); host 0.8.17 |
| Action approved through `_meta.decision` | **blocked** | the Fabric Dashboards audit: 34 agents, 32 with a dashboard, 31 flagged `audit.action.notAdopted`; the 32nd is not flagged but its provider manifest has no `extensions` either, so none declares `extensions/actions/0.1`; that is CT-127, each service's owner |

## What the author had to fix to pack

1. `kind: agent` without `provider` is read as a consumer agent and asks for `skills` and `requires`; a service needs
   `provider` (its `fabric-agent.json`) and `service {id, name, entry, runtime}`.
2. `service.entry[0]` must be a file of the package (`src/<package>/service.py`), not the interpreter the
   launchd job runs (`python -m <package>.service`).
3. A provider manifest that carries `costPresets` needs the same `costPresets` in `fabric.package.json`. The refusal
   reads only `provider-manifest` and does not say why: FAA-193.

Each refusal named its rule, and the receipt's suite digest came from `pack`'s own note, as
[`references/package.md`](../../../plugins/fabric-agent-adapter/skills/building-fabric-services/references/package.md)
says.

## What it means for 2026-11-07

The adapter's own part of the pilot works on the released 0.59.0: pack, sign, verify, the fail-closed `org:` instance,
the dashboard link. The two blocked steps belong to others and do not move on the adapter: the organizations and their
estate records (Fabric's slice and the organization platform, 2026-11-21) and services that declare actions (CT-127). The pilot check on
2026-11-07 can therefore cover only what this rehearsal covered, unless one service declares an action by then; it is
reported on board thread `e5dff486`.
