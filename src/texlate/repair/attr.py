"""repair.attr — logfix 错误归因叶 (repair 拆分叶).

错误标记簇（``err_signature``/``err_signatures``/``err_signatures_text`` +
``_sig_*``/``_undef_cs_culprit`` 内部件）、log 解析入口 ``_log_parse``、
chunk 落盘区间 ``chunk_spans``、文件名 token 解算 ``_resolve_fidx``、
归因底账 ``LogAttr``（逐文件 文本/行偏移/chunk 区间三表 + ``attr_error``
归因阶梯）与顶面 ``_attr_localize``。

归因桶（infra/struct/filelevel）成员类别由 ``rules/10-taxonomy.yaml``
的类别 id 单源裁决——``_bucket_rx`` 惰性构建 arm pattern 并集 + 扁平
语义补遗 ``_*_EXTRA``。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from texlate.compile.fixloop.ruleset import RulesetError, load_ruleset
from texlate.latex.reconstruct import (
    SEQ_MARK_RX,
    _Expander,
    translation_tokens,
)
from texlate.texlog import log_text_of
from texlate.validate import logattr

if TYPE_CHECKING:
    from typing import Any

    from texlate.compile.engine import CompRes
    from texlate.latex.model import ScanResult
    from texlate.repair.runstate import TreeRun

log = logging.getLogger(__name__)

#: logfix 回灌默认每文档重译上限（spec ≤10，参数化入口 ``logfix_max_chunks``）
LOGFIX_MAX_CHUNKS = 10
#: 错误行 → 最近 chunk 的归因距离上限（字符）；超出按基建错处理，不耗 LLM
_ATTR_WINDOW = 4000
#: logfix 单次回灌最多消费的 log 错误条数
_ATTR_MAX_ERRORS = 50
#: 归因桶成员类别——桶归属由 ``rules/10-taxonomy.yaml`` 的类别 id 单源
#: 裁决：桶 regex = 成员类别全部 head-scope arm 的 pattern 并集 + 扁平
#: 语义补遗 ``_*_EXTRA``。taxonomy arm 增删自动汇流进桶——消灭旧
#: python 侧手抄标记表的「两侧对照同步」契约。收录判据「译文内容能否
#: 造成该类错」：
#:
#: - infra = 基建/资源缺——译文修不了，永不归块（重译造不出文件/选项/
#:   字体，归因只会白烧重译额度并把无辜块回退成原文——algpseudocodex
#:   未装实证 main.tex 4 块 file 级兜底全灭 → partial）。不收
#:   runaway_scan/soul_err/undefined_color/invalid_char/syntax/other
#:   ——译文可直接造成（幻觉 \cs、括号失衡、soul 内容敏感、色名污染、
#:   控制字符）；early_eof 是尾段收束行，混进他错 ctx 窗时豁免反误伤
#:   真错。旧侧 ``Fatal error occurred`` 收窄随单源化撤除——yaml
#:   ``Fatal error`` 裸臂在 fixloop ``classify_head`` 同 head+ctx 窗
#:   评估，归因口径与之对齐。
#: - struct = 结构位标记——报错行恒在块外结构位（env 标签/定义点），
#:   但译文可向块内注入字面 ``\begin{X}``/``\end{X}``/``\newcommand``
#:   幻觉：只认报错行严格含块内，nearest/文件级兜底都禁（revtex4-2
#:   abstract 仅 frontmatter 期 let-bound——兜底只会把错贴给邻近
#:   无辜块）。
#: - filelevel = 无行号错误的全块兜底白名单——只在「块内容确能致错」
#:   的标记上开火（undefined_cs 幻觉 \cs 无定位行、capacity 爆栈可由
#:   内容暴走）。其余无行号错误位置信息为零，全块归因只是扫射烧块
#:   ——不归因，留 fixloop。
_INFRA_CATS: frozenset[str] = frozenset(
    {
        "missing_file",
        "fontspec_missing",
        "missing_tfm",
        "missing_pfb",
        "xetexglyph_tfm",
        "ps_image",
        "missing_graphic",
        "inputenc_unicode",
        "latex209",
        "pkg_obsolete",
        "option_clash",
        "babel_opt",
        "babel_undef",
        "hyperref_driver",
        "float_opt",
        "pkg_order",
        "key_unknown",
        "cannot_patch_macro",
        "hyphenation",
        "illegal_unit",
        "pream_token",
        "invalid_in_math",
        "minted_froz",
        "toolchain_skew",
        "pkg_version_skew",
        "expl3_backend",
        "aux_scan_eof",
        "emergency",
    }
)
_STRUCT_CATS: frozenset[str] = frozenset(
    {"env_undefined", "env_mismatch", "already_def"}
)
_FILELEVEL_CATS: frozenset[str] = frozenset({"undefined_cs", "capacity"})

#: infra 扁平补遗——head-arm 并集覆盖不到的标记：tail-scope 措辞的扁平
#: 借用（``Enter file name``/求档 plea/``please update`` 在分类器里挂
#: ``guard``/``preempts`` 机关，归因闸只要「译文修不了」的平匹配）；
#: 折行 ``not\nfound``（yaml 臂字面空格不吃换行——路径串把标记顶过
#: 79 列是常态）；版本闸裸形（``Critical Package X Error: Your LaTeX
#: release is too old`` 两窄臂各要 file-line 前缀/版本措辞皆不沾）；
#: ``Illegal pream-token`` 无括号残形；ucs 头邻接 ``\pdf*`` 原语
#: （subclassify 的 payload 等值闸比归因豁免严——桶侧保守宽收）。
_INFRA_EXTRA = (
    r"Enter\s+file\s+name"
    r"|please\s+update\s+your\s+system"
    r"|(?:download|install|get|need)\s+\S+\.(?:cls|sty|clo|tex|def|fd|map|cfg)"
    r"|File\s+`[^']+\.[a-zA-Z0-9_]+'\s+not\s+found"
    r"|(?:Package|Class)\s+[\w@*+-]+\s+Error[\s\S]{0,600}?too\s+old"
    r"|Illegal\s+pream-token"
    r"|Undefined\s+control\s+sequence[^\n]*\n[^\n]*\\pdf[a-zA-Z@]+"
)
#: struct 补遗 = 桶契约自留的宽空白/折行容差形（严格含位判的白名单，
#: yaml 臂同标记但字面空格口径——桶侧保留原判容差）。
_STRUCT_EXTRA = (
    r"Environment\s+[A-Za-z@*]+\s+undefined"
    r"|begin\{[^}]*\}[^\n]*ended\s+by|Extra\s+\\end"
    r"|Command\s+[`']?\\?[\w@]+'?\s+already\s+defined"
    r"|Theorem\s+style\s+[\w@]+\s+already\s+defined"
)
#: filelevel 补遗 = runaway 族类目重映射（``Runaway argument``/
#: ``Paragraph ended``/``Forbidden control sequence`` 在 yaml 归 syntax
#: 词族，桶语义是「块内容能致错」白名单）+ 宽空白容差形。
_FILELEVEL_EXTRA = (
    r"Undefined\s+control\s+sequence"
    r"|Command\s+[`']?\\[\w@]+'?\s+undefined"
    r"|TeX\s+capacity\s+exceeded"
    r"|Runaway\s+argument|Paragraph\s+ended\s+before"
    r"|Forbidden\s+control\s+sequence"
)

_BUCKETS: dict[str, tuple[frozenset[str], str]] = {
    "infra": (_INFRA_CATS, _INFRA_EXTRA),
    "struct": (_STRUCT_CATS, _STRUCT_EXTRA),
    "filelevel": (_FILELEVEL_CATS, _FILELEVEL_EXTRA),
}
_BUCKET_RX_CACHE: dict[str, re.Pattern[str]] = {}
#: arm pattern 行首裸全局旗（``(?m)`` 形）——并集内须收编成作用域组
#: （``(?m:...)``），裸旗在 pattern 中位是 3.11+ 语法错，全局生效还会
#: 改并集里其他臂的 ``^`` 语义。
_ARM_FLAG_RX = re.compile(r"^\(\?([aiLmsux]+)\)")


def _bucket_rx(name: str) -> re.Pattern[str]:
    """桶 regex 惰性构建——ruleset 装载推迟到首个归因请求（import 期零 IO）。

    桶 = 成员类别全部 head-scope arm 的 pattern 并集（``use_pre``/
    ``use_post`` 臂的检索窗条件已编进 pattern 本体，扁平并集天然自门；
    行首裸旗逐臂收编成作用域组）+ 扁平语义补遗 ``_*_EXTRA``。成员类别
    在 taxonomy 缺席（改名/删除）即炸——单源契约的机器闸，不许静默
    脱钩。
    """
    if name in _BUCKET_RX_CACHE:
        return _BUCKET_RX_CACHE[name]
    cats, extra = _BUCKETS[name]
    tax = load_ruleset(tolerant=True).taxonomy
    missing = cats - {e.get("id") for e, _ in tax.head}
    if missing:
        msg = f"logfix 归因桶成员类别在 taxonomy 缺席: {sorted(missing)}"
        raise RulesetError(msg)
    scoped = [
        f"(?{m.group(1)}:{p[m.end() :]})" if (m := _ARM_FLAG_RX.match(p)) else p
        for e, _ in tax.head
        if e.get("id") in cats
        for p in (e["pattern"],)
    ]
    rx = re.compile(
        "|".join(scoped) + f"|{extra}",
        re.IGNORECASE,  # taxonomy head 臂同口径装载旗
    )
    _BUCKET_RX_CACHE[name] = rx
    return rx


#: ``Undefined control sequence`` 头标记——罪魁 cs 在 ctx 窗
#: （``<recently read> \cs`` 优先，``l.N \cs`` 行首回退）。
_UNDEF_CS_HEAD_RX = re.compile(r"Undefined control sequence")
_UNDEF_CS_CULPRIT_RXS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<\s*recently read\s*>\s*(\\[A-Za-z@]+|\\[^\sA-Za-z])"),
    re.compile(r"(?m)^\s*l\.\d+\s*(\\[A-Za-z@]+|\\[^\sA-Za-z])"),
)


def _undef_cs_culprit(err: logattr.LogError) -> str | None:
    r"""``Undefined control sequence`` 的肇事 cs 名（``\\rowcolor`` 形）。"""
    blob = "\n".join(err.ctx)
    for rx in _UNDEF_CS_CULPRIT_RXS:
        if m := rx.search(blob):
            return m.group(1)
    return None


def _sig_head(head: str) -> str:
    """标记化 head：去 ``!`` 前缀 + 空白塌缩 + 数字归一（行号跨构不稳定）。"""
    h = re.sub(r"\s+", " ", head.strip().lstrip("!").strip())
    return re.sub(r"\d+", "#", h)


def err_signature(err: logattr.LogError) -> str:
    r"""错误标记——en/zh 双编译间稳定（``head|culprit`` 形）。

    ``Undefined control sequence`` 头恒定、罪魁全在 ctx——标记键必须是
    cs 名而非裸 head（否则 en 任一 undefined_cs 会豁免 zh 全部同类，
    译文幻觉 ``\\cs`` 被误放）。其余类 head 自带区分度（包名/env 名/
    宏名在文内），culprit 位留空。
    """
    culprit = ""
    if _UNDEF_CS_HEAD_RX.search(err.head):
        culprit = _undef_cs_culprit(err) or ""
    return f"{_sig_head(err.head)}|{culprit}"


def _sig_set(verdict: logattr.LogVerdict) -> set[str]:
    """LogVerdict → 错误标记集（``log_missing``/无错 → 空集）。"""
    if verdict.log_missing or not verdict.errors:
        return set()
    return {err_signature(e) for e in verdict.errors}


def err_signatures(res: CompRes) -> set[str]:
    """CompRes → 错误标记集（en 基线快照——worker 原文编译后取）。

    标记在 en 侧出现 = 源生错（无译文时已犯）——zh 侧同标记错误不归
    chunk（logfix 归因面消费；基线缺席返回空集=无过滤）。
    """
    return err_signatures_text(log_text_of(res), project_root=res.workdir)


def err_signatures_text(log_text: str, *, project_root: Path | None = None) -> set[str]:
    """Log 文本 → 错误标记集——``build-en`` 残存 .log 回扫臂（resume 路径）。"""
    if not log_text:
        return set()
    return _sig_set(logattr.parse_log_text(log_text, project_root=project_root))


def _log_parse(res: CompRes) -> logattr.LogVerdict:
    """CompRes → LogVerdict：``texlog.log_text_of`` 全文 → ``parse_log_text``。

    被杀编译留 0 字节 ``.log``——``exists()`` 判据下 0 错返回 logfix 臂
    静默空转（``log_text_of`` 单源同口径：``.log`` 非空优先、缺席/
    空文件/读失败退 ``stdout_tail``，worker 共享本函数同愈）。
    """
    text = log_text_of(res)
    if text:
        return logattr.parse_log_text(text, project_root=res.workdir)
    return logattr.LogVerdict(log_missing=True)


def chunk_spans(
    text: str, res: ScanResult, trans: dict[int, str]
) -> dict[int, tuple[int, int] | None]:
    """各 chunk 在当前文件中的 ``[s, e)`` 区间（文档序贪心 find）。

    cjk_glue_fix 可能在译文里插空格 → find 失败的块给 ``None``，位置由
    前后块锚定（归因是启发式，丢块可接受）。展开走 ``reconstruct`` 同款
    ``_Expander``（``translation_tokens`` 映射 + ``short_arg`` 折叠 +
    ``seg_join`` 接缝守卫 + memo/环检全单源）——落盘字节镜像口径：
    缺这步 ``find`` 必对不上落盘字节，块在 logfix 二次归因里整片消失。
    本函数只服务译文落盘文件，``glue_latin`` 恒真。
    """
    ex = _Expander(res, translation_tokens(res, trans), glue_latin=True)
    spans: dict[int, tuple[int, int] | None] = {}
    cur = 0
    for c in res.chunks:
        # 走 token 入口——短参折叠只在 expand 见到 [[CHUNK_n]] 时发生（同 reconstruct）
        body = ex.expand(f"[[CHUNK_{c.id}]]")
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
class LogAttr:
    """logfix 归因底账：每文件 文本/行偏移/chunk 区间 三表（惰性建）。"""

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

    def attribute(
        self, fidx: int, tex_line: int, *, nearest: bool = True
    ) -> int | None:
        """行号 → 字节偏移 → 所在/最近 chunk.id。

        顺序读取不变量：TeX 报 ``l.NNN`` 时还没读到该行之后——起点落在
        错误行行尾之后的块不可能是肇事者（repro-2501：preamble 错被
        forward-fallback 错归给首个正文块）。runaway/EOF 类报的父文件
        续行位由 ``attr_error`` 的 ``eof_file`` 改派兜住，不经此路。
        ``nearest=False``（struct 桶标记类）关掉最近块兜底——
        结构标记报错行恒在块外，兜底只会把错贴给邻近无辜块。
        """
        offs = self.line_off[fidx]
        if not (1 <= tex_line <= len(offs) - 1):
            return None
        text = self.texts[fidx]
        off = offs[tex_line - 1]
        line_end = offs[tex_line]
        best_cid, best_gap = None, _ATTR_WINDOW + 1
        for cid, sp in self.spans[fidx].items():
            if sp is None:
                continue
            s, e = sp
            if s <= off < e:
                return cid
            # 行首到 span 起点仅 seq 锚/空白 = span 视同含行首：BDC 前缀把
            # span 起点推出 off，行错会被 forward-fallback 错贴给前块
            if off < s < line_end and not SEQ_MARK_RX.sub("", text[off:s]).strip():
                return cid
            if not nearest or s >= line_end:
                continue
            gap = max(s - off, off - e, 0)
            if gap < best_gap:
                best_cid, best_gap = cid, gap
        return best_cid if best_gap <= _ATTR_WINDOW else None

    def _cs_source_carried(self, fidx: int, cs: str, sres: ScanResult) -> bool:
        """肇事 cs 是否确证源携带（非译文引入）——undefined_cs 归因豁免判据。

        ① work 文本块外区出现 cs（块外 verbatim 复制源）→ 源携带；
        ② cs 全落块内 span → 块 ``content``（源文本）含之即源携带
        （LLM 保留原用法），不含即译文新造可归因；③ work 文本零出现
        判不可豁免（无法证伪译文引入，罕见展开生成件归 fixloop 面）。
        """
        text = self.texts[fidx]
        tail = r"(?![A-Za-z@])" if cs[-1:].isalpha() else ""
        found_in_span = False
        for m in re.finditer(re.escape(cs) + tail, text):
            pos = m.start()
            inside = any(
                sp is not None and sp[0] <= pos < sp[1]
                for sp in self.spans[fidx].values()
            )
            if not inside:
                return True
            found_in_span = True
        if not found_in_span:
            return False
        # 块源文本侧同套边界尾——裸子串会把 ``\foo`` 误判成 ``\foobar`` 源携带
        return any(
            re.search(re.escape(cs) + tail, c.content or "") is not None
            for c in sres.chunks
        )

    def attr_error(  # noqa: PLR0911 -- 归因阶梯：豁免→结构→eof→白名单逐档直铺
        self, err: logattr.LogError
    ) -> tuple[int, list[int]] | None:
        """单条 log 错误 → (fidx, chunk.id 列表)；不可归因 → None。"""
        blob = err.head + "\n" + "\n".join(err.ctx)
        # 基建/资源缺失错永不归译文块——修归 fixloop install/filemap/
        # toolchain 面；重译造不出 .sty/字体/图片，归了只会白烧块。
        if _bucket_rx("infra").search(blob):
            return None
        # 结构位标记：只认报错行严格含于某块的归因——兜底会误伤邻近块
        strict = _bucket_rx("struct").search(blob) is not None
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
        # undefined_cs 源内 cs 豁免：肇事 cs 是源携带的（块外 verbatim 区
        # 出现/块源文本含之/展开生成件）——未定义根因是装载期（包未载/
        # 选项丢失，xcolor[table] clash 丢 \rowcolor 实证），重译造不出
        # 定义，归块只会白烧额度 + 回退原文（2505.17508 表格 5 块实证）。
        if _UNDEF_CS_HEAD_RX.search(err.head):
            cs = _undef_cs_culprit(err)
            if cs is not None and self._cs_source_carried(fidx, cs, sres):
                return None
        if not eof and err.tex_line is not None:
            cid = self.attribute(fidx, err.tex_line, nearest=not strict)
            return (fidx, [cid] if cid is not None else [])
        if strict:
            return (fidx, [])  # 结构标记无可含位行 → 一切兜底都禁
        if eof and sres.chunks:
            if len(sres.chunks) <= LOGFIX_MAX_CHUNKS:
                return (fidx, [c.id for c in sres.chunks])
            return (fidx, [sres.chunks[-1].id])
        # 无行号文件级错误：白名单标记才允许全块兜底——其余类位置
        # 信息为零，全块归因是扫射烧块，不归因留 fixloop。
        if len(sres.chunks) <= LOGFIX_MAX_CHUNKS and _bucket_rx("filelevel").search(
            blob
        ):
            return (fidx, [c.id for c in sres.chunks])
        return (fidx, [])


def _attr_localize(
    work: Path,
    run: TreeRun,
    res: CompRes,
    *,
    baseline_sigs: set[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], int]:
    """编译 log → ``{chunk_id: {file,line,head}}`` 归因表 + 错误总数。

    定位链：``eof_file``（runaway/EOF 错——报位是父文件续行，改派 ``)``
    刚弹出的肇事文件，行号丢弃）> ``tex_file``（file:line: 格式）> 文件栈
    **最内层**（``l.NNN`` 只对 TeX 正在读的文件有意义——栈里更深的
    ``.sty``/``.cls`` 错是基建问题，不归 chunk）。``tex_line`` → 字节偏移
    → 所在 chunk；不在任何块内则取最近块（≤ ``_ATTR_WINDOW``，且起点
    越过错误行行尾的块被顺序读取不变量排除）。豁免先于归因：
    ``baseline_sigs`` 命中的 en 基线标记判源生不归块；infra 桶
    基建标记永不归块；undefined_cs 肇事 cs 在源 chunk 文本中同理豁免；
    struct 桶结构标记只认报错行严格含于块内（无最近块兜底/
    文件级兜底）；无行号错误走 filelevel 桶白名单才允许文件级
    全块归因（且 chunk 数 ≤ ``LOGFIX_MAX_CHUNKS``）。
    """
    verdict = _log_parse(res)
    if verdict.log_missing or not verdict.errors:
        return {}, verdict.n_errors
    errs = verdict.errors
    if baseline_sigs:
        errs = [e for e in errs if err_signature(e) not in baseline_sigs]
    st = LogAttr(run, work)
    hits: dict[str, dict[str, Any]] = {}
    for err in errs[:_ATTR_MAX_ERRORS]:
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
