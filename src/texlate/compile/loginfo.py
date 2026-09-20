r"""log 语义层：TeX ``.log`` → ``LogInfo`` + 错误分类学适配（docs/spec/validate.md）。

行级词法原语（``(``/``)`` 文件栈、``file:line:``/``^!``/``l.NNN`` regex、
单遍事件流 ``iter_log_events``）在叶子层 ``texlog.py``；本模块持语义产物
（错误计数/首错上下文/红线命中 ``warnings_hit`` 与 ``warnings_sys``
归因）与 ``classify_error`` 薄适配——匹配语义（head/tail 有序评估、
payload_group、``subclassify`` 收窄、tail ``guard`` 复核）全部归
``compile.logparse.Taxonomy``（C3 归位——旧 ``fixloop.logparse`` 路径
经 shim 守恒），分类表**单源** = ``fixloop/rules/`` ``taxonomy:`` 段。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from texlate.compile._yamlish import load_yaml
from texlate.compile.logparse import ErrReport, Taxonomy
from texlate.redlines import ENGINE_RED_LINES, REDLINES_BY_ID, name_pattern
from texlate.texlog import (
    L_NUM_RE,
    is_dos_eps,
    is_project_file,
    iter_log_events,
    misschar_sweep_hits,
)

log = logging.getLogger(__name__)


@dataclass
class LogInfo:
    """`parse_log` 产物：错误计数、首错+上下文、tail、文件栈。"""

    n_errors: int = 0
    first_error: str | None = None
    error_ctx: str | None = None
    error_line: int | None = None  # l.NNN
    file_stack: list[str] = field(default_factory=list)
    #: 首错行位之前已弹出的文件名（pop 序；``None`` 非文件配对帧已滤）——
    #: ``File ended while scanning`` 类 runaway 错报位在父文件续行
    #: （``)`` 先于错误打印），``popped_files[-1]`` = 最近关闭的文件 =
    #: 肇事候选（#78）。与 ``file_stack`` 同位快照（首错时刻），无错 → 空。
    popped_files: list[str] = field(default_factory=list)
    tail: str = ""
    errors: list[str] = field(default_factory=list)  # 全部 '^!'/'file:line:' 行
    warnings_hit: list[str] = field(default_factory=list)  # judge 红线命中
    #: 系统 texmf/bundle 树来源的红线命中（``invalid_utf8@<file>``）——
    #: 工程文件不产生者的警告降为观察项，judge 记 notes 不阻断 clean。
    warnings_sys: list[str] = field(default_factory=list)


#: clean 判据的 log warning 红线（docs/spec/compile.md）：任一命中即 dirty。
#: ``invalid_utf8`` 按产生文件归因——仅工程文件源计入 ``warnings_hit``；
#: 系统 texmf/bundle 件（老 CTAN 包自带坏字节，loop1 归因占 96%）与
#: ``dos_eps_skipped`` 二进制件（normalize 原样保留、警告是必然残余）降
#: ``warnings_sys`` 观察项（fixer-utf8 `673d8ce` normalize 四臂后复审）。
#: 红线表单源 = ``texlate.redlines``（★2 收敛——本层发射名/pattern 即
#: registry ``engine`` 切片；``rules/`` ``warnings:``/judge/l2 同表别层）。
_UTF8_WARN_RE = re.compile(
    name_pattern(REDLINES_BY_ID["invalid_utf8"].engine)[1], re.IGNORECASE
)
WARNING_RED_LINES: list[tuple[str, str]] = list(ENGINE_RED_LINES)


def _scan_error_lines(
    lines: list[str], info: LogInfo, project_root: Path | None = None
) -> tuple[int, bool]:
    """数 `^!`+`file:line:` 错误、记首错位置——单遍事件流投影（texlog）。

    返回 ``(首错行号, 工程源 invalid_utf8 命中)``：逐事件把 ``ev.inner``
    （栈顶最内具名帧）作产生者交 ``is_project_file`` 判定——系统件源名
    收进 ``info.warnings_sys``（``invalid_utf8@<file>``），工程源命中由
    ``parse_log`` 收口进 ``warnings_hit``；DOS 魔数 EPS（normalize
    ``dos_eps_skipped`` 原样保留件）视同系统件降级，标 ``(dos-eps)``。
    """
    ctx_start = -1
    #: 弹栈史累计到首错（含首错行自身弹栈——本侧是含行快照口径，与
    #: logparse ``file_stack_at`` 排他栈是有意分歧不并）；``)`` 先于错误
    #: 行打印（runaway 报位在父文件续行），仅收集出错行会丢真肇事件；
    #: 首错捕获点与 file_stack 同位快照。
    popped: list[str | None] = []
    utf8_proj = False
    utf8_sys: set[str] = set()
    dos_eps_cache: dict[str, bool] = {}
    for ev in iter_log_events(lines):
        if info.first_error is None:
            popped.extend(ev.popped)
        if _UTF8_WARN_RE.search(ev.line):
            inner = ev.inner
            if is_dos_eps(inner, project_root, dos_eps_cache):
                # dos_eps_skipped 件：normalize 字节原样保留的二进制 EPS，
                # 残余警告降 warnings_sys 并打 (dos-eps) 标便于台账对账。
                name = Path(inner).name if inner else "?"
                utf8_sys.add(f"{name}(dos-eps)")
            elif is_project_file(inner, project_root):
                utf8_proj = True
            else:
                utf8_sys.add(Path(inner).name if inner else "?")
        if ev.err is not None:
            info.n_errors += 1
            info.errors.append(ev.err.head[:300])
            if info.first_error is None:
                info.first_error = ev.err.head
                ctx_start = ev.i
                info.file_stack = [s for s in ev.stack if s]
                info.popped_files = [t for t in popped if t is not None]
    info.warnings_sys = [f"invalid_utf8@{n}" for n in sorted(utf8_sys)]
    return ctx_start, utf8_proj


def parse_log(log_text: str, *, project_root: Path | None = None) -> LogInfo:
    """解析 TeX log 文本 → LogInfo（引擎无关；调用方负责拿文本）。

    错误计数**双格式**：`^!` 行 + `file:line:` 行（只数 `!` 会漏掉
    `-file-line-error` 模式下引擎级错误，docs/spec/validate.md）。

    ``project_root`` = 编译工作根（``wdir``）：invalid_utf8 红线按警告
    产生文件归因，系统 texmf/bundle 源与 DOS 魔数 EPS（normalize
    ``dos_eps_skipped`` 原样保留件）降 ``warnings_sys`` 观察项。
    缺席时绝对路径按 texmf 标记启发式、裸名保守归工程（不掉红线）。
    """
    info = LogInfo()
    if not log_text:
        return info
    lines = log_text.splitlines()
    ctx_start, utf8_proj = _scan_error_lines(lines, info, project_root)
    if ctx_start >= 0:
        ctx_lines = []
        for j in range(ctx_start, min(ctx_start + 9, len(lines))):
            ctx_lines.append(lines[j])
            if info.error_line is None:
                m = L_NUM_RE.match(lines[j].strip())
                if m:
                    info.error_line = int(m.group(1))
        info.error_ctx = "\n".join(ctx_lines)
    info.tail = "\n".join(lines[-30:])
    _scan_warnings(info, log_text, utf8_proj=utf8_proj)
    return info


def _scan_warnings(info: LogInfo, log_text: str, *, utf8_proj: bool) -> None:
    """红线 warning 扫描收口：invalid_utf8 按归因、missing_chars 扣扫掠。

    C0 测量扫掠豁免（``texlog.misschar_sweep_hits`` 签名面）：gate 命中
    全属扫掠成员时不发射——与 judge ``count_missing_chars`` 计数面同口径。
    """
    for name, pat in WARNING_RED_LINES:
        if name == "invalid_utf8":
            if utf8_proj:
                info.warnings_hit.append(name)
        elif name == "missing_chars":
            if (len(re.findall(pat, log_text)) - misschar_sweep_hits(log_text)) > 0:
                info.warnings_hit.append(name)
        elif re.search(pat, log_text, re.MULTILINE):
            info.warnings_hit.append(name)


# ================================================================ 错误分类学
#: ``scope:warnings`` 条目（``warn_*``）以 ``rep.warnings`` 为驱动原料——
#: 本接口只收 err/ctx/tail 三段不喂 warnings，故该段在本侧天然不触发
#: （fixloop 主循环以全文 log 扫描另行驱动，两处调用面本就不同）。


@lru_cache(maxsize=1)
def _taxonomy() -> Taxonomy | None:
    """``rules/`` ``taxonomy:`` → 编译态 ``Taxonomy``（进程内一次）。

    惰性只剩 ``RULES_PATH``：``fixloop.ruleset`` 经 builtins 链（平台门
    件）重且非全平台可 import；且引擎层在 ``rules/`` 缺席的上下文
    （裁剪部署、bench 快照）仍须可 import、可分类。``Taxonomy``/
    ``load_yaml`` 已归 compile 层（无 fixloop 依赖）故提升顶层——
    C3 归位杀掉的正是这两条 fixloop 惰性引。

    装载失败**不**重建冻结副本——副本即下一份漂移源；降级 ``None`` 使
    classify 退化为 ``other``/``clean``，warning 记一次（同根因由 fixloop
    侧 ``load_ruleset`` 的校验错误更完整报出）。只读 ``taxonomy:`` 段而不走
    ``Ruleset.load``：rules 段校验失败（规则 schema 面）不应击穿分类。
    """
    try:
        from texlate.compile.fixloop.ruleset import (  # noqa: PLC0415  # 延迟: fixloop builtins 链重+平台门
            RULES_PATH,
        )

        data = load_yaml(RULES_PATH)
        entries = data.get("taxonomy") if isinstance(data, dict) else None
        if not entries or data.get("version") != 1:
            log.warning("rules/ taxonomy 段缺失/空或 version!=1: %s", RULES_PATH)
            return None
        return Taxonomy(entries)
    except Exception:  # 装载失败 = 分类降级, 不阻断引擎层
        log.warning(
            "rules/ taxonomy 装载失败, 错误分类降级为 other/clean",
            exc_info=True,
        )
        return None


def _err_report(first: str | None, ctx: str | None, tail: str) -> ErrReport:
    """薄构造：``(err, ctx, tail)`` → ``logparse.ErrReport``。"""
    return ErrReport(first=first, ctx=ctx, tail=tail)


def classify_error(
    err: str | None, ctx: str | None, tail: str, *, timed_out: bool
) -> tuple[str | None, str | None]:
    """首错 → `(category, payload)`；payload 给规则定位用（文件名/字体名/cs 名）。

    分类学单源 = ``fixloop/rules/`` ``taxonomy:`` 段（见 ``_taxonomy``）；
    ``rules/`` 不可载时降级为 ``other``/``clean``（不留冻结副本——副本即
    漂移源）。
    """
    if timed_out:
        # timeout/runaway_output 细分单源在 ``Taxonomy.classify``——
        # rep 只携 tail 时按尾段刷屏判（暴走 log 的尾 30 行恒为签名）。
        tax = _taxonomy()
        if tax is not None:
            return tax.classify(_err_report(err, ctx, tail), timed_out=True)
        return "timeout", None
    tax = _taxonomy()
    if tax is None:
        return ("other" if err else "clean"), None
    return tax.classify(_err_report(err, ctx, tail or ""))
