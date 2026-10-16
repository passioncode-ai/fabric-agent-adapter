# Handoff — FAA-48: Codex accepts the session-start preamble (0.34.2)

**Objective.** A finding on the Fabric board (from another project's session, 2026-10-16) reported that in Codex the
adapter's SessionStart hook exits 0, prints `[fabric-agent-adapter] …`, and Codex refuses it with `invalid session
start JSON output`. Fix it and release 0.34.2.

## Done

- **Root cause, read in Codex's source** (`codex-rs/hooks/src/events/session_start.rs`): stdout that parses as the
  SessionStart output is used; stdout that only *looks like* JSON (it starts with `{` or `[`) fails; other text
  becomes context. Our preamble starts with `[fabric-agent-adapter]`, so Codex took it for a JSON array and failed it.
  Confirmed live with Codex 0.162.1: the installed (0.34.1) hook prints that text, and a `codex exec` session's record
  holds no preamble.
- **Fix**: `hook_session_start` writes Codex's SessionStart hook JSON (`hookSpecificOutput.hookEventName` +
  `additionalContext`, Codex's generated output schema, the same shape Claude Code takes). Kimi Code keeps plain text:
  its hook runner (read from the installed 2.1.1 binary) tries `JSON.parse` and reads `message`, not
  `additionalContext`, and takes non-JSON stdout as text.
- **Codex hook trust**: Codex keys a hook's trust by event, group and index (from a second board message, a host
  contract survey). `install-host-hooks --host codex` already appends last; `--remove` now names the SessionStart groups
  after ours that it moves, which Codex asks the person to approve again in `/hooks`.
- Tests: the old test asserted the bug (`assertNotIn("hookSpecificOutput")` for Codex); it now holds the output to
  Codex's schema. New: Kimi stays plain text; the removal warning. Three planted defects caught.
- Docs: `references/session-hooks.md`.

## Open

- After the release and `npx --yes @passioncode-ai/passioncode@latest update`: a live `codex exec` session must show the
  preamble in its record (the post-deploy check).
- The rest of the board's host survey targets Fabric's harness (session homes, `--strict-mcp-config`, PATH, the Codex
  enrollment cap), not this repository.

## Next task

Release 0.34.2, run the live Codex check, reply on the board thread.
