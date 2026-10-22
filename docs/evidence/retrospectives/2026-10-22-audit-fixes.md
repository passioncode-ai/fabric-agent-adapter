# Retrospective: the 2026-10-22 audit closed as 0.41.0

Run stamp: 2026-10-22. PR #153 (merge `5876df8`), tag `v0.41.0`, release run 39716366275.

## Where the run diverged

1. **A build before the version bump rewrote the last release's digests.** `fabric_kit.py build` writes the history
   entry of `kit.json`'s own version; run while it still said 0.40.0, it made genuine 0.40.0 copies read `modified`.
   Caught by the seam reading, not by a test. **Next time:** bump the version first, then build; the new
   `test_a_released_version_keeps_its_digests` fails the old order in a clone with tags (FAA-82 puts it in CI).
2. **An inode number is not identity on Linux.** The stale-lock take compared `(dev, ino)`; Linux handed the freed
   number to the next lock at once. Green on macOS, red on the hosted Linux jobs. **Next time:** a file identity check
   carries the write time and size too, and a lock or race test runs on Linux before it lands.
3. **Widening a CI job exposes the suite's platform assumptions.** Running the whole Node suite on Windows turned up 16
   POSIX assumptions and two real Python bugs (CRLF in `fabric.package.json`, cp1252 output). **Next time:** a change
   that adds an OS to a job budgets one builder for that OS's first run.
4. **A pin chosen without the last good run's version broke the publish.** Replacing `npm@latest` with an exact pin
   was right; picking 11.21.1 was a downgrade from the 12.2.0 that had published 0.40.0, and the publish failed with E401.
   **Next time:** pin a tool to the version the last successful run used, read from that run's log.
5. **What held:** disjoint file ownership let seven builders run in parallel with no merge conflict; a shared sentinel
   (`fabric_jsvalue.MISSING`) was agreed by message between two builders before either landed; the three blind
   readings reported 27 findings (some overlapping) on a candidate whose suites were green.
