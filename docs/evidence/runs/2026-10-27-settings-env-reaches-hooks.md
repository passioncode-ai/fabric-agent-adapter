# A Claude Code settings `env` value reaches settings and plugin hooks on macOS (2026-10-27)

What it proves: on macOS, `FABRIC_SESSION_NO_REPOSITORIES` set in Claude Code's settings `env` is in the environment
of hooks declared in a settings file and of hooks a plugin declares in its `hooks/hooks.json`, as this plugin's Stop
hook is, so it is a lasting way to turn off the Stop hook's transcript read there (FAA-160,
`plugins/fabric-agent-adapter/skills/working-with-fabric/references/session-hooks.md`). Found by the 0.56.0 product
reading 5.

Client: Claude Code 2.1.299 (`claude --version`), macOS. The variable was unset in the shell that started it. Two runs:
hooks declared in a settings file, then hooks declared by a plugin loaded with `--plugin-dir` (0.56.0 product reading
9). Not measured on Windows: a Windows run (Git Bash and PowerShell) is part of FAA-183.

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

Second run, a plugin's hooks. Plugin folder `<dir>/plug` with `.claude-plugin/plugin.json`
(`{"name": "env-probe", "version": "0.0.1", ...}`) and `hooks/hooks.json`:

```json
{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "printf 'plugin-stop:%s\\n' \"$FABRIC_SESSION_NO_REPOSITORIES\" >> <dir>/seen.txt"}]}],
           "SessionStart": [{"hooks": [{"type": "command", "command": "printf 'plugin-start:%s\\n' \"$FABRIC_SESSION_NO_REPOSITORIES\" >> <dir>/seen.txt"}]}]}}
```

The settings file holds only `{"env": {"FABRIC_SESSION_NO_REPOSITORIES": "1"}}`.

```
$ env -u FABRIC_SESSION_NO_REPOSITORIES claude -p --settings <dir>/settings.json --plugin-dir <dir>/plug --strict-mcp-config --model haiku "Answer with the single word ok."
ok
$ cat <dir>/seen.txt
plugin-start:1
plugin-stop:1
```

`fabric_session.py status` reads the environment of the shell it runs in, not the one Claude Code gives its hooks.
