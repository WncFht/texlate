"""specs._layoutqc.thresh — 阈值/检测模式常量叶 (_layoutqc 拆分叶).

校准集出来前全是先验值——一切 ``Final`` 阈、编译/文本/几何/raster 的
检测 regex 与门档 sig 集集中本叶，sig 即分桶键，阈值漂移只改一处。
叶子/门面直引本叶常量，不经 specs._layoutqc 门面回环。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from specs import _bootstrap

_bootstrap.ensure()

from texlate.textutil import VERBATIM_ENVS

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

OVERLAP_GRAZE_IY: Final = (
    2.6  # 巨型 unionbox 标题 bbox 上缘膨胀相擦（真伤族 iy≈3.3+，0928 实证不波及）
)

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
        "layout:compile_died",
        "layout:pdf_corrupt",
        "layout:lost_element",
        "layout:float_seq_mismatch",
        "layout:dropped_env",
        "layout:offpage",
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
        # 浮盒超高 ≥60pt 深溢出兜底（geo_margin_breach cy>b+20 死区
        # 对纯图形深裁切零覆盖——float_lost 簇 verify 要求保留）。
        "layout:float_oversize_big",
        "geo_header_lost",
        "align_order_break",
        "regress_ink_profile",
    }
)

_INFO_SIGS: Final = frozenset(
    {
        "layout:float_fit",
        "layout:marks_absent",
        # env_inventory 已切 live-env 口径（fls 开档集 + enddoc 死尾/
        # \iffalse 死支/def 体/弃料宏参数组留白）——孤儿文件与死代码
        # 假缺口收敛；残余=measure-then-discard 试排盒/未知弃料宏等
        # 引擎语义盲区（marks_chain 簇实证方向），继续驻 INFO 供分诊。
        "layout:marks_coverage",
        # 浮盒超高 <60pt——下边距吸收、内容不丢，记账不挡。
        "layout:float_oversize",
        # 深带但仍在页内的越界（folio 家具/源置几何/回退框误伤）——
        # 真离页词仍走 geo_margin_breach（WARN）
        "geo_deep_band",
        # 孤行溢出页（bib/段尾寡行+folio）——非内容洞，记账不挡
        "vis_widow_page",
        # \maketitle/titlepage 测量盒的整版过宽（cms-tdr banner 实证）
        "layout:overfull_titlepage",
        # 众数页尺寸比对后仍失配=期刊 trim-size special 单页偏离
        # （2505.06967 spr-astr-addons papersize special 实证）——源稿
        # 既定排版声明非内容伤，降 INFO 记账（0928 pdf_integrity 簇裁定）。
        "layout:paper_mismatch",
        # \\output 例程内溢出=页眉页脚家具/超高 vbox（源稿本就溢出
        # 或模板属性，overfull 簇 0928 裁定 accept_as_is——记录不挡）。
        "layout:overfull_output",
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

DEGEN_PERIODIC_MIN_LINES: Final = 20  # 行内周期占位行数阈——只计
# 含 CJK 的行（mock 占位洪水全是「这是译文」整行连珠 ≥377 行；
# 图区标签/括号 stretch glyph 的非 CJK 连珠 ≤16 行，0928 簇裁定）

EMPTY_PAGE_CHARS: Final = 10  # 空页字符下限

EMPTY_PAGE_MAX: Final = 2  # 空页容忍数

SKELETON_LCS_MIN: Final = 0.6  # 骨架 LCS 覆盖率下限

HEADER_ZONE_FRAC: Final = 0.12  # 页顶 running-head 带（页高比）

HEADER_MIN_FRAC: Final = 0.5  # base 页眉覆盖率阈（低于不测）

HEADER_LOST_FRAC: Final = 0.2  # zh 页眉覆盖率低于此 → sig

POPPLER_TIMEOUT: Final = 60.0

RASTER_TIMEOUT: Final = 420.0  # 全篇渲染 + 逐页度量随页数线性（176p 实证）

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

# _raster_child 留 specs/ 顶层（tests 直引 specs._raster_child）——本叶
# 下沉 _layoutqc/ 后须上溯一级取 sibling。
_RASTER_CHILD: Final = Path(__file__).resolve().parents[1] / "_raster_child.py"

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
#: \\output 例程内溢出——``has occurred while \output is active``
#: （日志 79 列折行允许 ``has occurred\nwhile \output is active``）：
#: 页眉页脚家具 + 超高 vbox 族，accept_as_is 降 ``overfull_output``。

_OUTPUT_ACTIVE_RX: Final = re.compile(r"\\output\s+is\s+active")

_FLOAT_FIT_RX: Final = re.compile(r"TeXlate-Float-Fit")
#: 浮体丢失只认浮体自身标记——``Float too large`` 及 float 丢失字样；
#: ``Reference/Citation `x' undefined`` 行改走 xlat_broken_refs 面
#: （_UNDEF_KEY_RX 抽键做 zh-base 差集）。

_FLOAT_LOST_RX: Final = re.compile(
    r"lost floats?|\bfloat\b[^\n]*\blost\b",
    re.IGNORECASE,
)
#: ``Float too large for page by Xpt``——原子浮盒超高仍整盒出页，
#: 溢出由下边距/页脚区吸收；与真裁切无线性相关（0928 float_lost
#: 簇复核：post-fix 8/9 渲全整、真裁切全被 geo_margin_breach 同页
#: 捕获）。劈出 float_lost 降 INFO；≥60pt 深溢出留 WARN 兜底——
#: geo_margin_breach 的 cy>b+20 死区对纯图形深裁切不可见。

_FLOAT_OVERSIZE_RX: Final = re.compile(
    r"Float too large[^\n]*?by\s*([\d.]+)\s*pt|(Float too large)",
    re.IGNORECASE,
)

FLOAT_OVERSIZE_WARN_PT: Final = 60.0

#: 终编中止判据——``! Emergency stop`` / ``No pages of output`` /
#: ``==> Fatal error`` 任一命中即编译半路死亡：船出页残缺或为零，
#: 下游 marks_absent（零 mark）只是症状非注入洞。entry 快照回退会
#: 掩住这条致命伤（qc_marks_absent 簇 2026-10 实证 7/7 全是中止编译）。
_COMPILE_DIED_RX: Final = re.compile(
    r"Emergency stop|No pages of output|==>\s*Fatal error"
)

#: ``Missing character: There is no X (U+NNNN) in font ...``——键取
#: U+ 码位（缺 ``(U+NNNN)`` 的裸行退字符名）跨臂可比，字体名异臂
#: 不同不算差。
_MISSING_CHAR_RX: Final = re.compile(
    r"Missing character: There is no (.*?)(?:\s*\(U\+([0-9A-Fa-f]{4,})\))?"
    r"\s*in font"
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

_BIB_LINE_RX: Final = re.compile(r"^[A-Za-z0-9 À-ɏ‐-―‘-” ,.'()\[\]:;/&+~_%#=-]{20,}$")

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

_BIB_AY_RX: Final = re.compile(r"et al\.|\(\d{4}\)|^\s*[A-Z][a-z]+,\s*[A-Z]\.")
#: DOI/arXiv/ISBN 行——簇区密度 ≥0.3 作独立 bib 证据。

_BIB_ID_RX: Final = re.compile(
    r"doi|arxiv[:.]|isbn|10\.\d{4,}/|https?://", re.IGNORECASE
)

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

_MATH_RX: Final = re.compile("[̃-ͯͰ-Ͽˆ˜′-‷∀-⋿⌈-⌋⟀-⟿⤀-⥿⨀-⫿±×÷𝐀-𝟿]")
#: BMP noncharacter 面——U+FDD0–FDEF/FFFE/FFFF，坏 cmap 抽出件常带
#: （``푥￿``/`` 푦￿`` 族，0928 text_overlap 图内伪 zh 对实证）。

_NONCHAR_RX: Final = re.compile("[﷐-﷯￾￿]")

#: 结构性首页行——分隔白页豁免：空页下一非空页首行命中即
#: verso/章前隔页（openright/twoside/frontmatter 常态）。
#: ``\d+(?:\.\d+)*\.?\s``=无关键字编号头（``2. 预备知识 ``/``3.2 X``
#: 页首）与 ``isbn``（版权/colophon 页）——1503.00131 实证缺口。
_STRUCT_HEAD_RX: Final = re.compile(
    r"^\s*(?:chapter|part|appendix|section|abstract|references|"
    r"bibliography|contents|preface|prologue|epilogue|acknowledg\w*|"
    r"declaration|glossary|index|isbn\b|第.{0,8}[章节部篇回]|附录|参考文献|"
    r"目录|前言|序言|绪论|引言|致谢|声明|摘要|符号表|术语表|结论|"
    r"尾声|索引|致读者|插图|表格|\d+(?:\.\d+)*\.?\s)",
    re.IGNORECASE,
)
#: folio 行（页码/罗马码）——页内唯一文字是 folio 时页仍算家具页。

_FOLIO_RX: Final = re.compile(r"^\s*[\dIVXLCDMivxlcdm]{1,8}\s*$")

_ROMAN_DIGIT: Final = {
    "i": 1,
    "v": 5,
    "x": 10,
    "l": 50,
    "c": 100,
    "d": 500,
    "m": 1000,
}
#: frontmatter 域深度——\blankpage 族标记佐证只作用于前 N 个 PDF
#: 页（verify 0928：tex 里存在 \blankpage 绝不能豁免全篇空页）。

FRONTMATTER_PAGES: Final = 10
#: tex 侧「显式造白页」标记族——\blankpage(memoir)/\clearempty
#: doublepage/\cleartooddpage 等；裸 \clearpage 不产白页不收。

_BLANKPAGE_RX: Final = re.compile(
    r"\\(?:blankpage|clearemptydoublepage|cleartooddpage|"
    r"cleartoevenpage|cleardoublepage|cleartoleftpage)\b"
)

#: \\title{…} 参数提取（一层嵌套花括号容差）——扉页/标题页 verso
#: 豁免的文档标题证据源。
_TITLE_ARG_RX: Final = re.compile(
    r"\\title\s*(?:\[[^\]]*\])?\s*\{((?:[^{}]|\{[^{}]*\})*)\}"
)

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

#: 全角标点占位符——glyph bbox 按全 em 计、墨迹只占一半，行末标点
#: 会让 xMax 虚超 textblock ~0.5em（2608.25736 实证 2.8–6.4pt 伪越界
#: 全挂在，。：（尾上）。真溢出按真实 box 计不受影响。
_CJK_PUNCT_R: Final = "，。、；：？！）】」』》〉”’…—·"

_CJK_PUNCT_L: Final = "（【「『《〈“‘"
#: verbatim 英文段豁免口径——越界词落在「x 序连续 ASCII 词跑」内且
#: 跑长 ≥此值即免数（附录/prompt 列表整段溢出是 en 原文同形）；句内
#: 夹的单枚英文术语（跑长不足）仍计。CJK 词天然断跑——双栏页英列
#: 不被邻栏 zh 词并带豁免，也不拖回计数面。

_ASCII_RUN_MIN: Final = 4

_ASCII_RUN_GAP: Final = 24.0  # pt——连跑内相邻 ASCII 词 x0−prev_x1 阈
# （列表对齐空隙仍归一跑；栏间分隔由 CJK 断跑承担）
