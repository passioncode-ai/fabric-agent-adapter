# fabric-agent-adapter — working in this repository

## Role

A portable adapter that makes any agent or existing project Fabric-compatible (a Provider under
the Fabric Agent Contract). It ships
as a Claude Code plugin and a public npm installer (`@passioncode-ai/fabric-agent-adapter`). It
carries three skills: `adapting-projects-to-fabric` and `creating-fabric-agents`, which adapt a
project to the [Fabric Agent Contract](https://github.com/passioncode-ai/fabric-agent-contract),
and `building-fabric-services`, which runs an agent as a `fabric-service/0.1` local service.

## Build and test

There is no build step. These are the validation commands from `README.md` ("Validate this
repository"):

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
`PUBLISH_NPMJS` are `"true"`. It is off by default.

## Where things live

- `plugins/fabric-agent-adapter/`: the plugin and its two skills. `.claude-plugin/marketplace.json`
  holds the marketplace entry.
- `test/`: the unit tests, `validate.py`, and each skill's trigger and scenario evals under
  `test/evals/<skill>/`.
- `docs/evidence/`: specs, plans, evals, reports and retrospectives. The scaffold's write set is
  declared in the [delivery brief](docs/evidence/specs/2026-08-27-brief.md).
- `CHANGELOG.md`, `SECURITY.md` and `SKILL-CARD.md` sit at the root. This repository has no ADR
  directory. Task handoffs go in `docs/handoffs/<date>-<topic>.md`.

## Rules in this repository

These come from `CONTRIBUTING.md`, `SECURITY.md` and `README.md`:

- Start from the pinned Fabric contract (`0.1.0`, the commit is in `README.md`). Updating the pin
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
- Source-available, never "open source" or "MIT": `PolyForm-Noncommercial-1.0.0 OR
  LicenseRef-PolyForm-Internal-Use-1.0.0` in every manifest and skill; releases up to v0.4.2
  (GitHub and npm) stay MIT. Contributions come in under `CLA.md`. `test/validate.py` enforces it.
- Examples, evals and docs use neutral names (`example-agent`); an agent someone built for
  themselves never appears in them.

## Organisation

This repository is one of the `passioncode-ai` repositories. **The org map, the shared
rules and onboarding live in [passioncode-ai/org-index](https://github.com/passioncode-ai/org-index)**
(private; readable by every org member):

- [README](https://github.com/passioncode-ai/org-index#repositories): which repository owns what, and how they connect
- [RULES.md](https://github.com/passioncode-ai/org-index/blob/main/RULES.md): branches, commits, CI, leases, secrets, handoffs
- [ONBOARDING.md](https://github.com/passioncode-ai/org-index/blob/main/ONBOARDING.md): setting up a new contributor's machine

Where this file is stricter than RULES.md, this file wins. A change to this repository's
role, dependencies or test command updates its row in `org-index/repositories.json` in the same change.
