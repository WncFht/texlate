r"""slot_arg_revert 内建 —— zh 化机位实参按 baseline 配对还原 (task#188)。

segmenter 把未注册机位实参放上翻译字面量面 → zh 化写回机位 →
``Undefined color '这是译文'``/``No counter``/``can't find file`` 族
(tmp/lane-zhleak)。builtin 在 ``mask_tex`` 等长视图上用 judge
``_MACHINE_SLOT_RXS`` + 扩展表定位实参, 与 baseline 同名件 per-kind
序号对齐: baseline 参纯 ASCII ident ∧ zh 参含 CJK ∧ 相异 → zh 参位
换回 baseline 字节。文位 (``\section{标题}``) 结构上不在机位表内
永不被碰; 双侧命中数分歧 → 该 kind 整跳; ``baseline_dir`` 缺席 →
False 空转。
"""

from pathlib import Path

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop.builtins import slot_arg_revert
from texlate.compile.fixloop.engine import LoopCtx


def _ctx(wdir: Path) -> LoopCtx:
    return LoopCtx(wdir=wdir, engine_name="xelatex", main_rel="main.tex", runner=None)


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
    return slot_arg_revert(_ctx(work), None, None, {"baseline_dir": str(base)})


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


# ------------------------------------------------- 负向: 文位/谓词/分歧/幂等/fail-safe


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
    """zh 参相异但零 CJK (ASCII 改动) → 非本族, 不动。"""
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
    """baseline 无同名件 → 无可对照, 不动。"""
    work, base = _trees(tmp_path)
    (work / "orphan.tex").write_text("\\label{这是译文}\n", encoding="utf-8")
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "orphan.tex").read_text(encoding="utf-8") == "\\label{这是译文}\n"


def test_missing_baseline_param_failsafe(tmp_path: Path) -> None:
    """无 ``baseline_dir`` param → False 不抛。"""
    ok, note = slot_arg_revert(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "baseline_dir" in note


def test_nonexistent_baseline_dir_failsafe(tmp_path: Path) -> None:
    """``baseline_dir`` 指不存在目录 → False 不抛。"""
    ok, note = slot_arg_revert(
        _ctx(tmp_path), None, None, {"baseline_dir": str(tmp_path / "nope")}
    )
    assert not ok
    assert "not a directory" in note


def test_idempotent_second_run(tmp_path: Path) -> None:
    """改写后重跑 → 参双侧一致, False 空转。"""
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


# ------------------------------------------------- kvcen: mathpartir inferkv 机位


def test_inferkv_opt_kv_reverted(tmp_path: Path) -> None:
    r"""mathpartir ``\inferrule*[left = \rlabel{Rec}]`` opt kv 键 zh 化
    (1708.07366 实证) —— opt 位 spec 域 ident 整体还原; premise 多层
    花括号/跨行参 ``_ARG`` 吃不进, kv 行盖不到 → inferkv opt-only 独盖;
    空 ``[]`` 双侧一致不占改写。"""
    work, base = _trees(tmp_path)
    src = (
        "\\inferrule*[left = \\rlabel{Rec}]\n"
        "{\n  \\inferrule*[left = \\rlabel{Alt}]{P\\to Q}{C}\n}\n{D}\n"
        "\\inferrule*[]\n{A}\n{B}\n"
    )
    zh = (
        "\\inferrule*[这是译文 = \\rlabel{Rec}]\n"
        "{\n  \\inferrule*[这是译文 = \\rlabel{Alt}]{P\\to Q}{C}\n}\n{D}\n"
        "\\inferrule*[]\n{A}\n{B}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_inferkv_bare_infer_covered(tmp_path: Path) -> None:
    r"""``\infer``/``\infer*`` 同族 opt 位同盖 (mathpartir ``\mpr@infer``
    双形同收 ``[opt]``)。"""
    work, base = _trees(tmp_path)
    src = "\\infer[lab = \\u{X}]{P}{C}\n\\infer*[right = \\u{Y}]{Q}{D}\n"
    zh = "\\infer[这是译文 = \\u{X}]{P}{C}\n\\infer*[这是译文 = \\u{Y}]{Q}{D}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_inferkv_no_opt_sites_not_slots(tmp_path: Path) -> None:
    r"""无 ``[]`` 的 ``\infer{a}{b}`` mand 参非机位 (premise/conclusion
    是数学面) —— zh 化也不还原; 一致 opt 不改写。"""
    work, base = _trees(tmp_path)
    src = "\\inferrule*[l=x]{P}{C}\n\\infer{A}{B}\n\\label{s}\n"
    zh = "\\inferrule*[l=x]{P}{C}\n\\infer{文}{B}\n\\label{文}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "\\infer{文}{B}" in out  # mand 参非机位, zh 保留
    assert "\\inferrule*[l=x]{P}{C}" in out  # 双侧一致 opt 未动
    assert "\\label{s}" in out


def test_inferkv_cjk_src_opt_not_reverted(tmp_path: Path) -> None:
    """baseline opt 自带 CJK (合法中文 label) → 非 ASCII, 不碰。"""
    work, base = _trees(tmp_path)
    _pair(
        work,
        base,
        "main.tex",
        "\\inferrule*[left = 归纳]{P}{C}\n",
        "\\inferrule*[left = 假设]{P}{C}\n",
    )
    ok, _note = _run(work, base)
    assert not ok


# ------------------------------------------------- primgap: 原语 pre-{ gap 机位 (2026-09-20)


def test_primgap_vadjust_reverted(tmp_path: Path) -> None:
    """2609.19815 实证: ``\\vadjust 这是译文{\\vskip 1pt}`` —— CJK 落在
    原语 cs 与 ``{``-组之间 (``pre`` keyword 被译), 3↔3 序号还原。"""
    work, base = _trees(tmp_path)
    src = (
        "$r^2$\\vadjust pre{\\vskip 1pt}\n"
        "$s^2$\\vadjust pre{\\vskip 1pt}\n"
        "$t^2$\\vadjust pre{\\vskip 1pt}\n"
    )
    zh = (
        "$r^2$\\vadjust 这是译文{\\vskip 1pt}\n"
        "$s^2$\\vadjust 这是译文{\\vskip 1pt}\n"
        "$t^2$\\vadjust 这是译文{\\vskip 1pt}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_primgap_leaders_broadcast(tmp_path: Path) -> None:
    """2609.20633 实证: baseline ``\\leaders\\hbox to .55em{...}`` 只在
    ``\\tocdots`` def 站 ×1, zh 展开把字面量倍增到调用站 → 计数分歧,
    unique-src ``\\hbox to .55em`` 广播到全部 CJK gap; def 站 zh 双侧
    一致不动, 无关 ``\\hbox`` 站不碰。"""
    work, base = _trees(tmp_path)
    src = (
        "\\newcommand{\\tocdots}{\\leaders\\hbox to .55em{\\hfil.\\hfil}\\hfill}\n"
        "\\newcommand{\\tocmain}[1]{#1 \\tocdots}\n"
        "\\tocmain{Alpha}\n\\tocmain{Beta}\n"
    )
    zh = (
        "\\newcommand{\\tocdots}{\\leaders\\hbox to .55em{\\hfil.\\hfil}\\hfill}\n"
        "\\newcommand{\\tocmain}[1]{#1 \\tocdots}\n"
        "条目甲 \\leaders\\hbox 这是译文{\\hfil.\\hfil}\\hfill\n"
        "条目乙 \\leaders\\hbox 这是译文{\\hfil.\\hfil}\\hfill\n"
        "条目丙 \\leaders\\hbox 这是译文{\\hfil.\\hfil}\\hfill\n"
        "\\hbox to\\texlate@floatwidth{injected}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, note = _run(work, base)
    assert ok
    assert "broadcast" in note
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "这是译文" not in out
    for tag in "甲乙丙":
        assert f"条目{tag} \\leaders\\hbox to .55em{{\\hfil.\\hfil}}\\hfill" in out
    assert "\\leaders\\hbox to .55em" in out.splitlines()[0]  # def 站原样
    assert "\\hbox to\\texlate@floatwidth{injected}" in out  # 非 CJK gap 不动


def test_primgap_multi_src_values_skip(tmp_path: Path) -> None:
    """src gap 多值 (``pre``/``to .55em``) 遇计数分歧 → 不广播整跳。"""
    work, base = _trees(tmp_path)
    src = "\\vadjust pre{\\vskip 1pt}\n\\hbox to .55em{x}\n"
    zh = (
        "\\vadjust 这是译文{\\vskip 1pt}\n"
        "\\hbox 这是译文{x}\n"
        "\\vadjust 这是译文{\\vskip 1pt}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, note = _run(work, base)
    assert not ok
    assert "primgap(2!=3)" in note
    assert (work / "main.tex").read_text(encoding="utf-8") == zh


def test_primgap_non_cjk_gap_untouched(tmp_path: Path) -> None:
    """zh gap 相异但零 CJK (``to 4em`` vs ``to 3em`` ASCII 改动) → 不动。"""
    work, base = _trees(tmp_path)
    _pair(
        work,
        base,
        "main.tex",
        "\\vadjust pre{\\vskip 1pt}\n\\hbox to 3em{x}\n",
        "\\vadjust pre{\\vskip 1pt}\n\\hbox to 4em{x}\n",
    )
    ok, _note = _run(work, base)
    assert not ok
    assert "\\hbox to 4em{x}" in (work / "main.tex").read_text(encoding="utf-8")


def test_primgap_empty_src_gap_skip(tmp_path: Path) -> None:
    """``\\hbox{`` → ``\\hbox 这是译文{`` 形: 空 gap 非 ident → 不还原
    (strip 臂有意不做 —— 丢 ``to <dimen>`` 语义, 仅证不误伤)。"""
    work, base = _trees(tmp_path)
    _pair(work, base, "main.tex", "\\hbox{x}\n", "\\hbox 这是译文{x}\n")
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "main.tex").read_text(encoding="utf-8") == "\\hbox 这是译文{x}\n"


def test_primgap_idempotent(tmp_path: Path) -> None:
    """改写后重跑 → gap 双侧一致, False 空转。"""
    work, base = _trees(tmp_path)
    _pair(
        work,
        base,
        "main.tex",
        "\\vadjust pre{\\vskip 1pt}\n",
        "\\vadjust 这是译文{\\vskip 1pt}\n",
    )
    ok, _note = _run(work, base)
    assert ok
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "main.tex").read_text(
        encoding="utf-8"
    ) == "\\vadjust pre{\\vskip 1pt}\n"
