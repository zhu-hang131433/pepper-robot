#!/usr/bin/env python3
"""Feed Pepper PCM callbacks directly into Bailian's streaming ASR WebSocket."""

import os
import socket
import subprocess
import sys
import threading
import time

import aiohttp
import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback

from process_utils import launcher_command, terminate_process_tree

def to_ws_url(base_url):
    base_url = base_url.rstrip("/")
    suffix = "/api/v1"
    if not base_url.endswith(suffix):
        raise ValueError("Base URL 必须以 /api/v1 结尾")
    if base_url.startswith("https://"):
        base_url = "wss://" + base_url[len("https://"):]
    elif base_url.startswith("http://"):
        base_url = "ws://" + base_url[len("http://"):]
    return base_url[:-len(suffix)] + "/api-ws/v1/inference"


def configure_websocket_proxy():
    """Make DashScope's aiohttp WebSocket honor the configured HTTPS proxy.

    aiohttp's ws_connect does not reliably pick up HTTPS_PROXY through
    trust_env.  In this WSL setup the Meta proxy returns a 198.18/16 fake DNS
    address, so attempting a direct connection hangs forever.  Pass the proxy
    explicitly for wss:// calls while leaving all other aiohttp traffic alone.
    """
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    if not proxy or getattr(aiohttp.ClientSession, "_pepper_proxy_patch", False):
        return
    original_ws_connect = aiohttp.ClientSession.ws_connect

    def ws_connect_with_proxy(session, url, *args, **kwargs):
        if str(url).startswith("wss://") and kwargs.get("proxy") is None:
            kwargs["proxy"] = proxy
        return original_ws_connect(session, url, *args, **kwargs)

    aiohttp.ClientSession.ws_connect = ws_connect_with_proxy
    aiohttp.ClientSession._pepper_proxy_patch = True


class StreamCallback(RecognitionCallback):
    def __init__(self):
        self._lock = threading.Lock()
        self._final_texts = []
        self._partial_text = ""
        self._error = None
        self.opened = threading.Event()
        self.complete = threading.Event()

    def on_open(self):
        self.opened.set()

    def on_event(self, result):
        sentence = result.get_sentence() or {}
        if not isinstance(sentence, dict):
            return
        text = (sentence.get("text") or "").strip()
        if not text:
            return
        with self._lock:
            self._partial_text = text
            if sentence.get("sentence_end") or sentence.get("end_time") is not None:
                if not self._final_texts or self._final_texts[-1] != text:
                    self._final_texts.append(text)
            print("识别中> " + text, file=sys.stderr)

    def on_error(self, result):
        self._error = result.message or str(result)
        self.complete.set()

    def on_complete(self):
        self.complete.set()

    def text(self):
        with self._lock:
            return "".join(self._final_texts) or self._partial_text


def start_recognition_safely(recognition):
    """Start DashScope only after its worker is allowed to see _running=True.

    DashScope 1.27.2 starts the receive thread before setting _running.  On
    Python 3.14 the new thread can evaluate the audio generator first, see
    False, and close the upload without consuming any queued PCM.  Gate that
    private worker for the few instructions inside Recognition.start().
    """
    worker_name = "_Recognition__receive_worker"
    receive_worker = getattr(recognition, worker_name, None)
    if receive_worker is None:
        recognition.start()
        return
    gate = threading.Event()

    def gated_worker():
        gate.wait()
        receive_worker()

    setattr(recognition, worker_name, gated_worker)
    try:
        recognition.start()
    finally:
        gate.set()


def _recognition_is_stopped_error(exc):
    return "Speech recognition has stopped" in str(exc)


def stop_recognition_safely(recognition):
    """Stop a streaming request without failing if DashScope ended it first."""
    try:
        recognition.stop()
    except Exception as exc:
        if not _recognition_is_stopped_error(exc):
            raise


def transcribe_pepper_stream(api_key, base_url, root, model, stream_args):
    """Return final ASR text while microphone PCM is uploaded in real time."""
    dashscope.api_key = api_key
    dashscope.base_websocket_api_url = to_ws_url(base_url)
    configure_websocket_proxy()
    callback = StreamCallback()
    recognition = Recognition(model=model, format="pcm", sample_rate=16000, callback=callback)
    start_recognition_safely(recognition)
    if not callback.opened.wait(3.0):
        raise RuntimeError("实时 ASR 客户端未完成启动")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    # The microphone process connects only after its NAOqi audio subscription
    # succeeds.  A finite setup timeout prevents a stuck Pepper audio service
    # from leaving this dialogue turn blocked forever.
    listener.settimeout(1.0)
    stream_port = listener.getsockname()[1]
    command = launcher_command(root, "run_pepper_pcm_stream", "--stream-port", stream_port, *stream_args)
    process = subprocess.Popen(command)
    connection = None
    return_code = None
    audio_frames = 0
    audio_bytes = 0
    recognition_stopped = False
    try:
        deadline = time.monotonic() + 30.0
        while connection is None:
            try:
                connection, _address = listener.accept()
            except socket.timeout:
                if process.poll() is not None:
                    raise RuntimeError(
                        "Pepper 麦克风采集进程启动失败（退出码 {0}）。请查看上方 NAOqi 错误。".format(
                            process.returncode
                        )
                    )
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Pepper 麦克风在 30 秒内未完成订阅。"
                        "这通常不是音频占用，而是 Pepper 无法反向访问电脑上的 qi 回调服务。"
                    )
        # The streamer exits on start/max recording time and closes this
        # socket.  Keep this read blocking so normal no-speech handling still
        # comes from the streamer rather than an arbitrary client timeout.
        while True:
            data = connection.recv(3200)
            if not data:
                break
            if callback.complete.is_set() or not getattr(recognition, "_running", True):
                recognition_stopped = True
                break
            try:
                recognition.send_audio_frame(data)
            except Exception as exc:
                # DashScope may finish a short utterance before Pepper's VAD
                # closes its socket.  Do not send more frames to that request.
                if not _recognition_is_stopped_error(exc):
                    raise
                recognition_stopped = True
                break
            audio_frames += 1
            audio_bytes += len(data)
        # The PCM helper closes its local socket as soon as VAD decides that
        # the user has finished.  Submit the ASR stream now, in parallel with
        # its NAOqi unsubscribe/session teardown, instead of waiting for that
        # teardown before asking DashScope for the final text.
        stop_recognition_safely(recognition)
        recognition_stopped = True
        return_code = process.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Pepper 麦克风采集进程在结束后仍未退出")
    finally:
        if connection:
            connection.close()
        listener.close()
        if process.poll() is None:
            terminate_process_tree(process)
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        try:
            queued_frames = recognition._stream_data.qsize()
            print(
                "ASR 音频上传：{0} 帧，{1} 字节，待发送队列 {2} 帧。".format(
                    audio_frames, audio_bytes, queued_frames
                ),
                file=sys.stderr,
            )
            if not recognition_stopped:
                stop_recognition_safely(recognition)
        except Exception:
            pass

    callback.complete.wait(5.0)
    if callback._error:
        raise RuntimeError("实时 ASR 调用失败: " + callback._error)
    if return_code == 2:
        raise subprocess.CalledProcessError(return_code, command)
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command)
    return callback.text(), recognition
