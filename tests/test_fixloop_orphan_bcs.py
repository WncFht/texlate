r"""o2-builtin-cs 面规则钉 (m1b-residue-routes-2026-09-17) —— orphan_rules 析出的第二半。

四个 builtin: ``undefined_env_polyfill`` / ``undefine_for_redef`` 批量+站点
前置 (含 end* 恒拒名 ``\@ifdefinable`` rc@ 旁路与 ``\QED`` 对偶件臂) /
``font_cs_shim`` (AMS 上古字体 cs) / ``cs_rebind`` (produced-by-cs 缺字
回绑 ``\txlatefallback``)。log 侧固定走 ``{main stem}.log``
(_fixloop_log 定位序)。
"""

from pathlib import Path

from _fixloopkit import mk_ctx, rs, rule

from texlate.compile.fixloop.builtins import TRANSFORM_FNS

_MAIN_DOCCLASS = "\\documentclass{article}\n"


def _write_main(tmp_path: Path, body: str) -> None:
    (tmp_path / "main.tex").write_text(_MAIN_DOCCLASS + body)


# ─── undefined_env_polyfill ───


def test_env_polyfill_multi_env_batch(tmp_path: Path) -> None:
    """1012.1059 形: 一轮 log 三 env 同缺 → 一次全清 (\\ifcsname 守卫 noop)。"""
    _write_main(
        tmp_path,
        "\\begin{document}\n"
        "\\begin{example}e\\end{example}\n"
        "\\begin{definition}d\\end{definition}\n"
        "\\begin{theorem}t\\end{theorem}\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:3: LaTeX Error: Environment example undefined.\n"
        "main.tex:4: LaTeX Error: Environment definition undefined.\n"
        "main.tex:5: LaTeX Error: Environment theorem undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        mk_ctx(tmp_path), None, "example", {"deny": ["document"]}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    for e in ("example", "definition", "theorem"):
        assert f"\\newenvironment{{{e}}}{{}}" in t, e
        assert f"\\ifcsname {e}\\endcsname" in t


def test_env_polyfill_math_env_shell(tmp_path: Path) -> None:
    """数学 env 给 ``\\[..\\]`` 壳兜底数学域 (MATH_ENVS 表)。"""
    _write_main(
        tmp_path,
        "\\begin{document}\n$\\begin{gather}a=b\\end{gather}$\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment gather undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        mk_ctx(tmp_path), None, "gather", {}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\newenvironment{gather}{\\[}{\\]}" in t


def test_env_polyfill_unused_env_declines(tmp_path: Path) -> None:
    """log 报了但源无 ``\\begin{env}`` 站点 → 不注 (窄谓词)。"""
    _write_main(tmp_path, "\\begin{document}\nx\n\\end{document}\n")
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment sidebar undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        mk_ctx(tmp_path), None, "sidebar", {}
    )
    assert not ok
    assert "not \\begin-used" in note


def test_env_polyfill_halt_expansion(tmp_path: Path) -> None:
    r"""halt_on_error 单行 log 只见 ``example`` —— 批扩把全部在用且无
    in-doc 定义证据的 env 一轮清 (1012.1059 实证 8env); 内核 env
    (figure) 与 ``\\newtheorem`` 已定义名 (corollary) 不注; 注入位在
    ``\\begin{document}`` 前 (``\\ifcsname`` 才能见包定义名)。"""
    _write_main(
        tmp_path,
        "\\usepackage{amsmath}\n"
        "\\newtheorem{corollary}{Cor}\n"
        "\\begin{document}\n"
        "\\begin{example}e\\end{example}\n"
        "\\begin{lemma}l\\end{lemma}\n"
        "\\begin{corollary}c\\end{corollary}\n"
        "\\begin{figure}f\\end{figure}\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:4: LaTeX Error: Environment example undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        mk_ctx(tmp_path), None, "example", {}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    for e in ("example", "lemma"):
        assert f"\\ifcsname {e}\\endcsname" in t, e
    # corollary 有 \newtheorem 活定义 → 扩面剔除; figure 内核 env → 不注
    assert "\\ifcsname corollary\\endcsname" not in t
    assert "\\ifcsname figure\\endcsname" not in t
    # 注入位在 \begin{document} 行首之前 (包装载已执行, 守卫才正确)
    assert t.index("\\ifcsname example\\endcsname") < t.index("\\begin{document}")
    # amsmath 在载 → gather 类包定义 env 若在用, 守卫行是死化无操作 ——
    # 本例未用 gather 故无其行
    assert "\\ifcsname gather\\endcsname" not in t


def test_env_polyfill_idempotent(tmp_path: Path) -> None:
    """二轮再点火: \\ifcsname 标记已见 → applied=False 不占轮次。"""
    _write_main(
        tmp_path,
        "\\begin{document}\n\\begin{lemma}l\\end{lemma}\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment lemma undefined.\n"
    )
    ctx = mk_ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["undefined_env_polyfill"](ctx, None, "lemma", {})
    assert ok
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](ctx, None, "lemma", {})
    assert not ok
    assert "already polyfilled" in note


def test_env_polyfill_deny_document(tmp_path: Path) -> None:
    """document 环境在 deny 表 —— 永不 noop 化。"""
    _write_main(tmp_path, "\\begin{document}\nx\n\\end{document}\n")
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment document undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        mk_ctx(tmp_path), None, "document", {"deny": ["document"]}
    )
    assert not ok
    assert "no undefined env" in note


# ─── undefined_env_polyfill: preamble renew 站点前置臂 ───


def test_env_polyfill_preamble_renew_site(tmp_path: Path) -> None:
    """0806.0904 形: ``\\renewenvironment{proof}`` 在序言报错 —— 守卫 noop
    前置到站点行首 (pre-begindoc 注入位在站点之后, 批扩够不到);
    renew 闸过后稿自带定义覆盖 noop, 站点行内容不动。"""
    _write_main(
        tmp_path,
        "\\usepackage{amsmath}\n"
        "\\renewenvironment{proof}{\\par\\noindent\\textbf{Pf.}}{\\par}\n"
        "\\begin{document}\n"
        "\\begin{proof}body\\end{proof}\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:3: LaTeX Error: Environment proof undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        mk_ctx(tmp_path), None, "proof", {}
    )
    assert ok, note
    assert "pre-renew noop: proof" in note
    t = (tmp_path / "main.tex").read_text()
    guard = "\\ifcsname proof\\endcsname\\else\\newenvironment{proof}{}{}\\fi"
    assert guard in t
    # 守卫落在 renew 站点行首之前, 而非 pre-begindoc 批块位
    assert t.index(guard) < t.index("\\renewenvironment{proof}")
    # proof 已站点前置 → 不占 pre-begindoc 批块
    assert t.count(guard) == 1


def test_env_polyfill_renew_site_no_begin_use(tmp_path: Path) -> None:
    """renew 站点本身即消费点 —— 无 ``\\begin{proof}`` 也修 (旧窄谓词会拒)。"""
    _write_main(
        tmp_path,
        "\\renewenvironment{sidebar}{}{}\n\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment sidebar undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        mk_ctx(tmp_path), None, "sidebar", {}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert t.index("\\ifcsname sidebar\\endcsname") < t.index(
        "\\renewenvironment{sidebar}"
    )


def test_env_polyfill_renew_site_in_other_file(tmp_path: Path) -> None:
    """renew 站点在非主文件 → 该文件行首前置; 主文件批块照注兜底
    (站点文件可能不被 ``\\input`` 抵达)。"""
    _write_main(
        tmp_path,
        "\\input{pre}\n"
        "\\begin{document}\n"
        "\\begin{proof}body\\end{proof}\n"
        "\\end{document}\n",
    )
    (tmp_path / "pre.tex").write_text(
        "% preamble helpers\n\\renewenvironment{proof}{}{}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "pre.tex:2: LaTeX Error: Environment proof undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        mk_ctx(tmp_path), None, "proof", {}
    )
    assert ok, note
    pre = (tmp_path / "pre.tex").read_text()
    assert pre.index("\\ifcsname proof\\endcsname") < pre.index(
        "\\renewenvironment{proof}"
    )
    # proof 仍在 fresh → 主文件 pre-begindoc 批块同注 (双保险)
    main = (tmp_path / "main.tex").read_text()
    assert "\\ifcsname proof\\endcsname" in main
    assert main.index("\\ifcsname proof\\endcsname") < main.index("\\begin{document}")


def test_env_polyfill_renew_dead_zone_ignored(tmp_path: Path) -> None:
    """注释掉的 ``%\\renewenvironment`` 不是站点 —— 不前置, 批块照常。"""
    _write_main(
        tmp_path,
        "%\\renewenvironment{proof}{}{}\n"
        "\\begin{document}\n"
        "\\begin{proof}body\\end{proof}\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:3: LaTeX Error: Environment proof undefined.\n"
    )
    ok, _note = TRANSFORM_FNS["undefined_env_polyfill"](
        mk_ctx(tmp_path), None, "proof", {}
    )
    assert ok
    t = (tmp_path / "main.tex").read_text()
    # 守卫只来自批块, 落在 \begin{document} 行首前, 而非注释行处
    assert t.index("\\ifcsname proof\\endcsname") < t.index("\\begin{document}")
    assert t.index("\\ifcsname proof\\endcsname") > t.index(
        "%\\renewenvironment{proof}"
    )


def test_env_polyfill_renew_inside_atbegindocument(tmp_path: Path) -> None:
    """站点裹在 ``\\AtBeginDocument{...}`` 实参里 —— 行首锚前置落活区,
    hook 执行时 env 已定义。"""
    _write_main(
        tmp_path,
        "\\AtBeginDocument{\\renewenvironment{proof}{}{}}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment proof undefined.\n"
    )
    ok, _note = TRANSFORM_FNS["undefined_env_polyfill"](
        mk_ctx(tmp_path), None, "proof", {}
    )
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert t.index("\\ifcsname proof\\endcsname") < t.index("\\AtBeginDocument")


def test_env_polyfill_renew_site_no_double_prepend(tmp_path: Path) -> None:
    """再点火幂等: 首轮站点前置+批扩已全覆盖 (lemma 在批扩面),
    二轮拒修且 proof 站点守卫不重复前置。"""
    _write_main(
        tmp_path,
        "\\renewenvironment{proof}{}{}\n"
        "\\begin{document}\n"
        "\\begin{proof}p\\end{proof}\n"
        "\\begin{lemma}l\\end{lemma}\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment proof undefined.\n"
    )
    ctx = mk_ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["undefined_env_polyfill"](ctx, None, "proof", {})
    assert ok
    (tmp_path / "main.log").write_text(
        "main.tex:4: LaTeX Error: Environment lemma undefined.\n"
    )
    ctx.invalidate(tmp_path / "main.log")
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](ctx, None, "lemma", {})
    assert not ok
    assert "already polyfilled" in note
    t = (tmp_path / "main.tex").read_text()
    assert t.count("\\ifcsname proof\\endcsname") == 1


# ─── undefined_env_polyfill: \QED 对偶件臂 (0707.1588) ───


def test_env_polyfill_proof_qed_companion_batch(tmp_path: Path) -> None:
    """proof 批扩 + 源内 ``\\QED`` 在用 → 同块补 ``\\providecommand{\\QED}``
    (amsthm 对偶件, 省一轮 undefined_cs)。"""
    _write_main(
        tmp_path,
        "\\begin{document}\n\\begin{proof}body \\QED\\end{proof}\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment proof undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        mk_ctx(tmp_path), None, "proof", {}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\providecommand{\\QED}" in t
    assert "\\hfil\\vrule" in t  # amsthm \qedsymbol 形开口盒
    assert t.index("\\providecommand{\\QED}") < t.index("\\begin{document}")


def test_env_polyfill_renew_site_qed_companion(tmp_path: Path) -> None:
    """站点前置块同样携 ``\\QED`` stub —— 序言 ``\\renewenvironment`` +
    body ``\\QED`` 用 (0707.1588 IEEEtran 形)。"""
    _write_main(
        tmp_path,
        "\\renewenvironment{proof}{}{}\n"
        "\\begin{document}\n"
        "\\begin{proof}body \\QED\\end{proof}\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment proof undefined.\n"
    )
    ok, _note = TRANSFORM_FNS["undefined_env_polyfill"](
        mk_ctx(tmp_path), None, "proof", {}
    )
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert t.index("\\providecommand{\\QED}") < t.index("\\renewenvironment{proof}")


def test_env_polyfill_no_qed_companion_without_use(tmp_path: Path) -> None:
    """proof polyfill 但源无 ``\\QED`` → 不补 stub (证据门, 免死代码)。"""
    _write_main(
        tmp_path,
        "\\begin{document}\n\\begin{proof}b\\end{proof}\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment proof undefined.\n"
    )
    ok, _note = TRANSFORM_FNS["undefined_env_polyfill"](
        mk_ctx(tmp_path), None, "proof", {}
    )
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\providecommand{\\QED}" not in t


def test_env_polyfill_qed_companion_independent_env(tmp_path: Path) -> None:
    """``\\QED`` 在用但缺的是 sidebar (非 proof) → 不补 ``\\QED`` stub。"""
    _write_main(
        tmp_path,
        "\\begin{document}\n\\begin{sidebar}s\\end{sidebar} \\QED\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment sidebar undefined.\n"
    )
    ok, _note = TRANSFORM_FNS["undefined_env_polyfill"](
        mk_ctx(tmp_path), None, "sidebar", {}
    )
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\providecommand{\\QED}" not in t


def test_cs_targeted_fix_qed_polyfill(tmp_path: Path) -> None:
    """独立 ``undefined_cs:\\QED`` (proof 已定义稿) → 95-targeted.yaml
    ``cs_table.QED`` polyfill 经 cs_targeted_fix 注入开口盒 stub。"""
    _write_main(tmp_path, "\\begin{document}\nx \\QED\n\\end{document}\n")
    params = dict(rule("cs_targeted_fix").action.get("params") or {})
    assert "QED" in (params.get("cs_table") or {})
    ok, note = TRANSFORM_FNS["cs_targeted_fix"](mk_ctx(tmp_path), None, "QED", params)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\providecommand{\\QED}" in t
    assert "\\hfil\\vrule" in t


# ─── undefine_for_redef: 批量 + 站点前置 + other 签 ───


def test_undefine_batch_journal_cluster(tmp_path: Path) -> None:
    """1206.0299 形 (halt_on_error 实证): log 只报首撞名 \\aj, 同文件
    \\newcommand 站点簇扩 → 一轮全清 (站点前置, 不靠多行 log)。"""
    _write_main(
        tmp_path,
        "\\newcommand{\\aj}{AJ}\n"
        "\\newcommand{\\jcap}{JCAP}\n"
        "\\newcommand{\\mnras}{MNRAS}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "odg.tex:221: LaTeX Error: Command \\aj already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        mk_ctx(tmp_path), None, "aj", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    for cs in ("aj", "jcap", "mnras"):
        assert f"\\csname {cs}\\endcsname\\TeXlateUndefCs" in t, cs
    # 站点前置在 \newcommand 行紧邻处
    assert (
        "\\expandafter\\let\\csname mnras\\endcsname\\TeXlateUndefCs\n"
        "\\newcommand{\\mnras}" in t
    )


def test_undefine_batch_multiline_log_still_batch(tmp_path: Path) -> None:
    """非 halt 轮 (post-verify/salvage) 多行 log: 撞名集全扫仍一轮批清。"""
    _write_main(
        tmp_path,
        "\\newcommand{\\aj}{AJ}\n"
        "\\newcommand{\\jcap}{JCAP}\n"
        "\\newcommand{\\mnras}{MNRAS}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "odg.tex:221: LaTeX Error: Command \\aj already defined.\n"
        "odg.tex:222: LaTeX Error: Command \\jcap already defined.\n"
        "odg.tex:226: LaTeX Error: Command \\mnras already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        mk_ctx(tmp_path), None, "aj", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    for cs in ("aj", "jcap", "mnras"):
        assert f"\\csname {cs}\\endcsname\\TeXlateUndefCs" in t, cs


def test_undefine_batch_single_collision_declines(tmp_path: Path) -> None:
    """min_batch=2 门: 孤站单撞名格 (文件仅一处站点) 让位 renew(111)。"""
    _write_main(
        tmp_path,
        "\\newcommand{\\Ref}[1]{(\\ref{#1})}\n\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\Ref already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        mk_ctx(tmp_path), None, "Ref", {"min_batch": 2}
    )
    assert not ok
    assert "<2" in note  # 撞名∪站点兄弟 <2 → 单撞名路径


def test_undefine_single_default_path(tmp_path: Path) -> None:
    """缺省 min_batch=1 (already_def_undefine@113 路径) —— 单撞名仍修。"""
    _write_main(
        tmp_path,
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\liningnums already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        mk_ctx(tmp_path), None, "liningnums", {}
    )
    assert ok, note
    assert (
        "\\csname liningnums\\endcsname\\TeXlateUndefCs"
        in (tmp_path / "main.tex").read_text()
    )


def test_undefine_backtick_other_signature(tmp_path: Path) -> None:
    r"""astro-ph/0408445 形: ``Command `\X' already defined`` 反引号签
    (taxonomy 落 other, payload=None → min_batch 恒 1); halt 单行 log
    只见 \\mathbfit, 站点簇扩把 \\mathbfss 同轮清。"""
    _write_main(
        tmp_path,
        "\\usepackage{bm}\n"
        "\\DeclareMathAlphabet{\\mathbfit}{OT1}{cmm}{b}{it}\n"
        "\\DeclareMathAlphabet{\\mathbfss}{OT1}{cmss}{bx}{n}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "PolarShapelets.tex:342: LaTeX Error: Command `\\mathbfit' already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        mk_ctx(tmp_path), None, None, {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert (
        "\\expandafter\\let\\csname mathbfit\\endcsname\\TeXlateUndefCs\n"
        "\\DeclareMathAlphabet{\\mathbfit}" in t
    )
    assert "\\csname mathbfss\\endcsname\\TeXlateUndefCs" in t


def test_undefine_allocated_name_guard(tmp_path: Path) -> None:
    """2211.04482 护栏: \\newbox\\splitbox 分配名 → 弃修 (Let 后名被抢占炸 Missing number)。"""
    _write_main(
        tmp_path,
        "\\newbox\\splitbox\n\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\splitbox already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](mk_ctx(tmp_path), None, "splitbox", {})
    assert not ok
    assert "allocated" in note  # 与 bblwall 钉同一 abstain 注记面


def test_undefine_cls_site_no_catcode_wrap(tmp_path: Path) -> None:
    r"""1706.00221 实证: 站点前置全局统一 csname-let 形 (零字面 ``@``
    免 catcode); 包文件内 ``\\makeatother`` 尾注会把 @ 翻回 catcode-12,
    其后 ``\\define@key`` 族全烂 —— 故永不再用 ``\\makeatletter`` 对。"""
    _write_main(tmp_path, "\\begin{document}\nx\n\\end{document}\n")
    (tmp_path / "foo.cls").write_text(
        "\\newcommand{\\aj}{AJ}\n\\newcommand{\\jcap}{J}\n\\def\\define@key#1{#1}\n",
    )
    (tmp_path / "main.log").write_text(
        "foo.cls:1: LaTeX Error: Command \\aj already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        mk_ctx(tmp_path), None, "aj", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "foo.cls").read_text()
    assert (
        "\\expandafter\\let\\csname aj\\endcsname\\TeXlateUndefCs\n"
        "\\newcommand{\\aj}" in t
    )
    assert (
        "\\expandafter\\let\\csname jcap\\endcsname\\TeXlateUndefCs\n"
        "\\newcommand{\\jcap}" in t
    )
    assert "makeatletter" not in t
    assert "makeatother" not in t


def test_undefine_theorem_style_payload_dropped(tmp_path: Path) -> None:
    """Theorem-style payload (plain, 非 cs) 不在 Command 扫集 → 丢弃只信 log。"""
    _write_main(tmp_path, "\\begin{document}\nx\n\\end{document}\n")
    (tmp_path / "main.log").write_text(
        "ntheorem.sty:524: LaTeX Error: Theorem style plain already defined.\n"
        "main.tex:9: LaTeX Error: Command \\foo already defined.\n"
        "main.tex:10: LaTeX Error: Command \\bar already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        mk_ctx(tmp_path), None, "plain", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\csname plain\\endcsname" not in t  # 非 Command 签 payload 不送信
    assert "\\csname foo\\endcsname\\TeXlateUndefCs" in t
    assert "\\csname bar\\endcsname\\TeXlateUndefCs" in t


def test_undefine_site_prepend_idempotent(tmp_path: Path) -> None:
    """二轮: 站点已有 \\let 前置 + docclass 块已注 → applied=False。"""
    _write_main(
        tmp_path,
        "\\newcommand{\\aj}{AJ}\n\\newcommand{\\mnras}{M}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\aj already defined.\n"
        "main.tex:2: LaTeX Error: Command \\mnras already defined.\n"
    )
    ctx = mk_ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["undefine_for_redef"](ctx, None, "aj", {"min_batch": 2})
    assert ok
    ok, note = TRANSFORM_FNS["undefine_for_redef"](ctx, None, "aj", {"min_batch": 2})
    assert not ok
    assert "already cleared" in note


# ─── W151: end* 恒拒名形 (\@ifdefinable \@qend 前缀拒, 与定义态无关) ───


def test_undefine_endstar_provide_site_rc_bypass(tmp_path: Path) -> None:
    r"""W151 主钉 (o2-stub-fill ``\providecommand{\endproof}`` r1→r2 死循环
    实证): undefined 态 ``\endproof`` + provide 站点 → ``\@ifdefinable``
    恒炸 already_def; undefine 清位徒劳。
    end* 名 × ``\@ifdefinable`` 路由命令 → rc@ 单发旁路前置。"""
    _write_main(
        tmp_path,
        "\\providecommand{\\endproof}{\\endtrivlist}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\endproof already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](mk_ctx(tmp_path), None, "endproof", {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert (
        "\\expandafter\\let\\csname @ifdefinable\\expandafter\\endcsname"
        "\\csname @rc@ifdefinable\\endcsname\n\\providecommand{\\endproof}" in t
    )
    # 恒拒名不注无效的清位 (docclass 块亦不收)
    assert "\\csname endproof\\endcsname" not in t


def test_undefine_endstar_newcommand_batch_mixed(tmp_path: Path) -> None:
    r"""end* + 非 end* 混合撞名批清: ``\newcommand{\endproof}`` 站走 rc@,
    ``\newcommand{\aj}`` 站仍走 undefine; end* 名不进 docclass 块。"""
    _write_main(
        tmp_path,
        "\\newcommand{\\endproof}{P}\n\\newcommand{\\aj}{A}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\endproof already defined.\n"
        "main.tex:2: LaTeX Error: Command \\aj already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        mk_ctx(tmp_path), None, "endproof", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert (
        "\\expandafter\\let\\csname @ifdefinable\\expandafter\\endcsname"
        "\\csname @rc@ifdefinable\\endcsname\n\\newcommand{\\endproof}" in t
    )
    assert "\\csname aj\\endcsname\\TeXlateUndefCs" in t  # 非 end* 双修不变
    assert "\\csname endproof\\endcsname" not in t


def test_undefine_endstar_min_batch_collapses(tmp_path: Path) -> None:
    r"""孤站单 end* 撞名 (min_batch=2 门): renew(111) 对 undefined-end* 的
    ``\@ifundefined`` 报错在 halt_on_error 下同卡死 → 该名形不能让位,
    fire_set 含 end* 名即坍缩 min_batch=1 由批路径收。"""
    _write_main(
        tmp_path,
        "\\newcommand{\\endnote}{N}\n\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\endnote already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        mk_ctx(tmp_path), None, "endnote", {"min_batch": 2}
    )
    assert ok, note
    assert "\\csname @rc@ifdefinable\\endcsname" in (
        tmp_path / "main.tex"
    ).read_text()


def test_undefine_endstar_ltcmd_site_keeps_let(tmp_path: Path) -> None:
    r"""``\NewDocumentCommand`` 站 (ltcmd ``\cs_if_exist``, 无 end 守卫):
    end* 名仍走 undefine 清位 —— rc@ 前置不食 ``\@ifdefinable``
    会泄给下个用户。"""
    _write_main(
        tmp_path,
        "\\NewDocumentCommand{\\endnote}{}\n"
        "\\newcommand{\\aj}{A}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX cmd Error: Command '\\endnote' already defined.\n"
        "main.tex:2: LaTeX Error: Command \\aj already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](mk_ctx(tmp_path), None, "endnote", {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert (
        "\\expandafter\\let\\csname endnote\\endcsname\\TeXlateUndefCs\n"
        "\\NewDocumentCommand{\\endnote}" in t
    )


def test_undefine_endstar_siteless_declines(tmp_path: Path) -> None:
    r"""end* 撞名无站点可指 (包内/csname 构名) → 不注徒劳 ``\let`` (毁既有
    义且重定义侧仍恒拒) —— decline 交下位规则。"""
    _write_main(tmp_path, "\\begin{document}\nx\n\\end{document}\n")
    (tmp_path / "main.log").write_text(
        "pkg.sty:9: LaTeX Error: Command \\endfoo already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](mk_ctx(tmp_path), None, "endfoo", {})
    assert not ok
    assert "endfoo" in note
    assert "\\csname endfoo\\endcsname" not in (tmp_path / "main.tex").read_text()


def test_undefine_relax_reserved_abstains(tmp_path: Path) -> None:
    r"""``\@qrelax`` 同恒拒 + ``\relax`` 是 primitive: undefine 清位
    注毁其义, rc@ 旁路真重定义 —— 皆全局灾难, 弃修。"""
    _write_main(
        tmp_path,
        "\\newcommand{\\relax}{X}\n\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\relax already defined.\n"
    )
    ok, _note = TRANSFORM_FNS["undefine_for_redef"](mk_ctx(tmp_path), None, "relax", {})
    assert not ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\csname relax\\endcsname" not in t
    assert "rc@ifdefinable" not in t


def test_undefine_endstar_provide_nonendstar_untouched(tmp_path: Path) -> None:
    r"""非 end* 名 ``\providecommand`` 站点不入列: 撞名静默族前置清位反夺
    cls 定义 —— guilty 文件内 ``\providecommand{\foo}`` 不吃 prepend。"""
    _write_main(
        tmp_path,
        "\\providecommand{\\foo}{F}\n\\newcommand{\\aj}{A}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Command \\aj already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](mk_ctx(tmp_path), None, "aj", {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\csname aj\\endcsname\\TeXlateUndefCs" in t
    assert "\\csname foo\\endcsname" not in t  # provide 站点非恒拒名 —— 不动


def test_undefine_endstar_rc_prepend_idempotent(tmp_path: Path) -> None:
    """二轮: rc@ 前置已见 (64 字窗幂等) → applied=False 不占轮次。"""
    _write_main(
        tmp_path,
        "\\providecommand{\\endproof}{P}\n\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\endproof already defined.\n"
    )
    ctx = mk_ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["undefine_for_redef"](ctx, None, "endproof", {})
    assert ok
    ok, note = TRANSFORM_FNS["undefine_for_redef"](ctx, None, "endproof", {})
    assert not ok
    assert "endproof" in note  # end* 无新站点可做 → defer 注记


# ─── font_cs_shim (AMS 上古字体 cs) ───


def test_font_cs_shim_skewchar_chain(tmp_path: Path) -> None:
    r"""hep-th/9703214 形: \\doit{0} 死块内 \\font 定义不执行 →
    活 \\skewchar\\fivmi 链 undefined_cs → \\font\\fivmi=cmmi10 at 5pt 注入
    (eng=None 不可探 tfm → at-尺寸兜底)。"""
    _write_main(
        tmp_path,
        "\\def\\doit#1#2{\\ifnum#1>0 #2\\fi}\n"
        "\\doit{0}{\\font\\fivmi=cmmi5 \\font\\fivsy=cmsy5}\n"
        "\\begin{document}\n\\skewchar\\fivmi=127 \\skewchar\\fivsy=48 x\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:4: Undefined control sequence.\nl.4 \\skewchar\\fivmi\n"
        "main.tex:4: Undefined control sequence.\nl.4 \\skewchar\\fivsy\n"
    )
    ok, note = TRANSFORM_FNS["font_cs_shim"](mk_ctx(tmp_path), None, "fivmi", {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\font\\fivmi=cmmi10 at 5pt" in t
    assert "\\font\\fivsy=cmsy10 at 5pt" in t


def test_font_cs_shim_nonfont_payload_declines(tmp_path: Path) -> None:
    """窄谓词: payload 不匹 <size><fam> 模式 → 落穿 cs_targeted_fix/guess。"""
    _write_main(tmp_path, "\\begin{document}\n\\textbf x\n\\end{document}\n")
    (tmp_path / "main.log").write_text(
        "main.tex:2: Undefined control sequence.\nl.2 \\textbf\n"
    )
    ok, note = TRANSFORM_FNS["font_cs_shim"](mk_ctx(tmp_path), None, "textbf", {})
    assert not ok
    assert "not an AMS-era font name" in note


def test_font_cs_shim_def_evidence_excluded(tmp_path: Path) -> None:
    """<size><fam> 名若另有 \\def 系定义证据 → 不接管 (真宏撞名防毁)。"""
    _write_main(
        tmp_path,
        "\\def\\tenbf{bold macro}\n\\begin{document}\n\\textfont9=\\tenbf\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text("")  # log 无 undefined 报错
    ok, note = TRANSFORM_FNS["font_cs_shim"](mk_ctx(tmp_path), None, "tenbf", {})
    assert not ok
    assert "no AMS font cs" in note


def test_font_cs_shim_idempotent(tmp_path: Path) -> None:
    """二轮: \\font\\<cs>= 已在文本且该 cs 本轮未报错 → applied=False。"""
    _write_main(
        tmp_path,
        "\\begin{document}\n\\skewchar\\ninmi=60 x\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: Undefined control sequence.\nl.2 \\skewchar\\ninmi\n"
    )
    ctx = mk_ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["font_cs_shim"](ctx, None, "ninmi", {})
    assert ok
    # 二轮 log 无报错 (清干净后) → pos_used 名有活 \\font 定义 → 跳
    (tmp_path / "main.log").write_text("This is XeTeX log — clean\n")
    ctx.invalidate(tmp_path / "main.log")
    ok, note = TRANSFORM_FNS["font_cs_shim"](ctx, None, "ninmi", {})
    assert not ok
    assert "already shimmed" in note


# ─── cs_rebind (produced-by-cs 缺字) ───


def test_cs_rebind_section_sign(tmp_path: Path) -> None:
    r"""2403.15096 形: \\S→§ 在 cmr10 缺字, 源无字面 § →
    \\protected\\def\\S 绑 txlatefallback。"""
    _write_main(
        tmp_path,
        "\\begin{document}\nSee \\S 7 and \\S 9 for details.\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        'Missing character: There is no § ("A7) in font cmr10!\n'
    )
    ok, note = TRANSFORM_FNS["cs_rebind"](mk_ctx(tmp_path), None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\newfontfamily\\txlatefallback{Libertinus Serif}" in t
    assert "\\protected\\def\\S{\\ifmmode\\mbox{\\txlatefallback §}" in t


def test_cs_rebind_literal_char_owns(tmp_path: Path) -> None:
    """字面 § 在源 → literal 面 (missing_char_fix/font_fallback) 先修, 本规退。"""
    _write_main(
        tmp_path,
        "\\begin{document}\nSee § 7 and \\S 9.\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        'Missing character: There is no § ("A7) in font cmr10!\n'
    )
    ok, note = TRANSFORM_FNS["cs_rebind"](mk_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no produced-by-cs" in note


def test_cs_rebind_no_producer_declines(tmp_path: Path) -> None:
    """缺字码位无 cs 生产者 (源无 \\o) → 不落本规。"""
    _write_main(tmp_path, "\\begin{document}\nplain text\n\\end{document}\n")
    (tmp_path / "main.log").write_text(
        'Missing character: There is no ø ("F8) in font cmr9!\n'
    )
    ok, note = TRANSFORM_FNS["cs_rebind"](mk_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no produced-by-cs" in note


def test_cs_rebind_producers_param(tmp_path: Path) -> None:
    """params.producers hex 键扩面: 0x2022(\\bullet 产出)→\\textbullet 式 cs。"""
    _write_main(
        tmp_path,
        "\\begin{document}\n\\mydotsep item\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        'Missing character: There is no • ("2022) in font cmr10!\n'
    )
    ok, note = TRANSFORM_FNS["cs_rebind"](
        mk_ctx(tmp_path), None, None, {"producers": {"2022": "mydotsep"}}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\protected\\def\\mydotsep" in t
    assert "•" in t


def test_cs_rebind_idempotent(tmp_path: Path) -> None:
    """二轮: 注入块自带字面 ø → ``ch in blob`` 先行短路 → applied=False 不重注。"""
    _write_main(
        tmp_path,
        "\\begin{document}\nFr\\o{}berg\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        'Missing character: There is no ø ("F8) in font cmr9!\n'
    )
    ctx = mk_ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["cs_rebind"](ctx, None, None, {})
    assert ok
    ok, _note = TRANSFORM_FNS["cs_rebind"](ctx, None, None, {})
    assert not ok
    t = (tmp_path / "main.tex").read_text()
    assert t.count("\\protected\\def\\o") == 1  # 不重注


# ─── 注册/装载面 (本批) ───


def test_bcs_builtins_registered() -> None:
    """本批三个新 builtin + 复用 undefine_for_redef 均注册进 TRANSFORM_FNS。"""
    for name in (
        "undefined_env_polyfill",
        "font_cs_shim",
        "cs_rebind",
        "undefine_for_redef",
    ):
        assert callable(TRANSFORM_FNS[name])


def test_bcs_rule_ids_in_ruleset() -> None:
    """四条新规则 id 在合并 ruleset 内且 function/序位对上。"""
    by_id = {r.id: r for r in rs().rules}
    want = {
        "missing_char_cs_rebind": "cs_rebind",
        "already_def_batch_undefine": "undefine_for_redef",
        "ams_font_cs_shim": "font_cs_shim",
        "undefined_env_polyfill": "undefined_env_polyfill",
    }
    for rid, fn in want.items():
        assert rid in by_id, rid
        assert (by_id[rid].raw.get("action") or {}).get("function") == fn
    # 序位钉: 批清位在 renew(111) 前; cs_rebind 在 font_fallback(26) 前;
    # font shim 在 cs_targeted_fix(165) 前; env polyfill 在 abstract(168) 后
    orders = {rid: r.order for rid, r in by_id.items()}
    assert orders["already_def_batch_undefine"] < orders["already_def_newcmd_renew"]
    assert orders["missing_char_cs_rebind"] < orders["font_fallback"]
    assert orders["ams_font_cs_shim"] < orders["cs_targeted_fix"]
    assert orders["undefined_env_polyfill"] > orders["abstract_frontmatter_hoist"]
