r"""ifscan 转义花括号 + operand 花括号回归单测 (impl2 pack 44)。

旧 TOKEN 正则 ``\\([a-zA-Z@]+)|([{}])`` 把 ``\{``/``\}`` 的 ``{}`` 当
开闭组 token——字面花括号 (控制符号) 腐蚀组栈: def 体内 ``\{`` 误开
grp 后真 ``}`` 错配收 grp, def 组残留 → 其后 ``\if`` 误判 def-open。
修复后 ``\\``/``\{``/``\%`` 等控制符号整枚成 token 由 dispatch 早跳
(operand 位仍占一枚预算)。

``\let\X{``/``\let\X}`` 的 operand 花括号同理占 operand 预算一枚、
不开闭组 (cond_ops 同款口径); ``\let{`` 名位花括号例外——仍开组、
不占预算 (test_let_bracename_operand_consumed 钉案)。
"""

from texlate.textutil import scan_ifs


def test_escaped_brace_not_group() -> None:
    r"""``\{``/``\}`` 字面花括号对 → 结构零影响, 全文无开闭组痕迹。"""
    r = scan_ifs("\\{\\}text\\{\\}\n\\begin{document}x\\end{document}\n")
    assert r.unclosed_live == []
    assert r.live_opens == 0
    assert r.live_closes == 0
    assert r.phantoms == []


def test_escaped_brace_does_not_corrupt_def_close() -> None:
    r"""``\def\foo{\{}\ifbaz`` —— ``\{`` 字面符非开组, ``}`` 闭 def 体,
    ``\ifbaz`` 是真活亏格 (旧版 ``\{`` 误开 grp → ``}`` 错配收 grp →
    def 组残留 → ``\ifbaz`` 误判 def-open 漏报活亏格)。"""
    r = scan_ifs("\\def\\foo{\\{}\\ifbaz\n\\begin{document}x\\end{document}\n")
    assert [o[0] for o in r.unclosed_live] == ["ifbaz"]
    assert r.live_opens == 1


def test_escaped_rbrace_not_close() -> None:
    r"""``\}`` 字面符非闭组——``{\}}`` 内层 ``\}`` 不抢收外层 ``{`` 组。"""
    # {\}}x\iffoo: 真 { 开组，\} 字面符，} 收组; \iffoo 活开亏格。
    r = scan_ifs("{\\}}x\\iffoo\n\\begin{document}x\\end{document}\n")
    assert [o[0] for o in r.unclosed_live] == ["iffoo"]


def test_ctrlsym_eats_cond_operand_slot() -> None:
    r"""``\ifx\\\ifbar`` —— ``\\`` 是首 operand, ``\ifbar`` 是次 operand
    (旧版 ``\\`` 不成 token 按两字面符抵满预算 → ``\ifbar`` 误计活开)。"""
    r = scan_ifs("\\ifx\\\\\\ifbar yes\\fi\n\\begin{document}x\\end{document}\n")
    assert r.unclosed_live == []
    assert r.live_opens == 1
    assert r.live_closes == 1
    assert ("ifbar", 1, "open") in r.phantoms  # operand 位在活帧内 → phantom


def test_let_lbrace_operand_not_group() -> None:
    r"""``\let\X{`` —— operand ``{`` 被吃不占组, ``\iftrue``/``\fi`` 活区平衡。"""
    r = scan_ifs("\\let\\X{\\iftrue yes\\fi\n\\begin{document}x\\end{document}\n")
    assert r.unclosed_live == []
    assert r.live_opens == 1
    assert r.live_closes == 1


def test_let_lbrace_operand_in_def_body() -> None:
    r"""def 体内 ``\let\Y{`` —— operand ``{`` 不开组, 后续 ``}`` 正收 def
    体, ``\ifbaz`` 落活区 (旧版 ``{`` 误开 grp → ``}`` 错配收 grp →
    def 残留 → ``\ifbaz`` 误判 def-open)。"""
    r = scan_ifs("\\def\\foo{x\\let\\Y{}\\ifbaz\n\\begin{document}x\\end{document}\n")
    assert [o[0] for o in r.unclosed_live] == ["ifbaz"]
    assert r.live_opens == 1


def test_let_rbrace_operand_not_close() -> None:
    r"""``\def\foo{\let\X}\ifbar`` —— ``}`` 是 ``\let`` operand 非闭组:
    def 体 EOF 未闭 (``\end{document}`` 在 def 内是死文不入 stops),
    ``\ifbar`` 落 def 冻结区非活亏格。"""
    src = "\\def\\foo{\\let\\X}\\ifbar\n\\begin{document}x\\end{document}\n"
    r = scan_ifs(src)
    assert r.unclosed_live == []
    assert r.live_opens == 0
    assert r.boundary == len(src)


def test_let_brace_name_still_opens_group() -> None:
    r"""``\let{`` 名位形不受 operand 抵扣影响——``{`` 仍开组, 组内
    operand cs 被吃 (与 test_let_bracename_operand_consumed 同案)。"""
    r = scan_ifs("\\let{\\iftrue}\n\\begin{document}x\\end{document}\n")
    assert r.unclosed_live == []
    assert r.live_opens == 0
