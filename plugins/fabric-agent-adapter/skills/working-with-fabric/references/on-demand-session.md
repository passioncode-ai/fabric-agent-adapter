# A session started on a board request (FAA-201)

When a board request reaches a project that has no responder and no live session, Fabric starts a session in the
project's folder to do it (Fabric's on-demand spec, sections 3.4 to 3.6, at Fabric commit `1329b60f`). That session
does the one request, reports, completes it and ends. Nobody watches it, so it never waits for a person. The
dispatcher is in no Fabric release yet (its wave 1 is off by default); the hooks recognise a dispatched session from
adapter 0.63.0 on, so a launcher can start one today.

## Contents

- How the session knows
- What the session does
- When a run ends without an answer
- A session inside the run
- What the session does not do

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
dispatch. Switchboard's `dispatch` sets all three and writes the line (SB-247, with
`FABRIC_DISPATCH_ID`, since Switchboard 0.7.8 of 2026-11-04; board thread `b3e60686`). With a launcher that sets the workflow alone, the session reads the handoff
from the packet and the request from the launcher's prompt; when neither names the request, it closes the workflow
`blocked` saying so and ends (Observatory's write redacts the packet's board references, below).

The plugin's session-start hook prints the exit contract (the steps below, with the values filled in or pointed at the
packet) in place of the usual preamble, whatever the folder shows, and also in a session Fabric launched (a run shown
in Fabric's console). In Claude Code the prompt hook prints it again when the first line adds a value the environment
left out or disagrees with it. A resumed or compacted session prints nothing. The plugin's hooks reach a Claude Code
run Switchboard starts (its isolated home carries the operator's plugins). A Codex run gets the adapter's hook only when
the person installed it with `install-host-hooks` and that run's `CODEX_HOME` trusts it: Codex runs a `hooks.json` hook
only when the home's own `config.toml` trusts it (measured with codex-cli 0.165.0). Switchboard links the person's
`hooks.json` into its isolated homes, and since 0.7.8 carries the person's trust in that
file into the home's `config.toml`, never a hook changed after it was trusted. Where the person has not trusted the
hook, or a Switchboard before 0.7.8 started the run, the launcher's appended exit contract alone tells a Codex run.

## What the session does

1. **Look, then read the packet.** `fabric_whoami` first, as in any session: until it, the session holds no other
   Fabric tool, and it returns the session's rules. Then `observatory_checkpoint_latest {workflowId}`. Its `goal`
   describes the request (its text is on the board); its `constraints` carry the exit contract, the three floors and
   the operator's mandate when the request has one: obey them first. Its `artifacts` are references only,
   `kind: "other"` with `ref` `board-request:<uuid>`, `board-thread:<uuid>`, `capability:<name>`,
   `fabric-project:<uuid>`, `deadline:<time>` and `run-ends-at:<time>`; Observatory's write redacts the three board
   ones (and a UUID in `goal`) today, so take the request from the environment or the first line, never from the
   packet. No message body travels in the packet: read the request with `com.get {message: <request>}` (a request's id
   is its message's) and its thread with `com.list {thread: <thread>}`, the `thread` `com.get` answered, under the
   session's own credential. The folder is the working directory. The body's `credentials` block names the
   keys the request needs, by name only; reach them with `use_secret.py run`. `observatory_checkpoint_latest` also
   shows the pending handoff, for a session whose launcher passed none.
2. **Take the lease.** `observatory_handoff_accept {owner, idempotencyKey, handoffId, executor?, sessionId?}`:
   pass this session's own `sessionId` (the same one on a retry); `owner` is `agent:<name>` (the same one for every write below); `executor` narrows the hand-over to the account the
   launcher chose: pass the `{provider, accountRef}` the launcher's prompt names, or leave it out when it names none.
   Reading the packet before the accept, as step 1 does, is harmless; a launcher's prompt that asks for the accept
   first is followed just as well, as long as `fabric_whoami` stays the first Fabric call. Keep the `leaseId` it returns: only its holder writes the workflow's checkpoints, and the dispatcher
   never passes a lease any other way.
3. **Take the request.** `com.status` once, for the epoch every idempotency key names and the slot's generation.
   `com.enroll` for the request's capability, then `com.claim {idempotency, capability, request}`, `com.accept`, and
   `com.effect_begin` before the work has an effect. An earlier run may have left the request taken: `com.get` on the
   request shows its state, and the latest checkpoint (step 1) what that run recorded. An accepted request is never
   claimed again: take it over with `com.responder_replace {expectedGeneration, transfer}` (its receipt carries the new
   attempt). An `outcome_unknown` one is settled only by `com.reconcile` with an observed result. Never complete what
   you did not observe. After the lease, after the claim or the takeover, and after the reply, write an `in_progress`
   checkpoint (`workflowId`, `leaseId`), so a later run has something to read. Observatory keeps only the latest
   body, so every checkpoint the session writes repeats `goal`, `constraints`, `artifacts` and `credentials` of
   `checkpoint.body` (from `observatory_checkpoint_latest`, or the accept answer's `checkpoint`) unchanged and adds `open`, `done` or `notes`, never a value: a body of `done` and `notes` alone would
   leave the next run a packet with no request and no constraints. Never write back the top-level `credentials` or the
   accept answer's `pack`: they carry each key's `state` and `use`, and Observatory refuses them in a body.
4. **Do the work** the goal names. The board's lease is 60 s: renew with `com.renew` or `com.progress` about every 20 s
   during a long step, so `com.complete` never meets `lease_expired`. Finish before `run-ends-at`, when the launcher
   stops the run. Work that cannot end by then gives its state (what is done, where it lies, what is left), before
   `run-ends-at`, as the note of a `com.progress` on the request's thread (the slot holder's state, DEC-0152 SA-6,
   proposed). Then:
   - when the request's `deadline` (the packet's `deadline:` artifact) is not after `run-ends-at`, the deadline cut the
     run, no run comes after the deadline and the board holds an accepted request past it: `com.complete` `failed_known` saying the
     deadline came first, and steps 6 and 7;
   - otherwise the request is left accepted for the next run: an `in_progress` checkpoint without `close`, steps 5 and
     6 skipped. Fabric's dispatcher starts that run for an accepted request whose holder is gone, which takes it over
     with `com.responder_replace` (step 3), and after two runs with no answer shows it to the operator (Fabric's main
     at `fff4b6d9`, in no release yet; a Fabric before it dispatches no accepted request). The open workflow is Fabric's
     to move, not the run's: after the run ends, and no sooner than 120 s of the executor's silence, Fabric hands it to
     itself (`observatory_handoff_create` with reason `restart`, or `crash` when Switchboard names the run crashed,
     to `service:fabric`), takes the new lease and routes it to the next run; when the request goes to «На проверке» or
     its deadline passes, Fabric closes it `blocked` the same way (Fabric's spec at `c560d97e`, sections 3.4 and 3.6;
     its decision on thread `b3e60686`, 2026-11-04). This run only leaves it open.

   A launcher that stops a run gives no time to answer:
   Switchboard sends SIGTERM and kills it about 5 s later on macOS and Linux, and at once on Windows (`taskkill`). Money, deletion and publication still go through `fabric_effect_request`. A sign-in, a one-time code,
   a typed secret or a payment is the person's: name it in the answer rather than wait.
5. **Answer and complete.** `com.reply` in the thread with the answer, then `com.complete` with an observed outcome:
   `completed`, or `failed_known` with the reason.
6. **Close the workflow.** `observatory_checkpoint_write {workflowId, owner, idempotencyKey, stepId, status, body,
   leaseId, close: true}`, with the packet's body and `done[]` and `notes` added, no values in it. Without `workflowId` Observatory
   reads the write as the start of a new workflow and refuses it. The status is `done` for `completed`; for
   `failed_known` it is `failed` once Observatory takes it (OBS-323; Observatory takes `in_progress`, `done` and
   `blocked` today), and until then `blocked` with the reason in `notes`.
7. **End the run.** The one write left is the retro Fabric's `fabric_whoami` asks for after work
   (`observatory_lesson` and insight/1 lines, or one line that there is nothing; no values; ADR-0188's
   `retro-after-work`); nothing more: no board sweep, no work claim, no
   `watch-mail`, no question to the operator.

On an error the session cannot get past (a refused claim, a missing key, a tool that fails twice), it completes the
request `failed_known` with the reason when it holds a fence for it, closes the workflow and ends.

A run started with `--permissions ask` may find the board or Observatory tools not allowed by the person's settings.
It cannot answer then: it says so in its final output and ends; Fabric records the outcome and does not retry the same
run unchanged.

## When a run ends without an answer

Fabric watches the request and the run (spec 3.6). The request keeps the state the board contract gives it: `queued`
stays queued, `claimed` is taken again under a new attempt, `accepted` is held until a responder takes it over, and
`in_progress` stays until the next holder registers, when the board records the lost result; an `outcome_unknown`
attempt is settled only by `com.reconcile` with an observed result. Fabric may start one more run for a request
still queued, claimed with a lapsed lease, or accepted or in progress with no live holder (an accepted one since its
main at `fff4b6d9`); after two runs with no answer it shows the request to the operator in «На проверке», unchanged. A run past its time limit is stopped
and ends `timed-out`.

## A session inside the run

A coding agent the run starts itself (a `claude -p` or `codex exec` from its shell, a reviewer) inherits the
environment. Only the run's first session holds the dispatch: the hooks record the first session id for the
dispatch, by its `FABRIC_DISPATCH_ID` (Fabric gives each dispatch one, a UUID v4 by Fabric's word on board thread `b3e60686`; Switchboard sets it since
0.7.8; a value outside `[A-Za-z0-9._-]{1,64}` is ignored), else by the
workflow, the handoff and the launcher's run id (`SWITCHBOARD_LAUNCH_ID`), so a new dispatch of the same workflow is a
new holder; a launcher that sets the workflow alone gives each run a distinct run id. A `/clear` in the holding
session keeps the contract (the record moves to the new session id). A holder that accepted the handoff before
the `/clear` lost its `leaseId` with the context: Observatory replays an accept, `leaseId` included, only for the same
`sessionId` and `idempotencyKey`, and a read never carries the lease. The hooks name the session id the clear replaced,
so the holder replays the accept exactly: that `sessionId`, the same key (Switchboard's prompt fixes it,
`accept-<handoff>`), the same `owner` and `executor` the first accept passed (the launcher's prompt names both;
`observatory_checkpoint_latest` shows the workflow's executor); a new accept under the new id is refused. When
`observatory_checkpoint_latest` still shows the handoff pending, no accept was made, and the holder accepts it now
under that same `sessionId`, key, owner and executor, so a later `/clear`, which names the same id, replays it. When
the hooks cannot name the replaced id (no readable record, or Windows, where any `/clear` takes the record and the
hooks name no id), the notice gives the new id instead: a pending handoff is accepted under it, and the next `/clear`
names it; an accept already made under the unknown id cannot be replayed, so the session ends the run without touching the
request, and Fabric takes the workflow over after it (step 4). Any other session gets one line in place of the
contract: do the task
you were given, and never accept the handoff, claim, replace the responder, complete the request or write the
workflow's checkpoints. `watch-mail` refuses to start in a dispatched session, and the dashboard-kit notice says
nothing there. A host whose hook gets no session id (the native bridges: Hermes, OpenCode, OpenClaw, Pi) is always
told the full contract, since the hooks cannot tell its sessions apart. The election counts sessions whose hook ran: in a run whose own session has no adapter hook (a Codex
run whose home does not trust the hook: the person never trusted it, or a Switchboard before 0.7.8 started it), the first nested session the run
starts is taken as the holder.

The plugin tells a dispatched session from 0.63.0 on; an older one prints its ordinary preamble there, and only the
launcher's appended exit contract tells the run what to do.

## What the session does not do

- It runs no board sweep, no work claim and no `watch-mail`: the packet names the one thing to do. The prompt hook
  prints it no unread line and no nudges. `fabric_whoami`
  stays its first Fabric call.
- It never writes the lease into a log, a note or a checkpoint body, and the packet holds no secret.
- It never starts a second run for the same request or answers a request other than the one it was started on.
