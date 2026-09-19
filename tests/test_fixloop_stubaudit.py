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
  2 参硬吃后随 cs 炸 \\csname/keyval) + ``references`` env
  (astro-ph/0104007 env_undefined→\\@listctr×12 级联)。
- ``tcilatex.tex``: ``\\QQQ`` 真件 2 参元数据机 (全部存本一致;
  1 参 sink 漏 {val} 进 preamble → Missing\begin{document},
  cond-mat/9910091 实证) + SW20 tag 机全套 (\tag×115 undefined_cs)。
- ``sw20lart.sty``/``BoxedEPS.tex``: 新 stub 顶掉 shim_map noop 条
  (vendored 预检先落件)——SW20 tag 机同套; BoxedEPS OzTeX 期图件
  实证面 + \\BoxedEPSF→\\includegraphics (cond-mat/0408520 ×16)。
- ``svglov3.clo``: catcode 免疫改写 (1608.06693 实证)——旧 stub 尾置
  ``\\makeatother``, svjour3.cls class-load 语境 ``\\input`` 返回后 @ 失
  字母位, cls:159 ``15\\p@`` 断读 → 全 cls 级联。现全件零 @-cs,
  ``\\PackageWarningNoLine`` 两语境皆可解析。
- shim_map body 升级 (round-2, 随稿签名挖掘): cimento ``\from/\\inst/
  \\instlist/\\PACSes/\\PACSit`` (0905.4620), pasj00 ``\\DeclareAbbreviation``
  2 参 + ``\\SetRunningHead/\\Received/\\Accepted/\\KeyWords/\\email/\\draft``
  preamble 存值 ``\\AtBeginDocument`` 释放 (1003.0945), PoS ``\\ShortTitle/
  \\speaker/\\email`` + 命令形 ``\abstract`` (1306.5919), imsart += ``\arxiv/
  \thanksref`` (1003.1513), aa501 ``{loads:"aa", needs:["aa.cls"]}`` 桥
  (0104346 实证面), flushrt ``\\AtBeginDocument{\raggedleft}`` (9910310:
  升级稿 ``\\usepackage{aaspp4,flushrt}`` 合行, 2.09 option→pkg 链)。
- shim_map geom.sty body 深件 (round-3, 0806.0904/0806.2953 实证 +
  CTAN latex209/contrib/geomsty 取件核实): ``\\ifstarredcontents`` 补
  ``\newif`` (稿 ``\\@ssect`` 直读未声明 → ``\\section*`` ``\\@tempb``
  错位 → illegal_unit); ``\\presection`` 正 ``\newskip`` 非宏;
  ``\newtheorem`` ``[{i}{}]{n}`` 派工系 + ``proof``/``Figure`` env
  基座 + ``\\provedbox``/``\\captionskip``/``\\@caption*`` 寄存器;
  ``\\prooftag`` 0 参; @-cs 段 ``\\catcode 64`` save/restore 免疫。

实证基线: bench/results/stagerun-loop2-2026-09-18/records/fixloop.jsonl,
stagerun-tarrecheck/, stagerun-flipcheck/ 同名 records。
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from texlate.compile.fixloop import load_ruleset

STUBS = (
    Path(__file__).resolve().parent.parent / "src/texlate/compile/fixloop/vendor/stubs"
)
SHIMS = STUBS.parent / "shims"  # .cls 替身 stub 归位层 (F2)
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
        body = (SHIMS / name).read_text(encoding="utf-8")
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
    aipproc = (SHIMS / "aipproc.cls").read_text(encoding="utf-8")
    for pkg in ("calc", "ifthen", "url"):
        assert f"\\RequirePackage{{{pkg}}}" in aipproc
    assert "\\RequirePackage[final]{graphicx}" in aipproc


def test_svjour3_natbib_option_declared() -> None:
    """svjour3 natbib 类选项 pin：真件 AtEndOfClass 装 natbib+版式参数。"""
    body = (SHIMS / "svjour3.cls").read_text(encoding="utf-8")
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
    code = _code_lines((SHIMS / "aipproc.cls").read_text(encoding="utf-8"))
    assert "\\renewcommand{\\author}[1]" in code
    assert "\\@ifnextchar\\bgroup{\\fixaip@author@kv" in code
    assert "\\renewcommand{\\author}[2]" not in code
    assert "\\newenvironment{references}" in code
    assert "\\usecounter{enumiv}" in code


# ------------------------------------------------------- 真编译钉


@pytest.mark.integration
@_COMPILE
def test_mn2e_usenatbib_loads_natbib(tmp_path: Path) -> None:
    """mn2e stub + usenatbib → mnras \\ds@usenatbib 点火 → \\citealt 定义。"""
    shutil.copy(SHIMS / "mn2e.cls", tmp_path / "mn2e.cls")
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


@pytest.mark.integration
@_COMPILE
def test_mn_usenatbib_loads_natbib(tmp_path: Path) -> None:
    """mn stub 同体转发 (mn.cls→mnras 同路径)。"""
    shutil.copy(SHIMS / "mn.cls", tmp_path / "mn.cls")
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
@_COMPILE
def test_svjour3_natbib_option(tmp_path: Path) -> None:
    """\\documentclass[natbib]{svjour3} → natbib 装载 (真件选项面)。"""
    shutil.copy(SHIMS / "svjour3.cls", tmp_path / "svjour3.cls")
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


@pytest.mark.integration
@_COMPILE
def test_aipproc_provides_graphicx_url(tmp_path: Path) -> None:
    """aipproc stub 镜像真件装载面: graphicx/url 由类提供。"""
    shutil.copy(SHIMS / "aipproc.cls", tmp_path / "aipproc.cls")
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
@_COMPILE
def test_aipproc_one_arg_author_and_references(tmp_path: Path) -> None:
    r"""REVTeX3 式 \author{names} + \address{} + references env
    （0104007 实证面）：不吞 \address、\bibitem 在 list 内工作。"""
    shutil.copy(SHIMS / "aipproc.cls", tmp_path / "aipproc.cls")
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


@pytest.mark.integration
@_COMPILE
def test_aipproc_two_arg_author_kept(tmp_path: Path) -> None:
    r"""新 keyval 双参 \author{Name}{address={..}} 不回潮（1306.2177 面）。"""
    shutil.copy(SHIMS / "aipproc.cls", tmp_path / "aipproc.cls")
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


# ------------------------------------------------------- round-2: catcode 钉 + shim body 钉


def test_svglov3_clo_catcode_immune() -> None:
    r"""svglov3.clo catcode 存复 pin（1608.06693 实证）：
    禁裸 ``\makeatletter``/``\makeatother``——class-load 语境 ``\input``
    返回后 @ 字母位不得被改写；``\catcode 64`` 存复对 + ``size10.clo``
    字体段 (真件内联同件) + ``\validfor``/``\if@runhead`` cls 校验点。"""
    code = _code_lines((STUBS / "svglov3.clo").read_text(encoding="utf-8"))
    assert "\\makeatletter" not in code
    assert "\\makeatother" not in code
    assert "\\catcode 64" in code
    assert "\\svglovrestore" in code
    assert "\\input{size10.clo}" in code
    assert "\\def\\validfor{svjour3}" in code


def _shim_map() -> dict[str, dict]:
    rules = {r.id: r for r in load_ruleset().rules}
    return rules["legacy_pkg_shim"].action["params"]["shim_map"]


def _vendor_file(name: str) -> Path | None:
    """shim_map 槽已删名 (routeclean 2026-09-20) → vendored_fetch 实件。"""
    for layer in (SHIMS, STUBS, VENDOR_FILES):
        vend = layer / name
        if vend.is_file():
            return vend
    return None


def _shim_body(name: str) -> str:
    spec = _shim_map().get(name)
    if spec is None:
        vend = _vendor_file(name)
        if vend is not None:
            return vend.read_text(encoding="utf-8")
        raise KeyError(name)
    assert "body" in spec, f"{name} 无 body 键"
    return spec["body"]


def test_cimento_frontmatter_kit() -> None:
    r"""cimento body pin（0905.4620 随稿签名 ``\author{..\from{ins:x}}`` +
    ``\instlist{\inst{ins:x} ..}`` + ``\PACSes{..\PACSit{c}{d}..}``）。
    ``\instlist``/``\PACSes`` preamble 期调用 → 存值 + ``\AtBeginDocument``。"""
    body = _shim_body("cimento.cls")
    for frag in (
        "\\providecommand{\\from}[1]",
        "\\providecommand{\\inst}[1]",
        "\\providecommand{\\instlist}[1]",
        "\\providecommand{\\PACSes}[1]",
        "\\providecommand{\\PACSit}[2]",
        "\\AtBeginDocument",
    ):
        assert frag in body, f"cimento 缺 {frag}"


def test_pasj00_kit() -> None:
    r"""pasj00 body pin（1003.0945 随稿签名）：
    ``\DeclareAbbreviation`` 2 参定义件 + frontmatter 面 + natbib/amssymb/
    graphicx 装载面 + 期刊缩写内建集 + ``\FigureFile`` + AAS 式 ``\altaffil*``
    + ``\rm`` 2.09 字件。"""
    body = _shim_body("pasj00.cls")
    for frag in (
        "\\providecommand{\\DeclareAbbreviation}[2]",
        "\\providecommand{\\SetRunningHead}[2]",
        "\\providecommand{\\Received}[1]",
        "\\providecommand{\\Accepted}[1]",
        "\\providecommand{\\KeyWords}[1]",
        "\\providecommand{\\email}[1]",
        "\\providecommand{\\draft}{}",
        "\\providecommand{\\altaffilmark}[1]",
        "\\providecommand{\\altaffiltext}[2]",
        "\\def\\FigureFile(",
        "\\DeclareOldFontCommand{\\rm}",
        "\\providecommand{\\mnras}",
        "\\providecommand{\\pasj}",
        "\\providecommand{\\apj}",
        "\\providecommand{\\iaucirc}",
        "\\RequirePackage[numbers]{natbib}",
        "\\RequirePackage{amssymb}",
        "\\RequirePackage{graphicx}",
        "\\AtBeginDocument",
    ):
        assert frag in body, f"pasj00 缺 {frag}"


def test_pos_kit() -> None:
    r"""PoS body pin（1306.5919 随稿签名）：``\ShortTitle/\speaker/\email``
    + 命令形 ``\abstract{}`` + ``\FullConference`` + ``acknowledgments``
    env + graphicx 装载面（PoS 无 env 形, JINST 条同形先例）。"""
    body = _shim_body("PoS.cls")
    for frag in (
        "\\providecommand{\\ShortTitle}[1]",
        "\\providecommand{\\speaker}[1]",
        "\\providecommand{\\email}[1]",
        "\\providecommand{\\FullConference}[1]",
        "\\renewcommand{\\abstract}[1]",
        "\\newenvironment{acknowledgments}",
        "\\RequirePackage{graphicx}",
        "\\AtBeginDocument",
    ):
        assert frag in body, f"PoS 缺 {frag}"


def test_imsart_arxiv_thanksref() -> None:
    r"""imsart body 增量 pin（1003.1513 随稿签名 ``\arxiv{math.PR/0000512}``
    + ``\thanksref{t2}`` + 结构 env 面 + ``\kwd/\ead/\printead`` +
    单参 ``\address``）。"""
    body = _shim_body("imsart.cls")
    for frag in (
        "\\providecommand{\\arxiv}[1]",
        "\\providecommand{\\thanksref}[1]",
        "\\providecommand{\\kwd}[1]",
        "\\providecommand{\\ead}[2][]",
        "\\providecommand{\\printead}",
        "\\providecommand{\\address}[2][]",
        "\\newenvironment{frontmatter}",
        "\\newenvironment{aug}",
        "\\newenvironment{keyword}",
        "\\maketitle",
    ):
        assert frag in body, f"imsart 缺 {frag}"
    # \address 单参实证 (1003.1513 :29)——裸 2 必参形吞后随 token 回潮禁;
    # vendored 件取 [2][] opt+mand 形 (真件签名, 单参调用兼容)。
    assert "\\providecommand{\\address}[2]{" not in body


def test_aa501_loads_aa_needs_aa() -> None:
    r"""aa501 桥 pin（0104346 实证面）：``loads`` 桥 + ``needs`` 依赖
    aa.cls 同仓 shim——leader 核准形。"""
    spec = _shim_map()["aa501.cls"]
    assert spec.get("loads") == "aa"
    assert spec.get("needs") == ["aa.cls"]
    assert "body" not in spec


def test_flushrt_shim_present() -> None:
    r"""flushrt shim pin（9910310 ``\usepackage{aaspp4,flushrt}`` 升级稿
    实证）：noop+``\raggedleft`` 语义即可——缺失态 2.09 option 链断点。"""
    body = _shim_body("flushrt.sty")
    assert "\\raggedleft" in body


# ------------------------------------------------------- round-2: shim body 真编译钉


def _write_shim(wdir: Path, name: str) -> None:
    r"""把 shim_map body (或 loads 模板) 物化成 wdir/<name>——复刻
    ``_builtins_shim`` 的 emit 面, 编译钉直打真实生成物。槽已删名
    改物化 vendored_fetch 实件 (同服务物)。"""
    spec = _shim_map().get(name)
    if spec is None:
        vend = _vendor_file(name)
        if vend is None:
            raise KeyError(name)
        (wdir / name).write_text(vend.read_text(encoding="utf-8"), encoding="utf-8")
        return
    body = spec.get("body")
    if body is None:
        loads = spec["loads"]
        stem = name.rsplit(".", 1)[0]
        body = (
            "\\NeedsTeXFormat{LaTeX2e}\n"
            f"\\ProvidesClass{{{stem}}}[2026/09/19 fixloop legacy shim -> {loads}]\n"
            f"\\LoadClassWithOptions{{{loads}}}\n"
            "\\endinput\n"
        )
    (wdir / name).write_text(body, encoding="utf-8")


@pytest.mark.integration
@_COMPILE
def test_svglov3_clo_input_mid_class_load(tmp_path: Path) -> None:
    r"""class-load 语境 ``\input svglov3.clo`` 后 ``\@``-cs/``\p@`` 仍可解析
    ——catcode 泄漏实测（1608.06693 ``15\p@`` 断读签名复现位）。"""
    shutil.copy(STUBS / "svglov3.clo", tmp_path / "svglov3.clo")
    (tmp_path / "minicls.cls").write_text(
        "\\NeedsTeXFormat{LaTeX2e}\n"
        "\\ProvidesClass{minicls}\n"
        "\\input{svglov3.clo}\n"
        "\\newlength{\\mylen}\\setlength{\\mylen}{15\\p@}\n"
        "\\LoadClass{article}\n",
        encoding="utf-8",
    )
    log = _run(
        tmp_path,
        r"""\documentclass{minicls}
\begin{document}
len ok
\end{document}
""",
    )
    assert _n_err(log) == 0, f"仍 {_n_err(log)} 个 '!' 错 (catcode 泄漏回潮)"
    assert (tmp_path / "main.pdf").is_file()


@pytest.mark.integration
@_COMPILE
def test_cimento_polyfills_compile(tmp_path: Path) -> None:
    r"""cimento shim body 编译钉：0905.4620 签名面——``\instlist``/``\PACSes``
    preamble 期调用（:14/:16, ``\begin{document}``:25）0 错无泄漏。"""
    _write_shim(tmp_path, "cimento.cls")
    log = _run(
        tmp_path,
        r"""\documentclass{cimento}
\title{T}
\author{C. Giunti\from{ins:x}}
\instlist{\inst{ins:x} INFN, Sezione di Torino, Italy}
\PACSes{\PACSit{14.60.Pq}{Neutrino oscillations}\PACSit{26.65}{Solar}}
\begin{document}
\maketitle
text.
\end{document}
""",
    )
    assert _n_err(log) == 0, f"仍 {_n_err(log)} 个 '!' 错"
    assert "Missing \\begin{document}" not in log
    assert (tmp_path / "main.pdf").is_file()


@pytest.mark.integration
@_COMPILE
def test_pasj00_polyfills_compile(tmp_path: Path) -> None:
    r"""pasj00 shim body 编译钉：1003.0945 签名面——``\DeclareAbbreviation``
    preamble 定义件 + frontmatter in-doc 调用（:77-114 实位）+ ``\citet``
    natbib 面 + ``\altaffil*`` AAS 件，0 错。"""
    _write_shim(tmp_path, "pasj00.cls")
    log = _run(
        tmp_path,
        r"""\documentclass{pasj00}
\DeclareAbbreviation\apj{Astrophys. J.}
\DeclareAbbreviation\mnras{Mon. Not. R. Astron. Soc.}
\draft
\begin{document}
\SetRunningHead{M. Uemura, et al.}{WZ Sge stars}
\Received{2010/01/04}
\Accepted{2010/03/03}
\title{T}
\author{M. \textsc{Uemura}\altaffilmark{1}}
\altaffiltext{1}{Hiroshima University \email{u@h.jp}}
\KeyWords{stars: novae}
\maketitle
ref \apj\ and \mnras; \citet{key} said.
\begin{thebibliography}{9}
\bibitem{key} X 2010
\end{thebibliography}
\end{document}
""",
    )
    assert _n_err(log) == 0, f"仍 {_n_err(log)} 个 '!' 错"
    assert "Missing \\begin{document}" not in log
    assert (tmp_path / "main.pdf").is_file()


@pytest.mark.integration
@_COMPILE
def test_pos_polyfills_compile(tmp_path: Path) -> None:
    r"""PoS shim body 编译钉：1306.5919 签名面——``\ShortTitle``/``\author``
    /命令形 ``\abstract``/``\FullConference`` 全在 preamble（:8-37,
    ``\begin{document}``:41）+ ``acknowledgments`` env，0 错无泄漏。"""
    _write_shim(tmp_path, "PoS.cls")
    log = _run(
        tmp_path,
        r"""\documentclass{PoS}
\ShortTitle{From p+p to Pb+Pb}
\title{T}
\author{\speaker{M. Gazdzicki} E-mail: \email{m@cern.ch}}
\abstract{This is the abstract text.}
\FullConference{8th International Workshop}
\begin{document}
\maketitle
text.
\begin{acknowledgments}
Thanks.
\end{acknowledgments}
\end{document}
""",
    )
    assert _n_err(log) == 0, f"仍 {_n_err(log)} 个 '!' 错"
    assert "Missing \\begin{document}" not in log
    assert (tmp_path / "main.pdf").is_file()


@pytest.mark.integration
@_COMPILE
def test_imsart_arxiv_compile(tmp_path: Path) -> None:
    r"""imsart 编译钉（1003.1513 签名面）：``\arxiv`` preamble 期 +``frontmatter``/``aug``/``keyword`` 结构 env + ``\kwd/\ead/\thanksref``。
    稿内无 ``\maketitle``——frontmatter env 尾触之。"""
    _write_shim(tmp_path, "imsart.cls")
    log = _run(
        tmp_path,
        r"""\documentclass{imsart}
\arxiv{math.PR/0000512}
\begin{document}
\begin{frontmatter}
\title{T}
\runtitle{T short}
\begin{aug}
\author{Y. Ritov\thanksref{t2}\ead[label=e1]{y@x.edu}}
\thankstext{t2}{Supported.}
\affiliation{Hebrew University}
\address{Dept of Statistics \printead{e1}}
\end{aug}
\begin{abstract}
Abs text.
\end{abstract}
\begin{keyword}
\kwd{Foundations}
\kwd{Time series}
\end{keyword}
\end{frontmatter}
text.
\end{document}
""",
    )
    assert _n_err(log) == 0, f"仍 {_n_err(log)} 个 '!' 错"
    assert "Missing \\begin{document}" not in log
    assert (tmp_path / "main.pdf").is_file()


@pytest.mark.integration
@_COMPILE
def test_aa501_bridges_aa_shim(tmp_path: Path) -> None:
    r"""aa501→aa 链编译钉：``loads`` 桥 emit + aa.cls body 双件物化,
    A&A polyfill 面 (``\offprints/\inst/\keywords``) 可用。"""
    _write_shim(tmp_path, "aa501.cls")
    _write_shim(tmp_path, "aa.cls")
    log = _run(
        tmp_path,
        r"""\documentclass{aa501}
\offprints{A. Author}
\begin{document}
\title{T}
\author{A\inst{1}}
\institute{Inst 1}
\maketitle
\keywords{stars: test}
text.
\end{document}
""",
    )
    assert _n_err(log) == 0, f"仍 {_n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()


# ------------------------------------------------------- round-3: geom.sty 深件


def test_geom_kit() -> None:
    r"""geom body pin（0806.0904/0806.2953 实证，CTAN geomsty 取件核实面）：
    三 ``\if`` 真身默认 true + ``\presection`` ``\newskip``（稿
    ``\@startsection`` ``\advance\@tempskipa by\presection`` 直读）+
    ``\newtheorem`` ``[{i}{}]{n}`` 派工系（``\@nnthm``→``\@xnnthm``|``\@ynnthm``
    计数创建 → ``\@nnnthm`` runner，``\@enva``|``\@envb`` env 桥）+
    ``proof``/``Figure`` env 基座（稿仅 ``\renewenvironment``）+
    ``\provedbox``/``\captionskip``/``\@captionmargin``/``\@captionwidth``
    + ``\prooftag`` 0 参（``\pro@f[\prooftag]`` 当值用）+ catcode 免疫段。"""
    body = _shim_body("geom.sty")
    for frag in (
        "\\newif\\ifproofing \\proofingtrue",
        "\\newif\\ifautolabel \\autolabeltrue",
        "\\newif\\ifstarredcontents \\starredcontentstrue",
        "\\newskip\\presection \\presection 0pt plus 10ex",
        "\\newskip\\captionskip \\captionskip=10pt",
        "\\newbox\\provedbox",
        "\\newenvironment{proof}",
        "\\newenvironment{Figure}",
        "\\providecommand{\\prooftag}{}",
        "\\providecommand{\\raggedcenter}{\\centering}",
        "\\providecommand{\\Bbb}{\\mathbb}",
        "\\RequirePackage{amssymb}",
        "\\RequirePackage{amsmath}",
        "\\catcode 64=",
        "\\def\\newtheorem{\\@ifnextchar[",
        "\\long\\def\\@newtheorem[#1]{\\@@newtheorem#1}",
        "\\def\\@nnthm#1#2{\\@ifnextchar[",
        "\\def\\@xnnthm#1#2[#3]{\\@definecounter{#1}\\@addtoreset{#1}{#3}",
        "\\def\\@ynnthm#1#2{\\@definecounter{#1}",
        "\\def\\@enva#1#2[#3]{\\begin{#1@}[#3]#2}",
        "\\def\\@envb#1#2{\\begin{#1@}#2}",
        "\\@namedef{#1@}{\\@nnnthm{#1}{#2}}",
        "\\newdimen\\@captionmargin",
        "\\newdimen\\@captionwidth",
        "\\geomrestore",
    ):
        assert frag in body, f"geom 缺 {frag}"
    # \presection 宏版回潮禁（真身是 skip 寄存器）。
    assert "\\providecommand{\\presection}" not in body
    # \prooftag [1] 版回潮禁（吞 \pro@f 后随 token）。
    assert "\\providecommand{\\prooftag}[" not in body


@pytest.mark.integration
@_COMPILE
def test_geom_polyfills_compile(tmp_path: Path) -> None:
    r"""geom shim 编译钉（0806.0904 装载形复刻）：稿 ``\makeatletter`` 区内
    ``\input{geom.sty}``（@=11 装载）→ ``\newtheorem`` 双形态派工 +
    ``\renewenvironment{proof}``/``{Figure}`` 基座 + ``\ifstarredcontents``
    直读 + ``\prooftag`` 值位 + ``\Bbb`` + ``\margins`` preamble 期，0 错。"""
    _write_shim(tmp_path, "geom.sty")
    log = _run(
        tmp_path,
        r"""\documentclass{article}
\makeatletter
\def\usepackage#1{\input{#1.sty}}
\input{geom.sty}
\makeatother
\newtheorem{lemma}{Lemma}
\newtheorem{nlemma}{NLemma}[section]
\newtheorem[{\ns}{}]{remark}[nlemma]{Remark}
\margins{3cm}{2cm}
\renewenvironment{proof}[1][pf]{\trivlist\item[{\bf #1}.]}{\endtrivlist}
\renewenvironment{Figure}{\begin{figure}}{\end{figure}}
\begin{document}
\section*{Starred}
\begin{lemma}body\end{lemma}
\begin{remark}rk\end{remark}
\begin{proof}done\end{proof}
$\Bbb R^2$ \prooftag {\raggedcenter x}
\end{document}
""",
    )
    assert _n_err(log) == 0, f"仍 {_n_err(log)} 个 '!' 错"
    assert "Missing \\begin{document}" not in log
    assert (tmp_path / "main.pdf").is_file()


def test_vendor_stubs_provides_optional_arg_dated() -> None:
    r"""vendor/stubs + vendor/shims 全件 ``\Provides{Package,Class,File,ExplPackage}{n}[o]``
    可选参必须 ``YYYY/MM/DD`` 前缀——裸文本经 ``\@parse@version@`` 把版本串
    漏进排版流 → ``Missing \begin{document}``（slashlane 实证, slashbox
    de1ba13 同工钉）。"""
    rx = re.compile(
        r"\\Provides(?:Package|Class|File|ExplPackage)\{[^}]*\}\s*\[([^\]]*)\]"
    )
    bad = []
    for f in sorted(STUBS.iterdir()) + sorted(SHIMS.iterdir()):
        if not f.is_file():
            continue
        for line in f.read_text(encoding="latin-1").splitlines():
            code = re.sub(r"(?<!\\)%.*", "", line)
            bad.extend(
                f"{f.name}: {m.group(0)}"
                for m in rx.finditer(code)
                if not re.match(r"\s*\d{4}/\d{2}/\d{2}", m.group(1))
            )
    assert not bad, "undated \\Provides* optional args: " + "; ".join(bad)
