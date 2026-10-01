# Events and notifications

## Map the log you already keep

| Existing log | View |
|---|---|
| a SQL `events`/`jobs` table with an autoincrement id | `SELECT … WHERE id > ? ORDER BY id LIMIT ?`; `id` as string |
| per-job JSONL files | keep one append-only `activity.jsonl` index written beside them, or merge by `(ts, job, seq)` into a composite id `"<ts>-<job>-<seq>"` that still sorts |
| a journal with no id | add a monotonic counter when appending; backfill ids once on migration |
| nothing | `JsonlEventLog` from the kit |

The feed is a view: never copy rows into a second store that can drift from the first.

## Writing an event

- `kind`: dotted, stable, past tense or state (`job.failed`, `job.awaiting_choice`,
  `service.started`, `collector.stale`). Hosts filter on it.
- `level`: `info` (routine), `notice` (the operator may want to look), `warning`
  (something is degrading), `error` (something failed and needs action).
- `text`: one sentence, in the operator's language, with the object named and the
  number stated — "The Q3 report draft is ready for your approval (12 sections, 3
  languages)." Never a machine id, never a stack trace.
- `subject`: what it is about (`{type: "report", id: "q3", label: "Q3 report"}`), so a host
  can group.
- `link`: the page that resolves it.

## When to set `notify: true`

`notify: true` asks the host to interrupt the operator. Hosts treat it as a request, not an
order: Fabric Dashboards shows a banner only for a **decision**, a **failure** or a **warning**,
once per episode, and puts everything else in Activity (its ADR-0010). Write events so that rule
lands on what matters:

| The operator… | Event | `notify` |
|---|---|---|
| must decide or act — a choice, an approval, a key to enter | kind says it: `job.awaiting_choice`, `plan.awaiting_approval`, `human_step.opened`; level `notice` | `true` |
| lost work — a job failed after its retries, a key expired | level `error`; kind `*.failed`, `*.expired` | `true` |
| will lose work soon — a degraded source that blocks orders | level `warning`, `service.degraded`, **once when it starts** | `true` |
| asked to be told when a long job finishes | `job.delivered`, level `notice` | `true` only if that person asked; a host may still keep it in Activity |
| only needs the record — progress, retries, recoveries, syncs | `job.started`, `service.recovered`, `*.cleared`, level `info` or `notice` | `false` |

- **One episode, one request.** Notify on the transition, never on each poll: a source that
  flaps between degraded and healthy sends `service.degraded` with `notify: true` once, and later
  repeats with `notify: false` until it has stayed healthy for a while. Asking the same question
  about the same subject again is not news.
- **Say who wants what.** `subject` names the thing (`{type: "job", id: "…", label: "Q3 report"}`)
  so a host can tell episodes apart and group; `text` names the object and what the operator
  should do ("The storyboard of the Q3 launch video waits for your decision."); `link` opens the
  page where they do it. The host adds the agent's name and instance.
- **One channel.** A service with a descriptor raises no banners of its own (AppleScript
  `display notification`, a notifier binary, its own notification-centre entries): the operator
  would get each one twice, from a sender that is not the host. Publish the event; the host
  delivers it, honouring quiet hours and per-service settings.
- Anything that would fire more than a few times an hour is not a notification.

## Lifecycle events every service emits

`service.started` (with the build), `service.stopping`, `service.degraded` and
`service.recovered` when a degraded source appears or clears, `update.available` when
the service learns of a newer release.

## Retention

At least seven days or 1000 events, whichever is more; trim oldest first; a cursor
older than retention returns the oldest retained page, not an error.
