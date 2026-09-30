r"""actions._actions_install — ``scan_install``/``install_file`` 机制 (C5 拆叶)。

静态扫 ``\usepackage``/``\documentclass`` → 探测缺失 → 批量装
(``_apply_scan_install``/``_scan_names``/``_scan_vendored``), 缺文件
候选链 probe → install_file → 复核/重链 (``_apply_install_file``/
``_fd_case_variants``/``_relink_misplaced``/``_filemap_candidates``),
包文件依赖闭包 BFS 补装 (``_dep_stems``/``_dep_fanout``/
``_install_dep_closure``/``_requester_paths``), 与 ``_probe``
(``probe_file`` cwd 兼容调用, 消费点全在本叶)。
"""

from __future__ import annotations

import re
import shutil
from itertools import islice
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import regex

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop.builtins.common import _advise, _index_candidates
from texlate.compile.fixloop.builtins.vendored import _vendored_drop
from texlate.textutil import safe_is_file

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from texlate.compile.fixloop.engine import Engine, LoopCtx
    from texlate.compile.logparse import ErrReport


def _probe(eng: Engine, fname: str, cwd: Path | None = None) -> str | None:
    """``probe_file`` 兼容调用：支持可选 ``cwd`` kwarg 的 impl 直传; 裸 Protocol 实现退无参。"""
    if cwd is not None:
        try:
            return eng.probe_file(fname, cwd=cwd)
        except TypeError:
            pass  # 裸签名实现 → 退回 fname-only
    return eng.probe_file(fname)


def _scan_names(code: str, sp: dict[str, Any]) -> Iterator[str]:
    r"""单行 (已切注释) 按 scan_pattern 抽文件名——构造名/截断头滤除。

    ``\input sv\CurrentOption.clo`` 裸名被 ``\`` 截成 ``sv`` 残头、
    ``\InputIfFileExists{aip-\X.tex}`` 花括号内构造名——都不可探测,
    放行即产 ``sv.tex``/``aip-.tex`` 噪音安装 (svjour/aipcheck 实证)。
    """
    for m in regex.finditer(sp["regex"], code):
        if m.end() < len(code) and code[m.end()] == "\\" and code[m.end() - 1] != "}":
            continue  # 匹配被 \ 截断——残头非实名
        names = [m.group(1)]
        if sp.get("split"):
            names = m.group(1).split(sp["split"])
        for nm in names:
            name = nm.strip()
            if name and "\\" not in name:
                yield name


def _apply_scan_install(
    ctx: LoopCtx, eng: Engine, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""静态扫 ``\usepackage``/``\documentclass`` → 探测缺失 → 批量装 (原型)。"""
    need: set[str] = set()
    noise = (
        regex.compile(params["noise_filter"]) if params.get("noise_filter") else None
    )
    for f in ctx.tex_files():
        t = ctx.read(f)
        if t is None:
            continue
        for sp in params.get("scan_patterns") or []:
            # 逐行切注释后扫——``% \input foo`` 注释行不该触发安装
            # (pst-notreal 实证; ``\%`` 转义不算注释起点)
            for line in t.splitlines():
                code = _COMMENT_CUT_RE.split(line, maxsplit=1)[0]
                for name in _scan_names(code, sp):
                    # suffix 仅补给无扩展名 (``\input epsf`` → epsf.tex);
                    # 已带扩展名者 (``\input{x.tex}``) 照旧不叠。
                    fname = name if Path(name).suffix else name + sp.get("suffix", "")
                    if noise and not noise.match(name):
                        continue
                    need.add(fname)
    missing = sorted(f for f in need if not _probe(eng, f, cwd=ctx.wdir))
    installed = [f for f in missing if eng.install_file(f)]
    ctx.installed.extend(installed)
    note = f"missing files={missing} -> installed {installed}"
    if params.get("vendored"):
        vendored = _scan_vendored(ctx, eng, params, missing, set(installed))
        if vendored:
            note += f" vendored {vendored}"
    return True, note


def _scan_vendored(
    ctx: LoopCtx,
    eng: Engine,
    params: dict[str, Any],
    missing: list[str],
    got: set[str],
) -> list[str]:
    r"""Install 全链败件 → repo vendored 兜底平铺 + 落点依赖闭包预装。

    ``builtins.vendored_fetch`` 同款语义 (basename 查件 / ``..``-绝对-NUL
    守卫 / payload 相对径落位)——预检在 round-0 落件, 不依赖 first-error
    序位 (hep-ph/0104121: ``fixes.sty:41`` 的 undefined_cs 抢在
    ``missing_file`` 前, 轮级分类永远看不到 vendored 可救的缺件)。
    落件喂 ``_dep_fanout``: 真件 ``\RequirePackage`` 依赖同轮预装
    (aastex62→revtex4-1 类二阶缺件前置, 免穿透轮)。
    """
    root = builtins._vendor_root(params)  # noqa: SLF001 - vendored 查件单源
    dropped: list[Path] = []
    out: list[str] = []
    for fname in missing:
        if fname in got:
            continue
        dst, _why = _vendored_drop(ctx, root, fname)
        if dst is None:
            continue
        out.append(fname)
        ctx.installed.append(fname)
        dropped.append(dst)
    if dropped:
        _dep_fanout(ctx, eng, dropped, set(ctx.installed), depth=2)
    return out


def _filemap_candidates(eng: Engine, fname: str) -> list[str]:
    """``filemap`` 查询 + tectonic 侧 tlpdb 索引兜底 (CtanFetcher.peek_index)。"""
    return _index_candidates(eng, fname, suggest=True)


#: 包文件行首依赖声明 —— 注释掉的 ``% \RequirePackage`` 不命中。
#: ``textutil.LOADER_CMDS`` 真子集：``PassOptionsToPackage``/``PassOptionsToClass``
#: 首 ``{}`` 实参是选项表，group(1) 抓错名会产噪音安装件; ``LoadClassWithOptions``
#: 首参虽为类名可收但原面不含 (差异留档非漏收)。
_DEP_DECL_RE = re.compile(
    r"^[ \t]*\\(?:RequirePackage|RequirePackageWithOptions|LoadClass|usepackage)"
    r"\s*(?:\[[^\]\n]*\])?\s*\{([^}]*)\}",
    re.MULTILINE,
)

#: ``\input stem``/``\input{stem}`` 裸名依赖——行内允许 (pst-* generic 实证：
#: pstricks-add.tex l.27-32 ``\ifx\PSTnodesLoaded\endinput\else \input pst-node \fi``
#: 顺序链，条件不管照装——probe/install 门控天然无害)。花括号形吃 ``\s*``
#: (``\input{x}`` 零空白是 LaTeX 主导形态; arxiv/locate.py:53 同口径),
#: 裸名仍要求 ``\s+``——否则 ``\inputfoo``/``\inputlineno`` 被前缀误吃成
#: ``foo``/``lineno`` 伪依赖 (lineno.sty 真实存在，会真装)。
_DEP_INPUT_RE = re.compile(r"\\input(?:\s*\{([^}\n]*)\}|\s+([^\s{}%\\]+))")

#: 行内注释切尾 —— ``\%`` 转义不算注释起点。
_COMMENT_CUT_RE = re.compile(r"(?<!\\)%")


def _dep_stems(path: Path) -> list[str]:
    r"""包文件依赖名表: 行首 ``\\RequirePackage``/``\\LoadClass`` + 行内 ``\\input``。"""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    stems = [
        stem
        for m in _DEP_DECL_RE.finditer(text)
        for stem in (s.strip() for s in m.group(1).split(","))
        if stem
    ]
    for line in text.splitlines():
        code = _COMMENT_CUT_RE.split(line, maxsplit=1)[0]
        for m in _DEP_INPUT_RE.finditer(code):
            g = m.group(1) or m.group(2)
            if not g or "\\" in g:
                continue  # 构造文件名 (aip-\CurrentOption.tex) 不可探测
            if m.group(2) is not None and m.end() < len(code) and code[m.end()] == "\\":
                continue  # 裸名被 \ 截断 (sv\CurrentOption.clo → 'sv' 残头)
            stems.append(g)
    return stems


def _try_install_dep(ctx: LoopCtx, eng: Engine, stem: str) -> Path | None:
    """单依赖名探测/补装 → 已解析路径 (供闭包续层)。"""
    cands = (
        [stem] if Path(stem).suffix else [f"{stem}.sty", f"{stem}.cls", f"{stem}.tex"]
    )
    for cand in cands:
        if r := _probe(eng, cand, cwd=ctx.wdir):
            return Path(r)
        if eng.install_file(cand):
            ctx.installed.append(cand)
            if r := _probe(eng, cand, cwd=ctx.wdir):
                return Path(r)
            return None
    return None


def _dep_fanout(
    ctx: LoopCtx, eng: Engine, seeds: Iterable[Path], seen: set[str], *, depth: int
) -> None:
    """``seeds`` 各文件依赖声明 BFS 补装 (就地改 ``ctx.installed``/``seen``)。"""
    frontier = list(seeds)
    for _ in range(depth):
        nxt: list[Path] = []
        for p in frontier:
            for stem in _dep_stems(p):
                if stem in seen:
                    continue
                seen.add(stem)
                if r := _try_install_dep(ctx, eng, stem):
                    nxt.append(r)
        if not nxt:
            return
        frontier = nxt


def _install_dep_closure(
    ctx: LoopCtx, eng: Engine, fname: str, path: str | None, *, depth: int = 2
) -> None:
    r"""包装文件的依赖闭包补装: 行首 ``\RequirePackage``/``\LoadClass`` 逐层探测+装。

    2410.00012 实证: 装 mhchem 不装 chemgreek (包内 ``\RequirePackage`` 依赖),
    texmf 遮蔽下依赖缺席 → log 尾 Emergency stop。``depth`` 界住链长。
    """
    if path is None:
        return
    _dep_fanout(ctx, eng, [Path(path)], set(ctx.installed) | {fname}, depth=depth)


#: ``-file-line-error`` 锚里的要求方文件 token (``./pst-all.sty:25:``)
_REQ_ANCHOR_RE = re.compile(r"([^\s(){}]+?\.(?:sty|cls|def|clo|tex)):\d+:")


def _requester_paths(ctx: LoopCtx, eng: Engine, rep: ErrReport) -> list[Path]:
    r"""missing_file 报错的要求方文件 (``\\RequirePackage`` 宿主) 逐个解析。

    pst-all 实证 (delta b4akkgal5): meta-wrapper 连发 11 个成员包, 缺谁报谁、
    file:line 锚是要求方自身 —— 一轮补一个要等 8+ 轮 max_rounds; 直接扫
    要求方依赖全表一轮补齐。锚序: 首错行 > ctx > tail 末位 > file_stack
    内层包文件兜底 (无 ``file:line`` 的老式 ``!`` 错误) > popped_files
    尾段 (runaway 把肇事帧先弹走——``\@iiiparbox``/``\next`` 扫描族)。
    """
    names = _REQ_ANCHOR_RE.findall(rep.first or "")
    names += _REQ_ANCHOR_RE.findall(rep.ctx or "")
    names += _REQ_ANCHOR_RE.findall(rep.tail)[::-1]
    stack = [s for s in rep.file_stack[-2:] if s.endswith((".sty", ".cls", ".def"))]
    if not stack:
        # runaway 错报位在最近关闭帧（``popped_files[-1]`` 肇事候选，
        # #78/\@iiiparbox×3/\next 扫描实证）——栈取不到时 ``site_frames``
        # 弹栈段递补（跳过 ``file_stack`` 全段 = ``popped_files`` 新→旧序）
        stack = [
            s
            for s in islice(rep.site_frames(), len(rep.file_stack), None)
            if s.endswith((".sty", ".cls", ".def"))
        ]
    names += stack
    out: list[Path] = []
    seen: set[str] = set()
    for name in names:
        base = Path(name).name
        if base in seen:
            continue
        seen.add(base)
        p = Path(name)
        if not p.is_absolute():
            p = ctx.wdir / p
        if not p.exists():
            hit = _probe(eng, base, cwd=ctx.wdir)
            if hit is None:
                continue
            p = Path(hit)
        if p not in out:
            out.append(p)
    return out


def _fd_case_variants(file: str) -> list[str]:
    r"""``.fd`` 候选按内核 ``\try@load@fontshape`` 探测序: 小写名先、原名后。

    filemap/kpsewhich 大小写敏感——``LGRcmr.fd`` 实档键是 ``lgrcmr.fd``
    (cbfonts-fd), 混档 ``OT1Tempora-TLF.fd``→tempora 则原名才中; 双形
    互补全收 (nfssfd 车道, ``No file X.fd.`` 签 payload=原名)。
    非 ``.fd`` / 已小写名 → 原名单候选。
    """
    p = Path(file)
    if p.suffix.lower() != ".fd":
        return [file]
    lower = str(p.with_name(p.name.lower()))
    return [lower, file] if lower != file else [file]


def _relink_misplaced(  # noqa: C901  # 目录/文件链分派决策树，拆则形合实离
    ctx: LoopCtx, fname: str, present: str
) -> Path | None:
    """工程内错位件 → 链进 TeX 解析位; 非工程件/已在解析位 → None。

    编译 cwd = main 所在目录：带目录 payload 只走 ``main_dir/fname`` 字面
    解析 (kpathsea 对 dir 分量无裸名递补), 裸名走 ``main_dir`` + TEXINPUTS
    —— 两形态下工程内错位件都够不到，而 already-present 探测以 ``wdir``
    为基会误报 (soak-2026-09-18 fairmeta/acronyms1: install_file 报
    already-present 但 TeX 照旧 missing_file)。
    """
    wdir = ctx.wdir
    main_rel = ctx.main_rel
    main_dir = (wdir / main_rel).parent if main_rel else wdir
    hit = Path(present)
    hit_abs = hit if hit.is_absolute() else wdir / hit
    try:
        hit_abs.resolve().relative_to(wdir.resolve())
    except (OSError, ValueError):
        return None  # texmf 命中/归属判不出 —— TEXINPUTS 可达，无 relink 面
    parts = PurePosixPath(fname).parts
    if len(parts) > 1:
        # 目录形 payload: wdir/<首段> 是目录且非 main_dir 祖先 → 目录级
        # 软链罩住整枝 (Content/* 链式缺件一轮收口); 首段恰是祖先
        # (templates/arxiv/main 引 templates/arxiv/fairmeta) 或解析位
        # 已有真目录/活链 → 落文件级链 (防目录环/不覆盖现场)。
        top = wdir / parts[0]
        try:
            top_resolved = top.resolve()
            if top_resolved.is_dir() and not main_dir.resolve().is_relative_to(
                top_resolved
            ):
                link = main_dir / parts[0]
                if not (link.is_symlink() or link.exists()):
                    try:
                        link.symlink_to(top_resolved, target_is_directory=True)
                    except OSError:
                        pass
                    else:
                        return link
        except OSError:
            pass
    expected = main_dir / fname
    if expected.is_symlink():
        if expected.exists():
            return None  # 活链已占位 —— 视为已在解析位
        expected.unlink()  # 死链换新
    elif safe_is_file(expected):
        return None  # 解析位已有真件 —— 真 already-present/名冲突, 不覆盖
    try:
        expected.parent.mkdir(parents=True, exist_ok=True)
        expected.symlink_to(hit_abs.resolve())
    except OSError:
        try:
            shutil.copy2(hit_abs, expected)
        except OSError:
            return None
    return expected


def _apply_install_file(  # noqa: C901, PLR0912  # 候选序×font_related×复核×relink 分支即参数面
    ctx: LoopCtx, eng: Engine, params: dict[str, Any], rep: ErrReport
) -> tuple[bool, str]:
    """缺文件 → probe → install_file → 复核; font_related → rebuild_fontmaps (原型)。"""
    fanout_seeds = _requester_paths(ctx, eng, rep)
    if fanout_seeds:
        before = len(ctx.installed)
        _dep_fanout(ctx, eng, fanout_seeds, set(ctx.installed), depth=2)
        fanout_note = f" (+{len(ctx.installed) - before} requester deps)"
    else:
        fanout_note = ""
    font_exts = tuple(params.get("font_related_exts") or ())
    # file_aliases: 查询名≠实档名桥 —— babel ini 按 \BabelDefinitionFile{0}{X}
    # 指名实档 (选项 ukrainian → ukraineb.ldf 型), try_exts 拼不出来的异形名
    # 走显式别名表先试 (序=别名先，本名扩展后)。
    candidates = list((params.get("file_aliases") or {}).get(params["file"], []))
    if params.get("try_exts"):
        candidates += [params["file"] + e for e in params["try_exts"]]
    else:
        candidates += _fd_case_variants(params["file"])
        if not Path(candidates[-1]).suffix:
            # `I can't find file `X'` 裸 payload (\input/openin 系报错) ——
            # TeX 语义实际找 X.tex; 裸名照试后补 .tex 变体 (epsf 实证：
            # filemap/shim_map 键全带扩展名，裸名恒 miss)。
            candidates.append(params["file"] + ".tex")
    missed: list[str] = []
    for fname in candidates:
        font_related = bool(params.get("font_related")) or fname.endswith(font_exts)
        # probe 带 cwd=wdir: 工程内文件/ctan_fetch 平铺落盘均算命中
        # (tectonic probe_file 无 cwd 恒 None, 复核必败)
        if present := _probe(eng, fname, cwd=ctx.wdir):
            if (link := _relink_misplaced(ctx, fname, present)) is not None:
                _install_dep_closure(ctx, eng, fname, present)
                return True, f"relinked {fname} -> {link}{fanout_note}"
            _install_dep_closure(ctx, eng, fname, present)
            if params.get("already_present_ok", True):
                return True, f"already-present {fname}{fanout_note}"
            continue
        if not eng.install_file(fname, font_related=font_related):
            pkgs = _filemap_candidates(eng, fname)
            hint = f" (candidates: {', '.join(pkgs)})" if pkgs else ""
            missed.append(f"no package provides {fname}{hint}")
            continue
        if not (installed := _probe(eng, fname, cwd=ctx.wdir)):
            _advise(ctx, f"installed but {fname} still not found")
            continue
        ctx.installed.append(fname)
        _install_dep_closure(ctx, eng, fname, installed)
        if font_related:
            eng.rebuild_fontmaps()
        return True, f"installed {fname}{fanout_note}"
    # 全候选失败才落 advisory——前候选 miss 后候选成 (裸名→.tex fallback)
    # 的常态路径不该污染归因统计 (scout-pst 实证噪音)
    for m in missed:
        _advise(ctx, m)
    return False, f"no candidate file installed for {params['file']}{fanout_note}"
