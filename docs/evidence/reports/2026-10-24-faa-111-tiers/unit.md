# FAA-111: the blind unit reading of 0.49.0's changes

Tier 1 (`task-pipeline:verifier-unit`), 2026-10-24, verbatim except local paths. What became of each finding: [README](README.md).

## FAA-111, unit tier: pass

The six changed units do what the brief asks, and every named check is green on the current tree. I'm filing four survivable findings as `risk`. The most important is that the board double-run fix still leaves one error path open. I edited no repository file. Scratch probes are in a scratch directory outside the repository.

Two things moved while I was reading, because something else was editing the worktree at the same time:
- **validate.py:** my first two runs exited 1 with "top changelog version is out of sync". `package.json` and `validate.py` had already moved to 0.49.0 while `CHANGELOG.md` still started at 0.48.3. Once the 0.49.0 entry landed it exited 0.
- **Python suite:** one run under a load average of about 270 ended `FAILED (errors=27)`, and I did not capture the tracebacks. The next three runs were all green (214 tests OK), with the reviewed script diffs unchanged.

```json
{
  "node": "FAA-111",
  "tier": "unit",
  "verdict": "pass",
  "scope": [
    "working-with-fabric/scripts/fabric_session_mail.py:42-112: poll_unread (all branches) and the new _deliver_and_count",
    "working-with-fabric/scripts/fabric_session_mcp.py:270-326, 365-523: _take_lock/_try_lock, board_unread, deliver (every exit: no entries, Fabric gone, end delivered, NoSessionError, TimeoutError, generic) and where board.json is written",
    "working-with-fabric/scripts/fabric_session_env.py:344-365, 460-467, 493-507: project_uses_fabric, rejoin_wait, session_dir, spool",
    "working-with-fabric/scripts/fabric_session_cli.py:54-133: PREAMBLE, POINTER, DOWN_NOTICE, hook_session_start, _read_count",
    "working-with-fabric/scripts/fabric_session.py:118-121: POINTER re-export",
    "building-fabric-services/scripts/check_service_rules.py:79-150: _body_carries_document, guard_verdict, _carries_document, no_token_verdict",
    "building-fabric-services/scripts/fabric_board_session.py:316-400, 660-860: _replace, _replied_before, _resume_next, _run, _resume, _fenced, _lose, _effect_begin, _finish, _settle_live, _complete, plus step/_fault/_drop_session 445-518",
    "building-fabric-services/scripts/fabric-board-session.mjs:300-345, 610-626: repliedBefore, resumeNext, runWork, resume",
    "building-fabric-services/scripts/fabric_openrouter.py:78-90, 212-230, 422-439: _price, spent_usd, totals",
    "building-fabric-services/scripts/fabric-openrouter.mjs:45-51, 140-150, 326-344: price, spentUsd, totals",
    "test/validate.py:845-861: the people list and the em dash scan",
    "the new tests in test/test_fabric_session.py, test_fabric_board.py, test_fabric_openrouter.py, test_fabric_service_remote.py, test/fabric-openrouter.test.mjs; FAA-86 tests test_fabric_board.py:722-748 and fabric-board.test.mjs:731-767; sample_service.py:211,306,313 (the kit's own 403 bodies)"
  ],
  "confirms": [
    "REQ-2 / D2: a watch-mail look that finds *-*.json spool entries calls deliver and reads the count from a board.json written during this look (mtime >= start - 1 s). One fabric-mcp serves both the spool and the count, and the next look within the minute returns ('wait', >0) without starting another (test_a_look_delivers_the_spooled_turns_in_the_same_rejoin).",
    "_deliver_and_count never returns ('ok', n) for a bool, null, missing, unparseable or stale board.json. A stale file falls through to the shared rejoin mark ('wait') or 'down'. deliver catches Exception, so only BaseException can leave poll_unread, as before.",
    "REQ-3 / D1: hook_session_start prints PREAMBLE only when project_uses_fabric names a sign, and the one-line POINTER otherwise. POINTER.format(host=...) cannot fail: it has no braces, and every HOSTS value formats to 238-247 characters with no em dash. A project- or local-scope registration still gets the preamble (test_a_pointer_when_running_in_a_project_without_a_sign).",
    "D4: _carries_document now needs a document's shape (protocol == fs.PROTOCOL, a service object with id, a process object with pid). A proxy error with a string service passes no_token_verdict, and the three shaped bodies fail it.",
    "guard_verdict does not wrongly fail an honest 403. The kit's own refusals are {\"error\": <string>} (sample_service.py:211,306,313), and a refusal naming its service as a string passes (test_a_403_that_carries_the_document_does_not_pass). Only a JSON body carrying the document's shape fails.",
    "Item 4: both twins remove the head before resume and put it back first only when resume raises and the checkpoint still holds the request. They agree branch for branch: a probe that raises happens before the shift, so the head stays; a missing or unheld entry is dropped. The FAA-86 lost-complete tests in both twins exercise the put-back path and pass.",
    "Item 5: spent_usd/spentUsd skip a subscription receipt in the same place (after the window check). totals agrees between Python and Node on 12 edge cases I ran: empty list, all-subscription priced and unpriced, mixed subscription priced + paid unpriced, bool, negative, 0, 1e400, a case-variant 'Subscription', platform-metered, and receipts with no costUsd.",
    "Item 6: validate.py adds */recipes/*/README.md to the people list, which feeds the U+2014 scan at :857-861. The one recipes README holds no em dash."
  ],
  "findings": [
    {
      "what": "The double-run fix leaves one error path open. In _resume_next's except branch the request is put back whenever the checkpoint still holds it, whatever its step. If a resumed handler settles inside the resume after begin_effect (_settle_live -> _lose marks step 'unknown', effect True) and the nested _replace then loses its answer, the request goes back to the front. On the next tick its handler runs again and com.effect_begin is sent a second time. I reproduced it against the fake board (scratchpad probe_resume.py, probe_resume2.py): handler calls 2, com.effect_begin calls 2. The fake board refused the second effect_begin, so the effect itself ran once. It only happens when the handler finishes inside spawn (synchronous spawn, or a thread that finishes before spawn returns, which is practically never with an HTTP begin_effect), so it is not reachable on the default path. The Node twin has the same condition.",
      "where": "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_board_session.py:394-397; fabric-board-session.mjs:338-340",
      "severity": "risk",
      "fix": "Put the request back only when its checkpoint entry is still resumable: no effect begun and step not 'unknown'. The same condition goes in both twins.",
      "check": "Extend test_a_resumed_handler_that_settles_inside_the_resume_runs_once: after _lose, set board.drop_next['com.responder_replace']=1, step three more times, and assert one handler call and one com.effect_begin. Add the matching Node case."
    },
    {
      "what": "totals() on an empty receipt list changed from spentUsd None/null to 0 in both twins. The boundary moved from 'every call is unpriced, including vacuously' to 'no paid call exists'. The twins agree, and no test in either suite pins the empty case.",
      "where": "fabric_openrouter.py:439; fabric-openrouter.mjs:343",
      "severity": "risk",
      "fix": "Keep 0 (nothing was spent) and pin it with a test in both twins, or keep null for calls == 0 if the old meaning was intended.",
      "check": "python3 -c 'fo.totals([])' and node fo.totals([]) asserted equal to {calls:0, spentUsd:0, unpricedCalls:0} in test_fabric_openrouter.py and fabric-openrouter.test.mjs"
    },
    {
      "what": "_deliver_and_count accepts any int count, including a negative one, from a fresh board.json. Its siblings in the same module family reject negatives (board_unread, mcp.py:376; _read_count, cli.py:133), so the count is validated twice and the two checks can disagree. deliver only writes values that passed board_unread, so only a foreign writer inside the 1-second window could plant one (probe: {\"unread\":-2} -> ('ok', -2)).",
      "where": "plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/fabric_session_mail.py:105",
      "severity": "risk",
      "fix": "Add `and unread >= 0`, or reuse _read_count's rule.",
      "check": "A unit test writing {\"unread\": -1} as a fresh board.json through a stubbed deliver expects ('unavailable', ...)"
    },
    {
      "what": "_deliver_and_count misreports two cases as 'down'. (a) When the look itself delivers the session's end entry, deliver removes the folder and writes no board.json, so the look reports 'down', 'the spooled turns could not be delivered now' although they were delivered. (b) A fresh board.json that is not a JSON object, or does not parse, reports 'down' instead of 'unavailable', because the except branch also clears `fresh`. Both only change watch-mail's one line and its backoff.",
      "where": "fabric_session_mail.py:100-112",
      "severity": "risk",
      "fix": "Return a distinct message when the folder is gone after deliver. Keep `fresh` from the stat when only the parse fails.",
      "check": "The scratchpad probe_mail.py cases 'ended, folder removed', 'list json' and 'bad json' turned into unit tests"
    }
  ],
  "evidence": [
    "cd test && python3 -m unittest test_fabric_session test_fabric_board test_fabric_openrouter test_fabric_service_remote -> Ran 214 tests, OK (three runs). One intermediate run under load average ~270 ended FAILED (errors=27); tracebacks not captured",
    "node --test test/fabric-openrouter.test.mjs test/fabric-board.test.mjs -> pass 38, fail 0 (twice)",
    "python3 test/validate.py -> exit 1 twice ('top changelog version is out of sync': package.json/validate.py at 0.49.0, CHANGELOG top still 0.48.3, a concurrent writer's in-flight bump), then exit 0 once CHANGELOG.md gained '## 0.49.0 (2026-10-24)'",
    "twin comparison of totals() over 12 edge cases (scratchpad cases.json, py.txt, js.txt): identical results",
    "probe_resume.py / probe_resume2.py: nested responder_replace answer lost or Fabric down after _lose -> request back in _to_resume with step 'unknown', effect True; handler run 2x, com.effect_begin 2x, final board state outcome_unknown",
    "probe_mail.py: _deliver_and_count verdicts: count 3 -> ok 3; bool -> unavailable; -2 -> ok -2; null -> unavailable; list/bad JSON -> down; stale without mark -> down; stale with fresh mark -> wait ~55 s; missing -> down; folder removed -> down; KeyboardInterrupt propagates",
    "POINTER.format(host=v) for all 7 HOSTS values: no braces left, no U+2014, 238-247 characters"
  ],
  "not_examined": [
    "Whether the new tests failed before the change (the brief's 'red before' for REQ-2, REQ-3 and the board and OpenRouter cases): I read them against the fixed code only",
    "No Node test exercises resumeNext's settle-inside-resume case. In Node it needs a handler that settles within one setImmediate, which a networked beginEffect does not",
    "Callers of totals() and spent_usd outside fabric_openrouter (usage report, dashboards) and how they show 0 versus null: seam tier",
    "Whether a Codex or native-host project-scope registration should count as a project_uses_fabric sign (registration is None for non-claude hosts, so those folders now get POINTER): seam tier",
    "The 27-error intermittent run: cause not identified (load or the concurrent writer)",
    "A race where the session folder disappears between poll_unread's is_dir() and glob() (Path.glob may raise FileNotFoundError on Python < 3.13), not exercised",
    "REQ-4 (trigger evals), REQ-6 (release), the docs edits, and the concurrent fabric_kit.py/kit.json/version changes, which are outside the six listed items"
  ]
}
```