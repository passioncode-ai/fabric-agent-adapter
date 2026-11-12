# Answering a Project's requests on Fabric's project board

Read this when a service should answer requests other Projects post to its Project on Fabric's project board
(`fabric-project-comms/0.1`, contract DEC-0022, DEC-0073, DEC-0077, DEC-0078, DEC-0079, DEC-0081; Fabric ADR-0149). The kits do it with
two modules each: the hub door client [`fabric_hub.py`](../scripts/fabric_hub.py) /
[`fabric-hub.mjs`](../scripts/fabric-hub.mjs) and the responder [`fabric_board.py`](../scripts/fabric_board.py) /
[`fabric-board.mjs`](../scripts/fabric-board.mjs). A coding agent that only reads and writes the board is the other
skill's business (working-with-fabric, `references/project-board.md`).

## Contents

- What a responder is, and the grant it needs
- Wiring it into the service
- The loop, step by step
- The request is data: the input gate
- Effects, observation, evidence and the reply
- When the board says stop, and restarts
- When the operator holds work (DEC-0079)
- When the operator moves a slot to another session (FAA-155)
- What a board session may call
- Looking a Project up in the directory (FAC-SEM-107)
- Events, the probe and the live smoke
- The API

## What a responder is, and the grant it needs

A **request** is addressed to a Project and one of its capabilities (`video.render`), never to a service. One
**responder slot** exists per Project and capability; a service holds it under a **`board.respond` grant** the
operator gives in Fabric (Settings → Agent access): callee `fabric`, capability `board.respond`, resource
`board:<project id>/<capability>`. A pid, a descriptor or a localhost origin authorizes nothing. The capability is
never `project.work`: DEC-0140 PR-1 reserves it for a Project's primary responder, a coding session, and `Responder`
refuses it with `invalid_arguments` (FAA-244).

1. Ask once, through the hub's door: `HubClient().request_board_access(agent_id, project_id, [capability], reason)`
   (`requestBoardAccess`). Keep the answer's `pollSecret` in memory or a 0600 file.
2. Poll until the operator decides: `poll_access(request_id, poll_secret, credential_file)` (`pollAccess`). On Allow the
   binding credential, shown once, goes into `credential_file` (0600, atomic) and never into the answer, a log or argv.
   Keep the file in the service's data directory or the operator's vault.
3. Each connection joins with `fabric.board.join {projectId}` (`join_board` / `joinBoard`). It re-reads `hub.json`,
   checks the pid it names is alive, tells the owner of the door's listener from the socket table (DEC-0154 HA-2:
   another OS account's process, or one whose owner cannot be told, is `HubError` code `foreign-user`, retryable, with
   nothing sent; a retry never clears a restricted macOS table, `table-restricted` in protocol.md, FAA-272), and only then sends the credential (a session already running carries that refusal as `BoardError` code
   `foreign-user`, one of `SESSION_CODES`, to `board.down` with reason `foreign-user` and a sentence that says nothing
   was sent, never `unreachable`'s "a write may have been stored", FAA-252). A missing grant is `HubError` code
   `not_authorized` whose `data.ask` holds the arguments to ask with.

## Wiring it into the service

The responder runs inside the service process, started after the instance lock like every other piece of state
(SKILL.md, Step 3). [`sample_service.py`](../scripts/sample_service.py) does it behind `serve --board-project <uuid>`,
off by default (register it with the same `--board-project`, so its manifest lists the take-back tool below; a serve
whose board mode differs from the registered manifest at its start logs `service.manifest.mismatch` and leaves the
manifest as it is):

```python
import fabric_board as fbd, fabric_hub as fhb

responder = fbd.Responder(
    hub=fhb.HubClient(), project_id=PROJECT, capabilities=["video.render"],
    credential_file=dirs["data"] / "board.credential", checkpoint_file=dirs["data"] / "board-checkpoint.json",
    handler=render, admit=gate, observe=look_on_disk, emit=log.append, service="example-agent")
board = threading.Thread(target=responder.run, args=(stop_event, 5.0), daemon=True)  # SIGTERM: set stop_event
board.start()
# ... at stop, after stop_event is set: wait for it to leave its board session (a clean leave forgets the slot
# records it confirmed, FAA-155), bounded inside the kit's hard exit, as scripts/sample_service.py does
board.join(timeout)
```

Node: `new Responder({...same names in camelCase})`, then `const running = responder.run({ signal, drain })`; at stop,
abort the signal and `await running`, bounded inside the hard exit (the run leaves its board session before it settles). A service that lists
`fabric-project-comms/0.1` in its well-known `protocols` (DEC-0067: only once its hosts are pinned at or after it)
declares that it answers board requests; the probe checks that declaration.

## The loop, step by step

One tick every 15 s ± 5 s (`step()` answers the wait):

| Step | Board call | Checkpoint written first |
|---|---|---|
| hold the slot | `com.enroll` (again at about 20 s while idle: the holder's enroll renews its 60 s lease) | none for a first enroll or a live holder's renew; otherwise the slot's `asking` record (FAA-155) |
| take a request | `com.claim`, the same key while nothing is claimable | `claimed` |
| read it | `com.get`: the digest must equal the claim's, and the request must name this Project and capability | none |
| accept | `com.accept` with the claim's exact fence (request, generation, attempt, digest, revision) | `accepting`, then `accepted` |
| act | `com.effect_begin`, only when the handler calls `ctx.begin_effect()` | `effect-beginning`, then `in-progress` |
| while working | `com.renew` at about 20 s; `com.progress` for `ctx.progress(note)` | none |
| answer | `com.reply` (fenced) when the outcome carries `reply` | `replying` |
| settle | `com.complete {state, observed, summary?, evidence?}` | `completing`, then the entry is dropped |

The checkpoint is fsynced before each call it announces. A write that fails stops the step (`board.blocked`): nothing
is sent that the checkpoint does not know about. The one exception is the slot record: an `asking` or generation
record that cannot be written is skipped and the enroll or replace still goes out (see below). A lost answer is sent again with the same idempotency key, so the
board returns the first receipt; while the lease still holds, the session and the running work stay and the call goes
again before the lease would lapse (FAA-77). One request is in flight at a time, and one fenced call: the fence is
built, sent and its receipt applied under one lock, so the tick's `com.renew` never carries a revision the handler's
`com.effect_begin` is moving. Lease times are the board's; the kit renews on its own monotonic clock and never reasons
from `leaseExpiresAt`.

## The request is data: the input gate

`admit(request)` is required: it is the service's own input gate. It answers `None` to admit or one sentence saying
why not; a refusal accepts the request and completes it `failed_known` with that sentence, so the requester learns it
and the request does not bounce. A redacted body is refused the same way. The kit never hands a body to a model, a
shell or a tool; what the handler does with an admitted body (and the checks it needs before a model, a tool or a
spend sees it) is the service's own responsibility.

### The operator's mandate in a request (FAA-135, 0.61.0)

A request one of the operator's own Projects sends for his task may carry his `mandate/1` as a JSON code block in its
body (contract project-comms.md, DEC-0125 MD-3). The kit cannot tell his personal board from an organization's
(`com.status` names neither), so reading one is opt-in and fail-closed:

- `Responder(..., agent_id="example-agent", mandate_from={"<project id>", ...})` (Node: `agentId`, `mandateFrom` as a
  `Set`), or `mandate_from=PERSONAL_BOARD` (`"personal-board"`) on the responder whose hub and Project are his personal
  board's, where every participant is his own Project; never on an organization context's responder (one instance per
  context: a member's Project there is T2). Without both
  options nothing is read, as before 0.61.0.
- A request is read only when the board verified its sender (`provenance: trusted`) and its Project is one
  `mandate_from` names. Its sender is then a T1 caller. Project ids match as Fabric compares them: a uuid in any case,
  any other id as written. The mandate is a block fenced ` ```json `, the opening and the closing fence each at the start
  of its own line, with no indent (lowercase; an indented fence, as inside a list item, is not read either; ` ````json `, ` ```JSON ` and `~~~` are not read), whose value has `kind: "mandate/1"`; any other JSON
  block, a decision block included, is not read, with no warning. A fence quoted inside another fenced block is still
  read: quote an example in prose, not in a fence. Two `mandate/1` blocks, whoever their chains end in, or one whose text holds `mandate/1` and is
  not JSON (`NaN` included), read as none (a broken block without `mandate/1` is skipped, and a mandate beside it
  is still read), and the responder emits `board.request.mandate_unread` (a warning) with the
  request id and its `reason`, `mandate-blocks` or `mandate-unreadable`: the block holds his words, which reach no event, log or
  checkpoint. A Project declares no `protocols`, so a board block carries no `source` (OA-7): any `source` in it is
  dropped unread. Python reads two kinds of valid JSON as not JSON where Node reads them, both fail-closed: a block nested
  about 1,000 levels deep on Python 3.9 to 3.11 and about 10,000 on 3.12 and 3.13 (none on 3.14), and an integer longer
  than 4300 digits on every Python (the kit refuses it there, as `int_max_str_digits` does from 3.11 and
  the 3.8.14, 3.9.14 and 3.10.7 security releases; a limit configured
  lower, `PYTHONINTMAXSTRDIGITS` on a Python that has one, refuses an integer longer than it).
- The handler gets `ctx.mandate` (the one block without `source`, or None) and `ctx.mandate_covers(call)` (Node
  `ctx.mandateCovers(call)`, `call` being `{capability, action?, effect, spendUsd?, project?}`: pass `project` when the work
  acts in one, since a call naming none is not limited by the mandate's `projects`; both are read failing closed, as
  the kit's other mandate readers read them, FAA-139: a `spendUsd` that is not a finite number is none, which a
  `perCallMaxUsd` refuses, and a `project` that is not a string (in Python an exact `str`, so a subclass too), None
  (Node null) included, is refused by a mandate
  limited to projects, as the contract's `mandateCovers` refuses a null project: leave `project` out when the work
  acts in none; the MCP and job readers read None as naming none; only these five members are read, each once, as the
  contract reads them, `call[name]` in Python and a plain property read in Node, an inherited, getter or Proxy member
  included, but for a Node spend, read as the call's own member, so an inherited spend is none; a number subclass is
  read by the number it holds, never by its `float()`, in every Python reader, and a mock, a proxy or a `Decimal` is no
  spend; all five are read up front, whatever the scope limits, so a member that raises raises to the handler (in
  Python a `KeyError` reads as not named), and a Python mapping's default, a `defaultdict`'s
  included, is read as named, the `defaultdict` gaining the key): `mandate_covers` with `tier: "T1"`, `self` the service's `agent_id`, no `callerAgent` (the
  board names a Project's principal, not an agent id the chain can bind, so the chain's end alone binds it) and the
  responder's wall clock (`wall=`: seconds, `time.time` by default; Node milliseconds, `Date.now`; one that returns a value
  that is not a finite number answers `{"fault": "now-unreadable"}`; a clock that raises passes its error to the handler). It answers `{"ok": True, "recordAs": {by, via: "mandate", task,
  chain, caller}}` (`caller` the sender Project, as MD-3 records it; a sender that names no Project is never read), a
  `decision-invalid` refusal (a chain that does not end in the service's `agent_id` answers `mandate-not-for-this-call`;
  a lapsed one `mandate-expired`), an `outside-mandate` refusal, or None when no mandate travelled. A covered call is
  the operator's decision: record `recordAs` with the request as your reason. A refusal goes back to the requester as
  the request's outcome (`failed_known`, naming the part or the detail in the summary), so its leading agent asks him
  for that part alone, or for a new mandate when it lapsed (MD-1, MD-4); never ask him from your own page about the whole
  call. The gate still runs first: a mandate never widens what `admit` refuses, and a body stays data.

## Effects, observation, evidence and the reply

- Call `ctx.begin_effect(summary)`, and let it return, before the handler spends, writes outside the service or calls
  anything that acts. If it raises `Stopped`, act no further.
- After an effect began, the outcome must be observed (`observed: true`): the kit never sends an unobserved result. A
  handler that raises after `begin_effect`, or answers unobserved, is settled at once from `observe(entry)` under the
  live fence; with nothing observed, the kit replaces its own slot (`com.responder_replace`), the contract's lost-result
  operation, so the board moves the request to `outcome_unknown`, and `com.reconcile` settles it once `observe` answers.
- `evidence` is at most 8 references `{id: uri, contentHash: sha256:<hex>, label?}`; `artifact_ref(uri, content=…|path=…)`
  hashes the bytes itself. Two ids with one normal form (DEC-0076) name one artifact and are refused.
- `reply: {text, format?, artifacts?}` is posted with `com.reply` before the completion. A reply is not a completion.
  It is a fenced reply, so it carries no `deliverTo` and reaches the requester (DEC-0135 DR-3).
- A handler that raises before any effect completes the request `failed_known` naming only the exception's class.
- The handler checks `ctx.stopped` in long work: after a session loss its answer is not sent.

## When the board says stop, and restarts

| Answer | What the kit does |
|---|---|
| `fenced` | the attempt is another responder's: stop the handler, drop the entry (nothing outside had begun); accepted work on a slot this responder recorded holding stays as `lapsed`, and the next tick asks `com.status` whether the slot [moved](#when-the-operator-moves-a-slot-to-another-session-faa-155) |
| `lease_expired` on accepted work | stop the handler; the board holds the request, and the kit takes it back with `com.responder_replace` and a transfer |
| `authority_changed`, `not_authorized` | stop claiming; one `board.access.needed` event (notify) saying what to ask for (except `not_authorized` on the move-back claim of a moved slot, read as another session's slot, [below](#when-the-operator-moves-a-slot-to-another-session-faa-155)) |
| `fenced` on enroll or claim | another live holder: wait for it to lapse; never replace it on its own initiative. When this responder recorded holding the slot, it first reads `com.status`: a newer generation means the slot [moved](#when-the-operator-moves-a-slot-to-another-session-faa-155), and it is not taken again even after that holder lapses |
| lost after an effect began | keep the entry as `unknown`; `observe(entry)` is asked to settle it with `com.reconcile` |
| Fabric down, hub missing | bounded backoff (2 s doubling to 5 minutes, jittered), one `board.down` event, no spinning |
| one call without an answer while the lease holds | `board.down`, but the session and the running work stay; the call goes again, with the same key, before the lease lapses |
| `revision_conflict` on `com.renew` or `com.progress` | they store nothing: the revision is read again (`com.get`) and the call sent once more; a second one loses the attempt |
| `idempotency_conflict` | a key sent with other content is a defect, not an outage: `board.blocked` (notify) naming it, and the session is left |
| in progress at a reconnect whose slot another session still holds | marked `unknown`; reconciled every five minutes once the slot is this session's |

On restart the checkpoint is read back: settled, queued, claimed or `answered` requests are dropped (`answered`:
the target Project's participant reply answered it, DEC-0098 and DEC-0102; not settled, the requester may still cancel
it, but no longer this responder's); `in_progress` and `outcome_unknown` are
reconciled from what `observe(entry)` answers (observed only; with no observation they stay unknown and notify);
accepted ones go back to this responder with `com.responder_replace {expectedGeneration, transfer}` (unless the slot
moved to another session meanwhile: they stay `lapsed` until take-back or a move back to this session, [below](#when-the-operator-moves-a-slot-to-another-session-faa-155)), whose receipt's
`transferred` (DEC-0078: `{request, revision, attempt}`) carries the new fence. **A Fabric that does not answer
`transferred` yet leaves the request held** (`board.request.held`, notify): the kit never claims it back, because the
contract has no `com.claim` read-back and `com.claim` never moves an accepted request. A known outcome is sent after the
transfer without running the handler again. Every transferred request resumes, one at a time as the responder goes
idle. A transfer makes every fenced idempotency key again, because the old key's digest named the old attempt; a reply
whose answer was lost is first sent again under its old key and fence, so the board's stored receipt says whether it
was posted, and it is never posted twice. That question is asked only after the new attempt is in the checkpoint and the
request is in the resume queue (the old fence is kept beside it as `probe`): when its answer is lost too, or the board
answers `not_available` or `capacity_exceeded`, which do not say whether the reply was stored, the request stays first
in line and the next tick asks again, and a restart asks with the same old fence. A request leaves the resume queue only
once it has resumed: when the `com.complete` that sends a known outcome loses its answer, the next tick sends the same
key again in the same session (FAA-86). `shutdown()` drains, then leaves the session (its DELETE releases the slot).
An idle responder waits 3 s at most for that DELETE (`IDLE_LEAVE_SECONDS`), so an idle stop ends within the org's 5 s
(LC-01, FAA-173); one with work waits up to the session's 15 s client timeout. A board call already in flight when the
stop comes (a poll against a slow hub) runs first; when the service's bounded join ends before the DELETE is sent, the
slot lapses on the board's clock as before. The slot records are forgotten only after
a DELETE Fabric answered with a 2xx (a 404, the session already gone, keeps them: a move made before it ended is read at the next `com.status`), also when a session is dropped on a live board (FAA-163): an unanswered one keeps
them, and the slot lapses in 60 s.

**One capability at a time (FAA-163).** At connect (and every reconnect) the responder starts with no slot. Each
capability's enroll or replace is settled on its own: a refusal of that capability (`capacity_exceeded`,
`invalid_arguments`, any code that is not about the board session) leaves it `retry`, asked again alone after 15 s,
30 s, doubling to 15 minutes, with one `board.slot.refused` event (warning; said again if it is refused again after
the slot was held); its accepted work waits `lapsed` and goes back
by a transfer once the slot is held; `idempotency_window_expired` also reads `com.status` first, so the retry goes
under the epoch Fabric names now (FAA-186). The capabilities after it are recovered as before. A refusal of the board session
(`unreachable`, `session-ended`, `not_available`, `not_authorized` and the other codes in `SESSION_CODES`) leaves the
rest `retry` too, says no `board.slot.refused`, and goes to the responder's fault, which says it by code:
`board.access.needed` for `not_authorized`, `authority_changed` and `credential` (the session is left),
`board.blocked` for a defect (`no-epoch`, `schema-unsupported`, `checkpoint`, `receipt-shape`,
`idempotency_conflict`), and `board.down` for the rest: `unreachable` keeps the session while a held slot's lease runs
(so a lost enroll of one capability is asked again at its next retry), `not_available` keeps it except at connect or recovery with no slot held,
and `session-ended`, `not-running` and the other hub codes drop it (as a fault during connect or recovery does) and
reconnect. A slot whose lease lapsed (`lease_expired`) holds
no lease for that decision.

## When the operator holds work (DEC-0079)

The operator can hold a thread, a whole Project or one (Project, capability) slot from Fabric's own controls. While the
hold lasts, the board refuses **new** work in its scope with `held`, which is always `retryable: true`. It never
refuses a call that settles, reports on or keeps alive work already started (`com.renew`, `com.progress`,
`com.complete`, `com.reconcile`), a cancel or a read. `hold_refuses(tool, target, holds)` / `holdRefuses` is the
contract's matrix, held to its vectors (`test/fixtures/contract/comms-hold-vectors.json`).

| Refused `held` | What the kit does |
|---|---|
| `com.status` names the slot `held: true` at connect | the slot is not enrolled; it pauses |
| `com.enroll`, `com.claim`, `com.responder_replace` | the slot pauses: asked again after 15 s, then 30 s, doubling to 15 minutes; one `board.slot.held` event per capability, and `board.slot.released` when an enroll succeeds again (except the move-back claim of a moved slot, which asks again at the next renewal with no `board.slot.held`, [below](#when-the-operator-moves-a-slot-to-another-session-faa-155)) |
| `com.accept` (the hold came after the claim) | nothing was done: the entry is dropped, the claim lapses and the request waits on the board (`board.request.waiting`); the slot pauses |
| `com.effect_begin` | the effect has not begun: the handler waits (same idempotency key, the pause doubling) while the tick keeps renewing the lease, then begins once the hold is lifted; `ctx.stopped` ends the wait |
| accepted work at restart under a hold | kept as `lapsed`, then taken back with `com.responder_replace` and a transfer once the hold is lifted, never claimed back |

A hold is not an outage: no `board.down`, no notify. Work already accepted keeps running and completes.

A receipt's request may carry `settledBy: "owner"` (DEC-0081): the estate owner settled an `outcome_unknown` request
whose responder was gone. Read it as the owner's attestation, not the responder's; it appears only on `completed` or
`failed_known`, and its absence means the responder settled it.

## When the operator moves a slot to another session (FAA-155)

The contract's DEC-0140 PR-2 (accepted 2026-10-30; in the pin since 0.71.0) lets the operator move a
(Project, capability) slot to another live session of the Project: one transition, as `com.responder_replace` would make
it for the receiving session (generation up, `claimed` back to `queued`, `in_progress` to `outcome_unknown`, `accepted`
held and not transferred). The responder keeps that move instead of undoing it:

- It records the generation it holds each slot at, in the checkpoint file beside the requests (`slots: {<capability>:
  {project, generation, moved?, asking?}}`). The record is written when a receipt's generation changes and before an
  enroll or a replace that can change it; a live holder's renew (about every 20 s) cannot, and writes nothing. At a
  clean leave (the service stopped; the session's DELETE released its slots) the record of a slot with no request left
  in the checkpoint and not moved is forgotten when this session confirmed its generation (held it, paused under the
  operator's hold included, or read it unmoved in `com.status`) and no fenced call has put in doubt since: the slot is
  free, and whoever takes it next is no move. An unconfirmed record stays, since the slot may have moved while the
  service was down, and a move this session saw keeps its record, so a clean stop never undoes it. A paused or
  retrying slot reads `com.status` before each new ask. A move made after the slot's last renew or check and before
  the stop, with no call since, is not seen at the leave: its record is forgotten, and the next start reads the slot
  as free and may enroll it once the other holder lets it go (FAA-187). A file without the record
  reads as before; a kit before 0.53.0 reads the file, ignores the record and drops it at its first checkpoint write. So a service stopped cleanly with no request left in its checkpoint, its DELETE answered 2xx and every slot confirmed
  in that session, rolled back to 0.52 and up again starts as on a first start. Otherwise (a 404, the idle wait running
  out, a slot this session never confirmed, one left retrying before `com.status` answered for it included) its records stay, and the case is the crash case below. After a crash the record stays: if 0.52 then ran, enrolled the slot and
  wrote nothing to the checkpoint, the next 0.53 start reads that enroll as a move; bring it back with the service's take-back action (below).
- An enroll or a replace is written into that record with its key before it is sent (`asking`). When its answer is
  lost, the next connect (or the next enroll) sends the same call again under the same key; the board answers the
  stored receipt, whose generation is this service's own, and the slot is then asked for once more for the new board
  session. A refusal is an answer and drops the `asking` record, so a move that happened meanwhile is still seen; except
  `idempotency_window_expired` (a retired epoch refuses even a repeat), which leaves it unknown whether the call
  landed: the whole record is forgotten and the slot reads as on a first start, never as a move. An
  `asking` record that cannot be written (a full disk) is skipped, as the generation record is: the call goes out
  unrecorded, and a lost answer to it, or a restart before the next receipt is recorded, may then read as a move.
- It reads the slot's generation from `com.status` at every connect (a restart), and after any call refused `fenced`:
  at once for a claim or an enroll, at the next tick for a fenced call on running work. Only a responder with a record
  asks, so a first start sends no extra call. A generation past the recorded one, with no own call of
  this service left unanswered, is a move, whatever made it: the operator, or another session that took the slot while
  this one was away or after it crashed. Before 0.53.0 a restarted responder took such a slot back by itself. So a
  second responder of the same capability is no longer a standby once the slot changed hands: after any change of
  holder it waits for take-back or a move back to its session, not for the other's lapse.
- A `fenced` refusal on accepted work while the slot did not move (the generation unchanged) keeps the entry
  `lapsed`; the next tick takes it back with a transfer and goes on (before 0.53.0 the entry was dropped and the
  request left accepted on the board).
- Then the slot is `moved`: the running handler is told to stop (`ctx.stopped`); a `claimed` entry is dropped (the move
  returned it to the queue); accepted work stays as `lapsed` and work whose effect began as `unknown` (only the slot's
  holder, or the estate owner, reconciles it now). While the slot is moved nothing but the move-back check
  (`com.status` once a renewal, then one `com.claim`, below) is sent for that capability: no `com.renew`,
  `com.complete`, `com.enroll` or `com.responder_replace`, not at recovery after a restart, and not when the new
  holder's lease lapses, nor when com.status later names no generation for the slot (a recorded move stays until
  take-back or a move back). Accepted requests stay `accepted` on the board, unanswered, until the slot is taken back
  or moved back (CT-175 will hand them to the new holder). One `board.slot.moved` event (warning, notify) says so, once, also across restarts
  (the record keeps `moved`).
- A responder that never held the slot (a first start: no record, or a record of another Project), or whose record
  equals the current generation, behaves as before: it enrolls, recovers and replaces its own lapsed work. A recorded or
  reported generation that is not an integer of at least 1, or one not past the record (lower: the record is not this
  board's), is not a move either: today's behaviour, not a stop, and the next receipt rewrites the record. A crash
  between a receipt and its record's write leaves the `asking` record: the next start asks again under the same key and
  records its own generation. Only a replay the board refuses, or one that ran for the first time (`repeated: false`)
  after the slot had moved past the record, reads as a move: the safe side; a slot such a replay took is left to lapse
  unused. A generation written `2.0` is `2`.
- The operator may move the slot back to this session in Fabric (DEC-0140 PR-2), which this client cannot hear. No
  Fabric release through v0.3.19 (2026-11-11) offers the operator's move (the control is CT-174's in Fabric, its agent twin CT-181 in the contract, then CT-125),
  so today every move is another session taking the slot and take-back is the route back; the check below is ready
  for the move. While
  a slot is moved the responder reads `com.status` once a renewal (20 s) and, when the slot's generation is past the
  recorded move, sends one `com.claim` under a fresh key, as PR-2's "Learning the slot is its own" says (FAA-165,
  0.60.0); the move itself drops the claim key of that capability, whose receipt the move made dead. A claim that
  lands is the slot held again: the record loses `moved`, the request it handed out is worked (with none, its own
  enroll renews the lease at once), accepted work left `lapsed` comes back with a transfer, and a later move is said
  again. `lease_expired` (the move reached this session and its lease lapsed first) enrolls again. `held` asks again
  at the next renewal. `idempotency_window_expired` or `capacity_exceeded` asks again at the next renewal under a
  fresh key, recording nothing. `fenced`, or any other refusal that is not the board session's (`not_authorized` counted with them, since a
  non-holder's claim may be refused so), is another session's slot:
  recorded as `moved` at that generation, so it is not asked about twice. A claim whose answer was lost (`unreachable`) is asked again under the same key at the next renewal, so a claim that
  landed is not stranded; until then it counts as at most a lease from that key's first send (a fresh key starts
  its own, and it counts only while more than the 10 s margin of that lease is left, then no more, as a lapsed slot), so a second lost answer keeps
  the session (finding 38). A replayed receipt from a generation older than `com.status` shows (a move away and back meanwhile) is
  dead: its key is dropped and a fresh key asks at the next renewal. A take-back drops the capability's claim key too, so a request a move-back claim handed out while the take-back raced
  it waits for its attempt's lease (60 s) before it is claimed again (a take-back that lands before the move-back check makes its claim key
  leaves that key to the claim loop, which works the request at once). Nothing is asked while the responder stops. It is never an enroll or a replace on a slot another session holds, and it waits
  while other work runs: a move back during a job longer than the lease (60 s) may lapse and be lost to another
  session, after which take-back, or another move back to this session, brings it back.
- Otherwise only the operator brings the slot back: `take_back(capability)` (`takeBack`) forgets the record, and wins over a move
  being read at the same time: the move is written under the responder's lock (Node: on the fence queue, after any fenced
  call in flight) and only while the record is unchanged (FAA-158). Never edit the
  checkpoint's `slots` record by hand to undo a move. In the same board
  session the next tick enrolls once the other session lets the slot go (a live holder is waited for) and takes the work
  left `lapsed` back with a transfer. A restart or reconnect before that, with accepted work waiting for the slot, takes it
  back at once by `com.responder_replace`, as a restart did before 0.53.0: the operator asked for the slot back, so the
  other session is replaced. In recovery, a refusal that leaves no slot held reconnects; one that leaves some held keeps
  the session and serves them. The kit gives it no route of its own. The reference service (`sample_service.py`) offers
  it on its dashboard (FAA-157): a moved slot shows a Take back button that posts `POST /api/board/take-back` from the
  operator's signed-in session with the `X-Fabric-Request` header; the service token alone is refused. Since 0.56.0 the
  button has its tool, `board.take-back` with `{capability}`, declared under `extensions/actions/0.1` with gate
  `relayed` and target `capability`, and a capability of the manifest like every tool the well-known lists
  (`interop.well-known-capabilities`): an agent whose MCP client sets `_meta` calls it over `/mcp` with the operator's
  decision in `_meta.decision` (a call without one is `operator-decision-required`); Claude Code and Codex send
  arguments only, so until CT-125 they hand the operator the page as Fabric Dashboards' `open_link`. Either door records
  the take-back as a `board.slot.returned` event (info, the capability as its subject) whose sentence says the route in
  words and whose `data` holds `by`, `via` and the `caller` (none when the feed refuses the caller), never the decision's words; a repeat after a lost answer is answered `{capability, moved: false}`. A service built on the kit declares it as an operator action, a button with its tool ([Every button has a
  tool](../SKILL.md), `fabric-actions/0.1`) with gate `relayed` (the operator's decision), never `none`, so a call
  without the operator's relayed decision is refused; on a server that reads mandates (`agent_id`) it also names its effect class, for example
  `change-policy` (DEC-0125); the operator reaches it through an agent that relays their decision in `_meta`, the
  service's page or its elicitation (Claude Code and Codex, which cannot set `_meta`, wait for CT-125's forwarding), and the service names it in its docs; otherwise a moved slot stays moved for good today (no Fabric release offers the operator's move back, above). The
  hand-over of accepted requests to another session (contract CT-175) waits for Fabric's session surface.

## What a board session may call

A board session (`fabric.board.join`) is served the respond scope only: `com.status`, `com.list`, `com.get`,
`com.reply` (the fenced form), `com.enroll`, `com.claim`, `com.renew`, `com.accept`, `com.progress`,
`com.effect_begin`, `com.complete`, `com.reconcile`, `com.responder_replace`. `BoardSession.call` refuses anything else
locally (`not-in-scope`): never `com.submit`, `com.cancel`, `com.read_ack` or `com.directory`.

The idempotency epoch comes from `com.status`. A Fabric built before its board-session fix tells a board session none:
the kit fails closed (`no-epoch`, `board.blocked`) instead of guessing one.

## Looking a Project up in the directory (FAC-SEM-107)

The directory belongs to a Project session (a coding agent's, or a launched one). Before looking a Project up in a
`com.directory` page, `find_project(page, project_id, capability=None)` / `findProject` checks the page: closed shapes
(no count, holder or generation) and FAC-SEM-107: each Project once, each capability once per Project. Project ids and
capability names compare **exactly as written** (DEC-0077; they are not URIs, so not by normal form). A page that fails
raises `directory-invalid` rather than answering; an unlisted Project may still be addressed by an id already held.

## Events, the probe and the live smoke

Events go to `emit(kind, level, text, notify=…, subject=…, data=…)` (`JsonlEventLog.append` fits: every level is one
of its `info`, `notice`, `warning`, `error`; `subject` is `{type, id}`, the notice's request, else its capability, else
its episode (such as a block's cause), else the Project; in Python it goes only to an `emit` whose signature names a `subject`
parameter with no value bound, as `JsonlEventLog.append` does, and any other `emit`, one with only `**kwargs`, one with
a subject bound by `functools.partial` (which then stands) or one whose signature cannot be read, is called once, without
one, as before 0.56.0; the Node responder always passes it in its options, which an `emit` that does not read it ignores) with
`data {schema, value}`
checked by FAC-SEM-101 (no credential in data): `board.request.completed`, `board.request.refused`,
`board.request.skipped`, `board.request.reconciled`, `board.request.held`, `board.attempt.lost`,
`board.reconcile.needed`, `board.slot.contested`, `board.slot.moved`, `board.slot.refused`, `board.access.needed`, `board.blocked`,
`board.down`, each notifying episode said once, and `board.outcome.invalid` (warning) when a handler's outcome fails
its checks and is not sent, and `board.request.mandate_unread` (warning) when a request's mandate is not read (above). The operator's hold (below) adds `board.held`, `board.slot.held`,
`board.slot.released` and `board.request.waiting`. The reference service adds `board.slot.returned` at a take-back.

`check_service.py <id> [--board-kit <the service's fabric_board.py or fabric-board.mjs>]` rule **board.responder**:
`NOT_RUN` when the well-known `protocols` names no `fabric-project-comms` revision; `FAIL` for a revision this kit does
not read or a fixture conversation that goes wrong; `PASS` when the kit's `self_check()` / `selfCheck()` passes (the
whole conversation, a fenced accept, a session without an epoch; no Fabric touched).

The live smoke runs only against a disposable Fabric (built app and its own stack), never an operator's estate: Fabric's
COM-03 packet (`docs/evidence/plans/2026-10-04-project-communications.md`) has the exact commands: register
`fabric-mcp` for Claude Code and Codex, the operator allows `session.enroll` and `board.respond`
(`board:<example-agent project>/<capability>`), Claude submits a request, the responder enrolls, claims, accepts and
completes, then is killed mid-claim and replaced. Without that Fabric, report it `NOT_RUN`.

## The API

Python (`fabric_hub`): `fabric_root(platform, env)`, `locate_hub(root=None, alive=pid_alive, estate=None, now=None)`,
`read_door_token(location)`, `read_credential(path)`, `HubClient(root=None, *, alive, timeout, estate, post)` with
`request_board_access(agent_id, project_id, capabilities, reason)`, `poll_access(request_id, poll_secret,
credential_file)`, `join_board(project_id, credential_file) -> BoardGrant`, `call_door(tool, args)`,
`call_binding(tool, args, credential_file)`; `Backoff(first=2, cap=300, jitter=0.2, floor=1)`; `HubError(code,
message, retryable, data)`.

Python (`fabric_board`): `Responder(*, hub, project_id, capabilities, credential_file, checkpoint_file, handler,
admit, observe=None, emit=None, service, now, rand, spawn, session_factory, agent_id=None, mandate_from=None, wall=time.time)`
with `step()`, `run(stop, drain)`, `shutdown(drain)`, `take_back(capability)`; `WorkContext.progress(note)`,
`.begin_effect(summary)`, `.stopped`, `.mandate`, `.mandate_covers(call)`; `PERSONAL_BOARD`; `BoardSession(grant)`;
`Checkpoint(path)`; `comms_canonical(value)`, `comms_digest(operation, value)`, `receipt_problems(value, op)`,
`refusal_problems(value)`, `directory_findings(page)`, `directory_problems(page)`, `find_project(page, project_id,
capability)`, `artifact_ref(uri, content|path, label)`, `evidence_problems(list)`, `outcome_problems(outcome,
effect_began)`, `self_check()`; `BoardError`, `Stopped`.

Node: the same names in camelCase (`locateHub(root, {alive, estate, now})`, `new HubClient(root, {alive, timeout,
estate, post})`, `new Responder({...})` with async `step()`, `run({signal, drain})`, `shutdown(drain)`,
`takeBack(capability)`; `await ctx.progress(note)`, `await ctx.beginEffect(summary)`, `ctx.mandate`, `ctx.mandateCovers(call)`;
the options `agentId`, `mandateFrom` and `wall` (milliseconds); `selfCheck()`). Both kits read and write the same checkpoint file.
