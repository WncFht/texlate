r"""T0 版面质检电池（layoutqc stage 的检测本体）。

输入全是现成产物：splice 树的 ``<stem>.pdf/.log/.txlm``、build-base 树
的同三件套、src 源树（env_inventory 期望面）。零 LLM、零重编——poppler
子进程（pdftotext/-bbox、pdfimages -list）+ 日志正则 + marks 查表。

每个 check 返 findings（``{sig, …}`` 逐条）+ metrics 计数；汇总成
``{findings, metrics}`` 由 stage 挂 verdict/sig/errors。设计口径见
docs/dev/layoutqc-plan.md §4 T0 表。

阈值集中本文件顶部——校准集（§7.4）出来前全是先验值，sig 即分桶键，
阈值漂移只改一处。
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Final

from texlate.compile.marks import (
    _MARK_ENVS,
    compare_marks,
    env_inventory,
    env_sequence,
    parse_txlm,
)

# ---------------------------------------------------------------- 阈值（先验）

OVERFULL_MAX_PT: Final = 50.0  # 单处 overfull 超此 pt 数 → sig
OVERFULL_COUNT: Final = 10  # overfull 总数超此 → sig
MARGIN_BREACH_PT: Final = 4.0  # word bbox 出 textblock 容差
MARGIN_BREACH_MIN: Final = 3  # 越界词数下限（抗下标噪）
OVERLAP_IOU: Final = 0.3  # 跨行 word IoU 阈（BabelDOC #615 法）
OVERLAP_MIN_PAIRS: Final = 3  # 重叠词对下限
CURVES_INK_MIN: Final = 0.005
#: 缺字框聚簇阈——单页 ≥4 个空心矩形才算 .notdef 连珠（单个 □
#: 可为合法符号/复选框）。
TOFU_MIN_PAGE: Final = 4
#: 表格规则丢失阈——zh 规则数 < base×0.6（base≥3 才有对拍意义，
#: booktabs 三线起步）。
TABLE_RULE_LOST: Final = 0.6
#: 逐页墨量回归阈——zh 页墨量 < base ±2 页窗峰值 ×0.35 → 局部
#: 掉图洞。译文偏短系统偏轻取 0.35 余量；±2 页窗吃 reflow 错位。
INK_DROP_RATIO: Final = 0.35

#: 门三档（docs/dev/layoutqc-plan.md §11.1）——HARD 挡 done 留全档、
#: WARN 进 QC score 不挡、INFO 纯记账。未分类新 sig 默认按 WARN
#: 计（新探测器默认不挡门，硬档须显式进 _HARD_SIGS）。
_HARD_SIGS: Final = frozenset(
    {
        "layout:no_pdf",
        "layout:pdf_corrupt",
        "layout:marks_coverage",
        "layout:lost_element",
        "layout:float_seq_mismatch",
        "layout:dropped_env",
        "layout:offpage",
        "layout:paper_mismatch",
        "layout:float_lost",
        "align_page_count",
        "align_figure_lost",
        "align_math_drift",
        "vis_degenerate",
        "vis_blank_page",
        "vis_ink_blob",
        "vis_void",
        "vis_tofu_box",
        "geo_table_lost",
        "geo_column_collapse",
        "geo_text_as_curves",
    }
)
_WARN_SIGS: Final = frozenset(
    {
        "xlat_residual_en",
        "xlat_broken_refs",
        "geo_margin_breach",
        "geo_text_overlap",
        "layout:float_drift",
        "layout:order_inversion",
        "layout:overfull",
        "geo_header_lost",
        "align_order_break",
        "regress_ink_profile",
    }
)
_INFO_SIGS: Final = frozenset(
    {"layout:float_fit", "layout:marks_absent"}
)  # 曲线化文本页墨量阈（页码空页<此）
PAGE_RATIO_LO: Final = 0.6  # zh/base 页数比合法带
PAGE_RATIO_HI: Final = 1.6
RESIDUAL_EN_MIN_LINES: Final = 25  # 残留英文行数阈（AND frac）
RESIDUAL_EN_MIN_FRAC: Final = 0.02  # 且占全部文本行比
RESIDUAL_EN_MASS_LINES: Final = 60  # 绝对质量逃逸臂（长文低占比也报）
DEGEN_NGRAM: Final = 5  # 重复 n-gram 长度
DEGEN_NGRAM_MAX: Final = 20  # 同 n-gram 出现上限
DEGEN_PERIODIC_MIN_LINES: Final = 3  # 行内周期占位行数阈（修辞性
# 重复偶发单行不计）
EMPTY_PAGE_CHARS: Final = 10  # 空页字符下限
EMPTY_PAGE_MAX: Final = 2  # 空页容忍数
SKELETON_LCS_MIN: Final = 0.6  # 骨架 LCS 覆盖率下限
HEADER_ZONE_FRAC: Final = 0.12  # 页顶 running-head 带（页高比）
HEADER_MIN_FRAC: Final = 0.5  # base 页眉覆盖率阈（低于不测）
HEADER_LOST_FRAC: Final = 0.2  # zh 页眉覆盖率低于此 → sig
POPPLER_TIMEOUT: Final = 60.0
RASTER_TIMEOUT: Final = 420.0  # 全篇渲染+逐页度量随页数线性（176p 实证）
KEEP_TIMEOUT: Final = 240.0  # 收割专道只渲标记页
KEEP_DPI: Final = "110"  # 目检 PNG 用更高分辨率（60dpi CJK 糊）
PT2BP: Final = 72.0 / 72.27  # TeX pt → PDF bp（72.27pt = 72bp = 1in）

# T1 raster（系统 python 子进程——bench .venv 无 pillow）
BLANK_INK_MAX: Final = 0.001  # ink<0.1% → 空白页
INKBLOB_CC_MIN: Final = 0.4  # 最大深连通块>40% 页 → 墨团
VOID_FRAC_MIN: Final = 0.3  # 最大空 rect>30% textblock → 空洞
RASTER_DPI: Final = "60"
_RASTER_CHILD: Final = Path(__file__).with_name("_raster_child.py")
_RASTER_PY: Final = (
    "/usr/bin/python3" if Path("/usr/bin/python3").exists() else "python3"
)

_WORD_RX: Final = re.compile(
    r"<word\s+xMin=([\d.]+)\s+yMin=([\d.]+)\s+xMax=([\d.]+)\s+yMax=([\d.]+)"
    r"[^>]*>([^<]*)</word>"
)
_OVERFULL_RX: Final = re.compile(
    r"Overfull\s+\\([hv])box\s+\(([\d.]+)pt\s+too\s+(wide|high)"
)
_FLOAT_FIT_RX: Final = re.compile(r"TeXlate-Float-Fit")
_FLOAT_LOST_RX: Final = re.compile(
    r"Float too large|LaTeX Warning:.*(?:undefined|lost)|"
    r"undefined references",
    re.IGNORECASE,
)
_ASCII_LINE_RX: Final = re.compile(r"^[A-Za-z0-9 ,.'()\[\]:;/&+-]{25,}$")
_REFS_HEAD_RX: Final = re.compile(
    r"^\s*(?:\d+\s*[.、]?\s*)?(?:references|bibliography|参考文献)\s*$",
    re.IGNORECASE,
)
_BIB_MARK_RX: Final = re.compile(r"^\s*\[(\d+)\]\s*\S")


def _refs_cut(lines: list[str]) -> int:
    """参考文献区起始行：尾部行首 ``[N]`` 稠密簇定位——从最后一个
    marker 倒序连回，相邻行距 ≤80（长条目跨行十余行、双栏交错
    打序是常态，PRX 实证最大间隔 70）。簇 ≥3 marker 且簇区 ASCII
    行占比 ≥50% 才算 bib——正文尾部密引的伪簇会被英文面占比拒掉。
    无命中返 len(lines)。"""
    marks: list[tuple[int, int]] = []
    for i, ln in enumerate(lines):
        m = _BIB_MARK_RX.match(ln)
        if m:
            marks.append((i, int(m.group(1))))
    if len(marks) < 3:
        return len(lines)
    start = len(marks) - 1
    for k in range(len(marks) - 2, -1, -1):
        if marks[k + 1][0] - marks[k][0] > 80:
            break
        start = k
    if len(marks) - start < 3:
        return len(lines)
    cut = marks[start][0]
    region = [ln.strip() for ln in lines[cut:] if ln.strip()]
    ascii_frac = sum(1 for ln in region if _ASCII_LINE_RX.match(ln)) / max(
        len(region), 1
    )
    return cut if ascii_frac >= 0.5 else len(lines)


_SKELETON_RX: Final = re.compile(
    r"\d{4}\.\d{4,5}|\[\d+(?:,\d+)*\]|\b\d+\.\d+\b|arXiv:\S+|"
    r"https?://\S+|www\.\S+"
)
#: n-gram 词 token 判定——须含字母/CJK；纯符号（散点 marker
#: ●/○）与纯数字（零矩阵/数据表天然重复，2603.07101 75×"0"实证）
#: 不算文本退化。
_WORD_CHAR_RX: Final = re.compile(r"[A-Za-z一-鿿]")
#: 行内短周期连珠——「这是译文这是译文…」式占位/mock 译文：
#: 2-12 字符子串行内 ≥4 连（CJK 无空格整行一个 token，词级
#: n-gram 对它失明——2609.19244 实证 top_rep=46 < 195 页放阈
#: 但满页皆是占位符）。「…………」类无词字符单元不算。
_PERIODIC_RX: Final = re.compile(r"(\S{2,12}?)\1{3,}")
#: 断链引用位点——``?{2,}`` 每 run 计一位（``????`` 多键 cite 仍算
#: 一位）；括/方号内单 ``?`` 亦计（natbib 断链渲成 ``(?)``/``[?]``，
#: 2602.09703 满页实证）；零散修辞双问号由 ≥8 位点阈豁免。
_BROKEN_REF_RX: Final = re.compile(r"[(\[]\?+[)\]]|\?{2,}")
BROKEN_REFS_MIN: Final = 8


def _run(
    argv: list[str], cwd: Path | None = None, *, timeout: float = POPPLER_TIMEOUT
) -> str:
    """poppler 子进程包——超时/缺席一律空串（调用方按缺席降级）。"""
    try:
        r = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout or ""


# ---------------------------------------------------------------- 检查件


def _logscan(log_text: str) -> tuple[list[dict], dict]:
    """编译日志信号：overfull 计数+峰值、Float-Fit typeout、浮体丢失。"""
    findings: list[dict] = []
    ov = [(m.group(1), float(m.group(2))) for m in _OVERFULL_RX.finditer(log_text)]
    fit = len(_FLOAT_FIT_RX.findall(log_text))
    lost = len(_FLOAT_LOST_RX.findall(log_text))
    metrics = {
        "overfull_n": len(ov),
        "overfull_max_pt": max((p for _, p in ov), default=0.0),
        "overfull_vbox_n": sum(1 for k, _ in ov if k == "v"),
        "float_fit_typeout": fit,
        "float_lost_warn": lost,
    }
    if len(ov) > OVERFULL_COUNT or metrics["overfull_max_pt"] > OVERFULL_MAX_PT:
        findings.append(
            {
                "sig": "layout:overfull",
                "n": len(ov),
                "max_pt": metrics["overfull_max_pt"],
                "vbox_n": metrics["overfull_vbox_n"],
            }
        )
    if fit:
        findings.append({"sig": "layout:float_fit", "n": fit})
    if lost:
        findings.append({"sig": "layout:float_lost", "n": lost})
    return findings, metrics


def _marks_scan(
    zh_txlm: Path | None,
    base_txlm: Path | None,
    splice_dir: Path | None,
    src_dir: Path | None,
    zh_pages: int | None = None,
    base_pages: int | None = None,
) -> tuple[list[dict], dict]:
    """marks 查表层：跨臂对照 + 单侧 offpage + 双层覆盖记账。

    - ``marks_coverage``：splice 树（实际编译面）有受钩 env 但零 MARK →
      注入/钩子层洞（demote 改名已在此面消化，不误报）。
    - ``dropped_env``：src 树有、splice 树无的 env —— splice/fixloop
      删元素的 never-silent 记账（BabelDOC #615 规则）。
    """
    findings: list[dict] = []
    metrics: dict = {}
    if zh_txlm is None or not zh_txlm.exists():
        return [{"sig": "layout:marks_absent", "side": "zh"}], metrics
    zh = parse_txlm(zh_txlm)
    metrics["zh_marks"] = len(zh["marks"])
    metrics["geom"] = zh["geom"]
    if not zh["marks"]:
        findings.append(
            {"sig": "layout:marks_absent", "side": "zh", "lines": zh["lines"]}
        )
        return findings, metrics
    base = None
    if base_txlm is not None and base_txlm.exists():
        base = parse_txlm(base_txlm)
        metrics["base_marks"] = len(base["marks"])
        if not base["marks"]:
            base = None
    if base is None:
        findings.append({"sig": "layout:marks_absent", "side": "base"})
    # 声明序主键：zh 侧读 splice 树（编译面），base 侧读 src 树
    # （en 原面——build-base 同构）→ demote 改名/缺 b-mark 皆免疫
    zh_decl = (
        env_sequence(splice_dir)
        if splice_dir is not None and splice_dir.is_dir()
        else None
    )
    base_decl = (
        env_sequence(src_dir) if src_dir is not None and src_dir.is_dir() else None
    )
    findings.extend(
        compare_marks(
            zh,
            base,
            zh_decl=zh_decl,
            base_decl=base_decl,
            zh_pages=zh_pages,
            base_pages=base_pages,
        )
    )
    emitted = Counter(v["uid"].rsplit("-", 2)[0] for v in zh["marks"].values())
    if splice_dir is not None and splice_dir.is_dir():
        sinv = env_inventory(splice_dir)
        gaps = {
            e: n for e, n in sinv.items() if e in _MARK_ENVS and emitted.get(e, 0) == 0
        }
        metrics["splice_inventory"] = sinv
        if gaps:
            findings.append({"sig": "layout:marks_coverage", "envs": gaps})
        if src_dir is not None and src_dir.is_dir():
            sinv_src = env_inventory(src_dir)
            dropped = {
                e: n
                for e, n in sinv_src.items()
                if e in _MARK_ENVS and sinv.get(e, 0) == 0
            }
            # demote_wrapfloats 的合法改名：wrap* 消失但目标 env 计数
            # 等量增长 → 改名非丢弃（wrapfloat{T}→T 同样覆盖）
            _demote_tgt = {
                "wrapfigure": "figure",
                "wrapfigure*": "figure*",
                "wraptable": "table",
                "wraptable*": "table*",
            }
            for e in list(dropped):
                tgt = _demote_tgt.get(e)
                if e == "wrapfloat":
                    tgts = ("figure", "figure*", "table", "table*")
                elif tgt:
                    tgts = (tgt,)
                else:
                    continue
                gain = sum(sinv.get(t, 0) - sinv_src.get(t, 0) for t in tgts)
                if gain >= dropped[e]:
                    del dropped[e]
            if dropped:
                findings.append({"sig": "layout:dropped_env", "envs": dropped})
    return findings, metrics


def _bbox_pages(pdf: Path) -> list[dict]:
    """``pdftotext -bbox`` → [{w,h,words:[(x0,y0,x1,y1,text)]}]（pt 轴、
    原点左上）。"""
    xml = _run(["pdftotext", "-bbox", pdf.name, "-"], cwd=pdf.parent)
    if not xml:
        return []
    pages: list[dict] = []
    cur: dict | None = None
    for m in re.finditer(
        r'<page\s+width="([\d.]+)"\s+height="([\d.]+)"|'
        r'<word\s+xMin="([\d.]+)"\s+yMin="([\d.]+)"\s+xMax="([\d.]+)"\s+'
        r'yMax="([\d.]+)"[^>]*>([^<]*)</word>|</page>',
        xml,
    ):
        if m.group(1) is not None:
            cur = {"w": float(m.group(1)), "h": float(m.group(2)), "words": []}
            pages.append(cur)
        elif m.group(3) is not None and cur is not None:
            cur["words"].append(
                (
                    float(m.group(3)),
                    float(m.group(4)),
                    float(m.group(5)),
                    float(m.group(6)),
                    m.group(7),
                )
            )
        else:
            cur = None
    return pages


def _textblock(geom: dict, page_w: float, page_h: float) -> tuple:
    """GEOM → textblock 矩形（bp，原点左上，与 pdftotext 同系）。
    GEOM 各量单位 TeX pt（72.27/in），mediabox 单位 bp（72/in）——
    letter 两侧分别是 614.295pt / 612bp，不换算会伪报纸型失配。
    GEOM 缺席或纸型真失配（本身即是缺陷信号，marks 坐标轴同受害）
    退 92% 页框。"""
    keys = ("pw", "ph", "tw", "th", "tm", "hh", "hs", "ho", "vo", "oi")
    if (
        geom
        and all(k in geom for k in keys)
        and abs(geom["pw"] * PT2BP - page_w) < 2.0
        and abs(geom["ph"] * PT2BP - page_h) < 2.0
    ):
        left = (72.27 + geom["ho"] + geom["oi"]) * PT2BP
        top = (72.27 + geom["vo"] + geom["tm"] + geom["hh"] + geom["hs"]) * PT2BP
        return left, top, left + geom["tw"] * PT2BP, top + geom["th"] * PT2BP
    m = 0.04
    return page_w * m, page_h * m, page_w * (1 - m), page_h * (1 - m)


def _word_overlap_pairs(words: list[tuple]) -> int:
    """跨行词重叠对数——同行相邻词天然贴近不算，只数「y 中心差 > 半词高
    且 bbox IoU > 阈」对（#615 重叠对法）。扫线法 O(n log n + k)。"""
    ws = sorted(words, key=lambda w: (w[1] + w[3]) / 2)
    n = 0
    for i, a in enumerate(ws):
        acy = (a[1] + a[3]) / 2
        ah = max(a[3] - a[1], 1e-6)
        for b in ws[i + 1 :]:
            bcy = (b[1] + b[3]) / 2
            if bcy - acy > max(ah, b[3] - b[1]) * 2:
                break  # y 序扫出窗
            if abs(bcy - acy) < ah * 0.5:
                continue  # 同行
            ix = min(a[2], b[2]) - max(a[0], b[0])
            iy = min(a[3], b[3]) - max(a[1], b[1])
            if ix <= 0 or iy <= 0:
                continue
            inter = ix * iy
            small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
            if small > 0 and inter / small > OVERLAP_IOU:
                n += 1
    return n


#: 全角标点占位符——glyph bbox 按全 em 计、墨迹只占一半，行末标点
#: 会让 xMax 虚超 textblock ~0.5em（2608.25736 实证 2.8–6.4pt 伪越界
#: 全挂在 ，。：（ 尾上）。真溢出按真实 box 计不受影响。
_CJK_PUNCT_R: Final = "，。、；：？！）】」』》〉”’…—·"
_CJK_PUNCT_L: Final = "（【「『《〈“‘"


def _page_word_stats(pg: dict, geom: dict) -> tuple[int, int]:
    """单页 (越界词数, 跨行重叠对数)——跨臂按页对拍的最小单位。
    越界只数正文带内词：running head / 页码等页眉页脚家具本就骑在
    textblock 之外（2608.25736 p7 实证——页眉行触发全页 breach），
    cy < t 或 cy > b+20 的词不算。"""
    left, t, r, b = _textblock(geom, pg["w"], pg["h"])
    tol = MARGIN_BREACH_PT
    words = pg["words"]
    nb = 0
    for x0, y0, x1, y1, wtext in words:
        cy = (y0 + y1) / 2
        if not (t - 2 <= cy <= b + 20.0):
            continue
        h = max(y1 - y0, 1e-6)
        bx0 = x0 + (h * 0.6 if wtext[:1] in _CJK_PUNCT_L else 0.0)
        bx1 = x1 - (h * 0.6 if wtext[-1:] in _CJK_PUNCT_R else 0.0)
        if bx0 < left - tol or bx1 > r + tol or y1 > b + tol:
            nb += 1
    return nb, _word_overlap_pairs(words)


def _bbox_scan(
    pages: list[dict], geom: dict, images_per_page: dict[int, int]
) -> tuple[list[dict], dict]:
    """word-bbox 层：越界/重叠/浮体挤页/页眉丢失（页眉判读在
    cross-arm 段——此处只产 per-page 度量）。"""
    findings: list[dict] = []
    metrics: dict = {"pages": len(pages)}
    # 纸型失配：GEOM pw/ph（\paperwidth，TeX pt）vs PDF mediabox（bp）
    # ——marks 轴与渲染轴分裂的独立信号（probe 实证 letterpaper 声明
    # → A4 输出）。比对前先 pt→bp 换算。
    if (
        pages
        and geom.get("pw")
        and geom.get("ph")
        and (
            abs(geom["pw"] * PT2BP - pages[0]["w"]) >= 2.0
            or abs(geom["ph"] * PT2BP - pages[0]["h"]) >= 2.0
        )
    ):
        findings.append(
            {
                "sig": "layout:paper_mismatch",
                "geom": [geom["pw"], geom["ph"]],
                "pdf": [pages[0]["w"], pages[0]["h"]],
            }
        )
    breach_n = overlap_n = 0
    word_counts: list[int] = []
    head_hits = 0
    breach_by_page: list[int] = []
    overlap_by_page: list[int] = []
    for pi, pg in enumerate(pages):
        words = pg["words"]
        word_counts.append(len(words))
        nb, op = _page_word_stats(pg, geom)
        breach_by_page.append(nb)
        overlap_by_page.append(op)
        if nb >= MARGIN_BREACH_MIN:
            breach_n += nb
            findings.append({"sig": "geo_margin_breach", "page": pi + 1, "words": nb})
        if op >= OVERLAP_MIN_PAIRS:
            overlap_n += op
            findings.append({"sig": "geo_text_overlap", "page": pi + 1, "pairs": op})
        if (
            pi >= 1
            and pg["h"]
            and any(
                (y0 + y1) / 2 < pg["h"] * HEADER_ZONE_FRAC
                for x0, y0, x1, y1, _ in words
            )
        ):
            head_hits += 1
    metrics["margin_breach_words"] = breach_n
    metrics["overlap_pairs"] = overlap_n
    metrics["breach_by_page"] = breach_by_page
    metrics["overlap_by_page"] = overlap_by_page
    metrics["header_pages"] = head_hits
    metrics["word_counts"] = word_counts
    return findings, metrics


def _plain_scan(text: str) -> tuple[list[dict], dict]:
    """pdftotext 纯文本层：退化兜底（olmOCR 系）+ 残留英文。"""
    findings: list[dict] = []
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()  # pdftotext 末页 \f 尾巴
    metrics: dict = {"chars": len(text), "npages_text": len(pages)}
    # 残留英文行：参考文献段本就保持英文——标题行起截断不计，只量
    # 正文域（无标题匹配 = 保守全计）。
    lines = text.splitlines()
    head_cut = next(
        (i for i, ln in enumerate(lines) if _REFS_HEAD_RX.match(ln)), len(lines)
    )
    cut = min(head_cut, _refs_cut(lines))
    body = lines[:cut]
    en_lines = [
        ln.strip()
        for ln in body
        if _ASCII_LINE_RX.match(ln.strip()) and len(ln.strip().split()) >= 4
    ]
    text_lines = [ln for ln in body if ln.strip()]
    metrics["en_tail_cut"] = cut if cut < len(lines) else None
    metrics["residual_en_lines"] = len(en_lines)
    frac = len(en_lines) / max(len(text_lines), 1)
    if len(en_lines) >= RESIDUAL_EN_MASS_LINES or (
        len(en_lines) >= RESIDUAL_EN_MIN_LINES and frac >= RESIDUAL_EN_MIN_FRAC
    ):
        findings.append(
            {"sig": "xlat_residual_en", "lines": len(en_lines), "frac": round(frac, 3)}
        )
    # 退化：FFFD / 重复 n-gram / 空页
    fffd = text.count("\ufffd")
    # n-gram 同吃 refs 截断（ACM 版权块逐条参考文献重复是合法面）；
    # 非字母 token 剔除——矢量图散点 marker（1706.02386 298×●）、
    # 零矩阵/数据表数字连珠（2603.07101 75×"0"）都不是文本退化。
    toks = [t for t in " ".join(body).split() if _WORD_CHAR_RX.search(t)]
    ngrams = Counter(
        tuple(toks[i : i + DEGEN_NGRAM]) for i in range(len(toks) - DEGEN_NGRAM + 1)
    )
    top_rep = max(ngrams.values(), default=0)
    empty = sum(1 for p in pages if len(p.strip()) < EMPTY_PAGE_CHARS)
    # 行内周期占位行数——CJK mock 译文整行无空格，词级 n-gram
    # 只反映局部重复（running head 放阈连它一起放走）；行内
    # 连珠才是真占位签名——页眉每页复现也不产生行内连珠。
    periodic = sum(
        1
        for ln in body
        if any(_WORD_CHAR_RX.search(m.group(1)) for m in _PERIODIC_RX.finditer(ln))
    )
    metrics.update(
        {
            "fffd": fffd,
            "top_ngram_rep": top_rep,
            "empty_pages": empty,
            "degen_periodic_lines": periodic,
        }
    )
    # running head 每页复现标题 ≈ npages 次；真退化环单页就产出
    # 数百次——阈值按页数放。
    ngram_cap = max(3 * len(pages), DEGEN_NGRAM_MAX)
    if (
        fffd
        or top_rep > ngram_cap
        or empty > EMPTY_PAGE_MAX
        or periodic >= DEGEN_PERIODIC_MIN_LINES
    ):
        findings.append(
            {
                "sig": "vis_degenerate",
                "fffd": fffd,
                "top_ngram_rep": top_rep,
                "empty_pages": empty,
                "periodic_lines": periodic,
            }
        )
    # 断链引用：未解析 \cite/\ref 渲成 ?? run——编译 pass 不全的
    # 产物级签名（2505.21476 正文 646 个 ?? 字符实证）；中文全角
    # ？？天然不匹配，修辞性 ??/??? 够不到位点阈。
    broken = len(_BROKEN_REF_RX.findall(text))
    metrics["broken_refs"] = broken
    if broken >= BROKEN_REFS_MIN:
        findings.append({"sig": "xlat_broken_refs", "n": broken})
    return findings, metrics


def _skeleton(text: str) -> list[str]:
    """翻不动的骨架 token 流（数字/引用/arXiv/URL）——页序对拍用。"""
    return _SKELETON_RX.findall(text)


def _lcs(a: list[str], b: list[str]) -> int:
    """经典 LCS 长度（骨架流 ≤ 数千，O(nm) 可接受）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[-1]))
        prev = cur
    return prev[-1]


def _images_per_page(pdf: Path) -> dict[int, int]:
    """``pdfimages -list`` → {page: n_images}（免抽取锚点近似）。"""
    out = _run(["pdfimages", "-list", pdf.name], cwd=pdf.parent)
    per: dict[int, int] = {}
    for ln in out.splitlines():
        m = re.match(r"\s*(\d+)\s+\d+\s+image\s", ln)
        if m:
            per[int(m.group(1))] = per.get(int(m.group(1)), 0) + 1
    return per


def _tier_of(findings: list[dict], *, marks_era: bool = False) -> str:
    """findings → ``clean|warn|hard``（§11.1 三档）。

    ``marks_era``=双臂注入编译语境时 ``marks_absent`` 升 WARN
    （注入缺席=仪表链断）；存量无注入期胞格它是 INFO 恒发。
    未分类新 sig 保守按 WARN——硬档须显式进 _HARD_SIGS。
    """
    tier = 0
    for f in findings:
        sig = f.get("sig", "")
        if sig in _HARD_SIGS:
            return "hard"
        if sig == "layout:marks_absent":
            if marks_era:
                tier = 1
            continue
        if sig in _INFO_SIGS:
            continue
        tier = max(tier, 1)
    return ("clean", "warn", "hard")[tier]


def _raster_pages(
    pdf: Path, *, keep_dir: Path | None = None, keep_pages: list[int] | None = None
) -> dict:
    """T1 子进程调用 → {pages:[…]} 或 {error:…}（pillow 缺席静默降级）。

    keep_dir+keep_pages 时走收割专道：只渲标记页 PNG 复制进
    keep_dir（§11.2 flagged_pages 目检素材，不产出度量）。
    """
    if not _RASTER_CHILD.exists():
        return {"error": "child_missing"}
    harvest = keep_dir is not None and bool(keep_pages)
    argv = [
        _RASTER_PY,
        str(_RASTER_CHILD),
        pdf.name,
        KEEP_DPI if harvest else RASTER_DPI,
    ]
    if harvest:
        argv.append(f"keep:{keep_dir}:{','.join(str(p) for p in keep_pages)}")
    out = _run(
        argv, cwd=pdf.parent, timeout=KEEP_TIMEOUT if harvest else RASTER_TIMEOUT
    )
    try:
        return json.loads(out) if out else {"error": "empty"}
    except ValueError:
        return {"error": "bad_json"}


def _raster_scan(
    zh_pages: list[dict],
    base_pages: list[dict] | None,
    zh_images: dict[int, int] | None = None,
) -> tuple[list[dict], dict]:
    """raster 检查：空白/墨团/空洞/tofu（zh 单侧）+ 栏数/规则
    对拍（跨臂）。

    ``zh_images`` = _images_per_page 页→嵌入位图数——含位图页跳过
    ink_blob（星系格/照片类深色位图天然产出巨大 dark CC，与
    text_as_curves 同一豁免族：位图页的大墨块是内容不是泼溅）。
    """
    findings: list[dict] = []
    metrics: dict = {"raster_pages": len(zh_pages)}
    blank = blob = void = 0
    tofu_pages: list[int] = []
    for i, pg in enumerate(zh_pages):
        if pg["ink"] < BLANK_INK_MAX:
            blank += 1
            findings.append({"sig": "vis_blank_page", "page": i + 1})
        if pg["dark_cc"] > INKBLOB_CC_MIN and not (zh_images or {}).get(i + 1, 0):
            blob += 1
            findings.append({"sig": "vis_ink_blob", "page": i + 1, "cc": pg["dark_cc"]})
        # 内部洞（四周皆有墨）才是真掉图窟窿；贴边留白是结构性
        # （目录收尾/末页早收/栏尾空行，2605.25645 p3 实证）
        if (
            i < len(zh_pages) - 1
            and pg.get("void_int", pg["void_frac"]) > VOID_FRAC_MIN
        ):
            void += 1
            findings.append(
                {
                    "sig": "vis_void",
                    "page": i + 1,
                    "frac": pg.get("void_int", pg["void_frac"]),
                }
            )
        if pg.get("tofu", 0) >= TOFU_MIN_PAGE:
            tofu_pages.append(i + 1)
    if tofu_pages:
        findings.append({"sig": "vis_tofu_box", "pages": tofu_pages})
    metrics.update(
        {
            "blank": blank,
            "ink_blob": blob,
            "void": void,
            "tofu_pages": tofu_pages,
            "rules_zh": sum(p.get("rules", 0) for p in zh_pages),
        }
    )
    if base_pages:
        metrics["rules_base"] = sum(p.get("rules", 0) for p in base_pages)
        # 规则丢失：zh 比 base 少 ≥40% 且 base 有 ≥3 条——tabular 网格
        # 被 splice 破坏（规则线消失）的代理信号；图内轴线两臂同构
        # 天然对消。BIoU/cell 级错位仍属 T2。
        if (
            metrics["rules_base"] >= 3
            and metrics["rules_zh"] < metrics["rules_base"] * TABLE_RULE_LOST
        ):
            findings.append(
                {
                    "sig": "geo_table_lost",
                    "zh": metrics["rules_zh"],
                    "base": metrics["rules_base"],
                }
            )
        # 栏数按文档众数对拍——逐页 i 对拍在 zh/base 页数不齐时纯属
        # 错位噪声（2512.01407 实证 42p vs 44p 假 collapse）；要抓的
        # 缺陷类是「双栏模板渲成单栏」的全局坍缩。
        zh_mode = Counter(p["cols"] for p in zh_pages if p.get("cols") is not None)
        base_mode = Counter(p["cols"] for p in base_pages if p.get("cols") is not None)
        if zh_mode and base_mode:
            zm, bm = zh_mode.most_common(1)[0][0], base_mode.most_common(1)[0][0]
            metrics["col_mode"] = {"zh": zm, "base": bm}
            if zm != bm:
                findings.append(
                    {"sig": "geo_column_collapse", "zh_mode": zm, "base_mode": bm}
                )
        ink_ratio = sum(p["ink"] for p in zh_pages) / max(
            sum(p["ink"] for p in base_pages), 1e-9
        )
        metrics["ink_ratio"] = round(ink_ratio, 3)
        # 逐页墨量回归：矢量图（tikz/pgfplots）掉图不进 pdfimages
        # 计数——image 对拍盲区的补位面。zh 页墨量崩到 base 邻窗
        # 峰值 35% 以下且 base 邻窗确有内容（>8%）即报。末页豁免
        # （收尾留白合法），blank 检出页已由 vis_blank_page 认领。
        ink_drops = []
        for i, pg in enumerate(zh_pages[:-1]):
            if pg["ink"] < BLANK_INK_MAX:
                continue
            lo = max(0, i - 2)
            hi = min(len(base_pages), i + 3)
            bw = max((base_pages[j]["ink"] for j in range(lo, hi)), default=0)
            if bw > 0.08 and pg["ink"] < bw * INK_DROP_RATIO:
                ink_drops.append(i + 1)
        if ink_drops:
            findings.append({"sig": "regress_ink_profile", "pages": ink_drops})
            metrics["ink_drop_pages"] = ink_drops
    return findings, metrics


# ---------------------------------------------------------------- 总装


def qc_paper(
    *,
    splice_dir: Path,
    main_rel: str,
    base_dir: Path | None = None,
    src_dir: Path | None = None,
    marks_era: bool = False,
    flag_dir: Path | None = None,
) -> dict:
    """一篇的 T0 全检。返回 ``{findings, metrics, qc_tier,
    sig_counts, flagged_pages}``——stage 侧直接消化。

    splice_dir/main_rel 定位 zh 产物；base_dir 缺席→跨臂项全降级为
    单侧（marks_absent/page_count/skeleton 只记 zh 侧度量）。
    ``marks_era``=双臂注入编译语境（marks_absent 升 WARN）；
    ``flag_dir`` 非空且 tier≥warn 时把标记页 PNG 收割进该目录
    （§11.2 分诊素材契约）。
    """
    findings: list[dict] = []
    metrics: dict = {}
    mp = Path(main_rel)
    zh_dir = splice_dir / mp.parent
    stem = mp.stem
    zh_pdf = zh_dir / f"{stem}.pdf"
    zh_log = zh_dir / f"{stem}.log"
    zh_txlm = zh_dir / f"{stem}.txlm"

    log_text = ""
    try:
        if zh_log.exists():
            log_text = zh_log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    f, m = _logscan(log_text)
    findings += f
    metrics["log"] = m

    btx = None
    base_pdf = None
    if base_dir is not None:
        bdir = base_dir / mp.parent
        btx = bdir / f"{stem}.txlm"
        base_pdf = bdir / f"{stem}.pdf"
    zh_geom = parse_txlm(zh_txlm)["geom"] if zh_txlm.exists() else {}

    if zh_pdf.exists():
        zh_text = _run(["pdftotext", zh_pdf.name, "-"], cwd=zh_pdf.parent)
        f, m = _plain_scan(zh_text)
        findings += f
        metrics["text"] = m
        zh_images = _images_per_page(zh_pdf)
        pages = _bbox_pages(zh_pdf)
        f, m = _bbox_scan(pages, zh_geom, zh_images)
        findings += f
        metrics["bbox"] = m
        if base_pdf is not None and base_pdf.exists():
            base_text = _run(["pdftotext", base_pdf.name, "-"], cwd=base_pdf.parent)
            base_pages = base_text.split("\f")
            if base_pages and not base_pages[-1].strip():
                base_pages.pop()
            metrics["base_pages"] = len(base_pages)
            # 页数漂移
            zh_np = metrics["text"].get("npages_text") or 0
            bp = len(base_pages)
            if bp:
                ratio = zh_np / bp
                metrics["page_ratio"] = round(ratio, 3)
                if not PAGE_RATIO_LO <= ratio <= PAGE_RATIO_HI:
                    findings.append(
                        {
                            "sig": "align_page_count",
                            "zh": zh_np,
                            "base": bp,
                            "ratio": round(ratio, 3),
                        }
                    )
            # 骨架序对拍
            zs, bs = _skeleton(zh_text), _skeleton(base_text)
            cov = _lcs(zs, bs) / max(len(bs), 1)
            metrics["skeleton_lcs"] = round(cov, 3)
            if bs and cov < SKELETON_LCS_MIN:
                findings.append(
                    {
                        "sig": "align_order_break",
                        "lcs_cov": round(cov, 3),
                        "zh_skel": len(zs),
                        "base_skel": len(bs),
                    }
                )
            # 丢图：image count 对拍
            base_images = _images_per_page(base_pdf)
            zh_imgs = sum(zh_images.values())
            base_imgs = sum(base_images.values())
            metrics["zh_images"] = zh_imgs
            metrics["base_images"] = base_imgs
            if base_imgs and zh_imgs < base_imgs:
                findings.append(
                    {"sig": "align_figure_lost", "zh": zh_imgs, "base": base_imgs}
                )
            # 页眉丢失：base 过半页有页眉而 zh 低于阈
            base_bbox = _bbox_pages(base_pdf)
            base_head = sum(
                1
                for pg in base_bbox[1:]
                if pg["h"]
                and any(
                    (y0 + y1) / 2 < pg["h"] * HEADER_ZONE_FRAC
                    for x0, y0, x1, y1, _ in pg["words"]
                )
            )
            zh_head = metrics["bbox"].get("header_pages", 0)
            bfrac = base_head / max(len(base_bbox) - 1, 1)
            zfrac = zh_head / max(len(pages) - 1, 1)
            metrics["header_frac"] = {"base": round(bfrac, 3), "zh": round(zfrac, 3)}
            if bfrac >= HEADER_MIN_FRAC and zfrac < HEADER_LOST_FRAC:
                findings.append(
                    {
                        "sig": "geo_header_lost",
                        "base_frac": round(bfrac, 3),
                        "zh_frac": round(zfrac, 3),
                    }
                )
            # 越界/重叠跨臂抑制：矢量图内部标注文字两臂同构（2609.20519
            # 实证 1805 对全在 figure 内、base 侧同数），zh ≤ base×1.5+3
            # 视为底噪不升级——只报 zh 新引入的版面碰撞。
            base_geom = (
                parse_txlm(btx)["geom"] if btx is not None and btx.exists() else {}
            )
            base_stats = [_page_word_stats(pg, base_geom) for pg in base_bbox]
            kept: list[dict] = []
            suppressed = 0
            for f_ in findings:
                sig_, pg_ = f_.get("sig"), f_.get("page")
                if (
                    sig_ in ("geo_margin_breach", "geo_text_overlap")
                    and isinstance(pg_, int)
                    and 1 <= pg_ <= len(base_stats)
                ):
                    bn, bo = base_stats[pg_ - 1]
                    bval, zval = (
                        (bn, f_["words"])
                        if sig_ == "geo_margin_breach"
                        else (bo, f_["pairs"])
                    )
                    if zval <= max(bval * 1.5, bval + 3):
                        suppressed += 1
                        continue
                kept.append(f_)
            findings[:] = kept
            metrics["base_word_stats"] = {
                "breach_by_page": [n for n, _ in base_stats],
                "overlap_by_page": [o for _, o in base_stats],
                "suppressed": suppressed,
            }
            # 公式漂移：marks 数学 env 对拍（无 marks 时用文本侧
            # 行级近似已并入 skeleton；此处只认 marks 口径）
            if btx is not None and btx.exists() and zh_txlm.exists():
                zm = parse_txlm(zh_txlm)["marks"]
                bm = parse_txlm(btx)["marks"]
                maths = ("equation", "align", "gather", "multline", "eqnarray")
                zc = sum(
                    1
                    for v in zm.values()
                    if v["uid"].rsplit("-", 2)[0].rstrip("*") in maths
                    and v["uid"].endswith("-e")
                )
                bc = sum(
                    1
                    for v in bm.values()
                    if v["uid"].rsplit("-", 2)[0].rstrip("*") in maths
                    and v["uid"].endswith("-e")
                )
                metrics["math_envs"] = {"zh": zc, "base": bc}
                if bc and zc < bc:
                    findings.append({"sig": "align_math_drift", "zh": zc, "base": bc})
        # T1 raster：zh 单侧 + base 栏数对拍（pillow 子进程缺席时降级）
        rz = _raster_pages(zh_pdf)
        if rz.get("pages"):
            rb = (
                _raster_pages(base_pdf)
                if base_pdf is not None and base_pdf.exists()
                else {}
            )
            f, m = _raster_scan(rz["pages"], rb.get("pages"), zh_images)
            findings += f
            metrics["raster"] = m
            # 曲线化文本页：有墨（非空页）+ 几乎零可提取词 + 无位图
            # 对象 → 文字被渲成曲线/路径（不可复制检索，olmOCR/babeldoc
            # 族已知缺陷类）。位图图版页被 images>0 排除；带页码的空页
            # ink 极低自然不过阈。矢量图不可提取文本页仍会过——罕见，
            # 留人工分诊。
            wcs = metrics["bbox"].get("word_counts", [])
            curves = [
                i + 1
                for i, pg in enumerate(rz["pages"])
                if pg["ink"] > CURVES_INK_MIN
                and i < len(wcs)
                and wcs[i] < 3
                and zh_images.get(i + 1, 0) == 0
            ]
            if curves:
                findings.append({"sig": "geo_text_as_curves", "pages": curves})
                metrics["raster"]["curves_pages"] = curves
        elif rz.get("error") and rz["error"] != "no_pillow":
            metrics["raster_error"] = rz["error"]
            # poppler 渲染级失败 = 文件体损坏（坏 xref/断 stream，
            # 2404.14219 实证）——区别于 "empty"（父侧超时）与
            # pdftoppm:<exc>（子进程内渲染超时），按 HARD sig 立档。
            if str(rz["error"]).startswith("pdftoppm_rc"):
                findings.append({"sig": "layout:pdf_corrupt", "err": rz["error"]})
    else:
        findings.append({"sig": "layout:no_pdf"})

    # marks 查表殿后——页数比外推期望落点需要 npages 已入账
    f, m = _marks_scan(
        zh_txlm,
        btx,
        splice_dir,
        src_dir,
        zh_pages=metrics.get("text", {}).get("npages_text"),
        base_pages=metrics.get("base_pages"),
    )
    findings += f
    metrics["marks"] = m
    # §11.2 契约键：tier/flagged/sig_counts——保留扫描器与分诊
    # 直接消费；tier≥warn 时标记页 PNG 收割（目检素材随 QC 报告走）。
    sig_counts = Counter(f_["sig"] for f_ in findings)
    flagged = sorted(
        {
            p
            for f_ in findings
            for p in (
                [f_["page"]]
                if isinstance(f_.get("page"), int)
                else f_.get("pages") or []
            )
        }
    )
    tier = _tier_of(findings, marks_era=marks_era)
    if flag_dir is not None and tier != "clean" and flagged and zh_pdf.exists():
        _raster_pages(zh_pdf, keep_dir=flag_dir, keep_pages=flagged)
    return {
        "findings": findings,
        "metrics": metrics,
        "qc_tier": tier,
        "sig_counts": dict(sig_counts),
        "flagged_pages": flagged,
    }
