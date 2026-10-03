#!/usr/bin/env bash
# Install every skill this plugin ships into the agents hub ~/.agents/skills/.
# Claude Code gets these skills through the plugin; a plain copy in
# ~/.claude/skills would shadow it, so this script never writes there.
# Idempotent: rerun to overwrite a copy it made. A link in the hub belongs to whoever made
# it (the PassionCode launcher links ~/.passioncode/current/...): it is never replaced, because
# a plain copy over it freezes the skill and its owner stops updating it.
# Zero dependencies beyond coreutils.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$ROOT/plugins/fabric-agent-adapter/skills"
DEST_ROOT="${HOME}/.agents/skills"

if [ ! -d "$SRC_ROOT" ]; then
  echo "error: skill sources missing at $SRC_ROOT" >&2
  exit 1
fi

# Iterate rather than name one skill: a skill added to the plugin must not
# require an installer change to reach anybody.
for SRC in "$SRC_ROOT"/*/; do
  NAME="$(basename "$SRC")"
  DEST="${DEST_ROOT}/${NAME}"
  if [ -L "$DEST" ]; then
    case "$(readlink "$DEST")" in
      *"/.passioncode/"*)
        echo "skip: ${NAME} at $DEST is managed by the PassionCode launcher — update it with: npx @passioncode-ai/passioncode@latest update" ;;
      *)
        echo "skip: ${NAME} at $DEST is a link managed elsewhere — remove the link first to install a copy here" ;;
    esac
    continue
  fi
  mkdir -p "$DEST_ROOT"
  rm -rf "$DEST"
  cp -R "${SRC%/}" "$DEST"
  echo "Installed ${NAME} skill -> $DEST"
done
echo "Claude Code: claude plugin marketplace add passioncode-ai/fabric-agent-adapter && claude plugin install fabric-agent-adapter@fabric-agent-adapter"
echo "Restart your agent — skills load at session start."
