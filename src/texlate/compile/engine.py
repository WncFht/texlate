r"""引擎层：Engine 协议 + xelatex/tectonic 实现 + 静态路由表（docs/08 §4）。

- Engine 协议（§4.1）：`detect/compile/probe_file/install_file/rebuild_fontmaps/
  filemap/parse_log` + `caps` 能力集——fixloop 按 caps 降级（tectonic 无
  tlmgr/kpsewhich/updmap，走 ctan_fetch 原语，见 §5.3）。
- 命令行（§4.1）：xelatex `-no-shell-escape -interaction=nonstopmode
  [-halt-on-error] -file-line-error -recorder` ≤2 pass；tectonic `-X compile
  --untrusted -Z continue-on-errors --keep-logs --keep-intermediates
  --makefile-rules`（continue-on-errors 对齐 nonstopmode 语义——tectonic
  默认 halt-on-error，engine-matrix §0 已实证）。
- pass 闸（B14 fix#7/C3）：``passes=None``（缺省）= 自适应——pass-1 后按
  log rerun 提示族（``_RERUN_HINT_RX``）决定续跑，无提示即收；显式 int
  = 无条件 ≤N 遍（fixloop 收敛终编靠它跑满）。两口径失败路径同闸：
  错误退出（rc>0 非信号）/exec 失败/无 pdf/超时即停——已炸编译不空烧；
  信号死（负 rc）保留续趟重试通道（2211.13013 实证可救）。
- 静态路由（§4.2）：`route_project` 编译前决策；失败集互补实测联合 clean
  9/12（engine-matrix §0）。
- OS 沙箱（§4.4）在 ``sandbox.py``（darwin ``sandbox-exec`` / linux ``bwrap``
  / 缺席退 env 白名单，``_apply_sandbox`` 分发，实落形态记
  ``CompRes.sandbox_mode``，``TEXLATE_NO_BWRAP=1`` 关停）；log 解析（§2.3）
  与错误分类学适配在 ``loginfo.py``；依赖记录（.fls/.mk→权威输入集）在
  ``deps.py``——本模块持引擎实现与路由，公共面经 import 回引保持
  ``from texlate.compile.engine import X`` 不破。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

from texlate.textutil import (
    DOCSTYLE_RX,
    decode_tex,
    safe_is_file,
    safe_resolve,
)

from .deps import compiled_dependencies
from .loginfo import (  # noqa: F401 -- WARNING_RED_LINES/classify_error 门面回引（judge/test_redlines 经本模块取）
    WARNING_RED_LINES,
    LogInfo,
    classify_error,
    parse_log,
)
from .mask import visible_tex
from .sandbox import (
    _apply_sandbox,
    _rc_to_signal,
    _texmfdist,
    child_env,
    find_tool,
    run_process,
)
from .toolchain import ensure_tectonic, tectonic_version

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 240.0  # docs/08 §4.1
MAX_PASSES = 2
_TECTONIC_ATTEMPTS = 2  # 冷 bundle 首拉超时后重试（缓存热身）

#: 续趟判据（B14 fix#7 rerun-gate）：逐趟 stdout 匹配——命中即 LaTeX 自报
#: 还要一遍。不收裸 ``rerun``（rerunfilecheck 包名行是常态噪音），也不收
#: biber 系请求（``Please (re)run Biber`` 单跑 latex 救不了 citation）。
_RERUN_HINT_RX: Final = re.compile(
    r"rerun to get|label\(s\) may have changed|there were undefined references"
    r"|table widths have changed",
    re.IGNORECASE,
)

#: ``probe_file`` texmf 树探测 memo 条数上限（B14 fix#3）：fixloop 格均
#: ~10–40 名、跨 cell 名集高重叠，容量远超格均即全覆盖；撞顶整表清——
#: 树态随 install 漂移，老条目残值低。
_PROBE_MEMO_MAX: Final = 4096
#: 重试趟预算上限——首趟已烧满 timeout，重试时缓存已热、只需覆盖真实编译
#: 时长；再给满 timeout 会把单次调用真超时翻倍且救不了真超时的论文。
_TECTONIC_RETRY_TIMEOUT = 120.0

#: tectonic bundle pin（docs/08 §4.1）——引擎默认 bundle；可用 env
#: TEXLATE_TEX_BUNDLE 或构造参数覆盖，置空串回落引擎自带默认 bundle。
TECTONIC_BUNDLE_PIN = "https://data1b.fullyjustified.net/tlextras-2022.0r0.tar"

#: ``compile(flags=…)`` 拒放面：重键输出落点的 flag 会毁掉 ``{stem}.pdf/.log``
#: 按 outdir 回收的约定——这类请求进 ``CompRes.flags_dropped`` 而非 argv。
_OUTPUT_REKEY_PREFIXES: Final = ("-output-directory", "-aux-directory", "-jobname")

#: engine_flags → tectonic argv 的受支持子集映射（原拼写 → argv token）。
#: ``-shell-escape`` 刻意不映射：``--untrusted`` 恒在 cmd 即禁 \write18，
#: 开 shell 与之矛盾且放大不可信源的 RCE 面 → 走 dropped，由 e2e 跨引擎
#: 换 xelatex 承载。
_TECTONIC_FLAG_MAP: Final = {
    "-synctex": ["--synctex"],
    "-synctex=1": ["--synctex"],
}

#: ``-Z`` 原生拼写直通是 ``-shell-escape`` 的后门（``-Z shell-escape``
#: 落位在 ``--untrusted`` 之后仍开 \write18；``-Z search-path=…`` 在 env
#: 降级下可读工程外路径）——只放已知无害子集，按 ``=`` 前值名匹配。
_TECTONIC_Z_OK: Final = frozenset(
    {
        "continue-on-errors",
        "minify-bundle",
        "keep-intermediates",
        "keep-logs",
        "deterministic-output",
        "synctex",
        "paper-size",
        "trace",
        "hide",
    }
)

#: xelatex 开 ``\write18`` 的 flag 拼写集——``env`` 降级（OS 容器缺席）时
#: 须从 argv 摘除降入 ``flags_dropped``：无沙箱兜底的 shell-escape 即裸
#: 命令执行面。``sandbox=off`` 是调用方明示退出，不动。
_SHELL_ESCAPE_FLAGS: Final = frozenset(
    {"-shell-escape", "--shell-escape", "-enable-write18", "--enable-write18"}
)

#: ``-X compile`` 撤 ``--web-bundle`` 的分界版本：0.17.0 起 URL 并入
#: ``--bundle``（0.17.0 help 实测 ``--bundle <BUNDLE>  Use this URL or
#: path``；老版 ``--bundle`` 只认本地路径，URL 必须 ``--web-bundle``，
#: 否则 URL 被当文件打开 → os error 2，archbox 全灭根因）。
_TECTONIC_BUNDLE_URL_MIN: Final = (0, 17, 0)


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
    seconds: float = 0.0
    passes: int = 0
    rc: int | None = None  # 最后一个 pass 的 rc（逐 pass 覆写）
    #: 任一 pass 被信号杀死时记信号号（如 13=SIGPIPE）——res.rc 只留
    #: 末 pass，mid-loop 死亡会被后 pass 掩盖（2211.13013 实证）。
    killed_signal: int | None = None
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
    """汇总各 pass 的 stdout 尾巴进 CompRes。"""
    res.stdout_tail = outputs[-1][-4000:] if outputs else ""


def _salvage_driver_fatal(info: LogInfo, res: CompRes) -> None:
    """信号死时从 stdout_tail 捞下游驱动 fatal 行补进 info 归因。

    xdvipdfmx 等下游 fatal 只走 stdout（stderr→STDOUT 合并）、不进
    .log——xelatex 被 SIGPIPE 带走时 .log 已截断，不捞则 first_error
    空缺（1404.6041: ``xdvipdfmx:fatal: Image inclusion failed`` →
    xelatex 写 xdv 管道收 SIGPIPE）。
    """
    if not res.killed_signal or not res.stdout_tail:
        return
    for m in re.finditer(r"(?m)^\s*(\w+:\s*fatal:[^\n]*)$", res.stdout_tail):
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


# ================================================================ xelatex
class XelatexEngine:
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
        # docs/08 命令行含 -halt-on-error（fixloop 首错语义）；bench 基线跑
        # best-effort（halt_on_error=False，对齐 compile_bench 方法论）。
        self.halt_on_error = halt_on_error
        self.texmfhome = texmfhome
        self.repository = repository or os.environ.get("TEXLATE_TLNET") or None
        self._search_cache: dict[str, list[str]] | None = None
        self._usertree_inited = False
        #: ``probe_file`` 树探测 memo——键 ``(fname, texmfhome, 宿主
        #: TEXMFHOME)``，值 None=阴性也缓存（缺件重探是真成本）；树态变动
        #: 只经本实例 install/updmap 通路，各落件点统一 ``clear()``。
        self._probe_cache: dict[tuple[str, str, str], str | None] = {}

    def detect(self) -> str | None:
        """Xelatex 二进制探测（ctor 指定优先，否则 PATH/常见落点）。"""
        return self.binary or find_tool("xelatex")

    def _env(self, extra: dict[str, str] | None) -> dict[str, str]:
        add = dict(extra or {})
        # 单行超长的 legacy 宏转储 (TCI tcilcomm.tex 实测 3MB/行) 会顶穿
        # web2c 默认 buf_size=200000 → `Unable to read an entire line` 硬死。
        # kpathsea cnf 变量可经 env 覆盖, 放宽输入行缓冲即解 (loop1-1706.02464)。
        add.setdefault("buf_size", "8000000")
        # fontspec 裸名查找走 fontconfig——texmf 自带 otf (FontAwesome.otf
        # 等) 未注册必炸 "font X cannot be found"。注入一份把
        # texmf-dist/opentype + usertree 字体注册的 conf（2211.12985 实证：
        # ambient/sandbox 同缺, OSFONTDIR 不吃, FONTCONFIG_FILE 一注即解）。
        fc = self._fontconfig_conf()
        if fc:
            add.setdefault("FONTCONFIG_FILE", fc)
        if self.texmfhome:
            # TEXMFHOME 写冒号链：usertree 居首（可写/优先），ambient
            # TEXMFHOME（缺席时取 kpathsea 默认 ~/texmf）尾随保持可见——
            # 否则宿主 ~/texmf 里的 shim/老包在 fixloop 冷树视角下凭空消失
            # （regress4 假退化根因）。tlmgr/updmap 不认链，走 _usertree_env。
            home_tree = str(self.texmfhome / "home")
            tail = os.environ.get("TEXMFHOME") or str(Path.home() / "texmf")
            homes = [home_tree] + [e for e in tail.split(":") if e and e != home_tree]
            add.update(
                {
                    "TEXMFHOME": ":".join(homes),
                    "TEXMFVAR": str(self.texmfhome / "var"),
                    "TEXMFCONFIG": str(self.texmfhome / "config"),
                }
            )
        return child_env(add)

    def _fontconfig_conf(self) -> str | None:
        """写一份 fontconfig conf 并返回路径（texmf opentype + usertree 字体注册）。

        ``FONTCONFIG_FILE`` 是整份替换语义——必须 ``<include>`` 系统 conf
        保住宿主机字体面。conf 落 ``usertree/home`` 之下（该目录经
        ``TEXMFHOME`` 链入 ``_bwrap_env_paths`` 挂进沙箱；usertree 根本身
        不在挂载面）；texmfhome 缺席时落 ``~/.cache/texlate/fontconfig/``
        （已列入 ``_bwrap_mounts`` rw）。重写幂等。
        """
        dist = _texmfdist()
        dirs = []
        if dist:
            dirs.append(str(Path(dist) / "fonts" / "opentype"))
        home_ot = (
            self.texmfhome / "home" / "fonts" / "opentype"
            if self.texmfhome
            else Path.home() / "texmf" / "fonts" / "opentype"
        )
        dirs.append(str(home_ot))
        try:
            cdir = (
                self.texmfhome / "home" / "fontconfig"
                if self.texmfhome
                else Path.home() / ".cache" / "texlate" / "fontconfig"
            )
            cdir.mkdir(parents=True, exist_ok=True)
            (cdir / "cache").mkdir(parents=True, exist_ok=True)
            conf = cdir / "fonts.conf"
            body = [
                "<?xml version='1.0'?>",
                "<!DOCTYPE fontconfig SYSTEM 'fonts.dtd'>",
                "<fontconfig>",
                '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>',
                *(f"  <dir>{d}</dir>" for d in dirs),
                # texmf opentype 数千枚，首扫几秒级——cachedir 落 usertree 内
                # 随格多次重编译摊销（沙箱 HOME 是 tmpfs，不落此即每次重扫）。
                f"  <cachedir>{cdir / 'cache'}</cachedir>",
                "</fontconfig>",
            ]
            conf.write_text("\n".join(body) + "\n", encoding="utf-8")
        except OSError:
            return None
        return str(conf)

    def _usertree_env(self) -> dict[str, str]:
        """tlmgr/updmap 系 env：TEXMFHOME 退链取首元素。

        tlmgr 把 env 值当字面路径——冒号链会被建成名为 ``texA:`` 的目录
        且 tlpdb 判定全炸（实测）。kpathsea 读侧（compile/probe）才吃链。
        """
        env = self._env(None)
        home = env.get("TEXMFHOME")
        if home and ":" in home:
            env["TEXMFHOME"] = home.split(":", 1)[0]
        return env

    @staticmethod
    def _split_flags(flags: Iterable[str] | None) -> tuple[list[str], list[str]]:
        """engine_flags → (进 argv, 丢弃)。

        ``_OUTPUT_REKEY_PREFIXES`` 系 flag 会重键 pdf/log 落点、毁掉按
        outdir 回收产物的约定 → 拒放进 dropped（kpathsea 单双横线等价，
        ``--output-directory=/x`` 同拒）；两 token 形态
        （``-output-directory /x``）把值 token 一并丢——留在 argv 会被
        xelatex 当第二输入文件处理。其余原样直通。
        """
        applied, dropped = [], []
        flist = list(flags or ())
        i = 0
        while i < len(flist):
            fl = flist[i]
            # kpathsea 长选项单双横线等价——归一成单横线再查重键表，
            # 否则 ``--output-directory=/x`` 绕过拒放面把 pdf/log 落点重键。
            norm = "-" + fl.lstrip("-")
            if norm.startswith(_OUTPUT_REKEY_PREFIXES):
                dropped.append(fl)
                if (
                    "=" not in fl
                    and i + 1 < len(flist)
                    and not flist[i + 1].startswith("-")
                ):
                    dropped.append(flist[i + 1])
                    i += 1
            elif fl not in applied:
                applied.append(fl)
            i += 1
        return applied, dropped

    def _cmd(
        self,
        binary: str,
        out: Path,
        main_name: str,
        *,
        best_effort: bool = False,
        flags: Iterable[str] | None = None,
    ) -> list[str]:
        """构造 xelatex 命令行（docs/08 §4.1 旗标集 + fixloop engine_flags）。

        ``flags`` 追加在基线旗标之后、``main_name`` 之前——kpathsea 选项
        last-wins，规则请求（如 minted 的 ``-shell-escape``）可压过
        ``-no-shell-escape``。
        """
        cmd = [
            binary,
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-file-line-error",
            "-recorder",
            f"-output-directory={out}",
        ]
        if self.halt_on_error and not best_effort:
            cmd.insert(3, "-halt-on-error")
        applied, _ = self._split_flags(flags)
        for fl in applied:
            if fl not in cmd:
                cmd.append(fl)
        cmd.append(main_name)
        return cmd

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
        """执行 xelatex ≤`passes` 遍；-recorder 产 .fls 供 compiled_dependencies。

        ``passes=None``（缺省）= 自适应门：pass-1 后只在 log 出现 rerun
        提示族（``_RERUN_HINT_RX``）时续跑，上限 ``MAX_PASSES``；显式 int
        = 无条件 ≤N 遍。失败路径两口径同闸：超时/错误退出（rc>0 且非信号）
        /exec 失败（rc=None）/无 pdf 即停——同输入重跑必同炸；信号死
        （负 rc）是外部截杀非确定性败，留续趟重试通道。
        """
        res = CompRes(engine=self.name)
        res.flags_applied, res.flags_dropped = self._split_flags(flags)
        binary = self.detect()
        if binary is None:
            res.stdout_tail = "xelatex not found"
            return res
        main_path = _checked_main(wdir, main)
        cwd = main_path.parent
        stem = main_path.stem
        out = (outdir or cwd).resolve()
        out.mkdir(parents=True, exist_ok=True)
        pdf, log = out / f"{stem}.pdf", out / f"{stem}.log"
        for stale in (pdf, log, out / f"{stem}.fls"):
            stale.unlink(missing_ok=True)
        env = self._env(env_extra)
        cmd = self._cmd(
            binary, out, main_path.name, best_effort=best_effort, flags=flags
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
        for p in range(1, eff_passes + 1):
            rc, out_s, sec, to = run_process(
                cmd, cwd=cwd, env=env, timeout=per_pass, should_cancel=should_cancel
            )
            res.rc = rc
            sig = _rc_to_signal(rc, res.sandbox_mode)
            if sig is not None:
                res.killed_signal = sig
            res.seconds += sec
            res.timed_out = res.timed_out or to
            res.passes = p
            outputs.append(out_s)
            # 停趟判据：超时 / exec 失败 / 确定性错误退出（rc>0 非信号）/ 无
            # pdf；自适应档（passes=None）再补一条——log 无 rerun 提示族即收。
            # 信号死（负 rc / 包裹层 128+N）是外部截杀非定败，留续趟通道。
            if (
                to
                or rc is None
                or (rc != 0 and sig is None)
                or not pdf.exists()
                or (passes is None and not _RERUN_HINT_RX.search(out_s))
            ):
                break
        _collect_compile_outputs(res, outputs)
        try:
            log_text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = ""
        res.log = parse_log(log_text or res.stdout_tail, project_root=wdir)
        _salvage_driver_fatal(res.log, res)
        res.log_text = log_text
        res.log_path = log if log.exists() else None
        res.pdf = pdf if pdf.exists() else None
        res.pdf_bytes = pdf.stat().st_size if pdf.exists() else 0
        res.ok = not res.timed_out and res.rc is not None and res.rc >= 0
        res.workdir = wdir
        res.deps = compiled_dependencies(wdir, main, out, self.name)
        return res

    def probe_file(self, fname: str, *, cwd: Path | None = None) -> str | None:
        """用 kpsewhich 探测文件可解析路径（texmf 树侧结果进程内 memo）。

        ``cwd`` 对应的 ``.`` 搜索元素拆成 ``Path.is_file`` 直查、不进 memo
        ——wdir 内文件随 fixloop 落件动态出现（vendored 平铺/stub 写件），
        直查让阴性缓存永不遮蔽新件。texmf 树探测按 ``(fname, texmfhome,
        宿主 TEXMFHOME)`` 键进 ``_probe_cache``——树内容变动只发生在本实例
        install/updmap 通路（各落件点统一清缓存）；跨进程同伴装件的陈旧
        阴性顶多让 tlmgr 空转一趟，``_post_install_verify`` 复核链自清。
        """
        if "\x00" in fname:
            return None  # NUL 进 argv 炸 Popen ValueError（log 可控面）
        base = cwd if cwd is not None else Path.cwd()
        if safe_is_file(cand := base / fname):
            return str(cand)
        key = (fname, str(self.texmfhome), os.environ.get("TEXMFHOME") or "")
        if key in self._probe_cache:
            return self._probe_cache[key]
        hit = self._probe_tree(fname)
        if len(self._probe_cache) >= _PROBE_MEMO_MAX:
            self._probe_cache.clear()
        self._probe_cache[key] = hit
        return hit

    def _probe_tree(self, fname: str) -> str | None:
        """``kpsewhich`` 纯树探测（``.`` 元素已由 ``probe_file`` cwd 直查覆盖）。"""
        tool = find_tool("kpsewhich")
        if tool is None:
            return None
        rc, out, _, to = run_process(
            [tool, fname],
            cwd=Path.cwd(),
            env=self._env(None),
            timeout=15,
        )
        if to or rc != 0 or not out.strip():
            return None
        return out.strip().splitlines()[0]

    def _search_cache_map(self) -> dict[str, list[str]]:
        """file→pkg 进程内缓存，首次访问时并入落盘缓存（远端仓库知识）。"""
        if self._search_cache is None:
            self._search_cache = load_search_cache()
        return self._search_cache

    def _filemap_index(self, fname: str) -> list[str] | None:
        """texlive.tlpdb 离线索引查询；索引不可用 → None（回退 tlmgr）。

        `tlmgr search --global` 逐查询远端 tlpdb，镜像 round-robin 实测挂出
        假 "no package provides"（fixloop-bench 口径）——同一份仓库知识走
        本地索引既稳又快（~/.texlate/cache/filemap.json 常驻）。
        """
        from texlate.compile.fixloop.ctan import (  # noqa: PLC0415  # 延迟: fixloop/__init__ 链重(cases→fcntl 平台门)
            MIRROR,
            TlpdbIndex,
        )

        try:
            idx = TlpdbIndex.ensure(mirror=self.repository or MIRROR)
        except Exception:  # noqa: BLE001  # 索引拉取失败不阻塞在线通路
            return None
        return idx.query(fname)

    def filemap(self, fname: str) -> list[str]:
        """file→TL 包名索引：tlpdb 离线索引优先，`tlmgr search --file` 兜底。"""
        if "\x00" in fname:
            return []  # NUL 进 tlmgr argv 炸 Popen ValueError（log 可控面）
        cache = self._search_cache_map()
        key = "/" + fname
        if key in cache:
            return cache[key]
        pkgs = self._filemap_index(fname)
        if pkgs is not None:
            cache[key] = pkgs
            return pkgs
        pkgs = self._filemap_tlmgr(fname)
        cache[key] = pkgs  # 进程内 memo 保留阴性（同文件重查不打爆 tlmgr）
        if pkgs:
            save_search_cache(cache)
        return pkgs

    def _filemap_tlmgr(self, fname: str) -> list[str]:
        """`tlmgr search --global --file /fname` 在线通路（索引缺席时兜底）。"""
        tool = find_tool("tlmgr")
        if tool is None:
            return []
        rc, out, _, to = run_process(
            [tool, "search", "--global", "--file", "/" + fname],
            cwd=Path.cwd(),
            env=self._usertree_env(),
            timeout=60,
        )
        pkgs: list[str] = []
        if not to and rc == 0:
            for ln in out.splitlines():
                m = re.match(r"^([\w.-]+):$", ln.strip())
                if not m:
                    continue
                pkg = m.group(1)
                # 滤平台特定条目与 tlmgr 自身输出
                if "." in pkg and pkg.split(".")[-1] in (
                    "windows",
                    "win32",
                    "macosx",
                    "linux",
                    "x86_64",
                    "aarch64",
                    "amd64",
                    "i386",
                    "universal",
                ):
                    continue
                if pkg.startswith(("tlmgr", "tlgs")):
                    continue
                pkgs.append(pkg)
        return sorted(set(pkgs))

    @contextlib.contextmanager
    def _install_lock(self) -> Iterator[None]:
        """同 usertree 的 tlmgr install 串行化（跨进程 flock；无 fcntl 则退化为直通）。"""
        base = (
            Path(self.texmfhome) if self.texmfhome else tlmgr_search_cache_path().parent
        )
        try:
            base.mkdir(parents=True, exist_ok=True)
            import fcntl  # noqa: PLC0415  # 平台门: 无 fcntl 则退化为直通
        except (OSError, ImportError):
            yield
            return
        with (base / ".texlate-install.lock").open("a+b") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        """经 kpsewhich 验证 → filemap 查包 → `tlmgr --usermode install` → 复核。"""
        if self.probe_file(fname):
            return True
        pkgs = self.filemap(fname)
        if not pkgs:
            return False
        tool = find_tool("tlmgr")
        if tool is None:
            return False
        env = self._usertree_env()
        home = env.get("TEXMFHOME")
        with self._install_lock():
            if self.probe_file(fname):
                return True  # 并发同伴已装好
            if (
                home
                and not self._usertree_inited
                and not (Path(home) / "tlpkg" / "texlive.tlpdb").exists()
            ):
                # 冷 TEXMFHOME：先建 usertree tlpdb，否则 --usermode 报
                # "Cannot determine type of tlpdb"（fixloop.py 实测坑）。
                rc_i, _, _, to_i = run_process(
                    [tool, "--usermode", "init-usertree"],
                    cwd=Path.cwd(),
                    env=env,
                    timeout=60,
                )
                # 失败/超时不钉 True——下次 install 按 tlpdb 缺席重试。
                self._usertree_inited = rc_i == 0 and not to_i
            argv = [tool, "--usermode"]
            if self.repository:
                argv += ["--repository", self.repository]
            argv += ["install", *pkgs]
            rc, _, _, to = run_process(argv, cwd=Path.cwd(), env=env, timeout=300)
        # tlmgr/init-usertree 动过树态——probe memo 清一遍再进复核链
        self._probe_cache.clear()
        if to or rc != 0:
            return False
        if font_related:
            self.rebuild_fontmaps()
        return self._post_install_verify(fname, pkgs, home)

    def _post_install_verify(
        self, fname: str, pkgs: list[str], home: str | None
    ) -> bool:
        """装后复核: tlmgr rc=0 未落盘走 CTAN overlay → doc-only 搬迁两兜底。

        postaction 类包在 usermode 整体拒装 ("package X is not relocatable",
        axodraw2 实证) —— 文件本身可直放, 走 CTAN archive 按 tlpdb relpath
        铺进 usertree home。mn2e.cls 类连 overlay 都落在 TEXINPUTS 外的
        doc/ 树 (mnras → doc/latex/mnras/LEGACY/) —— basename 恰一命中才
        搬进 tex/latex/。
        """
        if self.probe_file(fname) is not None:
            return True
        if not home:
            return False
        dest = Path(home)
        if self._fetch_into_usertree(fname, pkgs, dest):
            return True
        return self._relocate_doc_only(fname, dest)

    def _relocate_doc_only(self, fname: str, home: Path) -> bool:
        """把 doc/ 树落位的缺件搬进 tex/latex/ + kpsewhich 复核。"""
        base = Path(fname.replace("\\", "/")).name
        if not base or "\x00" in fname:
            return False
        try:
            root = home.resolve()
        except (OSError, RuntimeError, ValueError):
            return False
        doc = root / "doc"
        if not doc.is_dir():
            return False
        hits = [p for p in doc.rglob(base) if p.is_file()]
        if len(hits) != 1:  # 0=没装进来; >1=多副本歧义不猜
            return False
        dest = root / "tex" / "latex" / base
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(hits[0], dest)
        except OSError:
            return False
        if (root / "ls-R").is_file() and (tool := find_tool("mktexlsr")):
            run_process([tool, str(root)], cwd=Path.cwd(), timeout=60)
        self._probe_cache.clear()  # 刚把缺件搬进了树——复核前清 memo
        return self.probe_file(fname) is not None

    def _fetch_into_usertree(self, fname: str, pkgs: list[str], dest: Path) -> bool:
        """CTAN ``archive/<pkg>.tar.xz`` → overlay=tree 落 usertree home → 复核。"""
        from texlate.compile.fixloop.ctan import (  # noqa: PLC0415  # 延迟: fixloop/__init__ 链重(cases→fcntl 平台门)
            MIRROR,
            fetch_package,
        )

        for pkg in pkgs:
            # 网络/解包失败 → 试下一候选包 (复核探针是真值), 但不静默——
            # debug 留名供排障 (suppress 吞错曾让装包层故障零线索)
            try:
                fetch_package(
                    pkg,
                    dest,
                    mirror=self.repository or MIRROR,
                    overlay="tree",
                )
            except Exception as e:  # noqa: BLE001  # 候选包逐个试, 单包失败不致命
                log.debug("usertree fetch %s skipped: %r", pkg, e)
            # fetch 可能已部分落件——树态变了，复核前清 memo
            self._probe_cache.clear()
            if self.probe_file(fname) is not None:
                return True
        return False

    def rebuild_fontmaps(self) -> bool:
        """updmap-user 重建字体 map。"""
        tool = find_tool("updmap-user") or find_tool("updmap")
        if tool is None:
            return False
        args = [tool] if tool.endswith("updmap-user") else [tool, "--user"]
        rc, _, _, to = run_process(
            args, cwd=Path.cwd(), env=self._usertree_env(), timeout=120
        )
        self._probe_cache.clear()  # map 重建后字体类探测结果可能变
        return rc == 0 and not to

    def parse_log(self, res: CompRes) -> LogInfo:
        """编译期已读的 ``res.log_text`` 优先；缺席退 res.log_path，再 stdout_tail。"""
        text = res.log_text
        if not text and res.log_path is not None:
            with contextlib.suppress(OSError):
                text = res.log_path.read_text(encoding="utf-8", errors="replace")
        info = parse_log(text or res.stdout_tail, project_root=res.workdir)
        _salvage_driver_fatal(info, res)
        return info


def _mirror_source_dirs(cwd: Path, out: Path) -> None:
    r"""按源树目录集在 ``out`` 下镜像预建子目录（dot 目录不镜像）。

    tectonic ``--outdir`` 不预建子目录：``\\include``/``\\input`` 目标在
    子目录时 aux 写 ``<out>/<sub>/*.aux`` 直接 os error 2（modec-tec
    实证 2308.00125）。
    """
    for d in sorted(cwd.rglob("*")):
        if d.is_dir() and not d.is_relative_to(out):
            rel = d.relative_to(cwd)
            if not any(part.startswith(".") for part in rel.parts):
                (out / rel).mkdir(parents=True, exist_ok=True)


# ================================================================ tectonic
class TectonicEngine:
    """tectonic 便携引擎：分发默认优先（bundle 自足、初始 clean 率更高）。

    硬墙（换引擎信号，engine-matrix §7）：EPS/PS 图、bundle 缺物理字体、
    bundle 包版本旧语义错。`probe_file`/`install_file` 本地无解——
    ctan_fetch 原语由 fixloop 侧注入。
    """

    name = "tectonic"
    caps = frozenset({"bundle"})

    def __init__(
        self,
        binary: str | None = None,
        *,
        bundle: str | None = None,
        continue_on_errors: bool = True,
        hide_paths: list[Path] | None = None,
        ctan_fetch: Callable[[str], str | None] | None = None,
    ) -> None:
        """bundle=None → 钉版 tlextras-2022.0r0；ctan_fetch=(fname)->落点|None。"""
        self.binary = binary
        # 默认走 pin（docs/08 §4.1）；env TEXLATE_TEX_BUNDLE 覆盖，
        # 置空串 = 引擎自带默认 bundle。
        self.bundle = (
            bundle
            if bundle is not None
            else os.environ.get("TEXLATE_TEX_BUNDLE", TECTONIC_BUNDLE_PIN)
        )
        # 对齐 nonstopmode 语义（tectonic 默认 halt-on-error）。
        self.continue_on_errors = continue_on_errors
        self.hide_paths = list(hide_paths or [])
        self.ctan_fetch = ctan_fetch
        #: file→包名 离线索引（texlive.tlpdb 解析产物，§5.3）；
        #: fixloop 可注入 {basename: [pkg,...]}。
        self.filemap_index: dict[str, list[str]] = {}

    def detect(self) -> str | None:
        """Ctor 指定 → PATH/常见落点 → 托管件 → 自动下载（toolchain 矩阵）。"""
        return self.binary or ensure_tectonic()

    @staticmethod
    def _map_flags(
        flags: Iterable[str] | None,
    ) -> tuple[list[str], list[str], list[str]]:
        """engine_flags → (argv 追加 token, 丢弃的原 flag, 实放行的原 token)。

        放行面 = ``_TECTONIC_FLAG_MAP`` 显式映射 + ``-Z`` 白名单值域
        （``_TECTONIC_Z_OK``；``-Z<opt>`` 单 token 与 ``-Z <opt>`` 两 token
        都收）；其余（含 ``-shell-escape``、``-Z shell-escape`` 后门拼写与
        任何 ``--outdir`` 类重键尝试）进 dropped。``applied`` 是源 token
        级记账——``CompRes.flags_applied`` 取它（dropped 里 ``-Z <x>`` 是
        合体串，按 flist 差集会漏记成已放行）。
        """
        toks, dropped, applied = [], [], []
        flist = list(flags or ())
        i = 0
        while i < len(flist):
            fl = flist[i]
            if fl in _TECTONIC_FLAG_MAP:
                toks += _TECTONIC_FLAG_MAP[fl]
                applied.append(fl)
            elif fl == "-Z" and i + 1 < len(flist) and not flist[i + 1].startswith("-"):
                if flist[i + 1].split("=", 1)[0] in _TECTONIC_Z_OK:
                    toks += [fl, flist[i + 1]]
                    applied += [fl, flist[i + 1]]
                else:
                    dropped.append(f"-Z {flist[i + 1]}")
                i += 1
            elif fl.startswith("-Z") and fl != "-Z":
                if fl[2:].split("=", 1)[0] in _TECTONIC_Z_OK:
                    toks.append(fl)
                    applied.append(fl)
                else:
                    dropped.append(fl)
            else:
                dropped.append(fl)
            i += 1
        return toks, dropped, applied

    def _bundle_flag(self, binary: str) -> str:
        """Bundle 落 argv 的 flag 名：本地路径恒 ``--bundle``；URL 按版本分支。

        ``_TECTONIC_BUNDLE_URL_MIN`` 起 ``-X compile`` 撤了 ``--web-bundle``
        （URL 并入 ``--bundle``）；更老的 ``--bundle`` 只认本地路径。版本
        探不出 → ``--bundle``（托管件钉版已在新语法侧，新版是未来默认）。
        """
        if "://" not in self.bundle:
            return "--bundle"
        ver = tectonic_version(binary)
        if ver is not None and ver < _TECTONIC_BUNDLE_URL_MIN:
            return "--web-bundle"
        return "--bundle"

    def _cmd(
        self,
        binary: str,
        out: Path,
        main_name: str,
        *,
        best_effort: bool = False,
        flags: Iterable[str] | None = None,
    ) -> list[str]:
        """构造 tectonic V2 命令行（docs/08 §4.1 + continue-on-errors 语义对齐）。

        ``flags`` 经 ``_map_flags`` 过滤——只放受支持子集（见该方法 docstring）。
        """
        cmd = [
            binary,
            "--color",
            "never",  # 全局旗标，-X compile 子命令不认（实测 unexpected argument）
            "-X",
            "compile",
            "--untrusted",
            "--keep-logs",
            "--keep-intermediates",
            "--makefile-rules",
            str(out / "dependencies.mk"),
            "--outdir",
            str(out),
        ]
        if self.continue_on_errors or best_effort:
            cmd += ["-Z", "continue-on-errors"]
        if self.bundle:
            cmd += [self._bundle_flag(binary), self.bundle]
        for hide in self.hide_paths:
            cmd += ["--hide", str(hide)]
        toks, _dropped, _applied = self._map_flags(flags)
        cmd += toks
        cmd.append(main_name)
        return cmd

    def compile(  # noqa: PLR0913, PLR0915 — 签名即 docs/08 §4.1 规格面
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
        """执行 tectonic 单趟编译（自带 rerun 决策）；deps.mk 供 compiled_dependencies。"""
        del passes  # tectonic 自动决定 pass 数
        res = CompRes(engine=self.name)
        flist = list(flags or ())
        _toks, dropped, applied = self._map_flags(flist)
        res.flags_dropped = dropped
        res.flags_applied = applied
        binary = self.detect()
        if binary is None:
            res.stdout_tail = "tectonic not found"
            return res
        main_path = _checked_main(wdir, main)
        cwd = main_path.parent
        stem = main_path.stem
        out = (outdir or cwd / "_tect_out").resolve()
        out.mkdir(parents=True, exist_ok=True)
        _mirror_source_dirs(cwd, out)
        pdf, log = out / f"{stem}.pdf", out / f"{stem}.log"
        deps_mk = out / "dependencies.mk"
        for stale in (pdf, log, deps_mk):
            stale.unlink(missing_ok=True)
        env = child_env(env_extra)
        cmd = self._cmd(
            binary, out, main_path.name, best_effort=best_effort, flags=flist
        )
        # tectonic 冷拉 bundle/包走进程内 HTTPS——不能像 xelatex 那样断网。
        cmd, res.sandbox_mode = _apply_sandbox(
            cmd, root=wdir, out=out, env=env, enabled=sandbox, allow_net=True
        )
        # 冷 bundle 首拉可能超时：缓存热身后重试一次（compile_bench 惯例）。
        # 重试趟预算封顶 `_TECTONIC_RETRY_TIMEOUT`——首趟超时已烧满 timeout，
        # 满预算重试会把真超时翻倍（audit wave2）。
        outputs = []
        for budget in (timeout, min(timeout, _TECTONIC_RETRY_TIMEOUT))[
            :_TECTONIC_ATTEMPTS
        ]:
            rc, out_s, sec, to = run_process(
                cmd, cwd=cwd, env=env, timeout=budget, should_cancel=should_cancel
            )
            res.rc = rc
            sig = _rc_to_signal(rc, res.sandbox_mode)
            if sig is not None:
                res.killed_signal = sig
            res.seconds += sec
            outputs.append(out_s)
            # 末次尝试的 timeout 态才算数——首拉超时后重试成功不能再背
            # timed_out=True（否则 judge 走 timeout 短路，出了 pdf 也判 fail）。
            res.timed_out = to
            if not to:
                break
        res.passes = 1
        _collect_compile_outputs(res, outputs)
        try:
            log_text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = ""
        info = parse_log(log_text, project_root=wdir)
        if info.first_error is None and not log_text:
            # tectonic 有时不写 .log 就崩（如 \documentstyle）——stderr 兜底。
            info = parse_log(res.stdout_tail, project_root=wdir)
            if info.first_error is None:
                m = re.search(r"^error: (.+)$", res.stdout_tail, re.MULTILINE)
                if m:
                    info.first_error = "! " + m.group(1)
                    info.n_errors = max(1, info.n_errors)
        res.log = info
        res.log_text = log_text
        res.log_path = log if log.exists() else None
        res.pdf = pdf if pdf.exists() else None
        res.pdf_bytes = pdf.stat().st_size if pdf.exists() else 0
        res.ok = not res.timed_out and res.rc is not None and res.rc >= 0
        res.workdir = wdir
        res.deps = compiled_dependencies(wdir, main, out, self.name)
        return res

    def probe_file(self, fname: str, *, cwd: Path | None = None) -> str | None:
        """工程内探测（vendored 文件遮蔽检查）；bundle 探测留 ctan_fetch 层。"""
        if cwd is not None:
            # fixloop 供给的 fname 是 log 可控面——巨名/NUL 按未命中计，
            # ``../``/绝对路逃逸命中同样拒答：命中须留在 cwd 之内。
            cand = cwd / fname
            cand_r = safe_resolve(cand)
            cwd_r = safe_resolve(cwd)
            if (
                cand_r is not None
                and cwd_r is not None
                and cand_r.is_relative_to(cwd_r)
                and safe_is_file(cand)
            ):
                return str(cand)
        return None

    def filemap(self, fname: str) -> list[str]:
        """file→包索引：tectonic 侧无 tlmgr——返回 `filemap_index` 离线索引。"""
        return list(self.filemap_index.get(fname, []))

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        """ctan_fetch 降级原语（仅限 TeX 输入层文件 .sty/.cls/.tfm）。"""
        del font_related
        if self.ctan_fetch is None:
            return False
        dest = self.ctan_fetch(fname)
        return dest is not None

    def rebuild_fontmaps(self) -> bool:
        """返回 False：tectonic 无 updmap，noop。"""
        return False

    def parse_log(self, res: CompRes) -> LogInfo:
        """读 res.log_path；缺席/空文件时退 stdout_tail + ``error:`` 扫描。

        ``res.log_text`` 不可作 ``text`` 源——它已合并 stdout_tail，而下方
        ``error:`` 扫描门钉在「.log 文件侧为空」上（合并值会把空 .log +
        非空 stdout 的形态错挡在门外）。
        """
        text = ""
        if res.log_path is not None:
            with contextlib.suppress(OSError):
                text = res.log_path.read_text(encoding="utf-8", errors="replace")
        info = parse_log(text or res.stdout_tail, project_root=res.workdir)
        if info.first_error is None and not text:
            m = re.search(r"^error: (.+)$", res.stdout_tail, re.MULTILINE)
            if m:
                info.first_error = "! " + m.group(1)
                info.n_errors = max(1, info.n_errors)
        return info


# ================================================================ 静态路由表
@dataclass
class RouteDecision:
    """`route_project` 产物：引擎优先序 + 拒绝/降级原因。"""

    engines: list[str]  # 优先序，如 ["tectonic", "xelatex"]
    # 保留槽位：latex209 无条件拒已移 fixloop gate，route 现恒 None；
    # worker/e2e 的死检查即此槽位的预留消费点，留作将来"编译前必拒"语义。
    reject: str | None = None
    reasons: list[str] = field(default_factory=list)
    non_utf8: bool = False  # 非 UTF-8 源（需 iconv 预处理提示）
    latex209_suspect: bool = False  # \documentstyle 检出：降级为试编标记


#: pstricks/位图字体信号的名集单源——route_project 的文本签名与 probe 的
#: 声明依赖名查表共用（audit wave2 双表合一：probe.py 导入此处常量）。
#: pstricks 家族语义 = 精确名 ``pstricks`` + 前缀 ``pstricks-``/``pst-``
#: （pst-node/pst-plot/… 与 pstricks-add 全覆盖——probe 侧旧实现漏
#: pstricks-add，切名集后补齐）。
PSTRICKS_PKG_NAMES: Final = frozenset({"pstricks"})
PST_PKG_PREFIXES: Final = ("pstricks-", "pst-")
BITMAP_FONT_PKG_NAMES: Final = frozenset(
    {"bbm", "bbmfonts", "dsfont", "bbold", "yfonts", "wasy", "wasysym"}
)

#: 高置信 pstricks 依赖签名（visible_tex 遮蔽视图上匹配）：包名元素级
#: 精确（pstricks / pstricks-add / pst-* 家族——元素边界防 `{notpstricks}`
#: 类子串误中）+ `pspicture` 环境 + `\psset` 配置宏（vendored/传递装载的
#: 兜底信号，0905.2435/0905.4369 实证）。裸 `\psline`/`\psframe` 族不收——
#: polyfill 守卫与自定义宏残影假命中（corpus_v3 全扫零独立命中；新口径
#: 68 vs 旧 61，反增收 `{amsmath,pstricks}` 非首元素声明）。
_PSTRICKS_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*"
    r"\{[^}]*?\b(?:pstricks(?:-\w+)?|pst-\w+)\b|"
    r"\\begin\s*\{pspicture\*?\}|\\pspicture\b|\\psset\b"
)
_MINTED_FROZEN_RE = re.compile(r"frozencache")
#: ``frozencache`` 须与 minted 装载共现才翻 tectonic 优先（§4.2
#: "frozencache + minted"）——散文裸提 ``frozencache`` 词不构成信号。
_MINTED_PKG_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{[^}]*\bminted2?\b"
)
_BITMAP_FONT_PKGS = re.compile(
    r"\\usepackage(?:\[[^]]*\])?\{[^}]*\b("
    + "|".join(sorted(BITMAP_FONT_PKG_NAMES))
    + r")\b"
)


def route_project(root: Path, *, prefer: str = "tectonic") -> RouteDecision:
    r"""静态预检路由（docs/08 §4.2 表）：编译前即可决策的引擎分配。

    - `\documentstyle` → `latex209_suspect` 降级标记，**不再无条件 reject**
      （TL2026 实测 ~23% FP：cond-mat/9703223 等真 2.09 源编出 clean——
      先试编，fixloop `latex209_reject` gate 在真 2.09 错时兜底拒；
      inject 层仍按原样拒，两类 reject 在账本里分流）
    - `*.eps` / pstricks / pspicture → 跳过 tectonic 直走 xelatex（E2 硬墙）
    - frozencache + minted → tectonic 优先（bundle v2.6 兼容 v2 缓存）
    - bbm/dsfont 位图字体包 → tectonic 高风险标记（失败后换 xelatex）
    - 非 UTF-8 源 → 标记（iconv 预处理或 inputenc 路注，由调用方处理）
    """
    vis: dict[Path, str] = {}
    non_utf8 = False
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() != ".tex":
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue  # 不可读文件不参与路由信号（竞态删除/权限位）
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            non_utf8 = True
        vis[p] = visible_tex(decode_tex(raw))
    blob_vis = "\n".join(vis.values())

    # --- \documentstyle → latex209_suspect 标记（任何文件里出现都算）
    latex209_suspect = [
        str(p.relative_to(root)) for p, v in vis.items() if DOCSTYLE_RX.search(v)
    ]

    reasons: list[str] = []
    has_eps = any(p.suffix.lower() == ".eps" and p.is_file() for p in root.rglob("*"))
    has_pstricks = bool(_PSTRICKS_RE.search(blob_vis))
    has_minted_frozen = bool(
        _MINTED_FROZEN_RE.search(blob_vis) and _MINTED_PKG_RE.search(blob_vis)
    )
    has_bitmap_fonts = bool(_BITMAP_FONT_PKGS.search(blob_vis))

    engines = (
        ["xelatex", "tectonic"] if prefer == "xelatex" else ["tectonic", "xelatex"]
    )
    if has_eps or has_pstricks:
        # E2 硬墙：xdvipdfmx 不支持 EPS/PS → 跳过 tectonic
        engines = sorted(engines, key=lambda e: 0 if e == "xelatex" else 1)
        reasons.append(
            f"eps_files={has_eps} pstricks={has_pstricks} → xelatex 优先"
            "（tectonic xdvipdfmx 硬墙）"
        )
    elif has_minted_frozen:
        engines = sorted(engines, key=lambda e: 0 if e == "tectonic" else 1)
        reasons.append("minted frozencache → tectonic 优先（bundle v2.6 兼容）")
    if has_bitmap_fonts:
        reasons.append("bbm/dsfont 类位图字体包 → tectonic 高风险，失败换 xelatex")
    if latex209_suspect:
        reasons.append(
            f"latex209_suspect: {', '.join(latex209_suspect)} "
            "\\documentstyle → 试编不定死（fixloop gate 兜底拒）"
        )
    if non_utf8:
        reasons.append("非 UTF-8 源 → 需 iconv 转码预处理或 inputenc 路注")
    return RouteDecision(
        engines=engines,
        reject=None,
        reasons=reasons,
        non_utf8=non_utf8,
        latex209_suspect=bool(latex209_suspect),
    )


def engine_for(name: str, **kwargs: object) -> Engine:
    """按名构造引擎实例。"""
    if name == "xelatex":
        return XelatexEngine(**kwargs)  # type: ignore[arg-type]
    if name == "tectonic":
        return TectonicEngine(**kwargs)  # type: ignore[arg-type]
    msg = f"未知引擎 {name!r}"
    raise ValueError(msg)


def tlmgr_search_cache_path() -> Path:
    """定位 tlmgr file→pkg 搜索的跨进程落盘缓存位（fixloop 共用约定）。"""
    return Path(
        os.environ.get(
            "TEXLATE_TLMGR_CACHE",
            str(Path.home() / ".cache" / "texlate" / "tlmgr-search-cache.json"),
        )
    )


def load_search_cache() -> dict[str, list[str]]:
    """读 tlmgr 搜索缓存；缺席/损坏返回空表。

    空命中（阴性）载入即弃：镜像 round-robin 假 "no package provides"
    （``filemap`` docstring 记档）落盘后曾永久遮蔽索引——载入时滤掉
    空表，历史阴性一并自愈，索引/在线通路重获查询权。
    """
    try:
        raw = json.loads(tlmgr_search_cache_path().read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    # 值型闸：truthy 非标量（str/int/dict）原样进缓存会让 filemap 返回
    # 非 list[str]，下游 splat 把 "notalist" 散成单字符包名喂 tlmgr。
    return {
        k: v
        for k, v in raw.items()
        if isinstance(v, list) and v and all(isinstance(e, str) for e in v)
    }


def save_search_cache(cache: dict[str, list[str]]) -> None:
    """写 tlmgr 搜索缓存（父目录自动建）。空命中不落盘——阴性不跨进程固化。"""
    p = tlmgr_search_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({k: v for k, v in cache.items() if v}, indent=0, sort_keys=True)
    )
