# Impact map: Fabric Agent Contract `v0.1.0+2026-11-07.1` (`18f8d487`) to `v0.1.0+2026-11-08.1` (`93e7db16`), FAA-258

Written 2026-11-12 before the repin's code changes, then completed with what the regeneration and the suites showed.
Contract paths are at `93e7db16` unless marked. `kit/` is `plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/`;
`apf/`, `cfa/`, `wwf/`, `bfs/` are the skills `adapting-projects-to-fabric`, `creating-fabric-agents`,
`working-with-fabric`, `building-fabric-services`.

## 1. Source ledger

| Fact | Evidence |
|---|---|
| Old pin `18f8d48762edc5bfb1433657cbfe1c16196df1a6` = tag `v0.1.0+2026-11-07.1` | `fabric-contract.lock.json` before this change; `git rev-parse 'v0.1.0+2026-11-07.1^{commit}'` |
| New pin `93e7db164c7829e2783b4b7705c4113bb5201131` = tag `v0.1.0+2026-11-08.1`, the newest `v0.1.0+` tag on 2026-11-12 | `git -C fabric-agent-contract fetch --tags && git tag -l 'v0.1.0+*' --sort=-creatordate` (first line `v0.1.0+2026-11-08.1`) |
| Releases in between: `.2` `fabb7a90` (DEC-0149), `.3` `1705d0f3` (CT-254), `.4` `de8c0a7f` (DEC-0152), `.5` `3bfa5be2` (DEC-0155), `.8.1` `93e7db16` (DEC-0151) | `git rev-parse <tag>^{commit}` per tag; `git log --oneline 18f8d487..93e7db16` |
| 156 files, +23390 / -317 | `git diff --stat 18f8d487 93e7db16` |
| New decisions DEC-0149, DEC-0151, DEC-0152, DEC-0155 (DEC-0150, DEC-0153, DEC-0154 were already at the old pin) | `diff` of `grep '^### DEC-0'` of `docs/DECISIONS.md` at both commits |
| `contractVersion` stays `0.1.0` | each decision's Compatibility paragraph |

## 2. Per decision

| Release | What it decides | Kit reader | Verdict |
|---|---|---|---|
| DEC-0149 (`.2`): `fabric-source/1`, an agent's source and its instance; FAC-SEM-156 to 160; source hand-over | `schemas/fabric-source.schema.json`, `src/source-rules.ts`, `docs/specification/source.md` | `apf/scripts/fabric_source_check.py` (FAA-188 part 1); the protocol registers `kit/fabric_protocols.py`, `kit/fabric-protocols.mjs` | Register: adopt now (`fabric-source: 1`, held by `feed-protocols-vectors.json`). The source check's own key shapes: adopt now (`KEY_SHAPE_SOURCES`, `URL_SECRET_VALUE`, equal to `src/source-rules.ts:486` and `:693`). Templates laying down `fabric.source.json`, `pack` writing `secrets[]` and `state[]` from it, the hand-over, the rest of the FAC-SEM-156 to 160 parity: FAA-261 (next) |
| CT-254 (`.3`): HA-2's Linux source is the hybrid (an accepted row's own uid, the listener for a row not accept()ed) | `docs/specification/service.md` | `kit/fabric_peer_owner.py`, `kit/fabric-peer-owner.mjs` | Already matches since 0.74.0; the twins' comments drop "pending" |
| DEC-0152 (`.4`): a board message that waits for an answer is answered in the same turn; SA-6 | `docs/specification/project-comms.md`, two schema descriptions | `wwf/references/project-board.md`, the exit contract | Status word updated (accepted). Three differences the decision names for the adapter (FAA-241's question at an `active` slot; the error rule leaving a non-retryable refusal without asking; a session without the slot giving a request its state): new row |
| DEC-0155 (`.5`): a restricted socket table, RT-1 to RT-5 | `docs/specification/service.md` | `kit/fabric_peer_owner.py`, `kit/fabric-peer-owner.mjs`, `SECURITY.md`, `bfs/references/lifecycle.md`, `bfs/references/protocol.md` | Docs name RT-3 in place of CT-261. The kit's debts DEC-0155 lists (a `netstat` exit read as `table-restricted`, RT-3's exact `127.0.0.1` vouch in place of the IPv4 wildcard, an own-rows-only table read as RT-1, RT-2's libproc proof): new row for the first three, FAA-292 for RT-2 |
| DEC-0151 (`.8.1`): the channel agent standard's ticket counts in `support-quality-daily/1`; item 7, the shared detector's `SECRET_VALUE` | `src/secret-shape.ts`, `src/support-quality-rules.ts`, `schemas/support-quality-daily.schema.json` | `kit/fabric_secrets.py` and its `apf/` copy, `kit/fabric-secrets.mjs`, the three `check_dashboard_link.py`, `kit/check_service_channel_agent.py`, `bfs/assets/dashboard-kit/fabric-button.js` | Detector: adopt now in both twins and the link checkers (vectors below). `repository_name` keeps its own boundary-free, case-sensitive shapes, as the decision says. `hasJwt` (a one-pass JWT read, same answers): new row. The dashboard kit's `fabric-button.js` keeps the earlier, broader pattern (it refuses a superset): new row with the kit's 1.1.7. The kit ports no `support-quality-daily/1` rule: nothing to adopt |

## 3. `src/`

| File | Change | Kit reader | Verdict |
|---|---|---|---|
| `secret-shape.ts` (+82) | DEC-0151 `SECRET_VALUE`; `jwtSpans`, `hasJwt` | `fabric_secrets` twins, link checkers | adopt now (detector); row (`hasJwt`) |
| `protocol-revisions.ts` (+1) | `fabric-source: 1` | `fabric_protocols` twins | adopt now |
| `source-rules.ts` (new, 1454) | DEC-0149's tree check, manifest and package rules | `fabric_source_check.py` | key shapes adopt now; the rest FAA-261 |
| `channel-agent.ts` (+16) | `hasJwt`; the rename advice in canonical case | `check_service_channel_agent.py` | rename advice adopt now; vectors unchanged |
| `connections.ts` (+5) | comment on the detector's two remaining differences | `fabric_connections` twins (`_KEY_SHAPE`, `KEY_SHAPE`) | already matches; `connections-extra-vectors.json` changes through the detector |
| `ops-digest.ts` (+25) | `foldDir` through `foldPath` (one implementation), `hasJwt` | no port | none |
| `support-quality-rules.ts` (+46) | FAC-SEM-126 over the ticket counts | no port | none |
| `semantic-kinds.ts`, `semantic-rules.ts` | `source-manifest`, `source-package`, `source-tree` kinds | the kits run named rules, no kind dispatcher | none (FAA-261) |
| `session-handoff.ts` (+4) | its copy of the detector | the kits' launch-argument checks use `fabric_secrets` | already matches through the twins |
| `activity-rules.ts`, `proposal-rules.ts` | comments naming `SOURCE_HOME_PATHS` | no port | none |
| `validate-cli.ts` (+826), `validator.ts` (+44) | the contract's CLI and its messages | not used by the kits | none |

## 4. Schemas

| Schema | Change | Kit reader | Verdict |
|---|---|---|---|
| `fabric-source.schema.json` (new) | DEC-0149 | none yet | FAA-261 |
| `support-quality-daily.schema.json` (+119) | DEC-0151 ticket counts, `project` | through `vendor_vectors.mjs`'s feed fixtures only | regenerated (section 5) |
| `comms-enroll`, `comms-reply` | descriptions (DEC-0152) | `fabric_board_shapes` checks no description | none |

## 5. Vendored vectors, regenerated at `93e7db16`

Every generator ran under the contract's `tsx` on a clean worktree of the contract at the pin, with `node_modules` linked
(the command each header records; run at `18f8d487` first, every file came back byte-equal):

| File | Generator | What changed |
|---|---|---|
| `feed-protocols-vectors.json` | `vendor_vectors.mjs` | `fabric-source` in the register; the two new `service-events-page-support-quality-*` positive pages |
| `estate-vectors.json` | `make_estate_vectors.mjs` | `estate-secret-value-as-slot.json` names its slot `AKIA…` (was `GHP_…`, no key under DEC-0151); the record's digest |
| `package-vectors.json` | `vendor_vectors.mjs` | `package-secret-shaped-name.json`, the same rename and digest |
| `profile-vectors.json` | `make_profile_vectors.mjs` | four `sk-` samples without a digit read `false` |
| `connections-extra-vectors.json` | `make_connections_vectors.mjs --extra` | the `%zz` and `KIA` label is no longer a key, so the declaration reads |
| `channel-agent.source.json`, `load-vectors.json` | `make_channel_agent_vectors.mjs`, `make_load_vectors.mjs` | the pin only; `make_load_vectors.mjs` now reads it from the lock |

The other generators (`make_actions`, `make_ceremony`, `make_job_limit`, `make_link`, `make_mandate`, `make_page_link`,
`make_route`, `make_share`, `make_usage_spend`, `delegation/make_vectors.mjs`) wrote files equal to the vendored ones.
`fixtures/vectors/folder-attribution.json` (+479) and `source-tree.json` (new) are not vendored: the first has no kit
port, the second is FAA-261's.

## 6. Fixtures and docs

68 new fixtures (8 positive, 26 negative, 34 semantic; 2 semantic changed): the `fabric-source-*`, `source-*` and
`support-quality-daily-*` groups. The kits read the catalogue's service and feed groups through `vendor_vectors.mjs`;
the `fabric-source` and `source-*` groups are FAA-261's. Spec pages changed: `source.md` (new), `service.md` (RT-1 to
RT-5, CT-254), `project-comms.md` (SA-6), `support-quality.md`, `identifiers.md`, `interop.md` and `package.md`
(DEC-0149 hand-over and `pack`, FAA-261), `channel-agent.md`, `connections.md`, `fabric-button.md`, `profiles.md`,
`session-handoff.md`, `folder-attribution.md` (DEC-0151's detector), the rest wording.

## 7. Adapter tests whose samples changed answer

As the contract's CT-210 handoff (`docs/handoffs/2026-11-04-support-quality-tickets.md`) predicts: samples of a
digit-free or lower-case `sk-` key are rebuilt from pieces as keys DEC-0151 reads (`Q1`, `X1`, `Y1`, `Z1`, `W1` before
the run); the two ECMAScript cases in `test_fabric_profiles.py` answer as the contract does at the pin (checked with
its `secretValue` and `secretUrl` under `tsx`); nine repository vectors that DEC-0151 names as no keys (an `sk-` inside
a word, a digit-free or upper-case `sk-`, a name an `sk-` starts) move from `credential` to `name`, with `SKSTRONG`
and `SKREST` as keys at the same places.
