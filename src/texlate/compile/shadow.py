r"""系统包遮蔽层（normalize.py 拆出）：invalid_utf8 修复臂三。

工程 ``\usepackage``/``\documentclass`` 引用落在工程外的包/类件：非 UTF-8
系统件经 ``decode_tex`` 净化后写同名副本进 main 目录（kpathsea ``.`` 首位
命中），遮蔽件内 ``\RequirePackage`` 引用做有界传递闭包。边界纪律与
实证见 ``_shadow_broken_system_packages`` docstring。
"""

from __future__ import annotations

import logging
import os
import re
import shutil  # noqa: F401 -- 测试锚：tests patch ``shadow.shutil.which`` 落共享模块对象，``patchseams.find_tool`` 内部同拦
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from collections.abc import Callable

from texlate.compile import patchseams
from texlate.textutil import DECL_TAIL, decode_tex, decode_tex_with

from .mask import TEX_SOURCE_SUFFIXES, visible_tex
from .transcode import _iter_files

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- invalid_utf8 臂三：系统包遮蔽
#: 工程源里显式引用的包/类名采集面——``\input`` 工程件已转码不查。
#: 成员集是 textutil ``LOADER_CMDS`` 按实参形态的有意分片而非复抄：
#: 本式 = ``{names}`` 装载形（usepackage/RequirePackage/
#: RequirePackageWithOptions）+ ``{opts}{names}`` 传参形
#: （PassOptionsToPackage/Class）；``LoadClass*`` 归 ``_CLASS_USE_RX``
#: （.cls 遮蔽面）。成员集不齐属语义分片，勿为对齐词表强并。
_PACKAGE_USE_RX: Final = re.compile(
    r"\\(?:usepackage|RequirePackage|RequirePackageWithOptions)\s*"
    r"(?:\[[^]]*\]\s*)?\{([^}]+)\}"
    r"|\\PassOptionsTo(?:Package|Class)\s*\{[^}]*\}\s*\{([^}]+)\}"
)
#: 类侧 = ``documentclass``（``DOCCLASS_NAMES`` 族成员）+ ``LoadClass*``
#: （``LOADER_CMDS`` 子集）——跨两个单源族各取一部，无单一集合可组装。
_CLASS_USE_RX: Final = re.compile(
    r"\\(?:documentclass|LoadClass|LoadClassWithOptions)" + DECL_TAIL
)
#: 遮蔽传递闭包轮数上限——遮蔽件自身 ``\RequirePackage`` 再拉系统件时补探。
_SHADOW_MAX_ROUNDS: Final = 8


def _kpse_resolve(filename: str, progname: str, cwd: Path, kpse: str) -> Path | None:
    """``kpsewhich`` 单名解析；``cwd`` 取 main 目录即 ``.`` 元素镜像编译工作目录。"""
    try:
        proc = subprocess.run(  # noqa: S603 — 固定 argv 无 shell
            [kpse, "-progname", progname, "--", filename],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        # ValueError：包名含 NUL → argv embedded null byte
        log.debug("kpsewhich 探测失败 %s: %s", filename, e)
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.splitlines()[0].strip())


def _kpse_resolve_many(
    filenames: list[str], progname: str, cwd: Path, kpse: str
) -> dict[str, Path | None]:
    """``kpsewhich`` 单次多名解析 → ``{请求名: 命中路径|None}``，逐名语义同单名版。

    多名模式逐 argv 位次输出：命中行=路径、miss=空行、末尾连续 miss 整体
    截断（kpathsea 6.4.2 实证；returncode=miss 计数，不按失败判）——
    ``splitlines`` 右补空串后与请求序 ``zip`` 即还原逐名映射。输出行数
    溢出、或命中行 basename 与请求名不符（版本行为漂移）时该名回落
    ``_kpse_resolve`` 单名复核；子进程本身起不来（缺席/超时/NUL 名）则
    全量回落——批量是纯加速，单名语义铁律不破。
    """
    unique = list(dict.fromkeys(filenames))
    if not unique:
        return {}
    try:
        proc = subprocess.run(  # noqa: S603 — 固定 argv 无 shell
            [kpse, "-progname", progname, "--", *unique],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        log.debug("kpsewhich 批量探测失败，回落逐名: %s", e)
        return {f: _kpse_resolve(f, progname, cwd, kpse) for f in unique}
    lines = proc.stdout.splitlines()
    if len(lines) > len(unique):
        # 位次模型不成立（行为漂移/版本差异）——逐名复核也不错位
        log.debug(
            "kpsewhich 批量输出行数溢出 %d > %d，回落逐名", len(lines), len(unique)
        )
        return {f: _kpse_resolve(f, progname, cwd, kpse) for f in unique}
    lines += [""] * (len(unique) - len(lines))
    resolved: dict[str, Path | None] = {}
    for name, line in zip(unique, lines, strict=True):
        hit = line.strip()
        if hit and Path(hit).name != Path(name).name:
            resolved[name] = _kpse_resolve(name, progname, cwd, kpse)
        else:
            resolved[name] = Path(hit) if hit else None
    return resolved


def _collect_package_refs(text: str) -> tuple[set[str], set[str]]:
    """可见视图上采集 ``(包名集, 类名集)``——逗号列表拆开逐项。"""
    packages: set[str] = set()
    classes: set[str] = set()
    visible = visible_tex(text)
    for match in _PACKAGE_USE_RX.finditer(visible):
        for raw in match.groups():
            if raw:
                packages.update(n.strip() for n in raw.split(",") if n.strip())
    for match in _CLASS_USE_RX.finditer(visible):
        name = match[2].strip()
        if name:
            classes.add(name)
    return packages, classes


def _tree_has_name(root: Path, name: str) -> bool:
    """``root`` 内任意深度存在 ``name`` 条目（文件/目录/软链皆算）→ True。

    ``os.walk(followlinks=False)`` 版 ``rglob`` 名单命中——rglob 跟随目录
    符号链且无环检测（in-tree 软链环炸 RecursionError、穿链把 root 外件
    误判成 vendored），隐藏目录整支剪掉（``.git`` 内部非 vendored 面）。
    """
    for _dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if name in filenames or name in dirnames:
            return True
    return False


def _shadow_source(
    name: str,
    suffix: str,
    root: Path,
    resolve: Callable[[str], Path | None],
) -> tuple[Path, bytes] | None:
    """遮蔽源定位+读取；逃逸名/工程内同名/root 内命中/不可读 → None。"""
    req = name + suffix
    # 名字逃逸 + vendored 优先一并早退：工程树内任何位置已有同名件 →
    # 不遮蔽（kpathsea ``.`` 首位会让 main_dir 副本盖掉用户文件；同名件
    # 可能经 \input/自定义 TEXINPUTS 进编译，不写遮蔽面）。
    if (
        name.startswith(("/", "~"))
        or ".." in Path(name).parts
        or _tree_has_name(root, Path(req).name)
    ):
        return None
    resolved = resolve(req)
    try:
        if resolved is None or resolved.resolve().is_relative_to(root):
            return None
        return resolved, resolved.read_bytes()
    except (OSError, RuntimeError, ValueError) as e:
        log.debug("系统包遮蔽源不可读 %s: %s", resolved, e)
        return None


def _try_shadow(
    name: str,
    suffix: str,
    root: Path,
    main_dir: Path,
    resolve: Callable[[str], Path | None],
) -> tuple[dict[str, str] | None, set[tuple[str, str]]]:
    """单包探测+遮蔽；返回 ``(台账条目, 遮蔽件内新引用 (名, 后缀) 对)``，不遮蔽时 ``(None, set())``。"""
    req = name + suffix
    src = _shadow_source(name, suffix, root, resolve)
    if src is None:
        return None, set()
    resolved, blob = src
    try:
        blob.decode("utf-8")
    except UnicodeDecodeError:
        pass  # 有坏字节才遮蔽
    else:
        return None, set()  # 系统件干净，无需遮蔽
    target = main_dir / req
    if target.exists() or target.is_symlink():
        # 悬挂软链 exists()=False 但 write_text 会写穿到 root 外目标
        return None, set()
    text, verdict = decode_tex_with(blob)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError as e:
        log.debug("遮蔽件写入失败 %s: %s", target, e)
        return None, set()
    # 传递闭包：遮蔽件自引的包名下轮补探（algorithm.sty 内部
    # \RequirePackage 再拉一个坏件的场景）
    more, _ = _collect_package_refs(text)
    entry = {
        "package": req,
        "from": str(resolved),
        "encoding": verdict.encoding,
        "basis": verdict.basis,
    }
    return entry, {(n, ".sty") for n in more}


def _collect_pending_refs(root: Path) -> set[tuple[str, str]]:
    r"""工程 tex 源的 ``\usepackage``/``\documentclass`` 名集 → (名, 后缀) 待探集。"""
    pending: set[tuple[str, str]] = set()
    for path in _iter_files(root, TEX_SOURCE_SUFFIXES):
        try:
            packages, classes = _collect_package_refs(decode_tex(path.read_bytes()))
        except OSError:
            continue
        pending.update((n, ".sty") for n in packages)
        pending.update((n, ".cls") for n in classes)
    return pending


def _shadow_broken_system_packages(
    root: Path, main: str | None, engine: str
) -> list[dict[str, str]]:
    r"""工程引用但落在工程外的包/类文件：非 UTF-8 者净化副本落 main 目录遮蔽。

    kpathsea 的 ``.``（编译 cwd = main 所在目录）先于一切 texmf 树——把
    ``decode_tex`` 净化后的同名副本写进 main 目录，``\usepackage`` 即命中
    本副本而非 latin-1 注释污染的系统件（loop1 invalid_utf8 归因：96% 格
    的警告只来自 ``~/texmf``/texmf-dist 的老 CTAN 包 ``algorithm``/
    ``algorithmic``/``algorithm2e`` 系——上游源码即非 UTF-8，系统树不可
    写、也不应被产品改写，遮蔽是唯一输入侧手段）。遮蔽只动字节面：
    latin-1→UTF-8 是码点恒等改写，宏体零语义差。遮蔽件内部的
    ``\RequirePackage`` 引用做有界传递闭包。``tectonic`` 不经 kpathsea、
    ``kpsewhich`` 缺席即整体跳过。

    边界纪律：``root`` 恒为 copytree 下游工作副本（stagerun zh 树 /
    worker ``ctx.base_dir`` / e2e work），遮蔽写不到用户原始归档；
    工程树内任何位置的同名件（vendored 优先）与 kpsewhich 命中 root
    内的件一律跳过——``.fd/.def/.clo`` 等隐式加载不走 ``\usepackage``
    采集面，其系统件坏字节属已知残留不追。
    """
    if engine not in ("xelatex", "lualatex"):
        return []
    # 工具发现单源走 patchseams（macOS 落点回退 + patchseams/toolchain 双锚
    # patch 面）。patchseams.__getattr__ 惰性回指返 object——cast 只补 ty 签名视图。
    kpse = cast("Callable[[str], str | None]", patchseams.find_tool)("kpsewhich")
    if not kpse:
        return []
    root = root.resolve()
    main_dir = (root / main).parent if main else root
    pending = _collect_pending_refs(root)
    shadows: list[dict[str, str]] = []
    probed: set[str] = set()

    for _ in range(_SHADOW_MAX_ROUNDS):
        fresh = [item for item in pending if "".join(item) not in probed]
        if not fresh:
            break
        # 逐名各起一个 kpsewhich 子进程是 parse 段实测大头（B14 fix#4：
        # 88 次 ≈ 18.8% stage）——多名模式一次调用拿整轮映射。
        resolved = _kpse_resolve_many(
            [name + suffix for name, suffix in fresh], engine, main_dir, kpse
        )
        for name, suffix in fresh:
            probed.add(name + suffix)
            entry, more = _try_shadow(name, suffix, root, main_dir, resolved.get)
            if entry is None:
                continue
            shadows.append(entry)
            pending.update(more)
    return shadows
