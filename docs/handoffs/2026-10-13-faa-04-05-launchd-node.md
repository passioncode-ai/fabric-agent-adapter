# Handoff — FAA-04 and FAA-05: launchd in the Node kit, the supervisor-marker probe rule (0.30.0)

## Objective

Close the two board rows that were not blocked:

- **FAA-04:** give the Node service kit the launchd install and uninstall helpers that the Python kit has.
- **FAA-05:** have the probe fail a plist without the supervisor marker. It was deferred until FAA-06 released the
  plist that writes the marker; that happened in 0.8.0.

Also close the parent row FAA-12, whose two halves are both done.

## Done

- `fabric-service.mjs` gained `launchdPlist`, `launchdLoaded`, `launchdOverride`, `launchdInstall` and
  `launchdUninstall`. They follow the Python steps in order, and the plist bytes are identical to `plistlib`'s.
- `check_service.py` gained `marker_problem` and the rule `lifecycle.supervisor-marker`.
- Docs updated: `references/lifecycle.md` (the LC-14 row, the plist table, install steps 3 and 5) and `SKILL.md`
  (the Node installers).
- Release prep: 0.30.0 in every version file, and a CHANGELOG entry.
- Board: FAA-04 and FAA-05 set to in review; FAA-12 set to done.

## Checks run

- `python3 -m unittest discover -s test`: 597 tests, OK, 22 skipped.
- `node --test 'test/*.test.mjs'`: 180 tests, 0 failed.
- `python3 test/validate.py`: OK.
- 16 planted defects, all caught (listed in CHANGELOG 0.30.0).

## Open

- After the release, set FAA-04 and FAA-05 to done with the tag and npm receipts, and repin the launcher.

## Next task

The board's other rows wait on decisions made elsewhere:

- **FAA-10:** `surfaces.a2a`.
- **FAA-26, FAA-27, FAA-36:** `fabric-package/1` and ADR-0138.
- **FAA-28:** org servers.
- **FAA-29:** the DEC-0039 and DEC-0030 amendments.

The RM-28 pilot (fabric-workspace `docs/reports/2026-10-12-org-contexts/pilot-2026-10-13.md` §4) asks the adapter
for `pack` (FAA-27). Answer it there with what blocks it.
