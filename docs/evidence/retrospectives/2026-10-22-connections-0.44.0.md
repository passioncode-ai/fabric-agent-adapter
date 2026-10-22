# Retrospective: the repin as 0.43.0 and fabric-connections/0.1 as 0.44.0

Run stamp: 2026-10-22. PR #159 (`64cc2f1`, `v0.43.0`), PR #160 (`5ad5c2c`, `v0.44.0`).

## Where the run diverged

1. **A port that reuses a kit helper inherits that helper's language.** The Python reader imported `fabric_secrets`
   (Python `\s`, `\b`, Unicode case folding, `urllib`) to answer a reference written in ECMAScript with WHATWG URLs.
   Three blind readings found three layers of it (regex semantics, URL validity, the serialized query). **Next time:**
   a twin of a reference reads with the reference's semantics from its first line, and the reading is fuzzed against
   the reference itself (the blind reader's side-by-side harness) before the first review, not after the third.
2. **A reference that calls the runtime is not a fixed answer.** The contract's reader parses URLs with Node's own
   `new URL`, whose IDNA handling changed between Node 22 and 26; vectors generated on Node 26 failed the hosted jobs on
   22 and 18. **Next time:** vectors from a runtime-dependent reference are kept only where every supported runtime
   answers alike, checked on each before they are committed.
3. **Staging a contract inside its own checkout dirties it.** Sources copied into the checkout made the contract-gated
   tests refuse a "modified checkout". **Next time:** stage beside the checkout (`src` with `schemas` and
   `node_modules` linked), never inside it.
4. **What held:** dispatching the hosted `validate` on the branch head before the tag (the last run's lesson) caught the
   Node-version difference before any tag; the kit version was bumped before every build, so no released history moved.
