# FAA-353: the probe reports a broken service instead of dying (2026-11-18)

- Objective: SMM Manager's board request `26dabf75` (thread `a958ad7d`): `check_service.py` ended in a traceback on a
  token file that is not UTF-8 and on a launchd descriptor without `lifecycle.plist`.
- Done (branch `agent/faa-probe-crashes`, version 0.97.1): `fabric_auth.read_token` and `fabric-auth.mjs` `readToken`
  refuse a non-UTF-8 token file with `ServiceError` (never quoting its bytes; a BOM kept as before);
  `check_service_lifecycle.py` gives `lifecycle.plist` NOT_RUN when the descriptor names none and FAIL for a relative
  path; `kit.json` rebuilt at 0.97.1; CHANGELOG and backlog row FAA-353.
- Checks run: `test/test_check_service_crash_free.py` (5 tests, failing on `origin/main` first, green after); the
  real CLI against a live stub listener with both repro descriptors (old: `UnicodeDecodeError`; new: 45 rules, exit 1);
  the full gate (`python3 -m unittest discover -s test`, `test/validate.py`, `node --test`, both plugin validations).
- Open: the npm release of 0.97.1 (tag `v0.97.1`) is publication and goes with the next release run, not this
  board-request session.
- Next task: push tag `v0.97.1` from `main` after the merge, watch `release.yml`, confirm the npm package.
