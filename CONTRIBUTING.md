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

This repository is source-available under
`PolyForm-Noncommercial-1.0.0 OR LicenseRef-PolyForm-Internal-Use-1.0.0`
([LICENSE](LICENSE)). Contributions are accepted under the
[Contributor License Agreement](CLA.md): tick its box in the pull request template.
