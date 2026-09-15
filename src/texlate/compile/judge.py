r"""clean 判定三件套（docs/08 §4.3，判据非修复）：

    clean = ① 有 pdf
          ∧ ② `!`≤3 且首错非 missing_*/undefined_cs
          ∧ ③ log warning 扫描零命中（Invalid UTF-8 byte /
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
    "eps_image",
    "latex209",
}

#: CJK 渲染下限：译文 PDF 至少这么多 CJK 字符才算"中文真的渲染了"。
CJK_MIN_CHARS = 20

#: CJK 计数面：U+3400-4DBF 扩A + U+4E00-9FFF 基本区 + U+F900-FAFF 兼容区
#: + U+3007 〇（日期用字）+ U+20000-2FA1F 扩B~F（生僻字漏计会假阴）
_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿〇\U00020000-\U0002fa1f]")


@dataclass
class Verdict:
    """`judge` 产物：终态 + 判据明细（落盘可审计）。"""

    status: str  # "clean" | "partial" | "fail" | "reject"
    reasons: list[str] = field(default_factory=list)  # dirty/fail 判据
    notes: list[str] = field(default_factory=list)  # 信息性记录（不污染 status）
    n_errors: int = 0
    category: str | None = None
    payload: str | None = None
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


def count_missing_chars(log_text: str) -> int:
    """统计 log 里 `Missing character:` 行数（缺字形告警=中文静默丢失信号）。"""
    return len(re.findall(r"Missing character:", log_text))


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


def judge(res: CompRes, *, expect_cjk: bool = False, log_text: str = "") -> Verdict:
    """CompRes → 终态判定。`expect_cjk` 打开中文渲染检查（zh 条件必开）。

    `log_text`：调用方若已读 log 全文可传入；否则读 res.log_path
    （Missing character 计数需要全文，parse_log 只留了结构化字段）。
    """
    v = Verdict(status="fail", n_errors=res.log.n_errors)
    v.warnings_hit = list(res.log.warnings_hit)
    if not res.ok and res.timed_out:
        v.reasons.append("timeout")
        return v
    if not res.has_pdf:
        v.reasons.append("no_pdf")
        cat, pay = classify_error(
            res.log.first_error,
            res.log.error_ctx,
            res.log.tail,
            timed_out=res.timed_out,
        )
        v.category, v.payload = cat, pay
        return v

    # —— 有 pdf：进入 clean/partial 分界判定 ——
    cat, pay = classify_error(
        res.log.first_error,
        res.log.error_ctx,
        res.log.tail,
        timed_out=res.timed_out,
    )
    v.category, v.payload = cat, pay

    if res.log.n_errors > CLEAN_ERR_MAX:
        v.reasons.append(f"errors>{CLEAN_ERR_MAX} ({res.log.n_errors})")
    if cat in DIRTY_FIRST_CATEGORIES:
        v.reasons.append(f"first_error={cat}:{pay}")
    v.reasons.extend(f"warn:{hit}" for hit in res.log.warnings_hit)

    full_log = log_text
    if not full_log and res.log_path and res.log_path.exists():
        try:
            full_log = res.log_path.read_text(errors="replace")
        except OSError:
            full_log = ""
    v.missing_chars = count_missing_chars(full_log)
    if expect_cjk and v.missing_chars > 0:
        v.reasons.append(f"missing_character×{v.missing_chars}")

    if expect_cjk:
        _cjk_render_check(v, res)

    v.status = "clean" if not v.reasons else "partial"
    return v
