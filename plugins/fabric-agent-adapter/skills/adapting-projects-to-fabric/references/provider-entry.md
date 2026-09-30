# Provider entries: agents that are not services

Normative source: the Fabric Agent Contract's `docs/specification/provider.md`
(`fabric-provider/0.1`, DEC-0016, rulings DEC-0017) at the commit this plugin pins.

An agent Fabric reaches as a CLI or a stdio MCP server — not a long-running service —
is announced by one entry, `providers/<id>.json`, in the same root as the services
directory:

| Platform | Directory |
|---|---|
| macOS | `~/Library/Application Support/ai.passioncode.fabric/providers/` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/passioncode-fabric/providers/` |
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

`--stdio` takes the rest of the line as the argument array; there is no shell string.

It refuses, with one sentence that never quotes a value:

- a manifest that does not resolve, or whose `provider.id` is not the entry's
  `providerId` — the two URIs are compared as URIs (FAC-SEM-014);
- an id that is already a service in `services/` (FAC-SEM-013);
- an env value that is not `secret-ref:<name>`, or a reference that has the shape of a
  credential itself — a token prefix, a private key, a JWT (FAC-SEM-015: a value is
  checked by its form; name patterns apply to names);
- a URL other than `http://127.0.0.1:<port>/mcp`, a manifest path that is not an
  absolute or `~/` path to `fabric-agent.json`, a shell-string command, unknown fields.

`validate` also checks that the file is named `<id>.json` (FAC-SEM-014, slug half).
From Python: `write_provider_entry(entry)`, `remove_provider_entry(id)`,
`validate_provider_entry(entry)`, `manifest_problems(entry)`, `providers_dir()`.

## What the entry does not do

It grants nothing: Fabric lists the agent, and admission (probes) and a project binding
still decide what it may do. The manifest it points at is the authority for the
agent's capabilities. Equality is between like things (DEC-0017): the slug `id` with the
file name, the URI `providerId` with the manifest's URI `provider.id`.
