"""axodraw 替身 stub + ``_PKG_OPTS`` 提升链单测 (axodraw 车道，2026-09-19)。

实证背景 (corpus hep-ph/0111339, stagerun-loop2/loop3/loop4 车道
fixloop.jsonl 三源): ``\\documentstyle[preprint,aps,epsfig,axodraw]{revtex}``
——``axodraw`` 不在 ``_PKG_OPTS`` → ``_route_opts`` 落类选项位 → revtex4-2
不认识、静默不加载 → 正文 ``\\Line``×5/``\\LongArrow``×1 undefined_cs 残面。
修复：``_PKG_OPTS`` 收 ``axodraw`` → ``\\usepackage{axodraw}`` → missing_file
→ vendored_fetch 平铺 vendor/stubs/axodraw.sty。

stub 保真面 (真件 v1898, corpus hep-ph/0307200 extracted 签名源):

- 弧族 ``\\ArrowArc/\\CArc`` 真件仅两括号组——旧 stub 多吞 ``#3#4`` 会吃掉
  调用点后两 token (gobble 危害)。
- Dash 族真件带尾随 ``{dash}`` 参——漏吞则 ``{2}`` 泄正文。
- ``\\SetOffset/\\SetScaledOffset`` 真件是 ``(x,y)`` 括号形非 ``{x,y}``。
- ``\\Text(x,y)[pos]{label}`` 保 label 丢位置参；``[pos]`` 可缺省
  (``\\@ifnextchar`` 容错臂)。
- 色面 (o2-axodraw-color 车道): ``\\SetColor/\\Color/\\IfColor`` + dvips
  68 色名单参保文字臂——本文件不回测色面，只钉 axodraw 车道新增面。
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from _fixloopkit import STUBS, n_err, requires_xelatex, run_xelatex

from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.latex209 import main as latex209_main
from texlate.compile.latex209 import upgrade_209

_STUB = STUBS / "axodraw.sty"

_PDFTOTEXT = shutil.which("pdftotext")

#: hep-ph/0111339 main.tex:1 逐字节实证行。
_DOCSTYLE_0111339 = "\\documentstyle[preprint,aps,epsfig,axodraw]{revtex}\nx\n"


@pytest.fixture(autouse=True)
def _target_always_resolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    """revtex→revtex4-2 改名目标默认放行——升级结果不依赖测试机 texmf。"""
    monkeypatch.setattr(latex209_main, "_target_resolvable", lambda *_a: True)


def _code_lines(body: str) -> str:
    """滤 % 注释行后拼接——pin 断言不得被注释文本夹带。"""
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("%"))


# ------------------------------------------------- 209 option → pkg 提升链


def test_upgrade_209_axodraw_promoted_to_usepackage() -> None:
    """0111339 实证行：axodraw 进 pkg_opts 不落幕后的类选项位。"""
    out, info = upgrade_209(_DOCSTYLE_0111339)
    assert info["status"] == "converted"
    assert "axodraw" in info["pkg_opts"]
    assert "axodraw" not in info["class_opts"]
    assert "\\usepackage{epsfig,axodraw}" in out


def test_upgrade_209_axodraw_preserves_cls_opts() -> None:
    """同行内 preprint/aps 仍走类选项——提升不扰邻座。"""
    _, info = upgrade_209(_DOCSTYLE_0111339)
    assert info["class_opts"] == ["preprint", "aps"]
    assert info["pkg_opts"] == ["epsfig", "axodraw"]


def test_vendored_fetch_serves_axodraw_stub(tmp_path: Path) -> None:
    """missing_file|axodraw.sty → vendored_fetch 默认包内 vendor 直供 stub。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, note = TRANSFORM_FNS["vendored_fetch"](ctx, None, "axodraw.sty", {})
    assert ok, note
    assert "stubs" in note
    landed = (tmp_path / "axodraw.sty").read_text(encoding="utf-8")
    assert "\\LongArrow" in landed


# ------------------------------------------------- stub 签名 pin (免编译)


def test_stub_line_family_two_paren_groups() -> None:
    """残面正主：\\Line/\\LongArrow 真件 \\X(x1,y1)(x2,y2) 两括号组。"""
    code = _code_lines(_STUB.read_text(encoding="utf-8"))
    assert "\\def\\Line(#1)(#2){}" in code
    assert "\\def\\LongArrow(#1)(#2){}" in code


def test_stub_arc_family_no_over_gobble() -> None:
    """弧族两括号组封顶——多吞 #3#4 会吃调用点后 token (旧 stub 实证危害)。"""
    code = _code_lines(_STUB.read_text(encoding="utf-8"))
    for cs in ("ArrowArc", "ArrowArcn", "CArc", "LongArrowArc"):
        assert f"\\def\\{cs}(#1)(#2){{}}" in code, f"{cs} 签名漂移"
    assert "\\def\\ArrowArc(#1)(#2)#3" not in code
    assert "\\def\\CArc(#1)(#2)#3" not in code


def test_stub_dash_family_consumes_dash_arg() -> None:
    """Dash 族尾随 {dash} 必吞——漏吞则 {2} 以字面量泄正文。"""
    code = _code_lines(_STUB.read_text(encoding="utf-8"))
    for cs in ("DashLine", "DashArrowLine", "DashLongArrow", "DashCArc"):
        assert f"\\def\\{cs}(#1)(#2)#3{{}}" in code, f"{cs} 漏吞 dash 参"


def test_stub_setoffset_paren_form() -> None:
    """\\SetOffset 真件 (x,y) 括号形——花括号签名会把 (10,10) 泄成字面量。"""
    code = _code_lines(_STUB.read_text(encoding="utf-8"))
    assert "\\def\\SetOffset(#1){}" in code
    assert "\\def\\SetScaledOffset(#1){}" in code
    assert "\\SetOffset}[" not in code  # providecommand 花括号形不得回潮


def test_stub_text_preserves_label_via_optional_bracket() -> None:
    """\\Text(x,y)[pos]{label} 出 label 吞 pos；[pos] 缺省走容错臂。"""
    code = _code_lines(_STUB.read_text(encoding="utf-8"))
    assert "\\def\\Text(#1){\\@ifnextchar[" in code
    assert "\\def\\axo@Text[#1]#2{#2}" in code  # label = #2 照排


def test_stub_curve_and_vertex_family_present() -> None:
    """\\Curve{点列} 单参 + 顶点/胶子弧族补全——真件全族面不回缺。"""
    code = _code_lines(_STUB.read_text(encoding="utf-8"))
    for frag in (
        "\\def\\Curve#1{}",
        "\\def\\DashCurve#1#2{}",
        "\\def\\GlueArc(#1)(#2)#3#4{}",
        "\\def\\PhotonArc(#1)(#2)#3#4{}",
        "\\def\\Vertex(#1)#2{}",
        "\\def\\GCirc(#1)#2#3{}",
        "\\def\\GTri(#1)(#2)(#3)#4{}",
        "\\def\\GBox(#1)(#2)#3{}",
        "\\def\\LinAxis(#1)(#2)(#3){}",
        "\\def\\B2Text(#1)#2#3{#2 #3}",
    ):
        assert frag in code, f"{frag} 缺席"


# ------------------------------------------------- 编译级验证


@requires_xelatex
@pytest.mark.integration
def test_stub_loads_and_call_shapes_clean(tmp_path: Path) -> None:
    """0111339 调用形 + 全族代表面：装 stub 后 xelatex 零 '!' 错。"""
    log = run_xelatex(
        tmp_path,
        r"""\documentclass{article}
\usepackage{axodraw}
\begin{document}
\begin{picture}(200,100)
\Line(0,0)(100,0)
\LongArrow(0,10)(100,10)
\ArrowLine(0,20)(100,20)
\DashLine(0,30)(100,30){2}
\DashLongArrow(0,40)(100,40){3}
\Photon(0,50)(100,50){2}{5}
\Gluon(0,60)(100,60){2}{5}
\ArrowArc(50,50)(20,0,90)
\CArc(50,50)(25,0,180)
\DashArrowArc(50,50)(15,0,90){2}
\GlueArc(50,50)(30,0,90){2}{5}
\Curve{(0,0)(50,50)(100,0)}
\DashCurve{(0,0)(50,80)(100,0)}{3}
\Vertex(50,50){2}
\GCirc(50,50){10}{0.5}
\GBox(0,0)(20,20){0.5}
\LinAxis(0,0)(100,0)(5,2,1,0)
\Text(50,50)[l]{label-with-pos}
\Text(50,50){label-no-pos}
\B2Text(50,50){line one}{line two}
\SetOffset(10,10)
\SetScaledOffset(5,5)
\SetScale{1.5}
\SetWidth{0.5}
\SetColor{Red}
\Color{Blue}{colored text}
\IfColor{yes-arm}{no-arm}
\end{picture}
\end{document}
""",
        extra={"axodraw.sty": _STUB.read_text(encoding="utf-8")},
    )
    assert n_err(log) == 0, f"仍 {n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()


@requires_xelatex
@pytest.mark.integration
@pytest.mark.skipif(_PDFTOTEXT is None, reason="pdftotext not installed")
def test_stub_arc_does_not_gobble_following_text(tmp_path: Path) -> None:
    """\\ArrowArc 正确 arity 下后继文字全留存；多吞臂会吃掉前两字母。"""
    run_xelatex(
        tmp_path,
        r"""\documentclass{article}
\usepackage{axodraw}
\begin{document}
\begin{picture}(200,100)
\ArrowArc(50,50)(20,0,90)ZZMARKER
\Text(50,50)[l]{ZZLABEL}
\end{picture}
\end{document}
""",
        extra={"axodraw.sty": _STUB.read_text(encoding="utf-8")},
    )
    out = subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which
        [_PDFTOTEXT, "main.pdf", "-"],
        cwd=tmp_path,
        capture_output=True,
        timeout=60,
        check=True,
        text=True,
    ).stdout
    assert "ZZMARKER" in out, "ArrowArc 多吞后继 token"
    assert "ZZLABEL" in out, "Text label 丢失"
