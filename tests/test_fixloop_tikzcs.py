r"""pgffix lane (task #249) —— ``\node``/``\draw`` 族 tikz 缺载修复钉。

1306.0281 (acm_proc_article-sp shim 稿): 作者注释 ``%\usepackage{tikz}``
后 ``\tikzset``/``\node``/``\draw`` 连锁 undefined_cs; undefined_env_polyfill
吐空 ``tikzpicture`` noop 壳后体内 pgf cs 裸奔。这些 cs 带
``[opts] (name) {content};`` 括号+坐标尾, cs_map/gobble 无一能吞 ——
装真包是唯一正解; ``arrows``/``positioning``/``shapes`` 三库兜
``>=latex'``/``above right=of``/``mynode`` 系常见库键。

秩序钉 (本表独有): polyfill 须自足 ``\usepackage{tikz}`` 前缀 ——
``_inject_after_docclass`` 注缝 LIFO 语义下, 同臂 ``usepackage`` 先注
``polyfill`` 后注, 裸 ``\usetikzlibrary`` 会落在 arm usepackage 行
**之前** → 新 undefined_cs + Missing-begindoc 级联 (tmp/lane-pgffix
实测 ``! Undefined control sequence l.3 \usetikzlibrary``); 自足块对
注释载/死臂载/稿后载/preamble 库键 ``\tikzset`` 全免疫, dup
``\usepackage{tikz}`` 行 (arm 注入 + polyfill 内联) 是 benign no-op。

env→pkg 臂 (undefined_env_polyfill ``pkg_map``): tikzpicture/axis/tikzcd
装真包替代 noop —— noop 吞图体且 axis/tikzcd 在 cs_table 无对应 cs 臂。
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx

_RULES = load_ruleset().rules
_TARGETED = TRANSFORM_FNS["cs_targeted_fix"]
_PARAMS = next(r for r in _RULES if r.id == "cs_targeted_fix").action["params"]
_CSTABLE = _PARAMS["cs_table"]
_ENVPOLY = TRANSFORM_FNS["undefined_env_polyfill"]
_ENVPARAMS = next(r for r in _RULES if r.id == "undefined_env_polyfill").action[
    "params"
]

_TIKZ_CS = (
    "node",
    "draw",
    "path",
    "coordinate",
    "fill",
    "filldraw",
    "matrix",
    "tikzset",
)
_TIKZ_SPEC = {
    "usepackage": "tikz",
    "polyfill": "\n\\usepackage{tikz}\n\\usetikzlibrary{arrows,positioning,shapes}",
}

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


def _envfix(tmp_path: Path, env: str) -> tuple[bool, str]:
    return _ENVPOLY(_ctx(tmp_path), _EngStub(), env, _ENVPARAMS)


_DOC = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"


def test_table_entries_present() -> None:
    """八名全挂 usepackage+自足 polyfill —— 真包臂, 非吞参 noop。"""
    for cs in _TIKZ_CS:
        assert _CSTABLE.get(cs) == _TIKZ_SPEC, cs


def test_no_gobble_or_cs_map() -> None:
    r"""判词钉死: ``\node``/``\draw`` 的 ``[..] (..) {..};`` 尾吞不掉 —
    cs_map/gobble 属错义修, 表内不得出现。"""
    for cs in _TIKZ_CS:
        spec = _CSTABLE[cs]
        assert "cs_map" not in spec, cs
        assert "guard" not in spec, cs


@pytest.mark.parametrize("cs", ["node", "draw", "tikzset"])
def test_usepackage_injected_after_docclass(tmp_path: Path, cs: str) -> None:
    r"""``\usepackage{tikz}`` 落 ``\documentclass`` 缝后。"""
    (tmp_path / "main.tex").write_text(_DOC, encoding="utf-8")
    ok, note = _fix(tmp_path, cs)
    assert ok, note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\usepackage{tikz}" in text
    assert text.index("\\usepackage{tikz}") > text.index("\\documentclass")


def test_polyfill_self_ordering(tmp_path: Path) -> None:
    r"""秩序钉: 首个 ``\usepackage{tikz}`` 必须先于 ``\usetikzlibrary`` —
    反序即 ``\usetikzlibrary`` undefined_cs 级联 (处方裸形实测)。"""
    (tmp_path / "main.tex").write_text(_DOC, encoding="utf-8")
    ok, _ = _fix(tmp_path, "node")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    i_use = text.index("\\usepackage{tikz}")
    i_lib = text.index("\\usetikzlibrary")
    assert i_use < i_lib, "usetikzlibrary landed before usepackage"
    # polyfill 在 preamble 域 (begindoc 前)
    assert i_lib < text.index("\\begin{document}")


def test_commented_usepackage_still_injects(tmp_path: Path) -> None:
    r"""``%\usepackage{tikz}`` 不算已装载 (mask 检) —— 1306.0281 本体形。"""
    doc = _DOC.replace(
        "\\begin{document}", "%\\usepackage{tikz}\n\\begin{document}"
    )
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    ok, note = _fix(tmp_path, "node")
    assert ok, note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    live = [
        ln
        for ln in text.splitlines()
        if "\\usepackage{tikz}" in ln and not ln.lstrip().startswith("%")
    ]
    assert live, "no live \\usepackage{tikz} injected"
    assert "\\usetikzlibrary{arrows,positioning,shapes}" in text


def test_already_loaded_no_double_arm_inject(tmp_path: Path) -> None:
    r"""稿已 ``\usepackage{tikz}`` → arm 不再注入 (masked 面判重);
    polyfill 块仍注 (内含自足 usepackage+usetikzlibrary)。"""
    doc = (
        "\\documentclass{article}\n"
        "\\usepackage{tikz}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    ok, _ = _fix(tmp_path, "node")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "% fixloop: cs-fix" not in text
    assert "\\usetikzlibrary{arrows,positioning,shapes}" in text


def test_refire_no_duplicate_polyfill(tmp_path: Path) -> None:
    r"""二轮重火: usepackage 判重 + polyfill snippet 判重 → 幂等, 返回仍
    True (arm probe 注记保 done 非空, 不落 guess)。"""
    (tmp_path / "main.tex").write_text(_DOC, encoding="utf-8")
    ok1, _ = _fix(tmp_path, "node")
    assert ok1
    ok2, _ = _fix(tmp_path, "draw")
    assert ok2
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert text.count("\\usetikzlibrary{arrows,positioning,shapes}") == 1


def test_decline_on_nonmatching_payload(tmp_path: Path) -> None:
    """表外 payload → decline (不落本臂; split_heads 不命中者直 False)。"""
    (tmp_path / "main.tex").write_text(_DOC, encoding="utf-8")
    ok, note = _fix(tmp_path, "qzwkmisc")
    assert not ok
    assert "not in cs-fix table" in note
    assert "\\usepackage{tikz}" not in (
        tmp_path / "main.tex"
    ).read_text(encoding="utf-8")


def test_env_pkg_map_serves_tikzpicture(tmp_path: Path) -> None:
    r"""env→pkg 臂: ``tikzpicture`` 装真包, 不落 ``\newenvironment`` noop。"""
    doc = _DOC.replace(
        "x", "\\begin{tikzpicture}\\node (a) {x};\\end{tikzpicture}"
    )
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    ok, note = _envfix(tmp_path, "tikzpicture")
    assert ok, note
    assert "→pkg" in note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\usepackage{tikz}" in text
    assert "\\usetikzlibrary{arrows,positioning,shapes}" in text
    assert "\\newenvironment{tikzpicture}" not in text
    assert text.index("\\usepackage{tikz}") < text.index("\\usetikzlibrary")


@pytest.mark.parametrize(
    ("env", "pkg"), [("axis", "pgfplots"), ("tikzcd", "tikz-cd")]
)
def test_env_pkg_map_serves_siblings(tmp_path: Path, env: str, pkg: str) -> None:
    r"""axis→pgfplots / tikzcd→tikz-cd: cs_table 无 cs 臂, 真包是唯一活路。"""
    doc = _DOC.replace("x", f"\\begin{{{env}}}y\\end{{{env}}}")
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    ok, note = _envfix(tmp_path, env)
    assert ok, note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert f"\\usepackage{{{pkg}}}" in text
    assert f"\\newenvironment{{{env}}}" not in text


def test_env_nonmap_still_noop(tmp_path: Path) -> None:
    r"""表外 env (``thmx``) 仍走 ``\ifcsname`` 守卫 noop 旧路径。"""
    doc = _DOC.replace("x", "\\begin{thmx}y\\end{thmx}")
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    ok, note = _envfix(tmp_path, "thmx")
    assert ok, note
    assert "→pkg" not in note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifcsname thmx\\endcsname" in text
    assert "\\usepackage" not in text


def test_env_refire_idempotent(tmp_path: Path) -> None:
    r"""env 臂重火: arm probe 注记保 True, 不重复注入。"""
    doc = _DOC.replace(
        "x", "\\begin{tikzpicture}\\node (a) {x};\\end{tikzpicture}"
    )
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    ok1, _ = _envfix(tmp_path, "tikzpicture")
    assert ok1
    ok2, _ = _envfix(tmp_path, "tikzpicture")
    assert ok2
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert text.count("\\usetikzlibrary{arrows,positioning,shapes}") == 1


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
def test_fixed_doc_compiles(tmp_path: Path) -> None:
    r"""1306.0281 全形: 注释载 + body ``\tikzset`` + ``above right=of``
    (positioning 库) + ``>=latex'`` (arrows 库) —— 修复后零 ``!`` 错。"""
    tex = (
        "\\documentclass{article}\n"
        "%\\usepackage{tikz}\n"
        "\\begin{document}\n"
        "\\begin{tikzpicture}[node distance=1cm]\n"
        "\\tikzset{mynode/.style={rectangle,draw=black,thick},"
        "myarrow/.style={->,>=latex',thick}}\n"
        "\\node[mynode] (a) {x};\n"
        "\\node[mynode,above right=1cm of a] (b) {y};\n"
        "\\draw[myarrow] (a) -- (b);\n"
        "\\end{tikzpicture}\n"
        "\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(tex, encoding="utf-8")
    ok, note = _fix(tmp_path, "node")
    assert ok, note
    log = _compile(tmp_path, (tmp_path / "main.tex").read_text(encoding="utf-8"))
    errs = re.findall(r"^! ", log, re.MULTILINE)
    assert not errs, (
        f"compile errors remain: {log[log.find('!'):log.find('!') + 300]}"
    )
    assert (tmp_path / "main.pdf").is_file()


@pytest.mark.integration
@_COMPILE
def test_without_fix_is_undefined(tmp_path: Path) -> None:
    r"""阴性对照: 无注入时同稿 ``\node`` 即 undefined_cs。"""
    tex = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\begin{tikzpicture}\n\\node (a) {x};\n\\end{tikzpicture}\n"
        "\\end{document}\n"
    )
    log = _compile(tmp_path, tex)
    assert "Undefined control sequence" in log
