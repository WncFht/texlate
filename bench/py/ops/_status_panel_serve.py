"""ops.status_panel 服务叶 —— render 整页装配 + Handler/httpd + pidfile
生命周期（status_panel.py 拆分叶）。

门面回引名单见 ``ops.status_panel._LEAF_EXPORTS``。
"""

from __future__ import annotations

import datetime as dt
import os
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ops._status_panel_env import (
    C_CLEAN,
    C_FAIL,
    C_INFO,
    C_PART,
    HOST,
    PANEL_DIR,
    PIDFILE,
    PORT,
    REFRESH_SECONDS,
)
from ops._status_panel_page import PAGE
from ops._status_panel_sections import SECTIONS, sec_chips
from ops._status_panel_util import esc


def render() -> str:
    parts = []
    for title, fn in SECTIONS:
        try:
            frag = fn()
        except Exception as exc:  # section isolation: never 500 the page
            frag = f"<pre style='color:{C_FAIL}'>采集异常: {esc(repr(exc))}</pre>"
        parts.append(f"<h2>{esc(title)}</h2>{frag}")
    try:
        chips_html = sec_chips()
    except Exception as exc:  # 同 SECTIONS 隔离——chips 采集崩不带垮整页
        chips_html = (
            f"<pre style='color:{C_FAIL}'>chips 采集异常: {esc(repr(exc))}</pre>"
        )
    now = dt.datetime.now(tz=dt.UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return PAGE.format(
        refresh=REFRESH_SECONDS,
        now=now,
        c_clean=C_CLEAN,
        c_fail=C_FAIL,
        c_part=C_PART,
        c_info=C_INFO,
        chips=chips_html,
        body="\n".join(parts),
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/healthz":
            body, ctype = b"ok\n", "text/plain"
        elif self.path in ("/", "/index.html"):
            body, ctype = render().encode(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(
            f"[{dt.datetime.now(tz=dt.UTC).astimezone():%H:%M:%S}] "
            f"{self.address_string()} {fmt % args}",
            flush=True,
        )


def _stop(*_args) -> None:
    PIDFILE.unlink(missing_ok=True)
    raise SystemExit(0)


def main() -> None:
    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(
        f"[{dt.datetime.now(tz=dt.UTC).astimezone():%F %T}] "
        f"serving http://{HOST}:{PORT} pid={os.getpid()}",
        flush=True,
    )
    server.serve_forever()
