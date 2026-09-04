#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Read UTF-8 text from stdin and speak it through Pepper's built-in TTS."""
from __future__ import print_function

import argparse
import sys

from naoqi import ALProxy


def main():
    parser = argparse.ArgumentParser(description="Speak stdin text through Pepper")
    parser.add_argument("--robot-ip", required=True)
    parser.add_argument("--robot-port", type=int, default=9559)
    parser.add_argument("--language", default="Chinese")
    args = parser.parse_args()

    raw_text = sys.stdin.read()
    if not raw_text:
        raise SystemExit("没有收到需要朗读的文本")
    if isinstance(raw_text, unicode):
        text = raw_text
    else:
        text = raw_text.decode("utf-8")

    tts = ALProxy("ALTextToSpeech", args.robot_ip, args.robot_port)
    if args.language:
        available = tts.getAvailableLanguages()
        if args.language not in available:
            raise SystemExit("Pepper 未安装语音: " + args.language)
        tts.setLanguage(args.language)
    tts.say(text.encode("utf-8"))


if __name__ == "__main__":
    main()
