r"""endcsresid 普查 (task #230) 双修钉: vendor stub 自毒 Missing \endcsname。

格面 (tmp/lane-endcsresid/ 普查):

F1. active-& 书目 shim 毒 cite-key csname —— aa.cls / aaspp4.sty /
    aasms4.sty 三件套 (aaspatch 宽容面, test_fixloop_aas_amp 钉) 把
    ``thebibliography``/``references`` env 内 ``&`` 激活成 ``\&``。
    期稿 cite key 带裸 ``&`` (Rieke&Lebofsky, ADS bibcode
    1990A&A...231...19S —— 1003.0851/1003.4471/astro-ph/0103009
    实证): env 内 ``\bibitem{K&K}`` 读出 active-& → natbib/kernel
    建 ``b@<key>`` csname 时 ``\&`` (chardef ``\char"26`` 不可展)
    炸 Missing \endcsname。修两臂:

    a. 写侧: active-& 本体改 ``\ifincsname\string&\else\&\fi`` —
       csname 内 ``\string&`` 产 cat12-& 字符 (与 doc 体 cat4-&
       同字节 0x26 → ``b@`` 名一致), 离开 csname 仍 ``\&`` 保排版。
    b. 读侧: ``\bibitem`` 的 ``\write`` 已把 key 内 active-& 烤成
       字面 ``\&`` → aux ``\bibcite{K\&K}`` 在 enddoc/次轮 begindoc
       两次 ``\@input`` 回读再吞 chardef 自毒。``\*@sanl@bel`` 把
       key 参 ``\edef`` 重展开 (``\&``→cat12-& 字符, ``\protect``→∅),
       label/data 参原样过。挂 ``begindocument/before`` —— kernel
       ``\@input{jobname.aux}`` 早于 ``begindocument`` 钩
       (latex.ltx 9489<9512), ``AtBeginDocument`` 太晚; 该点亦
       捕获后载 natbib 最终 ``\bibcite``。罩 ``\bibcite`` /
       ``\@newl@bel`` (kernel ``\bibcite``+``\newlabel`` r@ 两路) /
       ``\@testdef`` / ``\NAT@testdef`` (两系 enddoc 复读,
       ``\@ifundefined`` 守卫不预定义)。

F2. aipproc.cls ``\author`` 双签名分歧 —— 新 keyval 双参
    ``\author{N}{address={...}}`` vs 老 REVTeX3 系单参
    ``\author{names}`` + 散调 ``\address{}`` (astro-ph/0104007/
    0104134)。2 参硬吃把后随 ``\address`` cs 吞进 ``\setkeys``
    → csname/keyval 炸 Missing \endcsname 级联。修 =
    ``\@ifnextchar\bgroup`` peek: 仅紧随 ``{`` 组才消费次参。
"""

import shutil
from pathlib import Path

import pytest
from _fixloopkit import code_lines, n_err, requires_xelatex, run_xelatex

STUBS = (
    Path(__file__).resolve().parent.parent / "src/texlate/compile/fixloop/vendor/stubs"
)
SHIMS = STUBS.parent / "shims"  # .cls 替身 stub 归位层 (F2)

# (stub 文件名, 命名空间前缀) —— aa.cls 用 aa@, aas4 系共享 aas@ (双载守卫互斥)
_AMP_STUBS = [
    ("aa.cls", "aa@"),
    ("aaspp4.sty", "aas@"),
    ("aasms4.sty", "aas@"),
]


# ------------------------------------------------------- F1 源码级 pin


@pytest.mark.parametrize(("name", "_ns"), _AMP_STUBS)
def test_ifincsname_guard_shape(name: str, _ns: str) -> None:
    r"""active ``&`` 本体 = ``\ifincsname\string&\else\&\fi`` 护臂形。"""
    code = code_lines((STUBS / name).read_text(encoding="utf-8"))
    assert (
        r"\begingroup\catcode`\&=\active"
        r"\gdef&{\ifincsname\string&\else\&\fi}\endgroup" in code
    )
    # 旧自毒形不得残留
    assert r"\gdef&{\&}" not in code


@pytest.mark.parametrize(("name", "ns"), _AMP_STUBS)
def test_sanitize_wrap_on_begindocument_before(name: str, ns: str) -> None:
    r"""读侧消洗臂挂 ``begindocument/before`` (begindoc aux 回读早于此点)。

    罩 ``\bibcite``/``\@newl@bel``/``\@testdef`` 三路 +
    ``\NAT@testdef`` 守卫形 (不得无条件预定义 —— 否则后载 natbib
    ``\newcommand`` 撞名)。"""
    code = code_lines((STUBS / name).read_text(encoding="utf-8"))
    assert r"\AddToHook{begindocument/before}" in code
    assert rf"\def\{ns}sanl@bel#1#2" in code
    hook = code.split(r"\AddToHook{begindocument/before}", 1)[1]
    assert rf"\gdef\bibcite{{\{ns}sanl@bel\{ns}bibcite}}" in hook
    assert rf"\gdef\@newl@bel#1{{\{ns}sanl@bel{{\{ns}newl@bel#1}}}}" in hook
    assert rf"\gdef\@testdef#1{{\{ns}sanl@bel{{\{ns}testdef#1}}}}" in hook
    assert r"\@ifundefined{NAT@testdef}" in hook


@pytest.mark.parametrize(("name", "ns"), _AMP_STUBS)
def test_sanitize_edefs_key_arg_only(name: str, ns: str) -> None:
    r"""消洗件只 ``\edef`` key 参 (``\protect``→∅, ``\&``→cat12-&),
    label/data 参 (``#2`` 之后的全部) 原样移交原宏。"""
    code = code_lines((STUBS / name).read_text(encoding="utf-8"))
    assert rf"\let\&\{ns}bibamp" in code
    assert r"\let\protect\@empty" in code
    assert rf"\edef\{ns}tmp{{\endgroup\noexpand#1{{#2}}}}\{ns}tmp" in code


# ------------------------------------------------------- F2 源码级 pin


def test_aipproc_author_peeks_second_group() -> None:
    r"""``\author`` = 单参 + ``\@ifnextchar\bgroup`` peek 双签名岔路。"""
    code = code_lines((SHIMS / "aipproc.cls").read_text(encoding="utf-8"))
    assert r"\renewcommand{\author}[1]{%" in code
    assert (
        r"\@ifnextchar\bgroup{\fixaip@author@kv{#1}}{\fixaip@author@plain{#1}}" in code
    )
    assert r"\def\fixaip@author@plain#1" in code
    assert r"\providecommand{\address}[1]" in code


# ------------------------------------------------------- 真编译钉


@pytest.mark.integration
@requires_xelatex
def test_aa_cls_amp_citekey_two_pass(tmp_path: Path) -> None:
    r"""1003.0851 型: ``\citep{Rieke&Lebofsky}`` + ``\bibitem`` &-key
    两轮 clean; aux 烤 ``\&`` 形由读侧消洗臂收。"""
    shutil.copy(STUBS / "aa.cls", tmp_path / "aa.cls")
    log = run_xelatex(
        tmp_path,
        r"""\documentclass{aa}
\begin{document}
See \citep{Rieke&Lebofsky} and \citep{1990A&A...231...19S}.
Section \ref{sec:A&A} here.
\section{Stuff}\label{sec:A&A}
\begin{thebibliography}{9}
\bibitem{Rieke&Lebofsky} Rieke, G.~H., \& Lebofsky, M.~J. 1985, ApJ, 288, 618
\bibitem{1990A&A...231...19S} Smith et al. 1990, A\&A, 231, 19
\end{thebibliography}
\end{document}
""",
        passes=2,
    )
    assert n_err(log) == 0, f"aa.cls 仍 {n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()
    aux = (tmp_path / "main.aux").read_text(encoding="utf-8")
    # key 内 active-& 烤成字面 \& —— 读侧消洗臂的回读对象
    assert r"\bibcite{Rieke\&Lebofsky}" in aux
    # r@ 路同罩: \label 带 & 的 sec:A&A 回读不炸
    assert r"\newlabel{sec:A&A}" in aux


@pytest.mark.integration
@requires_xelatex
@pytest.mark.parametrize("sty", ["aaspp4", "aasms4"])
def test_aas4_amp_citekey_two_pass(tmp_path: Path, sty: str) -> None:
    r"""astro-ph/0103009 型: aas4 系 + natbib ``\citep{K&K}`` 两轮 clean。"""
    shutil.copy(STUBS / f"{sty}.sty", tmp_path / f"{sty}.sty")
    log = run_xelatex(
        tmp_path,
        rf"""\documentclass{{article}}
\usepackage{{{sty}}}
\usepackage[numbers]{{natbib}}
\begin{{document}}
See \citep{{Rieke&Lebofsky}} and \citep{{1990A&A...231...19S}}.
\begin{{thebibliography}}{{9}}
\bibitem{{Rieke&Lebofsky}} Rieke, G.~H., \& Lebofsky, M.~J. 1985, ApJ, 288, 618
\bibitem{{1990A&A...231...19S}} Smith et al. 1990, A\&A, 231, 19
\end{{thebibliography}}
\end{{document}}
""",
        passes=2,
    )
    assert n_err(log) == 0, f"{sty} 仍 {n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()
    aux = (tmp_path / "main.aux").read_text(encoding="utf-8")
    assert r"\bibcite{Rieke\&Lebofsky}" in aux


@pytest.mark.integration
@requires_xelatex
def test_aipproc_onearg_author_address(tmp_path: Path) -> None:
    r"""astro-ph/0104007 型: 单参 ``\author`` + 散调 ``\address`` 不炸;
    双参 keyval 形共存。"""
    shutil.copy(SHIMS / "aipproc.cls", tmp_path / "aipproc.cls")
    log = run_xelatex(
        tmp_path,
        r"""\documentclass{aipproc}
\begin{document}
\title{T}
\author{Tsvi Piran}
\address{Racah institute for Physics, \\
The Hebrew University, Jerusalem Israel 91904}
\author{Second Author}{address={Nowhere},email={x@y}}
\maketitle
x
\end{document}
""",
        passes=1,
    )
    assert n_err(log) == 0, f"aipproc 仍 {n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()
