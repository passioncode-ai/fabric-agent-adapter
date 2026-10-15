# Handoff — FAA-45: repin to contract `d8146cf`; a lane that reads user content (DEC-0083) in both profile kits (0.34.0)

**Objective.** Lanes that read what members, clients or the public send must not run on closed vendors alone: those
refuse porn, scams and drugs, so the lane skips the worst content (the operator's rule of 2026-10-15, measured in
another project; wiki `synthesis/llm-models.md`). Contract DEC-0083 makes it a rule: a model profile declares `reads`,
the catalogue marks `open-vendor`, and FAC-SEM-112 holds the route ([contract PR #111](https://github.com/passioncode-ai/fabric-agent-contract/pull/111),
merge `a3e330f`, main `d8146cf`; board row CT-52). This change ports it to `fabric_profiles.py` and
`fabric-profiles.mjs` and releases 0.34.0.

## Done

- **Repin** `82e1636` → `d8146cf`; `82e1636` stays supported (`DEC82` in `test_contract_revisions.py`). `d8146cf` differs
  from the merge `a3e330f` only in the contract's board files (`git diff --stat a3e330f d8146cf -- src schemas fixtures`
  is empty).
- **FAC-SEM-112** in both kits: `closed_user_content_route` / `closedUserContentRoute`; a finding per profile at
  `/profiles/<i>/models`, and on the resolution's outcome at `/resolved/models` when the policy leaves the lane closed.
- **`open-vendor` descriptive** in both copies of the every-class rule: the resolver and the doctor's `model_usable`.
  Both answer the contract's shared `fixtures/vectors/model-admission.json` (vendored into `profile-vectors.json` as
  `admission`, each case checked against the contract's `admittedByClasses` when generated).
- **FAC-SEM-058/060 total on hostile input**: raw indexes, JavaScript `Set` semantics for duplicate ids, `show` for an
  id with its own `toString`.
- **Generator fix**: `make_profile_vectors.mjs` unwraps `{description, kind, expect, input}` fixtures and fails when a
  fixture's `expect` disagrees with the contract. Before, the new fixtures were read vacuously and the Node test passed
  without checking them.
- **Docs and evals**: `references/profiles.md` gains "A lane that reads user content"; `creating-fabric-agents/SKILL.md`
  asks which lanes read user content; `profile-selection.md` names the exception; eval scenarios
  `lanes-that-read-user-content` and `user-content-open-vendor-route`.
- **Found in the contract and fixed there**: FAC-SEM-112's `instancePath` shifted after a non-object (reported; fixed
  in #111 for 058/060/112).

## Checks run

- `python3 -m unittest discover -s test`: 637 tests, OK (22 skipped).
- `node --test 'test/*.test.mjs'`: 204 tests, 197 pass, 7 skipped, 0 fail.
- `python3 test/validate.py`: OK; `claude plugin validate` (plugin and marketplace, `--strict`): passed.
- Vectors: 72 rule cases (45 crafted), 81 resolutions, 8 admission cases.
- Planted defects: 51 (30 Python, 21 Node), all caught but two that cannot differ on JSON input; the admission
  vectors alone catch a doctor without the exemption in both kits.

## Open

- Release: PR → CI → merge → tag `v0.34.0` → npm; then FAA-45 → done.
- Launcher 0.2.6 with adapter `v0.34.0`; workspace `knowledge/products.md` / `roadmap.md`; org-index pin row.
- Not decided in the contract (DEC-0083): a checker's third-vendor fallback, per-model thresholds, and which lanes count
  as user content (the agent's own declaration).

## Next task

Release 0.34.0 as above. Then FAA-44 (the private agent catalog) when its contract decision and the operator's В-09
land; until then the board's next open row this agent can take.
