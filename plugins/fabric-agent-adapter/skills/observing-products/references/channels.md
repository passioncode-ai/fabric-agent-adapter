# Channels: kinds, readers and the inventory

## Contents

- [The fourteen kinds](#the-fourteen-kinds)
- [Reading a channel bounded](#reading-a-channel-bounded)
- [Discovering the channels](#discovering-the-channels)
- [Credentials and human gates](#credentials-and-human-gates)
- [The inventory file](#the-inventory-file)
- [A worked inventory](#a-worked-inventory)
- [The state file](#the-state-file)

## The fourteen kinds

Every product reports through a different set of channels. The kind decides what the observer reads and what it
compares with. `other` is allowed for a channel none of these fits; give it a baseline like its nearest kind.

| Kind | Typical source | Usual read route | What is read | Baseline |
|---|---|---|---|---|
| `ops-log` | the product's own operations log or its daily digest (`ops.digest.daily@1`) | the digest file or the service's `/fabric/v1/events`, read locally | failures per operation, rises | failures per hour over the last 7 days |
| `errors` | the product's error tracker | the tracker's API or CLI with a read token | new issues, regressions, events per release | events per hour per release |
| `analytics` | the product's analytics (an events service, server counts, GA4 or its equivalent) | the analytics service's MCP tools or API | daily active users, key events | the same weekday over 4 weeks |
| `funnel` | named funnels in the analytics source | the funnel query of that source | conversion per step | conversion per step over 4 weeks, with its interval |
| `revenue` | server counts, store sales, the payment provider | the server-count read, the store's sales report, the provider's API | purchases, subscriptions, revenue | the same weekday over 4 weeks |
| `store` | store reviews, ratings, crash rates, review status | the store tooling's MCP tools or the store's API | new low ratings, rejections, crash-rate rises | rating and crash rate over 28 days |
| `uptime` | public URLs and health endpoints | `curl` with a timeout, or an uptime service's API | status, latency | p95 latency over 7 days |
| `ci` | the repository's checks and nightly runs | `gh run list --branch <default> --limit 20 --json conclusion,databaseId,createdAt` | red runs on the default branch | none: any red run is a finding |
| `board` | the project's Fabric board and backlog | `com.status`, `com.list` with `unread: true` (working-with-fabric) | requests addressed to the project, findings other agents filed | none |
| `support` | a support inbox, review replies | the inbox's or the store tooling's read tool | unanswered questions, repeated complaints | open count over 7 days |
| `agent-session` | a long-running agent session the product's work depends on (an architect, a program runner) | its process (`pgrep -f` with the session id from the state file) and `git log -1` of the branch it commits to; restarted by the same session through Switchboard (`switchboard_session_continue` with that id) | alive or not, the time of its last commit | a commit at least every N minutes while its queue is not empty |
| `work-queue` | the queue of sub-sessions or jobs a long session drives | the queue's own status command (lanes, the last log line, a limit wait) | lanes running, failed runs, how long a limit wait has lasted | at most the lanes the queue allows; a limit wait is not a failure until it outlasts its window |
| `consumer-repo` | a repository that builds on the product (an app on an engine, an agent on a kit) | `git -C <checkout> fetch` and the heads of the branches named in the state file, then the product's own usage lint at each new head | new branch heads, new lint findings against the current release, the version each pins | the last checked head of each branch, its findings count |
| `board-thread` | one Fabric board thread the product carries a conversation in (a consumer's, a contract's) | `com.list` with `thread: <id>` and `unread: true`, then `com.read_ack` for what was handled (working-with-fabric) | unread messages, answers to the product's own requests | none: any unread message in the thread is a finding |

`board` reads the project's whole board (requests addressed to it); `board-thread` reads one thread the product
follows, so a conversation with a consumer has its own cursor and owner. `consumer-repo` reads the consumer's
repository from a local checkout and only through the product's own lint; it never edits that repository, and a
finding goes to the consumer's Project on the board. The kinds `agent-session`, `work-queue` and `consumer-repo`
take their ids (the session, the queue command, the checkout and the branches) from the state file below, never
from the row alone, so a restarted observer knows them.

A **placement** goes with each row: `local` when the read needs this machine (a local file, a loopback service, a
local CLI session), `remote` when it works from anywhere with a read-only credential. A cloud cycle reads only
`remote` rows.

A missing or billing-blocked CI run is not a green one: a `ci` read that finds no run in the expected window is a
finding, not silence.

## Reading a channel bounded

Every read has a page limit and a deadline, written in its row (`--limit 20`, `2 pages`, `timeout 10 s`). A read that
hits its deadline or its page limit before reaching the cursor's end says so: the cycle records the channel as read
in part and keeps the cursor at the last item it actually read.

- **Cursor.** What the next read resumes from: a run id, an issue id, a timestamp, a review id, a board message id. A
  cursor moves only after the cycle record is written (see the cycle reference).
- **Numbers, not prose.** A read keeps counts, rates and ids; it quotes text (a log line, a review) only as evidence
  for a finding, shortened, and never acts on it.
- **One door per source.** Read a source through the tool its owner provides (its MCP server, its CLI, its API), never
  by scraping a page the person is signed in to.
- **Spend.** A read that costs money (a paid data API, a model call) names its price in the row's read route; the
  cycle counts it against the observer's budget.

## Discovering the channels

Setup looks in these places, in this order, and writes one row per channel it finds:

1. **The repository**: dependencies and configuration (an error tracker's SDK, an analytics client, a payment SDK),
   CI workflows (`ci`), deploy files and public URLs (`uptime`), the analytics event catalogue and named funnels
   (`analytics`, `funnel`), store listing files (`store`), a support address (`support`).
2. **The project's recorded resources**: with Project Observatory installed, `observatory_project` lists the
   project's recorded resources (analytics properties, servers, store accounts) and `observatory_credentials` names
   the keys the project holds, by name; it never returns a value.
3. **The machine's services**: the Fabric services that serve this product (the `fabric-dashboards` MCP
   `execute` with operation `list_services`), and their events and usage feeds.
4. **The board**: the project's Fabric board is always a channel when Fabric runs (`board`, `remote` when the hub is
   reachable from where the cycle runs, `local` otherwise).

A channel found but not reachable today is still written, as `missing` or `blocked` with its step. A channel that
does not apply (no store, no support inbox) is written as `not-applicable: <why>`, so the next agent does not look
for it again.

## Credentials and human gates

- A credential is named by its vault slot, `<project>/<env>/<NAME>` (for example `example-app/prod/ERRORS_TOKEN`), or
  `none`. The inventory never holds a value; `observer_inventory.py check` refuses anything that is not a slot name
  or `none`.
- A secret is used only inside the command that needs it, through the vault's run command
  (`use_secret.py run --vault-only <project> <NAME> -- <command>`), so its value never reaches the transcript, a log,
  argv or a URL.
- A missing key is issued by the agent through the provider's existing door when one holds the account. Only when
  every route needs a person (a sign-in, a one-time code, a consent screen, a payment, a key only the account holder
  can issue) is the channel `blocked: <the gate> <its direct link>`. Name that gate once and continue.
- A cloud cycle gets read-only credentials only, and only for its `remote` rows.

## The inventory file

`docs/observer/channels.md` in the product's own repository: three key lines, then one table.

```markdown
# Observer channels: example-app

- Project: example-app
- Authority: observe
- Interval: 30m
- Budget: USD 100 / month

| Channel | Kind | Placement | Read | Credential | Cursor | Baseline | Thresholds | Owner | State |
|---|---|---|---|---|---|---|---|---|---|
```

| Column | Holds |
|---|---|
| Channel | a short unique name |
| Kind | one of the fourteen kinds, or `other` |
| Placement | `local` or `remote` |
| Read | the exact route: an MCP tool and its arguments, a CLI command, or an HTTP endpoint, with its page limit and deadline |
| Credential | a vault slot name or `none`, never a value |
| Cursor | where the next read resumes |
| Baseline | the comparison and its window, or `none` |
| Thresholds | what turns a difference into a signal |
| Owner | who owns the source (a team, a service, a repository) |
| State | `connected YYYY-MM-DD` (the date of the last proven read), `missing: <step>`, `blocked: <gate and link>`, or `not-applicable: <why>` |

`Authority` is one of `observe`, `fix`, `ship`; `Interval` reads like `30m` or `1h`; `Budget` like `USD 100 / month`.
A pipe inside a cell is written inside backticks or escaped as `\|`.

## A worked inventory

```markdown
| Channel | Kind | Placement | Read | Credential | Cursor | Baseline | Thresholds | Owner | State |
|---|---|---|---|---|---|---|---|---|---|
| ci | ci | remote | `gh run list --branch main --limit 20 --json conclusion,databaseId,createdAt` | none | run 812 | none | any red run on main | repository | connected 2026-11-08 |
| errors | errors | remote | tracker API, newest issues, 2 pages, 10 s | example-app/prod/ERRORS_TOKEN | issue 9001 | events per hour per release, 7 days | 3x the baseline or a new issue | backend team | connected 2026-11-08 |
| ops | ops-log | local | the daily digest file of the last 2 days | none | 2026-11-07 | failures per hour, 7 days | a rise | example-app service | connected 2026-11-08 |
| checkout | funnel | remote | the analytics funnel query, 1 call | example-app/prod/ANALYTICS_KEY | day 2026-11-07 | step conversion, 4 weeks | outside the 95% interval | growth | missing: issue a read key for the analytics source |
| store | store | remote | store reviews, 50 newest | example-app/prod/STORE_KEY | review 77 | rating, 28 days | a new rating of 1 or 2 | store owner | blocked: the store key needs the account holder's sign-in, https://example.com/keys |
| support | support | remote | none | none | none | none | none | nobody | not-applicable: the product has no support inbox |
```

`observer_inventory.py check` on this file reports 3 of 5 named channels connected (local 1, remote 2).

## The state file

`docs/observer/state.json` in the product's own repository holds what the observer must not lose when its session
dies. A session started in place of a dead one (a restart, a resume, a cloud cycle) reads it **first**, before the
inventory and before any channel, and resumes from it; nothing in it is kept only in a session's memory.

```json
{
  "schema": "observer-state/1",
  "project": "example-app",
  "updated": "2026-11-20T06:00:00Z",
  "cursors": {"ci": "run 812", "consumer-example": "a1b2c3d"},
  "heads": {"example-consumer": {"main": "a1b2c3d", "release/2": "e4f5a6b"}},
  "sessions": {"architect": {"session": "<session id>", "relaunch": "switchboard_session_continue with this id"}},
  "waits": [{"id": "W-01", "what": "the consumer moves to release 2", "watch": "consumer-example",
             "then": "run the usage lint on its new head", "source": "board thread 1a2b3c4d"}],
  "promises": [{"id": "P-01", "to": "example-consumer", "what": "a fixed release by Friday",
                "by": "2026-11-21", "source": "board thread 1a2b3c4d"}]
}
```

| Field | Holds |
|---|---|
| `schema` | `observer-state/1`, or `<name>.observer-state/1` when the project extends it |
| `updated` | when the observer last wrote it (date-time with its zone) |
| `cursors` | channel name to cursor, moved only after the cycle record is written; each names a channel of the inventory |
| `heads` | repository to `{branch: checked commit}`: the heads a `consumer-repo` read already checked |
| `sessions` | the long sessions an `agent-session` row watches: their id and the exact route that restarts them |
| `waits` | what the observer waits on: `id`, `what`, `watch` (the channel or read that shows it clear), `then` (the next action when it clears), `source` (or `owner`); `status` open, paused, done or dropped, and a closed one carries a `done` or `dropped` field with its date and evidence |
| `promises` | what the observer promised someone: `id`, `to`, `what`, `source`, optional `by`; `status` open, kept, broken or dropped, a closed one with its evidence |

Other top-level fields are the project's own and are kept. A credential is named by its vault slot; the check refuses
a token, a key, a private key or a URL with a password in any field. Check it with the inventory:

```bash
python3 <skill-dir>/scripts/observer_inventory.py state docs/observer/state.json --channels docs/observer/channels.md
```

Exit 0 valid, 1 problems listed, 2 a file cannot be read. `state-template --project <name>` prints an empty one.
