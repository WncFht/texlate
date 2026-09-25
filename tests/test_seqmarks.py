r"""seq 注锚（B 路 marked-content）——reconstruct 五闸 + resplice 偏移/自愈 + xelatex 实证。

规格锚点 = docs/dev/pdf-seq-anchors-impl-2026-09-23.md §2/§5：
``[[CHUNK_n]]`` 引用点按谓词包 ``\special{pdf:code /TLXC <</MCID 50000+seq>>
BDC}…\special{pdf:code EMC}``——xdvipdfmx 落内容流、pdf.js ``includeMarkedContent``
透出 ``span.markedContent[id$="_mc<N>"]``。五闸（skip ctx → 对齐 env → soul 栈 →
moving-arg → 行间界）保守方向 = 判不出不注；``seq_mark_issues`` 失衡即
``strip_seq_marks`` 全剥降级（丢锚不丢编译）。
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest
from conftest import DOC, scan_doc

from texlate.latex.reconstruct import (
    _MARK_CLOSE,
    SEQ_MARK_RX,
    _Expander,
    _mark_open,
    reconstruct,
    seq_mark_issues,
    strip_seq_marks,
    translation_tokens,
)
from texlate.repair_l2 import L2Attr, TreeRun, _resplice

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.latex.model import ScanResult

_PROSE_A = "First paragraph text here that is long enough to be a chunk for sure yes indeed it is."
_PROSE_B = (
    "Second paragraph also long enough to become its own chunk in the scan output."
)
_BODY2 = _PROSE_A + "\n\n" + _PROSE_B + "\n"
_ZH2 = {0: "第一段译文。", 1: "第二段译文。"}
_BASE = 50000  # SEQ_MARK_BASE


def _mcid(seq: int) -> str:
    return f"<</MCID {_BASE + seq}>>"


def _mk_exp(
    res: ScanResult,
    trans: dict[int, str],
    *,
    mark_seq0: int = 0,
    mark_moving: bool = False,
) -> _Expander:
    """顶层注锚口径的 expander（``glue_latin=True`` = 译文落盘侧同形）。"""
    return _Expander(
        res,
        translation_tokens(res, trans),
        glue_latin=True,
        mark_seq0=mark_seq0,
        mark_moving=mark_moving,
    )


# ---------------------------------------------------------------- 字节钉


def test_marks_wrap_chunk_expansion() -> None:
    """译文块引用点包 BDC…EMC——MCID = 50000+seq0+id 字节钉。"""
    res = scan_doc(_BODY2)
    zh = reconstruct(res, dict(_ZH2), mark_seq0=0)
    assert _mark_open(0) + _ZH2[0] + _MARK_CLOSE in zh
    assert _mark_open(1) + _ZH2[1] + _MARK_CLOSE in zh
    assert seq_mark_issues(zh) == []


def test_mark_seq0_offsets_mcid() -> None:
    """跨文件 seq 基址：``mark_seq0=7`` → MCID 50007/50008（未译块同序注锚）。"""
    res = scan_doc(_BODY2)
    zh = reconstruct(res, {0: "译文零。"}, mark_seq0=7)
    assert _mcid(7) in zh  # 已译块：译文包锚
    assert _mcid(8) in zh  # 未译块：原文包锚（seq 是区格标识非译文标识）


def test_identity_marks_byte_equal() -> None:
    """``translations=None`` + ``mark_seq0`` → identity 注锚（en.pdf 源侧锚）：

    剥锚后逐字节 = 原文（glue/cjk 修正随译文缺席而关），锚内是原文块体。
    """
    res = scan_doc(_BODY2)
    out = reconstruct(res, None, mark_seq0=0)
    assert _mark_open(0) + _PROSE_A + _MARK_CLOSE in out
    assert _mcid(1) in out
    assert _PROSE_B in out
    assert strip_seq_marks(out) == DOC % _BODY2
    assert seq_mark_issues(out) == []
    assert "TLXC" not in reconstruct(res)  # mark_seq0=None 旧面零副作用


def test_mark_seq0_none_no_marks() -> None:
    """有译文无 ``mark_seq0`` → 不注锚（旧调用面零副作用）。"""
    res = scan_doc(_BODY2)
    zh = reconstruct(res, dict(_ZH2))
    assert "TLXC" not in zh
    assert _ZH2[0] in zh


def test_in_brace_arg_marks() -> None:
    """``\\textbf{[[CHUNK_0]]}`` 内层 brace：whatsit 进 hmode 组合法 → 注锚。"""
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: "译文。"})
    out = ex.expand_body(r"\textbf{[[CHUNK_0]]}")
    assert out.startswith(r"\textbf{")
    assert out.endswith("}")
    assert _mark_open(0) + "译文。" + _MARK_CLOSE in out


def test_non_chunk_ph_never_marked() -> None:
    """非 ``[[CHUNK_n]]`` ph token（查无实体 → dangling 字面）→ 不注锚。"""
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: "译文。"})
    out = ex.expand_body("pre [[MATH_9]] post")
    assert "TLXC" not in out
    assert "[[MATH_9]]" in out
    assert "MATH_9" in ex.dangling or "[[MATH_9]]" in ex.dangling


# ---------------------------------------------------------------- 五闸


@pytest.mark.parametrize(
    "env",
    [
        "tabular",
        "tabularx",
        "longtable",
        "tblr",
        "array",
        "cases",
        "bmatrix",
        "nicetabular",
    ],
)
def test_align_env_skips(env: str) -> None:
    r"""对齐族 env 白名单化位判：``*matrix``/``nice*`` 数学对齐恒免注；
    具名对齐 env 在裸 piece 引用点（非序言/非行规缘）按 hmode 位照注
    ——env 标签不否决，whatsit 落点合法性才否决。"""
    res = scan_doc(_BODY2)
    res.chunks[0].env = env
    zh = reconstruct(res, dict(_ZH2), mark_seq0=0)
    if env.endswith("matrix") or env.startswith("nice"):
        assert _mcid(0) not in zh  # 数学对齐 env 恒免注
    else:
        assert _mcid(0) in zh  # 裸 hmode 位：whatsit 合法 → 照注
    assert _mcid(1) in zh  # chunk1 照注


@pytest.mark.parametrize(
    "body",
    [
        "\\multicolumn{3}{c}{[[CHUNK_0]]}",  # multicolumn 文字参内
        "x & [[CHUNK_0]] & y",  # 裸单元格（& 界内）
        "x & \\textbf{[[CHUNK_0]]} & y",  # 单元格内组合
        "a \\\\ [[CHUNK_0]] & b",  # 行界后首格（whatsit 开新行 cell）
        "a \\hline [[CHUNK_0]] & b",  # 行规后首格同上
    ],
)
def test_align_env_cell_sites_mark(body: str) -> None:
    r"""对齐 env 单元格内 whatsit 合法（hmode 组合/行首格隐式起点）→ 注锚。"""
    res = scan_doc(_BODY2)
    res.chunks[0].env = "tabular"
    ex = _mk_exp(res, {0: "译文。"})
    out = ex.expand_body(body)
    assert _mark_open(0) + "译文。" + _MARK_CLOSE in out


@pytest.mark.parametrize(
    "body",
    [
        "\\begin{tabular}{[[CHUNK_0]]}",  # 序言参内
        "\\begin{tabular}[t]{[[CHUNK_0]]}",
        "\\begin{tabular}{cc|[[CHUNK_0]]}",  # 序言中段
    ],
)
def test_align_env_preamble_skips(body: str) -> None:
    r"""``\begin{env}[opt]{preamble}`` 内 whatsit = 进参非法 → 免注。"""
    res = scan_doc(_BODY2)
    res.chunks[0].env = "tabular"
    ex = _mk_exp(res, {0: "译文。"})
    assert "TLXC" not in ex.expand_body(body)


@pytest.mark.parametrize(
    "body",
    [
        "a & [[CHUNK_0]] \\hline b",  # head 行规——marked 体后 \hline 行间错位
        "a & [[CHUNK_0]] \\midrule",
        "a & [[CHUNK_0]] \\multicolumn{2}{c}{x}",  # head omit 前瞻
    ],
)
def test_align_env_rule_head_skips(body: str) -> None:
    r"""对齐内 head 贴行规/omit 族 → 免注（``\\`` 后继合法不在此列）。"""
    res = scan_doc(_BODY2)
    res.chunks[0].env = "tabular"
    ex = _mk_exp(res, {0: "译文。"})
    assert "TLXC" not in ex.expand_body(body)


def test_align_env_expansion_edges_skip() -> None:
    r"""展开体头 ``\multicolumn``/尾 ``\\``（含 ph 边代换）→ 免注。"""
    res = scan_doc(_BODY2)
    res.chunks[0].env = "tabular"
    res.chunks[0].content = "\\multicolumn{2}{c}{x}"
    ex = _mk_exp(res, {})
    assert "TLXC" not in ex.expand_body("a & [[CHUNK_0]]")
    res.chunks[0].content = "cell text \\\\"
    ex = _mk_exp(res, {})
    assert "TLXC" not in ex.expand_body("a & [[CHUNK_0]]")
    # ph 边代换：译文以 [[CMD]] 收尾、CMD 体以 \\ 收尾 → 同样拦
    res.ph_map["[[CMD_9]]"] = "x \\\\"
    ex = _mk_exp(res, {0: "cell [[CMD_9]]"})
    assert "TLXC" not in ex.expand_body("a & [[CHUNK_0]]")


@pytest.mark.parametrize("ctx", ["section", "subsection", "caption", "addcontentsline"])
def test_moving_ctx_skips_unless_allowed(ctx: str) -> None:
    """moving-arg ctx：``mark_moving=False`` 免注（目录重放歧义）；True 放行。"""
    res = scan_doc(_BODY2)
    res.chunks[0].context = ctx
    zh = reconstruct(res, dict(_ZH2), mark_seq0=0)
    assert _mcid(0) not in zh
    zh2 = reconstruct(res, dict(_ZH2), mark_seq0=0, mark_moving=True)
    assert _mcid(0) in zh2


@pytest.mark.parametrize(
    "ctx", ["intertext", "shortintertext", "pdfbookmark", "index", "glossary"]
)
def test_skip_ctx_always_skips(ctx: str) -> None:
    """写流/书签类 ctx 硬免注——``mark_moving=True`` 也救不回。"""
    res = scan_doc(_BODY2)
    res.chunks[0].context = ctx
    zh = reconstruct(res, dict(_ZH2), mark_seq0=0, mark_moving=True)
    assert _mcid(0) not in zh


@pytest.mark.parametrize(
    "cs", ["ul", "hl", "sout", "uline", "uwave", "st", "letterspace"]
)
def test_soul_stack_skips(cs: str) -> None:
    r"""soul/ulem 族开栈内引用点 → 免注（whatsit 进参 = Reconstruction failed）。"""
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: "译文。"})
    out = ex.expand_body("\\" + cs + "{[[CHUNK_0]]}")
    assert "TLXC" not in out


def test_soul_nested_stack_skips() -> None:
    """嵌套 soul 栈同样免注；非 soul 包裹（``\\emph``）不拦。"""
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: "译文。"})
    assert "TLXC" not in ex.expand_body(r"\emph{\ul{[[CHUNK_0]]}}")
    out = ex.expand_body(r"\emph{[[CHUNK_0]]}")
    assert _mark_open(0) in out


# ---------------------------------------------------------------- 宏参扫描区


def test_pending_bdc_relocates_inside_text_arg() -> None:
    r"""``\href{u}|{t}`` 劈点 (t_e547 实证): BDC 挪进 text 参 ``{`` 内保锚。

    挪前 ``\href{u}\special{BDC}{t}`` → \href 吞 ``\special`` 作 arg2 →
    ``{pdf:code ...}`` 孤儿组 → ``Missing { inserted`` 级联硬毙。
    """
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: "{arXiv:2011.00110 [gr-qc]} 后续译文"})
    out = ex.expand_body(r"\href{https://arxiv.org/abs/2011.00110}[[CHUNK_0]]")
    assert (
        r"\href{https://arxiv.org/abs/2011.00110}{"
        + _mark_open(0)
        + "arXiv:2011.00110 [gr-qc]} 后续译文"
        + _MARK_CLOSE
    ) == out
    assert seq_mark_issues(out) == []


def test_pending_bdc_nontext_arg_skips() -> None:
    r"""``\cite|{key}`` 劈点: 待填参是结构参 → BDC 无处挪 → 裸发不注。"""
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: "{key1,key2}"})
    out = ex.expand_body(r"\cite[[CHUNK_0]]")
    assert "TLXC" not in out
    assert r"\cite{key1,key2}" in out


def test_pending_bdc_no_brace_head_skips() -> None:
    r"""``\href`` 后译文不以 ``{`` 起 → 参扫描直接吞 whatsit → 裸发不注。"""
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: "裸文本译文"})
    out = ex.expand_body(r"\href{u}[[CHUNK_0]]")
    assert "TLXC" not in out
    assert "裸文本译文" in out


def test_pending_emc_trims_before_macro() -> None:
    r"""展开体尾悬宏 → EMC 截到宏前（锚缩域）, head 参由宏自填。"""
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: r"条目正文 \href{https://doi.org/x}"})
    out = ex.expand_body("[[CHUNK_0]] {arXiv:1234 [cs]}")
    assert (
        _mark_open(0) + "条目正文 " + _MARK_CLOSE + r"\href{https://doi.org/x}"
    ) in out
    assert r"\href{https://doi.org/x} {arXiv:1234 [cs]}" in out


def test_pending_emc_after_emitted_mark_seen() -> None:
    r"""前块 EMC 不挡悬宏检出：``\href{u}\special{EMC}`` 尾仍判参区。"""
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: r"前块 \href{u}", 1: "{t} 后块"})
    out = ex.expand_body("[[CHUNK_0]][[CHUNK_1]]")
    # 块0 EMC 截 \href 前; 块1 BDC 挪 {t} 内——两臂合成全链合法
    assert _MARK_CLOSE + r"\href{u}{" + _mark_open(1) in out
    assert seq_mark_issues(out) == []


def test_open_nontext_brace_skips() -> None:
    r"""``\cite{key|key}`` 参内引用点 → 免注（key 域 whatsit 腐蚀）。"""
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: "key2"})
    out = ex.expand_body(r"\cite{key1,[[CHUNK_0]]}")
    assert "TLXC" not in out
    out = ex.expand_body(r"\url{[[CHUNK_0]]}")
    assert "TLXC" not in out
    out = ex.expand_body(r"\label{[[CHUNK_0]]}")
    assert "TLXC" not in out


def test_pending_begin_skips() -> None:
    r"""``\begin|{env}`` 劈点：env 名参 nontext → 裸发不注。"""
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: "{tabular}"})
    out = ex.expand_body(r"\begin[[CHUNK_0]]{cc}x\end{tabular}")
    assert "TLXC" not in out


@pytest.mark.parametrize(
    "body",
    [
        "a b \\\\\n[[CHUNK_0]]",  # \\ 行尾紧贴
        "a b \\\\[2pt]\n[[CHUNK_0]]",  # \\[opt] 行距参形态
    ],
)
def test_row_tail_skips(body: str) -> None:
    r"""chunk 前贴 ``\\``（含 ``[..]`` 垂直距参）→ 行间位免注。"""
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: "译文。"})
    assert "TLXC" not in ex.expand_body(body)


@pytest.mark.parametrize(
    "body",
    [
        "[[CHUNK_0]] \\\\\n\\hline x",  # \\ 后继
        "[[CHUNK_0]]\n\\hline x",  # \hline 后继
        "[[CHUNK_0]]\n\\midrule x",
        "[[CHUNK_0]]\n\\toprule\n",
    ],
)
def test_row_head_skips(body: str) -> None:
    r"""chunk 尾贴 ``\\``/行规族 token → 行间位免注（破 noalign 前瞻）。"""
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: "译文。"})
    assert "TLXC" not in ex.expand_body(body)


def test_row_gates_fall_back_to_site() -> None:
    """顶层 piece 体首/尾空 → 查 ``_site_prev``/``_site_next``（相邻 piece 界）。"""
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: "译文。"})
    ex.set_site(frozenset(), "a b \\\\", "")
    assert "TLXC" not in ex.expand_body("[[CHUNK_0]]")
    ex.set_site(frozenset(), "", "\\\\ x")
    assert "TLXC" not in ex.expand_body("[[CHUNK_0]]")
    ex.set_site(frozenset(), "", "")
    assert _mark_open(0) in ex.expand_body("[[CHUNK_0]]")


def test_nested_inherits_outer_context() -> None:
    """嵌套空缘引用点回落 ``_ctx_chain`` 外层邻居判闸（v11 链式语境）。

    - ``[[ENV_7]]`` 体 = 裸 ``[[CHUNK_0]]``：嵌套层首尾皆空 → 看外层
      引用点邻居——``\\ `` 行尾传染 → 拒注；孤立位 → 照注。
    - 嵌套体自身有字面邻居时邻居优先（``x [[CHUNK_0]] y`` 体内判）。
    """
    res = scan_doc(_BODY2)
    ex = _mk_exp(res, {0: "译文。"})
    res.ph_map["[[ENV_7]]"] = "[[CHUNK_0]]"
    # 外层引用点贴 \\ 行尾 → 嵌套空缘回落外层 tail → ROW_TAIL 拒注
    assert "TLXC" not in ex.expand_body("a \\\\ [[ENV_7]]")
    # 孤立位（全空语境）→ 无行界证据 → 注锚
    assert _mark_open(0) in ex.expand_body("[[ENV_7]]")
    # 嵌套体自带字面邻居 → 本层判（外层语境不遮）
    res.ph_map["[[ENV_8]]"] = "x [[CHUNK_0]] y"
    assert _mark_open(0) in ex.expand_body("[[ENV_8]]")
    # soul 栈经 ph 体前缀传染：嵌套 pre 的 _open_cs 照常命中
    res.ph_map["[[ENV_9]]"] = "\\ul{[[CHUNK_0]]}"
    assert "TLXC" not in ex.expand_body("[[ENV_9]]")


# ---------------------------------------------------------------- lint/剥面


def test_seq_mark_issues_clean() -> None:
    zh = _mark_open(0) + "a" + _MARK_CLOSE + _mark_open(1) + "b" + _MARK_CLOSE
    assert seq_mark_issues(zh) == []


def test_seq_mark_issues_imbalance_and_dup() -> None:
    bad = _mark_open(0) + "a" + _MARK_CLOSE + _mark_open(0) + "b"  # dup MCID + 失衡
    issues = seq_mark_issues(bad)
    assert any("bdc=2 emc=1" in i for i in issues)
    assert any("dup_mcid" in i and "50000" in i for i in issues)


def test_strip_seq_marks_all() -> None:
    zh = _mark_open(3) + "a" + _MARK_CLOSE + "mid" + _mark_open(4) + "b" + _MARK_CLOSE
    stripped = strip_seq_marks(zh)
    assert stripped == "amidb"
    assert seq_mark_issues(stripped) == []


# ---------------------------------------------------------------- resplice 面


def _mk_run(
    tmp_path: Path, files: dict[str, tuple[str, dict[int, str]]]
) -> tuple[Path, TreeRun]:
    """``{rel: (body, trans)}`` → workdir 落盘 + TreeRun（pipe 空——resplice 不触）。"""
    work = tmp_path / "w"
    scans = []
    trans: dict[int, dict[int, str]] = {}
    for i, (rel, (body, tr)) in enumerate(files.items()):
        f = work / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(DOC % body, encoding="utf-8")
        scans.append((f, scan_doc(body)))
        if tr:
            trans[i] = tr
    return work, TreeRun(scans=scans, trans=trans, chunk_ins={}, pipe=None)


def test_resplice_cross_file_seq_offset(tmp_path: Path) -> None:
    """seq0 = 前序文件 chunk 累计——sub.tex 首块 MCID = 50000+2+0。"""
    work, run = _mk_run(
        tmp_path,
        {
            "main.tex": (_BODY2, dict(_ZH2)),
            "sub.tex": (_PROSE_A + "\n", {0: "子文件译文。"}),
        },
    )
    _resplice(run, work, "main.tex", {0, 1}, seq_marks=True)
    main_zh = (work / "main.tex").read_text(encoding="utf-8")
    sub_zh = (work / "sub.tex").read_text(encoding="utf-8")
    assert _mcid(0) in main_zh
    assert _mcid(1) in main_zh
    assert _mcid(2) in sub_zh
    assert seq_mark_issues(sub_zh) == []


def test_resplice_seq_marks_off(tmp_path: Path) -> None:
    """``seq_marks=False`` → 重写零锚（显式关优先级高于 env 决议）。"""
    work, run = _mk_run(tmp_path, {"main.tex": (_BODY2, dict(_ZH2))})
    _resplice(run, work, "main.tex", {0}, seq_marks=False)
    zh = (work / "main.tex").read_text(encoding="utf-8")
    assert "TLXC" not in zh
    assert _ZH2[0] in zh


def test_resplice_env_flag_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``seq_marks=None`` → ``TEXLATE_NO_SEQ_MARKS`` env 决议（缺省开）。"""
    work, run = _mk_run(tmp_path, {"main.tex": (_BODY2, dict(_ZH2))})
    monkeypatch.setenv("TEXLATE_NO_SEQ_MARKS", "1")
    _resplice(run, work, "main.tex", {0})
    assert "TLXC" not in (work / "main.tex").read_text(encoding="utf-8")
    monkeypatch.delenv("TEXLATE_NO_SEQ_MARKS")
    _resplice(run, work, "main.tex", {0})
    assert "TLXC" in (work / "main.tex").read_text(encoding="utf-8")


def test_resplice_moving_ctx_marked(tmp_path: Path) -> None:
    r"""vtex 含 ``\tableofcontents`` 也全量注锚——moving ctx 照注（目录重放
    出的重复 occurrence 由读侧 seqpos occurrence 校验收敛）、para 同注。"""
    body = "\\tableofcontents\n\n" + _BODY2
    work, run = _mk_run(tmp_path, {"main.tex": (body, dict(_ZH2))})
    run.scans[0][1].chunks[
        0
    ].context = "section"  # post-parse 改面（谓词直读 Chunk.context）
    _resplice(run, work, "main.tex", {0}, seq_marks=True)
    zh = (work / "main.tex").read_text(encoding="utf-8")
    assert _mcid(0) in zh  # section chunk 照注
    assert _mcid(1) in zh  # para chunk 照注


def test_resplice_imbalance_self_heal(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """译文夹带游离 EMC → BDC≠EMC 失衡 → 剥净降级（锚全丢换编译面干净）。"""
    work, run = _mk_run(
        tmp_path,
        {"main.tex": (_BODY2, {0: "译文 " + _MARK_CLOSE + " 尾", 1: "二段。"})},
    )
    with caplog.at_level(logging.WARNING):
        _resplice(run, work, "main.tex", {0}, seq_marks=True)
    zh = (work / "main.tex").read_text(encoding="utf-8")
    assert "TLXC" not in zh
    assert "pdf:code EMC" not in zh
    assert "imbalanced" in caplog.text


def test_attribute_through_bdc_line_head(tmp_path: Path) -> None:
    """行首 BDC 前缀把 span 起点推出行首 off——attribute 须视同含行首。

    回归钉：标记态 file:line 归因曾 forward-fallback 错贴前块（e2e
    ``test_l2_retranslate_then_recompile`` 实证 hits '0:1' 而非 '0:2'）。
    """
    work, run = _mk_run(tmp_path, {"main.tex": (_BODY2, dict(_ZH2))})
    _resplice(run, work, "main.tex", {0}, seq_marks=True)
    lines = (work / "main.tex").read_text(encoding="utf-8").splitlines()
    line2 = next(i + 1 for i, ln in enumerate(lines) if _mcid(1) in ln)
    attr = L2Attr(run=run, work=work)
    attr.file_state(0)
    assert attr.attribute(0, line2) == 1
    # 对照：剥锚重写后同位置仍归 1——修复不破坏无锚归因
    (work / "main.tex").write_text(
        SEQ_MARK_RX.sub("", (work / "main.tex").read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    attr2 = L2Attr(run=run, work=work)
    attr2.file_state(0)
    stripped = (work / "main.tex").read_text(encoding="utf-8").splitlines()
    line2s = next(i + 1 for i, ln in enumerate(stripped) if _ZH2[1] in ln)
    assert attr2.attribute(0, line2s) == 1


# ---------------------------------------------------------------- xelatex 实证

_XELATEX = shutil.which("xelatex")


@pytest.mark.integration
@pytest.mark.skipif(_XELATEX is None, reason="xelatex not installed")
def test_xelatex_marked_content_stream(tmp_path: Path) -> None:
    r"""注锚稿真编译 → pypdf 解内容流 ``/TLXC <</MCID \d+>> BDC`` 在场 + log 无错位错。

    ``\special{pdf:code}`` 经 xdvipdfmx 原样落流；ASCII 伪译文避开 CJK 字体面，
    本钉只证 marked-content 存活与 ``Misplaced \noalign``/``Reconstruction failed``
    缺席（pdf.js DOM 侧锚面由 web/scripts/pdfanchor_verify.mjs 覆盖）。
    """
    res = scan_doc(_BODY2)
    zh = reconstruct(
        res,
        {0: "Translated paragraph one.", 1: "Translated paragraph two."},
        mark_seq0=0,
    )
    main = tmp_path / "main.tex"
    main.write_text(zh, encoding="utf-8")
    subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [_XELATEX, "-interaction=nonstopmode", "main.tex"],
        cwd=tmp_path,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert (tmp_path / "main.pdf").is_file()
    log_text = (tmp_path / "main.log").read_text(encoding="utf-8", errors="replace")
    assert "Reconstruction failed" not in log_text
    assert "Misplaced" not in log_text

    import pypdf  # noqa: PLC0415 -- integration 臂随用随引

    reader = pypdf.PdfReader(str(tmp_path / "main.pdf"))
    data = b"\n".join((p.get_contents().get_data() or b"") for p in reader.pages)
    mcids = re.findall(rb"/TLXC\s*<<\s*/MCID\s+(\d+)\s*>>\s*BDC", data)
    assert b"50000" in mcids
    assert b"50001" in mcids
    assert len(re.findall(rb"\bEMC\b", data)) >= len(mcids)
