# FAA-111: the blind product reading of v0.46.1..v0.48.3

Tier 3 (`task-pipeline:verifier-product`), 2026-10-24, verbatim except local paths. What became of each finding: [README](README.md).

Verdict: **pass**. Nothing documented in 0.47.0 to 0.48.3 is false enough to block. Five risks remain and should ship named: the remote-probe doc understates when its 401 check can wrongly fail, the usage doc doesn't warn about the spend change for services on an older kit copy, and three backlog wording issues (one of them three em dashes).

The receipts all check out. Tags, merge commits, release runs and npm versions agree for FAA-105, 107, 109, 110, 86 and 91. The FAA-91 row still read "open" at the `v0.48.3` tag; main (PR #187) has since recorded it as done. The versions and the contract pin match everywhere they appear, and `python3 test/validate.py` exits 0.

On kit-modules.md: it lists modules, not exported functions. No module was added in this range, so it makes no claim these releases broke. The new names (`usage_spend`, `_round_usd`, `set_has`, `machine_profile`, `delta_anchor_of`) are documented in usage.md and estate-record.md.

```json
{
  "node": "faa-0.47.0..0.48.3",
  "tier": "product",
  "verdict": "pass",
  "scope": [
    "CHANGELOG.md:3-104, entries 0.47.0 to 0.48.3, read against both twins' behaviour",
    "README.md:274-281 (pin), SKILL-CARD.md (four version and contract rows), AGENTS.md (unchanged in range), docs/DOCMAP.md",
    "the four SKILL.md files (metadata version and pin); building-fabric-services/SKILL.md:346 (remote well-known answers 401 with an empty body)",
    "references: estate-record.md (Machine profiles, The delta anchor), usage.md:80-86 (limits count money only), remote-placement.md:67-75 (DEC-0109 probe), protocol.md:1-17, delegation.md:90-96, board.md:131-136, package.md:45-51, kit-modules.md (whole), profiles.md:110-113 (Usage by route)",
    "recipes/support-agent/README.md:31-37 (FAA-84 limit) and its test",
    "docs/backlog.md rows FAA-84 (line 100), FAA-86, FAA-91 (line 107), FAA-104 to FAA-110 (lines 117-127), at the tag and on main",
    "docs/handoffs/2026-10-23-*.md (5) and 2026-10-24-read-folder-0.48.3.md",
    "features on the same path: the usage report Fabric Dashboards' Spend view reads (budget.spentUsd beside days[].costUsd), the probe's well-known.requires-token rule a person reads in its evidence, the facades' re-exports, the em dash validator's coverage"
  ],
  "confirms": [
    "Versions agree at 0.48.3 in package.json:3, plugin.json:6, marketplace.json:15, SKILL-CARD.md:5/28/51/72 and all four SKILL.md metadata blocks. The pin 2f020a696453ae299b123517f14957f6a1354379 agrees in fabric-contract.lock.json:5, README.md:277, SKILL-CARD.md, SKILL.md metadata and protocol.md:4. test/validate.py exits 0",
    "Every receipt matches: v0.47.0=0f2c37a (#173), v0.47.1=084ebbe (#176), v0.48.0=e19b299 (#178), v0.48.1=787c352 (#181), v0.48.2=565eaed (#183), v0.48.3=7dab86a (#186). Release runs 39940767558, 39964185276, 39971082088, 39989091246, 40013478433 and 40051057561 each read success on their tag. npm lists 0.47.0 to 0.48.3, and 0.48.3's gitHead is 7dab86a",
    "estate-record.md: the machine-profile section matches the Python profile rule (fabric_estate.py:653-697, FAC-SEM-134): an unknown value, a hub key on a member or view machine, a view machine that places, holds or fills a secret. machine_profile answers full, its value or None. The delta-anchor section matches delta_anchor_of and FAC-SEM-137 (fabric_estate.py:790-819). Node exports machineProfile, deltaAnchorOf and MACHINE_PROFILES",
    "usage.md:80-86 matches both twins: a spending limit counts money only, a window spent only on a subscription spends 0, and money is null only when calls off a subscription exist and none is priced (fabric_usage.py:507-595, fabric-usage.mjs usageSpend/money). The CHANGELOG line 'The day's costUsd still sums every route' holds",
    "The 0.48.1 rounding claim holds: _round_usd (fabric_usage.py:160) is used for both costUsd and spentUsd, as CHANGELOG.md:31-33 says, and the facade re-exports usage_spend and _round_usd",
    "package.md:48-51 describes the Node folder checks exactly as fabric-package.mjs does them after 0.48.3. board.md:134-136 states FAA-86's behaviour. delegation.md:93-94 places profile-forbids under 403. The protocol register (fabric_protocols.py:16-18) carries fabric-agent-call/1 and the five DEC-0111 names, as protocol.md and the CHANGELOG say",
    "SKILL.md:346 ('401 with an empty body') is still true of the kit's own server: sample-remote-service.mjs:49 sends 401 with no body",
    "recipes/support-agent/README.md:31-37: the .md/.py/.sh country codes are right (Moldova, Paraguay, Saint Helena), and test_a_file_name_on_a_country_code_reads_as_a_link_unless_a_cited_entry_carries_it pins both sides",
    "kit-modules.md lists modules, not functions, and no module was added in this range, so its table and the every-module-documented test still hold. docs/DOCMAP.md needs no change",
    "The six handoffs agree with the git history and with each other, and each names an exact next task. No em dash appears in the recipe README, the handoffs, the two briefs, or any validator-scanned file"
  ],
  "findings": [
    {
      "what": "The remote-placement doc says the no-token 401 check can wrongly fail in only one case (a page containing the pid). The code fails it in at least two more. (1) Any JSON 401 body with an object carrying a 'service' or 'process' key anywhere inside it fails, and the evidence wrongly says 'the body carries the well-known document'. (2) A proxy sign-in page that names the service's id fails, for example an identity-proxy page titled after an application named like the service. The host name is stripped, but the application name is not",
      "where": "plugins/fabric-agent-adapter/skills/building-fabric-services/references/remote-placement.md:72-75; check_service_rules.py _carries_document and no_token_verdict",
      "severity": "risk",
      "fix": "Replace 'One false FAIL remains possible' with the list of cases that fail: a JSON body with a service or process member, a page naming the id or id.instance (e.g. a proxy application named after the service), and the pid case. Or narrow _carries_document to the document's own shape, and give the evidence for a stray member its own wording",
      "check": "python3 -c 'from check_service_rules import no_token_verdict as v; print(v(401, b\"{\\\"error\\\":\\\"unauthorized\\\",\\\"service\\\":\\\"cloudflare-access\\\"}\", [\"example-agent\"], \"agent.example.com\"))' run in scripts/ prints FAIL today. After the fix, either the doc names this case (judgement) or the call prints PASS"
    },
    {
      "what": "A number on a dashboard moves, and usage.md does not warn about the period when old and new kits coexist. For a service that uses a subscription, budget.spentUsd and each machine limit's spentUsd drop from the list-price estimate to 0 when it re-vendors the 0.48.0 kit. A service on an older copied kit keeps reporting the estimate as spent money. In the same view, days[].costUsd still includes the estimate, so a day's total and the budget's spend now diverge. estate-record.md gives an 'update a copied kit' note for profile and deltaAnchor (lines 157, 174), but usage.md has none for DEC-0110. profiles.md 'Usage by route' does not say a subscription row's cost is an estimate",
      "where": "plugins/fabric-agent-adapter/skills/building-fabric-services/references/usage.md:80-86; references/profiles.md:110-113",
      "severity": "risk",
      "fix": "Add one sentence to usage.md: a service built before 0.48.0 counts a subscription's estimate in spentUsd until it re-vendors fabric_usage (fabric_kit.py install <dir> --module fabric_usage), and a day's costUsd includes the estimate while a limit's spentUsd does not. In profiles.md, link 'Usage by route' to that paragraph",
      "check": "judgement: usage.md read for the mixed-kit window and the costUsd/spentUsd difference; whether Fabric Dashboards' Spend view labels the estimate needs its owner"
    },
    {
      "what": "Three em dashes (U+2014) were introduced into a text people read in this range: the FAA-107 backlog row uses them as list bullets. The workspace backlog view publishes these rows. test/validate.py:846 exempts docs/ as dated records, so the gate did not catch them",
      "where": "docs/backlog.md:123",
      "severity": "risk",
      "fix": "Replace the '<br>' plus em dash bullets with '<br>(1) ', '(2) ', '(3) ' or semicolons, under an agent-sync lease on docs/backlog.md",
      "check": "sed -n 123p docs/backlog.md | grep -c \"$(printf '\\342\\200\\224')\" prints 0"
    },
    {
      "what": "The FAA-84 row is stale. It says 'No behaviour change, no release: it ships with the next one', but 0.48.3 shipped it: CHANGELOG.md:13-17 lists it under 0.48.3 Documentation, the 0.48.3 handoff (line 10) says the release carries it, and it merged as PR #185 (3801220) before the v0.48.3 tag. The row names no PR or release",
      "where": "docs/backlog.md:100",
      "severity": "risk",
      "fix": "Append 'shipped in 0.48.3: PR #185 merged as 3801220, tag v0.48.3' to the row's status",
      "check": "judgement: row 100 read against git log --merges v0.48.2..v0.48.3 and CHANGELOG.md:13-17"
    },
    {
      "what": "At the v0.48.3 tag, the FAA-91 row read 'open 2026-10-24: release 0.48.3' while the CHANGELOG called it Fixed. Main corrected it after the tag (680f362, PR #187), so main is now consistent. The released copy of the repository carries the open row. Because docs/ is not in package.json's files list, npm users never see it",
      "where": "docs/backlog.md:107 at v0.48.3; fixed on main",
      "severity": "risk",
      "fix": "None needed on main. When a release closes a row, land the receipts in the release PR or accept the one-commit lag as the pattern",
      "check": "git show v0.48.3:docs/backlog.md | grep '^| FAA-91' shows 'open'; git show HEAD:docs/backlog.md | grep '^| FAA-91' shows 'done 2026-10-24 in 0.48.3'"
    }
  ],
  "evidence": [
    "git diff --stat v0.46.1 v0.48.3: 70 files. git log v0.48.3..HEAD: only 680f362 and 9c84526 (backlog and handoff receipts)",
    "for t in v0.47.0..v0.48.3: git rev-list -n1 gives 0f2c37a, 084ebbe, e19b299, 787c352, 565eaed, 7dab86a, matching the merge commits of PRs #173, #176, #178, #181, #183 and #186",
    "gh run view on the six run ids: each 'release <tag> <sha> success'",
    "npm view @passioncode-ai/fabric-agent-adapter versions lists 0.47.0, 0.47.1, 0.48.0, 0.48.1, 0.48.2, 0.48.3; npm view @0.48.3 gitHead gives 7dab86a452ec4b238b72855bdbc61175c7c6e185",
    "python3 test/validate.py exits 0",
    "git diff v0.46.1 HEAD -- . ':!test/fixtures' | grep '^+' | grep U+2014: hits only in docs/backlog.md (FAA-107 row, 3) and in code comments in fabric_estate.py and fabric-estate.mjs (exempt)",
    "grep for U+2014 across recipes/, the six handoffs and the two 2026-10-23 briefs: no lines",
    "test/validate.py:846-860: the em dash scan covers README, AGENTS, SKILL-CARD, CONTRIBUTING, SECURITY, SKILL.md, references, evals, install.sh, the bin, HTML assets and .github. It does not cover docs/ (declared dated records) or recipes/*/README.md",
    "Direct calls to no_token_verdict: a JSON body {error, service} gives ('FAIL', 'the body carries the well-known document'); an HTML page titled 'Sign in to example-agent' gives FAIL on the identity value",
    "git diff v0.46.1 v0.48.3 -- fabric_service.py fabric-service.mjs: facade adds usage_spend, _round_usd / usageSpend",
    "git diff --stat v0.46.1 v0.48.3 -- test/evals: no change"
  ],
  "not_examined": [
    "Whether Fabric Dashboards' Spend view (another repository) follows DEC-0110 and labels a subscription's estimate apart from money. That is the downstream half of the usage finding and needs its owner",
    "Whether Fabric Inbox's remote placement still passes 34 of 34 (CHANGELOG.md:52-53, the 0.48.0 handoff line 16). This needs the operator's machine and the service token",
    "The launcher versions passioncode 0.2.33 and 0.2.34 (FAA-86 and FAA-91 rows, no PR link) and the 'byte-identical, 155 files' install claims. These are not in this repository",
    "The test counts in the handoffs (Python 1003 to 1018, Node 321 to 324). The suites were not rerun",
    "Whether reference prose changes (estate-record.md, usage.md, remote-placement.md) count as 'instructional prose' that AGENTS.md requires evals for first. No file under test/evals changed in this range",
    "protocol.md:87 lists a receipt's route as 'subscription or key' without platform-metered. That wording predates this range"
  ]
}
```

Key files:
- plugins/fabric-agent-adapter/skills/building-fabric-services/references/remote-placement.md
- plugins/fabric-agent-adapter/skills/building-fabric-services/references/usage.md
- plugins/fabric-agent-adapter/skills/building-fabric-services/references/profiles.md
- plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/check_service_rules.py
- docs/backlog.md
- test/validate.py

I didn't use any skill for this reading. No files were edited.
