---
report:
  id: fabric-agent-adapter/2026-10-22-adapter-audit
  title: "Whole-adapter audit at 0.40.0: weak spots in the kit, the session hooks, the skills and the delivery path"
  kind: audit
  project: fabric-agent-adapter
  domains: [service-kit, session-hooks, skills, ci, release, docs]
  as_of: 2026-10-22
  status: active
  valid_until: 2027-01-22
  summary: >-
    A read-only audit of main at f0736a6 (0.40.0, equal to npm latest). The local gate is green
    (785 Python tests, 22 skipped; 263 Node tests, 8 skipped), yet nine groups of defects stand:
    a session spool one JSON-RPC error blocks for good, Python twins of the kit that let secrets
    into launchd plists and race under threads, a validate workflow with no nightly trigger and
    contract checks that never run and have already rotted, a provider writer looser than the
    pinned schema, and documents that state false things about the network and the CI. Proposed
    as backlog rows FAA-68 to FAA-76.
---

# Whole-adapter audit at 0.40.0

**Question:** what in the adapter is weak right now, across the service kit, the four skills, the session hooks,
the tests, CI, the release path and the documents?

**Scope and method.** `main` at `f0736a6`, version 0.40.0, which `npm view` reports as `latest`; `git log
v0.40.0..origin/main` holds only the backlog receipt and a handoff, so the published code is the audited code.
The project-audit collector ran first (9 probes, 0 blind); four independent read-only reviewers then took one area
each (kit modules, session hooks and host installers, the adapting and creating skills, delivery). Every finding
kept below was either reproduced by a script in the session scratch directory or re-read in the code by the
auditor; what could not be substantiated was dropped. Nothing in the repository was changed by the audit itself.

## What is clean

| Area | Evidence |
|---|---|
| Local gate | `npm test`: `OK: Fabric Agent Adapter distribution is valid`, `Ran 785 tests ... OK (skipped=22)`, Node `tests 263, pass 255, fail 0` |
| Published package vs source | `npm pack --dry-run`: 153 files, no tests, handoffs or raw logs; versions agree in plugin.json, marketplace.json, the four SKILL.md, SKILL-CARD and CHANGELOG (all 0.40.0) |
| Secret-shaped strings | the collector's 118 tree hits are all under `test/` and are synthetic vectors (`sk-or-v1-test-only-not-a-key`, `ghp_bbbb…`, AWS's documented `AKIAIOSFODNN7EXAMPLE`); the 14 history hits are the same vectors and one PEM header literal in a detector |
| Auth core | constant-time token compare, token file refused when shared or linked, single-use login codes, `HttpOnly; SameSite=Strict` cookies with `__Host-` and `Secure` for remote, `fabric_http`'s total deadline and size cap |
| Hook safety net | every hook path in `fabric_session_cli.py` returns 0; observe arguments carry counts and ids only |

## Findings

Severity is the auditor's; `R` means reproduced in this audit, `C` read and confirmed in the code.

### Session spool and hooks (FAA-68)

| # | Sev | Where | What | Proof |
|---|---|---|---|---|
| 1 | high | `working-with-fabric/scripts/fabric_session_mcp.py:136-137`, `:258-313` | A JSON-RPC `error` (or an unreadable spool entry) raises out of the delivery loop; the entry is never unlinked, so every later worker fails on it and the `end` entry, the claim release and the end observation never go out | R: a stub answering `-32602` to the turn observe; two workers both log `outcome=failed reason='RuntimeError'`, both entries stay, `fabric_work_release` is never called |
| 2 | high | `fabric_session_mcp.py:150-162` (`McpStdio.close`), reused by `fabric_session_mail.py:67-69` | `proc.kill()` reaches only the direct child; behind a wrapper (`npx`, a shell script, Windows `fabric-mcp.cmd`) the server keeps stdout open and `close` blocks | R (reviewer): `deliver(..., deadline_s=5)` returned after 60.3 s |
| 3 | medium | `fabric_session_env.py:396-419` | The "launched by Fabric" ancestor walk treats a `ps` timeout as "not launched"; the session is then spooled and its claims are released at SessionEnd | R (reviewer): same ancestor, real `ps` gives true, a 0.7 s `ps` gives false |
| 4 | medium | `fabric_session_mcp.py:258`, `:293` | Turn facts (`git_facts`) are measured at delivery time, from the first entry's cwd, for every spooled turn | R (reviewer): turns with 0 and 1 changed files both reported `filesChanged: 6` |
| 5 | low | `fabric_session_mail.py:78-94` | Jitter is applied after the 10 s floor and the 15 min cap (8.0 s and 1080 s measured), and watch-mail ignores the once-a-minute rejoin mark | R (reviewer) |
| 6 | low | `fabric_session_cli.py:156-170`; `fabric_session_mcp.py:178-194` | Stale spool folders are pruned only when the hooks are live; the stale-lock takeover is check-then-act | C |

### Host installers and the dashboard notice (FAA-69)

| # | Sev | Where | What | Proof |
|---|---|---|---|---|
| 7 | medium | `building-fabric-services/scripts/dashboard_kit.py:190-376` | The SessionStart notice runs `rev-parse`, `ls-files` and an unbounded `os.walk` before asking whether the repository owns a service, so it can pass its 5 s budget in any repository | R (reviewer): 6.24 s with a slow git, in a repository owning no service |
| 8 | medium | `fabric_session_hosts.py:166-226` | The Kimi installer cannot repair a stale `--script` path and refuses to remove it; neither Kimi nor Codex checks that the script exists | R (reviewer) |
| 9 | low | `host_hooks.py:112`; `hosts/opencode/fabric.mjs:17-20`; `hosts/openclaw/index.mjs:22-33` | Hermes `--remove` needs the source folder; the OpenCode and OpenClaw bridges start Python on every request | R / C (reviewer) |

### Service kit, Python twins (FAA-70)

| # | Sev | Where | What | Proof |
|---|---|---|---|---|
| 10 | high | `fabric_supervisors.py:233-262` vs `fabric-supervisors.mjs:252-266` | Python `launchd_plist` checks only environment names; Node and Python's own systemd and Task Scheduler writers also refuse secret values in arguments and environment, a bad label, an empty argv and an `ExitTimeOut` under the drain. The plist is then installed 0644 | C by the auditor; R (reviewer): Python wrote `--api-key=sk-ant-…` into a plist that Node refused |
| 11 | medium | `fabric_interop.py:559-617`, `:674`; `fabric-interop.mjs:449` | `JobStore` is load-modify-save with no lock under a threading server: one idempotency key made two jobs; a cancelled job became `completed`; `pause` writes `pollIntervalMs` on a terminal job before refusing (both twins) | R: `jobs created for one key: 2`, `after: {... 'status': 'cancelled', 'pollIntervalMs': 3600000}` |
| 12 | medium | `fabric_events.py:120` | `JsonlEventLog.append` has the same race: 41 of 160 events kept, ids reused | R (reviewer) |
| 13 | medium | `fabric_delegation.py:630-672` | `JwksCache._fetch` has a per-read timeout only, runs under the cache lock and lets `BadStatusLine` escape; the Node twin bounds the whole fetch | R (reviewer): blocked over 25 s by a 1 byte/s issuer |
| 14 | medium | `fabric_descriptor.py:133,135,379`, `fabric_base.py:41,44`, `fabric_package.py:242` | Python `$`-anchored patterns accept a trailing newline; Node refuses. A descriptor id `"example-agent\n"` validates in Python | R: `'\n' False unauthenticated bad-signature` (Python) vs `malformed` (Node) |
| 15 | medium | `fabric_auth.py:339` vs `fabric-auth.mjs:231` | An origin written `https://host:443` refuses every request in Python and passes in Node | R (reviewer) |
| 16 | medium | `fabric_http.py:375` | On Python 3.9 (the stated floor, and `/usr/bin/python3` on macOS) a socket timeout is reported as `kind="connection"` | R: `/usr/bin/python3` 3.9.6, `test_fabric_http.py` `FAILED (failures=2)` |
| 17 | low | `fabric_interop.py:876`; `fabric_supervisors.py:67,101`; `sample_service.py:274,303` | Non-object MCP `params` crash instead of -32602; `Environment=` values get `$` doubled; the sample service trusts `Content-Length` | R / C (reviewer) |

### Adapting and creating skills (FAA-71)

| # | Sev | Where | What | Proof |
|---|---|---|---|---|
| 18 | high | `adapting-projects-to-fabric/scripts/fabric_provider.py:40,128,233,237,263` | The writer accepts what the pinned `provider.schema.json` refuses: port 80, a non-URI `source.repository`, arguments over 1024 characters; `--env` with `--url` is dropped silently and after `--stdio` it lands in argv | R: exit 0, entry with `127.0.0.1:80/mcp`, `"repository": "not a uri"`, no env |
| 19 | high | `adapt_project.py:600-607` vs `SKILL.md:116-118` | `check` warns only on the zero hash and manifest strings; generic schemas, `urn:fabric:adapter:author`, the weak probe assertion and defaulted data classes pass with no warning | R (reviewer) |
| 20 | medium | `adapt_project.py:468` | `check --contract` calls `pnpm exec tsx`, which can try to purge and reinstall the operator's contract checkout | R (reviewer): `ERR_PNPM_UNSAFE_MODULES_DIR` |
| 21 | low | `adapt_project.py:100,391-418` | `.mcp.json` client configs count as an MCP surface; a non-UTF-8 manifest crashes `check`; `--force` has no dry run or diff | R (reviewer) |

### CI and the contract checks (FAA-72)

| # | Sev | Where | What | Proof |
|---|---|---|---|---|
| 22 | high | `.github/workflows/validate.yml:3-5` | Triggers are `workflow_dispatch` and `workflow_call` only. The organization's rule (fabric-workspace `knowledge/rules.md` §3, org-index `docs/CI-BATCHING.md`) is a nightly hosted run on the default branch; this repository has none, so `main` is checked only when someone dispatches a branch | C: `gh run list --workflow validate.yml`: every run is `workflow_dispatch` on an `agent/*` branch |
| 23 | high | `test/test_contract_revisions.py`, `test/test_dashboard_kit.py:225` | The checks against the pinned contract skip unless `FABRIC_CONTRACT_NEW`/`OLD` point at installed checkouts; no job sets them, and one has already rotted: it compares the fixture's `fabric-dashboard-kit@1.0.0` with the kit's `1.1.1` | R: with both checkouts at the pins and `pnpm install`, `Ran 785 tests ... FAILED (failures=1, skipped=16)`; the 12 revision tests pass |
| 24 | medium | `validate.yml:12-54`, `package.json` | No Python 3.9 job though 3.9 is the stated floor; `test_fabric_session.py` is absent from the Windows job; no macOS job though launchd is the first supervisor; `engines.node` says `>=16` while the code needs 18 | C |
| 25 | low | `test/test_fabric_http.py:199-211` and `sleep(60)` children | Wall-clock margins; the one hosted failure in 40 runs was here | C (reviewer) |

### Release path (FAA-73)

| # | Sev | Where | What | Proof |
|---|---|---|---|---|
| 26 | medium | `release.yml:92-107` | The GitHub release is created `--latest` before the tarball smoke test | C (reviewer) |
| 27 | medium | `release.yml`, `validate.yml` | Actions on floating tags, `npm install -g npm@latest` in the job holding `id-token: write`, an unpinned Claude Code CLI; a standing `NPM_TOKEN` beside OIDC provenance | C (reviewer) |
| 28 | low | `release.yml:100-110,191-210` | Release titles carry U+2014 on every public release page; the text still says the repository is private, and its private branch is dead | C (reviewer) |

### Documents that state false things (FAA-74)

| # | Sev | Where | What |
|---|---|---|---|
| 29 | medium | `SECURITY.md:17-23`, `SKILL-CARD.md:56` | "talks only to `127.0.0.1:<port>`" and "loopback only", while `check_service.py` probes remote https origins and the kit's connectors reach external APIs; only launchd is listed among the supervisor files the kit writes |
| 30 | medium | `building-fabric-services/SKILL.md:348` | `vault.py moved --at <provider>` is not a valid call (`--how` is required) |
| 31 | medium | `creating-fabric-agents/SKILL.md:115-120`, `building-fabric-services/SKILL.md:130-133`, `recipes/support-agent/README.md:47` | The public package tells every user to run `use_secret.py`/`vault.py` with no path or fallback, and its own recipe puts the key in the environment by hand |
| 32 | low | `AGENTS.md:44`; `adapting-projects-to-fabric/SKILL.md:141,198` | "two jobs" (there are three); a CLI that does not speak MCP cannot follow step 4b; `NOT VERIFIED` vs `NOT_VERIFIED` |

### Skills as instructions (FAA-75)

| # | Sev | Where | What |
|---|---|---|---|
| 33 | medium | `test/validate.py:452-464`, `test/evals/*` | The trigger and scenario evals are counted, never run against a model; only `evals/dashboard-links` has a runner |
| 34 | low | the four SKILL.md | Trigger overlap («подключить проект к Fabric» vs «подключись к Fabric»), NOT-for lists that omit sibling skills, 35 duplicated long lines between adapting and creating, three byte-identical copies of `dashboard-links.md`; building's description is 1015 of 1024 characters |

### Hygiene (FAA-76)

Unused imports in `fabric_delegation.py`, `fabric_crypto.py`, `fabric_estate.py`; `fabric_auth.py` and
`fabric_supervisors.py` rely on another import's side effect for `urllib.parse` and `urllib.error`;
`fabric_interop.py` at 953 and `fabric_board_session.py` at 902 of the 1000-line cap; 27 layer modules with no test
file naming them; `test/test_fabric_service.py:584` uses a personal GitHub owner where the neutral-names rule asks
for `example-agent`.

## What this audit did not look at

Live behaviour against a running Fabric (the hooks were exercised against stubs only); the model-side quality of the
skills (finding 33 is exactly that gap); Windows and Linux beyond what the reviewers could reason about from code.
