# Recipe: a support agent

A service answers one inbound question from its own knowledge file, or hands it to a person. Built only on the service
kit: `fabric_openrouter` for the model, `fabric_usage` for receipts, `fabric_paths` for private, atomic state.
Tests: `test/test_support_agent_recipe.py` (a fake model; no network, no key).

## What it does with one message

| Step | Rule | When it fails |
|---|---|---|
| Repeat | the decision already made for this message id is returned, with no model call | |
| Lookup | entries sharing words with the question (its question, tags and answer), best three | handoff `no-knowledge` |
| Draft | `fabric_openrouter.Client.chat`: own key, spend ceiling before every attempt, a usage receipt per call, a fallback of another vendor, temperature 0 | handoff `model:<kind>` (`ceiling`, `failed`, `auth`, `payment`, `config`, `unpriced`) |
| Model unsure | the model may answer exactly `HANDOFF` | handoff `model-unsure` |
| Checks, proven by code | at least one `[KB:<id>]` citation; every cited id was given to the model; no em dash (U+2014), `--` or a spaced hyphen or en dash between words; the reply's script is the question's; at most `maxChars` | handoff, each failed check named (`no-citation`, `unknown-citation:<ids>`, `dash`, `script:<got>-not-<wanted>`, `too-long`, `empty`) |
| Record | the decision, 0600, written atomically; a handoff goes to the outbox first, so a crash repeats a handoff and never loses one | |

A reply comes back without its citation markers, with `citations` beside it. The agent never sends the reply: the
service that calls it owns its channel (mail, a chat, a store review) and its response time.

## Install into a service

```bash
python3 <adapter>/plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_kit.py \
  install <service>/support --lang py --module fabric_openrouter
cp <adapter>/plugins/fabric-agent-adapter/skills/building-fabric-services/recipes/support-agent/support_agent.py <service>/support/
python3 <adapter>/.../fabric_kit.py status <service>/support      # current, older or modified, per file
```

## Configure

`config.example.json`, paths relative to the config's folder:

| Key | Meaning |
|---|---|
| `knowledge` | the knowledge file: `{"entries": [{"id", "question", "answer", "tags"}]}`, ids unique |
| `stateDir` | decisions, the handoff outbox and the usage ledger (`usage.jsonl`) |
| `model`, `fallback` | two models of different vendors; a lane that reads what customers write runs on an open-vendor model (DEC-0083) |
| `keyEnv` | the environment variable that holds the agent's own OpenRouter key; never a value in the file |
| `ceilingUsd`, `window` | the spend ceiling per UTC `day` or `month` |
| `prices` or `catalog` | USD per token per model. The example's prices are placeholders, not OpenRouter's: take them from `GET https://openrouter.ai/api/v1/models` (a saved catalog file named in `catalog` is read with `prices_from_catalog`). A model without a price is never called |
| `maxTokens`, `maxChars` | the output budget per call and the reply's length limit |

## Run

```bash
OPENROUTER_API_KEY=... python3 support_agent.py answer --config config.json --message-id m-1 --text "How do I reset my password?"
```

The key comes from the environment the service manager gives the agent, never typed on a command line. The decision
prints as JSON: `{"messageId", "action": "reply"|"handoff", "reply"?, "citations", "reasons", "costUsd", "repeated"}`.
Exit 1 on a broken config or knowledge file. A missing key is not a crash: the message is handed off with
`model:config`.

From a service's capability handler, build the agent once with `support_agent.from_config(path)` and call
`agent.answer(message_id, text, task_run_id=...)`; pass `on_handoff=` to `SupportAgent` to route handoffs to the
operator's channel instead of the outbox file.

## Before you call it finished

- Replace the example knowledge with the product's own, and run real past questions through it ([practices](../../../creating-fabric-agents/references/practices.md#judges-and-evals), *Judges
  and evals*): count handoffs and read a sample of replies.
- Show spend: `fabric_usage.usage_report` over the ledger, or `fabric_openrouter.totals`.
- One decision per message id holds in one process; a service runs one instance per context under its instance lock.
