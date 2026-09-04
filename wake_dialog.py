#!/usr/bin/env python3
"""Continuous Pepper wake-word dialogue using Pepper's built-in ASR."""

import argparse
import atexit
import getpass
import ipaddress
import json
import os
import random
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from process_utils import launcher_command
from emoji_display import EmojiDisplay


DEFAULT_BAILIAN_API_BASE_URL = (
    "https://llm-jfo114fwn3ncq18m.cn-beijing.maas.aliyuncs.com/api/v1"
)


def ask_base_url():
    base_url = os.getenv("BAILIAN_API_BASE_URL") or DEFAULT_BAILIAN_API_BASE_URL
    if not base_url:
        base_url = input("请输入百炼控制台显示的 DashScope 地址（以 /api/v1 结尾）: ").strip()
    if not base_url.endswith("/api/v1"):
        raise ValueError("DashScope 地址必须以 /api/v1 结尾")
    return base_url.rstrip("/")


def check_callback_network(robot_ip):
    """Reject WSL2 NAT, where Pepper cannot call a service registered in WSL."""
    try:
        kernel_release = Path("/proc/sys/kernel/osrelease").read_text().lower()
    except OSError:
        return
    if "microsoft" not in kernel_release:
        return

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((robot_ip, 9559))
        source_ip = probe.getsockname()[0]
    finally:
        probe.close()
    robot_address = ipaddress.ip_address(robot_ip)
    source_address = ipaddress.ip_address(source_ip)
    if source_address in ipaddress.ip_network("{0}/24".format(robot_address), strict=False):
        return
    if os.getenv("PEPPER_ALLOW_WSL_NAT") == "1":
        print(
            "警告：已跳过 WSL2 NAT 回调检查；请确保 Pepper 能主动访问 {0}:54000。".format(source_ip),
            file=sys.stderr,
        )
        return
    raise SystemExit(
        "检测到 WSL2 NAT 网络：Pepper 是 {0}，但本程序对外地址是 {1}。\n"
        "普通 NAOqi 调用和唤醒事件可以工作，但 Pepper 无法反向调用 PCM 回调服务，"
        "因此麦克风订阅会卡住。\n"
        "请先在 Windows 的 %UserProfile%\\.wslconfig 中启用 networkingMode=mirrored，"
        "执行 wsl --shutdown 后重新进入 WSL。详见 README 的 WSL2 配置。\n"
        "如果已经配置了可用的端口转发，可临时设置 PEPPER_ALLOW_WSL_NAT=1 跳过检查。".format(
            robot_ip, source_ip
        )
    )


def load_greetings(path):
    """Load one greeting from text or several greetings from a JSON array."""
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        raise SystemExit("未找到校友欢迎词文件: {0}".format(path))
    if not content:
        raise SystemExit("校友欢迎词文件为空: {0}".format(path))

    try:
        parsed = json.loads(content)
    except ValueError:
        parsed = content
    if isinstance(parsed, list):
        greetings = [item.strip() for item in parsed if isinstance(item, str) and item.strip()]
    elif isinstance(parsed, str):
        greetings = [parsed]
    else:
        raise SystemExit("校友欢迎词文件必须是文本或 JSON 文本数组: {0}".format(path))
    if not greetings:
        raise SystemExit("校友欢迎词文件中没有可播放文本: {0}".format(path))
    return greetings


def start_periodic_greeting(root, env, greetings, min_minutes, max_minutes):
    """Play the alumni welcome message at a configurable interval until stopped."""
    stop_event = threading.Event()
    last_index = [None]

    def worker():
        while True:
            wait_seconds = random.uniform(min_minutes * 60.0, max_minutes * 60.0)
            if stop_event.wait(wait_seconds):
                return
            choices = list(range(len(greetings)))
            if len(choices) > 1 and last_index[0] in choices:
                choices.remove(last_index[0])
            selected_index = random.choice(choices)
            last_index[0] = selected_index
            try:
                subprocess.run(
                    launcher_command(root, "run_pepper_say"),
                    input=greetings[selected_index].encode("utf-8"), env=env, check=True,
                )
                if min_minutes == max_minutes:
                    next_message = "下一次将在 {0:g} 分钟后播放。".format(min_minutes)
                else:
                    next_message = "下一次将在 {0:g}～{1:g} 分钟内随机播放。".format(
                        min_minutes, max_minutes
                    )
                print("校友欢迎词已自动播报；{0}".format(next_message))
            except (OSError, subprocess.CalledProcessError) as exc:
                print("校友欢迎词自动播报失败：{0}".format(exc), file=sys.stderr)

    thread = threading.Thread(target=worker, name="periodic-alumni-greeting")
    thread.daemon = True
    thread.start()
    return stop_event, thread


def main():
    parser = argparse.ArgumentParser(description="Pepper continuous wake-word dialogue")
    parser.add_argument("--wake-word", default="小信")
    parser.add_argument("--confidence", type=float, default=0.15)
    parser.add_argument("--wake-timeout", type=float, default=3600.0)
    parser.add_argument("--start-timeout", type=float, default=6.0)
    parser.add_argument("--max-seconds", type=float, default=15.0)
    parser.add_argument("--start-threshold", type=int, default=300)
    parser.add_argument("--silence-threshold", type=int, default=400)
    parser.add_argument("--silence-seconds", type=float, default=0.45)
    parser.add_argument("--settle-seconds", type=float, default=1.2,
                        help="wait after Pepper's acknowledgement before opening the microphone")
    parser.add_argument("--autonomous-life-state", choices=("solitary", "disabled"), default="solitary",
                        help="Pepper standby state; solitary keeps an upright, non-interrupting posture")
    parser.add_argument("--keep-autonomous-life", action="store_true",
                        help="do not change Pepper's Autonomous Life state or posture")
    parser.add_argument("--llm-model", default=os.getenv("BAILIAN_LLM_MODEL", "qwen-flash"))
    parser.add_argument("--asr-model", default=os.getenv(
        "BAILIAN_ASR_MODEL", "qwen-audio-3.0-asr-flash-streaming"))
    parser.add_argument("--app-id", default=os.getenv("BAILIAN_APP_ID"))
    parser.add_argument("--use-agent", action="store_true",
                        help="use the published Bailian Agent app instead of the direct model")
    parser.add_argument("--system-prompt-file", default=os.getenv("BAILIAN_SYSTEM_PROMPT_FILE"))
    parser.add_argument("--local-replies-file", default=os.getenv("PEPPER_LOCAL_REPLIES_FILE"),
                        help="JSON file containing exact-match local replies")
    parser.add_argument("--learned-replies-file", default=os.getenv("PEPPER_LEARNED_REPLIES_FILE"),
                        help="JSON file used to remember Bailian answers for later exact matches")
    parser.add_argument("--no-local-replies", action="store_true",
                        help="send every recognized question to Bailian")
    parser.add_argument("--no-learned-replies", action="store_true",
                        help="do not load or save automatically learned replies")
    parser.add_argument("--no-emoji", action="store_true",
                        help="不在 Pepper 胸前平板显示 SVG 表情")
    parser.add_argument("--emoji-port", type=int, default=int(os.getenv("PEPPER_EMOJI_PORT", "54002")),
                        help="胸前平板 SVG 页面端口")
    parser.add_argument("--display-host", default=os.getenv("PEPPER_DISPLAY_HOST"),
                        help="Pepper 访问本机 SVG 页面时使用的 IP 地址")
    parser.add_argument("--greeting-file", default=None,
                        help="fixed alumni welcome text for periodic playback")
    parser.add_argument("--greeting-minutes", type=float, default=5.0,
                        help="minimum interval between alumni greetings")
    parser.add_argument("--greeting-max-minutes", type=float, default=5.0,
                        help="maximum interval between alumni greetings")
    parser.add_argument("--no-periodic-greeting", action="store_true",
                        help="disable periodic alumni welcome playback")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    if args.greeting_minutes <= 0 or args.greeting_max_minutes <= 0:
        raise SystemExit("欢迎词自动播报间隔必须大于 0 分钟")
    if args.greeting_max_minutes < args.greeting_minutes:
        raise SystemExit("--greeting-max-minutes 不能小于 --greeting-minutes")
    greeting_path = Path(args.greeting_file) if args.greeting_file else root / "alumni_welcome_options.json"
    greetings = None
    if not args.no_periodic_greeting:
        greetings = load_greetings(greeting_path)
    robot_ip = os.getenv("PEPPER_ROBOT_IP", "192.168.0.100")
    check_callback_network(robot_ip)
    emoji_display = None
    if not args.no_emoji:
        try:
            emoji_display = EmojiDisplay(root, robot_ip, args.emoji_port, args.display_host)
            atexit.register(emoji_display.close)
            emoji_display.show("idle")
            print("胸前平板待机表情已开启：等待唤醒时也会显示。")
        except (OSError, RuntimeError, ValueError) as exc:
            print("胸前平板表情未开启：{0}".format(exc), file=sys.stderr)
    api_key = os.getenv("DASHSCOPE_API_KEY") or getpass.getpass("请输入 DASHSCOPE_API_KEY（输入不回显）: ")
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY 不能为空")
    base_url = ask_base_url()
    child_env = os.environ.copy()
    child_env["DASHSCOPE_API_KEY"] = api_key
    child_env["BAILIAN_API_BASE_URL"] = base_url
    greeting_stop = None
    greeting_thread = None
    if greetings is not None:
        greeting_stop, greeting_thread = start_periodic_greeting(
            root, child_env, greetings, args.greeting_minutes, args.greeting_max_minutes
        )
        if args.greeting_minutes == args.greeting_max_minutes:
            greeting_schedule = "每 {0:g} 分钟播放一次".format(args.greeting_minutes)
        else:
            greeting_schedule = "每 {0:g}～{1:g} 分钟随机播放一次".format(
                args.greeting_minutes, args.greeting_max_minutes
            )
        print("校友欢迎词自动播报已开启：共 {0} 段，{1}。".format(
            len(greetings), greeting_schedule
        ))

    print("自动语音对话已启动：请说“{0}”唤醒 Pepper；按 Ctrl+C 退出。".format(args.wake_word))
    while True:
        try:
            wake = subprocess.run(
                launcher_command(
                    root, "run_wake_word_test", "--wake-word", args.wake_word,
                    "--confidence", args.confidence, "--timeout", args.wake_timeout,
                    "--autonomous-life-state", args.autonomous_life_state,
                    *( ["--keep-autonomous-life"] if args.keep_autonomous_life else [] )
                ),
                env=child_env,
            )
            if wake.returncode != 0:
                if emoji_display is not None:
                    emoji_display.show("idle")
                print("本次未唤醒，继续等待。", file=sys.stderr)
                time.sleep(1)
                continue
            if emoji_display is not None:
                emoji_display.show("listening")
            subprocess.run(launcher_command(root, "run_pepper_say"), input="我在，请说。".encode("utf-8"),
                           env=child_env, check=True)
            # ALTextToSpeech returns shortly before the physical speaker has
            # completely fallen silent. Avoid feeding that tail into the VAD.
            time.sleep(args.settle_seconds)
            subprocess.run(
                [sys.executable, str(root / "voice_dialog.py"), "--auto-record", "--continuous-auto",
                 "--streaming-asr", "--streaming-agent",
                 "--start-timeout", str(args.start_timeout), "--max-seconds", str(args.max_seconds),
                 "--start-threshold", str(args.start_threshold),
                 "--silence-threshold", str(args.silence_threshold),
                 "--silence-seconds", str(args.silence_seconds),
                 "--settle-seconds", str(args.settle_seconds),
                 "--emoji-port", str(args.emoji_port),
                 "--llm-model", args.llm_model,
                 "--asr-model", args.asr_model] + (
                    ["--use-agent"] if args.use_agent else []
                ) + (
                    ["--app-id", args.app_id] if args.app_id else []
                ) + (
                    ["--system-prompt-file", args.system_prompt_file] if args.system_prompt_file else []
                ) + (
                    ["--local-replies-file", args.local_replies_file] if args.local_replies_file else []
                ) + (
                    ["--learned-replies-file", args.learned_replies_file] if args.learned_replies_file else []
                ) + (
                    ["--no-local-replies"] if args.no_local_replies else []
                ) + (
                    ["--no-learned-replies"] if args.no_learned_replies else []
                ) + (
                    ["--no-emoji"] if args.no_emoji else []
                ) + (
                    ["--display-host", args.display_host] if args.display_host else []
                ) + (
                    ["--emoji-url-base", emoji_display.base_url] if emoji_display is not None else []
                ) + (
                    ["--emoji-control-host", emoji_display.control_host,
                     "--emoji-control-port", str(emoji_display.control_port)]
                    if emoji_display is not None else []
                ),
                env=child_env, check=False,
            )
            print("已回到唤醒等待状态。")
        except KeyboardInterrupt:
            if greeting_stop is not None:
                greeting_stop.set()
                greeting_thread.join(timeout=2.0)
            print("\n已停止自动语音对话。")
            return 0
        except subprocess.CalledProcessError as exc:
            if emoji_display is not None:
                emoji_display.show("error")
            print("语音输出失败：{0}；继续等待唤醒。".format(exc), file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
