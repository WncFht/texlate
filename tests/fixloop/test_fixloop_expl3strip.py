r"""expl3fix 车道 (2026-09-19): ``expl3_driver_opt_strip`` 逗号粘连修复钉。

批二四格 (0905.4874/1306.0364/hep-ph/0501170/hep-ph/9910403) 同形:
documentclass 全局驱动选项 (dvips/pdftex 系) 灌进 expl3 后端探测 →
"Backend request inconsistent with engine: using 'xetex'"。旧单正则
``,?driver,?`` 双吃两侧逗号, 中段剥除把邻项粘成幻影选项
(``[final,pdftex,reqno,...]`` → ``[finalreqno,...]``)。修复 = 表首/
表内/表尾三态拆分 (hyperref_driver_neutralize 形, 锚消费单遍);
corpus 普查驱动词恒单枚, 残余面=同表非连排多驱动词 (known_gap)。
"""

from pathlib import Path

from _fixloopkit import apply, mk_ctx, rule

from texlate.compile.fixloop import actions

_RID = "expl3_driver_opt_strip"


def _apply(tmp_path: Path) -> tuple[bool, str]:
    return apply(_RID, mk_ctx(tmp_path), None)


def _roundtrip(tmp_path: Path, docclass_line: str) -> str:
    (tmp_path / "main.tex").write_text(
        f"{docclass_line}\n\\begin{{document}}\nx\n\\end{{document}}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path)
    assert ok, note
    return (tmp_path / "main.tex").read_text().splitlines()[0]


def test_expl3strip_rule_registered() -> None:
    r = rule(_RID)
    assert r.order == 35  # noqa: PLR2004 - schema 断言值
    assert r.phase == "loop"
    assert r.when["category"] == "expl3_backend"
    assert r.action["kind"] == "regex_rewrite"
    assert r.action["params"]["exts"] == [".tex"]
    assert len(r.action["params"]["rewrites"]) == 4  # noqa: PLR2004


def test_expl3strip_when_gate_declines_other_categories(tmp_path: Path) -> None:
    """签名缺席: category != expl3_backend → when 闸拒 (本规则无 condition)。"""
    r = rule(_RID)
    ctx = mk_ctx(tmp_path)
    assert actions._when_ok(r.when, "expl3_backend", None, ctx)  # noqa: SLF001
    for cat in ("hyperref_driver", "other", "pdftex_prim", None):
        assert not actions._when_ok(r.when, cat, None, ctx)  # noqa: SLF001


def test_expl3strip_declines_no_driver_options(tmp_path: Path) -> None:
    """源面无驱动选项 → 0 文件改写, applied=False (不烧 applied 配额)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass[final,reqno,a4paper,12pt]{myectaart}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(tmp_path)
    assert not ok
    assert "final,reqno" in (tmp_path / "main.tex").read_text()


def test_expl3strip_target_cells_docclass(tmp_path: Path) -> None:
    """四格 docclass 行原样钉——1306.0364 是旧规则的粘逗号现场。"""
    cells = {
        "0905.4874": (
            "\\documentclass[dvips,aap]{imsart}",
            "\\documentclass[aap]{imsart}",
        ),
        "1306.0364": (
            "\\documentclass[final,pdftex,reqno,a4paper,12pt]{myectaart}",
            "\\documentclass[final,reqno,a4paper,12pt]{myectaart}",
        ),
        "hep-ph/0501170": (
            "\\documentclass[dvips,12pt,a4paper]{article}",
            "\\documentclass[12pt,a4paper]{article}",
        ),
        "hep-ph/9910403": (
            "\\documentclass[dvips,12pt,a4paper]{article}",
            "\\documentclass[12pt,a4paper]{article}",
        ),
    }
    for cell, (src, want) in cells.items():
        assert _roundtrip(tmp_path, src) == want, cell


def test_expl3strip_head_mid_tail_solo(tmp_path: Path) -> None:
    """位置三态 + 独占括号: 无粘连, 无孤儿逗号/空括号。"""
    cases = {
        "\\documentclass[pdftex,12pt]{article}": "\\documentclass[12pt]{article}",
        "\\documentclass[12pt,pdftex,a4paper]{article}": (
            "\\documentclass[12pt,a4paper]{article}"
        ),
        "\\documentclass[12pt,pdftex]{article}": "\\documentclass[12pt]{article}",
        "\\documentclass[dvips]{article}": "\\documentclass{article}",
        "\\documentclass[dvips,]{article}": "\\documentclass{article}",
        "\\documentclass[12pt,dvips,]{article}": "\\documentclass[12pt]{article}",
    }
    for src, want in cases.items():
        assert _roundtrip(tmp_path, src) == want, src


def test_expl3strip_multiple_drivers_all_stripped(tmp_path: Path) -> None:
    """连排多驱动词单遍全剥 (非连排残余见规则 known_gap)。"""
    cases = {
        "\\documentclass[dvips,pdftex,12pt]{article}": "\\documentclass[12pt]{article}",
        "\\documentclass[12pt,dvips,pdftex]{article}": "\\documentclass[12pt]{article}",
        "\\documentclass[dvips,dvipdfmx]{article}": "\\documentclass{article}",
        "\\documentclass[dvips,12pt,pdftex]{article}": "\\documentclass[12pt]{article}",
    }
    for src, want in cases.items():
        assert _roundtrip(tmp_path, src) == want, src


def test_expl3strip_corpus_shapes(tmp_path: Path) -> None:
    """corpus 普查实证形: sn-* / lineno / 长尾中段 / 名单尾位。"""
    cases = {
        "\\documentclass[pdflatex,sn-basic]{svjour3}": "\\documentclass[sn-basic]{svjour3}",
        "\\documentclass[lineno,pdflatex,sn-basic]{svjour3}": (
            "\\documentclass[lineno,sn-basic]{svjour3}"
        ),
        "\\documentclass[preprints,article,submit,pdftex,moreauthors]{mdpi}": (
            "\\documentclass[preprints,article,submit,moreauthors]{mdpi}"
        ),
        "\\documentclass[11pt,dvips]{article}": "\\documentclass[11pt]{article}",
        "\\documentclass[aoas,MSNbibl,nameyear,dvips]{imsart}": (
            "\\documentclass[aoas,MSNbibl,nameyear]{imsart}"
        ),
    }
    for src, want in cases.items():
        assert _roundtrip(tmp_path, src) == want, src


def test_expl3strip_non_driver_options_untouched(tmp_path: Path) -> None:
    """非驱动选项原样; \\b 词界挡 dvipsnames/xcolor=pdftex/dvips-x 伪命中。"""
    for src in (
        "\\documentclass[final,reqno,a4paper,12pt]{myectaart}",
        "\\documentclass[12pt,dvips-x]{article}",
        "\\documentclass[draft]{article}",
        "\\documentclass[sigconf,noacm,dvipsnames]{acmart}",
        "\\documentclass[xcolor=pdftex,usenames,dvipsnames,table]{beamer}",
    ):
        (tmp_path / "main.tex").write_text(
            f"{src}\n\\begin{{document}}\nx\n\\end{{document}}\n",
            encoding="utf-8",
        )
        ok, _ = _apply(tmp_path)
        assert not ok, src
        assert (tmp_path / "main.tex").read_text().startswith(src)


def test_expl3strip_usepackage_drivers_out_of_scope(tmp_path: Path) -> None:
    """作用域钉死 documentclass: usepackage 驱动表不碰 (爆半径守恒)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass[12pt]{article}\n"
        "\\usepackage[dvips]{graphicx}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(tmp_path)
    assert not ok
    assert "\\usepackage[dvips]{graphicx}" in (tmp_path / "main.tex").read_text()


def test_expl3strip_whitespace_shapes(tmp_path: Path) -> None:
    """\\documentclass 与括号间空白/选项内空格/换行表 均剥净。"""
    cases = {
        "\\documentclass [dvips,12pt]{article}": "\\documentclass [12pt]{article}",
        "\\documentclass[ dvips , 12pt ]{article}": "\\documentclass[ 12pt ]{article}",
        "\\documentclass[\n dvips,\n 12pt\n]{article}": (
            "\\documentclass[\n 12pt\n]{article}"
        ),
    }
    for src, want in cases.items():
        (tmp_path / "main.tex").write_text(
            f"{src}\n\\begin{{document}}\nx\n\\end{{document}}\n",
            encoding="utf-8",
        )
        ok, note = _apply(tmp_path)
        assert ok, note
        got = (tmp_path / "main.tex").read_text().split("\\begin{document}")[0]
        assert got == f"{want}\n", src


def test_expl3strip_idempotent_second_round(tmp_path: Path) -> None:
    """剥净后无残留驱动词 → 第二轮 applied=False (幂等)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass[final,pdftex,reqno]{myectaart}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(tmp_path)
    assert ok
    ok, _ = _apply(tmp_path)
    assert not ok
