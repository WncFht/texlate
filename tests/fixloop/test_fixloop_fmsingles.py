"""fmsingles 孤儿改动验收 —— ``graphics_ext_pslist_repair`` ctx_suggests ``any:`` 双臂。

实证背景 (failmine4 item5 + chronic347 item-a):

- 1012.1365 (PoS.cls): dvips 时代 ``\\ifpdf`` else 支
  ``\\DeclareGraphicsExtensions{.ps,.eps,.pstex}`` 在 unicode 引擎下整表
  不可解 → 6 处无扩展引用 ``File `X' not found`` +
  ``I could not locate the file with any of these extensions: .ps,.eps,.pstex``
  (PoSlogo + plots/*5 的 .pdf 在盘)。
- 2105.00106/2203.00045 (stagerun-loop3): doc ``\\ifpdf``/``\\ifCLASSINFOpdf``
  else 支 ``\\DeclareGraphicsExtensions{.eps}`` →
  ``paper.tex:N: LaTeX Error: File `X' not found.`` 归 ``other|None`` 死路
  (taxonomy ``missing_file`` 要求 ``\\.\\w+`` 扩展名锚，裸名够不着)。

孤儿改动 = ``ctx_suggests`` 单臂 ``could not locate ...`` 扩为 ``any:`` 双臂，
新增 ``File `[^'.]+' not found``: file:line issuer 形的签名在 ``rep.first``;
``rep.ctx`` = 首错行起 ``CTX_LINES=8`` 行止于 ``l.N`` 回显，``I could not
locate ...`` 帮助行在其后永不入 ``err_head`` (2203.00045 paper.log:2124-2133
实证帮助行在 i+8 出窗)。

scoping 论证：``[^'.]+`` 拒带点名 —— ``File `foo.sty' not found`` 归
install_file/shim 域不抢; 无扩展名缺件在非 graphics 语境罕见
(\\input/\\usepackage/\\documentclass 报错名恒带扩展，唯 graphicx
stem-resolution 报裸名)。AND 闸 ``source_contains`` PS-only decl +
``engine_in`` unicode 引擎兜残余：改写只向表前置原生可读扩展名，
自限一轮 (补后含 .pdf → ``(?![^}]*\\.pdf)`` 拒再火)。
"""

from pathlib import Path

from _fixloopkit import EngStub, apply, mk_ctx, rs, rule

from texlate.compile.fixloop import actions
from texlate.compile.fixloop.engine import LoopCtx

_RULE = "graphics_ext_pslist_repair"

# 2203.00045 paper.log:2124-2131 原样窗 (err_head = rep.first + rep.ctx,
# ctx 8 行止于 l.N 回显行 —— "I could not locate" 在窗外)
_HEAD_EXTLESS = (
    "/work/paper.tex:1205: LaTeX Error: File `fig2_direct_indirect_small'"
    " not found.\n\n"
    "See the LaTeX manual or LaTeX Companion for explanation.\n"
    "Type  H <return>  for immediate help.\n"
    " ...                                              \n"
    "                                                  \n"
    "l.1205 ...s[width=3in]{fig2_direct_indirect_small}\n"
    "                                                  "
)
# PoS.cls issuer 形：帮助行入 ctx 窗的签 (旧臂兜此面)。名取带点形
# ``PoSlogo.eps`` 是刻意的——新臂 ``[^'.]+`` 拒带点名，本钉独过旧臂;
# 裸名形两臂同中，删旧臂无任何钉失败 (裸名面已由 _HEAD_EXTLESS 独守新臂)。
_HEAD_HELPLINE = (
    "PoS.cls:205: LaTeX Error: File `PoSlogo.eps' not found.\n"
    "l.205 ...\\includegraphics{PoSlogo.eps}\n"
    "I could not locate the file with any of these extensions:\n"
    ".ps,.eps,.pstex"
)
_SRC_PS_DECL = (
    "\\documentclass{IEEEtran}\n"
    "\\ifCLASSINFOpdf\n"
    "  \\DeclareGraphicsExtensions{.pdf,.jpeg,.png}\n"
    "\\else\n"
    "  \\DeclareGraphicsExtensions{.eps}\n"
    "\\fi\n"
    "\\begin{document}\n\\includegraphics{fig2_direct_indirect_small}\n"
    "\\end{document}\n"
)


def _ctx(
    tmp_path: Path, *, engine: str = "xelatex", src: str = _SRC_PS_DECL
) -> LoopCtx:
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ctx = mk_ctx(tmp_path)
    ctx.engine_name = engine
    return ctx


def _cond(ctx: LoopCtx) -> tuple[bool, str]:
    r = rule(_RULE)
    return actions._cond_ok(r.condition, r, ctx, EngStub(), None)  # noqa: SLF001


# ════════════════════════ 接线与 dispatch 面 ════════════════════════


def test_rule_wired() -> None:
    """loop 相位 order 17.55 + regex_rewrite; when 三臂含裸 ``other``
    (无扩展名缺件归 other|None, 不得 payload_required)。"""
    r = rule(_RULE)
    assert r.phase == "loop"
    assert r.order == 17.55  # noqa: PLR2004 - schema 断言值
    assert r.action["kind"] == "regex_rewrite"
    ctx = mk_ctx(Path("/nonexistent"), main_rel=None)
    assert actions._when_ok(r.when, "other", None, ctx)  # noqa: SLF001
    assert actions._when_ok(r.when, "missing_file", "x.eps", ctx)  # noqa: SLF001
    assert actions._when_ok(r.when, "missing_graphic", "x.png", ctx)  # noqa: SLF001
    assert not actions._when_ok(r.when, "missing_file", None, ctx)  # noqa: SLF001


def test_order_before_placeholder() -> None:
    """序自洽：includepdf_stub(17.5) < 本规 < placeholder(17.6) —
    盘上有真件时补扩展表先解，占位是缺件兜底。"""
    orders = {r.id: r.order for r in rs().phase("loop")}
    assert orders["includepdf_missing_stub"] < orders[_RULE]
    assert orders[_RULE] < orders["graphic_missing_placeholder"]


# ════════════════════════ any: 双臂 ctx_suggests ════════════════════════


def test_cond_extless_file_not_found_arm(tmp_path: Path) -> None:
    """新臂：``File `X' not found`` 裸名 (file:line 形，rep.first 签名)。

    ctx 窗不含 ``could not locate`` 帮助行也过闸 —— 2105.00106/
    2203.00045 死路签的直达路径。"""
    ctx = _ctx(tmp_path)
    ctx.err_head = _HEAD_EXTLESS
    ok, why = _cond(ctx)
    assert ok, why


def test_cond_could_not_locate_arm(tmp_path: Path) -> None:
    """旧臂：``I could not locate ... extensions`` 帮助行入 ctx 窗的 issuer
    形仍过闸 (1012.1365 PoS.cls 面)。带点名 ``PoSlogo.eps`` 使新臂
    ``[^'.]+`` 不中——本钉独守旧臂，删旧臂即败。"""
    ctx = _ctx(tmp_path)
    ctx.err_head = _HEAD_HELPLINE
    ok, why = _cond(ctx)
    assert ok, why


def test_cond_decline_dotted_filename(tmp_path: Path) -> None:
    """``File `foo.sty' not found`` 带点名 → ``[^'.]+`` 不中：
    缺包件归 install_file/shim 域，本规不抢。"""
    ctx = _ctx(tmp_path)
    ctx.err_head = (
        "/work/paper.tex:42: LaTeX Error: File `foo.sty' not found.\n"
        "l.42 \\usepackage{foo}"
    )
    ok, why = _cond(ctx)
    assert not ok
    assert "any" in why


def test_cond_decline_dotted_graphic(tmp_path: Path) -> None:
    """``File `x.eps' not found`` 带扩展图形名 → 不中：
    归 ext_relax/eps_to_pdf/placeholder 族域。"""
    ctx = _ctx(tmp_path)
    ctx.err_head = "/work/main.tex:9: LaTeX Error: File `x.eps' not found."
    ok, _why = _cond(ctx)
    assert not ok


def test_cond_decline_decl_has_pdf(tmp_path: Path) -> None:
    """工程 decl 已含 .pdf → ``source_contains`` 负前瞻拒 —— 无表可补。"""
    ctx = _ctx(
        tmp_path,
        src="\\documentclass{article}\n"
        "\\DeclareGraphicsExtensions{.pdf,.png,.eps}\n"
        "\\begin{document}\n\\includegraphics{x}\n\\end{document}\n",
    )
    ctx.err_head = _HEAD_EXTLESS
    ok, why = _cond(ctx)
    assert not ok
    assert "pattern" in why


def test_cond_decline_engine_pdflatex(tmp_path: Path) -> None:
    """pdflatex 侧 PS-only 表本就合法 → ``engine_in`` 拒。"""
    ctx = _ctx(tmp_path, engine="pdflatex")
    ctx.err_head = _HEAD_EXTLESS
    ok, why = _cond(ctx)
    assert not ok
    assert "engine" in why


def test_cond_decline_no_signature(tmp_path: Path) -> None:
    """err_head 无两臂签名 → decline (undefined_cs 等异签不串域)。"""
    ctx = _ctx(tmp_path)
    ctx.err_head = "/work/main.tex:3: Undefined control sequence \\foo."
    ok, _why = _cond(ctx)
    assert not ok


def test_cond_decl_resident_in_cls(tmp_path: Path) -> None:
    """decl 只在随稿 ``.cls`` 内 → ``source_contains`` 的 blob 覆盖 ``.cls``
    同过闸 (1012.1365 部署形——decl 不落 main.tex, 只挂 documentclass)。"""
    (tmp_path / "PoS.cls").write_text(
        "%% PoS class\n"
        "\\ifpdf\n"
        "  \\DeclareGraphicsExtensions{.pdf,.jpg,.jpeg}\n"
        "\\else\n"
        "  \\DeclareGraphicsExtensions{.ps,.eps,.pstex}\n"
        "\\fi\n",
        encoding="utf-8",
    )
    ctx = _ctx(
        tmp_path,
        src="\\documentclass{PoS}\n\\begin{document}\nx\\end{document}\n",
    )
    ctx.err_head = _HEAD_EXTLESS
    ok, why = _cond(ctx)
    assert ok, why


# ════════════════════════ action: 扩展表前置 ════════════════════════


def test_apply_prepends_native_exts(tmp_path: Path) -> None:
    """else 支 ``{.eps}`` → ``{.pdf,.png,.jpg,.jpeg,.eps}``;
    已含 .pdf 的 if 支表不动 (2203.00045 真实双表形)。"""
    ctx = _ctx(tmp_path)
    ok, note = apply(_RULE, ctx, None)
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\DeclareGraphicsExtensions{.pdf,.jpeg,.png}" in t  # 原表未动
    assert "\\DeclareGraphicsExtensions{.pdf,.png,.jpg,.jpeg,.eps}" in t


def test_apply_covers_cls_files(tmp_path: Path) -> None:
    """1012.1365 面：decl 在随稿 .cls 内 → exts 含 .cls 同改。"""
    (tmp_path / "PoS.cls").write_text(
        "%% PoS class\n"
        "\\ifpdf\n"
        "  \\DeclareGraphicsExtensions{.pdf,.jpg,.jpeg}\n"
        "\\else\n"
        "  \\DeclareGraphicsExtensions{.ps,.eps,.pstex}\n"
        "\\fi\n",
        encoding="utf-8",
    )
    (tmp_path / "main.tex").write_text(
        "\\documentclass{PoS}\n\\begin{document}\nx\\end{document}\n",
        encoding="utf-8",
    )
    ctx = mk_ctx(tmp_path)
    ok, note = apply(_RULE, ctx, None)
    assert ok, note
    t = (tmp_path / "PoS.cls").read_text(encoding="utf-8")
    assert "\\DeclareGraphicsExtensions{.pdf,.jpg,.jpeg}" in t  # if 支不动
    assert "\\DeclareGraphicsExtensions{.pdf,.png,.jpg,.jpeg,.ps,.eps,.pstex}" in t


def test_apply_commented_decl_untouched(tmp_path: Path) -> None:
    """注释内 ``\\DeclareGraphicsExtensions`` 不算位 (masked 面)。"""
    ctx = _ctx(
        tmp_path,
        src="\\documentclass{article}\n"
        "% \\DeclareGraphicsExtensions{.eps}\n"
        "\\begin{document}\nx\\end{document}\n",
    )
    ok, note = apply(_RULE, ctx, None)
    assert not ok  # 无存活 decl 可改 → applied False
    assert "rewrite in 0" in note


def test_apply_self_limiting_second_fire(tmp_path: Path) -> None:
    """自限性：补后表含 .pdf → ``(?!...)`` 拒再中 —— 二次触火空转
    (false-accept 至多烧一轮，不成环)。"""
    ctx = _ctx(tmp_path)
    ok1, _n1 = apply(_RULE, ctx, None)
    ok2, _n2 = apply(_RULE, ctx, None)
    assert ok1
    assert not ok2
