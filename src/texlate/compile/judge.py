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
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from texlate.redlines import REDLINES_BY_ID, name_pattern
from texlate.textutil import CJK_RX, CMD_BOUNDARY, mask_tex

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

#: thm-restate ``restatable`` 观察探针（``restatable_loss`` 行，单源
#: ``texlate.redlines``）：包加载痕迹 → notes。env-name 参被译 → 存体
#: ``\csname #2\endcsname`` 打未定义 env 名 → ``\csname`` 自动 \relax
#: **零消息**（lane-silentthm 实证 ``{定理}{main}``：0 个 ``!`` 行、定理头
#: 静默丢、body 照排）——log 面无事件可挂，presence 是 log 侧最大诚实信号。
_THM_RESTATE = name_pattern(REDLINES_BY_ID["restatable_loss"].judge)
_THM_RESTATE_RX = re.compile(_THM_RESTATE[1])
#: vtex 源面判定信号（source 介质，不入 registry——judge LayerSpec 语义是
#: log regex）：``\begin{restatable}[?]{env}{cskey}`` 双机位参（env 名 +
#: csname 键）非 ASCII ≈ 参被译文污染=静默丢失真条件（纸真 CJK env 名
#: 合法 → note 不判红）。cskey 缺席的退化头仍收 env 参。
_RESTATABLE_HDR_RX = re.compile(
    r"\\begin\s*\{restatable\*?\}\s*(?:\[[^\]]*\])?\s*"
    r"\{([^{}]*)\}(?:\s*\{([^{}]*)\})?"
)
_HDR_NONASCII_RX = re.compile(r"[^\x00-\x7f]")

#: doc 级机位参数审计面（``_machine_slot_probe`` 消费）：逐 ``*.tex`` 在
#: ``mask_tex`` 视图上匹配机位实参——注释/verbatim/死区同形 token 非活
#: 机位（参定位在原文字节偏移上，报文回切原文）。每行 ``(kind, rx)``，
#: rx 捕获组全为机位实参候选（任一组非 ASCII 即记 note）。可选位一律先
#: 被 ``\[...\]``/``\*?`` 吃掉不命中；``\section{中文}`` 等文位结构上就
#: 不在此表。ph_map 字节同一性靠构造保住，本表盯的活口是未标机参进
#: ``[[CHUNK_n]]`` zh 面——restatable env 参被译（``\csname<undef>
#: \endcsname``→``\relax`` 零 ``!`` 行）是实证锚点。
_MACHINE_SLOT_RXS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # \begin/\end env 名
    ("env", re.compile(r"\\(?:begin|end)\s*\{([^{}\n]*)\}")),
    # \begin{restatable}[?]{env}{cskey} 双机位参
    ("restatable", _RESTATABLE_HDR_RX),
    # \label/\ref/\eqref/\pageref/\autoref 键（star 形同收）
    (
        "ref",
        re.compile(r"\\(?:label|ref|eqref|pageref|autoref)\*?\s*\{([^{}\n]*)\}"),
    ),
    # \bibliography/\addbibresource 文献路径
    (
        "bib",
        re.compile(
            r"\\(?:bibliography|addbibresource)\s*"
            r"(?:\[[^\]\n]*\]\s*)?\{([^{}\n]*)\}"
        ),
    ),
    # \csname...\endcsname 体（跨行体 DOTALL）
    (
        "csname",
        re.compile(r"\\csname" + CMD_BOUNDARY + r"\s*(.*?)\\endcsname", re.DOTALL),
    ),
    # \include/\includegraphics 必填路径（可选位排除）
    (
        "path",
        re.compile(
            r"\\(?:include|includegraphics)\*?\s*"
            r"(?:\[[^\]\n]*\]\s*)*\{([^{}\n]*)\}"
        ),
    ),
    # \input 三形态：花括号/引号/裸 token（\inputlineno 系被 CMD_BOUNDARY 挡）
    (
        "input",
        re.compile(
            r"\\input"
            + CMD_BOUNDARY
            + r"\s*(?:\{([^{}\n]*)\}|\"([^\"\n]*)\"|([^\s{}%\\]+))"
        ),
    ),
)
#: 机位审计 note 封顶——防巨型工程 notes 刷屏。
_MACHINE_SLOT_MAX = 20
#: 死尾截断（``compile.probe._DEAD_TAIL_RE`` 同口径）：``\end{document}``/
#: ``\endinput`` 之后的机位同形 token 非活 slot，在遮盖视图上定位（注释/
#: verbatim 内的字面命中不算死界）。
_DEAD_TAIL_RX = re.compile(r"\\end\s*\{document\}|\\endinput\b")


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


def _thm_restate_probe(v: Verdict, full_log: str) -> None:
    """thm-restate 观察项：包加载痕迹记 note；参审计并入 ``_machine_slot_probe``。"""
    if _THM_RESTATE_RX.search(full_log):
        v.notes.append(_THM_RESTATE[0])


def _slot_scan(
    src: str, rxs: tuple[tuple[str, re.Pattern[str]], ...]
) -> list[tuple[str, str]]:
    """单文件源文机位命中 → ``(kind, arg)`` 序对（遮盖视图 + 死尾截断）。"""
    view = mask_tex(src)
    dead = _DEAD_TAIL_RX.search(view)
    if dead is not None:
        view = view[: dead.start()]
    hits: list[tuple[str, str]] = []
    for kind, rx in rxs:
        for m in rx.finditer(view):
            for i, g in enumerate(m.groups(), start=1):
                if g is not None and _HDR_NONASCII_RX.search(g):
                    hits.append((kind, src[m.start(i) : m.end(i)]))
                    break
    return hits


def machine_slot_audit(workdir: Path) -> list[str]:
    r"""机位审计独立入口：``workdir`` 下 ``*.tex`` 机位实参非 ASCII → note 串。

    judge() 内 ``_machine_slot_probe`` 只兜 has_pdf 路径——编译挂死早退
    时本函数仍给 splice 后调用面（e2e ``_translate_tree``/worker splice/
    ``repair_l2._resplice``）留污染证据。note 形与探针同：
    ``machine_slot_nonascii:<kind>:<file>:<arg>`` + ``capped`` 截断标记。
    """
    from texlate.compile.fixloop._builtins_bib import (  # noqa: PLC0415  # 延迟: fixloop 链重
        _CITE_FAMILY_RE,
    )

    rxs = (*_MACHINE_SLOT_RXS, ("cite", _CITE_FAMILY_RE))
    hits: list[str] = []
    for tex in sorted(workdir.rglob("*.tex")):
        try:
            src = tex.read_text(errors="replace")
        except OSError:
            continue
        hits.extend(
            f"machine_slot_nonascii:{kind}:{tex.name}:{arg!r}"
            for kind, arg in _slot_scan(src, rxs)
        )
        if len(hits) >= _MACHINE_SLOT_MAX:
            break
    notes = hits[:_MACHINE_SLOT_MAX]
    if len(hits) >= _MACHINE_SLOT_MAX:
        notes.append(f"machine_slot_nonascii:capped@{_MACHINE_SLOT_MAX}")
    return notes


def _machine_slot_probe(v: Verdict, res: CompRes) -> None:
    r"""Doc 级机位审计：workdir ``*.tex`` 机位实参非 ASCII → note 观察项。

    未标机位参进 zh chunk 面=静默丢失真条件（``\label{中文}`` 断链、
    ``\cite{中文}`` undefined citation、restatable env 参 ``\relax``
    零 ``!`` 行），但纸真 CJK env 名/label 合法 → 只记 note 不判红。
    本体在 ``machine_slot_audit``（splice 后调用面复用同一扫描）。
    """
    if res.workdir is not None:
        v.notes.extend(machine_slot_audit(res.workdir))


def _full_log_text(res: CompRes, log_text: str) -> str:
    """Judge 用 log 全文：实参优先，缺席回退 log_path 读盘。"""
    if log_text:
        return log_text
    if res.log_path and res.log_path.exists():
        try:
            return res.log_path.read_text(errors="replace")
        except OSError:
            return ""
    return ""


def _log_probes(v: Verdict, res: CompRes, full_log: str, *, expect_cjk: bool) -> None:
    """log/源面观察探针束：缺字形门控 + thm-restate 包在场 note + 机位审计。"""
    _missing_char_check(v, full_log, expect_cjk=expect_cjk)
    _thm_restate_probe(v, full_log)
    _machine_slot_probe(v, res)


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


def _timeout_verdict(v: Verdict, res: CompRes, log_text: str) -> Verdict:
    """超时/截杀编译的早退判定：fail + category 细分（runaway_output/timeout）。

    活哨截杀留有行程内原因（``CompRes.sentry_reason`` 显式字段，或未经
    归位的 str 形 ``timed_out``）——记录值优先于文本重扫：截断窗口数
    不出全程签名密度（1003.2165 实证误归泛 timeout）。无记录原因退回
    文本证据：全量 .log（页洪签名只在全文计数够得着
    ``_RUNAWAY_PAGE_MAX``）+ stdout_tail 兜底窗。
    """
    v.reasons.append("timeout")
    sentry_reason = getattr(res, "sentry_reason", None)
    if sentry_reason is None and isinstance(res.timed_out, str):
        sentry_reason = res.timed_out
    if sentry_reason is not None:
        v.notes.append(f"sentry:{sentry_reason}")
        v.category = "runaway_output"
        return v
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
        from texlate.compile.fixloop.logparse import (  # noqa: PLC0415  # 延迟: fixloop/__init__ 链重
            _is_runaway_output,
        )

        blob = _full_log_text(res, log_text)
        if _is_runaway_output(blob) or _is_runaway_output(res.stdout_tail):
            cat = "runaway_output"
    v.category = cat
    return v


def judge(res: CompRes, *, expect_cjk: bool = False, log_text: str = "") -> Verdict:
    """CompRes → 终态判定。`expect_cjk` 打开中文渲染检查（zh 条件必开）。

    `log_text`：调用方若已读 log 全文可传入；否则读 res.log_path
    （Missing character 计数需要全文，parse_log 只留了结构化字段）。
    """
    v = Verdict(status="fail", n_errors=res.log.n_errors)
    v.warnings_hit = list(res.log.warnings_hit)
    if res.timed_out:
        return _timeout_verdict(v, res, log_text)
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

    _log_probes(v, res, _full_log_text(res, log_text), expect_cjk=expect_cjk)

    if expect_cjk:
        _cjk_render_check(v, res)

    v.status = "clean" if not v.reasons else "partial"
    return v


# ------------------------------------------------------------------ 配对机位 diff

#: 逗号键表归一的机位类：``\cite{a,b}``↔``\cite{b,a}`` 键序重排合法，
#: ``\bibliography``/``\addbibresource`` 多文件表同理——按键多重集比对。
#: 其余类原子比对（``\ref{a,b}`` 合并即缺陷）。
_SLOT_KEYLIST_KINDS = frozenset({"cite", "bib"})


def _slot_args(
    src: str, rxs: tuple[tuple[str, re.Pattern[str]], ...]
) -> list[tuple[str, str]]:
    r"""单文件源文机位实参全量命中 → ``(kind, arg)`` 序对。

    ``_slot_scan`` 同口径的 ``mask_tex`` 视图 + 死尾截断，但无非 ASCII
    过滤、每 match 全部非 None 捕获组各自入列（restatable 双参都收，
    ``\\input`` 三形态只中一支）——arg 按视图命中区间回切原文字节。
    """
    view = mask_tex(src)
    dead = _DEAD_TAIL_RX.search(view)
    if dead is not None:
        view = view[: dead.start()]
    hits: list[tuple[str, str]] = []
    for kind, rx in rxs:
        for m in rx.finditer(view):
            hits.extend(
                (kind, src[m.start(i) : m.end(i)])
                for i, g in enumerate(m.groups(), start=1)
                if g is not None
            )
    return hits


def _slot_arg_multiset(
    src: str, rxs: tuple[tuple[str, re.Pattern[str]], ...]
) -> Counter[tuple[str, str]]:
    """机位命中归一成 ``(kind, key)`` 多重集：keylist 类逗号拆键去空白。"""
    ms: Counter[tuple[str, str]] = Counter()
    for kind, arg in _slot_args(src, rxs):
        if kind in _SLOT_KEYLIST_KINDS:
            for raw in arg.split(","):
                key = raw.strip()
                if key:
                    ms[(kind, key)] += 1
        else:
            ms[(kind, arg)] += 1
    return ms


def paired_slot_diff(src_tex: str, zh_tex: str, rel: str) -> list[str]:
    r"""src/zh 机位实参配对 diff：splice 后逐文件对账 → note 串。

    ``res.vtex``（post-normalize 源，与落盘 src 字节同一）对 zh 重建文做
    ``(kind, arg)`` 多重集 diff——``src−zh`` 记 ``slot_arg_missing``（丢参/
    译参），``zh−src`` 记 ``slot_arg_extra``（幻影参：LLM 臆造 ``\cite`` →
    undefined citation 前兆）。cite/bib 逗号键表归一后比对；其余类原子。
    当前 chunk 面零机位 token 使本探针日常空转——价值在捕获下一个扫描
    缺口把机位参漏上 LLM 面（silentthm 事故类）+ 重建侧参字节腐烂。
    """
    from texlate.compile.fixloop._builtins_bib import (  # noqa: PLC0415  # 延迟: fixloop 链重
        _CITE_FAMILY_RE,
    )

    rxs = (*_MACHINE_SLOT_RXS, ("cite", _CITE_FAMILY_RE))
    src_ms = _slot_arg_multiset(src_tex, rxs)
    zh_ms = _slot_arg_multiset(zh_tex, rxs)
    notes = [
        f"slot_arg_missing:{kind}:{rel}:{arg!r}"
        for (kind, arg), n in sorted((src_ms - zh_ms).items())
        for _ in range(n)
    ]
    notes.extend(
        f"slot_arg_extra:{kind}:{rel}:{arg!r}"
        for (kind, arg), n in sorted((zh_ms - src_ms).items())
        for _ in range(n)
    )
    if len(notes) > _MACHINE_SLOT_MAX:
        notes = notes[:_MACHINE_SLOT_MAX]
        notes.append(f"slot_arg_missing:capped@{_MACHINE_SLOT_MAX}")
    return notes
