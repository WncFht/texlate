r"""restore_support_from_src 内建 —— 被翻译写脏的 support 文件从 baseline 复原。

prose gate (e2e._scan_tree) 前向挡机制件进翻译集; 本 builtin 收残案:
baseline 同名件判 support (``.rtx.tex``/``.code.tex`` 名闸或 file_has_prose
False) ∧ 字节有偏 ∧ CJK 计数超 baseline ∧ 无 ``% texlate``/``% fixloop``
自有标记 → 逐字节复原。``baseline_dir`` 缺失/非目录 → False fail-safe。
"""

from pathlib import Path

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop.builtins import restore_support_from_src
from texlate.compile.fixloop.engine import LoopCtx

#: 与 test_latex_prose 同 fixture: 真 parse 后零散文的机制件。
_MACH = "\\psset{unit=1cm}\npstverb moveto neg def set newpath lineto stroke\n"
#: 真 parse 后出散文 chunk 的内容件 (test_translate_tree_real_content 同句)。
_PROSE = (
    "The results of this paper show that the proposed method is "
    "effective and that the theory holds.\n"
)


def _ctx(wdir: Path) -> LoopCtx:
    return LoopCtx(wdir=wdir, engine_name="xelatex", main_rel="main.tex", runner=None)


def _trees(root: Path) -> tuple[Path, Path]:
    """wdir + baseline 双子树 —— baseline 必须在 wdir 外，否则被当工作件扫。"""
    work, base = root / "work", root / "baseline"
    work.mkdir()
    base.mkdir()
    return work, base


def _run(work: Path, base: Path) -> tuple[bool, str]:
    return restore_support_from_src(_ctx(work), None, None, {"baseline_dir": str(base)})


def test_restores_corrupted_support(tmp_path: Path) -> None:
    """机制件 +CJK 注入 → 逐字节复原 baseline, note 记名。"""
    work, base = _trees(tmp_path)
    (base / "pssupport.tex").write_text(_MACH, encoding="utf-8")
    (work / "pssupport.tex").write_text(
        _MACH + "这一段是被误翻注入的中文。\n", encoding="utf-8"
    )
    ok, note = _run(work, base)
    assert ok
    assert "pssupport.tex" in note
    assert (work / "pssupport.tex").read_bytes() == _MACH.encode()


def test_restores_nested_support(tmp_path: Path) -> None:
    """嵌套 support 件 → 复原 + note 记 posix 相对路径 ``sub/defs.tex``。"""
    work, base = _trees(tmp_path)
    (work / "sub").mkdir()
    (base / "sub").mkdir()
    (base / "sub" / "defs.tex").write_text(_MACH, encoding="utf-8")
    (work / "sub" / "defs.tex").write_text(_MACH + "中文注入\n", encoding="utf-8")
    ok, note = _run(work, base)
    assert ok
    assert "sub/defs.tex" in note
    assert (work / "sub" / "defs.tex").read_bytes() == _MACH.encode()


def test_content_file_not_restored(tmp_path: Path) -> None:
    """散文 baseline +CJK → 内容件非 support, 不回滚。"""
    work, base = _trees(tmp_path)
    (base / "body.tex").write_text(_PROSE, encoding="utf-8")
    corrupted = _PROSE + "中文内容译写\n"
    (work / "body.tex").write_text(corrupted, encoding="utf-8")
    ok, note = _run(work, base)
    assert not ok
    assert "body.tex" not in note
    assert (work / "body.tex").read_text(encoding="utf-8") == corrupted


def test_identical_bytes_skipped(tmp_path: Path) -> None:
    """工作件与 baseline 字节一致 → 不动，False。"""
    work, base = _trees(tmp_path)
    (base / "pssupport.tex").write_text(_MACH, encoding="utf-8")
    (work / "pssupport.tex").write_text(_MACH, encoding="utf-8")
    ok, note = _run(work, base)
    assert not ok
    assert "no corrupted" in note


def test_ascii_only_divergence_skipped(tmp_path: Path) -> None:
    """字节有偏但零 CJK 增量 → 非翻译污染，不回滚。"""
    work, base = _trees(tmp_path)
    (base / "pssupport.tex").write_text(_MACH, encoding="utf-8")
    diverged = _MACH + "\\psset{unit=2cm}\n"
    (work / "pssupport.tex").write_text(diverged, encoding="utf-8")
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "pssupport.tex").read_text(encoding="utf-8") == diverged


def test_own_markers_not_restored(tmp_path: Path) -> None:
    """``% texlate``/``% fixloop`` 自有标记件 → 有意改写，带 CJK 也不回滚。"""
    work, base = _trees(tmp_path)
    (base / "a.tex").write_text(_MACH, encoding="utf-8")
    (base / "b.tex").write_text(_MACH, encoding="utf-8")
    (work / "a.tex").write_text(
        "% texlate: CJK support\n" + _MACH + "中文\n", encoding="utf-8"
    )
    (work / "b.tex").write_text(
        "% fixloop: stripped \\usepackage{inputenc}\n" + _MACH + "中文\n",
        encoding="utf-8",
    )
    ok, _note = _run(work, base)
    assert not ok
    assert "中文" in (work / "a.tex").read_text(encoding="utf-8")
    assert "中文" in (work / "b.tex").read_text(encoding="utf-8")


def test_missing_baseline_param_failsafe(tmp_path: Path) -> None:
    """无 ``baseline_dir`` param → False 不抛。"""
    ok, note = restore_support_from_src(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "baseline_dir" in note


def test_nonexistent_baseline_dir_failsafe(tmp_path: Path) -> None:
    """``baseline_dir`` 指不存在目录 → False 不抛。"""
    ok, note = restore_support_from_src(
        _ctx(tmp_path), None, None, {"baseline_dir": str(tmp_path / "nope")}
    )
    assert not ok
    assert "not a directory" in note


def test_code_tex_name_gate_restored(tmp_path: Path) -> None:
    """``.code.tex``/``.rtx.tex`` 名闸先行 —— baseline 带散文也照回滚。"""
    work, base = _trees(tmp_path)
    (base / "tikzlibraryzz.code.tex").write_text(_PROSE, encoding="utf-8")
    (base / "rtxdump.rtx.tex").write_text(_PROSE, encoding="utf-8")
    (work / "tikzlibraryzz.code.tex").write_text(_PROSE + "中文\n", encoding="utf-8")
    (work / "rtxdump.rtx.tex").write_text(_PROSE + "中文\n", encoding="utf-8")
    ok, note = _run(work, base)
    assert ok
    assert "tikzlibraryzz.code.tex" in note
    assert "rtxdump.rtx.tex" in note
    assert (work / "tikzlibraryzz.code.tex").read_bytes() == _PROSE.encode()


def test_baseline_with_legit_cjk(tmp_path: Path) -> None:
    """baseline 自带 CJK 按计数差判 —— 增量仍恢复，同量不恢复。"""
    work, base = _trees(tmp_path)
    (base / "a.tex").write_text("% 中文注\n" + _MACH, encoding="utf-8")
    (work / "a.tex").write_text(
        "% 中文注\n" + _MACH + "又注入更多中文\n", encoding="utf-8"
    )
    (base / "b.tex").write_text("% 中文注\n" + _MACH, encoding="utf-8")
    same_cjk = "% 中文注\n" + _MACH + "\\psset{unit=2cm}\n"
    (work / "b.tex").write_text(same_cjk, encoding="utf-8")
    ok, note = _run(work, base)
    assert ok
    assert "a.tex" in note
    assert "b.tex" not in note
    assert (work / "b.tex").read_text(encoding="utf-8") == same_cjk


def test_no_baseline_counterpart_skipped(tmp_path: Path) -> None:
    """baseline 无同名件 → 无可对照，不动。"""
    work, base = _trees(tmp_path)
    (work / "orphan.tex").write_text(_MACH + "中文\n", encoding="utf-8")
    ok, _note = _run(work, base)
    assert not ok
    assert "中文" in (work / "orphan.tex").read_text(encoding="utf-8")


def test_restore_support_registered() -> None:
    """注册进 TRANSFORM_FNS (rules.yaml function: 面)。"""
    assert (
        builtins.TRANSFORM_FNS["restore_support_from_src"] is restore_support_from_src
    )
