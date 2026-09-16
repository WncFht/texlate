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

from texlate.textutil import decode_tex

from .mask import visible_tex

if TYPE_CHECKING:
    from collections.abc import Iterable

    from texlate.compile.fixloop.ctan import TlpdbIndex

    from .engine import CompRes

__all__ = [
    "DepProbe",
    "DepsDiff",
    "ProbeReport",
    "consume_deps",
    "dep_seen",
    "deps_diff",
    "target_probe",
]

_PKG_RE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_CLS_RE = re.compile(
    r"\\(documentclass|documentstyle|LoadClass)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}"
)
_INPUT_BRACED_RE = re.compile(r"\\(?:input|include|InputIfFileExists)\b\s*\{([^}]+)\}")
_INPUT_BARE_RE = re.compile(r"\\input\s+([^\s{}%\\]+)")
_DOC_BEGIN_RE = re.compile(r"\\begin\s*\{document\}")
#: 声明名噪声过滤（fixloop static_precheck 同款）：滤掉 `\@tempb` 类误捕。
_NAME_RE = re.compile(r"^[\w./+-]+$")
_MINTED_FROZEN_RE = re.compile(r"frozencache")

#: 声明包名 → (信号, 说明)。信号集：``xelatex`` = tectonic xdvipdfmx 硬墙；
#: ``shell_escape`` = 需 ``\write18``（xelatex flags 承载，tectonic
#: ``--untrusted`` 拒放）；``tectonic_risky`` = bundle 位图字体高风险标记
#: （失败后换引擎）。
_PKG_SIGNALS: dict[str, tuple[str, str]] = {
    "pstricks": ("xelatex", "pstricks → xelatex（tectonic xdvipdfmx 硬墙）"),
    "minted": ("shell_escape", "minted → 需 -shell-escape（pygments \\write18）"),
    "bbm": ("tectonic_risky", "bbm 位图字体包 → tectonic 高风险"),
    "bbmfonts": ("tectonic_risky", "bbmfonts 位图字体包 → tectonic 高风险"),
    "dsfont": ("tectonic_risky", "dsfont 位图字体包 → tectonic 高风险"),
    "bbold": ("tectonic_risky", "bbold 位图字体包 → tectonic 高风险"),
    "yfonts": ("tectonic_risky", "yfonts 位图字体包 → tectonic 高风险"),
    "wasy": ("tectonic_risky", "wasy 位图字体包 → tectonic 高风险"),
    "wasysym": ("tectonic_risky", "wasysym 位图字体包 → tectonic 高风险"),
}
_PST_PREFIX = "pst-"  # pstricks 家族包（pst-plot/pst-node/…）同走 xelatex


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
    """`target_probe` 扫描状态：声明去重 + blob 收集 + latex209 标记。"""

    root: Path
    index: TlpdbIndex | None
    rep: ProbeReport
    declared: set[tuple[str, str]] = field(default_factory=set)
    blob_parts: list[str] = field(default_factory=list)
    latex209: bool = False


def _load_index() -> TlpdbIndex | None:
    """默认 tlpdb 离线索引（`TlpdbIndex.ensure` 同款惰性缓存；失败 → None）。"""
    from texlate.compile.fixloop.ctan import (  # noqa: PLC0415  # 延迟: 防循环
        TlpdbIndex,
    )

    try:
        return TlpdbIndex.ensure()
    except Exception:  # noqa: BLE001  # 索引拉取失败降级「无索引」判定，不阻塞探针
        return None


def _clean_name(raw: str) -> str | None:
    """声明参数 → 干净文件名；含控制序列/括号/注释符的噪声 token → None。"""
    name = raw.strip().strip('"').strip()
    if not name or not _NAME_RE.match(name):
        return None
    return name


def _find_local(root: Path, decl_dir: Path, fname: str) -> Path | None:
    """声明文件目录 → 工程根 两跳本地解析（对齐 kpathsea cwd+TEXINPUTS 序）。"""
    for base in (decl_dir, root):
        cand = (base / fname).resolve()
        if cand.is_file() and cand.is_relative_to(root):
            return cand
    return None


def _resolve_dep(
    root: Path, decl_dir: Path, name: str, kind: str, index: TlpdbIndex | None
) -> tuple[str, str, str]:
    """单依赖三分支解析 → (fname, resolved, detail)。"""
    ext = {"package": ".sty", "class": ".cls", "input": ".tex"}[kind]
    fname = name if Path(name).suffix else name + ext
    local = _find_local(root, decl_dir, fname)
    if local is not None:
        return fname, "local", local.relative_to(root).as_posix()
    if index is not None:
        pkgs = index.query(PurePosixPath(fname).name)
        if pkgs:
            return fname, "tl_pkg", pkgs[0]
    return fname, "missing", ""


def _record_dep(
    ctx: _ScanCtx, decl_dir: Path, rel: str, name: str, kind: str
) -> DepProbe:
    """解析 + 登记一条声明依赖（同 kind+fname 去重，保首个声明位）。"""
    fname, resolved, detail = _resolve_dep(ctx.root, decl_dir, name, kind, ctx.index)
    probe = DepProbe(
        name=name,
        kind=kind,
        fname=fname,
        resolved=resolved,
        detail=detail,
        declared_in=rel,
    )
    if (kind, fname) in ctx.declared:
        return probe
    ctx.declared.add((kind, fname))
    ctx.rep.deps.append(probe)
    if resolved == "missing":
        ctx.rep.missing.append(fname)
        ctx.rep.missing.sort()
    elif resolved == "tl_pkg" and detail not in ctx.rep.tl_packages:
        ctx.rep.tl_packages.append(detail)
        ctx.rep.tl_packages.sort()
    return probe


def _scan_file(ctx: _ScanCtx, tex: Path, rel: str, queue: list[Path]) -> None:
    r"""扫单文件：preamble 取 package/class 声明，全文取 `\input` 并入队。"""
    vis = visible_tex(decode_tex(tex.read_bytes()))
    ctx.blob_parts.append(vis)
    m = _DOC_BEGIN_RE.search(vis)
    preamble = vis[: m.start()] if m is not None else vis
    decl_dir = tex.parent
    for match in _PKG_RE.finditer(preamble):
        for raw in match.group(1).split(","):
            name = _clean_name(raw)
            if name is not None:
                _record_dep(ctx, decl_dir, rel, name, "package")
    for match in _CLS_RE.finditer(preamble):
        name = _clean_name(match.group(2))
        if name is not None:
            _record_dep(ctx, decl_dir, rel, name, "class")
        if match.group(1) == "documentstyle":
            ctx.latex209 = True
    for match in (*_INPUT_BRACED_RE.finditer(vis), *_INPUT_BARE_RE.finditer(vis)):
        name = _clean_name(match.group(1))
        if name is None:
            continue
        probe = _record_dep(ctx, decl_dir, rel, name, "input")
        if probe.resolved == "local" and probe.fname.lower().endswith(".tex"):
            queue.append((ctx.root / probe.detail).resolve())


def _dep_signal(dep: DepProbe, blob: str) -> tuple[str, str] | None:
    """单依赖 → (信号, note)；无已知映射 → None。"""
    base = dep.name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if dep.fname.lower().endswith(".eps"):
        return "xelatex", f"{dep.fname} → xelatex（tectonic xdvipdfmx 硬墙）"
    sig = _PKG_SIGNALS.get(base)
    if sig is None and base.startswith(_PST_PREFIX):
        sig = ("xelatex", f"{base} pstricks 家族 → xelatex")
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
    if ctx.latex209:
        rep.notes.append(
            "\\documentstyle → latex209_suspect（试编不定死，fixloop gate 兜底拒）"
        )
    if not rep.index_available:
        rep.notes.append("tlpdb 索引不可用——missing 集含未证实项")
    if rep.missing:
        rep.notes.append("missing: " + ", ".join(rep.missing))


def target_probe(
    work_dir: Path | str, main_rel: str, deps_index: TlpdbIndex | None = None
) -> ProbeReport:
    r"""静态解析声明依赖 → ProbeReport（编译前 missing_file 预判 + 路由信号）。

    ``deps_index=None`` → `TlpdbIndex.ensure` 惰性装载（落盘缓存缺席才拉
    ~2.8MB tlpdb.xz——fixloop 反正要用）；显式传入索引实例可跳过网络。
    索引不可得时非本地依赖记 ``missing`` + ``index_available=False``。
    """
    root = Path(work_dir).resolve()
    index = deps_index if deps_index is not None else _load_index()
    rep = ProbeReport(index_available=index is not None)
    main = (root / main_rel).resolve()
    if not main.is_file():
        rep.notes.append(f"main {main_rel} 不存在——空探针")
        return rep
    ctx = _ScanCtx(root=root, index=index, rep=rep)
    queue = [main]
    visited: set[Path] = set()
    while queue:
        tex = queue.pop(0)
        if tex in visited or not tex.is_file() or not tex.is_relative_to(root):
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


def consume_deps(res: CompRes, expected: Iterable[str] | None = None) -> DepsDiff:
    """`res.deps` → DepsDiff 诊断视图（`compiled_dependencies` 权威集消费点）。

    ``expected=None`` → 只用 ``saw()`` 判据（missing_file payload 是否曾被
    记录）；给 expected（如 `ProbeReport.inputs` 或声明 fname 集）则同时
    得 seen/unseen/extra 三分量。
    """
    return deps_diff(expected or (), res.deps)
