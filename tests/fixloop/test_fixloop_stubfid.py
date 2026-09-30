"""vendor-stub fidelity pins（task #323 stubfid 车道，singtail census
"vendor-stub-fidelity" 簇 5 格）。

实证驱动的五处 stub 升级：

- 2609.19431 ``option-tolerance``：``\\usepackage[utf8]{xetex-inputenc}``
  在 shim 体下炸 ``Unknown option`` —— LaTeX 内核对 ``.sty`` 未知选项是
  硬错误（``.cls`` 仅 ``\\@unusedoptionlist`` 警告），noop stub 必须
  ``\\DeclareOption*{}``+``\\ProcessOptions`` 吞任意选项。本仓 shim_map
  全部 28 个 ``.sty`` 体已扫平，pin 成不变量。
- 2609.20764 ``counter``（误诊更正 → unkopt 接管）：真身 bxcjkjatype 是
  pTeX 专用包引擎自拒；unkopt 的 ``bxcjkjatype_engine_retire`` 臂
  （70-pkgopt.yaml order 201，注释掉装载行）已获采纳，本仓不做遮蔽件。
- 0807.5094 ``counter``：siamltex.cls 原与 siamart 共享 ``siam_body``
  纯桥体，缺真身定理机 —— 稿侧 ``\\newtheorem`` 裸调炸 ``already defined``
  / ``undefined env``。已拆分为带 ``onethmnum`` 选项 + theorem 计数器 +
  四个联动 env + ``\\proof`` 的独立体（真身 corpus/1102.0075 抄值）；
  siamart 侧保留纯桥（真身走 amsthm + 稿自定义，预定义必撞）。
- 1308.0304 ``bib-group``（误诊更正）：病灶是 ``\\href`` ×107 未定义 →
  Missing-$ 级联，非 thebibliography 形状。JHEP3.cls/JHEP.cls vendor
  件 + sissa_body（jhep.cls/jcap.cls shim_map 活键）补上 ``\\href`` 打印面
  + 19 宏 eprint 档号族（真身 JHEP3.cls :1687-1705 镜像）。
- 0712.1912（weak）：``\\@author`` 内 ``itemize``/``\\bigskip`` 被 article
  ``\\@maketitle`` 的 ``tabular{c}`` 囚 → ``Not allowed in LR mode``；
  真身 JHEP3 用 flushleft 段落式，同款镜像进三体。
- 2505.06598 ``svjour_clo_stub`` 自残（residtail 移交）：builtin 写的纯
  ``\\endinput`` noop ``sv<opt>.clo`` 遮蔽了真件内嵌的 size10.clo 复刻本
  → ``\\normalsize`` 停在 kernel ``\\@latex@error`` stub（latex.ltx），
  fontspec-xetex:443/ctex:715 报 "font size command \\normalsize is not
  defined"。``_SVJOUR_CLO_BODY`` 升级为 noop + size-family 播种
  （真件 corpus/1107.0209 svepj.clo:46-72 抄值）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.builtins.shim import _SVJOUR_CLO_BODY
from texlate.compile.fixloop.engine import LoopCtx

SHIMS = (
    Path(__file__).resolve().parents[2] / "src/texlate/compile/fixloop/vendor/shims"
)

_XELATEX = shutil.which("xelatex")
_COMPILE = pytest.mark.skipif(_XELATEX is None, reason="xelatex not installed")

#: option-tolerance 扫平时的 shim_map .sty 体数下限（2026-09-20 为 28）。
_MIN_STY_BODIES = 25


def _shim_map() -> dict[str, dict]:
    rules = {r.id: r for r in load_ruleset().rules}
    return rules["legacy_pkg_shim"].action["params"]["shim_map"]


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


def _ctx(wdir: Path) -> LoopCtx:
    (wdir / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    return LoopCtx(wdir=wdir, engine_name="xelatex", main_rel="main.tex")


# ------------------------------------------------- option-tolerance 扫平
def test_all_sty_shim_bodies_option_tolerant() -> None:
    r"""shim_map 全部 .sty 体 = ``\DeclareOption*``+``\ProcessOptions``
    （.sty 未知选项是硬错误，noop 拒收即炸——2609.19431 实证）。"""
    names = [n for n in _shim_map() if n.endswith(".sty")]
    assert len(names) >= _MIN_STY_BODIES, f"sty 体数异常收缩: {names}"
    for name in names:
        code = _code_lines(_shim_body(name))
        assert "\\DeclareOption*" in code, f"{name} 缺 catch-all 选项"
        assert "\\ProcessOptions" in code, f"{name} 缺 \\ProcessOptions"


def test_xetex_inputenc_option_tolerance() -> None:
    """2609.19431 本体钉: xetex-inputenc 吞 [utf8] 等任意选项。"""
    code = _code_lines(_shim_body("xetex-inputenc.sty"))
    assert "\\DeclareOption*{}" in code
    assert "\\ProcessOptions" in code


# ------------------------------------------------- siamltex 定理机拆分
def test_siamltex_theorem_machinery() -> None:
    r"""0807.5094 本体钉: siamltex 真身定理机——onethmnum 选项、section
    父计数器 theorem + 四个联动 env + ``\proof``/``\@begintheorem`` 三件套。"""
    code = _code_lines(_shim_body("siamltex.cls"))
    for frag in (
        "\\ProvidesClass{siamltex}",
        "\\DeclareOption{onethmnum}",
        "\\ProcessOptions",
        "\\newtheorem{theorem}{Theorem}[section]",
        "\\newtheorem{lemma}[theorem]{Lemma}",
        "\\newtheorem{corollary}[theorem]{Corollary}",
        "\\newtheorem{proposition}[theorem]{Proposition}",
        "\\newtheorem{definition}[theorem]{Definition}",
        "\\def\\proof",
        "\\@begintheorem",
        "\\@endtheorem",
    ):
        assert frag in code, f"siamltex 缺 {frag}"


def test_siamart_stays_plain_bridge() -> None:
    """拆分护栏: siamart 真身走 amsthm + 稿自定义 \\newtheorem——共享体
    预定义定理 env 必炸 already-defined，siamart 体保持纯桥。"""
    code = _code_lines(_shim_body("siamart.cls"))
    assert "\\ProvidesClass{siamart}" in code
    assert "\\newtheorem" not in code


# ------------------------------------------------- JHEP \href/eprint/\@maketitle
_JHEP_FRAGS = (
    "\\providecommand{\\href}[2]{#2}",
    "\\providecommand{\\hepth}[1]",
    "\\providecommand{\\hepph}[1]",
    "\\providecommand{\\Math}[2]",
    "\\providecommand{\\arXivid}[1]",
    "\\def\\@maketitle",
    "flushleft",
)


@pytest.mark.parametrize("fname", ["JHEP3.cls", "JHEP.cls"])
def test_jhep_vendor_shim_fidelity(fname: str) -> None:
    r"""1308.0304+0712.1912 本体钉: vendor 件 \href 打印面 + eprint 族 +
    段落式 ``\@maketitle``（真身 JHEP3.cls :485/:1687-1705 镜像）。"""
    code = _code_lines((SHIMS / fname).read_text(encoding="utf-8"))
    for frag in _JHEP_FRAGS:
        assert frag in code, f"{fname} 缺 {frag}"


@pytest.mark.parametrize("key", ["jhep.cls", "jcap.cls"])
def test_jhep_shim_map_body_fidelity(key: str) -> None:
    """sissa_body 活键同步钉: shim_map jhep.cls/jcap.cls 与 vendor 件同面。"""
    code = _code_lines(_shim_body(key))
    for frag in _JHEP_FRAGS:
        assert frag in code, f"shim_map {key} 缺 {frag}"


# ------------------------------------------------- svjour .clo size 播种
def test_svjour_clo_stub_seeds_size_family() -> None:
    r"""2505.06598 本体钉: ``_SVJOUR_CLO_BODY`` 播 ``\normalsize`` 族——
    ``\renewcommand`` 覆盖 kernel error-stub + 调一次 ``\normalsize``
    初始化 ``\@currsize``/``\f@size`` 寄存器（fontspec/ctex 探测点）。"""
    code = _code_lines(_SVJOUR_CLO_BODY)
    assert "\\renewcommand\\normalsize" in code
    assert "\\@setfontsize\\normalsize" in code
    assert "\n\\normalsize\n" in _SVJOUR_CLO_BODY
    for cs in (
        "small",
        "footnotesize",
        "scriptsize",
        "tiny",
        "large",
        "Large",
        "LARGE",
        "huge",
        "Huge",
    ):
        assert f"\\providecommand\\{cs}" in code, f"缺 \\{cs}"
    assert "\\endinput" in code


def test_svjour_clo_stub_writes_seeded_body(tmp_path: Path) -> None:
    """端到端写件钉: ``svjour_clo_stub`` 按 docclass 选项落 sv<opt>.clo,
    落件体含 size-family 播种（指纹闸 sha 变 → 旧 noop 自动刷新）。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass[epj]{svjour}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, note = TRANSFORM_FNS["svjour_clo_stub"](ctx, None, None, {})
    assert ok, note
    body = (tmp_path / "svepj.clo").read_text(encoding="utf-8")
    assert "\\@setfontsize\\normalsize" in body


# ------------------------------------------------- xelatex 编译钉
@_COMPILE
@pytest.mark.integration
def test_compile_xetex_inputenc_utf8(tmp_path: Path) -> None:
    """2609.19431 端到端: stub 在场时 [utf8] 选项不再炸 Unknown option。"""
    log = _run(
        tmp_path,
        "\\documentclass{article}\n\\usepackage[utf8]{xetex-inputenc}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        {"xetex-inputenc.sty": _shim_body("xetex-inputenc.sty")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_siamltex_theorems(tmp_path: Path) -> None:
    """0807.5094 端到端: siamltex stub 下 theorem/proof env 直接可用。"""
    log = _run(
        tmp_path,
        "\\documentclass{siamltex}\n\\begin{document}\n"
        "\\begin{theorem}T\\end{theorem}\n\\begin{proof}P\\end{proof}\n"
        "\\begin{lemma}L\\end{lemma}\n\\end{document}\n",
        {"siamltex.cls": _shim_body("siamltex.cls")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_jhep_href_itemized_author(tmp_path: Path) -> None:
    r"""1308.0304+0712.1912 端到端: ``\href`` 可用且 ``\author`` 内 itemize
    不再触 LR-mode 炸。"""
    log = _run(
        tmp_path,
        "\\documentclass{JHEP3}\n"
        "\\author{A\\begin{itemize}\\item x\\end{itemize}}\n\\title{T}\n"
        "\\begin{document}\n\\href{http://x}{y} \\hepph{0101001}\n\\end{document}\n",
        {"JHEP3.cls": (SHIMS / "JHEP3.cls").read_text(encoding="utf-8")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_svjour_clo_size_seed(tmp_path: Path) -> None:
    r"""2505.06598 端到端: stub .clo 播种后 ``\normalsize`` 族在 fontspec/
    ctex 面前有效——模拟真 .clo 缺席的 svjour 场景。"""
    (tmp_path / "svjour.cls").write_text(
        "\\NeedsTeXFormat{LaTeX2e}\n\\ProvidesClass{svjour}\n"
        "\\DeclareOption*{\\InputIfFileExists{sv\\CurrentOption.clo}"
        "{\\let\\journalopt\\CurrentOption}{}}\n"
        "\\ProcessOptions\n\\LoadClass{article}\n\\endinput\n",
        encoding="utf-8",
    )
    log = _run(
        tmp_path,
        "\\documentclass[epj]{svjour}\n\\usepackage{fontspec}\n"
        "\\begin{document}\nx {\\small y} {\\Huge z}\n\\end{document}\n",
        {"svepj.clo": _SVJOUR_CLO_BODY},
    )
    assert _n_err(log) == 0
    assert "font size command" not in log
