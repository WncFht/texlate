"""eraimpl lane pins — eracls2 后续批 (task #350, failmine7 普查
``tmp/lane-eracls2/candidates.json`` 出处逐条注 yaml 注释)。

四组件：

- ``90-shim-legacy.yaml::legacy_pkg_shim`` shim_map 新 8 键：
  ``l-aa.cls`` (×4 格, A&A Letters 变体 → vendored stubs/aa.cls 桥)、
  ``aip.cls`` (纯 article 面桥)、``ioplppt.cls`` (→ vendored files/
  iopart.cls 桥)、``ichep.cls`` (article 底 + ``\\affil``/命令形
  ``\\abstract``/``\\fnm`` 三件面)、``sn-jnl.cls`` (Springer Nature
  投稿类 frontmatter 面, journal-shipped 非 CTAN)、``mncite.sty``
  (MNRAS cite 伴船 noop+别名)、``cropmark.sty`` (纯 noop)、
  ``revtex.sty`` (REVTeX3 伴船 sty——原身 class-in-sty 架构,
  ``\\@currext`` 存复位绕 latex.ltx 硬拒)。
- ``vendor/stubs/siam1{0,1,2}.clo``：siamltex.cls 真件 (2511.16127
  随稿) ``:107 \\input{siam1\\@ptsize.clo}`` 尺寸件——内核 sizeNN.clo
  直通全真播种 (svglov3.clo 同款 catcode 存复裹两语境安全)。
- ``40-install.yaml::doc_absent_stub`` exts 表 +4：``.pgf`` (2506.05065
  ``figures/legendre.pgf`` 子目录位)、``.tikz`` (2603.07778)、
  ``.latex`` (chao-dyn/9412002)、``.cfg`` (2604.03663 econsocart.cls
  ``:67 \\input{econsocart.cfg}`` 伴生缺档)。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx

_ROOT = Path(__file__).resolve().parent.parent / "src/texlate/compile/fixloop"
STUBS = _ROOT / "vendor/stubs"
FILES = _ROOT / "vendor/files"

_XELATEX = shutil.which("xelatex")
_COMPILE = pytest.mark.skipif(_XELATEX is None, reason="xelatex not installed")


def _rule_params(rule_id: str) -> dict:
    rules = {r.id: r for r in load_ruleset().rules}
    return rules[rule_id].action["params"]


def _shim_map() -> dict[str, dict]:
    return _rule_params("legacy_pkg_shim")["shim_map"]


def _shim_body(name: str) -> str:
    spec = _shim_map().get(name)
    assert spec is not None, f"{name} 不在 shim_map"
    assert "body" in spec, f"{name} 无 body 键"
    return spec["body"]


def _code_lines(body: str) -> str:
    """滤 % 注释行——pin 断言不得被注释文本夹带。"""
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("%"))


def _run(wdir: Path, tex: str, extra: dict[str, str] | None = None) -> str:
    (wdir / "main.tex").write_text(tex, encoding="utf-8")
    for name, body in (extra or {}).items():
        (wdir / name).write_text(body, encoding="utf-8")
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


# ════════════════════════════ shim_map 新键形状钉 ════


def test_shim_map_loads_entries() -> None:
    """loads 形三键精确 dict——替身真件均在 vendor 域。"""
    sm = _shim_map()
    assert sm.get("l-aa.cls") == {"loads": "aa", "needs": ["aa.cls"]}
    assert sm.get("aip.cls") == {"loads": "article"}
    assert sm.get("ioplppt.cls") == {"loads": "iopart", "needs": ["iopart.cls"]}
    # needs 声明的 vendored 替身必须在场, 否则 loads 桥落空
    assert (STUBS / "aa.cls").is_file()
    assert (FILES / "iopart.cls").is_file()


def test_shim_map_body_entries() -> None:
    """body 形五键在册。"""
    sm = _shim_map()
    for key in (
        "ichep.cls",
        "sn-jnl.cls",
        "mncite.sty",
        "cropmark.sty",
        "revtex.sty",
    ):
        assert isinstance(sm.get(key, {}).get("body"), str), f"{key} 无 body"


# ════════════════════════════ ichep.cls 体面钉 ════


def test_ichep_body() -> None:
    r"""ICHEP94 三件面：``\affil`` 累进 + 命令形 ``\abstract`` provide+renew
    双写 (article env-begin 同名占位——裸 provide 会让 {参} 入 env 排版
    且 env 不闭合炸 ``\@checkend``) + ``\maketitle`` 后放出。"""
    code = _code_lines(_shim_body("ichep.cls"))
    for frag in (
        "\\ProvidesClass{ichep}",
        "\\LoadClassWithOptions{article}",
        "\\def\\ich@affils{}",
        "\\providecommand{\\affil}[1]",
        "\\providecommand{\\abstract}{}",
        "\\renewcommand{\\abstract}[1]{\\gdef\\ich@abstract{#1}}",
        "\\let\\ich@maketitle\\maketitle",
        "\\renewcommand{\\maketitle}",
        "\\ich@affils",
        "\\ich@abstract",
        "\\endinput",
    ):
        assert frag in code, f"ichep 缺 {frag}"
    # provide 必须先于 renew (env-begin 占位才落得进去)
    assert code.index("\\providecommand{\\abstract}") < code.index(
        "\\renewcommand{\\abstract}"
    )


def test_ichep_fnm_superscript_form() -> None:
    r"""``\fnm{N}{t}`` 显式脚注号 = superscript+footnote 双件——``\@maketitle``
    内 ``\let\footnote\thanks`` 不吃可选参, 直传 ``[#1]`` 会留 ``1]t``
    残文 (pdftotext 实证)。"""
    code = _code_lines(_shim_body("ichep.cls"))
    assert "\\providecommand{\\fnm}[2]{\\textsuperscript{#1}\\footnote{#2}}" in code
    assert "\\footnote[#1]" not in code


# ════════════════════════════ sn-jnl.cls 体面钉 ════


def test_snjnl_body() -> None:
    r"""sn-jnl frontmatter 面：``\title[..]`` opt 宽容 + ``\author[*][N]``
    星号+可选参双路由累进 ``\@author`` + ``\affil[*][N]`` 星号吞弃 +
    ``\abstract{}/\keywords{}`` 累进 + org* 八件参文直印。"""
    code = _code_lines(_shim_body("sn-jnl.cls"))
    for frag in (
        "\\ProvidesClass{sn-jnl}",
        "\\LoadClassWithOptions{article}",
        "\\renewcommand{\\title}{\\@ifnextchar[{\\snj@title@o}{\\snj@title@p}}",
        "\\renewcommand{\\author}{\\@ifstar{\\snj@author@s}{\\snj@author@n}}",
        "\\snj@addauthor",
        "\\g@addto@macro\\@author{\\and #1}",
        "\\providecommand{\\affil}{\\@ifstar{\\snj@affil@x}{\\snj@affil@x}}",
        "\\snj@addaffil",
        "\\renewcommand{\\abstract}[1]{\\gdef\\snj@abstract{#1}}",
        "\\providecommand{\\keywords}[1]{\\gdef\\snj@keywords{#1}}",
        "\\providecommand{\\fnm}[1]{#1}",
        "\\providecommand{\\sur}[1]{#1}",
        "\\providecommand{\\orgdiv}[1]{#1}",
        "\\providecommand{\\orgname}[1]{#1}",
        "\\providecommand{\\orgaddress}[1]{#1}",
        "\\providecommand{\\city}[1]{#1}",
        "\\providecommand{\\postcode}[1]{#1}",
        "\\providecommand{\\country}[1]{#1}",
        "\\endinput",
    ):
        assert frag in code, f"sn-jnl 缺 {frag}"


def test_snjnl_emit_sweep_idempotent() -> None:
    r"""emit 清位 + AtEndDocument 兜底：``\snj@emitfront`` 放出后
    ``\global\let`` 各累进件 ``\@empty`` (重调幂等), ``\maketitle``
    钩 + ``\AtEndDocument`` 扫残——preamble/正文任意调用序不丢内容。"""
    code = _code_lines(_shim_body("sn-jnl.cls"))
    assert "\\def\\snj@emitfront" in code
    for frag in (
        "\\global\\let\\snj@affils\\@empty",
        "\\global\\let\\snj@abstract\\@empty",
        "\\global\\let\\snj@keywords\\@empty",
    ):
        assert frag in code, f"sn-jnl emit 缺 {frag}"
    assert "\\let\\snj@maketitle\\maketitle" in code
    assert "\\renewcommand{\\maketitle}{\\snj@maketitle\\snj@emitfront}" in code
    assert "\\AtEndDocument{\\snj@emitfront}" in code


# ════════════════════════════ mncite/cropmark/revtex.sty 体钉 ════


def test_mncite_body() -> None:
    r"""mncite noop+cite 别名兜底：``\citep/\citet/\citealt/\citealp`` →
    ``\cite[#1]{#2}``; ``\citeauthor/\citeyear`` → 印第二参。"""
    code = _code_lines(_shim_body("mncite.sty"))
    for cs in ("citep", "citet", "citealt", "citealp"):
        assert f"\\providecommand{{\\{cs}}}[2][]{{\\cite[#1]{{#2}}}}" in code, cs
    assert "\\providecommand{\\citeauthor}[2][]{#2}" in code
    assert "\\providecommand{\\citeyear}[2][]{#2}" in code


def test_cropmark_body_pure_noop() -> None:
    """cropmark 裁切标记无内容语义——纯 noop, 任何命令提供都是污染。"""
    code = _code_lines(_shim_body("cropmark.sty"))
    assert "\\ProvidesPackage{cropmark}" in code
    assert "\\ProcessOptions" in code
    assert "\\providecommand" not in code
    assert "\\newcommand" not in code


def test_revtex_sty_body() -> None:
    r"""REVTeX3 伴船 sty：``\@ifundefined{@maketitle}`` 闸内 ``\@currext``
    存复位绕 ``\\LoadClass`` in-package 硬拒 (latex.ltx:18629) +
    ``\address/\andaddress/\pacs`` 累进 ``\rtx@front`` (就地印会炸
    preamble 调用 Missing-\begin{document}) \maketitle 钩 +
    AtEndDocument 扫残 + revtex3 残面 polyfill 表。"""
    code = _code_lines(_shim_body("revtex.sty"))
    for frag in (
        "\\ProvidesPackage{revtex}",
        "\\@ifundefined{@maketitle}",
        "\\let\\rtx@save@currext\\@currext",
        "\\let\\@currext\\@clsextension",
        "\\LoadClass{article}",
        "\\let\\@currext\\rtx@save@currext",
        "\\def\\rtx@front{}",
        "\\providecommand{\\address}[1]",
        "\\providecommand{\\andaddress}[1]",
        "\\providecommand{\\pacs}[1]",
        "\\g@addto@macro\\rtx@front",
        "\\def\\rtx@emitfront",
        "\\global\\let\\rtx@front\\@empty",
        "\\renewcommand{\\maketitle}{\\rtx@maketitle\\rtx@emitfront}",
        "\\AtEndDocument{\\rtx@emitfront}",
        "\\providecommand{\\preprint}[1]{}",
        "\\providecommand{\\draft}{}",
        "\\providecommand{\\tighten}{}",
        "\\providecommand{\\widetext}{}",
        "\\providecommand{\\narrowtext}{}",
        "\\providecommand{\\submit}[1]{}",
        "\\endinput",
    ):
        assert frag in code, f"revtex.sty 缺 {frag}"


def test_revtex_sty_loadclass_only_inside_gate() -> None:
    r"""不变量：``\LoadClass{article}`` 必须坐 ``\@ifundefined{@maketitle}``
    闸内——已载真类场景 ``\@ifl@aded`` clashchk 空参幂等, 裸调会双载类。"""
    code = _code_lines(_shim_body("revtex.sty"))
    assert code.index("\\@ifundefined{@maketitle}") < code.index("\\LoadClass{article}")
    assert code.count("\\LoadClass{article}") == 1


# ════════════════════════════ siam .clo vendored stub 钉 ════


@pytest.mark.parametrize("n", ["10", "11", "12"])
def test_siam_clo_stubs_vendored(n: str) -> None:
    r"""siamNN.clo 三件在 vendor/stubs——siamltex 真件 ``\input{siam1\@ptsize
    .clo}`` 尺寸臂; 内核 ``sizeNN.clo`` 直通 = ``\normalsize`` 族全真播种
    (空 stub 会让 ``\normalsize`` 停 kernel error-stub → fontspec/ctex
    级联, svjour_clo_stub/_SVJOUR_CLO_BODY 同案)。"""
    p = STUBS / f"siam{n}.clo"
    assert p.is_file(), f"{p.name} 不在 vendor/stubs"
    code = _code_lines(p.read_text(encoding="utf-8"))
    for frag in (
        f"\\ProvidesFile{{siam{n}.clo}}",
        "\\edef\\siamclorestore{\\catcode 64=\\the\\catcode 64\\relax}",
        "\\catcode 64=11\\relax",
        f"\\input{{size{n}.clo}}",
        "\\siamclorestore",
        "\\endinput",
    ):
        assert frag in code, f"{p.name} 缺 {frag}"
    # catcode 存 → 置位 → input → 复 次序钉
    assert code.index("\\edef\\siamclorestore") < code.index("\\catcode 64=11")
    assert code.index("\\catcode 64=11") < code.index(f"\\input{{size{n}.clo}}")
    assert code.index(f"\\input{{size{n}.clo}}") < code.rindex("\\siamclorestore")


# ════════════════════════════ doc_absent exts 扩位接线钉 ════


class _EngStub:
    """builtin 直驱引擎替身——doc_absent_stub ``del eng`` 不触引擎面。"""

    def probe_file(self, fname: str, cwd: Path | None = None) -> None:
        del fname, cwd

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return False


def _stub_wired(ctx: LoopCtx, payload: str | None) -> tuple[bool, str]:
    """经 ruleset 实载 ``rule.action.params`` 直驱——钉 yaml→builtin 接线。"""
    rule = next(r for r in load_ruleset().rules if r.id == "doc_absent_stub")
    return TRANSFORM_FNS["doc_absent_stub"](
        ctx, _EngStub(), payload, rule.action.get("params") or {}
    )


@pytest.mark.parametrize(
    ("payload", "site"),
    [
        ("figures/legendre.pgf", "figures/legendre.pgf"),  # 2506.05065 子目录位
        ("vanilla.tikz", "vanilla.tikz"),  # 2603.07778
        ("scheme2.latex", "scheme2.latex"),  # chao-dyn/9412002
        ("econsocart.cfg", "econsocart.cfg"),  # 2604.03663 cls :67 伴生件
    ],
)
def test_docabsent_new_exts_land(tmp_path: Path, payload: str, site: str) -> None:
    """扩位四扩展名经真 params 落空 stub 于解析位 (子目录径保留)。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, note = _stub_wired(ctx, payload)
    assert ok, note
    assert "doc-absent stub" in (tmp_path / site).read_text()


# ════════════════════════════ xelatex 编译钉 ════


@_COMPILE
@pytest.mark.integration
def test_compile_ichep_frontmatter(tmp_path: Path) -> None:
    r"""ichep 端到端：``\affil`` 累进 + 命令形 ``\abstract{}`` +
    ``\fnm{N}{t}`` 于 ``\author`` 块内 (``\let\footnote\thanks`` 语境)。"""
    log = _run(
        tmp_path,
        "\\documentclass{ichep}\n"
        "\\title{T}\n"
        "\\author{A.~Author\\fnm{1}{Speaker}}\n"
        "\\affil{CERN, Geneva}\n"
        "\\abstract{Abstract body text.}\n"
        "\\begin{document}\n\\maketitle\n\\section{S}\nx\n\\end{document}\n",
        {"ichep.cls": _shim_body("ichep.cls")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_snjnl_frontmatter(tmp_path: Path) -> None:
    r"""sn-jnl 端到端：``\title[..]`` + ``\author*[N]{\fnm..\sur..}`` +
    ``\affil*[N]{\orgdiv..\orgaddress{\city..\postcode..\country}}`` +
    ``\abstract{}/\keywords{}`` → ``\maketitle`` 后放出。"""
    log = _run(
        tmp_path,
        "\\documentclass[sn-basic,pdflatex]{sn-jnl}\n"
        "\\begin{document}\n"
        "\\title[Short]{The Full Title}\n"
        "\\author*[1]{\\fnm{First} \\sur{Last}}\n"
        "\\author[2]{\\fnm{Second} \\sur{Other}}\n"
        "\\affil*[1]{\\orgdiv{Dept}, \\orgname{Uni}, "
        "\\orgaddress{\\city{Town}, \\postcode{12345}, \\country{Country}}}\n"
        "\\affil[2]{\\orgname{Other Lab}}\n"
        "\\abstract{Abstract text here.}\n"
        "\\keywords{kw1, kw2}\n"
        "\\maketitle\n"
        "\\section{Intro}\nx\n\\end{document}\n",
        {"sn-jnl.cls": _shim_body("sn-jnl.cls")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_revtex_sty_via_thin_shell(tmp_path: Path) -> None:
    r"""revtex.sty 端到端：REVTeX3 薄壳 revtex.cls (hep-th/0103239 随稿形)
    ``\input{latex209.def}`` compat 模 + ``\RequirePackage{revtex}`` →
    shim ``\@currext`` 存复位 ``\LoadClass{article}`` 不炸 + revtex3
    面 polyfill 全调。"""
    shell = (
        "\\NeedsTeXFormat{LaTeX2e}\n"
        "\\ProvidesClass{revtex}[REVTeX3 thin shell]\n"
        "\\if@compatibility\\else\\input{latex209.def}\\fi\n"
        "\\DeclareOption*{\\PassOptionsToPackage{\\CurrentOption}{revtex}}\n"
        "\\ProcessOptions\\relax\n"
        "\\RequirePackage{revtex}\n"
        "\\endinput\n"
    )
    log = _run(
        tmp_path,
        "\\documentclass{revtex}\n"
        "\\draft\\tightenlines\\preprint{X-1}\n"
        "\\title{T}\n"
        "\\author{A.~Author}\n"
        "\\address{Lab}\\andaddress{Other}\n"
        "\\pacs{12.34.Xx}\n"
        "\\begin{document}\n\\maketitle\nx \\tighten \\widetext \\narrowtext\n"
        "\\submit{J}\n\\end{document}\n",
        {"revtex.cls": shell, "revtex.sty": _shim_body("revtex.sty")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_revtex_sty_polyfill_only_with_real_class(tmp_path: Path) -> None:
    r"""闸幂等面：``\documentclass{article}\usepackage{revtex}``——
    ``\@maketitle`` 已定义 → LoadClass 臂跳过, 只留 polyfill。"""
    log = _run(
        tmp_path,
        "\\documentclass{article}\n\\usepackage{revtex}\n"
        "\\begin{document}\n\\title{T}\\author{A}\\maketitle\n"
        "\\address{L}\\pacs{P}\\draft x\n\\end{document}\n",
        {"revtex.sty": _shim_body("revtex.sty")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_mncite_aliases(tmp_path: Path) -> None:
    r"""mncite 端到端：``\citep/\citet/\citeauthor/\citeyear`` 别名落
    ``\cite`` 不炸。"""
    log = _run(
        tmp_path,
        "\\documentclass{article}\n\\usepackage{mncite}\n"
        "\\begin{document}\n"
        "\\citep{r} \\citet{r} \\citealt{r} \\citealp{r} "
        "\\citeauthor{r} \\citeyear{r}\n"
        "\\begin{thebibliography}{9}\\bibitem{r} A.~Ref.\\end{thebibliography}\n"
        "\\end{document}\n",
        {"mncite.sty": _shim_body("mncite.sty")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_cropmark_noop(tmp_path: Path) -> None:
    """cropmark 端到端：裸 usepackage + 选项透传不炸。"""
    log = _run(
        tmp_path,
        "\\documentclass{article}\n\\usepackage[cam]{cropmark}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        {"cropmark.sty": _shim_body("cropmark.sty")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_siam10_clo_docinput(tmp_path: Path) -> None:
    r"""siam10.clo 端到端 (@=other 语境)：doc 级 ``\input{siam10.clo}`` →
    catcode 存复裹内 ``size10.clo`` 直通, ``\normalsize`` 族播种。"""
    log = _run(
        tmp_path,
        "\\documentclass{article}\n\\input{siam10.clo}\n"
        "\\begin{document}\n{\\small s}{\\Large L}x\n\\end{document}\n",
        {"siam10.clo": (STUBS / "siam10.clo").read_text(encoding="utf-8")},
    )
    assert _n_err(log) == 0
    assert "File: siam10.clo" in log
    assert "File: size10.clo" in log
