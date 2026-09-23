"""L2 回灌 / env judge 簇——自 ``repair`` 拆出的编译失败归因修复机械。

C4 拆分（reaudit-2026-09-18）：``repair.py`` 收敛为 fixloop 包装/跨引擎
重试/glossary confine 纯低层件，本模块承载 L2 阶梯全实现——
``TreeRun``/``split_cid`` 运行态、env judge 可译性判定
（``_env_judge_one``/``env_judge_all`` + 目标谓词 ``unknown_env_of``）、
L2 回灌机械（``_l2_parse``/``chunk_spans``/``_resolve_fidx``/``L2Attr``/
``_l2_localize``/``retranslate_hits``/``_resplice_and_diffs``/
``l2_repair_round``）与配套开关/上限常量。

``repair`` 门面按全仓实测消费回引公共名——私名消费请从本模块直取
（B12 口径，不批发回引）。
"""

from __future__ import annotations

import logging
import re
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.compile.inject import InjectRejectError, prepare_chinese
from texlate.compile.judge import paired_slot_diff
from texlate.latex.reconstruct import (
    MARK_MOVING_UNSAFE_RX,
    _Expander,
    reconstruct,
    seq_mark_issues,
    strip_seq_marks,
    translation_tokens,
)
from texlate.latex.tables import (
    ARG_TRANSPARENT_ENVS,
    MATH_ENVS,
    PROTECTED_ENVS,
    VERBATIM_ENVS,
)
from texlate.repair import log_text_of
from texlate.textutil import env_flag, mask_tex
from texlate.textutil.osutil import (  # noqa: F401 -- env 名钉点回引（字面量单源在 osutil 注册表）
    ENV_ENV_JUDGE,
    ENV_NO_L2,
    ENV_NO_SEQ_MARKS,
)
from texlate.validate import l2 as l2_mod
from texlate.xlat import prompts as xlat_prompts

if TYPE_CHECKING:
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
#: 基建类错误签名——head+ctx 窗匹配（fixloop taxonomy ``scope:head``
#: 同口径；签名内空格一律 ``\s+``——79 列折行能把短语切进 ctx 行）。
#: 收录判据「译文内容是否可能造成该类错」：肇事者是环境/装载期
#: 机关/工具链/收束签名（缺 .sty/字体/图片、引擎能力墙、包版本与
#: 装载序机关、aux 回读劈断、Emergency 收束）而非译文内容——重译
#: 造不出文件/选项/字体，归因只会白烧重译额度并把无辜块回退成原文
#: （algpseudocodex 未装实证：main.tex 4 块 file 级兜底全灭 →
#: partial）。``Fatal error`` 收紧为 ``Fatal error occurred``——
#: head+ctx 窗比 fixloop 首错行宽，裸签会误中正文复述行
#: （"a fatal error in their proof" 类）。与 ``rules/10-taxonomy.yaml``
#: 的 missing_file/missing_tfm/missing_pfb/xetexglyph_tfm/
#: fontspec_missing/missing_graphic/ps_image/inputenc_unicode/latex209/
#: pkg_obsolete/option_clash/babel_opt/babel_undef/hyperref_driver/
#: float_opt/pkg_order/key_unknown/cannot_patch_macro/toolchain_skew/
#: pkg_version_skew/expl3_backend/aux_scan_eof/emergency/minted_froz/
#: hyphenation/illegal_unit/pream_token/invalid_in_math/pdftex_prim
#: 各段同源——两侧改动须对照同步。不收：undefined_cs（主战场，
#: already_def/env_* 见 ``_STRUCT_ERR_RX``）/runaway_scan/capacity/
#: soul_err/undefined_color/invalid_char/syntax/other——译文可直接
#: 造成（幻觉 \cs、括号失衡、soul 内容敏感、色名参槽污染、控制
#: 字符）；early_eof/``No pages of output`` 是尾段收束行，会混进
#: 其他错误的 ctx 窗，豁免反误伤真错，不收。
_INFRA_ERR_RX = re.compile(
    # —— 文件缺失（含 cls/sty 求档 plea 与交互缺件提示）——
    r"File\s+`[^']+\.[a-zA-Z0-9]+'\s+not\s+found"
    r"|I\s+can't\s+find\s+file\s+`[^']+'"
    r"|Cannot\s+find\s+the\s+file\s+[\w@.+-]+\.[a-zA-Z0-9]+"
    r"|Enter\s+file\s+name"
    r"|please\s+update\s+your\s+system"
    r"|(?:download|install|get|need)\s+\S+\.(?:cls|sty|clo|tex|def|fd|map|cfg)"
    # —— 字体/图片资源缺失 + 引擎能力墙 ——
    r"|Font\s+\\?\S*?=?\s*[\w-]+\s+at\s+[0-9.]+pt\s+not\s+loadable"
    r"|Metric\s+\(TFM\)\s+file"
    r"|Cannot\s+proceed\s+without\s+\.vf|physical\s+font"
    r"|Cannot\s+use\s+XeTeXglyph\s+with\s+\S+"
    r"|font\s+[“\"][^”\"]+[”\"]\s+cannot\s+be\s+found"
    r"|Unable\s+to\s+load\s+picture\s+or\s+PDF\s+file"
    r"|image\s+inclusion\s+failed\s+for"
    r"|PostScript\s+images\s+are\s+not\s+supported"
    # —— 装载期/preamble 机关：选项表、装载序、源代际、包自检 ——
    # （babel AtBeginDocument 钩/hyperref 驱动处理等常无 l.N 行号，
    # 是文件级兜底误伤重灾区）
    r"|inputenc\s+is\s+not\s+designed\s+for"
    r"|\\documentstyle\b|LaTeX\s+2\.09\s+COMPATIBILITY\s+MODE"
    r"|LaTeX2e\s+command[^\n]*\bin\s+LaTeX\s+2\.09|LaTeX\s+Version\s+2\.09"
    r"|(?m:^[ \t]*Compatibility\s+mode)"
    r"|Package\s+[`'][\w-]+'\s+is\s+obsolete"
    r"|Option\s+clash\s+for\s+package"
    r"|Package\s+babel\s+Error:\s+Unknown\s+(?:option|language)"
    r"|You\s+haven't\s+defined\s+the\s+language"
    r"|Wrong\s+(?:hyperref\s+driver|(?:DVI\s+mode\s+)?driver\s+option)"
    r"|Unknown\s+float\s+option"
    r"|Package\s+\w+\s+Error:\s+\w+\s+must\s+be\s+loaded\s+(?:before|after)"
    r"|The\s+key\s+'[\w@./-]+'\s+is\s+unknown\s+and\s+is\s+being\s+ignored"
    r"|Cannot\s+patch\s+(?:bibliography|citation)\s+macro"
    r"|Not\s+a\s+letter"
    r"|Illegal\s+unit\s+of\s+measure"
    r"|Illegal\s+pream-token"
    r"|frozencache|Cannot\s+highlight\s+code"
    # —— 工具链/版本错配 + 后端请求 ——
    r"|biblatex\s+control\s+file\s+version\s+[\d.]+,\s+expected\s+version\s+[\d.]+"
    r"|(?:Package|Class)\s+[\w@*+-]+\s+Error[\s\S]{0,600}?too\s+old"
    r"|Backend\s+request\s+inconsistent\s+with\s+engine"
    # —— 源级正文机关：报错行可落块内但重译修不了 ——
    # invalid_in_math 实证=natbib \@citex 未定义引用标记（gr-qc/9901082），
    # 报错位在 thebibliography 正文块内——块内可归位的典型陷阱；
    # pdftex_prim=undefined_cs 的 pdftex 原语子类（xelatex 能力墙）。
    r"|LaTeX\s+Error:\s+Command\s+\\[a-zA-Z@]+\s+invalid\s+in\s+math\s+mode"
    r"|Undefined\s+control\s+sequence[^\n]*\n[^\n]*\\pdf[a-zA-Z@]+"
    # —— aux 回读劈断（CJK 8192B 写缓冲实证——译文邻接但重译产同文
    # 再劈，本质不可由重译修）+ 收束签名 ——
    r"|File\s+ended\s+while\s+scanning\s+use\s+of\s+\\?@?(?:newl@?bel|writefile|contentsline)"
    r"|Emergency\s+stop|cannot\s+\\read|Fatal\s+error\s+occurred|job\s+aborted"
)
#: 结构位签名——报错行恒在块外结构位（env 标签/定义点），但译文
#: 可向块内注入字面 ``\begin{X}``/``\end{X}``/``\newcommand`` 幻觉。
#: 此类只认「报错行严格落在某块内」的含位归因（nearest-fallback 与
#: 文件级兜底都不许）：源级 cls/装载机关（revtex4-2 abstract 仅
#: frontmatter 期 let-bound 实证）走兜底只会把错贴给邻近无辜块；
#: 幻觉注入的报错行在块内，照常归因重译。与 taxonomy 的
#: env_undefined/env_mismatch/already_def 同源——两侧改动须对照
#: 同步。
_STRUCT_ERR_RX = re.compile(
    r"Environment\s+[A-Za-z@*]+\s+undefined"
    r"|begin\{[^}]*\}[^\n]*ended\s+by|Extra\s+\\end"
    r"|Command\s+[`']?\\?[\w@]+'?\s+already\s+defined"
    r"|Theorem\s+style\s+[\w@]+\s+already\s+defined"
)
#: 无行号错误的文件级兜底白名单——全块归因只在「块内容确能致错」
#: 的签名上开火：undefined_cs（译文幻觉 \cs 无定位行）、capacity
#: （爆栈可由内容暴走）、runaway/scanning 族（译文括号失衡/字面
#: \par）。其余无行号错误位置信息为零，全块归因只是扫射烧块
#: （algpseudocodex 同型毒化面）——不归因，留 fixloop 处理。
_FILELEVEL_ERR_RX = re.compile(
    r"Undefined\s+control\s+sequence"
    r"|Command\s+[`']?\\[\w@]+'?\s+undefined"
    r"|TeX\s+capacity\s+exceeded"
    r"|Runaway\s+argument|Paragraph\s+ended\s+before"
    r"|Forbidden\s+control\s+sequence"
)
#: ``Undefined control sequence`` 头签名——罪魁 cs 在 ctx 窗
#: （``<recently read> \cs`` 优先，``l.N \cs`` 行首回退）。
_UNDEF_CS_HEAD_RX = re.compile(r"Undefined control sequence")
_UNDEF_CS_CULPRIT_RXS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<\s*recently read\s*>\s*(\\[A-Za-z@]+|\\[^\sA-Za-z])"),
    re.compile(r"(?m)^\s*l\.\d+\s*(\\[A-Za-z@]+|\\[^\sA-Za-z])"),
)


def _undef_cs_culprit(err: l2_mod.LogError) -> str | None:
    r"""``Undefined control sequence`` 的肇事 cs 名（``\\rowcolor`` 形）。"""
    blob = "\n".join(err.ctx)
    for rx in _UNDEF_CS_CULPRIT_RXS:
        if m := rx.search(blob):
            return m.group(1)
    return None


def _sig_head(head: str) -> str:
    """签名化 head：去 ``!`` 前缀 + 空白塌缩 + 数字归一（行号跨构不稳定）。"""
    h = re.sub(r"\s+", " ", head.strip().lstrip("!").strip())
    return re.sub(r"\d+", "#", h)


def err_signature(err: l2_mod.LogError) -> str:
    r"""错误签名——en/zh 双编译间稳定（``head|culprit`` 形）。

    ``Undefined control sequence`` 头恒定、罪魁全在 ctx——签名键必须是
    cs 名而非裸 head（否则 en 任一 undefined_cs 会豁免 zh 全部同类，
    译文幻觉 ``\\cs`` 被误放）。其余类 head 自带区分度（包名/env 名/
    宏名在文内），culprit 位留空。
    """
    culprit = ""
    if _UNDEF_CS_HEAD_RX.search(err.head):
        culprit = _undef_cs_culprit(err) or ""
    return f"{_sig_head(err.head)}|{culprit}"


def _sig_set(verdict: l2_mod.L2Verdict) -> set[str]:
    """L2Verdict → 错误签名集（``log_missing``/无错 → 空集）。"""
    if verdict.log_missing or not verdict.errors:
        return set()
    return {err_signature(e) for e in verdict.errors}


def err_signatures(res: CompRes) -> set[str]:
    """CompRes → 错误签名集（en 基线快照——worker 原文编译后取）。

    签名在 en 侧出现 = 源生错（无译文时已犯）——zh 侧同签名错误不归
    chunk（L2 归因面消费；基线缺席返回空集=无过滤）。
    """
    return err_signatures_text(log_text_of(res), project_root=res.workdir)


def err_signatures_text(log_text: str, *, project_root: Path | None = None) -> set[str]:
    """Log 文本 → 错误签名集——``build-en`` 残存 .log 回扫臂（resume 路径）。"""
    if not log_text:
        return set()
    return _sig_set(l2_mod.parse_log_text(log_text, project_root=project_root))


#: env judge 输入截断（长 env 体只喂前 N 字符）
_ENV_JUDGE_MAX_CHARS = 2000
#: 环境开关名（``ENV_NO_L2``/``ENV_ENV_JUDGE``）本体注册在
#: ``textutil.osutil``——本模块同名回引保 ``repair_l2.ENV_*`` 钉点面

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
    """单 env 可译性判定（docs/spec/translate.md）：0 温/16 tok/3 试/解析失败 fail-open。"""
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
    """CompRes → L2Verdict：``repair.log_text_of`` 全文 → ``parse_log_text``。

    被杀编译留 0 字节 ``.log``——``exists()`` 判据下 0 错返回 L2 臂
    静默空转（``log_text_of`` 单源同口径：``.log`` 非空优先、缺席/
    空文件/读失败退 ``stdout_tail``，worker 共享本函数同愈）。
    """
    text = log_text_of(res)
    if text:
        return l2_mod.parse_log_text(text, project_root=res.workdir)
    return l2_mod.L2Verdict(log_missing=True)


def chunk_spans(
    text: str, res: ScanResult, trans: dict[int, str]
) -> dict[int, tuple[int, int] | None]:
    """各 chunk 在当前文件中的 ``[s, e)`` 区间（文档序贪心 find）。

    cjk_glue_fix 可能在译文里插空格 → find 失败的块给 ``None``，位置由
    前后块锚定（归因是启发式，丢块可接受）。展开走 ``reconstruct`` 同款
    ``_Expander``（``translation_tokens`` 映射 + ``short_arg`` 折叠 +
    ``seg_join`` 接缝守卫 + memo/环检全单源）——落盘字节镜像口径：
    缺这步 ``find`` 必对不上落盘字节，块在 L2 二次归因里整片消失。
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

    def attribute(
        self, fidx: int, tex_line: int, *, nearest: bool = True
    ) -> int | None:
        """行号 → 字节偏移 → 所在/最近 chunk.id。

        顺序读取不变量：TeX 报 ``l.NNN`` 时还没读到该行之后——起点落在
        错误行行尾之后的块不可能是肇事者（repro-2501：preamble 错被
        forward-fallback 错归给首个正文块）。runaway/EOF 类报的父文件
        续行位由 ``attr_error`` 的 ``eof_file`` 改派兜住，不经此路。
        ``nearest=False``（``_STRUCT_ERR_RX`` 签名类）关掉最近块兜底——
        结构签名报错行恒在块外，兜底只会把错贴给邻近无辜块。
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
            if not nearest or s >= line_end:
                continue
            gap = max(s - off, off - e, 0)
            if gap < best_gap:
                best_cid, best_gap = cid, gap
        return best_cid if best_gap <= _L2_ATTR_WINDOW else None

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
        self, err: l2_mod.LogError
    ) -> tuple[int, list[int]] | None:
        """单条 log 错误 → (fidx, chunk.id 列表)；不可归因 → None。"""
        blob = err.head + "\n" + "\n".join(err.ctx)
        # 基建/资源缺失错永不归译文块——修归 fixloop install/filemap/
        # toolchain 面；重译造不出 .sty/字体/图片，归了只会白烧块。
        if _INFRA_ERR_RX.search(blob):
            return None
        # 结构位签名：只认报错行严格含于某块的归因——兜底会误伤邻近块
        strict = _STRUCT_ERR_RX.search(blob) is not None
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
        # 定义，归块只会白烧额度+回退原文（2505.17508 表格 5 块实证）。
        if _UNDEF_CS_HEAD_RX.search(err.head):
            cs = _undef_cs_culprit(err)
            if cs is not None and self._cs_source_carried(fidx, cs, sres):
                return None
        if not eof and err.tex_line is not None:
            cid = self.attribute(fidx, err.tex_line, nearest=not strict)
            return (fidx, [cid] if cid is not None else [])
        if strict:
            return (fidx, [])  # 结构签名无可含位行 → 一切兜底都禁
        if eof and sres.chunks:
            if len(sres.chunks) <= L2_MAX_CHUNKS:
                return (fidx, [c.id for c in sres.chunks])
            return (fidx, [sres.chunks[-1].id])
        # 无行号文件级错误：白名单签名才允许全块兜底——其余类位置
        # 信息为零，全块归因是扫射烧块，不归因留 fixloop。
        if len(sres.chunks) <= L2_MAX_CHUNKS and _FILELEVEL_ERR_RX.search(blob):
            return (fidx, [c.id for c in sres.chunks])
        return (fidx, [])


def _l2_localize(
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
    → 所在 chunk；不在任何块内则取最近块（≤ ``_L2_ATTR_WINDOW``，且起点
    越过错误行行尾的块被顺序读取不变量排除）。豁免先于归因：
    ``baseline_sigs`` 命中的 en 基线签名判源生不归块；``_INFRA_ERR_RX``
    基建签名永不归块；undefined_cs 肇事 cs 在源 chunk 文本中同理豁免；
    ``_STRUCT_ERR_RX`` 结构签名只认报错行严格含于块内（无最近块兜底/
    文件级兜底）；无行号错误走 ``_FILELEVEL_ERR_RX`` 白名单才允许文件级
    全块归因（且 chunk 数 ≤ ``L2_MAX_CHUNKS``）。
    """
    verdict = _l2_parse(res)
    if verdict.log_missing or not verdict.errors:
        return {}, verdict.n_errors
    errs = verdict.errors
    if baseline_sigs:
        errs = [e for e in errs if err_signature(e) not in baseline_sigs]
    st = L2Attr(run, work)
    hits: dict[str, dict[str, Any]] = {}
    for err in errs[:_L2_MAX_ERRORS]:
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


def _resplice_and_diffs(  # noqa: PLR0913 -- 注入面穿透（写盘/diff/锚三臂缝）
    run: TreeRun,
    work: Path,
    main_rel: str,
    fidxs: set[int],
    *,
    diffs: bool = True,
    seq_marks: bool | None = None,
) -> tuple[list[str], dict[str, list[str]]]:
    """受影响文件 reconstruct 重写 + 写入即 ``paired_slot_diff`` 对账（单遍）。

    diff 取**注入前**在手 ``zh``——``res.vtex`` 对重建体的干净口径
    （``pipecore.translate_tree_run`` 同形）：主文件的 ``prepare_chinese``
    注入不污染 notes（旧盘后重读会把 demote/inject 改写面记成机位差）。
    ``prepare_chinese`` 重跑补 ctex 在全量写+diff 之后；注入后树级审计
    由 ``machine_slot_audit``（judge）覆盖。``diffs=False`` 跳过对账
    （``_resplice`` 写盘臂——调用方另走 ``_slot_diffs`` 盘后真值口径，
    在手 diff 算了也丢）。``seq_marks`` 三态：None → ``TEXLATE_NO_SEQ_MARKS``
    env 决议（缺省开）；重烘焙产物与 ``_build_zh`` 同 seq 口径
    （``sum(len(chunks) for j < fidx)`` 基址）自动补锚，失衡即剥降级。
    """
    marks_on = (
        not env_flag(ENV_NO_SEQ_MARKS, default=False)
        if seq_marks is None
        else seq_marks
    )
    moving_ok = marks_on and not MARK_MOVING_UNSAFE_RX.search(
        "\n".join(mask_tex(res.vtex) for _, res in run.scans)
    )
    main_path = work / main_rel
    rewritten: list[str] = []
    diff_map: dict[str, list[str]] = {}
    touched_main = False
    for fidx in sorted(fidxs):
        f, res = run.scans[fidx]
        seq0 = sum(len(run.scans[j][1].chunks) for j in range(fidx))
        zh = reconstruct(
            res,
            run.trans.get(fidx) or {},
            mark_seq0=seq0 if marks_on else None,
            mark_moving=moving_ok,
        )
        if marks_on and (issues := seq_mark_issues(zh)):
            log.warning("seq marks imbalanced in %s (%s); stripped", f, "; ".join(issues))
            zh = strip_seq_marks(zh)
        f.write_text(zh, encoding="utf-8")
        rel = f.relative_to(work).as_posix()
        rewritten.append(rel)
        if diffs and (notes := paired_slot_diff(res.vtex, zh, rel)):
            diff_map[rel] = notes
        touched_main = touched_main or f == main_path
    if touched_main:
        # 首注已过——同文件重注不会再触发 \documentstyle 拒绝
        with suppress(InjectRejectError):
            prepare_chinese(work, main_rel)
    return rewritten, diff_map


def _resplice(
    run: TreeRun,
    work: Path,
    main_rel: str,
    fidxs: set[int],
    *,
    seq_marks: bool | None = None,
) -> list[str]:
    """受影响文件 reconstruct 重写；主文件重跑 ``prepare_chinese`` 补 ctex。

    ``_resplice_and_diffs`` 的写盘臂（worker ``_retr_resplice`` 旧签名档——
    其 ``_slot_diffs`` 盘后读回保留注入后磁盘真值口径，在手 diff 臂
    ``diffs=False`` 跳过不算）。
    """
    return _resplice_and_diffs(
        run, work, main_rel, fidxs, diffs=False, seq_marks=seq_marks
    )[0]


def _slot_diffs(run: TreeRun, work: Path, fidxs: set[int]) -> dict[str, list[str]]:
    """``_resplice`` 落盘 zh 对 ``res.vtex`` 的机位配对 diff——重写后逐文件对账。

    盘后读回 = 注入后磁盘真值口径（worker ``_retr_resplice`` 消费位）；
    ``l2_repair_round`` 内面走 ``_resplice_and_diffs`` 的注入前在手 zh 口径。
    """
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
    baseline_sigs: set[str] | None = None,
    seq_marks: bool | None = None,
) -> tuple[dict[str, Any], CompRes, Verdict | None]:
    """L2 回灌一轮骨架：归因 → 重译 → resplice → 重编 → 余孽回落原文。

    ``retranslate``/``recompile`` 两臂注入——e2e 包 ``asyncio.run(
    retranslate_hits)`` + ``_compile_judge``（tail dict 臂侧合成）；
    worker 包 client aclose 同 loop 纪律 + ``eng.compile``+``judge``。
    ``checkpoint`` 是 cancel 轮询点（worker ``_abort_if_cancelled``
    同位三处：重译前/后、首编后），缺省无操作。
    ``baseline_sigs`` 是 en 基线错误签名集（``err_signatures`` 快照）——
    命中判源生错不进归因面；两轮 localize（首归因 + 重编后余孽检测）
    同口径过滤。``seq_marks`` 透传 ``_resplice_and_diffs``（None → env
    决议）。返回 (l2 报告, 最新 CompRes, 新 Verdict 或 None=未重编)。
    """
    rep: dict[str, Any] = {"enabled": True, "cap": cap}
    hits, n_err = _l2_localize(work, run, res, baseline_sigs=baseline_sigs)
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
    rep["rewritten"], diffs = _resplice_and_diffs(
        run, work, main_rel, fidxs, seq_marks=seq_marks
    )
    if diffs:
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
    hits2, _ = _l2_localize(work, run, res2, baseline_sigs=baseline_sigs)
    still_bad = sorted(set(hits2) & adopted)
    rep["fallback_src"] = still_bad
    rep["unresolved"] = sorted(set(hits2) - adopted)
    if still_bad:
        for cid in still_bad:
            fidx, ccid = split_cid(cid)
            run.trans.get(fidx, {}).pop(ccid, None)
        fb_fidxs = {split_cid(c)[0] for c in still_bad}
        rep["fallback_rewritten"], fb_diffs = _resplice_and_diffs(
            run, work, main_rel, fb_fidxs, seq_marks=seq_marks
        )
        if fb_diffs:
            rep["fallback_slot_diffs"] = fb_diffs
        # 回落态即交付树——补一次裸编：fixloop 关/崩/reject 时不再有
        # 代验兜底，zh-src.zip 不能装未验证树（audit fallback_unverified）
        res3, v3 = recompile()
        rep["fallback_verdict"] = v3.status
        last_res, v2 = res3, v3
    return rep, last_res, v2
