"""Engine — fixloop 规则引擎主循环 (docs/08 §5, bench/py/fixloop.py 移植)。

管线: ``eng.compile → parse_log → taxonomy.classify → gate → match → apply →
重编``, ≤``meta.loop.max_rounds`` 轮 (默认 8)。

与 ``compile/engine.py`` 的边界: 本模块只依赖 :class:`Engine` Protocol
(docs/08:198-225 签名), 不实现引擎 —— xelatex/tectonic 引擎由
impl-compile 并行开发, 结构上满足本 Protocol 即可对接。

phase 语义 (rules/ 分片注释复制):
  ``gate``     每轮分类后最先评估 (spike 里 latex209 硬编码短路, L748-755)
  ``precheck`` 编译前一次性 (静态路由 + 装包预检)
  ``loop``     每轮错误驱动; 同 phase 按 order 升序, 每轮至多一条成功应用

C2 拆分: 规则库装载/校验侧剥入 ``ruleset.py``, 动作解释器簇 (when/cond
评估 + action.kind 分派 + 依赖闭包 + _match_apply) 剥入 ``actions.py``;
本文件收敛为协议面 (CompResLike/Engine/RunFn/LlmHook) + LoopCtx + 引擎
适配辅助 + 主循环, 并门面回引两叶公共名保 ``engine.X`` import 面不变。
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from texlate.compile import ctan
from texlate.compile.fixloop._builtins_common import _mc_parse_log
from texlate.compile.fixloop._builtins_misc import (
    _wdir_fingerprint,
)
from texlate.compile.fixloop.actions import (
    _REJECT_PREFIX,
    _apply,
    _apply_scan_install,
    _cond_ok,
    _dep_stems,
    _is_misschar_rule,
    _match_apply,
    _probe,
    _substitute,
    _when_ok,
)
from texlate.compile.fixloop.logparse import (
    ErrReport,
    _is_runaway_output,
    parse_log,
    parse_text,
)
from texlate.compile.fixloop.ruleset import (
    RULES_PATH,
    Rule,
    Ruleset,
    RulesetError,
    load_ruleset,
)
from texlate.compile.inject import classify_no_main as _classify_no_main
from texlate.compile.inject import find_main_tex as _inject_find_main_tex
from texlate.texlog import driver_fatal_line
from texlate.textutil import DOCCLASS_RX, decode_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.cases import CaseSink

__all__ = [
    "RULES_PATH",
    "_REJECT_PREFIX",
    "Engine",
    "LlmHook",
    "LoopCtx",
    "Rule",
    "Ruleset",
    "RulesetError",
    "_apply",
    "_apply_scan_install",
    "_cond_ok",
    "_dep_stems",
    "_match_apply",
    "_probe",
    "_substitute",
    "_when_ok",
    "find_main_tex",
    "fixloop",
    "load_ruleset",
]


# ════════════════════════════════════════════════════════════════
# Engine 协议 (docs/08:198-225 逐字签名; impl-compile 的实现对接此处)
# ════════════════════════════════════════════════════════════════


class CompResLike(Protocol):
    """``Engine.compile`` 返回的结构化结果 (属性级 duck-typing)。

    对接 impl-compile ``compile/engine.py`` 的 ``CompRes`` (L139-178):
    ``pdf: Path|None`` + ``has_pdf`` + ``pdf_bytes`` + ``seconds`` +
    ``stdout_tail`` (tectonic 无 .log 兜底)。spike 时代字段名 ``sec``
    经 getattr 链兼容。
    """

    pdf: object  # Path | None | bool
    log_path: Path | None
    timed_out: bool
    seconds: float


class Engine(Protocol):
    """编译引擎适配层 —— xelatex/tectonic 各一实现 (impl-compile 侧)。

    与 impl ``Engine`` Protocol (compile/engine.py:183) 的调用面兼容:
    本模块只用 ``compile(wdir, main, passes=...)`` / ``probe_file(fname[, cwd])``
    / ``install_file(fname, font_related=...)`` / ``rebuild_fontmaps()`` /
    ``filemap(fname)`` 五个方法 + ``caps``。
    """

    caps: set[str] | frozenset[str]  # {kpsewhich,tlmgr,updmap,shell_escape,bundle}

    def compile(  # noqa: PLR0913  # 镜像 impl Engine.compile 调用面
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = 2,
        timeout: float = 240.0,  # 同 compile/engine.py DEFAULT_TIMEOUT
        flags: Iterable[str] | None = None,
        best_effort: bool = False,
    ) -> CompResLike:
        """沙箱编译 ``main`` (相对 wdir), ≤``passes`` 轮 → CompResLike。

        ``timeout`` = 单格编译预算秒 (fixloop 传 ``meta.loop.timeout_sec``
        或调用方覆盖); ``flags`` = ``ctx.ledger.engine_flags`` 累计的引擎 CLI
        flag —— 经 impl 侧 seam 落 argv；引擎不收的项进
        ``CompResLike.flags_dropped`` (getattr 容错读取)。
        """
        ...

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        """Kpsewhich | 本地+bundle 探测; 命中返路径, 缺返 None。

        ``cwd`` 可选 (impl 签名 ``probe_file(fname, *, cwd=None)``): 传 wdir
        时把"工程目录内已存在"也算命中 —— ctan_fetch 平铺落盘的复核靠它。
        """
        ...

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        """装提供 ``fname`` 的包: tlmgr --usermode | ctan_fetch 降级。"""
        ...

    def rebuild_fontmaps(self) -> None:
        """updmap-user | noop (tectonic)。"""
        ...

    def filemap(self, fname: str) -> list[str]:
        """file→TL 包索引: tlmgr search --file | tlpdb 表 → 候选包名。"""
        ...


RunFn = Callable[..., tuple[int | None, str, float, bool | str]]
LlmHook = Callable[["LoopCtx", "ErrReport"], tuple[bool, str]]


# ── Engine 适配辅助 (impl-compile CompRes/Engine 的字段名差分吸收) ──


def _res_has_pdf(res: CompResLike) -> bool:
    """Pdf 产出判定: impl ``has_pdf`` (非空文件) 优先, 否则 pdf 字段真值。"""
    hp = getattr(res, "has_pdf", None)
    # 鸭子实现若把 has_pdf 写成方法而非 property，bound method 恒真——调用之
    if hp is not None:
        return bool(hp() if callable(hp) else hp)
    return bool(getattr(res, "pdf", False))


def _res_driver_fatal(res: CompResLike) -> str | None:
    r"""``res`` 的下游驱动 fatal 证据行（无则 None）——``_driver_fatal`` 鸭形对版。

    证据 = ``stdout_tail`` 有 ``*: fatal:`` 签名行 ∧ 编译呈失败相
    （``killed_signal`` 置位 / ``rc`` 非零 / 无 pdf）——``fatal:`` 字面
    行单有不足采：``\\write18`` 类孙件 fatal 可被主进程恢复，rc=0 且
    出 pdf 按 impl 侧同一契约不算驱动死。
    """
    line = driver_fatal_line(getattr(res, "stdout_tail", "") or "")
    if line is None:
        return None
    if getattr(res, "killed_signal", None) is not None:
        return line
    rc = getattr(res, "rc", None)
    if rc is not None and rc != 0:
        return line
    if not _res_has_pdf(res):
        return line
    return None


def _res_died(res: CompResLike) -> bool:
    r"""编译非正常跑完 (超时 killpg / 信号截杀 / 驱动 fatal) —— 死产出不证 clean。

    gr-qc/0104075 实证: ``\\output`` 死循环烧满 240s SIGKILL 留下 0 错
    log + 残 pdf, 裸 ``pdf and nerr==0`` 门把它判成 clean 又让后续臂
    白烧一轮满超时——被杀编译对正确性零证明, clean 判定必须否决。
    1907.00277 第二形态: xdvipdfmx ``pdf_link_obj`` fatal → xelatex
    rc=1 非信号退出, ``killed_signal`` 全程空, .log 零 ``!`` 错照出
    908KB 残 pdf——驱动死与被杀同属产出未证, 并否 clean。
    """
    return (
        bool(getattr(res, "timed_out", False))
        or getattr(res, "killed_signal", None) is not None
        or _res_driver_fatal(res) is not None
    )


def _round_cat(
    rs: Ruleset, rep: ErrReport, res: CompResLike
) -> tuple[str | None, str | None]:
    r"""轮内 ``(category, payload)`` —— 死编译否决 clean 类。

    活哨截杀留有行程内原因 (``sentry_reason`` 显式字段, 或未经归位的
    str 形 ``timed_out``) —— 记录值优先于文本重扫, 直归 ``runaway_output``,
    ``sentry:<arm>`` 挂 payload 槽回吐 (镜像 judge ``_timeout_verdict``
    的 notes 形; 轮内无 notes 面, payload 即轮次归因载体, 落
    ``entry["payload"]``/事件行 ``pay=`` 可查); 洪前有可分类首错时
    payload 追加 ``|<cat>``, 底层机理随归因可查。无记录原因的超时由
    ``Taxonomy.classify`` 直出 ``timeout``/``runaway_output`` —— 内部已扫
    ``rep.raw`` (= ``_report_of`` 喂入的 .log 全文, 与 judge
    ``_full_log_text`` 同源), 判泛 ``timeout`` 再补查 ``stdout_tail``;
    信号死 (非超时——外部截杀/驱动 SIGPIPE) 只在裸分类给 clean/None
    时改写: log 被 ``\\output`` 期 Overfull ``\\vbox`` 刷屏归
    ``runaway_output``, 否则 ``killed``。驱动 fatal 同位再一层:
    ``*: fatal:`` 签名 + 失败相 (rc 非零/无 pdf) 时归 ``driver_fatal``
    (1907.00277 rc=1 + 残 pdf 形——非信号死, killed 臂够不到)。
    注意主面不进本臂: ``_report_of`` 已把 fatal 行归一成 ``!`` →
    classify 出 ``other`` 供 ``when: category: other`` 修复规则
    (pdf_asset_sanitize) 派发; 本臂只兜 taxonomy 漏给 clean/None
    的残余边, 防驱动死判 clean。
    真错类照常走修复规则——信号死是非定败, 轮内重编即续趟通道
    (2211.13013 实证可救)。
    """
    timed_out = getattr(res, "timed_out", False)
    sentry_reason = getattr(res, "sentry_reason", None)
    if sentry_reason is None and isinstance(timed_out, str):
        sentry_reason = timed_out
    if sentry_reason is not None:
        pay = f"sentry:{sentry_reason}"
        if rep.first:
            # 洪前首错类追加 payload——runaway_output 标签不遮蔽底层可修
            # 机理（killsem2：2311.04163 洪上游是 fixable undefined_cs）。
            head = rs.taxonomy.classify_head(
                rep.first, rep.ctx, pre=rep.pre, post=rep.post
            )
            if head is not None and head[0]:
                pay += f"|{head[0]}"
        return "runaway_output", pay
    cat, pay = rs.taxonomy.classify(rep, timed_out=bool(timed_out))
    if cat == "timeout" and _is_runaway_output(getattr(res, "stdout_tail", "") or ""):
        # 活哨早杀的编译 .log 截断在签名刷屏之前——证据在 stdout_tail
        # （哨件正是凭它越阈），补查使归因仍是 runaway_output 而非泛 timeout。
        cat, pay = "runaway_output", None
    if cat in (None, "clean") and not timed_out:
        if getattr(res, "killed_signal", None) is not None:
            if _is_runaway_output(rep.raw or rep.tail):
                return "runaway_output", None
            return "killed", None
        fatal = _res_driver_fatal(res)
        if fatal is not None:
            return "driver_fatal", fatal
    return cat, pay


def _note_dropped_flags(ctx: LoopCtx, res: CompResLike) -> None:
    """引擎经 ``flags`` seam 丢回的项 → ctx.ledger.flags_dropped + advisory (每 flag 一次)。"""
    for fl in getattr(res, "flags_dropped", None) or []:
        if fl not in ctx.ledger.flags_dropped:
            ctx.ledger.flags_dropped.append(fl)
            ctx.ledger.advisories.append(
                f"engine flag unsupported on {ctx.deps.engine_name}: {fl}"
            )


#: TeX 每轮重写的读回辅助件 —— 被杀/超时编译留下截断形 (``\citation{``
#: 半行) 驻留 wdir 即毒化后续一切 compile ("File ended while scanning
#: use of \citation"; 1511.06744 实证, 既有 aux_scan_eof 签名盖不住
#: \citation 形态)。删可再生件代价至多一遍重排; .bbl/.ind/.bcf 可为
#: e-print 船货 (bbl_regen 靠它), 不在此表。
_AUX_WRITE_EXTS = frozenset(
    {".aux", ".toc", ".lof", ".lot", ".out", ".nav", ".snm", ".vrb"}
)


_LBRACE, _RBRACE, _BSLASH = ord("{"), ord("}"), ord("\\")


def _aux_file_bad(f: Path) -> bool:
    r"""截断辅助件判定: EOF 无尾换行 (半路断行) 或全文花括号不闭合。

    行界齐整的早夭 (尾部整行丢失) 不算毒——缺行重排自生; 毒在断开
    的命令。``\{``/``\}`` 转义不计深; ``\\{`` 极小样本误删健康件
    的代价至多一遍重排, 不腐蚀语义。
    """
    try:
        data = f.read_bytes()
    except OSError:
        return False
    if not data:
        return False
    if not data.endswith(b"\n"):
        return True
    depth = 0
    prev = -1
    for b in data:
        if b == _LBRACE and prev != _BSLASH:
            depth += 1
        elif b == _RBRACE and prev != _BSLASH and depth:
            depth -= 1
        prev = b
    return depth != 0


def _sweep_bad_aux(wdir: Path) -> list[str]:
    """删 wdir 内截断辅助件 (aux/toc/out 族), 返回删除的相对名供审计。"""
    dropped: list[str] = []
    for f in wdir.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in _AUX_WRITE_EXTS:
            continue
        if not _aux_file_bad(f):
            continue
        try:
            f.unlink()
        except OSError:
            continue
        dropped.append(str(f.relative_to(wdir)))
    return dropped


#: 进程内 ``_texts`` 缓存对 TeX 每轮重写/清场件不安全: compile 落盘
#: 重写 ``{stem}.log``/``.aux`` 族、aux-sweep 删截断件, 缓存照供旧文,
#: 扫 log/aux 的下游规则吃残影 (2403.00013 实证: r1 早读 ``{stem}.log``
#: 缓存 → r2 全部 misschar/font 规则在 pre-fix log 上判 "no Missing
#: character" 拒修)。``.bbl``/``.bcf`` 可为 e-print 船货且不由 tex
#: compile 重写, 不入此集——biber/docstrip 类 run_tool 产物由各调用
#: 方自行 ``ctx.invalidate`` (bib_regen/docstrip 先例)。循环内每个
#: ``eng.compile`` 后必失效此集 (含探针与兜底臂, 幂等)。
_VOLATILE_EXTS = _AUX_WRITE_EXTS | {".log"}


#: REJECT note 里的 ``route=<name>`` 令牌——``reject_route``/route 语义型
#: builtin (plain_format_detect/biber_biblatex_skew_route) 同一拼写约定；
#: 提出后落 ``cell["reject_route"]`` 供跨引擎臂消费（repair.consume_engine_flags）。
_REJECT_ROUTE_RE = re.compile(r"\broute=(\S+)")


def _note_route(note: str) -> str | None:
    """REJECT note → 目标路由名；无 route 令牌 → None。"""
    m = _REJECT_ROUTE_RE.search(note)
    return m.group(1) if m else None


def _report_of(
    res: CompResLike,
    warn_patterns: list[dict[str, Any]],
    project_root: Path | None = None,
) -> ErrReport:
    """CompRes → ErrReport: 优先 .log 文件; 缺席/空错误时 stdout_tail 兜底。

    tectonic 有时不写 .log (impl engine.py:1083-1090、:1146-1150 同策略); stderr 的
    ``error: msg`` 行归一成 ``! msg`` 喂同一套 taxonomy。下游驱动
    ``<tool>:fatal:`` 行 (xdvipdfmx 等) 同归一 —— 与 judge 侧
    ``_salvage_driver_fatal`` 同词素双臂: xelatex 被驱动 fatal 的 SIGPIPE
    带走时签名只存于 stdout_tail (.log 干净), 不捞则 ``pdf_link_obj`` 类
    签名对整个条件面不可见 (2403.05523 实证)。

    ``project_root`` = ``wdir``: 输入侧警告 (``_FILE_ATTRIBUTED_WARNS``)
    按文件栈归因——sys 件命中降 ``rep.warnings_sys`` 不再驱动 ``warn_*``。
    """
    log_path = getattr(res, "log_path", None)
    # CompRes.log_text = 引擎编译期已读的 .log 原文 —— 复用免二次开文件
    # (B14 fix#10); 假值 (老调用方/test double 不填) 走原文件读路径。
    text = getattr(res, "log_text", "") or ""
    if text:
        rep = parse_text(text, warn_patterns, project_root=project_root)
    else:
        rep = parse_log(
            Path(log_path) if log_path else None,
            warn_patterns,
            project_root=project_root,
        )
    if rep.n_bang == 0:
        tail = getattr(res, "stdout_tail", "") or ""
        if tail:
            norm = re.sub(r"(?m)^error:\s*", "! ", tail)
            norm = re.sub(r"(?m)^\s*(\w+:\s*fatal:)", r"! \1", norm)
            alt = parse_text(norm, warn_patterns, project_root=project_root)
            if alt.n_bang or rep.raw == "":
                rep = alt
    return rep


# ════════════════════════════════════════════════════════════════
# LoopCtx —— 每格运行上下文 (spike Ctx, L133-143)
#
# C4 分组: 平铺 grab-bag 拆为四个子 dataclass —— ``io`` 工程 io 面 /
# ``deps`` 注入依赖 / ``round`` 本轮分类态 / ``ledger`` 跨轮账簿。
# 旧平铺字段名经 ``__getattr__``/``__setattr__`` 全量转落分组存储:
# builtins/actions/llm_hook 与各测试的 ``ctx.<field>`` 读写面零迁移。
# ════════════════════════════════════════════════════════════════


@dataclass
class _CtxIO:
    """工程 io 面: 工作目录 + 主文件相对路径 + 进程内文本缓存。"""

    wdir: Path
    main_rel: str | None = None
    _texts: dict[Path, str | None] = field(default_factory=dict, repr=False)
    #: 本派发窗内 ``ctx.write`` 经手写件集 —— 窗开始处清零 (集差分认不出
    #: 对既有件的重写, run 级积累会把规则自改误判成外部落件); 落件同步
    #: 区分规则自改 (经缓存的 accounted 写) 与外部落件 (install/run_tool
    #: 裸写, 绕过 ``_texts``) 用。
    written: set[Path] = field(default_factory=set, repr=False)


@dataclass
class _CtxDeps:
    """注入依赖: 引擎名 + 外部工具 runner (测试注入点) + LLM 修复钩子。"""

    engine_name: str
    runner: RunFn | None = None
    llm_hook: LlmHook | None = None


@dataclass
class _CtxRound:
    """本轮分类/裁决态 —— 主循环每轮重写, 轮间不累计。"""

    #: 本轮 taxonomy 分类结果 —— llm_hook 的 prompt 装配读这两个字段
    #: (LlmHook 签名固定 (ctx, rep), cat/pay 经 ctx 传递)。
    err_cat: str | None = None
    err_pay: str | None = None
    err_head: str = ""  # 本轮错误 blob (ctx_suggests 条件用)
    #: 本轮编译 log 的 missing-char 码位集 (``_mc_parse_log`` 同口径,
    #: nullfont 已滤)——error-cat 轮照记 (缺字警告与 ``!`` 错可同现,
    #: ``warn_missing_char`` 类别排他使族臂平时够不到这些轮)。
    mc_cps: frozenset[int] = frozenset()

    def point(self, cat: str | None, pay: str | None, rep: ErrReport) -> None:
        """重指当前派发目标 (主错/孪生): err_cat/err_pay/err_head 同写。

        三字段的派发语义一体 (when 匹配读 cat/pay, ctx_suggests/llm_hook
        读 head)——主循环与次级派发共用同一写点, 免分点写字段漂移
        (写 head 忘写 pay 类)。err_head 恒为 ``rep.first + rep.ctx``
        单行推导——公式单源在此, 调用点不再各开一行拼接。
        """
        self.err_cat, self.err_pay = cat, pay
        self.err_head = (rep.first or "") + "\n" + (rep.ctx or "")


@dataclass
class _CtxLedger:
    """跨轮累计账簿: 规则应用/动作/装包/事件/引擎 flag/拒修与建议记录。"""

    applied: set[str] = field(default_factory=set)  # "{rule_id}:{payload}"
    #: 缺字族臂已消费码位账: ``{rule_id: {cp, ...}}``——臂**起火轮**看见
    #: 的全集记其名下 (declined 不记——未消费的码位后浪重评估仍合法);
    #: dedup 豁免按 ``mc_cps - mc_seen[rid]`` 增量判 (missdisp #189:
    #: fired_late_surface——``\bibitem`` 细空格/.bbl 字形/cs_rebind
    #: 重音后浪浮新码位, "fired" 不得把起火后才浮出的码位记消费)。
    mc_seen: dict[str, set[int]] = field(default_factory=dict)
    #: "看见但拒修" 记录面: when 命中后 cond-skip/applied=False 的 ``{id}: {why}``
    #: ——events 有但 cases.jsonl 不落, 这里单收一份供 records 物化。
    declined: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    installed: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    engine_flags: list[str] = field(default_factory=list)
    #: 经 ``compile(flags=…)`` seam 被引擎拒放的 flag（支持子集外）——
    #: 每 flag 记一次 advisory，cell 落 ``engine_flags_dropped``。
    flags_dropped: list[str] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)


#: 平铺字段名 → 所属分组: LoopCtx facade 经此表把 ``ctx.<field>`` 读写
#: 转落 ``ctx.<group>.<field>`` —— 兼容面整体保留, 新代码直用分组路径。
_CTX_FIELD_GROUP = {
    "wdir": "io",
    "main_rel": "io",
    "_texts": "io",
    "engine_name": "deps",
    "runner": "deps",
    "llm_hook": "deps",
    "err_cat": "round",
    "err_pay": "round",
    "err_head": "round",
    "mc_cps": "round",
    "applied": "ledger",
    "declined": "ledger",
    "mc_seen": "ledger",
    "actions": "ledger",
    "installed": "ledger",
    "events": "ledger",
    "engine_flags": "ledger",
    "flags_dropped": "ledger",
    "advisories": "ledger",
}


@dataclass(init=False)
class LoopCtx:
    """单格 fixloop 的运行上下文: io/deps/round/ledger 四组状态。

    构造签名逐参复刻旧平铺 dataclass 生成面; 旧字段名全量保留为
    facade —— 读 ``ctx.<field>`` = ``ctx.<group>.<field>``, 写同理转落
    (field→group 归属见 ``_CTX_FIELD_GROUP``)。
    """

    io: _CtxIO
    deps: _CtxDeps
    round: _CtxRound
    ledger: _CtxLedger

    def __init__(  # noqa: PLR0913, PLR0917  # 签名逐参复刻旧 dataclass 生成面
        self,
        wdir: Path,
        engine_name: str,
        main_rel: str | None = None,
        applied: set[str] | None = None,
        declined: list[str] | None = None,
        actions: list[dict[str, Any]] | None = None,
        installed: list[str] | None = None,
        events: list[str] | None = None,
        engine_flags: list[str] | None = None,
        flags_dropped: list[str] | None = None,
        advisories: list[str] | None = None,
        runner: RunFn | None = None,
        llm_hook: LlmHook | None = None,
        err_cat: str | None = None,
        err_pay: str | None = None,
        err_head: str = "",
        mc_cps: frozenset[int] = frozenset(),
        mc_seen: dict[str, set[int]] | None = None,
        _texts: dict[Path, str | None] | None = None,
    ) -> None:
        """平铺 kwargs → 四组子对象; ``None`` = 该组字段取默认值。"""
        self.io = _CtxIO(
            wdir=wdir,
            main_rel=main_rel,
            _texts=_texts if _texts is not None else {},
        )
        self.deps = _CtxDeps(engine_name=engine_name, runner=runner, llm_hook=llm_hook)
        self.round = _CtxRound(
            err_cat=err_cat,
            err_pay=err_pay,
            err_head=err_head,
            mc_cps=mc_cps,
        )
        self.ledger = _CtxLedger(
            applied=applied if applied is not None else set(),
            declined=declined if declined is not None else [],
            mc_seen=mc_seen if mc_seen is not None else {},
            actions=actions if actions is not None else [],
            installed=installed if installed is not None else [],
            events=events if events is not None else [],
            engine_flags=engine_flags if engine_flags is not None else [],
            flags_dropped=flags_dropped if flags_dropped is not None else [],
            advisories=advisories if advisories is not None else [],
        )

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 -- 平铺转发面天然 Any
        """平铺字段名 → 分组存储转读 (facade; 只兜真实属性查找失败的名)。"""
        group = _CTX_FIELD_GROUP.get(name)
        if group is None:
            raise AttributeError(name)
        return getattr(getattr(self, group), name)

    def __setattr__(self, name: str, value: Any) -> None:  # noqa: ANN401
        """平铺字段名赋值 → 分组存储转写 (facade; 组名自身直挂实例)。"""
        group = _CTX_FIELD_GROUP.get(name)
        if group is None:
            object.__setattr__(self, name, value)
        else:
            setattr(getattr(self, group), name, value)

    def tex_files(self, exts: Iterable[str] = (".tex", ".sty", ".cls")) -> list[Path]:
        """工程内指定扩展名文件 (排序稳定)。"""
        exts_t = tuple(e.lower() for e in exts)
        return [
            p
            for p in sorted(self.io.wdir.rglob("*"))
            if p.suffix.lower() in exts_t and p.is_file()
        ]

    def read(self, f: Path) -> str | None:
        """utf-8 读文件 (进程内缓存, errors=replace); 不可读 → None。"""
        texts = self.io._texts  # noqa: SLF001  # 组内缓存直读 (facade ``_texts`` 转读亦达, 省逐次 __getattr__ 一跳)
        if f not in texts:
            try:
                texts[f] = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                texts[f] = None
        return texts[f]

    def write(self, f: Path, text: str) -> None:
        """utf-8 写文件并同步缓存。"""
        f.write_text(text, encoding="utf-8")
        self.io._texts[f] = text  # noqa: SLF001  # 组内缓存同步
        self.io.written.add(f)

    def invalidate(self, f: Path) -> None:
        """外部改写过 (如字节级转码) 后失效缓存。"""
        self.io._texts.pop(f, None)  # noqa: SLF001

    def invalidate_suffixes(self, exts: Iterable[str]) -> int:
        """按扩展名集批量失效缓存条目 (compile/sweep 改盘件), 返回失效数。"""
        exts_t = {e.lower() for e in exts}
        keys = [p for p in self.io._texts if p.suffix.lower() in exts_t]  # noqa: SLF001
        for f in keys:
            self.io._texts.pop(f, None)  # noqa: SLF001
        return len(keys)

    def main_path(self) -> Path | None:
        """主文件绝对路径 (main_rel 未定 → None)。"""
        return self.io.wdir / self.io.main_rel if self.io.main_rel else None

    def main_head(self, n: int = 3000) -> str:
        r"""主文件前 n 字符 (spike L515 用 3000 判 \documentstyle)。"""
        main = self.main_path()
        if main is None:
            return ""
        return (self.read(main) or "")[:n]

    def source_blob(self) -> str:
        """全部 tex 源拼接 (source_contains 条件用)。"""
        return "\n".join(t for f in self.tex_files() if (t := self.read(f)))

    def run_tool(
        self, argv: list[str], timeout: int = 120
    ) -> tuple[int | None, str, bool | str]:
        """跑外部工具; 默认 subprocess (测试注入 runner)。"""
        if self.deps.runner:
            _rc, out, _sec, to = self.deps.runner(argv, timeout, self.io.wdir)
            return _rc, out, to
        try:
            p = subprocess.run(  # noqa: S603  # argv 列表无 shell; fixloop 动作原语
                argv,
                cwd=str(self.io.wdir),
                timeout=timeout,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            out = e.stdout or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            return None, out, True
        except OSError as e:
            return None, f"{type(e).__name__}: {e}", False
        return p.returncode, p.stdout, False


# ════════════════════════════════════════════════════════════════
# 主循环 (spike run_cell L691-792 + docs/08:295-310 伪码)
# ════════════════════════════════════════════════════════════════

#: 次级错误派发 (twinhead) 每格 best_effort 探针编译上限——xelatex
#: halt_on_error 单错 log 看不见孪生错, 规则 miss 时跑一发 nonstop
#: 探针取全错误面 (与 salvage 同参, 结果直接留给兜底复用, 净零编译)。
_SEC_PROBE_MAX = 2
#: 单次 miss 最多尝试的次级候选数——dedupe 后保错误序截前 4。
_SEC_CAND_MAX = 4


def find_main_tex(proj: Path) -> Path | None:
    r"""主文件定位：先严格档后宽松档。

    严格档 = ``inject.find_main_tex``（注释遮盖 + 语种排序）；无命中退
    宽松档——``\documentclass|style`` 在即可（fixloop 的职责是修坏论文，
    ``\begin{document}`` 缺失正是要修的对象；spike L575-587 口径保留）。
    """
    strict = _inject_find_main_tex(proj)
    if strict is not None:
        return strict
    cands = []
    for f in sorted(f for f in proj.rglob("*") if f.suffix.lower() == ".tex"):
        with contextlib.suppress(OSError):
            head = decode_tex(f.read_bytes())[:60000]
            if DOCCLASS_RX.search(head):
                has_body = "\\begin{document}" in head
                depth = len(f.relative_to(proj).parts)
                cands.append((depth, 0 if has_body else 1, str(f)))
    if not cands:
        return None
    cands.sort()
    return Path(cands[0][2])


def _landing_sync(
    ctx: LoopCtx,
    before: dict[Path, tuple[int, int]],
    pre_applied: set[str],
) -> int:
    """动作落件同步: 外部落件指纹 diff → ``_texts`` 失效 + 落件前烧键过期。

    规则动作可改写盘面 (``scan_install``/``install_file``/vendored 落件、
    ``run_tool``/docstrip 产物、builtin 直写)。``written`` 在派发窗开始
    时清空, 窗内经 ``ctx.write`` 落账的写件即本窗自产编辑; ``before``
    基线后的变化件分两档:

      - **规则自改** —— ``written`` 在账的 ``ctx.write`` 改写/新建
        (regex_rewrite/站点前置/shim 新建件): 写件已在 ``_texts`` 同步,
        键面不动——派发链的自产编辑不该稀释 dedup (stucksem 实证: 无
        差别过期会让先火规则非幂等重派, 抢走凭据门后位规则的派发窗)。
      - **外部落件** —— 绕 ``ctx.write`` 的新件/改写/删除 (install/
        vendor/run_tool 裸写): 全 invalidate (覆盖写与 miss→None 毒化
        条目同 logcache 病族, 下轮 ``ctx.read``/site-map 读新文), 并把
        ``pre_applied`` 基线前烧录的 ``{rule}:{pay}`` dedup 键整体过
        期——落件把新站点引进 fileset 后, 同签轮应允许同规则重派
        (defcensus E-route 病族: mid-loop install 后 already_def 臂
        按旧烧键跳过, 残签滞留)。基线后新烧键 (``applied - pre_applied``)
        保留——刚派发的规则不因自身落件立刻重派。

    返回外部落件数 (0 = 无外部落件, 键面不动)。
    """
    after = _wdir_fingerprint(ctx.io.wdir)
    authored = ctx.io.written
    external = [
        p
        for p in set(before) | set(after)
        if before.get(p) != after.get(p) and p not in authored
    ]
    for p in external:
        ctx.invalidate(p)
    if not external:
        return 0
    ctx.ledger.applied.intersection_update(ctx.ledger.applied - pre_applied)
    ctx.ledger.events.append(
        f"landing sync: {len(external)} external landing(s) — "
        "pre-landing dedup keys expired"
    )
    return len(external)


def _match_apply_landing(  # noqa: PLR0913, PLR0917  # 与 _match_apply 同签名面
    rs: Ruleset,
    ctx: LoopCtx,
    eng: Engine,
    cat: str | None,
    pay: str | None,
    rep: ErrReport,
    only: Callable[[Rule], bool] | None = None,
) -> tuple[Rule | None, str]:
    """``_match_apply`` + 落件同步——loop 相两处派发点共用。"""
    before = _wdir_fingerprint(ctx.io.wdir)
    pre = set(ctx.ledger.applied)
    ctx.io.written.clear()  # 本窗自产写从零计账
    rule, note = _match_apply(rs, ctx, eng, cat, pay, rep, only=only)
    _landing_sync(ctx, before, pre)
    return rule, note


def _gate_eval(  # noqa: PLR0913, PLR0917  # 与 _match_apply 同签名面
    rs: Ruleset,
    ctx: LoopCtx,
    eng: Engine,
    cat: str | None,
    pay: str | None,
    rep: ErrReport,
) -> tuple[str | None, str | None]:
    """Gate phase 规则逐条评估; REJECT note → ``(reject:<rid>, route)``。

    route 令牌在持有 note 的决策点即取即返 (``_precheck_phase`` 同一返回
    通道)——不再经 ``ctx.round`` 过桥 (旧 ``reject_route`` 字段是
    verdict-only 返回值时代的影子通道, 已删)。
    """
    for rule in rs.phase("gate"):
        key = f"{rule.id}:{pay}"
        if key in ctx.ledger.applied:  # 非 REJECT 型 gate 已应用过 → 不重发不重记账
            continue
        if not _when_ok(rule.when, cat, pay, ctx):
            continue
        spec = rule.engine_spec(ctx.deps.engine_name)
        if spec.get("mode") == "skip":
            continue
        ok, why = _cond_ok(rule.condition, rule, ctx, eng, pay)
        if not ok:
            ctx.ledger.events.append(f"gate {rule.id}: cond skip ({why})")
            continue
        before = _wdir_fingerprint(ctx.io.wdir)
        pre = set(ctx.ledger.applied)
        ctx.io.written.clear()
        try:
            applied, note = _apply(rule, ctx, eng, pay, rep)
        except Exception as e:  # noqa: BLE001
            applied, note = False, f"gate crashed: {type(e).__name__}: {e}"
        _landing_sync(ctx, before, pre)
        if applied and note.startswith(_REJECT_PREFIX):
            return f"reject:{rule.id}", _note_route(note)
        if applied:
            ctx.ledger.applied.add(key)
            ctx.ledger.actions.append({"round": -1, "rule": rule.id, "detail": note})
    return None, None


def _warn_family_due(
    rs: Ruleset, ctx: LoopCtx, cat: str | None, pay: str | None
) -> bool:
    """接受裁决前的缺字族勤勉检: 本轮残存 missing-char 码位有臂未见。

    「未见」双判缺一不可——``when`` 不匹配本轮 cat 的臂本轮根本没被
    评估 (error-cat 轮全族皆然, ``invalid_in_math`` 轮只
    macro_glyph_fix 评估过); 残存码位落在臂 ``mc_seen`` 消费账外
    (never-fired ⇒ 账空 ⇒ 全集皆增量)。两条件同假的臂重扫同一
    rep 必同判, 不算 due。``(cat, pay)`` 取调用方快照——派发窗内
    ``ctx.round`` 已被强指 ``warn_missing_char``, 原 cat 须外传入。
    """
    cps = ctx.round.mc_cps
    if not cps:
        return False
    for rule in rs.phase("loop"):
        if not _is_misschar_rule(rule):
            continue
        if _when_ok(rule.when, cat, pay, ctx):
            continue  # 本轮已在该 cat 下评估过此臂——同 rep 重扫是空转
        if cps - ctx.ledger.mc_seen.get(rule.id, frozenset()):
            return True
    return False


def _warn_preempt(
    rs: Ruleset, ctx: LoopCtx, eng: Engine, rep: ErrReport
) -> tuple[Rule | None, str]:
    """Warn 家族补发一轮派发 (error-cat 轮裁决点/loop 退出点两 site 共用)。

    ``ctx.round`` 暂指 ``warn_missing_char`` 让族臂 ``when`` 命中——与
    次级错误派发的 twin 重指同机制, 返回后复元。``(None, "")`` =
    残存缺字各臂均见过 (或本无缺字), 直走原裁决; REJECT note 经
    ``note`` 原样冒泡由调用方落 ``reject:<rid>``。码位面 = 轮记
    ``mc_cps`` ∪ 派发 rep 实解——次级探针编译后盘上 .log 是探针全
    错误面, 族臂 apply 读的是它, 勤勉判据须同面 (``mc_seen`` 起火
    记账亦落此并集)。
    """
    eff = ctx.round.mc_cps | frozenset(_mc_parse_log(rep.raw or ""))
    if not eff:
        return None, ""
    cat, pay = ctx.round.err_cat, ctx.round.err_pay
    keep_cps = ctx.round.mc_cps
    ctx.round.err_cat, ctx.round.err_pay = "warn_missing_char", None
    ctx.round.mc_cps = eff
    try:
        if not _warn_family_due(rs, ctx, cat, pay):
            return None, ""
        rule, note = _match_apply_landing(
            rs, ctx, eng, "warn_missing_char", None, rep, only=_is_misschar_rule
        )
    finally:
        ctx.round.err_cat, ctx.round.err_pay = cat, pay
        ctx.round.mc_cps = keep_cps
    if rule is None:
        ctx.ledger.events.append(
            f"warn-preempt: {len(eff)} residual cps, no arm applied"
        )
    return rule, note


def _wire_filemap_overrides(
    eng: Engine, overrides: dict[str, Any], ctx: LoopCtx
) -> None:
    """``eng.filemap`` 实例遮蔽: basename 先过手工映射, 未中走原查询。

    xelatex 通路 ``install_file``/``_filemap_candidates`` 共用 ``self.filemap``
    —— 单点遮蔽即全通路生效 (bench 现场 ``eng.filemap = idx.query`` 的既有
    遮蔽也照包, 次序 = overrides → 既有查询; worker 的 ``_RecEngine`` 与
    bench 的 ``_NoSandbox`` 均 ``__setattr__`` 透传, 遮蔽落在真引擎实例上)。
    显式 null = 已知噪声 → 空表短路, 不再落 tlmgr/索引往返。
    """
    orig = getattr(eng, "filemap", None)
    if not callable(orig) or getattr(orig, "overrides_wrapped", False):
        return

    def filemap(fname: str) -> list[str]:
        if fname in overrides:
            v = overrides[fname]
            return [v] if isinstance(v, str) else []
        return list(orig(fname))

    filemap.overrides_wrapped = True  # type: ignore[attr-defined]  # 幂等: 重入不叠包
    try:
        eng.filemap = filemap  # type: ignore[method-assign]  # 实例遮蔽协议方法
    except Exception as e:  # noqa: BLE001  # 遮蔽失败不阻塞: 退化为原生 filemap
        ctx.ledger.advisories.append(
            f"filemap overrides wire failed: {type(e).__name__}: {e}"
        )
    else:
        ctx.ledger.events.append("wire filemap overrides")


def _wire_engine(eng: Engine, rs: Ruleset, wdir: Path, ctx: LoopCtx) -> None:
    """引擎侧降级原语注入 (docs/08 §5.3)。

    ``filemap.overrides`` 手工映射对全引擎生效 (实例遮蔽 ``eng.filemap``);
    tectonic 追加: ``install_file`` 内部走 ``self.ctan_fetch`` callable ——
    未注入时这里装上 CtanFetcher (惰性 tlpdb 索引 + rules/
    ``filemap.version_guard`` 的 bundle epoch 接线)。
    """
    _wire_filemap_overrides(eng, rs.filemap_cfg.get("overrides") or {}, ctx)
    # texmfhome 缺省时 ``tlmgr --usermode install`` 落 kpathsea 默认 ~/texmf
    # ——全局可见树，跨跑污染 base 对照线（modec-rerun 实证：youngtab.sty 进
    # ~/texmf 后 1306.1931 base 臂 fail→clean 假象）。装包隔离到任务树内。
    if getattr(eng, "texmfhome", "unset") is None:
        eng.texmfhome = wdir / "_texmf"  # type: ignore[attr-defined]
        ctx.ledger.events.append("wire texmfhome -> workdir _texmf")
    if ctx.deps.engine_name != "tectonic":
        return
    if getattr(eng, "ctan_fetch", None) is not None or not hasattr(eng, "ctan_fetch"):
        return
    vg = rs.filemap_cfg.get("version_guard") or {}
    try:
        eng.ctan_fetch = ctan.CtanFetcher(
            wdir,
            overrides=rs.filemap_cfg.get("overrides") or {},
            epoch=(str(vg["texlive_format_epoch"]) if vg.get("enabled") else None),
        )
        ctx.ledger.events.append("wire ctan_fetch (lazy tlpdb index)")
    except Exception as e:  # noqa: BLE001  # 注入失败不阻塞: install_* 走 advisory
        ctx.ledger.advisories.append(f"ctan_fetch wire failed: {type(e).__name__}: {e}")


def _precheck_phase(
    rs: Ruleset, ctx: LoopCtx, eng: Engine
) -> tuple[str | None, str | None]:
    """Precheck 相逐规则评估 (第 0 招装包 + 静态路由)。

    全程不编译——规则面是 scan_install/builtin_transform 等增量件，
    对 resplice 安全 (改件不碰 .tex 源)。REJECT note →
    ``(reject:<rid>, route)``；跑完无拒绝 → ``(None, None)``。
    """
    dummy_rep = parse_log(None, rs.warn_patterns)
    for rule in rs.phase("precheck"):
        if not _when_ok(rule.when, None, None, ctx):
            continue
        spec = rule.engine_spec(ctx.deps.engine_name)
        mode = spec.get("mode")
        if mode in ("skip", "unsupported") or (
            mode == "degrade" and spec.get("degrade") == "skip"
        ):
            ctx.ledger.events.append(
                f"precheck {rule.id}: {mode} on {ctx.deps.engine_name}"
            )
            continue
        ok, why = _cond_ok(rule.condition, rule, ctx, eng, None)
        if not ok:
            ctx.ledger.events.append(f"precheck {rule.id}: cond skip ({why})")
            continue
        before = _wdir_fingerprint(ctx.io.wdir)
        pre = set(ctx.ledger.applied)
        ctx.io.written.clear()
        try:
            applied, note = _apply(rule, ctx, eng, None, dummy_rep)
        except Exception as e:  # noqa: BLE001
            applied, note = False, f"precheck crashed: {type(e).__name__}: {e}"
        _landing_sync(ctx, before, pre)
        ctx.ledger.actions.append(
            {"round": 0, "rule": rule.id, "detail": note, "applied": applied}
        )
        if applied and note.startswith(_REJECT_PREFIX):
            return f"reject:{rule.id}", _note_route(note)
    return None, None


def precheck_pass(  # noqa: PLR0913 -- 与 fixloop 同契约的注入面
    proj: Path | str,
    eng: Engine,
    *,
    ruleset: Ruleset | None = None,
    engine_name: str | None = None,
    main_rel: str | None = None,
    runner: RunFn | None = None,
) -> dict[str, Any]:
    """编译链前的静态预检——fixloop precheck 相的独立入口。

    与 ``fixloop()`` 内嵌预检同一 ``_precheck_phase``：装缺包/解嵌套
    tar/收割构建指令，不修 .tex 源，对 L2 resplice 安全。e2e/worker
    两臂在 L2 回灌前调它——缺件类失败在归因前就消掉 (algpseudocodex
    型 missing_file 不再进 L2 兜底面)。

    ``main_rel`` 缺省时 ``find_main_tex`` 宽松档推导；无主档置空串
    （预检的 source_contains/扫描原语只读工程树，不依赖主档存在）。
    """
    rs = ruleset or Ruleset.load(tolerant=True)
    engine_name = engine_name or getattr(
        eng, "name", rs.meta.get("engine_default", "xelatex")
    )
    wdir = Path(proj)
    if main_rel is None:
        main = find_main_tex(wdir)
        main_rel = str(main.relative_to(wdir)) if main is not None else ""
    ctx = LoopCtx(wdir=wdir, engine_name=engine_name, main_rel=main_rel, runner=runner)
    ctx.ledger.advisories.extend(rs.skipped_rules)
    _wire_engine(eng, rs, wdir, ctx)
    verdict, route = _precheck_phase(rs, ctx, eng)
    pre = {
        "actions": ctx.ledger.actions,
        "installed": ctx.ledger.installed,
        "engine_flags": [str(f) for f in ctx.ledger.engine_flags],
        "flags_dropped": ctx.ledger.flags_dropped,
        "advisories": ctx.ledger.advisories,
        "events": ctx.ledger.events,
        "verdict": verdict,
        "reject_route": route,
    }
    pre["gate_fired"] = _gate_fired_of(pre)
    return pre


def fixloop(  # noqa: C901, PLR0912, PLR0913, PLR0915  # 主循环分支即 spike 状态机
    proj: Path | str,
    eng: Engine,
    *,
    ruleset: Ruleset | None = None,
    engine_name: str | None = None,
    main_rel: str | None = None,
    corpus_id: str | None = None,
    cond: str | None = None,
    llm_hook: LlmHook | None = None,
    runner: RunFn | None = None,
    case_sink: CaseSink | None = None,
    compile_timeout: float | None = None,
    should_cancel: Callable[[], bool] | None = None,
    on_round: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """跑一格修复循环 → cell dict (字段与 spike fixloop-results.json 兼容)。

    verdict ∈ clean / acceptable_pdf / dirty_pdf / best_effort_pdf /
    unfixable:<cat> / stuck / max_rounds / reject:<rid> /
    no_errors_no_pdf / no_main_tex[:<sub>]（``classify_no_main`` 细分）

    ``main_rel`` 缺省时 ``find_main_tex`` 双档推导；调用方持有正确主档
    时显式传入（译后 splice 树的语种重排会让 ``language_rank`` 把
    CJK 主档输给 standalone 英文档——ds209diag #191 实证 4 格误选）。
    指定档缺件/指树外则回退自动探测，落 ``cell["main_fallback"]`` 留痕；
    ``cell["main"]`` 恒记实效主档。

    ``on_round`` 可选逐轮回调：每轮 ``cell["rounds"]`` 落新 entry 即同步
    调用（含 salvage 兜底轮），entry 与 cell 内同对象——server worker
    借此发 SSE 实况帧；None 时零开销，e2e/bench 直调臂行为不变。
    """
    rs = ruleset or Ruleset.load(tolerant=True)
    engine_name = engine_name or getattr(
        eng, "name", rs.meta.get("engine_default", "xelatex")
    )
    wdir = Path(proj)
    cfg = rs.loop_cfg
    max_rounds = int(cfg.get("max_rounds", 8))
    clean_err_max = int(cfg.get("clean_err_max", 3))
    passes = int(cfg.get("compile_passes", 2))
    stuck_n = int(cfg.get("stuck_sig_repeat", 3))
    # 重编超时: 参数 > meta.loop.timeout_sec > 引擎缺省 (None = 不透传)
    if compile_timeout is not None:
        timeout = float(compile_timeout)
    elif cfg.get("timeout_sec") is not None:
        timeout = float(cfg["timeout_sec"])
    else:
        timeout = None
    compile_kw: dict[str, Any] = {}
    if timeout is not None:
        compile_kw["timeout"] = timeout

    cell: dict[str, Any] = {
        "project": corpus_id or wdir.name,
        "cond": cond,
        "main": None,
        "engine": engine_name,
        "rounds": [],
        "actions": [],
        "verdict": None,
        # reject 决策名单: gate/loop 相 REJECT 不经 actions 列 (precheck 相
        # append 在先判 REJECT 在后, 双栖) —— 单列物化, 不混 rules_fired
        # 的修复语义, verdict ``reject:<rid>`` 的结构化面。
        "gate_fired": [],
        "floor_restored": False,
        # 调用方指定主档缺件/树外时的回退留痕——None = 无回退发生
        "main_fallback": None,
    }
    ctx = LoopCtx(wdir=wdir, engine_name=engine_name, runner=runner, llm_hook=llm_hook)
    ctx.ledger.advisories.extend(rs.skipped_rules)

    main: Path | None = None
    if main_rel is not None:
        cand = wdir / main_rel
        # 树外引用 (绝对路径/.. 逃逸) 与缺件同档处理——主档必须在工程树内
        if cand.is_file() and cand.resolve().is_relative_to(wdir.resolve()):
            main = cand
        else:
            cell["main_fallback"] = main_rel
            ctx.ledger.advisories.append(
                f"main_rel {main_rel} not in tree; fell back to find_main_tex"
            )
    if main is None:
        main = find_main_tex(wdir)
    if main is None:
        sub = _classify_no_main(wdir)
        cell["verdict"] = f"no_main_tex:{sub}" if sub else "no_main_tex"
        _record_case(
            case_sink, cell, corpus_id=corpus_id, cond=cond, engine_name=engine_name
        )
        return cell
    ctx.io.main_rel = str(main.relative_to(wdir))
    cell["main"] = ctx.io.main_rel
    cell["actions"] = ctx.ledger.actions  # 同一 list: precheck/gate/loop 动作汇入一处
    _wire_engine(eng, rs, wdir, ctx)

    # —— 不退化底板: 快照入口态 PDF ——
    # 先于 precheck/loop 一切编辑: 规则若把能出 pdf 的树打死, finalize 拷回
    # 入口产物兜底 (loop1 实证 partial→fail 真退化 4 格)。reject:* 不救。
    main_pdf = wdir / Path(ctx.io.main_rel).with_suffix(".pdf")
    floor_snap: Path | None = None
    if main_pdf.is_file() and main_pdf.stat().st_size > 0:
        snap = wdir / ".fixloop-entry.pdf"
        try:
            shutil.copy2(main_pdf, snap)
            floor_snap = snap
        except OSError as e:  # 快照失败仅失底板, 不阻塞修复
            ctx.ledger.advisories.append(f"floor snapshot: {e}")

    # —— precheck phase (第 0 招; 静态路由也在这里) ——
    p_verdict, p_route = _precheck_phase(rs, ctx, eng)
    if p_verdict is not None:
        cell["verdict"] = p_verdict
        cell["gate_fired"] = _gate_fired_of(cell)
        if p_route:
            cell["reject_route"] = p_route
        _record_case(
            case_sink, cell, corpus_id=corpus_id, cond=cond, engine_name=engine_name
        )
        return cell

    prev_sig, sig_n = "", 0
    last_rep: ErrReport | None = None
    sec_probes = 0  # 次级派发探针计数 (≤_SEC_PROBE_MAX/格)
    #: 上次探针时的 actions 计数——树无 apply 变化不重探 (重探=同 log 同候选)
    sec_probe_mark = -1
    #: 探针编译留给 salvage 兜底复用的槽——只在「探针同轮、无 apply、走向
    #: 裁决」时填入 (miss 块内探针→候选全灭→break 是原子序, 天然新鲜)。
    salvage_res: CompResLike | None = None
    salvage_rep: ErrReport | None = None
    for rnd in range(1, max_rounds + 1):
        if should_cancel is not None and should_cancel():
            raise asyncio.CancelledError
        swept = _sweep_bad_aux(wdir)
        if swept:
            ctx.ledger.events.append(f"r{rnd} aux-sweep: {', '.join(swept)}")
        res = eng.compile(
            wdir,
            ctx.io.main_rel,
            passes=1,  # 分类轮只读 pass-1 log——第二遍不产新分类信号
            flags=list(ctx.ledger.engine_flags),
            **compile_kw,
        )
        ctx.invalidate_suffixes(_VOLATILE_EXTS)
        _note_dropped_flags(ctx, res)
        rep = _report_of(res, rs.warn_patterns, wdir)
        cat, pay = _round_cat(rs, rep, res)
        round_sec = float(getattr(res, "seconds", getattr(res, "sec", 0.0)))
        if (  # pass-1 判收敛 → 同轮全遍终编定稿: rungen_stub 类机制靠
            # 第二遍 \write 填实成品; 复编重分类回流下方同一决策面,
            # pass-2-emergent 错照常进 gate/修复路径。tectonic 自定遍数
            # (impl del passes)、死编译轮不升遍——超时重跑大概率再超时;
            # 信号死 (xdvipdfmx SIGPIPE 截杀等) 产出未证且 aux 可正被截
            # 在半行, 同轮重编即吃毒件造 aux_scan_eof 幻影 (2403.05523
            # 实证, 与 :905 clean 门同一 _res_died 否决语义)。
            passes > 1
            and engine_name != "tectonic"
            and not _res_died(res)
            and _res_has_pdf(res)
            and rep.n_bang == 0
            and cat not in rs.taxonomy.warn_cats
        ):
            res = eng.compile(
                wdir,
                ctx.io.main_rel,
                # yaml ``compile_passes`` 权威依旧: >1 才进本臂; 值 ≤2 时传
                # ``None`` 走引擎自适应门 (rerun-hint 才升遍, MAX_PASSES=2
                # 同值), >2 是超自适应上限的显式诉求, 原样透传无条件执行。
                passes=None if passes <= 2 else passes,  # noqa: PLR2004 - 2 = compile/engine.py MAX_PASSES 自适应上限
                flags=list(ctx.ledger.engine_flags),
                **compile_kw,
            )
            ctx.invalidate_suffixes(_VOLATILE_EXTS)
            _note_dropped_flags(ctx, res)
            rep = _report_of(res, rs.warn_patterns, wdir)
            cat, pay = _round_cat(rs, rep, res)
            round_sec += float(getattr(res, "seconds", getattr(res, "sec", 0.0)))
            ctx.ledger.events.append(
                f"r{rnd} finalize: pass-1 clean → {passes}-pass "
                f"(pdf={_res_has_pdf(res)} err={rep.n_bang} cat={cat})"
            )
        last_rep = rep
        ctx.round.point(cat, pay, rep)
        # 本轮 missing-char 码位面 (error-cat 轮同记)——缺字族 dedup
        # 增量豁免与 warn-preempt 勤勉闸的判据底账。
        ctx.round.mc_cps = (
            frozenset(_mc_parse_log(rep.raw or ""))
            if "missing_char" in rep.warnings
            else frozenset()
        )
        pdf = _res_has_pdf(res)
        pdf_bytes = getattr(res, "pdf_bytes", None)
        if pdf and pdf_bytes is None:
            pdf_attr = getattr(res, "pdf", None)
            try:
                pdf_bytes = Path(pdf_attr).stat().st_size if pdf_attr else 0
            except (OSError, TypeError):
                pdf_bytes = 0
        entry = {
            "round": rnd,
            "pdf": pdf,
            "pdf_bytes": int(pdf_bytes or 0),
            # 超时/被杀轮——死编译产出未证，汇总段 clean/acceptable 判据须查。
            "died": _res_died(res),
            # 驱动 fatal 证据行（无则 None）——category 仍押 classify 的
            # "other" 面（pdf_asset_sanitize 等 ``when: category: other``
            # 规则靠它派发），本字段载精确归因 + salvage 定败排除闸。
            "driver_fatal": _res_driver_fatal(res),
            "n_errors": rep.n_bang,
            "category": cat,
            "payload": pay,
            "warnings": list(rep.warnings),
            # 系统源输入侧警告 (``<warn_id>@<file>``)——不驱 warn_* 但留
            # 归因证据供 census 对账 (loginfo warnings_sys 同形)。
            "warnings_sys": list(rep.warnings_sys),
            "line_no": rep.line_no,
            "file_stack": rep.file_stack,
            "sec": round(round_sec, 1),
        }
        cell["rounds"].append(entry)
        ctx.ledger.events.append(
            f"r{rnd}: pdf={pdf} err={rep.n_bang} cat={cat} pay={pay} ({entry['sec']}s)"
        )
        if on_round is not None:
            on_round(entry)
        if floor_snap is None and pdf:  # 入口无现存产物 → 快照首轮 pdf
            src = getattr(res, "pdf", None)
            if isinstance(src, Path):
                snap = wdir / ".fixloop-entry.pdf"
                try:
                    shutil.copy2(src, snap)
                    floor_snap = snap
                except OSError as e:
                    ctx.ledger.advisories.append(f"floor snapshot: {e}")
        # —— 终止判据 (spike L742-761 + docs/08:312) ——
        if (
            pdf
            and rep.n_bang == 0
            and cat not in rs.taxonomy.warn_cats
            and not _res_died(res)  # 被杀/超时编译产 pdf 也不证 clean
        ):
            # spike 首门 `pdf and nerr==0 → clean`; v1.1 放行 warn_* 伪类别
            # 让 warning 驱动的修复轮有机会跑 (non_utf8_source)
            cell["verdict"] = "clean"
            break
        if cat in (None, "clean"):
            cell["verdict"] = "clean" if pdf else "no_errors_no_pdf"
            break
        v, route = _gate_eval(rs, ctx, eng, cat, pay, rep)
        if v:
            cell["verdict"] = v
            if route:
                cell["reject_route"] = route
            break
        sig = f"{cat}:{pay}"
        sig_n = sig_n + 1 if sig == prev_sig else 1
        prev_sig = sig
        # sig_n = 同签连续 streak——只记账不判负: stuck verdict 移到下方
        # 派发耗尽点结算 (streak≥stuck_n 且本轮无 apply), 同签后位规则
        # 不再被「第 N 轮先判 stuck」抢掉派发窗口。
        # —— loop 规则匹配 + 应用 ——
        rule, note = _match_apply_landing(rs, ctx, eng, cat, pay, rep)
        sec_via: str | None = None
        if rule is None:
            # 次级错误派发 (twinhead): 首错无规则可修时, 同 log 后续错误行
            # 可能才载可修根因 (1206.0291: syntax 首错遮蔽 option_clash 孪生,
            # geometry_hoist 永远够不到)。候选源 ``rep.errs`` 全错误表
            # (n_bang≥2, tectonic continue_on_errors 下免费); xelatex
            # halt_on_error 单错 log 无孪生——未产 pdf 且探针预算未尽时
            # 跑一发 best_effort 探针编译 (与 salvage 同参), 在其全错误
            # 面上取候选; 探针结果留给下方兜底 pass 复用, 净零编译。
            probe_res: CompResLike | None = None
            probe_rep: ErrReport | None = None
            cand_rep = rep
            if (
                rep.n_bang < 2  # noqa: PLR2004 - 2=单错→多错阈; log 已有全错误面 → 免费候选, 不烧探针
                and getattr(eng, "halt_on_error", False)
                and not pdf  # dirty-pdf miss 只给免费候选 (探针闸)
                and sec_probes < _SEC_PROBE_MAX
                and len(ctx.ledger.actions) != sec_probe_mark
            ):
                probe_res = eng.compile(
                    wdir,
                    ctx.io.main_rel,
                    passes=1,
                    best_effort=True,
                    flags=list(ctx.ledger.engine_flags),
                    **compile_kw,
                )
                ctx.invalidate_suffixes(_VOLATILE_EXTS)
                sec_probes += 1
                sec_probe_mark = len(ctx.ledger.actions)
                _note_dropped_flags(ctx, probe_res)
                probe_rep = _report_of(probe_res, rs.warn_patterns, wdir)
                cand_rep = probe_rep
                ctx.ledger.events.append(
                    f"r{rnd} secondary probe: err={probe_rep.n_bang}"
                )
            n_sec = 0
            for c2, p2, eline, eblob in rs.taxonomy.err_candidates(cand_rep):
                if (c2, p2) == (cat, pay):
                    continue  # 主错刚 miss 过, 不再重扫
                if n_sec >= _SEC_CAND_MAX:
                    break
                n_sec += 1
                # ctx.round 重指孪生 (when/ctx_suggests/llm_hook 均见此面),
                # dispatch rep 携孪生行位 (requester 锚/cases excerpt 用)。
                twin_rep = ErrReport(first=eline, ctx=eblob, raw=cand_rep.raw)
                ctx.round.point(c2, p2, twin_rep)
                rule, note = _match_apply_landing(rs, ctx, eng, c2, p2, twin_rep)
                if rule is not None:
                    sec_via = f"secondary:{c2}"
                    ctx.ledger.events.append(
                        f"r{rnd} secondary dispatch -> {c2}:{p2} ({rule.id})"
                    )
                    break
            if rule is None:
                # 候选耗尽仍未命中——ctx.round 回指主错, 走原裁决路径;
                # 探针结果入兜底槽 (同轮无 apply, 状态未变, 复用安全)。
                ctx.round.point(cat, pay, rep)
                salvage_res, salvage_rep = probe_res, probe_rep
                # warn-preempt (missdisp #189): error-cat 轮把轮次烧完、
                # 裁决落 dirty/unfixable/stuck 前——残存 missing-char 码位
                # 若有族臂未见, 补发一轮 warn_missing_char 派发再言败
                # (family_not_dispatched: 60/77 覆盖格从未拿到 warn 轮)。
                # 派发送 cand_rep: 探针跑过时其全错误面才是族臂 apply
                # 实读的盘上 .log。
                wrule, wnote = _warn_preempt(rs, ctx, eng, cand_rep)
                if wrule is not None:
                    if wnote.startswith(_REJECT_PREFIX):
                        cell["verdict"] = f"reject:{wrule.id}"
                        if r := _note_route(wnote):
                            cell["reject_route"] = r
                        break
                    cell["actions"].append(
                        {
                            "round": rnd,
                            "rule": wrule.id,
                            "detail": wnote,
                            "via": "warn_preempt",
                        }
                    )
                    ctx.ledger.events.append(
                        f"r{rnd} warn-preempt -> {wrule.id} ({wnote})"
                    )
                    # apply 已落地——探针编译瞬间陈旧, 兜底槽必须弃用
                    salvage_res = salvage_rep = None
                    continue
                # stuck 结算点移到派发耗尽后: 同签 streak ≥ stuck_sig_repeat
                # 且本轮主+次级均无 apply → stuck。旧制在第 stuck_n 个同签轮
                # 派发前预判——产出轮 (apply 发生) 同样计入 sig_n, 会把只
                # 在第 N+1 轮才够得到的规则 (凭据门 if_phantom_protect 类)
                # 永久抢死在窗口外 (1206.0701/1306.0364: r1/r2 各有 apply,
                # r3 未派发即断)。新制下同签轮只有「本轮无产出」才结算
                # stuck——apply 轮次只续窗口, 真耗尽格烧轮止于派发枯竭。
                cell["verdict"] = (
                    "stuck"
                    if sig_n >= stuck_n
                    else f"unfixable:{cat}"
                    if not pdf
                    else "dirty_pdf"
                )
                break
        if note.startswith(_REJECT_PREFIX):
            cell["verdict"] = f"reject:{rule.id}"
            if r := _note_route(note):
                cell["reject_route"] = r
            break
        action_entry: dict[str, Any] = {"round": rnd, "rule": rule.id, "detail": note}
        if sec_via is not None:
            action_entry["via"] = sec_via
        cell["actions"].append(action_entry)
        ctx.ledger.events.append(f"apply {rule.id}: {note}")
    else:
        cell["verdict"] = "max_rounds"

    # —— best-effort 兜底 pass: 规则耗尽且末轮无 pdf → 去 halt-on-error 让
    # TeX 错误恢复跑到底救残页 (astro-ph/0306068 型真回归: 首错即停 vs
    # nonstopmode 续跑出 partial pdf)。reject:* 是语义拒绝不救; clean/
    # dirty/acceptable 已有 pdf 不救; timeout 重跑大概率再超时, 不救;
    # runaway_output 是 \output 死循环暴走, 非定败重跑必然再暴走, 不救;
    # 驱动 fatal 是驱动层确定败 (同输入同 fatal), nonstopmode 改不了
    # shipout 后管道, 不救——主面走末轮 ``driver_fatal`` 证据字段
    # (category 借 "other" 面供修复规则派发, verdict 词看不出驱动死),
    # ``unfixable:driver_fatal`` 兜 _round_cat clean/None 边路径。
    # ``unfixable:input_stack`` 同为定败——该 cat 只由 capacity 重路由产出,
    # 全属上游执行宏递归帧, nonstopmode 重跑同炸, 不救。
    v_now = str(cell["verdict"] or "")
    # warn-preempt 退出点补位 (missdisp #189): loop 以 max_rounds/非拒绝
    # verdict 收场且末轮残存 missing-char 码位有族臂未见 → 补一轮派发
    # 再走 salvage/汇总。无 pdf 格的兜底编译天然充当验证编; max_rounds
    # +pdf 格的 apply 落地后不复编 (低风险幂等件, 下游 post 编译验)。
    if not v_now.startswith("reject:"):
        wrule, wnote = _warn_preempt(rs, ctx, eng, last_rep or ErrReport())
        if wrule is not None:
            if wnote.startswith(_REJECT_PREFIX):
                cell["verdict"] = f"reject:{wrule.id}"
                if r := _note_route(wnote):
                    cell["reject_route"] = r
            else:
                cell["actions"].append(
                    {
                        "round": "post",
                        "rule": wrule.id,
                        "detail": wnote,
                        "via": "warn_preempt",
                    }
                )
                ctx.ledger.events.append(f"post warn-preempt -> {wrule.id} ({wnote})")
                salvage_res = salvage_rep = None
            v_now = str(cell["verdict"] or "")
    if (
        v_now
        and not v_now.startswith("reject:")
        and v_now
        not in (
            "clean",
            "acceptable_pdf",
            "dirty_pdf",
            "unfixable:timeout",
            "unfixable:runaway_output",
            "unfixable:driver_fatal",
            "unfixable:input_stack",
        )
        and not (cell["rounds"] and cell["rounds"][-1]["pdf"])
        and not (cell["rounds"] and cell["rounds"][-1].get("driver_fatal"))
    ):
        swept = _sweep_bad_aux(wdir)
        if swept:
            ctx.ledger.events.append(f"salvage aux-sweep: {', '.join(swept)}")
        # 次级派发探针复用: miss 轮已跑过同参 best_effort 编译且其间无
        # apply (状态未变)——直接取回, 不二次烧编译 (twinhead 净零成本)。
        sres = (
            salvage_res
            if salvage_res is not None
            else eng.compile(
                wdir,
                ctx.io.main_rel,
                passes=1,
                best_effort=True,
                flags=list(ctx.ledger.engine_flags),
                **compile_kw,
            )
        )
        ctx.invalidate_suffixes(_VOLATILE_EXTS)
        _note_dropped_flags(ctx, sres)  # 复用探针已记录过——flags_dropped 去重幂等
        srep = (
            salvage_rep
            if salvage_rep is not None
            else _report_of(sres, rs.warn_patterns, wdir)
        )
        spdf = _res_has_pdf(sres)
        sentry = {
            "round": len(cell["rounds"]) + 1,
            "salvage": True,
            "pdf": spdf,
            "pdf_bytes": int(getattr(sres, "pdf_bytes", 0) or 0),
            "died": _res_died(sres),
            "driver_fatal": _res_driver_fatal(sres),
            "n_errors": srep.n_bang,
            "category": None,
            "payload": None,
            "warnings": list(srep.warnings),
            "warnings_sys": list(srep.warnings_sys),
            "line_no": srep.line_no,
            "file_stack": srep.file_stack,
            "sec": round(float(getattr(sres, "seconds", 0.0)), 1),
        }
        cell["rounds"].append(sentry)
        if on_round is not None:
            on_round(sentry)
        cell["actions"].append(
            {
                "round": "salvage",
                "rule": "_best_effort_pass",
                "detail": f"nonstopmode 兜底: pdf={spdf} err={srep.n_bang}",
            }
        )
        ctx.ledger.events.append(f"salvage best_effort: pdf={spdf} err={srep.n_bang}")
        if spdf:
            cell["verdict"] = "best_effort_pdf"

    # —— 汇总最终态 (spike L776-791) ——
    last = cell["rounds"][-1] if cell["rounds"] else {}
    cell["final_pdf"] = bool(last.get("pdf"))
    # —— 底板兜回: 入口有 pdf 而末态无 → 拷回快照, verdict 置 None 让下方
    # 既有公式自然落成 dirty_pdf/clean; floor_from 记兜底前 verdict 供
    # triage/cases 观测 (不新增 verdict 词, 保持 docs/08 §6 词表封闭)。
    v_end = str(cell["verdict"] or "")
    if (
        not cell["final_pdf"]
        and floor_snap is not None
        and not v_end.startswith("reject:")
    ):
        main_pdf.unlink(missing_ok=True)  # 末态同名碎片先清再拷, 防半截混语义
        shutil.copy2(floor_snap, main_pdf)
        cell["floor_from"] = v_end
        cell["floor_restored"] = True
        cell["final_pdf"] = True
        cell["verdict"] = None
        ctx.ledger.events.append(f"floor: entry pdf restored (was {v_end or 'none'})")
    cell["final_errors"] = last.get("n_errors")
    cell["final_cat"] = last.get("category")
    cell["installed"] = ctx.ledger.installed
    # 「看见/拒修」物化: rules_fired (actions 列) 的互补面 —— when 命中
    # 但 cond/applied 败阵的规则 id 去重列 + 带因注记 (去重同条目)。
    cell["rules_declined"] = list(
        dict.fromkeys(d.split(":", 1)[0] for d in ctx.ledger.declined)
    )
    cell["decline_notes"] = ctx.ledger.declined
    cell["advisories"] = ctx.ledger.advisories
    cell["engine_flags"] = ctx.ledger.engine_flags
    cell["engine_flags_dropped"] = ctx.ledger.flags_dropped
    cell["log"] = ctx.ledger.events
    if last_rep is not None:  # triage 原料: 终态错误上下文 (docs/08:318 log_excerpt)
        head = "\n".join(x for x in (last_rep.first, last_rep.ctx) if x)
        cell["log_excerpt"] = (head or last_rep.tail)[:2000]
    cell["started_fail"] = not (cell["rounds"] and cell["rounds"][0]["pdf"])
    if cell["verdict"] in (None, "max_rounds", "stuck") and cell["final_pdf"]:
        # 末轮死编译（超时/信号杀）产出 pdf 未证 clean——压成 dirty 且禁升。
        cell["verdict"] = (
            "dirty_pdf"
            if (last.get("n_errors") or 9) > 0 or last.get("died")
            else "clean"
        )
    if (
        cell["final_pdf"]
        and (cell["final_errors"] or 0) <= clean_err_max
        and cell["verdict"] == "dirty_pdf"
        and not last.get("died")  # 死编译末轮的 dirty 不升 acceptable
    ):
        cell["verdict"] = "acceptable_pdf"
    # 末态清场: 末轮/兜底被杀的截断 aux 不驻留毒化格后 post 复判
    swept = _sweep_bad_aux(wdir)
    if swept:
        ctx.ledger.events.append(f"final aux-sweep: {', '.join(swept)}")
        cell["log"] = ctx.ledger.events  # 上方已赋值的同一 list 引用, 显式重挂防漂移
    cell["gate_fired"] = _gate_fired_of(cell)
    _record_case(
        case_sink, cell, corpus_id=corpus_id, cond=cond, engine_name=engine_name
    )
    return cell


def _gate_fired_of(cell: dict[str, Any]) -> list[str]:
    """``reject:<rid>`` verdict → 拒绝规则名单; 其余 verdict → ``[]``。"""
    v = str(cell.get("verdict") or "")
    return [v.split(":", 1)[1]] if v.startswith("reject:") else []


def _record_case(
    sink: CaseSink | None,
    cell: dict[str, Any],
    *,
    corpus_id: str | None,
    cond: str | None,
    engine_name: str,
) -> None:
    """沉淀 cases.jsonl (docs/08 §5.5); sink 缺省即不写。"""
    if sink is None:
        return
    sink.record(cell, corpus_id=corpus_id, cond=cond, engine=engine_name)
