# Recipe: a service that is only a dashboard

A `fabric-service/0.1` service with a dashboard and nothing else: no capabilities, no `mcp` surface, no `usage`
surface, no provider key and no token of anybody else. Fabric Dashboards asked for it (FD-171, board thread
`38c35e11`) for a page that shows what the agents of this computer are doing; this recipe is the shape agreed there
(FAA-268). Built only on the service kit (`fabric_service.py`, `fabric-service.mjs`). Tests:
`test/test_recipe_dashboard_only.py` and `test/recipe-dashboard-only.test.mjs`.

## Install

```bash
python3 recipes/dashboard-only/install.py --id example-dashboard --folder ~/.local/share/example-dashboard
node recipes/dashboard-only/install.mjs --id example-dashboard --folder ~/.local/share/example-dashboard
```

Both twins take the same flags and write the same descriptor bytes (but `installedAt`). Optional flags: `--instance`
(default `default`), `--name`, `--repository` (the repository its code is built from; by default the folder's own
`https://` origin, and a new install without one is refused by the kit, FAA-198), `--port` (this port and no other),
`--label` with `--plist` (a launchd job, below), `--services-dir` (default `FABRIC_SERVICES_DIR`, else the OS's),
`--json`.

| Output | Rule |
|---|---|
| last stdout line | `{"descriptor": "<path>", "key": "<id>.<instance>", "port": <n>}`; `--json` prints only it |
| a repeat with the same `--id` | changes nothing and answers the same line; a descriptor of that key another installer wrote, or one with another `--folder`, is refused and left as it is |
| exit codes | 0 installed or already installed, 1 refused (the reason on stderr, never a value), 2 usage |

The folder gets the token file (`service.token`, 0600, never printed) and later the event log, the login state and
`snapshot.json`. A refused install writes nothing.

## The port

The installer takes the first port of 47300 to 47999 that no other descriptor of this account declares and that
`127.0.0.1` binds now, and writes the descriptor through the kit's `write_descriptor` / `writeDescriptor`, whose port
claim check refuses a port another descriptor declares; a port taken between the two is retried on the next one, up to
eight. That is the kit's port check as it stands, the older sense of a port claim
([lifecycle.md](../../references/lifecycle.md), *Install, upgrade, uninstall*): a port another OS account listens on
or claims still passes (FAA-225). The contract's HA-1 claim file per OS account is not written, because its schema
waits on the contract's CT-228; the recipe writes it the day the kit does, with no change to its flags or its output.

## Running it

```bash
python3 recipes/dashboard-only/dashboard_service.py serve --descriptor <path the installer printed>
```

It serves `/.well-known/fabric-service` (surfaces `dashboard` and `events` only), the events feed and the login code
for the service token, the one-time login and the signed-in page. Under launchd, pass `--label` and `--plist` on the
first install and install the job with the kit's `launchd_plist` and `launchd_install`
([lifecycle.md](../../references/lifecycle.md)), whose `ProgramArguments` run the line above from a release
directory. `check_service.py <id>` passes every rule it can run on it (the test runs it).

## Where its data comes from

The page shows `<folder>/snapshot.json`, which the person's agent writes from what it reads through the Fabric
Dashboards MCP (`list_services`, `spend`, `connections`) and Project Observatory's tools. The service itself calls
nobody, so it holds no token but its own:

```json
{"takenAt": "2026-11-12T08:00:00Z",
 "sections": [{"title": "Services", "source": "fabric-dashboards list_services",
               "columns": ["Service", "State"], "rows": [["example-agent.default", "ready"]]}]}
```

A snapshot that is missing, cannot be read, does not have this shape, is over 1 MB or is older than a day is
reported in `degraded` (source `snapshot`) and never shown as data. The well-known document declares the snapshot as
its one connection (`kind: store`), so a host draws where the page's numbers come from.
