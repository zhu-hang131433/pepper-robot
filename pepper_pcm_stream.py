#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stream speech-only PCM from Pepper's front microphone over local TCP."""
from __future__ import print_function

import argparse
import audioop
import os
import socket
import sys
import threading
import time

import qi


FRONT_CHANNEL = 3
SAMPLE_RATE = 16000


def print_text(value, stream=None):
    stream = stream or sys.stderr
    if sys.version_info[0] < 3 and isinstance(value, unicode):
        stream.write(value.encode(stream.encoding or "utf-8", "replace") + "\n")
    else:
        stream.write(str(value) + "\n")
    stream.flush()


class SpeechPcmStream(object):
    """ALAudioDevice callback which starts at speech and ends after silence."""

    def __init__(self, output_socket, start_threshold, silence_threshold, silence_seconds):
        self.output_socket = output_socket
        self.output_socket_lock = threading.Lock()
        self.start_threshold = start_threshold
        self.silence_threshold = silence_threshold
        self.silence_seconds = silence_seconds
        self.started = False
        self.finished = threading.Event()
        self.last_voice_at = None
        self.pre_roll = []
        self.lock = threading.Lock()
        self.callback_count = 0
        self.invalid_buffer_count = 0
        self.rms_total = 0
        self.rms_max = 0
        self.emitted_bytes = 0

    def _emit(self, data):
        # Use a dedicated loopback socket. NAOqi's own logs may write to
        # stdout, so stdout is never safe for binary PCM.
        with self.output_socket_lock:
            output_socket = self.output_socket
            if output_socket is not None:
                output_socket.sendall(data)
                self.emitted_bytes += len(data)

    def close_output(self):
        """Signal end-of-audio before the slower NAOqi cleanup begins."""
        with self.output_socket_lock:
            output_socket = self.output_socket
            self.output_socket = None
        if output_socket is not None:
            try:
                output_socket.shutdown(socket.SHUT_WR)
            except socket.error:
                pass
            try:
                output_socket.close()
            except socket.error:
                pass

    def processRemote(self, nb_of_channels, samples_by_channel, timestamp, input_buffer):
        """Receive one 16-bit mono PCM block from the remote ALAudioDevice."""
        data = str(input_buffer)
        expected = int(nb_of_channels) * int(samples_by_channel) * 2
        if len(data) != expected:
            with self.lock:
                self.invalid_buffer_count += 1
            return
        now = time.time()
        rms = audioop.rms(data, 2)
        with self.lock:
            self.callback_count += 1
            self.rms_total += rms
            self.rms_max = max(self.rms_max, rms)
            if not self.started:
                self.pre_roll.append(data)
                if len(self.pre_roll) > 6:  # about half a second at Pepper's callback size
                    self.pre_roll.pop(0)
                if rms >= self.start_threshold:
                    self.started = True
                    self.last_voice_at = now
                    for buffered in self.pre_roll:
                        self._emit(buffered)
                    self.pre_roll = []
                return

            self._emit(data)
            if rms >= self.silence_threshold:
                self.last_voice_at = now
            elif self.last_voice_at is not None and now - self.last_voice_at >= self.silence_seconds:
                self.finished.set()


def main():
    parser = argparse.ArgumentParser(description="Stream Pepper microphone PCM to local TCP")
    parser.add_argument("--robot-ip", required=True)
    parser.add_argument("--robot-port", type=int, default=9559)
    parser.add_argument("--callback-port", type=int, default=54000)
    parser.add_argument("--stream-host", default="127.0.0.1")
    parser.add_argument("--stream-port", required=True, type=int,
                        help="local TCP port owned by the Python 3 ASR client")
    parser.add_argument("--setup-timeout", type=float, default=12.0,
                        help="maximum seconds for each Pepper audio-service setup call")
    parser.add_argument("--start-timeout", type=float, default=6.0)
    parser.add_argument("--max-seconds", type=float, default=15.0)
    parser.add_argument("--start-threshold", type=int, default=480)
    parser.add_argument("--silence-threshold", type=int, default=400)
    parser.add_argument("--silence-seconds", type=float, default=0.45)
    args = parser.parse_args()

    # Do not connect to the ASR process until ALAudioDevice has accepted the
    # subscription.  Previously this connection happened first, so the ASR
    # process could accept it and then wait forever when setClientPreferences
    # was stuck on Pepper.
    output_socket = None
    # A service must already be registered when ALAudioDevice accepts client
    # preferences.  It will not receive callbacks until subscribe(), by which
    # time output_socket is assigned below.
    stream = SpeechPcmStream(None, args.start_threshold, args.silence_threshold, args.silence_seconds)
    # A unique service name prevents a previously interrupted run from
    # colliding with a stale ALAudioDevice client entry on the robot.
    module_name = "PepperPcmStream_{0}".format(os.getpid())
    app = qi.Application([
        "pepper-pcm-stream",
        "--qi-url=tcp://{0}:{1}".format(args.robot_ip, args.robot_port),
        "--qi-listen-url=tcp://0.0.0.0:{0}".format(args.callback_port),
    ])
    app.start()
    service_id = app.session.registerService(module_name, stream)
    audio = app.session.service("ALAudioDevice")
    reason = ""
    started_at = None
    subscribed = False
    try:
        print_text(u"正在配置 Pepper 前方麦克风（服务名：{0}）…".format(module_name))
        try:
            audio.setClientPreferences(
                module_name, SAMPLE_RATE, FRONT_CHANNEL, 0, _async=True
            ).value(timeout=int(args.setup_timeout * 1000))
        except Exception as exc:
            raise RuntimeError(
                "ALAudioDevice.setClientPreferences 超时或失败: {0}。"
                "若运行于 WSL2，请检查 Pepper 是否能反向访问本机 qi 回调端口。".format(exc)
            )

        print_text(u"麦克风参数已接受，正在订阅 PCM 回调…")
        try:
            audio.subscribe(module_name, _async=True).value(
                timeout=int(args.setup_timeout * 1000)
            )
        except Exception as exc:
            raise RuntimeError(
                "ALAudioDevice.subscribe 超时或失败: {0}。"
                "Pepper 必须能主动连接本机显示的 54000 监听地址。".format(exc)
            )
        subscribed = True
        output_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        output_socket.connect((args.stream_host, args.stream_port))
        stream.output_socket = output_socket
        started_at = time.time()
        print_text(u"实时识别已就绪：请开始说话；检测到您说完后自动提交。")
        while True:
            now = time.time()
            if stream.finished.wait(0.05):
                reason = "silence"
                break
            if not stream.started and now - started_at >= args.start_timeout:
                reason = "no_speech"
                break
            if now - started_at >= args.max_seconds:
                reason = "max_duration"
                break
    finally:
        # Closing this socket first lets the streaming ASR submit its final
        # result immediately.  NAOqi unsubscription can otherwise add seconds
        # after the user has already stopped speaking.
        stream.close_output()
        try:
            if subscribed:
                audio.unsubscribe(module_name, _async=True).value(timeout=3000)
        except Exception:
            pass
        try:
            app.session.unregisterService(service_id)
        except Exception:
            pass
        try:
            app.stop()
        except Exception:
            pass
    average_rms = int(stream.rms_total / stream.callback_count) if stream.callback_count else 0
    print_text("reason={0}, callbacks={1}, invalid_buffers={2}, rms_avg={3}, rms_max={4}, bytes={5}".format(
        reason, stream.callback_count, stream.invalid_buffer_count,
        average_rms, stream.rms_max, stream.emitted_bytes
    ))
    return 2 if reason == "no_speech" else 0


if __name__ == "__main__":
    sys.exit(main())
