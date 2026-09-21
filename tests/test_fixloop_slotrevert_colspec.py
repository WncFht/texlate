r"""slot_arg_revert colspec 机位 —— arrayresid (2026-09-19) + zhleakimpl _ARGB (2026-09-20)。

列 spec 参 (``\begin{tabular}{|c|}``/``\multicolumn{n}{spec}{text}``/doc
自定义 spec-holder ``\betb``) zh 化 → 可打印 ASCII ident 配对还原;
``_ARGB`` 平衡组把跨行/嵌组 spec (``xltabular``/``tblr``/``xtabular``)
一并收入。envarg 严格 ident 够不着的 ``|``/空格/嵌套面归本 lane。
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


# ------------------------------------------------- arrayresid: 列 spec 机位 (2026-09-19)


def test_colspec_env_arg_reverted(tmp_path: Path) -> None:
    """``\\begin{tabular}{|c|}`` spec 参 zh 化 —— envarg 同位但严格
    ident 拒收 ``|``/空格 → colspec kind 可打印 ASCII ident 还原。"""
    work, base = _trees(tmp_path)
    src = "\\begin{tabular}{| cc | l |}\na&b\\\\\n\\end{tabular}\n"
    zh = "\\begin{tabular}{| 这是译文 |}\na&b\\\\\n\\end{tabular}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_colspec_two_arg_env(tmp_path: Path) -> None:
    """``\\begin{tabularx}{dimen}{spec}`` 双参全机位 —— dimen 参含
    反斜杠 (``\\textwidth``) 严格 ident 拒收, colspec 收。"""
    work, base = _trees(tmp_path)
    src = "\\begin{tabularx}{\\textwidth}{|X|X|}\na&b\\\\\n\\end{tabularx}\n"
    zh = "\\begin{tabularx}{这是译文}{这是译文}\na&b\\\\\n\\end{tabularx}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_colspec_multicolumn(tmp_path: Path) -> None:
    """``\\multicolumn{n}{spec}{text}`` n+spec 还原, text 散文不碰。"""
    work, base = _trees(tmp_path)
    src = "\\multicolumn{8}{c|}{Head}\n"
    zh = "\\multicolumn{这是译文}{这是译文}{标题译文}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "\\multicolumn{8}{c|}{标题译文}" in out  # text 参保留 zh


def test_colspec_holder_betb(tmp_path: Path) -> None:
    """1502.01845 实证锚点: ``\\betb`` = ``\\begin{center}\\begin{tabular}``
    doc 自定义 spec-holder → def 体尾部 spec-env ``\\begin`` 断言发现,
    调用站 zh 化 spec 还原; 纯字母 spec 双侧一致不动。"""
    work, base = _trees(tmp_path)
    src = (
        "\\newcommand\\betb{\\begin{center}\\begin{tabular}}\n"
        "\\betb{cccc|ccc}\nx\n"
        "\\betb{| cc cc  cc  cc | lc lc lc lc| }\ny\n"
    )
    zh = (
        "\\newcommand\\betb{\\begin{center}\\begin{tabular}}\n"
        "\\betb{cccc|ccc}\nx\n"
        "\\betb{| 这是译文 | 这是译文| }\ny\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_colspec_holder_def_site_not_counted(tmp_path: Path) -> None:
    """def 行 ``\\betb{body}`` 体含花括号天然不匹配调用站 rx ——
    src/zh 双侧计数只算真调用站。"""
    work, base = _trees(tmp_path)
    src = (
        "\\def\\mytab{\\begin{array}}\n\\mytab{cc}\n"
        "\\def\\other{not-a-spec}\n\\other{intro}\n"
    )
    zh = (
        "\\def\\mytab{\\begin{array}}\n\\mytab{译文}\n"
        "\\def\\other{not-a-spec}\n\\other{这是译文散文}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "\\mytab{cc}" in out  # array-holder 还原
    assert "\\other{这是译文散文}" in out  # 非 holder 散文位不碰


def test_colspec_holder_argc_macro_skipped(tmp_path: Path) -> None:
    """带 ``[n]`` 形参表的宏不是 holder (实参被 #n 消费不进流)。"""
    work, base = _trees(tmp_path)
    src = "\\newcommand\\ftab[1]{\\begin{tabular}}\n\\ftab{cc}\n"
    zh = "\\newcommand\\ftab[1]{\\begin{tabular}}\n\\ftab{译文}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "main.tex").read_text(encoding="utf-8") == zh


def test_colspec_no_false_revert_clean_spec(tmp_path: Path) -> None:
    """spec 双侧一致 → 不动; holder 散文位不存在的负向核验。"""
    work, base = _trees(tmp_path)
    src = "\\begin{tabular}{|c|c|}\nx\n\\end{tabular}\n"
    _pair(work, base, "main.tex", src, src)
    ok, _note = _run(work, base)
    assert not ok


def test_colspec_divergent_counts_skip(tmp_path: Path) -> None:
    """zh 侧多一个 ``\\begin{tabular}`` → colspec kind 整跳 (分歧保护)。"""
    work, base = _trees(tmp_path)
    src = "\\begin{tabular}{cc}\nx\n\\end{tabular}\n"
    zh = "\\begin{tabular}{译文}\nx\n\\end{tabular}\n\\begin{tabular}{cc}\ny\n\\end{tabular}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, note = _run(work, base)
    assert not ok
    assert "divergent" in note


# ------------------------------------ zhleakimpl: _ARGB 平衡组 spec (2026-09-20)


def test_colspec_xltabular_multiline_nested_spec(tmp_path: Path) -> None:
    r"""2609.20179 实证: ``\begin{xltabular}{\textwidth}{`` 跨行
    ``>{...}`` 嵌组 spec —— src 多行参 ``_ARG`` 捕不进, zh 压平
    单行 ``p``/``X`` → ``这是译文`` ×6; ``_ARGB`` 整参捕获 + ws
    spec ident 一次性换回 baseline 字节 (6 漏点一参覆盖), env 体
    内散文保 zh; 二次跑幂等空转。"""
    work, base = _trees(tmp_path)
    src = (
        "\\begin{xltabular}{\\textwidth}{\n"
        "\t\t>{\\raggedright\\arraybackslash}p{0.13\\textwidth}\n"
        "\t\t>{\\raggedright\\arraybackslash}p{0.17\\textwidth}\n"
        "\t\t>{\\raggedright\\arraybackslash}X\n"
        "\t}\n"
        "a & b & c \\\\\n\\end{xltabular}\n"
    )
    zh = (
        "\\begin{xltabular}{\\textwidth}{  >{\\raggedright\\arraybackslash}"
        "这是译文{0.13\\textwidth}  >{\\raggedright\\arraybackslash}"
        "这是译文{0.17\\textwidth}  >{\\raggedright\\arraybackslash}这是译文  }\n"
        "甲 & 乙 & 丙 \\\\\n\\end{xltabular}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert out.startswith(src.split("a & b", maxsplit=1)[0])  # spec 整参复原
    assert "甲 & 乙 & 丙" in out  # env 体散文保 zh
    ok, _note = _run(work, base)
    assert not ok  # 幂等


def test_colspec_nested_decl_one_arg_env(tmp_path: Path) -> None:
    r"""单参臂同盲区: ``\begin{tabular}{>{\raggedright}p{3cm}c}`` 与
    ``\begin{tblr}{colspec={Q[l]Q[c]}}`` 嵌组 spec zh 化 → ``_ARGB``
    + ws ident 还原。"""
    work, base = _trees(tmp_path)
    src = (
        "\\begin{tabular}{>{\\raggedright}p{3cm}c}\nx\n\\end{tabular}\n"
        "\\begin{tblr}{colspec={Q[l]Q[c]}, row{1}={c}}\ny\n\\end{tblr}\n"
    )
    zh = (
        "\\begin{tabular}{>{\\raggedright}这是译文{3cm}这是译文}\nx\n\\end{tabular}\n"
        "\\begin{tblr}{这是译文={这是译文}这是译文}\ny\n\\end{tblr}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_colspec_xtabular_and_multicolumn_nested(tmp_path: Path) -> None:
    r"""``xtabular`` 回单参臂 (xtab.sty ``\@supertabular[#1]#2`` 单
    mand 参实测) + ``\multicolumn{n}{>{...}c}{text}`` spec 位嵌组
    —— zh 化还原, multicolumn text 散文不碰。"""
    work, base = _trees(tmp_path)
    src = (
        "\\begin{xtabular}{>{\\footnotesize}lX}\nx\n\\end{xtabular}\n"
        "\\multicolumn{2}{>{\\raggedright}c|}{Head}\n"
    )
    zh = (
        "\\begin{xtabular}{>{\\footnotesize}这是译文这是译文}\nx\n\\end{xtabular}\n"
        "\\multicolumn{2}{>{\\raggedright}这是译文|}{标题}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "\\begin{xtabular}{>{\\footnotesize}lX}" in out
    assert "\\multicolumn{2}{>{\\raggedright}c|}{标题}" in out  # text 保 zh


def test_colspec_non_spec_env_prose_untouched(tmp_path: Path) -> None:
    r"""负向: 非 spec-env 后 ``{...}`` 散文组 —— colspec env 名单
    不收; envarg 同位捕获但严格 ident 拒空格散文 → 双面皆不碰,
    zh 保留 (ws-spec ident 不外溢到非机位)。"""
    work, base = _trees(tmp_path)
    src = "\\begin{myenv}{Dear reviewer}\nx\n\\end{myenv}\n"
    zh = "\\begin{myenv}{这是译文}\nx\n\\end{myenv}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "main.tex").read_text(encoding="utf-8") == zh
