r"""letltxmacro lane (task #243) —— ``\LetLtxMacro`` undefined_cs 修复钉。

2403.15085 (atlasdoc 系): preamble 裸调 ``\LetLtxMacro{\oldcite}{\cite}``
后 ``\renewcommand{\cite}[1]{\mbox{\oldcite{#1}}}`` —— atlasdoc/
atlasphysics 包链不传递载 letltxmacro (osajnl/socg-lipics 等 cls 均自
``\RequirePackage{letltxmacro}``, 故 cls 内调用面从未炸)。

机制判词: biblatex 的 ``\cite`` 是 robust cs (``\protected`` 壳 +
``\@protected@testopt`` 可选参机件)。朴素 ``\let`` 只拷顶层 meaning —
— ``\protected``/``\long``/可选参签名全丢, cs_map/gobble 属错义修,
本表拒收; ``usepackage: letltxmacro`` 装真包 (Heiko letltxmacro v1.6,
texmf 全集在位, tectonic 走 bundle/ctan_fetch) 是唯一正解。
``\GlobalLetLtxMacro`` 同包同件收同键; ``\LetLtxMacroOpt`` 在包内
不存在, 不收 (收了注入后仍 undefined → applied 假火)。
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx

_TARGETED = TRANSFORM_FNS["cs_targeted_fix"]
_PARAMS = next(r for r in load_ruleset().rules if r.id == "cs_targeted_fix").action[
    "params"
]
_CSTABLE = _PARAMS["cs_table"]

_XELATEX = shutil.which("xelatex")
_COMPILE = pytest.mark.skipif(
    _XELATEX is None or shutil.which("kpsewhich") is None,
    reason="xelatex/kpsewhich not installed",
)


class _EngStub:
    """probe 恒命中 / install 恒成 —— usepackage 臂走通支路。"""

    def probe_file(self, fname: str, cwd: Path | None = None) -> str:
        del cwd
        return f"/texmf/{fname}"

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return True


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def _fix(tmp_path: Path, cs: str) -> tuple[bool, str]:
    return _TARGETED(_ctx(tmp_path), _EngStub(), cs, _PARAMS)


_DOC = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"


def test_table_entries_present() -> None:
    """双公共名均挂 ``usepackage: letltxmacro`` —— 真包臂, 非 gobble。"""
    for cs in ("LetLtxMacro", "GlobalLetLtxMacro"):
        assert _CSTABLE.get(cs) == {"usepackage": "letltxmacro"}, cs


def test_no_gobble_or_plain_let() -> None:
    """判词钉死: 表内不得有 LetLtxMacro 的 polyfill/cs_map 错义修。"""
    spec = _CSTABLE["LetLtxMacro"]
    assert "polyfill" not in spec
    assert "cs_map" not in spec
    assert "LetLtxMacroOpt" not in _CSTABLE


@pytest.mark.parametrize("cs", ["LetLtxMacro", "GlobalLetLtxMacro"])
def test_usepackage_injected_after_docclass(tmp_path: Path, cs: str) -> None:
    """``\\RequirePackage{letltxmacro}`` 落 ``\\documentclass`` 缝后。"""
    (tmp_path / "main.tex").write_text(_DOC, encoding="utf-8")
    ok, note = _fix(tmp_path, cs)
    assert ok, note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\RequirePackage{letltxmacro}" in text
    assert text.index("\\RequirePackage{letltxmacro}") > text.index("\\documentclass")


def test_already_loaded_no_double_inject(tmp_path: Path) -> None:
    """稿已 ``\\usepackage{letltxmacro}`` → 不重复注入 (masked 面判重)。"""
    doc = (
        "\\documentclass{article}\n"
        "\\usepackage{letltxmacro}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    ok, _ = _fix(tmp_path, "LetLtxMacro")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert text.count("\\usepackage{letltxmacro}") == 1


def test_refire_no_duplicate_line(tmp_path: Path) -> None:
    """二轮重火: 已装载判定使注入幂等 —— 文件内仍只有一行装载行。"""
    (tmp_path / "main.tex").write_text(_DOC, encoding="utf-8")
    ok1, _ = _fix(tmp_path, "LetLtxMacro")
    assert ok1
    _fix(tmp_path, "LetLtxMacro")
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert text.count("\\RequirePackage{letltxmacro}") == 1


def _compile(wdir: Path, tex: str) -> str:
    (wdir / "main.tex").write_text(tex, encoding="utf-8")
    subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [_XELATEX, "-interaction=nonstopmode", "main.tex"],
        cwd=wdir,
        capture_output=True,
        timeout=120,
        check=False,
    )
    return (wdir / "main.log").read_text(encoding="utf-8", errors="replace")


@pytest.mark.integration
@_COMPILE
def test_robust_cs_copy_compiles(tmp_path: Path) -> None:
    r"""2403.15085 全形: ``\DeclareRobustCommand`` 目标 ``\LetLtxMacro`` 拷贝
    → renew 原 cs → ``\mbox{\oldcite{..}}`` 调用面 —— 真包下零 ``!`` 错。"""
    if (
        subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
            [shutil.which("kpsewhich") or "kpsewhich", "letltxmacro.sty"],
            capture_output=True,
            check=False,
        ).returncode
        != 0
    ):
        pytest.skip("letltxmacro.sty not in texmf")
    tex = (
        "\\documentclass{article}\n"
        "\\DeclareRobustCommand{\\citeX}[1]{CITED(#1)}\n"
        "\\LetLtxMacro{\\oldcite}{\\citeX}\n"
        "\\renewcommand{\\citeX}[1]{\\mbox{\\oldcite{#1}}}\n"
        "\\begin{document}\n"
        "see \\citeX{ref1} done\n"
        "\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(tex, encoding="utf-8")
    ok, note = _fix(tmp_path, "LetLtxMacro")
    assert ok, note
    log = _compile(tmp_path, (tmp_path / "main.tex").read_text(encoding="utf-8"))
    errs = re.findall(r"^! ", log, re.MULTILINE)
    assert not errs, (
        f"compile errors remain: {log[log.find('!') : log.find('!') + 300]}"
    )
    assert (tmp_path / "main.pdf").is_file()
    # robust 拷贝真到位: 若 \oldcite 是空壳/丢壳, xelatex 会报
    # "Undefined control sequence" 或 \protected 相关错 —— 零 ! 即判词


@pytest.mark.integration
@_COMPILE
def test_without_fix_is_undefined(tmp_path: Path) -> None:
    r"""阴性对照: 无注入时同稿 ``\LetLtxMacro`` 即 undefined_cs。"""
    tex = (
        "\\documentclass{article}\n"
        "\\DeclareRobustCommand{\\citeX}[1]{CITED(#1)}\n"
        "\\LetLtxMacro{\\oldcite}{\\citeX}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    log = _compile(tmp_path, tex)
    assert "Undefined control sequence" in log
    assert "\\LetLtxMacro" in log
