# FAA-48: native host hooks and full catalog check

Objective: repair the reported Codex SessionStart JSON error, provide native startup context for Claude Code, Codex, Hermes, OpenCode, OpenClaw and Pi, and check every Switchboard host plus the operator's additional list. RM-05. Canonical source: [FAA-48](../backlog.md); [bounded packet and ownership](../evidence/specs/host-hooks-2026-10-16/README.md); [all 31 host results](../evidence/specs/host-hooks-2026-10-16/compatibility.md).

## Implemented

- Codex structured SessionStart output, with native before/after parser reproduction. Leading `[` in the old plaintext preamble triggered JSON parsing.
- Hermes native frozen section, OpenCode system transform, OpenClaw prompt hook, Pi structured/forced/legacy prompt extension. Bounded, silent context failure, no model or enrollment from the hook.
- Native loader installation, source preflight, dry run/hash fences, managed destination checks, preserved foreign settings and permission denial. Codex owned-path upgrades retain matcher/timeout.
- Version 0.35.0 metadata, portable [native hook instructions](../../plugins/fabric-agent-adapter/skills/working-with-fabric/references/native-host-hooks.md), negative fixtures and optional no-model native probes.
- Primary-source capability survey covers 31 unique hosts. Extra hosts have explicit unimplemented/runtime boundaries; catalog MCP/proxy/launch does not imply hooks.

## Decisions and non-claims

No fabricated universal hook protocol, extra Fabric runner registration or non-Claude lifecycle rejoin. Hermes activation uses its native CLI, not a home-grown YAML rewrite. OpenClaw JSON5/explicit denial is refused; removal is ownership-limited. Native host fixture loading is not live Fabric admission, account setup, a model run or proof of every event.

Current tool session is `no-project` in Fabric, after an earlier credential-check outage. No board claim or cross-project delivery was asserted. This source task remains authorized by the operator and tracked locally. No private agent data or machine paths are included in this repository. Existing unrelated machine hooks remain local-only and are not copied here.

The isolated OpenClaw runtime was used for real positive and permission-negative loader checks, then removed after its own process ended because the machine hit ENOSPC. Approximately 628 MiB of available space was recovered (`df -k`: 615704 to 1258640 KiB). After space became available, OpenClaw 2026.10.4 (383c124) was installed permanently through npm. Its reviewed package postinstall completed, `fs-safe` reported ready, and the lifecycle marker was absent. `test/native/openclaw_hooks.py <installed CLI>` passed all three actual native cases: enabled hook, denied conversation access and denied prompt injection. No Gateway or model session was started.

## Verification and delivery

`npm test` exited 0: distribution validator passed; Python 662 tests (22 skipped); Node 228 tests (221 passed, 7 skipped, no failures), including actual OpenCode and Pi loaders. Hermes received a final bounded-input/region-marker delta during that run: all 11 focused Hermes tests passed afterward. Both Claude plugin schema validators and `git diff --check` passed. Independent integration review found no remaining blocking defect. Release and installed receipts are recorded below.

## Exact continuation

FAA-48 is complete for the requested hook repair, installation and 31-host capability check. To verify live project admission, start a fresh host session in an enrolled Fabric project, then call `fabric_whoami`, `com.status` and `com.list` through its registered tools. The current tool session returns `no-project`; no direct HTTP/token workaround or automated enrollment was used. This is an admission follow-up, not a remaining hook parser failure. No durable watcher for a human session restart was installed.

The knowledge-base source is merged. Its existing workspace publication process owns the next wiki refresh; live wiki publication was not asserted. Do not reset the unrelated stale Fabric checkout just to force that refresh.

### Native acceptance completed

- `python3 test/native/codex_hooks.py`: exit 0, native baseline failed with the exact reported error, corrected output completed with context.
- `python3 test/native/claude_hooks.py`: exit 0, isolated SDK initialize only, SessionStart started/responded successfully; no user turn or model call.
- `test/native/hermes_hooks.py --python <Hermes python>`: native discovery, bounded-context rendering and unload passed on final reader implementation.
- `FAA_PI_LOADER=<loader> FAA_OPENCODE_BIN=<binary> node --test test/host-hooks-opencode-pi.test.mjs`: 15 passed including actual native loaders before final hidden-tool negative fixture; final count belongs to aggregate gate.
- OpenClaw 2026.10.4 actual isolated native runtime loaded final adapter with `before_prompt_build`; denied conversation access omitted the typed hook as expected. Optional replay: `test/native/openclaw_hooks.py <runtime>`.
- `claude plugin validate ./plugins/fabric-agent-adapter --strict` and `claude plugin validate . --strict`: exit 0.

No private configuration, hook bodies or account data are part of these receipts.

## Delivery chain

| Owner | Revision / branch | Evidence and entry point |
|---|---|---|
| [fabric-agent-adapter](https://github.com/passioncode-ai/fabric-agent-adapter) | `v0.35.0`, `766dde0abadd929bcdb88a0d90fed23c114c3a7a` | [PR 116](https://github.com/passioncode-ai/fabric-agent-adapter/pull/116), [release workflow](https://github.com/passioncode-ai/fabric-agent-adapter/actions/runs/38967232797), this handoff |
| [passioncode](https://github.com/passioncode-ai/passioncode) | `v0.2.8`, `89a050d89f306d457f12b730156fa9f7ef286bd1`; closure `733668e83824afa578ed91b729c78d582788ef01` | [Release](https://github.com/passioncode-ai/passioncode/releases/tag/v0.2.8), [handoff](https://github.com/passioncode-ai/passioncode/blob/733668e83824afa578ed91b729c78d582788ef01/docs/handoffs/2026-10-16-adapter-0.35.0.md); PC-44 closed |
| [fabric-workspace](https://github.com/passioncode-ai/fabric-workspace) | `main`, `4c51a64d19f1d00d8de4521aadba69fa7516be94` | [PR 244](https://github.com/passioncode-ai/fabric-workspace/pull/244), [handoff](https://github.com/passioncode-ai/fabric-workspace/blob/4c51a64d19f1d00d8de4521aadba69fa7516be94/docs/handoffs/2026-10-16-host-hooks-release.md); owning product facts merged |

A clean remote clone of `v0.35.0` passed `python3 test/validate.py` and contained this handoff and the compatibility matrix. The release merge has the same tree as the locally tested implementation.

Global native loader installation must pass an explicit stable `--script <agents-hub>/working-with-fabric/scripts/fabric_session.py`; do not bind loaders to a release-cache directory that retention later removes. Local configuration hashes are kept local only. They are not repository artifacts.

## Final release and installed receipts

- Adapter workflow [38967232797](https://github.com/passioncode-ai/fabric-agent-adapter/actions/runs/38967232797): success, including Linux/Python/Node, Windows, strict Claude plugin checks, package smoke and npm publication. `npm view @passioncode-ai/fabric-agent-adapter@0.35.0 version` returned `0.35.0` after registry propagation; no repeat publish was attempted.
- Launcher workflow [38968387016](https://github.com/passioncode-ai/passioncode/actions/runs/38968387016): success. Its registry checker downloaded and verified the 554785-byte 0.2.8 tarball. Launcher checks: 148 tests, clone-only vendor, strict marketplace/three-plugin validation and packed smoke passed. A separate pre-existing brand registry finding is retained as PC-45 in its owner repository.
- Global update ran `node bin/passioncode.js update` from the exact tested/tagged launcher tree while registry propagation completed; exit 0. Installed launcher is 0.2.8; adapter is 0.35.0. All 81 tracked adapter files matched the released source in both the installed launcher payload and Claude plugin cache.
- The installed stable Codex helper emitted valid SessionStart JSON with empty stderr. Its existing command definition was unchanged, preserving that definition's trust state.
- Hermes, OpenCode, OpenClaw and Pi installers each planned and applied with their exact stale-plan hash and explicit stable helper path. Readback verified three shims and the OpenClaw path/permissions. `hermes plugins enable fabric-agent-adapter` succeeded; the prompt change takes effect in a new session.
- The permanently installed OpenClaw CLI also inspected the actual installed configuration: plugin `loaded`, typed hook `before_prompt_build` registered. It emitted one origin warning because a locally configured plugin has no npm/ClawHub installation record; trusted-registry status is not claimed, and the context hook remained registered.
- Eleven pre-existing configuration/extension file hashes remained unchanged, including Codex hooks/config and Claude settings. The only changed configuration paths in that baseline were Hermes and OpenClaw. The full Hermes semantic hash did not match its earlier baseline while the host installation also changed; no wholesale rollback or claim of full semantic identity was made. Native activation and current-runtime acceptance passed, and the existing unrelated plugin remains enabled.
- During final verification the Homebrew Hermes runtime disappeared and PATH selected native Hermes 0.21.5 (2026.9.24, upstream a928a959). Two native probes using that launcher's own `--print-runtime-command` bootstrap passed discovery, registration observation, section rendering and unload with zero model calls. Its stderr was isolated-runtime dependency preparation, not adapter JSON or hook failure; do not reuse the earlier 0.21.4 empty-stderr claim for this host version.
- KB checks: Node 24, 163 tests passed; 63 release cells/links matched, one unversioned row skipped; both exact-head hosted checks passed before merge.

Existing sessions may cache prior skills/plugins. New-session consumption is the supported activation boundary. No model/provider acceptance or live Fabric admission is claimed by these receipts. Private configuration, its backups and hash baselines remain local only.

## Skills used

`task-pipeline`: bounded delivery and checks; `agent-sync`: ownership and Git leases; `make-skill`: plugin construction and release validation; foreign `hook-development`: Claude hook implementation reference only, not a second router; `openai-docs`: Codex contract/source verification; `working-in-passioncode` and `working-with-fabric`: platform rules and admission boundaries; `evidence-docs`: source-linked receipts; `maintaining-fabric-workspace`: KB ownership/publication; `copywriting`: launcher text-registry constraints and existing debt classification.
