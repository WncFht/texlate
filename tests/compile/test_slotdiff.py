"""paired_slot_diff：src↔zh 机位实参配对 diff 探针单测。"""

from texlate.compile.judge import paired_slot_diff

REL = "main.tex"


def test_identity_silent() -> None:
    """同文零差全静默——占位符复原文两侧字节同一的常态面。"""
    src = (
        "\\documentclass{ctexart}\n\\begin{document}\n"
        "\\begin{theorem}\\label{thm:a}x\\end{theorem}\n"
        "\\cite{knuth84,lamport94}\\ref{thm:a}\\eqref{eq:1}\n"
        "\\bibliography{refs}\\input{macros}\\includegraphics{fig.png}\n"
        "\\end{document}\n"
    )
    assert paired_slot_diff(src, src, REL) == []


def test_restatable_env_arg_cjk_rewrite() -> None:
    """restatable env 参被译：missing+extra 双侧记（silentthm 事故类）。"""
    src = "\\begin{restatable}{theorem}{main}\nx\n\\end{restatable}\n"
    zh = "\\begin{restatable}{定理}{main}\nx\n\\end{restatable}\n"
    notes = paired_slot_diff(src, zh, REL)
    assert f"slot_arg_missing:restatable:{REL}:'theorem'" in notes
    assert f"slot_arg_extra:restatable:{REL}:'定理'" in notes


def test_ascii_label_typo_flags() -> None:
    """ASCII 键改写也记：diff 无非 ASCII 过滤，label 拼错即断链。"""
    src = "\\begin{theorem}\\label{sec:main}x\\end{theorem}\n"
    zh = "\\begin{theorem}\\label{sec:man}x\\end{theorem}\n"
    notes = paired_slot_diff(src, zh, REL)
    assert notes == [
        f"slot_arg_missing:ref:{REL}:'sec:main'",
        f"slot_arg_extra:ref:{REL}:'sec:man'",
    ]


def test_cite_key_reorder_suppressed() -> None:
    """cite/bib 键表逗号归一：\\cite{a,b}→\\cite{b,a} 重排合法。"""
    src = "\\cite{alpha,beta}\\citep{gamma}\\bibliography{x,y}\n"
    zh = "\\cite{beta, alpha}\\citep{gamma}\\bibliography{y,x}\n"
    assert paired_slot_diff(src, zh, REL) == []


def test_ref_arg_merge_flags() -> None:
    """ref 类原子比对：\\ref{a}+\\ref{b} 合并 \\ref{a,b} 即缺陷。"""
    notes = paired_slot_diff("\\ref{a}\\ref{b}\n", "\\ref{a,b}\n", REL)
    assert f"slot_arg_missing:ref:{REL}:'b'" in notes
    assert f"slot_arg_extra:ref:{REL}:'a,b'" in notes


def test_phantom_cite_extra() -> None:
    """zh 面臆造 \\cite → slot_arg_extra（undefined citation 前兆）。"""
    notes = paired_slot_diff("正文\n", "正文\\cite{hallucinated2026}\n", REL)
    assert notes == [f"slot_arg_extra:cite:{REL}:'hallucinated2026'"]


def test_masked_and_dead_tail_silent() -> None:
    """注释/verbatim/死尾两侧同口径遮盖——不对称的同形 token 不报。"""
    src = "\\begin{document}\\label{a}\\end{document}\n% \\label{b}\n"
    zh = "\\begin{document}\\label{a}\\end{document}\n\\label{c}\n"
    assert paired_slot_diff(src, zh, REL) == []


def test_cap_marker() -> None:
    """diff 超 _MACHINE_SLOT_MAX 截断 + capped 标记。"""
    src = "".join(f"\\label{{k{i}}}\n" for i in range(25))
    notes = paired_slot_diff(src, "", REL)
    assert len(notes) == 21  # noqa: PLR2004 - 20 命中 + capped 标记
    assert notes[-1] == "slot_arg_missing:capped@20"
