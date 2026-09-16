"""mock E2E 驱动（docs/10 B5 Mode A 的产品化扶正）。

全链走产品 API：``route_project → normalize_project → XlatPipeline(MockTranslator)
+ L0 校验 → splice 写回 → prepare_chinese → engine.compile → judge``。
bench harness（e2e_mock_bench）与 CLI ``texlate run`` 共用同一实现——
评测条件矩阵在 bench 侧，单工程驱动在这里。

编译失败后的两级修复（docs/08 §2.3/§5 接线）：

1. **L2 回灌**（先跑）——log 解析把错误定位到 chunk（file:line: 或文件栈
   归因），只重译被点名的块（每块限 1 次、per-doc 有上限），resplice 后
   重编一次；仍被点名且本轮重译过的块回落原文（"再不过 → fallback 原文"）。
   先修自家译文伤——fixloop 的 regex_rewrite 会直接改盘上文件，若先跑
   fixloop 再 resplice 会把它的修复冲掉。
2. **fixloop**（后跑）——yaml 规则引擎修源/基建类问题（缺包、preamble、
   字体……）。``TEXLATE_NO_FIXLOOP=1`` 关闭（测试/对照臂）；轮数上限沿用
   rules.yaml ``meta.loop.max_rounds``。产出 ``engine_flags`` 在此消费：
   当前引擎没法直接吃 CLI 旗标（引擎 seam 未开），先落 advisory + 触发
   跨引擎换编（tectonic 上收到 flag → 换 xelatex 再编，取更优 verdict）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.compile.cjkmap import embed_cjk_mappings
from texlate.compile.engine import engine_for, route_project
from texlate.compile.fixloop.engine import LlmHook, fixloop
from texlate.compile.inject import InjectRejectError, find_main_tex, prepare_chinese
from texlate.compile.judge import Verdict, judge
from texlate.compile.normalize import normalize_project
from texlate.latex.api import parse_file
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
from texlate.validate.l0 import validate_pair
from texlate.xlat import prompts as xlat_prompts
from texlate.xlat.glossary import Glossary
from texlate.xlat.pipeline import (
    ChunkIn,
    MockTranslator,
    XlatPipeline,
    chunk_to_in,
)
from texlate.xlat.placeholders import collect_doc_placeholders

if TYPE_CHECKING:
    import re

    from texlate.compile.engine import CompRes, Engine
    from texlate.latex.model import Chunk, ScanResult
    from texlate.xlat.pipeline import ChunkResult, Translator

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
_ENV_NO_FIXLOOP = "TEXLATE_NO_FIXLOOP"
_ENV_NO_L2 = "TEXLATE_NO_L2"
_ENV_ENV_JUDGE = "TEXLATE_ENV_JUDGE"

#: 静态环境表（已知语义的 env 不问 judge——体是否可译已由表决定）
_KNOWN_ENVS = MATH_ENVS | VERBATIM_ENVS | PROTECTED_ENVS | ARG_TRANSPARENT_ENVS

#: verdict 排序（跨引擎取优用）
_VERDICT_RANK = {"clean": 3, "partial": 2, "fail": 1, "reject": 0}


def _env_flag(name: str, *, default: bool) -> bool:
    """读布尔 env：``1/true/yes/on`` 为真；未设置取 default。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------- 翻译树


@dataclass
class _TreeRun:
    """``_translate_tree`` 的内部运行态——splice 后供 L2 回灌复用。"""

    scans: list[tuple[Path, ScanResult]]
    trans: dict[int, dict[int, str]]  # fidx → {chunk.id: 译文}
    chunk_ins: dict[str, ChunkIn]  # "fidx:cid" → ChunkIn（带 ph_fragments）
    pipe: XlatPipeline


def _split_cid(chunk_id: str) -> tuple[int, int]:
    """``"fidx:cid"`` → (fidx, cid)。"""
    a, _, b = chunk_id.partition(":")
    return int(a), int(b)


def _delivered(r: ChunkResult) -> bool:
    """该 chunk 的译文会进 splice——与产品臂同口径。

    worker ``_PIPE_TO_DB`` 把 pipeline ``partial``（阶梯 recovered）归
    ``ok`` 照常 splice；``e2e_real_bench`` 同此。只要求译文非空——
    skipped/fault 的 ``translation`` 是原文回填，不判。
    """
    return r.status == "ok" or (r.status == "partial" and bool(r.translation))


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
        except Exception as e:  # noqa: BLE001 -- judge 是旁路臂，异常→宁翻勿漏
            log.debug("env judge call failed (%s) → retry", e)
            continue
        return xlat_prompts.parse_env_judge_answer(raw)
    return True


async def _env_judge_all(
    pipe: XlatPipeline, targets: list[tuple[str, Chunk, str]]
) -> dict[str, bool]:
    """逐条判定未知 env 块（顺序跑——mock/单文件路径，量小）。"""
    out: dict[str, bool] = {}
    for cid, chunk, env_name in targets:
        out[cid] = await _env_judge_one(pipe, chunk, env_name)
    return out


def _env_judge_pass(
    pipe: XlatPipeline,
    scans: list[tuple[Path, ScanResult]],
    results: list[ChunkResult],
    by_file: dict[int, dict[int, str]],
) -> dict[str, Any]:
    """未知 env 块 → LLM 可译性判定；判 False 的块从 ``by_file`` 摘除（回落原文）。"""
    targets: list[tuple[str, Chunk, str]] = []
    for r in results:
        if not _delivered(r):
            continue
        fidx, cid = _split_cid(r.chunk_id)
        chunk = scans[fidx][1].chunks[cid]
        env_name = (chunk.env or "").strip()
        if env_name and env_name not in _KNOWN_ENVS:
            targets.append((r.chunk_id, chunk, env_name))
    verdicts = asyncio.run(_env_judge_all(pipe, targets))
    reverted = sorted(cid for cid, keep in verdicts.items() if not keep)
    for cid in reverted:
        fidx, ccid = _split_cid(cid)
        by_file.get(fidx, {}).pop(ccid, None)
    return {"enabled": True, "asked": len(targets), "reverted": reverted}


def _translate_tree(
    root: Path,
    *,
    translator: Translator | None = None,
    env_judge: bool = False,
) -> tuple[dict, _TreeRun]:
    """目录树翻译 + splice 写回；返回 (stats, 运行态)。

    ``env_judge=True`` 时对静态表外的未知 env 块问 LLM 可译性——
    False 的块回落原文不进 splice。
    """
    scans: list[tuple[Path, ScanResult]] = []
    chunks: list[ChunkIn] = []
    fault_files: list[str] = []
    for f in sorted(f for f in root.rglob("*") if f.suffix.lower() == ".tex"):
        if f.name.lower().endswith(".rtx.tex"):
            continue  # REVTeX 运行时转储不进翻译集 (regress4-1003.1717)
        try:
            res = parse_file(f, flatten=False)
        except Exception:  # noqa: BLE001 -- 单文件解析崩不拖垮整树：
            fault_files.append(f.name)  # 记名可审计，该文件按原文保留
            continue
        idx = len(scans)
        scans.append((f, res))
        chunks.extend(
            chunk_to_in(c, chunk_id=f"{idx}:{c.id}", ph_map=res.ph_map)
            for c in res.chunks
        )

    pipe = XlatPipeline(
        translator or MockTranslator(),
        glossary=Glossary.load(
            placeholders=collect_doc_placeholders(c.content for c in chunks)
        ),
        validator=lambda s, z: validate_pair(s, z).feedback(),
        cache={},
    )
    results = asyncio.run(pipe.run(chunks))
    by_file: dict[int, dict[int, str]] = {}
    n_fault = 0
    n_partial = 0
    for r in results:
        fidx, cid = _split_cid(r.chunk_id)
        if _delivered(r):
            by_file.setdefault(fidx, {})[cid] = r.translation
            if r.status == "partial":
                n_partial += 1
        else:
            n_fault += 1

    env_stats: dict[str, Any] = (
        _env_judge_pass(pipe, scans, results, by_file)
        if env_judge
        else {"enabled": False}
    )

    n_files = 0
    n_leftover = 0
    for idx, (f, res) in enumerate(scans):
        trans = by_file.get(idx)
        if not trans:
            continue
        zh = reconstruct(res, trans)
        f.write_text(zh, encoding="utf-8")
        n_files += 1
        n_leftover += len(PH_RX.findall(zh))
    stats = {
        "files": n_files,
        "chunks": len(chunks),
        "partial_chunks": n_partial,
        "fault_chunks": n_fault,
        "fault_files": fault_files,
        "leftover_ph": n_leftover,
        "env_judge": env_stats,
    }
    run = _TreeRun(
        scans=scans,
        trans=by_file,
        chunk_ins={c.chunk_id: c for c in chunks},
        pipe=pipe,
    )
    return stats, run


def mock_translate_tree(
    root: Path,
    *,
    translator: Translator | None = None,
    env_judge: bool | None = None,
) -> dict:
    """目录树内全部 .tex 走 XlatPipeline(MockTranslator) → splice 写回。

    单 pipeline 跨文件编排（chunk_id = ``{file_idx}:{chunk.id}``），
    校验器注入 L0 ``validate_pair``。返回 per-tree 汇总统计。
    ``translator`` 可注入真网关 Translator；``env_judge`` 缺省读
    ``TEXLATE_ENV_JUDGE``（默认关——静态表外 env 的可译性 LLM 判定）。
    """
    ej = _env_flag(_ENV_ENV_JUDGE, default=False) if env_judge is None else env_judge
    stats, _run = _translate_tree(root, translator=translator, env_judge=ej)
    return stats


# ---------------------------------------------------------------- 编译尾段


@dataclass(frozen=True)
class _Job:
    """单工程编译上下文——work/main/引擎/超时四件套在修复链里全程同捆。"""

    work: Path
    main_rel: str
    eng_name: str
    timeout: float


def _tail_dict(res: CompRes, v: Verdict) -> dict:
    """CompRes + Verdict → 报告尾段（compile/verdict/status 三键）。"""
    return {
        "compile": {
            "ok": res.ok,
            "timed_out": res.timed_out,
            "seconds": round(res.seconds, 2),
            "passes": res.passes,
            "rc": res.rc,
            "killed_signal": res.killed_signal,
            "pdf_bytes": res.pdf_bytes,
            "first_error": res.log.first_error,
        },
        "verdict": {
            "status": v.status,
            "reasons": v.reasons,
            "notes": v.notes,
            "n_errors": v.n_errors,
            "category": v.category,
            "cjk_chars": v.cjk_chars,
            "missing_chars": v.missing_chars,
            "warnings_hit": v.warnings_hit,
        },
        "status": v.status,
    }


def _compile_judge(
    job: _Job, *, expect_cjk: bool, flags: list[str] | None = None
) -> tuple[dict, CompRes]:
    """编译 + 判定公共尾段 → (报告 dict, CompRes)。

    best-effort 语义：xelatex halt_on_error=False 对齐 bench；
    tectonic 无此旋钮——恒 ``-Z continue-on-errors``。``flags`` 透传
    fixloop engine_flags（跨引擎臂用——tectonic 丢的 flag 由 xelatex 接）。
    """
    kw: dict[str, object] = (
        {"halt_on_error": False} if job.eng_name == "xelatex" else {}
    )
    res = engine_for(job.eng_name, **kw).compile(
        job.work, job.main_rel, timeout=job.timeout, sandbox=True, flags=flags
    )
    v = judge(res, expect_cjk=expect_cjk)
    return _tail_dict(res, v), res


def _embed_tounicode(pdf: Path) -> int:
    """``embed_cjk_mappings`` best-effort 壳：后处理崩不拖管线（对齐 worker 语义）。"""
    try:
        return embed_cjk_mappings(pdf)
    except Exception:  # 产物后处理失败不该 fault 整链
        log.debug("tounicode embed failed", exc_info=True)
        return 0


# ---------------------------------------------------------------- L2 回灌


def _l2_parse(res: CompRes) -> l2_mod.L2Verdict:
    """CompRes → L2Verdict：log_path 优先，缺席退 stdout_tail。"""
    if res.log_path is not None and res.log_path.exists():
        return l2_mod.parse_log(res.log_path, project_root=res.workdir)
    if res.stdout_tail:
        return l2_mod.parse_log_text(res.stdout_tail, project_root=res.workdir)
    return l2_mod.L2Verdict(log_missing=True)


def _expand_tokens(
    res: ScanResult, tokmap: dict[str, str], text: str, _depth: int = 0
) -> str:
    r"""``[[X_n]]`` 递归展开到落盘形态（与 reconstruct.expand 同优先级）。

    ``tokmap`` = ``{"[[CHUNK_k]]": unicode_math_fix(zh)}``——译文本位；
    未译 chunk 回落 ``chunks[k].content``，typed ph 走 ``ph_map``。
    已译且 context 非 para/item 的 ``[[CHUNK_n]]`` 展开后同样压 ``\n\n``→``\n``
    （reconstruct.expand 的 ``short_arg`` 同则）——缺这步 ``_chunk_spans`` 的
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


def _chunk_spans(
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


def _resolve_fidx(token: str, run: _TreeRun, work: Path) -> int | None:
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
class _L2Attr:
    """L2 归因底账：每文件 文本/行偏移/chunk 区间 三表（惰性建）。"""

    run: _TreeRun
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
        self.spans[fidx] = _chunk_spans(
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
    work: Path, run: _TreeRun, res: CompRes
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
    st = _L2Attr(run, work)
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


async def _retranslate_hits(
    run: _TreeRun, hits: dict[str, dict[str, Any]], cap: int
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
        fidx, ccid = _split_cid(cid)
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


def _resplice(run: _TreeRun, work: Path, main_rel: str, fidxs: set[int]) -> list[str]:
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


def _l2_repair(
    job: _Job, run: _TreeRun, res: CompRes, cap: int
) -> tuple[dict, CompRes, dict | None]:
    """L2 回灌一轮：归因 → 重译 → resplice → 重编一次 → 余孽回落。

    返回 (l2 报告, 最新 CompRes, 新尾段或 None)。
    """
    rep: dict[str, Any] = {"enabled": True, "cap": cap}
    hits, n_err = _l2_localize(job.work, run, res)
    rep["errors"] = n_err
    rep["hits"] = hits
    last_res = res
    if not hits:
        rep["note"] = "no chunk-level attribution"
        return rep, last_res, None

    retr = asyncio.run(_retranslate_hits(run, hits, cap))
    changed: set[str] = retr.pop("_changed")
    adopted: set[str] = retr.pop("_adopted")
    rep.update(retr)
    if not changed:
        rep["note"] = "no chunk changed"
        return rep, last_res, None

    rep["rewritten"] = _resplice(
        run, job.work, job.main_rel, {_split_cid(c)[0] for c in changed}
    )
    tail2, res2 = _compile_judge(job, expect_cjk=True)
    last_res = res2
    rep["recompiled"] = tail2["verdict"]["status"]
    if tail2["status"] == "clean":
        return rep, last_res, tail2

    # 重编仍不过：本轮"重译过且仍被点名"的块回落原文；
    # 其余归因（含已回落原文仍犯错的——那是源级问题）记名留 fixloop。
    hits2, _ = _l2_localize(job.work, run, res2)
    still_bad = sorted(set(hits2) & adopted)
    rep["fallback_src"] = still_bad
    rep["unresolved"] = sorted(set(hits2) - adopted)
    if still_bad:
        for cid in still_bad:
            fidx, ccid = _split_cid(cid)
            run.trans.get(fidx, {}).pop(ccid, None)
        rep["fallback_rewritten"] = _resplice(
            run, job.work, job.main_rel, {_split_cid(c)[0] for c in still_bad}
        )
        rep["fallback_unverified"] = True  # 回落后未再编——下一级 fixloop 代验
    return rep, last_res, tail2


# ---------------------------------------------------------------- fixloop


class _LastResEngine:
    """Engine 代理：转发 Protocol 面 + 记末次 CompRes（fixloop 终判原料）。

    ``__setattr__`` 透传到内层——fixloop ``_wire_engine`` 会给 tectonic
    注入 ``ctan_fetch``，必须落到真引擎上。
    """

    def __init__(self, inner: Engine) -> None:
        """包一层引擎。"""
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "last", None)

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 -- 代理面
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:  # noqa: ANN401
        if name in {"_inner", "last"}:
            object.__setattr__(self, name, value)
        else:
            setattr(self._inner, name, value)

    def compile(self, *args: Any, **kwargs: Any) -> CompRes:  # noqa: ANN401
        """转发 compile 并记录结果。"""
        res: CompRes = self._inner.compile(*args, **kwargs)
        object.__setattr__(self, "last", res)
        return res


def _slim_cell(cell: dict[str, Any]) -> dict[str, Any]:
    """Fixloop cell → 报告视图：rounds × actions 合并成 ``{cat,pay,rule,result}``。"""
    acts: dict[Any, dict[str, Any]] = {}
    for a in cell.get("actions") or []:
        acts.setdefault(a.get("round"), a)
    rounds = [
        {
            "round": r.get("round"),
            "cat": r.get("category"),
            "pay": r.get("payload"),
            "pdf": r.get("pdf"),
            "n_errors": r.get("n_errors"),
            "rule": (acts.get(r.get("round")) or {}).get("rule"),
            "result": (acts.get(r.get("round")) or {}).get("detail"),
        }
        for r in cell.get("rounds") or []
    ]
    return {
        "enabled": True,
        "verdict": cell.get("verdict"),
        "main": cell.get("main"),
        "rounds": rounds,
        "advisories": cell.get("advisories") or [],
        "installed": cell.get("installed") or [],
        "engine_flags": cell.get("engine_flags") or [],
        "engine_flags_dropped": cell.get("engine_flags_dropped") or [],
        "log_excerpt": cell.get("log_excerpt"),
    }


def _run_fixloop(  # noqa: PLR0913 -- 开关面穿透同 pipe_condition
    job: _Job,
    route_engines: list[str],
    prev_res: CompRes,
    *,
    timeout: float | None = None,
    llm_hook: LlmHook | None = None,
    expect_cjk: bool = True,
) -> tuple[dict, dict | None, CompRes]:
    """跑 fixloop + 消费 engine_flags → (报告, 新尾段或 None, 最新 CompRes)。

    引擎新造不带 e2e 的 best-effort 旋钮——xelatex 默认 halt_on_error=True
    （fixloop 首错分类语义）。flags 经 ``compile(flags=…)`` seam 落 CLI：
    xelatex 追加 argv；tectonic 只放支持子集，dropped 项（多为
    shell-escape 需求）→ 记 advisory + 换 xelatex 重编取优。

    ``timeout`` 覆盖 rules.yaml ``meta.loop.timeout_sec`` 的重编预算
    （None=用 yaml 值）。``llm_hook`` 未传时 ``TEXLATE_FIXLOOP_LLM=1``
    可经 env 启用 escalate_llm 钩（网关走 TEXLATE_* 三件套）。
    """
    if llm_hook is None and _env_flag("TEXLATE_FIXLOOP_LLM", default=False):
        from texlate.compile.fixloop.llm_hook import make_llm_hook  # noqa: PLC0415

        llm_hook = make_llm_hook()
    proxy = _LastResEngine(engine_for(job.eng_name))
    try:
        cell = fixloop(
            job.work,
            proxy,
            engine_name=job.eng_name,
            llm_hook=llm_hook,
            compile_timeout=timeout,
        )
    except Exception as e:  # noqa: BLE001 -- 修复臂崩不毁主报告
        return ({"enabled": True, "error": f"{type(e).__name__}: {e}"}, None, prev_res)
    rep = _slim_cell(cell)
    last_res = proxy.last or prev_res
    cell_verdict = str(cell.get("verdict") or "")
    if cell_verdict.startswith("reject:"):
        # reject:<rid> = 策略拒绝 (走降级链) → 终态合成 partial, 理由串
        # 保留 reject 令牌供下游分流审计 (docs/08:185, spec §9 F3)。
        tail = _tail_dict(last_res, Verdict(status="partial", reasons=[cell_verdict]))
        tail["reject_at"] = "fixloop"
    else:
        tail = _tail_dict(last_res, judge(last_res, expect_cjk=expect_cjk))

    flags: list[str] = rep["engine_flags"]
    dropped: list[str] = rep["engine_flags_dropped"]
    if dropped:
        rep["flags_unapplied"] = True
        # 跨引擎消费：dropped 多为 shell-escape 需求——tectonic --untrusted
        # 下不收 → 换 xelatex 重编并把全部请求 flag 经 seam 带给它
        if (
            job.eng_name == "tectonic"
            and "xelatex" in route_engines
            and _VERDICT_RANK.get(tail["status"], 0) < _VERDICT_RANK["clean"]
        ):
            xtail, xres = _compile_judge(
                _Job(job.work, job.main_rel, "xelatex", job.timeout),
                expect_cjk=expect_cjk,
                flags=flags,
            )
            rep["cross_engine"] = {
                "engine": "xelatex",
                "status": xtail["status"],
                "reason": f"engine_flags {dropped} tectonic 不支持 → 换 xelatex",
            }
            if _VERDICT_RANK.get(xtail["status"], 0) > _VERDICT_RANK.get(
                tail["status"], 0
            ):
                tail, last_res = xtail, xres
        # 注在换编之后——贴到最终采用的 tail 上，换臂不丢审计痕迹
        tail["verdict"]["notes"].append(
            f"engine_flags unsupported on {job.eng_name}: {dropped}"
        )
    elif flags:
        tail["verdict"]["notes"].append(f"engine_flags applied via CLI seam: {flags}")
    return rep, tail, last_res


# ---------------------------------------------------------------- 条件臂


def pipe_condition(  # noqa: PLR0913 -- 修复链开关面（env 缺省，显式可覆盖）
    work: Path,
    eng_name: str,
    main_rel: str,
    timeout: float,
    *,
    translator: Translator | None = None,
    env_judge: bool | None = None,
    l2_on: bool | None = None,
    fixloop_on: bool | None = None,
    l2_max_chunks: int = L2_MAX_CHUNKS,
    route_engines: list[str] | None = None,
) -> dict:
    """跑 pipe 条件：normalize → 翻译 → ctex 注入 → 编译 → 判定 → 修复链。

    非 clean 时先 L2 回灌（译文归因重译）再 fixloop（规则修源）。开关：
    ``TEXLATE_ENV_JUDGE`` / ``TEXLATE_NO_L2`` / ``TEXLATE_NO_FIXLOOP``
    （显式参数优先于 env）。``route_engines`` 供 engine_flags 跨引擎消费，
    缺省 ``[eng_name]``（bench 直调不跨界）。
    """
    rec: dict[str, object] = {"engine": eng_name}
    rec["normalize"] = normalize_project(work, eng_name, main_rel)
    job = _Job(work, main_rel, eng_name, timeout)
    ej = _env_flag(_ENV_ENV_JUDGE, default=False) if env_judge is None else env_judge
    stats, run = _translate_tree(work, translator=translator, env_judge=ej)
    rec["translate"] = stats
    try:
        rec["inject"] = prepare_chinese(work, main_rel)
    except InjectRejectError as e:
        # 策略拒绝 → partial (降级链交付), reject_at+reason 留审计 (F3)
        rec["status"] = "partial"
        rec["reject_at"] = "inject"  # inject_reject 类: 与 route reject 分流
        rec["verdict"] = {"status": "partial", "reasons": [e.reason]}
        return rec
    # 0-chunk 主文档 (includepdf 壳等) 无译文产出 → 不期待 CJK 渲染,
    # cjk_chars=0 是其正确终态而非静默失败 (scout-cjk0 F 桶 11 格假阳)
    expect_cjk = stats.get("chunks") != 0
    tail, res = _compile_judge(job, expect_cjk=expect_cjk)
    rec.update(tail)

    if rec["status"] != "clean":
        l2 = (not _env_flag(_ENV_NO_L2, default=False)) if l2_on is None else l2_on
        if l2:
            l2_rep, res, tail2 = _l2_repair(job, run, res, l2_max_chunks)
            rec["l2"] = l2_rep
            if tail2 is not None:
                rec.update(tail2)
        else:
            rec["l2"] = {"enabled": False, "reason": _ENV_NO_L2}

        fl = (
            (not _env_flag(_ENV_NO_FIXLOOP, default=False))
            if fixloop_on is None
            else fixloop_on
        )
        if rec["status"] != "clean" and fl:
            fl_rep, tail3, res = _run_fixloop(
                job, route_engines or [eng_name], res, expect_cjk=expect_cjk
            )
            rec["fixloop"] = fl_rep
            if tail3 is not None:
                rec.update(tail3)
        elif rec["status"] != "clean":
            rec["fixloop"] = {"enabled": False, "reason": _ENV_NO_FIXLOOP}
    # ToUnicode 注入在修复链收敛之后——L2 重编/fixloop 换编都会重写同一
    # <stem>.pdf，只对最终落盘产物注一次（worker _embed_tounicode 同位）
    if res.has_pdf and res.pdf is not None:
        rec["tounicode_fonts"] = _embed_tounicode(res.pdf)
    return rec


def base_condition(work: Path, eng_name: str, main_rel: str, timeout: float) -> dict:
    """跑 base 条件：不动源码直接编译+判定（管线引入 vs 原生失败的归因对照）。"""
    rec: dict[str, object] = {"engine": eng_name}
    job = _Job(work, main_rel, eng_name, timeout)
    tail, _res = _compile_judge(job, expect_cjk=False)
    rec.update(tail)
    return rec


def mock_pipeline_run(  # noqa: PLR0913 -- 同上：开关面穿透到 pipe_condition
    work: Path,
    engine_opt: str,
    timeout: float,
    *,
    translator: Translator | None = None,
    env_judge: bool | None = None,
    l2_on: bool | None = None,
    fixloop_on: bool | None = None,
    l2_max_chunks: int = L2_MAX_CHUNKS,
) -> dict:
    """工程目录上的 mock 全链（对齐 e2e_mock_bench 的 pipe 条件语义）。

    ``engine_opt``：``auto`` 取路由首选，或显式引擎名。返回结构化报告 dict
    （route/normalize/translate/inject/compile/verdict + 修复链 + 终态）。
    """
    report: dict[str, object] = {"work": str(work)}
    route = route_project(work)
    report["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
        "latex209_suspect": route.latex209_suspect,
    }
    if route.reject:
        report["status"] = "partial"  # 策略拒绝 → partial (F3), reject_at 审计
        report["reject_at"] = "route"
        return report
    main_path = find_main_tex(work)
    if main_path is None:
        report["status"] = "partial"
        report["reject_at"] = "route"
        report["route"]["reasons"] = [*route.reasons, "no main tex"]
        return report
    main_rel = main_path.relative_to(work).as_posix()
    report["main"] = main_rel

    eng_name = engine_opt if engine_opt != "auto" else route.engines[0]
    report.update(
        pipe_condition(
            work,
            eng_name,
            main_rel,
            timeout,
            translator=translator,
            env_judge=env_judge,
            l2_on=l2_on,
            fixloop_on=fixloop_on,
            l2_max_chunks=l2_max_chunks,
            route_engines=route.engines,
        )
    )
    return report
