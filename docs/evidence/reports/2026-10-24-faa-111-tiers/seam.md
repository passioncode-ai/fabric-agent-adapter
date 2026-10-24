# FAA-111: the blind seam reading of v0.46.1..v0.48.3

Tier 2 (`task-pipeline:verifier-seam`), 2026-10-24, verbatim except local paths. What became of each finding: [README](README.md).

I found one break: a regression in v0.48.2 that can run a board handler twice. Seven risks also ship, and none of them blocks the run. I edited no repository files. The only things I wrote were a scratch test and a v0.46.1 copy, both outside the repo.

**The break.** In v0.48.2, `_resume_next` now takes a request off the resume queue *after* `_resume` returns instead of before. A nested call can therefore see the same request still at the front and resume it again.
- **Path:** the resumed handler finishes inside `_run` (it calls `begin_effect`, then raises, and nothing is observed). Then `_finish` → `_settle_live` → `_replace` (line 834) → `_resume_next` (line 360) runs while the request is still first in the queue.
- **Reproduced:** with a synchronous `spawn`, HEAD runs the handler twice and sends `com.effect_begin` twice. The same test against v0.46.1 runs it once.
- **Who is exposed:** any `Responder` built with a synchronous `spawn`. That parameter is public (`references/board.md:207`), the kit's own `fabric_board_fixture.py:95` uses one, and so does the test harness. With the default threaded `spawn` it is only a narrow race.
- **Node twin:** same code shape (`fabric-board-session.mjs:333-335`), not reproduced. It is reachable only if the handler and `beginEffect` finish within one `setImmediate`.

```json
{
  "node": "faa-0.47.0..0.48.3-seam",
  "tier": "seam",
  "verdict": "fail",
  "scope": [
    "callers of _resume_next/resumeNext: fabric_board_session.py:360 (_replace end), :532 (_tick); fabric-board-session.mjs:297, :475. Re-entry path: _resume -> _run (inline finish when spawn is synchronous, :669-670) -> _finish -> _settle_live -> _replace (:834) -> _resume_next. Node: resume -> runWork (finish inline after one setImmediate) -> settleLive -> replace -> resumeNext. Public parameter spawn: references/board.md:207; synchronous spawn used by fabric_board_fixture.py:95 and test/test_fabric_board.py:194",
    "callers of _spent_in/_spent_since/spentIn/spentSince: only usage_report/usageReport (fabric_usage.py:483,494,496; fabric-usage.mjs:294,302,303). usage_report callers: JsonlUsageLedger.report (fabric_usage.py:781), Node ledger.report (fabric-usage.mjs:501), tests only. No recipe or sample calls it with budgets",
    "readers of spentUsd: usage_limit_problems 'budget repeats' (fabric_usage.py:716-730, fabric-usage.mjs:458); check_service usage.report via usage_problems (check_service_rules.py:200-235; does not read budget)",
    "second implementations of the spend rule: fabric_openrouter Client.spent_usd (fabric_openrouter.py:214-227) / spentUsd (fabric-openrouter.mjs:140-149), the enforced ceiling; totals() (fabric_openrouter.py:421-431, fabric-openrouter.mjs:326-335)",
    "shared state: the JsonlUsageLedger file (usage.jsonl) read by usage_report AND the OpenRouter ceiling; receipts() does not validate (fabric_usage.py:756-765)",
    "facade re-exports: fabric_service.py:137-139 (usage_report, usage_spend, _round_usd); fabric-service.mjs:72-73 (usageReport, usageSpend). Estate symbols are not in either facade; callers import fabric_estate directly",
    "check_service well_known_rules: add_no_token on 5 remote paths (check_service.py:196,208,213,220,224); host_name set only for remote (:106); sibling 'no data leaked' rule guard_verdict (check_service_rules.py:82-88); other 401 rules: events.requires-token :333, usage.requires-token :381; the server side still emits an empty 401 (fabric_auth.py:359, fabric-auth.mjs:243)",
    "estate: verify_estate_record/estate_record_rules have no in-kit production caller (grep: tests + docstrings only); hub_key_certified (fabric_estate.py:403) does not read profile; fabric_share/fabric_ceremonies only read revisions, never build one",
    "delegation refusal codes: refusal_http status map (fabric_delegation.py:74,823; fabric-delegation.mjs:38,502); board REFUSAL_CODES (fabric_board_shapes.py:42) is a separate namespace; no producer of profile-forbids in the kit",
    "protocol registers: readers fabric_service.py, fabric-service.mjs, test_fabric_service_feed_protocols.py, fabric-service-feed-protocols.test.mjs, vendor_vectors.mjs",
    "readFolder callers: pack (fabric-package.mjs:525) and verify (:545); tests fabric-package.test.mjs:365, kit-hostile-package.test.mjs:176-215",
    "pin/version neighbours: adapt_project.py CONTRACT_COMMIT/SUPPORTED_CONTRACT_COMMITS, test/validate.py PIN_*, test_contract_revisions.py, plugin.json, package.json, marketplace.json, fabric_session_env.py VERSION",
    "set_has: one call site (fabric_estate.py:696) vs 28 `new Set` in fabric-estate.mjs and 16 contains-style lookups in fabric_estate.py"
  ],
  "confirms": [
    "Both facades re-export the new spend helper (usage_spend / usageSpend). _round_usd is Python-only because Node rounds inline with Math.round, held to the same cases by kit-rounding-cases.json",
    "budget.spentUsd and an enforced machine limit's kit-computed spentUsd come from the same _spent_in / spentIn, so the 'budget repeats' twin check agrees whenever the kit computes both",
    "byModel rows have carried route since DEC-0046 (fabric_usage.py:447-452), so _spent_in now sees each route. OpenRouter receipts are route 'key' (fabric_openrouter.py:252), so key-only services see unchanged money",
    "check_service's usage.report rule never reads budget or budgets, so the new money-only meaning contradicts no probe rule",
    "profile-forbids maps to 403 with no challenge in both twins by the default branch. The REFUSAL_CODES and REFUSAL_MESSAGES twins carry the same entries",
    "PROTOCOL_REVISIONS: Python and Node registers are semantically equal (computed: True, no key or value differs)",
    "readFolder's early return on a swapped folder still leaves `refused` non-empty, so pack and verify both throw PackageError as before",
    "Every remote path that gets a first answer records well-known.requires-token exactly once, before well-known.answers. TLS failure records neither, as in v0.46.1",
    "FAC-SEM-137 is added the same way in both twins in the verdict (dropped + anchor) and in the estate-record-revision rules",
    "Version strings are 0.48.3 in plugin.json:6, package.json:3, marketplace.json:15, fabric_session_env.py:60 and validate.py. The pin lists agree between adapt_project.py, validate.py and test_contract_revisions.py"
  ],
  "findings": [
    {
      "what": "A resumed request's handler can run twice and send com.effect_begin twice. In 0.48.2, _resume_next removes the request from the queue only AFTER _resume returns. When the resumed handler finishes inside _run (begin_effect, then raise or an unobserved result, nothing observed), _settle_live calls _replace, which calls _resume_next re-entrantly. The request is still first in the queue and its checkpoint entry is still present at step 'unknown', so it is resumed again: com.get, then the handler a second time, then a second effect_begin. Before 0.48.2 it was popped before _resume and the nested call never saw it. Reproduced on HEAD (2 handler calls); v0.46.1 gives 1. Node has the same shape at fabric-board-session.mjs:333-335 (not reproduced; reachable only if the handler and beginEffect finish within one setImmediate)",
      "where": "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_board_session.py:384-394 (with :360 and :834); dependents: any Responder built with a synchronous spawn (references/board.md:207 documents the parameter; fabric_board_fixture.py:95 and test/test_fabric_board.py:194 use one)",
      "severity": "breaks",
      "fix": "Keep FAA-86's 'stays first on a lost answer' without the re-entry. Either pop the head before _resume as before and put it back at the front only when _resume raises (try/except, re-raise), or mark the request as resuming (self._resuming) and have a nested _resume_next return while one is in progress. Apply the same change to resumeNext in the Node twin",
      "check": "add to test/test_fabric_board.py (RestartTests): rid,_ = self._crash_after(effect=False); a handler that appends to a counter, calls ctx.begin_effect('x') and raises; self.observed=None; self.responder().step(); assert the counter is 1 and com.effect_begin was sent once. Then run `cd test && python3 -m unittest test_fabric_board` and `node --test test/fabric-board.test.mjs` (the FAA-86 tests must still pass)"
    },
    {
      "what": "The enforced OpenRouter ceiling and totals() still count every receipt in the ledger as spend: a subscription route's list-price estimate, and other providers' unpriced receipts at the worst-case amount. The usage report now counts money only (DEC-0110, CT-115). The ledger is shared (Client(ledger=JsonlUsageLedger(state/'usage.jsonl')) is the documented wiring). A service that runs a subscription runner beside OpenRouter and passes budget = its ceiling will report spentUsd below the amount at which its Client refuses calls. This is the duplicate of the spend rule that did not get the change",
      "where": "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_openrouter.py:214-227 and :421-431; fabric-openrouter.mjs:140-149 and :326-335",
      "severity": "risk",
      "fix": "Count only receipts whose route is not 'subscription' (or only provider 'openrouter') in spent_usd/spentUsd and totals, or state in references/usage.md that the OpenRouter ceiling counts every receipt in its ledger"
    },
    {
      "what": "Contract move for a service that states its own spentUsd on its enforced machine daily/monthly limit while also passing budget. budget.spentUsd is now money-only, so once the window holds a subscription row, a self-stated figure with the old meaning (all costs) no longer matches it. usage_report then raises ServiceError ('budget repeats ...') and the usage endpoint fails. No in-repo caller does this; the docs were updated (references/usage.md:80-86)",
      "where": "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_usage.py:716-730; fabric-usage.mjs:458 (dependents: services outside this repo that pass spentUsd themselves)",
      "severity": "risk",
      "fix": "Add a CHANGELOG/usage.md line telling services that state spentUsd themselves to drop subscription estimates, or let the kit compute it (omit spentUsd)"
    },
    {
      "what": "One malformed ledger receipt in a window (a route outside USAGE_ROUTES, a negative or non-numeric cost) now turns budget.spentUsd and every kit-computed machine limit's spentUsd for that window to null, because usage_spend answers None for the whole row set. Before, the other costs were summed. JsonlUsageLedger.receipts() parses lines without validating them. The twins agree",
      "where": "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_usage.py:577-595 reading fabric_usage.py:756-765; fabric-usage.mjs spentSince/spentIn",
      "severity": "risk",
      "fix": "Either accept it (null means unknown) and say so in usage.md, or have usage_report skip or flag receipts make_usage_receipt would refuse before computing spend"
    },
    {
      "what": "Two rules judge 'the answer leaks the service's data' and now disagree. no_token_verdict parses the body and looks for the document's shape and identity values (DEC-0109). guard_verdict, the sibling network rule, still uses the substring 'fabric-service/' and passes any 403 whatever its body",
      "where": "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/check_service_rules.py:82-88",
      "severity": "risk",
      "fix": "Judge guard bodies with the same _carries_document + identity check (a 403 that carries the document should FAIL)"
    },
    {
      "what": "The FAC-SEM-137 check added to verify_estate_record's verdict has no test. None of the 49 'verify' vectors carries a deltaAnchor (0 occurrences); FAC-SEM-137 is exercised only through estate_record_rules('estate-record-revision'). The twins agree by reading, but no test holds the verdict path",
      "where": "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_estate.py:361; fabric-estate.mjs verify (dropped + anchorFindings); test/fixtures/contract/make_estate_vectors.mjs (verify section)",
      "severity": "risk",
      "fix": "Generate verify vectors with parent/next anchors (moved back, dropped, same sequence with another hash) from the contract's verifyEstateRecord"
    },
    {
      "what": "Probe order changed on a remote placement: auth.token-file is now recorded before well-known.requires-token, because read_token runs before add_no_token. Tests assert only that requires-token comes before well-known.answers. No in-repo consumer reads results by position",
      "where": "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/check_service.py:193-197",
      "severity": "risk",
      "fix": "None needed unless an outside reader indexes results; note it in the CHANGELOG entry for DEC-0109"
    },
    {
      "what": "fabric_jsvalue now says 'use set_has where the contract keeps a Set' (FAA-107), but only FAC-SEM-134 was moved to it. Other Python estate lookups that mirror a Node Set still use SameValue semantics. They differ only for NaN, which Python's json.loads accepts and Node's JSON.parse rejects",
      "where": "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_estate.py (16 contains-style lookups vs 28 `new Set` in fabric-estate.mjs)",
      "severity": "risk",
      "fix": "Audit the remaining Set-mirroring lookups and move them to set_has, or record why NaN cannot reach them"
    }
  ],
  "evidence": [
    "git diff --stat v0.46.1 v0.48.3 -- plugins test: 55 files; code hunks read for fabric_usage/.mjs, fabric_service facades, fabric_jsvalue, check_service(+_rules), fabric_board_session/.mjs, fabric_delegation/.mjs, fabric_protocols/.mjs, fabric-package.mjs, fabric_estate.py (+ Node twin verify lines)",
    "grep -rnE '_spent_in|_spent_since|usage_spend|usageSpend|_round_usd|spentUsd' -> callers listed in scope; usage_report callers: fabric_usage.py:781, fabric-usage.mjs:501, tests only",
    "Scratch reproduction (RestartTests subclass, _crash_after(effect=False), then a handler that does begin_effect and raises, observed=None, inline spawn) on HEAD -> 'AssertionError: 2 != 1'; handler calls: 2; tools: ... 'com.responder_replace','com.get','com.effect_begin','com.get','com.responder_replace','com.get','com.effect_begin' ...",
    "Same scratch test against `git archive v0.46.1 plugins test` -> OK; handler calls: 1; a single com.effect_begin",
    "python3 -m unittest test_fabric_service_backups test_fabric_service_remote test_fabric_estate test_fabric_service_usage_attribution test_fabric_openrouter -> Ran 101 tests, OK",
    "python3 -m unittest test_fabric_board test_fabric_service test_fabric_kit -> Ran 151 tests, OK (kit.json freshness included)",
    "python3 -m unittest test_fabric_service_feed_protocols test_fabric_delegation test_contract_revisions -> Ran 63, OK (skipped=7, all NOT_RUN: FABRIC_CONTRACT_OLD unset)",
    "node --test fabric-service-backups, fabric-service, fabric-package, kit-hostile-package, fabric-estate, fabric-board -> tests 102, pass 102, fail 0",
    "node --test fabric-service-feed-protocols, fabric-delegation -> pass 18, fail 0",
    "PROTOCOL_REVISIONS Python vs Node computed via python3/node one-liners -> equal: True, no key or value differs",
    "estate-vectors.json: verify 49 cases with 0 'deltaAnchor'; rules 189 with 57 'deltaAnchor' and 29 'profile'; machineProfile 17; deltaAnchor 10"
  ],
  "not_examined": [
    "The Node twin of the resume re-entry: same code shape, not reproduced. The Node harness reaches the fake hub over HTTP, so beginEffect cannot finish within runWork's single setImmediate",
    "The threaded-spawn race for the Python re-entry (the handler finishing before `work.done.is_set()` at fabric_board_session.py:669); not measured",
    "Hosts outside this repo that read budget.spentUsd or days[].costUsd (Fabric Dashboards Spend) and might rely on the old meaning, including the subscription estimate",
    "The 7 contract-revision tests that need FABRIC_CONTRACT_OLD (an installed checkout of 2ce3922)",
    "The full suite, Windows/Linux and the Python 3.9 / Node 18 floors (machine under load; targeted modules only)",
    "check_dashboard_link.py and other probes of a remote origin, for an empty-401 assumption beyond the grep for '401' and 'empty body'"
  ]
}
```

The scratch reproduction is at a scratch file outside the repository, with a v0.46.1 variant beside it. Its body is the `check` for the break.

Skills used: none. This was a read-and-analyse reading, so no family route applied.
