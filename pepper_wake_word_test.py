#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test Pepper's built-in Chinese wake-word recognition through ALSpeechRecognition."""
from __future__ import print_function

import argparse
import sys
import threading
import time

import qi


def to_unicode(value):
    """Normalize argparse/NAOqi strings before passing them to Python 2 SDK."""
    if isinstance(value, unicode):
        return value
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        # Python 2 on Windows may receive command-line bytes in the active
        # console code page (usually CP936), while Linux receives UTF-8.
        return value.decode(sys.getfilesystemencoding() or "mbcs")


def print_text(value, stream=None):
    stream = stream or sys.stdout
    if sys.version_info[0] < 3 and isinstance(value, unicode):
        stream.write(value.encode(stream.encoding or "utf-8", "replace") + "\n")
    else:
        stream.write(str(value) + "\n")
    stream.flush()


class WakeWordListener(object):
    def __init__(self, wake_word, confidence):
        self.wake_word = wake_word
        self.confidence = confidence
        self.detected = threading.Event()
        self.result = None
        self.armed = False

    def arm(self):
        """Ignore ALMemory's cached WordRecognized value until ASR is ready."""
        self.result = None
        self.detected.clear()
        self.armed = True

    def on_word_recognized(self, value):
        """Handle ALMemory's WordRecognized event: [word, confidence]."""
        if not self.armed:
            return
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            return
        word = value[0]
        score = float(value[1])
        if isinstance(word, unicode):
            normalized = word
        else:
            normalized = word.decode("utf-8")
        print_text(u"检测到候选词：{0}（置信度 {1:.2f}）".format(normalized, score))
        if normalized == self.wake_word and score >= self.confidence:
            self.result = (normalized, score)
            self.detected.set()
        elif normalized == self.wake_word:
            print_text(u"候选词低于当前阈值 {0:.2f}，继续监听。".format(self.confidence))


def main():
    parser = argparse.ArgumentParser(description="Test Pepper wake word")
    parser.add_argument("--robot-ip", required=True)
    parser.add_argument("--robot-port", type=int, default=9559)
    parser.add_argument("--callback-port", type=int, default=54001)
    parser.add_argument("--wake-word", default=u"小信")
    parser.add_argument("--confidence", type=float, default=0.15)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--autonomous-life-state", choices=("solitary", "disabled"), default="solitary",
                        help="Pepper standby state before listening (default: solitary)")
    parser.add_argument("--keep-autonomous-life", action="store_true",
                        help="leave ALAutonomousLife state unchanged")
    args = parser.parse_args()
    # A Python 3 parent process passes --wake-word as UTF-8 bytes to this
    # Python 2 program. Decode it once; otherwise .encode() below first tries
    # an ASCII decode and fails before ALSpeechRecognition starts.
    args.wake_word = to_unicode(args.wake_word)

    app = qi.Application([
        "pepper-wake-word-test",
        "--qi-url=tcp://{0}:{1}".format(args.robot_ip, args.robot_port),
        "--qi-listen-url=tcp://0.0.0.0:{0}".format(args.callback_port),
    ])
    app.start()
    memory = app.session.service("ALMemory")
    speech = app.session.service("ALSpeechRecognition")
    listener = WakeWordListener(args.wake_word, args.confidence)
    subscriber = memory.subscriber("WordRecognized")
    connection_id = subscriber.signal.connect(listener.on_word_recognized)
    subscription_name = "PepperWakeWordTest"

    try:
        # A running Autonomous Life can keep ALDialog/awareness audio clients
        # active after a wake word is recognised.  "solitary" is the intended
        # reception standby state: it keeps Pepper awake and posture-managed
        # without initiating interactions itself.  "disabled" is available
        # for deployments that need fully manual control, but it can leave the
        # robot looking down and is therefore not the default.
        if not args.keep_autonomous_life:
            try:
                life = app.session.service("ALAutonomousLife")
                if life.getState() != args.autonomous_life_state:
                    life.setState(args.autonomous_life_state)
                if args.autonomous_life_state == "solitary":
                    print_text(u"Pepper 已进入安静待机模式（solitary）。")
                else:
                    print_text(u"Pepper 已进入完全手动模式（自主生命已禁用）。")
            except Exception as exc:
                print_text(u"无法切换 Pepper 自主生命模式：{0}".format(exc), sys.stderr)
            else:
                if args.autonomous_life_state == "solitary":
                    # Ensure the visual reception posture is restored when a
                    # previous disabled-mode run left the head lowered.
                    try:
                        app.session.service("ALMotion").wakeUp()
                        app.session.service("ALRobotPosture").goToPosture("StandInit", 0.5)
                        print_text(u"Pepper 已恢复站立抬头的接待姿态。")
                    except Exception as exc:
                        print_text(u"Pepper 已切换待机模式，但无法恢复站姿：{0}".format(exc), sys.stderr)
        speech.setLanguage("Chinese")
        # Autonomous Life's ALDialog may own the ASR engine and hold a
        # "modifiable_grammar" context that makes setVocabulary fail. Disable
        # the autonomous listening and clear every leftover grammar first.
        try:
            life = app.session.service("ALAutonomousLife")
            life.setAutonomousAbilityEnabled("BasicAwareness", False)
        except Exception:
            pass
        speech.pause(True)
        for cleanup in (speech.deleteAllContextSets, speech.removeAllContext, speech.deleteAllContexts):
            try:
                cleanup()
            except Exception:
                pass
        speech.setVocabulary([args.wake_word.encode("utf-8")], False)
        speech.pause(False)
        speech.subscribe(subscription_name)
        listener.arm()
        print_text(u"唤醒监听已订阅，ASR 引擎工作正常。")
        print_text(u"请在 Pepper 正前方说“{0}”唤醒。等待 {1:.0f} 秒。".format(args.wake_word, args.timeout))
        if listener.detected.wait(args.timeout):
            print_text(u"唤醒词测试成功：{0}（置信度 {1:.2f}）".format(listener.result[0], listener.result[1]))
            return 0
        print_text(u"未检测到唤醒词。请靠近前方麦克风、放慢语速后重试。")
        return 1
    finally:
        try:
            speech.pause(False)
        except Exception:
            pass
        try:
            speech.unsubscribe(subscription_name)
        except Exception:
            pass
        try:
            speech.removeAllContexts()
        except Exception:
            pass
        try:
            subscriber.signal.disconnect(connection_id)
        except Exception:
            pass
        app.stop()


if __name__ == "__main__":
    sys.exit(main())
