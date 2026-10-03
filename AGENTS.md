# Working in fabric-agent-adapter

## Read first

1. The PassionCode.ai knowledge base — `fabric-workspace/knowledge/` in your clone (org-index
   `scripts/clone_all.sh` makes it) or https://wiki.passioncode.ai/knowledge — at least its
   [README](https://github.com/passioncode-ai/fabric-workspace/blob/main/knowledge/README.md),
   vision, principles and how-to-work.
2. This file, then the organization's
   [CONTRIBUTING.md](https://github.com/passioncode-ai/.github/blob/main/CONTRIBUTING.md).

## What this repository is

Fabric Agent Adapter: makes any agent or existing project Fabric-compatible (a Provider under
the Fabric Agent Contract) — Agent Skills, reference kits and a conformance probe. It is how an
agent becomes one Fabric can bind; it also works on its own. It ships as a Claude Code plugin and a public npm installer (`@passioncode-ai/fabric-agent-adapter`). It
carries three skills: `adapting-projects-to-fabric` and `creating-fabric-agents`, which adapt a
project to the [Fabric Agent Contract](https://github.com/passioncode-ai/fabric-agent-contract),
and `building-fabric-services`, which runs an agent as a `fabric-service/0.1` local service
that is called the `fabric-interop/0.1` way (`scripts/fabric_interop.py`, `fabric-interop.mjs`).
Agents that are not services get a `fabric-provider/0.1` entry from
`adapting-projects-to-fabric/scripts/fabric_provider.py`.

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
<SKILL.md ...>` parses any SKILL.md front matter strictly, installed copies included. `.github/workflows/validate.yml` runs all four in two jobs
(`python`, `claude-plugin`). `.github/workflows/release.yml` validates, creates a GitHub release
and publishes to npm on a `v*` tag, but only when the repository variables `RELEASE_ENABLED` and
`PUBLISH_NPMJS` are `"true"` — off by default in a fork, both `true` here
(`gh variable list -R passioncode-ai/fabric-agent-adapter`). MCP (register + proving call): the
README's "Quick start → MCP" runs the sample service and calls `sample.echo` from `claude -p`
with `--strict-mcp-config` and a temporary config.

## Where things live

- `plugins/fabric-agent-adapter/`: the plugin and its three skills. `.claude-plugin/marketplace.json`
  holds the marketplace entry.
- `test/`: the unit tests, `validate.py`, and each skill's trigger and scenario evals under
  `test/evals/<skill>/`.
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
- Scripts use the Python standard library only and are non-destructive by default.
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

**Background footprint (LC-09): none.** The plugin is skills only — no hooks, no `.mcp.json`,
no launchd job, no port, no per-session server, no login item. Nothing runs without a window
and nothing idles; there is nothing to stop. `install.sh` and `bin/fabric-agent-adapter.js` run
once when a person calls them and exit.

| What | Started by | Cadence | With no window | Stopped by | Idle budget |
|---|---|---|---|---|---|
| `install.sh`, `npx @passioncode-ai/fabric-agent-adapter` | a person | on demand | nothing | exits when done | 0 |
| Services built with the kit (`fabric_service.py`, `fabric-service.mjs`) | the service's own installer → launchd (`RunAtLoad`, `KeepAlive`) | resident | the service | `launchctl bootout` + `disable`, or `launchd_uninstall` | declared by each service in its own `AGENTS.md` |
| Test suites (`npm test`) | a person or CI | on demand | nothing | exit; the lifecycle tests kill their own children in `finally` | 0 |

The kit's services own their labels and ports; this repository owns none. Tests never touch the
operator's launchd jobs: `test/test_fabric_service_lifecycle.py` puts a fake `launchctl` first on
`PATH` and uses throwaway labels (`ai.passioncode.test.lifecycle-<hex>`) (LC-14).

**Build retention (LC-15).** There is no build step and no release artefact on the machine: npm
and GitHub releases are built by `.github/workflows/release.yml` in CI. Output directories: none.
The only caches are `__pycache__/` (cap: 5 MB) and an `npm pack` tarball if someone makes one (keep
none). Clean command: `find . -name __pycache__ -prune -exec rm -rf {} + && rm -f *.tgz`. Services
built with the kit prune their own releases with `prune_releases` (current + previous).

## Organisation

This repository is one of the `passioncode-ai` repositories. The organization's rules —
branches, commits, CI, leases, secrets, handoffs — live in the knowledge base,
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
