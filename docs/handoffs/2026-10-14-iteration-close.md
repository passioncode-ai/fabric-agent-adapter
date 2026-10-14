# Handoff — iteration close, 2026-10-14: adapter 0.30.0 → 0.32.0

**Entry point for the next agent.** It covers what this run did, what it checked, what is left and what is waited on.

## The big goal

The Fabric Agent Adapter makes any agent Fabric-compatible: Agent Skills, two reference kits (Python, Node) and a
conformance probe, shipped as a Claude Code plugin and an npm package. Each contract decision
(`fabric-agent-contract`) is ported into both kits, held to the contract's own vectors, and released, and then the
launcher (`passioncode`) is repinned. The current stage is the organization edition (target architecture v4, roadmap
RM-28), where:

- a person's agent can be **packed and signed** (done here);
- a person's agent can be **shared into an organization under a grant, in a context** (FAA-41, waiting on the contract);
- a person's agent can be **published to an organization** (FAA-28, later);
- services cooperate through **Fabric's project board** (done, with holds, through 0.32.0).

## Done in this run

| Release | What | Board |
|---|---|---|
| 0.30.0 | launchd install and uninstall in the Node kit (byte-identical plist); the probe rule `lifecycle.supervisor-marker` | FAA-04, FAA-05 |
| 0.31.0 | `pack`, `sign`, `verify` for `fabric-package/1` in both kits and `npx @passioncode-ai/fabric-agent-adapter pack\|sign\|verify`; a consumer agent | FAA-27a, FAA-36 (RM-28 pilot) |
| 0.31.1 | a PEM-marker literal split so the launcher's vendor scan accepts the kit | — |
| 0.32.0 | pin `1636fa9`; the board kits wait under an operator's hold (DEC-0079) and read the owner's settlement (DEC-0081) | FAA-42 |

- **Launcher:** 0.2.1, then 0.2.2, which pins adapter `v0.32.0` (PC-38, PC-39). Installed on this machine.
- **Pilot:** the adapter's answer in the RM-28 pilot §4 is merged (fabric-workspace#212).
- **Fixed in this close-out:**
  - FAA-26's stale blocker corrected (`fabric-package/1` is decided);
  - AGENTS.md names the npm `pack`/`sign`/`verify` and lists them in the LC-09 footprint table;
  - workspace `roadmap.md` and `products.md` show the adapter at 0.32.0 and the launcher at 0.2.2 (fabric-workspace#226);
  - the org-index row moved from pin `a22dea3`/v0.5.0 to `1636fa9`/v0.32.0, with the Windows receipt workflow declared
    (org-index#76).

## Checks run (2026-10-14)

1. **Round 1, fresh checkout of `main`.**
   - Python: 629 tests, OK.
   - Node: 202 tests, 0 failed.
   - `validate.py`: OK. It caught a contract hash written into FAA-41; removed.
   - `claude plugin validate --strict`, both targets: passed.
   - Privacy check: 0 findings.
2. **Round 2, published artifacts.** `npx @passioncode-ai/fabric-agent-adapter@0.32.0`:
   - `pack` rebuilds the contract vector's digest exactly;
   - `sign` with an `openssl genpkey` key and `verify` both pass;
   - a tampered file fails `verify` (`file-digest`, exit 1);
   - no key bytes appear in any output;
   - the tarball carries the new files;
   - the installed plugin is byte-identical to tag `v0.32.0` (71 files).
3. **Round 3, across repositories.** These all agree: manifest versions, CHANGELOG, the pin, the release, the launcher's
   `family.json`, and the workspace.

## Open, and what each waits on

| Row | Waits on | Watcher |
|---|---|---|
| FAA-41 (RM-28 grant context, FAC-SEM-110/111) | contract DEC-0082, [PR #107](https://github.com/passioncode-ai/fabric-agent-contract/pull/107), still in fix rounds | a background poll of PR #107 in the session that wrote this (session-local) |
| FAA-26 (`new`/`test`) | Fabric's ADR-0138 D2b amendment, `fabric.agent.create`; the evals-suite format | none: read ADR-0138 on Fabric's `main` |
| FAA-27 remainder, FAA-29 | Fabric D2 (ES256), `org-countersign/1`, `org-authority/1` | none |
| FAA-28 (`publish`) | `estate-record/1`, `org-authority/1`, share grants, the first organization server | none |
| FAA-10 (A2A) | the contract's `surfaces.a2a` decision | none |
| live smokes (FAA-12b board, FAA-42 holds) | a disposable Fabric serving COM-03 and DEC-0079 | none |
| contract CT-18 and CT-42 rows (the adapter's adoption) | the contract session's lease on its `docs/backlog.md` | a background loop in the session that wrote this applies the edit when the lease frees |

## Next task

When contract PR #107 merges, take FAA-41:

1. Repin to that commit.
2. Re-vendor (`test/fixtures/contract/vendor_vectors.mjs`, run under the contract's `tsx`).
3. Port `parseContext`, `routeTarget`, `routeGrantUsage`, FAC-SEM-110 and FAC-SEM-111, plus the per-context placement
   and slot keys, into `fabric_estate.py` and `fabric-estate.mjs`.
4. Release, then repin the launcher.
