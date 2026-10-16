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

`npm test` exited 0: distribution validator passed; Python 662 tests (22 skipped); Node 228 tests (221 passed, 7 skipped, no failures), including actual OpenCode and Pi loaders. Hermes received a final bounded-input/region-marker delta during that run: all 11 focused Hermes tests passed afterward. Both Claude plugin schema validators and `git diff --check` passed. Independent integration review found no remaining blocking defect. Release and installed receipts remain pending below.

## Exact continuation

Commit/push the tested isolated branch, integrate through PR, release v0.35.0 through the existing tag workflow and verify installed skill/loader bytes. Update the launcher member pin before its next global update so it cannot downgrade the adapter. Record any concrete host/admission prerequisite below. Do not reset another checkout or dispatch an extra full CI run per push.

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
| [passioncode](https://github.com/passioncode-ai/passioncode) | `codex/launcher-adapter-035`, 0.2.8 pending | Member pin updates adapter to 0.35.0; release/install receipt pending |
| [fabric-workspace](https://github.com/passioncode-ai/fabric-workspace) | `codex/host-hooks-release`, pending | Owning products/how-to-work facts; publication uses existing workspace sync |

A clean remote clone of `v0.35.0` passed `python3 test/validate.py` and contained this handoff and the compatibility matrix. The release merge has the same tree as the locally tested implementation.

Global native loader installation must pass an explicit stable `--script <agents-hub>/working-with-fabric/scripts/fabric_session.py`; do not bind loaders to a release-cache directory that retention later removes. Local configuration hashes are kept local only. They are not repository artifacts.
