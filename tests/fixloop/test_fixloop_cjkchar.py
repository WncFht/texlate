r"""cjkchar 车道 —— ``Package CJK Error: Invalid character code`` 归 invalid_char。

singlesweep cjk-pkg-invalid-char 2 格 (1607.00157/2601.07372, base 臂;
1206.0266 tectonic 同句 ``! `` 形): CJKutf8/CJK 包解码面自报非 UTF-8
字节硬错, 措辞非内核 ``Text line contains an invalid character`` ——
旧 head 段恒归 ``other|None`` 无路由。归 ``invalid_char`` 后
``invalid_char_recode``(97) 接续: 非 UTF-8 源格转码即解 (1607.00157
.tex+.cls iconv decode-fail 实证), 全 UTF-8 格 recode 自 decline。
"""

from functools import lru_cache
from pathlib import Path

import regex

from texlate.compile.fixloop import Ruleset, load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.builtins.misc import cjk_env_relax
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.fixloop.ruleset import Rule
from texlate.compile.logparse import parse_text


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    """ruleset 首用时加载——收集期不 IO。"""
    return load_ruleset()


def _rule(rid: str) -> Rule:
    return next(r for r in _rs().rules if r.id == rid)


class _Eng:
    name = "xelatex"


def _ctx(tmp_path: Path) -> LoopCtx:
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ctx.err_head = "main.tex:1: Package CJK Error: Invalid character code."
    return ctx


# ── 1607.00157 形：file-line 前缀 + CJK 包错 (xelatex base 臂实录) ──
_CJK_FILELINE_LOG = (
    "This is XeTeX, Version 3.141592653-2.6-0.999996 (TeX Live 2025)\n"
    "/work/1607.00157/14C-clustering-r2.tex:58: Package CJK Error: "
    "Invalid character code.\n"
    "l.58 \\begin{CJK*}{UTF8}{gbsn}\n"
)

# ── 1206.0266 形：``! `` 顶行 (tectonic 实录) ──
_CJK_BANG_LOG = (
    "This is Tectonic\n"
    "! Package CJK Error: Invalid character code.\n"
    "l.74 \\begin{CJK}{UTF8}{}\n"
)

# ── 2601.07372 形：file-line 形 main.tex:222 (xelatex base 臂实录) ──
_CJK_MAIN_LOG = (
    "This is XeTeX\n"
    "/work/2601.07372/main.tex:222: Package CJK Error: Invalid "
    "character code.\n"
    "l.222 ...gbsn}\n"
)

# ── 内核原签守恒：Text line contains an invalid character 仍归同类 ──
_KERNEL_INVALID_LOG = (
    "This is XeTeX\n"
    "! Text line contains an invalid character.\n"
    "l.12 \\begin{document}\n"
)


def test_cjk_fileline_classifies_invalid_char() -> None:
    """1607.00157: file-line 形 → ``invalid_char`` (无 payload)。"""
    assert _rs().taxonomy.classify(parse_text(_CJK_FILELINE_LOG)) == (
        "invalid_char",
        None,
    )


def test_cjk_bang_classifies_invalid_char() -> None:
    """1206.0266: ``! `` 形 → ``invalid_char``。"""
    assert _rs().taxonomy.classify(parse_text(_CJK_BANG_LOG)) == (
        "invalid_char",
        None,
    )


def test_cjk_main_line222_classifies_invalid_char() -> None:
    """2601.07372: main.tex:222 file-line 形 → ``invalid_char``。"""
    assert _rs().taxonomy.classify(parse_text(_CJK_MAIN_LOG)) == (
        "invalid_char",
        None,
    )


def test_kernel_invalid_char_unchanged() -> None:
    """内核 ``Text line contains...`` 原签逐字节守恒 —— 拓宽不漂移。"""
    assert _rs().taxonomy.classify(parse_text(_KERNEL_INVALID_LOG)) == (
        "invalid_char",
        None,
    )


def test_other_cjk_errors_not_captured() -> None:
    """收紧面：其他 ``Package CJK Error`` (非 Invalid character code) 不误签。"""
    log = (
        "! Package CJK Error: You can't use \\CJKchar outside a CJK "
        "environment.\n"
        "l.5 x\n"
    )
    cat, _ = _rs().taxonomy.classify(parse_text(log))
    assert cat != "invalid_char"


# ── cjk_env_relax 臂 (order 96.5, invalid_char_recode 前的 CJK 分流) ──


def test_cjk_env_relax_rule_shape() -> None:
    """``when: invalid_char`` + ``source_contains`` 分流门 + recode 前位。"""
    rule = _rule("cjk_env_relax")
    assert rule.when == {"category": "invalid_char"}
    assert rule.order < _rule("invalid_char_recode").order
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "cjk_env_relax"
    assert TRANSFORM_FNS["cjk_env_relax"] is cjk_env_relax


def test_source_contains_gate() -> None:
    """CJK 标记稿过门，纯字节损坏稿 (无 CJK) 拒门 → 落 97 recode。"""
    pat = _rule("cjk_env_relax").condition["source_contains"]
    assert regex.search(pat, "\\usepackage{CJKutf8}\n\\begin{document}\n")
    assert regex.search(pat, "\\usepackage{CJK,upgreek}\n\\begin{CJK*}{GB}{gbsn}\n")
    assert regex.search(pat, "\\begin{CJK}{UTF8}{}\n")
    assert not regex.search(pat, "\\documentclass{article}\n\\begin{document}\nx\n")


def test_cjk_env_relax_utf8(tmp_path: Path) -> None:
    """2601.07372 形 (UTF-8 ``CJKutf8``): env→组 + xeCJK 换装，拉丁扩展字符保真。"""
    src = (
        "\\documentclass{article}\n\\usepackage{CJKutf8}\n"
        "\\begin{document}\n\\begin{CJK*}{UTF8}{gbsn}\n"
        "'é','è','ę','ě','í','ī' 汉字\n\\end{CJK*}\n\\end{document}\n"
    )
    main = tmp_path / "main.tex"
    main.write_text(src, encoding="utf-8")
    ok, note = cjk_env_relax(_ctx(tmp_path), _Eng(), None, {})
    assert ok, note
    t = main.read_text(encoding="utf-8")
    assert "\\usepackage{xeCJK}" in t
    assert "\\setCJKmainfont{FandolSong" in t
    assert "CJKutf8" not in t
    assert "\\begin{CJK*}" not in t
    assert "\\end{CJK*}" not in t
    assert "'é','è','ę','ě','í','ī' 汉字" in t  # env 内字符保真


def test_cjk_env_relax_gbk_transcode(tmp_path: Path) -> None:
    """1607.00157 形 (GBK 源 ``{CJK,upgreek}`` + ``{GB}{gbsn}``): 字节级
    ``decode_tex`` 进档，汉字不读成 FFFD, 逗号包表外科剥离 (upgreek 留)。"""
    src = (
        "\\documentclass{article}\n\\usepackage{CJK,upgreek,fancyhdr}\n"
        "\\begin{document}\n\\begin{CJK*}{GB}{gbsn}\n"
        "碳十四聚类分析结果图表\n\\end{CJK*}\n\\end{document}\n"
    )
    main = tmp_path / "main.tex"
    main.write_bytes(src.encode("gbk"))
    ok, note = cjk_env_relax(_ctx(tmp_path), _Eng(), None, {})
    assert ok, note
    t = main.read_text(encoding="utf-8")  # 写回即 UTF-8
    assert "碳十四聚类分析结果图表" in t  # GBK 汉字保真 (非 FFFD)
    assert "\ufffd" not in t
    assert "\\usepackage{upgreek,fancyhdr}" in t  # 逗号表外科剥离
    assert "\\usepackage{xeCJK}" in t


def test_cjk_env_relax_declines_plain(tmp_path: Path) -> None:
    """无 CJK 标记 → decline (由 97 recode 接续纯字节损坏面)。"""
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _ = cjk_env_relax(_ctx(tmp_path), _Eng(), None, {})
    assert not ok
