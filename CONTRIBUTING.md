# Contributing

1. Start from the pinned Fabric contract and write the intended behaviour/evidence first.
2. Add or update trigger and scenario evals before changing instructional prose.
3. Keep scripts Python standard-library only and non-destructive by default.
4. Run every command in the README validation section.
5. Keep marketplace, plugin, skill metadata, and changelog versions synchronized.
6. Before every push and every release, run `python3 test/validate.py --private-terms`: it reads the
   operator's private-terms list (org-index `check_private.py` rule P1; `$PASSIONCODE_PRIVATE_TERMS`, else
   `~/.config/passioncode/private-terms.txt`) and prints the path and line of each tracked file that names a term,
   never the term. Exit 0 is clean, 1 names files to fix (replace the term with a neutral word), 2 means the list is
   not on this machine and the check did not run: that is not a pass. `python3 test/validate.py` runs the same check
   whenever the list is present.

A contract-pin update is a compatibility change: review all three profiles, regenerate
fixtures intentionally, and release a new version. Never copy a newer normative rule into
this repository while leaving the old pin in metadata.

## License of contributions

This repository is open source under the [GNU AGPL-3.0](LICENSE), or available under a
[commercial license](COMMERCIAL-LICENSE.md): `AGPL-3.0-only OR LicenseRef-PassionCode-Commercial`.
Contributions are accepted under the [Contributor License Agreement](CLA.md), which allows that
dual licence: tick its box in the pull request template.
