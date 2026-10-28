# Provider entries: agents that are not services

Normative source: the Fabric Agent Contract's `docs/specification/provider.md`
(`fabric-provider/0.1`, DEC-0016, rulings DEC-0017) at the commit this plugin pins.

An agent Fabric reaches as a CLI or a stdio MCP server (not a long-running service)
is announced by one entry, `providers/<id>.json`, in the same root as the services
directory:

| Platform | Directory |
|---|---|
| macOS | `~/Library/Application Support/ai.passioncode.fabric/providers/` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/passioncode-fabric/providers/` |
| Windows | `%LOCALAPPDATA%\passioncode-fabric\providers\` (the same root as the services folder, DEC-0032; `~\AppData\Local` when `LOCALAPPDATA` is unset) |
| any | `FABRIC_PROVIDERS_DIR` when set |

A service uses a descriptor instead (the `building-fabric-services` skill). One id is a
service or a provider, never both.

## The writer

`scripts/fabric_provider.py` is the installer's tool; it writes atomically, mode 0600,
and refuses what the contract refuses.

```bash
python3 scripts/fabric_provider.py write --id example-agent --provider-id https://agents.example/providers/example-agent \
  --name "Example Agent" \
  --manifest ~/.local/share/example-agent/fabric-agent.json --installed-by "example-agent 1.0.0" \
  --env EXAMPLE_API_KEY=secret-ref:example-agent/EXAMPLE_API_KEY \
  --stdio ~/.local/bin/example-agent mcp
python3 scripts/fabric_provider.py write ... --url http://127.0.0.1:47201/mcp
python3 scripts/fabric_provider.py validate ~/Library/Application\ Support/ai.passioncode.fabric/providers/example-agent.json
python3 scripts/fabric_provider.py remove example-agent      # the uninstaller
```

`--stdio` comes last and takes the rest of the line as the argument array; there is no shell string. A writer
option after it (`--env`, `--name`, ...) is refused rather than swallowed into argv; write `--stdio -- EXECUTABLE ...`
when the server itself takes an option of that name. `--env` belongs to a stdio server and is refused with `--url`. An entry may carry
`run.mcp.stdio.scope` (DEC-0044): `project` (started for the sessions of a project that binds it) or `on-demand`;
`session` (a server in every coding session) is refused (FAC-SEM-056, LC-19). The validator accepts the field; the
writer does not set it until Fabric reads it. An argument that carries a credential is refused
(LC-21, FAC-SEM-057): a key goes in `env` as a `secret-ref:<name>`, never in argv.

It refuses, with one sentence that never quotes a value:

- a manifest that does not resolve, or whose `provider.id` is not the entry's
  `providerId`: the two URIs are compared as URIs (FAC-SEM-014);
- an id that is already a service in `services/` (FAC-SEM-013);
- an env value that is not `secret-ref:<name>`, or a reference that has the shape of a
  credential itself: a token prefix, a private key, a JWT (FAC-SEM-015: a value is
  checked by its form; name patterns apply to names);
- what the pinned `provider.schema.json` refuses: a URL other than `http://127.0.0.1:<port>/mcp` with a port from 100
  to 65535, a manifest path that is not an absolute, `~/` or `~\` path to a file named `fabric-agent.json` after
  either separator (DEC-0145; or is a network share, or over 1024 characters), a shell-string command, more than 32
  arguments or one over 1024 characters, more than 64 env names, a `source.repository` that is not an absolute URI, an
  `installedAt` that is not an RFC 3339 date-time, unknown fields. The patterns are the schema's, copied
  (`test_provider.SchemaParityTests` compares them with a contract checkout at the pin when `FABRIC_CONTRACT_NEW` names
  one, as the contract job of the nightly CI does), and the reader is held to every `provider.schema.json` fixture of
  the pin (`test/fixtures/contract/provider-fixtures.json`, `test_provider.ContractFixtureTests`);
- a `source.repository` with a `user:password@` or a value shaped like a credential: it names the repository, never
  reaches it (since 0.49.3, as the service kit's descriptor check);
- a manifest whose name follows a backslash (`C:\Agents\example\fabric-agent.json`). The reader,
  `validate_provider_entry`, accepts it since DEC-0145 (`MANIFEST_PATTERN`, the schema's), but a reader that has not
  re-pinned to DEC-0145 refuses the entry, Fabric's registry among them (CT-192), so the writer does not emit it until
  the oldest Fabric release in use reads it (the release after v0.3.15, CO-479). Write the path with `/` before the name. A manifest under the home folder
  (`~/Agents/example/fabric-agent.json`) is read by every Fabric release; one with a drive letter
  (`C:/Agents/example/fabric-agent.json`) only by Fabric after v0.3.15, whose registry took the repin (CO-479): v0.3.15
  and earlier read only a manifest under `~/` or `/`, so not `~\` either.

`validate` also checks that the file is named `<id>.json` (FAC-SEM-014, slug half): the stem is what follows the last
`/` or `\`, on every platform (CT-193).
From Python: `write_provider_entry(entry)`, `remove_provider_entry(id)`,
`validate_provider_entry(entry)`, `manifest_problems(entry)`, `providers_dir()`.

## What the entry does not do

It grants nothing: Fabric lists the agent, and admission (probes) and a project binding
still decide what it may do. The manifest it points at is the authority for the
agent's capabilities. Equality is between like things (DEC-0017): the slug `id` with the
file name, the URI `providerId` with the manifest's URI `provider.id`.
