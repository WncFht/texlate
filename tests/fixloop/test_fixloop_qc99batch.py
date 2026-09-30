"""qc99 (2026-09-28) fixloop-rules-batch 钉测试——a–h 项逐臂直驱。

覆盖：(a) DeclareUnicodeCharacter polyfill_pre / (b) babelfont 四臂 /
(c) typein_neutralize \\read-1 臂 + \\def 转义修复 / (d) pkg_alias_rewrite /
(e) maketitle_suppl_float_flush / (f) uchead_vskip_relax / (h) rotfig_caption_pad。
(g) bbl fmt<3.0 结构性错配判 accept-as-is, 无规则面不钉。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from _fixloopkit import (
    apply,
    cond_ok,
    mk_ctx_files,
    params,
    rule,
)

from texlate.compile.fixloop.builtins import TRANSFORM_FNS

if TYPE_CHECKING:
    from pathlib import Path


# ── (a) DeclareUnicodeCharacter: polyfill_pre 缝 docclass 前 ──
# copernicus.cls:1169+ 在 class 执行期调 \\DeclareUnicodeCharacter——
# post-docclass polyfill 在 halt_on_error 下永远落不到。
def test_declareunicode_polyfill_pre_key() -> None:
    spec = params("cs_targeted_fix")["cs_table"]["DeclareUnicodeCharacter"]
    assert "polyfill_pre" in spec
    assert "polyfill" not in spec


def test_declareunicode_injects_before_docclass(tmp_path: Path) -> None:
    files = {
        "main.tex": "\\documentclass{foo}\n\\begin{document}\nx\n\\end{document}\n",
        "foo.cls": "\\DeclareUnicodeCharacter{0394}{\\textrm{x}}\n",
    }
    ctx = mk_ctx_files(tmp_path, files)
    ok, note = apply("cs_targeted_fix", ctx, "DeclareUnicodeCharacter")
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    i_shim = t.index("providecommand{\\DeclareUnicodeCharacter}")
    assert i_shim < t.index("\\documentclass")


# ── (b) babelfont 四臂 (font_name_substitute) ──

ARABIC_CELL = """\\documentclass{article}
\\usepackage{babel}
\\babelprovide{arabic}
\\babelfont[arabic]{rm}[
  BoldFont=Amiri-Bold.ttf,
  ItalicFont=Amiri-Italic.ttf,
  BoldItalicFont=Amiri-BoldItalic.ttf
]{Amiri-Regular.ttf}
\\begin{document}
x
\\end{document}
"""


def test_babelfont_arabic_allfontkey_bracket_drop(tmp_path: Path) -> None:
    """2609.20684 实证形：arabic 臂整括号丢弃 → Naskh 家族自解析字重。"""
    ctx = mk_ctx_files(tmp_path, {"main.tex": ARABIC_CELL})
    ok, note = apply("font_name_substitute", ctx, "Amiri-Regular")
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\babelfont[arabic]{rm}{Noto Naskh Arabic}" in t
    assert "Amiri" not in t


def test_babelfont_arabic_mixed_bracket_kept(tmp_path: Path) -> None:
    """features 括号含非 *Font 键 → 括号保留，仅主参换 Naskh。"""
    tex = (
        "\\babelfont[arabic]{rm}[Language=Arabic,BoldFont=X-Bold.ttf]"
        "{Amiri-Regular.ttf}\n"
    )
    ctx = mk_ctx_files(tmp_path, {"main.tex": tex})
    ok, _ = apply("font_name_substitute", ctx, "Amiri-Regular")
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "[Language=Arabic,BoldFont=X-Bold.ttf]" in t
    assert "{Noto Naskh Arabic}" in t


def test_babelfont_generic_fontkey_bracket_drop(tmp_path: Path) -> None:
    tex = "\\babelfont{rm}[\n  BoldFont=PTSerif-Bold.ttf\n]{PTSerif-Regular.ttf}\n"
    ctx = mk_ctx_files(tmp_path, {"main.tex": tex})
    ok, _ = apply("font_name_substitute", ctx, "PTSerif-Regular")
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\babelfont{rm}{Latin Modern Roman}" in t


def test_babelfont_generic_no_bracket(tmp_path: Path) -> None:
    tex = "\\babelfont{rm}{CharisSIL-R.ttf}\n"
    ctx = mk_ctx_files(tmp_path, {"main.tex": tex})
    ok, _ = apply("font_name_substitute", ctx, "CharisSIL-R")
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\babelfont{rm}{Latin Modern Roman}" in t


# ── (c) typein_neutralize \\read-1 臂 + \\def 转义修复 ──
def test_read_neg1_terminal_stub(tmp_path: Path) -> None:
    """hep-th/9412166 实证形：\\read-1 to\\yesno → \\def\\yesno{}。"""
    tex = (
        "\\read-1 to\\yesno\n"
        "\\ifx\\yesno\\y\\textheight 23cm\\else\\textheight 21cm\\fi\n"
    )
    ctx = mk_ctx_files(tmp_path, {"main.tex": tex})
    ok, note = apply("typein_neutralize", ctx, None)
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\def\\yesno{}" in t
    assert "\\read-1" not in t


def test_typein_twoarg_repl_no_escape_corruption(tmp_path: Path) -> None:
    r"""regex 模块 repl 转义钉: \\def 必须字面落件 (\d=bad escape / \f=FF / \r=CR)。"""
    ctx = mk_ctx_files(tmp_path, {"main.tex": "\\typein[\\ans]{press return?}\n"})
    ok, _ = apply("typein_neutralize", ctx, None)
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert t.strip() == "\\typeout{press return?}\\def\\ans{}"


def test_read_file_stream_untouched(tmp_path: Path) -> None:
    """``\\read\\myin`` 文件流不受影响——模式钉 ``-\\d``。"""
    tex = "\\newread\\myin\n\\openin\\myin=data.txt\n\\read\\myin to\\val\n"
    ctx = mk_ctx_files(tmp_path, {"main.tex": tex})
    ok, _ = apply("typein_neutralize", ctx, None)
    assert not ok  # 无 typein/\\read- 字面 → rewrite 空转 applied=False
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\read\\myin to\\val" in t


def test_read_neg1_condition_gate(tmp_path: Path) -> None:
    ctx = mk_ctx_files(tmp_path, {"main.tex": "\\read-1 to\\yesno\n"})
    ok, _ = cond_ok("typein_neutralize", ctx, None)
    assert ok
    ctx2 = mk_ctx_files(tmp_path / "b", {"main.tex": "\\read\\myin to\\val\n"})
    ok2, _ = cond_ok("typein_neutralize", ctx2, None)
    assert not ok2


# ── (d) pkg_alias_rewrite: amssymbols → amssymb ──
def test_pkg_alias_rewrite_single(tmp_path: Path) -> None:
    """quant-ph/0003035 实证形。"""
    ctx = mk_ctx_files(tmp_path, {"main.tex": "\\usepackage{amssymbols}\n"})
    ok, note = apply("pkg_alias_rewrite", ctx, "amssymbols.sty")
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\usepackage{amssymb}" in t


def test_pkg_alias_rewrite_list_form(tmp_path: Path) -> None:
    ctx = mk_ctx_files(tmp_path, {"main.tex": "\\usepackage{foo,amssymbols,bar}\n"})
    ok, _ = apply("pkg_alias_rewrite", ctx, "amssymbols.sty")
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "{foo,amssymb,bar}" in t


def test_pkg_alias_rewrite_payload_gate(tmp_path: Path) -> None:
    ctx = mk_ctx_files(tmp_path, {"main.tex": "\\usepackage{amssymbols}\n"})
    ok, _ = cond_ok("pkg_alias_rewrite", ctx, "amssymbols.sty")
    assert ok
    ok2, _ = cond_ok("pkg_alias_rewrite", ctx, "other.sty")
    assert not ok2


# ── (e) maketitle_suppl_float_flush ──
ICCV_STY = "\\def\\maketitlesupplementary{ \\newpage \\twocolumn[\\iccvtitle] }\n"


def test_maketitle_suppl_flush(tmp_path: Path) -> None:
    """2504.07951 iccv.sty:479 实证形：\\newpage→\\clearpage + \\floatpagefraction 注入。"""
    ctx = mk_ctx_files(tmp_path, {"iccv.sty": ICCV_STY}, main="iccv.sty")
    ok, note = apply("maketitle_suppl_float_flush", ctx, None)
    assert ok, note
    t = (tmp_path / "iccv.sty").read_text(encoding="utf-8")
    assert "\\clearpage" in t
    assert "\\newpage" not in t
    assert "\\renewcommand{\\floatpagefraction}{0.15}" in t


def test_maketitle_suppl_idempotent(tmp_path: Path) -> None:
    ctx = mk_ctx_files(tmp_path, {"iccv.sty": ICCV_STY}, main="iccv.sty")
    apply("maketitle_suppl_float_flush", ctx, None)
    t1 = (tmp_path / "iccv.sty").read_text(encoding="utf-8")
    ok2, _ = apply("maketitle_suppl_float_flush", ctx, None)
    t2 = (tmp_path / "iccv.sty").read_text(encoding="utf-8")
    assert not ok2  # 二跑全臂空转 → applied=False
    assert t1 == t2


# ── (f) uchead_vskip_relax ──
ACM_CLS = (
    "\\def\\@uchead#1{%\n"
    "  \\vspace{6pt}%\n"
    "}\n"
    "\\def\\@sect#1#2{%\n"
    "  \\vskip -12pt  %gkmt, 11 aug 99 and GM July 2000 (was -14)\n"
    "  \\vskip -9pt % ssect tighter\n"
    "}\n"
)


def test_uchead_vskip_relax(tmp_path: Path) -> None:
    """ACM uchead 簇：-12pt→-2pt; 旁生 -9pt 不动。"""
    ctx = mk_ctx_files(tmp_path, {"sig.cls": ACM_CLS}, main="sig.cls")
    ok, note = apply("uchead_vskip_relax", ctx, None)
    assert ok, note
    t = (tmp_path / "sig.cls").read_text(encoding="utf-8")
    assert "\\vskip -2pt" in t
    assert "\\vskip -12pt" not in t
    assert "\\vskip -9pt" in t


def test_uchead_gate_blocks_non_uchead(tmp_path: Path) -> None:
    """非 @uchead 族标的 -12pt 不收 (cond 闸)。"""
    ctx = mk_ctx_files(tmp_path, {"x.cls": "\\vskip -12pt\n"}, main="x.cls")
    ok, _ = cond_ok("uchead_vskip_relax", ctx, None)
    assert not ok


# ── (h) rotfig_caption_pad builtin + rule ──

ROTATE_CELL = """\\begin{figure}
\\centering
\\rotatebox{-90}{\\includegraphics[width=0.34\\linewidth]{fig5a.eps}}
\\caption{两行长标题第二行}
\\end{figure}
"""


def test_rotfig_caption_pad_rotatebox(tmp_path: Path) -> None:
    """0812.0424 实证形：\\rotatebox + \\caption → env 头注 pad。"""
    ctx = mk_ctx_files(tmp_path, {"main.tex": ROTATE_CELL})
    ok, note = TRANSFORM_FNS["rotatebox_caption_pad"](ctx, None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\setlength{\\abovecaptionskip}{14pt}" in t
    i_pad = t.index("\\setlength{\\abovecaptionskip}")
    assert i_pad < t.index("\\rotatebox") < t.index("\\caption")


def test_rotfig_caption_pad_angle_optarg(tmp_path: Path) -> None:
    """0707.3761 实证形：angle=270 + [hb] placement——锚点须越过可选参。"""
    tex = (
        "\\begin{figure}[hb]\n"
        "\\includegraphics [width=6.0cm,angle=270]{f.eps}\n"
        "\\caption{x}\n"
        "\\end{figure}\n"
    )
    ctx = mk_ctx_files(tmp_path, {"main.tex": tex})
    ok, _ = apply("rotfig_caption_pad", ctx, None)
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "[hb]\n\\setlength{\\abovecaptionskip}{14pt}" in t


def test_rotfig_caption_pad_idempotent(tmp_path: Path) -> None:
    ctx = mk_ctx_files(tmp_path, {"main.tex": ROTATE_CELL})
    TRANSFORM_FNS["rotatebox_caption_pad"](ctx, None, None, {})
    t1 = (tmp_path / "main.tex").read_text(encoding="utf-8")
    ok2, _ = TRANSFORM_FNS["rotatebox_caption_pad"](ctx, None, None, {})
    assert not ok2
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == t1


def test_rotfig_caption_pad_negatives(tmp_path: Path) -> None:
    """非旋转图 / 无 caption / 注释内 env 均不垫。"""
    unrotated = (
        "\\begin{figure}\n\\includegraphics{a.pdf}\n\\caption{x}\n\\end{figure}\n"
    )
    no_caption = (
        "\\begin{figure}\n\\rotatebox{90}{\\includegraphics{a.eps}}\n\\end{figure}\n"
    )
    commented = (
        "% \\begin{figure}\n% \\rotatebox{90}{x}\n% \\caption{y}\n% \\end{figure}\n"
    )
    ctx = mk_ctx_files(
        tmp_path,
        {"a.tex": unrotated, "b.tex": no_caption, "c.tex": commented},
        main="a.tex",
    )
    ok, _ = TRANSFORM_FNS["rotatebox_caption_pad"](ctx, None, None, {})
    assert not ok
    for name in ("a.tex", "b.tex", "c.tex"):
        assert "abovecaptionskip" not in (tmp_path / name).read_text()


def test_rotfig_rule_registered() -> None:
    r = rule("rotfig_caption_pad")
    assert r.phase == "precheck"
    assert r.action["function"] == "rotatebox_caption_pad"
    assert "rotatebox_caption_pad" in TRANSFORM_FNS
