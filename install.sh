#!/usr/bin/env bash
# Install every skill this plugin ships into the agents hub ~/.agents/skills/.
# Claude Code gets these skills through the plugin; a plain copy in
# ~/.claude/skills would shadow it, so this script never writes there.
# The same rule as the npm installer (bin/fabric-agent-adapter.js): a copy already in the hub is
# kept unless you pass --force, and is then replaced whole (copied beside it and renamed over it),
# so a failure leaves the old copy or nothing. A link in the hub belongs to whoever made it (the
# PassionCode launcher links ~/.passioncode/current/...): it is never replaced, even with --force,
# because a plain copy over it freezes the skill and its owner stops updating it. Python bytecode
# (__pycache__, *.pyc) a checkout's own runs leave behind is never copied.
# Zero dependencies beyond coreutils.
set -euo pipefail

FORCE=0
for ARG in "$@"; do
  case "$ARG" in
    --force) FORCE=1 ;;
    -h|--help) echo "usage: install.sh [--force]"; exit 0 ;;
    *) echo "error: unknown argument $ARG" >&2; echo "usage: install.sh [--force]" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$ROOT/plugins/fabric-agent-adapter/skills"
DEST_ROOT="${HOME}/.agents/skills"

if [ ! -d "$SRC_ROOT" ]; then
  echo "error: skill sources missing at $SRC_ROOT" >&2
  exit 1
fi

FAILED=""
# Iterate rather than name one skill: a skill added to the plugin must not
# require an installer change to reach anybody.
for SRC in "$SRC_ROOT"/*/; do
  NAME="$(basename "$SRC")"
  DEST="${DEST_ROOT}/${NAME}"
  if [ -L "$DEST" ]; then
    case "$(readlink "$DEST")" in
      *"/.passioncode/"*)
        echo "skip: ${NAME} at $DEST is managed by the PassionCode launcher; update it with: npx @passioncode-ai/passioncode@latest update" ;;
      *)
        echo "skip: ${NAME} at $DEST is a link managed elsewhere; remove the link first to install a copy here" ;;
    esac
    continue
  fi
  if [ -e "$DEST" ] && [ "$FORCE" -ne 1 ]; then
    echo "skip: ${NAME} is already at $DEST (rerun with --force to replace it)"
    continue
  fi
  mkdir -p "$DEST_ROOT"
  STAMP="$$-$(date +%s)-${RANDOM}"
  TEMP="${DEST_ROOT}/.${NAME}.installing-${STAMP}"
  OLD="${DEST_ROOT}/.${NAME}.replaced-${STAMP}"
  if cp -R "${SRC%/}" "$TEMP" \
    && find "$TEMP" \( -name __pycache__ -prune -exec rm -rf {} + \) -o \( -name '*.pyc' -exec rm -f {} + \) \
    && { [ ! -e "$DEST" ] || mv "$DEST" "$OLD"; } \
    && { mv "$TEMP" "$DEST" || { [ ! -e "$OLD" ] || mv "$OLD" "$DEST"; false; }; }; then
    rm -rf "$OLD"
    echo "Installed ${NAME} skill -> $DEST"
  else
    rm -rf "$TEMP"
    echo "error: ${NAME} was not installed; the copy that was at $DEST, if any, is unchanged" >&2
    FAILED="${FAILED} ${NAME}"
  fi
done
echo "Claude Code: claude plugin marketplace add passioncode-ai/fabric-agent-adapter && claude plugin install fabric-agent-adapter@fabric-agent-adapter"
echo "Restart your agent: skills load at session start."
if [ -n "$FAILED" ]; then
  echo "error: not installed:${FAILED}" >&2
  exit 1
fi
