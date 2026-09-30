r"""specs._fixture_matrix.base — 底材名单 + 测量包叶 (_fixture_matrix 拆分叶).

FIXTURES/FIXTURE_FILES/LEAK_PATTERNS/FixtureScan/run_fixture + 逐条断言
共用小件 (chunks_blob/fake_translation/scan_chunks/classify_recon/
_meta_row/_all_re/_ph_roundtrip)。本叶的 ``LEAK_PATTERNS`` 与
``specs/_leak.py`` 是**有意不同的两表**——永不合并。
"""

from __future__ import annotations

import difflib
import re
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from specs import _bootstrap

_bootstrap.ensure()

from texlate.latex import parse_file, reconstruct
from texlate.latex.placeholder import CHUNK_RX, PH_RX

if TYPE_CHECKING:
    from types import FrameType

    from texlate.latex.model import Chunk, ScanResult

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"

#: (相对 ``FIXTURES`` 的 posix 名，路径)——名随路径派生，改名不会与
#: ``_FIXTURE_TOPDIR``/``_PARSED`` 键失同步。
FIXTURE_FILES = [
    (p.relative_to(FIXTURES).as_posix(), p)
    for p in (
        FIXTURES / "tricky.tex",
        FIXTURES / "tricky-209.tex",
        FIXTURES / "tricky-multi" / "main.tex",
        FIXTURES / "xlat-traps.tex",
        FIXTURES / "tricky-w.tex",
        FIXTURES / "tricky-w73" / "main" / "main.tex",
        FIXTURES / "tricky-wenc.tex",
        FIXTURES / "tricky-dollar.tex",
        FIXTURES / "tricky-mask.tex",
    )
]

# 泄漏扫描口径（原型同表）：可译 chunk 内不得出现这些构造
LEAK_PATTERNS = {
    "dollar": re.compile(r"\$"),
    "cite_family": re.compile(r"\\cite[a-zA-Z]*"),
    # 前缀位覆盖 eq/auto/name/sub/labelc + 单字母族（c/C/v/V/f/F），中段可选
    # ``page``、尾段可选 ``range``——\cref \Cref \crefrange \vref \vpageref
    # \fref \labelcref \cpageref 等 cleveref/varioref/fancyref 变体同闸；
    # ``\href`` 等不以 ref 收尾的 cs 不中（xlat-traps 的 \href 文本照样可译）。
    "ref_family": re.compile(
        r"\\(?:eq|auto|name|sub|labelc|[cCvVfF])?(?:page)?ref(?:range)?(?![a-zA-Z])"
    ),
    "begin_env": re.compile(r"\\begin\{"),
    "conditional": re.compile(r"\\(?:if[a-zA-Z]+|else|fi)(?![a-zA-Z])"),
    "input_include": re.compile(r"\\(?:input|include)\{"),
}


class ParseTimeoutError(Exception):
    """parse 超时（原型同款 30s SIGALRM 护栏——挂死型回归也按失败算）。"""


def _alarm(_signum: int, _frame: FrameType | None) -> None:
    raise ParseTimeoutError


# ---------------------------------------------------------------- 测量包


def chunks_blob(res: ScanResult) -> str:
    """全部可译 chunk 的 content 拼一块——泄漏断言的扫描面。"""
    return "\n".join(c.content for c in res.chunks)


def fake_translation(chunk: Chunk, idx: int) -> str:
    """假译文：CJK 前缀 + 原样保留的内嵌占位符（契约压力形）。"""
    keep = PH_RX.findall(chunk.content)
    return f"【假译文{idx}】" + "".join(keep)


def scan_chunks(res: ScanResult) -> dict:
    """泄漏扫描（原型同口径）：可译 chunk 内命中受保护构造的计数。"""
    hits = dict.fromkeys(LEAK_PATTERNS, 0)
    leaked = 0
    examples = []
    for c in res.chunks:
        found = [name for name, rx in LEAK_PATTERNS.items() if rx.search(c.content)]
        if found:
            leaked += 1
            for f in found:
                hits[f] += 1
            examples.append(
                {"context": c.context, "leaks": found, "snippet": c.content[:120]}
            )
    return {
        "n_translatable_chunks": len(res.chunks),
        "n_leaked": leaked,
        "hits": hits,
        "examples": examples[:5],
    }


def classify_recon(orig: str, recon: str) -> tuple[str, float, int]:
    """重建分级：identical / normalized / diverged（原型同口径）。"""
    if orig == recon:
        return "identical", 1.0, -1

    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    if norm(orig) == norm(recon):
        return "normalized", 1.0, -1
    i = 0
    n = min(len(orig), len(recon))
    while i < n and orig[i] == recon[i]:
        i += 1
    ratio = difflib.SequenceMatcher(None, orig, recon).quick_ratio()
    return "diverged", round(ratio, 4), i


def _meta_row(res: ScanResult, recon_fake: str) -> dict[str, str]:
    """``_meta`` info 行：chunk/ph 计数 + 假译文重建的占位符残留计数。"""
    return {
        "status": "info",
        "detail": f"chunks={len(res.chunks)} ph={len(res.ph_map)} "
        f"residue_chunk={len(CHUNK_RX.findall(recon_fake))} "
        f"residue_prot={len(PH_RX.findall(recon_fake))}",
    }


def _all_re(chunks: str, rxs: tuple[str, ...], note: str) -> dict[str, str]:
    """``rxs`` 全部命中 ``chunks`` → pass 行，缺一即 fail。"""
    missing = [rx for rx in rxs if not re.search(rx, chunks)]
    return {
        "status": "fail" if missing else "pass",
        "detail": f"missing {missing} in chunks" if missing else note,
    }


def _ph_roundtrip(
    chunks: str, recon: str, rx: str, needle: str, note: str
) -> dict[str, str]:
    """``rx`` 命中 ``chunks`` 且 ``needle`` 存活于 identity ``recon`` → pass 行。"""
    ok = re.search(rx, chunks) and needle in recon
    return {
        "status": "pass" if ok else "fail",
        "detail": note if ok else f"rx={rx!r} in chunks / {needle!r} in recon: false",
    }


@dataclass
class FixtureScan:
    """单个 fixture 的解析 + 双重重建测量包（断言函数的输入）。"""

    name: str
    ok: bool
    wall_ms: float
    res: ScanResult | None = None
    recon: str = (
        ""  # identity 重建（对比基准是 res.vtex——见 test_identity_reconstruct）
    )
    recon_fake: str = ""  # 假译文重建
    error: str = ""
    residue_chunk_ph: int = -1
    residue_protect_ph: int = -1


def run_fixture(
    name: str, path: Path, timeout_s: int = 30, top_dir: Path | None = None
) -> FixtureScan:
    """parse + identity/假译文重建一次（原型 ``parse_one``+``rebuild_metrics`` 合体）。"""
    t0 = time.perf_counter()
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(timeout_s)
    try:
        res = parse_file(path, flatten=True, top_dir=top_dir)
    except ParseTimeoutError:
        return FixtureScan(
            name=name, ok=False, wall_ms=timeout_s * 1000.0, error="Timeout(>30s)"
        )
    except Exception as e:  # 断言跑分语义：解析失败记为 fail 行而非抛出
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return FixtureScan(
            name=name, ok=False, wall_ms=ms, error=f"{type(e).__name__}: {e}"
        )
    finally:
        signal.alarm(0)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    recon = reconstruct(res)
    translated = {c.id: fake_translation(c, i) for i, c in enumerate(res.chunks)}
    recon_fake = reconstruct(res, translated)
    return FixtureScan(
        name=name,
        ok=True,
        wall_ms=ms,
        res=res,
        recon=recon,
        recon_fake=recon_fake,
        residue_chunk_ph=len(CHUNK_RX.findall(recon_fake)),
        residue_protect_ph=len(PH_RX.findall(recon_fake)),
    )
