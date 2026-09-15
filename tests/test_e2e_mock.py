r"""跨模块集成测试（M0）：``parse_file → XlatPipeline(Mock+L0) → reconstruct`` 全链。

覆盖的层间契约（每层一处断言）：

- ``latex.Chunk`` → ``xlat.ChunkIn`` 映射：``id``(int)→``chunk_id``(str)、
  ``context``→``normalize_kind``→``kind``；
- L0 校验器按 ``validator(src, zh) -> str`` 协议注入阶梯（空串=通过，
  ``L0Report.feedback()`` 即此形态）；
- ``r.skipped`` 结果**回退原文**进 splice——``fallback_orig`` 的
  ``translation`` 字段即原文（best_zh 残译文折进 warnings 留诊断）；
- reconstruct 后零占位符泄漏；``translations=None`` identity 逐字节还原。

``bench/corpus`` 数据层 gitignored——corpus 用例 skipif 守卫；
合成用例不依赖语料（CI 可跑），含 tmp_path 多文件 flatten 一例。
"""

import asyncio
import re
from pathlib import Path

import pytest

from texlate.latex import (
    parse_file,
    parse_tex,
    reconstruct,
    validate_result,
    validate_translation,
)
from texlate.latex.flatten import flatten_inputs
from texlate.latex.model import ScanResult
from texlate.validate.l0 import validate_pair
from texlate.xlat.pipeline import (
    ChunkIn,
    ChunkResult,
    MockTranslator,
    PipelineConfig,
    XlatPipeline,
)
from texlate.xlat.prompts import all_kinds, normalize_kind

CORPUS = Path(__file__).resolve().parents[1] / "bench" / "corpus"

needs_corpus = pytest.mark.skipif(
    not CORPUS.is_dir(), reason="bench/corpus 数据层不在场（gitignored 重产物）"
)

#: (paper_dir, 主文件) —— 覆盖多文件 /input、宏重 preamble、脆弱间距（~x.
#: 形态）、subfiles 类四型陷阱；选 124~364 chunk 的中型稿控制测试时长。
_CORPUS_PAPERS = [
    pytest.param("1706.03762", "ms.tex", id="attention-multifile"),
    pytest.param("1906.08237", "neurips_2019.tex", id="math-commands-macro"),
    pytest.param("2005.11401", "neurips_2020.tex", id="gpt3-fragile-spacing"),
    pytest.param("2203.02155", "neurips_2021.tex", id="subcaption"),
    pytest.param("2609.06443", "main.tex", id="subfiles-13tex"),
]

_STRUCTURAL_WARN_KINDS = {"dangling_ph", "dangling_chunk_ref", "pieces_gap"}

_DOC = "\\documentclass{article}\n%s\n\\begin{document}\n%s\n\\end{document}\n"

_SYNTH_PREAMBLE = (
    "\\newcommand{\\vect}[1]{\\mathbf{#1}}\n\\usepackage{amsmath}\n% preamble 注释"
)

_SYNTH_BODY = r"""% 段间注释行：须保持逐字节
\section{Introduction}
The model maps $\vect{x}$ to an output distribution. See Fig.~\ref{fig:arch}
and Table~\ref{tab:res} for details~\cite{vaswani2017}.
A second sentence ends here.

\begin{itemize}
\item First point about $O(n^2)$ complexity.
\item Second point, cf. \eqref{eq:attn} and \emph{emphasized} text.
\end{itemize}

\begin{equation}
\mathrm{Attn}(Q,K,V)=\mathrm{softmax}(QK^\top/\sqrt{d})V
\label{eq:attn}
\end{equation}
"""


def _l0_feedback(src: str, zh: str) -> str:
    """L0 全量规则 → pipeline ``validator`` 协议（error 文案串，空=通过）。"""
    return validate_pair(src, zh).feedback()


def _inputs(res: ScanResult) -> list[ChunkIn]:
    """``latex.Chunk`` → ``xlat.ChunkIn``（契约映射的唯一写法）。"""
    return [
        ChunkIn(
            chunk_id=str(c.id),
            content=c.content,
            kind=normalize_kind(c.context),
        )
        for c in res.chunks
    ]


def _run_mock(res: ScanResult, **kw: object) -> list[ChunkResult]:
    """Mock 管线跑完整篇（默认把 L0 接进 validator 位——生产同款接线）。"""
    kw.setdefault("validator", _l0_feedback)
    pipe = XlatPipeline(
        translator=MockTranslator(),
        config=PipelineConfig(concurrency=4),
        **kw,
    )
    return asyncio.run(pipe.run(_inputs(res)))


def _translations(res: ScanResult, results: list[ChunkResult]) -> dict[int, str]:
    """``{chunk_id: 译文}``；``skipped`` 一律回退原文（splice 侧契约）。"""
    return {
        c.id: (r.source if r.skipped else r.translation)
        for c, r in zip(res.chunks, results, strict=True)
    }


def _assert_no_placeholder_leak(res: ScanResult, out: str) -> None:
    """已签发 token 一个都不许留在成品里（未签发字面 ``[[X_99]]`` 可透传）。"""
    issued = set(res.ph_map) | {f"[[CHUNK_{c.id}]]" for c in res.chunks}
    leaked = [tok for tok in issued if tok in out]
    assert leaked == []


def _ws_fold(s: str) -> str:
    """surface 等价折叠：run 内空白/单 ``\\n`` → 一个空格；``\\n\\n`` 段界保留。"""
    return re.sub(r"[^\S\n]+|(?<!\n)\n(?!\n)", " ", s)


def _assert_mock_chain(res: ScanResult, flat: str) -> str:
    """良性 mock 全链断言：全 ok → L0 复核 → 占位符契约 → splice 成品。"""
    results = _run_mock(res)

    # 1) 全块 ok：Mock 是守规矩模型，fault/skipped/partial 出现即接缝信号
    assert [r.status for r in results] == ["ok"] * len(res.chunks)
    assert not any(r.skipped for r in results)

    # 2) L0 复核存下来的 (src, zh) 对（post-decode 形态，双侧注释豁免在内）
    bad = [r.chunk_id for r in results if not validate_pair(r.source, r.translation).ok]
    assert bad == []

    # 3) latex 侧译文契约：chunk.placeholders 全列在、无幻觉占位符
    bad_v = [
        c.id
        for c, r in zip(res.chunks, results, strict=True)
        if not validate_translation(c, r.translation).ok
    ]
    assert bad_v == []

    # 4) splice：零占位符泄漏 + 翻译确实发生
    out = reconstruct(res, _translations(res, results))
    _assert_no_placeholder_leak(res, out)
    assert "这是译文" in out
    assert out != flat
    return out


# ---------------------------------------------------------------- 合成用例（CI 可跑）


def test_synthetic_full_chain() -> None:
    """单文件合成 doc：宏定义/注释/~ref/cite/inline math/itemize/公式环境。"""
    src = _DOC % (_SYNTH_PREAMBLE, _SYNTH_BODY)
    res = parse_tex(src)
    assert res.chunks, "合成 doc 未产出 chunk"
    assert reconstruct(res) == src  # identity 逐字节

    out = _assert_mock_chain(res, src)
    # 结构命令与宏本体原样保留（mock 只动散文 run）
    assert "\\section{" in out
    assert "\\begin{itemize}" in out
    assert "\\vect{x}" in out  # $\vect{x}$ 经 [[MATH_n]] 保护，展开回原文逐字


def test_synthetic_multifile_flatten(tmp_path: Path) -> None:
    r"""``\input`` 真文件 flatten：跨文件 chunk 在同一 ScanResult 里走全链。"""
    (tmp_path / "sub.tex").write_text(
        "A subsection body with $e^{ix}$ math and \\cite{b}.\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\section{S}\nMain body text here for translation.\n"
        "\\input{sub}\n\\end{document}\n",
        encoding="utf-8",
    )
    res = parse_file(main)
    flat = flatten_inputs(
        main.read_text(encoding="utf-8"), str(tmp_path), str(tmp_path)
    )
    assert "\\cite{b}" in flat  # 展平确已发生
    assert reconstruct(res) == flat
    _assert_mock_chain(res, flat)


def test_all_fault_splices_source() -> None:
    """validator 恒败 → fault+skipped → splice 回退原文 = identity。

    ``fallback_orig`` 语义（2026-09-15 加固后）：``ChunkResult.translation``
    = 原文而非阶梯 best_zh 残译文——``skipped`` 门控仍是正确姿势，但下游
    即使误读 .translation 也只会拿到原文，名实相符。
    """
    res = parse_tex(_DOC % ("", _SYNTH_BODY))
    results = _run_mock(res, validator=lambda _s, _z: "always fails")

    non_trivial = [r for r in results if r.source.strip()]
    assert non_trivial
    assert all(r.skipped for r in non_trivial)
    assert all(r.status == "fault" for r in non_trivial)
    # fallback_orig 的 translation 字段即原文——无残译文泄漏面
    assert all(r.translation == r.source for r in non_trivial)

    out = reconstruct(res, _translations(res, results))
    # v2：fallback 拼回的是 chunk.content（token surface）——run 内单 \n 与
    # 空白折叠成一个 space（eol_par "\n\n" 不受影响）。逐字节断言放宽为空白
    # 不敏感等价；identity 逐字节由 res.vtex / reconstruct(res) 承担。
    assert _ws_fold(out) == _ws_fold(_DOC % ("", _SYNTH_BODY))
    _assert_no_placeholder_leak(res, out)


def test_kind_mapping_covers_six() -> None:
    """Chunk.context → ChunkIn.kind 归一：产出值必在六 kind 词表内。"""
    res = parse_tex(_DOC % ("", _SYNTH_BODY))
    kinds = {c.kind for c in _inputs(res)}
    assert kinds <= set(all_kinds())
    assert "para" in kinds  # 段落路径走到了


# ---------------------------------------------------------------- corpus 用例（本机）


@needs_corpus
@pytest.mark.parametrize(("paper", "main"), _CORPUS_PAPERS)
def test_corpus_paper_full_chain(paper: str, main: str) -> None:
    """真实论文全链：identity → mock 翻译（L0 校验）→ splice 无泄漏。"""
    path = CORPUS / paper / main
    if not path.is_file():
        pytest.skip(f"{paper}/{main} 不在语料内")
    d = str(path.resolve().parent)  # 与 parse_file 内部 flatten 同参
    flat = flatten_inputs(path.read_text(encoding="utf-8", errors="replace"), d, d)

    res = parse_file(path)
    assert res.chunks, f"{paper} 未产出 chunk"
    # v2 identity 基准 = res.vtex（调用点 ident 保真 + 展开产物在后）——
    # 宏展开区与 v1 flat 逐字节本就有别，不拿 flat 当基准
    assert reconstruct(res) == res.vtex  # identity 逐字节
    structural = [w for w in validate_result(res) if w.kind in _STRUCTURAL_WARN_KINDS]
    assert structural == []

    _assert_mock_chain(res, flat)
