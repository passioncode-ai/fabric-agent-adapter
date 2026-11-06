# Machine move, several macOS users, tokens: the adapter's gaps (2026-11-06)

The operator's instruction relayed by Observatory on board thread `1fe66e6e` (2026-11-05, session `456ad510`): read
Workspace's plan for moving to another machine and joining an organization, compare it with the code, write a spec per
gap, file backlog rows and close them in waves. Workspace's plan names the adapter twice
(fabric-workspace `knowledge/plans.md`: "How an agent gets its own machine, in creating-fabric-agents";
`docs/plans/2026-11-04-studio-spaces/placement.md`: the adapter's development sessions and full gates move to the
Studio). Workspace asked for the recipe on the board (`8dd7740c`, 2026-11-05): the port by the contract's norm, refusal
to start when `project-observatory/placement.json` names another machine, keys only from the user's own vault.

The contract's norm in draft (board `14b4dc86`, `db8090d1`, `d6035cae`; decision due 2026-11-07): a service records the
port it listens on per OS account (its own state and its descriptor's `origin`), the installer chooses it free on the
host, a client takes it only from the descriptor; before a credential goes to `127.0.0.1` the client checks the
listener's uid, else `foreign-user` and nothing is sent; a listener SHOULD refuse a peer of another account.

## Gaps, current behaviour with file:line, what is needed, acceptance

G1. **Port choice** (FAA-225). `fabric_descriptor.write_descriptor` refuses a port another descriptor of the same
account declares (`building-fabric-services/scripts/fabric_descriptor.py:495-506`) and nothing else: a port another
account listens on or claims, or any listener on the host, passes. Needed: the installer picks a port free on the host
(not listening, not declared by this account, not claimed by another account in the contract's sticky claim folder) and
writes the claim; a single-account host keeps its historical port. Acceptance: a test with a listening socket and a
foreign claim refuses both; the contract's vectors pass. Waits on the contract's decision.

G2. **Listener's uid before a token** (FAA-226). `check_service.py` sends the descriptor's token to
`127.0.0.1:<port>` with no check of who listens (`check_service.py:150-162`); the kit's other loopback clients the same.
Needed: before any credential, the listener's uid is this account's (macOS: `sysctl net.inet.tcp.pcblist64` or
`netstat -anv`, Linux: `/proc/net/tcp`, Windows: `GetExtendedTcpTable` and the owner's SID); otherwise state
`foreign-user`, nothing sent; an owner that cannot be told is a refusal. "Healthy" is only said of this account's
listener. Acceptance: a test with a listener of another uid (a stand-in reader of the socket table) gets no token and
reads `foreign-user`; an empty port stays `down`.

G3. **The hub client** (FAA-226, same row). `fabric_hub.py` trusts the hub by a live `pid` in `hub.json` alone
(`fabric_hub.py:10`, `:24`) and sends the binding credential. Needed: the same uid check on the hub's listener.

G4. **A listener refuses another account's peer** (FAA-227). Kit services (`LoopbackHTTPServer`,
`fabric_descriptor.py:85-97`) serve any loopback peer; their tokens are the only guard. Needed (SHOULD in the draft):
close a connection whose peer belongs to another uid before reading the request. Acceptance: a server test like
Switchboard's SB-273.

G5. **Services before the user logs in** (FAA-228). The kit's launchd installer uses the `gui/<uid>` domain
(`fabric_supervisors.py:300`), so a service starts only when its user's session opens; on the Studio FileVault is opened
by the operator and there is no auto-login (Workspace, board `b91c09eb`). Needed: follow the contract's rule for
services without an open session (its G8, a CT row after the port decision). Waits on the contract.

G6. **Fabric.app's place for a second user** (FAA-229). `fabric_session_env.fabric_bin_candidates` looks in
`/Applications` before `~/Applications` (`working-with-fabric/scripts/fabric_session_env.py:170-171`), so a second macOS
user on the Studio is pointed at another user's `fabric-mcp`. Needed: the launcher's rule (`lib/catalog.js` `appPath`
after its PR #277): `~/Applications` first, `/Applications` only when that copy is this user's. Acceptance: a test with
both copies picks the user's own.

G7. **The recipe in creating-fabric-agents** (FAA-230): how an agent gets its own machine: the port by the contract's
norm (until then `base + uid - 501`, Workspace's `placement.md`); refuse to start when
`project-observatory/placement.json` names another machine; keys only from the user's own vault, never copied between
vaults. Release after the contract's port decision (Workspace's date).

## Already met

- Token files on POSIX: `fabric_auth.read_token` refuses a symlink, a file of another uid and one others can read
  (`fabric_auth.py:71-90`); on Windows the ACL rule (DEC-0032). The contract's G4 holds for the kit.
- Descriptors are written 0600 in the account's own services folder (`fabric_descriptor.py:509`).

## Order

Wave 1 (no decision needed): G6. Wave 2 (after the contract's port decision, 2026-11-07): G2 with G3, G1, G7. Wave 3:
G4, then G5 after the contract's G8 row.
