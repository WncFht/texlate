"""``cli/`` 终端输出件：stderr Console 单例 + ``ReportSink`` 实况渲染。

``console`` 是全 CLI 唯一 rich Console——``configure_logging`` 的
RichHandler 与 ``CliSink`` 的 Progress 必须写同一实例，否则两个
Console 抢同一 stderr 的 Live 刷新区会错乱。Console 不绑文件对象
（``file`` 缺省动态解析 ``sys.stderr``）——CliRunner 捕获安全；
非 tty 自动无色、``is_terminal=False`` 时 Progress 走 ``disable``
退化线输出。

事件面与 server SSE 同源（``pipecore.ReportSink``）：``stage`` 边界帧、
``translate`` start/chunk/done 进度帧、``l2``/``fixloop`` done/round
帧、``log()`` 自由行——瘦客户端 ``thin.py`` SSE 渲染吃同形状 payload。
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

if TYPE_CHECKING:
    from rich.progress import TaskID

log = logging.getLogger(__name__)

#: 全 CLI 唯一 rich Console（stderr——stdout 是 JSON 契约面，永不写）。
console = Console(stderr=True)

#: 非 tty 退化线输出节奏——每 ~1/10 总量一行（零进度条环境不刷行）。
_FALLBACK_DIV = 10

#: stage 名 → 行首标签（未登记名原样小写输出）。
_STAGE_LABELS = {
    "route": "route",
    "normalize": "normalize",
    "translate": "translate",
    "inject": "inject",
    "compile": "compile",
    "precheck": "precheck",
    "l2": "l2",
    "fixloop": "fixloop",
    "tounicode": "tounicode",
    "repair": "repair",
}


def status(msg: str) -> None:
    """一行 ``→ msg`` 阶段提示（tty cyan，非 tty 纯文本）。"""
    console.print(f"→ {msg}", style="cyan")


def make_translate_progress() -> Progress:
    """翻译进度条：Spinner+Bar+MofN+Elapsed，transient（收工即清）；非 tty disable。"""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
        disable=not console.is_terminal,
    )


class CliSink:
    """``ReportSink`` → stderr 渲染：stage 行 + translate 进度条 + 修复帧。

    Protocol 结构化满足（不显式继承——本模块保持轻 import，不拖
    pipecore 依赖栈进 ``texlate version`` 等轻命令）。tty 下 translate
    走 Live 进度条；非 tty（管道/CliRunner/CI）退化为每 ~1/10 一行 +
    起止行——行数有界不刷屏。``log()`` 自由行一律 dim。
    """

    def __init__(self) -> None:
        self._progress: Progress | None = None
        self._task: TaskID | None = None
        self._total = 0
        self._done = 0
        self._counts: Counter[str] = Counter()

    # ---------------------------------------------------------------- 协议面

    def log(self, msg: str) -> None:
        """自由日志行 → dim（fixloop 轮内消息等）。"""
        console.print(msg, style="dim", highlight=False)

    def event(self, etype: str, payload: dict[str, Any]) -> None:
        """实况帧分发——未知类型 dim 折行不丢。"""
        if etype == "stage":
            self._on_stage(payload)
        elif etype == "translate":
            self._on_translate(payload)
        elif etype == "l2":
            self._on_l2(payload)
        elif etype == "fixloop":
            self._on_fixloop(payload)
        else:
            console.print(f"· {etype} {payload}", style="dim", highlight=False)

    # ---------------------------------------------------------------- 帧渲染

    def _on_stage(self, p: dict[str, Any]) -> None:
        stage = str(p.get("stage") or "?")
        label = _STAGE_LABELS.get(stage, stage)
        extras: list[str] = []
        if stage == "route" and p.get("engines"):
            extras.append(",".join(str(e) for e in p["engines"]))
        if stage == "compile" and p.get("engine"):
            extras.append(str(p["engine"]))
        if p.get("message"):
            extras.append(str(p["message"]))
        status(f"{label} {' '.join(extras)}".rstrip())

    def _on_translate(self, p: dict[str, Any]) -> None:
        phase = p.get("phase")
        if phase == "start":
            self._total = int(p.get("total") or 0)
            self._done = 0
            self._counts.clear()
            if console.is_terminal and self._total:
                self._progress = make_translate_progress()
                self._progress.start()
                self._task = self._progress.add_task("translate", total=self._total)
            else:
                status(f"translate {self._total} chunks")
        elif phase == "chunk":
            self._done = int(p.get("done") or self._done + 1)
            st = str(p.get("status") or "ok")
            self._counts[st] += 1
            if self._progress is not None and self._task is not None:
                self._progress.update(self._task, completed=self._done)
            elif self._total and (
                self._done == self._total
                or self._done % max(1, self._total // _FALLBACK_DIV) == 0
            ):
                console.print(f"  translate {self._done}/{self._total}", style="dim")
        elif phase == "done":
            self._finish_translate()

    def _finish_translate(self) -> None:
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._task = None
        parts = [f"{k}:{v}" for k, v in sorted(self._counts.items()) if k != "ok"]
        tail = f" ({', '.join(parts)})" if parts else ""
        status(f"translate done {self._done}/{self._total}{tail}")

    def _on_l2(self, p: dict[str, Any]) -> None:
        if p.get("phase") != "done":
            return
        if not p.get("enabled"):
            status("l2 skipped")
            return
        status(
            f"l2 done retranslated={p.get('retranslated', 0)}"
            f" fallback={p.get('fallback', 0)} errors={p.get('errors', 0)}"
        )

    def _on_fixloop(self, p: dict[str, Any]) -> None:
        phase = p.get("phase")
        if phase == "round":
            status(f"fixloop round {p.get('round')}")
        elif phase == "done":
            cell = p.get("cell") or {}
            status(f"fixloop done verdict={cell.get('verdict') or '—'}")
