"""csfix7 批 (task #274) —— m1kcensus2 undefined_cs singles ×3 直改单测。

``_CS_FIX_TABLE`` 默认表新增 ``z`` / ``oldcr`` / ``refpar`` 三行
(``backref``/``C``/``url``/``text`` 已由 shimfix-a #180/renewguard #234
收进 95-targeted.yaml cs_table, 本批不重覆)。钉死的机制要点:

- ``z`` (2105.12363): doc ``\\def\\And{...\\rule{\\z@}{24pt}}`` 在 @=other
  catcode 下分词成 cs ``\\z`` + 字符 ``@`` —— 作者本意 kernel 私有
  ``\\z@`` (0pt)。``\\def\\z@{0pt}`` @-分隔形让 ``\\z`` 吞 @ 吐 0pt;
  ``\\providecommand`` 形表达不了分隔参数, 裸 ``\\def`` 加 ``\\ifdefined``
  护 cls 已备 ``\\z`` 格。
- ``oldcr`` (1503.00273): rjparticle.cls ``\\let\\oldcr\\\\`` 于 ``\\affil``
  组内 —— 97 年代 authblk 形在现代内核下 ``\\\\`` 是 ``\\protected``,
  ``\\xdef`` 内不可展 → ``\\oldcr`` 字面嵌入 ``\\AB@affillist``,
  ``\\endgroup`` 后局部 let 蒸发 → ``\\@author`` 排版期 undefined。
  body 取 ``\\newline`` 不取 ``\\\\``: 同族稿 ``\\def\\\\{\\oldcr…}``
  重绑后 xdef 若无 let 冻结, ``\\oldcr→\\\\→\\oldcr`` 自指死循环。
- ``refpar`` (astro-ph/9612039): vendored aaspp4 的 ``\\def\\refpar`` 锁
  references env 组内, 稿在 thebibliography 裸调 ``\\reference→\\refpar``
  → verbatim 同体 provide 兜底 (env 内局部 def 仍遮罩)。
"""

from pathlib import Path

from _fixloopkit import DOC, mk_ctx, rule

from texlate.compile.fixloop._builtins_csfix import _CS_FIX_TABLE
from texlate.compile.fixloop.builtins import TRANSFORM_FNS

_TARGETED = TRANSFORM_FNS["cs_targeted_fix"]


class _EngStub:
    """probe 恒命中 / install 恒成 —— usepackage 臂走通支路。"""

    def probe_file(self, fname: str, cwd: Path | None = None) -> str:
        del cwd
        return f"/texmf/{fname}"

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return True


def _proj(tmp_path: Path, tex: str) -> None:
    (tmp_path / "main.tex").write_text(tex, encoding="utf-8")


def _fix(tmp_path: Path, cs: str) -> tuple[bool, str]:
    return _TARGETED(mk_ctx(tmp_path), _EngStub(), cs, {})


# ── csfix7/csfix8 共用断言助手 (cs_table 通用面, 逐文件逐字节同体) ──


def check_backslash_payload(tmp_path: Path, pay: str, needle: str) -> None:
    """log payload 带反斜杠形 → ``lstrip`` 归一同键命中。"""
    _proj(tmp_path, DOC)
    ok, note = _fix(tmp_path, pay)
    assert ok, note
    assert needle in (tmp_path / "main.tex").read_text(encoding="utf-8")


def check_refire_idempotent(tmp_path: Path, cs: str, needle: str) -> None:
    """二轮重火: snippet 已在文 → applied nothing, 不重复注入。"""
    _proj(tmp_path, DOC)
    ok1, _ = _fix(tmp_path, cs)
    assert ok1
    ok2, note2 = _fix(tmp_path, cs)
    assert not ok2
    assert "applied nothing" in note2
    assert (tmp_path / "main.tex").read_text(encoding="utf-8").count(needle) == 1


def check_unknown_cs_decline(tmp_path: Path) -> None:
    """非表键 payload → 拆分臂亦不中, 诚实 decline 落 guess 链。"""
    _proj(tmp_path, DOC)
    ok, note = _fix(tmp_path, "xyzzyqq")
    assert not ok
    assert "not in cs-fix table" in note


def test_table_entries_present() -> None:
    """三键在默认表, 全走 ``polyfill`` spec (docclass 缝后注入)。"""
    for cs in ("z", "oldcr", "refpar"):
        assert cs in _CS_FIX_TABLE, cs
        assert set(_CS_FIX_TABLE[cs]) == {"polyfill"}, (cs, _CS_FIX_TABLE[cs])


def test_z_atdelim_polyfill_injected(tmp_path: Path) -> None:
    """``\\z@`` 分词残骸 → @-分隔 ``\\def\\z@{0pt}``, ``\\ifdefined`` 护名。"""
    _proj(tmp_path, DOC)
    ok, note = _fix(tmp_path, "z")
    assert ok, note
    assert "polyfill injected" in note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifdefined\\z\\else\\def\\z@{0pt}\\fi" in text
    # 缝后落位: docclass 行之后、begin{document} 之前。
    assert text.index("\\def\\z@") > text.index("\\documentclass")
    assert text.index("\\def\\z@") < text.index("\\begin{document}")


def test_z_payload_backslash_form(tmp_path: Path) -> None:
    """log payload 带反斜杠 (``\\z``) → ``lstrip`` 归一同键命中。"""
    check_backslash_payload(tmp_path, "\\z", "\\def\\z@{0pt}")


def test_oldcr_newline_body(tmp_path: Path) -> None:
    """``\\newline`` 替身 —— 非 ``\\\\`` 本体 (\\\\-rebind 自指死循环免疫)。"""
    _proj(tmp_path, DOC)
    ok, note = _fix(tmp_path, "oldcr")
    assert ok, note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\providecommand\\oldcr{\\newline}" in text
    assert "\\providecommand\\oldcr{\\\\}" not in text


def test_refpar_verbatim_stub_body(tmp_path: Path) -> None:
    """aaspp4 env 内定义同体: ``\\par\\hangindent=3em\\hangafter=1``。"""
    _proj(tmp_path, DOC)
    ok, note = _fix(tmp_path, "refpar")
    assert ok, note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\providecommand\\refpar{\\par\\hangindent=3em\\hangafter=1}" in text


def test_refire_applied_nothing(tmp_path: Path) -> None:
    """二轮重火: snippet 已在文 → applied nothing, 文件不重复注入。"""
    check_refire_idempotent(tmp_path, "z", "\\def\\z@{0pt}")


def test_unknown_cs_still_declines(tmp_path: Path) -> None:
    """非表键 payload → 拆分臂亦不中, 诚实 decline 落 guess 链。"""
    check_unknown_cs_decline(tmp_path)


# ────────────────────────── breakurl_ifpdf_hook (task #289) ──────────────────────────
# breakurl v1.40 在 \ifpdf=false 支做 \@ifpackageloaded{hyperref} 硬检;
# 稿把 breakurl 排在 hyperref 前或根本不载 → PackageError+\endinput。
# 断臂 = ifpdf 钩 (非 strip/非 hyperref 前移): strip orphan \burl;
# hyperref 前移激活 DVI 支 \headerps@out 病理。snippet 与
# normalize.XETEX_COMPATIBILITY:98-103 逐字同源。

import regex  # noqa: E402

from texlate.compile.fixloop.ruleset import Rule  # noqa: E402

_HOOK_BEFORE = (
    "\\AddToHook{package/breakurl/before}{\\RequirePackage{xkeyval,ifpdf}"
    "\\let\\TeXlateSavedIfpdf\\ifpdf\\let\\ifpdf\\iftrue}"
)
_HOOK_AFTER = "\\AddToHook{package/breakurl/after}{\\let\\ifpdf\\TeXlateSavedIfpdf}"


def _breakurl_rule() -> Rule:
    return rule("breakurl_ifpdf_hook")


def test_breakurl_rule_shape() -> None:
    """when=other (depends-on 措辞不落 pkg_order), ctx_suggests 收窄到 breakurl。"""
    rule = _breakurl_rule()
    assert rule.when == {"category": "other"}
    assert "breakurl depends on hyperref" in rule.condition["ctx_suggests"]
    assert rule.action["kind"] == "regex_rewrite"


def test_breakurl_ctx_suggests_match() -> None:
    """真错行文命中; 别包同措辞 (foo depends on hyperref) 不误中。"""
    pat = _breakurl_rule().condition["ctx_suggests"]
    err = "breakurl.sty:62: Package breakurl Error: The breakurl depends on hyperref package."
    assert regex.search(pat, err)
    assert not regex.search(
        pat, "foo.sty:9: Package foo Error: The foo depends on hyperref package."
    )


def test_breakurl_hook_injected_before_docclass() -> None:
    """rewrite 在 \\documentclass 行前注 hook 对 —— 与 normalize snippet 同体。"""
    rw = _breakurl_rule().action["params"]["rewrites"][0]
    flags = regex.M if "M" in rw.get("flags", []) else 0
    out = regex.sub(rw["pattern"], rw["repl"], DOC, flags=flags)
    assert _HOOK_BEFORE in out
    assert _HOOK_AFTER in out
    assert out.index(_HOOK_BEFORE) < out.index("\\documentclass")
    assert "fixloop: breakurl ifpdf guard" in out
    # 无 docclass 锚的碎片 → 原文不动 (applied=False 诚实 decline 路径)。
    assert regex.sub(rw["pattern"], rw["repl"], "x\n", flags=flags) == "x\n"
