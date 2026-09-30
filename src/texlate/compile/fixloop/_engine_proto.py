"""engine._engine_proto — Engine 协议面 + CompResLike 鸭形判定 + 报告装配 (C5 拆叶)。

``CompResLike``/``Engine``/``RunFn``/``LlmHook`` 协议签名 (docs/spec/compile.md
§1.1) 与 impl ``CompRes`` 的字段名差分吸收辅助 (``_res_has_pdf``/
``_res_driver_fatal``/``_res_died``) 收此叶; 轮内 ``(category, payload)``
归因 (``_round_cat``) 与 ``CompRes → ErrReport`` 装配 (``_report_of``)
同为「编译产出阅读」域。本叶无 fixloop 内叶依赖 (底层叶)。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from texlate.compile.engine._base import CompRes, _driver_fatal
from texlate.compile.logparse import (
    ErrReport,
    _is_runaway_output,
    parse_log,
    parse_text,
)
from texlate.texlog import normalize_stderr_errors

if TYPE_CHECKING:
    from collections.abc import Iterable

    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop.ruleset import Ruleset

__all__ = [
    "CompRes",
    "CompResLike",
    "Engine",
    "ErrReport",
    "LlmHook",
    "RunFn",
    "_driver_fatal",
    "_is_runaway_output",
    "_note_dropped_flags",
    "_report_of",
    "_res_died",
    "_res_driver_fatal",
    "_res_has_pdf",
    "_round_cat",
    "normalize_stderr_errors",
    "parse_log",
    "parse_text",
]


# ════════════════════════════════════════════════════════════════
# Engine 协议 (docs/spec/compile.md §1.1 签名; 引擎实现对接此处)
# ════════════════════════════════════════════════════════════════


class CompResLike(Protocol):
    """``Engine.compile`` 返回的结构化结果 (属性级 duck-typing)。

    对接 ``compile/engine/_base.py`` 的 ``CompRes``:
    ``pdf: Path|None`` + ``has_pdf`` + ``pdf_bytes`` + ``seconds`` +
    ``stdout_tail`` (tectonic 无 .log 兜底)。原型时代字段名 ``sec``
    经 getattr 链兼容。
    """

    @property
    def pdf(self) -> object:
        """``Path | None | bool`` 鸭形宽容读 (只读——fixloop 不写 ``res.pdf``)。"""
        ...

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

    @property
    def caps(self) -> set[str] | frozenset[str]:
        """能力集 {kpsewhich,tlmgr,updmap,shell_escape,bundle} (只读元数据)。"""
        ...

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

    def probe_file(self, fname: str, *, cwd: Path | None = None) -> str | None:
        """Kpsewhich | 本地+bundle 探测; 命中返路径, 缺返 None。

        ``cwd`` 可选 (impl 签名 ``probe_file(fname, *, cwd=None)``): 传 wdir
        时把"工程目录内已存在"也算命中 —— ctan_fetch 平铺落盘的复核靠它。
        """
        ...

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        """装提供 ``fname`` 的包: tlmgr --usermode | ctan_fetch 降级。"""
        ...

    def rebuild_fontmaps(self) -> bool | None:
        """updmap-user | noop (tectonic)——impl ``-> bool``, noop 替身可 ``None``。"""
        ...

    def filemap(self, fname: str) -> list[str]:
        """file→TL 包索引: tlmgr search --file | tlpdb 表 → 候选包名。"""
        ...


RunFn = Callable[..., tuple[int | None, str, float, bool | str]]
LlmHook = Callable[["LoopCtx", "ErrReport"], tuple[bool, str]]


# ── Engine 适配辅助 (impl-compile CompRes/Engine 的字段名差分吸收) ──


def _res_has_pdf(res: CompResLike | CompRes) -> bool:
    """Pdf 产出判定: impl ``has_pdf`` (非空文件) 优先, 否则 pdf 字段真值。"""
    hp = getattr(res, "has_pdf", None)
    # 鸭子实现若把 has_pdf 写成方法而非 property，bound method 恒真——调用之
    if hp is not None:
        return bool(hp() if callable(hp) else hp)
    return bool(getattr(res, "pdf", False))


def _res_driver_fatal(res: CompResLike) -> str | None:
    r"""``res`` 的下游驱动 fatal 证据行——``_driver_fatal`` 单源 + 鸭形谓词。

    判定本体在 ``engine._base._driver_fatal``；``_res_has_pdf`` 作注入
    谓词兼容替身 ``has_pdf`` 为方法/缺位的 ``CompResLike``。
    """
    return _driver_fatal(cast("CompRes", res), has_pdf=_res_has_pdf)


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
            norm = normalize_stderr_errors(tail)
            alt = parse_text(norm, warn_patterns, project_root=project_root)
            if alt.n_bang or rep.raw == "":
                rep = alt
    return rep
