# Handoff — FAA-47: the profile and route rules answer as the contract on any JSON (0.34.1)

**Objective.** The operator asked for a bug and gap review of the work released this session (0.33.0, 0.34.0). The
review found the Python and Node profile kits (`fabric_profiles.py`, `fabric-profiles.mjs`) disagreeing with the
contract's TypeScript on JSON its vectors never held. This change fixes them and releases 0.34.1. The contract pin is
unchanged (`d8146cf`).

## Done

- **FAC-SEM-059** (`runner-profile`): `===` with absent distinct from `null` (Python `_at` / `_same`), `show` for the
  login, runner kind, allow-list and profile.
- **FAC-SEM-060**: a recorded `resolved` is compared with the contract's `jsonEqual` (Python `_json_equal`; Node's
  stringify comparison replaced). The Python resolver keeps NaN internally (`_resolve`) and writes it as null
  (`resolve_model_profile`, the finding's message).
- **The `model-classes-empty` refusal** names its policy with `show(meta.id)` and `toNumber(meta.revision)` (Python
  `_js_to_number` from the estate kit).
- **Route rules FAC-SEM-028…034**: Node `String()` → `show` (28 places); Python `_field` → `show`; a probe's runner kind
  and a drive compared with `===`.
- **The doctor's `model_usable` / `modelUsable`** never raises: only string ids are looked up (Python), the model and
  the policy id are shown.
- Removed: the profiles kit's own `_js_string` and `_js_number`, now unused.
- **Vectors**: 31 new profile cases (`crafted strict: …`) and 13 new route cases (`hostile: …`), answered by the
  contract's own rules. Unit tests for the doctor on hostile input in both kits.
- Reviewed and found sound: the estate kit's credential comparisons (strings only) and the board kit's `hold_refuses`
  (string-only comparisons).
- **Independent review** (a blind unit-tier reading against the TypeScript reference) found five more Python
  differences and one Node risk, all fixed:
  - `fabric_estate._json_stringify` writes like `JSON.stringify`: a lone surrogate escaped (`_js_json_string`), keys
    in JavaScript's own order (`_js_keys`);
  - `_same` and `fabric_identifiers._strict_equal` compare numbers as doubles (`_double`, an integer past the double
    range is ±Infinity), so `2**53 + 1 === 2**53` and no `OverflowError`;
  - `_set_key`, `_index_of` and the hex branch of `_js_to_number` read huge integers as Infinity; a probe index is a
    double and is written with `_js_string`;
  - Node's `profileProblems` / `routeProblems` look a kind up on the table's own members only.
- **Raw vectors**: a case JavaScript cannot carry as an object keeps its JSON text (`rawText` in profile vectors,
  `valueText` in route vectors); the contract answers `JSON.parse` of it and the tests read the same text.
- **The board**: rows FAA-28 (an escaped `\|`) and FAA-27a (a fragment a 0.31.0 edit left behind) split into six
  cells and stopped the workspace publication (reported by another session). Both are fixed; `test/validate.py`
  `malformed_board_rows` refuses such a row (it finds exactly lines 43 and 56 on the old board).
- **Found in the contract, reported**: `expectProbes` builds `Array.from({length: count})` from the selected index, so
  a selected index of 2**32 or more throws `RangeError` in the reference itself. The Python kit reads the length
  lazily (`range`).

## Checks run

- The new vectors against 0.34.0's kit files: 27 Python subtests and two Node tests fail; against this change, none.
- `python3 -m unittest discover -s test`: 641 tests, OK (22 skipped). `node --test 'test/*.test.mjs'`: 205 tests,
  198 pass, 7 skipped, 0 fail. `python3 test/validate.py`: OK. `claude plugin validate` ×2 (`--strict`): passed.
- The reviewer's comparison scripts on 17 hostile inputs: the contract, Node and Python agree on 17 of 17.
- Planted defects in the new code: all caught except two redundant pieces of code, which are removed (a NaN branch
  Python's `!=` already covers; a Node filter the `typeof model` check already covers).

## Open

- Release: PR → CI → merge → tag `v0.34.1` → npm; then FAA-47 → done. Launcher 0.2.7, workspace rows, org-index note.

## Next task

Release 0.34.1 as above. Then the board's next open row this agent can take (FAA-44 waits on a contract decision and
the operator's В-09).
