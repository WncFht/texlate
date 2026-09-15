"""L2 编译 log 回灌层 —— xelatex/tectonic ``.log`` 结构化解析（规格 docs/08 §2.3）。

职责边界：本层只做"读"——错误计数、warning 分类、首个错误定位、出错文件栈；
不判 clean/dirty（``!``≤3、首错类别门槛等策略属 compile/fixloop 侧，
docs/08 §4.3 的判据消费本层输出）。

要点：

- 错误计数**双格式**：``^!`` 经典行 + ``-file-line-error`` 的 ``file:line:`` 行。
  只数 ``!`` 会漏掉全部引擎级错误（bench 语料全部没用 ``-file-line-error`` 编译，
  生产引擎按 docs/08 §4.1 带该旗标，两种格式必须同吃）。
- 首个错误给定位信息：log 行号、其后 ≤8 行上下文、ctx 内 ``l.NNN`` 源码行号、
  ``(`` 开括号文件栈快照（定位出错 .tex/.sty，供 rewrite 规则缩小作用域）。
- warning 分类按真实 log 语料（bench/work_compile）归纳：missing_glyph /
  invalid_utf8 / citation / reference / rerun / font_subst / file_not_found /
  overfull / generic；并对 docs/08 §4.3 红线信号打标（invalid_utf8、
  CJK 缺字形、file_not_found）。
- tectonic 有时**不写 .log**：``parse_log`` 对不存在路径返回 ``log_missing=True``
  的 verdict，不抛异常——监控方不得假设 log 存在。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from texlate.texlog import looks_like_tex_file, update_file_stack

__all__ = [
    "L2Verdict",
    "LogError",
    "WarningSummary",
    "parse_log",
    "parse_log_text",
]

# ---------------------------------------------------------------- 常量

#: ``-file-line-error`` 格式：``./main.tex:44: msg`` / ``/abs/x.sty:7: msg``。
#: 要求首个分量带已知 tex 系扩展名，且行首不是 ``(``/``!``（避免误吃普通行）。
#: tex 系扩展名/文件栈判定收敛到 ``texlate.texlog``（三处实现单源化）。
_FILE_LINE_RX: Final = re.compile(
    r"^([^()\s:]+\.[A-Za-z0-9]{1,10}):(\d+):[ \t]*!?[ \t]*(.*)$"
)

#: ``file:line:`` 形态的非错误行（与 fixloop/logparse 同口径）：
#: Warning 行（部分引擎/包给 warning 也打 file:line: 前缀——fixloop 实测坑，
#: 不排会让 ``n_errors==0`` 干净门永不通）与 ``==> Fatal error`` 汇总尾行
#: （同一失败的复述，多计一次——bench/corpus_v2/2002.05660 colt2020.log 实测）。
_NONERR_FILELINE_RX: Final = re.compile(
    r"(?:LaTeX|Package|Class)\b[^\n]*?\bWarning\b|^\s*==>"
)

#: 经典错误行。
_BANG_RX: Final = re.compile(r"^!\s*(.*)$")

#: ctx 内 ``l.NNN`` 源码行号。
_LNUM_RX: Final = re.compile(r"^l\.(\d+)\s*(.*)$")

#: log 首行引擎签名 ``This is XeTeX, Version ...``。
_ENGINE_RX: Final = re.compile(r"^This is (\w+)")

#: ``Missing character: There is no X ("8FD9) in font ...`` —— 取码点判 CJK。
_MISSING_CHAR_RX: Final = re.compile(
    r'Missing character: There is no (?:\S+ )?\("([0-9A-Fa-f]{4,6})\)'
)

#: warning 分类规则（按序首中即归）。类别名即 by_class 键。
#: 注意预筛：只对有 warning 形态的行归类——error ctx 内的帮助文本
#: （``type `I\font<same font id>...'``）不打 Warning 标，曾被 font_subst 误吃。
_WARNING_RULES: Final = (
    (
        "invalid_utf8",
        re.compile(r"Invalid UTF-8 byte|replaced by U\+FFFD", re.IGNORECASE),
    ),
    ("missing_glyph", re.compile(r"Missing character:", re.IGNORECASE)),
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
    (
        "file_not_found",
        re.compile(
            r"File `[^']+' not found|cannot (?:find|open)|Could not locate",
            re.IGNORECASE,
        ),
    ),
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

_CTX_LINES: Final = 8  # 首个错误后抓取的上下文行数（docs/08 §2.3）
_TAIL_LINES: Final = 30  # log 尾部留存行数
_MAX_STORED_ERRORS: Final = 200  # 存储上限（n_errors 仍精确计数）
_MAX_WARN_SAMPLES: Final = 5  # 每类 warning 样例留存上限

#: CJK 码点区间（基本区+扩展 A/兼容区+扩展 B；对 missing_glyph 判中文渲染）。
_CJK_RANGES: Final = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2EBEF),
)

#: docs/08 §4.3 红线 warning 类（命中即记入 ``WarningSummary.redlines``）。
_REDLINE_CLASSES: Final = frozenset(
    {"invalid_utf8", "missing_glyph_cjk", "file_not_found"}
)


def _is_cjk(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


# ---------------------------------------------------------------- 数据


@dataclass(frozen=True, slots=True)
class LogError:
    """单个编译错误的定位。

    ``line_no`` = log 内 1-based 行号；``tex_file``/``tex_line`` = 源码定位
    （file:line: 直接给出，``^!`` 格式从 ctx 的 ``l.NNN`` 提）；
    ``file_stack`` = 出错时刻 ``(`` 开括号文件栈（外层→内层）。
    """

    line_no: int
    head: str
    tex_file: str | None = None
    tex_line: int | None = None
    ctx: tuple[str, ...] = ()
    file_stack: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """序列化为一级字典。"""
        return {
            "line_no": self.line_no,
            "head": self.head,
            "tex_file": self.tex_file,
            "tex_line": self.tex_line,
            "ctx": list(self.ctx),
            "file_stack": list(self.file_stack),
        }


@dataclass(slots=True)
class WarningSummary:
    """warning 分类汇总。``redlines`` 命中 docs/08 §4.3 红线信号即 dirty 依据。"""

    total: int = 0
    by_class: dict[str, int] = field(default_factory=dict)
    samples: dict[str, list[str]] = field(default_factory=dict)
    redlines: list[str] = field(default_factory=list)
    cjk_missing: int = 0

    def to_dict(self) -> dict[str, object]:
        """序列化为一级字典。"""
        return {
            "total": self.total,
            "by_class": dict(self.by_class),
            "samples": {k: list(v) for k, v in self.samples.items()},
            "redlines": list(self.redlines),
            "cjk_missing": self.cjk_missing,
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


def _classify_warning(line: str, ws: WarningSummary) -> None:
    """单行 warning 归类 + 红线打标。"""
    if not (_ANY_WARNING_RX.search(line) or _MARKERLESS_WARN_RX.search(line)):
        return  # 非 warning 形态行（含 error ctx 内的帮助文本）
    cls = "generic"
    for name, rx in _WARNING_RULES:
        if rx.search(line):
            cls = name
            break
    if cls == "missing_glyph":
        m = _MISSING_CHAR_RX.search(line)
        if m is not None and _is_cjk(int(m.group(1), 16)):
            ws.cjk_missing += 1
            cls = "missing_glyph_cjk"
    ws.total += 1
    ws.by_class[cls] = ws.by_class.get(cls, 0) + 1
    bucket = ws.samples.setdefault(cls, [])
    if len(bucket) < _MAX_WARN_SAMPLES:
        bucket.append(line.strip())
    if cls in _REDLINE_CLASSES:
        red = f"{cls}: {line.strip()[:120]}"
        if red not in ws.redlines:
            ws.redlines.append(red)


def _tex_line_from_ctx(ctx: list[str]) -> int | None:
    for ln in ctx:
        m = _LNUM_RX.match(ln.strip())
        if m:
            return int(m.group(1))
    return None


def _match_error_line(ln: str) -> tuple[str, str | None] | None:
    """``(head, file:line: 给的 tex_file)``；非错误行返回 None。"""
    if _BANG_RX.match(ln):
        return ln.strip(), None
    mf = _FILE_LINE_RX.match(ln)
    if (
        mf is not None
        and looks_like_tex_file(mf.group(1))
        and not _NONERR_FILELINE_RX.search(mf.group(3))
    ):
        return ln.strip(), mf.group(1)
    return None


# ---------------------------------------------------------------- 主入口


def parse_log_text(text: str) -> L2Verdict:
    """解析 log 文本为 ``L2Verdict``（单遍扫描，文件栈增量维护）。"""
    v = L2Verdict()
    lines = text.splitlines()
    if lines:
        m = _ENGINE_RX.match(lines[0])
        if m:
            v.engine = m.group(1)

    stack: list[str | None] = []
    for i, ln in enumerate(lines):
        update_file_stack(ln, stack)

        # —— 错误行：双格式 ——
        hit = _match_error_line(ln)
        if hit is not None:
            head, tex_file = hit
            v.n_errors += 1
            ctx = lines[i + 1 : i + 1 + _CTX_LINES]
            mf = _FILE_LINE_RX.match(ln)
            tex_line = int(mf.group(2)) if mf else None
            if tex_line is None:
                tex_line = _tex_line_from_ctx(ctx)
            err = LogError(
                line_no=i + 1,
                head=head,
                tex_file=tex_file,
                tex_line=tex_line,
                ctx=tuple(ctx),
                file_stack=tuple(s for s in stack if s),
            )
            if v.first_error is None:
                v.first_error = err
            if len(v.errors) < _MAX_STORED_ERRORS:
                v.errors.append(err)
            continue

        _classify_warning(ln, v.warnings)

    v.tail = tuple(lines[-_TAIL_LINES:])
    return v


def parse_log(path: str | Path) -> L2Verdict:
    """从路径读 ``.log`` 解析；文件不存在返回 ``log_missing=True``（不抛异常）。"""
    p = Path(path)
    if not p.exists():
        return L2Verdict(log_missing=True)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return L2Verdict(log_missing=True)
    return parse_log_text(text)
