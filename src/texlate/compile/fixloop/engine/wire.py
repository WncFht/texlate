"""engine.wire — 引擎侧降级原语接线 + 装配头 (C5 拆叶)。

``filemap.overrides`` 手工映射实例遮蔽 (``_wire_filemap_overrides``),
texmfhome 隔离/tectonic ``ctan_fetch`` 注入 (``_wire_engine``), 与两
入口共用的 Ruleset 装载 + LoopCtx 装配头 ``_setup_ctx``。
``ctan``/ruleset 五名 (``RULES_PATH``/``Rule``/``Ruleset``/
``RulesetError``/``load_ruleset``) 经本叶回引 (``engine.X`` 兼容面)。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.compile import ctan
from texlate.compile.fixloop.engine.ctx import LoopCtx
from texlate.compile.fixloop.ruleset import (
    RULES_PATH,
    Rule,
    Ruleset,
    RulesetError,
    load_ruleset,
)

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine.proto import Engine, LlmHook, RunFn

__all__ = [
    "RULES_PATH",
    "Rule",
    "Ruleset",
    "RulesetError",
    "_setup_ctx",
    "_wire_engine",
    "_wire_filemap_overrides",
    "ctan",
    "load_ruleset",
]


def _wire_filemap_overrides(
    eng: Engine, overrides: dict[str, Any], ctx: LoopCtx
) -> None:
    """``eng.filemap`` 实例遮蔽：basename 先过手工映射，未中走原查询。

    xelatex 通路 ``install_file``/``_filemap_candidates`` 共用 ``self.filemap``
    —— 单点遮蔽即全通路生效 (bench 现场 ``eng.filemap = idx.query`` 的既有
    遮蔽也照包，次序 = overrides → 既有查询; worker 的 ``_RecEngine`` 与
    bench 的 ``_NoSandbox`` 均 ``__setattr__`` 透传，遮蔽落在真引擎实例上)。
    显式 null = 已知噪声 → 空表短路，不再落 tlmgr/索引往返。
    """
    orig = getattr(eng, "filemap", None)
    if not callable(orig) or getattr(orig, "overrides_wrapped", False):
        return

    def filemap(fname: str) -> list[str]:
        if fname in overrides:
            v = overrides[fname]
            return [v] if isinstance(v, str) else []
        return list(orig(fname))

    filemap.overrides_wrapped = True  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]  # 幂等：重入不叠包
    try:
        eng.filemap = filemap  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]  # 实例遮蔽协议方法
    except Exception as e:  # noqa: BLE001  # 遮蔽失败不阻塞：退化为原生 filemap
        ctx.ledger.advisories.append(
            f"filemap overrides wire failed: {type(e).__name__}: {e}"
        )
    else:
        ctx.ledger.events.append("wire filemap overrides")


def _wire_engine(eng: Engine, rs: Ruleset, wdir: Path, ctx: LoopCtx) -> None:
    """引擎侧降级原语注入 (docs/spec/compile.md)。

    ``filemap.overrides`` 手工映射对全引擎生效 (实例遮蔽 ``eng.filemap``);
    tectonic 追加：``install_file`` 内部走 ``self.ctan_fetch`` callable ——
    未注入时这里装上 CtanFetcher (惰性 tlpdb 索引 + rules/
    ``filemap.version_guard`` 的 bundle epoch 接线)。
    """
    _wire_filemap_overrides(eng, rs.filemap_cfg.get("overrides") or {}, ctx)
    # texmfhome 缺省时 ``tlmgr --usermode install`` 落 kpathsea 默认 ~/texmf
    # ——全局可见树，跨跑污染 base 对照线（modec-rerun 实证：youngtab.sty 进
    # ~/texmf 后 1306.1931 base 臂 fail→clean 假象）。装包隔离到任务树内。
    if getattr(eng, "texmfhome", "unset") is None:
        eng.texmfhome = wdir / "_texmf"  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        ctx.ledger.events.append("wire texmfhome -> workdir _texmf")
    if ctx.deps.engine_name != "tectonic":
        return
    if getattr(eng, "ctan_fetch", None) is not None or not hasattr(eng, "ctan_fetch"):
        return
    vg = rs.filemap_cfg.get("version_guard") or {}
    try:
        eng.ctan_fetch = ctan.CtanFetcher(  # ty: ignore[invalid-assignment]  # 协议外成员动态注入 (tectonic 专属 callable)
            wdir,
            overrides=rs.filemap_cfg.get("overrides") or {},
            epoch=(str(vg["texlive_format_epoch"]) if vg.get("enabled") else None),
        )
        ctx.ledger.events.append("wire ctan_fetch (lazy tlpdb index)")
    except Exception as e:  # noqa: BLE001  # 注入失败不阻塞：install_* 走 advisory
        ctx.ledger.advisories.append(f"ctan_fetch wire failed: {type(e).__name__}: {e}")


def _setup_ctx(  # noqa: PLR0913  # 装配头参数列即两入口注入面交集
    proj: Path | str,
    eng: Engine,
    *,
    ruleset: Ruleset | None = None,
    engine_name: str | None = None,
    runner: RunFn | None = None,
    llm_hook: LlmHook | None = None,
) -> tuple[Ruleset, str, Path, LoopCtx]:
    """Ruleset 装载 + 引擎名解析 + wdir + LoopCtx + skipped 建议账——共用装配头。

    只收两入口同构段; ``_wire_engine`` 接线位与 main_rel 推导口径各异
    (precheck_pass 宽松 ``find_main_tex`` 直落 ``ctx.io.main_rel``;
    fixloop 严格树内校验 + ``main_fallback`` 留痕 + no_main 早退),
    各留调用点不入本缝。
    """
    rs = ruleset or Ruleset.load(tolerant=True)
    engine_name = engine_name or getattr(
        eng, "name", rs.meta.get("engine_default", "xelatex")
    )
    wdir = Path(proj)
    ctx = LoopCtx(wdir=wdir, engine_name=engine_name, runner=runner, llm_hook=llm_hook)
    ctx.ledger.advisories.extend(rs.skipped_rules)
    return rs, engine_name, wdir, ctx
