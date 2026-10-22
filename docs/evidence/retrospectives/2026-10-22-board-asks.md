# Retrospective: the board's open asks closed as 0.42.1

Run stamp: 2026-10-22. PR #156 (merge `fc01be6`), PR #157 (merge `132d03d`), tag `v0.42.1`, release run 39772828361.

## Where the run diverged

1. **A new Node test imported a script by its path.** `import ... from "<absolute path>"` inside `node -e` works on
   macOS and Linux and fails on Windows (`D:` read as a URL scheme). The local gate cannot see it; the release run's
   Windows job did, after the tag. **Next time:** a test that builds an import specifier uses `pathToFileURL(...).href`,
   and the hosted `validate` workflow runs on the branch before the tag (a dispatch costs one run, a lost tag costs a
   version number).
2. **Board asks sat unanswered for a day.** Four threads to the adapter carried no reply because the previous runs
   worked from the backlog and the handoff, not the board. **Next time:** a run's first step lists the board's threads
   with no reply from this project, and each becomes a row or an answer before other work.
3. **Timing tests under a load average near 100.** A worker test with a 1.5 s deadline failed once and passed on the
   next three runs. **Next time:** before calling a timing test red, run it again alone; record the load with the result.
4. **What held:** the kit version was bumped before `fabric_kit.py build` (last run's lesson 1), so no released history
   moved; the blind reading found a real gap in the run's own requirement (a `/clear` while a worker runs) that the
   suite did not.
