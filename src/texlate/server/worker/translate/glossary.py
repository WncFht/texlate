"""worker.translate.glossary — 术语表层解析/装配叶 (worker.translate 域缝叶)。

``_glossary_path`` ``glossary`` 选项 confine 仲裁、``_local_glossary``
论文级 ``glossary.local.yaml`` 探测、``_glossary_layers`` 生效层三面
单源（user/local）、``_arxiv_categories`` category 层键、
``_make_glossary`` 四层序装配 + ``ctx.memo`` 备忘、``_auto_glossary_fn``
``auto_glossary`` 自动术语抽取接线。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.pipecore import auto_glossary_fn
from texlate.repair import resolve_glossary_path
from texlate.server.worker._common import _glossary_option, opt_bool
from texlate.xlat.client import DEFAULT_MODEL
from texlate.xlat.glossary import (
    LOCAL_GLOSSARY_NAME,
    Glossary,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from texlate.server.worker._common import TaskCtx
    from texlate.xlat.client import ChatClient


class _TranslateGlossary:
    """术语表 mixin（路径 confine/层解析/装配/自动抽取接线）。"""

    def _glossary_path(
        self, ctx: TaskCtx, gpath: str, glossary_dir: str
    ) -> Path | None:
        """``glossary`` 选项 → confine 后的实际路径（None = 拒/无命中）。

        防任意文件读（审计 M2：glossary 内容进 LLM prompt 是外泄通道）：
        只收**相对路径**，逐个解析根——任务 ``base/`` 优先，然后
        ``glossary_dir``（settings 指定、运维侧受信目录，经 config_json
        透传）兜底；绝对路径与 ``..`` 形态即拒，resolve 后仍须
        is_relative_to 根（symlink 逃逸同挡）。
        """
        rel = Path(gpath)
        if rel.is_absolute() or ".." in rel.parts:
            self._warning(ctx, "glossary_rejected", f"glossary 路径越界被拒: {gpath!r}")
            return None
        cand = resolve_glossary_path(gpath, glossary_dir, ctx.base_dir)
        if cand is None:
            self._warning(
                ctx, "glossary_rejected", f"glossary 不在允许根内或不存在: {gpath!r}"
            )
        return cand

    def _local_glossary(self, ctx: TaskCtx) -> Path | None:
        """论文级 ``glossary.local.yaml`` 探测：任务 ``base/`` 根下同名文件。

        三级表（user > local > category seed）的 local 层——随源树走的
        项目内覆盖（upload_tex 压缩包/arxiv e-print 自带即生效）；docx/
        epub/pdf 路无 ``base/`` 自然缺省。返回 None = 无该层。
        """
        cand = ctx.base_dir / LOCAL_GLOSSARY_NAME
        return cand if cand.is_file() else None

    def _glossary_layers(
        self, ctx: TaskCtx, cfg: Mapping[str, Any], *, warn: bool
    ) -> tuple[Path | None, Path | None]:
        """生效术语层解析 → ``(confine 后 user 层|None, local 层|None)``——三面单源。

        ``glossary`` 选项取 ``cfg.glossary > options.glossary``（``_glossary_option``）；
        ``warn=True`` 经 ``_glossary_path`` confine——越界/无命中记
        ``glossary_rejected`` warning（``_make_glossary``/share 对账面）；
        ``warn=False`` 走静默 ``resolve_glossary_path``（``_make_cache``
        指纹面不告警——告警由 load 路单发不双发）。``user_glossary_path``
        缺省层回落不在内——各消费点按自身口径补（``Glossary.load`` 自带
        缺省、cache 指纹须显式覆盖、share 哈希走 ``fallback_user`` 参数）。
        """
        gpath = _glossary_option(ctx, cfg)
        local = self._local_glossary(ctx)
        if not gpath:
            return None, local
        gdir = str(cfg.get("glossary_dir") or "")
        user = (
            self._glossary_path(ctx, gpath, gdir)
            if warn
            else resolve_glossary_path(gpath, gdir, ctx.base_dir)
        )
        return user, local

    def _arxiv_categories(self, ctx: TaskCtx) -> list[str]:
        """``options.arxiv_categories``（``_fetch_arxiv`` 持久化）→ category 层键。"""
        raw = ctx.options().get("arxiv_categories")
        if not isinstance(raw, list):
            return []
        return [c for c in raw if isinstance(c, str)]

    def _make_glossary(self, ctx: TaskCtx) -> Glossary | None:
        """术语表：config.glossary 路径优先（confine 后），缺省内置默认层。

        四层序：user > local(``base/glossary.local.yaml``) > categories
        （arXiv 声明分类 → ``terms/*.csv`` 经 index.yaml）> default。
        占位符点名册不走本表——``pipeline._materialize`` 经
        ``render_placeholder_manifest`` 单行压 ``<Glossary>`` 块末行。

        每任务 2~4 调（主链/env_judge/logfix/pdf 臂同形构造）——``ctx.memo``
        按 ``"glossary"`` 备忘复用。
        """
        mkey = "glossary"
        if mkey in ctx.memo:
            return ctx.memo[mkey]
        cfg = ctx.config()
        cats = self._arxiv_categories(ctx)
        try:
            path, local = self._glossary_layers(ctx, cfg, warn=True)
            if path is None:
                g = Glossary.load(local_path=local, categories=cats)
            else:
                g = Glossary.load(
                    user_path=path,
                    local_path=local,
                    categories=cats,
                )
        except Exception as e:  # noqa: BLE001 -- 术语表是增强件：load 面 TypeError/yaml.YAMLError 等非 OSError/ValueError 同降级无表
            self._log(ctx, f"glossary load failed: {e}")
            g = None
        ctx.memo[mkey] = g
        return g

    def _auto_glossary_fn(
        self, ctx: TaskCtx, clients: list[ChatClient]
    ) -> Callable[[list[str]], Awaitable[dict[str, str]]] | None:
        """``auto_glossary`` option 开时接 ``autogloss.extract_terms``。

        抽取臂与翻译同模（``ctx.secrets.model``——BYOK 端点名字网关私有，
        硬编公网模型名会在非公网端点上 404）。ctx.memo 备忘防 resume
        重抽——同一 task 的二次 ``pipe.run`` 复用首轮结果。
        """
        # ``auto_glossary`` 与 ``_make_cache`` 的 ag 指纹成分同读法——
        # opt_bool 口径（"0"/"false" 字符串系判假），两站须同改
        if not opt_bool(ctx.options(), "auto_glossary", lambda: False) or not clients:
            return None
        return auto_glossary_fn(
            clients[0],
            str(ctx.secrets.model or DEFAULT_MODEL),
            ctx.memo,
            "autogloss_terms",
        )
