# Handoff — FAA-34: an app's own descriptor and the descriptor for listings (0.24.0)

**Objective.** Hold both kits to contract DEC-0069 and DEC-0061 at the current pin `fe55fc6` (the contract's CT-18 row).
Brief with REQ-01…11: [specs/2026-10-13-faa-34-app-descriptor.md](../evidence/specs/2026-10-13-faa-34-app-descriptor.md).

**Done.** Both kits:
- Managers `node` and `person`.
- An optional `origin`, for apps only.
- `installedBy` by role, `runner` and `peer`.
- FAC-SEM-085 and FAC-SEM-086.
- The ports `peer_refusal`, `app_descriptor_action` and `app_descriptor_stale`.
- `fabric_button_presence`.
- The usage route `platform-metered`.
- Writers write the object form of `installedBy`.
- Fixed: the probe and `write_descriptor` on descriptors without an origin.
- Docs: `protocol.md`, `lifecycle.md`, `dashboard-kit.md`, SKILL.md.
- Evals: the new scenario `app-descriptor-and-listing`.

**Checks run.**
- `npm test` exit 0: Python 503 OK (22 skipped); Node 137, 130 pass, 0 fail, 7 skipped.
- `test/validate.py` OK; both `claude plugin validate --strict` passed.
- Contract fixtures at `fe55fc6`, vendored by `vendor_vectors.mjs`:
  - every service-descriptor fixture: 10 valid accepted, every invalid one refused except the six local-channel ones
    (DEC-0075);
  - 22 peer cases and 14 app-descriptor cases.
- 32 planted defects, all caught.

**Open.**
- FAA-33, FAA-35, FAA-36 and FAA-37.
- FAA-39 (new): DEC-0076 identifier equality.
  - Port `sameIdentifier` and `normalIdentifier` and run `identifiers.json`.
  - Apply them in FAC-SEM-030/032/034 (`fabric-profiles`) and FAC-SEM-014 (`fabric_provider.py`).
  - Add respelled-id route vectors.
  - Repin to the contract's merge `4762876` or later.
- The local channel (DEC-0075) is not a kit surface yet.

**Next task.**
1. Merge, tag `v0.24.0`, release.
2. Close FAA-34 and add FAA-39 on the board.
3. Repin the launcher to `v0.24.0`.
4. Tell fabric-agent-contract-75.
5. Then take FAA-39.
