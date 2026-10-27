# Working in fabric-agent-adapter

## Read first

1. The organization's
   [roadmap](https://github.com/passioncode-ai/fabric-workspace/blob/main/knowledge/roadmap.md):
   every major feature and release across PassionCode.ai as `RM-*` tracks with owner, phase and
   state. It is the entry point: a task here that serves a track names it, and the track's status
   is edited only in the roadmap.
2. The PassionCode.ai knowledge base, `fabric-workspace/knowledge/` in your clone (org-index
   `scripts/clone_all.sh` makes it) or https://wiki.passioncode.ai/knowledge: at least its
   [README](https://github.com/passioncode-ai/fabric-workspace/blob/main/knowledge/README.md),
   vision, principles and how-to-work.
3. This file, then the organization's
   [CONTRIBUTING.md](https://github.com/passioncode-ai/.github/blob/main/CONTRIBUTING.md).

## What this repository is

Fabric Agent Adapter: makes any agent or existing project Fabric-compatible (a Provider under
the Fabric Agent Contract): Agent Skills, reference kits and a conformance probe. It is how an
agent becomes one Fabric can bind; it also works on its own. It ships as a Claude Code plugin and a public npm package (`@passioncode-ai/fabric-agent-adapter`): the skills installer, and since 0.31.0 the `pack`, `sign` and `verify` commands for a `fabric-package/1` folder (contract DEC-0050, DEC-0051; `building-fabric-services/scripts/fabric_package.py`, `fabric-package.mjs`). It
carries four skills: `adapting-projects-to-fabric` and `creating-fabric-agents`, which adapt a
project to the [Fabric Agent Contract](https://github.com/passioncode-ai/fabric-agent-contract),
and `building-fabric-services`, which runs an agent as a `fabric-service/0.1` local service
that is called the `fabric-interop/0.1` way (`scripts/fabric_interop.py`, `fabric-interop.mjs`; job limits per DEC-0087), and checks the estate record, share grants and the estate ceremonies (`fabric_estate.py`, `fabric_share.py`, `fabric_ceremonies.py` and their Node twins).
Agents that are not services get a `fabric-provider/0.1` entry from
`adapting-projects-to-fabric/scripts/fabric_provider.py`. The fourth, `working-with-fabric`, is the
other side: a coding agent opened outside Fabric working in a project through it (Fabric 0.4.0 REQ-07),
with the plugin's Claude Code session hooks (`scripts/fabric_session.py`, COM-04).

## Commands

There is no build step. These are the commands from `README.md` ("Quick start for a new
teammate" → Develop):

```bash
python3 -m unittest discover -s test -v
python3 test/validate.py
claude plugin validate ./plugins/fabric-agent-adapter --strict
claude plugin validate . --strict
```

`npm test` runs the first two plus `node --test 'test/*.test.mjs'`. `python3 test/validate.py --frontmatter
<SKILL.md ...>` parses any SKILL.md front matter strictly, installed copies included. `.github/workflows/validate.yml` runs them
nightly on `main`, on a manual dispatch, and from `release.yml` before a publish; never on each push or pull request.
Its jobs (since 0.41.0, FAA-72) cover the Python and Node suites on Linux, macOS and Windows, the Python 3.9 and Node 18
floors, the contract installed at the pin, and both plugin validations; the file's own job list is the authority. A missing
or billing-blocked run is not a green one. `.github/workflows/release.yml` validates, creates a GitHub release
and publishes to npm on a `v*` tag, but only when the repository variables `RELEASE_ENABLED` and
`PUBLISH_NPMJS` are `"true"`; off by default in a fork, both `true` here
(`gh variable list -R passioncode-ai/fabric-agent-adapter`). MCP (register + proving call): the
README's "Quick start → MCP" runs the sample service and calls `sample.echo` from `claude -p`
with `--strict-mcp-config` and a temporary config.

## Where things live

- `plugins/fabric-agent-adapter/`: the plugin, its four skills and `hooks/hooks.json`. `.claude-plugin/marketplace.json`
  holds the marketplace entry.
- The service kit: `building-fabric-services/scripts/`, layered modules in Python and Node twins, listed in dependency
  order in `kit.json` (a module imports only modules listed before it; none over 1000 lines; the core defined once;
  all enforced by `test/test_fabric_kit.py`). After changing a kit module run `python3 .../fabric_kit.py build`; CI
  fails a stale `kit.json` (`test_kit_json_is_what_the_sources_say`). At a release move `kit.json`'s own `"version"` first: `build` refuses to rewrite the digests of a version that has a release tag. The map, the layers and the rule for a new module: `references/kit-modules.md`. Recipes on the
  kit: `building-fabric-services/recipes/`. `fabric_session.py` in working-with-fabric is a facade over
  `fabric_session_{env,mcp,mail,hosts,cli}.py`; hooks and workers always run the facade.
- `test/`: the unit tests, `validate.py`, and each skill's trigger and scenario evals under
  `test/evals/<skill>/`. `test/evals/run_evals.py` runs the trigger evals against a real client, only when asked
  (`FABRIC_REAL_CLIENT=1` and `claude` on PATH); hosted CI holds no model credential and does not run it. Measured
  runs are recorded under `docs/evidence/evals/`.
- `docs/evidence/`: specs, plans, evals, reports and retrospectives. The scaffold's write set is
  declared in the [delivery brief](docs/evidence/specs/2026-08-27-brief.md).
- `CHANGELOG.md`, `SECURITY.md` and `SKILL-CARD.md` sit at the root. This repository has no ADR
  directory. Task handoffs go in `docs/handoffs/<date>-<topic>.md`.

## Local rules

These come from `CONTRIBUTING.md`, `SECURITY.md` and `README.md`:

- Start from the pinned Fabric contract (`0.1.0`; the one pin is `fabric-contract.lock.json`, and
  `test/validate.py` fails any other revision named in a live file). Updating the pin
  is a compatibility change: review all three profiles, regenerate fixtures intentionally and
  release a new version. Never copy a newer normative rule in while the old pin stays in metadata.
- Write the intended behaviour and evidence first. Add or update the trigger and scenario evals
  before you change instructional prose.
- Scripts use the Python standard library only and are non-destructive by default. The Hermes native
  plugin alone may import `hermes_cli.config` from its running host for read-only MCP registration;
  it adds no pip dependency. `test/validate.py` scopes this exception to that adapter file.
- Keep the marketplace, plugin, skill metadata and changelog versions in sync.
- SKILL.md front matter must survive a strict YAML reader, not only Claude Code: a value holding
  `: ` or ` #` goes in a folded block (`description: >-`) or quotes. `test/validate.py` enforces it.
- Never write secret values to manifests, fixtures, probes, logs or command arguments. Treat
  generated files and provider outputs as untrusted.
- The repository and the npm package are public (since 2026-09-29). Everything in the `files`
  list in `package.json` ships to npm.
- The licence is the organization's (Fabric ADR-0092): `AGPL-3.0-only OR
  LicenseRef-PassionCode-Commercial` in every manifest and skill, and `LICENSE`,
  `COMMERCIAL-LICENSE.md` and `CLA.md` byte for byte the knowledge base templates. Released
  versions keep theirs: v0.4.3 to v0.5.2 PolyForm Noncommercial or Internal Use, v0.4.2 and
  earlier MIT (GitHub and npm). Contributions come in under `CLA.md`. `test/validate.py`
  enforces all of it.
- The MCP step of the README quick start is verified with a real client (`claude -p` with
  `--strict-mcp-config` and a temporary config), never only through the kit's own tests.
- Examples, evals and docs use neutral names (`example-agent`); an agent someone built for
  themselves never appears in them.
- **Shared registers are edited under a lease.** [docs/AGENT_SYNC.md](docs/AGENT_SYNC.md)
  (generated from `.claude/agent-sync.json` by `agent_sync.py setup`; never edited by hand) lists
  the guarded files and the gate. Run `agent_sync.py acquire <file>` before editing one and
  `agent_sync.py release <file>` after, on every path including failure. The lease is a ref under
  `refs/agent-sync/leases/` on `origin`, so another contributor's agent sees it
  (`git ls-remote origin 'refs/agent-sync/leases/*'`); the record plane is local (`fs`), and
  `.agent-sync/` is git-ignored. No register here carries a "Next free ID" line, so nothing is
  reserved yet; a register that gains one is declared under `idRegisters` and taken with
  `agent_sync.py reserve <REG>`.

## Lifecycle

The org contract is [knowledge/lifecycle.md](https://github.com/passioncode-ai/fabric-workspace/blob/main/knowledge/lifecycle.md);
this repository both obeys it and ships its service layer
([`references/lifecycle.md`](plugins/fabric-agent-adapter/skills/building-fabric-services/references/lifecycle.md)).

**Background footprint (LC-09): five session hooks, nothing resident.** The plugin is skills plus
`plugins/fabric-agent-adapter/hooks/hooks.json`:

- `SessionStart` (matcher `startup|clear`): `dashboard_kit.py notice` asks the repository for its identity
  (`git rev-parse`, `git config`) and the services directory first; only when the repository owns a service (a
  descriptor names it as `source.repository`) does it read the tree (`git ls-files` or `git grep`), all within one
  3.5 s budget. It prints one line when that service's dashboard has no dashboard kit or an older one, prints nothing
  when the budget runs out, and exits 0, always, within its 5 s timeout; it writes nothing. Measured under a
  load average of about 50: median 294–443 ms per session start.
- `SessionStart`, `Stop`, `UserPromptSubmit`, `SessionEnd`: `fabric_session.py hook …` (working-with-fabric). Session
  start (matcher `startup|clear`) reads `~/.claude.json` and Fabric's `hub.json`, and prints the preamble only when
  `fabric` is registered, Fabric runs and the project uses Fabric (a contract file up to the checkout root, a
  project-bound registration, or, read last, a service descriptor naming the checkout's origin, one `git config`
  call); in a folder with no such sign, one line pointing at `fabric_whoami` (FAA-60); when Fabric is down, one line,
  and only in a project that uses Fabric. Stop and SessionEnd first remove
  their own session folders untouched for 7 days, then read `hub.json` and return, writing nothing else, unless the
  running Fabric advertises `session-hooks/1`; then they measure the turn's git facts (counts only, at most 1.5 s);
  only once a worker has seen the running Fabric's `fabric_session_observe` take `repositories` (a mark in the hooks'
  folder), Stop also reads the tail of the session's transcript (at most 512 KB from its end; message text and tool output, which can
  hold a secret the session displayed, are read with it in memory only, and only the current turn's tool names and path arguments are used) and names the other Git repositories the turn
  touched as `{host, owner, name}` from their `origin`, one `git rev-parse` and one `git config` each inside the same 1.5 s
  (FAA-140; measured 2026-10-27 at `f3765f1`, before the gate and the 64 KB cap, with a 4.8 MB transcript naming six other repositories: median 247 ms, against 109 ms
  for 0.52.0 on the same transcript, [raw](docs/reports/2026-10-27-faa-140-turn-repositories/raw/stop-hook-timing.log)); and they
  write a spool entry (0600, at most 50 per session) in the user's cache folder and start a **detached worker**
  (`fabric_session.py deliver`) that runs `fabric-mcp --rejoin-only` in its own process group with a 10 s deadline
  (the whole group is ended at the deadline; a refused or unreadable entry is logged by its code and dropped; an end
  whose release got no answer stays for the next worker), reads the board's unread
  count (`com.status`) after a turn, and exits. A session rejoins at most once a minute: a turn within 60 s of its
  last successful rejoin stays in the spool for the next worker; the end of a session always starts one (FAA-53). UserPromptSubmit reads small files in that spool (the count) and takes the nudges a
  turn's answer carried by renaming their file away (FAA-142); it calls nothing. Every one is silent in a session Fabric launched; a launched session is remembered by a marker so the process walk
  runs once, and a walk that cannot read the processes spools nothing (FAA-68). Measured 2026-10-11 under a load average of about 220,
  with the feature absent: medians 282 / 271 / 329 ms for start / stop / end, of which 65 ms is Python's own start
  ([raw](docs/reports/2026-10-11-working-with-fabric/raw/hook-timing.log)); the prompt hook is measured in
  [FAA-12a's raw](docs/reports/2026-10-12-faa-12a-board-participants/raw/hook-timing.log).
- Codex and Kimi Code: `fabric_session.py hook session-start --host codex|kimi`, only where the person added it with
  `install-host-hooks --apply`; it prints the preamble and exits.

No `.mcp.json`, no launchd job, no port, no per-session server, no login item. Nothing idles on its own; the one
long-lived process, `watch-mail`, runs only while an agent waits on the board, under that agent's watcher. `install.sh` and `bin/fabric-agent-adapter.js` (the installer and `pack`/`sign`/`verify`) run once when a person calls them and exit.

| What | Started by | Cadence | With no window | Stopped by | Idle budget |
|---|---|---|---|---|---|
| `install.sh`, `npx @passioncode-ai/fabric-agent-adapter` | a person | on demand | nothing | exits when done | 0 |
| `npx @passioncode-ai/fabric-agent-adapter pack\|sign\|verify`, `fabric_package.py`, `fabric-package.mjs` | a person or their agent | on demand | nothing | exits when done; writes only `fabric.package.json` in the folder named, and only with `--apply` | 0 |
| `dashboard_kit.py notice` (plugin `SessionStart` hook) | Claude Code, at session start or `/clear` | once per session | nothing | exits when done (≤ 5 s timeout) | 0 |
| `fabric_session.py hook session-start\|stop\|session-end` (plugin hooks) | Claude Code | per session start or `/clear`, per turn, per session end | nothing | exits when done (≤ 5 s timeout) | 0 |
| `fabric_session.py hook user-prompt-submit` (plugin hook) | Claude Code | per prompt | nothing | exits when done (≤ 5 s timeout) | 0 |
| `fabric_session.py hook session-start --host codex\|kimi` | Codex / Kimi Code, only after `install-host-hooks --apply` | once per session | nothing | exits when done (≤ 5 s timeout) | 0 |
| `fabric_session.py watch-mail` | a Claude Code agent, under its own background watcher, while it waits on the board | one look per interval (default 60 s ± 20 %, kept between 10 s and 15 min after the jitter; backoff to 15 min while Fabric is down; a look within a minute of the session's last rejoin waits; a look that finds turns the hooks spooled delivers them through its own rejoin, FAA-89) | nothing | its stdin's end, SIGTERM/SIGINT/SIGHUP, or its parent gone | 0 between looks (a sleeping process; each look one `fabric-mcp --rejoin-only` with a 10 s deadline) |
| `fabric_session.py deliver` (detached worker) | the Stop / SessionEnd hook, only when Fabric advertises `session-hooks/1` | per turn, at most one start per session a minute (an end always starts one), one per session at a time | finishes its spool | its own 10 s deadline; closes `fabric-mcp`'s stdin, then ends its whole process group | 0 |
| Services built with the kit (`fabric_service.py`, `fabric-service.mjs`) | the service's own installer → launchd (`RunAtLoad`, `KeepAlive`), a systemd user unit (`Restart=always`) or a per-user Scheduled Task (logon trigger) | resident | the service | `launchctl bootout` + `disable` or `launchd_uninstall`; `systemctl --user disable --now` or `systemd_uninstall`; `schtasks /End` + `/Change /DISABLE` or `task_uninstall` | declared by each service in its own `AGENTS.md` |
| Test suites (`npm test`) | a person or CI | on demand | nothing | exit; the lifecycle tests kill their own children in `finally` | 0 |

The kit's services own their labels and ports; this repository owns none. Tests never touch the
operator's launchd jobs: `test/test_fabric_service_lifecycle.py` puts a fake `launchctl` first on
`PATH` and uses throwaway labels (`ai.passioncode.test.lifecycle-<hex>`) (LC-14); the systemd and Task Scheduler
installers run against a recorder in place of `systemctl` and `schtasks` (`test/*supervisors*`).

**Build retention (LC-15).** There is no build step and no release artefact on the machine: npm
and GitHub releases are built by `.github/workflows/release.yml` in CI. Output directories: none.
The only caches are `__pycache__/` (cap: 5 MB) and an `npm pack` tarball if someone makes one (keep
none). Clean command: `find . -name __pycache__ -prune -exec rm -rf {} + && rm -f *.tgz`. Services
built with the kit prune their own releases with `prune_releases` (current + previous).

## Organisation

This repository is one of the `passioncode-ai` repositories. The organization's rules
(branches, commits, CI, leases, secrets, handoffs) live in the knowledge base,
[`knowledge/rules.md`](https://github.com/passioncode-ai/fabric-workspace/blob/main/knowledge/rules.md)
(Fabric ADR-0093); the repository map and onboarding are in
[passioncode-ai/org-index](https://github.com/passioncode-ai/org-index) (both private; readable
by every org member):

- [repositories](https://github.com/passioncode-ai/org-index#repositories): which repository owns what, and how they connect
- [ONBOARDING.md](https://github.com/passioncode-ai/org-index/blob/main/ONBOARDING.md): setting up a new contributor's machine

Where this file is stricter than the organization's rules, this file wins. A change to this repository's
role, dependencies or test command updates its row in `org-index/repositories.json` in the same change.

## Shared backlog

[docs/backlog-sources.json](docs/backlog-sources.json) declares this repository's canonical
local task sources and their vision goals. The [common backlog contract](https://github.com/passioncode-ai/fabric-workspace/blob/main/knowledge/backlog.md)
owns aggregation; [the workspace backlog](https://wiki.passioncode.ai/backlog) is a derived view.
Edit a task only in its canonical source under an agent-sync lease, retain stable IDs and
closure receipts, and declare any new source in the manifest. Do not edit generated task
status in the workspace or copy another repository's task into a second editable row.
Land the source change, then run `node scripts/workspace.mjs sync` from a Fabric checkout
(or use the scheduled sync); check the published source commit before calling it current.

## After work

In the same run: update this repository's docs with the change; if a cross-repository fact changed
(a product, a version, a plan row, a principle), update the page in `fabric-workspace/knowledge/`
that owns it; land both; publish (`node scripts/workspace.mjs sync` from a Fabric checkout) or
leave it to the scheduled sync. Leave a handoff with the exact next task.
