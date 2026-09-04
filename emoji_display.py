#!/usr/bin/env python3
"""Serve built-in SVG expressions and ask Pepper's tablet to display them.

The tablet loads the page over the LAN, so this module deliberately has no
third-party image or font dependency.  The SVG drawings also work when the
tablet has no network access to an emoji CDN.
"""

import html
import base64
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from process_utils import launcher_command


EXPRESSIONS = {
    "idle": ("🙂", "#4f8cff", "随时为你服务"),
    "listening": ("👂", "#38bdf8", "我在听"),
    "thinking": ("🤔", "#a78bfa", "让我想一想"),
    "happy": ("😊", "#22c55e", "很高兴帮助你"),
    "speaking": ("😄", "#f59e0b", "正在回答"),
    "goodbye": ("👋", "#fb7185", "下次再见"),
    "error": ("😅", "#ef4444", "请稍等一下"),
    "heart": ("❤️", "#fb7185", "欢迎你"),
    "rose": ("🌹", "#e11d48", "送你一朵小花"),
    "wink": ("😉", "#06b6d4", "你好呀"),
    "excited": ("🤩", "#f97316", "欢迎来到这里"),
    "star": ("⭐", "#eab308", "今天也闪闪发光"),
}


def _svg(expression):
    """Return a self-contained, tablet-friendly SVG face."""
    symbol, accent, caption = EXPRESSIONS.get(expression, EXPRESSIONS["idle"])
    safe_symbol = html.escape(symbol)
    safe_caption = html.escape(caption)
    eyes = '<circle cx="176" cy="190" r="12" fill="#172033"/><circle cx="304" cy="190" r="12" fill="#172033"/>'
    mouth = '<path d="M190 270 Q240 315 290 270" fill="none" stroke="#172033" stroke-width="12" stroke-linecap="round"/>'
    if expression == "listening":
        eyes = '<circle cx="176" cy="190" r="12" fill="#172033"/><circle cx="304" cy="190" r="12" fill="#172033"/>'
        mouth = '<path d="M220 270 Q240 290 260 270" fill="none" stroke="#172033" stroke-width="12" stroke-linecap="round"/>'
    elif expression == "thinking":
        eyes = '<circle cx="176" cy="190" r="12" fill="#172033"/><circle cx="304" cy="190" r="12" fill="#172033"/>'
        mouth = '<path d="M210 280 Q240 260 270 280" fill="none" stroke="#172033" stroke-width="12" stroke-linecap="round"/>'
    elif expression == "goodbye":
        eyes = '<path d="M160 190 Q176 170 192 190" fill="none" stroke="#172033" stroke-width="12" stroke-linecap="round"/><path d="M288 190 Q304 170 320 190" fill="none" stroke="#172033" stroke-width="12" stroke-linecap="round"/>'
    elif expression == "error":
        eyes = '<path d="M160 180 L192 212 M192 180 L160 212 M288 180 L320 212 M320 180 L288 212" stroke="#172033" stroke-width="10" stroke-linecap="round"/>'
        mouth = '<path d="M205 295 Q240 260 275 295" fill="none" stroke="#172033" stroke-width="12" stroke-linecap="round"/>'
    elif expression == "wink":
        eyes = '<path d="M160 190 Q176 170 192 190" fill="none" stroke="#172033" stroke-width="12" stroke-linecap="round"/><circle cx="304" cy="190" r="12" fill="#172033"/>'
    decoration = ""
    if expression == "heart":
        decoration = '<path d="M352 72 C330 48 286 78 352 132 C418 78 374 48 352 72 Z" fill="#fb7185" stroke="#be123c" stroke-width="5"/>'
    elif expression == "rose":
        decoration = '<path d="M352 132 Q348 184 345 216" fill="none" stroke="#15803d" stroke-width="8"/><path d="M347 188 Q320 168 304 190 Q330 205 348 200" fill="#22c55e"/><circle cx="352" cy="118" r="27" fill="#f43f5e"/><circle cx="330" cy="108" r="19" fill="#fb7185"/><circle cx="374" cy="108" r="19" fill="#fb7185"/><circle cx="352" cy="92" r="18" fill="#e11d48"/>'
    elif expression == "excited":
        decoration = '<path d="M352 62 L361 88 L389 88 L366 104 L375 131 L352 115 L329 131 L338 104 L315 88 L343 88 Z" fill="#facc15" stroke="#ca8a04" stroke-width="4"/>'
    elif expression == "star":
        decoration = '<path d="M352 62 L361 88 L389 88 L366 104 L375 131 L352 115 L329 131 L338 104 L315 88 L343 88 Z" fill="#fde047" stroke="#ca8a04" stroke-width="4"/><circle cx="109" cy="115" r="8" fill="#fde047"/><circle cx="392" cy="180" r="7" fill="#fde047"/>'
    elif expression == "goodbye":
        decoration = '<path d="M350 130 Q382 105 398 72 Q407 56 418 67 Q425 77 414 91 L430 78 Q442 70 448 82 Q452 92 439 103 L422 119 Q408 134 394 154" fill="#ffd166" stroke="#172033" stroke-width="6" stroke-linejoin="round"/>'
    return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 500" role="img" aria-label="{symbol} {caption}">
  <rect width="480" height="500" rx="42" fill="#f8fafc"/>
  <circle cx="240" cy="235" r="154" fill="{accent}" opacity="0.18"/>
  <circle cx="240" cy="235" r="118" fill="#ffd166" stroke="{accent}" stroke-width="9"/>
  {decoration}
  {eyes}
  {mouth}
  <text x="240" y="415" text-anchor="middle" font-family="Arial, sans-serif" font-size="27" font-weight="700" fill="#172033">{caption}</text>
</svg>'''.format(accent=accent, decoration=decoration, eyes=eyes, mouth=mouth, symbol=safe_symbol, caption=safe_caption)


def _html_page(expression):
    svg = _svg(expression)
    # Inline SVG avoids relying on the browser's emoji font or an external CDN.
    return '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#f8fafc}}#pepper-face{{width:100%;height:100%}}svg{{display:block;width:100%;height:100%}}</style></head><body><div id="pepper-face">{}</div></body></html>'''.format(svg)


class _EmojiRequestHandler(BaseHTTPRequestHandler):
    server_version = "PepperEmoji/1.0"

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API name
        parsed = urlparse(self.path)
        if parsed.path not in ("/", "/emoji.html"):
            self.send_error(404)
            return
        expression = parse_qs(parsed.query).get("face", ["idle"])[0].split("-", 1)[0]
        if expression not in EXPRESSIONS:
            expression = "idle"
        body = _html_page(expression).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


def display_host(robot_ip):
    """Find the local LAN address Pepper should use to reach this computer."""
    import os

    configured = os.getenv("PEPPER_DISPLAY_HOST")
    if configured:
        return configured
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((robot_ip, 9559))
        return probe.getsockname()[0]
    finally:
        probe.close()


def _free_local_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


class EmojiDisplay(object):
    """Own one tablet worker and update its SVG without reloading the page."""

    def __init__(self, root, robot_ip, port=54002, host=None, base_url=None,
                 control_host=None, control_port=None):
        self._root = root
        self._robot_ip = robot_ip
        self._server = None
        self._thread = None
        self._worker = None
        self._worker_lock = threading.Lock()
        self._remote_control = bool(base_url and control_port)
        self._control_host = control_host or "127.0.0.1"
        self._control_port = int(control_port) if control_port else _free_local_port()
        if base_url:
            self._base_url = base_url.rstrip("/")
            self._port = int(port)
        else:
            self._server = ThreadingHTTPServer(("0.0.0.0", int(port)), _EmojiRequestHandler)
            self._host = host or display_host(robot_ip)
            self._port = self._server.server_address[1]
            self._base_url = "http://{0}:{1}".format(self._host, self._port)
            self._thread = threading.Thread(target=self._server.serve_forever, name="pepper-emoji-http")
            self._thread.daemon = True
            self._thread.start()
        self._version = 0
        self._enabled = True
        self._last_expression = None
        self._lock = threading.Lock()

    @property
    def base_url(self):
        return self._base_url

    @property
    def control_host(self):
        return self._control_host

    @property
    def control_port(self):
        return self._control_port

    def show(self, expression):
        if not self._enabled:
            return
        if expression not in EXPRESSIONS:
            expression = "idle"
        with self._lock:
            if expression == self._last_expression:
                return
            self._last_expression = expression
            self._version += 1
        try:
            encoded_svg = base64.urlsafe_b64encode(
                _svg(expression).encode("utf-8")
            ).decode("ascii")
            if self._remote_control:
                self._send_svg(encoded_svg)
                return
            if self._worker is None:
                self._start_worker(expression)
            else:
                self._send_svg(encoded_svg)
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            # A tablet display problem must never stop speech recognition.
            print("胸前平板表情更新失败：{0}".format(exc))
            self._enabled = False

    def _start_worker(self, expression):
        """Start one Python 2 NAOqi worker that keeps the WebView alive."""
        url = "{0}/emoji.html?{1}".format(
            self._base_url,
            "face={0}-{1}".format(expression, self._version),
        )
        encoded_html = base64.urlsafe_b64encode(
            _html_page(expression).encode("utf-8")
        ).decode("ascii")
        command = launcher_command(
            self._root, "run_pepper_emoji",
            "--server",
            "--control-host", self._control_host,
            "--control-port", self._control_port,
            "--url", url,
            "--html-base64", encoded_html,
        )
        with self._worker_lock:
            if self._worker is not None:
                return
            self._worker = subprocess.Popen(command)
        # Do not let the wake-word process send the first state update until
        # the Python 2 worker has finished opening NAOqi and its control port.
        deadline = time.time() + 8.0
        while time.time() < deadline:
            if self._worker.poll() is not None:
                returncode = self._worker.returncode
                self._worker = None
                raise subprocess.CalledProcessError(returncode, command)
            try:
                with socket.create_connection(
                    (self._control_host, self._control_port), timeout=0.25
                ):
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("Pepper tablet emoji worker did not become ready")

    def _send_svg(self, encoded_svg):
        """Send one ASCII-safe SVG update to the persistent tablet worker."""
        with socket.create_connection(
            (self._control_host, self._control_port), timeout=1.5
        ) as connection:
            connection.sendall((encoded_svg + "\n").encode("ascii"))

    def close(self):
        with self._worker_lock:
            worker = self._worker
            self._worker = None
        if worker is not None and worker.poll() is None:
            try:
                from process_utils import terminate_process_tree
                terminate_process_tree(worker)
            except OSError:
                pass
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
