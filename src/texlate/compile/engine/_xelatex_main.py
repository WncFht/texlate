r"""xelatex 引擎组合根（``engine/_xelatex`` 二级缝叶）。

``XelatexEngine`` 是四域 mixin 的组合根——``_XelatexEnv``（env/argv）、
``_XelatexBib``（bib 趟间补跑）、``_XelatexProbe``（kpsewhich/tlpdb 探测）、
``_XelatexInstall``（tlmgr usermode 装件）；本叶自持构造/``detect``/
``compile`` pass 环主环/``parse_log``。``run_process``/``find_tool`` 走
``_eng.`` 运行期回查——测试 patch 缝钉在 ``texlate.compile.engine.X``
模块名上。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path
    from typing import Final

    from texlate.compile.loginfo import LogInfo
    from texlate.compile.proc import run_process
    from texlate.compile.toolchain import find_tool

    class _EngNS:
        """``_eng`` 静态面——锚位真签名经 staticmethod 别名钉入。

        ``engine/__init__`` 经 seams ``__getattr__`` 惰性回指锚位模块，ty
        仅见 ``object``；借 TYPE_CHECKING 命名空间把 ``_eng.X`` 回查收窄到
        真签名。仅类型面视图——运行期 ``else`` 分支绑定原样，patch 缝
        （``monkeypatch.setattr(engine.X, …)`` → 叶侧 ``_eng.X`` 命中）零漂移。
        """

        find_tool = staticmethod(find_tool)
        run_process = staticmethod(run_process)

    _eng = _EngNS()
else:
    import texlate.compile.engine as _eng

from texlate.compile.loginfo import parse_log
from texlate.compile.sandbox import _apply_sandbox, _rc_to_signal
from texlate.texlog import log_text_of
from texlate.textutil import env_raw
from texlate.textutil.osutil import ENV_TLNET

from ._base import (
    DEFAULT_TIMEOUT,
    CompRes,
    _collect_compile_outputs,
    _salvage_driver_fatal,
)
from ._xelatex_bib import _XelatexBib
from ._xelatex_frame import _harvest, _prepare_main
from ._xelatex_install import _XelatexInstall
from ._xelatex_probe import _XelatexProbe
from ._xelatex_runenv import _XelatexEnv

MAX_PASSES = 2

#: 自适应档续趟硬顶（qc-impl 批二，2026-09-28）——``passes=None`` 起步 ``MAX_PASSES``
#: 趟，趟末 rerun/undef 提示仍在即按剩余墙钟重劈预算自延一趟，至本顶停
#: 补。bib 采纳 → ``\bibcite`` 落 aux → 文内 ``[n]`` 渲染要 3 趟（PoC
#: 实证 2 趟仍 ``[?]``），cap=2 在末趟截死即 ``??`` 出货（broken_refs
#: ~34 格实证面）。显式 ``passes=N`` 钉死档不吃本顶——caller 钉几趟跑
#: 几趟；bib 末趟采纳的破例延趟同不受限（新 bbl 必须有人消费）。
_ADAPTIVE_PASS_CAP: Final = 4

#: 续趟判据（B14 fix#7 rerun-gate）：逐趟 stdout 匹配——命中即 LaTeX 自报
#: 还要一遍。不收裸 ``rerun``（rerunfilecheck 包名行是常态噪音）。
#: qc-impl 扩臂 (fp resolve-pass): ``(citation|reference)...undefined``
#: 与 ``Please (re)run Biber/BibTeX`` 入面——0806.3788 型 bib 内 brace
#: 错吞掉 Rerun 尾标时 citation undefined 是唯一存活签名; biber/bibtex
#: 请求行同理要续趟吸收 (bib 趟由 ``_bib_pass`` 文件态承，本行只管
#: "再给一趟 tex" 的自适应信号)。
_RERUN_HINT_RX: Final = re.compile(
    r"rerun to get|label\(s\) may have changed|there were undefined references"
    r"|table widths have changed"
    r"|(?:citation|reference)s?\b[^\n]*?undefined"
    r"|please \(re\)run\s+(?:biber|bibtex)",
    re.IGNORECASE,
)

#: xelatex 开 ``\write18`` 的 flag 拼写集——``env`` 降级（OS 容器缺席）时
#: 须从 argv 摘除降入 ``flags_dropped``：无沙箱兜底的 shell-escape 即裸
#: 命令执行面。``sandbox=off`` 是调用方明示退出，不动。
_SHELL_ESCAPE_FLAGS: Final = frozenset(
    {"-shell-escape", "--shell-escape", "-enable-write18", "--enable-write18"}
)


# ================================================================ xelatex
class XelatexEngine(_XelatexEnv, _XelatexBib, _XelatexProbe, _XelatexInstall):
    """TeX Live xelatex：M0 开发默认（tlmgr 可修性实测最高，engine-matrix §5）。"""

    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr", "updmap", "recorder"})

    def __init__(
        self,
        binary: str | None = None,
        *,
        halt_on_error: bool = True,
        texmfhome: Path | None = None,
        repository: str | None = None,
    ) -> None:
        """binary=None → PATH/常见落点探测；texmfhome=沙箱 usermode 树（冷启动）。

        repository=tlnet 镜像 pin：`tlmgr --usermode install` 与 tlpdb 索引
        拉取共用（env ``TEXLATE_TLNET`` 同效）；None = tlmgr 既有配置
        （mirror.ctan.org round-robin 在部分网络下不稳，bench 侧钉 TUNA）。
        """
        self.binary = binary
        # docs/spec/compile.md 命令行含 -halt-on-error（fixloop 首错语义）；bench 基线跑
        # best-effort（halt_on_error=False，对齐 compile_bench 方法论）。
        self.halt_on_error = halt_on_error
        self.texmfhome = texmfhome
        self.repository = repository or env_raw(ENV_TLNET) or None
        self._search_cache: dict[str, list[str]] | None = None
        self._usertree_inited = False
        #: ``_fontconfig_conf`` memo——``(texmfhome, conf 路径)``。conf 内容
        #: 只吃 texmfhome（``_texmfdist`` 进程级 lru_cache 恒定）；texmfhome
        #: 经 fixloop ``_wire_engine``/worker 接线漂移（None → 实树）即自动
        #: 失效重写，conf 文件被外删（usertree 整清）时 ``is_file`` 复核回写
        #: ——同键每实例只写一回，不再逐次 ``_env`` 重写。
        self._fontconfig_memo: tuple[Path | None, str] | None = None
        #: ``probe_file`` 树探测 memo——键 ``(fname, texmfhome, 宿主
        #: TEXMFHOME)``，值 None=阴性也缓存（缺件重探是真成本）；树态变动
        #: 只经本实例 install/updmap 通路，各落件点统一 ``clear()``。
        self._probe_cache: dict[tuple[str, str, str], str | None] = {}

    def detect(self) -> str | None:
        """Xelatex 二进制探测（ctor 指定优先，否则 PATH/常见落点）。"""
        return self.binary or _eng.find_tool("xelatex")

    def compile(  # noqa: PLR0913 — 签名即 docs/spec/compile.md 规格面；pass 环停趟判据单点平铺
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
        """执行 xelatex ≤`passes` 遍；-recorder 产 .fls 供 compiled_dependencies。

        ``passes=None``（缺省）= 自适应门：趟输出出现 rerun 提示族
        （``_RERUN_HINT_RX``）即续跑——起步 ``MAX_PASSES`` 趟，趟末提示
        仍在按剩余预算再延一趟，硬顶 ``_ADAPTIVE_PASS_CAP``；显式 int =
        无条件 ≤N 遍。停趟判据：超时/exec 失败（rc=None）/无 pdf 即停
        ——同输入重跑必同炸；错误退出（rc>0 非信号）仅自适应档被 rerun
        提示压过（提示即 LaTeX 自报 .aux 状态已变、pass-2 非同一输入），
        钉死档与提示缺席照旧即停；信号死（负 rc）是外部截杀非确定性败，
        留续趟重试通道。
        """
        res = CompRes(engine=self.name)
        res.flags_applied, res.flags_dropped = self._split_flags(flags)
        binary = self.detect()
        if binary is None:
            res.stdout_tail = "xelatex not found"
            return res
        main_path, cwd, stem, out, pdf, log = _prepare_main(
            wdir, main, outdir, extra_stale=("{stem}.fls",)
        )
        env = self._env(env_extra)
        cmd = self._cmd(
            binary,
            out,
            main_path.name,
            best_effort=best_effort,
            flag_toks=res.flags_applied,
        )
        cmd, res.sandbox_mode = _apply_sandbox(
            cmd,
            root=wdir,
            out=out,
            env=env,
            enabled=sandbox,
            # xelatex 工具链（kpsewhich/mktex*/xdvipdfmx）全本地——断网兜底
            # ``-shell-escape`` flag 穿透场景（fixloop minted 规则可压过
            # -no-shell-escape）的 curl 外联面。
            allow_net=False,
            extra_rw=[self.texmfhome] if self.texmfhome else [],
        )
        if res.sandbox_mode == "env":
            # env 降级 = OS 容器缺席——shell-escape 系 flag 没人兜底，压过
            # -no-shell-escape 即裸 \write18 → 从 argv 摘除降入 dropped。
            esc = [f for f in res.flags_applied if f in _SHELL_ESCAPE_FLAGS]
            if esc:
                res.flags_applied = [
                    f for f in res.flags_applied if f not in _SHELL_ESCAPE_FLAGS
                ]
                res.flags_dropped += esc
                cmd = [t for t in cmd if t not in _SHELL_ESCAPE_FLAGS]
        outputs = []
        eff_passes = MAX_PASSES if passes is None else passes
        per_pass = max(10.0, timeout / max(1, eff_passes))
        # while 非 for-range：bib 采纳后 eff_passes+1 要真吃进一趟
        # （range 界在入环时定死，中途改量不延趟——bibcite→aux→[n] 需 3 趟）。
        p = 0
        while p < eff_passes:
            p += 1
            rc, out_s, sec, to = _eng.run_process(
                cmd, cwd=cwd, env=env, timeout=per_pass, should_cancel=should_cancel
            )
            res.rc = rc
            if (sig := _rc_to_signal(rc, res.sandbox_mode)) is not None:
                res.killed_signal = sig
            res.seconds += sec
            # ``to`` 可携活哨原因 str（``vbox_flood``/``page_flood``）——槽位
            # 短暂带 str 经 ``_collect_compile_outputs`` 归位 sentry_reason。
            res.timed_out = res.timed_out or to  # ty: ignore[invalid-assignment]
            res.passes = p
            outputs.append(out_s)
            # 停趟判据：超时 / exec 失败 / 无 pdf 恒收。确定性错误退出
            # （rc>0 非信号）仅被自适应档（passes=None）的 rerun 提示压过——
            # 提示即 LaTeX 自报还要一趟：.aux 首趟陈态错（footmisc perpage
            # 首趟 \@ctrerr Counter too large 一族）pass-2 自愈，不算同输入
            # 重跑；提示缺席照旧即收。钉死档（passes=N）rc!=0 恒停、不吃提示。
            # 信号死（负 rc / 包裹层 128+N）是外部截杀非定败，留续趟通道。
            hint = _RERUN_HINT_RX.search(out_s) is not None
            # bib 中间趟（bibpass 车道）：趟间产物（.bcf/.aux）此刻最新。
            # qc-impl 扩闸 (fp bibtex_pass_coverage/bbl_backup): 旧 ``p <
            # eff_passes`` 闸把末趟封死——passes=1 的 sealed 格 (fixloop
            # 分类趟/salvage) 永远轮不到 bib; 现放宽为任何趟后都评，若在
            # 末趟补成则 ``eff_passes = p+1`` 自延一趟让 tex 吸收新 .bbl
            # (钉死档 caller 钉了 N 也在 bib 采纳时破例延一趟——不延则
            # 新 bbl 无人消费)。本趟恒收的死相（超时/exec 败/无 pdf）与
            # 钉死档 rc!=0 不补（补了也吃不到下趟）。采纳即续趟信号；
            # pass2 载 .bbl 把 \bibcite 落 aux，pass3 才渲文内 [n]
            # （PoC 实证 2 趟仍 [?]）。
            adopted = False
            if (
                not res.bib_ran
                and not (to or rc is None or not pdf.exists())
                and (rc == 0 or sig is not None or passes is None)
            ):
                res.bib_ran = self._bib_pass(
                    wdir,
                    out,
                    env,
                    stem=stem,
                    sandbox=sandbox,
                    per_pass=per_pass,
                    should_cancel=should_cancel,
                )
                adopted = bool(res.bib_ran)
            hint = hint or adopted
            # 延趟两臂同一预算口径 (末趟到顶才延，各 +1): bib 本趟采纳
            # (钉死档亦延——新 bbl 须有人消费) 或自适应档提示仍在且未撞
            # ``_ADAPTIVE_PASS_CAP`` (qc-impl 批二，2026-09-28: bib 首趟采纳→
            # \bibcite 落 aux→文内 [n] 要第 3 趟，cap=2 末趟截停即 ``??``
            # 出货; 死相趟不延——续趟必同死)。延趟后按剩余墙钟重劈
            # per_pass——``timeout/eff_passes`` 本就是总墙钟约束：不劈则
            # timeout=240 的 2 趟起跑 (per_pass=120) 延成 3 趟可烧 360s,
            # 静默超预算。
            if p >= eff_passes and (
                adopted
                or (
                    passes is None
                    and hint
                    and eff_passes < _ADAPTIVE_PASS_CAP
                    and not (to or rc is None or not pdf.exists())
                )
            ):
                eff_passes = p + 1
                per_pass = max(10.0, (timeout - res.seconds) / max(1, eff_passes - p))
            if (
                to
                or rc is None
                or (rc != 0 and sig is None and not (passes is None and hint))
                or not pdf.exists()
                or (passes is None and not hint)
            ):
                break
        _collect_compile_outputs(res, outputs)
        try:
            log_text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = ""
        res.log = parse_log(log_text or res.stdout_tail, project_root=wdir)
        _salvage_driver_fatal(res.log, res)
        # Guard A (adjudication #10): halt_on_error 下 n_errors>0 ⇒ 编译截在
        # 首错——计数是下界非测量值，log 证不了 errors≤阈值; best_effort
        # (nonstopmode) 跑全程不截。消费端 getattr 容错——tectonic/测试替身
        # 无此字段按不截断处理。
        res.log_truncated = (
            self.halt_on_error and not best_effort and res.log.n_errors > 0
        )
        _harvest(res, wdir, main, out, pdf, log, log_text)
        return res

    def parse_log(self, res: CompRes) -> LogInfo:
        """``texlog.log_text_of`` 同口径：log_text 优先、``.log`` 兜底、stdout_tail 收尾。"""
        info = parse_log(log_text_of(res), project_root=res.workdir)
        _salvage_driver_fatal(info, res)
        return info
