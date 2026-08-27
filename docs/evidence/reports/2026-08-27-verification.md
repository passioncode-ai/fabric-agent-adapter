# Verification report — 0.1.0

Date: 2026-08-27
Contract commit: `20a818e648a4c09a60df0126d11626922e8b9094`

| Check | Result | Receipt |
|---|---|---|
| Unit tests | PASS | `python3 -m unittest discover -s test -v` → 8 tests, exit 0 |
| House validator | PASS | `python3 test/validate.py` → distribution valid, exit 0 |
| Plugin manifest | PASS | `claude plugin validate ./plugins/fabric-agent-adapter --strict` → passed |
| Marketplace manifest | PASS | `claude plugin validate . --strict` → passed |
| Generic skill discovery | PASS | `npx --yes skills add . --list` → exactly `adapting-projects-to-fabric` |
| MCP generated manifest | PASS | helper `check --contract` → pinned declaration schema PASS |
| A2A generated manifest | PASS | helper `check --contract` → pinned declaration schema PASS |
| Local-runner generated manifest | PASS | helper `check --contract` → pinned declaration schema PASS |
| Diff whitespace | PASS | `git diff --check` → exit 0 |
| Fresh-model trigger eval | NOT_RUN | no explicitly scoped evaluation model/account pool |
| Live protocol/admission | NOT_VERIFIED | Fabric host/runtime is not implemented in contract 0.1.0 |

Generated templates intentionally remain `readyForAdmission: false` because endpoint,
executable, runner-kind, and content-hash placeholders require project-specific evidence.
