r"""gullet.py 审计修复钉（latex-audit / latex-audit-core 2026-09-17）。

C1 ``_resolve_input`` 任意路径读（SECURITY：``\input`` 出界 = 本机文件
经 token 流 → chunk → LLM 网关的外泄面）、F8 无扩展名 ``\input`` 候选序、
F5 ``process_if`` 把 IfSetter/未注册 ``if*`` 宏计入嵌套、C4
``_read_grouping`` 定界符不看 ``{…}`` 屏蔽、F9b ``\protected``/``\global\let``
前缀链。v2 默认路径。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import DOC, blob, scan_doc, text_of

from texlate.latex import parse_file, reconstruct
from texlate.latex.gullet import Arg, Gullet, MacroDef
from texlate.latex.mouth import Tok

if TYPE_CHECKING:
    from pathlib import Path


def _ab_body() -> list[Tok]:
    """``A #1 Z`` 四 token 宏体——C4 两钉共用（Tok 会被展开消费，每次新造）。"""
    return [
        Tok("letter", "A", (0, 0, 1)),
        Tok("param", "#", (0, 1, 2)),
        Tok("other", "1", (0, 2, 3)),
        Tok("letter", "Z", (0, 3, 4)),
    ]


# ---------------------------------------------------------------- C1 路径闸


def test_audit_c1_input_abs_path_denied(tmp_path: Path) -> None:
    r"""``\input{/abs/outside.tex}`` 拒绝读取——missing_input，字节不进球。"""
    outside = tmp_path / "outside_secret.tex"
    outside.write_text("SECRET-ABS-CONTENT", encoding="utf-8")
    root = tmp_path / "paper"
    root.mkdir()
    g = Gullet(root_dir=str(root), top_dir=str(root))
    # win32 str(Path) 出 '\' —— TeX 面 \input 参数是 / 语法
    g.push_source(f"\\input{{{outside.as_posix()}}}\ndone", str(root / "main.tex"))
    out = text_of(g.expand_all())
    assert "SECRET-ABS-CONTENT" not in out
    assert "done" in out
    assert any(w.kind == "missing_input" for w in g.warnings)


def test_audit_c1_input_dotdot_escape_denied(tmp_path: Path) -> None:
    r"""``\input{../x}`` 穿出根目录同样拒绝。"""
    outside = tmp_path / "outside_secret.tex"
    outside.write_text("SECRET-REL-CONTENT", encoding="utf-8")
    root = tmp_path / "paper"
    root.mkdir()
    g = Gullet(root_dir=str(root), top_dir=str(root))
    g.push_source("\\input{../outside_secret}\ndone2", str(root / "main.tex"))
    out = text_of(g.expand_all())
    assert "SECRET-REL-CONTENT" not in out
    assert "done2" in out
    assert any(w.kind == "missing_input" for w in g.warnings)


def test_audit_c1_input_symlink_escape_denied(tmp_path: Path) -> None:
    r"""根内 symlink 指出界——real-path 闸拦的不只是 ``..``/绝对路径。"""
    outside = tmp_path / "outside_secret.tex"
    outside.write_text("SECRET-LINK-CONTENT", encoding="utf-8")
    root = tmp_path / "paper"
    root.mkdir()
    (root / "evil.tex").symlink_to(outside)
    g = Gullet(root_dir=str(root), top_dir=str(root))
    g.push_source("\\input{evil}\ndone3", str(root / "main.tex"))
    out = text_of(g.expand_all())
    assert "SECRET-LINK-CONTENT" not in out
    assert "done3" in out


def test_audit_c1_legit_input_still_resolves(tmp_path: Path) -> None:
    r"""对照：根内 ``\input{sub}``/子目录相对路径照常内联。"""
    (tmp_path / "sub.tex").write_text("SUB-CONTENT", encoding="utf-8")
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "deep.tex").write_text("DEEP-CONTENT", encoding="utf-8")
    main = tmp_path / "main.tex"
    main.write_text("pre \\input{sub} mid \\input{inner/deep} post", encoding="utf-8")
    res = parse_file(main)
    assert "SUB-CONTENT" in res.vtex
    assert "DEEP-CONTENT" in res.vtex
    assert not any(w.kind == "missing_input" for w in res.warnings)


def test_audit_c1_top_dir_escape_allowed_within(tmp_path: Path) -> None:
    r"""``top_dir`` 显式给 paper 根时，``../sib`` 的 paper 内引用仍解析。"""
    paper = tmp_path / "paper"
    (paper / "main").mkdir(parents=True)
    (paper / "shared").mkdir()
    (paper / "shared" / "defs.tex").write_text("SHARED-DEFS", encoding="utf-8")
    (tmp_path / "beyond.tex").write_text("BEYOND-PAPER", encoding="utf-8")
    main = paper / "main" / "main.tex"
    main.write_text("\\input{../shared/defs} \\input{../../beyond}", encoding="utf-8")
    res = parse_file(main, top_dir=paper)
    # paper 内 ../ → top_dir 内：放行；出 paper 根 → missing_input
    assert "SHARED-DEFS" in res.vtex
    assert "BEYOND-PAPER" not in res.vtex
    assert any(w.kind == "missing_input" for w in res.warnings)


# ---------------------------------------------------------------- F8 候选序


def test_audit_f8_tex_wins_over_extensionless(tmp_path: Path) -> None:
    r"""``foo``/``foo.tex`` 并存 → ``\input{foo}`` 取 ``foo.tex``（TeX 补扩展名）。"""
    (tmp_path / "foo").write_text("BARE-JUNK", encoding="utf-8")
    (tmp_path / "foo.tex").write_text("REAL-TEX-CONTENT", encoding="utf-8")
    main = tmp_path / "main.tex"
    main.write_text("pre \\input{foo} post", encoding="utf-8")
    res = parse_file(main)
    assert "REAL-TEX-CONTENT" in res.vtex
    assert "BARE-JUNK" not in res.vtex


def test_audit_f8_extensionless_only_still_resolves(tmp_path: Path) -> None:
    r"""仅裸名 ``foo`` 存在时仍内联（补全失败回落裸名，召回不丢）。"""
    (tmp_path / "foo").write_text("BARE-ONLY", encoding="utf-8")
    main = tmp_path / "main.tex"
    main.write_text("pre \\input{foo} post", encoding="utf-8")
    res = parse_file(main)
    assert "BARE-ONLY" in res.vtex


def test_audit_f8_explicit_ext_keeps_name(tmp_path: Path) -> None:
    r"""``\input{defs.sty}`` 带显式扩展名 → 原样查找（不追加 ``.tex``）。"""
    (tmp_path / "defs.sty").write_text("STY-CONTENT", encoding="utf-8")
    (tmp_path / "defs.sty.tex").write_text("STYTEX-SHADOW", encoding="utf-8")
    main = tmp_path / "main.tex"
    main.write_text("pre \\input{defs.sty} post", encoding="utf-8")
    res = parse_file(main)
    assert "STY-CONTENT" in res.vtex
    assert "STYTEX-SHADOW" not in res.vtex


# ---------------------------------------------------------------- C4 定界参组屏蔽


def test_audit_c4_bracket_arg_respects_brace_shield() -> None:
    r"""``\foo[{]}]X``：``{…}`` 内 ``]`` 不提前闭合可选参（xparse/TeX 同）。"""
    body = "\\newcommand{\\foo}[1][d]{SEE #1 END}\n\\foo[{]}]X tail text."
    res = scan_doc(body)
    assert reconstruct(res) == DOC % body
    # 展开体里 {]} 整组代入——若 ] 早闭合，} 会滞留流面
    b = blob(res)
    assert "SEE {]} END" in b


def test_audit_c4_nested_bracket_still_counts() -> None:
    r"""对照：``\foo[[x]]Y`` 裸 ``[`` 仍嵌套计数——arg = ``[x]``。"""
    g = Gullet()
    body = _ab_body()
    g.macros.set(
        "foo",
        MacroDef(name="foo", spec=[Arg("o")], body=body, kind="transparent_expand"),
    )
    g.push_source("\\foo[[x]]Y")
    assert text_of(g.expand_all()) == "A[x]ZY"


def test_audit_c4_angle_delim_shielded() -> None:
    r"""``d<>`` 定界参同款：``<a{>}b>`` 的 ``{>}`` 不提前闭合。"""
    g = Gullet()
    body = _ab_body()
    g.macros.set(
        "foo",
        MacroDef(
            name="foo",
            spec=[Arg("o", open="<", close=">")],
            body=body,
            kind="transparent_expand",
        ),
    )
    g.push_source("\\foo<a{>}b>Q")
    assert text_of(g.expand_all()) == "Aa{>}bZQ"


# ---------------------------------------------------------------- F5 \if 嵌套


def test_audit_f5_ifsetter_not_counted_as_if() -> None:
    r"""``\newif\ififx`` 的 ``\ifxtrue``（IfSetter）不计 ``\if`` 嵌套。

    修复前 ``\ifxtrue`` 名带 ``if`` → nesting+1 → 真 ``\fi`` 配给它 →
    ``if_unterminated`` + 文尾吞进死支（整文 0 chunk）。
    """
    g = Gullet("\\newif\\ififx\n\\ififx TRUE-PATH \\ifxtrue SETTER \\fi AFTER-FI-TEXT.")
    out = text_of(g.expand_all())
    assert not any(w.kind == "if_unterminated" for w in g.warnings)
    assert "AFTER-FI-TEXT" in out
    # dead 支的 \ifxtrue 未执行（收集走 raw read，无 setter 副作用）
    assert g.ifflags["ifx"] is False


def test_audit_f5_dead_branch_setter_no_side_effect() -> None:
    r"""被跳过分支内 ``\abctrue`` 不改旗标——死支收集是 raw read。"""
    g = Gullet("\\newif\\ifabc\n\\iffalse \\abctrue \\else KEEP \\fi TAIL")
    out = text_of(g.expand_all())
    assert "KEEP" in out
    assert "TAIL" in out
    assert g.ifflags["abc"] is False


def test_audit_f5_live_branch_setter_fires() -> None:
    r"""对照：选中支内的 IfSetter 照常在流内执行（TeX 语义）。"""
    g = Gullet("\\newif\\ifabc\n\\iftrue KEEP \\abctrue \\else DROP \\fi TAIL")
    out = text_of(g.expand_all())
    assert "KEEP" in out
    assert g.ifflags["abc"] is True


def test_audit_f5_unregistered_if_macro_not_counted() -> None:
    r"""未注册 ``\ifdef`` 族包宏非 TeX 条件——不计嵌套，``\fi`` 归外层。

    修复前 ``\iftrue KEEP \ifdef{X}{Y} DROP \fi`` → ``\ifdef`` 计一层 →
    真 ``\fi`` 被当内层闭合 → ``if_unterminated`` + ``\fi`` 裸 cs 泄漏 /
    ``\iffalse`` 形选支空 → 文尾整段 literalize。
    """
    g = Gullet("\\iftrue KEEP \\ifdef{X}{Y} DROP \\fi TAIL")
    out = text_of(g.expand_all())
    assert not any(w.kind == "if_unterminated" for w in g.warnings)
    assert "\\ifdef" in out
    assert "TAIL" in out
    assert "\\fi" not in out


def test_audit_f5_unregistered_if_macro_dead_branch() -> None:
    r"""``\iffalse`` 变体：未注册 ``\ifdef`` 在死支内也不计——选支正常。"""
    g = Gullet("\\iffalse DROP \\ifdef{X}{Y} \\else KEEP \\fi TAIL")
    out = text_of(g.expand_all())
    assert not any(w.kind == "if_unterminated" for w in g.warnings)
    assert "KEEP" in out
    assert "TAIL" in out


def test_audit_f5_registered_ifcond_still_counts() -> None:
    r"""对照：``\newif`` 注册的 IfCond 仍是真条件——计嵌套。"""
    g = Gullet("\\newif\\ifpdf\n\\iftrue A \\ifpdf B \\else C \\fi D \\fi E")
    out = text_of(g.expand_all())
    assert not any(w.kind == "if_unterminated" for w in g.warnings)
    # \ifpdf（flag 初 False）选 else 支 → C 支入流
    assert "C" in out
    assert "E" in out
    assert "\\fi" not in out


def test_audit_f5_prim_if_still_counts() -> None:
    r"""对照：原语 ``\ifnum`` 仍计嵌套——``\iftrue A \ifnum1<2 B\else C\fi D\fi``。"""
    g = Gullet("\\iftrue A \\ifnum 1<2 B \\else C \\fi D \\fi E")
    out = text_of(g.expand_all())
    assert not any(w.kind == "if_unterminated" for w in g.warnings)
    assert "B" in out
    assert "E" in out
    assert "\\else" not in out
    assert "\\fi" not in out


# ---------------------------------------------------------------- F9b 前缀链


def test_audit_f9b_protected_def_no_leak() -> None:
    r"""``\protected\def\pd{A}``：``\protected`` 不再泄独立 literal piece。"""
    g = Gullet("\\protected\\def\\pd{A}x")
    out = g.expand_all()
    assert text_of(out) == "x"
    e = g.macros.lookup("pd")
    assert e is not None
    # consumed marker 从 \protected 起算（整段 def 覆盖，src 同）
    mk = next(t for t in out if t.kind == "consumed")
    assert mk.text == "def:pd"
    assert mk.pos[1] == 0


def test_audit_f9b_protected_chain_orders() -> None:
    r"""``\global\protected\def``/``\protected\gdef``/``\long\global\def`` 任意序。"""
    for src, name in [
        ("\\global\\protected\\def\\gpd{A}t", "gpd"),
        ("\\protected\\gdef\\pgd{B}t", "pgd"),
        ("\\long\\global\\def\\lgd{C}t", "lgd"),
        ("\\outer\\protected\\long\\gdef\\xgd{D}t", "xgd"),
    ]:
        g = Gullet(src)
        out = text_of(g.expand_all())
        assert g.macros.lookup(name) is not None, src
        assert out == "t", src  # 前缀 token 无残留


def test_audit_f9b_global_let_writes_global_scope() -> None:
    r"""``{\global\let\gl\real}``：组内写底帧——组弹后 ``\gl`` 仍解析。

    修复前 ``\global`` 泄 literal + ``\let`` 局部执行 → 组闭弹表 ``\gl``
    消失。分段器驱动 scope（``{``/``}`` 推弹），这里手动推弹复现。
    """
    g = Gullet()
    g.push_source("\\def\\real{R}")
    g.expand_all()
    g.macros.push_scope()  # `{`
    g.push_source("\\global\\let\\gl\\real")
    g.expand_all()
    g.macros.pop_scope()  # `}`
    e = g.macros.lookup("gl")
    assert e is not None
    assert g.macros.resolve(e) is not None


def test_audit_f9b_local_let_still_pops() -> None:
    r"""对照：无前缀 ``\let`` 仍局部——组弹后 ``\gl`` 消失。"""
    g = Gullet()
    g.push_source("\\def\\real{R}")
    g.expand_all()
    g.macros.push_scope()
    g.push_source("\\let\\gl\\real")
    g.expand_all()
    g.macros.pop_scope()
    assert g.macros.lookup("gl") is None


def test_audit_f9b_prefix_unknown_target_passthrough() -> None:
    r"""``\protected``/``\global`` 后接非定义族 → 前缀回吐走普通流（保守）。"""
    g = Gullet("\\protected x\\global y")
    out = text_of(g.expand_all())
    assert "\\protected" in out
    assert "\\global" in out
    assert "x" in out
    assert "y" in out


def test_audit_f9b_parse_level_identity() -> None:
    r"""公开路径整链：``\protected\def``/``{\global\let}`` identity 不破。"""
    body = (
        "\\protected\\def\\pd{A}Body text long enough for its own chunk "
        "yes indeed \\pd end."
    )
    res = scan_doc(body)
    assert reconstruct(res) == DOC % body
    assert res.macros.lookup("pd") is not None

    body2 = (
        "\\def\\real{REALMACRO}\n"
        "{\\global\\let\\gl\\real}Body text long enough for own chunk \\gl."
    )
    res2 = scan_doc(body2)
    assert reconstruct(res2) == DOC % body2
    e = res2.macros.lookup("gl")
    assert e is not None
    assert res2.macros.resolve(e) is not None


def test_audit_f9b_global_newif() -> None:
    r"""``\global\newif\ifx``：三项登记写底帧——组弹后 ``\ifx``/``\xtrue`` 仍解析。"""
    g = Gullet()
    g.macros.push_scope()
    g.push_source("\\global\\newif\\ifq")
    g.expand_all()
    g.macros.pop_scope()
    assert g.macros.lookup("ifq") is not None
    assert g.macros.lookup("qtrue") is not None
