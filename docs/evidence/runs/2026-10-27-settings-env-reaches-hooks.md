# A Claude Code settings `env` value reaches the hooks (2026-10-27)

What it proves: `FABRIC_SESSION_NO_REPOSITORIES` set in Claude Code's settings `env` is in the environment of the
hooks Claude Code runs, so it is a lasting way to turn off the Stop hook's transcript read (FAA-160,
`plugins/fabric-agent-adapter/skills/working-with-fabric/references/session-hooks.md`). Found by the 0.56.0 product
reading 5.

Client: Claude Code 2.1.299 (`claude --version`), macOS. The variable was unset in the shell that started it.

Settings file (a temporary folder; `<dir>` is that folder):

```json
{"env": {"FABRIC_SESSION_NO_REPOSITORIES": "1"},
 "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "printf 'stop:%s\\n' \"$FABRIC_SESSION_NO_REPOSITORIES\" >> <dir>/seen.txt"}]}],
           "SessionStart": [{"hooks": [{"type": "command", "command": "printf 'start:%s\\n' \"$FABRIC_SESSION_NO_REPOSITORIES\" >> <dir>/seen.txt"}]}]}}
```

Command and output:

```
$ env -u FABRIC_SESSION_NO_REPOSITORIES claude -p --settings <dir>/settings.json --strict-mcp-config --model haiku "Answer with the single word ok."
ok
$ cat <dir>/seen.txt
start:1
stop:1
```

`fabric_session.py status` reads the environment of the shell it runs in, not the one Claude Code gives its hooks.
