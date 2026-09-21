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

from pathlib import Path

from _fixloopkit import (
    EngStub,
    mk_ctx,
    requires_xelatex,
    run_xelatex_proc,
    write_file,
)

from texlate.compile.fixloop._builtins_paralong import (
    _WRAP_TABLE,
    _longize_defs,
    para_longize,
)


def test_def_site_longize(tmp_path: Path) -> None:
    """``\\def\\rf`` 非 \\long → 前插 \\long; \\par 参数不再炸。"""
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\def\\rf[#1]#2{see #1 #2}\n"
        "\\begin{document}\n\\rf[a]{x}\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:5: Paragraph ended before \\rf was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    assert "\\long \\def\\rf" in main.read_text()


def test_starred_newcommand_unstar(tmp_path: Path) -> None:
    """``\\newcommand*{\\foo}`` → 去星 (unstarred 本即 \\long)。"""
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\newcommand*{\\foo}[1]{#1}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:4: Paragraph ended before \\foo was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    assert "\\newcommand{\\foo}" in main.read_text()


def test_shipped_cls_def_site(tmp_path: Path) -> None:
    """shipped cls 内部宏 (\\@argswap 族) —— cls 件在 fileset 即改。"""
    write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{revtex4HOOMS}\n\\begin{document}\nx\n\\end{document}\n",
    )
    cls = write_file(
        tmp_path,
        "revtex4HOOMS.cls",
        "\\ProvidesClass{revtex4HOOMS}\n\\def\\add@AUCO@grp#1{#1}\n\\endinput\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="revtex4HOOMS.cls:2: Paragraph ended before \\add@AUCO@grp"
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    assert "\\long \\def\\add@AUCO@grp" in cls.read_text()


def test_kernel_wrap_injected(tmp_path: Path) -> None:
    """内核宏无 fileset 定义点 → \\par-strip wrap 注入 \\begin{document} 前。"""
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\usepackage{nameref}\n"
        "\\begin{document}\n\\section{t}\nx\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:4: Paragraph ended before \\NR@gettitle was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    t = main.read_text()
    assert "\\let\\TL@pl@NR@gettitle\\NR@gettitle" in t
    assert "\\TL@pl@strip" in t  # 共享剥参原语
    assert "\\long\\def\\NR@gettitle#1{\\TL@pl@strip{#1}" in t
    assert "\\long\\def\\TL@pl@NR@gettitle@si#1{\\TL@pl@NR@gettitle{#1}}" in t
    # wrap 块落在 \begin{document} 前 (aux 读死线)
    assert t.index("\\catcode 64=11") < t.index("\\begin{document}")
    assert "\\ifdefined\\NR@gettitle" in t


def test_caption_prepareanchor_wrap(tmp_path: Path) -> None:
    r"""``\caption@prepareanchor`` (caption*.sty ``\newcommand*[2]``) 双参形 —
    zh splice 空行漏进参槽触 para_ended (2201.11528/2211.01288 watch 格);
    ``#1#2``/``{#1}{#2}`` wrap 注入, 续级 ``@si`` stage 剥第二参。"""
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\usepackage{caption}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:4: Paragraph ended before \\caption@prepareanchor was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    t = main.read_text()
    assert "\\let\\TL@pl@caption@prepareanchor\\caption@prepareanchor" in t
    assert (
        "\\long\\def\\caption@prepareanchor#1#2{\\TL@pl@strip{#1}"
        "{\\TL@pl@caption@prepareanchor@si{#2}}}" in t
    )
    assert (
        "\\long\\def\\TL@pl@caption@prepareanchor@sii#1#2"
        "{\\TL@pl@caption@prepareanchor{#1}{#2}}" in t
    )
    assert t.index("\\catcode 64=11") < t.index("\\begin{document}")


def test_wrap_idempotent(tmp_path: Path) -> None:
    """复火不重注 —— 别名指纹已在件即跳。"""
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="m.tex:1: Paragraph ended before \\author was complete."
    )
    ok1, _ = para_longize(ctx, EngStub(), None, {})
    t1 = main.read_text()
    ok2, note2 = para_longize(ctx, EngStub(), None, {})
    assert ok1
    assert "TL@pl@author" in t1
    assert main.read_text() == t1  # 复火零增 (别名指纹短路)
    assert not ok2, note2  # 第二趟无新动作


def test_deny_scratch_cascade(tmp_path: Path) -> None:
    """\\bbl@tempe (babel 级联)/\\@tempa (amstex 暂存) 拒收 —— 修上游。"""
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:3: Paragraph ended before \\bbl@tempe was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert not ok
    assert "denied" in note
    assert "TL@pl@" not in main.read_text()


def test_unknown_macro_declines(tmp_path: Path) -> None:
    """无定义点且不在 wrap 表 → decline (LLM 手留)。"""
    write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:3: Paragraph ended before \\weirdmacro was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert not ok
    assert "not in wrap table" in note


def test_multi_macro_single_apply(tmp_path: Path) -> None:
    """dedup ``{rule}:None`` 共位 —— 单趟收 err_head + 日志全肇事宏。"""
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\def\\one#1{#1}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:4: Paragraph ended before \\one was complete."
    )
    # 全日志补第二肇事宏 (err_head 只载主错)
    write_file(
        tmp_path,
        "main.log",
        "main.tex:4: Paragraph ended before \\one was complete.\n"
        "main.tex:9: Paragraph ended before \\addcontentsline was complete.\n",
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    t = main.read_text()
    assert "\\long \\def\\one" in t  # def-site
    assert "TL@pl@addcontentsline" in t  # wrap 表宏同趟收


def test_no_sig_declines(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = mk_ctx(tmp_path, err_head="main.tex:3: Undefined control sequence.")
    ok, _ = para_longize(ctx, EngStub(), None, {})
    assert not ok


def test_wrap_table_fwd_braces() -> None:
    """表钉: 无界参转发必须补花括号 —— 裸 ``#n`` 会把实参重切成单 token。"""
    for name in (
        "NR@gettitle",
        "addcontentsline",
        "@citex",
        "@providesfile",
        "setlength",
        "author",
        "caption@prepareanchor",  # watchimpl para-ended-nonlong-cs 族 (zh splice 空行漏)
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
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:3: Paragraph ended before \\mycustom was complete."
    )
    ok, note = para_longize(
        ctx, EngStub(), None, {"wrap_table": {"mycustom": ("#1", "{#1}")}}
    )
    assert ok, note
    assert "TL@pl@mycustom" in main.read_text()


def test_preamble_callsite_seam(tmp_path: Path) -> None:
    """``\\author`` 在 ``\\begin{document}`` 前被调 (frontmatter 面) →
    wrap 块落在调用行之前而非 begindoc 缝 (2112.00059/2112.00071 机制)。"""
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\title{T}\n"
        "\\author{%\n  Alice\\\\\n\n  \\And\n  Bob\n}\n"
        "\\begin{document}\n\\maketitle\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:3: Paragraph ended before \\author was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    t = main.read_text()
    wrap_pos = t.index("% fixloop: para_longize")
    call_pos = t.index("\\author{%")
    assert wrap_pos < call_pos < t.index("\\begin{document}")
    assert "\\let\\TL@pl@author\\author" in t


def test_body_only_call_keeps_begindoc_seam(tmp_path: Path) -> None:
    """调用点只在 body → preamble 缝不启用, 仍落 ``\\begin{document}`` 前。"""
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n"
        "\\begin{document}\n\\author{A\n\nB}\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:3: Paragraph ended before \\author was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    t = main.read_text()
    assert t.index("% fixloop: para_longize") < t.index("\\begin{document}")


def test_def_site_not_a_callsite(tmp_path: Path) -> None:
    """``\\def\\author`` 是定义点不是调用点 —— def-site 臂补 \\long,
    wrap 不被它诱到 preamble 缝, 仍落 begindoc。"""
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\def\\author#1{#1}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:4: Paragraph ended before \\author was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    t = main.read_text()
    assert "\\long \\def\\author" in t
    assert (
        t.index("\\long \\def\\author")
        < t.index("% fixloop: para_longize")
        < t.index("\\begin{document}")
    )


def test_commented_call_not_counted(tmp_path: Path) -> None:
    """注释掉的 ``%\\author{..}`` 不算调用点 → 仍走 begindoc 缝。"""
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n%\\author{A and B}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:5: Paragraph ended before \\author was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    t = main.read_text()
    assert (
        t.index("%\\author")
        < t.index("% fixloop: para_longize")
        < t.index("\\begin{document}")
    )


def test_209_no_begindoc_callsite(tmp_path: Path) -> None:
    """全 fileset 无 ``\\begin{document}`` (2.09 ``\\documentstyle`` 稿) →
    preamble 缝落在首个 live 调用行前。"""
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentstyle{art11}\n\\author{A\n\nB}\ntext\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:2: Paragraph ended before \\author was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    t = main.read_text()
    assert t.index("% fixloop: para_longize") < t.index("\\author{A")


@requires_xelatex
def test_xelatex_preamble_author_e2e(tmp_path: Path) -> None:
    """真 xelatex preamble 缝: 内核非 \\long ``\\author`` (latex.ltx
    ``\\def\\author#1{\\gdef\\@author{#1}}``) preamble 多段调用 →
    begindoc 缝鞭长莫及, preamble 调用点缝 wrapper 吃掉 \\par。"""
    src = (
        "\\documentclass{article}\n\\title{T}\n"
        "\\author{Alice\n\n\\and\n\nBob}\n"
        "\\begin{document}\n\\maketitle\n\\end{document}\n"
    )
    write_file(tmp_path, "main.tex", src)
    run_xelatex_proc(tmp_path)
    log = (tmp_path / "main.log").read_text(errors="replace")
    assert "Paragraph ended before \\author" in log
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:3: Paragraph ended before \\author was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert t.index("% fixloop: para_longize") < t.index("\\author{Alice")
    r2 = run_xelatex_proc(tmp_path)
    log2 = (tmp_path / "main.log").read_text(errors="replace")
    assert r2.returncode == 0
    assert "Paragraph ended" not in log2


@requires_xelatex
def test_xelatex_defsite_e2e(tmp_path: Path) -> None:
    """真 xelatex: 非 \\long ``\\def\\rf`` + 参内空行 → para_ended;
    补 \\long 后同档干净过。"""
    src = (
        "\\documentclass{article}\n\\def\\rf#1{[#1]}\n"
        "\\begin{document}\n\\rf{line one\n\nline two}\n\\end{document}\n"
    )
    write_file(tmp_path, "main.tex", src)
    run_xelatex_proc(tmp_path)
    log = (tmp_path / "main.log").read_text(errors="replace")
    assert "Paragraph ended before \\rf" in log
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:4: Paragraph ended before \\rf was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    r2 = run_xelatex_proc(tmp_path)
    assert r2.returncode == 0
    assert "Paragraph ended" not in (tmp_path / "main.log").read_text(errors="replace")


@requires_xelatex
def test_xelatex_wrap_e2e(tmp_path: Path) -> None:
    """真 xelatex wrap 径: 内核非 \\long ``\\setlength`` (latex.ltx ``\\def
    \\setlength#1#2{#1 #2\\relax}``, fileset 外 → def-site 臂收不到) +
    参内空行 → wrap 注入后 wrapper 吃掉 \\par。"""
    src = (
        "\\documentclass{article}\n"
        "\\begin{document}\n\\setlength{\\parindent}{10pt\n\n}\nx\n\\end{document}\n"
    )
    write_file(tmp_path, "main.tex", src)
    run_xelatex_proc(tmp_path)
    assert "Paragraph ended before \\setlength" in (tmp_path / "main.log").read_text(
        errors="replace"
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:3: Paragraph ended before \\setlength was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    assert "wrap" in note  # 唯一修复径 —— def-site 臂零命中
    r2 = run_xelatex_proc(tmp_path)
    assert r2.returncode == 0


@requires_xelatex
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
    write_file(tmp_path, "main.tex", src)
    run_xelatex_proc(tmp_path)
    log = (tmp_path / "main.log").read_text(errors="replace")
    assert "Paragraph ended before \\NAT@@citetp" in log
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:7: Paragraph ended before \\NAT@@citetp was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    r2 = run_xelatex_proc(tmp_path)
    log2 = (tmp_path / "main.log").read_text(errors="replace")
    assert r2.returncode == 0
    assert "Paragraph ended" not in log2
    assert "CITEOUT:|see also|key1" in log2  # #3 = key1, 不是 \else
