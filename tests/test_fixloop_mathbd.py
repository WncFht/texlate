r"""mathbd 车道 (2026-09-20): singles3 bundle A+B 钉。

Bundle A —— zh 数学-文本边界三臂 (75-syntax.yaml):
- ``soul_cs_mbox`` (order 102): soul 族 ``\hl{\model}`` 单-cs 实参 →
  ``\mbox{\cs}`` (soul_cjk_mbox 字面 CJK 闸的姊妹臂; 2210.03629 实证)。
- ``math_alphabet_209_revert`` (order 190): ``\math<xx>{`` 全局回退
  ``{\<xx> `` —— latex209 升级把文本域 ``{\it}`` 组误改 ``\mathit{`` 的
  回退 (q-alg/9703043 实证; 内核 \DeclareOldFontCommand 双域自适应)。
- ``bm_symbfit_alias`` (order 191): ``Improper alphabetic constant`` 且
  offender 为 unicode-math ``\mit<cs>`` → ``\begin{document}`` 前注
  ``\bm``/``\boldsymbol``→``\symbfit``/``\symbf`` 双别名 (2609.20524
  实证; ``\mit`` 门与 pdfstring_cs_disarm(193) 的 ``\times`` 族分签)。

Bundle B —— ``normalize._strip_lead_junk`` (cond-mat/0003309):
Mac Finder-info/资源叉二进制前缀剥除, 行首 ``\documentstyle``/
``\documentclass``/``%&`` 锚点定界, 前缀含 NUL 才算垃圾 (许可证头/
注释块是纯文本, 不剥)。
"""

from pathlib import Path

from _fixloopkit import EngStub, apply, mk_ctx, rule
from conftest import _write

from texlate.compile.fixloop import actions
from texlate.compile.normalize import _strip_lead_junk, normalize_project


def _apply(rid: str, tmp_path: Path, err_head: str = "") -> tuple[bool, str]:
    """钉规则动作直驱——kit ``apply`` 收口 (eng 缺省 ``EngStub``, ErrReport 内置)。"""
    return apply(rid, mk_ctx(tmp_path, err_head=err_head), None)


def _cond(rid: str, tmp_path: Path, err_head: str = "") -> tuple[bool, str]:
    """``actions._cond_ok`` 直驱——SLF001 豁免一处收口。"""
    r = rule(rid)
    return actions._cond_ok(  # noqa: SLF001
        r.condition, r, mk_ctx(tmp_path, err_head=err_head), EngStub(), None
    )


# ── Bundle A: soul_cs_mbox ──────────────────────────────────────────


def test_mathbd_rules_registered() -> None:
    soul = rule("soul_cs_mbox")
    assert soul.phase == "loop"
    assert soul.order == 102  # noqa: PLR2004 - schema 断言值
    assert soul.when == {"category": "soul_err"}
    assert soul.action["kind"] == "regex_rewrite"

    rev = rule("math_alphabet_209_revert")
    assert rev.order == 190  # noqa: PLR2004
    assert rev.when == {"category": "syntax"}

    bm = rule("bm_symbfit_alias")
    assert bm.order == 191  # noqa: PLR2004
    assert bm.when == {"category": "syntax"}
    # 须在 pdfstring_cs_disarm(193) 之前收 \mit<cs> offender 形
    assert bm.order < rule("pdfstring_cs_disarm").order


def test_soul_cs_mbox_wraps_single_cs_arg(tmp_path: Path) -> None:
    _write(
        tmp_path, "main.tex", "\\usepackage{soul}\n\\hl{\\model} 与 \\so{ \\reason }\n"
    )
    applied, _ = _apply("soul_cs_mbox", tmp_path)
    assert applied
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\hl{\\mbox{\\model}}" in text
    assert "\\so{\\mbox{\\reason}}" in text


def test_soul_cs_mbox_declines_non_single_cs(tmp_path: Path) -> None:
    """多 token 实参与字面文本不命中 → applied=False 不烧轮次。"""
    body = "\\hl{\\model and text}\n\\hl{plain words}\n"
    _write(tmp_path, "main.tex", body)
    applied, _ = _apply("soul_cs_mbox", tmp_path)
    assert not applied
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == body


def test_soul_cs_mbox_idempotent(tmp_path: Path) -> None:
    """已裹站点实参为 \\mbox{..} 非单 cs → 第二轮 decline。"""
    _write(tmp_path, "main.tex", "\\hl{\\mbox{\\model}}\n")
    applied, _ = _apply("soul_cs_mbox", tmp_path)
    assert not applied


# ── Bundle A: math_alphabet_209_revert ──────────────────────────────


def test_math_revert_cond_gate(tmp_path: Path) -> None:
    ok, _ = _cond(
        "math_alphabet_209_revert",
        tmp_path,
        "main.tex:724: LaTeX Error: \\mathit allowed only in math mode",
    )
    assert ok
    # 五件套外 alphabet (mathbb/mathfrak) 不命中 → decline
    ok, _ = _cond(
        "math_alphabet_209_revert",
        tmp_path,
        "LaTeX Error: \\mathbb allowed only in math mode",
    )
    assert not ok


def test_math_revert_rewrites_five_alphabets(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "main.tex",
        "\\mathit{ Ann. of Phys. 70} $\\mathbf{x}_i$ \\mathrm{d}\\mathsf{S}\\mathtt{T} \\mathbb{R}\n",
    )
    applied, _ = _apply("math_alphabet_209_revert", tmp_path)
    assert applied
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    for cs in ("it", "bf", "rm", "sf", "tt"):
        assert f"{{\\{cs} " in text
    assert "\\math" not in text.replace("\\mathbb", "")
    assert "\\mathbb{R}" in text  # 五件套外不动


def test_math_revert_masked_comment_untouched(tmp_path: Path) -> None:
    """masked 面: 注释内字面 \\mathit{ 不改写。"""
    body = "% \\mathit{example}\n\\mathit{real}\n"
    _write(tmp_path, "main.tex", body)
    applied, _ = _apply("math_alphabet_209_revert", tmp_path)
    assert applied
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "% \\mathit{example}" in text
    assert "{\\it real}" in text


# ── Bundle A: bm_symbfit_alias ──────────────────────────────────────

_IMPROPER_MIT = (
    "main.tex:18: Improper alphabetic constant.\n"
    "<to be read again>\n"
    "                   \\mitxi\n"
    "l.18 $\\boldsymbol{\\xi}$"
)


def test_bm_alias_cond_gate(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n$\\boldsymbol{\\xi}$\n\\begin{document}\n",
    )
    ok, _ = _cond("bm_symbfit_alias", tmp_path, _IMPROPER_MIT)
    assert ok


def test_bm_alias_declines_pdfstring_offender(tmp_path: Path) -> None:
    """offender 非 \\mit<cs> (pdfstring \\times 族) → 让位 pdfstring_cs_disarm。"""
    _write(tmp_path, "main.tex", "$\\boldsymbol{\\xi}$\n\\begin{document}\n")
    head = (
        "Improper alphabetic constant.\n<to be read again>\n  \\times\n"
        "l.291 \\maketitle"
    )
    ok, _ = _cond("bm_symbfit_alias", tmp_path, head)
    assert not ok


def test_bm_alias_declines_no_bm_usage(tmp_path: Path) -> None:
    """源面无 \\bm/\\boldsymbol 使用 → decline (\\mit 肇事非 bm 语境)。"""
    _write(tmp_path, "main.tex", "\\documentclass{article}\n\\begin{document}\nx\n")
    ok, _ = _cond("bm_symbfit_alias", tmp_path, _IMPROPER_MIT)
    assert not ok


def test_bm_alias_injects_before_begindoc(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\usepackage{bm}\n% \\begin{document} 注释行\n"
        "\\begin{document}\n$\\bm{\\mu}$\n\\end{document}\n",
    )
    applied, _ = _apply("bm_symbfit_alias", tmp_path, _IMPROPER_MIT)
    assert applied
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\let\\bm\\symbfit" in text
    assert "\\let\\boldsymbol\\symbfit" in text
    assert "\\let\\bm\\symbf" in text
    assert "\\let\\boldsymbol\\symbf" in text
    # 注入落真 \\begin{document} 前 (masked: 注释行不被当锚点)
    assert text.index("\\ifdefined\\symbfit") < text.index("\\begin{document}\n$\\bm")
    assert text.index("% \\begin{document} 注释行") < text.index("\\ifdefined\\symbfit")


# ── Bundle B: _strip_lead_junk ──────────────────────────────────────


def test_lead_junk_stripped_at_anchor() -> None:
    junk = b"\x00\tpaper.tex" + b"\x00" * 60 + b"TEXT*TEX\x01\x00mBIN" + b"\x00" * 8
    blob = junk + b"\n\\documentstyle[aps,twocolumn]{revtex}\n\\begin{document}\n"
    out = _strip_lead_junk(blob)
    assert out.startswith(b"\\documentstyle")
    assert b"\x00" not in out[:100]


def test_lead_junk_stripped_at_fmt_anchor() -> None:
    """``%&`` fmt 锚点臂: 含 NUL 垃圾前缀剥至 ``%&`` 行。"""
    assert (
        _strip_lead_junk(b"\x00junk\x00\n%&latex\n\\documentclass{article}\n")
        == b"%&latex\n\\documentclass{article}\n"
    )


def test_lead_junk_text_prefix_kept() -> None:
    """锚点前纯文本 (许可证头/注释块) 非垃圾 → 不剥。"""
    blob = b"% license header\ntext before\n\\documentclass{article}\n"
    assert _strip_lead_junk(blob) is blob


def test_lead_junk_anchor_at_zero_kept() -> None:
    assert (
        _strip_lead_junk(b"\\documentclass{article}\nx\n")
        == b"\\documentclass{article}\nx\n"
    )
    assert _strip_lead_junk(b"%&latex\n\\documentclass{article}\nx\n") == (
        b"%&latex\n\\documentclass{article}\nx\n"
    )


def test_lead_junk_no_anchor_or_out_of_window() -> None:
    blob = b"\x00\x01" * 100 + b"no anchor here\n"
    assert _strip_lead_junk(blob) is blob
    far = b"\x00" * 4100 + b"\n\\documentclass{article}\n"
    assert _strip_lead_junk(far) is far  # 锚点出 4KiB 窗不剥


def test_lead_junk_normalize_project_e2e(tmp_path: Path) -> None:
    junk = b"\x00\tpaper.tex" + b"\x00" * 60 + b"TEXT*TEXmBIN" + b"\x00" * 8
    body = junk + b"\n\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    (tmp_path / "paper.tex").write_bytes(body)
    stats = normalize_project(tmp_path, "xelatex", main="paper.tex")
    assert stats["lead_junk_stripped"] == ["paper.tex"]
    out = (tmp_path / "paper.tex").read_bytes()
    assert b"TEXT*TEX" not in out
    assert b"\\documentclass{article}" in out
    assert b"\\begin{document}" in out
