"""``python -m texlate.server`` —— uvicorn 入口（§6 本地形态）。

``--port/--host/--data-dir``；缺省绑 127.0.0.1:8765（local 单机形态）。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

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
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=_port, default=8765)
    parser.add_argument(
        "--data-dir",
        default="",
        help="数据目录（缺省 TEXLATE_DATA_DIR 或 ~/.texlate）",
    )
    args = parser.parse_args()
    if args.data_dir:
        os.environ["TEXLATE_DATA_DIR"] = str(Path(args.data_dir).expanduser())

    import uvicorn  # noqa: PLC0415 -- server extra 延迟导入

    from texlate.server.app import create_app  # noqa: PLC0415

    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
