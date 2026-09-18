r"""声明依赖静态探针 + `compiled_dependencies` 权威集差分（docs/08 §3.4）。

- `target_probe`：编译前扫主文件 preamble 的 `\usepackage`/`\documentclass`/
  `\input` 声明依赖（`visible_tex` 遮蔽视图定位、`\input` 沿本地文件传递
  跟进），本地命中 → ``local``，tlpdb 索引命中 → ``tl_pkg``，两空 →
  ``missing``——编译前即知哪些文件会落 ``missing_file``，供 fixloop 预热
  装包与路由决策；包名→引擎信号口径同 `engine.route_project`（§4.2）。
- `deps_diff`/`dep_seen`：`CompRes.deps`（.fls INPUT / dependencies.mk
  权威输入集）对期望输入集的差分——``missing_file`` 缺失文件「是否曾被
  .fls 记录读取」区分真缺失 vs 路径/时序问题；静态 `\input` 图只作编译
  失败时的降级（§3.4），`ProbeReport.inputs` 即该降级图。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from texlate.textutil import (
    BEGIN_DOC_RX,
    DECL_TAIL,
    INPUT_BARE_RX,
    INPUT_BRACED_RX,
    _tar_disguised,
    clean_decl_name,
    decode_tex,
    safe_is_file,
    safe_resolve,
)

from .engine import (
    _MINTED_FROZEN_RE,
    BITMAP_FONT_PKG_NAMES,
    PST_PKG_PREFIXES,
    PSTRICKS_PKG_NAMES,
)
from .latex209 import _KERNEL_OPTS
from .mask import visible_tex

if TYPE_CHECKING:
    from collections.abc import Iterable

    from texlate.compile.fixloop.ctan import TlpdbIndex

__all__ = [
    "DepProbe",
    "DepsDiff",
    "ProbeReport",
    "dep_seen",
    "deps_diff",
    "target_probe",
]

#: ``textutil.LOADER_CMDS`` 真子集直写——``PassOptionsToPackage``/
#: ``PassOptionsToClass`` 的首个 ``{}`` 实参是选项表而非包名（并进并集
#: group(1) 会抓错名）；``LoadClass`` 族是类加载归 ``_CLS_RE`` 一侧；
#: ``RequirePackageWithOptions`` 首参虽为包名但原面不收（差异留档非漏收）。
_PKG_RE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
#: ``textutil.DOCCLASS_NAMES`` ∪ ``{LoadClass}`` 内联——``LoadClassWithOptions``
#: 首参同为类名可收但原面不含（同上留档）。
_CLS_RE = re.compile(r"\\(documentclass|documentstyle|LoadClass)" + DECL_TAIL)
#: 死尾边界：首个 ``\end{document}``/``\endinput`` 之后引擎不再读本文件——
#: 其后的 ``\input`` 不产生 missing_file，扫它只会报假缺失。
_DEAD_TAIL_RE = re.compile(r"\\end\s*\{document\}|\\endinput\b")
#: ``\PreventPackageFromLoading`` 阻断名单收割（scrlfile 机制）：声明的包
#: 运行时被拦——``\usepackage`` 仍在稿面但永不加载，依赖表若照声明装包
#: 即 FP 向；阻断行自身被注释遮蔽则 FN 向（走遮盖视图天然豁免）。
_PREVENT_RE = re.compile(r"\\PreventPackageFromLoading\*?\s*\{([^}]+)\}")
#: SWP/SW（Scientific Word/Workplace）源码指纹——``%TCIDATA``/multibyte
#: 头注释/``\input{tcilatex}``。跑 raw 文本：指纹活在注释里，遮盖视图不可见。
_SWP_RE = re.compile(r"TCIDATA|multibyte Version:|\\input\s*\{?\s*tcilatex")
#: 终端交互读原语：``\typein``（恒终端）+ ``\read-1``（-1=stdin 通道；
#: 正数流号是文件读不收）。sandbox stdin=DEVNULL 已兜底防挂——此处仅诊断。
_INTERACTIVE_RE = re.compile(r"\\typein\b|\\read\s*-1\b")
#: dvips 原语插图 ``\special{psfile=..}``——xelatex(xdvipdfmx)/tectonic 均
#: 不渲染 psfile special，检出即图件必缺（无双引擎可行路径，纯注记）。
_PSFILE_SPECIAL_RE = re.compile(r"\\special\s*\{\s*psfile\b")

#: 声明包名 → (信号, 说明)。信号集：``xelatex`` = tectonic xdvipdfmx 硬墙；
#: ``shell_escape`` = 需 ``\write18``（xelatex flags 承载，tectonic
#: ``--untrusted`` 拒放）；``tectonic_risky`` = bundle 位图字体高风险标记
#: （失败后换引擎）。pstricks 家族与位图字体名集单源在 engine（
#: ``PSTRICKS_PKG_NAMES``/``PST_PKG_PREFIXES``/``BITMAP_FONT_PKG_NAMES``）。
_PKG_SIGNALS: dict[str, tuple[str, str]] = {
    "minted": ("shell_escape", "minted → 需 -shell-escape（pygments \\write18）"),
}


@dataclass(frozen=True, slots=True)
class DepProbe:
    """单条声明依赖的解析结果。"""

    name: str  # 声明名原样（"amsmath" / "chaps/intro.tex"）
    kind: str  # "package" | "class" | "input"
    fname: str  # 解析用文件名（缺省扩展名补齐后的探测目标）
    resolved: str  # "local" | "tl_pkg" | "missing"
    detail: str  # local → root 相对路径；tl_pkg → 首候选 TL 包名；missing → ""
    declared_in: str  # 声明所在文件（work_dir 相对 posix）


@dataclass(slots=True)
class ProbeReport:
    """`target_probe` 产物：依赖解析表 + 静态输入图 + 路由信号 + 预热清单。"""

    deps: list[DepProbe] = field(default_factory=list)
    #: 静态可达的本地 .tex 输入集（root 相对 posix，BFS 序，main 打头）——
    #: §3.4「静态 \input 图」降级臂；与 res.deps 差分用 `deps_diff`。
    inputs: list[str] = field(default_factory=list)
    #: 本地+tlpdb 两空 → 编译时必落 missing_file 的文件名（fixloop 预热目标）。
    missing: list[str] = field(default_factory=list)
    #: tl_pkg 命中的 TL 包名集（dedup 排序）——索引侧可解的依赖。
    tl_packages: list[str] = field(default_factory=list)
    #: 路由建议：``xelatex``/``tectonic``/None（None = 交回 route_project 默认）。
    prefer_engine: str | None = None
    #: 建议追加的引擎 flag（如 minted 的 ``-shell-escape``）。
    flags: list[str] = field(default_factory=list)
    #: 信号/缺失理由（human-readable，进账本）。
    notes: list[str] = field(default_factory=list)
    #: tlpdb 索引是否可用——False 时 missing 集含未证实项（本地缺席即记）。
    index_available: bool = True


@dataclass(slots=True)
class _ScanCtx:
    """`target_probe` 扫描状态：声明去重 + missing 登记集 + blob 收集 + latex209。"""

    root: Path
    cwd: Path  # 编译工作目录（main 所在目录）——kpathsea `.` 的唯一基准
    index: TlpdbIndex | None
    rep: ProbeReport
    declared: set[tuple[str, str]] = field(default_factory=set)
    missing_recorded: set[tuple[str, str]] = field(default_factory=set)
    blob_parts: list[str] = field(default_factory=list)
    latex209: bool = False
    #: ``\PreventPackageFromLoading`` 阻断名单（跨文件并集）——名单内包
    #: 的 missing/tl_pkg/信号记账抑制（声明≠加载）。
    prevented: set[str] = field(default_factory=set)
    #: ``\documentstyle[o]`` 非内核选项（209 选项位即 ``<opt>.sty`` 加载）。
    docstyle_opts: list[str] = field(default_factory=list)
    swp: bool = False  # SWP/SW 指纹命中（tcilatex 走 vendor stub 链）
    interactive: int = 0  # 终端交互读原语命中数（DEVNULL 已兜底，纯诊断）
    psfile: int = 0  # dvips-only \special{psfile} 命中数（图件必缺注记）


def _load_index() -> TlpdbIndex | None:
    """默认 tlpdb 离线索引（`TlpdbIndex.ensure` 同款惰性缓存；失败 → None）。"""
    from texlate.compile.fixloop.ctan import (  # noqa: PLC0415  # 延迟: fixloop/__init__ 链重(cases→fcntl 平台门)
        TlpdbIndex,
    )

    try:
        return TlpdbIndex.ensure()
    except Exception:  # noqa: BLE001  # 索引拉取失败降级「无索引」判定，不阻塞探针
        return None


def _find_local(root: Path, cwd: Path, fname: str) -> Path | None:
    r"""编译 cwd（main 所在目录）单跳本地解析。

    kpathsea 的 ``.`` 是引擎进程 cwd——本仓两引擎恒以 main 目录为 cwd
    （engine.py xelatex/tectonic 同口径），声明文件自身目录不在搜索路径：
    `chaps/one.tex` 里 `\\input{shared}` 解析 `cwd/shared.tex` 而非
    `chaps/shared.tex`（xelatex TL2026 + tectonic 0.15 实证 not found）。
    """
    cand = safe_resolve(cwd / fname)
    if cand is not None and safe_is_file(cand) and cand.is_relative_to(root):
        return cand
    return None


def _resolve_dep(
    root: Path, cwd: Path, name: str, kind: str, index: TlpdbIndex | None
) -> tuple[str, str, str]:
    """单依赖三分支解析 → (fname, resolved, detail)。"""
    ext = {"package": ".sty", "class": ".cls", "input": ".tex"}[kind]
    if kind == "input":
        # \input 原名带扩展名按原名找，无扩展名才补 .tex
        fname = name if Path(name).suffix else name + ext
    else:
        # \usepackage/\documentclass 恒补扩展名（除非名已以其结尾）——
        # \usepackage{weird.dotted} 引擎实找 weird.dotted.sty
        fname = name if name.lower().endswith(ext) else name + ext
    local = _find_local(root, cwd, fname)
    if local is not None:
        return fname, "local", local.relative_to(root).as_posix()
    # 路径段声明名（``\usepackage{dir/Name}``）只能由本地同名路径满足——
    # basename 平铺装包不落该相对路径，且会拿同名真包遮蔽账（``dir/foo``
    # 缺席误报成 TL ``foo`` 可装）。``\input`` 的 ``/`` 是常态相对路径
    # （``chaps/one``），basename 反查同形 FP 但不在本机制范围，留旧口径。
    if index is not None and (kind == "input" or "/" not in name):
        pkgs = index.query(PurePosixPath(fname).name)
        if pkgs:
            return fname, "tl_pkg", pkgs[0]
    return fname, "missing", ""


def _record_dep(
    ctx: _ScanCtx, rel: str, name: str, kind: str, *, optional: bool = False
) -> DepProbe:
    """解析 + 登记一条声明依赖（同 kind+fname 去重，保首个声明位）。"""
    fname, resolved, detail = _resolve_dep(ctx.root, ctx.cwd, name, kind, ctx.index)
    probe = DepProbe(
        name=name,
        kind=kind,
        fname=fname,
        resolved=resolved,
        detail=detail,
        declared_in=rel,
    )
    # \PreventPackageFromLoading 名单内包：加载被运行时拦断——不产 missing_file
    # 也不需装包，记账面抑制（dep 行仍留，声明确在）。
    blocked = kind == "package" and name in ctx.prevented
    if (kind, fname) in ctx.declared:
        # 首个声明是 optional（\InputIfFileExists）缺席不计 missing；后续同名
        # 硬引用命中去重——引擎仍会落 missing_file，这里补登记一次。
        if (
            resolved == "missing"
            and not optional
            and not blocked
            and (kind, fname) not in ctx.missing_recorded
        ):
            ctx.missing_recorded.add((kind, fname))
            ctx.rep.missing.append(fname)
            ctx.rep.missing.sort()
        return probe
    ctx.declared.add((kind, fname))
    ctx.rep.deps.append(probe)
    if resolved == "missing" and not optional and not blocked:
        # \InputIfFileExists 缺席走 else 分支——不是 missing_file，不进预热清单
        ctx.missing_recorded.add((kind, fname))
        ctx.rep.missing.append(fname)
        ctx.rep.missing.sort()
    elif resolved == "tl_pkg" and not blocked and detail not in ctx.rep.tl_packages:
        ctx.rep.tl_packages.append(detail)
        ctx.rep.tl_packages.sort()
    return probe


def _scan_inputs(ctx: _ScanCtx, live: str, rel: str, queue: list[Path]) -> None:
    r"""`\input`/`\include`/`\InputIfFileExists` + 裸 `\input` 登记与跟进。"""
    for match in INPUT_BRACED_RX.finditer(live):
        name = clean_decl_name(match["arg"])
        if name is None:
            continue
        optional = match["verb"] == "InputIfFileExists"
        probe = _record_dep(ctx, rel, name, "input", optional=optional)
        if probe.resolved == "local" and probe.fname.lower().endswith(".tex"):
            queued = safe_resolve(ctx.root / probe.detail)
            if queued is not None:
                queue.append(queued)
    for match in INPUT_BARE_RX.finditer(live):
        name = clean_decl_name(match["arg"])
        if name is None:
            continue
        probe = _record_dep(ctx, rel, name, "input")
        if probe.resolved == "local" and probe.fname.lower().endswith(".tex"):
            queued = safe_resolve(ctx.root / probe.detail)
            if queued is not None:
                queue.append(queued)


def _scan_file(ctx: _ScanCtx, tex: Path, rel: str, queue: list[Path]) -> None:
    r"""扫单文件：preamble 取 package/class 声明，活区取 `\input` 并入队。"""
    try:
        blob = tex.read_bytes()
    except OSError:
        # 单件不可读不拖垮整针——跳过该文件扫描，其余情报保留
        ctx.rep.notes.append(f"{rel} 读取失败——跳过声明扫描")
        return
    if _tar_disguised(blob):
        # tar 伪装 .tex——成员字节不是声明面（decode_tex 永不抛会把成员文本
        # 当 tex 扫出假声明污染 census）；normalize._tex_sources 同闸
        ctx.rep.notes.append(f"{rel} 是 tar 伪装件——跳过声明扫描")
        return
    raw_text = decode_tex(blob)
    if not ctx.swp and _SWP_RE.search(raw_text):
        # SWP 指纹在注释里——须跑 raw 文本（vis 已抹注释）。
        ctx.swp = True
    vis = visible_tex(raw_text)
    ctx.blob_parts.append(vis)
    ctx.interactive += len(_INTERACTIVE_RE.findall(vis))
    ctx.psfile += len(_PSFILE_SPECIAL_RE.findall(vis))
    m = BEGIN_DOC_RX.search(vis)
    preamble = vis[: m.start()] if m is not None else vis
    dead = _DEAD_TAIL_RE.search(vis)
    live = vis[: dead.start()] if dead is not None else vis
    # 阻断名单先收——main 是 BFS 首件，其 preamble 的 PreventPackageFromLoading
    # 在一切 \usepackage 记账前就位（scrlfile 语义即声明顺序无关的运行时拦截）。
    _harvest_prevented(ctx, preamble)
    for match in _PKG_RE.finditer(preamble):
        for raw in match.group(1).split(","):
            name = clean_decl_name(raw)
            if name is not None:
                _record_dep(ctx, rel, name, "package")
    for match in _CLS_RE.finditer(preamble):
        name = clean_decl_name(match.group(3))
        if name is not None:
            _record_dep(ctx, rel, name, "class")
        if match.group(1) == "documentstyle":
            ctx.latex209 = True
            _scan_docstyle_opts(ctx, rel, match.group(2))
    _scan_inputs(ctx, live, rel, queue)


def _harvest_prevented(ctx: _ScanCtx, preamble: str) -> None:
    r"""``\PreventPackageFromLoading`` 阻断名单并入 ctx.prevented（逗号分名）。"""
    for match in _PREVENT_RE.finditer(preamble):
        for raw_name in match.group(1).split(","):
            pname = clean_decl_name(raw_name)
            if pname is not None:
                ctx.prevented.add(pname)


def _scan_docstyle_opts(ctx: _ScanCtx, rel: str, optspan: str | None) -> None:
    r"""``\documentstyle[opts]`` 非内核选项登记为 package 依赖。

    209 选项位即 ``<opt>.sty`` 加载（a 带宏包依赖此前全盲：flags 只扫
    ``\usepackage``）；内核选项名（12pt/twocolumn 族）不是样式文件，跳过。
    """
    for raw_opt in (optspan or "").split(","):
        opt = clean_decl_name(raw_opt)
        if opt is not None and opt not in _KERNEL_OPTS:
            _record_dep(ctx, rel, opt, "package")
            if opt not in ctx.docstyle_opts:
                ctx.docstyle_opts.append(opt)


def _dep_signal(dep: DepProbe, blob: str) -> tuple[str, str] | None:
    """单依赖 → (信号, note)；无已知映射 → None。"""
    base = dep.name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if dep.fname.lower().endswith(".eps"):
        return "xelatex", f"{dep.fname} → xelatex（tectonic xdvipdfmx 硬墙）"
    sig = _PKG_SIGNALS.get(base)
    if sig is None and (
        base in PSTRICKS_PKG_NAMES or base.startswith(PST_PKG_PREFIXES)
    ):
        sig = ("xelatex", f"{base} pstricks 家族 → xelatex")
    if sig is None and base in BITMAP_FONT_PKG_NAMES:
        sig = ("tectonic_risky", f"{base} 位图字体包 → tectonic 高风险")
    if sig is None:
        return None
    kind, note = sig
    if kind == "shell_escape" and _MINTED_FROZEN_RE.search(blob):
        # frozencache 实测 tectonic bundle v2.6 兼容 v2 缓存（§4.2）
        return "tectonic", "minted frozencache → tectonic 优先"
    return kind, note


def _apply_signals(ctx: _ScanCtx) -> None:
    """依赖表 + blob → 路由信号聚合进 prefer_engine/flags/notes。"""
    rep = ctx.rep
    blob = "\n".join(ctx.blob_parts)
    signals: list[str] = []
    for dep in rep.deps:
        if dep.kind == "package" and dep.name in ctx.prevented:
            continue  # 阻断名单内包不加载——其依赖信号一并豁免（防 FP 旗标）
        sig = _dep_signal(dep, blob)
        if sig is None:
            continue
        signals.append(sig[0])
        if sig[1] not in rep.notes:
            rep.notes.append(sig[1])
    if "shell_escape" in signals:
        rep.flags.append("-shell-escape")
    if "xelatex" in signals:
        rep.prefer_engine = "xelatex"  # 硬墙信号压一切
    elif "tectonic" in signals:
        rep.prefer_engine = "tectonic"
    _append_diag_notes(ctx)
    if not rep.index_available:
        rep.notes.append("tlpdb 索引不可用——missing 集含未证实项")
    if rep.missing:
        rep.notes.append("missing: " + ", ".join(rep.missing))


def _append_diag_notes(ctx: _ScanCtx) -> None:
    r"""路由诊断注记聚合（只播报不改决策）。

    209/docstyle_opts/阻断名单/SWP/交互读/psfile/.mf 各命中面。
    """
    rep = ctx.rep
    if ctx.latex209:
        rep.notes.append(
            "\\documentstyle → latex209_suspect（试编不定死，fixloop gate 兜底拒）"
        )
    if ctx.docstyle_opts:
        rep.notes.append(
            "docstyle_opts: "
            + ", ".join(ctx.docstyle_opts)
            + " → 209 选项位即 .sty 加载，已按 package 依赖登记"
        )
    if ctx.prevented:
        rep.notes.append(
            "PreventPackageFromLoading: "
            + ", ".join(sorted(ctx.prevented))
            + " → 声明≠加载，missing/装包/信号记账已抑制"
        )
    if ctx.swp:
        rep.notes.append(
            "SWP/SW 源指纹（TCIDATA/tcilatex）"
            " → tcilatex.tex 走 vendor stub 链，路由不拒"
        )
    if ctx.interactive:
        rep.notes.append(
            f"终端交互读原语 \\typein/\\read-1 ×{ctx.interactive}"
            " → stdin=DEVNULL 已兜底防挂（活性未区分，纯诊断）"
        )
    if ctx.psfile:
        rep.notes.append(
            f"dvips-only \\special{{psfile}} ×{ctx.psfile}"
            " → xelatex/tectonic 均不渲染，图件将缺（需 dvips 通道或预转换）"
        )
    if any(p.suffix.lower() == ".mf" for p in ctx.root.rglob("*")):
        rep.notes.append(
            "包内 .mf METAFONT 源 → tectonic 无 mf 链（xelatex 视 mktexfm 配置），"
            "真字体需求时字形必缺"
        )


def target_probe(
    work_dir: Path | str, main_rel: str, deps_index: TlpdbIndex | None = None
) -> ProbeReport:
    r"""静态解析声明依赖 → ProbeReport（编译前 missing_file 预判 + 路由信号）。

    ``deps_index=None`` → `TlpdbIndex.ensure` 惰性装载（落盘缓存缺席才拉
    ~2.8MB tlpdb.xz——fixloop 反正要用）；显式传入索引实例可跳过网络。
    索引不可得时非本地依赖记 ``missing`` + ``index_available=False``。
    """
    index = deps_index if deps_index is not None else _load_index()
    rep = ProbeReport(index_available=index is not None)
    root = safe_resolve(Path(work_dir))
    main = safe_resolve(root / main_rel) if root is not None else None
    if (
        root is None
        or main is None
        or not safe_is_file(main)
        or not main.is_relative_to(root)
    ):
        rep.notes.append(f"main {main_rel} 不存在或越出 work_dir——空探针")
        return rep
    ctx = _ScanCtx(root=root, cwd=main.parent, index=index, rep=rep)
    queue = [main]
    visited: set[Path] = set()
    while queue:
        tex = queue.pop(0)
        if tex in visited or not safe_is_file(tex) or not tex.is_relative_to(root):
            continue
        visited.add(tex)
        rel = tex.relative_to(root).as_posix()
        rep.inputs.append(rel)
        _scan_file(ctx, tex, rel, queue)
    _apply_signals(ctx)
    return rep


# ================================================================ 权威集差分
def _norm_dep(p: str) -> str:
    """依赖路径规范化：反斜杠→posix、PurePosixPath 去 ``./`` 与重复分隔。"""
    return PurePosixPath(p.replace("\\", "/")).as_posix()


def _dep_match(recorded: frozenset[str], fname: str) -> bool:
    """判 `fname` 是否见于权威集：规范化全路径优先、basename 兜底。"""
    norm = _norm_dep(fname)
    if norm in recorded:
        return True
    base = norm.rsplit("/", 1)[-1]
    return any(r.rsplit("/", 1)[-1] == base for r in recorded)


@dataclass(frozen=True, slots=True)
class DepsDiff:
    """`deps_diff` 产物：expected 声明/期望集 vs recorded 权威输入集。"""

    authoritative: bool  # recorded 是否存在（False = 引擎未产 .fls/.mk）
    expected: frozenset[str]
    recorded: frozenset[str]

    @property
    def seen(self) -> list[str]:
        """期望 ∩ 权威——曾被读取（missing_file 报错 = 路径/时序问题）。"""
        return sorted(self.expected & self.recorded)

    @property
    def unseen(self) -> list[str]:
        """期望 - 权威——从未被读取（真缺失判据；非权威时=全量声明）。"""
        return sorted(self.expected - self.recorded)

    @property
    def extra(self) -> list[str]:
        """权威 - 期望——权威集多出的隐式输入（kpsewhich 解析产物等）。"""
        return sorted(self.recorded - self.expected)

    def saw(self, fname: str) -> bool | None:
        """判 `fname` 是否被权威集记录；无记录集 → None（不可判，非 False）。"""
        if not self.authoritative:
            return None
        return _dep_match(self.recorded, fname)


def deps_diff(expected: Iterable[str], recorded: Iterable[str] | None) -> DepsDiff:
    """差分 expected 声明集 vs `res.deps` 权威输入集 → DepsDiff。

    ``recorded=None``（引擎未产依赖记录）→ ``authoritative=False``：
    无判据而非全缺，``unseen`` 语义退化为「全部声明」。
    """
    exp = frozenset(_norm_dep(p) for p in expected)
    if recorded is None:
        return DepsDiff(authoritative=False, expected=exp, recorded=frozenset())
    rec = frozenset(_norm_dep(p) for p in recorded)
    return DepsDiff(authoritative=True, expected=exp, recorded=rec)


def dep_seen(recorded: Iterable[str] | None, fname: str) -> bool | None:
    """判 `recorded`（res.deps）是否记录过 `fname`；记录缺席 → None。

    fixloop/judge 诊断消费点：missing_file 缺失文件曾被 .fls/.mk 记录
    → 路径/时序问题（勿装包）；未记录 → 真缺失（走 install_file）。
    """
    if recorded is None:
        return None
    return _dep_match(frozenset(_norm_dep(p) for p in recorded), fname)
