"""tests/xlat/test_resid_sweep.py — ``xlat.resid`` zh 树残英清扫的出货闸件。

覆盖三面：

- ``find_resid_spans`` 抽取面：tabular 胞格/顶层散文/include 盲区文件
  内正文、括号内联、空行分段、80 列折行整段；豁免面 math 域/文献体/
  verbatim 族/注释/tech/人名/ident-list；
- ``_clean_zh`` 清理闸：零 CJK/结构符回译弃置；
- ``sweep_tree`` 端到端：就地回写保结构件、跨文件去重一次烧、缓存命中
  免烧、败者留英文不毁树。
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

import pytest

from texlate.textutil.nets import _RESID_EN_MIN_LATIN
from texlate.xlat.resid import (
    _CACHE_ROLE,
    _clean_zh,
    find_resid_spans,
    sweep_tree,
)
from texlate.xlat.state import segment_key

if TYPE_CHECKING:
    from pathlib import Path

_EN = "This is a sufficiently long English sentence inside the table cell"
_EN2 = "Another distinct English run that also lives inside the float body"


def _tab(inner: str) -> str:
    return (
        "\\begin{table}\n\\centering\n\\begin{tabular}{ll}\n"
        f"{inner}\n\\end{{tabular}}\n\\end{{table}}\n"
    )


def test_spans_tabular_cell() -> None:
    t = _tab(f"Foo & {_EN} \\\\")
    (spans,) = find_resid_spans(t)
    start, end, run = spans
    assert run == _EN
    assert t[start:end] == _EN


def test_spans_nested_env_inner_cells() -> None:
    t = _tab(f"A & {_EN} \\\\\nB & {_EN2} \\\\")
    runs = [r for _s, _e, r in find_resid_spans(t)]
    assert runs == [_EN, _EN2]


def test_spans_toplevel_prose() -> None:
    """resolver 盲 include 文件的顶层散文——残英第三形态的正主。"""
    t = f"\\section{{Merkle Tree}}\\label{{sec::mt}}\n\n{_EN}\n\n{_EN2}\n"
    runs = [r for _s, _e, r in find_resid_spans(t)]
    assert runs == [_EN, _EN2]


def test_spans_brace_interior() -> None:
    t = _tab(f"\\multicolumn{{2}}{{c}}{{{_EN}}} \\\\")
    runs = [r for _s, _e, r in find_resid_spans(t)]
    assert runs == [_EN]


def test_spans_itemize_body() -> None:
    t = f"\\begin{{itemize}}\n\\item {_EN}\n\\end{{itemize}}\n"
    runs = [r for _s, _e, r in find_resid_spans(t)]
    assert runs == [_EN]


def test_spans_comment_masked() -> None:
    t = _tab(f"% {_EN}\nA & ok \\\\")
    assert find_resid_spans(t) == []


def test_spans_verbatim_env_masked() -> None:
    t = (
        "\\begin{verbatim}\n"
        "This English code comment must never be translated at all ever.\n"
        "\\end{verbatim}\n"
    )
    assert find_resid_spans(t) == []


def test_spans_inline_verb_masked() -> None:
    t = f"正文 \\verb|{_EN}| 已译。\n"
    assert find_resid_spans(t) == []


def test_spans_bibliography_excluded() -> None:
    t = (
        "\\begin{thebibliography}{9}\n"
        "\\bibitem{x} A. Author, This is a very long English title that must "
        "stay English forever.\n"
        "\\end{thebibliography}\n"
    )
    assert find_resid_spans(t) == []


def test_spans_unclosed_bib_to_eof() -> None:
    t = f"\\begin{{thebibliography}}{{9}}\n\\bibitem{{x}} {_EN}\n"
    assert find_resid_spans(t) == []


def test_spans_math_env_excluded() -> None:
    t = (
        "\\begin{equation}\n"
        "x = \\text{a very long English clause living inside math mode here}\n"
        "\\end{equation}\n"
    )
    assert find_resid_spans(t) == []


def test_spans_inline_math_excluded() -> None:
    t = (
        "where $\\sigma \\text{ denotes a quite long English explanation here }$ "
        "and $x$ 已译。\n"
    )
    assert find_resid_spans(t) == []


def test_spans_display_math_excluded() -> None:
    t = "\\[ y = \\text{another long English clause inside display math mode} \\]\n"
    assert find_resid_spans(t) == []


def test_spans_tech_run_exempt() -> None:
    tech = "scipy.optimize.minimize(method='bfgs') returns res.x[0] = 1.5e-4"
    assert _latin_ok(tech)
    t = _tab(f"A & {tech} \\\\")
    assert find_resid_spans(t) == []


def test_spans_name_list_exempt() -> None:
    names = "John von Neumann, Alan Turing, Claude Shannon, Donald Knuth"
    t = _tab(f"A & {names} \\\\")
    assert find_resid_spans(t) == []


def test_spans_ident_list_exempt() -> None:
    ids = "atexit, builtins, functools, itertools, operator, signal, sys"
    t = _tab(f"A & {ids} \\\\")
    assert find_resid_spans(t) == []


def test_spans_para_boundary_splits() -> None:
    body = f"\\parbox{{5cm}}{{{_EN}\n\n{_EN2}}}"
    t = _tab(f"A & {body} \\\\")
    runs = [r for _s, _e, r in find_resid_spans(t)]
    assert runs == [_EN, _EN2]


def test_spans_wrapped_line_kept_whole() -> None:
    wrapped = "This is a long wrapped sentence that continues\non the next line inside the same cell"
    t = _tab(f"A & {wrapped} \\\\")
    (spans,) = find_resid_spans(t)
    assert spans[2] == wrapped


def test_spans_unclosed_nonexcl_env_scans() -> None:
    """未闭合的非排除 env——体文照常扫描（tabular 不在排除名单）。"""
    t = f"\\begin{{tabular}}{{l}}\n{_EN}\n"
    runs = [r for _s, _e, r in find_resid_spans(t)]
    assert runs == [_EN]


def test_spans_short_run_under_threshold() -> None:
    t = _tab("A & short en text \\\\")
    assert find_resid_spans(t) == []


def test_spans_short_cell_tier2() -> None:
    """短胞格档——QC 渲染行口径下的数据表短语（1906.00256 实测主块）。"""
    short_cells = [
        "No NIR excess, PMS in CMD and CCD",
        "Kinematic outlier, PMS in CMD",
        "Eclipsing feature in the phased light curve",
        "On the CTT locus in CCD, PMS in RI CMD",
    ]
    for cell in short_cells:
        t = _tab(f"A & {cell} \\\\")
        runs = [r for _s, _e, r in find_resid_spans(t)]
        assert runs == [cell], cell


def test_spans_short_cell_tier2_cite_keys_rejected() -> None:
    """键值型命令参数整段排除——``\\citep`` 键串从源头不进 run。"""
    t = _tab("A & \\citep{smith, jones, taylor, brown} \\\\")
    assert find_resid_spans(t) == []
    t = _tab("A & \\citep{aa2008, bb2010, cc2015, dd2017} \\\\")
    assert find_resid_spans(t) == []
    t = _tab("A & \\eqref{eq:mass}, \\label{sec:obs}, \\url{https://x.y/a-b} \\\\")
    assert find_resid_spans(t) == []


def test_spans_short_cell_tier2_lowercase_prose_kept() -> None:
    """全小写真散文放行——小写闸只管逗号单字段键串形。"""
    t = _tab("A & and even more prose here \\\\")
    runs = [r for _s, _e, r in find_resid_spans(t)]
    assert runs == ["and even more prose here"]


def test_spans_short_cell_tier2_lowercase_keylist_rejected() -> None:
    """逗号单字段全小写清单=漏网 cite 键串形拒收（白名单外的键串兜底）。"""
    t = _tab("A & smith, jones, taylor, brown \\\\")
    assert find_resid_spans(t) == []


def test_spans_short_cell_tier2_verbatim_header_exempt() -> None:
    """表头全大写短胞格——``_keep_verbatim_run`` 豁免照管。"""
    t = _tab("A & ID Band MJD Mag Error \\\\")
    assert find_resid_spans(t) == []


def test_spans_inline_math_boundary_not_bridged() -> None:
    """遮盖区是硬边界——混排胞格的 span 不得吞掉原始 ``$..$`` 坐标。

    ``Low-amplitude $\\sim 0.05$ mag in $VRI$`` 类：桥接形 span 回写会
    把 ``\\sim``/``$VRI$`` 原式吃掉（成品损毁），哨兵切开后只留两侧
    碎片（欠阈自然弃收）。
    """
    t = _tab(
        "A & Low-amplitude $\\sim 0.05$ mag in $VRI$, quite long English "
        "run after math \\\\"
    )
    runs = [r for _s, _e, r in find_resid_spans(t)]
    assert runs == ["quite long English run after math"]


def test_spans_comment_boundary_not_bridged() -> None:
    """``%`` 注释遮区同哨兵——行尾注释坐标不进 span，``\\citep`` 类注释内件不丢。"""
    t = "This is a sufficiently long English clause here % keep \\citep{x}\nA & ok \\\\"
    (spans,) = find_resid_spans(_tab(t))
    _s, _e, run = spans
    assert run == "This is a sufficiently long English clause here"
    assert "%" not in run


def test_spans_verb_boundary_not_bridged() -> None:
    r"""``\verb|x-y|`` 遮区断开——桥接回写会吃掉可见 ``x-y`` 文本。"""
    t = _tab(
        "A & This is a long English clause \\verb|x-y| and even more prose here \\\\"
    )
    runs = [r for _s, _e, r in find_resid_spans(t)]
    assert runs == [
        "This is a long English clause",
        "and even more prose here",
    ]


def test_spans_pgfkeys_options_masked() -> None:
    r"""``\addplot[...]`` 键表——键名翻中文即 ``key_unknown``（2609.20069 实证）。"""
    t = (
        "\\addplot[only marks, mark=triangle*, mark options={fill=white}, "
        "color=AttackSpeculative, mark size=2.6pt, line width=1.1pt] "
        "table {data.dat};\n"
    )
    assert find_resid_spans(t) == []


def test_spans_axis_env_options_masked() -> None:
    r"""``\begin{axis}[...]`` 键表同罩；``xlabel={散文值}`` 的值域照常可译。"""
    t = (
        "\\begin{axis}[scale only axis, width=0.8\\textwidth, "
        "xlabel={A very long english axis label}, xmode=log]\n"
        "\\addplot {x};\n\\end{axis}\n"
    )
    runs = [r for _s, _e, r in find_resid_spans(t)]
    assert runs == ["A very long english axis label"]


def test_spans_tikz_draw_boolean_keys_masked() -> None:
    """无 ``=`` 的纯布尔键表——全短键多段仍按键表面罩。"""
    t = "\\draw[thick, rounded corners, dashed] (0,0) -- (1,1);\n"
    assert find_resid_spans(t) == []


def test_spans_item_label_prose_not_masked() -> None:
    r"""``\item[标签]`` 是散文不是键表——豁免面罩照常译。"""
    t = "\\begin{description}\n\\item[At test time, the defender wins] 正文。\n\\end{description}\n"
    runs = [r for _s, _e, r in find_resid_spans(t)]
    assert runs == ["At test time, the defender wins"]


def test_spans_caption_short_prose_not_masked() -> None:
    r"""``\caption[短题]`` 同豁免——短题是面向读者的散文。"""
    t = "\\caption[Short english caption for the list of figures]{Long cap}\n"
    runs = [r for _s, _e, r in find_resid_spans(t)]
    assert runs == ["Short english caption for the list of figures"]


def test_spans_tikzset_brace_arg_masked() -> None:
    r"""``\tikzset{}``/``\pgfplotsset{}`` 括号键表整段罩。"""
    t = "\\tikzset{every mark/.append style={fill=white}}\n"
    assert find_resid_spans(t) == []
    t = "\\pgfplotsset{compat=1.18}\n"
    assert find_resid_spans(t) == []


def test_spans_linebreak_optarg_not_masked() -> None:
    r"""``\\[2pt]`` 断行可选参不是键表——数字键名不符形不罩。"""
    t = _tab("A & text \\\\[2pt]\n")
    assert find_resid_spans(t) == []


def test_spans_multiline_axis_options_masked() -> None:
    r"""跨行 ``\begin{axis}[\n scale only axis,\n width=...``——2609.20069 逃脱形。"""
    t = (
        "\\begin{axis}[\n"
        "  scale only axis,\n"
        "  width=0.85\\linewidth,\n"
        "  height=0.36\\linewidth,\n"
        "]\n\\addplot {x};\n\\end{axis}\n"
    )
    assert find_resid_spans(t) == []


def test_spans_style_nested_keylist_masked() -> None:
    r"""``.style={键表}`` 值自身是键表——只罩键名会让内层键漏扫（chip 实证）。"""
    t = (
        "\\begin{tikzpicture}[chip/.style={rounded corners=2pt, "
        "inner sep=3pt, font=\\scriptsize, align=left}]\n"
        "\\node[chip] {已译};\n\\end{tikzpicture}\n"
    )
    assert find_resid_spans(t) == []


def test_spans_tikzset_nested_braces_masked() -> None:
    r"""``\tikzset{...}`` 嵌套花括号配对吃全参——扁平 ``[^}]*`` 只到首个 ``}``。"""
    t = (
        "\\tikzset{box/.style={draw=black!30, rounded corners=3pt, "
        "align=left, inner sep=5pt},\n"
        "chip/.style={rounded corners=2pt, inner sep=3pt, font=\\scriptsize}}\n"
    )
    assert find_resid_spans(t) == []


def test_spans_pgfqkeys_two_args_masked() -> None:
    r"""``\pgfqkeys{/tikz}{keys}`` 双参都吃。"""
    t = "\\pgfqkeys{/tikz}{scale only axis, rounded corners}\n"
    assert find_resid_spans(t) == []


def test_spans_axis_xlabel_value_still_translated() -> None:
    r"""``xlabel={散文}`` 值不是键表——罩键名留值域照常译。"""
    t = (
        "\\begin{axis}[\n  scale only axis,\n  width=0.8\\textwidth,\n"
        "  xlabel={A very long english axis label},\n]\n\\end{axis}\n"
    )
    runs = [r for _s, _e, r in find_resid_spans(t)]
    assert runs == ["A very long english axis label"]


def test_spans_hypersetup_masked() -> None:
    r"""``\hypersetup{pdftitle={...}}`` 嵌套参全罩——元数据留英合法。"""
    t = "\\hypersetup{pdftitle={A very long english document title}}\n"
    assert find_resid_spans(t) == []


def test_spans_axis_code_value_inner_bracket_masked() -> None:
    r"""``.code={\draw[#1] ...}`` 内层括号截断扁平 ``[^\[\]]*``——v1.5 实证逃逸。

    整表 ``\begin{axis}[...]`` 因值域内 ``[#1]`` 匹配失败而全漏；配对扫
    +code 键值整段哨兵后只剩 ``ylabel={散文}`` 值域可译。
    """
    t = (
        "\\begin{axis}[\n"
        "  scale only axis,\n"
        "  width=0.88\\linewidth,\n"
        "  ylabel={Median attack success rate across all models},\n"
        "  symbolic x coords={Narwhal,Bullshark,Mysticeti},\n"
        "  legend image code/.code={\\draw[#1] (0cm,-0.06cm) rectangle "
        "(0.18cm,0.10cm);},\n"
        "  axis y line*=left,\n"
        "]\n\\addplot {x};\n\\end{axis}\n"
    )
    runs = [r for _s, _e, r in find_resid_spans(t)]
    joined = "\n".join(runs)
    assert "scale only axis" not in joined
    assert "rectangle" not in joined
    assert "legend image code" not in joined
    assert "symbolic" not in joined
    assert any("Median attack success rate" in r for r in runs)


def test_spans_axis_code_key_unbraced_value_masked() -> None:
    r"""``.code`` 键无 ``{}`` 包裹值也整段罩——code 键名本身就是暗语。"""
    t = "\\begin{axis}[legend image code/.code=\\draw rectangle;, ymin=0]\n\\end{axis}\n"
    runs = [r for _s, _e, r in find_resid_spans(t)]
    joined = "\n".join(runs)
    assert "rectangle" not in joined
    assert "legend image code" not in joined


def test_spans_axis_label_key_not_codeword() -> None:
    r"""``xlabel`` 以 ``label`` 结尾但不是 code 键——散文值域照常可译。"""
    t = (
        "\\begin{axis}[xlabel={A very long english axis label}, "
        "label={fig:internal}, ymin=0]\n\\end{axis}\n"
    )
    runs = [r for _s, _e, r in find_resid_spans(t)]
    assert runs == ["A very long english axis label"]


def test_spans_node_anchor_enum_value_masked() -> None:
    r"""``anchor=north west`` 非 ``{}`` 包裹枚举值——v1.5 实证桥接损毁。

    值域留可见面时 ``north west] (codebases) at (0,0`` 汇成 run 整段被翻，
    节点名/``]``/坐标全灭（``codebases.east`` 悬空）。整段哨兵后尾巴
    碎片不足阈值自然弃收。
    """
    t = (
        "\\node[box, fill=cbSky!15, text width=7.4cm, anchor=north west] "
        "(codebases) at (0,0)\n  {\\textbf{Instrumented codebases.} 已译正文};\n"
        "\\draw[side] (codebases.east) -- (env.west);\n"
    )
    runs = [r for _s, _e, r in find_resid_spans(t)]
    joined = "\n".join(runs)
    assert "codebases" not in joined
    assert "north west" not in joined


def _latin_ok(s: str) -> bool:
    lat = sum(1 for c in s if c.isascii() and c.isalpha())
    return lat >= _RESID_EN_MIN_LATIN


def test_clean_zh_gates() -> None:
    assert _clean_zh("  你好，世界  ") == "你好，世界"
    assert _clean_zh("pure english no cjk") is None
    assert _clean_zh("中文带{结构}符") is None
    assert _clean_zh("中文夹[[PH_1]]占位") is None
    assert _clean_zh("中文带\\cmd 命令") is None
    assert _clean_zh("") is None


class _MapTranslator:
    """查表型 translator——miss 记 None 形，raise_map 注入败者臂。"""

    def __init__(self, table: dict[str, str], raise_on: set[str] | None = None) -> None:
        self.table = table
        self.raise_on = raise_on or set()
        self.calls: list[str] = []

    async def translate(
        self,
        *,
        system: str,  # noqa: ARG002 -- 协议形参伪件不消费
        user: str,
        temperature: float,  # noqa: ARG002 -- 协议形参伪件不消费
        max_tokens: int,  # noqa: ARG002 -- 协议形参伪件不消费
    ) -> str:
        self.calls.append(user)
        if user in self.raise_on:
            msg = f"boom:{user[:20]}"
            raise RuntimeError(msg)
        return self.table.get(user, "未映射兜底译文")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def test_sweep_rewrites_in_place(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text(_tab(f"Foo & {_EN} \\\\"), encoding="utf-8")
    tr = _MapTranslator({_norm(_EN): "这是一段足够长的中文译文占位"})
    m = asyncio.run(sweep_tree(tmp_path, tr))
    out = tex.read_text(encoding="utf-8")
    assert "这是一段足够长的中文译文占位" in out
    assert "Foo &" in out
    assert "\\\\" in out
    assert "\\begin{tabular}" in out
    assert _EN not in out
    assert m["replaced"] == 1
    assert m["calls"] == 1


def test_sweep_dedup_across_files(tmp_path: Path) -> None:
    for name in ("a.tex", "b.tex"):
        (tmp_path / name).write_text(_tab(f"A & {_EN} \\\\"), encoding="utf-8")
    tr = _MapTranslator({_norm(_EN): "同一句中文译文"})
    m = asyncio.run(sweep_tree(tmp_path, tr))
    two = 2
    assert m["uniq"] == 1
    assert m["calls"] == 1
    assert m["replaced"] == two
    assert len(tr.calls) == 1


def test_sweep_zero_cjk_rejected(tmp_path: Path) -> None:
    tex = tmp_path / "m.tex"
    raw = _tab(f"A & {_EN} \\\\")
    tex.write_text(raw, encoding="utf-8")
    tr = _MapTranslator({_norm(_EN): "still english output"})
    m = asyncio.run(sweep_tree(tmp_path, tr))
    assert m["kept_en"] == 1
    assert tex.read_text(encoding="utf-8") == raw


def test_sweep_structchar_rejected(tmp_path: Path) -> None:
    tex = tmp_path / "m.tex"
    raw = _tab(f"A & {_EN} \\\\")
    tex.write_text(raw, encoding="utf-8")
    tr = _MapTranslator({_norm(_EN): "译文带{花括号}"})
    m = asyncio.run(sweep_tree(tmp_path, tr))
    assert m["kept_en"] == 1
    assert tex.read_text(encoding="utf-8") == raw


def test_sweep_translator_error_kept(tmp_path: Path) -> None:
    tex = tmp_path / "m.tex"
    raw = _tab(f"A & {_EN} \\\\")
    tex.write_text(raw, encoding="utf-8")
    tr = _MapTranslator({}, raise_on={_norm(_EN)})
    m = asyncio.run(sweep_tree(tmp_path, tr))
    assert m["kept_en"] == 1
    assert tex.read_text(encoding="utf-8") == raw


def test_sweep_cache_hit_skips_call(tmp_path: Path) -> None:
    tex = tmp_path / "m.tex"
    tex.write_text(_tab(f"A & {_EN} \\\\"), encoding="utf-8")
    key = segment_key(_EN, _CACHE_ROLE)
    cache = {key: "缓存里的中文译文"}
    tr = _MapTranslator({})
    m = asyncio.run(sweep_tree(tmp_path, tr, cache=cache))
    assert m["cache_hits"] == 1
    assert m["calls"] == 0
    assert tr.calls == []
    assert "缓存里的中文译文" in tex.read_text(encoding="utf-8")


def test_sweep_cache_store_on_miss(tmp_path: Path) -> None:
    (tmp_path / "m.tex").write_text(_tab(f"A & {_EN} \\\\"), encoding="utf-8")
    cache: dict = {}
    tr = _MapTranslator({_norm(_EN): "新译中文"})
    asyncio.run(sweep_tree(tmp_path, tr, cache=cache))
    assert segment_key(_EN, _CACHE_ROLE) in cache


def test_sweep_empty_tree(tmp_path: Path) -> None:
    (tmp_path / "m.tex").write_text("全中文无保护区。\n", encoding="utf-8")
    tr = _MapTranslator({})
    m = asyncio.run(sweep_tree(tmp_path, tr))
    assert m["files"] == 0
    assert m["spans"] == 0
    assert tr.calls == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
