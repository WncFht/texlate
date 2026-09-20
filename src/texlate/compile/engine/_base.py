"""引擎协议 + 编译结果类型 + 共享小件 —— ``engine.py`` 拆分基座叶。

``CompRes``/``Engine`` 契约（docs/08 §4.1）与两引擎共用的输出汇总、
信号死 stdout 打捞、main 参数合法性闸。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

from texlate.compile.loginfo import LogInfo
from texlate.texlog import DRIVER_FATAL_RE, driver_fatal_line
from texlate.textutil import safe_resolve

DEFAULT_TIMEOUT = 240.0  # docs/08 §4.1


# ================================================================ 数据类型
@dataclass
class CompRes:
    """一次编译调用的完整结果（clean 判定原料 + fixloop 输入）。"""

    engine: str
    ok: bool = False  # 进程正常跑完（非超时/启动失败）
    #: 编译工作根（compile 的 ``wdir`` 实参）——log 警告按「是否工程文件
    #: 产生」归因的根；post-hoc ``parse_log(res)`` 重解析时同源取用。
    workdir: Path | None = None
    pdf: Path | None = None
    pdf_bytes: int = 0
    log_path: Path | None = None
    log: LogInfo = field(default_factory=LogInfo)
    #: 编译期已读的 ``.log`` 文件全文（空/缺席/读失败为 ``""``；stdout_tail
    #: 兜底逻辑归消费方自理，与各家 ``or stdout_tail`` 口径一致）——fixloop
    #: ``_report_of``/``log_text_of``/``_l2_parse``/``parse_log(res)`` 直接复用，
    #: 同一文本不再重复开文件（B14 fix#10 格内 ~4× 文件读 → 1×）。
    log_text: str = ""
    timed_out: bool = False
    #: 活哨截杀原因（``vbox_flood``/``page_flood``）——``run_process``
    #: 经 ``timed_out`` 槽回吐 str，``_collect_compile_outputs`` 归位到
    #: 本字段并复归 bool。事后归因读记录值，不再凭 4KB stdout_tail 重数
    #: 全程签名密度（1003.2165 实证旧判据误归泛 timeout）。
    sentry_reason: str | None = None
    seconds: float = 0.0
    passes: int = 0
    rc: int | None = None  # 最后一个 pass 的 rc（逐 pass 覆写）
    #: 任一 pass 被信号杀死时记信号号（如 13=SIGPIPE）——res.rc 只留
    #: 末 pass，mid-loop 死亡会被后 pass 掩盖（2211.13013 实证）。
    killed_signal: int | None = None
    #: 趟间补跑的参考文献工具采纳记录（``bibtex:<aux-rel-stem>`` /
    #: ``biber:<stem>``）——非空即本编译跑过 bib 中间趟（``_bib_pass``
    #: 文件态触发，design tmp/lane-bibpass）；空表 = 未跑或未采纳。
    bib_ran: list[str] = field(default_factory=list)
    stdout_tail: str = ""
    deps: list[str] | None = None  # compiled_dependencies（.fls/.mk 权威输入集）
    #: 本次实际生效的 OS 沙箱形态：``off``（sandbox=False 或未走到 wrap
    #: 决策）/ ``sandbox-exec``（darwin）/ ``bwrap``（linux）/ ``env``
    #: （OS 包裹缺席，只剩 env 白名单 + TeX 阀层）——bench/stagerun 归因用。
    sandbox_mode: str = "off"
    #: ``compile(flags=…)`` 实落 argv 的请求 flag（tectonic 记映射前原拼写）。
    flags_applied: list[str] = field(default_factory=list)
    #: 请求但引擎拒放的 flag（支持子集外 / 会重键输出落点）→ fixloop 记
    #: advisory、e2e 凭它跨引擎取优。
    flags_dropped: list[str] = field(default_factory=list)

    @property
    def has_pdf(self) -> bool:
        """是否产出非空 PDF。"""
        return self.pdf is not None and self.pdf_bytes > 0


# ================================================================ Engine 协议
@runtime_checkable
class Engine(Protocol):
    """docs/08 §4.1 五方法 + detect/parse_log。

    `caps` 能力集决定 fixloop 哪些规则可跑：`{kpsewhich,tlmgr,updmap,
    shell_escape,bundle}`；tectonic 只有 `bundle`——install 系规则在其上
    走 ctan_fetch 原语（§5.3，由 fixloop 注入 callable）。
    """

    name: str
    caps: frozenset[str]

    def detect(self) -> str | None:
        """引擎二进制路径；不可用返回 None。"""
        ...

    def compile(  # noqa: PLR0913 — 签名即 docs/08 §4.1 规格面
        self,
        wdir: Path,
        main: str,
        *,
        passes: int | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        outdir: Path | None = None,
        sandbox: bool = True,
        env_extra: dict[str, str] | None = None,
        best_effort: bool = False,
        flags: Iterable[str] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> CompRes:
        """编译 `wdir/main`（相对路径）；产物落 `outdir`（默认 main 旁）。

        ``passes`` = 遍数上限：``None``（缺省）自适应——xelatex pass-1 后
        按 log rerun 提示族续跑（上限 ``MAX_PASSES``）；显式 int 无条件
        ≤N 遍（fixloop 收敛终编/bench 对齐口径）。两口径失败路径同停：
        错误退出/exec 失败/无 pdf/超时即不再跑下一趟。

        ``best_effort=True`` 强制 nonstopmode 兜底语义：xelatex 去掉
        ``-halt-on-error``（TeX 错误恢复跑到底，救残页），tectonic 强制
        continue-on-errors——fixloop 规则耗尽后的最后一搏用。

        ``flags`` = fixloop 规则请求追加的引擎 CLI flag（engine_flags cell
        的落点）：xelatex 原样追加 argv（kpathsea last-wins，可压
        ``-no-shell-escape``）；tectonic 只放 ``_map_flags`` 支持子集，
        其余记 ``CompRes.flags_dropped`` 降级为 advisory。

        ``should_cancel`` = 取消旗标轮询钩（worker 喂
        ``ctx.cancel_flag.is_set``）——置位即杀进程树抛
        ``asyncio.CancelledError``，不再等满 timeout 的孤儿编译段。
        """
        ...

    def probe_file(self, fname: str, *, cwd: Path | None = None) -> str | None:
        """文件可解析路径：kpsewhich（xelatex）| 本地+bundle 探测（tectonic）。"""
        ...

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        """装 `fname` 所在包：tlmgr usermode（xelatex）| ctan_fetch（tectonic）。"""
        ...

    def rebuild_fontmaps(self) -> bool:
        """updmap-user 重建字体 map（xelatex）；tectonic noop。"""
        ...

    def filemap(self, fname: str) -> list[str]:
        """file→包名索引：tlmgr search --file | 离线索引（fixloop 注入）。"""
        ...

    def parse_log(self, res: CompRes) -> LogInfo:
        """res.log_path 读不到时退 res.stdout_tail（tectonic 有时不写 .log）。"""
        ...


def _collect_compile_outputs(res: CompRes, outputs: list[str]) -> None:
    """汇总各 pass 的 stdout 尾巴进 CompRes + 活哨原因归位。

    ``run_process`` 把活哨截杀臂名写进 ``timed_out`` 槽以 str 回吐，引擎
    逐 pass 原样落 ``res.timed_out``——此处归位显式字段并复归纯 bool，
    下游（``_res_died``/e2e JSON/judge truthiness）只吃 bool 语义。
    """
    res.stdout_tail = outputs[-1][-4000:] if outputs else ""
    if isinstance(res.timed_out, str):
        res.sentry_reason = res.timed_out
        res.timed_out = True


def _driver_fatal(res: CompRes) -> str | None:
    r"""CompRes 的下游驱动 fatal 证据行（无则 ``None``）——clean 否决/归因单源。

    证据 = ``stdout_tail`` 有 ``*: fatal:`` 签名行 ∧ 编译呈失败相
    （``killed_signal`` 置位 / ``rc`` 非零 / 无 pdf）——``fatal:``
    字面行单有不足采：``\\write18`` 类孙件 fatal 可被主进程恢复，
    rc=0 且出 pdf 的编译按既有契约不算驱动死（salvage 阴性钉）。
    """
    line = driver_fatal_line(getattr(res, "stdout_tail", "") or "")
    if line is None:
        return None
    if getattr(res, "killed_signal", None) is not None:
        return line
    rc = getattr(res, "rc", None)
    if rc is not None and rc != 0:
        return line
    if not res.has_pdf:
        return line
    return None


def _salvage_driver_fatal(info: LogInfo, res: CompRes) -> None:
    """编译呈失败相时从 stdout_tail 捞下游驱动 fatal 行补进 info 归因。

    xdvipdfmx 等下游 fatal 只走 stdout（stderr→STDOUT 合并）、不进
    .log——两形态不捞则 first_error 空缺：xelatex 被 SIGPIPE 带走时
    .log 截断（1404.6041 ``Image inclusion failed``）；rc=1 非信号
    退出时 .log 完好零 ``!`` 错（1907.00277 ``pdf_link_obj`` fatal
    + 908KB 残 pdf——judge/fixloop 另经 ``_driver_fatal`` 否决 clean）。
    """
    if _driver_fatal(res) is None:
        return
    for m in DRIVER_FATAL_RE.finditer(res.stdout_tail):
        line = m.group(1).strip()[:300]
        if line not in info.errors:
            info.errors.append(line)
            info.n_errors += 1
        if info.first_error is None:
            info.first_error = line


def _checked_main(wdir: Path, main: str) -> Path:
    """``compile`` 的 main 参数合法性闸：NUL/``..``/符号链逃逸一律 ValueError。

    返回 ``wdir / main`` 的 normpath 形（折叠 ``.``/``..`` 但不解符号链——
    stem/cwd 沿用调用方给的拼写）。逃逸检查走 resolve 后双侧比对：
    ``../main.tex`` 把 cwd 与 ``{stem}.pdf/.log`` 产物落出 wdir，毁掉
    outdir 回收约定；NUL 路径在 stale unlink 处炸裸 ``ValueError`` 逃过
    fixloop 轮内捕获——校验先于一切 FS 变更。
    """
    if "\x00" in main:
        msg = f"invalid main {main!r}: embedded null"
        raise ValueError(msg)
    main_path = Path(os.path.normpath(wdir / main))
    wdir_r = safe_resolve(wdir)
    main_r = safe_resolve(main_path)
    if wdir_r is None or main_r is None or not main_r.is_relative_to(wdir_r):
        msg = f"invalid main {main!r}: escapes workdir"
        raise ValueError(msg)
    return main_path
