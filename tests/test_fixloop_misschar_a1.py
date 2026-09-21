"""misscharA1 钉 —— failmine8 census A1 桶 char_table 字面补表 (2026-09-20)。

14 cps / 12 cells 分四类经 ``missing_char_fix`` 真臂路径 (落地 ruleset
params) 验替换:

- 双线大写+∂ 落 lmmono8/9 → ``\\ensuremath{\\mathbb{X}}``/``\\partial``
  (2608.09867/2609.19352/2609.20805; ``\\mathbb`` 依赖 amssymb 同 dblz 先例);
- 数学斜体字母落 LinLibertine 文本字体 → kernel ``\\mu``/``\\theta``
  (2609.20309/2510.02854);
- 符号/标点 ⪪―‑≥→ 各落 OTF/T1 字体 → ``<``/``---``/``-``/``\\geq``/
  ``\\rightarrow`` (2609.19583/2504.14870/2503.23278/2609.20425/2501.19393);
- Վ 亚美尼亚大写 → ``V`` (1109.1915); ─│ 制表符 → ``-``/``|``
  ascii-art 语义还原 (2408.07394/nlin/0103011)。
"""

from pathlib import Path

from _fixloopkit import mk_ctx, rule

from texlate.compile.fixloop.builtins import missing_char_fix


def _missing_char_fix_params() -> dict:
    """落地 ruleset 里 ``missing_char_fix`` 的真 params (测 yaml 条目本身)。"""
    return rule("missing_char_fix").action.get("params") or {}


def _fix(tmp_path: Path, main: str, log: str) -> tuple[bool, str]:
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    (tmp_path / "main.log").write_text(log, encoding="utf-8")
    return missing_char_fix(mk_ctx(tmp_path), None, None, _missing_char_fix_params())


def test_char_table_a1_entries_registered() -> None:
    """14 条新条目按 id 在落地 char_table 在册。"""
    table = {
        e["id"] for e in _missing_char_fix_params()["char_table"] if isinstance(e, dict)
    }
    want = {
        "dblr",
        "dblq",
        "dblc",
        "partial",
        "itmu",
        "ittheta",
        "smaller_than",
        "horizbar",
        "nbhyphen",
        "geq",
        "rarrow",
        "armenian_vew",
        "boxdraw_2500",
        "boxdraw_2502",
    }
    assert want <= table


def test_blackboard_partial_lmmono(tmp_path: Path) -> None:
    """ℝℚℂ∂ 落 lmmono → \\mathbb 族 + \\partial (lean/literate 签名)。"""
    main = (
        "\\documentclass{article}\n\\usepackage{amssymb}\n"
        "\\begin{document}\nℝℚℂ∂ x\n\\end{document}\n"
    )
    log = (
        "Missing character: There is no ℚ (U+211A) in font [lmmono9-regular]:!\n"
        "Missing character: There is no ℝ (U+211D) in font [lmmono9-regular]:!\n"
        "Missing character: There is no ℂ (U+2102) in font [lmmono9-regular]:!\n"
        "Missing character: There is no ∂ (U+2202) in font [lmmono8-regular]:!\n"
    )
    ok, note = _fix(tmp_path, main, log)
    assert ok is True, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ensuremath{\\mathbb{R}}\\ensuremath{\\mathbb{Q}}" in t
    assert "\\ensuremath{\\mathbb{C}}\\ensuremath{\\partial}" in t


def test_math_alnum_in_text_font(tmp_path: Path) -> None:
    """𝜇𝜃 数学斜体落 LinLibertine 文本字体 → kernel \\mu/\\theta。"""
    main = (
        "\\documentclass{article}\n\\begin{document}\n"
        "parameter 𝜇 and angle 𝜃 end\n\\end{document}\n"
    )
    log = (
        "Missing character: There is no 𝜇 (U+1D707) in font "
        "[LinLibertine_RB.otf]/OT:script=latn;language=dflt;+tnum;+lnum;mapping=tex-text;!\n"
        "Missing character: There is no 𝜃 (U+1D703) in font "
        "[LinLibertine_R.otf]/OT:script=latn;language=dflt;+tnum;+lnum;mapping=tex-text;!\n"
    )
    ok, note = _fix(tmp_path, main, log)
    assert ok is True, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "parameter \\ensuremath{\\mu} and angle \\ensuremath{\\theta} end" in t


def test_symbol_punct_group(tmp_path: Path) -> None:
    """⪪―‑≥→ 五枚 → < --- - \\geq \\rightarrow (跨 OTF/T1 字体)。"""
    main = (
        "\\documentclass{article}\n\\begin{document}\n"
        "a⪪b ―quote third‑party x≥y V2→V3\n\\end{document}\n"
    )
    log = (
        "Missing character: There is no ⪪ (U+2AAA) in font "
        "[LinLibertine_R.otf]/OT:script=latn;language=dflt;+tnum;+lnum;mapping=tex-text;!\n"
        "Missing character: There is no ― (U+2015) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n"
        "Missing character: There is no ‑ (U+2011) in font "
        "[Inconsolatazi4-Regular.otf]/OT:script=latn;language=dflt;+ss03;!\n"
        "Missing character: There is no ≥ (U+2265) in font [lmmono8-regular]:!\n"
        'Missing character: There is no → ("2192) in font t1-stixgeneral-bold!\n'
    )
    ok, note = _fix(tmp_path, main, log)
    assert ok is True, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "a\\ensuremath{<}b" in t
    assert "\\mbox{---}quote" in t
    assert "third\\mbox{-}party" in t
    assert "x\\ensuremath{\\geq}y" in t
    assert "V2\\ensuremath{\\rightarrow}V3" in t


def test_armenian_and_boxdraw(tmp_path: Path) -> None:
    """Վ → V (亚美尼亚大写音写); ─│ → - | (ascii-art 语义还原)。"""
    main = (
        "\\documentclass{article}\n\\begin{document}\n"
        "name Վ. author and a─b│c\n\\end{document}\n"
    )
    log = (
        "Missing character: There is no Վ (U+054E) in font "
        "[lmroman9-regular]:mapping=tex-text;!\n"
        "Missing character: There is no ─ (U+2500) in font "
        "[lmroman7-regular]:mapping=tex-text;!\n"
        "Missing character: There is no │ (U+2502) in font "
        "[lmroman10-italic]:mapping=tex-text;!\n"
    )
    ok, note = _fix(tmp_path, main, log)
    assert ok is True, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "name V. author" in t
    assert "a-b|c" in t


def test_boxdraw_verbatim_masked_untouched(tmp_path: Path) -> None:
    """遮盖面守卫: ─│ 在 verbatim 体内不被替换 (2408.07394 Verbatim 签名)。"""
    main = (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{verbatim}\n───│││\n\\end{verbatim}\n"
        "\\end{document}\n"
    )
    log = (
        "Missing character: There is no ─ (U+2500) in font "
        "[lmroman7-regular]:mapping=tex-text;!\n"
        "Missing character: There is no │ (U+2502) in font "
        "[lmroman7-regular]:mapping=tex-text;!\n"
    )
    ok, _note = _fix(tmp_path, main, log)
    assert ok is False  # 命中全在遮盖域 → applied=False 落穿, 不谎报
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "───│││" in t  # verbatim 体原样
