r"""slot_arg_revert pgtable 机位 —— zhleakimpl pgfplots 数据参 (2026-09-20)。

``\pgfplotstableread{inline table}\cs`` 与 ``\addplot table[kv]{\cs}``
/裸 ``{expr}`` 数据机位 zh 化 → spec 域 (无 kv 门控) ident 配对还原;
``\cs`` 尾巴与散文组不碰; 双侧计数分歧整跳。
"""

from pathlib import Path

from _fixloopkit import mk_ctx

from texlate.compile.fixloop.builtins import slot_arg_revert


def _trees(root: Path) -> tuple[Path, Path]:
    """wdir + baseline 双子树 —— baseline 必须在 wdir 外。"""
    work, base = root / "work", root / "baseline"
    work.mkdir()
    base.mkdir()
    return work, base


def _pair(work: Path, base: Path, name: str, src: str, zh: str) -> None:
    (base / name).write_text(src, encoding="utf-8")
    (work / name).write_text(zh, encoding="utf-8")


def _run(work: Path, base: Path) -> tuple[bool, str]:
    return slot_arg_revert(mk_ctx(work), None, None, {"baseline_dir": str(base)})


def test_pgtable_read_inline_numeric_table(tmp_path: Path) -> None:
    r"""2609.19828 实证: ``\pgfplotstableread{内联数值表}\cs`` 整参
    zh 化 (头行标识 + ``7.045e-03`` 的 ``e`` → ``这是译文``) ——
    纯数值表无 ``=``,``/``#`` kv 形, spec 域 (无门控) ident 还原;
    ``[col sep=...]`` opt 同机位; ``\cs`` 尾巴不碰; 幂等。"""
    work, base = _trees(tmp_path)
    src = (
        "\\pgfplotstableread{\n"
        "gpus cells dofs cg_time\n"
        "4 4194304 269748225 7.045e-03\n"
        "8 8388608 538970625 7.256e-03\n"
        "}\\tableWeakFour\n"
        "\\pgfplotstableread[col sep=space]{\n"
        "a b\n1 2\n}\\tableWeakFive\n"
    )
    zh = (
        "\\pgfplotstableread{\n"
        "这是译文这是译文这是译文这是译文\n"
        "4 4194304 269748225 7.045这是译文-02\n"
        "8 8388608 538970625 7.256这是译文-02\n"
        "}\\tableWeakFour\n"
        "\\pgfplotstableread[这是译文]{\n"
        "这是译文这是译文\n1 2\n}\\tableWeakFive\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src
    ok, _note = _run(work, base)
    assert not ok  # 幂等


def test_pgtable_addplot_keyword_and_bare_expr(tmp_path: Path) -> None:
    r"""``\addplot`` 系: ``table[x expr={...}]{\cs}`` opt+data 双机位
    还原 (opt 含 ``{}`` ``_OPTB`` 收); 裸 ``{expr}`` 无 keyword 同盖
    (pgfplots 语法 ``{...}`` 恒为 plot spec); ``\addplot[opt] 散文
    {..}`` keyword 门控不收 —— 散文组保 zh。"""
    work, base = _trees(tmp_path)
    src = (
        "\\addplot table[x expr={\\thisrowno{0}/4}, y expr={\\thisrowno{5}}] {\\tableMG};\n"
        "\\addplot[domain=1:128, dashed] {3.6*x};\n"
        "\\addplot[red] prose {keepme}\n"
    )
    zh = (
        "\\addplot table[这是译文={\\thisrowno{0}/4}, 这是译文={\\thisrowno{5}}] {这是译文};\n"
        "\\addplot[domain=1:128, dashed] {这是译文};\n"
        "\\addplot[red] prose {这是译文}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "x expr={\\thisrowno{0}/4}, y expr={\\thisrowno{5}}] {\\tableMG}" in out
    assert "{3.6*x}" in out  # 裸 expr 还原
    assert "prose {这是译文}" in out  # keyword 门控，散文不碰


def test_pgtable_divergent_counts_skip(tmp_path: Path) -> None:
    """zh 侧多一个 ``\\pgfplotstableread`` → pgtable kind 整跳 (分歧
    保护，note 记 colspec 同款 ``kind(n!=m)``)。"""
    work, base = _trees(tmp_path)
    src = "\\pgfplotstableread{\na b\n1 2\n}\\ta\n"
    zh = (
        "\\pgfplotstableread{\n这是译文这是译文\n1 2\n}\\ta\n"
        "\\pgfplotstableread{\nc d\n3 4\n}\\tb\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, note = _run(work, base)
    assert not ok
    assert "pgtable(1!=2)" in note


def test_pgtable_src_cjk_data_not_reverted(tmp_path: Path) -> None:
    """baseline 数据参自带 CJK (合法中文表头) → 非 ASCII ws-ident,
    不碰。"""
    work, base = _trees(tmp_path)
    _pair(
        work,
        base,
        "main.tex",
        "\\pgfplotstableread{\n列名 值\n1 2\n}\\ta\n",
        "\\pgfplotstableread{\n其他列 值\n1 2\n}\\ta\n",
    )
    ok, _note = _run(work, base)
    assert not ok
    assert "其他列" in (work / "main.tex").read_text(encoding="utf-8")
