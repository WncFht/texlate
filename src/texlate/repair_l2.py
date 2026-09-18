"""L2 回灌 / env judge 簇——自 ``repair`` 拆出的编译失败归因修复机械。

C4 拆分（reaudit-2026-09-18）：``repair.py`` 收敛为 fixloop 包装/跨引擎
重试/glossary confine 纯低层件，本模块承载 L2 阶梯全实现——
``TreeRun``/``split_cid`` 运行态、env judge 可译性判定
（``_env_judge_one``/``env_judge_all`` + 目标谓词 ``unknown_env_of``）、
L2 回灌机械（``_l2_parse``/``_expand_tokens``/``chunk_spans``/
``_resolve_fidx``/``L2Attr``/``_l2_localize``/``retranslate_hits``/
``_resplice``/``l2_repair_round``）与配套开关/上限常量。

``repair`` 门面按全仓实测消费回引公共名——私名消费请从本模块直取
（B12 口径，不批发回引）。
"""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.compile.inject import InjectRejectError, prepare_chinese
from texlate.compile.judge import paired_slot_diff
from texlate.latex.placeholder import CHUNK_RX, PH_RX
from texlate.latex.reconstruct import (
    _LATIN_ITEM_RX,
    _PAR_RUN_RX,
    _seg_join,
    reconstruct,
    unicode_math_fix,
)
from texlate.latex.tables import (
    ARG_TRANSPARENT_ENVS,
    MATH_ENVS,
    PROTECTED_ENVS,
    VERBATIM_ENVS,
)
from texlate.validate import l2 as l2_mod
from texlate.xlat import prompts as xlat_prompts

if TYPE_CHECKING:
    import re
    from collections.abc import Callable

    from texlate.compile.engine import CompRes
    from texlate.compile.judge import Verdict
    from texlate.latex.model import Chunk, ScanResult
    from texlate.xlat.pipeline import ChunkIn, XlatPipeline

log = logging.getLogger(__name__)

#: L2 回灌默认每文档重译上限（spec ≤10，参数化入口 ``l2_max_chunks``）
L2_MAX_CHUNKS = 10
#: 错误行 → 最近 chunk 的归因距离上限（字符）；超出按基建错处理，不耗 LLM
_L2_ATTR_WINDOW = 4000
#: L2 单次回灌最多消费的 log 错误条数
_L2_MAX_ERRORS = 50
#: ``_expand_tokens`` 递归深度保险丝（自引用 token 不死循环）
_EXPAND_MAX_DEPTH = 32
#: env judge 输入截断（长 env 体只喂前 N 字符）
_ENV_JUDGE_MAX_CHARS = 2000
#: 环境开关
ENV_NO_L2 = "TEXLATE_NO_L2"
ENV_ENV_JUDGE = "TEXLATE_ENV_JUDGE"

#: 静态环境表（已知语义的 env 不问 judge——体是否可译已由表决定）
_KNOWN_ENVS = MATH_ENVS | VERBATIM_ENVS | PROTECTED_ENVS | ARG_TRANSPARENT_ENVS

# ---------------------------------------------------------------- 运行态/env judge


@dataclass
class TreeRun:
    """``_translate_tree`` 的内部运行态——splice 后供 L2 回灌复用。"""

    scans: list[tuple[Path, ScanResult]]
    trans: dict[int, dict[int, str]]  # fidx → {chunk.id: 译文}
    chunk_ins: dict[str, ChunkIn]  # "fidx:cid" → ChunkIn（带 ph_fragments）
    pipe: XlatPipeline


def split_cid(chunk_id: str) -> tuple[int, int]:
    """``"fidx:cid"`` → (fidx, cid)。"""
    a, _, b = chunk_id.partition(":")
    return int(a), int(b)


def unknown_env_of(chunk: Chunk) -> str | None:
    """静态表外 env 名——体可译性未定的 env 返名，已知/无 env 返 None。

    ``env_judge_all`` 目标选择谓词（e2e ``_env_judge_pass`` 与 worker
    ``_env_judge_filter`` 同一闸）。
    """
    env_name = (chunk.env or "").strip()
    return env_name if env_name and env_name not in _KNOWN_ENVS else None


async def _env_judge_one(pipe: XlatPipeline, chunk: Chunk, env_name: str) -> bool:
    """单 env 可译性判定（docs/08 §1.5）：0 温/16 tok/3 试/解析失败 fail-open。"""
    system = xlat_prompts.env_judge_system_prompt(pipe.cfg.src_lang, pipe.cfg.tgt_lang)
    user = (
        f"\\begin{{{env_name}}}\n"
        f"{chunk.content[:_ENV_JUDGE_MAX_CHARS]}\n\\end{{{env_name}}}"
    )
    for _ in range(xlat_prompts.ENV_JUDGE_RETRIES):
        try:
            raw = await pipe.translator.translate(
                system=system,
                user=user,
                temperature=xlat_prompts.ENV_JUDGE_TEMPERATURE,
                max_tokens=xlat_prompts.ENV_JUDGE_MAX_TOKENS,
            )
            return xlat_prompts.parse_env_judge_answer(raw)
        except Exception as e:  # noqa: BLE001 -- judge 是旁路臂，异常→宁翻勿漏
            log.debug("env judge call failed (%s) → retry", e)
            continue
    return True


async def env_judge_all(
    pipe: XlatPipeline, targets: list[tuple[str, Chunk, str]]
) -> dict[str, bool]:
    """逐条判定未知 env 块（顺序跑——mock/单文件路径，量小）。"""
    out: dict[str, bool] = {}
    for cid, chunk, env_name in targets:
        out[cid] = await _env_judge_one(pipe, chunk, env_name)
    return out


# ---------------------------------------------------------------- L2 回灌


def _l2_parse(res: CompRes) -> l2_mod.L2Verdict:
    """CompRes → L2Verdict：log 文本优先，缺席/空文件/读失败退 stdout_tail。

    被杀编译留 0 字节 ``.log``——``exists()`` 判据下 0 错返回 L2 臂
    静默空转（engine.parse_log 同款修复，worker 共享本函数同愈）。
    """
    text = getattr(res, "log_text", "") or ""
    if not text and res.log_path is not None:
        with suppress(OSError):
            text = res.log_path.read_text(encoding="utf-8", errors="replace")
    if text or res.stdout_tail:
        return l2_mod.parse_log_text(text or res.stdout_tail, project_root=res.workdir)
    return l2_mod.L2Verdict(log_missing=True)


def _expand_tokens(
    res: ScanResult, tokmap: dict[str, str], text: str, _depth: int = 0
) -> str:
    r"""``[[X_n]]`` 递归展开到落盘形态（与 reconstruct.expand 同优先级）。

    ``tokmap`` = ``{"[[CHUNK_k]]": unicode_math_fix(zh)}``——译文本位；
    未译 chunk 回落 ``chunks[k].content``，typed ph 走 ``ph_map``。
    已译且 context 非 para/item 的 ``[[CHUNK_n]]`` 展开后同样压 ``\n\n``→``\n``
    （reconstruct.expand 的 ``short_arg`` 同则）——缺这步 ``chunk_spans`` 的
    ``find`` 必对不上落盘字节，块在 L2 二次归因里整片消失。字面/ph 交错段
    接缝同走 ``_seg_join``（``\cs`` 尾 + 字母头补空格）——本函数只服务
    译文落盘文件，``reconstruct`` 侧 ``glue_latin`` 恒真。
    """
    if _depth > _EXPAND_MAX_DEPTH:
        return text

    def rep(m: re.Match[str]) -> str:
        tok = m.group(0)
        body = tokmap.get(tok)
        if body is None:
            body = res.ph_map.get(tok)
        cm = CHUNK_RX.fullmatch(tok)
        if body is None and cm:
            idx = int(cm.group(1))
            if 0 <= idx < len(res.chunks):
                body = res.chunks[idx].content
        if body is None:
            return tok
        out = _expand_tokens(res, tokmap, body, _depth + 1)
        if cm and tok in tokmap:
            idx = int(cm.group(1))
            if 0 <= idx < len(res.chunks) and res.chunks[idx].context not in (
                "para",
                "item",
            ):
                out = _PAR_RUN_RX.sub("\n", out)
        return out

    segs: list[str] = []
    pos = 0
    for m in PH_RX.finditer(text):
        segs.append(text[pos : m.start()])
        segs.append(rep(m))
        pos = m.end()
    segs.append(text[pos:])
    return _seg_join(segs)


def chunk_spans(
    text: str, res: ScanResult, trans: dict[int, str]
) -> dict[int, tuple[int, int] | None]:
    """各 chunk 在当前文件中的 ``[s, e)`` 区间（文档序贪心 find）。

    cjk_glue_fix 可能在译文里插空格 → find 失败的块给 ``None``，位置由
    前后块锚定（归因是启发式，丢块可接受）。
    """
    tokmap = {
        f"[[CHUNK_{cid}]]": _LATIN_ITEM_RX.sub(r"\\item ", unicode_math_fix(zh))
        for cid, zh in trans.items()
    }
    spans: dict[int, tuple[int, int] | None] = {}
    cur = 0
    for c in res.chunks:
        # 走 token 入口——短参折叠只在 rep 见到 [[CHUNK_n]] 时发生（同 reconstruct）
        body = _expand_tokens(res, tokmap, f"[[CHUNK_{c.id}]]")
        if not body:
            continue
        i = text.find(body, cur)
        if i < 0:
            i = text.find(body)  # 乱序兜底（pieces 保序，正常不该走到）
        if i < 0:
            spans[c.id] = None
            continue
        spans[c.id] = (i, i + len(body))
        cur = i + len(body)
    return spans


def _resolve_fidx(token: str, run: TreeRun, work: Path) -> int | None:
    """Log 里的文件名 token → scans 下标（相对/``./``/绝对路径三形态）。"""
    t = token.strip()
    while t.startswith("./"):
        t = t[2:]
    for i, (f, _res) in enumerate(run.scans):
        rel = f.relative_to(work).as_posix()
        if t == rel or t.endswith("/" + rel) or rel.endswith("/" + t):
            return i
    try:
        rel2 = Path(t).resolve().relative_to(work.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    for i, (f, _res) in enumerate(run.scans):
        if f.relative_to(work).as_posix() == rel2:
            return i
    return None


@dataclass
class L2Attr:
    """L2 归因底账：每文件 文本/行偏移/chunk 区间 三表（惰性建）。"""

    run: TreeRun
    work: Path
    texts: dict[int, str] = field(default_factory=dict)
    line_off: dict[int, list[int]] = field(default_factory=dict)
    spans: dict[int, dict[int, tuple[int, int] | None]] = field(default_factory=dict)

    def file_state(self, fidx: int) -> None:
        """惰性建文件文本/行偏移/chunk 区间三表。"""
        if fidx in self.texts:
            return
        f, sres = self.run.scans[fidx]
        self.texts[fidx] = f.read_text(encoding="utf-8", errors="replace")
        offs = [0]
        for ln in self.texts[fidx].splitlines(keepends=True):
            offs.append(offs[-1] + len(ln))
        self.line_off[fidx] = offs
        self.spans[fidx] = chunk_spans(
            self.texts[fidx], sres, self.run.trans.get(fidx) or {}
        )

    def attribute(self, fidx: int, tex_line: int) -> int | None:
        """行号 → 字节偏移 → 所在/最近 chunk.id。

        顺序读取不变量：TeX 报 ``l.NNN`` 时还没读到该行之后——起点落在
        错误行行尾之后的块不可能是肇事者（repro-2501：preamble 错被
        forward-fallback 错归给首个正文块）。runaway/EOF 类报的父文件
        续行位由 ``attr_error`` 的 ``eof_file`` 改派兜住，不经此路。
        """
        offs = self.line_off[fidx]
        if not (1 <= tex_line <= len(offs) - 1):
            return None
        off = offs[tex_line - 1]
        line_end = offs[tex_line]
        best_cid, best_gap = None, _L2_ATTR_WINDOW + 1
        for cid, sp in self.spans[fidx].items():
            if sp is None:
                continue
            s, e = sp
            if s <= off < e:
                return cid
            if s >= line_end:
                continue
            gap = max(s - off, off - e, 0)
            if gap < best_gap:
                best_cid, best_gap = cid, gap
        return best_cid if best_gap <= _L2_ATTR_WINDOW else None

    def attr_error(self, err: l2_mod.LogError) -> tuple[int, list[int]] | None:
        """单条 log 错误 → (fidx, chunk.id 列表)；不可归因 → None。"""
        # runaway/EOF 错（eof_file 非 None）：报位是父文件 ``\input`` 续行，
        # 真肇事文件是 ``)`` 刚弹出的那个——行号属父文件须丢弃，归肇事
        # 文件整体（块多时任归 EOF 侧末块——runaway 的参数起点在文件尾）
        eof = err.eof_file is not None
        src_tok = (
            err.eof_file
            or err.tex_file
            or (err.file_stack[-1] if err.file_stack else None)
        )
        fidx = _resolve_fidx(src_tok, self.run, self.work) if src_tok else None
        if fidx is None:
            return None  # 肇事文件不在产物树——错怪父文件不如不归因
        self.file_state(fidx)
        sres = self.run.scans[fidx][1]
        if not eof and err.tex_line is not None:
            cid = self.attribute(fidx, err.tex_line)
            return (fidx, [cid] if cid is not None else [])
        if len(sres.chunks) <= L2_MAX_CHUNKS:
            return (fidx, [c.id for c in sres.chunks])
        if eof and sres.chunks:
            return (fidx, [sres.chunks[-1].id])
        return (fidx, [])


def _l2_localize(
    work: Path, run: TreeRun, res: CompRes
) -> tuple[dict[str, dict[str, Any]], int]:
    """编译 log → ``{chunk_id: {file,line,head}}`` 归因表 + 错误总数。

    定位链：``eof_file``（runaway/EOF 错——报位是父文件续行，改派 ``)``
    刚弹出的肇事文件，行号丢弃）> ``tex_file``（file:line: 格式）> 文件栈
    **最内层**（``l.NNN`` 只对 TeX 正在读的文件有意义——栈里更深的
    ``.sty``/``.cls`` 错是基建问题，不归 chunk）。``tex_line`` → 字节偏移
    → 所在 chunk；不在任何块内则取最近块（≤ ``_L2_ATTR_WINDOW``，且起点
    越过错误行行尾的块被顺序读取不变量排除）。无行号错误按文件级
    归因——仅当该文件 chunk 数 ≤ ``L2_MAX_CHUNKS`` 才全收。
    """
    verdict = _l2_parse(res)
    if verdict.log_missing or not verdict.errors:
        return {}, verdict.n_errors
    st = L2Attr(run, work)
    hits: dict[str, dict[str, Any]] = {}
    for err in verdict.errors[:_L2_MAX_ERRORS]:
        got = st.attr_error(err)
        if got is None:
            continue
        fidx, cids = got
        for cid in cids:
            key = f"{fidx}:{cid}"
            if key not in hits:
                rel = run.scans[fidx][0].relative_to(work).as_posix()
                hits[key] = {"file": rel, "line": err.tex_line, "head": err.head}
    return hits, verdict.n_errors


async def retranslate_hits(
    run: TreeRun, hits: dict[str, dict[str, Any]], cap: int
) -> dict[str, Any]:
    """逐块重译（单发）+ 结果入账；返回报告 dict（``_`` 前缀内部键）。"""
    rep: dict[str, Any] = {
        "retranslated": [],
        "reverted_l0": [],
        "kept_transport_err": [],
        "over_cap": [],
    }
    changed: set[str] = rep.setdefault("_changed", set())
    adopted: set[str] = rep.setdefault("_adopted", set())
    tried = 0
    for cid, info in hits.items():
        if tried >= cap:
            rep["over_cap"].append(cid)
            continue
        ci = run.chunk_ins.get(cid)
        if ci is None:
            continue
        tried += 1
        fidx, ccid = split_cid(cid)
        loc = f"{info['file']}:{info['line']}" if info["line"] else info["file"]
        r = await run.pipe.retranslate_chunk(ci, f"{info['head']}\n(at {loc})")
        if r is None:
            rep["kept_transport_err"].append(cid)
            continue
        if r.status == "ok":
            run.trans.setdefault(fidx, {})[ccid] = r.translation
            rep["retranslated"].append(cid)
            adopted.add(cid)
        else:
            # 重译产物仍不过 L0 → 回落原文（spec: 再不过 → fallback 原文）
            run.trans.get(fidx, {}).pop(ccid, None)
            rep["reverted_l0"].append(cid)
        changed.add(cid)
    return rep


def _resplice(run: TreeRun, work: Path, main_rel: str, fidxs: set[int]) -> list[str]:
    """受影响文件 reconstruct 重写；主文件重跑 ``prepare_chinese`` 补 ctex。"""
    main_path = work / main_rel
    rewritten: list[str] = []
    touched_main = False
    for fidx in sorted(fidxs):
        f, res = run.scans[fidx]
        f.write_text(reconstruct(res, run.trans.get(fidx) or {}), encoding="utf-8")
        rewritten.append(f.relative_to(work).as_posix())
        touched_main = touched_main or f == main_path
    if touched_main:
        # 首注已过——同文件重注不会再触发 \documentstyle 拒绝
        with suppress(InjectRejectError):
            prepare_chinese(work, main_rel)
    return rewritten


def _slot_diffs(run: TreeRun, work: Path, fidxs: set[int]) -> dict[str, list[str]]:
    """``_resplice`` 落盘 zh 对 ``res.vtex`` 的机位配对 diff——重写后逐文件对账。"""
    out: dict[str, list[str]] = {}
    for fidx in sorted(fidxs):
        f, res = run.scans[fidx]
        rel = f.relative_to(work).as_posix()
        if notes := paired_slot_diff(res.vtex, f.read_text(encoding="utf-8"), rel):
            out[rel] = notes
    return out


def l2_repair_round(  # noqa: C901, PLR0913 -- 阶梯直铺：钩子面穿透两臂同一契约
    run: TreeRun,
    work: Path,
    main_rel: str,
    res: CompRes,
    cap: int,
    *,
    retranslate: Callable[[TreeRun, dict[str, dict[str, Any]], int], dict[str, Any]],
    recompile: Callable[[], tuple[CompRes, Verdict]],
    checkpoint: Callable[[], None] | None = None,
) -> tuple[dict[str, Any], CompRes, Verdict | None]:
    """L2 回灌一轮骨架：归因 → 重译 → resplice → 重编 → 余孽回落原文。

    ``retranslate``/``recompile`` 两臂注入——e2e 包 ``asyncio.run(
    retranslate_hits)`` + ``_compile_judge``（tail dict 臂侧合成）；
    worker 包 client aclose 同 loop 纪律 + ``eng.compile``+``judge``。
    ``checkpoint`` 是 cancel 轮询点（worker ``_abort_if_cancelled``
    同位三处：重译前/后、首编后），缺省无操作。
    返回 (l2 报告, 最新 CompRes, 新 Verdict 或 None=未重编)。
    """
    rep: dict[str, Any] = {"enabled": True, "cap": cap}
    hits, n_err = _l2_localize(work, run, res)
    rep["errors"] = n_err
    rep["hits"] = hits
    last_res = res
    if not hits:
        rep["note"] = "no chunk-level attribution"
        return rep, last_res, None
    if checkpoint is not None:
        checkpoint()
    retr = retranslate(run, hits, cap)
    if checkpoint is not None:
        checkpoint()
    changed: set[str] = retr.pop("_changed")
    adopted: set[str] = retr.pop("_adopted")
    rep.update(retr)
    if not changed:
        rep["note"] = "no chunk changed"
        return rep, last_res, None

    fidxs = {split_cid(c)[0] for c in changed}
    rep["rewritten"] = _resplice(run, work, main_rel, fidxs)
    if diffs := _slot_diffs(run, work, fidxs):
        rep["slot_diffs"] = diffs
    res2, v2 = recompile()
    if checkpoint is not None:
        checkpoint()
    last_res = res2
    rep["recompiled"] = v2.status
    if v2.status == "clean":
        return rep, last_res, v2

    # 重编仍不过：本轮"重译过且仍被点名"的块回落原文；
    # 其余归因（含已回落原文仍犯错的——那是源级问题）记名留 fixloop。
    hits2, _ = _l2_localize(work, run, res2)
    still_bad = sorted(set(hits2) & adopted)
    rep["fallback_src"] = still_bad
    rep["unresolved"] = sorted(set(hits2) - adopted)
    if still_bad:
        for cid in still_bad:
            fidx, ccid = split_cid(cid)
            run.trans.get(fidx, {}).pop(ccid, None)
        fb_fidxs = {split_cid(c)[0] for c in still_bad}
        rep["fallback_rewritten"] = _resplice(run, work, main_rel, fb_fidxs)
        if diffs := _slot_diffs(run, work, fb_fidxs):
            rep["fallback_slot_diffs"] = diffs
        # 回落态即交付树——补一次裸编：fixloop 关/崩/reject 时不再有
        # 代验兜底，zh-src.zip 不能装未验证树（audit fallback_unverified）
        res3, v3 = recompile()
        rep["fallback_verdict"] = v3.status
        last_res, v2 = res3, v3
    return rep, last_res, v2
