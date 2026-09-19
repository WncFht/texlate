r"""para_longize (#155): "Paragraph ended before \X" 族修复钉。

para-census (#145) 定形的双臂: fileset ``\def\X`` 非 ``\long`` 定义点
前插 ``\long`` / starred ``\newcommand*`` 去星; 内核/包内宏不在
fileset → ``\par``-strip wrap 注入 ``\begin{document}`` 前 (aux 读死线
+ 包装载期 \let 再绑双约束): ``\let`` 快照 + ``\long`` wrapper 逐参
剥顶层 ``\par`` 再按原签名转发 —— 裸 ``\let``-wrap 的 ``{#n}`` 含
``\par`` 会在原宏非 ``\long`` 重扫上原样复炸 (实测钉过)。dedup 键
``{rule}:None`` 全族共位 → 单次应用收日志全肇事宏。拒收暂存/级联名
(\bbl@tempe/\@tempa/\next) —— 上游臂 (babel_opt/scratch 宿主错) 才
是根修。
"""

import subprocess
from pathlib import Path

import pytest

from texlate.compile.fixloop._builtins_paralong import (
    _WRAP_TABLE,
    _longize_defs,
    para_longize,
)
from texlate.compile.fixloop.engine import LoopCtx


class _Eng:
    name = "xelatex"


def _ctx(tmp_path: Path, err_head: str) -> LoopCtx:
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ctx.err_head = err_head
    return ctx


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


_XELATEX = "/usr/bin/xelatex"
_HAS_XELATEX = Path(_XELATEX).exists()


def _xelatex(wdir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — 固定 argv, 测试面实弹编译
        [_XELATEX, "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
        cwd=wdir,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_def_site_longize(tmp_path: Path) -> None:
    """``\\def\\rf`` 非 \\long → 前插 \\long; \\par 参数不再炸。"""
    main = _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\def\\rf[#1]#2{see #1 #2}\n"
        "\\begin{document}\n\\rf[a]{x}\n\\end{document}\n",
    )
    ctx = _ctx(tmp_path, "main.tex:5: Paragraph ended before \\rf was complete.")
    ok, note = para_longize(ctx, _Eng(), None, {})
    assert ok, note
    assert "\\long \\def\\rf" in main.read_text()


def test_starred_newcommand_unstar(tmp_path: Path) -> None:
    """``\\newcommand*{\\foo}`` → 去星 (unstarred 本即 \\long)。"""
    main = _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\newcommand*{\\foo}[1]{#1}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = _ctx(tmp_path, "main.tex:4: Paragraph ended before \\foo was complete.")
    ok, note = para_longize(ctx, _Eng(), None, {})
    assert ok, note
    assert "\\newcommand{\\foo}" in main.read_text()


def test_shipped_cls_def_site(tmp_path: Path) -> None:
    """shipped cls 内部宏 (\\@argswap 族) —— cls 件在 fileset 即改。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{revtex4HOOMS}\n\\begin{document}\nx\n\\end{document}\n",
    )
    cls = _write(
        tmp_path,
        "revtex4HOOMS.cls",
        "\\ProvidesClass{revtex4HOOMS}\n\\def\\add@AUCO@grp#1{#1}\n\\endinput\n",
    )
    ctx = _ctx(tmp_path, "revtex4HOOMS.cls:2: Paragraph ended before \\add@AUCO@grp")
    ok, note = para_longize(ctx, _Eng(), None, {})
    assert ok, note
    assert "\\long \\def\\add@AUCO@grp" in cls.read_text()


def test_kernel_wrap_injected(tmp_path: Path) -> None:
    """内核宏无 fileset 定义点 → \\par-strip wrap 注入 \\begin{document} 前。"""
    main = _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\usepackage{nameref}\n"
        "\\begin{document}\n\\section{t}\nx\n\\end{document}\n",
    )
    ctx = _ctx(
        tmp_path, "main.tex:4: Paragraph ended before \\NR@gettitle was complete."
    )
    ok, note = para_longize(ctx, _Eng(), None, {})
    assert ok, note
    t = main.read_text()
    assert "\\let\\TL@pl@NR@gettitle\\NR@gettitle" in t
    assert "\\TL@pl@strip" in t  # 共享剥参原语
    assert "\\long\\def\\NR@gettitle#1{\\TL@pl@strip{#1}" in t
    assert "\\long\\def\\TL@pl@NR@gettitle@si#1{\\TL@pl@NR@gettitle{#1}}" in t
    # wrap 块落在 \begin{document} 前 (aux 读死线)
    assert t.index("\\catcode 64=11") < t.index("\\begin{document}")
    assert "\\ifdefined\\NR@gettitle" in t


def test_wrap_idempotent(tmp_path: Path) -> None:
    """复火不重注 —— 别名指纹已在件即跳。"""
    main = _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = _ctx(tmp_path, "m.tex:1: Paragraph ended before \\author was complete.")
    ok1, _ = para_longize(ctx, _Eng(), None, {})
    t1 = main.read_text()
    ok2, note2 = para_longize(ctx, _Eng(), None, {})
    assert ok1
    assert "TL@pl@author" in t1
    assert main.read_text() == t1  # 复火零增 (别名指纹短路)
    assert not ok2, note2  # 第二趟无新动作


def test_deny_scratch_cascade(tmp_path: Path) -> None:
    """\\bbl@tempe (babel 级联)/\\@tempa (amstex 暂存) 拒收 —— 修上游。"""
    main = _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = _ctx(tmp_path, "main.tex:3: Paragraph ended before \\bbl@tempe was complete.")
    ok, note = para_longize(ctx, _Eng(), None, {})
    assert not ok
    assert "denied" in note
    assert "TL@pl@" not in main.read_text()


def test_unknown_macro_declines(tmp_path: Path) -> None:
    """无定义点且不在 wrap 表 → decline (LLM 手留)。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = _ctx(
        tmp_path, "main.tex:3: Paragraph ended before \\weirdmacro was complete."
    )
    ok, note = para_longize(ctx, _Eng(), None, {})
    assert not ok
    assert "not in wrap table" in note


def test_multi_macro_single_apply(tmp_path: Path) -> None:
    """dedup ``{rule}:None`` 共位 —— 单趟收 err_head + 日志全肇事宏。"""
    main = _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\def\\one#1{#1}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = _ctx(tmp_path, "main.tex:4: Paragraph ended before \\one was complete.")
    # 全日志补第二肇事宏 (err_head 只载主错)
    _write(
        tmp_path,
        "main.log",
        "main.tex:4: Paragraph ended before \\one was complete.\n"
        "main.tex:9: Paragraph ended before \\addcontentsline was complete.\n",
    )
    ok, note = para_longize(ctx, _Eng(), None, {})
    assert ok, note
    t = main.read_text()
    assert "\\long \\def\\one" in t  # def-site
    assert "TL@pl@addcontentsline" in t  # wrap 表宏同趟收


def test_no_sig_declines(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = _ctx(tmp_path, "main.tex:3: Undefined control sequence.")
    ok, _ = para_longize(ctx, _Eng(), None, {})
    assert not ok


def test_wrap_table_fwd_braces() -> None:
    """表钉: 无界参转发必须补花括号 —— 裸 ``#n`` 会把实参重切成单 token。"""
    for name in (
        "NR@gettitle",
        "addcontentsline",
        "@citex",
        "@providesfile",
        "setlength",
    ):
        assert name in _WRAP_TABLE
    for name, (sig, fwd) in _WRAP_TABLE.items():
        assert "#" in fwd, name
        if sig == "#1":  # 纯无界单参 → fwd 必为 {#1}
            assert fwd == "{#1}", name


def test_commented_def_not_touched() -> None:
    """遮盖面钉: 注释内 ``%\\def\\dead`` 不改写 (死代码)。"""
    t = "%\\def\\dead#1{x}\n\\def\\dead#1{y}\n"
    nt, n = _longize_defs(t, "dead")
    assert n == 1
    assert nt.startswith("%\\def\\dead")


def test_wrap_table_param_extend(tmp_path: Path) -> None:
    """params.wrap_table 同形扩表 —— 未收内核名可 yaml 侧补。"""
    main = _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = _ctx(tmp_path, "main.tex:3: Paragraph ended before \\mycustom was complete.")
    ok, note = para_longize(
        ctx, _Eng(), None, {"wrap_table": {"mycustom": ("#1", "{#1}")}}
    )
    assert ok, note
    assert "TL@pl@mycustom" in main.read_text()


@pytest.mark.skipif(not _HAS_XELATEX, reason="xelatex not installed")
def test_xelatex_defsite_e2e(tmp_path: Path) -> None:
    """真 xelatex: 非 \\long ``\\def\\rf`` + 参内空行 → para_ended;
    补 \\long 后同档干净过。"""
    src = (
        "\\documentclass{article}\n\\def\\rf#1{[#1]}\n"
        "\\begin{document}\n\\rf{line one\n\nline two}\n\\end{document}\n"
    )
    _write(tmp_path, "main.tex", src)
    _xelatex(tmp_path)
    log = (tmp_path / "main.log").read_text(errors="replace")
    assert "Paragraph ended before \\rf" in log
    ctx = _ctx(tmp_path, "main.tex:4: Paragraph ended before \\rf was complete.")
    ok, note = para_longize(ctx, _Eng(), None, {})
    assert ok, note
    r2 = _xelatex(tmp_path)
    assert r2.returncode == 0
    assert "Paragraph ended" not in (tmp_path / "main.log").read_text(errors="replace")


@pytest.mark.skipif(not _HAS_XELATEX, reason="xelatex not installed")
def test_xelatex_wrap_e2e(tmp_path: Path) -> None:
    """真 xelatex wrap 径: 内核非 \\long ``\\setlength`` (latex.ltx ``\\def
    \\setlength#1#2{#1 #2\\relax}``, fileset 外 → def-site 臂收不到) +
    参内空行 → wrap 注入后 wrapper 吃掉 \\par。"""
    src = (
        "\\documentclass{article}\n"
        "\\begin{document}\n\\setlength{\\parindent}{10pt\n\n}\nx\n\\end{document}\n"
    )
    _write(tmp_path, "main.tex", src)
    _xelatex(tmp_path)
    assert "Paragraph ended before \\setlength" in (tmp_path / "main.log").read_text(
        errors="replace"
    )
    ctx = _ctx(tmp_path, "main.tex:3: Paragraph ended before \\setlength was complete.")
    ok, note = para_longize(ctx, _Eng(), None, {})
    assert ok, note
    assert "wrap" in note  # 唯一修复径 —— def-site 臂零命中
    r2 = _xelatex(tmp_path)
    assert r2.returncode == 0


@pytest.mark.skipif(not _HAS_XELATEX, reason="xelatex not installed")
def test_xelatex_undelimited_cont_e2e(tmp_path: Path) -> None:
    r"""钉 \else-吞吃回归: CONT 链含吃**无界**实参的宏 (natbib
    ``\@citex[#1][#2]#3`` 的 #3) 时, strip 的 ``\ifx`` 真分支若直接执行
    CONT, 挂起的 ``\else`` 会被当 #3 吞掉 → 残留 else 支二次执行连锁炸
    (实测 ``\@fortmp`` runaway)。``\expandafter\TL@pl@first/\fi`` 出闸
    钉住: ``\NAT@@citetp`` wrap 后 ``\@citex`` 的 #3 须吃到真参。"""
    src = (
        "\\documentclass{article}\n\\makeatletter\n"
        "\\def\\@citex[#1][#2]#3{\\typeout{CITEOUT:#1|#2|#3}}\n"
        "\\def\\NAT@@citetp[#1]{\\@ifnextchar[{\\@citex[#1]}{\\@citex[][#1]}}\n"
        "\\def\\citep{\\NAT@@citetp}\n"  # @-宏不能裸叫 (正文 @ catcode-12)
        "\\makeatother\n\\begin{document}\n\\citep[see\n\nalso]{key1}\n"
        "\\end{document}\n"
    )
    _write(tmp_path, "main.tex", src)
    _xelatex(tmp_path)
    log = (tmp_path / "main.log").read_text(errors="replace")
    assert "Paragraph ended before \\NAT@@citetp" in log
    ctx = _ctx(
        tmp_path, "main.tex:7: Paragraph ended before \\NAT@@citetp was complete."
    )
    ok, note = para_longize(ctx, _Eng(), None, {})
    assert ok, note
    r2 = _xelatex(tmp_path)
    log2 = (tmp_path / "main.log").read_text(errors="replace")
    assert r2.returncode == 0
    assert "Paragraph ended" not in log2
    assert "CITEOUT:|see also|key1" in log2  # #3 = key1, 不是 \else
