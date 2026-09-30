r"""raster_pdf_rename 单测 —— mislabeled-raster-as-pdf 伪装件改名+引用改写。

实证背景 (singlesweep mech_buckets mislabeled-raster-as-pdf 6 格):
e-print 船货 ``X.pdf`` 实为 PNG/JPEG 字节 —— 引擎按后缀走 pdf 链
拒载, xetex 报 ``Unable to load picture or PDF file 'X.pdf'`` 归
missing_graphic (``missing_file|X.pdf`` 是 pdftex.def 同族措辞)。
修复 = magic 嗅探改名真扩展名 (``X.png``/``X.jpg``) + 存活
``\includegraphics`` 显式 ``.pdf`` arg 后缀改写; 无扩展名 arg 经
``\Gin@extensions`` 自解不动 (1607.00405 ``{fig5}`` 实证)。
``\includepdf`` arg 不改 —— pdfpages 只收真 pdf, 改名后归
includepdf_missing_stub 落 ``\clearpage\null`` 诚实降级。
"""

from pathlib import Path

from _fixloopkit import mk_ctx, rs, rule

from texlate.compile.fixloop import actions
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx

_RULE = "raster_pdf_rename"

#: 合法最小 PNG/JPEG 前缀 (magic + 少量填充 —— builtin 只读头 16 字节)。
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
_REAL_PDF = b"%PDF-1.4\n" + b"\x00" * 32


def _run(ctx: LoopCtx, payload: str | None = "x.pdf") -> tuple[bool, str]:
    # raster_pdf_rename ``del eng`` 不触引擎面 —— None 直传
    # (test_fixloop_restore_support 同款先例)。
    return TRANSFORM_FNS[_RULE](ctx, None, payload, {})


# ════════════════════════════ 规则接线 ════════════════════════════


def test_rule_wired() -> None:
    """order 17.7 + builtin_transform + missing_graphic/missing_file 双臂。"""
    r = rule(_RULE)
    assert r.order == 17.7  # noqa: PLR2004 - schema 断言值
    assert r.action["kind"] == "builtin_transform"
    assert r.action["function"] == _RULE
    ctx = LoopCtx(wdir=Path("/nonexistent"), engine_name="xelatex")
    assert actions._when_ok(r.when, "missing_graphic", "x.pdf", ctx)  # noqa: SLF001
    assert actions._when_ok(r.when, "missing_file", "x.pdf", ctx)  # noqa: SLF001
    assert not actions._when_ok(r.when, "missing_graphic", None, ctx)  # noqa: SLF001
    assert not actions._when_ok(r.when, "other", "x.pdf", ctx)  # noqa: SLF001


def test_rule_order_before_repair() -> None:
    """序自洽：placeholder(17.6) < raster_pdf_rename < graphic_repair(18)。"""
    orders = {r.id: r.order for r in rs().phase("loop")}
    assert orders["graphic_missing_placeholder"] < orders[_RULE]
    assert orders[_RULE] < orders["graphic_repair"]


# ════════════════════════════ magic 改名 + 引用改写 ════════════════════════════


def test_png_explicit_arg_renamed_and_rewritten(tmp_path: Path) -> None:
    """2504.15280 形：PNG 字节 .pdf + 显式 .pdf arg → 改名 .png + arg 改写。"""
    (tmp_path / "figure").mkdir()
    (tmp_path / "figure" / "icon.pdf").write_bytes(_PNG)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\includegraphics[width=\\linewidth]{figure/icon.pdf}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _run(mk_ctx(tmp_path), "figure/icon.pdf")
    assert ok, note
    assert not (tmp_path / "figure" / "icon.pdf").exists()
    assert (tmp_path / "figure" / "icon.png").read_bytes() == _PNG
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "{figure/icon.png}" in t
    assert "{figure/icon.pdf}" not in t


def test_jpeg_subdir_arg_renamed_jpg(tmp_path: Path) -> None:
    """2310.01082 形：JPEG 字节 .pdf 子目录件 → 改名 .jpg + arg 后缀换。"""
    (tmp_path / "plots").mkdir()
    (tmp_path / "plots" / "mlp_noise.pdf").write_bytes(_JPEG)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\includegraphics[width=0.23\\linewidth]{plots/mlp_noise.pdf}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _run(mk_ctx(tmp_path), "plots/mlp_noise.pdf")
    assert ok, note
    assert (tmp_path / "plots" / "mlp_noise.jpg").read_bytes() == _JPEG
    assert "{plots/mlp_noise.jpg}" in (tmp_path / "main.tex").read_text(
        encoding="utf-8"
    )


def test_extless_arg_self_heals_untouched(tmp_path: Path) -> None:
    """1607.00405 形：无扩展名 arg {fig5} → 只改名不改 arg (ext 表自解)。"""
    (tmp_path / "fig5.pdf").write_bytes(_PNG)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\includegraphics[height=6.2cm]{fig5}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _run(mk_ctx(tmp_path), "fig5.pdf")
    assert ok, note
    assert (tmp_path / "fig5.png").read_bytes() == _PNG
    assert "{fig5}" in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_real_pdf_untouched(tmp_path: Path) -> None:
    """真 %PDF 头件不落表 —— 无伪装件 decline, 文件与引用原样。"""
    (tmp_path / "paper.pdf").write_bytes(_REAL_PDF)
    (tmp_path / "main.tex").write_text(
        "\\includegraphics{paper.pdf}\n", encoding="utf-8"
    )
    ok, note = _run(mk_ctx(tmp_path), "paper.pdf")
    assert not ok
    assert "no raster-bytes" in note
    assert (tmp_path / "paper.pdf").read_bytes() == _REAL_PDF
    assert "{paper.pdf}" in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_sweep_covers_unreferenced_and_multi(tmp_path: Path) -> None:
    """一次点火全量扫 —— 无引用伪装件同改 (2504.15280 双件实证)。"""
    (tmp_path / "a.pdf").write_bytes(_PNG)
    (tmp_path / "b.pdf").write_bytes(_JPEG)
    (tmp_path / "main.tex").write_text("\\includegraphics{a.pdf}\n", encoding="utf-8")
    ok, note = _run(mk_ctx(tmp_path), "a.pdf")
    assert ok, note
    assert (tmp_path / "a.png").is_file()
    assert (tmp_path / "b.jpg").is_file()
    assert "2/2" in note


def test_commented_ref_not_rewritten(tmp_path: Path) -> None:
    """遮盖面：注释内 \\includegraphics arg 不算存活引用位。"""
    (tmp_path / "x.pdf").write_bytes(_PNG)
    (tmp_path / "main.tex").write_text(
        "% \\includegraphics{x.pdf}\n\\includegraphics{x}\n",
        encoding="utf-8",
    )
    ok, _ = _run(mk_ctx(tmp_path), "x.pdf")
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "% \\includegraphics{x.pdf}" in t  # 注释原样


def test_includepdf_arg_not_rewritten(tmp_path: Path) -> None:
    """\\includepdf arg 不改 —— pdfpages 只收真 pdf, 归 stub 降级域。"""
    (tmp_path / "supp.pdf").write_bytes(_PNG)
    (tmp_path / "main.tex").write_text(
        "\\includepdf{supp.pdf}\n\\includegraphics{supp}\n",
        encoding="utf-8",
    )
    ok, _ = _run(mk_ctx(tmp_path), "supp.pdf")
    assert ok
    assert (tmp_path / "supp.png").is_file()
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\includepdf{supp.pdf}" in t  # 引用原样 —— 下轮 stub 接


def test_collision_declines_file_not_overwrite(tmp_path: Path) -> None:
    """目标位撞名 → 该件跳过不覆写; 无件改成 → 整体 decline。"""
    (tmp_path / "x.pdf").write_bytes(_PNG)
    (tmp_path / "x.png").write_bytes(b"real png\n")
    (tmp_path / "main.tex").write_text("\\includegraphics{x.pdf}\n", encoding="utf-8")
    ok, note = _run(mk_ctx(tmp_path), "x.pdf")
    assert not ok
    assert "exists" in note
    assert (tmp_path / "x.png").read_bytes() == b"real png\n"
    assert (tmp_path / "x.pdf").read_bytes() == _PNG


def test_skip_dirs_and_main_pdf_excluded(tmp_path: Path) -> None:
    """_tect_out/dot-dir/main.pdf 排除面 —— 封装树与产物不嗅探。"""
    (tmp_path / "_tect_out").mkdir()
    (tmp_path / "_tect_out" / "mid.pdf").write_bytes(_PNG)
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "x.pdf").write_bytes(_PNG)
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    (tmp_path / "main.pdf").write_bytes(_PNG)  # 产物 pdf 非内嵌图件
    ok, note = _run(mk_ctx(tmp_path), "x.pdf")
    assert not ok
    assert "no raster-bytes" in note
    assert (tmp_path / "_tect_out" / "mid.pdf").is_file()
    assert (tmp_path / "main.pdf").read_bytes() == _PNG


def test_basename_hit_via_graphicspath(tmp_path: Path) -> None:
    """basename 形 arg ({icon.pdf} 经 graphicspath/子目录解析) → 后缀换名。"""
    (tmp_path / "figure").mkdir()
    (tmp_path / "figure" / "icon.pdf").write_bytes(_PNG)
    (tmp_path / "main.tex").write_text(
        "\\graphicspath{{figure/}}\n\\includegraphics{icon.pdf}\n",
        encoding="utf-8",
    )
    ok, _ = _run(mk_ctx(tmp_path), "figure/icon.pdf")
    assert ok
    assert (tmp_path / "figure" / "icon.png").is_file()
    assert "{icon.png}" in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_sty_ext_arg_rewritten(tmp_path: Path) -> None:
    """``.sty`` 内 ``\\includegraphics{x.pdf}`` 同扫 —— exts=('.tex','.sty') 覆盖面。"""
    (tmp_path / "x.pdf").write_bytes(_PNG)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{mypkg}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "mypkg.sty").write_text(
        "\\ProvidesPackage{mypkg}\n\\newcommand{\\splash}{\\includegraphics{x.pdf}}\n",
        encoding="utf-8",
    )
    ok, note = _run(mk_ctx(tmp_path), "x.pdf")
    assert ok, note
    assert (tmp_path / "x.png").is_file()
    sty = (tmp_path / "mypkg.sty").read_text(encoding="utf-8")
    assert "\\includegraphics{x.png}" in sty
    assert "x.pdf" not in sty


def test_partial_skip_note_lists_collision(tmp_path: Path) -> None:
    """a.pdf→a.png 成、b.pdf→b.jpg 撞名跳过 → True + note 带 ``; skipped:``。"""
    (tmp_path / "a.pdf").write_bytes(_PNG)
    (tmp_path / "b.pdf").write_bytes(_JPEG)
    (tmp_path / "b.jpg").write_bytes(b"real jpg\n")
    (tmp_path / "main.tex").write_text(
        "\\includegraphics{a.pdf}\n\\includegraphics{b.pdf}\n", encoding="utf-8"
    )
    ok, note = _run(mk_ctx(tmp_path), "a.pdf")
    assert ok, note
    assert "; skipped:" in note
    assert "b.jpg exists" in note
    assert (tmp_path / "a.png").is_file()
    assert "{a.png}" in (tmp_path / "main.tex").read_text(encoding="utf-8")
    # 撞名件原地保留不覆写
    assert (tmp_path / "b.pdf").read_bytes() == _JPEG
    assert (tmp_path / "b.jpg").read_bytes() == b"real jpg\n"
