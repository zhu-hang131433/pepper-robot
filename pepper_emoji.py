#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Open a local SVG page on Pepper's chest tablet."""
from __future__ import print_function

import argparse
import base64
import json
import socket
import time

from naoqi import ALProxy


LOCAL_BOOTSTRAP_URL = "http://198.18.0.1/apps/boot-config/preloading_dialog.html"


def show_inline_html(tablet, encoded_html, reuse_webview=False):
    """Render inline HTML through Pepper's robot-to-tablet internal network."""
    try:
        raw_html = base64.urlsafe_b64decode(encoded_html.encode("ascii"))
        html_text = raw_html.decode("utf-8")
    except Exception as exc:
        raise SystemExit("Invalid inline tablet HTML: {0}".format(exc))

    tablet.wakeUp()
    tablet.turnScreenOn(True)
    if reuse_webview:
        loaded = tablet.showWebview()
    else:
        loaded = tablet.showWebview(LOCAL_BOOTSTRAP_URL)
        time.sleep(1.0)
    if loaded is False:
        loaded = tablet.showWebview(LOCAL_BOOTSTRAP_URL)
        time.sleep(1.0)
        if loaded is False:
            raise SystemExit("Pepper internal tablet page could not be opened.")
    script = "document.open();document.write({0});document.close();".format(
        json.dumps(html_text, ensure_ascii=True)
    )
    tablet.executeJS(script)
    return True


def update_inline_svg(tablet, encoded_svg):
    """Update the already-open SVG container without reloading the WebView."""
    try:
        raw_svg = base64.urlsafe_b64decode(encoded_svg.encode("ascii"))
        svg_text = raw_svg.decode("utf-8")
    except Exception as exc:
        raise SystemExit("Invalid inline tablet SVG: {0}".format(exc))

    script = """
        (function () {{
            var face = document.getElementById('pepper-face');
            if (face) {{
                face.innerHTML = {0};
            }}
        }})();
    """.format(json.dumps(svg_text, ensure_ascii=True))
    tablet.executeJS(script)
    return True


def run_update_server(tablet, host, port):
    """Keep one NAOqi proxy alive and accept SVG updates from Python 3."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, int(port)))
    listener.listen(4)
    print("Pepper tablet emoji worker ready on {0}:{1}.".format(host, port))
    try:
        while True:
            connection, _address = listener.accept()
            try:
                chunks = []
                while True:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    if b"\n" in chunk or sum(len(item) for item in chunks) >= 262144:
                        break
                encoded_svg = b"".join(chunks).strip().split(b"\n", 1)[0]
                if encoded_svg:
                    update_inline_svg(tablet, encoded_svg.decode("ascii"))
            except Exception as exc:
                print("Pepper tablet SVG update failed: {0}".format(exc))
            finally:
                connection.close()
    finally:
        listener.close()


def main():
    parser = argparse.ArgumentParser(description="Show an SVG expression on Pepper tablet")
    parser.add_argument("--robot-ip", required=True)
    parser.add_argument("--robot-port", type=int, default=9559)
    parser.add_argument("--url")
    parser.add_argument("--html-base64",
                        help="inline HTML fallback for a tablet without Wi-Fi")
    parser.add_argument("--svg-base64",
                        help="update the SVG inside the already-open tablet page")
    parser.add_argument("--server", action="store_true",
                        help="keep one NAOqi proxy alive for later SVG updates")
    parser.add_argument("--control-host", default="127.0.0.1",
                        help="local host for the persistent SVG update worker")
    parser.add_argument("--control-port", type=int,
                        help="local port for the persistent SVG update worker")
    parser.add_argument("--reuse-webview", action="store_true",
                        help="update the already-open internal tablet page")
    args = parser.parse_args()

    tablet = ALProxy("ALTabletService", args.robot_ip, args.robot_port)
    if args.reuse_webview and args.svg_base64:
        update_inline_svg(tablet, args.svg_base64)
        return 0
    wifi_status = tablet.getWifiStatus()
    if args.server:
        if args.control_port is None:
            raise SystemExit("--server 必须同时提供 --control-port")
        loaded = False
        if wifi_status == "CONNECTED" and args.url:
            loaded = tablet.showWebview(args.url)
            if loaded is not False:
                run_update_server(tablet, args.control_host, args.control_port)
                return 0
        if args.html_base64:
            show_inline_html(tablet, args.html_base64)
            run_update_server(tablet, args.control_host, args.control_port)
            return 0
        if loaded is False:
            raise SystemExit("Pepper tablet could not open the expression page.")
        raise SystemExit("Pepper tablet Wi-Fi is {0}, and no expression page was supplied.".format(wifi_status))
    if wifi_status == "CONNECTED" and args.url:
        loaded = tablet.showWebview(args.url)
        if loaded is not False:
            return 0
    if args.html_base64:
        show_inline_html(tablet, args.html_base64, args.reuse_webview)
        print("Pepper tablet used the offline inline-SVG fallback.")
        return 0
    if wifi_status != "CONNECTED":
        raise SystemExit(
            "Pepper tablet Wi-Fi is {0}, and no inline HTML fallback was supplied.".format(
                wifi_status
            )
        )
    raise SystemExit("Pepper tablet could not load the page: {0}".format(args.url))


if __name__ == "__main__":
    main()
