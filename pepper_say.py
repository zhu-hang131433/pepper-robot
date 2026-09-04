#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Read UTF-8 text from stdin and speak it through Pepper's built-in TTS."""
from __future__ import print_function

import argparse
import os
import random
import tempfile
import sys
import threading
import time

from naoqi import ALProxy


TALK_MOTION_JOINTS = [
    "LShoulderPitch", "LShoulderRoll", "LElbowRoll",
    "RShoulderPitch", "RShoulderRoll", "RElbowRoll",
]

# Pepper raises an arm forward by decreasing ShoulderPitch.  ShoulderRoll only
# adds a small outward opening, and ElbowRoll bends the elbow.  ElbowYaw is
# intentionally absent: continuously rotating it was what made the previous
# motion look like aimless arm circles.
TALK_GESTURES = (
    {
        "name": "raise_left",
        "target": {
            "LShoulderPitch": -0.48,
            "LShoulderRoll": 0.16,
            "LElbowRoll": -0.26,
        },
        "raise_seconds": 1.10,
        "hold_seconds": 0.55,
        "lower_seconds": 1.15,
        "rest_seconds": 0.40,
    },
    {
        "name": "raise_right",
        "target": {
            "RShoulderPitch": -0.48,
            "RShoulderRoll": -0.16,
            "RElbowRoll": 0.26,
        },
        "raise_seconds": 1.10,
        "hold_seconds": 0.55,
        "lower_seconds": 1.15,
        "rest_seconds": 0.40,
    },
    {
        "name": "open_both",
        "target": {
            "LShoulderPitch": -0.32,
            "RShoulderPitch": -0.32,
            "LShoulderRoll": 0.14,
            "RShoulderRoll": -0.14,
            "LElbowRoll": -0.18,
            "RElbowRoll": 0.18,
        },
        "raise_seconds": 1.20,
        "hold_seconds": 0.45,
        "lower_seconds": 1.25,
        "rest_seconds": 0.45,
    },
)

# Conservative absolute bounds provide a second safety layer if a speech
# command starts while Pepper is in an unusual but valid upper-body posture.
TALK_MOTION_BOUNDS = {
    "LShoulderPitch": (-1.45, 1.35),
    "RShoulderPitch": (-1.45, 1.35),
    "LShoulderRoll": (-0.45, 0.45),
    "RShoulderRoll": (-0.45, 0.45),
    "LElbowRoll": (-1.20, -0.05),
    "RElbowRoll": (0.05, 1.20),
}


class SpeechMotion(object):
    """Perform smooth, recognisable arm gestures during one TTS utterance."""

    update_interval = 0.050
    max_delta = 0.50

    def __init__(self, robot_ip, robot_port):
        self.motion = ALProxy("ALMotion", robot_ip, robot_port)
        self.base_angles = self.motion.getAngles(TALK_MOTION_JOINTS, True)
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self._run, name="pepper-talk-motion")
        self.worker.daemon = True

    def start(self):
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        self.worker.join(timeout=1.5)
        if self.worker.is_alive():
            return
        # Return gently to the exact posture captured before speaking.  This
        # prevents a sequence of short sentences from accumulating offsets.
        try:
            self.motion.setAngles(TALK_MOTION_JOINTS, self.base_angles, 0.18)
        except Exception:
            pass

    def _target(self, offsets):
        values = []
        for name, base in zip(TALK_MOTION_JOINTS, self.base_angles):
            delta = offsets.get(name, 0.0)
            delta = min(self.max_delta, max(-self.max_delta, delta))
            value = base + delta
            lower, upper = TALK_MOTION_BOUNDS[name]
            # If the starting posture is inside the conservative range, use
            # it as an additional absolute guard.  The relative clamp above
            # always wins when a robot starts in another valid posture, so an
            # unusual posture can never cause a large corrective movement.
            if lower <= base <= upper:
                value = min(upper, max(lower, value))
            values.append(value)
        return values

    def _interpolate_offsets(self, start, target, progress):
        """Cubic smoothstep between two arm poses, without overshoot."""
        progress = min(1.0, max(0.0, progress))
        weight = progress * progress * (3.0 - 2.0 * progress)
        offsets = {}
        for name in TALK_MOTION_JOINTS:
            start_value = start.get(name, 0.0)
            target_value = target.get(name, 0.0)
            offsets[name] = start_value + (target_value - start_value) * weight
        return offsets

    def _transition(self, start, target, duration):
        """Drive one raise/lower phase and return its last requested pose."""
        started_at = time.time()
        current = dict(start)
        while not self.stop_event.is_set():
            progress = (time.time() - started_at) / max(0.01, duration)
            current = self._interpolate_offsets(start, target, progress)
            self.motion.setAngles(
                TALK_MOTION_JOINTS,
                self._target(current),
                0.22,
            )
            if progress >= 1.0:
                return current
            self.stop_event.wait(self.update_interval)
        return current

    def _run(self):
        generator = random.Random(time.time() + os.getpid())
        current = {}
        last_index = None
        try:
            while not self.stop_event.is_set():
                choices = list(range(len(TALK_GESTURES)))
                if len(choices) > 1 and last_index in choices:
                    choices.remove(last_index)
                selected_index = generator.choice(choices)
                last_index = selected_index
                gesture = TALK_GESTURES[selected_index]

                current = self._transition(
                    current, gesture["target"], gesture["raise_seconds"]
                )
                if self.stop_event.wait(gesture["hold_seconds"]):
                    break
                current = self._transition(
                    current, {}, gesture["lower_seconds"]
                )
                if self.stop_event.wait(gesture["rest_seconds"]):
                    break
        except Exception:
            # Animation must never prevent Pepper from speaking.  A robot
            # with an unavailable ALMotion service simply speaks normally.
            return


def motion_enabled(args):
    """Resolve the command-line switch and inherited process-wide setting."""
    if args.no_motion:
        return False
    return os.environ.get("PEPPER_TALK_MOTION", "1").strip().lower() not in {
        "0", "false", "off", "no"
    }


class SpeechLock(object):
    """Serialize TTS processes so two utterances cannot drive Pepper together."""

    path = os.path.join(tempfile.gettempdir(), "pepper_bailian_tts.lock")

    def __enter__(self):
        self.handle = open(self.path, "a+")
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt
            self.handle.write("0")
            self.handle.flush()
            self.handle.seek(0)
            # LK_NBLCK lets us wait indefinitely instead of failing after
            # msvcrt's finite LK_LOCK retry window on long utterances.
            while True:
                try:
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except IOError:
                    self.handle.seek(0)
                    time.sleep(0.1)
        else:
            import fcntl
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()


def main():
    parser = argparse.ArgumentParser(description="Speak stdin text through Pepper")
    parser.add_argument("--robot-ip", required=True)
    parser.add_argument("--robot-port", type=int, default=9559)
    parser.add_argument("--language", default="Chinese")
    parser.add_argument(
        "--no-motion", action="store_true",
        help="朗读时不做头部、肩部和肘部的小幅动作",
    )
    args = parser.parse_args()

    raw_text = sys.stdin.read()
    if not raw_text:
        raise SystemExit("没有收到需要朗读的文本")
    if isinstance(raw_text, unicode):
        text = raw_text
    else:
        text = raw_text.decode("utf-8")

    with SpeechLock():
        tts = ALProxy("ALTextToSpeech", args.robot_ip, args.robot_port)
        if args.language:
            available = tts.getAvailableLanguages()
            if args.language not in available:
                raise SystemExit("Pepper 未安装语音: " + args.language)
            tts.setLanguage(args.language)

        motion = None
        if motion_enabled(args):
            try:
                motion = SpeechMotion(args.robot_ip, args.robot_port)
                motion.start()
            except Exception:
                # ALMotion is optional for compatibility with a locked or
                # already-busy robot; TTS remains the primary function.
                motion = None
        try:
            tts.say(text.encode("utf-8"))
        finally:
            if motion is not None:
                motion.stop()


if __name__ == "__main__":
    main()
