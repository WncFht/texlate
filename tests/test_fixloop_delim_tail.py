r"""csdelim lane (2026-09-19): ``cs_delim_tail_fix`` 走查单元。

``\def\X<lit>{...}`` —— TeX 解为 cs + 字面参数文本 (``\c3h2``/``\b0bmode``/
``\0cc``/``\ch3oh`` 伪多名宏, 化学/物理速写)。译者把尾中字母段当正文
吃掉 → 调用点不再带全尾 → "Use of \X doesn't match its definition"
(落 other 类)。修 = def 扫面 + 逐站补回: 乱序对齐全命中 REPLACE 损毁域,
部分证据 INSERT 残余尾, 零证据不动。规则钉随
``tmp/lane-csdefmismatch/delim-tail-rule.patch`` 落 (yaml + builtins 注册
原子应用, TRANSFORM_FNS 手工表无自动注册)。
"""

from pathlib import Path

from _fixloopkit import EngStub, mk_ctx

from texlate.compile.fixloop._builtins_docfix import (
    _DEF_TAIL_RE,
    cs_delim_tail_fix,
)

_ERR = "Use of \\c doesn't match its definition."


def _fix(tmp_path: Path, err_head: str = _ERR) -> tuple[bool, str]:
    return cs_delim_tail_fix(mk_ctx(tmp_path, err_head=err_head), EngStub(), None, {})


def test_def_tail_re() -> None:
    """``_DEF_TAIL_RE`` 各 def 形的 cs/尾配对。"""
    cases = {
        r"\def\c3h2{\mbox{C$_3$H$_2$}}": ("c", "3h2"),
        r"\def\b0bmode{$\bar{B}^0/B^0$}": ("b", "0bmode"),
        r"\def\0cc{$\Lambda = 0$}": ("0", "cc"),
        r"\def\ch3oh{CH$_3$OH}": ("ch", "3oh"),
        r"\long\def\a7x{y}": ("a", "7x"),
        r"\global\edef\z q{p}": ("z", "q"),
        r"\def\b{plain}": ("b", ""),
        r"\def\a#1{#1}": ("a", "#1"),
    }
    for src, want in cases.items():
        m = _DEF_TAIL_RE.search(src)
        assert m is not None, src
        assert m.group(1) == want[0], src
        assert m.group(2).strip() == want[1], src


def test_replace_full_align(tmp_path: Path) -> None:
    """1404.0519 / astro-ph-0408509 形: ``\\c3这是译文2`` → ``\\c3h2``。"""
    (tmp_path / "main.tex").write_text(
        "\\def\\c3h2{\\mbox{C$_3$H$_2$}}\n"
        "l-\\c3这是译文2\\ and c-\\c3这是译文2\\ ok.\n",
        encoding="utf-8",
    )
    applied, note = _fix(tmp_path)
    assert applied, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert out.count("\\c3h2") == 3  # noqa: PLR2004 -- def 行 + 两站
    assert "这是译文" not in out.split("\\c3h2")[1][:4]  # 蚀除域已还原


def test_insert_partial_align(tmp_path: Path) -> None:
    """``\\b0这是译文`` → ``\\b0bmode这是译文`` (零内容损失插缺)。"""
    (tmp_path / "main.tex").write_text(
        "\\def\\b{\\ensuremath{b}\\xspace}\n"
        "\\def\\b0bmode{$\\bar{B}^0/B^0$}\n"
        "from neutral, \\b0这是译文, and charged.\n",
        encoding="utf-8",
    )
    applied, note = _fix(tmp_path, "Use of \\b doesn't match its definition.")
    assert applied, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\b0bmode这是译文, and charged." in out


def test_symbol_cs_insert(tmp_path: Path) -> None:
    """``\\0`` 符型 cs: ``\\0这是译文`` → ``\\0cc这是译文`` (不吸空白)。"""
    (tmp_path / "main.tex").write_text(
        "\\def\\0cc{$\\Lambda = 0$}\n\\section{between \\0这是译文\\ and other}\n",
        encoding="utf-8",
    )
    applied, note = _fix(tmp_path, "Use of \\0 doesn't match its definition.")
    assert applied, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\0cc这是译文\\" in out


def test_cross_file_sty_fallback(tmp_path: Path) -> None:
    """astro-ph/0408446 形: def 在 .sty, 蚀除站在 .tex → 全局唯一尾回落。"""
    (tmp_path / "0343.sty").write_text("\\def\\ch3oh{CH$_3$OH}\n", encoding="utf-8")
    (tmp_path / "main.tex").write_text(
        "masers \\ch3这是译文这是译文这是译文这是译文这是译文. end\n",
        encoding="utf-8",
    )
    applied, note = _fix(tmp_path, "Use of \\ch doesn't match its definition.")
    assert applied, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ch3oh这是译文这是译文这是译文这是译文这是译文. end" in out


def test_nearest_preceding_def(tmp_path: Path) -> None:
    """站点先于本文件一切 def → 沿用前义 (accent ``\\b``), 不动。"""
    (tmp_path / "main.tex").write_text(
        "early \\b0这是译文 site.\n"
        "\\def\\b{plain}\n\\def\\b0bmode{x}\n"
        "late \\b0这是译文 site.\n",
        encoding="utf-8",
    )
    applied, note = _fix(tmp_path, "Use of \\b doesn't match its definition.")
    assert applied, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "early \\b0这是译文 site." in out  # def 前站不动
    assert "late \\b0bmode这是译文 site." in out


def test_no_evidence_skip(tmp_path: Path) -> None:
    """``\\c{o}``/``\\c3x`` 无蚀除证据 → 上游断裂原样, 不动。"""
    (tmp_path / "main.tex").write_text(
        "\\def\\c3h2{x}\naccent \\c{o} and broken \\c3x end.\n",
        encoding="utf-8",
    )
    applied, _note = _fix(tmp_path)
    assert not applied
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\c{o}" in out
    assert "\\c3x" in out


def test_no_doc_def_abstain(tmp_path: Path) -> None:
    """工程内无此 cs 的 def (包内 delimited 宏) → abstain。"""
    (tmp_path / "main.tex").write_text("text \\c3这是译文2 here.\n", encoding="utf-8")
    applied, note = _fix(tmp_path)
    assert not applied
    assert "intact" in note or "no doc-side" in note


def test_intact_site_untouched(tmp_path: Path) -> None:
    """完好 ``\\c3h2`` 站 (含 def 行自身) → applied=False。"""
    src = "\\def\\c3h2{x}\nuse \\c3h2 and \\c3h2\\ again.\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    applied, _note = _fix(tmp_path)
    assert not applied
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == src


def test_comment_site_masked(tmp_path: Path) -> None:
    """注释内 ``\\c3这是译文`` 被 mask → 不动。"""
    (tmp_path / "main.tex").write_text(
        "\\def\\c3h2{x}\n% \\c3这是译文2 commented\nlive \\c3这是译文2.\n",
        encoding="utf-8",
    )
    applied, note = _fix(tmp_path)
    assert applied, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "% \\c3这是译文2 commented" in out  # 注释站原样
    assert "live \\c3h2." in out
