"""def-D 三格 (task #143) —— already_def 尾段新子机制单测。

item 1 ``.bbl`` 站点面 (1907.10621): shipped madminer.bbl ``\\newcommand{\\enquote}``
    自体双 input 撞名 —— revtex4-1 ``rtx@thebibliography`` env-end
    ``\\auto@bib@innerbib`` → ``\\bibliography{}`` 再 input ``\\jobname.bbl``,
    第二遍撞第一遍的组内定义; 锚 ``\\bibliography``/``\\input`` 外侧的清位够不到
    bbl 内互撞 → ``_redef_site_map`` 扩 ``.bbl``, 站点前置清位落 bbl 内
    (每遍 input 各自先清后定义)。清位统一 csname-let 形 —— ``.bbl`` 在
    文档面 input (@=catcode-12), 零字面 ``@`` 任意宿主 catcode 可读。
item 2 ``\\AtBeginDocument`` 迟延定义者 (1706.00033): 用户 ``\\def\\sh`` vs
    babel russianb.ldf ``\\AtBeginDocument`` 钩内 ``\\DeclareMathOperator{\\sh}``
    —— 钩执行期错误的 file:line 归因恒为 ``\\begin{document}`` 所在行;
    一切立即 ``\\let`` (docclass 块/装载点前) 恒错序 → 声明点前注
    ``\\AtBeginDocument{<csname-let 清位串>}`` 占首钩位, 钩 FIFO 先清位,
    迟延定义者再定义赢。
item 3 ``\\newfont`` 站点命令 (astro-ph/0307459): ``\\newfont{\\Bbb}{msbm10
    scaled 1200}`` 产 Command 签 already_def —— ``_SITE_DEF_CMDS`` 收录后
    站点前置生效; 裸形 ``\\newfont\\X`` 仍由 ``_ALLOC_CS_RE`` 分配名护栏剔出
    abstain。
"""

from pathlib import Path

from _fixloopkit import mk_ctx
from test_fixloop_csfix2 import _proj, _read

from texlate.compile.fixloop._builtins_csfix import _site_clear_line
from texlate.compile.fixloop.builtins import TRANSFORM_FNS

_UNDEF = TRANSFORM_FNS["undefine_for_redef"]

#: 1907.10621 同型 —— revtex auto-bib 二次 input, 归因落在 bbl 内行。
_BBL_LOG = (
    "(./madminer.bbl\n"
    "./madminer.bbl:2: LaTeX Error: Command `\\enquote' already defined.\n"
    "See the LaTeX manual or LaTeX Companion for explanation.\n"
)

#: 1706.00033 同型 —— 钩执行期错误, 归因行 = \begin{document} 所在行 (main.tex:5)。
_SH_LOG = (
    "./main.tex:5: LaTeX Error: Command `\\sh' already defined.\n"
    "See the LaTeX manual or LaTeX Companion for explanation.\n"
)

#: astro-ph/0307459 同型 —— \newfont{\Bbb} 站点行即归因行。
_NEWFONT_LOG = (
    "./main.tex:3: LaTeX Error: Command `\\Bbb' already defined.\n"
    "See the LaTeX manual or LaTeX Companion for explanation.\n"
)

_SH_TEX = (
    "\\documentclass{book}\n"
    "\\usepackage{amsmath}\n"
    "\\usepackage[russian]{babel}\n"
    "\\def\\sh{\\mathop{\\rm sh}\\nolimits}\n"
    "\\begin{document}\nx\n\\end{document}\n"
)


class _EngStub:
    """引擎面替身 —— probe 恒命中, install 恒成。"""

    def probe_file(self, fname: str, cwd: Path | None = None) -> str:
        del cwd
        return f"/texmf/{fname}"

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return True


# ═══════════════════════ item 1: .bbl 站点面 ═══════════════════════


def test_bbl_site_prepend_csname(tmp_path: Path) -> None:
    """``.bbl`` 内 ``\\newcommand`` 站前置 csname-let 清位 (无 makeatletter 对)。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{revtex4-1}\n\\begin{document}\nx\n\\end{document}\n"
            ),
            "madminer.bbl": (
                "\\begin{thebibliography}{100}\n"
                "\\newcommand{\\enquote}[1]{``#1''}\n"
                "\\bibitem{x} y\n"
                "\\end{thebibliography}\n"
            ),
            "main.log": _BBL_LOG,
        },
    )
    ok, note = _UNDEF(mk_ctx(tmp_path), _EngStub(), "enquote", {})
    assert ok, note
    assert "site-prepend" in note
    bbl = _read(tmp_path, "madminer.bbl")
    assert (
        "\\expandafter\\let\\csname enquote\\endcsname\\TeXlateUndefCs\n"
        "\\newcommand{\\enquote}" in bbl
    )
    # 站点臂只剔 pkg_covered/abd 名 —— docclass 块 belt 同轮照发 (无害)。
    main = _read(tmp_path, "main.tex")
    assert "% fixloop: batch undefine" in main


def test_bbl_site_cluster_expanded_provide_skipped(tmp_path: Path) -> None:
    """同 bbl 其它 ``\\newcommand`` 站同清; ``\\providecommand`` 非恒拒名站不收。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{revtex4-1}\n\\begin{document}\nx\n\\end{document}\n"
            ),
            "madminer.bbl": (
                "\\begin{thebibliography}{100}\n"
                "\\newcommand{\\enquote}[1]{``#1''}\n"
                "\\newcommand{\\arx}{arXiv}\n"
                "\\providecommand{\\urlprefix}{URL }\n"
                "\\bibitem{x} y\n"
                "\\end{thebibliography}\n"
            ),
            "main.log": _BBL_LOG,
        },
    )
    ok, note = _UNDEF(mk_ctx(tmp_path), _EngStub(), "enquote", {"min_batch": 2})
    assert ok, note
    bbl = _read(tmp_path, "madminer.bbl")
    assert (
        "\\expandafter\\let\\csname arx\\endcsname\\TeXlateUndefCs\n"
        "\\newcommand{\\arx}" in bbl
    )
    assert "\\csname urlprefix\\endcsname" not in bbl


def test_bbl_refire_no_double_prepend(tmp_path: Path) -> None:
    """已清位站点 64 字前缀窗幂等 —— 再火不在 bbl 二次前置。"""
    files = {
        "main.tex": (
            "\\documentclass{revtex4-1}\n\\begin{document}\nx\n\\end{document}\n"
        ),
        "madminer.bbl": (
            "\\begin{thebibliography}{100}\n"
            "\\newcommand{\\enquote}[1]{``#1''}\n"
            "\\bibitem{x} y\n"
            "\\end{thebibliography}\n"
        ),
        "main.log": _BBL_LOG,
    }
    _proj(tmp_path, files)
    ok, _ = _UNDEF(mk_ctx(tmp_path), _EngStub(), "enquote", {})
    assert ok
    before = _read(tmp_path, "madminer.bbl")
    _UNDEF(mk_ctx(tmp_path), _EngStub(), "enquote", {})
    after = _read(tmp_path, "madminer.bbl")
    assert after == before
    assert after.count("\\csname enquote\\endcsname\\TeXlateUndefCs") == 1


def test_bbl_dead_site_masked(tmp_path: Path) -> None:
    """bbl 内注释掉的 ``\\newcommand`` 是死站 —— 不锚不数, docclass 块兜底。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{revtex4-1}\n\\begin{document}\nx\n\\end{document}\n"
            ),
            "madminer.bbl": (
                "\\begin{thebibliography}{100}\n"
                "% \\newcommand{\\enquote}[1]{``#1''}\n"
                "\\bibitem{x} y\n"
                "\\end{thebibliography}\n"
            ),
            "main.log": _BBL_LOG,
        },
    )
    ok, note = _UNDEF(mk_ctx(tmp_path), _EngStub(), "enquote", {})
    assert ok, note
    assert "docclass block" in note
    bbl = _read(tmp_path, "madminer.bbl")
    assert "\\csname enquote\\endcsname" not in bbl


# ═══════════════ item 2: \AtBeginDocument 迟延定义者臂 ═══════════════


def test_abd_hook_injected_pre_docclass(tmp_path: Path) -> None:
    """归因行 ``\\begin{document}`` → 声明点前注首钩位清位, docclass 块不发。"""
    _proj(tmp_path, {"main.tex": _SH_TEX, "main.log": _SH_LOG})
    ok, note = _UNDEF(mk_ctx(tmp_path), _EngStub(), "sh", {})
    assert ok, note
    assert "AtBeginDocument" in note
    text = _read(tmp_path, "main.tex")
    assert (
        "\\AtBeginDocument{\\expandafter\\let\\csname sh\\endcsname\\TeXlateUndefCs}"
    ) in text
    # 钩注册位必须先于 \documentclass —— FIFO 首钩, 抢在 babel 钩注册前。
    assert text.index("\\AtBeginDocument{\\expandafter") < text.index("\\documentclass")
    # 迟延定义者不被立即 \let 覆盖 → docclass 块不重发。
    assert "% fixloop: batch undefine" not in text


def test_abd_line_not_begindoc_falls_to_docclass(tmp_path: Path) -> None:
    """归因行非 ``\\begin{document}`` → 钩臂不接管, docclass 块走老路。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{book}\n"
                "\\def\\zz{x}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "main.log": (
                "./main.tex:2: LaTeX Error: Command `\\zz' already defined.\n"
            ),
        },
    )
    ok, note = _UNDEF(mk_ctx(tmp_path), _EngStub(), "zz", {})
    assert ok, note
    assert "docclass block" in note
    text = _read(tmp_path, "main.tex")
    assert "\\AtBeginDocument{" not in text
    assert "\\csname zz\\endcsname\\TeXlateUndefCs" in text


def test_abd_no_docclass_declines_to_block(tmp_path: Path) -> None:
    """无声明点 (残缺稿) → 钩臂不接管, docclass 块文件头兜底。"""
    _proj(
        tmp_path,
        {
            "main.tex": "\\def\\sh{x}\n\\begin{document}\nx\n\\end{document}\n",
            "main.log": (
                "./main.tex:2: LaTeX Error: Command `\\sh' already defined.\n"
            ),
        },
    )
    ok, note = _UNDEF(mk_ctx(tmp_path), _EngStub(), "sh", {})
    assert ok, note
    assert "docclass block" in note
    text = _read(tmp_path, "main.tex")
    assert "\\AtBeginDocument{" not in text
    assert "\\csname sh\\endcsname\\TeXlateUndefCs" in text


def test_abd_refire_idempotent(tmp_path: Path) -> None:
    """钩已注册 → 不重注; 立即 ``\\let`` 亦不重发 → "already cleared" 收束。"""
    _proj(tmp_path, {"main.tex": _SH_TEX, "main.log": _SH_LOG})
    ok, _ = _UNDEF(mk_ctx(tmp_path), _EngStub(), "sh", {})
    assert ok
    ok2, note2 = _UNDEF(mk_ctx(tmp_path), _EngStub(), "sh", {})
    assert not ok2
    assert "already cleared" in note2
    assert _read(tmp_path, "main.tex").count("\\AtBeginDocument{") == 1


def test_abd_hook_via_err_head(tmp_path: Path) -> None:
    """归因证据在 ``ctx.err_head`` (本轮错误 blob) 亦可触发钩臂。"""
    _proj(tmp_path, {"main.tex": _SH_TEX})
    ctx = mk_ctx(tmp_path, err_head=_SH_LOG)
    ok, note = _UNDEF(ctx, _EngStub(), "sh", {})
    assert ok, note
    assert (
        "\\AtBeginDocument{\\expandafter\\let\\csname sh\\endcsname\\TeXlateUndefCs}"
        in _read(tmp_path, "main.tex")
    )


# ═══════════════════════ item 3: \newfont 站点命令 ═══════════════════════


def test_newfont_brace_site_prepend(tmp_path: Path) -> None:
    """``\\newfont{\\X}{spec}`` 花括号形入站点面; 簇内兄弟站同清。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage{amssymb}\n"
                "\\newfont{\\Bbb}{msbm10 scaled 1200}\n"
                "\\newfont{\\frak}{eufm10 scaled 1200}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "main.log": _NEWFONT_LOG,
        },
    )
    ok, note = _UNDEF(mk_ctx(tmp_path), _EngStub(), "Bbb", {})
    assert ok, note
    assert "site-prepend" in note
    text = _read(tmp_path, "main.tex")
    assert (
        "\\expandafter\\let\\csname Bbb\\endcsname\\TeXlateUndefCs\n"
        "\\newfont{\\Bbb}{msbm10 scaled 1200}" in text
    )
    assert (
        "\\expandafter\\let\\csname frak\\endcsname\\TeXlateUndefCs\n"
        "\\newfont{\\frak}{eufm10 scaled 1200}" in text
    )


def test_newfont_bare_form_alloc_guarded(tmp_path: Path) -> None:
    """``\\newfont\\X`` 裸形 = ``_ALLOC_CS_RE`` 分配名 —— 剔出撞名集 abstain。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\newfont\\Bbb{msbm10}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "main.log": _NEWFONT_LOG,
        },
    )
    ok, note = _UNDEF(mk_ctx(tmp_path), _EngStub(), "Bbb", {})
    assert not ok
    assert "allocated" in note


def test_newfont_ifn_routed_endstar() -> None:
    """``\\newfont`` 是 ``\\@ifdefinable`` 路由命令 —— end* 名换 rc@ 旁路。"""
    assert _site_clear_line("newfont", "endfoo") == (
        r"\expandafter\let\csname @ifdefinable\expandafter\endcsname"
        r"\csname @rc@ifdefinable\endcsname"
    )
    assert _site_clear_line("newfont", "Bbb") == (
        r"\expandafter\let\csname Bbb\endcsname\TeXlateUndefCs"
    )
