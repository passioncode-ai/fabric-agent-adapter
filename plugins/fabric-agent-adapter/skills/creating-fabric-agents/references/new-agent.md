# One command for a new agent project

`new` creates an agent project with the contract built in, from the kit's template (FAA-270, North Star G21). It runs
after the intake grill (step 0) has named the agent's id, its profile and whether it runs as a service; the grill's
other answers still go into the project by hand.

```bash
npx @passioncode-ai/fabric-agent-adapter new <folder> --id <agent-id> [--profile mcp|a2a|local-runner] [--service]
python3 <plugin-dir>/skills/adapting-projects-to-fabric/scripts/new_agent.py <folder> --id <agent-id> [...]
```

Both run the same script (the npm command runs it under the first Python 3.9 or later on PATH). Optional flags:
`--capability <domain.action>` (default `<id>.run`), `--effect <class>` (default `none`: declare money, deletion or
publication now), `--force`, `--json`.

## What it writes

| Path | What |
|---|---|
| `fabric-agent.json`, `fabric-contract.lock.json`, `fabric/` | the provider bundle `adapt_project.py scaffold` writes, pinned to the contract; every value it invents is a sentinel `adapt_project.py check` names |
| `fabric.source.json` | the source manifest (DEC-0149): `include` names the project's source, default deny; the slots are the publisher's URI behind `provider.createdBy` (`PUBLISHER_URI`), the placement record (`PLACEMENT_RECORD`) and, for a service, its supervisor label and port (`SUPERVISOR_LABEL`, `SERVICE_PORT`), never a value ([the source and the instance](source-and-instance.md)) |
| `src/placement.py`, `tests/test_placement.py` | the placement guard ([where agents run](where-agents-run.md), *Its own machine*): placed on another machine, it refuses to start; no record, it starts; a record it cannot read, it starts degraded; the three cases are its tests |
| `config/placement.example.json` | Project Observatory's placement record (`observatory-placement/1`) on neutral values: the shape the guard reads |
| `README.md`, `LICENSE`, `.gitignore` | the layout and the slots by name; all rights reserved until the owner names the terms; the instance kept out of Git |
| `service/` (with `--service`) | the service kit's sample (`service.py`, a `fabric-service/0.1` service) and the kit modules it imports, copied by `fabric_kit.py install` so `fabric_kit.py status` checks them later |
| `fabric/new-agent.json` | the arguments it was made with, so a repeat is recognised |

## Rules

- **Idempotent.** A repeat with the same arguments in a folder this command made changes nothing and answers the same
  line with `"repeated": true`.
- **Never over someone's files.** A folder holding anything else is refused (exit 1) unless `--force`, which writes the
  planned files over it and leaves every other file as it is.
- **The last stdout line is JSON:** `{"folder", "id", "profile", "service", "created", "repeated"}`; `--json` prints
  only it. Exit 0 made or already made, 1 refused (the reason on stderr), 2 usage.
- **Done means checked.** The new project passes `fabric_source_check.py check <folder>` under its own manifest and its
  own tests; a service passes `check_service.py` against its sample once it is served and registered
  (`python3 service/service.py serve --id <agent-id> --port <port> --data-dir <data>`, then `register` with
  `--repository`). Then the sentinels are replaced, the grill's answers written in, and the agent built.

What it does not do yet: infer the agent from a sentence (`new "<sentence>"`) and run its evals (`test`). Both stay with
FAA-26, blocked on Fabric's `fabric.agent.create`.
