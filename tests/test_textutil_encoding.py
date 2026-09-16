"""textutil 编码分档判定的构造样例测试（compilebench-v3 语料族逐层对应）。

覆盖：BOM → utf-16 NUL 密度 → strict UTF-8 → 声明采纳/不符 → 双字节
族快判（gb18030/shift_jis）→ 单字节评分（cp1252/cp1251/mac_roman）
→ mixed 分段 → latin-1 兜底。校准锚点均为语料实证案例（见各用例注释）。
"""

from texlate.textutil import (
    CJK_RANGES,
    _char_class,
    decode_tex,
    decode_tex_with,
    is_cjk_cp,
    sniff_tex_encoding,
)

ASCII_TEX = b"\\documentclass{article}\n\\begin{document}\nhello\n\\end{document}\n"


def _verdict(blob: bytes) -> tuple[str, str]:
    v = sniff_tex_encoding(blob)
    return v.encoding, v.basis


# ---------------------------------------------------------------- strict / BOM 档
def test_plain_utf8_is_strict() -> None:
    enc, basis = _verdict(ASCII_TEX + "café αβγ\n".encode())
    assert (enc, basis) == ("utf-8", "strict-utf8")


def test_utf8_sig_bom() -> None:
    enc, basis = _verdict(b"\xef\xbb\xbf" + ASCII_TEX)
    assert (enc, basis) == ("utf-8-sig", "bom")
    assert decode_tex(b"\xef\xbb\xbf" + ASCII_TEX).startswith("\\documentclass")


def test_utf16_bom() -> None:
    enc, basis = _verdict(b"\xff\xfe" + ASCII_TEX.decode().encode("utf-16-le"))
    assert (enc, basis) == ("utf-16", "bom")


def test_utf16_nul_dense_no_bom() -> None:
    """无 BOM utf-16le：NUL+ASCII 本身是合法 UTF-8，NUL 密度判定须先行。"""
    blob = ASCII_TEX.decode().encode("utf-16-le")
    enc, basis = _verdict(blob)
    assert enc == "utf-16-le"
    assert basis == "detector"


# ---------------------------------------------------------------- 声明档
def test_declared_latin1_accepted() -> None:
    """decl=latin1 且字节与检测器一致 → declared 档采纳。"""
    blob = (
        b"\\usepackage[latin1]{inputenc}\n% pr\xe9sent\xe9 \xe0 l'\xe9l\xe8ve\n"
        + ASCII_TEX
    )
    text, v = decode_tex_with(blob)
    assert v.basis == "declared"
    assert v.declared == "latin1"
    assert "présenté" in text


def test_declared_utf8_but_bytes_cp1252() -> None:
    """decl=utf8 实 cp1252——字节胜出并记 mismatch 注记（语料实证族）。"""
    blob = b"\\usepackage[utf8]{inputenc}\n% \x93quoted\x94\n" + ASCII_TEX
    text, v = decode_tex_with(blob)
    assert v.encoding == "cp1252"
    assert "mismatch" in v.note
    assert "“quoted”" in text


def test_declared_latin1_ignored_when_strict_utf8() -> None:
    """decl=latin1 但字节 strict utf-8 → strict-utf8 档 + 忽略注记。"""
    blob = "\\usepackage[latin1]{inputenc}\n% café\n".encode() + ASCII_TEX
    enc, basis = _verdict(blob)
    assert (enc, basis) == ("utf-8", "strict-utf8")
    assert "ignored" in sniff_tex_encoding(blob).note


# ---------------------------------------------------------------- 双字节族快判
def test_gbk_declared_cp936() -> None:
    """decl=cp936 + 相邻高字节块 → gb18030（2105.03820 实证形态）。"""
    body = b"% " + "干涉仪相位灵敏度分析结果如下".encode("gb18030") + b"\n"
    blob = b"% CodePage: 936\n" + body + ASCII_TEX
    text, v = decode_tex_with(blob)
    assert v.encoding == "gb18030"
    assert v.declared == "cp936"
    assert "干涉仪相位灵敏度分析结果如下" in text


def test_shift_jis_kana_evidence() -> None:
    """SJIS 注释块：假名专属面加分压过 gb18030 误吃（cond-mat/0111097）。"""
    body = b"% " + "これはコメントです。入してください。".encode("shift_jis") + b"\n"
    blob = body + ASCII_TEX
    text, v = decode_tex_with(blob)
    assert v.encoding == "shift_jis"
    assert "これはコメントです" in text


def test_sparse_latin_not_cjk() -> None:
    """稀疏 latin 重音不进双字节门——重音后随 ASCII 字母曾喂满
    旧「下位字节」判据误判 gb18030（1206.5832 的 Ciência 实证）。"""
    blob = b"% Ci\xeancia e Tecnologia, S\xe3o Paulo, an\xe1lise\n" + ASCII_TEX
    enc, _basis = _verdict(blob)
    assert enc in {"cp1252", "latin-1", "mac_roman"}


# ---------------------------------------------------------------- 单字节评分档
def test_cp1251_cyrillic_run() -> None:
    blob = b"% " + "Проверка ортографии текста".encode("cp1251") + b"\n" + ASCII_TEX
    text, v = decode_tex_with(blob)
    assert v.encoding == "cp1251"
    assert "Проверка" in text


def test_applemac_curly_quotes() -> None:
    """applemac 0xD2/0xD3 = “”——Word/Classic-Mac 导出签名。"""
    blob = b"% \xd2quoted\xd3 by \xd2editor\xd3\n" + ASCII_TEX
    text, v = decode_tex_with(blob)
    assert v.encoding == "mac_roman"
    assert "“quoted”" in text


def test_lone_0xa3_prefers_cp1252_not_cp866() -> None:
    """单字节 0xA3：cp866 的 ``г`` 曾凭 +1 单字分抢赢 cp1252 的 ``£``
    （hep-ph/9910443 实证）——非拉丁孤立字降半分后 cp1252 胜出。"""
    blob = b"% value \xa3 = 11.57\n" + ASCII_TEX
    enc, _basis = _verdict(blob)
    assert enc in {"cp1252", "mac_roman"}


# ---------------------------------------------------------------- mixed / 兜底
def test_mixed_utf8_plus_latin1() -> None:
    """合法 UTF-8 序列与孤立 latin1 共存 → utf-8-mixed 分段解码。"""
    blob = b"% caf\xc3\xa9 r\xc3\xa9sum\xc3\xa9\n% stray \xe9 byte\n" + ASCII_TEX
    text, v = decode_tex_with(blob)
    assert v.encoding == "utf-8-mixed"
    assert v.basis == "mixed"
    assert "café" in text


def test_decode_tex_never_raises() -> None:
    assert isinstance(decode_tex(bytes(range(256))), str)


def test_decode_tex_matches_with_variant() -> None:
    blob = b"% caf\xe9\n" + ASCII_TEX
    assert decode_tex(blob) == decode_tex_with(blob)[0]


# ---------------------------------------------------------------- 码点面边界（bisect 查找面钉点）
def test_is_cjk_cp_boundaries() -> None:
    """``CJK_RANGES`` 每区间 lo±1/hi±1 + 代表点——bisect 面与原线性
    区间逐点同义，边界含侧不得漂移（0x3007 是单点区间）。"""
    spec = lambda cp: any(lo <= cp <= hi for lo, hi in CJK_RANGES)  # noqa: E731
    pts = {0, 0x41, 0xFFFD, 0x10FFFF, 0x2FA20}
    for lo, hi in CJK_RANGES:
        pts |= {lo - 1, lo, lo + 1, hi - 1, hi, hi + 1}
    for cp in pts:
        assert is_cjk_cp(cp) == spec(cp), hex(cp)
    # 〇（U+3007 日期用字）+ 已知内/外代表点
    for cp in (0x3007, 0x4E00, 0x20000):
        assert is_cjk_cp(cp), hex(cp)
    for cp in (0x3006, 0xA000):
        assert not is_cjk_cp(cp), hex(cp)


def test_char_class_boundaries() -> None:
    """``_CLASS_RANGES`` 全边界逐点钉名——含相邻区间接界与双覆盖点
    （0x3007 同时在 cjk 类区与 ``CJK_RANGES``；0x3400 由扩A 归 cjk）。"""
    cases = {
        # latin_ext
        0x9F: "other",
        0xA0: "latin_ext",
        0x24F: "latin_ext",
        0x250: "other",
        0x1DFF: "other",
        0x1E00: "latin_ext",
        0x1EFF: "latin_ext",
        # greek
        0x36F: "other",
        0x370: "greek",
        0x3FF: "greek",
        0x1F00: "greek",
        0x1FFF: "greek",
        0x2000: "other",
        # cyrillic
        0x400: "cyrillic",
        0x52F: "cyrillic",
        0x530: "other",
        0x2DDF: "other",
        0x2DE0: "cyrillic",
        0x2DFF: "cyrillic",
        0x2E00: "other",
        # boxdraw
        0x24FF: "other",
        0x2500: "boxdraw",
        0x259F: "boxdraw",
        0x25A0: "other",
        # cjk 类区 + CJK_RANGES 续段
        0x2FFF: "other",
        0x3000: "cjk",
        0x3007: "cjk",
        0x33FF: "cjk",
        0x3400: "cjk",
        0x9FFF: "cjk",
        0xF900: "cjk",
        0xFAFF: "cjk",
        0x20000: "cjk",
        0x2FA1F: "cjk",
        0x2FA20: "other",
        # 面外
        0x41: "other",
        0x7F: "other",
        0xFFFD: "other",
        0x10FFFF: "other",
    }
    for cp, want in cases.items():
        assert _char_class(chr(cp)) == want, hex(cp)
