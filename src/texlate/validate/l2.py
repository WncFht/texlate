"""L2 编译 log 回灌层 —— xelatex/tectonic ``.log`` 结构化解析（规格 docs/spec/validate.md）。

职责边界：本层只做"读"——错误计数、warning 分类、首个错误定位、出错文件栈；
不判 clean/dirty（``!``≤3、首错类别门槛等策略属 compile/fixloop 侧，
docs/spec/compile.md 的判据消费本层输出）。

要点：

- 错误计数**双格式**：``^!`` 经典行 + ``-file-line-error`` 的 ``file:line:`` 行。
  只数 ``!`` 会漏掉全部引擎级错误（bench 语料全部没用 ``-file-line-error`` 编译，
  生产引擎按 docs/spec/compile.md 带该旗标，两种格式必须同吃）。
- 首个错误给定位信息：log 行号、其后 ≤8 行上下文、ctx 内 ``l.NNN`` 源码行号、
  ``(`` 开括号文件栈快照（定位出错 .tex/.sty，供 rewrite 规则缩小作用域）。
- warning 分类按真实 log 语料（bench/work_compile）归纳：missing_glyph /
  invalid_utf8 / citation / reference / rerun / font_subst / file_not_found /
  overfull / generic；并对 docs/spec/compile.md 红线信号打标（invalid_utf8、
  缺字形全家含 U+FFFD 具名红线与 CJK 缺字形、file_not_found）。
- tectonic 有时**不写 .log**：``parse_log`` 对不存在路径返回 ``log_missing=True``
  的 verdict，不抛异常——监控方不得假设 log 存在。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from texlate.redlines import L2_REDLINE_CLASSES, L2_WARNING_RULES
from texlate.texlog import (
    CTX_LINES,
    L_NUM_RE,
    TAIL_LINES,
    iter_log_events,
    match_error_line,
    producer_tag,
)
from texlate.textutil import is_cjk_cp

__all__ = [
    "L2Verdict",
    "LogError",
    "WarningSummary",
    "parse_log",
    "parse_log_text",
]

# ---------------------------------------------------------------- 常量

#: ``-file-line-error`` 格式：``./main.tex:44: msg`` / ``/abs/x.sty:7: msg``。
#: 只要求首个分量是 ``name.ext`` 形态——**不**限 tex 系扩展名：TeX 会按
#: file:line: 报任何被它当输入读的文件（``.eps``/``.pdf_t``/``.lbx``/
#: ``.tikz``/``.end``/``.lof``/``.fgx`` 实测全为真错误，loop1 语料 7814
#: log 全扫、扩展名白名单漏 586 行真错含 3 例整体 ok=True 假干净）。
#: 行首 ``(``/``!`` 与 ``:``/空白内嵌仍排除（避免误吃普通行）。
#: 判定单源 = ``texlog.match_error_line``（``ERR_FILELINE_ROW_RE`` 捕获形
#: 兼给 ``tex_file``/``tex_line``，msg 原样进组 3 不做 ``!`` 剥离，
#: ``! LaTeX Warning`` 伪豁免面随之封死）；非错误形态行排除走
#: ``NONERR_MSG_RE`` 消息面锚定（Warning/``==>`` 双腿单源）。

#: ctx 内 ``l.NNN`` / ctx·tail 窗宽 / 单遍事件流——词法与栈走查单源 =
#: ``texlog``（``L_NUM_RE``/``CTX_LINES``/``TAIL_LINES``/
#: ``iter_log_events``）。

#: log 首行引擎签名 ``This is XeTeX, Version ...``。
_ENGINE_RX: Final = re.compile(r"^This is (\w+)")

#: ``Missing character: There is no X ("8FD9)/(U+8FD9) in font ...`` ——
#: 取码点判 CJK。码点形态随引擎代际分叉：老 TL 打 ``("8FD9)``、新 TL
#: 打 ``(U+8FD9)``（corpus log 两种并存，U+ 形态约 1/3——单认引号形会
#: 漏掉新工具链全部 CJK 缺字红线）。
_MISSING_CHAR_RX: Final = re.compile(
    r'Missing character: There is no (?:\S+ )?\((?:"|U\+)([0-9A-Fa-f]{4,6})\)'
)


#: warning 分类规则（按序首中即归）。类别名即 by_class 键。
#: 注意预筛：只对有 warning 形态的行归类——error ctx 内的帮助文本
#: （``type `I\font<same font id>...'``）不打 Warning 标，曾被 font_subst 误吃。
#: 红线相关类的 ``(类名, pattern)`` 单源在 ``texlate.redlines``（★2）——
#: ``_rl`` 按 canonical id 取本层发射名与行级模式；citation/rerun 等
#: 非红线观察类仍本层自持。
def _rl(rid: str) -> tuple[str, re.Pattern[str]]:
    name, pat = L2_WARNING_RULES[rid]
    return name, re.compile(pat, re.IGNORECASE)


_WARNING_RULES: Final = (
    _rl("invalid_utf8"),
    _rl("missing_char_nullfont"),
    _rl("missing_char"),
    ("citation", re.compile(r"Citation.*undefined|undefined citations", re.IGNORECASE)),
    (
        "reference",
        re.compile(
            r"(?:Reference|Label|Citation).*(?:multiply[- ]defined|undefined)"
            r"|undefined references|multiply[- ]defined",
            re.IGNORECASE,
        ),
    ),
    ("rerun", re.compile(r"\b[Rr]erun\b|may have changed", re.IGNORECASE)),
    (
        "font_subst",
        re.compile(r"Font shape.*undefined|Some font shapes", re.IGNORECASE),
    ),
    _rl("missing_graphic"),
    ("overfull", re.compile(r"(?:Over|Under)full \\[hv]box", re.IGNORECASE)),
)

#: warning 形态预筛：``* Warning:`` 标记行，或无标记的硬 warning
#: （Missing character / Invalid UTF-8 / Over|Underfull 这些从来不打 Warning: 字）。
_ANY_WARNING_RX: Final = re.compile(
    r"^(?:LaTeX|Package|Class)\b[^:\n]*Warning:|Warning:", re.IGNORECASE
)
_MARKERLESS_WARN_RX: Final = re.compile(
    r"Missing character:|Invalid UTF-8 byte|(?:Over|Under)full \\[hv]box"
    r"|File `[^']+' not found|cannot (?:find|open)",
    re.IGNORECASE,
)

_MAX_STORED_ERRORS: Final = 200  # 存储上限（n_errors 仍精确计数）
_MAX_WARN_SAMPLES: Final = 5  # 每类 warning 样例/hits 留存上限
#: ``attribution_dict`` 错误命中条数上限——级联错长尾同形，前 50 条
#: 足够聚类（``n_errors`` 仍精确计数；e2e ``_L2_MAX_ERRORS`` 同量级口径）。
_MAX_ATTR_ERRORS: Final = 50

#: runaway 扫描错（``File ended while scanning use of \xxx``）——文件栈
#: 在 ``)`` 处已弹出肇事文件，错误行报的是**父文件** ``\input`` 续行位。
_EOF_ERR_RX: Final = re.compile(r"File ended while scanning")
#: ``)`` 弹出到错误打印的最大行距（日志折行/font dump 可隔几行）。
_EOF_POP_WINDOW: Final = 16

#: docs/spec/compile.md 红线 warning 类（命中即记入 ``WarningSummary.redlines``）
#: ——集合单源 ``texlate.redlines.L2_REDLINE_CLASSES``（★2）。``fffd_glyph``
#: = 缺 U+FFFD 替换符字形（invalid_utf8 源被排版成缺字——loginfo 侧
#: ``WARNING_RED_LINES`` 同名红线的 L2 对应类）。``missing_glyph``
#: （非 CJK/非 FFFD/码点不可解）同入红线——judge 的 ``missing_chars``
#: 对全部缺字形判 dirty，§4.3 渲染检查亦要求计数==0。
#: ``missing_glyph_nullfont``（试排/测量盒良性吞字）**不入**红线——
#: 计数留 by_class/samples 观察面，redlines 保净（judge 门控同口径
#: 排除，裁决证据 bench/results/nullfont-scout-2026-09-17/）。
_REDLINE_CLASSES: Final = L2_REDLINE_CLASSES


# ---------------------------------------------------------------- 数据


@dataclass(frozen=True, slots=True)
class LogError:
    """单个编译错误的定位。

    ``line_no`` = log 内 1-based 行号；``tex_file``/``tex_line`` = 源码定位
    （file:line: 直接给出，``^!`` 格式从 ctx 的 ``l.NNN`` 提）；
    ``file_stack`` = 出错时刻 ``(`` 开括号文件栈（外层→内层）；
    ``eof_file`` = ``File ended while scanning`` 类错误的真肇事文件——
    该错误打印前 ``)`` 已把肇事文件弹出栈，报位落在父文件续行，
    此处回填最近一次弹出的文件名（#78）。
    """

    line_no: int
    head: str
    tex_file: str | None = None
    tex_line: int | None = None
    ctx: tuple[str, ...] = ()
    file_stack: tuple[str, ...] = ()
    eof_file: str | None = None

    def to_dict(self) -> dict[str, object]:
        """序列化为一级字典。"""
        return {
            "line_no": self.line_no,
            "head": self.head,
            "tex_file": self.tex_file,
            "tex_line": self.tex_line,
            "ctx": list(self.ctx),
            "file_stack": list(self.file_stack),
            "eof_file": self.eof_file,
        }


@dataclass(slots=True)
class WarningSummary:
    r"""warning 分类汇总。``redlines`` 命中 docs/spec/compile.md 红线信号即 dirty 依据。

    ``sys_hits`` = 系统 texmf/bundle 件产生的红线类命中
    （``invalid_utf8@<file>``）——观察项不判 dirty（loginfo 侧
    ``LogInfo.warnings_sys`` 同口径）。

    ``hits`` = 每类结构化命中条（``{file, line, head, log_line}``，
    ≤``_MAX_WARN_SAMPLES`` 条与 ``samples`` 同口径）——``file`` 是命中时
    ``(`` 栈最内层文件（启发式归因：warning 多在读到肇事文件期间打印，
    ``\output`` 时机打印的行栈可能已弹出归 None）；``line`` 恒 None
    （warning 源码行号格式不统一暂不解析，占位保 hits 表键形一致）。
    """

    total: int = 0
    by_class: dict[str, int] = field(default_factory=dict)
    samples: dict[str, list[str]] = field(default_factory=dict)
    hits: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    redlines: list[str] = field(default_factory=list)
    cjk_missing: int = 0
    sys_hits: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """序列化为一级字典。"""
        return {
            "total": self.total,
            "by_class": dict(self.by_class),
            "samples": {k: list(v) for k, v in self.samples.items()},
            "hits": {k: [dict(h) for h in v] for k, v in self.hits.items()},
            "redlines": list(self.redlines),
            "cjk_missing": self.cjk_missing,
            "sys_hits": list(self.sys_hits),
        }


@dataclass(slots=True)
class L2Verdict:
    """编译 log 解析结果。

    ``ok`` = 零错误（双格式计数）。``log_missing`` 为真时其余字段为空——
    tectonic 不写 .log 的情形，消费方按"信息缺失"而非"编译干净"处理。
    """

    n_errors: int = 0
    first_error: LogError | None = None
    errors: list[LogError] = field(default_factory=list)
    warnings: WarningSummary = field(default_factory=WarningSummary)
    tail: tuple[str, ...] = ()
    engine: str | None = None
    log_missing: bool = False

    @property
    def ok(self) -> bool:
        """无编译错误即过。"""
        return self.n_errors == 0

    def to_dict(self) -> dict[str, object]:
        """序列化为一级字典。"""
        return {
            "ok": self.ok,
            "n_errors": self.n_errors,
            "first_error": self.first_error.to_dict() if self.first_error else None,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": self.warnings.to_dict(),
            "tail": list(self.tail),
            "engine": self.engine,
            "log_missing": self.log_missing,
        }

    def attribution_dict(self) -> dict[str, object]:
        """序列化为 records 落账的紧凑归因载荷（canonical 键 ``l2_attr``）。

        ``hits`` = 错误+warning 统一命中表（``log_line`` 升序，逐条
        ``{kind, file, line, head, log_line}``）——错误 kind=``"error"``
        另带 ``stack_file``/``eof_file``（``!`` 格式无 tex_file 时的
        归因兜底链，与 e2e ``attr_error`` 的 src_tok 优先级同序：
        eof_file > tex_file > 栈最内层），条数 ≤``_MAX_ATTR_ERRORS``；
        warning kind=by_class 类名，``file`` 为命中时栈最内层（每类
        ≤``_MAX_WARN_SAMPLES`` 条，与 ``samples`` 同口径）。命中表截断
        不影响计数：``n_errors``/``warn_by_class`` 恒为精确全量。

        单源供 ``benchlib.judge_dict`` 嵌进 records/{stage}.jsonl——
        离线按 kind/file 聚类 warning/error 用，勿在此键内塞
        ctx/tail/file_stack 全量（那些走 ``to_dict`` 的单跑报告）。
        """
        ws = self.warnings
        hits: list[dict[str, object]] = [
            {
                "kind": "error",
                "file": e.tex_file,
                "line": e.tex_line,
                "head": e.head,
                "log_line": e.line_no,
                "stack_file": e.file_stack[-1] if e.file_stack else None,
                "eof_file": e.eof_file,
            }
            for e in self.errors[:_MAX_ATTR_ERRORS]
        ]
        for cls, bucket in ws.hits.items():
            hits.extend({"kind": cls, **h} for h in bucket)
        hits.sort(key=lambda h: int(h["log_line"]))
        return {
            "n_errors": self.n_errors,
            "log_missing": self.log_missing,
            "engine": self.engine,
            "hits": hits,
            "warn_by_class": dict(ws.by_class),
            "redlines": list(ws.redlines),
            "sys_hits": list(ws.sys_hits),
            "cjk_missing": ws.cjk_missing,
        }

    def __str__(self) -> str:
        """PASS/FAIL 头 + 首错定位。"""
        if self.log_missing:
            return "L2 ? (log missing)"
        head = (
            f"{'PASS' if self.ok else 'FAIL'} "
            f"(err={self.n_errors} warn={self.warnings.total} "
            f"redline={len(self.warnings.redlines)})"
        )
        if self.first_error is not None:
            head += f"\n  first: {self.first_error.head}"
            if self.first_error.tex_line is not None:
                where = self.first_error.tex_file or "?"
                head += f"\n         at {where}:{self.first_error.tex_line}"
        return head


# ---------------------------------------------------------------- 内部


@dataclass(slots=True)
class _WarnScan:
    """warning 扫描归因参数组——``_mark_redline``/``_classify_warning`` 共用。

    ``ws`` = 累计中的 ``WarningSummary``；``project_root``/``dos_eps_cache``
    是 invalid_utf8 系统件/DOS-EPS 归因用的根与判定缓存（``is_dos_eps``
    逐文件名记忆，一次 parse 内共享）。``stack`` 逐事件随 ``(`` 栈
    变化、不属本组，仍单列传入。``seen_*`` = ``redlines``/``sys_hits``
    的去重影子集——warning 洪峰 log 上 ``x not in list`` 逐条 O(n)
    累计成 O(n²)，集成员判 O(1) 且 append 序不变。
    """

    ws: WarningSummary
    project_root: Path | None
    dos_eps_cache: dict[str, bool] = field(default_factory=dict)
    seen_red: set[str] = field(default_factory=set)
    seen_sys: set[str] = field(default_factory=set)


def _mark_redline(
    cls: str,
    line: str,
    scan: _WarnScan,
    stack: tuple[str | None, ...],
) -> None:
    """红线打标——``invalid_utf8`` 按 ``stack`` 最内文件归因产生者。

    系统 texmf/bundle 件进 ``sys_hits`` 观察项（老 CTAN 包自带坏字节
    非工程文件问题，fixer-utf8 归因 96% 属此类）；DOS 魔数 EPS
    （normalize ``dos_eps_skipped`` 原样保留件）视同系统件降级并打
    ``(dos-eps)`` 标（loginfo.py ``_scan_error_lines`` 同口径）；其余类
    全量进 ``redlines``（missing_glyph/file_not_found 按内容论不按产生
    文件论）。三支判定单源 = ``texlog.producer_tag``——本件只消费
    tag，``cls@`` 前缀与 ``sys_hits``/``redlines`` 归集桶是 l2 侧语义。
    """
    ws = scan.ws
    if cls == "invalid_utf8":
        inner = next((s for s in reversed(stack) if s), None)
        tag = producer_tag(inner, scan.project_root, scan.dos_eps_cache)
        if tag is not None:
            hit = f"{cls}@{tag}"
            if hit not in scan.seen_sys:
                scan.seen_sys.add(hit)
                ws.sys_hits.append(hit)
            return
    red = f"{cls}: {line.strip()[:120]}"
    if red not in scan.seen_red:
        scan.seen_red.add(red)
        ws.redlines.append(red)


def _is_warning_form(ln: str) -> bool:
    """Warning 形态预筛：``* Warning:`` 标记行，或无标记硬 warning。"""
    return bool(_ANY_WARNING_RX.search(ln) or _MARKERLESS_WARN_RX.search(ln))


def _record_hit(
    ws: WarningSummary,
    cls: str,
    stack: tuple[str | None, ...],
    head: str,
    log_line: int,
) -> None:
    """留存 samples 原文样例 + hits 结构化命中条（各 ≤``_MAX_WARN_SAMPLES``）。"""
    bucket = ws.samples.setdefault(cls, [])
    if len(bucket) < _MAX_WARN_SAMPLES:
        bucket.append(head)
    hb = ws.hits.setdefault(cls, [])
    if len(hb) < _MAX_WARN_SAMPLES:
        inner = next((s for s in reversed(stack) if s), None)
        hb.append({"file": inner, "line": None, "head": head, "log_line": log_line})


def _classify_warning(
    line: str,
    scan: _WarnScan,
    stack: tuple[str | None, ...],
    *,
    log_line: int,
    next_ln: str = "",
) -> None:
    r"""单行 warning 归类 + 红线打标 + 命中条留存（``hits`` 归因载荷原料）。

    ``next_ln``：misschar 行的下一物理行——79 列 wrap 会把 ``in font ...``
    声明推进续行，规则检索面拼上它使限界窗可跨一个 ``\n``（与
    loginfo/judge 同口径）；记录/打标仍用物理 ``line``。调用侧只在续行
    是裸折行碎片时拼接——续行自身命中 warning 形态（独立消息行而非
    折行残段）时不拼，防 probe 内第二锚点窃走本行归类（D4）。
    """
    if not _is_warning_form(line):
        return  # 非 warning 形态行（含 error ctx 内的帮助文本）
    ws = scan.ws
    cls = "generic"
    probe = line + "\n" + next_ln if next_ln else line
    for name, rx in _WARNING_RULES:
        if rx.search(probe):
            cls = name
            break
    if cls == "missing_glyph":
        m = _MISSING_CHAR_RX.search(line)
        if m is not None:
            cp = int(m.group(1), 16)
            if cp == 0xFFFD:  # noqa: PLR2004 - U+FFFD 码点字面量即规格
                cls = "fffd_glyph"
            elif is_cjk_cp(cp):
                ws.cjk_missing += 1
                cls = "missing_glyph_cjk"
    ws.total += 1
    ws.by_class[cls] = ws.by_class.get(cls, 0) + 1
    _record_hit(ws, cls, stack, line.strip(), log_line)
    if cls in _REDLINE_CLASSES:
        _mark_redline(cls, line, scan, stack)


def _tex_line_from_ctx(ctx: list[str]) -> int | None:
    for ln in ctx:
        m = L_NUM_RE.match(ln.strip())
        if m:
            return int(m.group(1))
    return None


def _match_error_line(ln: str) -> tuple[str, str | None] | None:
    """``(head, file:line: 给的 tex_file)``；非错误行返回 None。

    判定单源 = ``texlog.match_error_line``——bench ``extract_l2_fixture``
    钉点经本私有名消费，薄 delegate 保旧签名。
    """
    hit = match_error_line(ln)
    return (hit.head, hit.tex_file) if hit is not None else None


def _eof_culprit(head: str, last_pop: tuple[int, str] | None, i: int) -> str | None:
    """Runaway 扫描错的真肇事文件：错误行前 ``_EOF_POP_WINDOW`` 内最后弹出的文件。"""
    if last_pop is None or i - last_pop[0] > _EOF_POP_WINDOW:
        return None
    if not _EOF_ERR_RX.search(head):
        return None
    return last_pop[1]


def _error_ctx(lines: list[str], i: int) -> list[str]:
    """错误行后 ≤``CTX_LINES`` 行上下文——截断于下一错误行。

    窗内 ``l.NNN`` 是**该**错的源码定位；不截断会让无自带行号的错
    （``! Emergency stop`` 类）借用邻错行号误归因。
    """
    ctx = lines[i + 1 : i + 1 + CTX_LINES]
    for k, cln in enumerate(ctx):
        if _match_error_line(cln) is not None:
            return ctx[:k]
    return ctx


def _misschar_next_ln(lines: list[str], i: int) -> str:
    """``Missing character:`` 行的拼接续行。

    本行无 ``in font `` 声明（79 列 wrap 推走）且续行含 ``in font``
    时返回 ``lines[i+1]``，否则 ``""``。续行自身命中 warning 形态
    （独立的 ``Missing character``/``Invalid UTF-8`` 等消息行）时不拼
    ——probe 内第二锚点会窃走本行归类（CJK 缺字形被次行
    ``in font nullfont`` 归 ``missing_glyph_nullfont``，丢红线丢
    ``cjk_missing``）。
    """
    ln = lines[i]
    if (
        "Missing character:" in ln
        and "in font " not in ln
        and i + 1 < len(lines)
        and "in font" in lines[i + 1]
        and not _is_warning_form(lines[i + 1])
    ):
        return lines[i + 1]
    return ""


# ---------------------------------------------------------------- 主入口


def parse_log_text(text: str, *, project_root: Path | None = None) -> L2Verdict:
    """解析 log 文本为 ``L2Verdict``（单遍事件流投影——``texlog.iter_log_events``）。

    ``project_root`` = 编译工作根：invalid_utf8 红线按产生文件归因，
    系统 texmf/bundle 源与 DOS 魔数 EPS（normalize ``dos_eps_skipped``
    原样保留件）降 ``warnings.sys_hits``；缺席时裸名保守归工程
    （不掉红线），绝对路径按 texmf 标记启发式。
    """
    v = L2Verdict()
    lines = text.splitlines()
    if lines:
        m = _ENGINE_RX.match(lines[0])
        if m:
            v.engine = m.group(1)

    last_pop: tuple[int, str] | None = None  # (行 idx, 刚弹出的文件 token)
    scan = _WarnScan(v.warnings, project_root)
    for ev in iter_log_events(lines):
        for tok in ev.popped:
            if tok is not None:
                last_pop = (ev.i, tok)

        # —— 错误行：双格式（``ErrHit`` 捕获形兼给 tex_file/tex_line）——
        hit = ev.err
        if hit is not None:
            v.n_errors += 1
            ctx = _error_ctx(lines, ev.i)
            tex_line = hit.tex_line
            if tex_line is None:
                tex_line = _tex_line_from_ctx(ctx)
            eof_file = _eof_culprit(hit.head, last_pop, ev.i)
            err = LogError(
                line_no=ev.i + 1,
                head=hit.head,
                tex_file=hit.tex_file,
                tex_line=tex_line,
                ctx=tuple(ctx),
                file_stack=tuple(s for s in ev.stack if s),
                eof_file=eof_file,
            )
            if v.first_error is None:
                v.first_error = err
            if len(v.errors) < _MAX_STORED_ERRORS:
                v.errors.append(err)
            continue

        _classify_warning(
            ev.line,
            scan,
            ev.stack,
            log_line=ev.i + 1,
            next_ln=_misschar_next_ln(lines, ev.i),
        )

    v.tail = tuple(lines[-TAIL_LINES:])
    return v


def parse_log(path: str | Path, *, project_root: Path | None = None) -> L2Verdict:
    """从路径读 ``.log`` 解析；非正规文件同归 ``log_missing=True``（不抛异常）。

    缺席/目录/fifo/NUL 路径全归 ``log_missing``——``is_file`` 闸先于
    ``read_text``（fifo 无闸会阻塞至有 writer）。

    ``project_root`` 透传 ``parse_log_text``——注意勿以 ``path.parent``
    猜测：tectonic 日志落在 ``_tect_out/`` 子目录，父目录不是工程根。
    """
    p = Path(path)
    # is_file 闸：fifo/目录/缺席/坏路径（含 NUL）同归 log_missing——
    # exists() 对 fifo 为真，read_text 会阻塞至有 writer。
    if not p.is_file():
        return L2Verdict(log_missing=True)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return L2Verdict(log_missing=True)
    return parse_log_text(text, project_root=project_root)
