"""aa.cls stub 选项机面 pin（task #250 aafidelity lane）。

真身 aa.cls v6.1–v9.2 默认 {a4paper,twoside,twocolumn,fleqn,final,10pt,
runningheads}；原 \\LoadClassWithOptions 裸转发 → 裸 \\documentclass{aa}
吃 article onecolumn/oneside/letterpaper 栏型失真，referee 无双距稿面。

stub 走 wrapper 惯用形：aa 专名 \\DeclareOption 吞位消 Unused-option
警告；catch-all 把用户选项显式转 article（cls 级 ProcessOptions 不查
\\@classoptionslist，全局选项不自暨嵌套 LoadClass——latex.ltx 实证）；
默认侧经条件臂注入（article 按声明序执行，onecolumn/oneside/leqno
均先于默认侧声明，同表必败——article.cls:96<98/84<86/99<100）；
referee 臂 = onecolumn + \\linespread{1.5}（真身 v7.0 :1334
\\baselinestretch{1.5}+\\onecolumn），AtBeginDocument 延后避开
article.cls:116 \\renewcommand\\baselinestretch{} 抹除。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

STUBS = (
    Path(__file__).resolve().parent.parent / "src/texlate/compile/fixloop/vendor/stubs"
)

_XELATEX = shutil.which("xelatex")
_COMPILE = pytest.mark.skipif(_XELATEX is None, reason="xelatex not installed")

_AA_BODY = (STUBS / "aa.cls").read_text(encoding="utf-8")


def _code_lines(body: str) -> str:
    """滤 % 注释行——pin 断言不得被注释文本夹带。"""
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("%"))


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


_PROBE = (
    r"\makeatletter\AtBeginDocument{\typeout{AAOPT>"
    r" twocol=\if@twocolumn T\else F\fi"
    r" twoside=\if@twoside T\else F\fi"
    r" pw=\the\paperwidth"
    r" bs=\baselinestretch"
    r" ofr=\the\overfullrule}}\makeatother"
)

_AA_SPECIFIC = (
    "letter",
    "onlletter",
    "online",
    "contents",
    "contentsAut",
    "rnote",
    "longauth",
    "longfn",
    "wideboxfn",
    "oldversion",
    "traditabstract",
    "structabstract",
    "runningheads",
    "envcountreset",
    "envcountsect",
    "ascii",
    "latin1",
    "latin9",
    "ansinews",
    "applemac",
    "utf8",
    "cm",
    "bibauthoryear",
    "showoverfull",
    "hideoverfull",
)


# ------------------------------------------------------- 源码级 pin（免编译）


def test_aa_option_table_present() -> None:
    """aa 专名吞位表 pin：真身声明名不得缺位（缺了 Unused-option 警告回潮）。"""
    code = _code_lines(_AA_BODY)
    for name in _AA_SPECIFIC:
        assert f"\\DeclareOption{{{name}}}" in code, f"aa.cls 缺 {name} 吞位"


def test_aa_catchall_forwards_to_article() -> None:
    """cls 级全局选项不自暨嵌套 LoadClass——catch-all 转发链不得回潮。"""
    code = _code_lines(_AA_BODY)
    assert "\\DeclareOption*{\\PassOptionsToClass{\\CurrentOption}{article}}" in code


def test_aa_defaults_conditional_arms() -> None:
    """默认侧条件注入 pin：无条件 \\PassOptionsToClass{twocolumn} 会压掉
    用户 [onecolumn]（article 声明序 twocolumn 后位必胜）。"""
    code = _code_lines(_AA_BODY)
    for flag, opt in (
        ("onecol", "twocolumn"),
        ("oneside", "twoside"),
        ("leqno", "fleqn"),
    ):
        assert (
            f"\\ifaa@{flag}\\else\\PassOptionsToClass{{{opt}}}{{article}}\\fi" in code
        ), f"aa.cls 缺 {opt} 条件默认臂"
    assert "\\PassOptionsToClass{a4paper}{article}" in code


def test_aa_override_arms_forward() -> None:
    """用户臂 pin：立 flag 抑默认 + 显式转发（leqno 不转则静默丢失）。"""
    code = _code_lines(_AA_BODY)
    for flag, opt in (
        ("onecol", "onecolumn"),
        ("oneside", "oneside"),
        ("leqno", "leqno"),
    ):
        assert f"\\aa@{flag}true\\PassOptionsToClass{{{opt}}}{{article}}" in code, (
            f"aa.cls 缺 {opt} 用户臂"
        )


def test_aa_referee_arm() -> None:
    """referee 臂 pin：onecolumn + 双距（真身 v7.0 :1334 值）；
    \\linespread 必须 AtBeginDocument 延后过 article.cls:116 抹除点。"""
    code = _code_lines(_AA_BODY)
    assert "\\DeclareOption{referee}" in code
    m = re.search(r"\\DeclareOption\{referee\}\{(.{0,200})", code, re.DOTALL)
    assert m is not None
    arm = m.group(1)
    assert "\\aa@onecoltrue" in arm
    assert "\\PassOptionsToClass{onecolumn}{article}" in arm
    assert "\\AtBeginDocument{\\linespread{1.5}" in arm


def test_aa_processoptions_loadclass() -> None:
    """机面收尾 pin：\\ProcessOptions 在条件臂前，\\LoadClass{article}
    终载——\\LoadClassWithOptions 裸转发不得回潮。"""
    code = _code_lines(_AA_BODY)
    assert "\\ProcessOptions" in code
    assert code.index("\\ProcessOptions") < code.index("\\ifaa@onecol\\else")
    assert "\\LoadClass{article}" in code
    assert "\\LoadClassWithOptions" not in code


# ------------------------------------------------------- 真编译钉


@pytest.mark.integration
@_COMPILE
def test_aa_bare_defaults_compile(tmp_path: Path) -> None:
    """裸 \\documentclass{aa} → twocolumn+twoside+a4paper+overfullrule=0。"""
    shutil.copy(STUBS / "aa.cls", tmp_path / "aa.cls")
    log = _run(
        tmp_path,
        "\\documentclass{aa}\n" + _PROBE + "\n\\begin{document}\nx\n\\end{document}\n",
    )
    assert _n_err(log) == 0
    assert "twocol=T" in log
    assert "twoside=T" in log
    assert "pw=597.50787pt" in log  # a4 宽
    assert "ofr=0.0pt" in log


@pytest.mark.integration
@_COMPILE
def test_aa_referee_onecolumn_doublespace(tmp_path: Path) -> None:
    """[referee] → onecolumn + baselinestretch=1.5（真身 v7.0 值）。"""
    shutil.copy(STUBS / "aa.cls", tmp_path / "aa.cls")
    log = _run(
        tmp_path,
        "\\documentclass[referee]{aa}\n"
        + _PROBE
        + "\n\\begin{document}\nx\n\\end{document}\n",
    )
    assert _n_err(log) == 0
    assert "twocol=F" in log
    assert "bs=1.5" in log


@pytest.mark.integration
@_COMPILE
def test_aa_user_options_reach_article(tmp_path: Path) -> None:
    """用户选项经 catch-all 达 article：[onecolumn]/[letterpaper] 覆盖默认。"""
    for sub, opt, want in (
        ("oc", "onecolumn", "twocol=F"),
        ("os", "oneside", "twoside=F"),
        ("lp", "letterpaper", "pw=614.295"),
        ("lq", "leqno", "leqno.clo"),
    ):
        wdir = tmp_path / sub
        wdir.mkdir()
        shutil.copy(STUBS / "aa.cls", wdir / "aa.cls")
        log = _run(
            wdir,
            f"\\documentclass[{opt}]{{aa}}\n"
            + _PROBE
            + "\n\\begin{document}\nx\n\\end{document}\n",
        )
        assert _n_err(log) == 0, f"{opt} 编译出错"
        assert want in log, f"{opt} 未生效 (want {want!r})"


@pytest.mark.integration
@_COMPILE
def test_aa_unused_option_parity(tmp_path: Path) -> None:
    """警告面与真身一致：aa 专名吞位静默，未声明名仍 Unused-option 警告。"""
    for sub, opt, warns in (
        ("swallow", "letter", False),
        ("swallow2", "online", False),
        ("bogus", "bibyear", True),
        ("bogus2", "usenatbibs", True),
    ):
        wdir = tmp_path / sub
        wdir.mkdir()
        shutil.copy(STUBS / "aa.cls", wdir / "aa.cls")
        log = _run(
            wdir,
            f"\\documentclass[{opt}]{{aa}}\n"
            "\\begin{document}\nx\n\\end{document}\n",
        )
        assert _n_err(log) == 0, f"{opt} 编译出错"
        assert ("Unused global option" in log) is warns, f"{opt} 警告面与真身不一致"
