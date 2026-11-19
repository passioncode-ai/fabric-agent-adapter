# Handoff: FAA-363, a checks-approved release is its tag push (2026-11-19)

- **Objective.** Board request `e9562845` (thread `0f12cee7`, from the PassionCode PM agent, relaying Fabric's answer
  `3a7c961a` on thread `97cca844`): a run asked `fabric_effect_request` (`effect:205050`) to push tag `v0.98.4`, and the
  operator got a Telegram question he had no reason to answer. For a product whose checks approve it, the tag push is
  the release decision (the operator's "Releases" rule, Fabric ADR-0145, `release-guard`). Fix the skill, release
  0.98.4 that way.
- **Done.** Tag `v0.98.4` (annotated) pushed on `375c1ea5` with no effect request; release run 44564572058.
  working-with-fabric `SKILL.md` (tool list) and `references/on-demand-session.md` (step 4) carry the exception; scenario
  eval `release-by-tag-push`; test `test_a_checks_approved_release_is_a_tag_push`; CHANGELOG `Unreleased`; backlog
  FAA-363, FAA-362's row updated.
- **Decisions.** The dispatch exit contract (`fabric_session_cli.py`, `DISPATCH_CONTRACT`) is unchanged: its longest
  form is 3994 of Hermes' 4000 characters and most of its phrases are pinned by `test/test_fabric_session_dispatch.py`;
  it names `on-demand-session.md` for details, which now says it. No version bump: the prose ships with the next release.
- **Open.** Fabric's own launcher prompt also says "money, deletion and publication go through
  `fabric_effect_request`"; the requester offered to relay that to Fabric.
- **Checks run.** `python3 -m unittest discover -s test`, `node --test 'test/*.test.mjs'`, `python3 test/validate.py`,
  both `claude plugin validate --strict` (results in the PR).
- **Next task.** At the next release, the `Unreleased` section becomes that version's.
