# A session started on a board request (FAA-201)

When a board request reaches a project that has no live responder and no live session, Fabric starts a session in the
project's folder to do it (Fabric's on-demand spec, sections 3.4 to 3.6, at Fabric commit `1329b60f`). That session
does the one request, reports, completes it and ends. Nobody watches it, so it never waits for a person. The
dispatcher ships in Fabric 0.3.16 (released 2026-11-05, tag `v0.3.16` at `bcead0ef`), on by default since
`a6f0ffda`. Fabric 0.3.17 (2026-11-08) adds CO-409 (`babb2dc1`, `09ddb2fc`), CO-506 (`027cb809`: a session's own
Project is granted `board.respond` at `com.enroll`) and the slot condition in `board.read-at-start` and `com.enroll`'s
description (`dbfbfce4`, `12d57bdd`, `4f3c742a`); the latest release is v0.3.20 (2026-11-12, tag at `bcf3b4dd`), which
ships CO-563 (`780022af`). "Fabric's main" below names the commit a change landed at, each in v0.3.17 or earlier
unless it says otherwise. The hooks recognise a dispatched session from
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
3.5 on its main at `deaf51fe`, agreed on the project board, 2026-11-05). The environment alone makes no run: a reader or a subshell the run
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
only when the home's own `config.toml` trusts it (measured with codex-cli 0.165.0; `test/native/codex_hooks.py` runs
the same hook trusted and untrusted: untrusted, Codex lists it `untrusted` and sends no hook event while the turn
runs, FAA-201 (b)). Switchboard links the person's
`hooks.json` into its isolated homes, and since 0.7.8 carries the person's trust in that
file into the home's `config.toml`, never a hook changed after it was trusted. Where the person has not trusted the
hook, or a Switchboard before 0.7.8 started the run, the launcher's appended exit contract alone tells a Codex run.

## What the session does

1. **Look, then read the packet.** `fabric_whoami` first, as in any session: until it, the session holds no other
   Fabric tool, and it returns the session's rules. A run that still sees only `fabric_whoami` among Fabric's tools
   after that call runs on a Fabric before 0.3.20 and met its CO-563: `fabric-mcp` offered the rest only once the
   session was admitted, and a headless Claude Code run (`claude -p`) reads its list of tools once. Fabric 0.3.20
   (2026-11-12) lists them from the first tool list, so the remedy is Fabric 0.3.20 or later; on an older Fabric an
   interactive session can reconnect the `fabric` MCP server (`/mcp`) after `fabric_whoami`, which a headless run
   cannot. Such a run cannot read or answer the board, so it says so in its exit report (an `in_progress` checkpoint
   naming CO-563 and Fabric's version when it holds the lease, then the retro), never claims the board was read, and
   ends (FAA-296). Then `observatory_checkpoint_latest {workflowId}`. Its `goal`
   describes the request (its text is on the board); its `constraints` carry the exit contract, the three floors and
   the operator's mandate when the request has one: obey them first. Its `artifacts` are references only,
   `kind: "other"` with `ref` `board-request:<uuid>`, `board-thread:<uuid>`, `capability:<name>`,
   `fabric-project:<uuid>`, `deadline:<time>` and `run-ends-at:<time>`. Take the board ids from the environment and
   the first line first; the packet's `board-request:`, `board-thread:` and `fabric-project:` refs are the fallback
   (Observatory keeps them with their UUIDs since 0.34.0: OBS-323, PR #437 at `63e2cc43`, its answer `7e5b4e2d` on
   board thread `7ae9ac3a`), while it still redacts a `board-message:` ref, so a run started for a board message finds
   no message ref in the packet (FAA-295). No message body travels in the packet: read the request with `com.get {message: <request>}` (a request's id
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
3. **Take the request.** `com.status` once, for the epoch every idempotency key names and the request capability's
   slot (its state and generation), read before anything else is called on the request (contract DEC-0152 SA-6, FAA-311).
   When the slot reads `active`, or a `com.enroll` refused `fenced` (a holder became live meanwhile), the run
   leaves the request to that holder: it enrolls on nothing, sends no `com.reply` and asks no one; the request is not
   this run's to settle, so the workflow stays open (the error rule below) and the run writes the retro (step 7) and
   ends. Otherwise `com.enroll` for the request's capability, then `com.claim {idempotency, capability, request}`, `com.accept`, and
   `com.effect_begin` before the work has an effect. A `com.enroll` refused `not_authorized` (the run's Project holds
   no `board.respond` grant for the capability) takes no slot, asks for no grant itself (no `fabric.access.request`) and
   does no work: a session has no route to that grant (`fabric.access.request` is the door's and a binding's, never
   exposed by `fabric-mcp`, and Fabric's Agent access only decides a request already waiting), and work without a slot
   has no fence, no `com.progress` and a live session may take the request in parallel. From Fabric 0.3.17 (CO-506,
   `027cb809`) a session's own Project is granted it at `com.enroll`, so the refusal comes only where CO-506 grants
   nothing, for the reason Fabric's `board.own-respond` log line names: a machine marked as an organization's (the mark
   in Fabric's settings), no live credential for the session or its runner (the agent enrolls again), a standing denial
   ("Снять отказ" in Agent access) or a full ask queue (the operator answers the asks that wait, or they expire)
   (Fabric, thread `1add3c03`, `315c5b54`). Before 0.3.17 every session is refused. A run cannot tell from the board
   which Fabric it runs on: when the refusal names no reason, its reply and question name both cases. When `com.get`
   reads the request `queued` and `com.status`'s entry for the request's capability reads `absent` at generation 0 (no
   service of the project ever held it; `com.status` lists the capability of every open request, up to the 256
   capabilities Fabric lists, so a missing entry or an unavailable board is the error rule),
   the run answers it once with `com.reply` (`replyTo` the request, from the target Project, which answers
   it: DEC-0098, DEC-0102) declining it with the reason and what opens it (before 0.3.17: a Fabric with CO-506; from
   it: the reason above clearing), and that the requester sends it again then (the reply ends the queue, so nothing
   takes it later; never say it waits). Since only the operator
   opens that gate and the decline shows the operator no gate (at most an unread answer on the requester's Project
   until it is read), it then asks the operator once:
   `fabric_question_ask` with `kind: access`, `about: board.gate.<capability>`, the `commandId` the contract names (UUID
   v5 of the name `board.gate` in the request id's namespace, `gate_question_id` in `fabric_session_cli.py`, so every run
   on that request gets the same question back) and a `text` naming the request (its id, the requesting Project, the
   capability), the gate (this Project's `board.respond` grant for that capability) and what opens it (the reply's
   reason and what lifts it; at a slot a holder held, also the Project's service enrolling again, which takes the
   request itself without opening this gate; on Fabric 0.3.16 nothing else does, since Agent access only decides a
   request a service filed); it waits for no answer (FAA-224; the tool needs no slot; Fabric keeps the
   `about` with the question and settles no later question by it yet (CO-519), so each gate question reaches the operator and a
   repeat with the same `commandId` returns the same question: Fabric, thread `1add3c03`, `5b216035`). A question that fails is left (the decline already answered the request), and the closing write's
   `notes` say so, since then nothing about the gate reached the operator. Then it closes the workflow `done` once
   `com.get` reads it answered (step 6), and writes the retro (step 7). When the request is not queued, or the slot
   reads `stale`, `absent` at a generation of 1 or more (a holder enrolled on it: a
   service of this Project, or from 0.3.17 a session; one that stopped cleanly reads `absent`, and a service takes the
   request when it rejoins, so a decline would take it from it), or shows no generation or no row, or the slot or the
   Project is held (Fabric serves a session no `held` flag yet), it sends no
   `com.reply` but asks the operator with the same `fabric_question_ask` (a question answers no request and takes
   nothing from the service; from 0.3.17 such a refusal comes from the reason `board.own-respond` names, so it is never
   silent: Fabric `4f3c742a`; a question that fails is named in the
   `notes` of one more in_progress checkpoint), then the error rule below holds and the request stays as it is (a queued request goes to
   the operator after two runs with no answer). A
   capability listed only by a service's live grant, with no enroll yet, also reads `absent` at generation 0: a run
   declines it, which a service asking and enrolling at once (ADR-0186) seldom leaves time for.
   A gate question is moot once the request is answered or taken (the usual end at a slot a service held is that
   service rejoining and taking it): the question stays open, since Fabric settles none by its `about` (CO-519) and no
   Fabric through v0.3.19 lets an agent close one, so a run or session that later finds the request answered, or taken
   and completed, says so once in its closing `notes`, naming the question (its `about` and `commandId`) (FAA-248).
   After the decline, the target's request no longer waits for the operator on the board (an answered request is settled: no second run,
   no unmoved or to-operator finding; the question above is what reaches the operator, when Fabric took it); the requester reads the decline, and until it reads and acknowledges it (`com.read_ack`) Fabric
   shows it on the requester's Project in «На проверке» as an answer nobody read,
   and the closing write's `notes` say the request was declined and why.
   Fabric's dispatcher counts an answered request as settled and starts no second run for it.
   FAA-219; Fabric's answer in board thread `1add3c03` (option (b), 2026-11-05), the responder's run's rule plus the
   slot condition, which Fabric's `board.read-at-start` took from the adapter (FAA-231, `dbfbfce4`, in Fabric 0.3.17);
   Fabric 0.3.16's `com.enroll` description tells a session to ask the grant, which it cannot, and its own
   `not_authorized` refusal says to reply with the answer; step 3 wins over both (Fabric 0.3.17 gives `com.enroll`'s
   tool description the same slot condition, `12d57bdd`, FAA-231); the refusal text waits
   for its CO-507. An earlier run may have left the request taken: `com.get` on the
   request shows its state, and the latest checkpoint (step 1) what that run recorded. An accepted request is never
   claimed again: take it over with `com.responder_replace {expectedGeneration, transfer}` (its receipt carries the new
   attempt). An `outcome_unknown` one is resolved only by `com.reconcile` with an observed result; so is an `in_progress` one an
   earlier run left (its effect begun, as before 0.67.0), which the takeover makes `outcome_unknown`: what the run cannot
   observe it leaves to the operator, to whom Fabric shows the request (step 4). Never complete what
   you did not observe. After the lease, after the claim or the takeover, and after the reply, write an `in_progress`
   checkpoint (`workflowId`, `leaseId`), so a later run has something to read. Observatory keeps only the latest
   body, so every checkpoint the session writes repeats `goal`, `constraints`, `artifacts` and `credentials` of
   `checkpoint.body` (from `observatory_checkpoint_latest`, or the accept answer's `checkpoint`) unchanged and adds `open`, `done` or `notes`, never a value: a body of `done` and `notes` alone would
   leave the next run a packet with no request and no constraints. Never write back the top-level `credentials` or the
   accept answer's `pack`: they carry each key's `state` and `use`, and Observatory refuses them in a body.
4. **Do the work** the goal names. The board's lease is 60 s: renew with `com.renew` or `com.progress` about every 20 s
   during a long step, so `com.complete` never meets `lease_expired`. Finish before `run-ends-at`, when the launcher
   stops the run. Work that cannot end by then gives its state (what is done, where it lies, what is left), before
   `run-ends-at`, as the note of a `com.progress` on the request's thread (the slot holder's state, DEC-0152 SA-6). Then:
   - after `com.effect_begin` the request is `in_progress`, which a next run could only settle as `outcome_unknown`
     with `com.reconcile`: `com.complete` `failed_known` with `observed: true` and the state it observed (Fabric refuses
     a complete after an effect began without `observed: true`, `observation_required`; FAA-215), and steps 6 and 7 (FAA-210; the
     same choice as a responder's run, board thread `1add3c03`);
   - when the request's `deadline` (the packet's `deadline:` artifact) is not after `run-ends-at` plus 10 minutes, no
     run comes before the deadline and an accepted request does not expire by itself: `com.complete` `failed_known`
     saying the deadline came first, and steps 6 and 7. Fabric decides on a next run no later than 120 s of the
     executor's silence and one 60 s cycle after `run-ends-at`, and starts none with less than 5 minutes to the
     deadline (`LAUNCH_MARGIN_MS`): 8 minutes, 10 with room for a slow launch (`RUN_END_TO_DEADLINE_MS` and spec 3.6 on
     Fabric's main since `afe28a60`); an accepted or in-progress request with no live holder past its deadline goes
     to the operator, with its workflow closed `blocked`;
   - otherwise (accepted, no effect begun) the request is left accepted for the next run: an `in_progress` checkpoint without `close`, steps 5 and
     6 skipped. Fabric's dispatcher starts that run for an accepted request whose holder is gone, which takes it over
     with `com.responder_replace` (step 3), and after two runs with no answer shows it to the operator (Fabric's main
     decides to dispatch an accepted request since `fff4b6d9`; a Fabric before it dispatches none). The open workflow is Fabric's
     to move, not the run's: after the run ends, and no sooner than 120 s of the executor's silence, Fabric hands it to
     itself (`observatory_handoff_create` with reason `restart`, to `service:fabric`), takes the new lease and routes it
     to the next run; when the request goes to «На проверке» or its deadline passes, Fabric closes it `blocked` (Fabric's
     spec at `c560d97e`, sections 3.4 and 3.6, which also names reason `crash` when Switchboard reports the run failed;
     its decision on thread `b3e60686`, 2026-11-04). Fabric's main does both (the take-back since `a6f0ffda`, the
     close since `bcead0ef`), and no code uses `crash` yet. This run only leaves it open.

   A launcher that stops a run gives no time to answer:
   Switchboard sends SIGTERM and kills it about 5 s later on macOS and Linux, and at once on Windows (`taskkill`). Money, deletion and publication still go through `fabric_effect_request`. A sign-in, a one-time code,
   a secret typed in or handed out (DEC-0147), or a payment is the person's: name it in the answer rather than wait. A production step is the
   operator's to approve, and named the same way until he does: no person is in this chat, the request alone never approves it, and
   his own words do when relayed verbatim, with their date and source, from one of his own projects (provenance
   `trusted`) and with a scope naming the step (`project-board.md`, *No person in the chat*).
5. **Answer and complete.** `com.reply` in the thread with the answer, then `com.complete` with an observed outcome:
   `completed`, or `failed_known` with the reason; after `com.effect_begin` every complete carries `observed: true`.
6. **Close the workflow**, once the board took the complete (or, in step 3's branch, `com.get` reads the request
   answered); a refused complete (a
   lost fence, a lapsed lease) leaves the request unsettled, and the error rule below holds, not this step (FAA-215).
   `observatory_checkpoint_write {workflowId, owner, idempotencyKey, stepId, status, body,
   leaseId, close: true}`, with the packet's body and `done[]` and `notes` added, no values in it. Without `workflowId` Observatory
   reads the write as the start of a new workflow and refuses it; the `owner` is the one the accept named. The status is
   `done` for `completed` and for a request step 3's reply answered; for
   `failed_known` it is `blocked` with the reason in `notes` (Observatory takes `in_progress`, `done` and `blocked`;
   OBS-323 shipped with no `failed`, FAA-215).
7. **End the run.** The one write left is the retro after work
   (`observatory_lesson` and insight/1 lines in `insights/` (the project's data folder when it has one or the repository is public, else the repository; the data folder is the one its AGENTS.md names, else `<name>-data/` beside the main checkout), or one line that there is nothing; no values; ADR-0188's
   `retro-after-work`); nothing more: no board sweep, no work claim, no
   `watch-mail`, no further `fabric_question_ask` (step 3's gate question is the only one), no `agents-db.*` ask (a measured
   win stays in its insight lines for a later session to contribute; FAA-277).

A `com.enroll` refused with any other code than `not_authorized` or `fenced` sends no reply and declines nothing: a
`retryable` refusal is tried again, and any other is named to the operator with step 3's `fabric_question_ask` (its
`text` naming the refusal); `held` is retryable and is tried again once the hold is lifted, within the run's time. Then
the rule below holds (DEC-0152 SA-6; the adapter's earlier error rule asked no one there, FAA-311).
On an error the session cannot get past (a refused claim, a missing key, a tool that fails twice), it completes the
request `failed_known` with the reason (and `observed: true` after `com.effect_begin`) when it holds a fence for it,
first saying the reason in a `com.progress` note on the request's thread, where the requester and the operator read it.
A run that leaves the workflow open names its reason in the open checkpoint, which Fabric's take-back does not carry to
the next run (it starts from a fresh body; open in FAA-215). It closes the workflow only once the request is settled: the board accepted the complete or a reconcile, or `com.get` reads the request answered, terminal or
`outcome_unknown` (no Fabric starts a run for an `outcome_unknown` request, so its workflow is closed safely; Fabric's
main counts such a run finished, not empty, since `babb2dc1`). Otherwise (the request still `queued`, `claimed`, `accepted` or
`in_progress`, and not this run's to settle) it leaves the workflow open, with an `in_progress` checkpoint without
`close` naming the reason when it holds the lease, and writes the retro (step 7) and ends: a workflow closed over an
unsettled request made the next dispatch fail at the take-back on every cycle (Fabric's main at `a6f0ffda`; since
`bcead0ef` Fabric opens a new workflow instead), while an open one is taken back for the next run when the project has
no live session (a live session holds the request), and after two runs with no answer Fabric shows the request to the
operator whatever its state. A workflow left open because another session holds the request is closed by Fabric once
that request settles, and a request a run's `com.enroll` left `outcome_unknown` shows in «На проверке» at once
(Fabric 0.3.17, `09ddb2fc`; FAA-213). Switchboard's appended exit contract says the same from
0.7.13 (SB-258); an earlier Switchboard tells the run to close the workflow whatever the request's state, and this
rule, the later one, is the one to follow.

A run started with `--permissions ask` may find the board or Observatory tools not allowed by the person's settings.
It cannot answer then: it says so in its final output and ends; Fabric records the outcome and does not retry the same
run unchanged.

## When a run ends without an answer

Fabric watches the request and the run (spec 3.6). The request keeps the state the board contract gives it: `queued`
stays queued, `claimed` is taken again under a new attempt, `accepted` is held until a responder takes it over, and
`in_progress` stays until the next holder registers, when the board records the lost result; an `outcome_unknown`
attempt is resolved only by `com.reconcile` with an observed result. Fabric may start one more run, when the project has no live session, for a request
still queued, claimed with a lapsed lease, or accepted or in progress with no live holder; after two runs with no
answer it shows the request to the operator in «На проверке», unchanged, whatever its state. A run past its time limit is stopped
and ends `timed-out`.

## A session inside the run

A session the run starts itself (`claude -p`, `codex exec`) runs with that runner's bypass flag, once: Claude Code
`--dangerously-skip-permissions`, Codex `--dangerously-bypass-approvals-and-sandbox`. Nobody is in its chat to answer a
permission prompt, so the task's limits (its folder, its tools, its time and spend) are set when the run launches it,
in its prompt and arguments, never asked for later (the operator's decision of 2026-11-07, relayed on board thread
`eefa7959`, message `aa7c14a9`; FAA-274). No adapter code launches a runner.

A coding agent the run starts itself (a `claude -p` or `codex exec` from its shell, a reviewer) inherits the
environment, and its prompt does not start with the line, so it is a helper; an Agent tool subagent runs in the same
process and gets no hook output at all. Every session under the environment gets the conditional contract at its
start, except a `/clear`: the holder's own keeps the run's contract, and one while another session holds the
dispatch is told it is nested; the prompt hook prints one line only to a second session whose own first line names the dispatch, telling it
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
Fabric takes it back (SB-253 makes the fallback leave a board-request workflow to Fabric, released in Switchboard 0.7.11 on 2026-11-05; thread
`b3e60686`). A lapsed handoff (`lapsedHandoff`) was never
accepted and no longer can be: the session ends the run without touching the request. Observatory shows the
workflow's newest offer, which may be another hand-over's: the session reads only this dispatch's handoff, and when
the one shown is another, it ends the run without touching the request. When
the record names a replaced id the hooks cannot pass on (one that is not a lowercase UUID), the notice says first that
nothing can be replayed and gives the new id: a pending handoff is accepted under it, and the next `/clear` names it;
an accept already made under that id cannot be replayed, so the session ends the run without touching the request,
and Fabric takes the workflow over after it (step 4). On Windows, where each hook's parent is a new Git Bash, a
`/clear` cannot tell the holder from a helper: it holds nothing (and neither does a session inside the run that
clears), and while the record names the replaced session the
cleared session is told at once that it runs inside a run that holds it, stays a helper whatever its prompt's line
says, and Fabric takes the workflow over after the run. A second session whose own first line names the
dispatch gets one line at its first prompt, after the conditional contract its start printed: do the task
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
