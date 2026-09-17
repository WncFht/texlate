"""``PipelineWorker`` 脊椎：构造注入面 + ``run`` 编排 + tex/share 两链入口。"""

from __future__ import annotations

import asyncio
import logging
import threading
from http import HTTPStatus
from typing import TYPE_CHECKING

from texlate.arxiv.unpack import UnpackError
from texlate.compile.inject import InjectRejectError
from texlate.server.store import (
    ACTIVE_STATUSES,
    Store,
)
from texlate.xlat.client import (
    AuthError,
    ChatError,
    RetryableHTTPError,
)

from ._common import (
    COMPILE_TIMEOUT,
    TaskCtx,
    _RouteRejectError,
    _ShareRejectError,
    _StageError,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from texlate.arxiv.cache import SourceCache
    from texlate.arxiv.fetch import Fetcher
    from texlate.compile.engine import Engine
    from texlate.compile.fixloop.ctan import TlpdbIndex
    from texlate.server.events import EventBus
    from texlate.xlat.pipeline import Translator


log = logging.getLogger(__name__)


class _Core:
    """构造注入面 + ``run`` 编排 + ``_run_tex``/``_run_share`` 两链入口。"""

    def __init__(  # noqa: PLR0913 -- 依赖注入面集中声明
        self,
        store: Store,
        bus: EventBus,
        data_dir: Path,
        *,
        translator_factory: Callable[[TaskCtx], Translator] | None = None,
        fetcher: Fetcher | None = None,
        source_cache: SourceCache | None = None,
        engine_factory: Callable[[str], Engine] | None = None,
        babeldoc: str | None = None,
        compile_timeout: float = COMPILE_TIMEOUT,
        deps_index: TlpdbIndex | None = None,
    ) -> None:
        """data_dir = ``TEXLATE_DATA_DIR`` 根；任务工作区 ``tasks/{id}/``。"""
        self.store = store
        self.bus = bus
        self.data_dir = data_dir
        self._translator_factory = translator_factory
        self._fetcher = fetcher
        self._src_cache = source_cache
        self._engine_factory = engine_factory
        self._babeldoc = babeldoc
        #: probe 的 tlpdb 索引注入面：None = `target_probe` 内部惰性 ensure
        self._deps_index = deps_index
        self._compile_timeout = compile_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_tid = 0
        #: ``mock_translator`` 告警按 task 去重（translate/env_judge/L2/doc 多处
        #: 调 ``_make_translator``，同一任务只留一条痕）
        self._mock_warned: set[str] = set()

    # ------------------------------------------------------------ 主入口

    async def run(self, ctx: TaskCtx) -> None:  # noqa: C901, PLR0912 -- 异常阶梯平铺即 §2.2 错误码映射表
        """按 kind 跑全链；异常按错误码映射落 fault/cancelled。"""
        # resume：内存字段从行快照重建（main_tex/engine_resolved 持久化值）
        self._loop = asyncio.get_running_loop()
        self._loop_tid = threading.get_ident()
        ctx.main_rel = str(ctx.row.get("main_tex") or "")
        ctx.engine_name = str(ctx.options().get("engine_resolved") or "tectonic")
        try:
            self._check_cancelled(ctx)
            if ctx.row["kind"] == "upload_pdf":
                await self._run_pdf(ctx)
            elif ctx.row["kind"] in ("docx", "epub"):
                await self._run_doc(ctx)
            elif ctx.row["kind"] == "share":
                await self._run_share(ctx)
            elif ctx.row["kind"] == "arxiv_html":
                await self._run_html(ctx)
            else:
                await self._run_tex(ctx)
        except asyncio.CancelledError:
            # 在飞 to_thread 段即刻开始收敛（cancel_running/stop 已置过幂等）
            ctx.cancel_flag.set()
            # cancel 端点已置 cancelled；只在没有终态时补 interrupted
            if self._current_status(ctx) in ACTIVE_STATUSES:
                self.store.transition(
                    ctx.task_id,
                    "interrupted",
                    force=True,
                    message="worker cancelled",
                )
                # 终态必须配 done 事件——SSE reader/等待者靠它收尾
                self.bus.publish(
                    ctx.task_id,
                    "done",
                    {
                        "status": "interrupted",
                        "artifacts": self._artifact_urls(ctx),
                        "stats": self._stats(ctx),
                    },
                )
            raise
        except _StageError as e:
            self._fail(
                ctx,
                e.code,
                str(e),
                retryable=e.retryable,
                stage=ctx.row["stage"],
            )
        except AuthError as e:
            self._fail(
                ctx,
                "provider_auth",
                str(e),
                retryable=False,
                stage=ctx.row["stage"],
            )
        except RetryableHTTPError as e:
            code = (
                "provider_rate"
                if e.status == HTTPStatus.TOO_MANY_REQUESTS
                else "provider_timeout"
            )
            self._fail(ctx, code, str(e), retryable=True, stage=ctx.row["stage"])
        except ChatError as e:
            self._fail(
                ctx,
                "provider_error",
                str(e),
                retryable=e.retryable,
                stage=ctx.row["stage"],
            )
        except _RouteRejectError as e:
            self._reject(ctx, "route_reject", f"route reject: {e}", reject_at="route")
        except _ShareRejectError as e:
            self._reject(
                ctx,
                "share_verify",
                f"share verify: {e}",
                reject_at="share_verify",
            )
        except InjectRejectError as e:
            self._reject(
                ctx,
                "inject_reject",
                f"inject reject: {e.reason}",
                reject_at="inject",
            )
        except (UnpackError, ValueError, OSError) as e:
            self._fail(ctx, "parse", str(e), retryable=False, stage=ctx.row["stage"])
        except Exception as e:
            log.exception("task %s crashed", ctx.task_id)
            self._fail(
                ctx,
                "internal",
                f"{type(e).__name__}: {e}",
                retryable=True,
                stage=ctx.row["stage"],
            )
        finally:
            # 有界等在飞 to_thread 段排空——retry/下一任务复跑时孤儿
            # 线程已死，目录写不交错（原子段残尾见 _drain_threads）
            await self._drain_threads(ctx)

    # ------------------------------------------------------------ tex 管线

    async def _run_tex(self, ctx: TaskCtx) -> None:
        """arxiv/upload_tex 共链：fetch → parse → translate|share_apply → compile。

        parse 后先查共享 index（``_share_lookup``）——命中即换
        ``_stage_share_apply`` 对账通道（零 token）；对账拒绝不替用户
        拒包，摘标记回退自译——隐式命中是优化不是承诺。
        """
        ctx.root.mkdir(parents=True, exist_ok=True)
        await self._stage_fetch(ctx)
        if ctx.reuse_hit is not None:
            return  # post-resolve dedup 命中——产物已物化 + 终态已写
        await self._stage_parse(ctx)
        if await self._to_thread(ctx, self._share_lookup):
            try:
                await self._stage_share_apply(ctx)
            except _ShareRejectError as e:
                self._warning(ctx, "share_apply", f"共享包对账失败，回退自译: {e}")
                await self._to_thread(ctx, self._share_unmark)
            else:
                await self._stage_compile(ctx, share=True)
                return
        await self._stage_translate(ctx)
        await self._stage_compile(ctx)

    # ------------------------------------------------------------ share 导入

    async def _run_share(self, ctx: TaskCtx) -> None:
        """kind=share：fetch → parse → 包内 dual.json 对账回灌 → compile。

        ``shared-cache.md §5`` 消费侧——与 ``_run_tex`` 唯一差异是
        translating 段换成 ``_stage_share_apply``：译文来自共享包而非
        LLM，但 fetch/parse/splice/inject/compile/judge/dual 全链本地
        重跑。包内 ``zh-src.zip``/``zh.pdf`` 是贡献者侧证据，不解、不进
        产物面——读者看到的每个字节都由本源 + 本地管线再生。
        """
        ctx.root.mkdir(parents=True, exist_ok=True)
        await self._stage_fetch(ctx)
        await self._stage_parse(ctx)
        await self._stage_share_apply(ctx)
        await self._stage_compile(ctx, share=True)
