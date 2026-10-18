#!/usr/bin/env bash
set -euo pipefail
workspace_root=$(cd "$(dirname "$0")/.." && pwd)
export CODEX_HOME="$workspace_root/.codex"
export HOME="$workspace_root"
umask 077
mkdir -p "$CODEX_HOME"
chmod 700 "$CODEX_HOME"
codex_bin="$workspace_root/.local/node_modules/.bin/codex"
test -x "$codex_bin" || { echo 'Codex is not installed in this workspace.' >&2; exit 1; }
cmd=${1:-help}
if (($#)); then shift; fi
case "$cmd" in
  status) exec "$codex_bin" login status "$@" ;;
  login) exec "$codex_bin" login --device-auth "$@" ;;
  run) exec "$codex_bin" exec "$@" ;;
  review) exec "$codex_bin" review "$@" ;;
  *) exec "$codex_bin" "$cmd" "$@" ;;
esac
