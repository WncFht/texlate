r"""lane-nfsstu (2026-09-20): nfss_enc 类三臂 —— xelatex TU 下 legacy NFSS
enc 声明族 (0712.1142 / 2609.20339 / 2609.20539 原归 other|None)。

- ``nfss_cmd_enc_polyfill`` (Arm A): ``Command \X unavailable in encoding E``
  → ``\DeclareTextCommand{\X}{E}{body}`` docclass 后注入; ``\ensuremath``
  体表两模态通用 (DeclareTextSymbol 字面槽在 cm 字体 missing-char, f1c
  repro 实证); 体表外 cs decline。
- ``nfss_enc_scheme_relax`` (Arm B): ``Encoding scheme `E' unknown`` →
  活 ``\usefont/\fontencoding{E}`` 站点改 TU + T2A Cyrillic 字形 cs 表
  ``\providecommand`` polyfill; 空 ``\DeclareFontEncoding`` 产 Corrupted
  NFSS 硬错 (f2a) 不可用作声明侧修法。
- ``nfss_fam_declare`` (Arm C): ``Font family `E+F' unknown`` →
  ``\DeclareFontFamily{E}{F}{}`` (空 family 合法, fd 同款; E 已声明是
  本签成立前提)。
"""

from pathlib import Path

from _fixloopkit import EngStub, mk_ctx, rs, rule

from texlate.compile.fixloop.builtins import (
    nfss_cmd_enc_polyfill,
    nfss_enc_scheme_relax,
    nfss_fam_declare,
)
from texlate.compile.logparse import parse_text


def _params() -> dict:
    return {"exts": (".tex", ".sty", ".cls")}


_DOC = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"


# ------------------------------------------------------- nfss_cmd_enc_polyfill


def test_cmd_polyfill_textprime_tu(tmp_path: Path) -> None:
    """0712.1142 形: PU-declared ``\\textprime`` TU 下补 ``\\ensuremath{'}`` 体。"""
    (tmp_path / "main.tex").write_text(_DOC, encoding="utf-8")
    ctx = mk_ctx(
        tmp_path,
        err_head="LaTeX Error: Command \\textprime unavailable in encoding TU.",
    )
    ok, note = nfss_cmd_enc_polyfill(ctx, EngStub(), "textprime", _params())
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\DeclareTextCommand{\\textprime}{TU}{\\ensuremath{'}}" in t
    # 注入点在 docclass 之后、begin{document} 之前
    assert t.index("DeclareTextCommand") < t.index("\\begin{document}")


def test_cmd_polyfill_enc_from_err_head(tmp_path: Path) -> None:
    """实报 enc 从 err_head 提取 —— 非 TU 名按实报声明。"""
    (tmp_path / "main.tex").write_text(_DOC, encoding="utf-8")
    ctx = mk_ctx(
        tmp_path,
        err_head="LaTeX Error: Command \\textdprime unavailable in encoding PD1.",
    )
    ok, note = nfss_cmd_enc_polyfill(ctx, EngStub(), "textdprime", _params())
    assert ok, note
    assert "{PD1}" in (tmp_path / "main.tex").read_text()


def test_cmd_polyfill_unknown_cs_declines(tmp_path: Path) -> None:
    """体表外 cs → decline, 不猜字形。"""
    (tmp_path / "main.tex").write_text(_DOC, encoding="utf-8")
    ok, note = nfss_cmd_enc_polyfill(
        ctx=mk_ctx(tmp_path), eng=EngStub(), payload="cyrrandom", params=_params()
    )
    assert not ok
    assert "no TU body-table entry" in note
    assert (tmp_path / "main.tex").read_text() == _DOC


def test_cmd_polyfill_idempotent(tmp_path: Path) -> None:
    """二次点火: 声明已在 → decline 不叠写。"""
    (tmp_path / "main.tex").write_text(_DOC, encoding="utf-8")
    ctx = mk_ctx(tmp_path)
    assert nfss_cmd_enc_polyfill(ctx, EngStub(), "textprime", _params())[0]
    ok, note = nfss_cmd_enc_polyfill(ctx, EngStub(), "textprime", _params())
    assert not ok
    assert "already present" in note


# ------------------------------------------------------- nfss_enc_scheme_relax

_T2A_SRC = (
    "\\documentclass{article}\n"
    "\\def\\easycyrsymbol#1{{\\usefont{T2A}{\\rmdefault}{m}{n}#1}}\n"
    "\\newcommand{\\Zhe}{\\easycyrsymbol{\\CYRZH}}\n"
    "\\begin{document}\n\\Zhe\n\\end{document}\n"
)


def test_scheme_relax_t2a_usefont(tmp_path: Path) -> None:
    """2609.20339 形: ``\\usefont{T2A}``→TU + ``\\CYRZH`` polyfill 落地。"""
    (tmp_path / "main.tex").write_text(_T2A_SRC, encoding="utf-8")
    ok, note = nfss_enc_scheme_relax(mk_ctx(tmp_path), EngStub(), "T2A", _params())
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usefont{TU}{\\rmdefault}{m}{n}" in t
    assert "T2A" not in t
    assert "\\providecommand{\\CYRZH}{Ж}" in t


def test_scheme_relax_fontencoding_site(tmp_path: Path) -> None:
    """``\\fontencoding{T2A}\\selectfont`` 站点同改 TU。"""
    src = (
        "\\documentclass{article}\n\\begin{document}\n"
        "{\\fontencoding{T2A}\\selectfont \\cyra}\n\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, note = nfss_enc_scheme_relax(mk_ctx(tmp_path), EngStub(), "T2A", _params())
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\fontencoding{TU}" in t
    assert "\\providecommand{\\cyra}{а}" in t


def test_scheme_relax_masked_site_untouched(tmp_path: Path) -> None:
    """注释内假站点不改写; 全文零活面 → decline。"""
    src = "% \\usefont{T2A}{\\rmdefault}{m}{n}\\CYRZH\nx\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, note = nfss_enc_scheme_relax(mk_ctx(tmp_path), EngStub(), "T2A", _params())
    assert not ok
    assert "no live" in note
    assert (tmp_path / "main.tex").read_text() == src


def test_scheme_relax_unknown_enc_rewrites_sites(tmp_path: Path) -> None:
    """表外 enc (无字形表): 活站点照改 TU, 残 cs 留下轮。"""
    src = "{\\fontencoding{XYZ}\\selectfont x}\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, note = nfss_enc_scheme_relax(mk_ctx(tmp_path), EngStub(), "XYZ", _params())
    assert ok, note
    assert "no glyph table" in note
    assert "\\fontencoding{TU}" in (tmp_path / "main.tex").read_text()


def test_scheme_relax_bad_payload_declines(tmp_path: Path) -> None:
    """非 enc 名 payload → decline。"""
    ok, note = nfss_enc_scheme_relax(
        mk_ctx(tmp_path), EngStub(), "t2aenc.def", _params()
    )
    assert not ok
    assert "not an encoding name" in note


# ------------------------------------------------------- nfss_fam_declare


def test_fam_declare_t1_ptm(tmp_path: Path) -> None:
    """2609.20539 形: ``\\DeclareFontFamily{T1}{ptm}{}`` docclass 后注入。"""
    (tmp_path / "main.tex").write_text(_DOC, encoding="utf-8")
    ok, note = nfss_fam_declare(mk_ctx(tmp_path), EngStub(), "T1+ptm", _params())
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\DeclareFontFamily{T1}{ptm}{}" in t
    assert t.index("DeclareFontFamily") < t.index("\\begin{document}")


def test_fam_declare_bad_payload_declines(tmp_path: Path) -> None:
    """非 ``E+F`` 形 payload → decline。"""
    ok, note = nfss_fam_declare(mk_ctx(tmp_path), EngStub(), "ptm", _params())
    assert not ok
    assert "not an E+F family pair" in note


def test_fam_declare_idempotent(tmp_path: Path) -> None:
    """二次点火: 声明已在 → decline。"""
    (tmp_path / "main.tex").write_text(_DOC, encoding="utf-8")
    ctx = mk_ctx(tmp_path)
    assert nfss_fam_declare(ctx, EngStub(), "T1+ptm", _params())[0]
    ok, note = nfss_fam_declare(ctx, EngStub(), "T1+ptm", _params())
    assert not ok
    assert "already present" in note


# ------------------------------------------------------- 规则注册钉


def test_nfss_rules_registered() -> None:
    """三臂同 cat nfss_enc + payload_required, ctx_suggests 签名分流。"""
    for rid, sig, fn in (
        ("nfss_cmd_enc_polyfill", "unavailable in encoding", "nfss_cmd_enc_polyfill"),
        ("nfss_enc_scheme_relax", "Encoding scheme", "nfss_enc_scheme_relax"),
        ("nfss_fam_declare", "Font family", "nfss_fam_declare"),
    ):
        r = rule(rid)
        assert r.when["category"] == "nfss_enc"
        assert r.when["payload_required"] is True
        assert sig in r.condition["ctx_suggests"]
        assert r.action["kind"] == "builtin_transform"
        assert r.action["function"] == fn


def test_nfss_taxonomy_classify() -> None:
    """三签实测形 → ``nfss_enc``, payload 各归其位 (file-line/bang 两形)。"""
    cases = [
        (
            "/w/main.tex:1740: LaTeX Error: Command \\textprime unavailable in encoding TU.\nl.1740 x\n",
            ("nfss_enc", "textprime"),
        ),
        (
            "! LaTeX Error: Encoding scheme `T2A' unknown.\nl.801 x\n",
            ("nfss_enc", "T2A"),
        ),
        (
            "/w/main.tex:377: LaTeX Error: Font family `T1+ptm' unknown.\nl.377 \\begin{document}\n",
            ("nfss_enc", "T1+ptm"),
        ),
    ]
    for log, want in cases:
        assert rs().taxonomy.classify(parse_text(log)) == want, log


def test_nfss_family_no_plus_not_captured() -> None:
    """``Font family `X' unknown`` 无 ``+`` 不捕 (payload 恒 E+F 形)。"""
    log = "! LaTeX Error: Font family `ptm' unknown.\nl.5 x\n"
    cat, _ = rs().taxonomy.classify(parse_text(log))
    assert cat != "nfss_enc"
