# The architect's audit of fabric-agent-adapter

The North Star's rule of 2026-11-13 ("Merged with the North Star, validated by the architect", fabric-workspace
`knowledge/north-star.md` §6, gap G30) asks every project to run the agents database's audit at each release.

| Date | Base | Checkout | Scan | Verdict |
|---|---|---|---|---|
| 2026-11-13 | `2ea5dd1` | `9297a999` (0.83.0 candidate) | [2026-11-13-scan.json](2026-11-13-scan.json): no close template (best `host-operations` 2.669, text similarity 0.267) | the judged half does not apply |

**Why the judged half does not apply.** This repository is the kit and the skills an agent is built with, not an
agent: it has no model, prompt, tools of its own or running service, as fabric-agent-contract and relay recorded for
themselves on the same thread (board `16093ded`). What it ships that is shaped like an agent, the recipes, is built from
the database's templates through the architect's consult (0.83.0: the data-agent recipe from `data-room` 1.7.0, the
support recipe's parts from `support-answerer` 1.8.1). A recipe that becomes an agent of its own gets the full audit in
the repository that runs it.

The scan runs again at each release; the next is the one after 0.83.0.
