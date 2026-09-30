"""normalize.py 无条件手术的单测——纯文本手术面（docs/spec/translate.md §3.1 逐条对应）。

工程级集成面（encoding/junk/PS/atend/transcode/rebase/shadow/kpse/legacy-latin）
归 test_compile_normalize_project.py；bundled .bbl 面归 test_compile_bbl.py。
"""

from texlate.compile.normalize import (
    PIXEL_COMPATIBILITY,
    TECTONIC_FONT_COMPATIBILITY,
    XETEX_COMPATIBILITY,
    normalize_comment_terminators,
    normalize_engine,
    normalize_float_positions,
    normalize_legacy_cjk,
    normalize_pdf_primitives,
    normalize_pdftex_features,
    normalize_pixel_dimensions,
    strip_input_encodings,
)


# 1. comment 终结行
def test_comment_terminators_strip_trailing_ws() -> None:
    tex = "a\n\\end{comment}  \t\nb"
    assert "\\end{comment}\n" in normalize_comment_terminators(tex)


def test_comment_terminators_idempotent_clean() -> None:
    tex = "a\n\\end{comment}\nb"
    assert normalize_comment_terminators(tex) == tex


# 2. float 位置参数
def test_float_positions_illegal_letter() -> None:
    """`[!htbpX]` 的非法字母 X 剥掉 → `[!htbp]`。"""
    tex = "\\begin{figure}[!htbpX]\nx\\end{figure}"
    out = normalize_float_positions(tex)
    assert "[!htbp]" in out


def test_float_positions_all_illegal_drops_bracket() -> None:
    tex = "\\begin{table}[xyz]\nx\\end{table}"
    out = normalize_float_positions(tex)
    assert "\\begin{table}\nx" in out


def test_float_positions_symbol_chars_untouched() -> None:
    """`[^@]` 这类含符号的位置参数不匹配正则——保持上游语义不改。"""
    tex = "\\begin{table}[^@]\nx\\end{table}"
    assert normalize_float_positions(tex) == tex


# 3. pdfTeX 特性
def test_pdftex_output_settings_removed() -> None:
    tex = "\\pdfcompresslevel=9\n\\input{glyphtounicode}\nkeep"
    out = normalize_pdftex_features(tex, "xelatex")
    assert "\\pdfcompresslevel" not in out
    assert "glyphtounicode" not in out
    assert "keep" in out
    assert out.count("\n") == tex.count("\n")


def test_microtype_unsupported_options() -> None:
    tex = "\\usepackage[protrusion=true,expansion=true,tracking=true]{microtype}"
    xe = normalize_pdftex_features(tex, "xelatex")
    assert "expansion=false" in xe
    assert "tracking=true" in xe  # xelatex 保留 tracking
    tec = normalize_pdftex_features(tex, "tectonic")
    assert "tracking=false" in tec  # tectonic bundle microtype 无 tracking


def test_microtype_options_in_multipkg_list() -> None:
    """多包列表 `{microtype,amsmath}` 的选项同样到 microtype——也得改写。"""
    tex = "\\usepackage[expansion=true]{microtype,amsmath}"
    out = normalize_pdftex_features(tex, "xelatex")
    assert "expansion=false" in out
    assert "microtype,amsmath" in out  # 包列表本身不动


# 4. px → \pdfpxdimen（语境受限）
def test_pixel_dimensions_includegraphics() -> None:
    tex = "\\includegraphics[width=360px]{a.pdf}"
    out = normalize_pixel_dimensions(tex)
    assert r"360\pdfpxdimen" in out


def test_pixel_dimensions_setlength() -> None:
    tex = "\\setlength{\\foo}{12px}"
    out = normalize_pixel_dimensions(tex)
    assert r"12\pdfpxdimen" in out


def test_pixel_dimensions_not_global() -> None:
    """散文里的 "360px" 描述文本不被误改。"""
    tex = "The image is 360px wide in CSS terms."
    assert normalize_pixel_dimensions(tex) == tex


# 4b. px → bp（空格分隔多值键；`\pdfpxdimen` 控制词吞分隔空格挤塌
# `\Gread@parse@vp` 四参解析，只能落字面单位——2308.00148/2211.00113 实案）
def test_pixel_dimensions_trim_braced_bp() -> None:
    """2308.00148 cw-sup-content.tex 实形：braced trim 四值 → bp。"""
    tex = (
        "\\includegraphics[trim={0cm 128px 0cm 127px},clip,"
        "width=\\textwidth,height=0.75\\textwidth]{#1}"
    )
    out = normalize_pixel_dimensions(tex)
    assert "trim={0cm 128bp 0cm 127bp}" in out
    assert "pdfpxdimen" not in out


def test_pixel_dimensions_trim_unbraced_bp() -> None:
    """2211.00113 introduction.tex 实形：无括号 trim=10px ×4 → 10bp ×4。"""
    tex = (
        "\\includegraphics[height=\\FigHeight mm, trim=10px 10px 10px 10px, "
        "clip]{figure/x.png}"
    )
    out = normalize_pixel_dimensions(tex)
    assert "trim=10bp 10bp 10bp 10bp" in out
    assert "px" not in out.replace("pdfpxdimen", "")


def test_pixel_dimensions_viewport_bb_bp() -> None:
    """viewport/bb 同为四值空格分隔 → bp。"""
    tex = "\\includegraphics[viewport=0 0 100px 200px,clip]{x.png}"
    out = normalize_pixel_dimensions(tex)
    assert "viewport=0 0 100bp 200bp" in out
    tex = "\\includegraphics[bb=0 0 10px 20px]{x.png}"
    out = normalize_pixel_dimensions(tex)
    assert "bb=0 0 10bp 20bp" in out


def test_pixel_dimensions_bb_scalar_pdfpxdimen() -> None:
    """bbllx/bburx/natheight 等单值键走 \\pdfpxdimen（无空格分隔问题）。"""
    tex = "\\includegraphics[bburx=30px,natheight=40px]{x.png}"
    out = normalize_pixel_dimensions(tex)
    assert r"bburx=30\pdfpxdimen" in out
    assert r"natheight=40\pdfpxdimen" in out


def test_pixel_dimensions_mixed_keys() -> None:
    """同括号内 trim → bp 与 width → \\pdfpxdimen 并存。"""
    tex = "\\includegraphics[trim={0 0 8px 0},width=5px]{x.png}"
    out = normalize_pixel_dimensions(tex)
    assert "trim={0 0 8bp 0}" in out
    assert r"width=5\pdfpxdimen" in out


def test_pixel_dimensions_nondim_keys_untouched() -> None:
    """非尺寸键（scale/hiresbb/clip/非键名 xwidth）里的 px 不动。"""
    tex = (
        "\\includegraphics[scale=0.5,hiresbb=true,clip]{x.png}\n"
        "\\includegraphics[xwidth=10px]{x.png}\n"
        "trim={0cm 99px 0cm 99px}  % not in includegraphics bracket"
    )
    out = normalize_pixel_dimensions(tex)
    assert out == tex


def test_pixel_dimensions_commented_trim_masked() -> None:
    """注释里的 trim px 在遮蔽面外——不动。"""
    tex = (
        "% \\includegraphics[trim={0cm 128px 0cm 127px}]{x}\n"
        "\\includegraphics[trim={0cm 1px 0cm 1px}]{x}\n"
    )
    out = normalize_pixel_dimensions(tex)
    assert "% \\includegraphics[trim={0cm 128px 0cm 127px}]{x}" in out
    assert "trim={0cm 1bp 0cm 1bp}" in out


def test_pixel_dimensions_idempotent() -> None:
    """重写幂等：二遍 normalize 不再动已归一的 bp/\\pdfpxdimen。"""
    tex = "\\includegraphics[trim={0cm 128px 0cm 127px},width=5px]{x.png}"
    once = normalize_pixel_dimensions(tex)
    assert normalize_pixel_dimensions(once) == once


def test_pixel_block_in_subfile() -> None:
    """子文件 \\input 场景：px 只在子件时子件自带 PIXEL 块（主件无注入面）。

    实案面：cw-sup-content.tex/introduction.tex 类子文件含 px——has_document
    闸曾把 PIXEL_COMPATIBILITY 限死在带 \\begin{document} 的文件，子件改出的
    \\pdfpxdimen 无定义 → Undefined cs 级联（今 \\ifdefined 幂等闸随件落地）。
    """
    tex = "\\includegraphics[width=5px]{a.pdf}\n"
    out = normalize_engine(tex, "xelatex")
    assert PIXEL_COMPATIBILITY.strip() in out
    assert out.index("pdfpxdimen") < out.index("width=5")


# 5. 兼容前导块
def test_compat_blocks_injected_once() -> None:
    tex = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}"
    out = normalize_engine(tex, "tectonic")
    assert XETEX_COMPATIBILITY.strip().splitlines()[0] in out
    assert TECTONIC_FONT_COMPATIBILITY.strip().splitlines()[0] in out
    out2 = normalize_engine(out, "tectonic")
    assert out2.count("texlate-native") == out.count("texlate-native")


def test_quantumarticle_option_spelled_exactly() -> None:
    """拼写守卫：类只认 `allowfontchangeintitle`——错一个字母 xkeyval 静默拒收。"""
    assert "allowfontchangeintitle" in XETEX_COMPATIBILITY
    assert "allowfontchageintitle" not in XETEX_COMPATIBILITY


def test_pixel_block_only_when_pxd_used() -> None:
    plain = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}"
    out = normalize_engine(plain, "xelatex")
    assert "pdfpxdimen" not in out.split("\\begin{document}")[0]
    withpx = "\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\n\\includegraphics[width=5px]{a}\n\\end{document}"
    out2 = normalize_engine(withpx, "xelatex")
    assert PIXEL_COMPATIBILITY.strip() in out2


# 6. fontspec no-math 前插
def test_fontspec_no_math_prepended() -> None:
    tex = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}"
    out = normalize_engine(tex, "xelatex")
    assert out.startswith("\\PassOptionsToPackage{no-math}{fontspec}")


# 7. inputenc/fontenc
def test_strip_inputenc_keeps_others() -> None:
    tex = "\\usepackage[utf8]{inputenc,amsmath,T1fontenc}\n\\usepackage{fontenc}"
    out = strip_input_encodings(tex.replace("T1fontenc", "fontenc"))
    assert "amsmath" in out
    assert "inputenc" not in out


def test_strip_inputenc_list_only_removes_named() -> None:
    tex = "\\usepackage[utf8]{inputenc,amsmath}"
    out = strip_input_encodings(tex)
    assert "{amsmath}" in out


def test_strip_inputenc_sole_removal_preserves_line_count() -> None:
    """整包剔除后是空行而非多插行——删除须保行号稳定（模块不变量）。"""
    tex = "line1\n\\usepackage{fontenc}\nline3\n"
    out = strip_input_encodings(tex)
    assert out.count("\n") == tex.count("\n")
    assert "fontenc" not in out
    assert out.splitlines()[1].strip() == ""


# 8. pdfinfo / pdfoutput / 驱动选项
def test_pdfinfo_removed() -> None:
    tex = "\\pdfinfo{/Title (Hi)}\nkeep"
    out = normalize_pdf_primitives(tex)
    assert "\\pdfinfo" not in out
    assert "keep" in out


def test_pdfoutput_removed() -> None:
    tex = "\\pdfoutput=1\nkeep"
    out = normalize_pdf_primitives(tex)
    assert "\\pdfoutput" not in out


def test_driver_option_pdftex_to_xetex() -> None:
    tex = "\\usepackage[pdftex,bookmarks]{hyperref}\n\\usepackage[pdftex]{graphicx}"
    out = normalize_pdf_primitives(tex)
    assert "[xetex,bookmarks]" in out
    assert "[xetex]{graphicx}" in out


def test_driver_option_unrelated_untouched() -> None:
    tex = "\\usepackage[pdftex]{amsmath}"
    assert normalize_pdf_primitives(tex) == tex


def test_driver_option_multipkg_to_xetex() -> None:
    """多包并列面: [drv]{a,b} 表内含驱动敏感包 → token 改写 (pasj00/aa.cls 形)。"""
    tex = (
        "\\usepackage[dvips]{graphicx,color}\n"
        "\\usepackage[pdftex]{epsfig,graphicx}\n"
        "\\usepackage[dvips]{graphics, color}\n"
    )
    out = normalize_pdf_primitives(tex)
    assert "[xetex]{graphicx,color}" in out
    assert "[xetex]{epsfig,graphicx}" in out
    assert "[xetex]{graphics, color}" in out


def test_driver_option_multipkg_no_sensitive_untouched() -> None:
    """多包面保守侧: 表内无驱动敏感包 → 原样 (\\b 挡 colortbl 子串伪命中)。"""
    tex = "\\usepackage[dvips]{amsmath,amssymb}\n\\usepackage[pdftex]{colortbl}"
    assert normalize_pdf_primitives(tex) == tex


def test_driver_option_dvips_to_xetex() -> None:
    """ps 系驱动 token → xetex：usepackage + documentclass + PassOptions 三面。"""
    tex = (
        "\\documentclass[dvips,twocolumn]{article}\n"
        "\\usepackage[dvips]{graphicx}\n"
        "\\PassOptionsToPackage{dvips}{color}\n"
    )
    out = normalize_pdf_primitives(tex)
    assert "[xetex,twocolumn]" in out
    assert "[xetex]{graphicx}" in out
    assert "{xetex}{color}" in out


def test_driver_option_dvipdfmx_kept() -> None:
    """dvipdfmx 与 XeTeX 兼容——不改写。"""
    tex = "\\usepackage[dvipdfmx]{graphicx}"
    assert normalize_pdf_primitives(tex) == tex


# 9. legacy CJK
def test_legacy_cjk_to_xecjk() -> None:
    tex = (
        "\\documentclass{article}\n\\usepackage{CJKutf8}\n"
        "\\begin{document}\n\\begin{CJK}{UTF8}{gbsn}x\\end{CJK}\n\\end{document}"
    )
    out = normalize_legacy_cjk(tex, "xelatex")
    assert "CJKutf8" not in out
    assert "xeCJK" in out
    assert "FandolSong" in out
    assert "\\begin{CJK}" not in out


def test_normalize_engine_lualatex_only_cjk() -> None:
    """lualatex 不走 XeTeX 手术，只换 legacy CJK——且落 luatexja 而非 xeCJK。"""
    tex = "\\documentclass{article}\n\\pdfcompresslevel=9\n\\begin{document}\nx\\end{document}"
    out = normalize_engine(tex, "lualatex")
    assert "\\pdfcompresslevel=9" in out  # lualatex 保留 pdftex 原语
    cjk = (
        "\\documentclass{article}\n\\usepackage{CJKutf8}\n"
        "\\begin{document}\n\\begin{CJK}{UTF8}{gbsn}x\\end{CJK}\n\\end{document}"
    )
    out_cjk = normalize_engine(cjk, "lualatex")
    assert "CJKutf8" not in out_cjk
    assert "luatexja" in out_cjk
    assert "xeCJK" not in out_cjk
