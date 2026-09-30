"""graphic_ext_relax — sibling_exts stem 域闸 + masked 改写面 (gfxrelax #229).

firedunfixed 普查: 旧 ``has_ext`` global-any 闸在工程内随便一张 .pdf 即
放行, 真缺件 (tar 未随图) 也剥名白烧一轮才轮到 order 17.6 占位臂。
新闸 ``fileset.sibling_exts``: payload 剥扩展名后的 basename stem 在
工程内存图形族交替件才点火 —— same-basename-anywhere 语义
(kpathsea TEXINPUTS 近似, 宁宽勿严)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.logparse import ErrReport

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.compile.fixloop.ruleset import Rule

_ERR = "LaTeX Error: File `{pay}' not found.\nSee the LaTeX manual ...\nl.7 \\includegraphics"


def _ctx(tmp_path: Path, files: dict[str, str], pay: str = "a.eps") -> LoopCtx:
    for rel, txt in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    return LoopCtx(
        wdir=tmp_path,
        engine_name="xelatex",
        main_rel="main.tex",
        err_head=_ERR.format(pay=pay),
    )


class _Eng:
    """regex_rewrite/condition 路径的最小引擎替身 (不触 probe/install)。"""

    name = "xelatex"
    caps = frozenset()

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return False

    def rebuild_fontmaps(self) -> bool:
        return True

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _rule(rid: str) -> Rule:
    return next(r for r in load_ruleset().rules if r.id == rid)


def _cond(ctx: LoopCtx, pay: str) -> tuple[bool, str]:
    rule = _rule("graphic_ext_relax")
    return actions._cond_ok(  # noqa: SLF001 - 钉条件原语直驱
        rule.condition, rule, ctx, _Eng(), pay, ErrReport()
    )


def _dispatch(ctx: LoopCtx, pay: str) -> tuple[Rule | None, str]:
    return actions._match_apply(  # noqa: SLF001 - 钉派发链直驱
        load_ruleset(), ctx, _Eng(), "missing_file", pay, ErrReport()
    )


_MAIN = (
    "\\documentclass{article}\n\\usepackage{graphicx}\n"
    "\\begin{document}\n\\includegraphics{FIGS/plot.eps}\n\\end{document}\n"
)


# ─────────────── condition: sibling_exts stem 域闸 ───────────────


def test_stem_with_pdf_sibling_passes(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"main.tex": _MAIN, "FIGS/plot.pdf": "%PDF fake"})
    ok, _why = _cond(ctx, "FIGS/plot.eps")
    assert ok


def test_stem_without_sibling_abstains(tmp_path: Path) -> None:
    # 工程内有无关 stem 的 .pdf —— global-any 时代会误放行, stem 域闸拒
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\begin{document}\n\\includegraphics{a.eps}\n\\end{document}\n"
            ),
            "unrelated.pdf": "%PDF fake",
        },
    )
    ok, why = _cond(ctx, "a.eps")
    assert not ok
    assert "sibling" in why


def test_basename_anywhere_counts(tmp_path: Path) -> None:
    # same-basename-anywhere (文档化宽语义): payload 带 figs/ 前缀,
    # sibling 在 other/ —— 仍算 (kpathsea 同名位近似, 宁宽勿严)
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": _MAIN.replace("FIGS/plot.eps", "figs/a.eps"),
            "other/a.pdf": "%PDF fake",
        },
    )
    ok, _why = _cond(ctx, "figs/a.eps")
    assert ok


def test_stem_case_insensitive(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": _MAIN.replace("FIGS/plot.eps", "plot.eps"),
            "PLOT.PDF": "%PDF fake",
        },
    )
    ok, _why = _cond(ctx, "plot.eps")
    assert ok


def test_hidden_and_engine_dirs_not_counted(tmp_path: Path) -> None:
    # ``.`` 前缀部件 + _texmf/_tect_out 封装树不计存活面 —
    # 每个隔离目录下只藏一件 sibling
    for hidden in (".git", "_texmf", "_tect_out"):
        wdir = tmp_path / f"case_{hidden.lstrip('.')}"
        wdir.mkdir(parents=True, exist_ok=True)
        (wdir / "main.tex").write_text(
            "\\documentclass{article}\n\\usepackage{graphicx}\n"
            "\\begin{document}\n\\includegraphics{a.eps}\n\\end{document}\n",
            encoding="utf-8",
        )
        d = wdir / hidden
        d.mkdir()
        (d / "a.pdf").write_text("%PDF fake", encoding="utf-8")
        ctx = _ctx(wdir, {}, pay="a.eps")
        ok, _why = _cond(ctx, "a.eps")
        assert not ok, f"{hidden} 内 sibling 不应计存活面"


def test_eps_converted_to_sibling_counts(tmp_path: Path) -> None:
    # epstopdf ``-eps-converted-to.pdf`` 转换件归一 <stem> 算 sibling —
    # 2308.04278 实证: system-model.eps 缺件但该命名件在盘时剥名是真解,
    # stem 严格相等会把 epstopdf 工程格饿死 (clean→partial 回归)
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": _MAIN.replace("FIGS/plot.eps", "system-model.eps"),
            "system-model-eps-converted-to.pdf": "%PDF fake",
        },
    )
    ok, _why = _cond(ctx, "system-model.eps")
    assert ok


def test_sibling_eps_family_counts(tmp_path: Path) -> None:
    # sibling 候选含 PS 族: a.ps 在盘 → 剥名后 graphicx 扩展表可达
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": _MAIN.replace("FIGS/plot.eps", "a.eps"),
            "a.ps": "%!PS-Adobe",
        },
    )
    ok, _why = _cond(ctx, "a.eps")
    assert ok


# ─────────────── dispatch: 点火/让位 ───────────────


def test_dispatch_relaxes_when_sibling_on_disk(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path, {"main.tex": _MAIN, "FIGS/plot.pdf": "%PDF fake"}, pay="FIGS/plot.eps"
    )
    rule, _note = _dispatch(ctx, "FIGS/plot.eps")
    assert rule is not None
    assert rule.id == "graphic_ext_relax"
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\includegraphics{FIGS/plot}" in text
    assert ".eps" not in text


def test_dispatch_falls_through_to_placeholder(tmp_path: Path) -> None:
    # 无 sibling → ext_relax 闸拒 → 同轮落到 17.6 占位臂 (饥饿解除)
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\begin{document}\n\\includegraphics{a.eps}\n\\end{document}\n"
            ),
            "unrelated.pdf": "%PDF fake",
        },
    )
    rule, _note = _dispatch(ctx, "a.eps")
    assert rule is not None
    assert rule.id == "graphic_missing_placeholder"
    assert (tmp_path / "a.eps").is_file()
    assert (tmp_path / "a.eps").read_text(encoding="utf-8").startswith("%!PS-Adobe")


def test_commented_site_not_rewritten(tmp_path: Path) -> None:
    # masked 面: 注释内引用点不改写不计命中 —— 活引用照剥, 死引用原样
    main = (
        "\\documentclass{article}\n\\usepackage{graphicx}\n"
        "\\begin{document}\n% \\includegraphics{a.eps}\n"
        "\\includegraphics{a.eps}\n\\end{document}\n"
    )
    ctx = _ctx(tmp_path, {"main.tex": main, "a.pdf": "%PDF fake"})
    rule, _note = _dispatch(ctx, "a.eps")
    assert rule is not None
    assert rule.id == "graphic_ext_relax"
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "% \\includegraphics{a.eps}" in text  # 注释位原样
    assert "\n\\includegraphics{a}\n" in text  # 活位剥名


def test_commented_only_site_declines_rewrite(tmp_path: Path) -> None:
    # payload 引用点全在注释内 → 改写 0 命中 → applied=False → 落到占位臂
    main = (
        "\\documentclass{article}\n\\usepackage{graphicx}\n"
        "\\begin{document}\n% \\includegraphics{a.eps}\n\\end{document}\n"
    )
    ctx = _ctx(tmp_path, {"main.tex": main, "a.pdf": "%PDF fake"})
    rule, _note = _dispatch(ctx, "a.eps")
    assert rule is not None
    assert rule.id == "graphic_missing_placeholder"
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "% \\includegraphics{a.eps}" in text
    assert (tmp_path / "a.eps").is_file()


def test_multi_ref_mixed(tmp_path: Path) -> None:
    # 双引用混合: payload a.eps 有 sibling → 只剥 a; other.eps 无 sibling
    # 原样保留 (payload 锚定不误吃), 其轮再由占位臂兜底
    main = (
        "\\documentclass{article}\n\\usepackage{graphicx}\n"
        "\\begin{document}\n\\includegraphics{a.eps}\n"
        "\\includegraphics{other.eps}\n\\end{document}\n"
    )
    ctx = _ctx(tmp_path, {"main.tex": main, "a.pdf": "%PDF fake"})
    rule, _note = _dispatch(ctx, "a.eps")
    assert rule is not None
    assert rule.id == "graphic_ext_relax"
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\includegraphics{a}" in text
    assert "\\includegraphics{other.eps}" in text  # 非 payload 引用不动
    # 次轮: other.eps 无 sibling → ext_relax 拒 → 占位臂收
    ctx2 = _ctx(tmp_path, {}, pay="other.eps")
    rule2, _note2 = _dispatch(ctx2, "other.eps")
    assert rule2 is not None
    assert rule2.id == "graphic_missing_placeholder"
    assert (tmp_path / "other.eps").is_file()


# ─────────────── 结构断言 ───────────────


def test_rule_sits_before_placeholder() -> None:
    ids = [r.id for r in load_ruleset().phase("loop")]
    assert ids.index("graphic_ext_relax") < ids.index("graphic_missing_placeholder")
