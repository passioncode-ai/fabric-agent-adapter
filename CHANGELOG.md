# Changelog

## 0.4.3 - 2026-09-29

### Changed

- **License.** The adapter is now source-available under
  `PolyForm-Noncommercial-1.0.0 OR LicenseRef-PolyForm-Internal-Use-1.0.0`, with a
  commercial license on request (contact@passioncode.ai). Versions up to and including
  v0.4.2, on GitHub and on npm, were released under MIT and remain available under it. The manifests, the three skills' `license:` and the README say the
  same; contributions come in under `CLA.md`, which the new PR template asks for.
  `test/validate.py` fails a tree that slips back to MIT.
- Author and marketplace owner are PassionCode.ai (`https://passioncode.ai/`).
- **Contract pin** moves from `20a818e` to `a5a2709` (fabric-agent-contract `main`), the
  commit `building-fabric-services` already pinned. Between the two the provider
  profiles are unchanged — only the `fabric-service/0.1` extension was added — and
  `adapt_project.py check --contract` gives the same verdicts for an MCP, an A2A and a
  local-runner bundle at both commits (declaration shape PASS). One pin for all three
  skills.
- `creating-fabric-agents` hands the agent's own loop to `agent-orchestrator`, its
  eval suite to `agent-evals` (agent-stack) and plugin packaging to `make-skill`;
  `adapting-projects-to-fabric` sends wire-level MCP/A2A questions to `agent-interop`.

### Fixed

- The installer's help names the launcher by its npm org name,
  `npx @passioncode-ai/passioncode@latest update`; the bare `passioncode` is not ours.
- A distributed eval named a personal agent as its example service; the
  `building-fabric-services` evals use `example-agent`, and its description says "a
  macOS machine" instead of naming whose.

## 0.4.2 - 2026-09-29

- Kit: `LoopbackHTTPServer`, a `ThreadingHTTPServer` whose bind asks no resolver.
  `http.server` calls `socket.getfqdn()` between `bind()` and `listen()`; on a macOS
  CI runner that held a service's port bound but silent for over 20 seconds. The
  sample service and the skill's startup order use it, and the skill names the trap.
- Kit: a garbled pid file (for example a superscript digit) now reads as "no pid"
  instead of raising `ValueError` while naming the holder of a lock.

## 0.4.1 - 2026-09-29

### Fixed

- `building-fabric-services` could not be loaded by a strict YAML reader: its
  front-matter `description` was an unquoted plain scalar holding `: `
  ("fabric-service/0.1 extension: which surface", line 3, column 493), which YAML
  rejects with "mapping values are not allowed here". Claude Code read it
  leniently, so the plugin worked, but an agent reading the skill from
  `~/.agents/skills` could drop it. The description is now a folded block
  scalar (`>-`) with the exact same text (927 characters).
- The validator could not see that class of defect: `test/validate.py` now
  parses every SKILL.md front matter strictly (standard library only) and
  rejects what a YAML reader rejects in an unquoted value — `: ` or a trailing
  `:`, ` #` (a comment that silently truncates the value), a leading indicator
  character, a duplicate key, an unclosed quote, an undeclared multi-line
  value — with the line and column. `test/test_validate.py` plants each case.
  `validate.py --frontmatter <SKILL.md ...>` checks installed copies anywhere.
- The release smoke test looked for `~/.claude/skills`, where the installer has
  not written since 0.4.0, so it would fail on the first release that ran it.
  It now checks all three skills in `~/.agents/skills`, that `~/.claude/skills`
  stays untouched, and that the installed front matter parses strictly.
- `SKILL-CARD.md` versions and the release smoke paths joined the validator's
  sync checks.

## 0.4.0 - 2026-09-28

- Add the `building-fabric-services` skill for the `fabric-service/0.1` local
  service extension (Fabric Agent Contract DEC-0015): surface choice (MCP
  streamable HTTP, CLI, A2A), token and one-time login, state and cache
  directories, one copy per machine, launchd, descriptor, well-known document,
  events feed and notifications.
- Ship reference kits in Python (`fabric_service.py`) and Node
  (`fabric-service.mjs`) whose instance locks exclude each other, a complete
  `sample_service.py`, and `check_service.py`, a live conformance probe that
  reports PASS, FAIL or NOT_RUN per rule.
- `creating-fabric-agents` now routes an agent that runs as a service through
  the new skill.
- Fix the installer shadowing its own plugin: `npx @passioncode-ai/fabric-agent-adapter`
  and `install.sh` now install into the agents hub `~/.agents/skills`; a plain
  copy into `~/.claude/skills` is refused while the plugin is installed, and
  `--prune-shadow` moves existing shadowing copies aside.

## 0.3.1 - 2026-08-27

- Fix the executable bit on `bin/fabric-agent-adapter.js` and `install.sh`: the
  packed tarball shipped them non-executable, so `npx` failed with exit 126.
  Caught by the release workflow's own packed-tarball smoke — the gate this
  release added, doing its job on its first run.

## 0.3.0 - 2026-08-27

- Ship the npm channel: the package is `@passioncode-ai/fabric-agent-adapter`,
  an installer CLI (`bin/fabric-agent-adapter.js`) plus the plugin tree, with
  `install.sh` as the POSIX fallback.
- Add toggleable release automation (`release.yml`): a `v*` tag runs validate,
  checks tag reachability and version sync, cuts the GitHub release from the
  CHANGELOG section, smoke-tests the packed tarball from a clean cwd (the
  repository is private, so the tarball — not `npx github:` — is the artifact
  under test), and publishes to npm with provenance. Armed by RELEASE_ENABLED
  and PUBLISH_NPMJS repository variables.
- Extend the validator: package.json joins the version sync, the files
  whitelist and scoped-access rules are checked, and the new files are required.

## 0.2.0 - 2026-08-27

- Add the `creating-fabric-agents` skill: the intake grill (capability, named
  consumer, workflow-or-agent, profile, effect and tenancy declarations), the
  knowledge intake whose recorded traps become planted eval fixtures, skeleton
  and scaffold reuse of the pinned contract machinery, two-clock evals, and the
  canary-binding expectation in the conformance report.
- Point the adapting skill's boundary at its new sibling for greenfield requests.
- Rework the repository validator for multiple skills with per-skill trigger and
  scenario evals.

## 0.1.0 - 2026-08-27

- Add the `adapting-projects-to-fabric` skill.
- Add evidence-based MCP, A2A, and local-runner profile selection.
- Add a standard-library project inspector, non-destructive scaffolder, and checker.
- Add contract pinning and independent conformance gate reporting.
- Add trigger/scenario evals, unit tests, repository validator, and plugin packaging.

