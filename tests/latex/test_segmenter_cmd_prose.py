r"""``[[CMD]]`` 臂散文参挖掘钉版 —— ``_handle_unknown_cs`` 探针臂 +
``_handle_argspec_cs`` protect/key（+in_arg boundary）臂逐参散文门控。

背景：宏表/argspec 表双未中的未知命令走投机探针（``[o]{m}``×6、禁单
token 参），任一参消费即整调用折进单个 ``[[CMD_n]]``——花括号参里的
散文整块蒸发不进 chunk（1803.00127 ``\@maketitle{\begin{figure}…
\caption{…}`` 标题块 555B 全灭；corpus 扫描另见 ``\acks``/
``\titlerunning``/``\texorpdfstring``/``\shortstack`` 同型）。argspec
签名臂同型：``\marginpar``/``\abstract``/``\frame``/``\only`` 等 protect
条目的散文参同塌缩。

修法（本文件钉住的语义，与 ``_handle_opaque_macro`` 散文挖掘同形）：

- 消费参逐参过 scout 散文判据（剔注释+cs 后 ≥4 连词、非全大写）——
  命中即抠出 ``[[CMD]]`` 覆盖、内容子扫渲进 run surface；命令名段与
  非散文参、散文参两侧花括号所在结构段仍 opaque 原文。
- 非 ``{``/``[``-open 参（``d<>``/``e``/``r()``/``t``/单 token——探针本
  不收后者）、跨 fid 组、未消费占位不挖；``[``-open 可选参散文同挖
  （``\subfigure[长 caption]{..}`` 面，L8 SEGB 放开——``[width=2cm]``/
  ``[see]`` 由 keyval/词链门挡住）；``gen >= MAX_GEN`` 回压维持整调用
  opaque + ``gen_overflow`` 告警。
- ``key=`` 起头的 keyval 组不挖——``{pdftitle={长标题}}`` 值内散文会连
  键位一起抬进译文面（``\setkeys`` 炸面，``_keyval_tail_end`` 同款形状门）。
- 零消费照旧回吐逐字（``\foo x`` 的 ``x`` 是正文不是参——泄漏机制 A）。

每条用例过公共不变式：``reconstruct(res) == tex`` + ``validate_result``
零告警 + pieces 无缝平铺。
"""

from _segkit import (
    KEY,
    PROSE,
    cmd_bodies,
    nested_probe_call,
    ph_bodies,
)
from _segkit import (
    scan_art as scan,
)
from conftest import blob

#: beamer 包条目（``\only``/``\onslide``）——argspec 表不按包门控后
#: docclass 不再 load-bearing：同名 cs 在 article 下也走 argspec 臂。
BEAMER = "\\documentclass{beamer}\n%s\\begin{document}\n%s\n\\end{document}\n"


def test_probe_prose_arg_surfaces() -> None:
    r"""``\unknowncmd{prose}``：散文参进 chunk surface，``\unknowncmd{``/``}`` 留 CMD ph。"""
    res = scan(f"\\unknowncmd{{{PROSE}.}}")
    assert PROSE in blob(res)
    bodies = cmd_bodies(res)
    assert "\\unknowncmd{" in bodies
    assert "}" in bodies
    assert all(PROSE not in b for b in bodies)


def test_probe_key_arg_stays_opaque() -> None:
    r"""``\unknowncmd{cite-key}`` 非散文参：整调用单 CMD ph，参不外流。"""
    res = scan(f"\\unknowncmd{{{KEY}}} Tail prose words keep flowing here.")
    bodies = cmd_bodies(res)
    assert f"\\unknowncmd{{{KEY}}}" in bodies
    assert KEY not in blob(res)


def test_probe_opt_arg_prose_lifted() -> None:
    r"""``[``-open 可选参散文同挖（L8 SEGB 放开）：opt 散文出 surface，
    ``\\unknowncmd[``/``]{key}`` 结构段留 CMD——``{key}`` 参仍不外流。"""
    res = scan(
        "\\unknowncmd[optional words with several terms here]"
        f"{{{KEY}}} Tail prose keeps flowing."
    )
    text = blob(res)
    assert "optional words with several terms" in text
    assert KEY not in text
    bodies = cmd_bodies(res)
    assert "\\unknowncmd[" in bodies
    assert all("optional" not in b for b in bodies)


def test_probe_opt_arg_keyval_not_lifted() -> None:
    r"""``[o]`` 参装 keyval（``[width=2cm]``）不过形状门——整调用 opaque。"""
    res = scan(
        "\\unknowncmd[width=2cm and height=3cm]"
        f"{{{KEY}}} Tail prose keeps flowing here."
    )
    bodies = cmd_bodies(res)
    whole = f"\\unknowncmd[width=2cm and height=3cm]{{{KEY}}}"
    assert whole in bodies
    assert "height" not in blob(res)


def test_probe_second_arg_prose_first_key() -> None:
    r"""``\unknowncmd{key}{prose}`` 逐参判定：key 参留 CMD，散文参出 surface。"""
    res = scan(f"\\unknowncmd{{{KEY}}}{{{PROSE}.}}")
    assert PROSE in blob(res)
    bodies = cmd_bodies(res)
    assert any(f"\\unknowncmd{{{KEY}}}" in b and PROSE not in b for b in bodies)
    assert KEY not in blob(res)


def test_probe_nested_cs_in_prose_arg() -> None:
    r"""散文参内嵌未知调用：子扫探针臂照常把 ``\\inner{key}`` 折成 CMD，散文出 surface。"""
    res = scan(f"\\unknowncmd{{{PROSE} \\innercs{{{KEY}}} inside.}}")
    text = blob(res)
    assert PROSE in text
    assert "inside" in text
    assert KEY not in text
    assert f"\\innercs{{{KEY}}}" in cmd_bodies(res)


def test_probe_at_cs_after_makeatletter() -> None:
    r"""``\\makeatletter`` 区段内 ``\\@maketitle{prose}``——1803.00127 同型现场。"""
    defs = ""
    body = f"\\makeatletter\n\\@maketitle{{{PROSE}.}}\n\\makeatother\n"
    res = scan(body, defs)
    assert PROSE in blob(res)
    bodies = cmd_bodies(res)
    assert "\\@maketitle{" in bodies
    assert all(PROSE not in b for b in bodies)


def test_probe_unclosed_arg_bails() -> None:
    r"""未配对 ``{`` 参：``_collect_group`` EOF 回吐——探针零消费，
    组回主流重扫散文照常进 surface。"""
    res = scan("\\unknowncmd{unclosed prose group words here\n")
    assert "unclosed prose group words" in blob(res)


def test_probe_no_args_literal() -> None:
    r"""零消费照旧逐字：``\\foo`` 后无组参 → 名进 run，不收尾参。"""
    res = scan("\\unknowncmd rest of the paragraph text flows on here.")
    assert "rest of the paragraph text" in blob(res)


def test_probe_all_caps_rejected() -> None:
    r"""全大写缩写列（``NASA ESA SOHO MISSION LIST``）不算散文——维持 opaque。"""
    res = scan("\\unknowncmd{NASA ESA SOHO MISSION LIST}")
    assert any("NASA" in b for b in cmd_bodies(res))
    assert "NASA" not in blob(res)


def test_probe_commented_prose_not_lifted() -> None:
    r"""参内散文全在注释里 → 判据剔注释后无 ≥4 连词 → 维持 opaque。"""
    res = scan(
        "\\unknowncmd{%``A commented out paper title goes here''\n"
        "S.~Passaglia and M.~Sasaki}"
    )
    assert any("Passaglia" in b for b in cmd_bodies(res))
    assert "Passaglia" not in blob(res)


def test_probe_swallow_name_stays_opaque() -> None:
    r"""未定义 ``\comment{prose}``：吞块名闸命中——散文参不挖，整调用 CMD（W50 面）。"""
    res = scan(f"\\comment{{{PROSE}.}} Tail prose keeps flowing here.")
    bodies = cmd_bodies(res)
    assert f"\\comment{{{PROSE}.}}" in bodies
    assert PROSE not in blob(res)


def test_opaque_swallow_name_stays_opaque() -> None:
    r"""已定义 ``\def\comment#1{}`` + ``\comment{prose}``：opaque 臂同款闸——
    散文参不挖，整调用 MACRO（双臂一致）。"""
    res = scan(
        f"\\comment{{{PROSE}.}} Tail prose keeps flowing here.",
        "\\def\\comment#1{}\n",
    )
    assert PROSE not in blob(res)
    macro_bodies = ph_bodies(res, "MACRO")
    assert f"\\comment{{{PROSE}.}}" in macro_bodies


def test_probe_gen_backpressure() -> None:
    r"""嵌套散文参递归子扫到 ``MAX_GEN``：内层 ``\\f{prose}`` 不挖，
    整调用 opaque + ``gen_overflow`` 告警；外层散文照常出 surface。"""
    res = scan(nested_probe_call())
    kinds = [w.kind for w in res.warnings]
    assert "gen_overflow" in kinds
    text = blob(res)
    assert "Outer prose words" in text  # 外层（gen<MAX_GEN）照常挖掘
    assert f"{PROSE} deep." not in text  # 最内层（gen 触底）维持 opaque


def test_probe_gaddto_maketitle_figure_arg() -> None:
    r"""1803.00127 实形：``\g@addto@macro\@maketitle{\begin{figure}…\caption{prose}}``
    ——散文参抠出后 caption 文本进 chunk（修前整块 ``[[CMD]]`` 蒸发）。"""
    res = scan(
        "\\makeatletter\n"
        "\\g@addto@macro\\@maketitle{\n"
        "\\begin{figure}[H]\n"
        "\\centering\n"
        "\\caption{Sample point-cloud output which does not have loop closure.}\n"
        "\\end{figure}\n"
        "}\n"
        "\\makeatother\n"
        "\\maketitle\n"
    )
    assert "Sample point-cloud output" in blob(res)


def test_argspec_protect_prose_arg_surfaces() -> None:
    r"""argspec ``protect`` 臂 ``\marginpar{prose}``：散文参进 chunk surface。"""
    res = scan(f"\\marginpar{{{PROSE}.}}")
    assert PROSE in blob(res)
    bodies = cmd_bodies(res)
    assert "\\marginpar{" in bodies
    assert "}" in bodies
    assert all(PROSE not in b for b in bodies)


def test_argspec_frame_prose_surfaces() -> None:
    r"""``\frame{prose}``（latex2e 恒激活 protect）：散文参抠出。"""
    res = scan(f"\\frame{{{PROSE}.}}")
    assert PROSE in blob(res)
    bodies = cmd_bodies(res)
    assert "\\frame{" in bodies
    assert all(PROSE not in b for b in bodies)


def test_argspec_protect_key_arg_stays_opaque() -> None:
    r"""``\marginpar{cite-key}`` 非散文参：整调用单 CMD ph，参不外流。"""
    res = scan(f"\\marginpar{{{KEY}}} Tail prose words keep flowing here.")
    bodies = cmd_bodies(res)
    assert f"\\marginpar{{{KEY}}}" in bodies
    assert KEY not in blob(res)


def test_argspec_second_arg_prose_first_key() -> None:
    r"""``\subpdfbookmark{level}{prose}``（hyperref protect ``m m``）逐参判定。"""
    res = scan(
        f"\\subpdfbookmark{{level}}{{{PROSE}.}}",
        "\\usepackage{hyperref}\n",
    )
    assert PROSE in blob(res)
    bodies = cmd_bodies(res)
    assert any("\\subpdfbookmark{level}{" in b and PROSE not in b for b in bodies)
    assert "level" not in blob(res)


def test_argspec_both_args_prose() -> None:
    r"""``\subpdfbookmark{prose}{prose}`` 双散文参：两段都出 surface。"""
    p2 = "Another independent paragraph of prose follows here"
    res = scan(
        f"\\subpdfbookmark{{{PROSE} one.}}{{{p2} two.}}",
        "\\usepackage{hyperref}\n",
    )
    text = blob(res)
    assert PROSE in text
    assert p2 in text
    assert any("}{" in b for b in cmd_bodies(res))  # 参间结构段仍 CMD


def test_argspec_beamer_overlay_prose() -> None:
    r"""beamer ``\only<1>{prose}``：``d<>`` 定界参随 CMD，散文 m 参出 surface。"""
    res = scan(f"\\only<1>{{{PROSE}.}}", art=BEAMER)
    assert PROSE in blob(res)
    bodies = cmd_bodies(res)
    assert "\\only<1>{" in bodies
    assert "}" in bodies


def test_argspec_hyphenation_wordlist_stays() -> None:
    r"""``\hyphenation{op-tical net-works…}``：断词表非散文（连字符断链）——维持 opaque。"""
    res = scan("\\hyphenation{op-tical net-works semi-conduc-tor}")
    bodies = cmd_bodies(res)
    assert "\\hyphenation{op-tical net-works semi-conduc-tor}" in bodies
    assert "tical" not in blob(res)


def test_argspec_key_keyval_arg_stays_opaque() -> None:
    r"""``\hypersetup{pdftitle={长标题}}``（hyperref ``key`` 臂）：keyval 组
    不挖——值内散文不连 ``pdftitle=`` 键位一起抬进译文面。"""
    res = scan(
        "\\hypersetup{pdftitle={Some Really Long Paper Title}}",
        "\\usepackage{hyperref}\n",
    )
    bodies = cmd_bodies(res)
    assert "\\hypersetup{pdftitle={Some Really Long Paper Title}}" in bodies
    assert "Really Long" not in blob(res)


def test_argspec_keyval_mixed_stays_opaque() -> None:
    r"""多键 keyval 组 ``{colorlinks=true, pdftitle={…}, citecolor=blue}`` 同门。"""
    res = scan(
        "\\hypersetup{colorlinks=true, pdftitle={Some Really Long Paper Title},"
        " citecolor=blue}",
        "\\usepackage{hyperref}\n",
    )
    bodies = cmd_bodies(res)
    assert any("pdftitle" in b for b in bodies)
    assert "Really Long" not in blob(res)


def test_probe_keyval_arg_stays_opaque() -> None:
    r"""未定义 cs + ``{key=…}`` 组：探针臂同款形状门——不挖（判据共享）。"""
    res = scan("\\unknowncmd{pdftitle={Some Really Long Paper Title}}")
    bodies = cmd_bodies(res)
    assert "\\unknowncmd{pdftitle={Some Really Long Paper Title}}" in bodies
    assert "Really Long" not in blob(res)


def test_opaque_keyval_arg_stays_opaque() -> None:
    r"""opaque 宏臂同款：``\kv{key={长标题}}`` keyval 组不挖，整调用 MACRO。"""
    res = scan(
        "\\kv{pdftitle={Some Really Long Paper Title}}",
        "\\makeatletter\n\\def\\kv#1{\\@store{#1}}\n\\makeatother\n",
    )
    macro_bodies = ph_bodies(res, "MACRO")
    assert "\\kv{pdftitle={Some Really Long Paper Title}}" in macro_bodies
    assert "Really Long" not in blob(res)


def test_argspec_comma_list_stays_opaque() -> None:
    r"""``\usetikzlibrary{arrows, automata, backgrounds, calendar}`` 机读名单
    （1907.03868 实遇）：逗号列表形状门——不挖，名单不被译断。"""
    res = scan(
        "\\usetikzlibrary{arrows, automata, backgrounds, calendar}",
        "\\usepackage{tikz}\n",
    )
    bodies = cmd_bodies(res)
    assert "\\usetikzlibrary{arrows, automata, backgrounds, calendar}" in bodies
    assert "automata" not in blob(res)


def test_probe_comma_list_stays_opaque() -> None:
    r"""未定义 cs + 逗号名单参：探针臂同款形状门——不挖。"""
    res = scan("\\unknowncmd{arrows, automata, backgrounds, calendar}")
    bodies = cmd_bodies(res)
    assert "\\unknowncmd{arrows, automata, backgrounds, calendar}" in bodies
    assert "automata" not in blob(res)


def test_comma_list_prose_not_overrejected() -> None:
    r"""词间缺逗号的真散文不受名单门误收：``{word, word rest prose}`` 仍挖。"""
    res = scan(f"\\unknowncmd{{first, {PROSE} remainder.}}")
    assert PROSE in blob(res)
