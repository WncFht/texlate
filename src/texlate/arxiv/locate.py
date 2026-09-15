r"""主文件定位 + \input 拓扑（docs/06 §2.3/§2.4）。

候选：``*.tex``/``*.ltx`` 中剥注释后含 ``\documentclass``/``\documentstyle``
的文件。裁决序：``\begin{document}`` 优先 → include 图的**根**优先 →
文件名先验（``main|paper|ms|root|manuscript|thesis|{id}``，顶层目录优先）→
仍 ≥2 个独立根则 ``multi_doc`` 并取 include-degree 最大者。零候选 → 非
LaTeX（plain TeX ``\bye`` / ConTeXt ``\starttext``）→ 进降级链。

``\input`` 八形态：``\input{…}`` / 裸 ``\input file``（1502.01589 实测
25 处）/ ``\include`` / ``\InputIfFileExists`` / ``\subfile`` /
``\import{dir}{file}`` / ``\subimport`` / ``\includestandalone`` /
``\CatchFileBetweenTags``；另有 ``\bibliography{x}`` → ``x.bbl``。

路径解析基准序（corpus39-profile 实测修正 docs/06「相对 including 文件
目录 → 退项目根」）：**编译 CWD（主文件目录）→ 项目根 → including 文件
目录**；扩展名补全 ``.tex → .sty → 裸名``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

from texlate.arxiv._texutil import strip_comments
from texlate.arxiv.sniff import check_pdf_wrapper
from texlate.textutil import decode_tex

#: 候选扩展名（docs/06 只列 .tex；corpus_v2 实测 .latex/.ltx 亦存在——
#: nucl-ex/0203009 唯一主文件即 article.latex）
_TEX_EXT: Final = (".tex", ".ltx", ".latex")
_FILENAME_PRIOR: Final = frozenset(
    {"main", "paper", "ms", "root", "manuscript", "thesis"}
)
_MAX_DEPTH: Final = 64
_MULTI_ROOT: Final = 2

_DOCCLASS_RE: Final = re.compile(r"\\(?:documentclass|documentstyle)(?![a-zA-Z@])")
_BEGINDOC_RE: Final = re.compile(r"\\begin\s*\{document\}")
_PLAIN_RE: Final = re.compile(r"\\bye(?![a-zA-Z@])")
_CONTEXT_RE: Final = re.compile(
    r"\\(?:starttext|startdocument|startcomponent)(?![a-zA-Z@])"
)

_BRACED: Final = r"\{([^{}]+)\}"
_BOUND: Final = r"(?![a-zA-Z@])"


def _cmd(name: str, tail: str) -> re.Pattern[str]:
    return re.compile(r"\\" + name + _BOUND + tail)


# (command, pattern, arg_group, dir_group)。八形态 + bibliography；
# 全部带控制词边界（\\include 不会误吞 \includegraphics）。
_REF_RES: Final = (
    ("input", _cmd("input", r"\s*" + _BRACED), 1, None),
    ("input_bare", re.compile(r"\\input" + _BOUND + r"\s+([^\s{]\S*)"), 1, None),
    ("include", _cmd("include", r"\s*" + _BRACED), 1, None),
    ("InputIfFileExists", _cmd("InputIfFileExists", r"\s*" + _BRACED), 1, None),
    ("subfile", _cmd("subfile", r"\s*(?:\[[^\]]*\])?\s*" + _BRACED), 1, None),
    (
        "includestandalone",
        _cmd("includestandalone", r"\s*(?:\[[^\]]*\])?\s*" + _BRACED),
        1,
        None,
    ),
    (
        # \CatchFileBetweenTags\token{file}{tag} —— file 是第一个花括号参数
        "CatchFileBetweenTags",
        _cmd("CatchFileBetweenTags", r"\s*\\?\w*\s*" + _BRACED + r"\s*\{[^{}]*\}"),
        1,
        None,
    ),
    ("import", _cmd("import", r"\s*" + _BRACED + r"\s*" + _BRACED), 2, 1),
    ("subimport", _cmd("subimport", r"\s*" + _BRACED + r"\s*" + _BRACED), 2, 1),
    ("bibliography", _cmd("bibliography", r"\s*" + _BRACED), 1, None),
)


class DocKind(StrEnum):
    """文档谱系。零候选时区分 plain TeX / ConTeXt / 空。"""

    LATEX = "latex"
    PLAIN_TEX = "plain_tex"
    CONTEXT = "context"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class InputRef:
    """一条 include 边（按文档出现序）。"""

    command: str  # input / input_bare / include / import / … / bibliography
    arg: str  # 解析用参数（import 已拼 dir/file）
    source: str  # 发出引用的文件 relpath
    resolved: str | None = None  # 解析到的 relpath
    basis: str | None = None  # main_dir / root / including_dir


@dataclass(slots=True)
class FileNode:
    """单个 .tex 文件的扫描结果。"""

    path: str
    stripped: str
    has_documentclass: bool
    has_begin_document: bool
    refs: list[InputRef] = field(default_factory=list)


@dataclass(slots=True)
class _Resolved:
    edges: dict[str, list[str]]  # source → [resolved relpath]
    in_degree: dict[str, int]  # 每 .tex 被其他文件引次数
    unresolved: list[InputRef]
    bibliographies: list[str]


@dataclass(slots=True)
class LocateResult:
    """主文件定位 + 拓扑结果。"""

    root: Path
    kind: DocKind
    main: str | None = None
    candidates: list[str] = field(default_factory=list)
    independent_roots: list[str] = field(default_factory=list)
    multi_doc: bool = False
    pdf_wrapper: bool = False
    warnings: list[str] = field(default_factory=list)
    order: list[str] = field(default_factory=list)  # 展平顺序（含 main）
    edges: dict[str, list[str]] = field(default_factory=dict)  # file → resolved
    unresolved: list[InputRef] = field(default_factory=list)
    bibliographies: list[str] = field(default_factory=list)
    dead_files: list[str] = field(default_factory=list)


def _iter_files(root: Path) -> list[str]:
    r"""全树相对路径（posix 形），含非 .tex（\input 可指 .sty/无后缀）。"""
    out = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() or p.is_symlink()
    ]
    return sorted(out)


def _scan_refs(path: str, stripped: str) -> list[InputRef]:
    refs: list[tuple[int, InputRef]] = []
    for command, rx, arg_grp, dir_grp in _REF_RES:
        for m in rx.finditer(stripped):
            if dir_grp is not None:
                d = m.group(dir_grp).strip()
                arg = (
                    f"{d}/{m.group(arg_grp).strip()}" if d else m.group(arg_grp).strip()
                )
            else:
                arg = m.group(arg_grp).strip()
            refs.append((m.start(), InputRef(command=command, arg=arg, source=path)))
    refs.sort(key=lambda t: t[0])
    return [r for _, r in refs]


def _norm_arg(arg: str) -> str | None:
    r"""\input 参数 → 规范相对路径；包外/绝对 → None。"""
    arg = arg.strip().strip('"').strip("'").strip()
    if not arg:
        return None
    arg = arg.replace("\\", "/")
    if arg.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", arg):
        return None
    parts = [p for p in arg.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _resolve(
    arg: str,
    bases: list[str],
    fileset: set[str],
    lowermap: dict[str, str],
    *,
    force_tex: bool = False,
) -> tuple[str | None, str | None]:
    """按基准序+扩展名补全解析。返回 (relpath|None, basis|None)。"""
    rel = _norm_arg(arg)
    if rel is None:
        return None, None
    has_ext = bool(PurePosixPath(rel).suffix)
    if rel.lower().endswith(".tex"):
        tries = [rel]
    elif force_tex:  # \include 隐含 .tex
        tries = [rel + ".tex", rel]
    elif has_ext:
        tries = [rel, rel + ".tex", rel + ".sty"]
    else:
        tries = [rel + ".tex", rel + ".sty", rel]  # .tex → .sty → 裸名
    seen_tries: set[str] = set()
    for basis in bases:
        for cand in tries:
            joined = cand if basis == "" else f"{basis}/{cand}"
            if joined in seen_tries:
                continue
            seen_tries.add(joined)
            if joined in fileset:
                return joined, basis or "root"
            low = lowermap.get(joined.lower())
            if low is not None:
                return low, basis or "root"
    return None, None


def _bases(main_dir: str, including_dir: str) -> list[str]:
    """基准序：编译 CWD（主文件目录）→ 项目根 → including 文件目录。"""
    out: list[str] = []
    for b in (main_dir, "", including_dir):
        if b not in out:
            out.append(b)
    return out


@dataclass(frozen=True, slots=True)
class _ResolveCtx:
    """解析上下文：基准序 + 文件集 + 大小写映射。"""

    bases: list[str]
    fileset: set[str]
    lowermap: dict[str, str]


def _resolve_ref(ref: InputRef, ctx: _ResolveCtx) -> InputRef:
    hit, basis = _resolve(
        ref.arg,
        ctx.bases,
        ctx.fileset,
        ctx.lowermap,
        force_tex=ref.command == "include",
    )
    return InputRef(ref.command, ref.arg, ref.source, hit, basis)


def _resolve_bib(
    ref: InputRef,
    ctx: _ResolveCtx,
    bibs: list[str],
    unresolved: list[InputRef],
) -> None:
    r"""\bibliography{a,b} → x.bbl / x.bib 逐个解析。"""
    for piece in ref.arg.split(","):
        arg = piece.strip()
        if not arg:
            continue
        probe = arg if arg.endswith((".bbl", ".bib")) else arg + ".bbl"
        hit, _basis = _resolve(probe, ctx.bases, ctx.fileset, ctx.lowermap)
        if hit:
            if hit not in bibs:
                bibs.append(hit)
        else:
            unresolved.append(InputRef(ref.command, arg, ref.source))


def _resolve_all(
    nodes: dict[str, FileNode],
    fileset: set[str],
    lowermap: dict[str, str],
    main_dir: str,
) -> _Resolved:
    """全图解析：nodes 每文件的 refs → resolved 边/未解析/bib。"""
    edges: dict[str, list[str]] = {}
    in_degree: dict[str, int] = dict.fromkeys(nodes, 0)
    unresolved: list[InputRef] = []
    bibs: list[str] = []
    for rel, node in nodes.items():
        incl_dir = str(PurePosixPath(rel).parent)
        if incl_dir == ".":
            incl_dir = ""
        bases = _bases(main_dir, incl_dir)
        ctx = _ResolveCtx(bases, fileset, lowermap)
        out_edges: list[str] = []
        for ref in node.refs:
            if ref.command == "bibliography":
                _resolve_bib(ref, ctx, bibs, unresolved)
                continue
            r = _resolve_ref(ref, ctx)
            if r.resolved is None:
                unresolved.append(r)
            else:
                out_edges.append(r.resolved)
                if r.resolved != rel and r.resolved in in_degree:
                    in_degree[r.resolved] += 1
        edges[rel] = out_edges
    return _Resolved(edges, in_degree, unresolved, bibs)


def locate(root: Path, arxiv_id: str = "") -> LocateResult:
    r"""定位主文件并展平 \input 拓扑。"""
    root = Path(root)
    res = LocateResult(root=root, kind=DocKind.NONE)
    fileset = set(_iter_files(root))
    lowermap = {p.lower(): p for p in fileset}
    tex_files = sorted(p for p in fileset if p.lower().endswith(_TEX_EXT))
    if not tex_files:
        res.warnings.append("no_tex_files")
        return res

    nodes = _scan_nodes(root, tex_files, res)
    if not nodes:
        res.warnings.append("all_tex_unreadable")
        return res

    candidates = sorted(p for p, n in nodes.items() if n.has_documentclass)
    res.candidates = candidates
    if not candidates:
        joined = "\n".join(n.stripped for n in nodes.values())
        if _PLAIN_RE.search(joined):
            res.kind = DocKind.PLAIN_TEX
        elif _CONTEXT_RE.search(joined):
            res.kind = DocKind.CONTEXT
        res.warnings.append(f"no_documentclass:{res.kind}")
        return res
    res.kind = DocKind.LATEX

    # 第一遍建图（main 未定，root 基准）——支撑根判定
    first = _resolve_all(nodes, fileset, lowermap, "")
    main = _choose(candidates, nodes, first, arxiv_id, res)

    # 第二遍：换上主文件目录基准（CWD 语义）出最终边/序
    main_dir = str(PurePosixPath(main).parent)
    if main_dir == ".":
        main_dir = ""
    final = _resolve_all(nodes, fileset, lowermap, main_dir)
    res.edges = final.edges
    res.unresolved = final.unresolved
    res.bibliographies = final.bibliographies
    res.main = main

    _add_jobname_bbl(res, nodes, fileset, lowermap, main)

    verdict = check_pdf_wrapper(nodes[main].stripped)
    res.pdf_wrapper = verdict.is_wrapper
    if verdict.is_wrapper:
        res.warnings.append(
            f"pdf_wrapper:{main}:sections={verdict.n_sections},text={verdict.body_text_bytes}B"
        )
    elif verdict.is_stub:
        res.warnings.append(f"stub_body:{main}")

    res.order = _flatten(main, final.edges, nodes, res.warnings)
    res.dead_files = sorted(p for p in nodes if p not in res.order)
    return res


def _add_jobname_bbl(
    res: LocateResult,
    nodes: dict[str, FileNode],
    fileset: set[str],
    lowermap: dict[str, str],
    main: str,
) -> None:
    r"""\bibliography 实际消费的是 \jobname.bbl（主文件词干）。

    bib 缺、bbl 在即正常编译——1502.01589：24 个 .bib 全缺但
    planck_parameters_2015.bbl 在包内。
    """
    has_bibref = any(
        ref.command == "bibliography" for node in nodes.values() for ref in node.refs
    )
    if not has_bibref:
        return
    main_dir = str(PurePosixPath(main).parent)
    stem = PurePosixPath(main).stem
    jobname_bbl = f"{main_dir}/{stem}.bbl" if main_dir != "." else f"{stem}.bbl"
    if jobname_bbl in res.bibliographies:
        return
    if jobname_bbl in fileset:
        res.bibliographies.append(jobname_bbl)
        return
    low = lowermap.get(jobname_bbl.lower())
    if low:
        res.bibliographies.append(low)


def _scan_nodes(
    root: Path, tex_files: list[str], res: LocateResult
) -> dict[str, FileNode]:
    nodes: dict[str, FileNode] = {}
    for rel in tex_files:
        try:
            raw = decode_tex((root / rel).read_bytes())
        except OSError as e:
            res.warnings.append(f"unreadable:{rel}:{e}")
            continue
        stripped = strip_comments(raw)
        nodes[rel] = FileNode(
            path=rel,
            stripped=stripped,
            has_documentclass=bool(_DOCCLASS_RE.search(stripped)),
            has_begin_document=bool(_BEGINDOC_RE.search(stripped)),
            refs=_scan_refs(rel, stripped),
        )
    return nodes


def _choose(
    candidates: list[str],
    nodes: dict[str, FileNode],
    first: _Resolved,
    arxiv_id: str,
    res: LocateResult,
) -> str:
    r"""裁决序：a.\begin{document} → b.图的根 → c.文件名先验+顶层 → d.include-degree。"""
    pool = [c for c in candidates if nodes[c].has_begin_document]
    if not pool:
        pool = list(candidates)
    indep = [c for c in pool if first.in_degree.get(c, 0) == 0]
    res.independent_roots = sorted(indep)
    res.multi_doc = len(indep) >= _MULTI_ROOT
    if indep:
        pool = indep
    id_norm = arxiv_id.replace("/", "").replace(".", "").lower()

    def _stem(p: str) -> str:
        return PurePosixPath(p).stem.lower()

    prior = [
        c
        for c in pool
        if _stem(c) in _FILENAME_PRIOR or _stem(c).replace(".", "") == id_norm
    ]
    if prior:
        pool = prior
    min_depth = min(len(PurePosixPath(c).parts) for c in pool)
    pool = [c for c in pool if len(PurePosixPath(c).parts) == min_depth]
    # include-degree 最大者；并列取路径序最小（确定性）
    return min(pool, key=lambda c: (-len(first.edges.get(c, [])), c))


def _flatten(
    main: str,
    edges: dict[str, list[str]],
    nodes: dict[str, FileNode],
    warnings: list[str],
) -> list[str]:
    """DFS 展平：seen 去重（菱形重访静默），visiting 断真环。"""
    seen: set[str] = set()
    visiting: set[str] = set()
    order: list[str] = []

    def _dfs(p: str, depth: int) -> None:
        if p in seen:
            return
        if depth > _MAX_DEPTH:
            warnings.append(f"max_depth:{p}")
            return
        seen.add(p)
        visiting.add(p)
        order.append(p)
        for nxt in edges.get(p, []):
            if nxt in visiting:
                warnings.append(f"cycle:{p}->{nxt}")
                continue
            if nxt in nodes:  # 只追 .tex 图
                _dfs(nxt, depth + 1)
        visiting.discard(p)

    _dfs(main, 0)
    return order
