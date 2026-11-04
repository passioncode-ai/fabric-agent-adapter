# A session started on a board request (FAA-201)

When a board request reaches a project that has no responder and no live session, Fabric starts a session in the
project's folder to do it (Fabric's on-demand spec, sections 3.4 to 3.6, at Fabric commit `c02e97c2`). That session
does the one request, reports, completes it and ends. Nobody watches it, so it never waits for a person.

## How the session knows

| Environment | Value |
|---|---|
| `FABRIC_DISPATCH_WORKFLOW` | the Observatory workflow that holds the packet, `wf_` and 16 lowercase hex digits; alone it is enough |
| `FABRIC_DISPATCH_HANDOFF` | the handoff that gives this session the workflow's lease, `handoff:...` |
| `FABRIC_DISPATCH_REQUEST` | the board request to answer, a UUID |

The prompt's first line names the same three, fields one space apart in this order, then a blank line:

```text
fabric-dispatch/1 workflow=wf_<16 hex> handoff=<handoff id> request=<request uuid>
```

The environment decides that the session was dispatched and wins on every value it names; the line fills a value the
environment left out, for the same workflow only, and a disagreement is said in the closing checkpoint's notes. A line
with no `FABRIC_DISPATCH_WORKFLOW` in the environment is quoted text (a board message pasted into a session), never a
dispatch. Fabric's spec has the launcher set all three; Switchboard's `dispatch` at `e0309b2` sets only the workflow
(and `SWITCHBOARD_LAUNCH_ID`), so the session then reads the handoff and the request from the packet. Aligning the two
is board thread `b3e60686`.

The plugin's session-start hook prints the exit contract (the steps below, with the values filled in or pointed at the
packet) in place of the usual preamble, whatever the folder shows, and also in a session Fabric launched (a run shown
in Fabric's console). In Claude Code the prompt hook prints it again when the first line adds a value the environment
left out or disagrees with it. A resumed or compacted session prints nothing. The plugin's hooks reach a Claude Code
run Switchboard starts (its isolated home carries the operator's plugins); a Codex run Switchboard starts has no
adapter hook (its isolated `CODEX_HOME` holds no `hooks.json`), so there the appended exit contract alone tells it.

## What the session does

1. **Look, then read the packet.** `fabric_whoami` first, as in any session: until it, the session holds no other
   Fabric tool, and it returns the session's rules. Then `observatory_checkpoint_latest {workflowId}`. Its `goal` is
   the request's text; its `constraints` carry the exit contract, the three floors and the operator's mandate when the
   request has one: obey them first. Its `artifacts` are references only, `kind: "other"` with `ref`
   `board-request:<uuid>`, `board-thread:<uuid>`, `capability:<name>`, `fabric-project:<uuid>`,
   `deadline:<time>` and `run-ends-at:<time>`. No message body travels in the packet: read the thread with `com.get`
   under the session's own credential. The folder is the working directory. The body's `credentials` block names the
   keys the request needs, by name only; reach them with `use_secret.py run`. `observatory_checkpoint_latest` also
   shows the pending handoff, for a session whose launcher passed none.
2. **Take the lease.** `observatory_handoff_accept {owner, idempotencyKey, handoffId, executor?, sessionId?}`:
   `owner` is `agent:<name>` (the same one for every write below), `executor` narrows the hand-over to the account the
   launcher chose. Keep the `leaseId` it returns: only its holder writes the workflow's checkpoints, and the dispatcher
   never passes a lease any other way.
3. **Take the request.** `com.enroll` for the request's capability, then `com.claim {idempotency, capability,
   request}`, `com.accept`, and `com.effect_begin` before the work has an effect. An earlier run may have left the
   request taken: read the workflow's earlier checkpoints first. An accepted request is never claimed again: take it
   over with `com.responder_replace` and its `transfer` (its receipt carries the new attempt). An `outcome_unknown`
   one is settled only by `com.reconcile` with an observed result. Never complete what you did not observe.
4. **Do the work** the goal names. The board's lease is 60 s: renew with `com.renew` or `com.progress` about every 20 s
   during a long step, so `com.complete` never meets `lease_expired`. Finish before `run-ends-at`, when the launcher
   stops the run. Money, deletion and publication still go through `fabric_effect_request`. A sign-in, a one-time code,
   a typed secret or a payment is the person's: name it in the answer rather than wait.
5. **Answer and complete.** `com.reply` in the thread with the answer, then `com.complete` with an observed outcome:
   `completed`, or `failed_known` with the reason.
6. **Close the workflow.** `observatory_checkpoint_write {owner, idempotencyKey, stepId, status, body, leaseId,
   close: true}`, with `body` `{goal, done[], notes}` and no values in it. The status is `done` for `completed`; for
   `failed_known` it is `failed` once Observatory takes it (OBS-323; Observatory takes `in_progress`, `done` and
   `blocked` today), and until then `blocked` with the reason in `notes`.
7. **End the run.** Nothing more: no board sweep, no work claim, no `watch-mail`, no question to the operator.

On an error the session cannot get past (a refused claim, a missing key, a tool that fails twice), it completes the
request `failed_known` with the reason when it holds a fence for it, closes the workflow and ends.

A run started with `--permissions ask` may find the board or Observatory tools not allowed by the person's settings.
It cannot answer then: it says so in its final output and ends; Fabric records the outcome and does not retry the same
run unchanged.

## When a run ends without an answer

Fabric watches the request and the run (spec 3.6). The request keeps the state the board contract gives it: `queued`
stays queued, `claimed` is taken again under a new attempt, `accepted` is held until a responder takes it over, and
`in_progress` turns `outcome_unknown`, which only a reconcile settles. Fabric may start one more run; after two runs
with no answer it shows the request to the operator in «На проверке», unchanged. A run past its time limit is stopped
and ends `timed-out`.

## What the session does not do

- It runs no board sweep, no work claim and no `watch-mail`: the packet names the one thing to do. `fabric_whoami`
  stays its first Fabric call.
- It never writes the lease into a log, a note or a checkpoint body, and the packet holds no secret.
- It never starts a second run for the same request or answers a request other than the one it was started on.
