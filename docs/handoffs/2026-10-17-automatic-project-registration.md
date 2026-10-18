# Automatic project registration — adapter guidance

## Done

- `working-with-fabric` now sends an unknown eligible Git folder through Fabric's own enrollment/admission path instead of telling the agent to create or attach a Project through a side channel.
- The no-project eval expects the same boundary and keeps the older-Fabric manual path explicit.
- No production bridge code changed: the adapter already supplies `cwd` and calls `fabric_whoami`.

## Checks

- `npm test` — exit 0 (663 Python tests, 228 Node tests; 22 Python skips, 9 Node skips).
- `python3 test/validate.py` after the final wording edit — exit 0.
- `git diff --check` — exit 0.

## Exact next task

After Fabric's admission implementation lands, verify the guidance against its actual `fabric_whoami` outcomes and the installed Fabric release; then publish this documentation through the adapter's normal release process. The cross-repository run index is `org-index/docs/runs/2026-10-17-automatic-project-registration/README.md`.
