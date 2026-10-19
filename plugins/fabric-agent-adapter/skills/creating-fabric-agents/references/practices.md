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

## Shipping

- **A release smoke goes through the code the change touched**, not a version flag.
- **A deploy is accepted on the bytes it serves**, hashed against the build, not on the deploy command's exit.
- **Measure a size budget on a build from the commit you ship.**
- **A changed default model is not a changed installed agent.**
- **Start a long verification suite only above a disk floor.**
- **Agents that number rows in one register need a gate that fails on a duplicate id.**
