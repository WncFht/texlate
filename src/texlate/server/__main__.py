"""``python -m texlate.server`` —— uvicorn 入口（§6 本地形态）。

``--port/--host/--data-dir``；缺省绑 127.0.0.1:8765（local 单机形态）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from texlate.textutil import DEFAULT_BIND_HOST, DEFAULT_BIND_PORT, set_data_dir

#: TCP 端口上限
_PORT_MAX = 65535


def _port(s: str) -> int:
    """``--port`` 值闸：越界/非数字在 argparse 层拒（exit 2）。"""
    try:
        p = int(s)
    except ValueError:
        msg = f"--port 非数字：{s!r}"
        raise argparse.ArgumentTypeError(msg) from None
    if not 1 <= p <= _PORT_MAX:
        msg = f"--port 需在 1-{_PORT_MAX}：{p}"
        raise argparse.ArgumentTypeError(msg)
    return p


def main() -> None:
    """解析参数 → ``uvicorn.run(create_app(...))``。"""
    parser = argparse.ArgumentParser(prog="texlate.server")
    parser.add_argument("--host", default=DEFAULT_BIND_HOST)
    parser.add_argument("--port", type=_port, default=DEFAULT_BIND_PORT)
    parser.add_argument(
        "--data-dir",
        default="",
        help="数据目录（缺省 TEXLATE_DATA_DIR 或 ~/.texlate）",
    )
    args = parser.parse_args()
    if args.data_dir:
        set_data_dir(Path(args.data_dir))

    import uvicorn  # noqa: PLC0415 -- 延迟导入保 CLI 冷启动

    from texlate.logsetup import configure_server_logging  # noqa: PLC0415
    from texlate.server.app import _exposed_bind_warning, create_app  # noqa: PLC0415
    from texlate.server.settings import data_dir as _data_dir  # noqa: PLC0415

    warning = _exposed_bind_warning(args.host)
    if warning is not None:
        print(  # noqa: T201 -- __main__ 无 typer 依赖，stderr 直写
            warning,
            file=sys.stderr,
        )
    configure_server_logging(_data_dir())
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
