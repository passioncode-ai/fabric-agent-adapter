# Models and providers: which model for which lane, and how it is paid

An agent has lanes: the part that plans and calls tools, the part that writes to a person, the part that classifies a
thousand items a day, the part that reads an image. Each lane gets its model on purpose, a fallback from another vendor,
and a budget that survives a verbose model. Most agents reach models through OpenRouter, one key per agent.

Normative rules: the Fabric Agent Contract's `runners.md` (*Runner and model profiles*, DEC-0046: model classes, the
resolution order request > agent > binding > policy), DEC-0083 (a lane that reads user content runs on an open-vendor
model, FAC-SEM-112) and `openrouter-attribution.md` (FAC-SEM-098). The kit that resolves profiles is
`building-fabric-services/scripts/fabric_profiles.py` (references/profiles.md there).

## Contents

- [Lanes, not one model](#lanes-not-one-model)
- [A starting choice](#a-starting-choice)
- [Several kinds of input and output](#several-kinds-of-input-and-output)
- [Ids, budgets and deadlines](#ids-budgets-and-deadlines)
- [OpenRouter: one key per agent](#openrouter-one-key-per-agent)
- [Measuring a choice](#measuring-a-choice)
- [The checklist](#the-checklist)

## Lanes, not one model

- **Big model where it pays, light model where volume is.** The strongest model for low-volume reasoning: an agent
  that plans and calls tools, research, a judge. A light, cheap model for high-volume work: classification,
  extraction to JSON, reranking, summaries, periodic jobs, routine chat.
- **Every lane has a fallback from another vendor** (the prefix before `/` differs), and the config loader refuses a
  profile without one. One vendor's outage or policy change must not take the whole agent down.
- **A lane that reads what users send runs on an open-vendor model** as its primary, or as its fallback when the
  primary is closed (DEC-0083: declare `reads: ["user-content"]` on the profile; FAC-SEM-112 refuses a route without
  one). Closed vendors refuse or hedge on whole topics; the lane must still handle the worst message it receives.
- **A judge is another vendor than the writer.** A model grading its own family rates its own habits.
- **Declare classes, not names, in the agent's profile** (`modelClasses`): the policy and the binding narrow them, and
  the host resolves the model. A hard-coded model name in code is a release to change it.

## A starting choice

As of 2026-11, all on OpenRouter. Prices and modalities change: read the catalog
(`GET https://openrouter.ai/api/v1/models`, `architecture.input_modalities`, `pricing`) before you rely on them. Prices
below are dollars per million tokens, input / output, read 2026-11-06; reasoning tokens bill as output.

| Lane | Primary | Fallback (another vendor) |
|---|---|---|
| Decisions: plan, orchestrate, call tools, converse, transform, hard classification, images and video, generated code | `moonshotai/kimi-k3.1-pro` (2 / 10; text, image, video) | internal lanes `anthropic/claude-sonnet-5.5`; lanes reading user content `xiaomi/mimo-v2.6-pro` or `z-ai/glm-5.3` |
| Verification of another model's output on internal lanes (a plan, code, a synthesis, an extraction, a step before it acts) | `anthropic/claude-sonnet-5.5` (2 / 10; text, image, file) | `z-ai/glm-5.3` or `deepseek/deepseek-v4.1-flash` |
| Plan and strategy validation | a panel of three vendors, e.g. `moonshotai/kimi-k3.1-pro`, `google/gemini-4-argon` and `anthropic/claude-opus-5.5` (4 / 20); the author never judges | the two left |
| Data, documents, audio and video input | `google/gemini-3.1-pro-preview` (2 / 12) or `google/gemini-4-argon` (2 / 10); both read every input | `xiaomi/mimo-v2.6-pro` (0.435 / 0.87; audio and video) |
| User requests and user content | an open-vendor model, e.g. `moonshotai/kimi-k3.1-pro` where a decision or a reply needs intelligence, `z-ai/glm-5.3` or `deepseek/deepseek-v4.1-flash` at volume | another open vendor; a closed vendor is never the only route (DEC-0083), and we recommend it neither draft a reply to a person nor check such a lane, where its refusals turn into silence |
| Strong, cheap reasoning over text at volume | `z-ai/glm-5.3` (0.07 / 1.40; text only) | `deepseek/deepseek-v4.1-flash` |
| Volume: classification, extraction, triage, screenshots, periodic jobs (a channel agent's batch triage runs on the planning model instead: communication-agent-template.md, section 3) | `deepseek/deepseek-v4.1-flash` (0.051 / 0.567; text, image); always the newest `-flash`, never `-pro` | `qwen/qwen3.8-flash`; `z-ai/glm-5.3-flash` only with a generous budget, its reasoning cannot be turned off |

Which vendor is open is the catalogue's fact (`open-vendor` class, FAC-SEM-112), not this table's: check it there. A communication agent built from
[communication-agent-template.md](communication-agent-template.md) keeps every route of such a lane open-vendor,
fallbacks included (its rule 6), which is narrower than the floor above.
A frontier-class model costs several times a light one per turn: put it where decisions are made and volume is
moderate, and keep volume on the light models.

Embeddings, speech to text and text to speech are separate choices: keep the one measured on your data, and never
change an embedding model without re-indexing every stored vector (search silently turns into noise).

## Several kinds of input and output

- **Input.** A model's name does not tell you what it reads: check `input_modalities` in the catalog. Send the medium
  itself (an image, an audio clip) to a model that reads it, rather than a description another model wrote.
- **A checker that cannot see a medium must not judge it.** A text-only judge refuses an audio or image candidate
  instead of scoring its file name.
- **Generated media** (images, video, voice, music, 3D) go through one media service that picks the provider, records
  the cost and keeps the original, not through provider SDKs scattered across the agent. Check the input against the
  provider's limits (media type, length, size) before a paid stage.
- **Long documents** translated or rewritten in one call come back cut off without an error: send them in sections and
  check that each section's end arrived.

## Ids, budgets and deadlines

- **Model ids are configuration**, read at start from one place; a changed default applies to new installs, and an
  installed agent keeps its own until it is told.
- **Set the default per job explicitly.** Never let the order of a catalog choose it.
- **Reasoning spends the output budget.** With reasoning on and a tight `max_tokens`, a light model returns empty
  content (`finish_reason: length`). Leave the budget generous, or turn reasoning off for short outputs where the
  model allows it; some models refuse to turn it off.
- **Some models will not turn reasoning off.** Reported on OpenRouter on 2026-11-06 (not measured in this repository; check on your key): `kimi-k3.1-pro` ignores the flag and writes its
  reasoning into the answer, running into `max_tokens`; `glm-5.3`, `claude-sonnet-5.5` and `claude-opus-5.5` answer
  HTTP 400 to it. Before switching a lane that sends reasoning off, drop the flag for such a model and give it a
  generous budget, or the lane fails on every call, its fallback included.
- **A judge may refuse to judge.** A model can refuse to grade other models' outputs; count a refusal as the judge
  failing, never as a verdict, and keep a judge of another vendor ready.
- **An empty answer is neither a refusal nor a success.** Retry with a larger budget or the fallback; never ship it.
- **A fixed output budget must survive a verbose model**, and a deadline sized for one model times out another: count
  partial and timed-out attempts per model before choosing either.
- **A probe with `max_tokens: 1` proves routing and permission, not quality.**

## OpenRouter: one key per agent

- **Each agent spends its own key, with its own ceiling.** The key is minted for that agent (and that project) by the
  estate's key manager, with a monthly limit; it is never pasted by a person into a file, a prompt or a command line.
  A new agent's key gets USD 100 a month unless the operator names a higher one for that agent, and the agent's own
  stop sits a little under the key's limit, so the provider never refuses first.
  Read it from the environment the service manager or the session gives the agent (Fabric Switchboard hands an agent
  the key of the project it starts in).
- **An organization's instance spends the organization's key** under its grant; a personal key never pays for an
  organization's work.
- **Check every attempt against the ceiling before it is sent,** retries included, estimating at the full output
  budget; record the actual cost each call returns (`usage: {include: true}`).
- **Show spend.** An agent's interface shows spend per day, per provider and per model for 30 days; spend nobody sees
  is spend nobody controls.
- **Unknown cost is `null`, never 0** (DEC-0087, `fabric-interop/0.2`).
- **The kit does this for a service.** `fabric_openrouter` (building-fabric-services, references/connectors.md): the
  key from a named environment variable, the ceiling before every attempt at the full output budget, a receipt per
  call, empty and `length` answers never returned as success, a fallback of another vendor required.
- **Attribution is off by default.** A product may send OpenRouter's attribution headers only with its operator's
  setting and only for requests it originates (FAC-SEM-098); an agent a user built keeps the user's own.

## Measuring a choice

Choose a model on the agent's own real inputs, under its own key: a set of real cases (including the worst ones it
will see), a score the code computes where it can, a judge of another vendor where it cannot, the date and the key
scope recorded next to the default. Re-run it when you change the model, the prompt or the provider.

## The checklist

- Each lane: primary, fallback of another vendor, open-vendor where it reads user content, a declared class.
- Each lane's input modalities checked in the catalog; media generation through one media service.
- Budgets that survive reasoning; empty answers retried, never shipped.
- One key per agent and context, read from the environment, with a ceiling checked before every call.
- The choice measured on real inputs, recorded with its date.
