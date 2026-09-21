r"""key-arg 泄漏修复回归：跨边界待绑参吸纳 + S3 字面别名闸。

S1（≈85% 语料命中）：零参/不透明别名展开成 key-arg cs——
``\def\r{\ref}`` + ``\r{key}`` 的 ``{key}`` 必须在展开组内绑定；
S2：宏体尾待绑参——``\be{key}``→``\begin{eq}\label{key}`` 族；
S3：字面别名 cs 抵达分派未展开（``\noexpand`` 打标）→ 按 key-arg
族 ``_protect_cs`` 保护，参缺席记 ``keyarg_unbound``，``\r`` 不字面进
chunk。``\r``/``\S`` 等单字母名与 accent/INLINE_LITERAL 族撞名走各自
既有行（``\r a`` 是 ring accent）——S3 用 ``\R`` 避开撞名面。
"""

from conftest import DOC, blob, check_invariants, scan_doc

from texlate.latex.model import ScanResult

PROSE = " and the paragraph continues with enough plain prose to form a chunk."


def scan(body: str) -> ScanResult:
    res = scan_doc(body)
    check_invariants(res, DOC % body)  # 每个用例都过 identity+validate+平铺
    return res


def ph_body(res: ScanResult, typ: str) -> str:
    for k, v in res.ph_map.items():
        if k.startswith(f"[[{typ}_"):
            return v
    return ""


# ---------------------------------------------------------------- S1


def test_s1_def_alias_binds_key() -> None:
    r"""``\def\r{\ref}`` + ``\r{sec:a}``：``{sec:a}`` 入 ``[[REF]]`` 不落 chunk。"""
    res = scan("\\def\\r{\\ref}\nWe discuss Section~\\r{sec:a}" + PROSE)
    assert "[[REF_1]]" in blob(res)
    assert "{sec:a}" not in blob(res)
    assert ph_body(res, "REF") == "\\ref{sec:a}"
    assert res.ph_map.get("[[EXPAND_2]]") == "\\r{sec:a}"


def test_s1_newcommand_alias() -> None:
    r"""``\newcommand`` 别名同形。"""
    res = scan("\\newcommand{\\r}{\\ref}\nWe discuss Section~\\r{sec:a}" + PROSE)
    assert "{sec:a}" not in blob(res)
    assert ph_body(res, "REF") == "\\ref{sec:a}"


def test_s1_alias_space_before_arg() -> None:
    r"""``\r {sec:a}``（ws 分隔）同样绑参。"""
    res = scan("\\def\\r{\\ref}\nWe discuss Section~\\r {sec:a}" + PROSE)
    assert "{sec:a}" not in blob(res)
    assert ph_body(res, "REF") == "\\ref{sec:a}"


def test_s1_alias_chain() -> None:
    r"""``\rr``→``\r``→``\ref`` 链式别名。"""
    res = scan("\\def\\r{\\ref}\\def\\rr{\\r}\nWe discuss Section~\\rr{sec:a}" + PROSE)
    assert "{sec:a}" not in blob(res)
    assert ph_body(res, "REF") == "\\ref{sec:a}"


def test_s1_let_alias() -> None:
    r"""``\let\myref\ref``：Alias 目标解析到 ``ref`` 族。"""
    res = scan("\\let\\myref\\ref\nWe discuss Section~\\myref{sec:a}" + PROSE)
    assert "{sec:a}" not in blob(res)


def test_s1_cite_opt_arg() -> None:
    r"""``\def\c{\cite}`` + ``\c[see]{k9}``：opt+key 全绑。"""
    res = scan("\\def\\c{\\cite}\nAs shown \\c[see]{key9}" + PROSE)
    assert "{key9}" not in blob(res)
    assert ph_body(res, "CITE") == "\\cite[see]{key9}"


def test_s1_cite_star_arg() -> None:
    r"""``\c*{k2}``：星参不跳 ws 规则下紧邻 ``*`` 仍绑。"""
    res = scan("\\def\\c{\\cite}\nAs shown \\c*{k2}" + PROSE)
    assert "{k2}" not in blob(res)
    assert ph_body(res, "CITE") == "\\cite*{k2}"


def test_s1_nested_brace_key() -> None:
    r"""``\r{sec:{a}}``：内嵌组整段绑进。"""
    res = scan("\\def\\r{\\ref}\nWe discuss Section~\\r{sec:{a}}" + PROSE)
    assert ph_body(res, "REF") == "\\ref{sec:{a}}"


def test_s1_two_uses() -> None:
    r"""同段两处调用各自绑参。"""
    res = scan("\\def\\r{\\ref}\nFirst \\r{sec:a} then \\r{sec:b}" + PROSE)
    assert "{sec:a}" not in blob(res)
    assert "{sec:b}" not in blob(res)
    assert "\\ref{sec:a}" in res.ph_map.values()
    assert "\\ref{sec:b}" in res.ph_map.values()


def test_s1_label_alias() -> None:
    r"""``\def\l{\label}`` → ``[[LABEL]]`` 族。"""
    res = scan("\\def\\l{\\label}\nIntro \\l{sec:z}" + PROSE)
    assert "{sec:z}" not in blob(res)
    assert ph_body(res, "LABEL") == "\\label{sec:z}"


def test_s1_url_alias() -> None:
    r"""``\def\u{\url}`` → ``[[URL]]`` 族。"""
    res = scan("\\def\\u{\\url}\nSee \\u{http://x}" + PROSE)
    assert "http://x" not in blob(res)
    assert ph_body(res, "URL") == "\\url{http://x}"


# ---------------------------------------------------------------- S2


def test_s2_tail_label_in_env() -> None:
    r"""``\def\bl{\begin{lem}\label}`` + ``\bl{thm:x}`` → ``[[LABEL]]`` 绑 key。"""
    body = (
        "\\newtheorem{lem}{Lemma}\n\\def\\bl{\\begin{lem}\\label}\n"
        "\\bl{thm:x} Statement prose long enough to form a chunk of text. \\end{lem}"
    )
    res = scan(body)
    assert "{thm:x}" not in blob(res)
    assert ph_body(res, "LABEL") == "\\label{thm:x}"


def test_s2_math_env_tail_label() -> None:
    r"""``\be{eq:x}``→``\begin{equation}\label``：math env 无 ``\end`` 整组回
    literal——``{eq:x}`` 随调用点进 literal 段而非 chunk。"""
    body = (
        "\\def\\be{\\begin{equation}\\label}\n"
        "\\be{eq:x} E=mc^2 \\end{equation}\n"
        "After the equation we keep writing enough prose text to form a chunk."
    )
    res = scan(body)
    assert "{eq:x}" not in blob(res)


def test_s2_tail_text_then_ref() -> None:
    r"""``\newcommand{\eref}{Eq.~\,\ref}`` + ``\eref{eq:y}``：体中文本照出、
    尾参 ``{eq:y}`` 绑 ``[[REF]]``。"""
    res = scan("\\newcommand{\\eref}{Eq.~\\,\\ref}\nWe refer to \\eref{eq:y}" + PROSE)
    assert "{eq:y}" not in blob(res)
    assert "Eq.~" in blob(res)
    assert ph_body(res, "REF") == "\\ref{eq:y}"


def test_s2_tail_text_body() -> None:
    r"""``\def\see{see Section~\ref}``：体散文 + 尾 ``\ref`` 绑参。"""
    res = scan("\\def\\see{see Section~\\ref}\nAs \\see{sec:q} shows" + PROSE)
    assert "{sec:q}" not in blob(res)
    assert ph_body(res, "REF") == "\\ref{sec:q}"


# ---------------------------------------------------------------- S3


def test_s3_noexpand_alias_binds() -> None:
    r"""``\noexpand\R{sec:a}``：别名 cs 未展开到分派 → key-arg 族保护
    整调用 ``[[REF]]`` 盖 ``\R{sec:a}``。"""
    res = scan("\\def\\R{\\ref}\nWe discuss \\noexpand\\R{sec:a}" + PROSE)
    assert "{sec:a}" not in blob(res)
    assert ph_body(res, "REF") == "\\R{sec:a}"


def test_s3_noexpand_bare_warns() -> None:
    r"""``\noexpand\R`` 无参：cs-only ``[[REF]]`` + ``keyarg_unbound``。"""
    res = scan("\\def\\R{\\ref}\nWe discuss \\noexpand\\R and then prose" + PROSE)
    assert ph_body(res, "REF") == "\\R"
    assert "\\R" not in blob(res)
    assert any(w.kind == "keyarg_unbound" for w in res.warnings)


def test_s3_noexpand_par_boundary() -> None:
    r"""``\noexpand\R\n\n{sec:a}``：参不跨段界——cs-only + 告警，``{sec:a}``
    留字面。"""
    res = scan("\\def\\R{\\ref}\nWe discuss \\noexpand\\R\n\n{sec:a}" + PROSE)
    assert ph_body(res, "REF") == "\\R"
    assert any(w.kind == "keyarg_unbound" for w in res.warnings)


def test_s1_star_only_warns() -> None:
    r"""``\r*``：星参吸进但 ``{key}`` 缺席 → ``keyarg_unbound``。"""
    res = scan("\\def\\r{\\ref}\nWe discuss \\r* and then prose" + PROSE)
    assert ph_body(res, "REF") == "\\ref*"
    assert any(w.kind == "keyarg_unbound" for w in res.warnings)


# ---------------------------------------------------------------- 非回归


def test_direct_ref_unchanged() -> None:
    r"""直接 ``\ref{key}`` 不走吸纳路径，行为不变。"""
    res = scan("We discuss Section~\\ref{sec:a}" + PROSE)
    assert ph_body(res, "REF") == "\\ref{sec:a}"
    assert not any(w.kind == "keyarg_unbound" for w in res.warnings)


def test_cite_second_brace_is_text() -> None:
    r"""``\cite{a}{b}`` 的 ``{b}`` 是正文（mand=1 上限），不被吞。"""
    res = scan("As shown \\cite{a}{b} follows" + PROSE)
    assert ph_body(res, "CITE") == "\\cite{a}"
    assert "{b}" in blob(res)


def test_alias_par_boundary_not_bound() -> None:
    r"""``\r\n\n{sec:a}``：待绑参不跨 ``\par``——``{sec:a}`` 落字面 + 告警。

    组尾 ``\ref`` 未绑参 → surface 只出 ``\ref`` 字面（短段无 chunk 时
    不进 ph_map）；``{sec:a}`` 留第二段 chunk 文本——段界不跨是全代码
    库 ``ws_skip_arg``/``_peek_nonspace`` 的一致约定（残留面，告警留痕）。
    """
    res = scan("\\def\\r{\\ref}\nWe discuss \\r\n\n{sec:a}" + PROSE)
    assert "{sec:a}" in blob(res)
    assert any(w.kind == "keyarg_unbound" for w in res.warnings)
