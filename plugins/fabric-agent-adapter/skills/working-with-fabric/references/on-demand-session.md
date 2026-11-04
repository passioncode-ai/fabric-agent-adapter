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
| `FABRIC_DISPATCH_WORKFLOW` | the Observatory workflow that holds the packet, `wf_` and 16 lowercase hex digits; without the other two no session under it is a run |
| `FABRIC_DISPATCH_HANDOFF` | the handoff that gives this session the workflow's lease, `handoff:...` |
| `FABRIC_DISPATCH_REQUEST` | the board request to answer, a UUID |

The prompt's first line names the same three, fields one space apart in this order, then a blank line:

```text
fabric-dispatch/1 workflow=wf_<16 hex> handoff=<handoff id> request=<request uuid>
```

A session is the run only when its own prompt's first line names the same three as the environment (Fabric's spec
3.5 on its main at `deaf51fe`, agreed with Vesta on board thread `1add3c03`). The environment alone makes no run: a reader or a subshell the run
starts inherits it, and its prompt does not start with the line, so it is a helper that does its own task only. A line
that disagrees with the environment, or an environment without all three, makes no run either: that session says so
in the request's thread (`com.get` the request the line names, then `com.submit` kind `message` to its thread, naming
only the ids), takes nothing, writes no checkpoint and stops. A line with no `FABRIC_DISPATCH_WORKFLOW` in the
environment is quoted text (a board message pasted into a session), never a dispatch. Switchboard's `dispatch` sets
all three and writes the line (SB-247, with `FABRIC_DISPATCH_ID`, since Switchboard 0.7.8 of 2026-11-04; board thread
`b3e60686`).

The plugin's session-start hook, which sees no prompt yet, prints the exit contract (the steps below, with the values
filled in) on that condition, in place of the usual preamble, whatever the folder shows, and also in a session Fabric
launched (a run shown in Fabric's console). In Claude Code the prompt hook, which sees the line, says the session is
the run, or that it is none; in Codex and Kimi, which have no prompt hook, the session checks its first line itself. A resumed or compacted session prints nothing. The plugin's hooks reach a Claude Code
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
   shows the pending handoff.
2. **Take the lease.** `observatory_handoff_accept {owner, idempotencyKey, handoffId, executor?, sessionId?}`:
   pass this session's own `sessionId` (the same one on a retry) and the `owner`, `idempotencyKey` and `executor` the
   launcher's prompt names (Switchboard's: `agent:<provider>`, `accept-<handoff>` and `{provider, accountRef}`); when
   it names none, `owner` is `agent:<name>` (the same one for every write below), the key is `accept-<handoff>` too,
   so a later `/clear` can replay it, and the executor is left out. A lapsed or refused handoff (`lapsedHandoff`,
   `HandoffExpired`) holds no lease: the session ends the run without touching the request or the workflow.
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
   - when the request's `deadline` (the packet's `deadline:` artifact) is not after `run-ends-at` plus 10 minutes, no
     run comes before the deadline and an accepted request does not expire by itself: `com.complete` `failed_known`
     saying the deadline came first, and steps 6 and 7. Fabric decides on a next run no later than 120 s of the
     executor's silence and one 60 s cycle after `run-ends-at`, and starts none with less than 5 minutes to the
     deadline (`LAUNCH_MARGIN_MS`): 8 minutes, 10 with room for a slow launch (`RUN_END_TO_DEADLINE_MS` and spec 3.6 on
     Fabric's main at `afe28a60`, in no release yet); a request whose deadline passed unsettled goes
     to the operator with its workflow closed `blocked`;
   - otherwise the request is left accepted for the next run: an `in_progress` checkpoint without `close`, steps 5 and
     6 skipped. Fabric's dispatcher starts that run for an accepted request whose holder is gone, which takes it over
     with `com.responder_replace` (step 3), and after two runs with no answer shows it to the operator (Fabric's main
     at `fff4b6d9`, in no release yet; a Fabric before it dispatches no accepted request). The open workflow is Fabric's
     to move, not the run's: after the run ends, and no sooner than 120 s of the executor's silence, Fabric hands it to
     itself (`observatory_handoff_create` with reason `restart`, or `crash` when Switchboard reports the run failed,
     to `service:fabric`), takes the new lease and routes it to the next run; when the request goes to «На проверке» or
     its deadline passes, Fabric closes it `blocked` the same way (Fabric's spec at `c560d97e`, sections 3.4 and 3.6;
     its decision on thread `b3e60686`, 2026-11-04; its code at that commit does not do it yet, so a second run on
     Fabric's main meets a workflow whose lease is still this run's). This run only leaves it open.

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
environment, and its prompt does not start with the line, so it is a helper; an Agent tool subagent runs in the same
process and gets no hook output at all. Every session under the environment gets the conditional contract at its
start; the prompt hook prints one line only to a second session whose own first line names the dispatch, telling it
the run holds it. A helper launched outside the run is best started with `env -u
FABRIC_DISPATCH_WORKFLOW -u FABRIC_DISPATCH_HANDOFF -u FABRIC_DISPATCH_REQUEST`. The first session whose own line names
the dispatch holds it: the prompt hook records that session id for the dispatch, by its `FABRIC_DISPATCH_ID` (Fabric gives each dispatch one, a UUID v4 by Fabric's word on board thread `b3e60686`; Switchboard sets it since
0.7.8; a value outside `[A-Za-z0-9._-]{1,64}` is ignored), else by the
workflow, the handoff and the launcher's run id (`SWITCHBOARD_LAUNCH_ID`), so a new dispatch of the same workflow is a
new holder. A `/clear` in the holding session's process keeps the contract (the record moves to the new session id);
a `/clear` with no record (in Codex and Kimi the hooks keep none, having no prompt hook) gets the conditional contract
again, so a cleared Codex run reads as a helper and Fabric takes the request over after it. A holder that accepted the handoff before
the `/clear` lost its `leaseId` with the context: Observatory replays an accept, `leaseId` included, only for the same
`sessionId` and `idempotencyKey`, and a read never carries the lease. The hooks name the session id the clear replaced,
so the holder replays the accept exactly: that `sessionId`, the same key (Switchboard's prompt fixes it,
`accept-<handoff>`), the same `owner` and the `executor` as the first accept passed them. Once the handoff is taken
(neither pending nor lapsed, and the lease's `handoffId` is this dispatch's handoff), the lease `observatory_checkpoint_latest` shows is that accept's and survives the clear: its `holder`
is the first accept's owner, and its `executor` merges the offer (a provider only, Fabric's spec 3.5) with what was
passed, so it is the passed executor when it carries an `accountRef`, and the first accept passed none when it shows
a provider alone. A new accept under the new id is refused, and so is a replay with another owner or executor; after
any refused replay the session ends the run without touching the request and Fabric takes the workflow over. When
`observatory_checkpoint_latest` still shows the handoff pending, no accept was made and the lease it shows is
Fabric's own (the workflow's creator, or its `restart` hand-over to `service:fabric`), not the run's: the holder
accepts it now under that same `sessionId`, with the key and owner step 2 names (`accept-<handoff>`, and
`agent:<provider>`, such as `agent:claude-code`, when Switchboard started the run, else `agent:<name>`) and no executor, since the launcher's prompt is gone, so a later `/clear`, which names the same id,
replays it with no executor; the lease then records the provider alone, not the account Switchboard chose (Fabric's
spec 3.5 has the session narrow it), and Switchboard's fallback before 0.7.11 reads such a lease as the person's
ordinary CLI session, so after the run a limit on that account may continue it through `switchboard continue` before
Fabric takes it back (SB-253 makes the fallback leave a board-request workflow to Fabric, due in 0.7.11; thread
`b3e60686`). A lapsed handoff (`lapsedHandoff`) was never
accepted and no longer can be: the session ends the run without touching the request. Observatory shows the
workflow's newest offer, which may be another hand-over's: the session reads only this dispatch's handoff, and when
the one shown is another, it ends the run without touching the request. When
the hooks cannot name the replaced id (no readable record, or Windows, where any `/clear` takes the record and the
hooks name no id), the notice says first that nothing can be replayed and gives the new id: a pending handoff is accepted under it, and the next `/clear`
names it, except on Windows, where it names no id either, so an accept made there cannot be replayed after another
`/clear`. An accept already made under an id the hooks could not name cannot be replayed, so the session ends the run
without touching the request, and Fabric takes the workflow over after it (step 4). Any other session gets one line in place of the
contract: do the task
you were given, and never accept the handoff, claim, replace the responder, complete the request or write the
workflow's checkpoints. `watch-mail` refuses to start under a board request's environment, the run's or a helper's,
and the dashboard-kit notice says nothing there. A host whose hook gets no session id (the native bridges: Hermes,
OpenCode, OpenClaw, Pi) is always told the conditional contract and checks its first line itself; no record is
written. A run whose own session has no prompt hook (Codex, Kimi, or a Codex home that does not trust the hook: the
person never trusted it, or a Switchboard before 0.7.8 started it) elects no holder either: the session checks its
first line itself, and a nested session, whose prompt has no line, stays a helper. A Claude Code session such a run
starts with the run's own full prompt, line included, finds no record and is told it is the run; Observatory's one
accept per handoff then decides which of the two goes on, the other's accept being refused.

The plugin tells a dispatched session from 0.63.0 on; an older one prints its ordinary preamble there, and only the
launcher's appended exit contract tells the run what to do.

## What the session does not do

- It runs no board sweep, no work claim and no `watch-mail`: the packet names the one thing to do. The prompt hook
  prints it no unread line and no nudges. `fabric_whoami`
  stays its first Fabric call.
- It never writes the lease into a log, a note or a checkpoint body, and the packet holds no secret.
- It never starts a second run for the same request or answers a request other than the one it was started on.
