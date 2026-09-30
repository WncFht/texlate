r"""armgap4 三臂钉 (armgap4 车道普查): soul_multi_mbox / inputenc_noop_shadow /
bib_backend_biber_swap —— covered_preexisting 臂面缺口的第三批 soul/编码/文献臂。

- 1107.0598 soul_err gate_miss: ``\so{\MakeTextUppercase{#1}}`` cs+花括号组
  多 token 实参 —— soul_cjk_mbox(100, 字面 CJK) 与 soul_cs_mbox(102, 单 cs)
  双 decline → 第三臂裹 ``\mbox`` (lookahead 拦已裹站点幂等)。
- 1003.2165 inputenc_unicode fired_ineffective: 活装载点在 fileset 外
  (texmf-dist cc.cls) → vendored_fetch_multi 投 noop inputenc.sty 到
  compile cwd (main_dir), kpathsea ``.`` 遮蔽 TEXMFDIST 真件。
- 2605.29672 warn_utf8 fired_ineffective: bibtex 8-bit 行包劈断 UTF-8 产
  腐 .bbl (recode 够不到生成件) → biblatex 装载行 backend=bibtex→biber。
"""

import re
from functools import lru_cache
from pathlib import Path

from _fixloopkit import apply, mk_ctx

from texlate.compile.fixloop import Ruleset, actions, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx, Rule


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    """ruleset 首用时加载——收集期不 IO（坏 yaml 报 test fail 而非 collection error）。"""
    return load_ruleset()


def _rule(rid: str) -> Rule:
    return next(r for r in _rs().rules if r.id == rid)


def _apply(rid: str, ctx: LoopCtx, pay: str | None = None) -> tuple[bool, str]:
    return apply(_rule(rid), ctx, pay)


def _tex(tmp_path: Path, body: str, name: str = "main.tex") -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"\\documentclass{{article}}\n\\begin{{document}}\n{body}\n\\end{{document}}\n",
        encoding="utf-8",
    )
    return p


# ─── soul_multi_mbox ───


def test_soul_multi_registered() -> None:
    rule = _rule("soul_multi_mbox")
    assert rule.order == 103  # noqa: PLR2004 - schema 断言值
    assert rule.phase == "loop"
    assert rule.when["category"] == "soul_err"
    assert rule.action["kind"] == "regex_rewrite"


def test_soul_multi_when_gate(tmp_path: Path) -> None:
    rule = _rule("soul_multi_mbox")
    ctx = mk_ctx(tmp_path)
    assert actions._when_ok(rule.when, "soul_err", None, ctx)  # noqa: SLF001
    for cat in ("syntax", "other", "inputenc_unicode", None):
        assert not actions._when_ok(rule.when, cat, None, ctx)  # noqa: SLF001


def test_soul_multi_wraps_cs_group_arg(tmp_path: Path) -> None:
    r"""1107.0598 def-站签名: ``\so{\MakeTextUppercase{#1}}`` → mbox 裹。"""
    _tex(tmp_path, "\\newcommand\\secformat[1]{\\so{\\MakeTextUppercase{#1}}}")
    ok, note = _apply("soul_multi_mbox", mk_ctx(tmp_path))
    assert ok, note
    out = (tmp_path / "main.tex").read_text()
    assert "\\so{\\mbox{\\MakeTextUppercase{#1}}}" in out


def test_soul_multi_wraps_caps_variant(tmp_path: Path) -> None:
    r"""同格姊妹站 ``\caps{\MakeTextLowercase{#1}}`` 同裹。"""
    _tex(tmp_path, "\\caps{\\MakeTextLowercase{#1}}")
    ok, _ = _apply("soul_multi_mbox", mk_ctx(tmp_path))
    assert ok
    assert (
        "\\caps{\\mbox{\\MakeTextLowercase{#1}}}" in (tmp_path / "main.tex").read_text()
    )


def test_soul_multi_wraps_text_plus_cs(tmp_path: Path) -> None:
    r"""soul_cs_mbox 记档缺面 ``\hl{a \model}`` 文本+cs 混合实参同收。"""
    _tex(tmp_path, "\\hl{a \\model}")
    ok, _ = _apply("soul_multi_mbox", mk_ctx(tmp_path))
    assert ok
    assert "\\hl{\\mbox{a \\model}}" in (tmp_path / "main.tex").read_text()


def test_soul_multi_declines_no_cs(tmp_path: Path) -> None:
    r"""无 cs 纯文本实参不收 —— 字面 CJK 归 soul_cjk_mbox, 纯拉丁不同机理。"""
    _tex(tmp_path, "\\so{plain} and \\so{中文}")
    ok, _ = _apply("soul_multi_mbox", mk_ctx(tmp_path))
    assert not ok
    assert "\\mbox" not in (tmp_path / "main.tex").read_text()


def test_soul_multi_idempotent(tmp_path: Path) -> None:
    r"""已裹站点 (本臂/soul_cs_mbox 产出 ``\mbox`` 首实参) 不二裹。"""
    _tex(tmp_path, "\\so{\\MakeTextUppercase{#1}}")
    ok, _ = _apply("soul_multi_mbox", mk_ctx(tmp_path))
    assert ok
    ok, _ = _apply("soul_multi_mbox", mk_ctx(tmp_path))
    assert not ok
    _tex(tmp_path, "\\hl{\\mbox{\\model}}")  # soul_cs_mbox(102) 产出形
    ok, _ = _apply("soul_multi_mbox", mk_ctx(tmp_path))
    assert not ok


def test_soul_multi_comment_shielded(tmp_path: Path) -> None:
    r"""masked 面: 注释内同形不改写, 活站仍裹。"""
    _tex(
        tmp_path,
        "% \\so{\\MakeTextUppercase{#1}}\n\\so{\\MakeTextLowercase{#2}}",
    )
    ok, _ = _apply("soul_multi_mbox", mk_ctx(tmp_path))
    assert ok
    out = (tmp_path / "main.tex").read_text()
    assert "% \\so{\\MakeTextUppercase{#1}}" in out
    assert "\\so{\\mbox{\\MakeTextLowercase{#2}}}" in out


def test_soul_multi_deep_nest_untouched(tmp_path: Path) -> None:
    r"""两层花括号嵌套实参超 [^{}] 窗 → 记档 known_gap, 不收。"""
    _tex(tmp_path, "\\so{\\textbf{a {b}}}")
    ok, _ = _apply("soul_multi_mbox", mk_ctx(tmp_path))
    assert not ok


# ─── inputenc_noop_shadow ───


def test_inputenc_shadow_registered() -> None:
    rule = _rule("inputenc_noop_shadow")
    assert rule.order == 94.5  # noqa: PLR2004 - schema 断言值
    assert rule.phase == "loop"
    assert rule.when["category"] == "inputenc_unicode"
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "vendored_fetch_multi"
    assert rule.action["params"]["files"] == ["inputenc.sty"]


def test_inputenc_shadow_drops_noop(tmp_path: Path) -> None:
    r"""投放 noop inputenc.sty 到 compile cwd; 内容 = option-tolerant noop。"""
    _tex(tmp_path, "x")
    ok, note = _apply("inputenc_noop_shadow", mk_ctx(tmp_path))
    assert ok, note
    dst = tmp_path / "inputenc.sty"
    assert dst.is_file()
    body = dst.read_text()
    assert "\\ProvidesPackage{inputenc}" in body
    assert "\\DeclareOption*{}" in body
    assert "\\endinput" in body


def test_inputenc_shadow_lands_at_main_dir(tmp_path: Path) -> None:
    r"""嵌套 main 落点是 main_dir (kpathsea ``.`` 解析位) 非 wdir 根 —
    _resolve_site 口径钉, 系统 cls 装载链遮蔽靠它。"""
    _tex(tmp_path, "x", name="sub/main.tex")
    ctx = mk_ctx(tmp_path, main_rel="sub/main.tex")
    ok, note = _apply("inputenc_noop_shadow", ctx)
    assert ok, note
    assert (tmp_path / "sub" / "inputenc.sty").is_file()
    assert not (tmp_path / "inputenc.sty").exists()


def test_inputenc_shadow_idempotent(tmp_path: Path) -> None:
    r"""dst 在场 (前轮已投/稿自带) → 跳过不覆写 → applied=False。"""
    _tex(tmp_path, "x")
    ok, _ = _apply("inputenc_noop_shadow", mk_ctx(tmp_path))
    assert ok
    ok, _ = _apply("inputenc_noop_shadow", mk_ctx(tmp_path))
    assert not ok


def test_inputenc_shadow_declines_foreign_file(tmp_path: Path) -> None:
    r"""稿自带 inputenc.sty 不覆写 —— 保守 decline。"""
    _tex(tmp_path, "x")
    foreign = tmp_path / "inputenc.sty"
    foreign.write_text("% doc-shipped inputenc\n\\endinput\n", encoding="utf-8")
    ok, _ = _apply("inputenc_noop_shadow", mk_ctx(tmp_path))
    assert not ok
    assert "doc-shipped" in foreign.read_text()


# ─── bib_backend_biber_swap ───


def test_biber_swap_registered() -> None:
    rule = _rule("bib_backend_biber_swap")
    assert rule.order == 195.5  # noqa: PLR2004 - schema 断言值
    assert rule.phase == "loop"
    assert rule.when["category"] == "warn_utf8"
    assert rule.action["kind"] == "regex_rewrite"
    cond = rule.condition
    assert cond["fileset"]["has_ext"] == [".bcf"]
    assert cond["tool_available"] == "biber"
    assert "backend" in cond["source_contains"]


def test_biber_swap_rewrites_options() -> None:
    r"""``backend=bibtex`` → ``biber``, 其余选项原样保留。"""
    pat = re.compile(
        _rule("bib_backend_biber_swap").action["params"]["rewrites"][0]["pattern"]
    )
    src = "\\usepackage[style=authoryear,backend=bibtex,natbib=true]{biblatex}"
    out = pat.sub("\\g<1>backend=biber", src)
    assert out == "\\usepackage[style=authoryear,backend=biber,natbib=true]{biblatex}"
    src2 = "\\RequirePackage[backend = bibtex]{biblatex}"
    assert pat.sub("\\g<1>backend=biber", src2) == (
        "\\RequirePackage[backend=biber]{biblatex}"
    )


def test_biber_swap_apply(tmp_path: Path) -> None:
    r"""2605.29672 签名: 装载行改写后 .bcf→biber 通道产净 .bbl。"""
    _tex(tmp_path, "\\usepackage[style=authoryear,backend=bibtex]{biblatex}\nx")
    ok, note = _apply("bib_backend_biber_swap", mk_ctx(tmp_path))
    assert ok, note
    out = (tmp_path / "main.tex").read_text()
    assert "backend=biber" in out
    assert "style=authoryear" in out


def test_biber_swap_bibtex8_untouched(tmp_path: Path) -> None:
    r"""``backend=bibtex8`` 词界不收 —— 记档 known_gap, 不误改。"""
    _tex(tmp_path, "\\usepackage[backend=bibtex8]{biblatex}")
    ok, _ = _apply("bib_backend_biber_swap", mk_ctx(tmp_path))
    assert not ok
    assert "backend=bibtex8" in (tmp_path / "main.tex").read_text()


def test_biber_swap_non_biblatex_untouched(tmp_path: Path) -> None:
    r"""同文件他包 backend=bibtex 选项不带 biblatex 锚 → 不改写。"""
    _tex(tmp_path, "\\usepackage[backend=bibtex]{otherpkg}\n\\usepackage{biblatex}")
    ok, _ = _apply("bib_backend_biber_swap", mk_ctx(tmp_path))
    assert not ok
    assert "backend=bibtex" in (tmp_path / "main.tex").read_text()


def test_biber_swap_comment_shielded(tmp_path: Path) -> None:
    r"""masked 面: 注释掉的装载行不改写。"""
    _tex(tmp_path, "% \\usepackage[backend=bibtex]{biblatex}")
    ok, _ = _apply("bib_backend_biber_swap", mk_ctx(tmp_path))
    assert not ok


def test_biber_swap_idempotent(tmp_path: Path) -> None:
    _tex(tmp_path, "\\usepackage[backend=bibtex]{biblatex}")
    ok, _ = _apply("bib_backend_biber_swap", mk_ctx(tmp_path))
    assert ok
    ok, _ = _apply("bib_backend_biber_swap", mk_ctx(tmp_path))
    assert not ok


# ─── 全库钉 ───


def test_armgap_ruleset_loads() -> None:
    ids = [r.id for r in _rs().rules]
    assert len(ids) == len(set(ids))
    for rid in ("soul_multi_mbox", "inputenc_noop_shadow", "bib_backend_biber_swap"):
        assert rid in ids
