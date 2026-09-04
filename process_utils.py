"""Small helpers for launching the Pepper bridge on every supported OS.

The dialogue controller is Python 3, while the NAOqi 2.5 clients must run
under Python 2.7.  Keep the platform-specific shell details in one place so
the application code does not need to know whether it is calling a .sh or a
.cmd launcher.
"""

import os
import subprocess
from pathlib import Path


def launcher_command(root, name, *args):
    """Return a subprocess argv for a launcher next to the Python sources."""
    suffix = ".cmd" if os.name == "nt" else ".sh"
    launcher = Path(root) / (name + suffix)
    if not launcher.exists():
        raise RuntimeError("未找到 Pepper 启动脚本: {0}".format(launcher))

    command_args = [str(arg) for arg in args]
    if os.name == "nt":
        # .cmd files are interpreted by cmd.exe rather than CreateProcess.
        # CALL also preserves the batch file's exit code for the parent.
        return ["cmd.exe", "/d", "/c", "call", str(launcher)] + command_args
    return [str(launcher)] + command_args


def terminate_process_tree(process):
    """Stop a launcher and its child Python 2 process when running on Windows."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.terminate()
