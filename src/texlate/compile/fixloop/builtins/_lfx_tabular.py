r"""builtins._lfx_tabular — 表族盒宽钳 (layoutfix 拆分, fp wide_tabular + minipage_clamp 折叠臂)。

``tabular_fit``: 表族盒宽钳到 ``\linewidth`` —— 源级跨度
``adjustbox{max width=\linewidth,max totalheight=\textheight}`` 包
(inject 侧 ``TABLE_FITTING`` 成对钩法 0930 拔除后本 builtin 是表族
钳宽唯一面) + 可断页表族 (longtable 系) env/begin 局部收缩
+ 列声明 ``p{\textwidth}``/表域负 ``\hspace``/绝对宽 minipage 文本臂。
``legacy_clamp_purge``: env_mismatch 自注成对钩残块整剥。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins._lfx_core import (
    _env_spans,
    _in_spans,
    _max_overfull_pt,
    _span_marks,
)
from texlate.compile.fixloop.builtins.common import (
    _fixloop_log,
    _inject_before_begindoc,
    _is_live,
    _map_tex_files,
    _splice,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx

__all__ = [
    "_LEGACY_CLAMP_RX",
    "_LEGACY_HOOK_RX",
    "_MATH_ENVS",
    "_MATH_INLINE_RX",
    "_MINIPAGE_CLAMP_PT",
    "_MINIPAGE_ENV_RX",
    "_MINIPAGE_RX",
    "_MINIPAGE_UNIT_PT",
    "_PCOL_KEEP_FACTOR",
    "_PCOL_SPEC_RX",
    "_TAB_BOX_ENVS",
    "_TAB_FLOW_ANY_RX",
    "_TAB_FLOW_ENVS",
    "_TAB_NEGHSPACE_RX",
    "_TAB_SPAN_ENVS",
    "Any",
    "_fixloop_log",
    "_inject_before_begindoc",
    "_is_live",
    "_map_tex_files",
    "_math_marks",
    "_splice",
    "_strip_legacy_clamp",
    "_tabular_box_edits",
    "_tabular_snippet",
    "_tabular_text_edits",
    "legacy_clamp_purge",
    "mask_tex",
    "tabular_fit",
]


# ════════════════════════════════════════════════════════════════
# tabular_fit —— 表族盒宽钳 (fp wide_tabular + minipage_clamp 折叠臂)
# ════════════════════════════════════════════════════════════════

#: adjustbox 装箱面表族 —— 单页盒语义环境, 装箱不失跨页断行。
#: spec E 列逐名 (``array`` 是数学盒不入钩面, display_math_shrink 分管);
#: ``threeparttable`` 同单页盒语义并入 (旧 TABLE_FITTING 钩面同款)。
_TAB_BOX_ENVS = (
    "tabular",
    "tabular*",
    "tabularx",
    "tabulary",
    "tabu",
    "smalldeluxetable",
    "threeparttable",
)

#: 可断页表族 —— 装箱即失跨页断行语义 (spec 已钉陷), 走 env/begin 局部
#: 收缩 (字号+``\tabcolsep``, 组内设定 env 末自还原)。``deluxetable``
#: 跨页长表同理移此——0930 实证 env 成对钩在配对不候场面失衡
#: (``ended by`` 93 格), 长表族本就不许装箱。
_TAB_FLOW_ENVS = ("longtable", "supertabular", "mpsupertabular", "deluxetable")

#: 文本臂 (p{} 列声明/负 \hspace 剥除) 的表域跨度族——钩面 + 断页族 +
#: 旋转/包装容器 (内部才是出血站位)。
_TAB_SPAN_ENVS = frozenset(
    _TAB_BOX_ENVS
    + _TAB_FLOW_ENVS
    + ("sidewaystable", "sidewaysdeluxetable", "sidewaysfigure", "threeparttable")
)

_TAB_FLOW_ANY_RX = re.compile(
    r"\\begin\s*\{(?:" + "|".join(re.escape(e) for e in _TAB_FLOW_ENVS) + r")\}"
)


#: 成对钩残块整剥式 (marker 行 → 首个 ``\endgroup``)——in-place 再跑
#: fixloop 的稿面若带 v1 注块必须清掉, 否则成对钩继续毁编组。
#: inject 侧 ``TABLE_FITTING`` (compile/layout.py 0930 拔除注入) 在席稿
#: 同剥——``env/E/before+after`` 成对钩与文本跨度包并存即双压崩
#: (0930 普查: ``TabClamp ended by \end{TeXlateFitTable}`` 系 1080 事件)。
_LEGACY_CLAMP_RX = re.compile(
    r"% texlate(?:-fixloop)?: (?:table width clamp v1"
    r"|fit complete measured table containers[^\n]*)\n[\s\S]*?\\endgroup\n?"
)

#: 块边界失配形态的兜底行剥——成对钩注册行单删即拆解 (env 定义残壳
#: 无钩触发是死码无害)。
_LEGACY_HOOK_RX = re.compile(
    r"\\AddToHook\{env/[^}\n]+/(?:before|after)\}"
    r"\{\\(?:begin|end)\{TeXlate(?:FitTable|TabClamp)\}\}%?\n?"
)


def _strip_legacy_clamp(t: str) -> str:
    """剥成对钩钳宽残块——fixloop v1 注块 + inject TABLE_FITTING 块/散钩行。"""
    return _LEGACY_HOOK_RX.sub("", _LEGACY_CLAMP_RX.sub("", t))


#: 数学域 env 名单——``_env_spans`` 取跨。``array`` 仅数学内合法, 同收。
_MATH_ENVS = frozenset(
    {
        "math",
        "displaymath",
        "equation",
        "equation*",
        "align",
        "align*",
        "alignat",
        "alignat*",
        "xalignat",
        "xxalignat",
        "gather",
        "gather*",
        "multline",
        "multline*",
        "flalign",
        "flalign*",
        "eqnarray",
        "eqnarray*",
        "dmath",
        "dmath*",
        "dseries",
        "dgroup",
        "dgroup*",
        "array",
    }
)

#: 行内/展示数学域字面形——``$$`` 先配 (``$`` 单符会把它劈两半);
#: ``\$`` 转义与 ``$x$$`` 相邻形由 lookbehind/lookahead 挡。
_MATH_INLINE_RX = re.compile(
    r"\$\$[\s\S]*?\$\$"
    r"|(?<!\\)\$(?!\$)[\s\S]*?(?<!\\)\$(?!\$)"
    r"|\\\([\s\S]*?\\\)"
    r"|\\\[[\s\S]*?\\\]"
)


def _math_marks(vis: str) -> list[int]:
    r"""遮盖视图数学域合并边界列 (``_in_spans`` 直吃)。

    盒表 env 落数学内时 adjustbox 文本包会把 hbox 材料楔进数学模式
    (Missing $ 崩), 旧 TABLE_FITTING ``\ifmmode`` 臂的静态等价守卫。
    """
    spans = _env_spans(vis, _MATH_ENVS)
    spans.extend(m.span() for m in _MATH_INLINE_RX.finditer(vis))
    return _span_marks(spans)


def _tabular_snippet(flow_size: str) -> str:
    r"""表族钳宽前导块 v2: adjustbox 载备 + 可断页族 ``env/E/begin`` 收缩钩。

    可装箱族改走源级跨度包 (``_tabular_box_edits``)——``env/E/before+
    after`` 成对钩在 ``\\begin{E}`` 参数读取位前即注入, begin/end 配对
    不候场形 (cls 内部 ``\\@tabular``/宏内 env/跨名收尾) 即崩成
    ``ended by`` 失衡 (0930 普查 93 格实证), 钩面换成文本跨度包。
    可断页族钩只注组内参数, 无成对面包裹, 维持 ``env/E/begin`` 钩法。
    """
    lines = [
        "% texlate-fixloop: table width clamp v2",
        "\\usepackage{adjustbox}",
    ]
    lines.extend(
        f"\\AddToHook{{env/{e}/begin}}{{\\{flow_size}"
        "\\setlength{\\tabcolsep}{2pt}\\relax}%"
        for e in _TAB_FLOW_ENVS
    )
    return "\n".join(lines)


def _tabular_box_edits(t: str, state: dict[str, int]) -> tuple[str, int]:
    r"""最外层盒表 env 跨度 → ``adjustbox{max width,max totalheight}`` 文本包。

    跨度由 ``_env_spans`` 栈配对出 (残稿容错), 内嵌 env 一律弃跨——
    外层盒已罩住内层。紧邻前缀已带 ``\begin{adjustbox}`` 的跨度幂等跳过;
    ``lo`` 落数学域的跨度跳过 (``$\begin{tabular}$`` 内联形——盒材料
    楔进数学模式即崩, 旧 TABLE_FITTING ``\ifmmode`` 臂同款守卫)。
    """
    vis = mask_tex(t)
    spans = _env_spans(vis, frozenset(_TAB_BOX_ENVS))
    if not spans:
        return t, 0
    outer = [s for s in spans if not any(o[0] < s[0] < s[1] < o[1] for o in spans)]
    math = _math_marks(vis)
    edits: list[tuple[int, int, str]] = []
    n = 0
    for lo, hi in outer:
        if _in_spans(math, lo):
            continue  # 数学域内不包
        # 回看窗 ≥ 自注行全长 (``\begin{adjustbox}{max width=..,max
        # totalheight=..}\n`` ≈70B)——窗短于插入行会把 ``\begin`` 切断,
        # 幂等闸失效即叠包 (二跑 ``box-env wrapped x1`` 实证)。
        pre = vis[max(0, lo - 128) : lo]
        if re.search(r"\\begin\{adjustbox\}\s*\{[^}\n]*\}\s*$", pre):
            continue  # 已包 (幂等)
        edits.append(
            (
                lo,
                lo,
                "\\begin{adjustbox}{max width=\\linewidth,max totalheight=\\textheight}\n",
            )
        )
        edits.append((hi, hi, "\n\\end{adjustbox}"))
        n += 1
    if not edits:
        return t, 0
    state["box"] += n
    return _splice(t, edits), n


#: ``p{<dim>}`` 列声明里版心级宽度声明 —— ``\textwidth``/``\linewidth``/
#: ``\columnwidth`` 裸名或带系数的相对宽。组1=系数 (缺省视作 1.0);
#: ``p{0.8\linewidth}`` 这类本就合规的 (<0.95) 由系数门放行不动。
_PCOL_SPEC_RX = re.compile(
    r"p\{\s*(?:(\d+(?:\.\d+)?)\s*)?\\(?:textwidth|linewidth|columnwidth)\s*\}"
)
#: ``p{f\linewidth}`` 系数放行阈——本就缩进的列声明 (<0.95) 不动。
_PCOL_KEEP_FACTOR = 0.95


#: 表域内 ``\hspace{-<dim>}`` 收区 hack —— 排版期即盒溢出源 (1607.00323
#: 实证), 剥成空组 (负值才剥, 正间距无害留)。
_TAB_NEGHSPACE_RX = re.compile(
    r"\\hspace\*?\{-\s*\d+(?:\.\d+)?\s*(?:pt|pc|mm|cm|in|em|ex|bp|dd|cc|sp)\s*\}"
)

#: ``\begin{minipage}[opts]{<absdim>}`` —— 组1 数字组2 单位; 字体相对
#: 单位 (em/ex) 与 ``\linewidth`` 族不收 (abs-dim 门专用)。
_MINIPAGE_RX = re.compile(
    r"\\begin\s*\{minipage\}(?:\[[^\]\n]*\])*\s*\{\s*(\d+(?:\.\d+)?)\s*"
    r"(pt|pc|mm|cm|in|bp|dd|cc)\s*\}"
)
#: abs 单位 → pt 换算 (TeX 点制); bp/dd/cc 一并收。
_MINIPAGE_UNIT_PT = {
    "pt": 1.0,
    "pc": 12.0,
    "bp": 72.27 / 72.0,
    "in": 72.27,
    "cm": 72.27 / 2.54,
    "mm": 72.27 / 25.4,
    "dd": 1238.0 / 1157.0,
    "cc": 12.0 * 1238.0 / 1157.0,
}
#: minipage 钳门 = 160mm (~453.5pt)——单栏版心 ~470pt 上限, 两栏稿
#: ~240pt; ≥160mm 的字面绝对宽盒任何栏形都溢出 (0905.1250 200mm→329pt
#: 出血实证)。
_MINIPAGE_CLAMP_PT = 160.0 * 72.27 / 25.4

_MINIPAGE_ENV_RX = re.compile(r"\\(begin|end)\s*\{minipage\}")


def _tabular_text_edits(  # noqa: C901 -- 三臂顺序闸共一个 span/live 走查面
    t: str, state: dict[str, int]
) -> tuple[str, int]:
    r"""单文件表域/盒宽文本臂 → ``(nt, 编辑段数)``。

    1. 表族跨度内 ``p{\textwidth}`` 类列声明 → ``p{0.85\linewidth}``;
    2. 表族跨度内负 ``\hspace{-dim}`` 剥除;
    3. abs-dim ≥160mm ``minipage`` → ``adjustbox{max width=\linewidth}``
       外套 (fp minipage_clamp 折叠臂——adjustbox 包法对任意大值安全)。
    """
    vis = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    marks = _span_marks(_env_spans(vis, _TAB_SPAN_ENVS))
    n = 0
    if marks:
        for m in _PCOL_SPEC_RX.finditer(vis):
            f = m.group(1)
            if f is not None and float(f) < _PCOL_KEEP_FACTOR:
                continue  # 本就合规的缩进列声明不动
            if not (_in_spans(marks, m.start()) and _is_live(m, vis, t)):
                continue
            edits.append((m.start(), m.end(), "p{0.85\\linewidth}"))
            n += 1
        for m in _TAB_NEGHSPACE_RX.finditer(vis):
            if _in_spans(marks, m.start()) and _is_live(m, vis, t):
                edits.append((m.start(), m.end(), "{}"))
                n += 1
    # —— minipage abs-dim 钳 (全局面, 非表域限定) ——
    begins = [
        m
        for m in _MINIPAGE_RX.finditer(vis)
        if _is_live(m, vis, t)
        and float(m.group(1)) * _MINIPAGE_UNIT_PT[m.group(2)] >= _MINIPAGE_CLAMP_PT
    ]
    for bm in begins:
        depth = 0
        end_pos = None
        for tm in _MINIPAGE_ENV_RX.finditer(vis, bm.start()):
            depth += 1 if tm.group(1) == "begin" else -1
            if depth == 0:
                end_pos = tm.end()
                break
        if end_pos is None:
            continue
        edits.append(
            (
                bm.start(),
                bm.start(),
                "\\begin{adjustbox}{max width=\\linewidth,max totalheight=\\textheight}",
            )
        )
        edits.append((end_pos, end_pos, "\\end{adjustbox}"))
        n += 1
        state["minipage"] += 1
    if not edits:
        return t, 0
    return _splice(t, edits), n


def tabular_fit(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""warn_overfull 表族臂: 盒宽钳到 ``\linewidth`` 三面合修 (v2)。

    实证面 (qc wide_tabular 桶, 24 格): ``tabular{...}`` 超宽盒在浮体里
    出血无警告签名差异 (``in paragraph``/``in alignment`` 同收)。

    - **盒表源包臂** (v2): 最外层盒表 env 跨度文本级 ``adjustbox{max
      width=\linewidth,max totalheight=\textheight}`` 包——``env/E/before+
      after`` 成对钩法在 begin/end 配对不候场形 (cls ``\@tabular``/宏内
      env/跨名收尾) 崩成 ``ended by`` 失衡毁编 (0930 普查 ~1200 事件),
      换栈配对的文本跨度包; 数学域内跨度跳过 (``\ifmmode`` 臂等价守卫);
      fixloop v1 注块/inject TABLE_FITTING 块+散钩行在席整剥。
    - **断页族钩臂**: ``env/E/begin`` 局部 ``\<size>``/``\tabcolsep``
      收缩 (longtable/supertabular/deluxetable 跨页不可装箱),
      收缩档按本轮 log 最大 overfull 幅度选: ≥40pt ``\footnotesize``
      否则 ``\small``。
    - **文本臂**: 表域内 ``p{\textwidth}`` 列声明 → ``p{0.85\linewidth}``
      (2105.03891) + 负 ``\hspace`` 剥除 (1607.00323)。
    - **minipage 臂**: abs-dim ≥160mm ``\begin{minipage}`` 外套
      adjustbox (0905.1250 200mm 实证, fp minipage_clamp 同臂折叠)。

    只动排版面不遮警告 (``\hfuzz`` 不设——qc 证据面保留);
    verbatim/注释内同形 token 由遮盖视图天然豁免。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex",))
    state = {"minipage": 0, "box": 0}

    def _edits(t: str) -> tuple[str, int]:
        t2 = _strip_legacy_clamp(t)
        stripped = t2 != t
        t2, n_box = _tabular_box_edits(t2, state)
        t2, n_txt = _tabular_text_edits(t2, state)
        return t2, n_box + n_txt + (1 if stripped else 0)

    n_files = _map_tex_files(ctx, exts, _edits)
    blob = "\n".join(mask_tex(t) for f in ctx.tex_files(exts) if (t := ctx.read(f)))
    need_snippet = bool(
        state["box"] or state["minipage"] or _TAB_FLOW_ANY_RX.search(blob)
    )
    if not need_snippet:
        if n_files:
            return True, f"table-span edits in {n_files} file(s)"
        return False, "no table-family env / oversized minipage"
    mx = _max_overfull_pt(_fixloop_log(ctx))
    flow_size = "footnotesize" if mx >= 40.0 else "small"  # noqa: PLR2004 - 幅度档阈
    injected = _inject_before_begindoc(
        ctx, _tabular_snippet(flow_size), fallback="head"
    )
    parts: list[str] = []
    if injected:
        parts.append(f"adjustbox + flow-shrink @{flow_size}")
    if state["box"]:
        parts.append(f"box-env wrapped x{state['box']}")
    if n_files:
        parts.append(f"text edits in {n_files} file(s)")
    if state["minipage"]:
        parts.append(f"minipage wrapped x{state['minipage']}")
    if not parts:
        return False, "clamp block already present, no edits"
    return True, "; ".join(parts)


def legacy_clamp_purge(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""env_mismatch 自注成对钩残块整剥。

    inject ``TABLE_FITTING`` (compile/layout.py, 0930 拔除注入) 与
    fixloop v1 ``TeXlateTabClamp`` 注块并存/在席稿面走 ``ended by``
    失衡毁编; 源级跨度包不消费该签 (warn_overfull 驱动), 本臂专职
    中和 (0930 普查 ~1200 事件面)。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex",))

    def _strip(t: str) -> tuple[str, int]:
        t2 = _strip_legacy_clamp(t)
        return t2, 1 if t2 != t else 0

    n = _map_tex_files(ctx, exts, _strip)
    if not n:
        return False, "no legacy table-clamp block"
    return True, f"purged paired-hook clamp blocks in {n} file(s)"
