# Host hook compatibility — bounded delivery brief

Operator request, 2026-10-16: repair hooks for Claude Code, Codex, Hermes, OpenCode, OpenClaw and Pi, including the reported invalid SessionStart JSON. RM-05 (more harnesses). Existing authorization covers implementation, local configuration repair, validation and release under the repository rules. No new model selection or credential borrowing. Keep the current model; no intake question is needed to select these six hosts.

## Scope and evidence

| Requirement | Exit evidence |
|---|---|
| HH-1 Codex accepts structured SessionStart output, Claude remains compatible | A regression fails against baseline, then passes against the corrected output and installed host parser |
| HH-2 Hermes, OpenCode, OpenClaw and Pi use their actual native extension contracts | Versioned upstream/installed-source contract evidence and host-specific adapter tests; native loading receipt for each installed runtime |
| HH-3 Installation preserves unrelated settings and is repeatable/reversible | Dry-run, conflict/hash fence, duplicate install, upgrade and removal tests; local readback |
| HH-4 Malformed input, missing dependency, Fabric unavailable and launched sessions are bounded and harmless | Negative fixtures, timeout checks, no new resident process or accidental enrollment |
| HH-5 Hooks and live Fabric access are different evidence layers | Per-host matrix names supported events, loaded adapter and actual admission result; no invented native parity |
| HH-6 Delivery survives this session | Same-change docs, tests, pushed branch, release/install receipts where gates pass, exact remaining prerequisite for any unavailable host |

No private case data, personal paths, tokens or agent names enter public fixtures or evidence. Upstream/runtime absence cannot be called success. Do not disable unrelated safety hooks to make startup appear green.

## Harvest

- Adapter origin/main 7ad8371, package 0.34.0: fabric_session.py supports claude/codex/kimi; line 464 returns plain text for non-Claude hosts. test_fabric_session.py explicitly expects Codex text.
- AGENTS.md: stdlib Python, native plugin validation, source evidence first, shared registers leased, public privacy boundary.
- Knowledge base agents-first.md: runtime rejoin only Claude; OpenCode/Pi missing runner catalogue as of that record. Verify live state; hooks alone do not add runners.
- Knowledge base principles/how-to-work/rules: parallel bounded modules, isolated worktree, local gates, release acceptance separate from source.
- Installed capability discovery: Claude/Codex/Hermes/OpenCode/Pi executables found; OpenClaw not on PATH. Runtime versions and OpenClaw installation remain research tasks.
- Fabric whoami currently returns hub credential-check unavailable. Board unreadable, not empty. No board claim asserted.
- Prior compatibility lesson: installation/discovery and model/runtime behavior are separate acceptance layers.

Contradictions: existing Codex plain-text test conflicts with the reported JSON parse failure. Verify against installed parser before declaring root cause closed. Generic Claude hook-development examples are guidance only; installed/upstream host schemas govern.

## Work graph and ownership

A custom profile: harvest/contracts → failing fixtures + adapters → native validation + release. Kernel scope, evidence, dependencies and resume apply throughout.

1. Root: Codex/Claude wire contract, shared fabric_session.py, installers, aggregate docs, local setup and integration.
2. Hermes module: installed/upstream hooks, native adapter design and isolated tests. Initial research only; no global writes.
3. OpenCode/Pi module: native extension contracts and isolated tests. Initial research only; no global writes.
4. OpenClaw module: installed/runtime discovery, native contract and isolated tests. Initial research only; no global writes.

Modules return evidence before implementations are assigned exclusive paths. Common contract: context text only, never an approval; do not start/restart Fabric, read its token or enroll a new session from a hook. Existing full Claude lifecycle stays supported; other events are advertised only if proven. Shared source changes belong to root. Native verification follows implementation and fixture gates. Release follows full repository gates; existing signed release workflow, never a new publishing path.

## Resume

Read this brief, inspect the working branch and per-host evidence. Next: pin actual host versions/contracts, reproduce Codex JSON failure, then add adapters with tests before changing installed settings. Durable handoff will name every host status and exact next action.
