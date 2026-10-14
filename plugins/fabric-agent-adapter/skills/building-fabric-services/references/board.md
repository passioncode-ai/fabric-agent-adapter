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
- What a board session may call
- Looking a Project up in the directory (FAC-SEM-107)
- Events, the probe and the live smoke
- The API

## What a responder is, and the grant it needs

A **request** is addressed to a Project and one of its capabilities (`video.render`), never to a service. One
**responder slot** exists per Project and capability; a service holds it under a **`board.respond` grant** the
operator gives in Fabric (Agents & access): callee `fabric`, capability `board.respond`, resource
`board:<project id>/<capability>`. A pid, a descriptor or a localhost origin authorizes nothing.

1. Ask once, through the hub's door: `HubClient().request_board_access(agent_id, project_id, [capability], reason)`
   (`requestBoardAccess`). Keep the answer's `pollSecret` in memory or a 0600 file.
2. Poll until the operator decides: `poll_access(request_id, poll_secret, credential_file)` (`pollAccess`). On Allow the
   binding credential, shown once, goes into `credential_file` (0600, atomic) and never into the answer, a log or argv.
   Keep the file in the service's data directory or the operator's vault.
3. Each connection joins with `fabric.board.join {projectId}` (`join_board` / `joinBoard`). It re-reads `hub.json`,
   checks the pid it names is alive, and only then sends the credential. A missing grant is `HubError` code
   `not_authorized` whose `data.ask` holds the arguments to ask with.

## Wiring it into the service

The responder runs inside the service process, started after the instance lock like every other piece of state
(SKILL.md, Step 3). [`sample_service.py`](../scripts/sample_service.py) does it behind `serve --board-project <uuid>`,
off by default:

```python
import fabric_board as fbd, fabric_hub as fhb

responder = fbd.Responder(
    hub=fhb.HubClient(), project_id=PROJECT, capabilities=["video.render"],
    credential_file=dirs["data"] / "board.credential", checkpoint_file=dirs["data"] / "board-checkpoint.json",
    handler=render, admit=gate, observe=look_on_disk, emit=log.append, service="example-agent")
threading.Thread(target=responder.run, args=(stop_event, 5.0), daemon=True).start()   # SIGTERM: set stop_event
```

Node: `new Responder({...same names in camelCase})`, then `responder.run({ signal, drain })`. A service that lists
`fabric-project-comms/0.1` in its well-known `protocols` (DEC-0067: only once its hosts are pinned at or after it)
declares that it answers board requests; the probe checks that declaration.

## The loop, step by step

One tick every 15 s ± 5 s (`step()` answers the wait):

| Step | Board call | Checkpoint written first |
|---|---|---|
| hold the slot | `com.enroll` (again at about 20 s while idle: the holder's enroll renews its 60 s lease) | — |
| take a request | `com.claim`, the same key while nothing is claimable | `claimed` |
| read it | `com.get`: the digest must equal the claim's, and the request must name this Project and capability | — |
| accept | `com.accept` with the claim's exact fence (request, generation, attempt, digest, revision) | `accepting`, then `accepted` |
| act | `com.effect_begin`, only when the handler calls `ctx.begin_effect()` | `effect-beginning`, then `in-progress` |
| while working | `com.renew` at about 20 s; `com.progress` for `ctx.progress(note)` | — |
| answer | `com.reply` (fenced) when the outcome carries `reply` | `replying` |
| settle | `com.complete {state, observed, summary?, evidence?}` | `completing`, then the entry is dropped |

The checkpoint is fsynced before each call it announces. A write that fails stops the step (`board.blocked`): nothing
is sent that the checkpoint does not know about. A lost answer is sent again with the same idempotency key, so the
board returns the first receipt. One request is in flight at a time. Lease times are the board's; the kit renews on its
own monotonic clock and never reasons from `leaseExpiresAt`.

## The request is data: the input gate

`admit(request)` is required: it is the service's own input gate. It answers `None` to admit or one sentence saying
why not; a refusal accepts the request and completes it `failed_known` with that sentence, so the requester learns it
and the request does not bounce. A redacted body is refused the same way. The kit never hands a body to a model, a
shell or a tool; what the handler does with an admitted body — and the checks it needs before a model, a tool or a
spend sees it — is the service's own responsibility. A message never carries an approval.

## Effects, observation, evidence and the reply

- Call `ctx.begin_effect(summary)` — and let it return — before the handler spends, writes outside the service or calls
  anything that acts. If it raises `Stopped`, act no further.
- After an effect began, the outcome must be observed (`observed: true`): the kit never sends an unobserved result; the
  request stays unknown and is reconciled later.
- `evidence` is at most 8 references `{id: uri, contentHash: sha256:<hex>, label?}`; `artifact_ref(uri, content=…|path=…)`
  hashes the bytes itself. Two ids with one normal form (DEC-0076) name one artifact and are refused.
- `reply: {text, format?, artifacts?}` is posted with `com.reply` before the completion. A reply is not a completion.
- A handler that raises before any effect completes the request `failed_known` naming only the exception's class.
- The handler checks `ctx.stopped` in long work: after a session loss its answer is not sent.

## When the board says stop, and restarts

| Answer | What the kit does |
|---|---|
| `fenced` | the attempt is another responder's: stop the handler, drop the entry (nothing outside had begun) |
| `lease_expired` on accepted work | stop the handler; the board holds the request, and the kit takes it back with `com.responder_replace` and a transfer |
| `authority_changed`, `not_authorized` | stop claiming; one `board.access.needed` event (notify) saying what to ask for |
| `fenced` on enroll | another live holder: wait for it to lapse; never replace it on its own initiative |
| lost after an effect began | keep the entry as `unknown`; `observe(entry)` is asked to settle it with `com.reconcile` |
| Fabric down, hub missing | bounded backoff (2 s doubling to 5 minutes, jittered), one `board.down` event, no spinning |

On restart the checkpoint is read back: settled or queued requests are dropped; `in_progress` and `outcome_unknown` are
reconciled from what `observe(entry)` answers (observed only; with no observation they stay unknown and notify);
accepted ones go back to this responder with `com.responder_replace {expectedGeneration, transfer}`, whose receipt's
`transferred` (DEC-0078: `{request, revision, attempt}`) carries the new fence. **A Fabric that does not answer
`transferred` yet leaves the request held** (`board.request.held`, notify): the kit never claims it back, because the
contract has no `com.claim` read-back and `com.claim` never moves an accepted request. A known outcome is sent after the
transfer without running the handler again. `shutdown()` drains, then leaves the session (its DELETE releases the slot).

## When the operator holds work (DEC-0079)

The operator can hold a thread, a whole Project or one (Project, capability) slot from Fabric's own controls. While the
hold lasts, the board refuses **new** work in its scope with `held`, which is always `retryable: true`. It never
refuses a call that settles, reports on or keeps alive work already started (`com.renew`, `com.progress`,
`com.complete`, `com.reconcile`), a cancel or a read. `hold_refuses(tool, target, holds)` / `holdRefuses` is the
contract's matrix, held to its vectors (`test/fixtures/contract/comms-hold-vectors.json`).

| Refused `held` | What the kit does |
|---|---|
| `com.status` names the slot `held: true` at connect | the slot is not enrolled; it pauses |
| `com.enroll`, `com.claim`, `com.responder_replace` | the slot pauses: asked again after 15 s, then 30 s, doubling to 15 minutes; one `board.slot.held` event per capability, and `board.slot.released` when an enroll succeeds again |
| `com.accept` (the hold came after the claim) | nothing was done: the entry is dropped, the claim lapses and the request waits on the board (`board.request.waiting`); the slot pauses |
| `com.effect_begin` | the effect has not begun: the handler waits (same idempotency key, the pause doubling) while the tick keeps renewing the lease, then begins once the hold is lifted; `ctx.stopped` ends the wait |
| accepted work at restart under a hold | kept as `lapsed`, then taken back with `com.responder_replace` and a transfer once the hold is lifted — never claimed back |

A hold is not an outage: no `board.down`, no notify. Work already accepted keeps running and completes.

A receipt's request may carry `settledBy: "owner"` (DEC-0081): the estate owner settled an `outcome_unknown` request
whose responder was gone. Read it as the owner's attestation, not the responder's; it appears only on `completed` or
`failed_known`, and its absence means the responder settled it.

## What a board session may call

A board session (`fabric.board.join`) is served the respond scope only: `com.status`, `com.list`, `com.get`,
`com.reply` (the fenced form), `com.enroll`, `com.claim`, `com.renew`, `com.accept`, `com.progress`,
`com.effect_begin`, `com.complete`, `com.reconcile`, `com.responder_replace`. `BoardSession.call` refuses anything else
locally (`not-in-scope`) — never `com.submit`, `com.cancel`, `com.read_ack` or `com.directory`.

The idempotency epoch comes from `com.status`. A Fabric built before its board-session fix tells a board session none:
the kit fails closed (`no-epoch`, `board.blocked`) instead of guessing one.

## Looking a Project up in the directory (FAC-SEM-107)

The directory belongs to a Project session (a coding agent's, or a launched one). Before looking a Project up in a
`com.directory` page, `find_project(page, project_id, capability=None)` / `findProject` checks the page: closed shapes
(no count, holder or generation) and FAC-SEM-107 — each Project once, each capability once per Project. Project ids and
capability names compare **exactly as written** (DEC-0077; they are not URIs, so not by normal form). A page that fails
raises `directory-invalid` rather than answering; an unlisted Project may still be addressed by an id already held.

## Events, the probe and the live smoke

Events go to `emit(kind, level, text, notify=…, data=…)` — `JsonlEventLog.append` fits — with `data {schema, value}`
checked by FAC-SEM-101 (no credential in data): `board.request.completed`, `board.request.refused`,
`board.request.skipped`, `board.request.reconciled`, `board.request.held`, `board.attempt.lost`,
`board.reconcile.needed`, `board.slot.contested`, `board.access.needed`, `board.blocked`, `board.down`, each
notifying episode said once.

`check_service.py <id> [--board-kit <the service's fabric_board.py or fabric-board.mjs>]` rule **board.responder**:
`NOT_RUN` when the well-known `protocols` names no `fabric-project-comms` revision; `FAIL` for a revision this kit does
not read or a fixture conversation that goes wrong; `PASS` when the kit's `self_check()` / `selfCheck()` passes (the
whole conversation, a fenced accept, a session without an epoch — no Fabric touched).

The live smoke runs only against a disposable Fabric (built app and its own stack), never an operator's estate: Fabric's
COM-03 packet (`docs/evidence/plans/2026-10-04-project-communications.md`) has the exact commands — register
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
admit, observe=None, emit=None, service, now, rand, spawn, session_factory)` with `step()`, `run(stop, drain)`,
`shutdown(drain)`; `WorkContext.progress(note)`, `.begin_effect(summary)`, `.stopped`; `BoardSession(grant)`;
`Checkpoint(path)`; `comms_canonical(value)`, `comms_digest(operation, value)`, `receipt_problems(value, op)`,
`refusal_problems(value)`, `directory_findings(page)`, `directory_problems(page)`, `find_project(page, project_id,
capability)`, `artifact_ref(uri, content|path, label)`, `evidence_problems(list)`, `outcome_problems(outcome,
effect_began)`, `self_check()`; `BoardError`, `Stopped`.

Node: the same names in camelCase (`locateHub(root, {alive, estate, now})`, `new HubClient(root, {alive, timeout,
estate, post})`, `new Responder({...})` with async `step()`, `run({signal, drain})`, `shutdown(drain)`; `await
ctx.progress(note)`, `await ctx.beginEffect(summary)`; `selfCheck()`). Both kits read and write the same checkpoint file.
