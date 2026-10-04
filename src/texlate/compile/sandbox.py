r"""编译沙箱策略面：env 白名单 + macOS sandbox-exec + linux bwrap（docs/spec/compile.md）。

- env **白名单**（非黑名单）：只放编译所需最小集，天然洗 KEY/TOKEN/SECRET；
  叠加 `TECTONIC_UNTRUSTED_MODE=1 openin_any=p openout_any=p shell_escape=f`。
- macOS `sandbox-exec` profile：deny `$HOME` 读 + 全写，再按白名单放行
  工程/输出/缓存/字体/usermode texmf——settings.json、浏览器 profile、
  SSH key 编译期不可读。
- linux `bwrap`：userns + 挂载白名单复刻 sandbox-exec 同语义（``$HOME``
  影子化只挂白名单子路径、pid/ipc/uts unshare、断网可选）；能力缺席退回
  env 白名单 + TeX 阀层。实落形态经 ``_apply_sandbox`` 记
  ``CompRes.sandbox_mode``，``TEXLATE_NO_BWRAP=1`` 显式关停。
- 子进程执行件（进程组隔离/单调钟排干环/超时 killpg/POSIX rlimits/
  ``_RunawaySentry`` 活哨）出叶 ``proc.py``——下段 ``from .proc import``
  只再出口 ``sandbox.X`` 旧路径仍在消费的名（``run_process`` 兼供
  ``judge``/``compile`` 包面与本模块自用；``_RunawaySentry``/
  ``_cap_rlimit``/``_SENTRY_KEEP`` 供测试），runner 其余名径走
  ``texlate.compile.proc``。**monkeypatch 钉定义模块**：runner 行为
  （``_RLIMIT_*`` 帽值、``subprocess`` 替身等）钉
  ``texlate.compile.proc``；本模块内被调名（``run_process``/``find_tool``/
  ``sandbox_wrap``/``_bwrap_*``/``_kpathsea_*``）仍钉本模块。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Final

from texlate.textutil import env_flag, filtered_env
from texlate.textutil.osutil import ENV_NO_BWRAP, ENV_TEX_BUNDLE

from .proc import (  # noqa: F401  # 再出口：``sandbox.X`` 旧路径仍在消费的名
    _SENTRY_KEEP,
    _cap_rlimit,
    _RunawaySentry,
    run_process,
)
from .toolchain import find_tool

if TYPE_CHECKING:
    from collections.abc import Iterable

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
    ENV_TEX_BUNDLE,
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
    env = filtered_env(_ENV_PASS_EXACT, _ENV_PASS_PREFIX, _ENV_FORCED)
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
        # deny 的是**内容读**；metadata(stat/目录遍历) 放行——否则白名单
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


# ================================================================ Linux bwrap 兜底
#: bwrap 挂载面默认覆盖的系统前缀（ro-bind-try：缺席跳过）。texmf 树不在此列
#: ——发行版布局分散（arch 把 TEXMFSYSVAR 放 ``/var/lib/texmf``，上游安装进
#: ``~/texlive/YYYY`` 或 ``/usr/local/texlive``），由 ``_kpathsea_dirs`` 按
#: texmf.cnf 权威值动态补挂。
_BWRAP_SYS_RO: Final = (
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/opt",
    "/etc",
    "/var/cache/fontconfig",
)

#: 需 RW 进沙箱的 env 键：texmf 可写树 + 自定义 tmp 目录。
_BWRAP_ENV_RW: Final = {
    "TEXMFHOME",
    "TEXMFVAR",
    "TEXMFCONFIG",
    "TEXMFSYSVAR",
    "TEXMFSYSCONFIG",
    "TMPDIR",
    "TEMP",
    "TMP",
}
#: env 键里 TMPDIR 系的子集——一律不挂宿主路径，``_bwrap_wrap`` 把它们
#: --setenv 重定向进沙箱私有 tmpfs。
_BWRAP_TMP_KEYS: Final = {"TMPDIR", "TEMP", "TMP"}
#: 需 RO 进沙箱的 env 键：kpathsea 搜索路径列表 + 本地 bundle 文件。
_BWRAP_ENV_RO: Final = {
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
    ENV_TEX_BUNDLE,
}
#: kpathsea 树变量：rw 侧是用户树；ro 侧是系统树（用户可写的经
#: ``os.access(W_OK)`` 升 rw——存在用户可写 SYSVAR 的发行版布局）。
_BWRAP_KPSE_RW: Final = ("TEXMFHOME", "TEXMFVAR", "TEXMFCONFIG")
_BWRAP_KPSE_RO: Final = (
    "TEXMFSYSVAR",
    "TEXMFSYSCONFIG",
    "TEXMFLOCAL",
    "TEXMFDIST",
    "TEXMFMAIN",
    "TEXMFINIT",
)
_KPATHSEA_ELEM_RX: Final = re.compile(r"[\s,:{}]+")
#: 沙箱内私有 tmpfs 挂点字面量——``/tmp`` 下的宿主路径判定专用。
_SANDBOX_TMP: Final = "/tmp"  # noqa: S108 -- 挂点语义即字面 /tmp


@lru_cache(maxsize=1)
def _texmfdist() -> str | None:
    """解 ``TEXMFDIST``（fontconfig conf 的 opentype 树锚点；无 → None）。"""
    try:
        proc = subprocess.run(
            ["kpsewhich", "-var-value", "TEXMFDIST"],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out or None


def _kpathsea_list(value: str) -> list[str]:
    """拆 kpathsea 路径列表（``:``/``,``/``{}`` 分隔，剥 ``!`` 与 ``//`` 尾）。"""
    out = []
    for elem in _KPATHSEA_ELEM_RX.split(value):
        p = elem.lstrip("!").removesuffix("//")
        if p and Path(p).is_absolute():
            out.append(p)
    return out


def _kpse_var(tool: str, var: str) -> str:
    """``kpsewhich -var-value <var>`` 单变量查询；任何失败返空串。"""
    try:
        rc, out, _, to = run_process(
            [tool, "-var-value", var], cwd=Path.cwd(), env=child_env(), timeout=15
        )
    except OSError:
        return ""
    return out if rc == 0 and not to else ""


@lru_cache(maxsize=1)
def _kpathsea_dirs() -> tuple[list[str], list[str]]:
    """问 kpathsea 各 texmf 树落点 → ``(rw, ro)``（进程内一次性探测）。

    发行版布局分散（arch 的 TEXMFSYSVAR 在 ``/var/lib/texmf``、上游装在
    ``~/texlive/YYYY`` 或 ``/usr/local/texlive``）——按 texmf.cnf 权威值挂，
    比写死路径或只按 binary 锚点可靠；kpsewhich 缺席返空表。
    """
    tool = find_tool("kpsewhich")
    if tool is None:
        return [], []
    rw: list[str] = []
    ro: list[str] = []
    for var in _BWRAP_KPSE_RW:
        rw += _kpathsea_list(_kpse_var(tool, var))
    for var in _BWRAP_KPSE_RO:
        for p in _kpathsea_list(_kpse_var(tool, var)):
            (rw if os.access(p, os.W_OK) else ro).append(p)
    return rw, ro


def _bwrap_env_paths(env: dict[str, str]) -> tuple[list[str], list[str]]:
    """编译子进程 env 里的路径值 → ``(rw, ro)`` 挂载名单。"""
    rw: list[str] = []
    ro: list[str] = []
    for key, val in env.items():
        if not val:
            continue
        if key in _BWRAP_ENV_RW:
            # TMPDIR 系不挂——`_bwrap_wrap` 会 --setenv 进私有 tmpfs，宿主
            # 路径挂进来既扩写面也可能在沙箱内根本不该存在。texmf 树变量
            # 可以是冒号链（_env 把 ambient 树链进 TEXMFHOME），逐元素拆。
            if key not in _BWRAP_TMP_KEYS:
                rw += _kpathsea_list(val)
        elif key in _BWRAP_ENV_RO:
            ro += _kpathsea_list(val)
    return rw, ro


def _bwrap_mounts(
    binary: str,
    *,
    root: Path,
    out: Path,
    env: dict[str, str],
    extra_rw: Iterable[Path | str] = (),
) -> tuple[list[str], list[str]]:
    """汇总 ``(rw, ro)`` 挂载面——root/out 由调用方单独硬挂，不在返回值里。

    ``$HOME`` 本体不挂：bwrap 为嵌套 bind 自建的父目录是沙箱内 tmpfs，
    宿主机 ``~/.ssh``/``~/.aws`` 保持不可见——对齐 macOS deny-$HOME 语义。
    """
    home = Path.home()
    rw: list[str] = [
        *(str(p) for p in sorted(home.glob(".texlive*"))),
        str(home / "texmf"),
        str(home / ".cache" / "fontconfig"),
        str(home / ".cache" / "texlate"),
        str(home / ".cache" / "Tectonic"),
        str(home / ".cache" / "TectonicProject.Tectonic"),
        *(str(p) for p in extra_rw),
    ]
    ro: list[str] = [
        str(home / ".fonts"),
        str(home / ".local" / "share" / "fonts"),
    ]
    env_rw, env_ro = _bwrap_env_paths(env)
    kpse_rw, kpse_ro = _kpathsea_dirs()
    rw += env_rw + kpse_rw
    ro += env_ro + kpse_ro
    # 引擎本体在系统前缀/工程/输出之外时锚发行根（``<dist>/bin/<arch>/<tool>``
    # 上三级即发行根，连带同级 texmf 树与 bin 伙伴）；锚点过宽（``/``、
    # ``$HOME``、``/home``）时退化为只挂二进制文件本身——托管/自装引擎
    # （~/.texlate/tools、~/.local/bin）都是自足单文件，足够。
    covered = [*_BWRAP_SYS_RO, str(root), str(out)]
    real = Path(binary).resolve()
    if not any(real.is_relative_to(p) for p in covered):
        anchor = real.parent.parent.parent
        if anchor in (Path("/"), home, home.parent):
            anchor = real
        if anchor not in (Path("/"), home, home.parent):
            ro.append(str(anchor))
    rw_set = set(rw)
    return sorted(set(rw)), sorted({p for p in ro if p not in rw_set})


@lru_cache(maxsize=1)
def _bwrap_capable() -> bool:
    """探测 bwrap 可用性：二进制在 + userns/pid/ipc/uts/net/cap-drop 全旗标可建。

    一次性全量探测——任一 namespace 被内核禁用（如
    ``kernel.unprivileged_userns_clone=0``）即返 False，编译退回 env-only
    而不是批量挂掉。``TEXLATE_NO_BWRAP`` 真值 = 显式关停（坏件逃生门）。
    """
    if env_flag(ENV_NO_BWRAP, default=False):
        return False
    tool = find_tool("bwrap")
    if tool is None:
        return False
    try:
        rc, _, _, to = run_process(
            [
                tool,
                "--die-with-parent",
                "--unshare-pid",
                "--unshare-ipc",
                "--unshare-uts",
                "--unshare-net",
                "--cap-drop",
                "ALL",
                "--ro-bind-try",
                "/",
                "/",
                "--",
                "/bin/true",
            ],
            cwd=Path.cwd(),
            env={},
            timeout=10,
        )
    except OSError:
        return False
    return rc == 0 and not to


def _bwrap_wrap(  # noqa: PLR0913 -- 挂载面组装参数即签名
    cmd: list[str],
    *,
    root: Path,
    out: Path,
    env: dict[str, str],
    allow_net: bool,
    extra_rw: Iterable[Path | str] = (),
) -> list[str] | None:
    """Linux 用 bwrap 复刻 sandbox-exec 语义；不可用返 ``None``（调用方直通）。

    - ``--die-with-parent`` + unshare pid/ipc/uts：pid-ns init 死亡时内核清
      场整棵进程树，与 run_process 的 killpg 互为兜底（**不**加
      ``--new-session``——那会另起进程组让 killpg 打不中孙进程）。
    - ``allow_net=False`` 追加 ``--unshare-net``：xelatex 工具链全本地可断
      网；tectonic 冷拉 bundle 必须留网，恒 True。
    - 挂载白名单见 ``_bwrap_mounts``；``--dir $HOME`` 保底存在（自建的
      tmpfs 影子目录，mktex 系 mkdir 有落点）。
    """
    if not _bwrap_capable():
        return None
    # bwrap 的 --bind 源按其自身 cwd（= run_process 的 cwd = build 目录）
    # 解析——调用方漏传绝对路径时 bind 在沙箱内落空 ENOENT、双引擎全灭
    # （live-smoke2 实证）→ 入口统一 resolve。
    root = Path(root).resolve()
    out = Path(out).resolve()
    extra_rw = [Path(p).resolve() for p in extra_rw]
    tool = find_tool("bwrap") or "bwrap"
    rw, ro = _bwrap_mounts(cmd[0], root=root, out=out, env=env, extra_rw=extra_rw)
    argv = [
        tool,
        "--die-with-parent",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--cap-drop",
        "ALL",
    ]
    if not allow_net:
        argv.append("--unshare-net")
    argv += [
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        _SANDBOX_TMP,
        "--dir",
        str(Path.home()),
    ]
    for prefix in _BWRAP_SYS_RO:
        argv += ["--ro-bind-try", prefix, prefix]
    # ro 先挂、rw 后挂：重叠路径上后挂的 rw 生效（如 TEXMFVAR 恰好落在
    # ro 系统树之下仍保持可写）。
    for p in ro:
        argv += ["--ro-bind-try", p, p]
    argv += ["--bind", str(root), str(root), "--bind", str(out), str(out)]
    # XDG_CACHE_HOME 不在 env 白名单内、子进程本不可见；宿主设了它则补挂并
    # --setenv 还原，让 tectonic 继续命中父侧热缓存而不是沙箱内重拉 bundle。
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg and Path(xdg).is_absolute() and not Path(xdg).is_relative_to(_SANDBOX_TMP):
        argv += ["--setenv", "XDG_CACHE_HOME", xdg]
        cache = str(Path(xdg) / "Tectonic")
        argv += ["--bind-try", cache, cache]
    # TMPDIR 系指向宿主路径时挂进来只是扩写面（甚至可能不存在）——一律
    # 重定向进私有 tmpfs；`_bwrap_env_paths` 同步不再为这三键加挂载。
    for key in _BWRAP_TMP_KEYS:
        if env.get(key):
            argv += ["--setenv", key, _SANDBOX_TMP]
    for p in rw:
        argv += ["--bind-try", p, p]
    argv += ["--", *cmd]
    return argv


def _apply_sandbox(  # noqa: PLR0913 -- 沙箱决策参数面
    cmd: list[str],
    *,
    root: Path,
    out: Path,
    env: dict[str, str],
    enabled: bool,
    allow_net: bool,
    extra_rw: Iterable[Path | str] = (),
) -> tuple[list[str], str]:
    """OS 沙箱分发 → ``(argv, mode)``，mode 落 ``CompRes.sandbox_mode``。

    ``sandbox=True`` 的既有契约本就含 env 白名单 + TeX 阀（恒在）；本层补
    OS 包裹：darwin ``sandbox-exec``、linux ``bwrap``、其余/能力缺席退回
    ``env``（与改动前 linux 行为一致）。
    """
    if not enabled:
        return cmd, "off"
    wrapped = sandbox_wrap(
        cmd, root=root, out=out, extra_rw=extra_rw, allow_net=allow_net
    )
    if wrapped is not cmd:
        return wrapped, "sandbox-exec"
    if sys.platform != "linux":
        return cmd, "env"
    bw = _bwrap_wrap(
        cmd, root=root, out=out, env=env, allow_net=allow_net, extra_rw=extra_rw
    )
    if bw is None:
        return cmd, "env"
    return bw, "bwrap"


#: 包裹层信号死上报基数：128+signo（bwrap/shell 惯例）
_WRAP_SIG_BASE: Final = 128
#: 上限 = 128+NSIG(64)；超过按字面退出码判
_WRAP_SIG_MAX: Final = 128 + 64


def _rc_to_signal(rc: int | None, sandbox_mode: str) -> int | None:
    """``run_process`` rc → 信号号（无则 None）。

    Popen 直通约定：信号死 = 负 rc。bwrap/sandbox-exec 包裹层把子进程
    信号死亡上报为 ``128+N``（xelatex 被 xdvipdfmx 拉死走 SIGPIPE=141
    实证）——不解码则 ``killed_signal`` 漏记，judge 把死进程产物当
    活结果判。

    已知取舍（评审 F2-low 档）：包裹层下 ``exit(128+N)`` 与真信号
    死不可区分——``exit(141)`` 会误记 SIGPIPE。代价止于归因噪声：
    ``_salvage_driver_fatal``/``_driver_fatal`` 只凭 ``*: fatal:`` 标记
    + 失败相补 stdout_tail 行，不翻转判定。按不实信号记录处理。
    """
    if rc is None:
        return None
    if rc < 0:
        return -rc
    if _WRAP_SIG_BASE < rc <= _WRAP_SIG_MAX and sandbox_mode in {
        "bwrap",
        "sandbox-exec",
    }:
        return rc - _WRAP_SIG_BASE
    return None
