r"""normalize 可再生中间产物截尾整形：8192B 劈断的 aux 不再留不完整末行。

docs/research/latex/2026-09-16-aux-cjk-truncation.md（2211.13013）：
XeTeX 写缓冲在 8192B 边界劈断多字节字符 → shipped/自产 ``.aux`` 系
终结于半截 ``\newlabel``——只转码不整形回读时 ``\@newl@bel`` 照样
扫过 EOF（不完整末行是参数层截断，合法 UTF-8 救不回来）。normalize
侧砍回完整行界、无完整行可留则删除（引擎下遍重长）；
引擎自产件的运行时截断归 fixloop ``purge_corrupt_intermediates``。
"""

from pathlib import Path

import pytest

from texlate.compile.normalize import normalize_project

MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"

#: XeTeX 写缓冲边界——2211.13013 现场的截断点。
XETEX_WRITE_BUF = 8192
#: ``_aux_truncated_at_8192`` 里完整 ``\\newlabel{u}`` 行数（构造参数推演值）。
_UNIT_LINES = 313


def _aux_truncated_at_8192() -> bytes:
    """逐字节复刻 2211.13013 现场：文件总长恰 8192B，末两字节是「中」的前两节。

    XeTeX 写缓冲在 8192 边界截断 → .aux 终结于半截 UTF-8 序列
    （``unexpected end of data``），末行 ``\\newlabel`` 参数不全。
    """
    head = b"\\relax\n"
    unit = b"\\newlabel{u}{{1}{1}{x}{}}\n"
    partial = "\\newlabel{b}{{2}{3}{章节标题".encode() + "中".encode()[:2]
    room = XETEX_WRITE_BUF - len(head) - len(partial)
    lines = (room // len(unit)) * unit
    filler = b"%" + b"p" * (room - len(lines) - 2) + b"\n"  # 完整行补足到 8192
    blob = head + lines + filler + partial
    assert len(blob) == XETEX_WRITE_BUF
    return blob


@pytest.mark.parametrize("suffix", [".aux", ".toc", ".out"])
def test_truncated_intermediate_cut_at_line_boundary(
    tmp_path: Path, suffix: str
) -> None:
    """8192B 劈断的中间产物 → 砍掉不完整末行，写回合法 UTF-8 + 完整 ``\\newlabel``。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    target = tmp_path / f"main{suffix}"
    target.write_bytes(_aux_truncated_at_8192())
    stats = normalize_project(tmp_path, "xelatex")
    rel = f"main{suffix}"
    assert rel in stats["trimmed_intermediates"]
    assert "purged_intermediates" not in stats
    out = target.read_bytes()
    text = out.decode("utf-8")  # strict——不再含非法字节/FFFD
    assert "\ufffd" not in text
    assert text.endswith("\n")
    assert "\\newlabel{b}" not in text  # 半截行整行砍掉
    assert text.count("\\newlabel{u}") == _UNIT_LINES  # 完整前缀一行不丢


def test_truncated_aux_without_complete_line_deleted(tmp_path: Path) -> None:
    """连一行完整内容都留不下 → 直接删除，引擎首遍重长。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    aux = tmp_path / "main.aux"
    aux.write_bytes("\\newlabel{x}{{1}{1}{章节".encode() + b"\xe4")
    stats = normalize_project(tmp_path, "xelatex")
    assert stats["purged_intermediates"] == ["main.aux"]
    assert not aux.exists()


def test_clean_boundary_truncation_also_trimmed(tmp_path: Path) -> None:
    """边界恰好落在字符缝：可解码但末行不完整（无尾 ``\\n`` 即截断判据）。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    aux = tmp_path / "main.aux"
    aux.write_bytes(b"\\relax\n\\newlabel{a}{{1}{1}{ok}{}}\n\\newlabel{b}{{2}{3")
    stats = normalize_project(tmp_path, "xelatex")
    assert stats["trimmed_intermediates"] == ["main.aux"]
    text = aux.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "\\newlabel{a}" in text
    assert "\\newlabel{b}" not in text


def test_healthy_intermediate_untouched(tmp_path: Path) -> None:
    """完整 UTF-8 中间产物（尾换行收尾）不进任何修复台账、字节不变。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    blob = "\\relax\n\\newlabel{a}{{1}{1}{已翻译标题}{}}\n".encode()
    (tmp_path / "main.aux").write_bytes(blob)
    stats = normalize_project(tmp_path, "xelatex")
    assert "trimmed_intermediates" not in stats
    assert "purged_intermediates" not in stats
    assert (tmp_path / "main.aux").read_bytes() == blob


def test_truncated_bib_not_trimmed(tmp_path: Path) -> None:
    """.bib 是数据文件不可再生——无尾换行的完整末行是合法形态，不砍不删。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    bib = "@article{k, author={Doe}, title={t}, year={2020}}"  # 无尾换行
    (tmp_path / "main.bib").write_bytes(bib.encode())
    stats = normalize_project(tmp_path, "xelatex")
    assert "trimmed_intermediates" not in stats
    assert "purged_intermediates" not in stats
    assert (tmp_path / "main.bib").read_text(encoding="utf-8") == bib


def test_truncated_gbk_aux_trimmed_after_decode(tmp_path: Path) -> None:
    """非 UTF-8 中间产物同样先解码再按行界截——GBK 截尾不炸字节砍。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    # 成段 CJK 体量（≥8 相邻高字节）才进双字节族判定——短样本的
    # 单/双字节歧义是检测器既有口径，非本修范围。
    cjk = "第一章节标题内容" * 3
    complete = ("\\relax\n\\newlabel{a}{{1}{1}{" + cjk + "}{}}\n").encode("gbk")
    partial = "\\newlabel{b}{{2}{3}{中".encode("gbk")[:-1]  # 砍掉半个 GBK 字
    aux = tmp_path / "main.aux"
    aux.write_bytes(complete + partial)
    stats = normalize_project(tmp_path, "xelatex")
    assert stats["trimmed_intermediates"] == ["main.aux"]
    text = aux.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert cjk in text
    assert "\\newlabel{b}" not in text
