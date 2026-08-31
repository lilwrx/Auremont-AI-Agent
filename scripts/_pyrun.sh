#!/usr/bin/env bash
# Cross-platform Python launcher that never blocks AI hooks.
set -u

# Probe candidates because Windows app aliases may not be real interpreters.
works() {
  # shellcheck disable=SC2086
  $1 -c "import sys; sys.exit(0)" >/dev/null 2>&1
}

PY=""
for cand in python3 python "py -3"; do
  if works "$cand"; then PY="$cand"; break; fi
done

if [ -z "$PY" ]; then
  shopt -s nullglob 2>/dev/null || true
  for cand in \
    /c/Users/*/AppData/Local/Programs/Python/Python*/python.exe \
    "/c/Program Files/Python"*/python.exe \
    "/c/Program Files (x86)/Python"*/python.exe \
    /c/Python*/python.exe; do
    if [ -x "$cand" ] && works "$cand"; then PY="$cand"; break; fi
  done
  shopt -u nullglob 2>/dev/null || true
  [ -n "$PY" ] || exit 0
fi

# shellcheck disable=SC2086
exec $PY "$@"
