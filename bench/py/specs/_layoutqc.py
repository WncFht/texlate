r"""T0 版面质检电池（layoutqc stage 的检测本体）。

输入全是现成产物：splice 树的 ``<stem>.pdf/.log/.txlm``、build-base 树
的同三件套、src 源树（env_inventory 期望面）。零 LLM、零重编——词面
pymupdf 优先（clip-aware，缺席退 pdftotext -bbox）+ poppler 子进程
（pdfimages -list）+ 日志正则 + marks 查表。

每个 check 返 findings（``{sig, …}`` 逐条）+ metrics 计数；汇总成
``{findings, metrics}`` 由 stage 挂 verdict/sig/errors。设计口径见
docs/dev/layoutqc.md §4 T0 表。

阈值集中本文件顶部——校准集（§7.4）出来前全是先验值，sig 即分桶键，
阈值漂移只改一处。
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
from collections import Counter
from contextlib import suppress
from pathlib import Path
from typing import Final

from texlate.compile.marks import (
    _MARK_ENVS,
    compare_marks,
    env_inventory,
    env_sequence,
    parse_txlm,
)
from texlate.textutil import VERBATIM_ENVS, _keep_verbatim_run

# ---------------------------------------------------------------- 阈值（先验）

OVERFULL_MAX_PT: Final = 50.0  # 单处 overfull 超此 pt 数 → sig
OVERFULL_COUNT: Final = 10  # overfull 去重后条数超此 → sig（须伴峰值闸）
#: overfull 计数臂的下限峰值——逐页同值 running-head/vbox 亚像素
#: 溢出可凑满计数却零视觉伤，计数触发还须见到 ≥20pt 的真溢出。
OVERFULL_COUNT_MIN_PT: Final = 20.0
#: vbox overfull 亚像素地板——EAJ/snjnl 模板的 textheight×baselineskip
#: 固有 1.58pt 逐页高发，<2pt 的视觉不可见溢出整丢。
OVERFULL_VBOX_FLOOR_PT: Final = 2.0
MARGIN_BREACH_PT: Final = 4.0  # word bbox 出 textblock 容差
MARGIN_BREACH_MIN: Final = 3  # 越界词数下限（抗下标噪）
OVERLAP_IOU: Final = 0.3  # 跨行 word IoU 阈（BabelDOC #615 法）
OVERLAP_MIN_PAIRS: Final = 3  # 重叠词对下限
#: bbox 相擦带——IoU∈[0.30,0.45) 且纵向重叠 <2.5pt（或小盒高 20%）
#: 的「擦边」对视为 bbox 相擦非墨触（0812.1246/1012.1161 实证）。
OVERLAP_GRAZE_HI: Final = 0.45
OVERLAP_GRAZE_IY: Final = 2.5
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
#: zh 内部离群闸——掉图页墨量还须 < 全 zh 页中位数 ×此值（自身
#: 文档内也是离群低点才算掉内容；重排错位的「比 base 稀但非离群」
#: 页不报）。
INK_SELF_OUTLIER: Final = 0.25

#: 门三档（docs/dev/layoutqc.md §11.1）——HARD 挡 done 留全档、
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
        "xlat_residual_en_heavy",
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
    {
        "layout:float_fit",
        "layout:marks_absent",
        # 深带但仍在页内的越界（folio 家具/源置几何/回退框误伤）——
        # 真离页词仍走 geo_margin_breach（WARN）
        "geo_deep_band",
        # 孤行溢出页（bib/段尾寡行+folio）——非内容洞，记账不挡
        "vis_widow_page",
        # \maketitle/titlepage 测量盒的整版过宽（cms-tdr banner 实证）
        "layout:overfull_titlepage",
    }
)  # 曲线化文本页墨量阈（页码空页<此）
PAGE_RATIO_LO: Final = 0.6  # zh/base 页数比合法带
PAGE_RATIO_HI: Final = 1.6
RESIDUAL_EN_MIN_LINES: Final = 25  # 残留英文行数阈（AND frac）
RESIDUAL_EN_MIN_FRAC: Final = 0.02  # 且占全部文本行比
RESIDUAL_EN_MASS_LINES: Final = 60  # 绝对质量逃逸臂（长文低占比也报）
RESIDUAL_EN_FURNITURE: Final = 4  # 归一后正文域复现 ≥N 次的行=页眉家具剔除
RESIDUAL_EN_HEAVY_FRAC: Final = 0.15  # frac ≥ 此 → xlat_residual_en_heavy
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
#: 寡行页墨量上限——孤行溢出（bib 末行/段尾词）墨量介于空白地板
#: 与真内容页（≥3%）之间，先验取 1% 待 §7.4 校准。
WIDOW_INK_MAX: Final = 0.01
INKBLOB_CC_MIN: Final = 0.4  # 最大深连通块>40% 页 → 墨团
VOID_FRAC_MIN: Final = 0.3  # 最大空 rect>30% textblock → 空洞
#: 密封白区内墨率下限——框线（tcolorbox/lstlisting/坐标轴）封出的
#: 白 CC 内部有渲染内容即非真空洞；先验值待 §7.4 校准（残留风险：
#: 超稀疏 line-art 内墨可能 <2%，届时用内接最大净矩形臂复核）。
VOID_INT_INK_MIN: Final = 0.02
#: 候选封闭框占页面积下限（void_int 阈=30% textblock≈25% 页，框须
#: 更大；取 15% 留余量）与框内矢量构件数下限（曲线/刻度族）。
VOID_FRAME_MIN_FRAC: Final = 0.15
VOID_FRAME_ART_MIN: Final = 8
#: 共线游程合并后仍超过此件数的页只拿长边（≥12% 页长）进聚簇
#: 对配——矢量散点页数千小件的 O(n²) 闸（实证拖垮全检）；小件
#: 聚不出 15% 面积簇，不受影响（仍作簇内 art 计数）。
_FRAME_CLUSTER_MAX: Final = 800
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
#: overfull 尾随语境定位行号——``detected at line 339`` /
#: ``in paragraph at lines 45--46``（日志 79 列折行，取匹配点后 160
#: 字符窗口内首个行号锚）。
_OVERFULL_LINE_RX: Final = re.compile(
    r"(?:detected at line|at lines?)\s+(\d+)(?:--(\d+))?"
)
_FLOAT_FIT_RX: Final = re.compile(r"TeXlate-Float-Fit")
#: 浮体丢失只认浮体自身签名——``Float too large`` 及 float 丢失字样；
#: ``Reference/Citation `x' undefined`` 行改走 xlat_broken_refs 面
#: （_UNDEF_KEY_RX 抽键做 zh-base 差集）。
_FLOAT_LOST_RX: Final = re.compile(
    r"Float too large|lost floats?|\bfloat\b[^\n]*\blost\b",
    re.IGNORECASE,
)
_UNDEF_KEY_RX: Final = re.compile(
    r"(?:Reference|Citation)\s+`([^']+)'\s+on page\s+\d+\s+undefined",
    re.IGNORECASE,
)
#: 类目内建标签白名单——mn2e/mnras firstpage/lastpage 习语、elsarticle
#: \Newlabel 作者标签、lastpage/labels 组件（源内固有悬空，非管线产物）。
_UNDEF_WHITE_RX: Final = re.compile(
    r"(?i)^(?:firstpage|lastpage|lastbibitem|totpages|addr\d*|cor\d*|"
    r"fn\d*|.*thanks.*)$"
)
_ASCII_LINE_RX: Final = re.compile(r"^[A-Za-z0-9 ,.'()\[\]:;/&+-]{25,}$")
#: bib 区 ASCII 行判定（加 ~_%# 与拉丁扩展/连接号/弯引号容忍——
#: 作者名变音符与页码 en-dash 是 bib 常态；与 en_lines 计数用的
#: _ASCII_LINE_RX 拆开，防宽字符集波及主计数）。
_BIB_LINE_RX: Final = re.compile(
    r"^[A-Za-z0-9 À-ɏ‐-―‘-” ,.'()\[\]:;/&+~_%#=-]{20,}$"
)
_REFS_HEAD_RX: Final = re.compile(
    r"^\s*(?:\d+\s*[.、]?\s*)?(?:references|bibliography|参考文献)\s*$",
    re.IGNORECASE,
)
#: bib 条目首行标记——[N] / [S1] 补充文献 / [Smi19]·[ABC+20]
#: author-year 标签（字母前缀 ≤6 + 数字尾 + 可选小写年字母）。
_BIB_MARK_RX: Final = re.compile(r"^\s*\[([A-Za-z]{0,6}\d+[a-z]?)\]\s*\S")
_BIB_TAGNUM_RX: Final = re.compile(r"\d+")
#: 数字形条目标记（``12.``/``12)``/裸 ``12``）——必须同行佐证才算
#: bib marker，防正文枚举号误锚。
_BIB_NUM_RX: Final = re.compile(r"^\s*(\d{1,4})[.)]?\s+\S")
_BIB_CORRO_RX: Final = re.compile(
    r"doi|arxiv|isbn|et al\.|https?://|www\.|\b(?:19|20)\d{2}[a-z]?\b",
    re.IGNORECASE,
)
#: author-year 尾段探测——无 [N] 簇时按作者/年份行密度锚 bib 区。
_BIB_AY_RX: Final = re.compile(
    r"et al\.|\(\d{4}\)|^\s*[A-Z][a-z]+,\s*[A-Z]\."
)
#: DOI/arXiv/ISBN 行——簇区密度 ≥0.3 作独立 bib 证据。
_BIB_ID_RX: Final = re.compile(r"doi|arxiv[:.]|isbn|10\.\d{4,}/|https?://",
    re.IGNORECASE)


def _refs_cut(lines: list[str]) -> int:
    """参考文献区起始行：尾部 bib marker 稠密簇定位 + 锚定校验。

    marker 三族：``[N]``/``[S1]``/``[Auth19]`` 括形（自证）；``N.``/``N)``/
    裸 ``N`` 数字形（须同行 DOI|arXiv|et al.|(19|20)\\d\\d 佐证，防正文枚举
    误锚）；``et al.``/``(2019)``/``Smith, J.`` 作者年形（无数字锚用）。

    簇锚定：从最后 marker 倒序连回，相邻行距 >80 或数字回跳（前一标号
    比后一标号大 >2——双栏交错 ±1/±2 抖动容忍）即截断。锚条件：簇内含
    标号 1、或尾部 ≥3 数字标号严格递增、或（全簇无数字标号时）≥3 条
    author-year 行——正文密引伪簇（高标号无锚）被拒。

    判据：簇 marker 行 bib-ASCII 占比 ≥50%，或簇区 DOI/arXiv/ISBN 行密度
    ≥0.3（独立证据）。无命中返 len(lines)。"""
    marks: list[tuple[int, int | None, str]] = []
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        m = _BIB_MARK_RX.match(ln)
        if m:
            marks.append((i, int(_BIB_TAGNUM_RX.search(m.group(1)).group()), "brk"))
            continue
        m = _BIB_NUM_RX.match(ln)
        if m and _BIB_CORRO_RX.search(ln):
            marks.append((i, int(m.group(1)), "num"))
            continue
        if _BIB_AY_RX.search(ln):
            marks.append((i, None, "ay"))
    if len(marks) < 3:
        return len(lines)
    start = len(marks) - 1
    for k in range(len(marks) - 2, -1, -1):
        if marks[k + 1][0] - marks[k][0] > 80:
            break
        nk, nk1 = marks[k][1], marks[k + 1][1]
        if nk is not None and nk1 is not None and nk > nk1 + 2:
            break  # 正文 [N] 引用倒灌截断
        start = k
    cluster = marks[start:]
    if len(cluster) < 3:
        return len(lines)
    nums = [n for _, n, _ in cluster if n is not None]
    ays = sum(1 for *_, k in cluster if k == "ay")
    tail = nums[-3:]
    anchored = (
        any(n == 1 for n in nums)
        or (
            len(nums) >= 3
            and len(tail) == 3
            and tail[0] < tail[1] < tail[2]
        )
        or (not nums and ays >= 3)
    )
    if not anchored:
        return len(lines)
    cut = cluster[0][0]
    mark_lines = [lines[i].strip() for i, _, _ in cluster]
    ascii_frac = sum(1 for ln in mark_lines if _BIB_LINE_RX.match(ln)) / max(
        len(mark_lines), 1
    )
    span = [ln for ln in lines[cut:] if ln.strip()]
    doi_frac = sum(1 for ln in span if _BIB_ID_RX.search(ln)) / max(len(span), 1)
    return cut if ascii_frac >= 0.5 or doi_frac >= 0.3 else len(lines)


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
#: CJK 词判定——geo_text_overlap 的参与闸（splice 只产 zh 墨，
#: en×en 碰撞非本管线产物）。CJK 统一表意 + 日文假名 + 谚文音节。
_CJK_RX: Final = re.compile(r"[一-鿿぀-ヿ가-힯]")
#: 数学字符面——math-alnum U+1D400–1D7FF、letterlike U+2100–214F、
#: 组合重音 U+0300–036F + 02C6/02DC、箭头 2190–21FF、算子 2200–22FF、
#: 括号/底顶 2308–230B/27C0–27FF、n-ary 2A00–2AFF、增补箭头
#: 2900–297F、希腊 0370–03FF、质数 2032–2037、±×÷——pymupdf 把
#: frac/sub/sup 堆叠与 CJK 合成 unionbox 时的碰撞豁免族。
_MATH_RX: Final = re.compile(
    "[̃-ͯͰ-Ͽˆ˜′-‷∀-⋿⌈-⌋⟀-⟿⤀-⥿⨀-⫿±×÷𝐀-𝟿]"
)
#: zh 参与判定——CJK 命中且不含 U+FFFD（图内坏 cmap 字体抽出的
#: ``푣`` 类 token 不算 zh 墨，2503.05281 实证）。
def _zh_tok(t: str) -> bool:
    return _CJK_RX.search(t) is not None and "\ufffd" not in t


#: 结构性首页行——分隔白页豁免：空页下一非空页首行命中即
#: verso/章前隔页（openright/twoside/frontmatter 常态）。
_STRUCT_HEAD_RX: Final = re.compile(
    r"^\s*(?:chapter|part|appendix|section|abstract|references|"
    r"bibliography|contents|preface|prologue|epilogue|acknowledg\w*|"
    r"declaration|glossary|index|第.{0,8}[章节部篇回]|附录|参考文献|"
    r"目录|前言|序言|绪论|引言|致谢|声明|摘要|符号表|术语表|结论|"
    r"尾声|索引|致读者|插图|表格)",
    re.IGNORECASE,
)
#: folio 行（页码/罗马码）——页内唯一文字是 folio 时页仍算家具页。
_FOLIO_RX: Final = re.compile(r"^\s*[\dIVXLCDMivxlcdm]{1,8}\s*$")
#: furniture 频次的数字归一（页眉年份/页码变体坍缩）。
_DIGIT_RX: Final = re.compile(r"\d+")
_NORM_RX: Final = re.compile(r"[^a-z0-9]+")
_TEX_CMD_RX: Final = re.compile(r"\\[a-zA-Z@]+\*?")
#: 断链引用位点——``?{2,}`` 每 run 计一位（``????`` 多键 cite 仍算
#: 一位）；括/方号内单 ``?`` 亦计（natbib 断链渲成 ``(?)``/``[?]``，
#: 2602.09703 满页实证）；零散修辞双问号由 ≥8 位点阈豁免。
_BROKEN_REF_RX: Final = re.compile(r"[(\[]\?+[)\]]|\?{2,}")
_BROKEN_BRK_RX: Final = re.compile(r"[(\[]\?+[)\]]")
#: 裸 ?? 位点权重——tikz-cd/xy 箭头字形（⇒/⇉）与源字面 ?? 都抽成
#: 裸形；括号形 (?)/[?] 是断链专属渲法保持全权。
BROKEN_BARE_W: Final = 0.5
BROKEN_REFS_MIN: Final = 8
#: log 缺字佐证缺席时 FFFD 净差的保险丝——base 亦残会把 net 压成
#: 0；net≥3 仍报（内嵌图 ToUnicode 缺口的批量 FFFD 无 Missing
#: character 行佐证即被此闸挡下的另一侧风险已知情）。
DEGEN_FFFD_FUSE: Final = 3
#: splice tex haystack 规模闸——巨型多文件工程全量读盘成本封顶。
_TEX_HAY_MAX: Final = 200
#: verbatim 环境内文块——\\begin{X}…\\end{X} 同名回引。
_VERB_ENV_RX: Final = re.compile(
    r"\\begin\s*\{("
    + "|".join(re.escape(e) for e in sorted(VERBATIM_ENVS))
    + r")\}(.*?)\\end\{\1\}",
    re.DOTALL,
)
#: \\newlabel/\\Newlabel 衍生键——aux 与 cls 生成的标签不在悬空
#: ref 键集内（elsarticle cor/addr 实证）。
_NEWLABEL_RX: Final = re.compile(r"\\[nN]ewlabel\s*\{([^}]+)\}")


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


def _frontmatter_lines(tex_files: list[Path]) -> set[int]:
    """各 splice tex 的 ``\\maketitle`` 行号与 titlepage 环境行区间的
    并集（1-based；对撞文件只共享行号不共享文件名——单发大 overfull
    降权路径只覆盖能反查到标题语境的格）。"""
    out: set[int] = set()
    for p in tex_files:
        try:
            tl = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        depth = 0
        for i, ln in enumerate(tl, 1):
            if re.search(r"\\begin\s*\{titlepage\}", ln):
                depth += 1
            if depth:
                out.add(i)
            if re.search(r"\\end\s*\{titlepage\}", ln):
                depth = max(0, depth - 1)
            if re.search(r"\\maketitle\b", ln):
                out.add(i)
    return out


def _logscan(
    log_text: str, title_lines: set[int] | None = None
) -> tuple[list[dict], dict]:
    """编译日志信号：overfull 去重计数+峰值、Float-Fit typeout、浮体
    丢失（浮体臂）、未解引用键集（喂 xlat_broken_refs 证据面）。

    overfull 判定三层先收口：(1) ``(kind, round(pt,1))`` 去重——逐页
    同值 running-head/vbox 条目塌缩成单签；(2) vbox <2pt 亚像素带整丢；
    (3) 计数臂 ``distinct > OVERFULL_COUNT`` 还须峰值 ≥20pt，峰值臂
    >50pt 不变。``title_lines`` 给出 splice tex 的 \\maketitle/
    titlepage 行号集——全部驱动级（≥20pt）溢出都落在标题语境时降为
    ``layout:overfull_titlepage``（INFO；cms-tdr banner 测量盒实证）。
    """
    findings: list[dict] = []
    seen: set[tuple[str, float]] = set()
    ov: list[tuple[str, float, int | None]] = []
    for m in _OVERFULL_RX.finditer(log_text):
        kind, pt = m.group(1), float(m.group(2))
        if kind == "v" and pt < OVERFULL_VBOX_FLOOR_PT:
            continue
        key = (kind, round(pt, 1))
        if key in seen:
            continue
        seen.add(key)
        ctx = log_text[m.end() : m.end() + 160]
        lm = _OVERFULL_LINE_RX.search(ctx)
        ov.append((kind, pt, int(lm.group(1)) if lm else None))
    fit = len(_FLOAT_FIT_RX.findall(log_text))
    lost = len(_FLOAT_LOST_RX.findall(log_text))
    undef_keys = sorted(set(_UNDEF_KEY_RX.findall(log_text)))
    metrics = {
        "overfull_n": len(ov),
        "overfull_max_pt": max((p for _, p, _ in ov), default=0.0),
        "overfull_vbox_n": sum(1 for k, _, _ in ov if k == "v"),
        "float_fit_typeout": fit,
        "float_lost_warn": lost,
        "undef_ref_keys": undef_keys,
    }
    if (
        len(ov) > OVERFULL_COUNT and metrics["overfull_max_pt"] >= OVERFULL_COUNT_MIN_PT
    ) or metrics["overfull_max_pt"] > OVERFULL_MAX_PT:
        drivers = [o for o in ov if o[1] >= OVERFULL_COUNT_MIN_PT]
        title_ctx = bool(
            title_lines
            and drivers
            and all(o[2] is not None and o[2] in title_lines for o in drivers)
        )
        findings.append(
            {
                "sig": (
                    "layout:overfull_titlepage"
                    if title_ctx
                    else "layout:overfull"
                ),
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

    - ``marks_absent``：zh 侧 txlm 缺席/零 mark → 注入层真洞；base 侧
      ``base_txlm=None`` 的「未建对照臂」只是参数事实（base=onfail
      时 clean 不编 base 臂），metrics 记账不出 finding——但臂已建
      （base_dir 传入）而 txlm 缺席/零 mark 仍是注入链断，照报。
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
    if base_txlm is not None:
        if base_txlm.exists():
            base = parse_txlm(base_txlm)
            metrics["base_marks"] = len(base["marks"])
            if not base["marks"]:
                base = None
        if base is None:
            # 臂已建（base_dir 传入）却 txlm 缺席/零 mark = 注入/仪表
            # 链断；区别于 base_txlm=None 的「未建对照臂」参数事实
            findings.append({"sig": "layout:marks_absent", "side": "base"})
    # base 臂未建只记 metrics——对照臂编不编是参数选择非缺陷
    metrics.setdefault("base_marks", 0)
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


def _page_frames(pg, words: list[tuple]) -> list[dict]:
    """矢量框线聚簇 → 每页「封印框」候选 [{rect, words, art}]——
    vis_void 的 frames 兜底闸：tcolorbox/lstlisting/axis 框把白连通块
    封出内部洞形是合法排版，框内有词或有小矢量件即非掉图窟窿。

    pymupdf get_drawings 把框拆成逐边独立 path（2605.27680 实证 4 条
    边线分列），须 union-find 把「相交或 ≤2pt 间隙」的 path rect 聚簇；
    聚出 rect 占页 ≥15% 才算框（散点小件不聚出大簇）。簇内数：
    词 = 词心落入数；art = 严格内嵌的小矢量件数（坐标轴刻度/ticks）。
    """
    try:
        rects = [d["rect"] for d in pg.get_drawings() if d.get("rect")]
    except Exception:  # 个别页 drawings 解码失败不毙整篇
        return []
    # 退化 rect（零高/零宽的框边线）不能丢——框就是四条边线聚簇
    # 出来的（2605.27680 p17 实证：tcolorbox 4 条 is_empty 边线）。
    rects = [r for r in rects if r is not None]
    pw = pg.rect.width
    ph = pg.rect.height
    dil = 2.0
    # 共线游程合并：listings 系把框侧边渲成逐行 \\vrule 短段堆叠
    # （1812.00089 p44 实证 ~40 段 14pt 竖段链成 605pt 边），先沿
    # 主轴把「同车道且首尾相接 ≤2pt」的段并成一条，否则短段聚簇
    # 全对配是 O(n²) 炸弹且框认不出。排序键=垂直车道中心；run
    # 中心钉首个成员——连锁漂移限 2·dil 带宽。
    def _merge_runs(idx: list[int], horiz: bool) -> list:
        if horiz:
            order = sorted(idx, key=lambda i: (rects[i].y0 + rects[i].y1) / 2)
        else:
            order = sorted(idx, key=lambda i: (rects[i].x0 + rects[i].x1) / 2)
        runs: list[list] = []  # [lane_center, x0,y0,x1,y1]
        for i in order:
            r = rects[i]
            c = (r.y0 + r.y1) / 2 if horiz else (r.x0 + r.x1) / 2
            lo = r.x0 if horiz else r.y0
            hi = r.x1 if horiz else r.y1
            axis_lo = 1 if horiz else 2  # run 里沿轴起/端坐标槽位
            axis_hi = 3 if horiz else 4
            for run in reversed(runs[-3:]):
                if (
                    abs(c - run[0]) <= dil
                    and lo <= run[axis_hi] + dil
                    and hi + dil >= run[axis_lo]
                ):
                    run[1] = min(run[1], r.x0)
                    run[2] = min(run[2], r.y0)
                    run[3] = max(run[3], r.x1)
                    run[4] = max(run[4], r.y1)
                    break
            else:
                runs.append([c, r.x0, r.y0, r.x1, r.y1])
        return [tuple(run[1:]) for run in runs]

    horiz = [i for i, r in enumerate(rects) if r.width >= r.height]
    vert = [i for i, r in enumerate(rects) if r.width < r.height]
    merged = _merge_runs(horiz, True) + _merge_runs(vert, False)
    # 聚簇对配：合并后仍密（矢量散点页数千小件互不并合）时只过
    # 长边——封印框的边必是长条（≥12% 页长），小件聚不出 15%
    # 面积簇，只作簇内 art 计数。
    if len(merged) > _FRAME_CLUSTER_MAX:
        cand = [
            i
            for i, r in enumerate(merged)
            if max(r[2] - r[0], r[3] - r[1]) >= 0.12 * max(pw, ph)
        ]
    else:
        cand = list(range(len(merged)))
    if not cand:
        return []
    par = {i: i for i in cand}

    def find(i: int) -> int:
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    for a, i in enumerate(cand):
        ri = merged[i]
        for j in cand[a + 1 :]:
            rj = merged[j]
            if not (
                ri[2] + dil < rj[0]
                or rj[2] + dil < ri[0]
                or ri[3] + dil < rj[1]
                or rj[3] + dil < ri[1]
            ):
                par[find(i)] = find(j)
    clusters: dict[int, list] = {}
    for i in cand:
        clusters.setdefault(find(i), []).append(i)
    out: list[dict] = []
    for ids in clusters.values():
        # 手算并 bbox——pymupdf ``|`` 对退化（零面积）rect 返回空
        # 操作数（1.28.2 实证），框边线聚簇必须用坐标 min/max。
        x0 = min(merged[i][0] for i in ids)
        y0 = min(merged[i][1] for i in ids)
        x1 = max(merged[i][2] for i in ids)
        y1 = max(merged[i][3] for i in ids)
        if (x1 - x0) * (y1 - y0) < pw * ph * VOID_FRAME_MIN_FRAC:
            continue
        nw = sum(
            1
            for wx0, wy0, wx1, wy1, _ in words
            if x0 <= (wx0 + wx1) / 2 <= x1 and y0 <= (wy0 + wy1) / 2 <= y1
        )
        art = sum(
            1
            for i in range(len(merged))
            if i not in ids
            and x0 < merged[i][0]
            and merged[i][2] < x1
            and y0 < merged[i][1]
            and merged[i][3] < y1
        )
        out.append({"rect": (x0, y0, x1, y1), "words": nw, "art": art})
    return out


def _bbox_pages_mupdf(pdf: Path) -> list[dict] | None:
    """pymupdf 词面（可选件缺席/坏档 → None 回落 poppler）——clip-aware：
    splice 常把整页源内容封成 Form XObject 裁框当矢量图用，被裁掉部分的
    en 词 poppler 仍全数报出（幻影层），mupdf 与渲染器同口径不收录
    （2609.05962 p11 实证 pdftotext 460 词 vs mupdf 82 词，幻影 en 行
    压在 zh 行上成 96 对假重叠）。
    /Rotate 页：get_text("words") 出未旋转坐标——乘 rotation_matrix
    映射回显示轴（1003.5197 p25 实证），否则 rot 页 margin/overlap 全
    在错轴上量。"""
    try:
        import pymupdf
    except ImportError:
        return None
    try:
        with pymupdf.open(str(pdf)) as doc:
            pages: list[dict] = []
            for pg in doc:
                rot = pg.rotation
                ws = [tuple(w[:5]) for w in pg.get_text("words")]
                if rot:
                    rm = pg.rotation_matrix
                    ws = [
                        (r.x0, r.y0, r.x1, r.y1, w[4])
                        for w in ws
                        for r in (pymupdf.Rect(w[:4]) * rm,)
                    ]
                pages.append(
                    {
                        "w": pg.rect.width,
                        "h": pg.rect.height,
                        "rot": rot,
                        "words": ws,
                        "frames": _page_frames(pg, ws),
                    }
                )
            return pages
    except Exception:
        return None


def _bbox_pages(pdf: Path) -> list[dict]:
    """[{w,h,words:[(x0,y0,x1,y1,text)]}]（pt 轴、原点左上）——词源
    pymupdf 优先（clip-aware），缺席退 ``pdftotext -bbox``（clip-blind，
    幻影源文面会虚报 overlap/margin）。"""
    mp = _bbox_pages_mupdf(pdf)
    if mp is not None:
        return mp
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


def _sym_tok(t: str) -> bool:
    """数学符号 token——≤2 字符且全为非字母数字（√ ∼ ± → ∫ ∑ 等
    bbox 瘦高符号；\\stackrel{iid}{\\sim} 堆叠的 iid×∼ 假重叠对
    即此类）。CJK 在 Python 里算 alnum，不受影响。"""
    return len(t) <= 2 and not any(c.isalnum() for c in t)


def _math_tok(t: str) -> bool:
    """重叠判定的数学 token——_sym_tok 之外再收：含数学字符的 token
    （math-alnum 𝑖𝛼𝜃、letterlike ℝ𝔼ℏℓ、组合重音 Q̂/ˆ、算子 ∫∑∏√∂∇、
    希腊字母等）。pymupdf 把公式堆叠/上下标与 CJK 合 unionbox，含数学
    字符的合并簇（``⟨n⟩为一个强C`` 形）整体豁免——同时覆盖
    「CJK+数学字符」merged-cluster 臂。"""
    return _sym_tok(t) or _MATH_RX.search(t) is not None


def _word_overlap_pairs(words: list[tuple], cjk_gate: bool = True) -> int:
    """跨行词重叠对数——同行相邻词天然贴近不算，只数「y 中心差 > 半词高
    且 bbox IoU > 阈」对（#615 重叠对法）。扫线法 O(n log n + k)。
    数学 token 不参与——瘦高 bbox 天然与邻行堆叠；含数学字符的合并簇
    （math+CJK unionbox）同豁免。
    CJK 参与闸（cjk_gate，zh 侧默认）：splice 只产 zh 墨——en×en 对非
    本管线产物（图内源侧碰撞）；base 侧（纯 en 文档对拍）传 False 全量
    计，否则 src-inherent 碰撞永远 suppress 不掉。
    对级豁免两层：堆叠（小盒 x 区间被大盒包含 ±2pt 且小 token ≤4 字符
    无 CJK——frac 分子/上下标原子）与相擦带（IoU∈[0.30,0.45) 且纵向
    重叠 <2.5pt 或 <小盒高 20%——bbox 相擦非墨触）。"""
    ws = sorted(words, key=lambda w: (w[1] + w[3]) / 2)
    n = 0
    for i, a in enumerate(ws):
        if _math_tok(a[4]):
            continue
        acy = (a[1] + a[3]) / 2
        ah = max(a[3] - a[1], 1e-6)
        for b in ws[i + 1 :]:
            bcy = (b[1] + b[3]) / 2
            if bcy - acy > max(ah, b[3] - b[1]) * 2:
                break  # y 序扫出窗
            if abs(bcy - acy) < ah * 0.5:
                continue  # 同行
            if _math_tok(b[4]):
                continue  # 数学 token/合并簇
            if cjk_gate and not (_zh_tok(a[4]) or _zh_tok(b[4])):
                continue  # en×en——非 splice 产物（图内源侧/残留 en 面）
            ix = min(a[2], b[2]) - max(a[0], b[0])
            iy = min(a[3], b[3]) - max(a[1], b[1])
            if ix <= 0 or iy <= 0:
                continue
            inter = ix * iy
            sa = (a[2] - a[0]) * (a[3] - a[1])
            sb = (b[2] - b[0]) * (b[3] - b[1])
            small = min(sa, sb)
            if small <= 0 or inter / small <= OVERLAP_IOU:
                continue
            # 堆叠豁免：小盒被大盒 x 向包含（±2pt）且是 ≤4 字符非 CJK
            # 原子——frac 分子/上下标 bbox 上探行盒是合法排版
            s, g = (a, b) if sa <= sb else (b, a)
            if (
                g[0] - 2.0 <= s[0]
                and s[2] <= g[2] + 2.0
                and len(s[4]) <= 4
                and not _CJK_RX.search(s[4])
            ):
                continue
            # 相擦带：阈上低 IoU + 纵向重叠极薄 → bbox 相擦非墨触
            if inter / small < OVERLAP_GRAZE_HI and (
                iy < OVERLAP_GRAZE_IY or iy < 0.2 * (s[3] - s[1])
            ):
                continue
            n += 1
    return n


#: 全角标点占位符——glyph bbox 按全 em 计、墨迹只占一半，行末标点
#: 会让 xMax 虚超 textblock ~0.5em（2608.25736 实证 2.8–6.4pt 伪越界
#: 全挂在 ，。：（ 尾上）。真溢出按真实 box 计不受影响。
_CJK_PUNCT_R: Final = "，。、；：？！）】」』》〉”’…—·"
_CJK_PUNCT_L: Final = "（【「『《〈“‘"
#: verbatim 英文段豁免口径——越界词落在「x 序连续 ASCII 词跑」内且
#: 跑长 ≥此值即免数（附录/prompt 列表整段溢出是 en 原文同形）；句内
#: 夹的单枚英文术语（跑长不足）仍计。CJK 词天然断跑——双栏页英列
#: 不被邻栏 zh 词并带豁免，也不拖回计数面。
_ASCII_RUN_MIN: Final = 4
_ASCII_RUN_GAP: Final = 24.0  # pt——连跑内相邻 ASCII 词 x0−prev_x1 阈
# （列表对齐空隙仍归一跑；栏间分隔由 CJK 断跑承担）


def _page_word_stats(
    pg: dict, geom: dict, ascii_run_exempt: bool = True, cjk_gate: bool = True
) -> tuple[int, int, int]:
    """单页 (越界词数, 离页词数, 跨行重叠对数)——跨臂按页对拍的最小单位。
    越界只数正文带内的词：running head / 页码等页眉页脚家具本就
    骑在 textblock 之外（2608.25736 p7 实证——页眉行触发全页
    breach），cy < t 或 cy > b+20 的词不算。``ascii_run_exempt``
    开（zh 侧）：越界词在 ≥_ASCII_RUN_MIN 词 ASCII 连跑内即免——
    verbatim 附录行溢出归 en 原文同形。base 侧（纯 en 文档）传
    False 全量计——跨臂抑制要的是 en 原件的固有溢出量，豁免会
    把 base 侧压成 0 使抑制退化。
    离页词数 = 越界词中 bbox 真正出纸面的子集（x0<-tol|x1>w+tol|
    y0<-tol|y1>h+tol）——页内深带（folio 家具/源置 geometry）是另
    一类；``cjk_gate`` 传给重叠对判定，base 侧 False。"""
    left, t, r, b = _textblock(geom, pg["w"], pg["h"])
    tol = MARGIN_BREACH_PT
    words = pg["words"]
    run_len: dict[int, int] = {}
    if ascii_run_exempt:
        # cy 序贪心聚行成横带（cy 差 < 行高×0.5 归一带），带内 x 序
        # 切 ASCII 连跑：相邻 ASCII 词间距 ≤_ASCII_RUN_GAP 续跑，
        # CJK/符号词或大空隙断跑
        wline = [-1] * len(words)
        nlines = 0
        cur_cy = cur_h = 0.0
        for i in sorted(
            range(len(words)), key=lambda j: (words[j][1] + words[j][3]) / 2
        ):
            cy = (words[i][1] + words[i][3]) / 2
            h = max(words[i][3] - words[i][1], 1e-6)
            if nlines == 0 or cy - cur_cy >= max(cur_h, h) * 0.5:
                nlines += 1
                cur_cy, cur_h = cy, h
            wline[i] = nlines - 1
        for ln in range(nlines):
            cur: list[int] = []
            prev_x1 = -1e18
            for i in sorted(
                (j for j in range(len(words)) if wline[j] == ln),
                key=lambda j: words[j][0],
            ):
                x0, x1, wtext = words[i][0], words[i][2], words[i][4]
                if wtext.isascii():
                    if cur and x0 - prev_x1 > _ASCII_RUN_GAP:
                        for j in cur:
                            run_len[j] = len(cur)
                        cur = []
                    cur.append(i)
                elif not _sym_tok(wtext):
                    # CJK 等实质非 ASCII 词断跑；数学符号 token 透明
                    # 穿透——``x ≥ t → a`` 伪码行不被劈成短跑误计
                    for j in cur:
                        run_len[j] = len(cur)
                    cur = []
                prev_x1 = x1
            for j in cur:
                run_len[j] = len(cur)
    nb = off = 0
    pw, ph = pg["w"], pg["h"]
    for i, (x0, y0, x1, y1, wtext) in enumerate(words):
        cy = (y0 + y1) / 2
        if not (t - 2 <= cy <= b + 20.0):
            continue
        if _sym_tok(wtext) or run_len.get(i, 0) >= _ASCII_RUN_MIN:
            continue  # 数学符号 token / verbatim 英文段越界豁免
        h = max(y1 - y0, 1e-6)
        bx0 = x0 + (h * 0.6 if wtext[:1] in _CJK_PUNCT_L else 0.0)
        bx1 = x1 - (h * 0.6 if wtext[-1:] in _CJK_PUNCT_R else 0.0)
        if bx0 < left - tol or bx1 > r + tol or y1 > b + tol:
            nb += 1
            if bx0 < -tol or bx1 > pw + tol or y0 < -tol or y1 > ph + tol:
                off += 1
    return nb, off, _word_overlap_pairs(words, cjk_gate=cjk_gate)


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
    breach_n = overlap_n = band_n = 0
    word_counts: list[int] = []
    head_hits = 0
    breach_by_page: list[int] = []
    overlap_by_page: list[int] = []
    for pi, pg in enumerate(pages):
        words = pg["words"]
        word_counts.append(len(words))
        nb, off, op = _page_word_stats(pg, geom)
        breach_by_page.append(nb)
        overlap_by_page.append(op)
        if nb >= MARGIN_BREACH_MIN and off >= 1:
            breach_n += nb
            findings.append(
                {
                    "sig": "geo_margin_breach",
                    "page": pi + 1,
                    "words": nb,
                    "off": off,
                }
            )
        elif nb >= MARGIN_BREACH_MIN:
            # 全量「越界」词其实都在纸面内——只是骑进 textblock 深带：
            # 源置 geometry（revtex 窄栏 folio）、页码/running head
            # 残词等非离页现象；INFO 立档不报警。
            band_n += nb
            findings.append(
                {"sig": "geo_deep_band", "page": pi + 1, "words": nb}
            )
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
    metrics["deep_band_words"] = band_n
    metrics["overlap_pairs"] = overlap_n
    metrics["breach_by_page"] = breach_by_page
    metrics["overlap_by_page"] = overlap_by_page
    metrics["header_pages"] = head_hits
    metrics["word_counts"] = word_counts
    return findings, metrics


def _plain_scan(
    text: str,
    base_text: str | None = None,
    *,
    zh_log: str | None = None,
    tex_hay: str | None = None,
    verb_hay: str | None = None,
) -> tuple[list[dict], dict]:
    """pdftotext 纯文本层：退化兜底（olmOCR 系）+ 残留英文两级档
    （furniture 剔除后 frac≥RESIDUAL_EN_HEAVY_FRAC 升 heavy 档）。

    ``base_text``=en 对照臂全文（缺失→全部跨臂豁免退化单侧口径）；
    ``zh_log``=zh 编译日志（FFFD 臂的 Missing-character 佐证）；
    ``tex_hay``/``verb_hay``=splice tex 全文/verbatim 段内容的
    ``_NORM_RX`` 归一化 blob——残英行回查用。"""
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
    body_norm = [" ".join(ln.split()) for ln in body]
    # 页眉页脚 furniture——正文域内复现 ≥4 次的行（running head 每页
    # 复现属合法面）不计残英；频数只数 body——把 refs 尾算进来会把
    # 「正文残英 + refs 复现」的真残英行也冲进家具（verify 实证）。
    # 二闸：数字归一键跨 ≥4 个不同页 = 页码/年份变体页眉（2410.00043
    # 逐页异码头逃脱精确匹配的实证）；同页序列号行（编号列）页跨=1
    # 不会误坍成家具。
    freq = Counter(body_norm)
    norm_span: dict[str, set[int]] = {}
    for pi, ptxt in enumerate(pages):
        for ln in ptxt.splitlines():
            norm = _DIGIT_RX.sub("#", " ".join(ln.split()))
            if norm:
                norm_span.setdefault(norm, set()).add(pi)

    def _furniture(ln: str) -> bool:
        return freq[ln] >= RESIDUAL_EN_FURNITURE or len(
            norm_span.get(_DIGIT_RX.sub("#", ln), ())
        ) >= RESIDUAL_EN_FURNITURE

    en_lines = [
        ln
        for ln in body_norm
        if _ASCII_LINE_RX.match(ln) and len(ln.split()) >= 4 and not _furniture(ln)
    ]
    text_lines = [ln for ln in body_norm if ln]
    # 发报口径三级豁免（metric 保留原始行数）：
    # - tex-hay 缺席：图内嵌字/includepdf/cls 套话——splice 只译 tex
    #   面，tex 里查无此行的英文不是译文债（figure_embedded 大头）。
    #   splice 缺失（tex_hay=None）时整层退化现行为。
    # - verbatim 环境回显：行落在 lstlisting/verbatim 原文段。
    # - author-run：署名/机构块的天然英文（_keep_verbatim_run 同口径）。
    en_eff: list[str] = []
    en_unreached = 0
    for ln in en_lines:
        blob = _NORM_RX.sub("", ln.lower())
        if tex_hay is not None and (len(blob) < 4 or blob not in tex_hay):
            en_unreached += 1
            continue
        if verb_hay is not None and len(blob) >= 4 and blob in verb_hay:
            continue
        if _keep_verbatim_run(ln):
            continue
        en_eff.append(ln)
    metrics["en_tail_cut"] = cut if cut < len(lines) else None
    metrics["residual_en_lines"] = len(en_lines)
    metrics["residual_en_eff"] = len(en_eff)
    metrics["en_unreached_lines"] = en_unreached
    frac = len(en_eff) / max(len(text_lines), 1)
    if len(en_eff) >= RESIDUAL_EN_MASS_LINES or (
        len(en_eff) >= RESIDUAL_EN_MIN_LINES and frac >= RESIDUAL_EN_MIN_FRAC
    ):
        findings.append(
            {
                "sig": (
                    "xlat_residual_en_heavy"
                    if frac >= RESIDUAL_EN_HEAVY_FRAC
                    else "xlat_residual_en"
                ),
                "lines": len(en_eff),
                "frac": round(frac, 3),
            }
        )
    # 退化：FFFD / 重复 n-gram / 空页——三臂跨 base 对拍（嵌入图
    # ToUnicode 缺口的 FFFD、running head n-gram、verso 白页在 en
    # 原件同形复现，差净才算 splice 产物）。
    fffd = text.count("\ufffd")
    fffd_net = fffd - (base_text.count("\ufffd") if base_text is not None else 0)
    # n-gram 同吃 refs 截断（ACM 版权块逐条参考文献重复是合法面）；
    # 非字母 token 剔除——矢量图散点 marker（1706.02386 298×●）、
    # 零矩阵/数据表数字连珠（2603.07101 75×"0"）都不是文本退化。
    toks = [t for t in " ".join(body).split() if _WORD_CHAR_RX.search(t)]
    ngrams = Counter(
        tuple(toks[i : i + DEGEN_NGRAM]) for i in range(len(toks) - DEGEN_NGRAM + 1)
    )
    top_rep = max(ngrams.values(), default=0)
    base_empty = None
    if base_text is not None:
        btoks = [t for t in base_text.split() if _WORD_CHAR_RX.search(t)]
        ngrams -= Counter(
            tuple(btoks[i : i + DEGEN_NGRAM])
            for i in range(len(btoks) - DEGEN_NGRAM + 1)
        )
        top_rep = max(ngrams.values(), default=0)
        bpages = base_text.split("\f")
        if bpages and not bpages[-1].strip():
            bpages.pop()
        base_empty = sum(1 for p in bpages if len(p.strip()) < EMPTY_PAGE_CHARS)
    # verso/分隔白页豁免：空页的下一非空页首行命中结构性标题
    # （Chapter/第N章/参考文献…）即章前隔页——openright/frontmatter
    # 常态排版非缺陷。
    empty_idx = [i for i, p in enumerate(pages) if len(p.strip()) < EMPTY_PAGE_CHARS]

    def _verso(pi: int) -> bool:
        for j in range(pi + 1, len(pages)):
            if pages[j].strip():
                head = next(
                    (
                        ln
                        for ln in pages[j].splitlines()
                        if ln.strip() and not _FOLIO_RX.match(ln)
                    ),
                    "",
                )
                return bool(_STRUCT_HEAD_RX.match(head))
        return False

    empty_eff = [i for i in empty_idx if not _verso(i)]
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
            "fffd_net": fffd_net,
            "top_ngram_rep": top_rep,
            "empty_pages": len(empty_idx),
            "empty_pages_eff": len(empty_eff),
            "degen_periodic_lines": periodic,
        }
    )
    if base_empty is not None:
        metrics["empty_pages_base"] = base_empty
    # running head 每页复现标题 ≈ npages 次；真退化环单页就产出
    # 数百次——阈值按页数放。无 base 时再加家具地板 rep≤npages 免
    # （每页一次即家具），有 base 由差集承担。
    ngram_cap = max(3 * len(pages), DEGEN_NGRAM_MAX)
    ngram_fire = top_rep > ngram_cap and (
        base_text is not None or top_rep > len(pages)
    )
    # FFFD 臂：log 缺字行佐证——内嵌图字体不经主编译装载，log 零
    # Missing character 时 FFFD 面全是图内继承；保险丝 net≥3 仍报
    # （base 亦残的边角不吞真缺字）。
    if zh_log is None:
        fffd_fire = fffd_net > 0
    else:
        missing = len(re.findall(r"Missing character", zh_log))
        metrics["missing_chars"] = missing
        fffd_fire = fffd_net >= DEGEN_FFFD_FUSE or (missing > 0 and fffd_net > 0)
    empty_fire = (
        (len(empty_eff) - base_empty) if base_empty is not None else len(empty_eff)
    ) > EMPTY_PAGE_MAX
    if fffd_fire or ngram_fire or empty_fire or periodic >= DEGEN_PERIODIC_MIN_LINES:
        findings.append(
            {
                "sig": "vis_degenerate",
                "fffd": fffd,
                "fffd_net": fffd_net,
                "top_ngram_rep": top_rep,
                "empty_pages": len(empty_eff),
                "periodic_lines": periodic,
            }
        )
    # 断链引用：未解析 \cite/\ref 渲成 ?? run——编译 pass 不全的
    # 产物级签名（2505.21476 正文 646 个 ?? 字符实证）；中文全角
    # ？？天然不匹配，修辞性 ??/??? 够不到位点阈。裸 ?? 与括号形
    # 分别记账——跨臂/log 佐证降权在 qc_paper 收口（_plain_scan
    # 纯文本面保持原子口径）。
    broken = len(_BROKEN_REF_RX.findall(text))
    metrics["broken_refs"] = broken
    metrics["broken_refs_brk"] = len(_BROKEN_BRK_RX.findall(text))
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
    *,
    zh_text_pages: list[str] | None = None,
    zh_geo: list[dict] | None = None,
    twoside: bool = False,
) -> tuple[list[dict], dict]:
    """raster 检查：空白/墨团/空洞/tofu（zh 单侧）+ 栏数/规则
    对拍（跨臂）。

    ``zh_images`` = _images_per_page 页→嵌入位图数——含位图页跳过
    ink_blob（星系格/照片类深色位图天然产出巨大 dark CC，与
    text_as_curves 同一豁免族：位图页的大墨块是内容不是泼溅）。
    ``zh_text_pages``=pdftotext 逐页文本（verso/孤行判定）；``zh_geo``
    =_bbox_pages 页 dict（frames 键给 void 的封印框兜底闸）；
    ``twoside``=文档双面排版（偶数 verso 空白页合法）。

    空白页抑制四层：base ±1 窗同空白（源承）/下一非白页首行结构性
    标题（章前分隔）/twoside 偶数页（verso）/末页 folio-only（收尾）。
    近空页（墨量过空白地板但 <WIDOW_INK_MAX 且正文 ≤2 行）降为
    ``vis_widow_page``（INFO）——孤行页是排版丑态非缺陷面。"""
    findings: list[dict] = []
    metrics: dict = {"raster_pages": len(zh_pages)}
    blank = blob = void = blank_supp = widow = 0
    tofu_pages: list[int] = []
    n_zh = len(zh_pages)
    n_tx = len(zh_text_pages) if zh_text_pages is not None else 0
    for i, pg in enumerate(zh_pages):
        if pg["ink"] < BLANK_INK_MAX:
            # 近空白页上有 1-2 行非 folio 文字 → 孤行/孤题残留页
            # （stub 孤 preprint 页/pstricks 垃圾页/浮体搁浅的孤零零
            # 标题页实证）→ 降 vis_widow_page（INFO），不占 HARD 档。
            body_ls = None
            if i < n_tx:
                body_ls = [
                    ln
                    for ln in zh_text_pages[i].splitlines()
                    if ln.strip() and not _FOLIO_RX.match(ln)
                ]
            if body_ls is not None and 0 < len(body_ls) <= 2:
                widow += 1
                findings.append(
                    {
                        "sig": "vis_widow_page",
                        "page": i + 1,
                        "ink": pg["ink"],
                        "lines": len(body_ls),
                    }
                )
            else:
                supp = False
                if base_pages:
                    lo, hi = max(0, i - 1), min(len(base_pages), i + 2)
                    if any(
                        base_pages[j]["ink"] < BLANK_INK_MAX for j in range(lo, hi)
                    ):
                        supp = True  # en 原件同页位留白——源承非缺陷
                if not supp and zh_text_pages is not None:
                    for j in range(i + 1, n_tx):
                        if zh_text_pages[j].strip():
                            head = next(
                                (
                                    ln
                                    for ln in zh_text_pages[j].splitlines()
                                    if ln.strip() and not _FOLIO_RX.match(ln)
                                ),
                                "",
                            )
                            if _STRUCT_HEAD_RX.match(head):
                                supp = True  # 章/部/附录前分隔白页
                            break
                if not supp and twoside and (i + 1) % 2 == 0:
                    supp = True  # 双面排版偶数 verso 留白
                if (
                    not supp
                    and i == 1
                    and zh_text_pages is not None
                    and zh_text_pages[0].strip()
                ):
                    supp = True  # 扉页后 verso——frontmatter 常态空背
                if not supp and i == n_zh - 1 and zh_text_pages is not None:
                    tail_ls = [
                        ln for ln in zh_text_pages[i].splitlines() if ln.strip()
                    ]
                    if all(_FOLIO_RX.match(ln) for ln in tail_ls):
                        supp = True  # 末页仅页码——收尾留白
                if supp:
                    blank_supp += 1
                else:
                    blank += 1
                    findings.append({"sig": "vis_blank_page", "page": i + 1})
        elif pg["ink"] < WIDOW_INK_MAX:
            nlines = (
                sum(1 for ln in zh_text_pages[i].splitlines() if ln.strip())
                if i < n_tx
                else None
            )
            if nlines is None or nlines <= 2:
                widow += 1
                findings.append(
                    {
                        "sig": "vis_widow_page",
                        "page": i + 1,
                        "ink": pg["ink"],
                        "lines": nlines,
                    }
                )
        if pg["dark_cc"] > INKBLOB_CC_MIN and not (zh_images or {}).get(i + 1, 0):
            blob += 1
            findings.append({"sig": "vis_ink_blob", "page": i + 1, "cc": pg["dark_cc"]})
        # 内部洞（四周皆有墨）才是真掉图窟窿；贴边留白是结构性
        # （目录收尾/末页早收/栏尾空行，2605.25645 p3 实证）。
        # void_ink 闸（raster 子进程新版输出）：封印框内墨率 ≥2% =
        # 有内容的 tcolorbox/listing/axis 白内腔，非掉图。缓存 JSON
        # 无 void_ink 时退 frames 兜底：≥15% 页面积矢量框簇内有词心
        # 或 ≥8 小矢量件 → 合法封印框不报。
        v_int = pg.get("void_int", pg["void_frac"])
        if i < n_zh - 1 and v_int > VOID_FRAC_MIN:
            if "void_ink" in pg:
                void_hit = pg["void_ink"] < VOID_INT_INK_MIN
            else:
                frames = (
                    zh_geo[i].get("frames")
                    if zh_geo is not None and i < len(zh_geo)
                    else None
                )
                void_hit = not any(
                    fr["words"] > 0 or fr["art"] >= VOID_FRAME_ART_MIN
                    for fr in (frames or [])
                )
            if void_hit:
                void += 1
                findings.append(
                    {"sig": "vis_void", "page": i + 1, "frac": v_int}
                )
        if pg.get("tofu", 0) >= TOFU_MIN_PAGE:
            tofu_pages.append(i + 1)
    if tofu_pages:
        findings.append({"sig": "vis_tofu_box", "pages": tofu_pages})
    metrics.update(
        {
            "blank": blank,
            "blank_suppressed": blank_supp,
            "widow_pages": widow,
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
        # 计数——image 对拍盲区的补位面。zh 页墨量崩到 base 邻窗峰值
        # 35% 以下、base 邻窗确有内容（>8%）、且该页在自身文档内也是
        # 离群低点（< 全 zh 页中位数×INK_SELF_OUTLIER——重排错位的
        # 「比 base 稀但非离群」页不报）才报。末页豁免（收尾留白
        # 合法），blank 检出页已由 vis_blank_page 认领。
        ink_drops = []
        # 中位数只过非空页——空页已由 vis_blank_page 认领，计入会把
        # 中位数压到 ~0 使离群闸在「半空白文档」里永不触发；全空文档
        # zh_med=0 天然不报警（空页签名已逐页认领）。
        nz = [p["ink"] for p in zh_pages if p["ink"] >= BLANK_INK_MAX]
        zh_med = statistics.median(nz) if nz else 0.0
        for i, pg in enumerate(zh_pages[:-1]):
            if pg["ink"] < BLANK_INK_MAX:
                continue
            lo = max(0, i - 2)
            hi = min(len(base_pages), i + 3)
            bw = max((base_pages[j]["ink"] for j in range(lo, hi)), default=0)
            if (
                bw > 0.08
                and pg["ink"] < bw * INK_DROP_RATIO
                and pg["ink"] < zh_med * INK_SELF_OUTLIER
            ):
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
    # zh_pdf 解析链：{stem}.pdf → .fixloop-entry.pdf 地板快照 →
    # 目录内最大非 fig 命名 *.pdf（main_rel 陈旧/meta skew 面收
    # zone/altseq 判定之外的产物缺席假阳性）。
    zh_pdf = zh_dir / f"{stem}.pdf"
    if not zh_pdf.exists():
        alt = zh_dir / ".fixloop-entry.pdf"
        if alt.exists():
            zh_pdf = alt
        else:
            cands = [
                c
                for c in zh_dir.glob("*.pdf")
                if not re.match(r"(?i)(?:fig|plot|pic)", c.stem)
            ]
            if cands:
                with suppress(OSError):
                    zh_pdf = max(cands, key=lambda c: c.stat().st_size)
    if zh_pdf.name != f"{stem}.pdf":
        metrics["pdf_fallback"] = zh_pdf.name
    zh_log = zh_dir / f"{stem}.log"
    zh_txlm = zh_dir / f"{stem}.txlm"

    # splice tex haystack：残英行 tex-hit 回查 + verbatim 段豁免 +
    # \maketitle/titlepage 行号集（overfull 降权）+ documentclass
    # 双面判定共用一份拼合体。
    try:
        tex_files = sorted(splice_dir.rglob("*.tex"))[:_TEX_HAY_MAX]
    except OSError:
        tex_files = []
    parts = []
    for t in tex_files:
        with suppress(OSError):
            parts.append(t.read_text(encoding="utf-8", errors="replace"))
    src_blob = "\n".join(parts)
    tex_hay = verb_hay = None
    if src_blob:
        tex_hay = _NORM_RX.sub("", _TEX_CMD_RX.sub(" ", src_blob).lower())
        verb_hay = (
            _NORM_RX.sub(
                "",
                " ".join(m.group(2) for m in _VERB_ENV_RX.finditer(src_blob)).lower(),
            )
            or None
        )
    dc = re.search(
        r"\\documentclass\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}", src_blob
    )
    twoside = bool(
        dc
        and (
            re.search(r"twoside|openright", dc.group(1) or "")
            or dc.group(2).strip() in {"book", "scrbook", "memoir", "amsbook"}
        )
    )

    log_text = ""
    try:
        if zh_log.exists():
            log_text = zh_log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    title_lines = (
        _frontmatter_lines(tex_files)
        if "Overfull" in log_text and tex_files
        else None
    )
    f, m = _logscan(log_text, title_lines)
    findings += f
    metrics["log"] = m

    btx = None
    base_pdf = None
    base_undef: set[str] = set()
    if base_dir is not None:
        bdir = base_dir / mp.parent
        btx = bdir / f"{stem}.txlm"
        base_pdf = bdir / f"{stem}.pdf"
        blog = bdir / f"{stem}.log"
        try:
            if blog.exists():
                base_undef = set(
                    _UNDEF_KEY_RX.findall(
                        blog.read_text(encoding="utf-8", errors="replace")
                    )
                )
        except OSError:
            pass
    # zh 新增悬空键 = zh − base（源承）− 类内白名单 − \Newlabel 衍生
    # 标签（elsarticle cor/addr 系）——喂 xlat_broken_refs 佐证面。
    zh_undef = set(metrics["log"].get("undef_ref_keys") or [])
    newlabel_keys = set(_NEWLABEL_RX.findall(src_blob))
    try:
        for aux in zh_dir.glob("*.aux"):
            newlabel_keys |= set(
                _NEWLABEL_RX.findall(
                    aux.read_text(encoding="utf-8", errors="replace")
                )
            )
    except OSError:
        pass
    zh_new_undef = (
        zh_undef
        - base_undef
        - newlabel_keys
        - {k for k in zh_undef if _UNDEF_WHITE_RX.match(k)}
    )
    metrics["log"]["undef_new"] = sorted(zh_new_undef)
    zh_geom = parse_txlm(zh_txlm)["geom"] if zh_txlm.exists() else {}

    if zh_pdf.exists():
        zh_text = _run(["pdftotext", zh_pdf.name, "-"], cwd=zh_pdf.parent)
        zh_text_pages = zh_text.split("\f")
        if zh_text_pages and not zh_text_pages[-1].strip():
            zh_text_pages.pop()
        base_text = None
        if base_pdf is not None and base_pdf.exists():
            base_text = _run(
                ["pdftotext", base_pdf.name, "-"], cwd=base_pdf.parent
            )
        f, m = _plain_scan(
            zh_text,
            base_text or None,
            zh_log=log_text if zh_log.exists() else None,
            tex_hay=tex_hay,
            verb_hay=verb_hay,
        )
        findings += f
        metrics["text"] = m
        zh_images = _images_per_page(zh_pdf)
        pages = _bbox_pages(zh_pdf)
        f, m = _bbox_scan(pages, zh_geom, zh_images)
        findings += f
        metrics["bbox"] = m
        # 断链 ?? 收口：括号形 (?) /[?] 全权，裸 ?? 半权（tikz-cd 箭头
        # 字形与源字面 ?? 都抽成裸形）；net = zh 加权 − base 加权。
        # net<MIN 且（zh log 缺席 或 zh 新增 undefined 键集空）→ 抑制
        # ——log 有真悬空键佐证时 net 不足也照报。
        bbrk = metrics["text"].get("broken_refs_brk", 0)
        btot = metrics["text"].get("broken_refs", 0)
        w_zh = bbrk + BROKEN_BARE_W * (btot - bbrk)
        w_base = 0.0
        if base_text:
            ebrk = len(_BROKEN_BRK_RX.findall(base_text))
            etot = len(_BROKEN_REF_RX.findall(base_text))
            w_base = ebrk + BROKEN_BARE_W * (etot - ebrk)
        bnet = w_zh - w_base
        metrics["text"]["broken_refs_net"] = round(bnet, 1)
        if bnet < BROKEN_REFS_MIN and (
            not zh_log.exists() or not zh_new_undef
        ):
            before = len(findings)
            findings[:] = [
                f_ for f_ in findings if f_.get("sig") != "xlat_broken_refs"
            ]
            metrics["text"]["broken_refs_suppressed"] = before - len(findings)
        if base_text:
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
            # base 侧 cjk_gate=False 全量计 en×en（全英原件的固有碰撞
            # 才是真底噪）；±1 页漂移窗吃 zh/base 分页错位（0812.0424
            # zh p18 vs base p19 实证）——窗内取峰值比较，
            # suppressed_with_drift 记峰值落在邻页的抑制数防窗宽误掩。
            base_geom = (
                parse_txlm(btx)["geom"] if btx is not None and btx.exists() else {}
            )
            base_stats = [
                _page_word_stats(
                    pg, base_geom, ascii_run_exempt=False, cjk_gate=False
                )
                for pg in base_bbox
            ]
            kept: list[dict] = []
            suppressed = suppressed_drift = 0
            for f_ in findings:
                sig_, pg_ = f_.get("sig"), f_.get("page")
                if (
                    sig_ in ("geo_margin_breach", "geo_text_overlap")
                    and isinstance(pg_, int)
                    and base_stats
                    and 1 <= pg_ <= len(base_stats) + 1
                ):
                    lo = max(0, pg_ - 2)
                    hi = min(len(base_stats), pg_ + 1)
                    win = base_stats[lo:hi]
                    vals = [
                        (bn if sig_ == "geo_margin_breach" else bo)
                        for bn, _boff, bo in win
                    ]
                    zval = (
                        f_["words"]
                        if sig_ == "geo_margin_breach"
                        else f_["pairs"]
                    )
                    bval = max(vals, default=0)
                    if zval <= max(bval * 1.5, bval + 3):
                        suppressed += 1
                        same_pos = (pg_ - 1) - lo
                        if 0 <= same_pos < len(vals) and bval > vals[same_pos]:
                            suppressed_drift += 1
                        continue
                kept.append(f_)
            findings[:] = kept
            metrics["base_word_stats"] = {
                "breach_by_page": [n for n, _, _ in base_stats],
                "overlap_by_page": [o for _, _, o in base_stats],
                "suppressed": suppressed,
                "suppressed_with_drift": suppressed_drift,
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
            f, m = _raster_scan(
                rz["pages"],
                rb.get("pages"),
                zh_images,
                zh_text_pages=zh_text_pages,
                zh_geo=pages,
                twoside=twoside,
            )
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
