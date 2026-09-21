"""tofu 否决 + 一跳 ``\\input`` docclass 探测 pin 测试（lane tofuveto）。

- judge：``expect_cjk`` + 出 pdf + ``cjk_chars=0`` → ``fail``——豆腐 pdf
  不计 partial 交付面，bench onfail ``_want_fix`` 只接 fail；
  ``expect_cjk=False``（0-chunk 编排壳正确终态）、``cjk=-1``（pdftotext
  缺席不可测）、``cjk>0`` 均不受影响。
- inject：main 本体无 dc 缝但字面 ``\\input`` 目标一跳携带 dc → ctex 块
  落子件缝位、``CJK_MATH_FALLBACK`` 挪到 main bd 前；无携带者维持
  ``no-docline`` 票面。
"""

from pathlib import Path

import pytest
from conftest import judge_mod, make_comp_res

from texlate.compile.inject import prepare_chinese
from texlate.compile.judge import judge


def _prep(root: Path, name: str = "main.tex") -> dict:
    """``prepare_chinese`` 定参面——float_sizing/demote_wrap 全关。"""
    return prepare_chinese(root, name, float_sizing=False, demote_wrap=False)


def test_tofu_veto_partial_to_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """出 pdf + cjk_chars=0 → fail：豆腐 pdf 不许计 partial 交付。"""
    monkeypatch.setattr(judge_mod(), "pdf_cjk_chars", lambda _p: 0)
    v = judge(make_comp_res(tmp_path), expect_cjk=True)
    assert v.status == "fail"
    assert "cjk_chars=0" in v.reasons
    assert "tofu_veto" in v.notes


def test_tofu_veto_missing_chars_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """soak 两格账面形态：missing_character reason 保留，status 翻 fail。"""
    monkeypatch.setattr(judge_mod(), "pdf_cjk_chars", lambda _p: 0)
    log = "Missing character: There is no 中 (U+4E2D) in font cmr10\n"
    v = judge(make_comp_res(tmp_path, log_text=log), expect_cjk=True, log_text=log)
    assert v.status == "fail"
    assert any(r.startswith("missing_character×") for r in v.reasons)
    assert "cjk_chars=0" in v.reasons


def test_tofu_veto_no_expect_cjk_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """expect_cjk=False：0-chunk 编排壳 cjk=0 是正确终态——不否决。"""
    monkeypatch.setattr(judge_mod(), "pdf_cjk_chars", lambda _p: 0)
    v = judge(make_comp_res(tmp_path), expect_cjk=False)
    assert v.status == "clean"
    assert v.cjk_chars == -1  # 未测
    assert "tofu_veto" not in v.notes


def test_tofu_veto_cjk_unverified_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pdftotext 缺席（cjk=-1）不可测不否决——工具缺席非文档问题。"""
    monkeypatch.setattr(judge_mod(), "pdf_cjk_chars", lambda _p: -1)
    v = judge(make_comp_res(tmp_path), expect_cjk=True)
    assert v.status == "clean"
    assert "tofu_veto" not in v.notes


def test_tofu_veto_cjk_positive_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CJK 真的渲染了 → clean，否决不触。"""
    monkeypatch.setattr(judge_mod(), "pdf_cjk_chars", lambda _p: 500)
    v = judge(make_comp_res(tmp_path), expect_cjk=True)
    assert v.status == "clean"
    assert "tofu_veto" not in v.notes


def _mk_hop_project(root: Path) -> Path:
    """2609.19979 形态：dc 藏 preambule.tex，main 字面 ``\\input`` 一跳。

    preambule.tex 首行是注释掉的 dc（遮盖视图抹平）——真缝在第 2 行。
    """
    (root / "preambule.tex").write_text(
        "% \\documentclass{commented}\n"
        "\\documentclass[a4paper,twoside,leqno]{article}\n"
        "\\usepackage{amsmath}\n",
        encoding="utf-8",
    )
    (root / "macros.tex").write_text("\\newcommand{\\x}{y}\n", encoding="utf-8")
    main = root / "main.tex"
    main.write_text(
        "% top comment\n"
        "\\input{preambule}\n"
        "\\input{macros}\n"
        "\\begin{document}\n"
        "hello $x$\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    return main


def test_hop_injects_into_child_preamble(tmp_path: Path) -> None:
    """dc 一跳子件：ctex 落子件缝位、mathgroup 兜底挪到 main bd 前。"""
    main = _mk_hop_project(tmp_path)
    info = _prep(tmp_path)
    assert info["status"] == "injected"
    assert info["input_hop"] == "preambule.tex"
    assert info.get("math_fallback") == "main-bd"
    sub = (tmp_path / "preambule.tex").read_text(encoding="utf-8")
    assert "{ctex}" in sub
    assert "% [texlate injected]" in sub
    # 子件缝位在组合 preamble 只是中段——符号字体块不下进子件
    assert "texlatecjk" not in sub
    new_main = main.read_text(encoding="utf-8")
    assert "texlatecjk" in new_main
    # preamble 尾锚：兜底在用户包之后的 main bd 前
    assert new_main.index("texlatecjk") < new_main.index("\\begin{document}")
    # 注入物没进 main 本体
    assert "% [texlate injected]" not in new_main
    # 非携带者子件不被改写
    assert (tmp_path / "macros.tex").read_text(encoding="utf-8") == (
        "\\newcommand{\\x}{y}\n"
    )


def test_hop_bare_input_form(tmp_path: Path) -> None:
    """2609.20454 形态：``\\input preamble`` 裸参（无括号）同口径解析。"""
    (tmp_path / "preamble.tex").write_text(
        "\\documentclass[11pt]{article}\n", encoding="utf-8"
    )
    (tmp_path / "arxiv.tex").write_text(
        "\\input preamble\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    info = _prep(tmp_path, "arxiv.tex")
    assert info["status"] == "injected"
    assert info["input_hop"] == "preamble.tex"
    assert "{ctex}" in (tmp_path / "preamble.tex").read_text(encoding="utf-8")


def test_hop_no_carrier_keeps_no_docline(tmp_path: Path) -> None:
    """一跳目标无 dc 携带者 → 维持 no-docline，任何文件不被改写。"""
    (tmp_path / "body.tex").write_text("just text\n", encoding="utf-8")
    main = tmp_path / "main.tex"
    main.write_text(
        "\\input{body}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    before = main.read_bytes()
    info = _prep(tmp_path)
    assert info["status"] == "no-docline"
    assert main.read_bytes() == before


def test_hop_already_cjk_shortcircuit(tmp_path: Path) -> None:
    """一跳面已带 CJK 支持 → already：dc 件先注入再撞兄弟 ctex = option clash。"""
    (tmp_path / "pre.tex").write_text(
        "\\documentclass{article}\n\\usepackage{ctex}\n", encoding="utf-8"
    )
    main = tmp_path / "main.tex"
    main.write_text(
        "\\input{pre}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    before = main.read_bytes()
    info = _prep(tmp_path)
    assert info["status"] == "already"
    assert main.read_bytes() == before


def test_hop_post_bd_input_ignored(tmp_path: Path) -> None:
    """bd 后 ``\\input`` 是 body 件——dc 藏此非 preamble 缝，不注入。"""
    (tmp_path / "weird.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    main = tmp_path / "main.tex"
    main.write_text(
        "\\begin{document}\n\\input{weird}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    info = _prep(tmp_path)
    assert info["status"] == "no-docline"
    assert "{ctex}" not in (tmp_path / "weird.tex").read_text(encoding="utf-8")


def test_hop_include_not_preamble_carrier(tmp_path: Path) -> None:
    """``\\include``/``\\InputIfFileExists`` 目标非 preamble 载体——只认 ``\\input``。"""
    (tmp_path / "inc.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    main = tmp_path / "main.tex"
    main.write_text(
        "\\include{inc}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    info = _prep(tmp_path)
    assert info["status"] == "no-docline"


def test_hop_no_bd_fallback_stays_in_child(tmp_path: Path) -> None:
    """main 无 bd（编排壳残留）：mathgroup 兜底留子件缝位（默认落点语义）。"""
    (tmp_path / "pre.tex").write_text(
        "\\documentclass{article}\n\\usepackage{amsmath}\n", encoding="utf-8"
    )
    main = tmp_path / "main.tex"
    main.write_text("\\input{pre}\nhello\n", encoding="utf-8")
    info = _prep(tmp_path)
    assert info["status"] == "injected"
    assert "math_fallback" not in info
    sub = (tmp_path / "pre.tex").read_text(encoding="utf-8")
    assert "texlatecjk" in sub  # defer 未置位——落子件缝位默认位
    assert main.read_text(encoding="utf-8") == "\\input{pre}\nhello\n"


def test_hop_relative_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """相对 root 不得静默零跳：_resolve_input 产绝对路径，is_relative_to
    相对帧恒假——未归一时 hop 悄悄 None 回退 no-docline（豆腐路原位）。"""
    _mk_hop_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    info = _prep(Path())
    assert info["status"] == "injected"
    assert info["input_hop"] == "preambule.tex"
    assert "{ctex}" in (tmp_path / "preambule.tex").read_text(encoding="utf-8")


def test_normal_main_docclass_unaffected(tmp_path: Path) -> None:
    """常规形态回归：dc 在 main 本体 → 走原路径，info 无 input_hop。"""
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\n\\usepackage{amsmath}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    info = _prep(tmp_path)
    assert info["status"] == "injected"
    assert "input_hop" not in info
    new_main = main.read_text(encoding="utf-8")
    assert "% [texlate injected]" in new_main
    assert new_main.index("texlatecjk") < new_main.index("\\begin{document}")
