# Shared by Agate's git hooks (sourced, not a hook itself). POSIX sh; works in Git Bash on Windows.
agate_root=$(git rev-parse --show-toplevel 2>/dev/null) || agate_root=""
agate_cli="$agate_root/.agate/agate.py"

# Run `.agate/agate.py mcp …` with the first Python that works: python3, python, then py -3.
agate_mcp_run() {
  [ -n "$agate_root" ] && [ -f "$agate_cli" ] || return 0
  for agate_py in python3 python; do
    if command -v "$agate_py" >/dev/null 2>&1 && "$agate_py" -c "import sys" >/dev/null 2>&1; then
      "$agate_py" "$agate_cli" mcp --project "$agate_root" "$@"
      return $?
    fi
  done
  if command -v py >/dev/null 2>&1; then
    py -3 "$agate_cli" mcp --project "$agate_root" "$@"
    return $?
  fi
  echo "Agate (git hook): Python not found; MCP configs were not regenerated." >&2
  return 127
}
