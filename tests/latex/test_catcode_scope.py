r"""catcode 组作用域回归 —— ``\catcode``/``\makeatletter`` 写组局部化钉版。

取证现场 ``bench/corpus/0707.4206/extracted/pstricks.tex``：
``{\catcode`\p=12 ...}`` 的写曾泄出 ``}``——cat 表是平表、组不记账，
``p``/``t`` 永久落 12 → ``\psset@border`` 整名被斩成 ``\p``+字面
``sset@border``，宏表长出 ``p``/``t``/``new``/``@@`` 碎名，chunk 里
``st@getlength``/``sk@border`` 残段进译文面。

机制：``CatTable`` 挂 per-frame undo log（``set`` 记帧内首写旧值，
``pop`` 回放），scope 事件两侧共主——分段器 ``lbrace``/``rbrace``/
env 推弹（body 档 ``_dispatch`` + preamble 档 ``_preamble_tok`` 同报），
``\begingroup``/``\endgroup``/``\bgroup``/``\egroup`` 由 gullet
``_exec_prim`` 在分派点直接推弹（cs 形不另报，免双推）。

TeX 同义边界：被改的字母出现在闭名里则闭名自斩——
``\bgroup\catcode`\p=12 \egroup`` 的 ``\egroup`` 在真 TeX 里同样
读不出（``\egrou``+``p``），组永不闭合；本文件不钉这类自伤形。
"""

import re
from pathlib import Path

import pytest
from conftest import ART, DOC, blob, check_invariants

from texlate.latex import parse_file, parse_tex
from texlate.latex.model import ScanResult

CORPUS_V3 = Path(__file__).resolve().parents[2] / "bench" / "corpus"
PSTRICKS = CORPUS_V3 / "0707.4206" / "extracted" / "pstricks.tex"

# 斩名指纹：``\p ``/``\t `` 裸单字母 cs——残段串 ``st@``/``sk@``/``sunit``
# 恒是整名（``\pst@getlength``/``\psk@tbarsize``/``\psunit``）的子串，
# 子串断言必误报，只钉 cs 斩口形。
_CHOPPED_CS_RX = re.compile(r"\\[pt]\s")


def scan(body: str, preamble: str = "") -> ScanResult:
    tex = DOC % body if not preamble else ART % (preamble + "\n", body)
    res = parse_tex(tex)
    check_invariants(res, tex)
    return res


def base_names(res: ScanResult) -> set[str]:
    """末态 scope 链全帧可见名（底帧 + 未弹帧并查）。"""
    return {n for s in res.macros.scopes for n in s}


# ------------------------------------------------------------ brace 组回收


def test_catcode_write_reverts_at_rbrace() -> None:
    r"""``{\catcode`\p=12\relax}`` 后 ``\psetup`` 整名登记——``p`` 回 11。"""
    res = scan(r"{\catcode`\p=12\relax}\def\psetup{x}")
    names = base_names(res)
    assert "psetup" in names
    assert "p" not in names  # 泄漏旧世界：\def\p setup{x} → 碎名 'p'


def test_catcode_group_inside_preamble() -> None:
    r"""preamble 档 ``{…}`` 组同收——``\input`` 进 preamble 的 .sty 即此路径。"""
    res = scan(r"\def\psetup{x}", preamble=r"{\catcode`\p=12\relax}")
    names = base_names(res)
    assert "psetup" in names
    assert "p" not in names


def test_makeatletter_reverts_at_rbrace() -> None:
    r"""``{\makeatletter}`` 后 ``@`` 回 12：``\baz@qux`` → ``\baz`` + 字面参。"""
    res = scan(r"{\makeatletter\def\foo@bar{x}}\def\baz@qux{y}")
    names = base_names(res)
    assert "baz" in names
    assert "baz@qux" not in names
    assert "foo@bar" not in names  # 组内 def 随组弹


# --------------------------------------------------------- 原语组推弹（gullet）


def test_begingroup_endgroup_restores_brace_catcodes() -> None:
    r"""``\begingroup\catcode`\[=1 \catcode`\]=2 …\endgroup`` 后 ``{}`` 仍是组界。"""
    res = scan(
        r"\begingroup\catcode`\[=1 \catcode`\]=2 \gdef\w[x]#1{[#1]}\endgroup"
        r"\def\x{a}"
    )
    names = base_names(res)
    assert "x" in names  # 若 } 留在 12，\def\x{a} 的 {a} 不再成组
    assert "w" in names  # \gdef 写底帧——组弹不撤（TeX \global 语义）


def test_begingroup_scopes_macro_defs() -> None:
    r"""``\begingroup\def\localmac…\endgroup``：宏定义同收——双泄漏同修。"""
    res = scan(r"\begingroup\def\localmac{x}\endgroup\def\keep{y}")
    names = base_names(res)
    assert "keep" in names
    assert "localmac" not in names


def test_bgroup_egroup_scope_pair() -> None:
    r"""``\bgroup``/``\egroup`` 显式组界：组内 catcode 写不泄。

    闭名字母避开被改字符（``\egroup`` 含 ``p``——真 TeX 同样自斩，不钉）。"""
    res = scan(r"\bgroup\catcode`\q=12 \egroup\def\psetup{x}")
    names = base_names(res)
    assert "psetup" in names
    assert "p" not in names


# ------------------------------------------------------------ 实文件回归


@pytest.mark.skipif(not PSTRICKS.exists(), reason="corpus 数据不在场（gitignored）")
def test_pstricks_no_chopped_cs_fragments() -> None:
    r"""pstricks.tex 整文：``\psset@border{0pt}`` 整调用罩 ph，无 ``\p `` 斩名残段。"""
    res = parse_file(str(PSTRICKS), flatten=False)
    vals = {str(v) for v in res.ph_map.values()}
    assert "\\psset@border{0pt}" in vals
    names = base_names(res)
    for chopped in ("p", "t", "new", "@", "@@", "begin@O"):
        assert chopped not in names
    content = blob(res)
    m = _CHOPPED_CS_RX.search(content)
    assert m is None, "斩名残段进 chunk：" + m.group(0)
