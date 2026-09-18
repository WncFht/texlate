r"""clean 判定三件套（docs/08 §4.3，判据非修复）：

    clean = ① 有 pdf
          ∧ ② `!`≤3 且首错非 missing_*/undefined_cs
          ∧ ③ log warning 扫描零命中（Invalid UTF-8 byte——限工程文件
               产生者，系统 texmf/bundle 件降 notes 观察项 /
               Missing character.*U+FFFD / tectonic `File.*not found` 降级行 /
               missing_graphic 红线）
          ∧ ④ 中文实际渲染检查（`expect_cjk` 时）

    partial = 有 pdf 但 dirty；fail = 无 pdf / 超时 / 引擎缺失。

铁律"出 PDF ≠ 成功"（docs/08 §0）：2501.14787 在 1519 个 `!` 错误下照样吐
1MB pdf；hep-th 出 8 页 PDF 但 0 中文字节——校验必须独立于编译。

中文渲染检查选 **pdftotext**（poppler，子进程边界）：
- PyMuPDF 是 AGPL——只能走 sidecar 进程边界，为一次计数引它进来不划算；
- pypdf 是 BSD 但对 Identity-H/Adobe-GB1 无 ToUnicode 的 CJK 字体抽取不可靠
  （正是 embed_cjk_mappings 要修的场景）；
- pdftotext 零依赖、GPL 二进制走子进程不染库、对 CID 字体抽取最稳。
pdftotext 缺席时降级为 log 判据：`Missing character:` 计数==0。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from texlate.redlines import REDLINES_BY_ID, name_pattern
from texlate.textutil import CJK_RX

from .engine import CompRes, classify_error
from .sandbox import find_tool, run_process

if TYPE_CHECKING:
    from pathlib import Path

#: `!` 错误容忍上限（docs/08 §4.3）。
CLEAN_ERR_MAX = 3

#: 首错命中这些类别 → 即使有 pdf 也判 dirty（出 pdf ≠ 内容完整）。
DIRTY_FIRST_CATEGORIES = {
    "missing_file",
    "missing_tfm",
    "missing_pfb",
    "missing_graphic",
    "fontspec_missing",
    "undefined_cs",
    "ps_image",
    "latex209",
}

#: CJK 渲染下限：译文 PDF 至少这么多 CJK 字符才算"中文真的渲染了"。
CJK_MIN_CHARS = 20

#: CJK 计数面单源在 ``texlate.textutil.CJK_RX``（扩A+基本+兼容+〇+扩B~F）。
_CJK_RE = CJK_RX


@dataclass
class Verdict:
    """`judge` 产物：终态 + 判据明细（落盘可审计）。"""

    status: str  # "clean" | "partial" | "fail"
    reasons: list[str] = field(default_factory=list)  # dirty/fail 判据
    notes: list[str] = field(default_factory=list)  # 信息性记录（不污染 status）
    n_errors: int = 0
    category: str | None = None
    payload: str | None = None
    #: 逐错误行 cat 构成（``res.log.errors`` 全量分类计数）——首错 cat
    #: 遮 bulk 的纠偏原料（quant-ph/9703040：110 错中 108 syntax
    #: 而 category=illegal_unit）；签名聚合取众数用。
    error_cats: dict[str, int] = field(default_factory=dict)
    #: cat → 首见 payload（``error_cats`` 同键子集，仅非空 payload 收录）。
    error_pay: dict[str, str] = field(default_factory=dict)
    cjk_chars: int = -1  # -1 = 未测
    missing_chars: int = 0
    warnings_hit: list[str] = field(default_factory=list)


def pdf_cjk_chars(pdf: Path, *, timeout: float = 60) -> int:
    """用 pdftotext 抽全文计 CJK 字符数；pdftotext 缺席/失败返回 -1。"""
    tool = find_tool("pdftotext")
    if tool is None or not pdf.is_file():
        return -1
    rc, out, _, to = run_process(
        [tool, "-enc", "UTF-8", str(pdf), "-"],
        cwd=pdf.parent,
        env={},
        timeout=timeout,
    )
    if to or rc != 0:
        return -1
    return len(_CJK_RE.findall(out))


#: 门控缺字形计数：排除 `in font nullfont`——试排/测量盒吞字是良性
#: （37 纯 nullfont 格零 CJK 实证见 bench/results/nullfont-scout-2026-09-17/）。
#: 两 pattern + reason 词干单源在 ``texlate.redlines``（★2，与 engine
#: missing_chars/rules missing_char/l2 missing_glyph 同概念行）。
_MISSCHAR_GATE = name_pattern(REDLINES_BY_ID["missing_char"].judge)
_MISSCHAR_NULLFONT = name_pattern(REDLINES_BY_ID["missing_char_nullfont"].judge)
_MISSCHAR_GATE_RX = re.compile(_MISSCHAR_GATE[1])
_MISSCHAR_NULLFONT_RX = re.compile(_MISSCHAR_NULLFONT[1])


def count_missing_chars(log_text: str) -> int:
    """统计 log 里 `Missing character` 行数（缺字形告警=中文静默丢失信号）。

    `in font nullfont` 命中不计入——良性试排吞字非正文丢字。
    """
    return len(_MISSCHAR_GATE_RX.findall(log_text))


def _missing_char_check(v: Verdict, full_log: str, *, expect_cjk: bool) -> None:
    """缺字形门控计数（nullfont 排除）+ nullfont 命中进 notes 观察项。"""
    v.missing_chars = count_missing_chars(full_log)
    nf_misses = len(_MISSCHAR_NULLFONT_RX.findall(full_log))
    if nf_misses:
        v.notes.append(f"{_MISSCHAR_NULLFONT[0]}×{nf_misses}")
    if expect_cjk and v.missing_chars > 0:
        v.reasons.append(f"{_MISSCHAR_GATE[0]}×{v.missing_chars}")


def _signal_attribution(res: CompRes) -> int | None:
    """引擎被杀的信号号（无则 None）。

    ``killed_signal`` 覆盖任一 pass（res.rc 只记末 pass，mid-loop 死亡会被
    掩盖——2211.13013 实证）；``rc<0`` 兜底手工构造的 CompRes。
    """
    if res.killed_signal is not None:
        return res.killed_signal
    if res.rc is not None and res.rc < 0:
        return -res.rc
    return None


def _cjk_render_check(v: Verdict, res: CompRes) -> None:
    """中文渲染检查（expect_cjk 时）：pdftotext 优先，缺席降级 log 判据。"""
    cjk = pdf_cjk_chars(res.pdf) if res.pdf else -1
    v.cjk_chars = cjk
    if cjk == 0:
        # hep-th 教训：8 页 PDF、0 中文字节——全线最坏静默失败。
        v.reasons.append("cjk_chars=0")
    elif 0 < cjk < CJK_MIN_CHARS:
        v.reasons.append(f"cjk_chars<{CJK_MIN_CHARS} ({cjk})")
    elif cjk < 0:
        # pdftotext 缺席：降级判据 = log Missing character 计数。
        # 无负信号不判 dirty（工具缺席是环境限制，不是文档问题）。
        if v.missing_chars > 0:
            v.reasons.append("cjk_unverified+missing_chars")
        else:
            v.notes.append("cjk_unverified(pdftotext absent)")


def _error_composition(
    v: Verdict, res: CompRes, first_cat: str | None, first_pay: str | None
) -> None:
    """逐错误行分类 → ``v.error_cats`` 构成 + ``v.error_pay`` 首见 payload。

    首错复用 ``(first_cat, first_pay)`` 权威对（带 ctx/tail 分类更准）；
    其余行裸行分类——只能靠 ctx 命中的类别会落 ``other``，构成仍忠实。
    """
    if not res.log.errors:
        return
    cats: dict[str, int] = {}
    pays: dict[str, str] = {}
    for i, ln in enumerate(res.log.errors):
        cat, pay = (
            (first_cat, first_pay)
            if i == 0
            else classify_error(ln, None, "", timed_out=False)
        )
        if not cat or cat == "clean":
            cat = "other"
        cats[cat] = cats.get(cat, 0) + 1
        if pay and cat not in pays:
            pays[cat] = str(pay)
    v.error_cats = cats
    v.error_pay = pays


def judge(res: CompRes, *, expect_cjk: bool = False, log_text: str = "") -> Verdict:
    """CompRes → 终态判定。`expect_cjk` 打开中文渲染检查（zh 条件必开）。

    `log_text`：调用方若已读 log 全文可传入；否则读 res.log_path
    （Missing character 计数需要全文，parse_log 只留了结构化字段）。
    """
    v = Verdict(status="fail", n_errors=res.log.n_errors)
    v.warnings_hit = list(res.log.warnings_hit)
    if res.timed_out:
        v.reasons.append("timeout")
        # 超时编译细分 category（taxonomy 单源）：\output 期 Overfull \vbox
        # 刷屏 → runaway_output（输出例程暴走），否则泛 timeout——triage/
        # 账本据 category 分流（gr-qc/0104075：73,595 页暴走烧满预算）。
        cat, _pay = classify_error(
            res.log.first_error,
            res.log.error_ctx,
            res.log.tail,
            timed_out=True,
        )
        if cat == "timeout":
            # 活哨早杀的 .log 截在签名刷屏前——证据在 stdout_tail
            # （哨件凭它越阈），补查使归因仍是 runaway_output。
            from texlate.compile.fixloop.logparse import (  # noqa: PLC0415  # 延迟: fixloop/__init__ 链重
                _is_runaway_output,
            )

            if _is_runaway_output(res.stdout_tail):
                cat = "runaway_output"
        v.category = cat
        return v
    # 引擎被信号杀死：死进程产出不可信，有 pdf 也判 dirty，
    # 并把真凶写进 reasons/notes（截断 aux 的下游症状不再顶包归因）。
    sig = _signal_attribution(res)
    if sig is not None:
        v.notes.append(f"engine_killed:SIG{sig}")
        v.reasons.append(f"killed_by_signal:{sig}")
    if not res.has_pdf:
        v.reasons.append("no_pdf")
        cat, pay = classify_error(
            res.log.first_error,
            res.log.error_ctx,
            res.log.tail,
            timed_out=res.timed_out,
        )
        # 无 log 可分类（引擎缺席/启动失败）时 classify 返回 "clean"——
        # 与 status=fail 矛盾，账本归 "other"。
        v.category, v.payload = ("other", None) if cat == "clean" else (cat, pay)
        _error_composition(v, res, v.category, v.payload)
        return v

    # —— 有 pdf：进入 clean/partial 分界判定 ——
    cat, pay = classify_error(
        res.log.first_error,
        res.log.error_ctx,
        res.log.tail,
        timed_out=res.timed_out,
    )
    v.category, v.payload = cat, pay
    _error_composition(v, res, cat, pay)

    if res.log.n_errors > CLEAN_ERR_MAX:
        v.reasons.append(f"errors>{CLEAN_ERR_MAX} ({res.log.n_errors})")
    if cat in DIRTY_FIRST_CATEGORIES:
        v.reasons.append(f"first_error={cat}:{pay}")
    v.reasons.extend(f"warn:{hit}" for hit in res.log.warnings_hit)
    # 系统 texmf/bundle 件产生的红线（老 CTAN 包自带坏字节）——观察项
    # 留痕不阻断 clean（fixer-utf8 归因：96% invalid_utf8 属此类）。
    v.notes.extend(f"sys_warn:{hit}" for hit in res.log.warnings_sys)

    full_log = log_text
    if not full_log and res.log_path and res.log_path.exists():
        try:
            full_log = res.log_path.read_text(errors="replace")
        except OSError:
            full_log = ""
    _missing_char_check(v, full_log, expect_cjk=expect_cjk)

    if expect_cjk:
        _cjk_render_check(v, res)

    v.status = "clean" if not v.reasons else "partial"
    return v
