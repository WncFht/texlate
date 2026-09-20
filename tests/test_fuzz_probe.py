r"""probe.py 性质 fuzz——合成工程树/字节汤/对抗 main_rel 下的不变量 + 独立 oracle 对拍。

oracle 方法：发生器落盘时逐条登记声明日志（offset/kind/name/form/masked），
期望报告完全由**生成侧事实**重算——不复用 impl 的扫描/解析/差分路径。
region 边界（preamble/死尾）与文件名清洗按 docs/spec/compile.md 语义独立实现；
解码/遮蔽走共享件 ``decode_tex``/``visible_tex``（独立受测，且只有等长
遮蔽才能保证 offset 语义一致）。

核心不变量：

- ``target_probe`` 任意输入不抛（字节汤/目录当 .tex/空文件/越界 main_rel/
  不存在 work_dir）；同树两次调用逐字段相等；
- ``rep.inputs``：BFS 序、main 打头、root 相对 posix、无重复、逐项现存文件；
- ``rep.deps``：(kind,fname) 唯一；resolved ∈ {local,tl_pkg,missing}；
  ``detail==""`` iff missing；local → ``root/detail`` 为文件；
  ``declared_in ∈ inputs``；tl_pkg → ``detail == index.query(basename)[0]``；
- ``rep.missing``：有序多重集（跨 kind 同 fname 可重）⊆ missing-resolved
  dep 的 fname 计数值；``rep.tl_packages`` 有序唯一 == tl_pkg detail 集；
- ``prefer_engine`` ∈ {None,xelatex,tectonic}，``flags`` ⊆ {-shell-escape}；
- ``deps_diff``/``dep_seen``：seen/unseen/extra == 规范化集合差分；
  ``saw`` = 规范化全路径命中 ∨ basename 兜底，且 ⊇ seen；recorded=None →
  三值 None；``dep_seen(rec,f) == deps_diff([],rec).saw(f)``。
"""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import pytest
from _fuzzkit import fuzz_rng

from texlate.compile.ctan import TlpdbIndex
from texlate.compile.engine import (
    BITMAP_FONT_PKG_NAMES,
    PST_PKG_PREFIXES,
    PSTRICKS_PKG_NAMES,
)
from texlate.compile.mask import visible_tex
from texlate.compile.probe import (
    ProbeReport,
    dep_seen,
    deps_diff,
    target_probe,
)
from texlate.textutil import decode_tex

if TYPE_CHECKING:
    import random
    from collections.abc import Iterable

#: 注入用迷你 tlpdb 索引——basename → [TL 包]（全离线，绝不 ensure）。
_INDEX = TlpdbIndex(
    {
        "amsmath.sty": ["amsmath"],
        "article.cls": ["latex"],
        "bbm.sty": ["bbm"],
        "hyperref.sty": ["hyperref"],
        "minted.sty": ["minted"],
        "pst-node.sty": ["pst-node"],
        "pstricks.sty": ["pstricks"],
        "revtex4-2.cls": ["revtex"],
        "shared.tex": ["somebundle"],
        "xspace.sty": ["xspace", "tools"],
    }
)

_EXT_OF = {"package": ".sty", "class": ".cls", "input": ".tex"}
_O_DOC_BEGIN = re.compile(r"\\begin\s*\{document\}")
_O_DEAD = re.compile(r"\\end\s*\{document\}|\\endinput\b")
_O_NAME = re.compile(r"[\w./+-]+")

#: 发生器概率常量（PLR2004：阈值字面量一律提名）。
_P_MASKED_DECL = 0.25
_P_CLASS_DECL = 0.7
_P_SUB_CLS = 0.3
_P_DOCSTYLE = 0.08
_P_NO_DOC = 0.08
_P_DEAD_TAIL = 0.35
_P_DEAD_BEFORE_DOC = 0.08
_P_FROZEN = 0.15
_P_MATERIALIZE = 0.55
_P_JUNK_RAND = 0.35
_P_JUNK_TRUNC = 0.6
_P_JUNK_EMPTY = 0.75
_P_JUNK_DIR = 0.9
_P_REC_NONE = 0.12
_P_EXTRA_DIR = 0.3
_P_SEED_PATH = 0.4
_R_INPUT = 0.5
_R_INCLUDE = 0.7
_R_OPT = 0.85

_NAME_POOL_PKG = [
    "amsmath",
    "hyperref",
    "ghostpkg",
    "localpkg",
    "bbm",
    "pstricks",
    "pst-node",
    "pstricks-add",
    "minted",
    "fontspec",
    "xspace",
    "zzbogus",
]
_NAME_POOL_CLS = ["article", "myclass", "revtex4-2", "ghostcls", "standalone"]
_NAME_POOL_IN = [
    "macros",
    "chaps/one",
    "chaps/two",
    "shared",
    "data/table",
    "g",
    "h.tex",
    "UP.TEX",
    "plot.eps",
    "style/minted.sty",
    "fig.pgf",
    "zzabsent",
    "a+b",
    "x-y",
    "数据",
]
#: ``\InputIfFileExists`` 专用池——与强制 ``\input`` 池不相交（dedup 顺序
#: 吞 missing 是已钉缺陷，等值层不混入该形态）。
_NAME_POOL_OPT = ["optcfg", "localcfg", "extras/setup"]
#: bare ``\input`` 池——含清洗即滤的噪声 token（逗号/@ 不入 ``[\w./+-]``）。
_NAME_POOL_BARE = ["plainmac", "sub/plain", "b.tex", "weird,bad", "@tempb"]
_NAME_POOL_MASKED = ["maskedpkg", "ghostin", "verbpkg"]

_FILLER = (
    "body text with no commands at all\n",
    "\\def\\foo{bar}\n",
    "\\newcommand{\\baz}[1]{#1}\n",
    "more filler } { unbalanced\n",
    "\\section{Intro}\n",
)


@dataclass(slots=True)
class _Decl:
    """生成侧声明日志：offset 即原文位置（等长遮蔽视图同 offset）。"""

    kind: str  # "package" | "class" | "input"
    name: str  # 声明名原样
    file_rel: str = ""
    offset: int = 0
    optional: bool = False  # \InputIfFileExists
    form: str = "braced"  # input 专用：braced | bare
    masked: bool = False  # 注释/verbatim 内或清洗即滤——对扫描不可见
    docstyle: bool = False  # \documentstyle → latex209_suspect
    seq: int = 0  # 同 offset 多名的稳定序


@dataclass(slots=True)
class _Log:
    """声明日志收集器：登记时回填 file_rel/offset/seq。"""

    decls: list[_Decl] = field(default_factory=list)
    seq: int = 0

    def emit(
        self,
        parts: list[str],
        file_rel: str,
        piece: str,
        decls: Iterable[_Decl] = (),
    ) -> None:
        """拼接一段文本并按 offset 登记其中每个声明名。"""
        off = sum(len(p) for p in parts)
        parts.append(piece)
        for d in decls:
            d.file_rel = file_rel
            d.offset = off
            d.seq = self.seq
            self.seq += 1
            self.decls.append(d)


@dataclass(slots=True)
class _Pools:
    """单树名池抽样结果。"""

    pkg: list[str]
    cls: list[str]
    inp: list[str]
    opt: list[str]
    bare: list[str]


def _o_clean(raw: str) -> str | None:
    """独立版清洗：strip → 剥双引号 → strip → ``[\\w./+-]+`` 全匹配。"""
    name = raw.strip().strip('"').strip()
    return name if name and _O_NAME.fullmatch(name) else None


def _o_resolve(
    root: Path, cwd: Path, name: str, kind: str, index: TlpdbIndex
) -> tuple[str, str, str]:
    """独立版三分支解析：cwd 单跳 local → index basename → missing。

    fname 补齐规则与 impl 逐条对应：``\\input`` 原名带扩展名按原名找、无扩展名
    补 .tex；package/class 恒补扩展名（除非名已以其结尾）——
    ``\\usepackage{weird.dotted}`` 引擎实找 ``weird.dotted.sty``。
    """
    ext = _EXT_OF[kind]
    if kind == "input":
        fname = name if PurePosixPath(name).suffix else name + ext
    else:
        fname = name if name.lower().endswith(ext) else name + ext
    cand = (cwd / fname).resolve()
    if cand.is_file() and cand.is_relative_to(root):
        return fname, "local", cand.relative_to(root).as_posix()
    hits = index.query(PurePosixPath(fname).name)
    if hits:
        return fname, "tl_pkg", hits[0]
    return fname, "missing", ""


def _scan_order(d: _Decl) -> tuple[int, int, int, int]:
    """impl 扫描序：pkg → class → input(braced 先 bare 后)，同级按 offset。"""
    cat = {"package": 0, "class": 1, "input": 2}[d.kind]
    bare = 1 if (d.kind == "input" and d.form == "bare") else 0
    return cat, bare, d.offset, d.seq


class _OExpect:
    """oracle 重算的期望报告。"""

    def __init__(self) -> None:
        self.inputs: list[str] = []
        self.deps: list[tuple[str, str, str, str, str, str]] = []
        self.missing: list[str] = []
        self.tl: set[str] = set()
        self.blobs: list[str] = []
        self.declared: set[tuple[str, str]] = set()
        self.missing_recorded: set[tuple[str, str]] = set()
        self.latex209 = False


@dataclass(slots=True)
class _OCtx:
    """oracle BFS 上下文：root/cwd/index/声明索引/队列/期望累积。"""

    root: Path
    cwd: Path
    index: TlpdbIndex
    by_file: dict[str, list[_Decl]]
    queue: list[Path]
    exp: _OExpect = field(default_factory=_OExpect)

    def note_missing(self, d: _Decl, fname: str, resolved: str) -> None:
        """missing 登记（impl ``missing_recorded`` 镜像）：optional 缺席不计；
        dedup 命中的后续硬引用仍落 missing_file——同 (kind,fname) 只补一次。"""
        if (
            resolved == "missing"
            and not d.optional
            and (d.kind, fname) not in self.exp.missing_recorded
        ):
            self.exp.missing_recorded.add((d.kind, fname))
            self.exp.missing.append(fname)

    def scan_file(self, tex: Path, rel: str) -> None:
        """单文件 oracle 扫：region 边界过滤 + 解析登记 + local .tex 入队。"""
        vis = visible_tex(decode_tex(tex.read_bytes()))
        self.exp.blobs.append(vis)
        mb = _O_DOC_BEGIN.search(vis)
        pre_end = mb.start() if mb is not None else len(vis)
        md = _O_DEAD.search(vis)
        live_end = md.start() if md is not None else len(vis)
        for d in sorted(self.by_file.get(rel, []), key=_scan_order):
            if d.masked:
                continue
            if d.kind == "input" and d.offset >= live_end:
                continue
            if d.kind != "input" and d.offset >= pre_end:
                continue
            if d.docstyle:
                self.exp.latex209 = True
            fname, resolved, detail = _o_resolve(
                self.root, self.cwd, d.name, d.kind, self.index
            )
            if (
                d.kind == "input"
                and resolved == "local"
                and fname.lower().endswith(".tex")
            ):
                self.queue.append((self.root / detail).resolve())
            if (d.kind, fname) in self.exp.declared:
                self.note_missing(d, fname, resolved)
                continue
            self.exp.declared.add((d.kind, fname))
            self.exp.deps.append((d.name, d.kind, fname, resolved, detail, rel))
            self.note_missing(d, fname, resolved)
            if resolved == "tl_pkg":
                self.exp.tl.add(detail)


def _oracle_signals(
    deps: list[tuple[str, str, str, str, str, str]], blobs: list[str]
) -> tuple[str | None, list[str]]:
    """依赖表 + blob → (prefer_engine, flags)：信号表按规格独立重述。"""
    frozen = "frozencache" in "\n".join(blobs)
    signals: list[str] = []
    for name, _kind, fname, _res, _det, _rel in deps:
        base = name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        sig = None
        if fname.lower().endswith(".eps"):
            sig = "xelatex"
        elif base == "minted":
            sig = "tectonic" if frozen else "shell_escape"
        elif base in PSTRICKS_PKG_NAMES or base.startswith(PST_PKG_PREFIXES):
            sig = "xelatex"
        elif base in BITMAP_FONT_PKG_NAMES:
            sig = "tectonic_risky"
        if sig is not None:
            signals.append(sig)
    prefer = None
    if "xelatex" in signals:
        prefer = "xelatex"
    elif "tectonic" in signals:
        prefer = "tectonic"
    return prefer, ["-shell-escape"] if "shell_escape" in signals else []


def _oracle(
    root: Path, main_rel: str, decls: list[_Decl], index: TlpdbIndex
) -> dict[str, object] | None:
    """由生成日志独立重算期望报告；main 不可达 → None（空报告）。"""
    root = Path(root).resolve()
    main = (root / main_rel).resolve()
    if not main.is_file() or not main.is_relative_to(root):
        return None
    cwd = main.parent
    by_file: dict[str, list[_Decl]] = {}
    for d in decls:
        by_file.setdefault(d.file_rel, []).append(d)
    ctx = _OCtx(root=root, cwd=cwd, index=index, by_file=by_file, queue=[main])
    visited: set[Path] = set()
    while ctx.queue:
        tex = ctx.queue.pop(0)
        if tex in visited or not tex.is_file() or not tex.is_relative_to(root):
            continue
        visited.add(tex)
        rel = tex.relative_to(root).as_posix()
        ctx.exp.inputs.append(rel)
        ctx.scan_file(tex, rel)
    prefer, flags = _oracle_signals(ctx.exp.deps, ctx.exp.blobs)
    return {
        "inputs": ctx.exp.inputs,
        "deps": sorted(ctx.exp.deps),
        "missing": sorted(ctx.exp.missing),
        "tl_packages": sorted(ctx.exp.tl),
        "prefer_engine": prefer,
        "flags": flags,
        "latex209": ctx.exp.latex209,
    }


@dataclass(slots=True)
class _Gen:
    """单文件生成器：rng/log/pools 随 self 走，方法只收 parts/rel。"""

    rng: random.Random
    log: _Log
    pools: _Pools

    def masked_head(self, parts: list[str], rel: str) -> None:
        if self.rng.random() >= _P_MASKED_DECL:
            return
        n = self.rng.choice(_NAME_POOL_MASKED)
        self.log.emit(
            parts,
            rel,
            f"% \\usepackage{{{n}}}\n",
            [_Decl(kind="package", name=n, masked=True)],
        )

    def class_decl(self, parts: list[str], rel: str, *, is_main: bool) -> None:
        rng = self.rng
        if rng.random() >= _P_CLASS_DECL or not (is_main or rng.random() < _P_SUB_CLS):
            return
        cls = rng.choice(self.pools.cls)
        if is_main and rng.random() < _P_DOCSTYLE:
            self.log.emit(
                parts,
                rel,
                f"\\documentstyle{{{cls}}}\n",
                [_Decl(kind="class", name=cls, docstyle=True)],
            )
        else:
            self.log.emit(
                parts,
                rel,
                f"\\documentclass{{{cls}}}\n",
                [_Decl(kind="class", name=cls)],
            )

    def pkg_decls(self, parts: list[str], rel: str) -> None:
        rng = self.rng
        for _ in range(rng.randint(0, 3)):
            ks = rng.sample(self.pools.pkg, rng.randint(1, min(3, len(self.pools.pkg))))
            cmd = rng.choice(["usepackage", "RequirePackage"])
            opt = "[frozencache]" if rng.random() < _P_FROZEN else ""
            self.log.emit(
                parts,
                rel,
                f"\\{cmd}{opt}{{{','.join(ks)}}}\n",
                [_Decl(kind="package", name=k) for k in ks],
            )

    def dead_early(self, parts: list[str], rel: str) -> None:
        r"""``\endinput`` 先于 ``\begin{document}``：其间 pkg 仍在 preamble
        （impl 语义），input 已死——oracle 的 offset 模型天然复刻这条边界。"""
        parts.append("\\endinput\n")
        n = self.rng.choice(self.pools.pkg)
        self.log.emit(
            parts, rel, f"\\usepackage{{{n}}}\n", [_Decl(kind="package", name=n)]
        )
        n = self.rng.choice(self.pools.inp)
        self.log.emit(parts, rel, f"\\input{{{n}}}\n", [_Decl(kind="input", name=n)])

    def body_inputs(self, parts: list[str], rel: str) -> None:
        rng = self.rng
        for _ in range(rng.randint(0, 4)):
            roll = rng.random()
            if roll < _R_INPUT:
                n = rng.choice(self.pools.inp)
                self.log.emit(
                    parts, rel, f"\\input{{{n}}}\n", [_Decl(kind="input", name=n)]
                )
            elif roll < _R_INCLUDE:
                n = rng.choice(self.pools.inp)
                self.log.emit(
                    parts, rel, f"\\include{{{n}}}\n", [_Decl(kind="input", name=n)]
                )
            elif roll < _R_OPT:
                n = rng.choice(self.pools.opt)
                self.log.emit(
                    parts,
                    rel,
                    f"\\InputIfFileExists{{{n}}}{{}}{{}}\n",
                    [_Decl(kind="input", name=n, optional=True)],
                )
            else:
                n = rng.choice(self.pools.bare)
                self.log.emit(
                    parts,
                    rel,
                    f"\\input {n}\n",
                    [
                        _Decl(
                            kind="input",
                            name=n,
                            form="bare",
                            masked=_o_clean(n) is None,
                        )
                    ],
                )

    def dead_tail(self, parts: list[str], rel: str) -> None:
        if self.rng.random() >= _P_DEAD_TAIL:
            return
        parts.append(self.rng.choice(["\\end{document}\n", "\\endinput\n"]))
        n = self.rng.choice(self.pools.inp)
        self.log.emit(parts, rel, f"\\input{{{n}}}\n", [_Decl(kind="input", name=n)])
        n = self.rng.choice(self.pools.inp)
        self.log.emit(
            parts,
            rel,
            f"\\begin{{verbatim}}\n\\input{{{n}}}\n\\end{{verbatim}}\n",
            [_Decl(kind="input", name=n, masked=True)],
        )

    def file(self, rel: str, *, is_main: bool) -> str:
        """随机单文件文本 + 声明日志；布局覆盖 dead_before_doc/no_doc/dead_tail。"""
        parts: list[str] = []
        self.masked_head(parts, rel)
        self.class_decl(parts, rel, is_main=is_main)
        self.pkg_decls(parts, rel)
        layout_roll = self.rng.random()
        if layout_roll < _P_DEAD_BEFORE_DOC:
            self.dead_early(parts, rel)
        if layout_roll >= _P_DEAD_BEFORE_DOC + _P_NO_DOC:
            parts.append("\\begin{document}\n")
        parts.append(self.rng.choice(_FILLER))
        self.body_inputs(parts, rel)
        self.dead_tail(parts, rel)
        return "".join(parts)


def _gen_tree(rng: random.Random, root: Path) -> tuple[str, list[_Decl], TlpdbIndex]:
    """随机工程树：main 位随机 + 概率物化 .tex/.sty/.cls + 声明日志。"""
    main_rel = rng.choice(["main.tex", "main.tex", "d1/main.tex", "d1/d2/main.tex"])
    cwd = (root / main_rel).parent
    pools = _Pools(
        pkg=rng.sample(_NAME_POOL_PKG, rng.randint(4, len(_NAME_POOL_PKG))),
        cls=rng.sample(_NAME_POOL_CLS, rng.randint(2, len(_NAME_POOL_CLS))),
        inp=rng.sample(_NAME_POOL_IN, rng.randint(5, len(_NAME_POOL_IN))),
        opt=rng.sample(_NAME_POOL_OPT, rng.randint(1, len(_NAME_POOL_OPT))),
        bare=rng.sample(_NAME_POOL_BARE, rng.randint(2, len(_NAME_POOL_BARE))),
    )
    gen = _Gen(rng=rng, log=_Log(), pools=pools)
    # 物化：cwd 下按解析文件名落盘（kpathsea 基准 = main 所在目录）
    all_names = (
        [(n, ".sty") for n in pools.pkg]
        + [(n, ".cls") for n in pools.cls]
        + [(n, ".tex") for n in pools.inp + pools.opt + pools.bare]
    )
    tex_files: list[str] = []
    main_abs = (cwd / "main.tex").resolve()
    for name, ext in all_names:
        fname = name if PurePosixPath(name).suffix else name + ext
        if rng.random() >= _P_MATERIALIZE:
            continue
        p = cwd / fname
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        p.write_text("% generated\n", encoding="utf-8")
        if fname.lower().endswith(".tex") and p.resolve() != main_abs:
            tex_files.append(fname)
    main_abs.parent.mkdir(parents=True, exist_ok=True)
    main_abs.write_text(gen.file(main_rel, is_main=True), encoding="utf-8")
    for fname in rng.sample(tex_files, min(len(tex_files), rng.randint(0, 6))):
        p = cwd / fname
        rel = p.resolve().relative_to(root.resolve()).as_posix()
        p.write_text(gen.file(rel, is_main=False), encoding="utf-8")
    return main_rel, gen.log.decls, _INDEX


def _check_report(rep: ProbeReport, root: Path, index: TlpdbIndex) -> None:
    """ProbeReport 结构不变量——oracle 无关面，任何输入恒成立。"""
    assert isinstance(rep.index_available, bool)
    inputs = rep.inputs
    assert len(set(inputs)) == len(inputs), "inputs 含重复"
    for rel in inputs:
        assert not rel.startswith("/"), rel
        assert ".." not in PurePosixPath(rel).parts, rel
        assert (root / rel).is_file(), f"inputs 项非现存文件: {rel}"
    keyset = set()
    for d in rep.deps:
        assert d.kind in ("package", "class", "input")
        assert (d.kind, d.fname) not in keyset, f"(kind,fname) 重复: {d.fname}"
        keyset.add((d.kind, d.fname))
        assert d.resolved in ("local", "tl_pkg", "missing")
        assert _O_NAME.fullmatch(d.name), f"dep.name 噪声未滤: {d.name!r}"
        if d.resolved == "missing":
            assert d.detail == ""
        elif d.resolved == "local":
            assert (root / d.detail).is_file(), f"local detail 不在盘: {d.detail}"
        else:
            hits = index.query(PurePosixPath(d.fname).name)
            assert hits, f"tl_pkg 索引空命中: {d}"
            assert d.detail == hits[0], f"tl_pkg detail 与索引不符: {d}"
        assert d.declared_in in set(inputs), f"declared_in 未扫描: {d.declared_in}"
    assert rep.missing == sorted(rep.missing), "missing 未排序"
    resolved_missing = Counter(d.fname for d in rep.deps if d.resolved == "missing")
    for fname, cnt in Counter(rep.missing).items():
        assert resolved_missing[fname] >= cnt, f"missing 项无 missing dep: {fname}"
    assert rep.tl_packages == sorted(set(rep.tl_packages))
    assert set(rep.tl_packages) == {
        d.detail for d in rep.deps if d.resolved == "tl_pkg"
    }
    assert rep.prefer_engine in (None, "xelatex", "tectonic")
    assert set(rep.flags) <= {"-shell-escape"}


def test_fuzz_target_probe_structured_trees(tmp_path: Path) -> None:
    """生成侧 oracle 对拍：inputs 精确 BFS 序、deps 集合、missing 多重集、
    tl_packages/prefer_engine/flags 全等 + 结构不变量 + 确定性。"""
    rng = fuzz_rng(20260917)
    for i in range(140):
        tree = tmp_path / f"t{i}"
        tree.mkdir()
        main_rel, decls, index = _gen_tree(rng, tree)
        rep = target_probe(tree, main_rel, index)
        rep2 = target_probe(tree, main_rel, index)
        assert rep == rep2, f"iter {i}: 同树两跑不等"
        _check_report(rep, tree.resolve(), index)
        exp = _oracle(tree, main_rel, decls, index)
        assert exp is not None, "生成器保证 main 可达"
        assert rep.inputs == exp["inputs"], (
            f"iter {i}: inputs {rep.inputs} != {exp['inputs']}"
        )
        got_deps = sorted(
            (d.name, d.kind, d.fname, d.resolved, d.detail, d.declared_in)
            for d in rep.deps
        )
        assert got_deps == exp["deps"], (
            f"iter {i}: deps 差 {set(got_deps) ^ set(exp['deps'])}"
        )
        assert rep.missing == exp["missing"], (
            f"iter {i}: missing {rep.missing} != {exp['missing']}"
        )
        assert rep.tl_packages == exp["tl_packages"]
        assert rep.prefer_engine == exp["prefer_engine"], (
            f"iter {i}: prefer {rep.prefer_engine} != {exp['prefer_engine']}"
        )
        assert rep.flags == exp["flags"]
        assert any("latex209_suspect" in n for n in rep.notes) == exp["latex209"]
        if rep.missing:
            assert any(n.startswith("missing:") for n in rep.notes)


def test_fuzz_target_probe_adversarial(tmp_path: Path) -> None:
    """字节汤/截断/目录当 .tex/空文件/对抗 main_rel：恒不抛 + 结构不变量。"""
    rng = fuzz_rng(20260918)
    good_tex = (
        "\\documentclass{article}\n\\input{macros}\n\\begin{document}x\\end{document}\n"
    )
    main_rels = [
        "main.tex",
        "./main.tex",
        "sub//main.tex",
        "missing.tex",
        "",
        ".",
        "..",
        "/etc/passwd",
        "sub/../main.tex",
        "数据.tex",
        "\\win\\path.tex",
    ]
    for i in range(320):
        w = tmp_path / f"w{i}"
        w.mkdir()
        (w / "main.tex").write_text(good_tex, encoding="utf-8")
        (w / "macros.tex").write_text("\\usepackage{amsmath}\n", encoding="utf-8")
        r = rng.random()
        junk = w / f"j{i}.tex"
        if r < _P_JUNK_RAND:
            junk.write_bytes(rng.randbytes(rng.randint(0, 1500)))
        elif r < _P_JUNK_TRUNC:
            junk.write_bytes(good_tex.encode()[: rng.randrange(len(good_tex))])
        elif r < _P_JUNK_EMPTY:
            junk.write_bytes(b"")
        elif r < _P_JUNK_DIR:
            junk.mkdir()
        else:
            junk.write_bytes(b"%PDF-1.4\n" + rng.randbytes(80))
        if rng.random() < _P_EXTRA_DIR:
            (w / "dir.tex").mkdir(exist_ok=True)
        rel = rng.choice([*main_rels, f"j{i}.tex", "dir.tex"])
        rep = target_probe(w, rel, _INDEX)
        rep2 = target_probe(w, rel, _INDEX)
        assert rep == rep2, f"iter {i}: 非确定"
        _check_report(rep, w.resolve(), _INDEX)
        if rel in ("", ".", "..", "/etc/passwd", "missing.tex"):
            assert rep.inputs == []
            assert rep.deps == []


def test_target_probe_nonexistent_workdir_and_file_workdir(tmp_path: Path) -> None:
    """work_dir 不存在/是文件：早退空报告不抛。"""
    rep = target_probe(tmp_path / "nope", "main.tex", _INDEX)
    assert rep.inputs == []
    assert rep.deps == []
    f = tmp_path / "afile"
    f.write_text("x", encoding="utf-8")
    rep = target_probe(f, "main.tex", _INDEX)
    assert rep.inputs == []
    assert rep.deps == []


def test_target_probe_no_index_degrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``TlpdbIndex.ensure`` 抛 → _load_index 兜底 None：index_available=False
    + 未证实 missing 仍记录 + note 在场（绝不触网）。"""

    def _boom(*_a: object, **_k: object) -> TlpdbIndex:
        msg = "tripwire: 不得触网"
        raise RuntimeError(msg)

    monkeypatch.setattr(TlpdbIndex, "ensure", _boom)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{amsmath}\n"
        "\\usepackage{totallybogus}\n\\begin{document}x\\end{document}\n",
        encoding="utf-8",
    )
    rep = target_probe(tmp_path, "main.tex")
    assert rep.index_available is False
    assert rep.missing == ["amsmath.sty", "article.cls", "totallybogus.sty"]
    assert any("tlpdb" in n for n in rep.notes)
    assert any(n.startswith("missing:") for n in rep.notes)


def test_escape_symlink_input_is_missing(tmp_path: Path) -> None:
    r"""``\input`` 指向 root 外 symlink 目标：resolve 越界 → missing，不泄漏。"""
    outside = tmp_path.parent / f"{tmp_path.name}-secret.tex"
    outside.write_text("secret\n", encoding="utf-8")
    try:
        (tmp_path / "main.tex").write_text(
            "\\documentclass{article}\n\\input{esc}\n"
            "\\begin{document}x\\end{document}\n",
            encoding="utf-8",
        )
        (tmp_path / "esc.tex").symlink_to(outside)
        rep = target_probe(tmp_path, "main.tex", _INDEX)
        assert "esc.tex" in rep.missing
        assert rep.inputs == ["main.tex"]
    finally:
        outside.unlink()


def test_optional_tlpkg_still_lists_package(tmp_path: Path) -> None:
    r"""``\InputIfFileExists`` 的 tl_pkg 命中仍进 tl_packages——optional 只豁免
    missing 清单，不豁免装包候选集（``_record_dep`` 语义钉）。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\InputIfFileExists{shared.tex}{}{}\n"
        "\\begin{document}x\\end{document}\n",
        encoding="utf-8",
    )
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    by = {d.fname: d for d in rep.deps}
    assert by["shared.tex"].resolved == "tl_pkg"
    assert "somebundle" in rep.tl_packages
    assert rep.missing == []


def test_abs_main_rel_inside_root(tmp_path: Path) -> None:
    """main_rel 绝对路径但落在 root 内：接受且 inputs 归一为相对 posix。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
        encoding="utf-8",
    )
    rep = target_probe(tmp_path, str(tmp_path / "main.tex"), _INDEX)
    assert rep.inputs == ["main.tex"]


def test_signal_decision_table(tmp_path: Path) -> None:
    r"""prefer_engine/flags 决策表钉点——tectonic 格 fuzz 命中稀薄（~1/140），
    此处补确定性覆盖。

    - minted 裸用 → ``-shell-escape``、prefer None（shell_escape 不设 prefer）；
    - minted+frozencache → prefer tectonic、flag 清空（信号被 frozencache 改写）；
    - 再叠 ``.eps`` input dep → xelatex 硬墙压 tectonic（missing 态信号照样发）；
    - minted 裸用 + .eps → xelatex 与 ``-shell-escape`` 并存；
    - pstricks → xelatex；bbm → 仅 tectonic_risky note，prefer/flags 不动。
    """
    cases = [
        ("\\usepackage{minted}\n", "x\n", None, ["-shell-escape"]),
        ("\\usepackage[frozencache]{minted}\n", "x\n", "tectonic", []),
        (
            "\\usepackage[frozencache]{minted}\n",
            "\\input{plot.eps}\n",
            "xelatex",
            [],
        ),
        (
            "\\usepackage{minted}\n",
            "\\input{plot.eps}\n",
            "xelatex",
            ["-shell-escape"],
        ),
        ("\\usepackage{pstricks}\n", "x\n", "xelatex", []),
    ]
    for i, (pre, body, want_engine, want_flags) in enumerate(cases):
        w = tmp_path / f"c{i}"
        w.mkdir()
        (w / "main.tex").write_text(
            f"\\documentclass{{article}}\n{pre}"
            f"\\begin{{document}}\n{body}\\end{{document}}\n",
            encoding="utf-8",
        )
        rep = target_probe(w, "main.tex", _INDEX)
        assert rep.prefer_engine == want_engine, pre
        assert rep.flags == want_flags, pre
    w = tmp_path / "bbm"
    w.mkdir()
    (w / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{bbm}\n"
        "\\begin{document}x\\end{document}\n",
        encoding="utf-8",
    )
    rep = target_probe(w, "main.tex", _INDEX)
    assert rep.prefer_engine is None
    assert rep.flags == []
    assert any("tectonic 高风险" in n for n in rep.notes)


# ---------------------------------------------------------------- deps_diff / dep_seen

_PATH_ALPHABET = [*"ab/.\\-_+~ ", "中", "文", "..", "//", "/", ""]
_PATH_SEEDS = [
    "main.tex",
    "sub/foo.sty",
    "a/b/c.cls",
    "./x.tex",
    "a//b.tex",
    "../up.tex",
    "C:\\w\\y.sty",
    "texlive/amsmath.sty",
    "",
    "/",
    "数据.tex",
    "trail/",
    ".",
    "..",
]


def _rand_path(rng: random.Random) -> str:
    """路径汤：种子串或字母表随机拼接（含反斜杠/双斜杠/上跳/空）。"""
    if rng.random() < _P_SEED_PATH:
        return rng.choice(_PATH_SEEDS)
    return "".join(rng.choice(_PATH_ALPHABET) for _ in range(rng.randint(0, 14)))


def _o_norm(p: str) -> str:
    """独立规范化：反斜杠 → posix + PurePosixPath 归一。"""
    return PurePosixPath(p.replace("\\", "/")).as_posix()


def _o_match(recorded: frozenset[str], fname: str) -> bool:
    """独立判据：规范化全路径命中 ∨ basename 兜底。"""
    norm = _o_norm(fname)
    if norm in recorded:
        return True
    base = norm.rsplit("/", 1)[-1]
    return any(r.rsplit("/", 1)[-1] == base for r in recorded)


def test_fuzz_deps_diff_oracle() -> None:
    """随机 expected/recorded：seen/unseen/extra == 规范化集合差分；
    ``saw`` == 独立判据；``dep_seen`` 与 ``deps_diff([],rec).saw`` 恒等。"""
    rng = fuzz_rng(20260919)
    for _ in range(2500):
        expected = [_rand_path(rng) for _ in range(rng.randint(0, 8))]
        recorded: list[str] | None = (
            None
            if rng.random() < _P_REC_NONE
            else [_rand_path(rng) for _ in range(rng.randint(0, 8))]
        )
        diff = deps_diff(iter(expected), None if recorded is None else iter(recorded))
        exp_set = frozenset(_o_norm(p) for p in expected)
        assert diff.expected == exp_set
        if recorded is None:
            assert not diff.authoritative
            assert diff.recorded == frozenset()
            assert diff.unseen == sorted(exp_set)
            assert diff.seen == []
            assert diff.extra == []
            for _ in range(3):
                assert diff.saw(_rand_path(rng)) is None
            continue
        assert diff.authoritative
        rec_set = frozenset(_o_norm(p) for p in recorded)
        assert diff.recorded == rec_set
        assert diff.seen == sorted(exp_set & rec_set)
        assert diff.unseen == sorted(exp_set - rec_set)
        assert diff.extra == sorted(rec_set - exp_set)
        for _ in range(4):
            f = _rand_path(rng)
            want = _o_match(rec_set, f)
            assert diff.saw(f) is want, f"saw({f!r}) {diff.saw(f)} != {want}"
            assert dep_seen(iter(recorded), f) is want
            assert dep_seen(recorded, f) == deps_diff([], recorded).saw(f)
        # seen ⊆ saw-true：规范化命中者 basename 兜底必中
        for f in expected:
            if _o_norm(f) in rec_set:
                assert diff.saw(f) is True


def test_dep_seen_monotone_under_superset() -> None:
    """recorded 扩集只能把 saw 翻 False→True（basename 兜底单调性）。"""
    rng = fuzz_rng(20260920)
    for _ in range(800):
        rec = {_rand_path(rng) for _ in range(rng.randint(0, 6))}
        extra = {_rand_path(rng) for _ in range(rng.randint(0, 4))}
        f = _rand_path(rng)
        small = dep_seen(rec, f)
        big = dep_seen(rec | extra, f)
        assert small in (True, False)
        assert big in (True, False)
        assert not (small is True and big is False)


def test_deps_diff_generator_inputs() -> None:
    """Iterable 契约：生成器实参一次性消费、结果与 list 版一致。"""
    expected = ["a.tex", "b/c.sty"]
    recorded = ["a.tex", "x.sty"]
    assert deps_diff(iter(expected), iter(recorded)) == deps_diff(expected, recorded)
    assert dep_seen(iter(recorded), "a.tex") is True
    assert dep_seen(None, "a.tex") is None


# ---------------------------------------------------------------- 边界钉


def test_missing_survives_optional_then_mandatory_dedup(tmp_path: Path) -> None:
    r"""``\InputIfFileExists{g}`` + ``\input{g}`` 同 fname：后者是硬引用，
    编译必落 missing_file——``rep.missing`` 应含 g.tex（现漏报）。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\InputIfFileExists{ghost}{}{}\n"
        "\\input{ghost}\n"
        "\\begin{document}x\\end{document}\n",
        encoding="utf-8",
    )
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert "ghost.tex" in rep.missing


@pytest.mark.skipif(
    os.geteuid() == 0, reason="root 下 chmod 0 仍可读，无法复现权限拒绝"
)
def test_unreadable_input_never_raises(tmp_path: Path) -> None:
    r"""权限 000 的 ``\input`` 目标：is_file 通过但 read_bytes 抛——应跳过
    坏文件保留其余情报，而非整针崩溃（worker/e2e 靠 fail-open 壳兜底）。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\input{locked}\n"
        "\\begin{document}x\\end{document}\n",
        encoding="utf-8",
    )
    locked = tmp_path / "locked.tex"
    locked.write_text("x\n", encoding="utf-8")
    locked.chmod(0)
    try:
        rep = target_probe(tmp_path, "main.tex", _INDEX)
    finally:
        locked.chmod(0o644)
    assert rep.inputs  # 期望：跳过坏文件、其余情报保留


def test_symlink_loop_input_never_raises(tmp_path: Path) -> None:
    r"""``\input{loop}`` 指向自环 symlink：resolve() RuntimeError 穿透。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\input{loop}\n\\begin{document}x\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "loop.tex").symlink_to("loop.tex")
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert "loop.tex" in rep.missing


def test_symlink_loop_main_never_raises(tmp_path: Path) -> None:
    """main_rel 本身是 symlink loop：应走「不存在/越界」空报告路径。"""
    (tmp_path / "loop.tex").symlink_to("loop.tex")
    rep = target_probe(tmp_path, "loop.tex", _INDEX)
    assert rep.inputs == []
    assert any("loop.tex" in n for n in rep.notes)


def test_overlong_name_never_raises(tmp_path: Path) -> None:
    """300 字符 main_rel 与 ``\\input`` 名：ENAMETOOLONG 不应穿透。"""
    long_rel = "a" * 300
    rep = target_probe(tmp_path, long_rel, _INDEX)
    assert rep.inputs == []
    (tmp_path / "main.tex").write_text(
        f"\\documentclass{{article}}\n\\input{{{long_rel}}}\n"
        "\\begin{document}x\\end{document}\n",
        encoding="utf-8",
    )
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert rep.inputs == ["main.tex"]


def test_nul_main_rel_never_raises(tmp_path: Path) -> None:
    """``\\x00`` 嵌入 main_rel：resolve 期 ValueError 不应穿透。"""
    rep = target_probe(tmp_path, "\x00nul.tex", _INDEX)
    assert rep.inputs == []


def test_dotted_package_resolves_sty(tmp_path: Path) -> None:
    r"""``\usepackage{weird.dotted}`` + 本地 ``weird.dotted.sty`` 在场：
    引擎可解——探针应 local 命中 .sty 而非报 missing。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{weird.dotted}\n"
        "\\begin{document}x\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "weird.dotted.sty").write_text("% pkg\n", encoding="utf-8")
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    by = {d.name: d for d in rep.deps}
    assert by["weird.dotted"].resolved == "local"
    assert by["weird.dotted"].fname == "weird.dotted.sty"
    assert rep.missing == []


def test_dotted_package_bare_file_not_local(tmp_path: Path) -> None:
    r"""``\usepackage{weird.dotted}`` 仅裸 ``weird.dotted`` 在盘：该文件
    引擎不会读——应判 missing 而非 local。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{weird.dotted}\n"
        "\\begin{document}x\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "weird.dotted").write_text("junk\n", encoding="utf-8")
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    by = {d.name: d for d in rep.deps}
    assert by["weird.dotted"].resolved == "missing"
    assert rep.missing == ["weird.dotted.sty"]
