# Handoff — FAA-39: identifier equality by normal form, repin to `a046f57` (0.25.0)

**Objective.** Port the contract's DEC-0076 into both kits and repin to contract `main` `a046f57` (CT-18). Brief:
[specs/2026-10-13-faa-39-identifiers.md](../evidence/specs/2026-10-13-faa-39-identifiers.md).

**Done.**
- New modules: `fabric_identifiers.py` (byte-identical in both skills) and `fabric-identifiers.mjs`.
- Compared by normal form: FAC-SEM-030/032/034 (`fabric_profiles`, `fabric-profiles`), FAC-SEM-076 (both estate ports)
  and FAC-SEM-014 (`fabric_provider.py`).
- Written in normal form: the scaffolder's provider and capability ids, and a provider entry's `providerId`.
- Respelled-id cases added to the route and estate generators; the identifier vectors are vendored.
- Pin `a046f57`; `fe55fc6` is supported.
- Docs: `protocol.md` (*Identifier equality*). Eval: `identifiers-by-normal-form`. Version 0.25.0 and CHANGELOG.

**Checks run.**
- `npm test` exit 0 (Python 509 OK; Node 139, 132 pass, 0 fail).
- `test/validate.py` OK; both strict plugin validations pass.
- `test_contract_revisions` at `2ce3922` → `a046f57`: 12 OK.
- 20 planted defects, all caught.

**Open.**
- FAA-33, FAA-35, FAA-36, FAA-37.
- DEC-0077 (`com.directory` FAC-SEM-107): the kits check a page before looking a Project up. This belongs with FAA-12b's
  board client and gets a board row.

**Next task.**
1. Release 0.25.0 and close FAA-39 on the board, adding the DEC-0077 row.
2. Repin the launcher to `v0.25.0`.
3. Tell fabric-agent-contract-75.
