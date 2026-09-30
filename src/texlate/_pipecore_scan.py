"""``texlate._pipecore_scan`` — front_matter 域 + 树扫描/术语注入叶（``pipecore`` 拆分叶）。

preamble 前置发射键面（``FRONT_MATTER_NAMES``/``ENV_FRONT_MATTER``
同名回引）与缺省/意图/实跑三解析（``default_front_matter``/
``front_matter_of``/``ran_front_matter``）；``scan_tree`` 四级分流
壳（枚举 ``.tex`` → fault/support 分桶 → ``(scans, chunks)`` 折叠）与
``auto_glossary_fn`` LLM 术语抽取装配厂。

门面回引名单见 ``texlate.pipecore._LEAF_EXPORTS``。
monkeypatch 锚点：setattr patch 须指本叶，指门面无效。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from texlate.compile.inject import find_main_tex
from texlate.latex.api import scan_tex_tree
from texlate.textutil import env_str
from texlate.textutil.osutil import ENV_FRONT_MATTER
from texlate.xlat.pipeline import chunk_to_in

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from pathlib import Path

    from texlate.chunk import ChunkIn
    from texlate.latex.model import ScanResult
    from texlate.xlat.client import ChatClient

#: preamble 前置发射名全集——`options.front_matter`/`TEXLATE_FRONT_MATTER`
#: 的合法键面。
FRONT_MATTER_NAMES = frozenset({"abstract", "title", "author"})

#: ``options.front_matter`` 各键缺省（摘要+标题开、作者关——既定产品默认）。
_FRONT_MATTER_DEFAULT: dict[str, bool] = {
    "abstract": True,
    "title": True,
    "author": False,
}


def default_front_matter() -> frozenset[str]:
    """Env 缺省集：``TEXLATE_FRONT_MATTER`` 逗号清单，未设取 ``_FRONT_MATTER_DEFAULT`` 的开键。"""
    raw = env_str(ENV_FRONT_MATTER)
    if not raw:
        return frozenset(k for k, v in _FRONT_MATTER_DEFAULT.items() if v)
    return frozenset(x.strip() for x in raw.split(",")) & FRONT_MATTER_NAMES


def front_matter_of(options: dict[str, Any]) -> frozenset[str]:
    """``options.front_matter`` dict → frozenset；缺键按 ``_FRONT_MATTER_DEFAULT``。"""
    fm = options.get("front_matter")
    if not isinstance(fm, dict):
        return default_front_matter()
    return frozenset(
        k for k in FRONT_MATTER_NAMES if bool(fm.get(k, _FRONT_MATTER_DEFAULT[k]))
    )


def ran_front_matter(options: Mapping[str, Any]) -> frozenset[str]:
    """任务**实跑**前置集还原：显式 dict → ``front_matter_of``；缺席 → ``frozenset()``。

    与 ``front_matter_of`` 的分工：后者是**提交意图**解析（缺键落产品
    缺省，enqueue/扫描用）；本函数是**事后归因**解析——parse 段把解析
    集显式写回 ``options.front_matter``，故 done/partial 行的缺席即
    pre-feature 产物（前置全盖过的历史形态，实跑 ∅）。share manifest
    与 cache_key 重算据本函数还原实跑集，不给历史行错标缺省。
    """
    if not isinstance(options.get("front_matter"), dict):
        return frozenset()
    return front_matter_of(dict(options))


def scan_tree(
    root: Path,
    *,
    front_matter: frozenset[str] = frozenset(),
    main: Path | None = None,
) -> tuple[list[tuple[Path, ScanResult]], list[ChunkIn], list[str], list[str]]:
    """枚举树内 ``.tex`` → 四级分流 → 解析 + chunk 收集。

    扫描段单源 ``latex.api.scan_tex_tree``（文件名闸 ``.rtx.tex`` 运行时
    转储静默跳过、``.code.tex`` tikzlibrary 机制件记 support → 解析崩
    分两叉（解析闸内判定）：``OSError(EINVAL)``（tar 伪装 ``.tex``，tar
    闸在 ``parse_file`` 内）静默跳过——不进任何名单、逐字节保留；其余
    解析崩记 ``fault_files``（单文件崩不拖垮整树，原文保留）→ 无散文
    记 ``support_files``——pstricks/epsf/宏件/gnuplot 转储送译即腐蚀，
    按原文保留；与 fault 分流：有意跳过而非失败）。本壳只把 ``parsed``
    桶折成 ``(scans, chunks)``——chunk_id ``{idx}:{c.id}`` 方案归本臂。
    ``front_matter`` = preamble 前置发射白名单（透传 ``scan_tex_tree``）。
    ``main`` 缺省 → ``find_main_tex(root)`` 自检出——闭包裁剪与 worker
    ``_parse_all`` 同闸（检出失败/无命中即不裁，fail-open 同侧）。
    """
    if main is None:
        main = find_main_tex(root)
    tree = scan_tex_tree(root, main=main, front_matter=front_matter)
    scans: list[tuple[Path, ScanResult]] = []
    chunks: list[ChunkIn] = []
    for f, _rel, res in tree.parsed:
        idx = len(scans)
        scans.append((f, res))
        chunks.extend(
            chunk_to_in(c, chunk_id=f"{idx}:{c.id}", ph_map=res.ph_map)
            for c in res.chunks
        )
    return scans, chunks, [rel for rel, _exc in tree.fault], tree.support


def auto_glossary_fn(
    client: ChatClient | None,
    model: str,
    memo: dict[str, Any] | None = None,
    memo_key: str = "terms",
) -> Callable[[list[str]], Awaitable[dict[str, str]]] | None:
    """``PipelineConfig.auto_glossary_fn`` 装配工厂（e2e/worker 两臂单源）。

    ``client=None`` → ``None``（mock/无 key 路径不打网关）。``memo`` 给
    跨 ``pipe.run`` 复用的备忘袋——worker 侧 ``ctx.memo`` 防 resume 重抽；
    缺省 = 本 fn 私有袋只防二次调用重抽。``memo_key`` 备忘键名——调用方
    共享袋时自取名防撞键。
    """
    if client is None:
        return None
    store: dict[str, Any] = {} if memo is None else memo

    async def _fn(texts: list[str]) -> dict[str, str]:
        from texlate.xlat.autogloss import (  # noqa: PLC0415 -- 可选件惰载
            extract_terms,
        )

        if memo_key not in store:
            store[memo_key] = await extract_terms(texts, client, model=model)
        return store[memo_key]

    return _fn
