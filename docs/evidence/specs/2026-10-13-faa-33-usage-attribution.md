# FAA-33 — OpenRouter attribution and the usage report's window and project attribution (DEC-0065)

Run: 2026-10-13. Branch `agent/faa-33-usage-attribution`. Board row FAA-33. Pin `a046f57`. Version 0.27.0.

## Source ledger

| Source | What it gave |
|---|---|
| contract DEC-0065 (and its annotations: CT-40 cost sums, DEC-0076 normal-form `projectId`) | the window: every `days[].date` exists, is not after `generatedAt`'s UTC date and at most 30 days before it; `byProject[]` (`projectId`, calls, unpriced calls, cost, `taskRuns[]`), each project and task run once, the sums bounded; OpenRouter attribution off by default |
| contract `src/usage-rules.ts`, `schemas/service-usage.schema.json` (`byProject`, `route` incl. `platform-metered`) | FAC-SEM-025 whole: arithmetic, window, projects |
| contract `src/openrouter-attribution.ts`, `schemas/openrouter-attribution.schema.json`, `fixtures/vectors/openrouter-attribution.json` (34 cases) | `attributionHeaders`: three headers, only with a valid setting (FAC-SEM-098), only to `https://openrouter.ai` (WHATWG parsing: default port, case, backslash, no slashes), only for originated traffic, never over a user's own attribution |
| this repository: `make_usage_receipt`, `usage_report` (both kits), `check_service.py` `usage_problems` | where each rule lands |

## Decisions

1. Receipts take an optional `project_id` / `projectId` (an identifier, kept in normal form, DEC-0076) and `task_run_id`
   / `taskRunId`; `usage_report` adds `byProject` when any receipt in the window has a project.
2. `usage_findings` / `usageFindings` port FAC-SEM-025 whole (arithmetic, window, projects); the probe reports them.
3. `attribution_headers` / `attributionHeaders` and `attribution_setting_findings` (FAC-SEM-098) are offered, off by
   default: a service passes its setting and the request, and adds the headers it gets back.
4. The probe reads `platform-metered` rows as a usage route.

## REQ table

| REQ | Requirement | Verified by |
|---|---|---|
| REQ-01 | Attribution helper and setting rule | `openrouter-attribution.json` (34), both kits |
| REQ-02 | `byProject` written by the kits, ids in normal form | builder tests; FAC-SEM-025 on the written report |
| REQ-03 | FAC-SEM-025 ported whole | the contract's `usageRules` answers on generated reports, both kits |
| REQ-04 | The probe reads the window, `byProject` and `platform-metered` rows | probe test |
| REQ-05 | Docs, eval, 0.27.0, CHANGELOG, board, handoff, launcher | files; `validate.py` |
