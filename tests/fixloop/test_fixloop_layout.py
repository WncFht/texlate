r"""97-layout 版面缺陷规则 —— warn_overfull/warn_float_big 伪类别驱动钉测。

qc_wanted 补票格 (e2e_real ``_QC_WANTED_MIN``) 进 fixloop 时编译
clean——无 '!' 错可分类, 版面 sig 的 log 面标记经 warnings 段升
``warn_*`` 伪类别驱动修复:

- ``overfull_hbox`` → ``warn_overfull`` → ``para_loosen``: preamble 尾注
  ``\emergencystretch``+``\tolerance`` (三遍排版真修复, 不设 ``\hfuzz``
  阈值遮掩);
- ``float_too_large`` → ``warn_float_big`` → ``float_h_demote`` 复用:
  [H] 超高非浮体盒降级 ``!``+placement 翻回真浮体 (runaway_output
  臂同机理不同驱动面)。
"""

from pathlib import Path

from _fixloopkit import CLEAN_LOG, MockEngine, make_proj, mk_ctx

from texlate.compile.fixloop import fixloop
from texlate.compile.fixloop.builtins.optfix import para_loosen

OVERFULL_LOG = (
    "This is XeTeX, Version 3\n"
    "Overfull \\hbox (12.345pt too wide) in paragraph at lines 42--43\n"
    "Overfull \\hbox (3.0pt too wide) in paragraph at lines 88--90\n"
    "Output written on main.pdf (1 page).\n"
)

FLOAT_BIG_LOG = (
    "This is XeTeX, Version 3\n"
    "LaTeX Warning: Float too large for page by 24.0pt on input line 55.\n"
    "Output written on main.pdf (1 page).\n"
)

H_FLOAT_MAIN = (
    "\\documentclass{article}\n"
    "\\usepackage{float}\n"
    "\\begin{document}\n"
    "\\begin{figure}[H]\n\\rule{10cm}{80cm}\n\\end{figure}\n"
    "tail\n\\end{document}\n"
)


def test_overfull_drives_para_loosen(tmp_path: Path) -> None:
    """Overfull \\hbox 无 '!' 错 → warn_overfull → preamble 尾注松化 → clean。"""
    eng = MockEngine(
        [
            {"log": OVERFULL_LOG, "pdf": True},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "warn_overfull"
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\emergencystretch=1.5em\\relax" in t
    assert "\\tolerance=2000\\relax" in t
    assert "\\hfuzz" not in t  # 阈值遮掩会吃掉 qc 证据面——永不做
    assert t.index("\\emergencystretch") < t.index("\\begin{document}")


def test_float_big_drives_h_demote(tmp_path: Path) -> None:
    """Float too large + [H] 站 → warn_float_big → [H]→[!htp] → clean。"""
    eng = MockEngine(
        [
            {"log": FLOAT_BIG_LOG, "pdf": True},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(make_proj(tmp_path, H_FLOAT_MAIN), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "warn_float_big"
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\begin{figure}[!htp]" in t


def test_float_big_no_h_site_declines(tmp_path: Path) -> None:
    """Float too large 但无 [H] 站 → builtin decline (非钉死形不担责)。"""
    eng = MockEngine([{"log": FLOAT_BIG_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["rounds"][0]["category"] == "warn_float_big"
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "[!htp]" not in t  # 无 [H] 站零改写


def test_para_loosen_idempotent(tmp_path: Path) -> None:
    """二次命中幂等——已注入报 applied (修复环收敛不叠注)。"""
    ctx = mk_ctx(tmp_path)
    make_proj(tmp_path)
    ok, _ = para_loosen(ctx, None, None, {})
    assert ok is True
    ok, note = para_loosen(ctx, None, None, {})
    assert ok is True
    assert "already present" in note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert t.count("\\emergencystretch") == 1


def test_para_loosen_no_main_declines(tmp_path: Path) -> None:
    """无主文件 → decline。"""
    ctx = mk_ctx(tmp_path, main_rel=None)
    ok, note = para_loosen(ctx, None, None, {})
    assert ok is False
    assert "no main file" in note
