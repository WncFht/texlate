"""编译沙箱：env 白名单 + macOS sandbox-exec + 进程树超时杀（docs/08 §4.4）。

- env **白名单**（非黑名单）：只放编译所需最小集，天然洗 KEY/TOKEN/SECRET；
  叠加 `TECTONIC_UNTRUSTED_MODE=1 openin_any=p openout_any=p shell_escape=f`。
- macOS `sandbox-exec` profile：deny `$HOME` 读 + 全写，再按白名单放行
  工程/输出/缓存/字体/usermode texmf——settings.json、浏览器 profile、
  SSH key 编译期不可读。
- 进程组隔离（`start_new_session`）+ `killpg` 杀整棵进程树；非 POSIX 降级
  为 `proc.kill()`。子进程输出封顶 8MB 防内存炸。
- POSIX rlimits 纵深：exec 前经 preexec_fn 装 AS/NOFILE/CPU 软帽——失控
  TeX 吃不光宿主内存与 fd，自旋进程墙钟之外还有 SIGXCPU 第二闸。
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

if sys.platform != "win32":
    import resource
else:
    resource = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

#: 透传父进程的 env 名（白名单）。
_ENV_PASS_EXACT = {
    "HOME",
    "PATH",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "USER",
    "LOGNAME",
    "SOURCE_DATE_EPOCH",
    "TEXLATE_TEX_BUNDLE",
}

#: 透传父进程的 env 前缀（TeX/kpathsea 配置面）。
_ENV_PASS_PREFIX = (
    "TEXMF",
    "TEXINPUTS",
    "BIBINPUTS",
    "BSTINPUTS",
    "TFMFONTS",
    "VFFONTS",
    "T1FONTS",
    "TTFONTS",
    "OPENTYPEFONTS",
    "TEXFONTMAPS",
    "ENCFONTS",
    "XDVIFONTS",
)

#: 强制覆盖的 TeX 安全阀（kpathsea 环境变量层）。
_ENV_FORCED = {
    "TECTONIC_UNTRUSTED_MODE": "1",
    "openin_any": "p",  # 只允许读工程内（paranoid）
    "openout_any": "p",  # 只允许写工程内
    "shell_escape": "f",
    "max_print_line": "10000",  # 防长行截断丢错误上下文
}


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    r"""编译子进程环境：白名单透传 + 安全阀覆盖 + 调用方增量。

    ``extra`` 不得松动 ``_ENV_FORCED`` 阀位——``shell_escape=t`` 类增量
    静默压过强制阀即裸 ``\write18`` 面，同名键直接滤除（阀值恒赢）。
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if k in _ENV_PASS_EXACT or k.startswith(_ENV_PASS_PREFIX)
    }
    env.update(_ENV_FORCED)
    if extra:
        env.update({k: v for k, v in extra.items() if k not in _ENV_FORCED})
    return env


def sandbox_wrap(  # noqa: PLR0913 -- 沙箱决策参数面
    cmd: list[str],
    *,
    root: Path,
    out: Path,
    extra_read: list[Path] | None = None,
    extra_rw: Iterable[Path | str] = (),
    allow_net: bool = True,
) -> list[str]:
    """沙箱包裹命令（sandbox-exec，仅 macOS）；非 darwin / 无 sandbox-exec 原样返回。

    profile：`deny $HOME 读 + deny 全写`，然后白名单放行：
    - 读：工程目录、输出目录、tectonic 缓存、`~/Library/texmf`（usermode
      装的包）、`~/Library/texlive`（TEXMFVAR——fontmap/字体缓存，
      xdvipdfmx 必读；e2e-real 实证其被拒 → xdvipdfmx 死 → xelatex
      收 SIGPIPE）、`~/texmf`（TEXMFHOME）、`~/Library/Fonts`、
      系统字体/TeX 树、tmp、工具链目录；
    - 写：输出目录、tectonic 缓存、tmp、`/dev`、工程目录（xelatex 在 cwd
      写 .aux/.log）。

    ``allow_net=False`` 追加 ``(deny network*)``——与 bwrap ``--unshare-net``
    同义（xelatex 侧调用约定：工具链全本地，断网压 shell-escape 穿透的
    curl 外联面）；tectonic 冷拉 bundle 走 HTTPS，调用方须保持默认 True。
    """
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").exists():
        return cmd
    # SBPL 按 canonical 路径匹配——相对 root/out 生成的 literal 永远打不中，
    # 等同全拒（与 bwrap 相对 bind 同源坑）。
    root = Path(root).resolve()
    out = Path(out).resolve()
    home = Path.home()
    cache = home / "Library/Caches/TectonicProject.Tectonic"
    cache.mkdir(parents=True, exist_ok=True)
    read = [
        str(root),
        str(out),
        str(cache),
        str(home / "Library/texmf"),
        # TEXMFVAR 默认落点（fontmap/mktex 产物）——write 名单已有，
        # read 漏了：deny-$HOME-read 截获 xdvipdfmx 的 fontmap 读 →
        # 进程死 → xelatex 收 SIGPIPE（2211.13013 等 3/40 实证）。
        str(home / "Library/texlive"),
        str(home / "texmf"),  # TEXMFHOME 平台默认
        str(home / "Library/Fonts"),
        "/Library/Fonts",
        "/Library/TeX",
        "/System/Library/Fonts",
        "/usr/local",  # TeX Live 树与本机二进制
        "/opt/homebrew",  # tectonic/pdftotext 等
        "/etc",
        "/private/etc",
        # sandbox profile 按 canonical 路径匹配——macOS /var 是
        # /private/var 的软链，字面 /var/folders/... 规则永远打不中
        # （e2e-real 实证：mktexpk 建 pk 字体的 TMPDIR mkdir 被拒 →
        # xdvipdfmx 死 → xelatex 收 SIGPIPE，3/40 篇）。双形都写兜底。
        os.path.realpath(tempfile.gettempdir()),
        tempfile.gettempdir(),
        "/dev",
        # extra_rw 须读写双放——deny-$HOME-read 在前，只放写仍会读拒。
        *(str(Path(p).resolve()) for p in extra_rw),
        *(str(p) for p in (extra_read or [])),
    ]
    write = [
        str(root),
        str(out),
        str(cache),
        str(home / "Library/texmf"),  # updmap-user/mktex 迟建字体缓存
        str(home / "Library/texlive"),  # TEXMFVAR/CONFIG 默认落点
        os.path.realpath(tempfile.gettempdir()),  # canonical 形必须
        tempfile.gettempdir(),
        "/dev",
        *(str(Path(p).resolve()) for p in extra_rw),
    ]

    def _paths(paths: list[str]) -> str:
        # SBPL ``subpath X`` 只匹配 X 的**严格子孙**、不含 X 自身——
        # cd/stat 目录本体仍被 deny-$HOME-read 截获（e2e-real 实证：
        # mktexpk ``cd ~/Library/texmf/...`` ENOTDIR → bbold pk 装不上 →
        # xdvipdfmx 死 → xelatex SIGPIPE）。literal+subpath 双发才完备。
        return " ".join(
            "(literal "
            + json.dumps(p, ensure_ascii=False)
            + ")"
            + "(subpath "
            + json.dumps(p, ensure_ascii=False)
            + ")"
            for p in paths
        )

    profile = (
        "(version 1)\n(allow default)\n(deny file-read* (subpath "
        + json.dumps(str(home), ensure_ascii=False)
        + "))\n(deny file-write*)\n"
        + ("(deny network*)\n" if not allow_net else "")
        # deny 的是**内容读**；metadata(stat/目录遍历)放行——否则白名单
        # 子路径内的 shell ``cd``/getcwd 要 stat 祖先目录全被截获，
        # mktexpk 装 pk 字体的 cd 链必死（2211.13013 SIGPIPE 根因）。
        # 密钥/配置内容仍不可读，代价仅是 $HOME 下文件名可枚举。
        + "(allow file-read-metadata (subpath "
        + json.dumps(str(home), ensure_ascii=False)
        + "))\n"
    )
    profile += "(allow file-read* " + _paths(read) + ")\n"
    profile += "(allow file-write* " + _paths(write) + ")\n"
    return ["/usr/bin/sandbox-exec", "-p", profile, *cmd]


#: 子进程地址空间软帽（字节）——TeX 正常编译峰值 <1GiB，4GiB 只拦失控
#: 分配；macOS 不强制 RLIMIT_AS，设之无害。
_RLIMIT_AS_BYTES = 4 * 1024**3
#: 文件描述符软帽——kpathsea 正常并发 fd 峰值远低于 1024。
_RLIMIT_NOFILE = 1024
#: CPU 秒软帽下限：cap = max(2×墙钟, 本下限)——timeout/killpg 仍是主杀器，
#: CPU 帽兜「100% 自旋但墙钟面失守」的逃逸（SIGXCPU → engine 信号归因
#: 照常吃）；短 timeout 探针调用也拿 600s 地板，永不误杀。
_RLIMIT_CPU_FLOOR = 600


def _cap_rlimit(what: int, cap: int) -> None:
    """把 *what* 软帽降到 ``cap``（已低于 cap 则不动）；hard 保持原值。

    TeX 系进程从不自行 setrlimit——降 hard 是永久自残且无收益。单件失败
    （平台缺该 limit / 容器拒设）静默跳过：rlimits 是纵深兜底不是主闸。
    """
    try:
        soft, hard = resource.getrlimit(what)
    except (OSError, ValueError):
        return
    if soft == resource.RLIM_INFINITY or soft > cap:
        with contextlib.suppress(OSError, ValueError):
            resource.setrlimit(what, (cap, hard))


def _rlimit_preexec(timeout: float) -> Callable[[], None] | None:
    """返回 Popen ``preexec_fn``：exec 前装 AS/NOFILE/CPU 软帽；非 POSIX → None。"""
    if resource is None:
        return None
    caps = {resource.RLIMIT_CPU: max(2 * int(timeout), _RLIMIT_CPU_FLOOR)}
    if hasattr(resource, "RLIMIT_AS"):
        caps[resource.RLIMIT_AS] = _RLIMIT_AS_BYTES
    if hasattr(resource, "RLIMIT_NOFILE"):
        caps[resource.RLIMIT_NOFILE] = _RLIMIT_NOFILE

    def _install() -> None:
        for what, cap in caps.items():
            _cap_rlimit(what, cap)

    return _install


def run_process(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    out_cap: int = 8 * 1024 * 1024,
) -> tuple[int | None, str, float, bool]:
    """同步跑子进程：进程组隔离 + 超时 killpg + 输出封顶 + POSIX rlimits。

    返回 `(rc, output, seconds, timed_out)`；timeout 后 SIGKILL 整组
    （latex→dvips/mktextfm 子进程一并带走），非 POSIX 平台降级 proc.kill。
    子进程 exec 前装资源软帽（仅降不升），硬顶之外的纵深兜底。
    """
    t0 = time.time()
    try:
        proc = subprocess.Popen(  # noqa: S603 — 编译器子进程即本模块职责，输入已由
            cmd,  # --untrusted/-no-shell-escape/env 白名单/sandbox-exec 约束
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,  # 缺文件时 TeX 仍 \read stdin 问替代名——
            # 不钉死则吃 harness 继承的 stdin，行为随父进程飘（e2e-real 2308.12712
            # r1 出 4.4MB pdf / r2 emergency stop 即此不确定性）；钉 DEVNULL =
            # 确定性 EOF → emergency stop → missing_file 归因稳定。
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=(sys.platform != "win32"),
            # PLW1509: rlimits 只能 fork 后 exec 前装——回调只碰
            # resource.setrlimit（纯 syscall 封套，不取锁不分配）。
            preexec_fn=_rlimit_preexec(timeout),  # noqa: PLW1509
        )
    except OSError as e:
        # 二进制缺席/cwd 失效等 exec 失败——返回 rc=None 而非炸掉调用方
        # （fixloop 轮内 FileNotFoundError 会整格崩）。
        return None, f"exec failed: {e}", time.time() - t0, False
    timed_out = False
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        try:
            out, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired as e2:
            # setsid/双 fork 逃逸的孙进程仍握 stdout 写端——killpg 只带走
            # 本组，无限 communicate 会等孙进程退格才返 → 弃读防整格挂死。
            partial = e2.output
            out = b"".join(partial) if isinstance(partial, list) else partial
    except BaseException:
        # KeyboardInterrupt/GeneratorExit 等——不杀树会把编译进程连同
        # mktex*/dvips 子孙一起孤儿化（sleep 30 探针实证幸存）。
        _kill_tree(proc)
        proc.wait()
        raise
    if out is None:
        out = b""
    # 封顶保留**尾部**——消费端是 stdout_tail（tectonic 不写 .log 时的错误
    # 兜底），fatal error 恒在末尾；截头会把诊断现场丢掉。
    return (
        proc.returncode,
        out[-out_cap:].decode("utf-8", errors="replace"),
        time.time() - t0,
        timed_out,
    )


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """SIGKILL 整进程组；组杀失败退化为单进程 kill。"""
    try:
        if sys.platform != "win32":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()


def find_tool(name: str) -> str | None:
    """`shutil.which` + macOS TeX 常见落点（/Library/TeX/texbin、brew 前缀）。"""
    found = shutil.which(name)
    if found:
        return found
    if sys.platform == "darwin":
        for base in ("/Library/TeX/texbin", "/opt/homebrew/bin", "/usr/local/bin"):
            p = Path(base) / name
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
    return None
