"""``cli/`` 终端输出件：stderr Console 单例 + ``ReportSink`` 实况渲染。

``console`` 是全 CLI 唯一 rich Console——``configure_logging`` 的
RichHandler 与 ``CliSink`` 的 Progress 必须写同一实例，否则两个
Console 抢同一 stderr 的 Live 刷新区会错乱。Console 不绑文件对象
（``file`` 缺省动态解析 ``sys.stderr``）——CliRunner 捕获安全；
非 tty 自动无色、``is_terminal=False`` 时 Progress 走 ``disable``
退化线输出。

事件面与 server SSE 同源（``pipecore.ReportSink``）：``stage`` 边界帧、
``translate`` start/chunk/done 进度帧、``logfix``/``fixloop`` done/round
帧、``log()`` 自由行——瘦客户端 ``thin.py`` SSE 渲染吃同形状 payload，
帧→行（``logfix_done_line``/``fixloop_frame_line``）与 chunk 进度策略件
（``_ChunkProgress``）与本模块共用。
"""

from __future__ import annotations

import logging
import re
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
    from collections.abc import Mapping

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
    "logfix": "logfix",
    "fixloop": "fixloop",
    "tounicode": "tounicode",
    "repair": "repair",
}


def status(msg: str) -> None:
    """一行 ``→ msg`` 阶段提示（tty cyan，非 tty 纯文本）。"""
    console.print(f"→ {msg}", style="cyan")


#: fixloop cell ``log`` 重放行里的逐规则/清扫噪音——逐条 ``cond skip``、
#: 引擎不适用行、轮次小结（已由紧凑 round 帧渲染）与 aux-sweep 清扫账。
#: 动作叙事行（``apply``/``warn-preempt``/``landing sync``/``wire`` 等）不在此列。
_TRACE_NOISE_RE = re.compile(
    r"cond skip|: skip \(|escalate skip|: (?:skip|unsupported) on "
    r"|fixloop: r\d+:|aux-sweep"
)


def log_line_filtered(msg: str) -> bool:
    """``log()`` 自由行是否该在终端隐去——噪音形状且 ``texlate`` logger 未到 DEBUG。

    全量 trace 不失：``-vv``/``TEXLATE_LOG=debug`` 放行全部行；server 侧
    任务日志抽屉/落盘文件本就收全量（过滤只是 CLI 呈现层的事）。
    """
    return not log.isEnabledFor(logging.DEBUG) and bool(_TRACE_NOISE_RE.search(msg))


def fixloop_round_line(r: Mapping[str, Any]) -> str:
    """单轮 dict → 紧凑一行 ``fixloop r1 missing_file:plex-sans.sty err=68 (15.7s)``。"""
    bits = [f"fixloop r{r.get('round', '?')}"]
    if r.get("salvage"):
        bits.append("salvage")
    cat, pay = r.get("category"), r.get("payload")
    if cat:
        bits.append(f"{cat}:{pay}" if pay else str(cat))
    if r.get("n_errors") is not None:
        bits.append(f"err={r['n_errors']}")
    stack = r.get("file_stack") or []
    if stack:
        loc = str(stack[-1]).rsplit("/", 1)[-1]
        bits.append(f"at={loc}:{r['line_no']}" if r.get("line_no") else f"at={loc}")
    warns = [str(w) for w in (r.get("warnings") or []) if w]
    if warns:
        bits.append("warn=" + ",".join(warns))
    if not r.get("pdf"):
        bits.append("nopdf")
    if r.get("died"):
        bits.append("died")
    if r.get("driver_fatal"):
        bits.append(f"fatal:{r['driver_fatal']}")
    if r.get("sec") is not None:
        bits.append(f"({r['sec']}s)")
    return " ".join(bits)


def logfix_done_line(p: Mapping[str, Any]) -> str | None:
    """``logfix`` 帧 → 状态行文本；非 ``done`` 相位 ``None``。

    ``CliSink._on_logfix``（本地管道）与 ``thin.py`` SSE 跟随共用的渲染口径。
    """
    if p.get("phase") != "done":
        return None
    if not p.get("enabled"):
        return "logfix skipped"
    return (
        f"logfix done retranslated={p.get('retranslated', 0)}"
        f" fallback={p.get('fallback', 0)} errors={p.get('errors', 0)}"
    )


def fixloop_frame_line(p: Mapping[str, Any]) -> str | None:
    """``fixloop`` round/done 帧 → 状态行文本；其余相位 ``None``。

    ``CliSink._on_fixloop`` 与 ``thin.py`` SSE 跟随共用的渲染口径。
    """
    phase = p.get("phase")
    if phase == "round":
        r = p.get("round")
        return fixloop_round_line(r) if isinstance(r, dict) else f"fixloop round {r}"
    if phase == "done":
        cell = p.get("cell") or {}
        n = len(cell.get("rounds") or [])
        return f"fixloop done verdict={cell.get('verdict') or '—'} rounds={n}"
    return None


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


class _ChunkProgress:
    """chunk 计数 → tty 进度条 / 非 tty 退化行的 sink 无关策略件。

    tty 下 ``make_translate_progress`` Live 条 advance；非 tty 按
    ``_FALLBACK_DIV`` 节奏节流单行。
    ``close()`` 停 Live——断流/终帧/回轮询前必须收工，否则刷新区残留。
    ``CliSink``（本地管道）与 ``thin.py`` SSE 跟随共用本策略。
    """

    def __init__(self, label: str = "chunks") -> None:
        self._label = label
        self._progress: Progress | None = None
        self._task: TaskID | None = None
        self._total = 0

    def update(self, done: int, total: int | None = None) -> None:
        """新 ``done`` 计数（可携新 ``total``）→ 进度条 advance / 退化行节流。"""
        if total:
            self._total = total
        if console.is_terminal and self._total:
            if self._progress is None:
                self._progress = make_translate_progress()
                self._progress.start()
                self._task = self._progress.add_task("translate", total=self._total)
            if self._task is not None:
                self._progress.update(self._task, completed=done)
        elif self._total and (
            done >= self._total or done % max(1, self._total // _FALLBACK_DIV) == 0
        ):
            console.print(f"  {self._label} {done}/{self._total}", style="dim")

    def close(self) -> None:
        """进度条收工——断流/终帧/回轮询前必须停 Live，否则刷新区残留。"""
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._task = None


class CliSink:
    """``ReportSink`` → stderr 渲染：stage 行 + translate 进度条 + 修复帧。

    Protocol 结构化满足（不显式继承——本模块保持轻 import，不拖
    pipecore 依赖栈进 ``texlate version`` 等轻命令）。tty 下 translate
    走 Live 进度条；非 tty（管道/CliRunner/CI）退化为每 ~1/10 一行 +
    起止行——行数有界不刷屏。``log()`` 自由行一律 dim。
    """

    def __init__(self) -> None:
        self._chunks = _ChunkProgress("translate")
        self._total = 0
        self._done = 0
        self._counts: Counter[str] = Counter()

    # ---------------------------------------------------------------- 协议面

    def log(self, msg: str) -> None:
        """自由日志行 → dim（fixloop 轮内消息等）；trace 噪音行 DEBUG 级才放行。"""
        if log_line_filtered(msg):
            return
        console.print(msg, style="dim", highlight=False)

    def event(self, etype: str, payload: dict[str, Any]) -> None:
        """实况帧分发——未知类型 dim 折行不丢。"""
        if etype == "stage":
            self._on_stage(payload)
        elif etype == "translate":
            self._on_translate(payload)
        elif etype == "logfix":
            self._on_logfix(payload)
        elif etype == "fixloop":
            self._on_fixloop(payload)
        elif etype == "verdict":
            self._on_verdict(payload)
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
            self._chunks.close()
            self._chunks = _ChunkProgress("translate")
            if not (console.is_terminal and self._total):
                status(f"translate {self._total} chunks")
        elif phase == "chunk":
            self._done = int(p.get("done") or self._done + 1)
            st = str(p.get("status") or "ok")
            self._counts[st] += 1
            self._chunks.update(self._done, self._total)
        elif phase == "done":
            self._finish_translate()

    def _finish_translate(self) -> None:
        self._chunks.close()
        parts = [f"{k}:{v}" for k, v in sorted(self._counts.items()) if k != "ok"]
        tail = f" ({', '.join(parts)})" if parts else ""
        status(f"translate done {self._done}/{self._total}{tail}")

    def _on_logfix(self, p: dict[str, Any]) -> None:
        line = logfix_done_line(p)
        if line is not None:
            status(line)

    def _on_fixloop(self, p: dict[str, Any]) -> None:
        line = fixloop_frame_line(p)
        if line is not None:
            status(line)

    def _on_verdict(self, p: dict[str, Any]) -> None:
        """终态 verdict dict → 一行收官摘要（JSON 报告前的可读句读）。"""
        bits = [f"done {p.get('status') or '—'}"]
        if p.get("reject_at"):
            bits.append(f"reject@{p['reject_at']}")
        v = p.get("verdict") or {}
        if isinstance(v, dict):
            if v.get("category"):
                cat = str(v["category"])
                bits.append(f"{cat}:{v['payload']}" if v.get("payload") else cat)
            if v.get("n_errors"):
                bits.append(f"errors={v['n_errors']}")
            if v.get("missing_chars"):
                bits.append(f"missing={v['missing_chars']}")
        status(" ".join(bits))
