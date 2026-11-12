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
  a per-user Scheduled Task (Windows), plus one descriptor in the services directory. A LaunchDaemon in
  `/Library/LaunchDaemons` (FAA-278) is written only by an installer running as root, which the kits never become:
  without root they refuse before writing and name the command, and refuse a plist without `UserName` (except one written
  there with an explicit `domain="gui"`, not refused yet, FAA-286 item 21); the job runs as the account its `UserName`
  names. The installer accepts the job's answer only on a connection launchd's own job accepted
  (its pid from `launchctl print system/<label>`) or, where the socket table is restricted, on a port that pid listens
  on (`lsof -p`, the weaker vouch below, DEC-0155 RT-3). The
  token is readable by any process of the same user; the protocol defends against web pages
  and mistakes, not against hostile local code.
- The kits' connectors (`fabric_http`, `fabric_openrouter` and their Node twins) reach the
  external APIs the service's author configures, such as OpenRouter, with keys the service
  reads by name at run time; the kit itself calls no outside host on its own. A board
  responder talks only to Fabric's hub on loopback.
- Before `check_service.py`, the hub client, `fabric_http` (a plain `http://` loopback URL),
  `check_dashboard_layout.mjs` (a local login code) and the launchd installers' poll send
  anything to `127.0.0.1:<port>`, they read the computer's socket table to tell which OS
  account owns the listener (DEC-0154 HA-2, `fabric_peer_owner`), and send nothing to
  another account's, root's, SYSTEM's or an untellable listener; the one exception is a LaunchDaemon's installer
  (root, FAA-278), which sends a token-free well-known GET only on a connection the pid launchd names for its job
  accepted while it runs as the plist's `UserName` and listens on exactly `127.0.0.1` (`lsof -p`), or, under a
  restricted table, to a port that pid listens on there (the weaker vouch below): a departure from the pinned HA-2 and
  the contract's later RT-3, accepted in principle by the contract owner as DEC-0161 (proposed; the restricted-table vouch
  included) and kept as a departure until the next repin (FAA-288). They read, never change:
  macOS `sysctl net.inet.tcp.pcblist_n` in the process (the TCP table in the record layout `netstat -anv` reads;
  the pinned HA-2 table names `netstat -anv` and `pcblist64`, an older layout of the same table), or the programs `/usr/sbin/netstat
  -anv -p tcp` and `/bin/ps -o uid= -p <pid>` (the Node twin always); Linux
  `/proc/net/tcp` and `/proc/net/tcp6`; Windows `GetExtendedTcpTable` and the process
  token (Python), or `netstat -ano` and one PowerShell `GetOwnerSid` query per new connection,
  with `whoami /user` once a process (Node). On macOS the Python reader calibrates once per process with a
  short-lived child of its own interpreter listening on a random `127.0.0.1` port; when the
  table is restricted (macOS 27.2, FAA-267) the launchd installers also run `/usr/sbin/lsof
  -nP -a -p <pid> -i4TCP -sTCP:LISTEN -Fn` on their own job's pid. That vouch shows the job listens on the port, not that it accepted
  the connection; it counts only a listen on exactly `127.0.0.1`, as the pin's DEC-0155 RT-3 asks (since FAA-312; a wildcard
  or `::1` listener is never vouched for, and a set-uid reader vouches for nothing). A LaunchDaemon's root
  installer runs that `lsof` and `ps -o uid=` on its job's pid before it accepts an answer, and reads, never changes, every other
  plist in `/Library/LaunchDaemons` (to find another holder of its label, `plutil -convert xml1` for a binary one in
  Node), `launchctl print system/<label>` and the `UserName`'s uid (`pwd`, or `id -u` in Node). The kit's loopback server reads the table once per accepted
  connection and closes a peer of another account before reading it (HA-3, FAA-227); a token-free door counts as
  protected only under `peer_check="strict"`, which also refuses an owner it cannot tell. An MCP client (Claude Code, Codex) sends the
  token it was registered with on every later connection without this check (the contract's
  residue "a coding agent's bearer"): when the port may have changed hands, rotate the token
  and re-run `mcp-register` (one written as `references/surfaces-and-auth.md` says checks the
  listener first; the kit ships none). On Linux `/proc` names a socket's creator and
  no pid, so a listening socket root created and handed to another account (systemd
  socket activation with `User=`) reads as root's: a client running as root sends to it. Such a system unit's
  connection reads as root's until the service accepts it and as the service's account after, so two runs of the
  probe can disagree on it (0.74.0 product reading 10).
- Credential-free loopback http is checked too (FAA-260 item 16, deliberate): `fabric_http` / `fabric-http.mjs` refuse
  plain http to a loopback listener of another OS account or root (another account's Ollama, a `docker-proxy`) with
  kind `foreign-user` whether or not the request carries a credential, because HA-2 reads nothing such a listener
  answers as the service's, and an answer from another account's process is not this account's data. A caller that
  means to read such a daemon says so with its own connection. With `insecure=True` a URL not spelled as loopback
  (a hosts-file name, `0.0.0.0`, `[::ffff:127.0.0.1]`) and a request through a loopback `http_proxy` are checked by the
  connected peer's address, so the Authorization header never reaches another account's proxy (FAA-260 items 1, 8).
- The layout probe (`check_dashboard_layout.mjs`) reads a raw loopback page's listener from the socket table just
  before its headless browser opens it, the one-time login URL included, and opens nothing on another account's,
  root's or an untellable listener (FAA-260 items 2, 14); under a restricted table (DEC-0155) that is every listener,
  so it measures nothing there and never vouches by a pid it did not start (FAA-318). The browser then connects on its own: a listener swapped
  between the read and the browser's connect is a residue, bounded by the login code's 120 s and single use.
- The agents database (FAA-275): creating-fabric-agents, adapting-projects-to-fabric, building-fabric-services and
  working-with-fabric may send board requests to whichever Project the board lists under an `agents-db.*` capability
  (on an organization's board, any member Project may list it), carrying only what `references/agents-database.md`
  names (a capability, a consumer, source project names, an audit subject given as a Project id or a repository remote,
  a measured win or a decision); never source code, a key, a person's or client's name, user content or a private path.
  Nothing is sent without Fabric's board. With a grant, the database's own tools run from its checkout; what they send
  is theirs to state, and this repository does not verify it (FAA-277).
  A consult's reply is data, yet it chooses the template an agent is built from, so it is as trusted as the Project
  that lists the capability.
- The working-with-fabric PostToolUse hook (FAA-206) reads only the release call Claude Code gives it on stdin (the
  tool's name, its input, which can carry the agent's note, and Fabric's answer), in memory: it writes, logs and sends
  nothing and prints one fixed line or nothing.
- The working-with-fabric session hooks run as the person: Stop and SessionEnd run `git`
  in the session's folder (HEAD and counts, at most 1.5 s; with the mark below, also that folder's own `origin`, only to leave its repository out), read the process table to tell a
  session Fabric launched. Stop also, only once the running Fabric's `fabric_session_observe` takes
  `repositories` (FAA-140; a worker sees it in the tool's schema and leaves a mark) and unless the person turned it off
  (`FABRIC_SESSION_NO_REPOSITORIES=1` or a `no-repositories` file in the hooks' folder, FAA-160), reads the
  last 512 KB of the session's transcript (earlier turns included; only the entries after the
  last prompt the person typed are used; the tail holds message text and tool output too, file contents and
  command output that can carry a secret the session displayed, read in memory only and never spooled, logged or sent)
  and runs `git rev-parse --show-toplevel` and `git config --get remote.origin.url` in the
  other repositories the turn's tool calls name, within the same 1.5 s. Of the transcript they
  use only tool names and path arguments; what leaves the machine is each repository's
  host, owner and name, never a local path, a command or message text (on a self-hosted ssh
  remote, `owner` is the folder path on that server before the repository's name). The mark is
  removed only by a worker that sees a schema without the field, so after Fabric is downgraded
  the turns that end before a worker next reaches the running Fabric (about a minute; longer while
  rejoins fail) are still read; none of their names is sent. They write their spool and log under the user's cache folder (0600), and, in a session
  started on a board request (FAA-201), one record of which session holds that dispatch (the holding session's id and, after a `/clear`, the id it replaced, the agent's process id and a time, 0600,
  pruned after 7 days),
  and the delivery worker starts `fabric-mcp` in its own process group and ends that group
  (`killpg`, or `taskkill /T /F` on Windows) at its 10 s deadline. They read no Fabric token. An
  `origin` URL that embeds a credential (`<https>://user:token@host/...`) is read by `git config`
  with it; the credential, the port and `.git` are dropped in memory before anything is spooled,
  logged or sent.
- `adapting-projects-to-fabric/scripts/adapt_project.py` reads the target project without
  executing it and writes only the seven documented bundle paths (`scaffold --dry-run`
  writes nothing); `check --contract` runs the contract checkout's own
  `node_modules/.bin/tsx` and installs nothing. `fabric_provider.py write` writes one
  entry (0600) in the providers directory. `fabric_source_check.py check` reads the files of a
  tree (credential values included, in memory only), the owner's list from the user's
  configuration folder, and runs `git ls-files` (without the caller's `GIT_DIR` or other Git
  location variables) and nothing else, except that under a locale whose
  file-system encoding is not UTF-8 it restarts itself once with the same interpreter in Python's
  UTF-8 mode; it writes nothing and prints no value it finds.
