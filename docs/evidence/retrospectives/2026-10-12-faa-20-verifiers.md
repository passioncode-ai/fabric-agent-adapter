# Retrospective — FAA-20 part two (0.11.1)

Run stamp: 2026-10-12. Adapter PR #60 and #61, tag `v0.11.1` (`v0.11.0` tagged, refused by release CI, never
published); launcher passioncode 0.1.35.

## Where the run diverged

1. **The differential vectors were only as good as the runtime that produced them.** The expected answers came from
   the contract's verifier on the local Node 26, which refuses small-order keys; Node 20/22 (the CI version) accept the
   same forgery. The local suite was green, the release CI was red. Surfaced at stage 7 (release CI); owned by stage 4
   (the plan named one runtime). Root cause: a crypto primitive's behaviour was assumed stable across runtime versions.
   **Next time:** a security check that leans on a platform primitive runs on every runtime version CI and users run
   (here `node@20`, `node@22`, `node@26`, Python 3.9/3.11/3.14), and the kit never delegates a refusal it can state
   itself.
2. **The independent review found seven defects the vectors missed** (small-order forgery in Python, a RecursionError
   crash, jti replay on an unreadable file, redirects, ungated job tools, no backoff, `__proto__`). Same class as the
   part-one retrospective: the tests followed the specification's happy paths, not an attacker's inputs. The standing
   instruction from part one held only partly. **Next time:** before the first commit of a verifier, list the attacker's
   inputs (malformed, hostile encodings, degraded storage, redirects, side doors such as job tools) as REQ rows.
3. **A version bump during a running suite** produced two false `test_repository_validates` failures. **Next time:**
   never edit tracked files while a suite runs in the background; rerun on the committed state for the receipt.
