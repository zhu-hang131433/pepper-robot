#!/usr/bin/env bash
set -euo pipefail

# WSL 启动脚本
BRIDGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PEPPER_SDK_ROOT="${PEPPER_SDK_ROOT:-/mnt/c/Users/朱航/Desktop/pepper/pynaoqi-python2.7-2.5.7.1-linux64}"

# 激活 Python3 虚拟环境
if [ -d ~/pepper_venv ]; then
    source ~/pepper_venv/bin/activate
else
    echo "创建 Python 虚拟环境..."
    python3 -m venv ~/pepper_venv
    source ~/pepper_venv/bin/activate
    pip install 'dashscope>=1.25.17'
fi

# 设置 Pepper SDK 环境
export PEPPER_SDK_ROOT="$PEPPER_SDK_ROOT"

echo "=== Pepper 百炼语音对话系统 ==="
echo "SDK 路径: $PEPPER_SDK_ROOT"
echo ""

# 运行主程序
cd "$BRIDGE_ROOT"
python3 wake_dialog.py "$@"
