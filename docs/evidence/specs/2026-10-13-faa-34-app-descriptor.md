# FAA-34 — an app's own descriptor (DEC-0069) and the descriptor for listings (DEC-0061)

Run: 2026-10-13. Branch `agent/faa-34-app-descriptor`. Backlog row FAA-34. Asked for by the contract (CT-18, items for
DEC-0061 and DEC-0069). The pin stays `fe55fc6`: both decisions are already in it.

## Source ledger

| Source | What it gave |
|---|---|
| contract DEC-0069, `src/app-descriptor.ts`, `fixtures/vectors/app-descriptor.json` | `manager: "person"` with `lifecycle.app`; `origin` optional for an app only; no port without an origin (`FAC-SEM-010`); `appDescriptorAction`, `appDescriptorStale`; a reader skips such an entry rather than fail the directory |
| contract DEC-0061, `src/descriptor-rules.ts`, `fixtures/vectors/service-peer.json`, semantic fixtures `service-descriptor-*`, `service-peer-*`, `service-runner-*` | `peer {endpoint, custody, residency, maxDataClass}`, `runner {kind?, credentialKind}`, `installedBy {by, role?, tool}`, `manager: "node"` with no supervisor file, usage `route: platform-metered`; `peerRefusal`; FAC-SEM-085/086 |
| contract `schemas/service-descriptor.schema.json` and its fixtures at `fe55fc6` | 11 positive and 67 negative descriptors — the shape the kits' validators mirror |
| contract CT-18 row (read in full, per FAA-32's retrospective) | the kits write `installedBy` as an object where they know who installed, `runner.credentialKind`, `peer` for a listing; accept `node` and refuse `label`/`plist` beside it; accept `person` and a missing origin, skip the port check without one; the "Open in <app>" button reads the descriptor, a sender reads the liveness file |
| Fabric ADR-0139, carry-over CO-263, scenario SCN-142 | Fabric's own descriptor is `services/fabric.default.json`; the button shows only when Fabric's descriptor is registered; liveness stays in Fabric's `hub.json` |
| this repository: `fabric_service.py` / `fabric-service.mjs` `validate_descriptor`, `register_remote`, `make_usage_receipt`; `sample_service.py register`; `check_service.py`; `fabric_interop.py`; `references/dashboard-kit.md` (Fabric's button, FB-5 `data-fabric="absent"`) | where each rule lands |

Code graph, wiki, retro ledger: none for this repository.

## Decisions (closed from the sources)

1. **Validators mirror the schema at the pin**, held to the contract's own fixtures: every positive `service-descriptor-*`
   accepted, every negative of DEC-0057/0061/0069 refused for its reason. Members the kits do not otherwise read (the
   local channel, DEC-0075) are left to the schema, never refused.
2. **Writers:** `register` in the sample and `register_remote` / `registerRemote` write `installedBy {by: "person",
   role: "operator", tool}` (a person runs them), and take `runner` and `peer`; the string form stays accepted on read.
3. **Readers skip, never fail:** a directory listing skips an entry it cannot use; `check_service.py` checks no port
   without an origin and reads an app's descriptor as installed, never as running; a caller that would send to a
   descriptor without an origin is refused with the reason (the liveness file is the app's own, DEC-0069 *Not decided*).
4. **Fabric's button:** `fabric_button_presence` / `fabricButtonPresence` read `fabric.default.json` and answer
   `present` or `absent` (no descriptor, or an app's descriptor whose app is gone), so a server can set
   `data-fabric="absent"` (FB-5). A press only follows a link, so the liveness file is not read for the button.
5. **Ports with vectors:** `peer_refusal`, `app_descriptor_action`, `app_descriptor_stale`.
6. **Usage:** `route` admits `platform-metered`. `byGrant` and the usage window stay FAA-33's.
7. **Version 0.24.0.**

## REQ table

| REQ | Requirement | Verified by |
|---|---|---|
| REQ-01 | `manager` admits `node` and `person`; `label`/`plist`/`unit`/`task` refused beside either; `node` local only; `person` needs `lifecycle.app` and the object `installedBy` with `by: "person"` | contract fixtures through both validators |
| REQ-02 | `origin` optional for `person` only; no port check without one | fixtures; `check_service` test |
| REQ-03 | `installedBy` string or `{by, role?, tool}` (role only for a person); FAC-SEM-086 on `runner` and `installedBy` | fixtures; semantic fixtures |
| REQ-04 | `runner {kind?, credentialKind}`; `peer` shape; `peer` needs `runner`, never `subscription`; FAC-SEM-085 | fixtures; semantic fixtures |
| REQ-05 | `peer_refusal` / `peerRefusal` | `service-peer.json`, both kits |
| REQ-06 | `app_descriptor_action` / `app_descriptor_stale` | `app-descriptor.json`, both kits |
| REQ-07 | Readers skip an entry they cannot use; a caller refuses a descriptor without an origin, saying why | reader tests |
| REQ-08 | `fabric_button_presence` / `fabricButtonPresence` | tests with a services directory |
| REQ-09 | Writers write the object `installedBy`, take `runner` and `peer` | writer tests; the written descriptor valid under the `fe55fc6` schema |
| REQ-10 | Usage `route: platform-metered` | usage tests; schema |
| REQ-11 | Docs (`protocol.md`, `lifecycle.md`, `dashboard-kit.md`, SKILL.md), a scenario eval first, 0.24.0, CHANGELOG, FAA-34 closed, handoff, launcher repin | `test/validate.py`; files |

## Run state (2026-10-13, second cut by a usage limit)

Done on this branch:
- REQ-01…10 in both kits, with tests: `test_fabric_service_descriptors.py` (12 tests) and
  `fabric-service-descriptors.test.mjs` (7 tests), both passing.
- 32 planted defects, all caught.
- Scenario eval `app-descriptor-and-listing`.
- Docs: `protocol.md` (the descriptor table), `dashboard-kit.md` (FB-5 presence), `lifecycle.md` (*An app's own
  descriptor and the node*), SKILL.md. `test/validate.py` OK.

Open — the next agent starts here:
1. `npm test` (full suite, not yet run after the docs).
2. Version 0.24.0 in every manifest, and CHANGELOG under a lease.
3. PR, dispatch `validate.yml` on the branch, merge, validate on main, tag `v0.24.0`, release.
4. Close FAA-34 in the backlog under a lease.
5. Repin the launcher to `v0.24.0` (passioncode `family.json`, 0.1.48, PC-31).
6. Tell fabric-agent-contract-75 for CT-18.
