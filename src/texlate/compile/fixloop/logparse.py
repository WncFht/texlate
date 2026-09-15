"""logparse — .log 解析 + taxonomy 分类 (rules.yaml 第一层)。

移植自 bench/py/fixloop.py L48-125 (`first_error`/`classify`), 增强两点
(docs/research/latex/fixloop-rules.md §5 spec):
  - ctx 内 ``l.<N>`` 行号 → ``ErrReport.line_no``
  - ``(`` 开括号文件栈追踪 → ``ErrReport.file_stack`` (定位出错 .tex/.sty)

另加 rules.yaml ``warnings:`` 段扫描 (docs/08 §4.3 红线) → ``warnings`` 字段;
``invalid_utf8`` 命中在无 '!' 错时升级为 ``warn_utf8`` 伪类别 (v1.1 扩展,
驱动 non_utf8_source 修复轮)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from texlate.texlog import file_stack_at

__all__ = ["ErrReport", "Taxonomy", "parse_log", "parse_text"]

_CTX_LINES = 8  # spike L62: 首错行后取 8 行上下文
_TAIL_LINES = 30  # spike L63: tail 30 行
_LINE_NO_RE = re.compile(r"l\.(\d+)")
# `-file-line-error` 模式下错误行是 `path:line: msg` (无 '!' 前缀) ——
# impl-compile 的 xelatex 命令行带此旗标, 只数 '!' 会漏全部错误。
# Warning 行 (`./f.tex:5: LaTeX Warning: ...`) 同格式但非错误, 须排除,
# 否则 `n_bang==0 → clean` 门永远不通。
_ERR_FILELINE_RE = re.compile(r"^\S+?:\d+: \S")
_WARN_FILELINE_RE = re.compile(
    r"^\S+?:\d+: (?:LaTeX|Package|Class)\b[^\n]*?\bWarning\b"
)
#: ``==> Fatal error occurred`` 汇总尾行也是 ``file:line:`` 形态——
#: 同一失败的复述（单空格变体存在），计入会多报一个错误。
_FATAL_TRAILER_RE = re.compile(r"^\S+?:\d+:\s*==>")


def _is_err_line(ln: str) -> bool:
    """`!` 行或 `-file-line-error` 行 (排除 Warning 伪命中与 ==> 汇总尾行)。"""
    if ln.startswith("!"):
        return True
    return (
        bool(_ERR_FILELINE_RE.match(ln))
        and not _WARN_FILELINE_RE.match(ln)
        and not _FATAL_TRAILER_RE.match(ln)
    )


@dataclass(slots=True)
class ErrReport:
    """一次编译的 log 摘要 (首个错误 + 计数 + tail + 结构定位 + warnings)。"""

    first: str | None = None  # 首个 '!' 行 (strip 后)
    ctx: str | None = None  # 首错行起 ≤8 行
    n_bang: int = 0  # '!' 行总数
    tail: str = ""  # 末 30 行
    line_no: int | None = None  # ctx 内 l.N 行号
    file_stack: list[str] = field(default_factory=list)  # 出错时打开的文件栈
    warnings: list[str] = field(default_factory=list)  # 命中的 warning id
    raw: str = ""  # log 全文 (供 escalate_llm context / cases log_excerpt)


def parse_log(
    log_path: Path | None, warn_patterns: list[dict[str, Any]] | None = None
) -> ErrReport:
    """读 .log → ErrReport。log 不存在/不可读 → 全空 report (spike L50-55)。"""
    if log_path is None or not Path(log_path).exists():
        return ErrReport()
    try:
        text = Path(log_path).read_text(errors="replace")
    except OSError:
        return ErrReport()
    return parse_text(text, warn_patterns)


def parse_text(
    text: str, warn_patterns: list[dict[str, Any]] | None = None
) -> ErrReport:
    """Log 文本 → ErrReport (tectonic stdout_tail 兜底也走这里)。

    错误行双格式: `^!` (spike 原语义) + `file:line:` (-file-line-error,
    impl-compile xelatex 命令行旗标; Warning 行不计入)。
    """
    rep = ErrReport(raw=text)
    lines = text.splitlines()
    first_i: int | None = None
    for i, ln in enumerate(lines):
        if _is_err_line(ln):
            rep.n_bang += 1
            if first_i is None:
                first_i = i
                rep.first = ln.strip()
                rep.ctx = "\n".join(lines[i : i + _CTX_LINES])
    rep.tail = "\n".join(lines[-_TAIL_LINES:])
    if rep.ctx:
        m = _LINE_NO_RE.search(rep.ctx)
        if m:
            rep.line_no = int(m.group(1))
    if first_i is not None:
        rep.file_stack = file_stack_at(lines, first_i)
    for w in warn_patterns or []:
        if re.search(w["pattern"], text, re.IGNORECASE | re.MULTILINE):
            rep.warnings.append(w["id"])
    return rep


def _payload(entry: dict[str, Any], m: re.Match[str]) -> str | None:
    """Payload 取值: payload_group 指定组, 否则首个非空组 (spike L109)。"""
    if not m.re.groups:
        return None
    grp = entry.get("payload_group")
    if grp is not None:
        return m.group(grp) if grp <= len(m.groups()) else None
    if "payload_group" in entry:  # 显式 null → 无 payload
        return None
    return next((g for g in m.groups() if g), None)


class Taxonomy:
    """rules.yaml taxonomy 段的编译态: scope 三段评估序照 spike L67-125。"""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        """编译 taxonomy 条目 → head/tail/warnings 三个有序评估表。"""
        self.head: list[tuple[dict[str, Any], re.Pattern[str]]] = []
        self.tail: list[tuple[dict[str, Any], re.Pattern[str]]] = []
        self.warn: list[dict[str, Any]] = []
        for e in entries:
            scope = e.get("scope", "head")
            if scope == "head":
                self.head.append((e, re.compile(e["pattern"], re.IGNORECASE)))
            elif scope == "tail":
                self.tail.append((e, re.compile(e["pattern"], re.IGNORECASE)))
            elif scope == "warnings":
                self.warn.append(e)
        self.warn_cats = {e["id"] for e in self.warn}

    def classify(  # noqa: C901  # scope 三段评估序即分支
        self, rep: ErrReport, *, timed_out: bool = False
    ) -> tuple[str | None, str | None]:
        """→ (category, payload)。payload 供规则定位 (文件名/字体名/cs 名)。"""
        if timed_out:
            return "timeout", None
        if rep.first:
            head = rep.first + ("\n" + rep.ctx if rep.ctx else "")
            for entry, pat in self.head:
                m = pat.search(head)
                if not m:
                    continue
                sub = entry.get("subclassify")
                if sub:
                    sm = re.search(sub["pattern"], head)
                    if sm:
                        grp = sub.get("payload_group")
                        pay = (
                            sm.group(grp)
                            if grp
                            else next((g for g in sm.groups() if g), None)
                        )
                        return sub["into"], pay
                return entry["id"], _payload(entry, m)
        # —— 无 '!' 行: tail 段回溯 (交互式缺文件/Emergency) ——
        blob = rep.tail
        for entry, pat in self.tail:
            m = pat.search(blob)
            if m and (not entry.get("guard") or re.search(entry["guard"], blob)):
                return entry["id"], _payload(entry, m)
        # —— 仍不中: warning 驱动的伪类别 (v1.1, docs/08 §5.2) ——
        for entry in self.warn:
            if entry.get("warn_id") in rep.warnings:
                return entry["id"], None
        return ("other" if rep.first else "clean"), None
