# FAA-235: how Claude Code keys a `--scope local` MCP entry

Run 2026-11-12 with Claude Code 2.1.299 on macOS, under a throwaway `HOME` (no `CLAUDE_CONFIG_DIR`), so no real
configuration was read or written. A git repository `repo` with a folder `repo/sub/deeper`, and a plain folder
`plain` with a child `plain/child`. `claude mcp add --scope local fabric -- /x/fabric-mcp --runner claude-code` was run
in `repo/sub/deeper`, and `claude mcp add --scope local fabric -- /y/fabric-mcp` in `plain`; a nested repository
`repo/nested` was then made with `git init`. The script printed only the keys of `projects` that hold `mcpServers`, and
for each folder the number of `fabric:` lines `claude mcp list` printed there. Temporary paths are written `<tmp>`.

## Output

```text
2.1.299 (Claude Code)
['<tmp>/plain', '<tmp>/repo']
repo/sub: 1
plain/child: 0
repo/nested: 0
plain: 1
```

## What it shows

- Inside a checkout the entry is keyed by the git root (`<tmp>/repo`), not the folder `claude mcp add` ran in, and it
  applies in every folder of that checkout (`repo/sub`).
- Outside a checkout it is keyed by the folder itself (`<tmp>/plain`) and applies there only: a child folder outside
  git (`plain/child`) does not see it.
- A nested repository (`repo/nested`) is its own key: the outer repository's entry does not apply there.

So `claude_registration` (working-with-fabric `scripts/fabric_session_env.py`) looks up one key, the nearest checkout's
root or the folder itself, and never walks ancestors (`test_a_local_entry_is_keyed_by_the_git_root_or_the_exact_folder`
in `test/test_fabric_session.py`). The project scope's `.mcp.json` walk was not measured here and is unchanged.
