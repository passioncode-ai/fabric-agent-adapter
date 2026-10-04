# Local backlog

This is the canonical status source for the tasks below. Keep stable IDs, close with a
receipt in Source, and retain closed rows. The workspace derives its common backlog
from [backlog-sources.json](backlog-sources.json). Dated handoffs remain historical evidence.

Release 0.5.5 has no outstanding local release step; see [its receipt](handoffs/2026-10-01-adapter-0.5.5.md).
Future adapter work gets a row here. Consumer pin decisions stay with the consumer. The contract
question raised by PR #28 (naming the supervised-lock wait) is owned by fabric-agent-contract
[CT-01](https://github.com/passioncode-ai/fabric-agent-contract/blob/main/docs/backlog.md).

| ID | Item | Status | Source |
|---|---|---|---|
| FAA-01 | Land the service kit's lifecycle-contract work (LC-01, LC-03, LC-11, LC-12, LC-14, LC-15; audit findings F7–F9, F11 pattern, F16) as 0.7.0 — PR #28 | blocked by a rebase: PR #28 (head `0e98264`, CI green) conflicts with `main` since 0.6.2 (#29) and 0.6.3 (#30) landed. Next step for the PR's owning session: rebase `claude/lifecycle-contract` onto `origin/main`, put the 0.7.0 CHANGELOG entry above 0.6.3 and keep the version files in sync, rerun `npm test`, land. Release and the launcher pin follow separately (passioncode PC-03). Goal: reliable-work | [PR #28](https://github.com/passioncode-ai/fabric-agent-adapter/pull/28); [lifecycle audit](https://github.com/passioncode-ai/fabric-workspace/blob/main/docs/reports/2026-10-03-lifecycle-audit/raw/passioncode-adapter.md) |
| FAA-02 | Lower the `launchd_plist` default `ExitTimeOut` from 40 s to 15 s, above `Drain`'s 10 s bound, so launchd's SIGKILL never comes first (LC-01) | blocked by FAA-01: the change is part of PR #28 ("Also changed") and lands with it | [PR #28](https://github.com/passioncode-ai/fabric-agent-adapter/pull/28) |
| FAA-03 | Probe sends the MCP 2026-07-28 `Mcp-Method`/`Mcp-Name` request headers derived from the JSON-RPC body, with a legacy-server fallback — PR #24 | blocked by a rebase: PR #24 (another session's branch `fix/mcp-probe-headers`, head `843d277`, CI green) conflicts with `main`. Next step for its author: rebase onto `origin/main`, version it at release, land. Goal: interoperability | [PR #24](https://github.com/passioncode-ai/fabric-agent-adapter/pull/24) |
| FAA-04 | Add launchd install/uninstall helpers to the Node service kit; lock, drain, rotation and release pruning already reach parity in PR #28 | deferred: a separate feature, named as not fixed in PR #28 | [PR #28 "Not fixed here"](https://github.com/passioncode-ai/fabric-agent-adapter/pull/28) |
| FAA-05 | Probe rule in `check_service.py` that flags a plist without `FABRIC_SERVICE_SUPERVISOR` | deferred until after FAA-01: the rule would fail every existing service until its next reinstall, so the follow-up must be deliberate | [PR #28 "Not fixed here"](https://github.com/passioncode-ai/fabric-agent-adapter/pull/28) |
