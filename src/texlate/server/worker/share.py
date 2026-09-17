"""``PipelineWorker._Share`` + share 模块件——共享包对账/摘标/打包发布。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
from collections import defaultdict, deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.arxiv.fetch import normalize_arxiv_id
from texlate.server.settings import share_dir
from texlate.share import (
    ShareError,
    index_append,
    pack_share,
    share_key,
    unpack_share,
)
from texlate.textutil import CJK_RX
from texlate.validate.l0 import validate_pair
from texlate.xlat.glossary import (
    LOCAL_GLOSSARY_NAME,
)
from texlate.xlat.prompts import PROMPT_VERSION

from ._common import (
    PIPELINE_VERSION,
    PROGRESS,
    TaskCtx,
    _ShareRejectError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from texlate.share import ShareManifest

import texlate.server.worker as _w


def _share_pool(raw: list[object]) -> dict[tuple[str, str], deque[str]]:
    """包内 dual chunks → ``(src_file, en)`` → zh 队列（重复段按序消费）。

    只收真译文载荷：zh 非 str/空白串、或 ``zh == en`` 且不含 CJK 的条目
    不进池——源任务 ``fallback_orig``/``failed`` 行的 dual.json zh 位装
    的是原文回写/空串，对无占位符 src 这两形态都能过 ``validate_pair``
    （CJK 占比仅 WARN），收进池会让英文原文/空译文以 ``ok`` 落库续传。
    ``zh == en`` 含 CJK 是合法恒等译文（原文即中文段），照常放行。
    """
    pool: dict[tuple[str, str], deque[str]] = defaultdict(deque)
    for c in raw:
        if not isinstance(c, dict):
            continue
        src_file, en, zh = c.get("src_file"), c.get("en"), c.get("zh")
        if not (isinstance(src_file, str) and isinstance(en, str)):
            continue
        if not isinstance(zh, str) or not zh.strip():
            continue
        if zh == en and not CJK_RX.search(zh):
            continue
        pool[(src_file, en)].append(zh)
    return pool


def _share_row(
    r: dict[str, Any], pool: dict[tuple[str, str], deque[str]]
) -> tuple[str, dict[str, Any] | None]:
    """单 chunk 对账 → ``(outcome, update|None)``。

    outcome ∈ ``ok``/``dropped``/``missed``/``resumed_ok``/``resumed``——
    非 pending 行（resume 幂等）只归类不重判，``resumed_ok`` 计入 matched
    防上轮已落库命中在重跑时误判零命中。
    """
    if r["status"] != "pending":
        return ("resumed_ok" if r["status"] == "ok" else "resumed", None)
    q = pool.get((str(r["src_file"]), str(r["src_text"])))
    if not q:
        return "missed", {
            "status": "fallback_orig",
            "translation": str(r["src_text"]),
            "error_code": "share_miss",
        }
    zh = q.popleft()
    rep = validate_pair(str(r["src_text"]), zh)
    if rep.ok:
        return "ok", {"status": "ok", "translation": zh}
    return "dropped", {
        "status": "fallback_orig",
        "translation": str(r["src_text"]),
        "error_code": "validate",
        "warnings": json.dumps(
            [f"share_validate: {rep.feedback()}"], ensure_ascii=False
        ),
    }


def _share_sourced(ctx: TaskCtx) -> bool:
    """译文载荷来自共享包：``kind=share`` 导入，或 arxiv 隐式命中已接线。

    零 token 结构承诺的判据面——``options["share"]`` 审计载荷由导入端点
    /``_share_lookup`` 写入；对账回退时 ``_share_unmark`` 摘除即恢复自译。
    """
    return ctx.row["kind"] == "share" or bool(ctx.options().get("share"))


def share_pack_publish(
    work_dir: Path, manifest: Mapping[str, object], out_dir: Path
) -> tuple[Path, ShareManifest]:
    """``pack_share`` → ``unpack_share`` 全量回验 → ``index_append`` 落行。

    完成钩 ``_share_pack_try`` 与 ``POST /api/task/{id}/share/pack`` 共用
    的发布段：包与 ``index.jsonl`` 同落 ``out_dir``（``share_dir()``），
    行内 ``url`` 记包文件名（§7 文件级形态——目录整体挂静态托管后，
    行内相对名即取包路径）。写盘损坏的包不进索引（``.share-verify``
    scratch 目录随验随清）。

    纯 FS 面——不触 store/bus，可在 ``asyncio.to_thread`` 工作线程跑。
    返回 ``(包路径, 校验后 manifest)``。
    """
    bundle = pack_share(work_dir, manifest, out_dir=out_dir)
    # mkdtemp 唯一 scratch——并发同任务双发不会互删对方的校验现场
    scratch = Path(tempfile.mkdtemp(prefix=".share-verify-", dir=work_dir))
    try:
        mf = unpack_share(bundle, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    index_append(
        out_dir / "index.jsonl",
        mf,
        url=bundle.name,
        package_bytes=bundle.stat().st_size,
    )
    return bundle, mf


class _Share:
    """共享包对账/摘标/打包发布 mixin。"""

    async def _stage_share_apply(self, ctx: TaskCtx) -> None:
        """translating（共享臂）：包内 chunks 对账本地 chunks → 译文落库。"""
        self._stage(ctx, "translating", "共享译文对账", PROGRESS["translating"][0])
        # retry 换包重对账会改 chunks 行——同款快照供事后摘 .splice-done
        pre_rows = {
            r["chunk_id"]: (str(r["status"]), str(r["translation"] or ""))
            for r in self.store.all_chunks(ctx.task_id)
        }
        ctx.share = await asyncio.to_thread(self._share_apply, ctx)
        s = ctx.share
        self._log(
            ctx,
            f"share apply: matched={s['matched']}/{s['total']}"
            f" dropped={s['dropped']} missed={s['missed']} extra={s['extra']}",
        )
        self._invalidate_splice(ctx, pre_rows)
        self._stage(ctx, "translating", "对账完成", PROGRESS["translating"][1])
        self._check_cancelled(ctx)

    def _share_apply(self, ctx: TaskCtx) -> dict[str, int]:
        """包内 ``dual.json.chunks`` → 本地 chunks 表译文（§5 第 3 步对账）。

        对账键 ``(src_file, en==src_text)``——本地行按 seq 序贪心消费
        同键包内条目（重复原文段按序各得一份）。``_share_pool`` 只收真
        译文载荷（zh 空/非 str、``zh==en`` 无 CJK 的原文回写条目不进池），
        被滤条目视同无条目。命中译文先过 ``validate_pair``（与 LLM 产出
        同款 L0 判据）：过 → ``ok``；不过 → ``fallback_orig`` +
        ``validate``。本地无包条目的块 → ``fallback_orig`` +
        ``share_miss``（v1 不回退自译——导入保持零 token）；包内多余
        条目只记 ``extra`` 忽略。零命中即包与本源不对应 →
        ``_ShareRejectError``（不写库）。``flush_chunk_batch``
        单事务落盘——崩溃只有「全没落」一态，resume 重跑即幂等。
        """
        dual_path = ctx.root / "share" / "dual.json"
        try:
            doc = json.loads(dual_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            # UnicodeDecodeError 是 ValueError 非 JSONDecodeError——漏它会
            # 走 run() 的 parse 臂把隐式命中任务 fault 掉，而非回退自译
            msg = f"dual.json unreadable: {e}"
            raise _ShareRejectError(msg) from e
        raw = doc.get("chunks") if isinstance(doc, dict) else None
        if not isinstance(raw, list):
            msg = "dual.json missing chunks[]"
            raise _ShareRejectError(msg)
        pool = _share_pool(raw)
        updates: list[tuple[str, dict[str, Any]]] = []
        total = matched = dropped = missed = 0
        for r in self._on_loop(self.store.all_chunks, ctx.task_id):
            total += 1
            outcome, upd = _share_row(r, pool)
            if upd is not None:
                updates.append((r["chunk_id"], upd))
            if outcome in ("ok", "resumed_ok"):
                matched += 1
            elif outcome == "dropped":
                dropped += 1
            elif outcome == "missed":
                missed += 1
        if matched == 0:
            msg = (
                f"share chunks 对账零命中（包内 {len(raw)} 条 vs 本地 "
                f"{total} 块）——包与本源不对应"
            )
            raise _ShareRejectError(msg)
        self._flush_chunk_updates(ctx, updates, [])
        return {
            "total": total,
            "matched": matched,
            "dropped": dropped,
            "missed": missed,
            "extra": sum(len(q) for q in pool.values()),
        }

    # ------------------------------------------------------------ share 命中查询

    def _share_current_key(self, ctx: TaskCtx) -> str | None:
        """库内现值 → share_key（``share_pack_manifest`` 同派生面）；不可寻址 → None。"""
        row = self._on_loop(self.store.get, ctx.task_id)
        if row is None:
            return None
        manifest = self.share_pack_manifest(ctx, row)
        if manifest is None:
            return None
        return share_key(
            str(manifest["arxiv_id"]),
            str(manifest["version"]),
            str(manifest["model"]),
            str(manifest["prompt_ver"]),
            str(manifest["target_lang"]),
            str(manifest["glossary_hash"]),
            str(manifest["pipeline_ver"]),
        )

    def _share_lookup(self, ctx: TaskCtx) -> bool:  # noqa: C901, PLR0911 -- 守卫/回退阶梯平铺即 spec 的跳过面
        """隐式 share 命中查询（shared-cache.md §8）：``_run_tex`` 在 parse 后调。

        触发点选型：share_key 七组分此刻才全齐且与翻译时同口径——
        ``arxiv_id`` 钉版在 fetch 落库，``glossary_hash`` 的 local 层
        （``base/glossary.local.yaml``）与 ``_glossary_path`` confine 根
        都依赖 ``_build_base`` 产物；fetch 后即查会把生效术语表算漏。

        命中 → 包校验解包 ``ctx.root/"share"`` + ``options["share"]`` 审计
        载荷（与导入端点同形）+ ``options["reuse_hit"]="share:{key}"`` 来历
        标记（share/pack 端点据以拒自包——译文非本实例术语表产出，错标
        ``glossary_hash`` 比不打包更糟）。miss/索引损坏/包缺失/校验失败 →
        log 留痕回退自译——隐式命中是优化不是承诺，绝不让任务因查询变坏。

        幂等：标记与 ``share/`` 现场都持久化——resume 重验 key 符且
        ``dual.json`` 在场即直返；retry 改 options 致 key 漂移或 ``share``
        载荷伪造/残缺 → ``_share_unmark`` 摘除后按现状重查。
        """
        if ctx.row["kind"] != "arxiv" or ctx.reuse_hit is not None:
            return False  # share 走 _run_share 自有链；dedup 命中已终态
        opts = ctx.options()
        if str(opts.get("prefer") or "reuse") == "fresh":
            return False
        key = self._share_current_key(ctx)
        marked = opts.get("share")
        if marked is not None:
            if (
                key is not None
                and isinstance(marked, dict)
                and marked.get("share_key") == key
                and (ctx.root / "share" / "dual.json").is_file()
            ):
                if not str(opts.get("reuse_hit") or "").startswith("share:"):
                    # 来历标记被 fetch 摘除/外力抹掉——补回保持拒自包面完整
                    opts["reuse_hit"] = f"share:{key}"
                    ctx.row["options_json"] = json.dumps(opts, ensure_ascii=False)
                    self._on_loop(
                        self.store.update_fields,
                        ctx.task_id,
                        options_json=ctx.row["options_json"],
                    )
                return True  # resume/retry 重验通过——已接线状态直走对账
            self._share_unmark(ctx)
            opts = ctx.options()
        if opts.get("reuse_hit") or key is None:
            return False  # dedup 命中史（来历标记归 dedup 面管）/ 不可寻址
        if not self._on_loop(self.store.has_chunks, ctx.task_id):
            return False  # 零块任务对账必零命中——让自译面正常收尾
        out_dir = share_dir(self.data_dir)
        try:
            hit = _w.index_lookup(out_dir / "index.jsonl", key)
        except (OSError, UnicodeDecodeError) as e:
            # 索引是缓存——读挂一律降级 miss，不为查询面 fault 任务
            # （index_lookup 真实异常面只有 OSError/UnicodeDecodeError：
            # FileNotFoundError 归 None，坏行内吞记 warning）
            self._log(ctx, f"share lookup: index 不可读按 miss 处理: {e}")
            return False
        if hit is None:
            return False
        name = str(hit.get("url") or "")
        if "/" in name or "\\" in name or name in ("", ".", ".."):
            self._log(
                ctx, f"share lookup: index 行 url 非扁平名 {name!r}，按 miss 处理"
            )
            return False
        bundle = out_dir / name
        if not bundle.is_file():
            self._log(ctx, f"share lookup: 行在包不在 {name}，按 miss 处理")
            return False
        dest = ctx.root / "share"
        try:
            mf = unpack_share(bundle, dest)
        except (ShareError, OSError) as e:
            shutil.rmtree(dest, ignore_errors=True)  # 校验中途失败可能留半解包现场
            self._log(ctx, f"share lookup: 包校验失败回退自译: {e}")
            return False
        opts = ctx.options()
        opts["share"] = {
            "share_key": mf.share_key,
            "contributor": mf.contributor,
            "created_at": mf.created_at,
            "key_parts": dict(mf.key_parts),
        }
        opts["reuse_hit"] = f"share:{mf.share_key}"
        ctx.row["options_json"] = json.dumps(opts, ensure_ascii=False)
        self._on_loop(
            self.store.update_fields,
            ctx.task_id,
            options_json=ctx.row["options_json"],
        )
        self._log(
            ctx,
            f"share lookup: 命中 {mf.share_key[:16]}… → 共享对账通道（零 token）",
        )
        return True

    def _share_unmark(self, ctx: TaskCtx) -> None:
        """摘除隐式命中痕迹：``options.share``/``reuse_hit`` 标记 + ``share/`` 解包现场。

        retry 换 options 致 key 漂移、伪造 ``share`` 载荷、对账失败回退
        共用。dedup 来源的 ``reuse_hit``（task id 形）不摘——归 dedup 面管。
        """
        opts = ctx.options()
        dirty = opts.pop("share", None) is not None
        if str(opts.get("reuse_hit") or "").startswith("share:"):
            opts.pop("reuse_hit", None)
            dirty = True
        if dirty:
            ctx.row["options_json"] = json.dumps(opts, ensure_ascii=False)
            self._on_loop(
                self.store.update_fields,
                ctx.task_id,
                options_json=ctx.row["options_json"],
            )
        shutil.rmtree(ctx.root / "share", ignore_errors=True)

    # ------------------------------------------------------------ share 打包钩

    def _share_pack_opt_in(self, ctx: TaskCtx) -> bool:
        """``options.share_pack`` 真值判定（bool 直读；字符串按 ``0/false/no/off`` 系判假）。"""
        v = ctx.options().get("share_pack")
        if v is None or isinstance(v, bool):
            return bool(v)
        return str(v).strip().lower() not in ("", "0", "false", "no", "off")

    def _share_glossary_hash(self, ctx: TaskCtx, cfg: Mapping[str, Any]) -> str:
        """``glossary_hash`` 组分：翻译时**生效**的自定义术语层内容复合指纹。

        口径对齐 ``_make_glossary``：配置的 ``glossary`` 路径经
        ``_glossary_path`` confine——拒/缺席即与翻译时同态回落
        ``USER_GLOSSARY_PATH``（``Glossary.load`` 的缺省 user 层）；
        local 层 ``base/glossary.local.yaml`` 恒进指纹。category/default
        内建层随 ``pipeline_ver`` 走不进指纹（cli ``_share_glossary_hash``
        同口径）。无自定义层 → ``""``。
        """
        gpath = str(cfg.get("glossary") or ctx.options().get("glossary") or "")
        gfile: Path | None = None
        if gpath:
            gfile = self._glossary_path(ctx, gpath, str(cfg.get("glossary_dir") or ""))
        if gfile is None and _w.USER_GLOSSARY_PATH.is_file():
            gfile = _w.USER_GLOSSARY_PATH
        files = [
            f
            for f in (gfile, ctx.base_dir / LOCAL_GLOSSARY_NAME)
            if f is not None and f.is_file()
        ]
        if not files:
            return ""
        h = hashlib.sha256()
        for f in files:
            h.update(hashlib.sha256(f.read_bytes()).digest())
        return h.hexdigest()

    def share_pack_manifest(
        self, ctx: TaskCtx, row: dict[str, Any]
    ) -> dict[str, object] | None:
        """任务行 → key_parts 七组分 manifest；``None`` = 不参与共享寻址。

        完成钩与 ``POST /api/task/{id}/share/pack`` 共用同一派生面：
        ``arxiv_id`` 取库内现值（fetch 后已钉版成 ``{id}v{N}``），
        ``normalize_arxiv_id`` 拆回 base+ver 进组分；``glossary_hash``
        走 ``_share_glossary_hash``（翻译时生效层的复合指纹）；
        ``prompt_ver``/``pipeline_ver`` 钉当前管线常量。
        """
        base, ver = normalize_arxiv_id(str(row.get("arxiv_id") or ""))
        if not base:
            return None
        try:
            cfg = json.loads(str(row.get("config_json") or "{}"))
            if not isinstance(cfg, dict):
                cfg = {}
        except json.JSONDecodeError:
            cfg = {}
        return {
            "arxiv_id": base,
            "version": f"v{ver}" if ver is not None else "",
            "model": str(row["model"]),
            "prompt_ver": PROMPT_VERSION,
            "target_lang": str(row["target_lang"]),
            "glossary_hash": self._share_glossary_hash(ctx, cfg),
            "pipeline_ver": PIPELINE_VERSION,
        }

    async def _maybe_share_pack(self, ctx: TaskCtx) -> None:
        """opt-in 共享包完成钩（shared-cache.md §7/§8）：``_stage_compile`` 各终态分支末尾调用。

        产物面满足 ``REQUIRED_ARTIFACTS``（zh-src.zip+dual.json）即打包——
        zh.pdf 缺席落 partial 包（§9 已放行：fixloop_exhausted 型任务的
        L2/修复译文经包传播有实证价值）。``kind=="share"`` 是导入产物永不
        自包；``options.reuse_hit`` 标记的命中任务（dedup 捷径在
        ``_stage_fetch`` 提前 return 到不了本段，隐式 share 命中会走到
        这里——检查是承重的）译文非本实例术语表产出，错标
        ``glossary_hash`` 比不打包更糟。
        best-effort：任何失败只留 warning，绝不影响任务终态。
        """
        if (
            _share_sourced(ctx)
            or ctx.options().get("reuse_hit")
            or not self._share_pack_opt_in(ctx)
        ):
            return
        try:
            await asyncio.to_thread(self._share_pack_try, ctx)
        except Exception as e:  # noqa: BLE001 -- 共享打包是附加产物，炸不拖累任务终态
            self._warning(ctx, "share_pack", f"共享打包失败（任务不受影响）: {e}")

    def _share_pack_try(self, ctx: TaskCtx) -> None:
        """Worker 线程侧打包体：key_parts 派生 → ``share_pack_publish`` 发布。

        manifest 派生与包发布两段已抽出共用（``share_pack_manifest`` +
        ``share_pack_publish``）——API 事后打包端点走同一口径。upload 类
        无 arxiv_id 不参与共享寻址，记行跳过。
        """
        row = self._on_loop(self.store.get, ctx.task_id)
        if row is None:
            return
        if str(row["status"]) not in ("done", "partial", "fault"):
            # 弃单系终态（cancelled/interrupted/needs_auth）不打：终态检查到
            # 本钩之间用户仍可 cancel——半成品译文进公共 index 违背弃单语义
            return
        manifest = self.share_pack_manifest(ctx, row)
        if manifest is None:
            self._log(ctx, "share pack: 任务无 arxiv_id（不参与共享寻址），跳过打包")
            return
        out_dir = share_dir(self.data_dir)
        bundle, _mf = _w.share_pack_publish(ctx.root, manifest, out_dir)
        self._log(ctx, f"share pack: {bundle.name} → {out_dir}（index.jsonl 已落行）")
