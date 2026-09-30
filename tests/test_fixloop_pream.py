r"""arraypream 车道 (task #105): ``pream_token_cs_expand`` 规则 + ``pream_token`` 分类钉。

array.sty ``\@mkpream`` 只改写 ``*``-repeat 与 ``\NC@`` 名, 其余 preamble
宏留字面 token → ``Illegal pream-token (\X): `c' used.`` (kernel
``\@xexpast`` 全展开形原可吃, 差异即 array 装载面)。实证簇
(arraypream census 2026-09-19, records 41 cs-token 实例): ``\@delspec``
×30 (aaspp4/aasms4 ``\tablehead`` → ``\tabular{\@delspec}``),
``\pt@format`` ×11 (aastex.cls/emulateapj ``\def\pt@format{\string#1}``
+ ``\pt@tabular{\pt@format}``)。CJK 字面 token (这/是/译/文 ×54) 是
译文漏 preamble 的另一机制, 须落 ``syntax`` 不进本类。

修 = 三臂: call-站 ``\expandafter`` 一阶展开 + def-站 ``\edef`` 烘焙
(``\string`` 在 edef 内执行产字面 token) + emulateapj ``\pt@tabular``
死绑 let 链中和 (array 把 ``\@tabclassz/\@tabclassiv`` 存名中和成
``\relax`` → 重绑即炸 "Missing # inserted in alignment preamble")。
preamfix 探针 t2/t7/t8/t13 全链编译实证。
"""

from functools import lru_cache
from pathlib import Path

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx, Rule, Ruleset
from texlate.compile.logparse import ErrReport, parse_text


class _Eng:
    """regex_rewrite 路径的最小引擎替身 (不触 probe/install)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    return load_ruleset()


def _rule() -> Rule:
    return next(r for r in _rs().rules if r.id == "pream_token_cs_expand")


def _apply(tmp_path: Path, payload: str) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        _rule(), _ctx(tmp_path), _Eng(), payload, ErrReport()
    )


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def _classify(text: str) -> tuple[str | None, str | None]:
    return _rs().taxonomy.classify(parse_text(text, _rs().warn_patterns))


# ---------------------------------------------------------------- 规则注册
def test_pream_rule_registered() -> None:
    rule = _rule()
    assert rule.order == 198  # noqa: PLR2004 - schema 断言值
    assert rule.phase == "loop"
    assert rule.when["category"] == "pream_token"
    assert rule.when["payload_required"] is True
    assert rule.action["kind"] == "regex_rewrite"
    rws = rule.action["params"]["rewrites"]
    assert len(rws) == 4  # noqa: PLR2004 - def烘焙/call展开/3-let/2-let
    assert set(rule.action["params"]["exts"]) == {".tex", ".sty", ".cls"}


# ---------------------------------------------------------------- 分类路由
def test_pream_taxonomy_bang_form() -> None:
    """'!' 前缀形 + 双空格 file-line 形皆路由 pream_token 携 cs payload。"""
    cat, pay = _classify(
        "! Package array Error: Illegal pream-token (\\@delspec): `c' used.\n"
        "l.572 \\tablehead{h}\n"
    )
    assert (cat, pay) == ("pream_token", "@delspec")
    cat, pay = _classify(
        "./paper.tex:572: Package array Error:  Illegal pream-token "
        "(\\pt@format): `c' used.\n"
    )
    assert (cat, pay) == ("pream_token", "pt@format")


def test_pream_taxonomy_cjk_falls_to_syntax() -> None:
    """CJK 字面 token 无反斜杠前缀 → 不落 pream_token, 归 syntax 宽词。"""
    cat, pay = _classify("! Package array Error: Illegal pream-token (这): `c' used.\n")
    assert cat == "syntax"
    assert pay is None


# ---------------------------------------------------------------- 臂2: call-站
def test_delspec_callsite_expandafter(tmp_path: Path) -> None:
    """aaspp4 ``\\tablehead`` 实形: ``\\tabular{\\@delspec}`` → 双侧 ``\\expandafter``。"""
    sty = (
        "\\def\\tablehead#1{\\tabular{\\@delspec}#1\\\\\\hline}\n\\def\\tabletail#1{}\n"
    )
    (tmp_path / "aaspp4.sty").write_text(sty, encoding="utf-8")
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    ok, note = _apply(tmp_path, "@delspec")
    assert ok, note
    t = (tmp_path / "aaspp4.sty").read_text(encoding="utf-8")
    assert "\\expandafter\\tabular\\expandafter{\\@delspec}#1\\\\\\hline}" in t
    # 邻行无副作用
    assert "\\def\\tabletail#1{}" in t


def test_ptformat_three_arm(tmp_path: Path) -> None:
    """emulateapj 实形 (767-769/786/801 行字面): def烘焙 + call展开 + let链中和。"""
    sty = (
        "\\def\\pt@tabular{\\hbox \\bgroup \\pt@fontsize $\\let\\@acol\\@ptabacol \n"
        "   \\let\\@classz\\@tabclassz\n"
        "   \\let\\@classiv\\@tabclassiv \\let\\\\\\@tabularcr\\@tabarray}\n"
        "\\def\\@ptabacol{\\edef\\@preamble{\\@preamble \\hskip \\tabcolsep\\tabskip\\fill}}\n"
        "\\newenvironment{deluxetable}[1]{\\def\\pt@format{\\string#1}%\n"
        "   \\setbox\\pt@box=\\pt@tabular{\\pt@format}\\pt@head}\n"
    )
    (tmp_path / "emulateapj.sty").write_text(sty, encoding="utf-8")
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    ok, note = _apply(tmp_path, "pt@format")
    assert ok, note
    t = (tmp_path / "emulateapj.sty").read_text(encoding="utf-8")
    # def-站烘焙臂
    assert "\\edef\\pt@format{\\string#1}" in t
    assert "\\def\\pt@format{\\string#1}" not in t
    # call-站展开臂
    assert "\\setbox\\pt@box=\\expandafter\\pt@tabular\\expandafter{\\pt@format}" in t
    # 死绑 let 链整删臂 (含 \\@acol 绑位), 行间空白收拢无 \par
    assert "\\let\\@classz" not in t
    assert "\\let\\@classiv" not in t
    assert "\\let\\@acol\\@ptabacol" not in t
    assert (
        "$\\let\\\\\\@tabularcr" in t.replace(" ", "")
        or "\\let\\\\\\@tabularcr\\@tabarray}" in t
    )
    assert "\n\n" not in t.split("\\def\\pt@tabular")[1].split("}")[0]
    # 存活件不动
    assert "\\def\\@ptabacol" in t


def test_ptformat_already_expanded_callsite(tmp_path: Path) -> None:
    """aastex.cls 实形: call-站已 ``\\expandafter`` → 只发 def-站臂, 不二重展开。"""
    cls = (
        "\\newenvironment{deluxetable}[1]{%\n"
        " \\maketitle\n"
        " \\edef\\pt@format{\\string#1}%\n"
        "}\n"
        "\\def\\pt@head{\\expandafter\\@tabular\\expandafter{\\pt@format}}\n"
    )
    (tmp_path / "aastex.cls").write_text(cls, encoding="utf-8")
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    ok, _note = _apply(tmp_path, "pt@format")
    # \\edef 已烘焙 + \\expandafter 已就位的件无任何臂命中 → decline
    assert not ok
    assert (tmp_path / "aastex.cls").read_text(encoding="utf-8") == cls


def test_ptformat_def_only_still_fires(tmp_path: Path) -> None:
    """aastex.cls 未修形: ``\\def\\pt@format`` 在 + 已展开 call-站 → 只烘焙。"""
    cls = (
        " \\def\\pt@format{\\string#1}%\n"
        "\\def\\pt@head{\\expandafter\\@tabular\\expandafter{\\pt@format}}\n"
    )
    (tmp_path / "aastex.cls").write_text(cls, encoding="utf-8")
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    ok, note = _apply(tmp_path, "pt@format")
    assert ok, note
    t = (tmp_path / "aastex.cls").read_text(encoding="utf-8")
    assert "\\edef\\pt@format{\\string#1}" in t
    assert t.count("\\expandafter") == 2  # noqa: PLR2004 - 未二重展开


# ---------------------------------------------------------------- 负面/幂等
def test_pream_negative_plain_preamble(tmp_path: Path) -> None:
    """字面 spec 与无关宏零命中 → decline, 文件原样。"""
    src = (
        "\\documentclass{article}\n"
        "\\usepackage{array}\n"
        "\\def\\myformat{lcc}\n"
        "\\begin{document}\n"
        "\\begin{tabular}{ll}a&b\\\\\\end{tabular}\n"
        "\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, note = _apply(tmp_path, "pt@format")
    assert not ok
    assert "0 files" in note
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == src


def test_pream_idempotent(tmp_path: Path) -> None:
    """改写一次后二发零命中 → decline (applied=False), 内容稳定。"""
    sty = (
        "\\def\\tablehead#1{\\tabular{\\@delspec}#1\\\\\\hline}\n"
        "\\newenvironment{deluxetable}[1]{\\def\\pt@format{\\string#1}}{}\n"
        "\\setbox\\pt@box=\\pt@tabular{\\pt@format}\\pt@head\n"
    )
    (tmp_path / "emulateapj.sty").write_text(sty, encoding="utf-8")
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    ok, _ = _apply(tmp_path, "pt@format")
    assert ok
    once = (tmp_path / "emulateapj.sty").read_text(encoding="utf-8")
    ok2, note2 = _apply(tmp_path, "pt@format")
    assert not ok2, note2
    assert (tmp_path / "emulateapj.sty").read_text(encoding="utf-8") == once


def test_pream_payload_isolation(tmp_path: Path) -> None:
    """payload ``@delspec`` 不动 ``\\pt@format`` 件——{payload} 字面锚定。"""
    sty = (
        "\\newenvironment{deluxetable}[1]{\\def\\pt@format{\\string#1}}{}\n"
        "\\setbox\\pt@box=\\pt@tabular{\\pt@format}\\pt@head\n"
    )
    (tmp_path / "emulateapj.sty").write_text(sty, encoding="utf-8")
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    ok, _note = _apply(tmp_path, "@delspec")
    assert not ok
    assert (tmp_path / "emulateapj.sty").read_text(encoding="utf-8") == sty


def test_pream_when_gating() -> None:
    """when 断言: 非 pream_token 类 / 缺 payload 皆不进入匹配面。"""
    rule = _rule()
    assert rule.when["category"] == "pream_token"
    # payload_required 语义: pay=None 时 _match_apply 跳过本规则
    assert rule.when.get("payload_required") is True


def test_let_chain_variant_two_let(tmp_path: Path) -> None:
    """缺 ``\\@acol`` 链节的变种 → 臂4 (2-let) 兜底。"""
    sty = (
        "\\def\\pt@tabular{\\hbox \\bgroup $\\let\\@classz\\@tabclassz\n"
        "   \\let\\@classiv\\@tabclassiv \\let\\\\\\@tabularcr\\@tabarray}\n"
        "\\setbox\\pt@box=\\pt@tabular{\\pt@format}\\pt@head\n"
    )
    (tmp_path / "emulateapj.sty").write_text(sty, encoding="utf-8")
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    ok, note = _apply(tmp_path, "pt@format")
    assert ok, note
    t = (tmp_path / "emulateapj.sty").read_text(encoding="utf-8")
    assert "\\let\\@classz" not in t
    assert "\\let\\@classiv" not in t
    assert "\\let\\\\\\@tabularcr\\@tabarray}" in t
