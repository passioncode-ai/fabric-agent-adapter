# Brief: close the 2026-10-22 audit (FAA-68 to FAA-81) as 0.41.0

**Request (operator, 2026-10-22):** «исправь ошибки, разберись в причинах и системно всё поправь, слей в главную ветку,
почисти хвосты, доки обнови и дай саммари: что сделано, что в приоритете, что в бэклоге».

**Route:** task-pipeline, wave mode over the audit's rows. The inventory is the audit report
([report](../../reports/2026-10-22-adapter-audit/README.md), findings 1 to 53, each with its receipt), so wave 0's
survey is already done; the plan below is a prose table checked by hand rather than a `graph.py` work graph, said
here as the weaker form it is.

## Root causes, and the guard each one gets

The 53 findings are not 53 accidents. They fall into six classes; each class gets a fix AND a guard that fails the
next instance, so the class does not come back.

| Class | Findings | Why it happened | Guard |
|---|---|---|---|
| R1 Twin drift: Python and Node answer the same input differently | 5, 10, 14, 15, 40, 43, 44 | the shared vectors cover the contract's cases, not hostile ones (trailing newline, `null`, U+2028, invalid UTF-8, `__proto__`, explicit default port) | a shared hostile-input vector file run by both twins; a validator rule that refuses `$`-anchored `re.match`/`re.compile` patterns in kit modules (use `\Z` or `fullmatch`) |
| R2 Failure paths never exercised | 1, 2, 3, 13, 16, 41, 51 | tests drive the happy path; a refused call, an unreadable directory, a wrapped child, a slow `ps` were never injected | fault-injection tests per path: the error is injected and the test asserts the documented outcome |
| R3 Shared state without a lock in the Python twin | 11, 12, 36 | `ThreadingHTTPServer` and the responder's handler thread run beside load-modify-save code written for Node's single thread | a lock per store, and a concurrency test for every store that a threaded server can reach |
| R4 Non-atomic replace and destructive defaults | 6, 50, 51, 42 | remove-then-copy, `rm -rf` before checking, check-then-read on links | copy beside and rename; `O_NOFOLLOW`; installers refuse without `--force`, the same rule in both installers |
| R5 Gates that cannot fail | 22, 23, 24, 33, 19 | checks gated on an env var no job sets; evals counted, never run; no nightly; no 3.9 job | a nightly trigger; a job that installs the contract at the pin and sets the env; a Python 3.9 job; an eval runner |
| R6 Documents written once and never re-checked | 29 to 32, 28, 9 (release titles) | no check reads SECURITY.md, SKILL-CARD or `.github/` | `validate.py` scans `.github/` for U+2014 and the docs for the corrected claims stay under the validator's em dash and link checks |

## Decisions (resolved from the sources; none asked)

| Id | Decision | Source |
|---|---|---|
| D1 | Python 3.9 stays the floor: fix the code and add a 3.9 job | README promises 3.9+; macOS ships 3.9.6 |
| D2 | `engines.node` becomes `>=18` | the code uses `fetch` and `AbortSignal.timeout` |
| D3 | `null` for `applied` and `estate` fails closed in both twins | fail-closed is the kit's rule for unreadable input (`fabric_estate` `estate-unreadable`) |
| D4 | JWKS `x` is strict base64url in both twins; the contract is told | strict is the safer side; contract owns the final word |
| D5 | Both twins refuse U+2028/U+2029 and control characters in package paths beyond the schema; the contract is told (board message `95ba2bb0`) | the schema's own intent (no `..`, no `\\`, no `//`) |
| D6 | The support recipe hands off any reply carrying a URL, address, number or amount absent from the cited entries | the recipe's own rule: the model's text is data |
| D7 | The eval runner runs with a real client only when asked (`FABRIC_REAL_CLIENT=1`), like `test_real_client.py`; not in hosted CI, which holds no model credential | the existing opt-in pattern |
| D8 | Removing `NPM_TOKEN` and registering trusted publishing is **needs-operator** (npmjs.com sign-in); the workflow keeps the token until then | a sign-in is a human gate |
| D9 | The result ships as 0.41.0 | the release rule: releases are the agent's after green checks |

## Waves and file ownership

**Wave 1** runs seven builders in parallel, each in its own worktree under `~/DATA/_worktrees/faa-audit-<x>` on branch
`agent/faa-audit-<x>`. No two own one file. Nobody edits `kit.json`, `CHANGELOG.md`, `docs/backlog.md`, versions or
README: those are wave 2's. A builder that needs a test in a file it does not own adds a new test file.

| Builder | Rows | Owns |
|---|---|---|
| A | FAA-68, FAA-69 | `skills/working-with-fabric/**`, `building-fabric-services/scripts/dashboard_kit.py`, `test/test_fabric_session.py`, `test/test_hermes_host.py`, `test/test_native_hook_install.py`, `test/host-hooks-opencode-pi.test.mjs`, `test/openclaw-hooks.test.mjs` |
| B | FAA-70, FAA-78 (delegation), FAA-76 (its modules) | `fabric_supervisors.*`, `fabric_interop.*` (incl. the intent digest of FAA-77 item 39), `fabric_events.*`, `fabric_delegation.*`, `fabric_descriptor.*`, `fabric_base.*`, `fabric_auth.*`, `fabric_http.*`, `sample_service.py`, `sample-service.mjs`; tests `test_fabric_service*.py`, `fabric-service*.test.mjs`, `test_interop.py`, `fabric-interop.test.mjs`, `test_job_limits.py`, `job-limits.test.mjs`, `test_fabric_delegation.py`, `fabric-delegation.test.mjs`, `test_fabric_http.py`, `fabric-http.test.mjs` |
| C | FAA-78 (package, estate, crypto), FAA-76 (its modules) | `fabric_package.*`, `fabric-package.schema.json`, `fabric_estate.*`, `fabric_crypto.*`, `fabric_share.*`; tests `test_fabric_package.py`, `fabric-package.test.mjs`, `test_fabric_estate.py`, `fabric-estate.test.mjs`, `test_fabric_share.py`, `fabric-share.test.mjs` |
| D | FAA-77 items 35 to 38 | `fabric_board*.py`, `fabric-board*.mjs`; tests `test_fabric_board.py`, `fabric-board.test.mjs`, `fake_fabric_hub.py` |
| E | FAA-79, FAA-80, FAA-81 | `check_dashboard_layout.mjs`, `check_dashboard_link.py` (all three copies), `assets/dashboard-kit/**`, `bin/fabric-agent-adapter.js`, `install.sh`, `recipes/**`; tests `test_dashboard_layout.py`, `test_dashboard_links.py`, `fabric-button.test.mjs`, `fabric-dashboard-kit.test.mjs`, `test_installer.py`, `test_support_agent_recipe.py` |
| F | FAA-71, FAA-74, FAA-75 | `skills/adapting-projects-to-fabric/**`, `skills/creating-fabric-agents/**`, `building-fabric-services/SKILL.md`, `building-fabric-services/references/**`, `SECURITY.md`, `SKILL-CARD.md` (claims only, not the version line), `AGENTS.md`, `test/evals/**`, `test/test_adapt_project.py`, `test/test_provider.py` |
| G | FAA-72, FAA-73, R1 and R6 guards | `.github/workflows/**`, `package.json` (`engines` only), `test/validate.py`, `test/test_validate.py`, `test/test_dashboard_kit.py`, `test/test_contract_revisions.py`, a new shared hostile-vector fixture `test/fixtures/kit-hostile-inputs.json` (shape only; B and C add their cases through their own tests reading it) |

**Wave 2** (the auditor): merge the seven branches into one integration branch, rebuild `kit.json`, run the full
Python and Node suites and both `claude plugin validate --strict`, fix what the merge exposes, then CHANGELOG, the
version 0.41.0 in every place it lives, the backlog receipts, the knowledge-base fact if one moved, the handoff, one
PR merged into `main`, the tag, the release run watched to green, the published package and the local install
checked. Then the clean-up: merged branches, worktrees, scratch.

**Exit criteria, written before the build:** every finding of the report closed in code with a test seen failing
first, or carried with a row and a reason; `npm test` and both plugin validations exit 0; the R1 to R6 guards each
proved both ways (fails on a planted defect, passes on the fix); npm `latest` = 0.41.0.

## Run state

- 2026-10-22: brief written; wave 1 launched.
