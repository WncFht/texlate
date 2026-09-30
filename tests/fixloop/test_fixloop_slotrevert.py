r"""slot_arg_revert 内建 —— zh 化机位实参按 baseline 配对还原 (task#188)。

segmenter 把未注册机位实参放上翻译字面量面 → zh 化写回机位 →
``Undefined color '这是译文'``/``No counter``/``can't find file`` 族
(zhleak 车道)。builtin 在 ``mask_tex`` 等长视图上用 judge
``_MACHINE_SLOT_RXS`` + 扩展表定位实参, 与 baseline 同名件 per-kind
序号对齐: baseline 参纯 ASCII ident ∧ zh 参含 CJK ∧ 相异 → zh 参位
换回 baseline 字节。文位 (``\section{标题}``) 结构上不在机位表内
永不被碰; 双侧命中数分歧 → 该 kind 整跳; ``baseline_dir`` 缺席 →
False 空转。
"""

from pathlib import Path

from _fixloopkit import mk_ctx

from texlate.compile.fixloop import builtins
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


# ---------------------------------------------------------------- 各 kind 正向还原


def test_csname_body_reverted(tmp_path: Path) -> None:
    """``\\csname`` 体 zh 化 (aipcheck ``ver@times.sty`` 实证锚点) → 换回。"""
    work, base = _trees(tmp_path)
    src = "\\global\\expandafter\\let\\csname ver@times.sty\\endcsname\\relax\n"
    zh = "\\global\\expandafter\\let\\csname 这是译文\\endcsname\\relax\n"
    _pair(work, base, "aipcheck.tex", src, zh)
    ok, note = _run(work, base)
    assert ok
    assert "aipcheck.tex" in note
    assert (work / "aipcheck.tex").read_text(encoding="utf-8") == src


def test_env_name_reverted(tmp_path: Path) -> None:
    """``\\begin/\\end{env}`` 名 zh 化 (judge ``env`` 行) → 双侧各还原。"""
    work, base = _trees(tmp_path)
    src = "\\begin{thmenv}\nbody\n\\end{thmenv}\n"
    zh = "\\begin{这是译文}\nbody\n\\end{这是译文}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_env_trailing_args_reverted(tmp_path: Path) -> None:
    """未注册 env 尾随机参 (``translatedabstract{french}``/``Mizar{x,Y,A}``)。"""
    work, base = _trees(tmp_path)
    src = (
        "\\begin{translatedabstract}{french}\nText.\n\\end{translatedabstract}\n"
        "\\begin{Mizar}{x,Y,A}\nBody.\n\\end{Mizar}\n"
    )
    zh = (
        "\\begin{translatedabstract}{这是译文}\n正文。\n\\end{translatedabstract}\n"
        "\\begin{Mizar}{x,译文,A}\n正文。\n\\end{Mizar}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "\\begin{translatedabstract}{french}" in out
    assert "\\begin{Mizar}{x,Y,A}" in out
    assert "正文。" in out  # env 内散文照旧 zh 不碰


def test_envarg_opt_only(tmp_path: Path) -> None:
    """``\\begin{tikzpicture}[kv]`` opt-only 站 (envarg 末臂 ``|_OPTC``)。"""
    work, base = _trees(tmp_path)
    src = "\\begin{tikzpicture}[scale=2]\n\\end{tikzpicture}\n"
    zh = "\\begin{tikzpicture}[缩放=二]\n\\end{tikzpicture}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_envarg_newline_arg_reverted(tmp_path: Path) -> None:
    r"""2609.19556 实证: ``\begin{promptbox}{General\ninstructions}
    {colframe=black!60}`` —— src 参带字面换行 ``_ARG`` 捕不进, zh 平
    参站双侧 26≠28 → envarg 整跳 7 站全漏; ``_ARGNL`` 跨行容忍后对
    齐, kv 参还原; 参1 含 ``\n`` 非严格 ident 保留 zh (title 散文位)。"""
    work, base = _trees(tmp_path)
    src = (
        "\\begin{promptbox}{General\ninstructions}{colframe=black!60}\n"
        "body\n\\end{promptbox}\n"
        "\\begin{promptbox}{Exhaustion}{colframe=blue!50!black}\n"
        "body\n\\end{promptbox}\n"
    )
    zh = (
        "\\begin{promptbox}{这是译文这是译文}{这是译文!60}\n"
        "正文\n\\end{promptbox}\n"
        "\\begin{promptbox}{这是译文}{这是译文这是译文}\n"
        "正文\n\\end{promptbox}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "\\begin{promptbox}{这是译文这是译文}{colframe=black!60}" in out
    assert "\\begin{promptbox}{Exhaustion}{colframe=blue!50!black}" in out


def test_envarg_newline_divergence_healed(tmp_path: Path) -> None:
    """计数分歧不再整跳后，同文件无关 envarg 站 (``Mizar`` 尾参) 照
    常还原 —— 跨行参站补齐后 28=28 对齐。"""
    work, base = _trees(tmp_path)
    src = (
        "\\begin{promptbox}{General\ninstructions}{colframe=black!60}\n"
        "x\n\\end{promptbox}\n"
        "\\begin{Mizar}{x,Y,A}\ny\n\\end{Mizar}\n"
    )
    zh = (
        "\\begin{promptbox}{这是译文}{这是译文!60}\n"
        "x\n\\end{promptbox}\n"
        "\\begin{Mizar}{x,译文,A}\ny\n\\end{Mizar}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "{colframe=black!60}" in out
    assert "\\begin{Mizar}{x,Y,A}" in out


def test_envarg_blank_line_still_breaks(tmp_path: Path) -> None:
    r"""``\n\n``=``\par`` 仍截断 arg 扫描 —— 含空行的组双侧都不捕
    (``_ARGNL`` 只放单 ``\n``, 不过度放宽)。"""
    work, base = _trees(tmp_path)
    src = "\\begin{e}{a\n\nb}\nx\n\\end{e}\n"
    zh = "\\begin{e}{a\n\n这是译文}\nx\n\\end{e}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "main.tex").read_text(encoding="utf-8") == zh


def test_restatable_double_args(tmp_path: Path) -> None:
    """``\\begin{restatable}{env}{cskey}`` 双机位参 (同位 envarg 重扫被去重)。"""
    work, base = _trees(tmp_path)
    src = "\\begin{restatable}{theorem}{mainthm}\nBody.\n\\end{restatable}\n"
    zh = "\\begin{restatable}{定理}{主定理}\n正文。\n\\end{restatable}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == (
        "\\begin{restatable}{theorem}{mainthm}\n正文。\n\\end{restatable}\n"
    )


def test_ref_label_and_cite(tmp_path: Path) -> None:
    """``\\label``/``\\ref``/``\\cite`` 键 zh 化 → 还原 (``\\section`` 不动)。"""
    work, base = _trees(tmp_path)
    src = "\\section{Intro}\\label{sec:intro}\nSee \\ref{sec:intro} \\cite{a,b}.\n"
    zh = "\\section{这是译文}\\label{这是译文}\n见 \\ref{这是译文} \\cite{这是译文}。\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "\\label{sec:intro}" in out
    assert "\\ref{sec:intro}" in out
    assert "\\cite{a,b}" in out
    assert "\\section{这是译文}" in out  # 文位参永不被还原


def test_color_and_counter(tmp_path: Path) -> None:
    """``\\textcolor``/``\\setcounter`` 机位名参 zh 化 → 还原。"""
    work, base = _trees(tmp_path)
    src = "\\textcolor{red}{x}\\setcounter{page}{3}\n"
    zh = "\\textcolor{这是译文}{x}\\setcounter{这是译文}{3}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_pkg_bib_and_lang(tmp_path: Path) -> None:
    """``\\usepackage``/``\\bibliography``/``\\selectlanguage`` 三族。"""
    work, base = _trees(tmp_path)
    src = "\\usepackage{amsmath}\\bibliography{refs}\\selectlanguage{english}\n"
    zh = "\\usepackage{这是译文}\\bibliography{这是译文}\\selectlanguage{这是译文}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_input_filearg_and_url(tmp_path: Path) -> None:
    """``\\input``/``\\lstinputlisting``/``\\url`` 路径族。"""
    work, base = _trees(tmp_path)
    src = "\\input{chap/intro}\n\\lstinputlisting{code/a.py}\\url{a.b/c}\n"
    zh = "\\input{这是译文}\n\\lstinputlisting{这是译文}\\url{这是译文}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_kv_and_font(tmp_path: Path) -> None:
    """``\\hypersetup`` kv 串 + ``\\setmainfont`` 空格字体名 (loose ident)。"""
    work, base = _trees(tmp_path)
    src = "\\hypersetup{colorlinks,linkcolor=blue}\\setmainfont{Times New Roman}\n"
    zh = "\\hypersetup{这是译文}\\setmainfont{这是译文}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_footopt_and_comment_masked(tmp_path: Path) -> None:
    """``\\footnotemark[n]`` opt 机参还原; 注释内同形 token 遮盖不计。"""
    work, base = _trees(tmp_path)
    src = "\\footnotemark[1] % \\footnotemark[9]\n"
    zh = "\\footnotemark[文] % \\footnotemark[9]\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_multi_file_note(tmp_path: Path) -> None:
    """多文件各命中 → note 记件数。"""
    work, base = _trees(tmp_path)
    _pair(work, base, "a.tex", "\\label{a}\n", "\\label{文}\n")
    _pair(work, base, "b.tex", "\\label{b}\n", "\\label{文}\n")
    ok, note = _run(work, base)
    assert ok
    assert "2 files" in note


# ------------------------------------------------- 负向：文位/谓词/分歧/幂等/fail-safe


def test_prose_args_never_touched(tmp_path: Path) -> None:
    """``\\section{标题}``/裸 ``{word}`` 散文位不在机位表 → 零改写。"""
    work, base = _trees(tmp_path)
    src = "\\section{Intro} {word} prose\n"
    zh = "\\section{这是译文} {这是译文} 散文\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "main.tex").read_text(encoding="utf-8") == zh


def test_cjk_src_arg_not_reverted(tmp_path: Path) -> None:
    """baseline 参自带 CJK (合法中文标识符) → 非 ASCII ident, 不碰。"""
    work, base = _trees(tmp_path)
    _pair(work, base, "main.tex", "\\label{中文键}\n", "\\label{另一中文}\n")
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "main.tex").read_text(encoding="utf-8") == "\\label{另一中文}\n"


def test_divergent_counts_skip_kind(tmp_path: Path) -> None:
    """zh 侧多一个 ``\\cite`` → cite kind 整跳 (note 记分歧); env 照改。"""
    work, base = _trees(tmp_path)
    src = "\\begin{e}x\\end{e}\n\\cite{a}\n"
    zh = "\\begin{文}x\\end{文}\n\\cite{文}\\cite{文2}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, note = _run(work, base)
    assert ok
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "\\begin{e}x\\end{e}" in out  # env kind 2v2 对齐还原
    assert "\\cite{文}\\cite{文2}" in out  # cite 1v2 分歧整跳
    assert "divergent" in note


def test_ascii_divergence_no_cjk(tmp_path: Path) -> None:
    """zh 参相异但零 CJK (ASCII 改动) → 非本族，不动。"""
    work, base = _trees(tmp_path)
    _pair(work, base, "main.tex", "\\label{a}\n", "\\label{b}\n")
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "main.tex").read_text(encoding="utf-8") == "\\label{b}\n"


def test_dead_tail_ignored(tmp_path: Path) -> None:
    """``\\end{document}`` 死尾后同形 token 非活 slot。"""
    work, base = _trees(tmp_path)
    src = "\\end{document}\n\\label{a}\n"
    zh = "\\end{document}\n\\label{文}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "main.tex").read_text(encoding="utf-8") == zh


def test_identical_files_fastpath(tmp_path: Path) -> None:
    """工作件与 baseline 一致 → 不动。"""
    work, base = _trees(tmp_path)
    _pair(work, base, "main.tex", "\\label{a}\n", "\\label{a}\n")
    ok, _note = _run(work, base)
    assert not ok


def test_no_baseline_counterpart(tmp_path: Path) -> None:
    """baseline 无同名件 → 无可对照，不动。"""
    work, base = _trees(tmp_path)
    (work / "orphan.tex").write_text("\\label{这是译文}\n", encoding="utf-8")
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "orphan.tex").read_text(encoding="utf-8") == "\\label{这是译文}\n"


def test_missing_baseline_param_failsafe(tmp_path: Path) -> None:
    """无 ``baseline_dir`` param → False 不抛。"""
    ok, note = slot_arg_revert(mk_ctx(tmp_path), None, None, {})
    assert not ok
    assert "baseline_dir" in note


def test_nonexistent_baseline_dir_failsafe(tmp_path: Path) -> None:
    """``baseline_dir`` 指不存在目录 → False 不抛。"""
    ok, note = slot_arg_revert(
        mk_ctx(tmp_path), None, None, {"baseline_dir": str(tmp_path / "nope")}
    )
    assert not ok
    assert "not a directory" in note


def test_idempotent_second_run(tmp_path: Path) -> None:
    """改写后重跑 → 参双侧一致，False 空转。"""
    work, base = _trees(tmp_path)
    _pair(work, base, "main.tex", "\\label{a}\n", "\\label{文}\n")
    ok, _note = _run(work, base)
    assert ok
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "main.tex").read_text(encoding="utf-8") == "\\label{a}\n"


def test_slot_arg_revert_registered() -> None:
    """注册进 TRANSFORM_FNS (rules.yaml ``function:`` 面)。"""
    assert builtins.TRANSFORM_FNS["slot_arg_revert"] is slot_arg_revert
