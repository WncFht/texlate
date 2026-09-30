r"""bm_extended_mathchar_wrap 内建 —— \bm{<CJK>} 撞 XeTeX mathchar 墙的组路径重绑。

实证簇 (failmine3 census ~6 格, hep-ph/0605174 GLUON.tex:464 + 1206.0485 +
2112.00003): bm.sty ``\bm@test@token`` 对实参内 catcode-11/12 token 逐个
``\count@\mathcode`#1`` —— >0xFF 字符在 XeTeX legacy 15-bit mathchar
扫描位必炸 "Extended mathchar used as mathchar" (mathchar 探针 t1-t6/
probe4-5 实证: 裸 ``$这$`` 不炸、``\bm{这}`` 即炸、``\mathcode`Ω`` 同炸
非 CJK 专属)。修复 = 序言守卫式 ``\bm#1 → \TeXlateBM{{#1}}`` 双花括号走
bm 自带 ``\bm@group``→``\boldmath`` 组路径 (fix3/fix4 全形零错)。
"""

from pathlib import Path

from texlate.compile.fixloop import builtins, load_ruleset
from texlate.compile.fixloop.builtins import bm_mathchar_wrap
from texlate.compile.fixloop.builtins.csbind import _BM_MATHCHAR_WRAP
from texlate.compile.fixloop.engine import LoopCtx

_DOC = (
    "\\documentclass{article}\n"
    "\\usepackage{bm}\n"
    "\\newcommand{\\unit}[1]{\\hat{{\\bm #1}}}\n"
    "\\begin{document}\n"
    "$\\varphi({\\bm 这是译文},这是译文_1) \\Phi(\\bm{这是译文},这是译文_2)$\n"
    "\\end{document}\n"
)


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path, engine_name="xelatex", main_rel="main.tex", runner=None
    )


def _main(tmp_path: Path, text: str) -> None:
    (tmp_path / "main.tex").write_text(text, encoding="utf-8")


def test_hit_injects_before_begindoc(tmp_path: Path) -> None:
    r"""``\bm`` 在用 → ``\begin{document}`` 前注入守卫式重定义块。"""
    _main(tmp_path, _DOC)
    ok, note = bm_mathchar_wrap(_ctx(tmp_path), None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    mark = "% fixloop: bm-family atom-walk"
    assert mark in t
    # 注入位：\begin{document} 之前 (全部 \usepackage 装载已毕，\bm 已定义)
    assert t.index("\\usepackage{bm}") < t.index(mark) < t.index("\\begin{document}")
    # 守卫式重定义块：\bm + \hm 双臂，\ifdefined\TeXlateBM 幂等防自捕环
    assert "\\ifdefined\\bm" in t
    assert "\\let\\TeXlateBM\\bm" in t
    assert "\\protected\\def\\bm#1{\\TeXlateBM{{#1}}}" in t
    assert "\\ifdefined\\TeXlateBM\\else" in t
    # \let-别名 (\boldsymbol/\heavysymbol) 经 \ifx 等义复核后重绑
    assert "\\ifx\\boldsymbol\\TeXlateBM\\let\\boldsymbol\\bm\\fi" in t
    assert "\\ifx\\heavysymbol\\TeXlateHM\\let\\heavysymbol\\hm\\fi" in t


def test_hit_via_newcommand_alias(tmp_path: Path) -> None:
    r"""``\b``/``\unit`` 别名定义体内含 ``\bm`` 字面 → 探针命中。"""
    _main(
        tmp_path,
        "\\documentclass{article}\n"
        "\\usepackage{bm}\n"
        "\\renewcommand{\\b}[1]{{\\bm #1}}\n"  # 1206.0485 形
        "\\begin{document}\n$\\b{这是译文}$\n\\end{document}\n",
    )
    ok, _note = bm_mathchar_wrap(_ctx(tmp_path), None, None, {})
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\protected\\def\\bm#1{\\TeXlateBM{{#1}}}" in t


def test_hit_via_boldsymbol(tmp_path: Path) -> None:
    r"""只用 ``\boldsymbol`` 字面 (bm.sty ``\let`` 别名) 同样探针命中。"""
    _main(
        tmp_path,
        "\\documentclass{article}\n"
        "\\usepackage{bm}\n"
        "\\begin{document}\n$\\boldsymbol{这是译文}$\n\\end{document}\n",
    )
    ok, _note = bm_mathchar_wrap(_ctx(tmp_path), None, None, {})
    assert ok


def test_reject_no_bm_use(tmp_path: Path) -> None:
    r"""无 bm 族使用的稿不注 (mathchar 错另有肇事者时让位他规则/LLM)。"""
    _main(
        tmp_path,
        "\\documentclass{article}\n\\begin{document}\n$这是译文_1$\n\\end{document}\n",
    )
    before = (tmp_path / "main.tex").read_text(encoding="utf-8")
    ok, note = bm_mathchar_wrap(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no bm-family" in note
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == before


def test_reject_masked_bm_deadzone(tmp_path: Path) -> None:
    r"""注释/verbatim 死区里的 ``\bm`` 不算在用 (遮盖视图口径)。"""
    _main(
        tmp_path,
        "\\documentclass{article}\n"
        "% \\usepackage{bm} $\\bm{这是译文}$\n"  # 整行注释 —— 死区
        "\\begin{document}\n"
        "\\begin{verbatim}\n$\\bm{x}$\n\\end{verbatim}\n"
        "$x$\n\\end{document}\n",
    )
    ok, note = bm_mathchar_wrap(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no bm-family" in note
    assert "TeXlateBM" not in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_idempotent_second_call(tmp_path: Path) -> None:
    """二入幂等：首注 True, 再调 False 且文本不变。"""
    _main(tmp_path, _DOC)
    ctx = _ctx(tmp_path)
    ok, _note = bm_mathchar_wrap(ctx, None, None, {})
    assert ok
    after = (tmp_path / "main.tex").read_text(encoding="utf-8")
    ok2, note2 = bm_mathchar_wrap(ctx, None, None, {})
    assert not ok2
    assert "already present" in note2
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == after


def test_wrap_block_self_idempotent() -> None:
    r"""注入块 TeX 层幂等: ``\ifdefined\TeXlateBM`` 闸防 ``\let`` 重捕自环。"""
    # 二次注入 (异标记/手工复粘) 时 \TeXlateBM 已定义 → \let 不再重捕新 \bm,
    # 否则 \TeXlateBM{{#1}} 无穷递归
    assert "\\ifdefined\\TeXlateBM\\else" in _BM_MATHCHAR_WRAP
    assert "\\ifdefined\\TeXlateHM\\else" in _BM_MATHCHAR_WRAP
    # 双花括号实参 —— bm 自带组路径签名
    assert "\\protected\\def\\bm#1{\\TeXlateBM{{#1}}}" in _BM_MATHCHAR_WRAP


def test_registration_and_rule() -> None:
    """注册钉：TRANSFORM_FNS 直连 + rules/ 装载含同名规则且接线一致。"""
    assert builtins.TRANSFORM_FNS["bm_mathchar_wrap"] is bm_mathchar_wrap
    rules = {r.id: r for r in load_ruleset().rules}
    rule = rules["bm_extended_mathchar_wrap"]
    assert rule.phase == "loop"
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "bm_mathchar_wrap"
    cats = {c.get("category") for c in rule.when["any"]}
    assert cats == {"other", "mathchar_ext"}
    assert "Extended mathchar" in rule.condition["ctx_suggests"]
