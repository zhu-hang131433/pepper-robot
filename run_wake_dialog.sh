#!/usr/bin/env bash
set -euo pipefail

BRIDGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PY="${PEPPER_PYTHON:-}"
if [ -z "$PY" ]; then
    for candidate in "$BRIDGE_ROOT/../pepper_venv/bin/python3" /opt/pepper_venv/bin/python3; do
        if [ -x "$candidate" ]; then
            PY="$candidate"
            break
        fi
    done
fi
if [ -z "$PY" ]; then
    PY="$(command -v python3)"
fi
if [ -z "$PY" ]; then
    echo "python3 未找到" >&2
    exit 1
fi

exec "$PY" "$BRIDGE_ROOT/wake_dialog.py" "$@"
