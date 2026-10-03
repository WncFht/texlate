r"""aux/bib UTF-8 守卫：截断尾豁免 + shipped 中间产物转码覆盖。

docs/research/latex/2026-09-16-aux-cjk-truncation.md 立项（2211.13013）：
shipped 非 UTF-8 .aux/.toc 被引擎首遍回读即 "Invalid UTF-8 byte"
→ ``\@newl@bel`` EOF；截断在 UTF-8 字符中间的文件不再误入双字节检测器。
"""

from pathlib import Path

from conftest import DOC

from texlate.compile.normalize import normalize_project
from texlate.textutil import decode_tex, sniff_tex_encoding


def test_sniff_truncated_utf8_tail_stays_utf8() -> None:
    """尾部半截 UTF-8 序列（截断文件）→ utf-8 判定 + 注记，不进检测器。"""
    blob = "正文内容\nnewlabel 尾".encode() + b"\xe4\xb8"  # 中 的 3 字节被截成 2
    v = sniff_tex_encoding(blob)
    assert v.encoding == "utf-8"
    assert v.note == "truncated utf-8 tail"


def test_sniff_truncated_tail_decodes_with_fffd() -> None:
    blob = b"abc" + "内容".encode() + b"\xe4"
    text = decode_tex(blob)
    assert text.startswith("abc内容")
    assert text.endswith("\ufffd")  # 只炸尾部一字，不整文乱码


def test_sniff_mid_corruption_not_truncated() -> None:
    """中段真坏点不算截断尾——仍走检测器仲裁（verdict 不含截断注记）。"""
    v = sniff_tex_encoding(b"abc\xe4x" + b"plain ascii tail")
    assert v.note != "truncated utf-8 tail"


def test_sniff_latin1_tail_accent_not_truncated() -> None:
    """纯 ASCII 前缀 + 尾部孤立高字节（latin-1 café 尾 0xE9）无法与截断区分——
    交回检测器走 latin-1，不抢 utf-8 截断判。"""
    blob = "café".encode("latin-1")
    v = sniff_tex_encoding(blob)
    assert v.note != "truncated utf-8 tail"
    assert decode_tex(blob) == "café"


def test_normalize_transcodes_shipped_aux(tmp_path: Path) -> None:
    """shipped GBK .aux → UTF-8 写回 + 进 transcoded_aux 台账。"""
    (tmp_path / "main.tex").write_text(DOC % "x", encoding="utf-8")
    aux_gbk = "\\newlabel{fig:x}{{1}{1}{中文标题}{}}\n".encode("gbk")
    (tmp_path / "main.aux").write_bytes(aux_gbk)
    stats = normalize_project(tmp_path, "xelatex")
    assert "main.aux" in stats["transcoded_aux"]
    assert "中文标题" in (tmp_path / "main.aux").read_text(encoding="utf-8")


def test_normalize_transcodes_toc_and_out(tmp_path: Path) -> None:
    """同族回读中间产物（.toc/.out）一并覆盖。"""
    (tmp_path / "main.tex").write_text(DOC % "x", encoding="utf-8")
    (tmp_path / "main.toc").write_bytes("第一章 标题\n".encode("gbk"))
    (tmp_path / "main.out").write_bytes("中文书签\n".encode("gbk"))
    stats = normalize_project(tmp_path, "xelatex")
    assert sorted(stats["transcoded_aux"]) == ["main.out", "main.toc"]
    (tmp_path / "main.toc").read_text(encoding="utf-8")  # 不再炸解码


def test_normalize_keeps_valid_utf8_aux(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(DOC % "x", encoding="utf-8")
    (tmp_path / "main.aux").write_text(
        # win32 write_text 默认 \n→\r\n——转码闸 text.encode()!=original 判重写
        "\\newlabel{a}{{1}{1}{已是中文}{}}\n",
        encoding="utf-8",
        newline="",
    )
    stats = normalize_project(tmp_path, "xelatex")
    assert "transcoded_aux" not in stats
    assert "中文" in (tmp_path / "main.aux").read_text(encoding="utf-8")
