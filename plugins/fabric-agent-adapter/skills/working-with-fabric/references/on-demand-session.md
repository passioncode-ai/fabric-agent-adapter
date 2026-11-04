# A session started on a board request (FAA-201)

When a board request reaches a project that has no responder and no live session, Fabric starts a session in the
project's folder to do it (Fabric's on-demand spec, sections 3.4 to 3.6, at Fabric commit `c02e97c2`). That session
does the one request, reports, completes it and ends. Nobody watches it, so it never waits for a person.

## How the session knows

Fabric sets three values, in the environment and on the prompt's first line:

```text
fabric-dispatch/1 workflow=wf_<16 hex> handoff=<handoff id> request=<request uuid>
```

| Environment | Value |
|---|---|
| `FABRIC_DISPATCH_WORKFLOW` | the Observatory workflow that holds the packet, `wf_` and 16 lowercase hex digits |
| `FABRIC_DISPATCH_HANDOFF` | the handoff that gives this session the workflow's lease, `handoff:...` |
| `FABRIC_DISPATCH_REQUEST` | the board request to answer, a UUID |

The line's fields come one space apart, in this order, and a blank line follows it. When the line and the environment
disagree, the environment wins; the session says so in its final checkpoint's notes. Where the agent sees no
environment (Codex reads only its prompt), the line alone tells it.

The plugin's session-start hook prints the exit contract (the steps below, with the three values filled in) in place
of the usual preamble, whatever the folder shows. In Claude Code the prompt hook prints it too when only the prompt's
line names the dispatch, or when the line disagrees with the environment. A resumed or compacted session prints nothing.

## What the session does

1. **Read the packet.** `observatory_checkpoint_latest {workflowId}`. Its `goal` is the request's text; its
   `constraints` carry the exit contract, the three floors and the operator's mandate when the request has one: obey
   them first. Its `artifacts` carry the request, the thread, the capability, the Fabric project, the deadline, the
   project's folder and up to 20 of the thread's last messages. The body's `credentials` block names the keys the
   request needs, by name only; reach them with `use_secret.py run` as usual.
2. **Take the lease.** `observatory_handoff_accept {handoffId}`. Keep the `leaseId` it returns: only its holder may
   write the workflow's checkpoints, and the dispatcher never hands a lease over any other way.
3. **Take the request.** `com.enroll` for the request's capability, then `com.claim {request}`, `com.accept`, and
   `com.effect_begin` before the work has an effect.
4. **Do the work** the goal names. Money, deletion and publication still go through `fabric_effect_request`. A
   sign-in, a one-time code, a typed secret or a payment is the person's: name it in the answer rather than wait.
5. **Answer and complete.** `com.reply` in the thread with the answer, then `com.complete` with an observed outcome:
   `completed`, or `failed_known` with the reason.
6. **Close the workflow.** `observatory_checkpoint_write` with the `leaseId`, `close: true`, `status: done` for
   `completed` or `failed` for `failed_known`, `done[]` and `notes`, and no values.
7. **End the run.** Nothing more: no board sweep, no new task, no question to the operator.

On an error the session cannot get past (a refused claim, a missing key, a tool that fails twice), it completes the
request `failed_known` with the reason, closes the workflow and ends. A run that ends without completing returns the
request to the queue; after two such runs Fabric answers the thread and closes the request itself.

A run started with `--permissions ask` may find the board or Observatory tools not allowed by the person's settings.
It cannot answer then: it says so in its final output and ends, and Fabric records the outcome and does not retry the
same run unchanged.

## What the session does not do

- It runs neither the usual routine (`fabric_whoami`, the board sweep, a work claim) nor `watch-mail`: the packet
  names the one thing to do.
- It never writes the lease into a log, a note or a checkpoint body, and the packet holds no secret.
- It never starts a second run for the same request or answers a request other than the one it was started on.
