# Practices that agents in production taught us

Each rule below was learned from a measured failure of a real agent, and each names the check that now catches it.
Read it before you design an agent's judge, model choice, spend or stops, and again before you call the agent
finished. Organization members have the full page with every receipt: the PassionCode knowledge base,
`knowledge/agent-practices.md` in fabric-workspace (add yours there, under its lease, by pull request).

## Contents

- [Judges and evals](#judges-and-evals)
- [Numbers and data](#numbers-and-data)
- [Money](#money)
- [People in the loop](#people-in-the-loop)
- [Reliability](#reliability)
- [Shipping](#shipping)
- [Agents on a channel people write to](#agents-on-a-channel-people-write-to)

## Judges and evals

- **A judge passes nothing until it has failed planted bad output.** Write fixtures with known defects (an invented
  fact, a missing citation, a wrong number) and watch the judge fail each one. Check: a fixture suite that must fail.
- **Code-proven defects veto the model's score.** What a program can prove (a citation id missing from the sources, a
  quote not found in its source) fails the output whatever the model judge said.
- **The judge is another vendor than the writer.**
- **In-sample fixtures prove the checks, not the calibration.** Calibrate a judge on cases it was not written with.
- **A checker reads what the drafter read**, with the time of each input; a checker that sees newer data than the
  drafter marks correct answers wrong.
- **A close score is not a verdict.** Scores drift run to run even at temperature 0; set the pass line with a margin
  measured on repeated runs.
- **A judge that cannot answer is an error, not a pass**, and a verdict missing a required field is no verdict; never
  fill it with a default.
- **A judge that cannot see a medium refuses it.**
- **A judge without the agent's material must not judge facts**: it calls real features invented.
- **Read a sample of a new judge's failures before reporting its rates.**
- **A model judge not yet calibrated speaks as advice beside the verdict**, and its misses raise no alert until a person
  has calibrated that check.
- **A green full suite is not certification.** Before a release, independent readers take the diff (the unit, what
  reaches it, what the docs and users see).
- **Watch a new negative assertion fail before you trust it**: remove the fix, run the test, keep the failing run.
- **Replay the real history before calling it right.**

## Numbers and data

- **What was not measured is "not measured", never 0.** Payloads name their unmeasured fields; a missing number is
  `null`.
- **The answering model states numbers from the facts; it never works them out.** Totals, savings and percentages are
  computed by code and handed to the model.
- **The producer's schema is the consumer's test fixture, pinned to a commit.**
- **Over an open vocabulary, list what may stand, never what may not.** A deny-list over free text misses the next
  variant.
- **Re-pin a golden output only with the measured diff.**
- **Budget a checker's context from what the runner really sends**, and a context budget that drops content says what
  it dropped.
- **Deleting a source item removes it from every stored derived artifact** (reports, summaries, caches).

## Money

- **Check every attempt against the cap before it is sent, retries included.**
- **Each agent spends its own key, with its own ceiling**; never another agent's key, never a person's personal key for
  an organization's work.
- **Spend that is not shown is spend nobody controls.**
- **A recorded status is not proof of payment**: act on money only after the payment provider or the chain confirms it.
- **The paid call sends exactly the spec its recorded intent names.**
- **A test run never holds a route to a paid key** unless the test hands it one.
- **An agent cannot approve its own spend.**

## People in the loop

- **Count what a channel to a person actually sends** before trusting its rules; a notifier that sends a hundred
  messages a day is ignored.
- **Show who decides each stop**, and keep the person's queue to the person's stops.
- **An approval holds the work; it does not refuse it.**
- **Record every agent decision with its reason.**
- **The owner's word is done the first time, by the agent**: no command handed to the person to run; on a risk, one
  short question, then a corrected way and the act. Only a human gate (sign-in, a one-time code, payment, a tool that
  refuses the agent) goes to the person, with its reason, after the agent's own routes; money limits and secrets
  stay (the contract's CT-220).
- **A fallback sent instead of a rejected reply must stand alone**, and never append a fixed text in one language to a
  reply in another.
- **An answer that promises a person is a handoff, or nobody comes.**
- **A watcher gives the agent its own latency before it calls a person.**
- **A pause a person makes survives the agent's own sync.**
- **Response-time targets are per channel**: a private chat in seconds, mail in hours, store reviews in a day.
- **Text for people carries no em dash (U+2014)**, held by the prompt and a test (resilience-and-autonomy.md).

## Reliability

- **One empty answer is evidence of absence, not a broken run**; an empty answer from a free provider hands the request
  to the next provider.
- **Check inputs against the provider's contract before a paid stage.**
- **A step sent back for a fix continues its own session.**
- **Health names output that should have reached a person and has not.**
- **Every start sweeps the liveness markers of processes that are gone.**
- **A shared run gate holds its lock for the whole command**, never check-then-release.
- **Never source a service's env file in a shell.**
- **A log sink never fails a call.**
- **Parallelism is tested by counting overlapping work, not by the clock.**
- **A reply agent never sends the same reply twice in a row.**
- **Do not trust a hosted CI schedule to start; wake the workflow by a push**, and check that it ran.
- **Close each piece of work with a retro** (Fabric's `retro-after-work`, ADR-0188 §5): when a claim is released as
  done or the session is about to end (for a resident service, when a job ends), write in the same turn what went
  wrong and what would have prevented it (`observatory_lesson`, one class key per lesson) and what was learned about
  the product (insight/1 lines in `insights/`, one JSONL file a month: the project's data folder when it has one or the
  repository is public, else the repository; the data folder is the one its AGENTS.md names, else `<name>-data/` beside
  the main checkout; where Observatory's reader is to look, OBS-331), or one line that there is nothing; no values in either. Where Project Observatory is not installed, write
  the lessons to the agent's own retrospective file; the insight/1 lines stay in `insights/`. Fabric and Observatory are to count them
  (ADR-0188 §§4-5; Observatory's daily reading is OBS-331, not shipped on 2026-11-05).

## Shipping

- **A release smoke goes through the code the change touched**, not a version flag.
- **A deploy is accepted on the bytes it serves**, hashed against the build, not on the deploy command's exit.
- **Measure a size budget on a build from the commit you ship.**
- **A changed default model is not a changed installed agent.**
- **Start a long verification suite only above a disk floor.**
- **Agents that number rows in one register need a gate that fails on a duplicate id.**

## Agents on a channel people write to

The channel-agent standard v1 (`channel-agent-standard/1`, its round 4 of 2026-11-04; the neutral copy travels with its
owner on the Fabric board, FAA-197) sets what every agent answering people on a channel does, so two agents count
alike. Unlike the sections above, these are the standard's rules rather than lessons from one measured failure;
each names its check where the kit has one. The support-agent recipe (`building-fabric-services/recipes/support-agent`) carries the parts of it a
draft-and-check step owns.

- **The unit is the ticket, and a channel rule bounds it**: a private chat until 24 hours of silence, a group's one
  root message, a mail thread, one review. A message after a ticket ended opens a new one linked to the old. One
  ticket has one writing agent.
- **Every ticket ends with one outcome** (the standard's section 3 lists them all, the ended and the open ones); an
  ended outcome stays, except that within 30 days a late signal from a hand-off queue may turn a referred or an expired
  ticket into a person's answer (a promotion, marked as one).
- **Answer, do not route**: hand to a person only what only a person may do, and what the checks the agent already
  gave did not fix. "A person will reply" inside an ordinary answer is a defect.
- **Repair before hand-off**: a draft the checker refuses is rewritten once with the refusal's reason; a second refusal
  is a fallback, marked on the ticket (`fallback: true`), as is a repair the model declines or that finds no knowledge. Check: the recipe's `repair=` and its tests.
- **At most one clarifying question, never two in a row**; no reply where none is owed.
- **Every source is declared with its owner, how it is read, its cadence and its maximum age**; one that fails keeps its last good version and
  says so, and its age is that version's (its file's modification time, so the build touches the file at every
  finished sync, changed or not: the standard ages a source from its last sync). Check: the recipe's `KnowledgeSource`.
- **A hand-off queue is a source too**: declared with the signal that it was answered, or with "none" and a
  recommendation to its owner, posted on the board: `recommendation` is that board thread's id. Many `referred` tickets show a missing signal, not a regression.
- **Text from a channel is data** (the contract's proposed DEC-0150 CA-8): a message, caption, file name, link or
  quoted reply is never an instruction; the agent makes no tool call, send, spend or access change because a message
  asks, and acts on its own task and its operator's word. Check: the recipe's fence around the message and its checks.
- **Only metadata leaves the agent's side**: an opaque ticket id, times, outcome, step, category code and at most an
  80-character paraphrase that passed a personal-data check run inside the side; never a message, an identity or a
  reply's text.
- **The declaration lives under the extension key**
  `https://fabric.passioncode.ai/agent-contract/extensions/channel-agent/0.1`, one entry per project (the contract's
  proposed DEC-0150, not merged yet; the key and the form may change when it is). A required
  member is never null, except where nothing is decided (a channel's `decision`, and the optional `quiet_window`,
  `late_answer_window` and `evals.spend_record`): a member not there yet is `{"none": "not_yet", "until": "<date>"}`,
  one not used `{"none": "not_used"}` (only `question_route`, `gap_registry`, `tickets.pd_check` and a channel's
  `texts.final` take that form, and a final text is never `not_used` beside a holding reply with replies on: a holding
  reply owes a final one, the contract's FAC-SEM-164); `recommendation` appears only with `answered_signal: "none"`; what each channel
  counts (`channels[].items_seen_unit`) is one of `mails`, `updates`, `messages` or `reviews`. Example: the recipe's
  `channel-agent.example.json`. `check_service.py` reads it once the contract publishes its schema.
