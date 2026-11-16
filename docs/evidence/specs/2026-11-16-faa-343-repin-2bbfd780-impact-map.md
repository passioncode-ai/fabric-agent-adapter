# FAA-343: the repin to Fabric Agent Contract v0.1.0+2026-11-16.6 (2bbfd780): impact map

The contract moved from `v0.1.0+2026-11-16` to `v0.1.0+2026-11-16.6` (tags `.2` to `.6`): DEC-0174 (CT-327), DEC-0175
(CT-325), DEC-0176 (CT-328), DEC-0177 (CT-329), DEC-0178 (CT-333). `contractVersion` stays `0.1.0`; the previous pin
stays in `SUPPORTED_CONTRACT_COMMITS` for bundles issued under it. Source: `git diff 560d6036 2bbfd780` in the
contract, 39 files outside `docs/` and `test/` (the list in the commit message of this change).

| Decision | What changed in the contract | What the adapter does |
|---|---|---|
| DEC-0174 (CT-327) | instance facts beside a subscription runner; the protocol in a protocols list (`src/instance-facts.ts`, its vectors) | `instance-facts-vectors.json` regenerated (38 contract cases, 34 hostile); `fabric_instance_facts` answers them unchanged (`test_fabric_instance_facts`) |
| DEC-0175 (CT-325) | the source tree check reads six forms it missed: a token user, a key behind a percent-encoded separator, a password under a password's name, an escaped `\"`, the new assignment heads, pieces after a `,` (`src/source-rules.ts`) | ported into `fabric_source_check.py` (`ASSIGNED_HEAD_SOURCE`, `_url_secret`, `_JSON_ESCAPES`), which `fabric_source_tree.py` reads; `source-vectors.json` 91 to 107 tree cases, all answered (`test_source_tree`) |
| DEC-0176 (CT-328) | eight false findings narrowed by rule: `LETTER_OR_DIGIT` by code-point ranges, a URL parameter's key at a word start, `URL_BEARER_VALUE`, `DOCUMENTATION_HOST` with `GENERATED_LENGTH`, `PLACEHOLDER`, `PUBLIC_SIGNATURE` with ECDSA and `=>` | the same constants in `fabric_source_url.py` (new sibling of the check), held equal to the vectors' `constants` (`test_constants_are_the_contracts`); masking probes on `h.test`, no documentation host |
| DEC-0177 (CT-329) | `tokenUserName`: a URL's user name of 40 or more `[A-Za-z0-9_-]` with a letter and a digit is a token; `secretUrl` refuses it; `detectorCost` adds `url.username.length` | `token_user_name` and `secret_url` in both `fabric_secrets.py` copies, `tokenUserName` and `secretUrl` in `fabric-secrets.mjs`; a stored manifest URL refuses one (FAC-SEM-057, `test_token_user_name`); `detector_cost` adds the user name as WHATWG writes it, equal to the contract's on six strings (`TokenUserCost`) |
| DEC-0178 (CT-333) | session handoff reads a server's URL as a URL (`src/session-handoff.ts`) | nothing to port: the adapter only names `session-handoff/1` in `PROTOCOL_REVISIONS` and reads no handoff URL |

Waiting, with the reason:

- `recordOrigin` and `fixtures/vectors/folder-attribution.json`'s three new AT-15 cases: the adapter ports `normalizeOrigin`
  only (`origin-vectors.json`, unchanged at this pin), not `recordOrigin`.
- The contract's open edges CT-331, CT-332 (the tree check), CT-333 and CT-334 (command-line secrets): followed at the next pin.

Regenerated on a clean tree of the pin: `channel-agent-vectors.json` and `channel-agent.source.json`, `instance-facts-vectors.json`,
`levels-vectors.json`, `standing-vectors.json`, `load-vectors.json` (the recorded commit), `source-vectors.json`. Every
other generator's output equals the vendored copy, or its inputs did not change between the two pins.
