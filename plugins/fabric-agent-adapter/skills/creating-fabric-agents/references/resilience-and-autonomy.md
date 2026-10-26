# Resilience and autonomy: what kept agents working

Read when designing an agent's loop, its model calls, its spend and its stops, before the first
stage that calls a model or spends money. These rules come from a retrospective of about twenty
production agents (2026-10-17): each rule names the failure that taught it, generalized, and the
mechanism that held after the fix. Every rule is cheaper to build in than to retrofit.

## Contents

- Limits are pauses
- Model answers are untrusted until accepted
- Money is a ledger
- Autonomy: decide, record, continue
- Verification you can believe
- Operations that survive restarts
- Secrets and confinement
- Text for people
- Checklist

## Limits are pauses

1. **A provider or subscription limit pauses the job; it never fails it.** Keep the job `working` and
   write its `statusMessage` in the contract's pause grammar, `quota-exhausted` or
   `quota-exhausted until <UTC instant>` (optionally `: <text>`, at most 500 characters), with
   `pollIntervalMs` reaching the reset; resume from the same stage. Only a job its provider will not
   resume ends `failed` with `error: {code: "quota-exhausted", message, data: {retryable, resetsAt?}}`:
   `retryable: false` when a person must act, and `resetsAt` (UTC, `T` and `Z`, at most three
   fraction digits) only when `retryable: true` (contract DEC-0087, `FAC-SEM-119`). Failing a job a
   limit only paused cost callers whole jobs and resubmits.
2. **Resume first.** Every worker reads its own state (checkpoint, worktree, branches, open
   pull requests, notes) before it acts, and continues from there. Relaunching from scratch
   after a limit recreated work over committed work and re-issued credentials already held.
3. **A silent worker is a limit until proven otherwise.** A watcher that sees no progress for N
   minutes, or limit text in the last output, resumes the run with the *same* run id.
4. **Keep prompt cache keys stable across a resume.** One changed argument that every prompt
   carries (today's date) re-keyed a finished stage and paid for it again.
5. **Count only the job's own failures toward its retry limit.** A lost lease, a busy lock or a
   provider outage is bounded by a time budget instead; five infrastructure stops a day ended a
   healthy phase as FAILED.
6. **Match concurrency to the account's rate, and cool down after a 429** per provider door: ten
   parallel workers met a 429 about hourly and each lost a whole batch; three to five heavy ones,
   resumed in batches, did not. A "busy" or "still starting" dependency is retried a bounded number
   of times with spacing (a handful, seconds apart, only on refusals classified as transient):
   never once, never forever.
7. **Inside a fallback chain, do not retry a provider that answered 429 or timed out**: move to
   the next one. Retries there stalled a waiting user. Stagger many resumes; bound each worker's
   working set (a narrow time window, a prefix), so one stop does not become a burst.

8. **Move a refused request to another account at most once, and only before any byte reached the
   client**: a replay after streaming began duplicated output. Persist a provider's `Retry-After`
   across restarts; a check inside the hold answers the stored observation instead of probing.

## Model answers are untrusted until accepted

1. **"Answered" is not "usable".** Each call site has its own `accept(text)`: the parser the
   result must pass. Empty content, a refusal, a truncation (`finish_reason: length`) or an
   unparseable answer is a failure, and only an accepted answer may be cached. A cached
   unreadable answer once served "0 labelled" for hours.
2. **Fallbacks cross vendors.** A chain is an ordered list of models from different vendors; a
   same-vendor fallback refuses the same inputs. Build the chain where a test can refuse a lane
   with no other-vendor route, and act on a new fallback only after measuring it.
3. **The checker is never the drafter's vendor.** Choose it per turn from the model that
   *actually* drafted (a fallback may have), in the router, not in configuration. No checker
   left, or a checker outage, means hold or stay silent, never ship unchecked.
4. **Size the output budget for the answer, not the input.** Reasoning tokens eat `max_tokens`:
   a judge capped at 800 tokens returned no JSON in 8 of 14 calls. Give judges room or turn
   reasoning off for that route; on `length`, retry once with a larger cap.
5. **Run code checks before model checks**, and degrade to a fixed safe reply with a reason code.
6. **A model's word verifies nothing.** A fact is verified by stored source text (or two truly
   independent sources); an effect by the system of record it lands in, never by the page, a
   flag the model set, or its "done".
7. **A coding agent runs only on a model it knows.** One CLI agent on an unfamiliar vendor's model
   read its instructions and ended its turn with nothing written; measure each (agent, model)
   pair live before making it a default.
8. **Pin what the agent says about itself.** A short block of true facts (what it can see, its
   pipeline, its limits) lives in code; a test fails when a fact drifts. Forbid promises the
   pipeline cannot keep.

## Money is a ledger

1. **Unknown is unknown, never zero** (in cost, in verdicts, in health), and nothing acts on it.
   A missing price is a high estimate, a missing field is `NOT_RUN`, never a pass; a probe that
   timed out is "unreadable", not "credential rejected"; a cooldown that could not be read is not
   "never sent". An owner's refusal inside a successful response (`ok: false` over a 200) is a
   refusal, never an empty result.
2. **Persist the attempt before dispatch** (its route and a hash of its prompt) and finalize it
   in `finally`; spend is Σ actual + Σ estimate for attempts without an actual. In-memory counters
   reset on every resume. A call that broke before the provider answered is reconciled against
   the provider's own history by that route and hash, never guessed; one provider request id
   belongs to exactly one ledger row.
3. **Check the cap before every HTTP attempt, retries included**, with one stop rule; record the
   provider's own reported cost per call; count reserved or held tokens as spent.
4. **A resend of an unknown outcome reuses its idempotency key, or does not happen.** Derive
   keys from the intent (action and entity, or run and step), never from a clock or a random
   value, and make them unique in storage: time-and-random keys let redelivered requests charge
   again. A write whose effect is uncertain ends `failed` with the code `outcome-unknown`; only an
   observed result settles it, and a new key there pays twice. A caller acts on each answer as the
   contract's `jobCallerAction` does: wait out a pause, resend a retryable `quota-exhausted` under the
   same key after `resetsAt`, hand a non-retryable one or `limit-reached` to a person, reconcile an
   `outcome-unknown`, and never resend it.
5. **A client error at submit is a rejection, not a lost task.** Settle it with known usage (zero
   if none), release the reserved money in the same transaction, and never resend the identical
   request; a 4xx while polling is still a lost task.
6. **A failed outer job cancels the paid work it started**, and a cancel is a row the worker reads
   at every claim and checkpoint, never an in-memory flag that a restart forgets.
7. **Reuse what was paid for.** A restarted stage looks up the job's successful call with the
   same route, prompt version and inputs before calling again (one restart made 117 paid calls
   where 49 sufficed). Cache keys are content plus definition, never an identity alone.
8. **A rerun after an interruption calls read-only tools until its open outcomes are reconciled**;
   an idempotency key covers the content as well as the run, so a retried run that asks a new
   question is not refused as a conflict.
9. **Deny spending tools by enumerated name, and test the list**: a provider's newer tools were
   missing from a deny list while older ones were denied.

## Autonomy: decide, record, continue

1. **An open question is a decision to make.** Decide from the recorded decisions, then the
   goal, then the safest reversible option; write the decision and its source where the work
   lives; batch the questions only a person can answer (sign-in, consent, payment, a typed
   secret) and keep working around them.
2. **Nothing in a user's path waits for a human approval.** Send now or not at all; when unsure,
   say so, open a recorded question, and answer again automatically when the knowledge changes.
   Drafts awaiting approval waited for days.
3. **Every wait lives in durable storage**, rebuilt on start from a "debt" query; timers in
   process memory died with every restart. A wait that must outlive a session (a credential that
   has not landed yet) is an operating-system job, not a session's background task.
4. **Stop at the third round.** Tuning wording or patching one heuristic a third time means
   splitting the change or replacing the mechanism with one invariant and a property test.
   Write a review's exit criterion before its rounds start, and block only on what breaks a
   documented promise; the rest becomes a board row with its evidence.
5. **Find the real cause before telling a person what to do**: a full disk once read as "the
   service stopped" while the service was healthy; check free space and the service's own health
   first.
6. **Background chores never hold a finished command open**, unattended runs skip them, and an
   unattended `--yes` never reverses a "no" a person saved.

7. **When a peer waits on your decision, make it**, mark it reversible, record it where the work
   lives and reply naming the record; a platform once built nothing for days waiting on a
   definition. Release a coordination lease in the same step as the commit that used it, the
   failure path included.
8. **Hand work over only while it is alive**, and claim each hand-over exactly once by an exclusive
   create; a forgotten workflow was handed over twice.

### In a Fabric project

An agent that works in a project through Fabric follows Fabric's rule `work.check-every-three-minutes`: every three
minutes while it works, and before any wait, it calls `fabric_work_list`, acts first on `nudges` and
`waiting_for_you`, then reads its unread board answers (`com.list {unread: true}`, then `com.read_ack`), and never
leaves a held task still. The working-with-fabric skill's Step 5 carries it; Fabric serves it through `fabric_whoami`.

## Verification you can believe

1. **A test counts once it was watched failing against a planted defect** (clear bytecode caches
   first: stale bytecode reported mutants killed); a mutation battery
   asserts its own reach ("no tests ran" is not "all plants survived"). Exercise every guard
   with a must-catch and a must-pass case.
2. **Write expectations out; never compute them from the code under test**, and run a reference
   function and its schema on the same inputs in one test; the most common defect a first reading
   found was a function returning what its own schema refuses. A wall-clock bound sits far above a
   loaded machine and far below the defect it guards.
3. **Test against the real deployed instance behind its platform**, not a sample the same run
   wrote: a probe passed the shipped sample and failed the first real service behind a router.
4. **After each wave, three blind readings** (the changed units, everything that reaches them,
   and the documented behaviour), then one fix round. Green suites hid six to ten real breaks.
5. **Read a gate's exit code directly**, never through a pipe in the same command (`| tail` hid a
   failed gate as success): write the output to a file, take the status, then read the file.
6. **"Could not measure" is its own outcome.** An overloaded machine makes a gate refuse, and a
   timeout under load is unmeasured, not failed or passed.
7. **Measure noise before calling a regression**; release a retrieval change only with zero new
   confident wrong answers against the previous version.
8. **Compute a status from the whole group**, never incrementally; verify a release by the
   commit it serves, from a fresh checkout of that commit.
9. **Probe live after every deploy on every consumer channel**, not the default one; read the
   nightly full-suite result first when resuming work, and release from a full local run, not a
   selected subset.
10. **Port a protocol from the contract's shared vectors, never its prose**, vendored with a hash
   per file and run case by case; a prose port accepted a year-0000 date the vectors refused.
11. **Read an external contract from its raw documentation or a recorded live snapshot**, never
   from a summarising fetch; fail closed on a field nobody documented.

## Operations that survive restarts

1. **One owner per run, named.** Only the holder of the run's lock changes its lifecycle, and each
   concurrent worker has its own identity; a refused claim names the run that holds the task, never
   a guessed race against a lease that lapsed long ago; a copy that a
   supervisor started backs off on a held lock instead of exiting into a respawn loop. A failed
   lease renewal is not a lost lease; stop only when the remaining margin runs out.
2. **Health treats "never finished" as a fault.** Age each phase from its last completion; a
   phase that only ever yielded looked healthy for fifteen days.
3. **Everything a run creates carries its owner** (run id, pid); the next start sweeps what a dead
   owner left: markers, test databases, temp roots, container volumes. Nothing a long job needs
   lives in a temp directory; a cleaner removed a test database mid-deploy.
4. **Check disk and load before heavy work**, and serialize heavy suites behind a lock held for
   the whole run. A disk cleanup never deletes files version control tracks.
5. **State that must survive a restart or a second instance lives in the shared store**, never in
   process memory or on one instance's disk; a per-process cache is a cache with a TTL.
6. **Every scheduled job leaves a trace when it dies, stalls or never starts**: a heartbeat at the
   start of each tick, a queryable error row, re-arming in `finally`, an alert when quiet for two
   intervals. Serialize every use of a connection threads share, reads included.
7. **Bound every wait on a shared lock and survive a lost connection.** A lock timeout (a few
   seconds) answers a retryable "busy", never a crash or a deadlock; every pooled connection has
   an error listener, and readiness reports the store while liveness reports the process, so a
   database blip takes the instance out of traffic instead of restarting it.
8. **Every accumulating output has a cap in the code that writes it** (logs, receipts, caches),
   with both bounds tested.
9. **Name the account and context on every cloud CLI call** and verify the account before a write;
   a saved default context once pointed a correct token at another team.
10. **Log by error name and code**, never a driver's raw message, which can carry connection
   details. A failed command logs its cause (deadline, signal, exit code, missing program), never a
   bare "command failed"; a watched dependency logs once when it fails and once when it recovers,
   never on every poll.
11. **Admit work only when the machine can carry it** (free disk, swap, a cap on concurrent
   sessions) and say why when you defer.

12. **Keep blocking work off the workers that answer requests**, never let a read wait behind a long
   transaction, and log a transaction held long with the step that held it. Every blocking network
   wait is interruptible from outside, with its deadline on the socket, not between frames.

## Secrets and confinement

1. **A secret never enters an environment, argv, URL or log a child can read.** Hand it over a
   pipe or file descriptor, or through a vault runner per command; never print a configuration
   dump, and never filter one yourself.
2. **Confine what an agent runs by the operating system**, per run (filesystem, network, ports),
   and treat prompt rules and command guards as tripwires, not boundaries.
3. **Fail closed.** When a reduced view or a scope cannot be built, answer an error, never the
   wider view; a new matching rule fires only when every neighbouring input is on its allow-list.
4. **Run the private-name gate chained before every public push** (`<gate> && git push`), not only
   before merge: a `;` once let a private path reach a public branch.
5. **Freeze every input at acceptance**, nested references included: copy it by hash and work on
   the copy, so a file swapped between acceptance and use is never read.
6. **Pin every tool's input schema to the domain schema with a test.** A save tool that silently
   dropped unknown fields once stored an agent set to send without the guards it was given.
7. **Treat what a run wrote as untrusted** before the service copies, reads or renders it: a
   regular file whose real path is inside the run's own tree.
8. **An artefact missing a secret refuses to start**, never runs unauthenticated: validation rejects
   placeholder-shaped values, and a test renders the configuration without the value and expects
   an error.
9. **Widen an access configuration first, code second**, so nothing is over-scoped even briefly.

10. **Bound every recursive parse of untrusted input** (a depth limit, tested at the limit and one
    above). Revoke or retire by a content-addressed reference, never a reusable name: a re-keyed
    machine keeps its key id. Never refresh a person's own credentials as a side effect; renew only
    what you own.

## Text for people

1. **Text a person reads carries no em dash** (U+2014) and no substitute for it: not `--`, not a
   spaced hyphen used as a dash. The operator reads it as the mark of machine-written text. Use a
   full stop, a comma, a colon or parentheses, or rewrite the sentence. This covers replies,
   messages, posts, mail, reports, captions and UI strings, in every language.
2. **Exceptions are exact, never stylistic:** exact quotations, code, commands, paths and
   historical records keep the character as they are.
3. **The rule lives in the prompt and in a test.** The prompt of every lane that writes for people
   states it; a test feeds that lane's output (and every fixed template) through a check that
   fails on U+2014, for example `assert "\u2014" not in text`, and is seen failing on a planted
   dash. A spaced hyphen cannot be told from a range or a minus by a pattern: the prompt and a
   reviewer carry that half, the check does not guess.
4. **A model's slip is rewritten or refused, never shipped.** When an accepted answer still holds U+2014, the
   call site's `accept` rewrites it or retries once, then refuses; it never sends the dash on.

## Checklist

Before the first release, answer each with a file and a test: where a limit pauses and resumes; what
`accept` each model call has; which vendors its fallback and checker use; where the attempt ledger
and idempotency keys live; what happens to an unknown outcome; which waits are durable; who owns the
run lock; what the next start sweeps; how a cancel reaches paid inner work; which outputs are
capped; how a secret reaches a child; which test was seen failing for each fix; and, for an agent
that writes text for people, where its prompt says no em dash and which test fails on U+2014 in its
output.
