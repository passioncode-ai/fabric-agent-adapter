# A wait is not a stop

The operator's rule (board message `bfc0e14e`, 2026-11-12, FAA-300). Finish a unit of work, then take the next one in
the same turn: an open task on the board, a board request addressed to your Project, the handoff's next task.
**A turn never ends with "shall I continue?"**: the task you were given is the permission for every step inside it.

## Every wait is recorded

A wait (on a person's answer, a peer Project's reply, CI, a release, a scheduled run) carries four things:

- **the condition** that ends it, checkable (`the PR's checks are green`, `request 1a2b3c4d is answered`);
- **the owner** of that condition (a person, a Project, a CI system) and where it was asked;
- **the next action**: exactly what you do when it clears;
- **the watcher**: the background process or scheduler that observes the condition and continues that action, or an
  honest "no watcher" when none is available. Never claim a watcher that is not running.

While you wait, send `fabric_heartbeat` with `phase: "waiting"`: `waitingOn: {kind: "question", id}` for a question you
asked with `fabric_question_ask`, `{kind: "grant", id}` for an access request, `{kind: "continuation", id}` for work
handed on; otherwise the condition in one line of `note`. Then take an independent task; work that depends on the wait
goes on an isolated branch and lands when its prerequisite does. When the wait clears, release what you held for it.

A board request is waited on with `fabric_session.py watch-mail` under your own background watcher
([project board](project-board.md)); a session process does not outlive the session, so a wait that must survive it
needs a durable trigger that already exists, recorded in the handoff.

## The end of a turn

**A turn ends with one line per open wait**: what it waits on, who owns it, what happens next and which watcher acts
(or "no watcher"). No open wait: say so. The same lines go into the handoff.

## The checklist

- [ ] The unit's checks green, then the next task taken in the same turn.
- [ ] Each wait: condition, owner, next action, watcher or "no watcher".
- [ ] `fabric_heartbeat` with `phase: "waiting"` and `waitingOn` (or a `note`) before the wait.
- [ ] The turn's last lines: one per open wait; no "shall I continue?".
