#!/usr/bin/env bash
set -euo pipefail

BRIDGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PEPPER_RUNTIME="$BRIDGE_ROOT/.runtime/usr"
PEPPER_SDK_ROOT="${PEPPER_SDK_ROOT:-$BRIDGE_ROOT/../pynaoqi-python2.7-2.5.7.1-linux64}"
ROBOT_IP="${PEPPER_ROBOT_IP:-192.168.0.100}"

if [ ! -d "$PEPPER_SDK_ROOT/lib/python2.7/site-packages" ]; then
    echo "Pepper NAOqi SDK 路径无效: $PEPPER_SDK_ROOT" >&2
    exit 1
fi

export PYTHONHOME="$PEPPER_RUNTIME"
export PYTHONPATH="$PEPPER_SDK_ROOT/lib/python2.7/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$PEPPER_RUNTIME/lib/x86_64-linux-gnu:$PEPPER_SDK_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

exec "$PEPPER_RUNTIME/bin/python2.7" "$BRIDGE_ROOT/pepper_pcm_stream.py" --robot-ip "$ROBOT_IP" "$@"
