"""soak ingest 段叶——catalog 状态机分类 → src_path 物化。"""

from __future__ import annotations

from kernel import lake

from specs import _bootstrap

_bootstrap.ensure()

from specs._shared import _gate
from specs.soak.items import _HYDRATABLE, _catalog
from texlate.compile.inject import find_main_tex

#: fmt 死路词表（本路径永不可解——reject 的 manifest_dead_end 系）。
_BAD_FMTS = frozenset({"stub", "pdf", "error"})

# ---------------------------------------------------------------- stage: ingest


def _ingest(ctx) -> dict:
    """catalog 状态机分类 → src_path 物化；四键 metrics 同旧口径。

    cat=code 旧约——sig 要能分流 stub_format/eprint_fetch_unwired 等
    （旧世界 errors[0].cat 就是 code 字符串本身）。cat=ingest 只留给
    no_extracted torn 格。
    """
    cell = ctx.cell
    fmt = cell.get("format")
    ch = cell.get("channel")
    item = cell.get("item")
    member = cell.get("member")
    metrics = {
        "n_files": 0,
        "main_tex_guess": None,
        "source": "ia" if item else None,
        "sha256_ok": None,
    }

    st = _catalog().state(ctx.idc)
    complete = lake.is_complete(ctx.idc)
    if not complete:
        # fmt 死路只在缺字节时判（旧式：extracted 在场者不看 manifest
        # format 标签）；catalog state 再真也救不回 stub/pdf/error 伪条目。
        if fmt in _BAD_FMTS:
            c = f"{fmt}_format"
            return _gate("reject", c, c, member, metrics)
        if st == "failed":
            # manifest_dead_end 系：catalog 判死的格 reject。
            return _gate("reject", "catalog_failed", "catalog_failed", member, metrics)
        if st == "empty":
            # 空载荷格——src_path() 会把它投影成伪 ok 空树，先截。
            return _gate("reject", "empty_payload", "empty_payload", member, metrics)

    src = ctx.src_path()
    if src is not None:
        main = find_main_tex(src)
        metrics.update(
            {
                "n_files": sum(1 for p in src.rglob("*") if p.is_file()),
                "main_tex_guess": (main.relative_to(src).as_posix() if main else None),
                "source": "lake",
            }
        )
        return {"status": "ok", "metrics": metrics}
    # src_path None 且 catalog 声称有货 = torn 湖格（raw/extracted 双缺，
    # fetch_fn 未接）——error；未登记/不可水化态走 skip 分类树。
    if complete or st in _HYDRATABLE:
        return _gate("error", "no_extracted", "ingest", ctx.idc, metrics)
    if not item:
        c = "eprint_fetch_unwired" if ch == "arxiv_eprint" else "no_item"
        return _gate("skip", c, c, member, metrics)
    return _gate(
        "skip", "ia_fetch_unwired", "ia_fetch_unwired", f"item={item}", metrics
    )
