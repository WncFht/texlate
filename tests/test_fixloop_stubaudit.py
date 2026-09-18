"""vendor stub 保真审计钉 (stubaudit lane, 2026-09-18):

- ``mn2e.cls``/``mn.cls``: ``\\LoadClass{mnras}`` 裸调用把 option list 视空 —
  ``usenatbib``/``useAMS``/``referee`` 全丢 (loop2 实证 0707.4614
  citealt×142 / 1206.0597 citealt×57 / 1206.5819 citet×134)。改
  ``\\LoadClassWithOptions`` 按 scrub 后 ``\\@classoptionslist`` 转发,
  mnras 老 ``\\ds@`` 系 option 照常点火。
- ``aaspp4.sty``/``aasms4.sty``: ``\\markcite``/``\\reference`` 真身均单参
  ``{key}`` (9910310 ``\\markcite{Na_95}``/``\\reference{Al_96}`` 实证),
  0-arg 版把 ``{key}`` 漏进正文流 → ``_`` 触发 ``Missing $`` 级联。
- ``jheppub.sty``/``jinstpub.sty``: 真件装载面 (amssymb/epsfig/graphicx/
  natbib[numbers,sort&compress]/color/hyperref | amsthm/amsmath/amssymb/
  graphicx/natbib/hyperref/wrapfig) stub 未装 → 稿内 natbib 引文面
  (\\citep/\\citet) undefined_cs 级联。
- ``svjour3.cls``: 真件 ``natbib`` 类选项 → AtEndOfClass 装 natbib;
  stub 星号转发把 ``natbib`` 当未知 option 丢给 article 静默吞。
- ``aipproc.cls``: 真件装载面 calc/ifthen/graphicx[final]/url;
  ``\author`` 双签名 (新 keyval 双参 | 老 REVTeX3 单参+散调 ``\address``,
  2 参硬吃后随 cs 炸 \csname/keyval) + ``references`` env
  (astro-ph/0104007 env_undefined→\@listctr×12 级联)。
- ``tcilatex.tex``: ``\QQQ`` 真件 2 参元数据机 (全部存本一致;
  1 参 sink 漏 {val} 进 preamble → Missing\begin{document},
  cond-mat/9910091 实证) + SW20 tag 机全套 (\tag×115 undefined_cs)。
- ``sw20lart.sty``/``BoxedEPS.tex``: 新 stub 顶掉 shim_map noop 条
  (vendored 预检先落件)——SW20 tag 机同套; BoxedEPS OzTeX 期图件
  实证面 + \BoxedEPSF→\includegraphics (cond-mat/0408520 ×16)。

实证基线: bench/results/stagerun-loop2-2026-09-18/records/fixloop.jsonl,
stagerun-tarrecheck/, stagerun-flipcheck/ 同名 records。
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

STUBS = (
    Path(__file__).resolve().parent.parent / "src/texlate/compile/fixloop/vendor/stubs"
)
VENDOR_FILES = STUBS.parent / "files"

_XELATEX = shutil.which("xelatex")
_COMPILE = pytest.mark.skipif(_XELATEX is None, reason="xelatex not installed")


def _run(wdir: Path, tex: str) -> str:
    (wdir / "main.tex").write_text(tex, encoding="utf-8")
    subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [_XELATEX, "-interaction=nonstopmode", "main.tex"],
        cwd=wdir,
        capture_output=True,
        timeout=120,
        check=False,
    )
    return (wdir / "main.log").read_text(encoding="utf-8", errors="replace")


def _n_err(log: str) -> int:
    return len(re.findall(r"^! ", log, re.MULTILINE))


# ------------------------------------------------------- 源码级 pin (免编译)


def test_mn_family_uses_loadclasswithoptions() -> None:
    """mn2e/mn 转发链 pin：裸 \\LoadClass{mnras} 不得回潮。"""
    for name in ("mn2e.cls", "mn.cls"):
        body = (STUBS / name).read_text(encoding="utf-8")
        code = "\n".join(
            ln for ln in body.splitlines() if not ln.lstrip().startswith("%")
        )
        assert "\\LoadClassWithOptions{mnras}" in code
        assert "\\LoadClass{mnras}" not in code


def test_aas4_markcite_reference_take_key() -> None:
    """aaspp4/aasms4 的 \\markcite/\\reference 必须吞 {key}。"""
    for name in ("aaspp4.sty", "aasms4.sty"):
        body = (STUBS / name).read_text(encoding="utf-8")
        assert "\\def\\markcite#1{}" in body
        assert "\\def\\reference#1{\\refpar}" in body
        assert "\\def\\markcite{}" not in body
        assert "\\def\\reference{\\refpar}" not in body


def test_iface_requires_present() -> None:
    """真件装载面 pin：缺的 \\RequirePackage 不得回潮。"""
    jheppub = (STUBS / "jheppub.sty").read_text(encoding="utf-8")
    for pkg in ("amssymb", "epsfig", "graphicx", "color", "hyperref"):
        assert f"\\RequirePackage{{{pkg}}}" in jheppub
    assert "\\RequirePackage[numbers,sort&compress]{natbib}" in jheppub
    jinstpub = (STUBS / "jinstpub.sty").read_text(encoding="utf-8")
    for pkg in ("amsthm", "amsmath", "amssymb", "graphicx", "hyperref", "wrapfig"):
        assert f"\\RequirePackage{{{pkg}}}" in jinstpub
    assert "\\RequirePackage[numbers,sort&compress]{natbib}" in jinstpub
    aipproc = (STUBS / "aipproc.cls").read_text(encoding="utf-8")
    for pkg in ("calc", "ifthen", "url"):
        assert f"\\RequirePackage{{{pkg}}}" in aipproc
    assert "\\RequirePackage[final]{graphicx}" in aipproc


def test_svjour3_natbib_option_declared() -> None:
    """svjour3 natbib 类选项 pin：真件 AtEndOfClass 装 natbib+版式参数。"""
    body = (STUBS / "svjour3.cls").read_text(encoding="utf-8")
    assert "\\DeclareOption{natbib}" in body
    assert "\\AtEndOfClass{\\RequirePackage{natbib}" in body


def _code_lines(body: str) -> str:
    """滤 % 注释行后拼接——pin 断言不得被注释文本夹带。"""
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("%"))


def test_tcilatex_qqq_two_arg_definer() -> None:
    r"""tcilatex \QQQ 真件 2 参元数据机 pin（cond-mat/9910091
    \QQQ{Language}{American English} 漏参 Missing\begin{document} 实证）。"""
    code = _code_lines((STUBS / "tcilatex.tex").read_text(encoding="utf-8"))
    assert (
        "\\long\\def\\QQQ#1#2{\\long\\expandafter\\def\\csname#1\\endcsname{#2}}"
        in code
    )
    assert "\\def\\QQQ#1{}" not in code


def test_sw20_tag_machinery_present() -> None:
    r"""SW20 tag 机 pin：tcilatex/sw20lart 双件各立全套
    （cond-mat/9910091 \tag×115 undefined_cs 实证）。"""
    for name in ("tcilatex.tex", "sw20lart.sty"):
        code = _code_lines((STUBS / name).read_text(encoding="utf-8"))
        for frag in (
            "\\newif\\iftag@",
            "\\def\\tag{\\@ifnextchar*{\\@tagstar}{\\@tag}}",
            "\\def\\@@eqncr",
            "\\def\\endequation",
            "\\def\\TCItag",
            "\\@ifundefined{tag}",
        ):
            assert frag in code, f"{name} 缺 {frag}"


def test_boxedeps_iface_present() -> None:
    r"""BoxedEPS kit pin（cond-mat/0408520 16 undefined_cs 实证）：
    实证面 + 兄弟件齐全，\BoxedEPSF 退化 \includegraphics。"""
    code = _code_lines((STUBS / "BoxedEPS.tex").read_text(encoding="utf-8"))
    for frag in (
        "\\def\\ForceWidth#1",
        "\\def\\ForceHeight#1",
        "\\def\\BoxedEPSF#1",
        "\\def\\SetOzTeXEPSFSpecial{}",
        "\\def\\HideDisplacementBoxes{}",
        "\\def\\ShowDisplacementBoxes{}",
        "\\includegraphics",
    ):
        assert frag in code, f"BoxedEPS.tex 缺 {frag}"


def test_aipproc_author_dual_signature_and_references() -> None:
    r"""aipproc \author 双签名 + references env pin（0104007 :250
    keyval 爆 + env_undefined/\@listctr×12 实证）。"""
    code = _code_lines((STUBS / "aipproc.cls").read_text(encoding="utf-8"))
    assert "\\renewcommand{\\author}[1]" in code
    assert "\\@ifnextchar\\bgroup{\\fixaip@author@kv" in code
    assert "\\renewcommand{\\author}[2]" not in code
    assert "\\newenvironment{references}" in code
    assert "\\usecounter{enumiv}" in code


# ------------------------------------------------------- 真编译钉


@_COMPILE
def test_mn2e_usenatbib_loads_natbib(tmp_path: Path) -> None:
    """mn2e stub + usenatbib → mnras \\ds@usenatbib 点火 → \\citealt 定义。"""
    shutil.copy(STUBS / "mn2e.cls", tmp_path / "mn2e.cls")
    shutil.copy(VENDOR_FILES / "mnras.cls", tmp_path / "mnras.cls")
    log = _run(
        tmp_path,
        r"""\documentclass[usenatbib]{mn2e}
\begin{document}
text \citealt{key}
\end{document}
""",
    )
    assert "natbib.sty" in log, "usenatbib 未转发, natbib 未装"
    assert _n_err(log) == 0, f"仍 {_n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()


@_COMPILE
def test_mn_usenatbib_loads_natbib(tmp_path: Path) -> None:
    """mn stub 同体转发 (mn.cls→mnras 同路径)。"""
    shutil.copy(STUBS / "mn.cls", tmp_path / "mn.cls")
    shutil.copy(VENDOR_FILES / "mnras.cls", tmp_path / "mnras.cls")
    log = _run(
        tmp_path,
        r"""\documentclass[usenatbib]{mn}
\begin{document}
text \citet{key}
\end{document}
""",
    )
    assert "natbib.sty" in log
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.parametrize("sty", ["aaspp4", "aasms4"])
def test_aas4_markcite_reference_consume_key(tmp_path: Path, sty: str) -> None:
    """\\markcite{Na_95}/\\reference{Al_96}: {key} 不泄正文, 无 Missing $。"""
    shutil.copy(STUBS / f"{sty}.sty", tmp_path / f"{sty}.sty")
    log = _run(
        tmp_path,
        rf"""\documentclass{{article}}
\usepackage{{{sty}}}
\begin{{document}}
text \markcite{{Na_95}}Nakajima et al. 1995
\begin{{references}}
\reference{{Al_96}} Allard et al. 1996
\end{{references}}
\end{{document}}
""",
    )
    assert _n_err(log) == 0, f"{sty} 仍 {_n_err(log)} 个 '!' 错 (key 泄正文)"
    assert (tmp_path / "main.pdf").is_file()


@_COMPILE
@pytest.mark.parametrize("sty", ["jheppub", "jinstpub"])
def test_sissa_stub_provides_natbib(tmp_path: Path, sty: str) -> None:
    """SISSA kit stub 镜像真件装载面 → \\citep 等 natbib 面可用。"""
    shutil.copy(STUBS / f"{sty}.sty", tmp_path / f"{sty}.sty")
    log = _run(
        tmp_path,
        rf"""\documentclass{{article}}
\usepackage{{{sty}}}
\begin{{document}}
text \citep{{key}}
\end{{document}}
""",
    )
    assert "natbib.sty" in log, f"{sty} 未装 natbib"
    assert "graphicx.sty" in log, f"{sty} 未装 graphicx"
    assert _n_err(log) == 0, f"{sty} 仍 {_n_err(log)} 个 '!' 错"


@_COMPILE
def test_svjour3_natbib_option(tmp_path: Path) -> None:
    """\\documentclass[natbib]{svjour3} → natbib 装载 (真件选项面)。"""
    shutil.copy(STUBS / "svjour3.cls", tmp_path / "svjour3.cls")
    log = _run(
        tmp_path,
        r"""\documentclass[natbib]{svjour3}
\begin{document}
text \citep{key}
\end{document}
""",
    )
    assert "natbib.sty" in log, "natbib 类选项未生效"
    assert _n_err(log) == 0


@_COMPILE
def test_aipproc_provides_graphicx_url(tmp_path: Path) -> None:
    """aipproc stub 镜像真件装载面: graphicx/url 由类提供。"""
    shutil.copy(STUBS / "aipproc.cls", tmp_path / "aipproc.cls")
    log = _run(
        tmp_path,
        r"""\documentclass{aipproc}
\begin{document}
see \url{https://example.org}
\end{document}
""",
    )
    assert "graphicx.sty" in log
    assert "url.sty" in log
    assert _n_err(log) == 0


@_COMPILE
def test_tcilatex_qqq_defines_name_and_no_preamble_leak(tmp_path: Path) -> None:
    r"""\QQQ{Language}{American English} → \Language 定义（真件元数据机），
    次参不漏 preamble → 无 Missing\begin{document}。"""
    shutil.copy(STUBS / "tcilatex.tex", tmp_path / "tcilatex.tex")
    log = _run(
        tmp_path,
        r"""\documentclass{article}
\input tcilatex
\QQQ{Language}{American English}
\begin{document}
lang=\Language.
\end{document}
""",
    )
    assert _n_err(log) == 0, f"仍 {_n_err(log)} 个 '!' 错"
    assert "Missing \\begin{document}" not in log
    assert (tmp_path / "main.pdf").is_file()


@_COMPILE
@pytest.mark.parametrize("kit", ["tcilatex", "sw20lart"])
def test_sw20_tag_in_equation_and_eqnarray(tmp_path: Path, kit: str) -> None:
    r"""\tag{N}/\tag*{lit} 在 equation 与 eqnarray 两族皆消费
    （9910091 实证面：\tag{2.1} equation、\tag{2.2} eqnarray）。"""
    if kit == "tcilatex":
        shutil.copy(STUBS / "tcilatex.tex", tmp_path / "tcilatex.tex")
        load = "\\input tcilatex"
    else:
        shutil.copy(STUBS / "sw20lart.sty", tmp_path / "sw20lart.sty")
        load = "\\usepackage{sw20lart}"
    log = _run(
        tmp_path,
        rf"""\documentclass{{article}}
{load}
\begin{{document}}
\begin{{equation}} x=1 \tag{{2.1}} \end{{equation}}
\begin{{eqnarray}} y&=&2 \tag{{2.2}} \end{{eqnarray}}
\begin{{equation}} z=3 \tag*{{lit}} \end{{equation}}
\end{{document}}
""",
    )
    assert _n_err(log) == 0, f"{kit} 仍 {_n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()


@_COMPILE
def test_boxedeps_iface_degrades_to_includegraphics(tmp_path: Path) -> None:
    r"""\input BoxedEPS + 全实证面调用面 0 错；\BoxedEPSF→\includegraphics。"""
    shutil.copy(STUBS / "BoxedEPS.tex", tmp_path / "BoxedEPS.tex")
    log = _run(
        tmp_path,
        r"""\documentclass{article}
\input BoxedEPS.tex
\renewcommand{\includegraphics}[2][]{}
\begin{document}
\SetOzTeXEPSFSpecial\HideDisplacementBoxes
\ForceWidth{7cm}
fig: \BoxedEPSF{fig.eps}
\ForceHeight{3cm}
fig2: \BoxedEPSF{fig2.eps}
\ShowDisplacementBoxes
\end{document}
""",
    )
    assert "graphicx.sty" in log, "BoxedEPS 未装 graphicx"
    assert _n_err(log) == 0, f"仍 {_n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()


@_COMPILE
def test_aipproc_one_arg_author_and_references(tmp_path: Path) -> None:
    r"""REVTeX3 式 \author{names} + \address{} + references env
    （0104007 实证面）：不吞 \address、\bibitem 在 list 内工作。"""
    shutil.copy(STUBS / "aipproc.cls", tmp_path / "aipproc.cls")
    log = _run(
        tmp_path,
        r"""\documentclass{aipproc}
\begin{document}
\title{T}
\author{Marcelo Alvarez$^*$, Paul R. Shapiro$^*$ and Hugo Martel$^*$}
\address{$^*$Department of Astronomy, UT Austin}
\maketitle
text \cite{Moore00}.
\begin{references}
\bibitem{Moore00} Moore et al.
\end{references}
\end{document}
""",
    )
    assert _n_err(log) == 0, f"仍 {_n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()


@_COMPILE
def test_aipproc_two_arg_author_kept(tmp_path: Path) -> None:
    r"""新 keyval 双参 \author{Name}{address={..}} 不回潮（1306.2177 面）。"""
    shutil.copy(STUBS / "aipproc.cls", tmp_path / "aipproc.cls")
    log = _run(
        tmp_path,
        r"""\documentclass{aipproc}
\begin{document}
\title{T}
\author{Alice}{address={MIT},email={a@x}}
\author{Bob}{address={CERN}}
\maketitle
text.
\end{document}
""",
    )
    assert _n_err(log) == 0, f"仍 {_n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()
