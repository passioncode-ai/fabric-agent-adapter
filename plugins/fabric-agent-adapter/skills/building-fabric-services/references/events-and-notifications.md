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
  number stated — "AION store listing is ready for your approval (12 fields in 3
  locales)." Never a machine id, never a stack trace.
- `subject`: what it is about (`{type: "app", id: "aion", label: "AION"}`), so a host
  can group.
- `link`: the page that resolves it.

## When to set `notify: true`

Notify when the operator must act (an approval is waiting, a key expired, a job failed
after retries) or asked to be told (a long job finished). Do not notify for routine
progress, retries that will succeed, or anything that fires more than a few times an
hour. The host decides whether to show it — quiet hours, per-service settings — and
debounces; the service decides only what is notification-worthy.

## Lifecycle events every service emits

`service.started` (with the build), `service.stopping`, `service.degraded` and
`service.recovered` when a degraded source appears or clears, `update.available` when
the service learns of a newer release.

## Retention

At least seven days or 1000 events, whichever is more; trim oldest first; a cursor
older than retention returns the oldest retained page, not an error.
