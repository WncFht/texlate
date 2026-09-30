r"""builtins.layoutfix — qc-wanted 版面/字符面修复原语 (impl-builtins lane)。

``warn_overfull`` 驱动的版面钳 builtin 族 (qc_replay 2026-09-27 普查):

- ``tabular_fit``: 表族盒宽钳到 ``\linewidth`` —— 源级跨度
  ``adjustbox{max width=\linewidth,max totalheight=\textheight}`` 包
  (inject 侧 ``TABLE_FITTING`` 成对钩法 0930 拔除后本 builtin 是表族
  钳宽唯一面) + 可断页表族 (longtable 系) env/begin 局部收缩
  + 列声明 ``p{\textwidth}``/表域负 ``\hspace``/绝对宽 minipage 文本臂。
- ``math_run_break``: 行内数学断点 penalty 清零 + para_loosen 强剂量。
- ``display_math_shrink``: 编号对齐族 env/before 字号+muskip 收缩 +
  ``$$``/``\[`` 无编号 display ``\adjustbox`` 包。
- ``gfx_width_clamp``: ``\includegraphics`` ``max width`` 钳 (adjustbox
  export 直通) + 相邻图组宽和收缩 + 字面超宽 ``width=N\linewidth`` 改写。
- ``fffd_context_fix``: 字面 U+FFFD 邻域分派替换 (CJK 间 ``{}``/页码
  ``--``/拉丁名断点 ``'``/``\'``/兜底 ``{}``) —— 替掉 char_table
  ``fffd_repl('-')`` 的无语境连字符 (``许-多``/``C-orcoles`` 错修实证)。

注册表接线在 ``builtins/__init__.py`` 门面 (``_LEAF_EXPORTS``/``_TRANSFORM_KEYS``/
``__all__``/TYPE_CHECKING 四表) —— 本叶只供函数本体, 名表合同即注册键。
"""

from __future__ import annotations

import re
from bisect import bisect_right
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import (
    _fixloop_log,
    _inject_before_begindoc,
    _is_live,
    _map_tex_files,
    _pkg_list_re,
    _splice,
)
from texlate.textutil import is_cjk_cp, mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx


# ════════════════════════════════════════════════════════════════
# 通用件: env 跨度 / overfull 幅度 / 编辑回放
# ════════════════════════════════════════════════════════════════

#: ``\begin{E}``/``\end{E}`` token 面——遮盖视图上扫 (注释/verbatim 内死命中
#: 天然不现)。星号名/连名 (``tableorg`` 等) 由各族名单放行。
_ENV_TOKEN_RX = re.compile(r"\\(begin|end)\s*\{([^}\s]+)\}")

#: ``Overfull \hbox (12.34pt too wide) ...`` 幅度数字组——_fixloop_log 上
#: 取 max 决定收缩档 (内联/对齐/段落三形态同收 ``\hbox``+``\vbox``)。
_OVF_PT_RX = re.compile(r"Overfull \\[hv]box \((\d+(?:\.\d+)?)pt too wide\)")


def _max_overfull_pt(log: str) -> float:
    """Log 里 Overfull box 最大出血点; 无 → 0.0。"""
    mx = 0.0
    for m in _OVF_PT_RX.finditer(log):
        mx = max(mx, float(m.group(1)))
    return mx


def _env_spans(vis: str, names: frozenset[str]) -> list[tuple[int, int]]:
    r"""遮盖视图内 ``names`` 族 env 的 ``(begin_start, end_end)`` 跨度表。

    ``\begin``/``\end`` token 序走查, 同名嵌套计深, 非配对 ``\end`` 容错
    出栈到匹配层 (残稿容忍, layout._demote_wrapfloats_text 同款骨架)。
    """
    spans: list[tuple[int, int]] = []
    stack: list[tuple[str, int]] = []
    for m in _ENV_TOKEN_RX.finditer(vis):
        tag, name = m.group(1), m.group(2)
        if tag == "begin":
            stack.append((name, m.start()))
            continue
        for i in range(len(stack) - 1, -1, -1):
            if stack[i][0] == name:
                if name in names:
                    spans.append((stack[i][1], m.end()))
                del stack[i:]
                break
    return spans


def _span_marks(spans: list[tuple[int, int]]) -> list[int]:
    """跨度表 → 合并区间的命中判定用边界列 (bisect 前缀和)。"""
    if not spans:
        return []
    spans = sorted(spans)
    merged: list[list[int]] = [[*spans[0]]]
    for lo, hi in spans[1:]:
        if lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    marks: list[int] = []
    for lo, hi in merged:
        marks.extend((lo, hi))
    return marks


def _in_spans(marks: list[int], pos: int) -> bool:
    """``pos`` 是否落在合并区间列内 (marks = 交错 lo/hi 边界列)。"""
    i = bisect_right(marks, pos)
    return i % 2 == 1


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


# ════════════════════════════════════════════════════════════════
# math_run_break —— 行内数学断点 penalty + 强剂量 (fp unbreakable_para_run)
# ════════════════════════════════════════════════════════════════

#: 断点清零注入块——``\relpenalty``/``\binoppenalty`` 归零使行内数学在
#: 关系符/二元符后可断 (集合记法/元组 run 的不可断死结面; 默认 500/700
#: 的软禁在长 run 里等价不可断)。
_MATHRUN_SNIPPET = (
    "% texlate-fixloop: math-run break hints\n"
    "\\relpenalty=0\\relax\n"
    "\\binoppenalty=0\\relax"
)

#: 强剂量——para_loosen 未注时随本块同注 (断不开的段落仍需三遍排版
#: 兜底); 已注走就地升级 (下方正则臂)。
_MATHRUN_STRONG = "\n\\emergencystretch=3em\\relax\n\\tolerance=9999\\relax"

#: ``para_loosen`` 注入块标记行 (builtins.misc._LOOSEN_SNIPPET 首行)——
#: 已注检出即升级剂量而非重注 (同位赋值后注后胜, 不叠注语义靠升级臂)。
_LOOSEN_MARK = "% texlate-fixloop: overfull-hbox mitigation"
_LOOSEN_UP_RX = (
    (re.compile(r"\\emergencystretch\s*=\s*[\d.]+em"), "\\emergencystretch=3em"),
    (re.compile(r"\\tolerance\s*=\s*\d+"), "\\tolerance=9999"),
)


def math_run_break(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""warn_overfull 行内数学臂: penalty 清零 + 强排版剂量。

    实证面 (qc unbreakable_para_run 桶, 24 格): ``$...$`` 长 run
    (set-builder/braket/pmatrix/tuple/CJK 混排) 无合法断点把词间 glue
    拉竭——``\relpenalty=0 \binoppenalty=0`` 放开关系/二元符后断点;
    ``\emergencystretch=3em \tolerance=9999`` 强剂量对 para_loosen
    已注格就地升级 (标记行检出), 未注格随本块同注——两条目同
    warn_overfull 驱动面不互抢 (同签共存稿各臂按序收)。

    ``\Big\{…\Big\}`` 单原子不可断格 (0806.2533 180pt 实证) 断点全缺
    本臂无解——promotion (overfull 内联数 → display) 未实装, 留
    known_gap。
    """
    del eng, payload, params
    main = ctx.main_path()
    if main is None:
        return False, "no main file"
    t = ctx.read(main)
    if t is None:
        return False, "main unreadable"
    parts: list[str] = []
    nt = t
    if _LOOSEN_MARK in nt:  # para_loosen 已注 → 就地升级强剂量
        for rx, rep_s in _LOOSEN_UP_RX:
            nt = rx.sub(rep_s, nt)
        if nt != t:
            ctx.write(main, nt)
            parts.append("loosen dose upgraded to tier2 (3em/9999)")
            t = nt
    if _MATHRUN_SNIPPET.split("\n", 1)[0] not in t:
        snippet = _MATHRUN_SNIPPET + ("" if _LOOSEN_MARK in t else _MATHRUN_STRONG)
        if _inject_before_begindoc(ctx, snippet, fallback="head"):
            parts.append(
                "injected \\relpenalty/\\binoppenalty=0"
                + ("" if _LOOSEN_MARK in t else " +tier2 stretch")
            )
    if not parts:
        return False, "math-run hints already present"
    return True, "; ".join(parts)


# ════════════════════════════════════════════════════════════════
# display_math_shrink —— 编号对齐族收缩 + 无编号 display 包钳
# ════════════════════════════════════════════════════════════════

#: 编号对齐族 env/before 收缩面——数学字号随环境外文本字号走 (钩在
#: ``before`` 即数学模式开启前注入, 组内设定 env 末自还原), 编号保留。
#: ``bea``/``displaymath`` 同收 (revtex/旧式简写族同名环境钩面)。
_DISP_SHRINK_ENVS = (
    "equation",
    "equation*",
    "eqnarray",
    "eqnarray*",
    "align",
    "align*",
    "gather",
    "gather*",
    "multline",
    "multline*",
    "flalign",
    "flalign*",
    "IEEEeqnarray",
    "IEEEeqnarray*",
    "dmath",
    "displaymath",
    "bea",
)

_DISP_ANY_RX = re.compile(
    r"\\begin\s*\{(?:"
    + "|".join(re.escape(e) for e in _DISP_SHRINK_ENVS)
    + r")\}|\$\$|\\\["
)


def _display_snippet(size: str) -> str:
    r"""编号对齐族 env/before 收缩钩块 + adjustbox 载备 (``$$``/``\[`` 臂用)。"""
    lines = [
        "% texlate-fixloop: display-math shrink v1",
        "\\usepackage{adjustbox}",
        "\\AtBeginDocument{%",
    ]
    lines.extend(
        f"\\AddToHook{{env/{e}/before}}{{\\{size}"
        "\\setlength{\\arraycolsep}{1.5pt}\\setlength{\\jot}{2pt}"
        "\\medmuskip=2mu\\thinmuskip=2mu\\thickmuskip=2mu\\relax}%"
        for e in _DISP_SHRINK_ENVS
    )
    lines.append("}")
    return "\n".join(lines)


#: 无编号 display 面包钳——``$$...$$`` 与 ``\[...\]`` 双形态。
#: ``[\s\S]*?`` 非贪配对 (``$$A$$ B $$C$$`` 逐对), 组1=body。
_DD_DOLLAR_RX = re.compile(r"\$\$([\s\S]*?)\$\$")
_DD_BRACKET_RX = re.compile(r"\\\[([\s\S]*?)\\\]")


def _display_wrap_edits(t: str) -> tuple[str, int]:
    r"""``$$``/``\[`` 体 → ``\[\adjustbox{max width=\linewidth}{$\displaystyle<body>$}\]``。

    adjustbox ``max width`` 只缩超宽者 (不拉宽小公式, resizebox 恒等宽
    不采); 体内 aligned/array 在 inline math 域照常 boxed。已有
    ``\adjustbox``/``\resizebox`` 的体不叠包 (幂等); <4 字符玩具体跳过。
    """
    vis = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    for rx in (_DD_DOLLAR_RX, _DD_BRACKET_RX):
        for m in rx.finditer(vis):
            body = t[m.start(1) : m.end(1)]
            if not body.strip():
                continue
            if "\\adjustbox" in body or "\\resizebox" in body:
                continue
            # 跨注释/逐字死区的命中剔除 (遮盖差 = 体穿 masked 区)
            if vis[m.start() : m.end()] != t[m.start() : m.end()]:
                continue
            rep = (
                "\\[\n\\adjustbox{max width=\\linewidth}{$\\displaystyle "
                + body
                + "$}\n\\]"
            )
            edits.append((m.start(), m.end(), rep))
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def display_math_shrink(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""warn_overfull display 数学臂: 编号族收缩 + 无编号包钳。

    实证面 (qc wide_display_math 桶, 21+1 格): ``detected at line N``
    签名 = display 超宽 (eqnarray/``\bea`` 8 格、align/equation、
    ``$$``-chain、flalign、IEEEeqnarray; 0707.2648 单列 210pt)。

    - **env/before 臂**: 编号对齐族钩 ``\<size>`` + ``\arraycolsep``/
      ``\jot``/muskip 收缩——诊断面 26-75pt/~470pt 溢出 ≈6-16%,
      ``\footnotesize`` (10-12%) + colsep 多够; ``params.size`` 可换
      ``scriptsize``。钩在 ``before`` (数学开启前) 使文本字号传导进
      数学度规——fp 行号→env 绑定的脆径不需要, 钩面全域生效。
    - **包钳臂**: ``$$...$$``/``\[...\]`` → ``\[\adjustbox{max width=
      \linewidth}{$\displaystyle ...$}\]``。

    ``\left/\right`` 单原子撑宽与 eqnarray→array 丢行号改写不采
    (known_gap 同 math_run_break 边界)。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex",))
    n_files = _map_tex_files(ctx, exts, _display_wrap_edits)
    size = str(params.get("size") or "footnotesize")
    blob = "\n".join(mask_tex(t) for f in ctx.tex_files(exts) if (t := ctx.read(f)))
    injected = False
    if _DISP_ANY_RX.search(blob) is not None:
        injected = _inject_before_begindoc(ctx, _display_snippet(size), fallback="head")
    parts: list[str] = []
    if injected:
        parts.append(f"env-shrink hooks injected @{size}")
    if n_files:
        parts.append(f"display wrapped in {n_files} file(s)")
    if not parts:
        return False, "shrink hooks already present, no wraps"
    return True, "; ".join(parts)


# ════════════════════════════════════════════════════════════════
# gfx_width_clamp —— includegraphics max width 钳 + 相邻图组收 + 字面超宽改写
# ════════════════════════════════════════════════════════════════

#: ``\includegraphics`` 调用点 (遮盖面)——组 ``opts`` 含括号。
_GFX_CALL_RX = re.compile(r"\\includegraphics\*?(?P<opts>\[[^\]\n]*\])?\s*\{[^}\n]*\}")

#: ``width=<f>\linewidth`` 族——f>1 即字面超宽 (pgfplots ``width=1.3
#: \linewidth`` 同收, 不只 \includegraphics 域)。
_RELWIDE_RX = re.compile(
    r"width\s*=\s*(\d+(?:\.\d+)?)\s*\\(linewidth|textwidth|columnwidth)"
)

#: 图间 glue 面——连续 ``\includegraphics`` 之间的合法间隙串 (空判用)。
_GFX_GLUE_RX = re.compile(
    r"^(?:[\s~]|\\hfill|\\hfil|\\hspace\*?\{[^}\n]*\}|\\quad|\\qquad|\\,)+$"
)

#: 并图组收窄阈——相邻图声明宽和 ≥0.98 才等比缩 (indent/glue 吃残量)。
_GFX_PAIR_SUM = 0.98
#: 组链下限——单图本就走 ``max width`` 单臂, 链臂只对 ≥2 成员生效。
_GFX_PAIR_MIN = 2


def _gfx_call_edits(t: str) -> tuple[str, int]:
    r"""逐 ``\includegraphics`` 追 ``max width=\linewidth`` (无 opts 补括号)。

    adjustbox ``export`` 使 ``max width`` 直接挂 graphics 键——只缩超
    限者, ``scale=``/height-only/无尺寸 EPS 均被兜底 (1906.00253/
    2609.19592/2504.15280 实证面)。已带 ``max width`` 的站不叠注。
    """
    vis = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    for m in _GFX_CALL_RX.finditer(vis):
        if not _is_live(m, vis, t):
            continue
        opts = m.group("opts")
        if opts and "max width" in opts:
            continue
        if opts:
            ins_at = m.end("opts") - 1
            sep = "," if opts[1:-1].strip() else ""
            edits.append((ins_at, ins_at, f"{sep}max width=\\linewidth"))
        else:
            # ``{file}`` 组前补 ``[max width=\linewidth]``
            brace = vis.rfind("{", m.start(), m.end())
            if brace >= 0:
                edits.append((brace, brace, "[max width=\\linewidth]"))
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def _gfx_pair_edits(t: str) -> tuple[str, int]:
    r"""相邻图组宽和 ≥0.98\linewidth → 各 ``width`` 系数按比缩到和 0.98。

    两图并排行 (``[width=0.5\textwidth]`` 对间仅 glue) 声明宽和顶格仍
    出血——indent/glue 吃掉残量 (1306.0563/2608.08891/1003.0851 实证);
    系数等比缩 (0.98/sum) 而非固定 0.49——三图组同臂吸收。链仅由
    glue 连排且**逐成员皆声明相对宽**的 ``\includegraphics`` 构成——
    无宽成员与 ``\\par``/空行隔断链 (未知自然宽在场则宽和不可信)。
    """
    vis = mask_tex(t)
    hits = [m for m in _GFX_CALL_RX.finditer(vis) if _is_live(m, vis, t)]
    edits: list[tuple[int, int, str]] = []
    run: list[tuple[re.Match[str], re.Match[str]]] = []

    def flush() -> None:
        if len(run) < _GFX_PAIR_MIN:
            run.clear()
            return
        total = sum(float(wm.group(1)) for _, wm in run)
        if total >= _GFX_PAIR_SUM:
            scale = _GFX_PAIR_SUM / total
            for m, wm in run:
                new_f = float(wm.group(1)) * scale
                new_s = f"{new_f:.3f}".rstrip("0").rstrip(".")
                edits.append(
                    (
                        m.start("opts") + wm.start(1),
                        m.start("opts") + wm.end(1),
                        new_s,
                    )
                )
        run.clear()

    prev_end: int | None = None
    for m in hits:
        glue_ok = False
        if prev_end is not None:
            glue = t[prev_end : m.start()]
            glue_ok = (
                "\n\n" not in glue
                and "\\par" not in glue
                and _GFX_GLUE_RX.match(glue) is not None
            )
        wm = _RELWIDE_RX.search(m.group("opts") or "")
        if not glue_ok or wm is None:
            flush()
        if wm is not None:
            run.append((m, wm))
            prev_end = m.end()
        else:
            prev_end = None  # 无宽成员断链——其后不得续链配对
    flush()
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def _gfx_relwide_edits(t: str) -> tuple[str, int]:
    r"""字面超宽 ``width=N\linewidth`` (N>1) → ``width=\linewidth``。

    pgfplots/tikz ``width=`` 键同收 (2504.07951 ``width=1.3\linewidth``
    实证)——相对宽 >1 在任何键域都是越版声明。
    """
    vis = mask_tex(t)
    edits = [
        (m.start(0), m.end(0), "width=\\linewidth")
        for m in _RELWIDE_RX.finditer(vis)
        if float(m.group(1)) > 1.0 and _is_live(m, vis, t)
    ]
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def _ensure_adjustbox_export(ctx: LoopCtx) -> bool:
    r"""工程内 adjustbox 装载点全数补 ``export`` 键; 无装载 → preamble 注一行。

    ``export`` 必须挂在**最先执行**的装载点上 (迟到的 ``[export]`` 装载
    撞 Option clash)——文件序≠执行序不可知, 故对一切活装载点并
    ``export`` (首个执行者带 export 后其余装载成子集幂等)。全树无装载
    才 ``\begin{document}`` 前自注 ``\usepackage[export]{adjustbox}``。
    """
    rx = _pkg_list_re("adjustbox")
    found = False
    for f in ctx.tex_files((".tex", ".sty", ".cls")):
        t = ctx.read(f)
        if t is None:
            continue
        masked = mask_tex(t)
        edits: list[tuple[int, int, str]] = []
        for m in rx.finditer(masked):
            if not _is_live(m, masked, t):
                continue
            found = True
            opts = m.group("opts_inner") or ""
            if re.search(r"(?:^|,)\s*export\s*(?=,|$)", opts):
                continue  # export 已在
            names = (m.group("before") or "") + "adjustbox" + (m.group("after") or "")
            new = (
                f"\\{m.group('cmd')}"
                f"[{opts + ',' if opts.strip() else ''}export]"
                f"{{{names}}}"
            )
            edits.append((m.start(), m.end(), new))
        if edits:
            ctx.write(f, _splice(t, edits))
    if found:
        return True
    return _inject_before_begindoc(
        ctx,
        "% texlate-fixloop: gfx width clamp\n\\usepackage[export]{adjustbox}",
        fallback="head",
    )


def gfx_width_clamp(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""warn_overfull 图形臂: ``\includegraphics`` ``max width`` 钳三面合修。

    实证面 (qc oversized_graphics 桶, 20 格): ``scale=0.66`` 巨图源
    (1906.00253)、``width=2\linewidth`` (2504.15280)、``0.5+0.5`` 对
    (1306.0563)、height-only (2609.19592)、pgfplots ``width=1.3
    \linewidth`` (2504.07951)。

    1. adjustbox ``export`` 键落实 (装载点补注或未载新注) → 逐
       ``\includegraphics`` 追 ``max width=\linewidth``;
    2. 相邻图组 (glue 连排 ≥2) 声明宽和 ≥0.98 → 等比缩到 0.98;
    3. 字面 ``width=N\linewidth`` (N>1) → ``width=\linewidth``。

    picture env 系统盒 (1306.0005) 非 ``\includegraphics`` 面——
    known_gap 留 tabular_fit/display 族分管。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex",))
    n_clamp = _map_tex_files(ctx, exts, _gfx_call_edits)
    n_pair = _map_tex_files(ctx, exts, _gfx_pair_edits)
    n_wide = _map_tex_files(ctx, exts, _gfx_relwide_edits)
    loaded = _ensure_adjustbox_export(ctx)
    parts: list[str] = []
    if n_clamp:
        parts.append(f"max-width clamp in {n_clamp} file(s)")
    if n_pair:
        parts.append(f"pair/group shrink in {n_pair} file(s)")
    if n_wide:
        parts.append(f"literal-wide rewrite in {n_wide} file(s)")
    if loaded and not parts:
        parts.append("adjustbox[export] ensured")
    if not parts:
        return False, "no \\includegraphics sites / clamp already present"
    return True, "; ".join(parts)


# ════════════════════════════════════════════════════════════════
# fffd_context_fix —— 字面 U+FFFD 邻域分派 (替 fffd_repl('-') 盲换)
# ════════════════════════════════════════════════════════════════

#: FFFD 连跑 (多字 mojibake 常连发, ``来\uFFFD\uFFFD级``) —— 整跑按
#: 双侧邻域一次替换, 不留 ``{}{}`` 串。
_FFFD_RUN_RX = re.compile("\\uFFFD+")


def _fffd_repl(before: str, after: str) -> str:
    r"""FFFD 跑双侧邻域 → 替换串。

    - CJK 夹 ``→ ``{}`` (``许多``→``许多`` 原字已失, 空组保 token 界);
    - 数字尾页码域 ``→ ``--`` (``91104``/``120C139`` en-dash 页域);
    - 拉丁字母夹 ``→ ``\'`` (后随小写, ``Corcoles``→``C\'orcoles``=
      Córcoles) / ``'`` (后随大写, ``DellAnna``→``Dell'Anna``——撇号
      断点非重音);
    - 单侧 CJK / emoji / hashtag / 兜底 ``→ ``{}``。
    """
    if before and after:
        b_cjk = is_cjk_cp(ord(before))
        a_cjk = is_cjk_cp(ord(after))
        if b_cjk and a_cjk:
            return "{}"
        if before.isdigit():
            return "--"
        if b_cjk or a_cjk:
            # CJK-拉丁混夹 (``isalpha`` 对 CJK 为真, 须在拉丁臂前分流)
            return "{}"
        if before.isalpha() and after.isalpha():
            return "'" if after.isupper() else "\\'"
    elif (before and is_cjk_cp(ord(before))) or (after and is_cjk_cp(ord(after))):
        return "{}"
    return "{}"


def _fffd_text_edits(t: str) -> tuple[str, int]:
    """单文件 FFFD 跑分派 (遮盖视图活位 only——注释/verbatim 内不动)。"""
    vis = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    for m in _FFFD_RUN_RX.finditer(vis):
        before = t[m.start() - 1] if m.start() else ""
        after = t[m.end()] if m.end() < len(t) else ""
        edits.append((m.start(), m.end(), _fffd_repl(before, after)))
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def fffd_context_fix(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""字面 U+FFFD 邻域分派替换 (vis_degenerate 桶, 10 格实证)。

    源档 FFFD = mojibake 残痕, 无语境 ``-`` 盲换 (char_table
    ``fffd_repl``) 产 ``许-多``/``C-orcoles`` 错修实证——邻域分派:

    - CJK 夹 ``{}``: 0812.1323 许多 / 1206.0210 存在 / 1206.5329 表明;
    - 数字尾 ``--``: 1107.0677 ``91104`` / 1812.00010 ``120C139``;
    - 拉丁夹 ``\'``/``'``: 1003.0894 ``DellAnna`` (大写随=撇号) /
      1306.2279 ``Corcoles`` (小写随=重音, 实面在 .bbl);
    - emoji/hashtag/兜底 ``{}``: 2501.16123 / 2302.00102 / 2409.11654。

    词法单源 ``mask_tex`` 遮盖面——注释/verbatim 内 FFFD 不动; 嵌
    PDF 轴标里的 FFFD 是非字面位 (figure 内嵌), 不在本臂面。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex", ".bbl", ".cls", ".sty"))
    n = _map_tex_files(ctx, exts, _fffd_text_edits)
    if not n:
        return False, "no literal U+FFFD in live surface"
    return True, f"context-dispatched U+FFFD runs in {n} file(s)"


# ════════════════════════════════════════════════════════════════
# section_skip_floor: \\@startsection 小正 afterskip 垫底 (qc-impl)
# ════════════════════════════════════════════════════════════════

#: ``\\@startsection{name}{lvl}{indent}{beforeskip}{afterskip}{style}``
#: 六参形 —— afterskip (第 5 参) 纯字面量捕获 (组 1 = 含花括整参,
#: 组 2 = 数值, 组 3 = 单位)。glue 形 (``1.5ex plus .2ex``) 与 cs 形
#: (``\\smallskipamount``) 不匹配本式, 天然不收。
_STARTSEC_RX = re.compile(
    r"\\@startsection\s*"
    r"\{[^{}]*\}\s*"  # name
    r"\{[^{}]*\}\s*"  # level
    r"\{[^{}]*\}\s*"  # indent
    r"\{[^{}]*\}\s*"  # beforeskip
    r"(\{\s*([0-9]*\.?[0-9]+)\s*([a-zA-Z]{2})\s*\})"  # afterskip 字面量
)

#: 单位 → pt 折算 (「小正」门近似值即可——ex/em 按 10pt 标准体估,
#: 误判域仅限 1.0–1.4 档 afterskip, 垫到 1.5ex 仍是无害小垫高)。
_DIMEN_PT: dict[str, float] = {
    "pt": 1.0,
    "bp": 1.00375,
    "pc": 12.0,
    "in": 72.27,
    "cm": 28.4528,
    "mm": 2.84528,
    "dd": 1.07,
    "cc": 12.84,
    "sp": 1.0 / 65536,
    "ex": 4.3,
    "em": 10.0,
}

#: afterskip 地板 (~1.4ex @10pt ≈ 6pt) 与目标值 —— sig-alternate.cls
#: 4pt 实证在闸内 (1503.00038: fandol CJK extents 下标题贴正文)。
_AFTERSKIP_FLOOR_PT = 6.0
_AFTERSKIP_TARGET = "{1.5ex}"


def _section_skip_floor_text(t: str) -> tuple[str, int]:
    vis = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    for m in _STARTSEC_RX.finditer(vis):
        num, unit = m.group(2), m.group(3).lower()
        factor = _DIMEN_PT.get(unit)
        if factor is None:
            continue  # mu/陌生单位不动
        pt = float(num) * factor
        if not 0 < pt < _AFTERSKIP_FLOOR_PT:
            continue  # 负值本不匹配 (regex 无 - 位); 零/已足高跳过
        edits.append((m.start(1), m.end(1), _AFTERSKIP_TARGET))
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def section_skip_floor(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""cls/sty ``\\@startsection`` 小正 afterskip (0 < x < ~1.4ex) → ``1.5ex``。

    实证 (qc-impl 2026-09-28, 1503.00038): ``sig-alternate.cls:1009``
    ``\\@startsection{section}...{4pt}`` —— afterskip 4pt 在 fandol CJK
    extents 下标题贴正文 (``geo_text_overlap``, 600dpi seam 0 白行)。
    编译 clean 无 log 签名, 唯 precheck ``always`` 面可达。负值
    (run-in 标题有意设计) 与 glue/cs 形不收——只动纯字面量。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".cls", ".sty", ".tex"))
    n = _map_tex_files(ctx, exts, _section_skip_floor_text)
    if not n:
        return False, r"no small positive \@startsection afterskip"
    return True, f"afterskip floored to 1.5ex in {n} file(s)"
