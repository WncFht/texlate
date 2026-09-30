r"""ENC 族机制钉（L6 车道）：normalize/decode 项目级编码归一化实证。

L6 车道七机制逐条钉位。stagerun-loop1 records 实证
（19 例 zh 臂全零 ``warn:invalid_utf8``——裸源 base 臂的 warn 即对照组）：
B02/W08/W13/W42/W43/W72 的编码层在生产路径已修对，本文件把
「裸源坏字节 → ``normalize_project`` → 盘上干净 UTF-8」端到端钉死；
W91 ``\-`` 断词还原为 2026-09-18 新增手术（hep-th/9910234 实证族）；
同日顺手修 ``_score_text`` 无声明通路的 mac_roman ``‡`` 彩票误吃
latin-1 法文（词中大写重音签名罚分）。
"""

from pathlib import Path

from texlate.compile.normalize import (
    normalize_engine,
    normalize_manual_hyphens,
    normalize_project,
)
from texlate.textutil import decode_tex, decode_tex_with


def _strict_utf8(path: Path) -> str:
    """盘上件按 strict UTF-8 回读——坏字节残留直接炸出。"""
    return path.read_bytes().decode("utf-8")


# ---------------------------------------------------------------- B02 非 UTF-8 源
def test_latin1_project_transcoded_to_utf8(tmp_path: Path) -> None:
    """latin-1 .tex → 盘上 UTF-8 + 重音存活（0707.0167/0905.4368 实证形）。"""
    (tmp_path / "main.tex").write_bytes(
        "\\documentclass{article}\n\\begin{document}\n"
        "Université de Montréal, présenté à l'élève\n\\end{document}\n".encode(
            "latin-1"
        )
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    text = _strict_utf8(tmp_path / "main.tex")
    assert "Université" in text
    assert "présenté" in text
    assert stats["rewritten"] >= 1
    assert stats["encodings"]["main.tex"]["basis"] == "detector"


def test_undeclared_french_latin1_beats_mac_roman() -> None:
    """无声明法文 latin-1：mac_roman 把 ``à``(0xE0) 吃成 ``‡`` 曾凭 typo
    彩票分压过正确解码产 ``UniversitÈ`` mojibake——词中小写 + 大写重音
    签名罚分后 cp1252/latin-1 胜出（declared 通路早有 slack 兜底，无
    声明通路此钉前一直裸奔）。"""
    blob = "Université de Montréal, présenté à l'élève\n".encode("latin-1")
    text, v = decode_tex_with(blob)
    assert v.encoding in {"latin-1", "cp1252"}
    assert "Université" in text
    assert "présenté" in text


# ---------------------------------------------------------------- W08 CRLF
def test_eol_norm_cr_and_crlf() -> None:
    """``\\r\\n`` 与裸 ``\\r`` 同归 ``\\n``——TeX 输入处理同口径。"""
    assert decode_tex(b"a\r\nb\rc\nd") == "a\nb\nc\nd"


def test_crlf_project_normalized_to_lf(tmp_path: Path) -> None:
    """全 CRLF .tex → 盘上 LF（1404.5809 paper2.tex 1742/1742 行实证）。"""
    (tmp_path / "main.tex").write_bytes(
        b"\\documentclass{article}\r\n\\begin{document}\r\n"
        b"line one\r\n\\input sub\r\n\\end{document}\r\n"
    )
    (tmp_path / "sub.tex").write_bytes(b"sub body\r\n")
    normalize_project(tmp_path, "xelatex", "main.tex")
    for name in ("main.tex", "sub.tex"):
        assert b"\r" not in (tmp_path / name).read_bytes()
    assert "\\input sub\n" in _strict_utf8(tmp_path / "main.tex")


# ---------------------------------------------------------------- W13 声明≠字节
def test_declared_latin1_but_utf8_bytes(tmp_path: Path) -> None:
    """声明 latin1 实 UTF-8 → 字节判定胜出（1511.06943 实证形）。"""
    (tmp_path / "main.tex").write_bytes(
        "\\documentclass{article}\n\\usepackage[latin1]{inputenc}\n"
        "\\begin{document}\nUniversité\n\\end{document}\n".encode()
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert "Université" in _strict_utf8(tmp_path / "main.tex")
    entry = stats["encodings"]["main.tex"]
    assert entry["basis"] == "strict-utf8"
    assert "ignored" in entry["note"]


# ---------------------------------------------------------------- W72 混合编码
def test_mixed_utf8_isolated_byte_project(tmp_path: Path) -> None:
    """合法 UTF-8 对与孤立 latin1 字节共存 → 分段解码盘上 UTF-8。

    1511.06717 starsim_p1_v8.tex 实证：C3A8(è)×2 + 孤立 0xC4——单码
    iconv 不可救的混合形态（splice 臂实测 strict UTF-8 落盘）。
    """
    (tmp_path / "main.tex").write_bytes(
        b"\\documentclass{article}\n\\begin{document}\n"
        b"caf\xc3\xa9 r\xc3\xa9sum\xc3\xa9\n"
        b"% aims heading\xc4\n"
        b"\\end{document}\n"
    )
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    text = _strict_utf8(tmp_path / "main.tex")
    assert "café" in text
    assert "heading" in text
    assert stats["encodings"]["main.tex"]["basis"] == "mixed"


# ---------------------------------------------------------------- W42/W43 字面 Unicode
def test_literal_unicode_math_symbols_preserved(tmp_path: Path) -> None:
    """字面 Unicode 数学符号过 normalize 原样存活（2105.11398 newunicodechar 族）。"""
    (tmp_path / "main.tex").write_bytes(
        "\\documentclass{article}\n\\begin{document}\n"
        "$x ∈ A ⊆ B$ and $a ⎨⎬ b$, also ⋅ ∈ ⊆\n\\end{document}\n".encode()
    )
    normalize_project(tmp_path, "xelatex", "main.tex")
    text = _strict_utf8(tmp_path / "main.tex")
    for ch in "∈⊆⎨⎬⋅":
        assert ch in text


def test_literal_typographic_unicode_preserved(tmp_path: Path) -> None:
    """字面排版引号/破折号散落正文 → 原样存活（2203.13106/2403.15111 族）。"""
    (tmp_path / "main.tex").write_bytes(
        "\\documentclass{article}\n\\begin{document}\n"
        "STAR’s “destinations” — application’s\n\\end{document}\n".encode()
    )
    normalize_project(tmp_path, "xelatex", "main.tex")
    text = _strict_utf8(tmp_path / "main.tex")
    for ch in "’“”—":
        assert ch in text


# ---------------------------------------------------------------- W91 \- 断词还原
def test_manual_hyphen_words_restored() -> None:
    """字母夹 ``\\-`` 断词整词还原（hep-th/9910234 实证形）。"""
    assert normalize_manual_hyphens("sphe\\-ri\\-cal") == "spherical"
    assert normalize_manual_hyphens("cy\\-lin\\-dri\\-cal") == "cylindrical"
    assert normalize_manual_hyphens("non-Car\\-te\\-sian") == "non-Cartesian"
    assert normalize_manual_hyphens("dis\\-able") == "disable"


def test_manual_hyphen_cs_tail_untouched() -> None:
    r"""``\foo\-bar`` 的 ``foo`` 是 cs 尾——剥 ``\-`` 会接成 ``\foobar``。"""
    assert normalize_manual_hyphens(r"\foo\-bar baz") == r"\foo\-bar baz"
    assert normalize_manual_hyphens(r"\mbox\-text") == r"\mbox\-text"
    # 断词串续段同样挡死：bar 前位是 \- 尾符，不放行
    assert normalize_manual_hyphens(r"\foo\-bar\-baz") == r"\foo\-bar\-baz"


def test_manual_hyphen_tabbing_env_untouched() -> None:
    """tabbing 环境 ``\\-`` 是「上一制表位」命令——env 面豁免。"""
    src = "\\begin{tabbing}\nfoo \\> bar\\-baz \\\\\n\\end{tabbing}\n"
    assert normalize_manual_hyphens(src) == src
    assert normalize_manual_hyphens("out\\-side\n" + src) == "outside\n" + src


def test_manual_hyphen_comment_verbatim_untouched() -> None:
    """注释/verbatim 在遮蔽视图外——``\\-`` 原样保留。"""
    src = "% sphe\\-ri\\-cal\n\\begin{verbatim}\nx\\-y\n\\end{verbatim}\n"
    assert normalize_manual_hyphens(src) == src


def test_manual_hyphen_via_engine_and_project(tmp_path: Path) -> None:
    """normalize_engine 链路与项目级落盘双钉。"""
    src = "A dis\\-cretionary sphe\\-ri\\-cal word\n"
    assert "discretionary spherical" in normalize_engine(src, "xelatex")
    (tmp_path / "main.tex").write_bytes(
        b"\\documentclass{article}\n\\begin{document}\n"
        b"dis\\-cretionary sphe\\-ri\\-cal\n\\end{document}\n"
    )
    normalize_project(tmp_path, "xelatex", "main.tex")
    text = _strict_utf8(tmp_path / "main.tex")
    assert "discretionary spherical" in text
    assert "\\-" not in text
