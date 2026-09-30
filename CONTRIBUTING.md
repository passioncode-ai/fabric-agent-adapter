# Contributing

1. Start from the pinned Fabric contract and write the intended behaviour/evidence first.
2. Add or update trigger and scenario evals before changing instructional prose.
3. Keep scripts Python standard-library only and non-destructive by default.
4. Run every command in the README validation section.
5. Keep marketplace, plugin, skill metadata, and changelog versions synchronized.

A contract-pin update is a compatibility change: review all three profiles, regenerate
fixtures intentionally, and release a new version. Never copy a newer normative rule into
this repository while leaving the old pin in metadata.

## License of contributions

This repository is open source under the [GNU AGPL-3.0](LICENSE), or available under a
[commercial license](COMMERCIAL-LICENSE.md): `AGPL-3.0-only OR LicenseRef-PassionCode-Commercial`.
Contributions are accepted under the [Contributor License Agreement](CLA.md), which allows that
dual licence: tick its box in the pull request template.
