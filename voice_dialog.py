#!/usr/bin/env python3
"""Pepper voice dialogue: record -> ASR -> Agent -> Pepper TTS."""

import argparse
import atexit
from datetime import datetime
import getpass
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from asr_pcm_stream import ASRThrottledError, transcribe_pepper_stream
from emoji_display import EmojiDisplay
from process_utils import launcher_command


APP_ID = "3905b256f5fc43f2a71c3c8eb707ba6d"
DEFAULT_BAILIAN_API_BASE_URL = (
    "https://llm-jfo114fwn3ncq18m.cn-beijing.maas.aliyuncs.com/api/v1"
)


def normalize_local_question(text):
    """Normalize a short ASR result for exact local intent matching."""
    return re.sub(r"[\s，。！？、；：,.!?;:'\"“”‘’（）()]+", "", text).lower()


def is_reply_worthy_text(text):
    """Accept phrases/sentences, but ignore empty or single-character ASR noise."""
    return len(normalize_local_question(text)) >= 2


def load_local_replies(path):
    """Load optional exact-match replies without making startup depend on them."""
    try:
        raw_replies = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        print("本地快速回答配置无效，已忽略：{0}".format(exc), file=sys.stderr)
        return {}
    if not isinstance(raw_replies, dict):
        print("本地快速回答配置必须是 JSON 对象，已忽略。", file=sys.stderr)
        return {}
    replies = {}
    for question, answer in raw_replies.items():
        if isinstance(question, str) and isinstance(answer, str) and answer.strip():
            replies[normalize_local_question(question)] = answer.strip()
    return replies


def save_learned_reply(path, question, answer, protected_replies=None):
    """Persist an answered question so the next exact match can skip the LLM."""
    normalized_question = normalize_local_question(question)
    answer = (answer or "").strip()
    if not normalized_question or not answer:
        return False
    if protected_replies and normalized_question in protected_replies:
        return False

    try:
        raw_replies = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw_replies = {}
    except (OSError, ValueError) as exc:
        print("自动学习问答配置无效，未写入：{0}".format(exc), file=sys.stderr)
        return False
    if not isinstance(raw_replies, dict):
        print("自动学习问答配置必须是 JSON 对象，未写入。", file=sys.stderr)
        return False

    stored_key = None
    for existing_question in raw_replies:
        if isinstance(existing_question, str) and normalize_local_question(existing_question) == normalized_question:
            stored_key = existing_question
            break
    if stored_key is None:
        stored_key = question.strip()
    if raw_replies.get(stored_key) == answer:
        return False

    raw_replies[stored_key] = answer
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(path.name + ".tmp")
        temp_path.write_text(
            json.dumps(raw_replies, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(str(temp_path), str(path))
    except OSError as exc:
        print("自动学习问答写入失败：{0}".format(exc), file=sys.stderr)
        return False
    return True


def local_quick_reply(user_text, configured_replies=None, now=None):
    """Return (answer, end_dialogue) for safe, narrow local intents."""
    question = normalize_local_question(user_text)
    configured_replies = configured_replies or {}
    if question in configured_replies:
        return configured_replies[question], False

    exact_replies = {
        "你好": "你好，我是小信，很高兴见到你。",
        "您好": "您好，我是小信，很高兴为您服务。",
        "嗨": "嗨，你好呀。",
        "哈喽": "哈喽，你好呀。",
        "hello": "Hello，你好呀。",
        "早上好": "早上好，祝你今天心情愉快。",
        "上午好": "上午好，很高兴见到你。",
        "下午好": "下午好，很高兴见到你。",
        "晚上好": "晚上好，很高兴见到你。",
        "你好吗": "我很好，谢谢关心。",
        "你是谁": "我是 Pepper 机器人小信，负责现场语音接待。",
        "请问你是谁": "我是 Pepper 机器人小信，负责现场语音接待。",
        "你叫什么": "我叫小信，是一台 Pepper 机器人。",
        "你叫什么名字": "我叫小信，是一台 Pepper 机器人。",
        "你的名字是什么": "我叫小信，是一台 Pepper 机器人。",
        "你能做什么": "我可以和你聊天，也可以回答现场活动相关的问题。",
        "你会做什么": "我可以和你聊天，也可以回答现场活动相关的问题。",
        "你会什么": "我可以和你聊天，也可以回答现场活动相关的问题。",
        "谢谢": "不客气，很高兴能帮到你。",
        "谢谢你": "不客气，很高兴能帮到你。",
        "多谢": "不客气。",
        "辛苦了": "不辛苦，谢谢你的关心。",
        "听得到吗": "听得到，请说吧。",
        "你能听到吗": "听得到，请说吧。",
        "能听见吗": "能听见，请说吧。",
    }
    if question in exact_replies:
        return exact_replies[question], False

    current = now or datetime.now()
    if question in {"几点了", "现在几点", "现在几点了", "现在是什么时间", "现在时间"}:
        return "现在是{0}点{1:02d}分。".format(current.hour, current.minute), False
    if question in {"今天几号", "今天是几号", "今天日期", "今天是什么日期"}:
        return "今天是{0}年{1}月{2}日。".format(current.year, current.month, current.day), False
    if question in {"今天星期几", "今天是星期几", "今天周几", "今天是周几"}:
        weekdays = "一二三四五六日"
        return "今天是星期{0}。".format(weekdays[current.weekday()]), False
    if question in {"再见", "拜拜", "bye", "下次再见"}:
        return "再见，需要我的时候再叫小信。", True
    return None, False


def ask_base_url():
    base_url = os.getenv("BAILIAN_API_BASE_URL") or DEFAULT_BAILIAN_API_BASE_URL
    if not base_url:
        base_url = input("请输入百炼控制台显示的 DashScope 地址（以 /api/v1 结尾）: ").strip()
    if not base_url.endswith("/api/v1"):
        raise ValueError("DashScope 地址必须以 /api/v1 结尾")
    return base_url.rstrip("/")


def call_agent(api_key, base_url, app_id, prompt, session_id=None):
    payload = {"input": {"prompt": prompt}, "parameters": {"incremental_output": False, "enable_thinking": False}}
    if session_id:
        payload["input"]["session_id"] = session_id
    endpoint = base_url + "/apps/" + app_id + "/completion"
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError("百炼 Agent HTTP {0}: {1}".format(exc.code, exc.read().decode("utf-8", "replace")))
    except URLError as exc:
        raise RuntimeError("无法连接百炼 Agent: {0}".format(exc))

    output = result.get("output") or {}
    answer = output.get("text")
    if not answer:
        raise RuntimeError("百炼 Agent 未返回文本: {0}".format(result.get("message") or result))
    return answer, output.get("session_id") or session_id


def call_agent_stream(api_key, base_url, app_id, prompt, on_delta, session_id=None):
    """Read incremental Agent 2.0 SSE output and invoke on_delta for each chunk."""
    payload = {"input": {"prompt": prompt}, "parameters": {"incremental_output": True, "enable_thinking": False}}
    if session_id:
        payload["input"]["session_id"] = session_id
    request = Request(
        base_url + "/apps/" + app_id + "/completion",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-DashScope-SSE": "enable",
        },
    )
    answer_parts = []
    response_session_id = session_id
    try:
        with urlopen(request, timeout=60) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line or line.startswith("event:") or line.startswith("id:"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                output = event.get("output") or {}
                delta = output.get("text") or ""
                if delta:
                    answer_parts.append(delta)
                    on_delta(delta)
                response_session_id = output.get("session_id") or response_session_id
                if event.get("code") and event.get("code") != "Success":
                    raise RuntimeError(event.get("message") or str(event))
    except HTTPError as exc:
        raise RuntimeError("百炼 Agent HTTP {0}: {1}".format(exc.code, exc.read().decode("utf-8", "replace")))
    except URLError as exc:
        raise RuntimeError("无法连接百炼 Agent: {0}".format(exc))
    answer = "".join(answer_parts).strip()
    if not answer:
        raise RuntimeError("百炼 Agent 未返回文本")
    return answer, response_session_id


def _parse_generation_delta(event):
    output = event.get("output") or {}
    delta = output.get("text") or ""
    if not delta:
        for choice in output.get("choices") or []:
            message = choice.get("message") or {}
            if message.get("content"):
                delta = message["content"]
                break
    return delta


def call_llm_stream(api_key, base_url, model, messages, on_delta):
    """Call a DashScope qwen model directly with incremental SSE output."""
    payload = {
        "model": model,
        "input": {"messages": messages},
        "parameters": {"incremental_output": True, "enable_thinking": False, "result_format": "message"},
    }
    request = Request(
        base_url + "/services/aigc/text-generation/generation",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-DashScope-SSE": "enable",
        },
    )
    answer_parts = []
    try:
        with urlopen(request, timeout=60) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("code") and event.get("code") != "Success":
                    raise RuntimeError(event.get("message") or str(event))
                delta = _parse_generation_delta(event)
                if delta:
                    answer_parts.append(delta)
                    on_delta(delta)
    except HTTPError as exc:
        raise RuntimeError("百炼模型 HTTP {0}: {1}".format(exc.code, exc.read().decode("utf-8", "replace")))
    except URLError as exc:
        raise RuntimeError("无法连接百炼模型: {0}".format(exc))
    answer = "".join(answer_parts).strip()
    if not answer:
        raise RuntimeError("百炼模型未返回文本")
    return answer


def call_llm(api_key, base_url, model, messages):
    """Call a DashScope qwen model directly and wait for the full answer."""
    payload = {
        "model": model,
        "input": {"messages": messages},
        "parameters": {"enable_thinking": False, "result_format": "message"},
    }
    request = Request(
        base_url + "/services/aigc/text-generation/generation",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError("百炼模型 HTTP {0}: {1}".format(exc.code, exc.read().decode("utf-8", "replace")))
    except URLError as exc:
        raise RuntimeError("无法连接百炼模型: {0}".format(exc))

    output = result.get("output") or {}
    answer = output.get("text") or ""
    if not answer:
        for choice in output.get("choices") or []:
            message = choice.get("message") or {}
            if message.get("content"):
                answer = message["content"]
                break
    answer = answer.strip()
    if not answer:
        raise RuntimeError("百炼模型未返回文本: {0}".format(result.get("message") or result))
    return answer


class SentenceSpeaker(object):
    """Speak completed Chinese sentences while later Agent chunks still arrive."""

    def __init__(self, root, on_speaking=None):
        self._root = root
        self._on_speaking = on_speaking
        self._pending = ""
        self._queue = queue.Queue()
        self._error = None
        self._speaking_started = False
        self._worker = threading.Thread(target=self._run, name="pepper-tts-worker")
        self._worker.daemon = True
        self._worker.start()

    def add(self, delta):
        self._pending += delta
        while True:
            positions = [self._pending.find(mark) for mark in u"。！？；\n" if self._pending.find(mark) >= 0]
            if not positions:
                return
            end = min(positions) + 1
            self._queue.put(self._pending[:end].strip())
            self._pending = self._pending[end:]

    def finish(self):
        if self._pending.strip():
            self._queue.put(self._pending.strip())
        self._queue.put(None)
        self._worker.join()
        if self._error:
            raise self._error

    def _run(self):
        while True:
            sentence = self._queue.get()
            if sentence is None:
                return
            if not sentence:
                continue
            try:
                if self._on_speaking and not self._speaking_started:
                    self._on_speaking()
                    self._speaking_started = True
                subprocess.run(
                    launcher_command(self._root, "run_pepper_say"),
                    input=sentence.encode("utf-8"), check=True,
                )
            except subprocess.CalledProcessError as exc:
                self._error = exc
                return


def response_expression(user_text, end_dialogue, counter):
    """Choose a cute response icon while keeping goodbye visually distinct."""
    if end_dialogue:
        return "goodbye"
    question = normalize_local_question(user_text)
    if question in {"你好", "您好", "嗨", "哈喽", "hello", "早上好", "上午好", "下午好", "晚上好"}:
        return "heart"
    if question in {"谢谢", "谢谢你", "多谢", "辛苦了"}:
        return "rose"
    return ("happy", "wink", "excited", "star")[counter % 4]


def main():
    parser = argparse.ArgumentParser(description="Pepper voice dialogue")
    root = Path(__file__).resolve().parent
    parser.add_argument("--once", action="store_true", help="run exactly one dialogue turn")
    parser.add_argument("--auto-record", action="store_true", help="stop recording after detected silence")
    parser.add_argument("--continuous-auto", action="store_true",
                        help="continue automatic turns until no follow-up speech is heard")
    parser.add_argument("--streaming-asr", action="store_true",
                        help="send Pepper PCM to Bailian ASR during recording")
    parser.add_argument("--streaming-agent", action="store_true",
                        help="start Pepper speech on the first completed Agent sentence")
    parser.add_argument("--start-timeout", type=float, default=6.0)
    parser.add_argument("--max-seconds", type=float, default=15.0)
    parser.add_argument("--start-threshold", type=int, default=480)
    parser.add_argument("--silence-threshold", type=int, default=400)
    parser.add_argument("--silence-seconds", type=float, default=0.45)
    parser.add_argument("--settle-seconds", type=float, default=1.2,
                        help="wait after Pepper finishes speaking before listening again")
    parser.add_argument("--app-id", default=os.getenv("BAILIAN_APP_ID", APP_ID))
    parser.add_argument("--llm-model", default=os.getenv("BAILIAN_LLM_MODEL", "qwen-flash"))
    parser.add_argument("--system-prompt-file", default=os.getenv(
        "BAILIAN_SYSTEM_PROMPT_FILE", str(root / "system_prompt.txt")))
    parser.add_argument("--local-replies-file", default=os.getenv(
        "PEPPER_LOCAL_REPLIES_FILE", str(root / "local_replies.json")),
        help="JSON file containing exact-match local replies")
    parser.add_argument("--learned-replies-file", default=os.getenv(
        "PEPPER_LEARNED_REPLIES_FILE", str(root / "learned_replies.json")),
        help="JSON file used to remember Bailian answers for later exact matches")
    parser.add_argument("--no-local-replies", action="store_true",
                        help="send every recognized question to Bailian")
    parser.add_argument("--no-learned-replies", action="store_true",
                        help="do not load or save automatically learned replies")
    parser.add_argument("--use-agent", action="store_true",
                        help="use the published Bailian Agent app instead of the direct model")
    parser.add_argument("--asr-model", default="qwen-audio-3.0-asr-flash-streaming")
    parser.add_argument("--no-emoji", action="store_true",
                        help="不在 Pepper 胸前平板显示 SVG 表情")
    parser.add_argument("--emoji-port", type=int, default=int(os.getenv("PEPPER_EMOJI_PORT", "54002")),
                        help="胸前平板 SVG 页面端口")
    parser.add_argument("--display-host", default=os.getenv("PEPPER_DISPLAY_HOST"),
                        help="Pepper 访问本机 SVG 页面时使用的 IP 地址")
    parser.add_argument("--emoji-url-base", default=None,
                        help="复用唤醒主流程已经启动的 SVG 页面服务")
    parser.add_argument("--emoji-control-host", default=None,
                        help="复用唤醒主流程的本地表情更新通道")
    parser.add_argument("--emoji-control-port", type=int, default=None,
                        help="复用唤醒主流程的本地表情更新端口")
    args = parser.parse_args()
    if args.continuous_auto and not args.auto_record:
        raise SystemExit("--continuous-auto 必须和 --auto-record 一起使用")
    if not args.auto_record or not args.streaming_asr:
        raise SystemExit("当前运行模式必须使用 --auto-record --streaming-asr")

    emoji_display = None
    if not args.no_emoji:
        robot_ip = os.getenv("PEPPER_ROBOT_IP", "192.168.0.100")
        try:
            emoji_display = EmojiDisplay(
                root, robot_ip, args.emoji_port, args.display_host, args.emoji_url_base,
                args.emoji_control_host, args.emoji_control_port,
            )
            atexit.register(emoji_display.close)
            if not args.emoji_url_base:
                emoji_display.show("idle")
            print("胸前平板表情已开启：使用内置 SVG，无需下载 emoji 资源。")
        except (OSError, RuntimeError, ValueError) as exc:
            print("胸前平板表情未开启：{0}".format(exc), file=sys.stderr)

    def set_emoji(expression):
        if emoji_display is not None:
            emoji_display.show(expression)

    response_counter = [0]

    def next_response_expression(user_text, end_dialogue=False):
        expression = response_expression(user_text, end_dialogue, response_counter[0])
        response_counter[0] += 1
        return expression

    if not args.use_agent:
        try:
            system_prompt = Path(args.system_prompt_file).read_text(encoding="utf-8").strip()
        except OSError:
            raise SystemExit("未找到系统提示词文件: {0}".format(args.system_prompt_file))
        if not system_prompt:
            raise SystemExit("系统提示词文件为空: {0}".format(args.system_prompt_file))
        messages = [{"role": "system", "content": system_prompt}]
    else:
        messages = None

    api_key = os.getenv("DASHSCOPE_API_KEY") or getpass.getpass("请输入 DASHSCOPE_API_KEY（输入不回显）: ")
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY 不能为空")
    base_url = ask_base_url()
    session_id = None
    local_replies = {} if args.no_local_replies else load_local_replies(Path(args.local_replies_file))
    learned_replies_path = Path(args.learned_replies_file)
    learned_replies = (
        {}
        if args.no_local_replies or args.no_learned_replies
        else load_local_replies(learned_replies_path)
    )
    quick_replies = {}
    quick_replies.update(learned_replies)
    quick_replies.update(local_replies)

    if args.once:
        print("语音对话：自动录一轮。")
    elif args.continuous_auto:
        print("连续语音对话已启动：您可连续提问；等待新问题超时后将回到唤醒状态。")
    else:
        print("语音对话已启动。按回车后自动收音；检测到说完后自动停止；输入 q 后回车退出。")
    print("每轮依次执行：录音 → 识别 → 本地快速回答或百炼回复 → Pepper 朗读。")
    while True:
        if not args.once and not args.continuous_auto:
            command = input("\n[回车开始自动收音 / q 退出] ").strip().lower()
            if command in {"q", "quit", "exit"}:
                break

        try:
            set_emoji("listening")
            user_text, _recognition = transcribe_pepper_stream(
                api_key, base_url, root, args.asr_model,
                [
                    "--start-timeout", str(args.start_timeout), "--max-seconds", str(args.max_seconds),
                    "--start-threshold", str(args.start_threshold),
                    "--silence-threshold", str(args.silence_threshold),
                    "--silence-seconds", str(args.silence_seconds),
                ],
            )
            if not is_reply_worthy_text(user_text):
                set_emoji("idle")
                if user_text:
                    print("识别结果过短，已忽略：{0}".format(user_text))
                else:
                    print("未识别到人声，请靠近 Pepper 前方麦克风后再试。")
                continue
            print("您> " + user_text)
            set_emoji("thinking")
            local_answer, end_dialogue = (None, False)
            if not args.no_local_replies:
                local_answer, end_dialogue = local_quick_reply(user_text, quick_replies)
            if local_answer:
                print("Pepper> " + local_answer)
                print("本地快速回答：未调用百炼大模型。")
                set_emoji(next_response_expression(user_text, end_dialogue))
                subprocess.run(
                    launcher_command(root, "run_pepper_say"),
                    input=local_answer.encode("utf-8"), check=True,
                )
                if messages is not None:
                    messages.append({"role": "user", "content": user_text})
                    messages.append({"role": "assistant", "content": local_answer})
                if end_dialogue:
                    return 0
                set_emoji("idle")
                time.sleep(args.settle_seconds)
                continue
            if args.use_agent:
                if args.streaming_agent:
                    streaming_speaker = SentenceSpeaker(root, on_speaking=lambda: set_emoji("speaking"))
                    answer, session_id = call_agent_stream(
                        api_key, base_url, args.app_id, user_text, streaming_speaker.add, session_id
                    )
                    print("Pepper> " + answer)
                    streaming_speaker.finish()
                    set_emoji("idle")
                else:
                    answer, session_id = call_agent(api_key, base_url, args.app_id, user_text, session_id)
                    print("Pepper> " + answer)
                    set_emoji(next_response_expression(user_text))
                    subprocess.run(
                        launcher_command(root, "run_pepper_say"),
                        input=answer.encode("utf-8"), check=True,
                    )
                    set_emoji("idle")
                if not args.no_local_replies and not args.no_learned_replies:
                    if save_learned_reply(learned_replies_path, user_text, answer, local_replies):
                        learned_replies = load_local_replies(learned_replies_path)
                        quick_replies = {}
                        quick_replies.update(learned_replies)
                        quick_replies.update(local_replies)
                        print("自动学习问答：已记录，下次同样问法将本地快速回答。")
            else:
                messages.append({"role": "user", "content": user_text})
                if args.streaming_agent:
                    streaming_speaker = SentenceSpeaker(root, on_speaking=lambda: set_emoji("speaking"))
                    answer = call_llm_stream(api_key, base_url, args.llm_model, messages, streaming_speaker.add)
                    print("Pepper> " + answer)
                    streaming_speaker.finish()
                    set_emoji("idle")
                else:
                    answer = call_llm(api_key, base_url, args.llm_model, messages)
                    print("Pepper> " + answer)
                    set_emoji(next_response_expression(user_text))
                    subprocess.run(
                        launcher_command(root, "run_pepper_say"),
                        input=answer.encode("utf-8"), check=True,
                    )
                    set_emoji("idle")
                messages.append({"role": "assistant", "content": answer})
                if not args.no_local_replies and not args.no_learned_replies:
                    if save_learned_reply(learned_replies_path, user_text, answer, local_replies):
                        learned_replies = load_local_replies(learned_replies_path)
                        quick_replies = {}
                        quick_replies.update(learned_replies)
                        quick_replies.update(local_replies)
                        print("自动学习问答：已记录，下次同样问法将本地快速回答。")
        except ASRThrottledError as exc:
            set_emoji("idle")
            print(
                "百炼实时 ASR 当前限流，已暂停 15 秒，随后回到唤醒等待。",
                file=sys.stderr,
            )
            print("限流详情：{0}".format(exc), file=sys.stderr)
            time.sleep(15.0)
            break
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            if args.auto_record and isinstance(exc, subprocess.CalledProcessError) and exc.returncode == 2:
                set_emoji("idle")
                print("未听到新的问题，结束本轮连续对话。")
                break
            set_emoji("error")
            print("本轮失败：{0}".format(exc), file=sys.stderr)
            if args.continuous_auto:
                # A microphone/network setup error will not heal by spawning a
                # new process every 30 seconds. Return to the wake controller
                # and leave one clear diagnostic in the terminal.
                break
        else:
            if args.continuous_auto:
                # Do not let the microphone capture Pepper's own final audio.
                time.sleep(args.settle_seconds)
        if args.once:
            break


if __name__ == "__main__":
    main()
