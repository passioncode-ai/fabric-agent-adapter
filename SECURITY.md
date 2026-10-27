# Security

Report vulnerabilities privately to contact@passioncode.ai. Do not open a public issue
containing credentials, private provider URLs, or customer project data.

The adapter must not write secret values to manifests, fixtures, probes, logs, or command
arguments. Generated and external provider outputs are untrusted. Live probes must be
bounded and non-publishing until explicit scoped grants exist in a project binding.


## What the installers and scripts touch

- `npx @passioncode-ai/fabric-agent-adapter` and `install.sh` write only
  `~/.agents/skills/<skill>` (and, while replacing a copy with `--force`, the sibling folders
  `.<skill>.installing-*` and `.<skill>.replaced-*`, removed when the run ends; a killed run can
  leave one behind); `--target claude` writes `~/.claude/skills/<skill>` and is
  refused while the plugin is installed; `--prune-shadow` moves shadowing copies into
  `~/.claude/skills-shadow-backup/`.
- `building-fabric-services/scripts/check_service.py` reads a descriptor and the token
  file it names, and redeems one login code it asked for itself (creating one dashboard
  session). It never prints the token. For a local service it talks only to
  `127.0.0.1:<port>`; for a remote placement it talks to the service's own `https` origin
  named in the descriptor (`--ca-file` and `--connect` only change which CA it trusts and
  which address it dials, for tests).
- The service kits create the service token (0600) and the instance lock in the
  service's own data directory, and write supervisor files only when an installer calls
  them: a launchd plist in `~/Library/LaunchAgents` (macOS), a systemd user unit (Linux) or
  a per-user Scheduled Task (Windows), plus one descriptor in the services directory. The
  token is readable by any process of the same user; the protocol defends against web pages
  and mistakes, not against hostile local code.
- The kits' connectors (`fabric_http`, `fabric_openrouter` and their Node twins) reach the
  external APIs the service's author configures, such as OpenRouter, with keys the service
  reads by name at run time; the kit itself calls no outside host on its own. A board
  responder talks only to Fabric's hub on loopback.
- The working-with-fabric session hooks run as the person: Stop and SessionEnd run `git`
  in the session's folder (counts only, at most 1.5 s; with the mark below, also that folder's own `origin`, only to leave its repository out), read the process table to tell a
  session Fabric launched. Stop also, only once the running Fabric's `fabric_session_observe` takes
  `repositories` (FAA-140; a worker sees it in the tool's schema and leaves a mark), reads the
  last 512 KB of the session's transcript (earlier turns included; only the entries after the
  last prompt the person typed are used; the tail holds message text and tool output too, file contents and
  command output that can carry a secret the session displayed, read in memory only and never spooled, logged or sent)
  and runs `git rev-parse --show-toplevel` and `git config --get remote.origin.url` in the
  other repositories the turn's tool calls name, within the same 1.5 s. Of the transcript they
  use only tool names and path arguments; what leaves the machine is each repository's
  host, owner and name, never a local path, a command or message text (on a self-hosted ssh
  remote, `owner` is the folder path on that server before the repository's name). The mark is
  removed only by a worker that sees a schema without the field, so after Fabric is downgraded
  the turns that end before a worker next runs (about a minute) are still read; none of their
  names is sent. They write their spool and log under the user's cache folder (0600),
  and the delivery worker starts `fabric-mcp` in its own process group and ends that group
  (`killpg`, or `taskkill /T /F` on Windows) at its 10 s deadline. They read no Fabric token. An
  `origin` URL that embeds a credential (`https://user:token@host/...`) is read by `git config`
  with it; the credential, the port and `.git` are dropped in memory before anything is spooled,
  logged or sent.
- `adapting-projects-to-fabric/scripts/adapt_project.py` reads the target project without
  executing it and writes only the seven documented bundle paths (`scaffold --dry-run`
  writes nothing); `check --contract` runs the contract checkout's own
  `node_modules/.bin/tsx` and installs nothing. `fabric_provider.py write` writes one
  entry (0600) in the providers directory.
