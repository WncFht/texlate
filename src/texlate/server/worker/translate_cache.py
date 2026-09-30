"""worker.translate_cache — 段缓存门面 + M1 防毒围栅栏 (worker.translate 域缝叶)。

``_NullCache`` 段缓存全哑面（无 key/mock/``no_seg_cache`` 形态持久面整层
短路）；``_TranslateCache`` mixin 的 ``_make_cache`` = cfg 指纹前缀
（model/prompt_ver/lang/base/术语层/key 指纹分桶）段缓存构造。
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from texlate.server.settings import cache_scope
from texlate.server.worker import seams
from texlate.textutil.osutil import translator_mode
from texlate.xlat.prompts import PROMPT_VERSION

from ._common import SegmentCache, opt_bool

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ._common import TaskCtx


class _NullCache(SegmentCache):
    """段缓存全哑面（M1 防毒围栅）：读只认本 run 自写、``drain`` 恒空不落库。

    适用面在 ``_make_cache`` 判定——段缓存键指纹不含凭证，无 key/mock
    形态写出的占位译文会跨凭证命中续毒（实测 fresh+ 真 key 重交同论文
    仍 67% 段命中 mock 缓存）；结构性短路比事后清洗可靠。

    ``_pending``/``_written`` 保留 run 内 dedup 语义（同文档重复段只译
    一次——``no_seg_cache`` 的重跑臂不为每条重复句白烧 token）；落盘
    面整层短路。继承只为 ``SegmentCache`` 注解位兼容（``_stage_translate``
    /``_flush_translate``/``_repend_puts``），``__init__`` 不走父类——无
    store/prefix 绑定，所有触库方法全部覆写。
    """

    def __init__(self) -> None:
        self.hits = 0
        self._prefix = ""
        self._pending: dict[str, str] = {}
        self._written: dict[str, str] = {}

    def prewarm(self, seg_keys: Iterable[str]) -> None:
        """无持久面可预载——读面只有本 run 自写内存层。"""

    def __contains__(self, seg_key: object) -> bool:
        """存在性探测只看 run 内层（持久面恒 miss——防毒核心语义）。"""
        return isinstance(seg_key, str) and (
            seg_key in self._pending or seg_key in self._written
        )

    def __getitem__(self, seg_key: str) -> str:
        """Run 内层命中记 hits（``_flush_translate`` 的 cached 计数口径不变）。"""
        hit = self._pending.get(seg_key)
        if hit is None:
            hit = self._written.get(seg_key)
        if hit is None:
            raise KeyError(seg_key)
        self.hits += 1
        return hit

    def __setitem__(self, seg_key: str, translation: str) -> None:
        self._pending[seg_key] = translation

    def __delitem__(self, seg_key: str) -> None:
        self._pending.pop(seg_key, None)
        self._written.pop(seg_key, None)

    def __len__(self) -> int:
        return len(self._pending)

    def drain(self) -> list[tuple[str, str, str, str]]:
        """吞掉待写：挪进 ``_written`` 保 run 内可读，返空不落 ``translation_cache``。"""
        self._written.update(self._pending)
        self._pending.clear()
        return []


class _TranslateCache:
    """段缓存构造 mixin（``_make_cache``）。"""

    def _make_cache(self, ctx: TaskCtx) -> SegmentCache:
        """段缓存门面（cfg 指纹前缀含 model/prompt_ver/lang[/key 指纹]）。

        M1 防毒围栅——以下任一成立返 ``_NullCache``（持久面读恒 miss、
        写不落库；run 内 dedup 语义保留）：

        - 无 ``api_key``：``file_cache_key`` 指纹不含凭证，无 key 形态
          写出的条目跨凭证命中续毒（实测 fresh+ 真 key 仍 67% 命中 mock
          残段）——缺 key 臂已被 ``_resolve_translator`` AuthError 拦死，
          本项兜 factory 注入/未来新入口的零 key 跑；
        - ``TEXLATE_TRANSLATOR=mock`` / 行 ``mock_run`` 标记：mock 产物
          永不进共享缓存；
        - ``no_seg_cache`` 内部选项：retry 闸对 mock_run 行注入——绕开
          mock 期写入的存量残毒（读面也断）。
        """
        opts = ctx.options()
        if (
            not ctx.secrets.api_key
            or translator_mode() == "mock"
            or opt_bool(opts, "no_seg_cache", lambda: False)
            or opt_bool(opts, "mock_run", lambda: False)
        ):
            return _NullCache()
        cfg_row = ctx.config()
        # user/local 层解析与 ``_make_glossary`` 同源（``warn=False``
        # 静默 confine——告警由 load 路 ``_glossary_path`` 单发不双发）
        gfile, local = self._glossary_layers(ctx, cfg_row, warn=False)
        local_sig = ""
        if local is not None:
            # local 层内容进指纹——同名文件换内容/有无该层都改变有效术语表；
            # 读失败与 user_sig 同态按无层（术语层是增强件不毁段）
            try:
                local_sig = hashlib.sha256(local.read_bytes()).hexdigest()[:12]
            except OSError:
                local_sig = ""
        # user 层同按内容进指纹（``_share_glossary_hash`` 同口径）：
        # 路径字符串当指纹会同名换内容串桶/异名同内容分桶；拒/缺席与
        # ``_make_glossary`` 同态回落 ``user_glossary_path`` 缺省层
        if gfile is None and seams.user_glossary_path().is_file():
            gfile = seams.user_glossary_path()
        user_sig = ""
        if gfile is not None:
            try:
                user_sig = hashlib.sha256(gfile.read_bytes()).hexdigest()[:12]
            except OSError:
                user_sig = ""
        # categories 进指纹：不同分类 → category 层术语不同 → 同源句的
        # 翻译函数不同，跨论文共享必须按分类分桶。文档占位符点名册逐文档
        # 漂移——进指纹会把缓存锁死成单文档桶，不进。
        cats = ",".join(self._arxiv_categories(ctx))
        # base_url 进指纹：同名 model 换后端（free 网关 vs BYOK 端点）产出
        # 不同——缺此项段缓存跨 provider 混桶中毒（spec file_cache_key
        # 公式含 base 同口径，spec-xlat #7）。
        base = str(ctx.secrets.base_url or cfg_row.get("base_url") or "")
        # auto_glossary 开关进指纹：开=auto 抽取层进 system prompt → 同源句
        # 翻译函数变，须分桶防关态译文污染开态桶（术语内容本身非确定，
        # 不进——temp 抽取逐跑微漂，进了会把桶锁死成单次跑）。读法与
        # ``_auto_glossary_fn`` 同走 opt_bool——指纹须与实际行为同源
        ag = "1" if opt_bool(ctx.options(), "auto_glossary", lambda: False) else "0"
        cfg = hashlib.sha256(
            f"{ctx.row['model']}|{PROMPT_VERSION}|{ctx.row['target_lang']}"
            f"|{base}|u:{user_sig}|l:{local_sig}|c:{cats}|ag:{ag}".encode()
        ).hexdigest()[:16]
        if cache_scope() == "per_key":
            # 与 cache_key_for 同一 oracle 防护：段级 translation_cache
            # 表同样可被跨租户探测命中，按 key 指纹分桶。
            key_sha = hashlib.sha256(ctx.secrets.api_key.encode()).hexdigest()[:16]
            cfg = f"k{key_sha}:{cfg}"
        return SegmentCache(
            self.store,
            prefix=cfg,
            model=str(ctx.row["model"]),
            target_lang=str(ctx.row["target_lang"]),
        )
