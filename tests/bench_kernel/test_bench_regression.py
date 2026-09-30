r"""B2 fixtures 陷阱断言回归（docs/spec/benchmark.md §B2）——原型 ``miniscanner_test`` 断言矩阵移植到 ``texlate.latex``。

底材 ``bench/fixtures/*.tex``（入库，逐字节即语义——永不格式化/润色）：

- ``tricky.tex``：T01–T29 单点陷阱 26 条断言 + ``_meta`` 残留计数 info 行；
- ``tricky-209.tex``：LaTeX 2.09 旧式组合 3 条（``\beq/\eeq``、``\documentstyle``、``\def``）+ parse_ok；
- ``tricky-multi/``：T14 ``\input/\include`` 展平 4 条；
- ``xlat-traps.tex``：xlat 契约压力形 4 条（``@Xn``——产品遮蔽口径
  ``[[BIB_n]]``/``\href[[HREF_n]]``/``[[URL_n]]``，与 xlatbench SYNTHETIC S1–S4 同源）；
- ``tricky-w.tex``：W 系列野机制 11 条（``@Wnn`` ↔ corpus mechanisms.jsonl 台账行，
  infix-over/unbraced-args/arg-next-line/eol-pct-join/range-cite/discretionary/
  pct-comment/comment-macro/spaced-env/enddoc-tail/usepackage-comment）；
- ``tricky-w73/``：``\input{../...}`` 路径逃逸两向断言（gullet C1 openin_any 等价闸）——
  出 main/ 进 shared/（paper 根内，``top_dir=tricky-w73``）照常 resolved inline；
  出 paper 根进 fixtures/（根外）被拒 → ``missing_input``，逃逸句不进 chunks；
- ``tricky-wenc.tex``：W72 混合编码字节件（合法 UTF-8 序列 + 孤立 latin1 字节共存），
  走 ``decode_tex`` 单码选定路径——identity 基准同源改用 ``decode_tex`` 而非
  ``errors="replace"``，断言只锁 latin1 侧 ``café``（单码不可救的 utf8 侧形态留给
  normalize 分档层演进）；
- ``tricky-dollar.tex``：D 系列 dollar 族 10 条（``@Dnn`` ↔ corpus ``$``-leak
  归因亚型——散文 ``\$`` 转义、``\section``/``\textit``/``\item``/footnote 组参内 ``\$``、
  ``$$..env..`` 区内空行照常配对、孤 ``$$``/孤 ``$`` → CMD ph + ``unpaired_dollar``、
  ``\$`` 与 ``$x$`` 同行混排 CMD+MATH 双路）；
- ``tricky-mask.tex``：M 系列 MASK 族 11 条（``@Mnn`` ↔ W07/W11/W84/W92 机制钉——
  comment env 死块三态行锚、docclass/usepackage 跨行夹注释参、行尾 ``%`` 拼接、
  注释内孤立 ``$`` 不参配对；``env_name_at``/``unescaped_dollar_odd`` 修复面）。

断言矩阵本体（``assert_tricky`` / ``assert_209`` / ``assert_multi`` / ``assert_xlat``
/ ``assert_w`` / ``assert_w73`` / ``assert_wenc`` / ``assert_dollar`` / ``assert_mask``
与测量包 ``_PARSED``/``run_fixture``/``FixtureScan`` 等）单源在
``bench/py/specs/_fixture_matrix.py``，与 bench 跑分器 ``bench/py/fixture_assert.py``
共享；本文件只留 pytest 驱动面。
门槛（docs/spec/benchmark.md §B2）：72 条 dict 断言全 ``pass``——``partial`` 在原型里是容忍档，
但产品现状全 pass，退化到 partial 即回归，这里按 ``== "pass"`` 严判。
"""

from __future__ import annotations

import pytest
from specs._fixture_matrix import (
    _PARSED,
    ALL_FIXTURE_NAMES,
    ASSERTS_209,
    D_IDS,
    DOLLAR_ASSERTS,
    IDS_209,
    M_IDS,
    MASK_ASSERTS,
    MULTI_ASSERTS,
    MULTI_IDS,
    TRICKY_ASSERTS,
    TRICKY_IDS,
    W73_ASSERTS,
    W73_IDS,
    W_ASSERTS,
    W_IDS,
    WENC_ASSERTS,
    WENC_IDS,
    XLAT_ASSERTS,
    XLAT_IDS,
    classify_recon,
    scan_chunks,
)

from texlate.latex import validate_result

# ---------------------------------------------------------------- 逐 fixture 结构断言


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_parse_ok(name: str) -> None:
    """解析零异常（含 30s 超时护栏）。"""
    p = _PARSED[name]
    assert p.ok, p.error


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_identity_reconstruct(name: str) -> None:
    """identity 重建 == ``res.vtex``（逐字节）。

    v2 的 identity 基准是 vtex（展开机产出文本），不是 flatten 输出——
    cs 后空白被 tokenizer 吞、``\\if`` 死支不落地等差异属产品语义。
    """
    p = _PARSED[name]
    assert p.ok, p.error
    assert p.res is not None
    status, _ratio, _first = classify_recon(p.res.vtex, p.recon)
    assert status == "identical", f"{status} first_diff_at={_first}"


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_no_placeholder_residue(name: str) -> None:
    """假译文重建后无 ``[[CHUNK_n]]``/``[[TYPE_n]]`` 残留。"""
    p = _PARSED[name]
    assert p.ok, p.error
    assert p.residue_chunk_ph == 0
    assert p.residue_protect_ph == 0


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_validate_result_clean(name: str) -> None:
    """``validate_result`` 结构校验零告警（孤儿 chunk/死 ph/平铺/悬空引用全覆盖）。"""
    p = _PARSED[name]
    assert p.ok, p.error
    assert p.res is not None
    assert validate_result(p.res) == []


#: 各 fixture 期望的 warning kind 集（缺省 = 零 warning）。w73 的
#: ``missing_input`` 是 C1 闸拒根外逃逸的断言面本身，由 ``test_w73`` 两向锁定。
#: 多重集口径（sorted 精确比对）——tricky-dollar 的 D07/D08/D09 三个孤 ``$$``/``$``
#: 各产一条 ``unpaired_dollar``，期望值必须列足 3 条。
_EXPECTED_WARN_KINDS: dict[str, set[str] | list[str]] = {
    "tricky-w73/main/main.tex": {"missing_input"},
    "tricky-dollar.tex": [
        "unpaired_dollar",
        "unpaired_dollar",
        "unpaired_dollar",
    ],
}


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_no_parse_warnings(name: str) -> None:
    """解析 ``ScanWarning`` 精确匹配期望集（缺省零——unclosed_env 等任一即回归）。"""
    p = _PARSED[name]
    assert p.ok, p.error
    assert p.res is not None
    kinds = [w.kind for w in p.res.warnings]
    assert sorted(kinds) == sorted(_EXPECTED_WARN_KINDS.get(name, set()))


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_no_chunk_leaks(name: str) -> None:
    """可译 chunk 内零泄漏（LEAK_PATTERNS 六类受保护构造）。"""
    p = _PARSED[name]
    assert p.ok, p.error
    assert p.res is not None
    lk = scan_chunks(p.res)
    assert lk["n_leaked"] == 0, lk["examples"]


# ---------------------------------------------------------------- tricky.tex 逐条


@pytest.mark.parametrize("tid", TRICKY_IDS)
def test_tricky(tid: str) -> None:
    """tricky.tex 逐条陷阱断言（断言体在 ``assert_tricky``）。"""
    a = TRICKY_ASSERTS.get(tid)
    assert a is not None, f"missing assertion {tid} (parse failed?)"
    assert a["status"] == "pass", f"{tid} {a['status']}: {a['detail']}"


def test_tricky_matrix_complete() -> None:
    """断言矩阵只增不减：新增 ``@Tnn`` 断言必须登记进 ``TRICKY_IDS``。"""
    assert set(TRICKY_ASSERTS) == set(TRICKY_IDS) | {"_meta"}


def test_tricky_meta_info() -> None:
    """``_meta`` info 行在（残留计数由 ``test_no_placeholder_residue`` 严判）。"""
    assert TRICKY_ASSERTS["_meta"]["status"] == "info"


# ---------------------------------------------------------------- tricky-209 / tricky-multi


def test_209_parse_ok() -> None:
    assert ASSERTS_209["parse_ok"] is True


@pytest.mark.parametrize("aid", IDS_209)
def test_209(aid: str) -> None:
    a = ASSERTS_209[aid]
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


@pytest.mark.parametrize("aid", MULTI_IDS)
def test_multi(aid: str) -> None:
    a = MULTI_ASSERTS.get(aid)
    assert a is not None, f"missing assertion {aid} (parse failed?)"
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


# ---------------------------------------------------------------- xlat-traps 逐条


@pytest.mark.parametrize("aid", XLAT_IDS)
def test_xlat(aid: str) -> None:
    """xlat-traps.tex 逐条遮蔽形状断言（断言体在 ``assert_xlat``）。"""
    a = XLAT_ASSERTS.get(aid)
    assert a is not None, f"missing assertion {aid} (parse failed?)"
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


def test_xlat_matrix_complete() -> None:
    """断言矩阵只增不减：新增 ``@Xn`` 断言必须登记进 ``XLAT_IDS``。"""
    assert set(XLAT_ASSERTS) == set(XLAT_IDS)


# ---------------------------------------------------------------- tricky-w / w73 / wenc 逐条


@pytest.mark.parametrize("aid", W_IDS)
def test_w(aid: str) -> None:
    """tricky-w.tex W 系列野机制逐条断言（断言体在 ``assert_w``）。"""
    a = W_ASSERTS.get(aid)
    assert a is not None, f"missing assertion {aid} (parse failed?)"
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


def test_w_matrix_complete() -> None:
    """``@Wnn`` 断言与 ``W_IDS`` 登记一致（只增不减口径同 tricky）。"""
    assert set(W_ASSERTS) == set(W_IDS) | {"_meta"}


@pytest.mark.parametrize("aid", W73_IDS)
def test_w73(aid: str) -> None:
    """tricky-w73 ``\\input{../}`` 路径逃逸断言。"""
    a = W73_ASSERTS.get(aid)
    assert a is not None, f"missing assertion {aid} (parse failed?)"
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


@pytest.mark.parametrize("aid", WENC_IDS)
def test_wenc(aid: str) -> None:
    """tricky-wenc 混合编码字节件断言。"""
    a = WENC_ASSERTS.get(aid)
    assert a is not None, f"missing assertion {aid} (parse failed?)"
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


# ---------------------------------------------------------------- tricky-dollar 逐条


@pytest.mark.parametrize("aid", D_IDS)
def test_dollar(aid: str) -> None:
    """tricky-dollar.tex D 系列 ``$``-leak 亚型逐条断言（断言体在 ``assert_dollar``）。"""
    a = DOLLAR_ASSERTS.get(aid)
    assert a is not None, f"missing assertion {aid} (parse failed?)"
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


def test_dollar_matrix_complete() -> None:
    """``@Dnn`` 断言与 ``D_IDS`` 登记一致（只增不减口径同 tricky/w）。"""
    assert set(DOLLAR_ASSERTS) == set(D_IDS) | {"_meta"}


# ---------------------------------------------------------------- tricky-mask 逐条


@pytest.mark.parametrize("aid", M_IDS)
def test_mask(aid: str) -> None:
    """tricky-mask.tex M 系列 MASK 族逐条断言（断言体在 ``assert_mask``）。"""
    a = MASK_ASSERTS.get(aid)
    assert a is not None, f"missing assertion {aid} (parse failed?)"
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


def test_mask_matrix_complete() -> None:
    """``@Mnn`` 断言与 ``M_IDS`` 登记一致（只增不减口径同 tricky/w/dollar）。"""
    assert set(MASK_ASSERTS) == set(M_IDS) | {"_meta"}
