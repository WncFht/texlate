"""``match_surface: masked`` —— rewrite 条目遮盖面匹配机制钉。

机制 (actions._masked_sub): ``mask_tex`` 等长视图 finditer → span 回切
原文右→左拼接。注释/逐字/失活区在视图中是等长空白, pattern 必要内容
无法锚在其中——natbib_numbers_pass 注释行 ``\\begin{document}`` 裂伤
(astro-ph/0307344 ms.tex:172/198, begindoc_tail_recomment 收伤规则尚在)
的类级根修。字段逐条 opt-in, 缺席走原文 ``sub`` 零行为差。
"""

from pathlib import Path

import pytest

from texlate.compile.fixloop import actions
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.fixloop.ruleset import (
    Ruleset,
    RulesetError,
    load_ruleset,
)
from texlate.compile.logparse import ErrReport


class _Eng:
    """regex_rewrite 路径的最小引擎替身 (该 kind 不触 probe/install)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex")


def _rewrite_rule(rewrites: list[dict]) -> Rule:
    return Rule(
        {
            "id": "t_mask",
            "phase": "loop",
            "when": {"always": True},
            "action": {
                "kind": "regex_rewrite",
                "params": {"exts": [".tex"], "rewrites": rewrites},
            },
        }
    )


def _apply(rule: Rule, ctx: LoopCtx) -> tuple[bool, str]:
    return actions._apply(rule, ctx, _Eng(), None, ErrReport())  # noqa: SLF001


_BEGINDOC_RW = {
    "pattern": "(\\\\begin\\{document\\})",
    "repl": "INJ\n\\g<0>",
}


def test_masked_skips_comment_match(tmp_path: Path) -> None:
    # (a) 注释行内 \begin{document} 不改写——astro-ph/0307344 裂伤形态
    (tmp_path / "main.tex").write_text(
        "% see \\begin{document} for details\n\\begin{document}\nx\n"
    )
    ok, note = _apply(
        _rewrite_rule([{**_BEGINDOC_RW, "match_surface": "masked"}]), _ctx(tmp_path)
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert t == "% see \\begin{document} for details\nINJ\n\\begin{document}\nx\n"


def test_raw_default_still_matches_in_comments(tmp_path: Path) -> None:
    # (b) 不带字段 → 原文 sub 旧行为保留 (注释内照常命中——潜伏面钉档)
    (tmp_path / "main.tex").write_text("% \\begin{document} noted\n")
    ok, note = _apply(_rewrite_rule([dict(_BEGINDOC_RW)]), _ctx(tmp_path))
    assert ok, note
    assert (tmp_path / "main.tex").read_text() == "% INJ\n\\begin{document} noted\n"


def test_masked_skips_verbatim_and_dead_env(tmp_path: Path) -> None:
    # 遮盖面不止注释: verbatim 体/comment.sty 失活环境体同样不命中
    (tmp_path / "main.tex").write_text(
        "\\begin{verbatim}\n\\begin{document}\n\\end{verbatim}\n"
        "\\begin{comment}\n\\begin{document}\n\\end{comment}\n"
        "\\begin{document}\n"
    )
    ok, _ = _apply(
        _rewrite_rule([{**_BEGINDOC_RW, "match_surface": "masked"}]), _ctx(tmp_path)
    )
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert t.count("INJ\n\\begin{document}") == 1
    assert "\\begin{verbatim}\n\\begin{document}\n\\end{verbatim}" in t
    assert "\\begin{comment}\n\\begin{document}\n\\end{comment}" in t


def test_masked_multimatch_right_to_left_splice(tmp_path: Path) -> None:
    # (c) 含 \n 的 replacement 多命中右→左拼接: 前位 span 不因变长漂移
    (tmp_path / "main.tex").write_text(
        "\\begin{document}\na\n"
        "% \\begin{document} fake\n"
        "\\begin{document}\nb\n"
        "\\begin{document}\n"
    )
    ok, _ = _apply(
        _rewrite_rule([{**_BEGINDOC_RW, "match_surface": "masked"}]), _ctx(tmp_path)
    )
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert t == (
        "INJ\n\\begin{document}\na\n"
        "% \\begin{document} fake\n"
        "INJ\n\\begin{document}\nb\n"
        "INJ\n\\begin{document}\n"
    )


def test_masked_repl_group_backrefs_expand(tmp_path: Path) -> None:
    # 视图 group 展开: 活面命中区与原文逐字节一致, \\g<1> 取回原文 token
    (tmp_path / "main.tex").write_text("x \\foo{bar} % \\foo{dead}\n")
    ok, _ = _apply(
        _rewrite_rule(
            [
                {
                    "pattern": "\\\\foo\\{(\\w+)\\}",
                    "repl": "[\\g<1>]",
                    "match_surface": "masked",
                }
            ]
        ),
        _ctx(tmp_path),
    )
    assert ok
    assert (tmp_path / "main.tex").read_text() == "x [bar] % \\foo{dead}\n"


def test_match_surface_roundtrip_loader() -> None:
    # (d) yaml 字段经 Ruleset 校验装载透传 → _compile_rewrites 拿到 masked 臂
    data = {
        "version": 1,
        "rules": [
            {
                "id": "r_masked",
                "phase": "loop",
                "when": {"always": True},
                "action": {
                    "kind": "regex_rewrite",
                    "params": {
                        "rewrites": [{**_BEGINDOC_RW, "match_surface": "masked"}]
                    },
                },
            }
        ],
    }
    rule = Ruleset(data).rules[0]
    rws = rule.action["params"]["rewrites"]
    assert rws[0]["match_surface"] == "masked"
    subs = actions._compile_rewrites(rws)  # noqa: SLF001
    assert subs[0][2] is True


def test_match_surface_invalid_value_rejected() -> None:
    # typo 值装载期拦 (fail-closed)——静默退 raw 与 categry: 同类 fail-open
    data = {
        "version": 1,
        "rules": [
            {
                "id": "r_bad",
                "phase": "loop",
                "when": {"always": True},
                "action": {
                    "kind": "regex_rewrite",
                    "params": {
                        "rewrites": [{**_BEGINDOC_RW, "match_surface": "maskd"}]
                    },
                },
            }
        ],
    }
    with pytest.raises(RulesetError, match="match_surface"):
        Ruleset(data)


def test_natbib_numbers_pass_opted_in() -> None:
    # 真实规则库: natbib_numbers_pass 全部 rewrite 条目已 opt-in
    rs = load_ruleset()
    rule = next(r for r in rs.phase("loop") if r.id == "natbib_numbers_pass")
    rws = rule.action["params"]["rewrites"]
    assert rws
    assert all(rw.get("match_surface") == "masked" for rw in rws)
