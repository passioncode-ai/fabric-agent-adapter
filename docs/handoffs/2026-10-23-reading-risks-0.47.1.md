# 2026-10-23: the blind reading's risks (0.47.1)

**Objective.** The exact next task of [the 0.47.0 handoff](2026-10-23-repin-87d384f-0.47.0.md) once FAA-87 still waits
on the operator: FAA-107, the three risks the blind unit reading of 0.47.0 found (verdict pass, nothing broken).

**Done.** 0.47.1: the Python core gains `set_has` (a JavaScript Set's `has`, SameValueZero: NaN matches NaN) and the
estate reader's `FAC-SEM-134` uses it where the contract keeps a `Set`; `same`'s docstring says `===` only.
`profile-forbids`' 403 is asserted in both delegation kits. `make_estate_vectors.mjs` gains nine `FAC-SEM-134` variants
(a `view` machine id of another JSON type against each `from`), regenerated from the contract's staged sources at the
pin `87d384f`. PR [#176](https://github.com/passioncode-ai/fabric-agent-adapter/pull/176) (`084ebbe`), tag `v0.47.1`,
npm 0.47.1 (the release run's eight jobs green); launcher 0.2.30
([passioncode#148](https://github.com/passioncode-ai/passioncode/pull/148)), installed here byte-identical to the tag
(155 of 155 files).

**Checks actually run.** The new NaN test red on the Python twin before the change, green after; the Node twin
already answered it. Targeted suites: Python (`test_fabric_estate`, `test_kit_hostile_estate`, `test_fabric_delegation`,
`test_fabric_kit`) OK, Node 32 pass 0 fail; `validate.py` and both `claude plugin validate --strict` exit 0. Full
suites: Node 321 tests 0 fail; Python 1003 tests with 2 failures in `test_fabric_profiles` (a fake runner's `--version`
missed its 5000 ms deadline under a load average near 30; the module passes alone, its code is not in this change),
filed as FAA-108. The hosted suite runs in `release.yml` before the publish.

**Process note.** A blanket `sed s/0.47.0/0.47.1/` over `kit.json` also renamed the released `0.47.0` history entry;
only the `version` member moves (Fabric memory `project / kit-json-version-before-build`).

**Open.** FAA-87 (the operator's `npm login`), FAA-106 and FAA-103 on demand, FAA-86, FAA-98 and the earlier open rows.

**Exact next task.** FAA-87 once the operator has run `npm login`; otherwise FAA-86 (the board responder's checkpoint
entry left at `completing` after a lost `com.complete` answer).
