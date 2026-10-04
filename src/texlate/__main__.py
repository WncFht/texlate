"""``python -m texlate`` —— ``texlate`` CLI 入口别名。

``service start`` 的 spawn 目标（``sys.executable -m texlate web`` 不吃
``texlate`` 入口脚本在 PATH 上的形态，pipx/uvx/venv 安装均适用）；
``server/__main__`` 是不持锁的低层入口，本件走 ``cli.app`` 持锁主路。
"""

from __future__ import annotations


def main() -> None:
    """转交 ``texlate.cli:app``（懒门面首访装齐命令叶）。"""
    from texlate.cli import app  # noqa: PLC0415 -- 延迟导入保模块加载轻量

    app()


if __name__ == "__main__":
    main()
