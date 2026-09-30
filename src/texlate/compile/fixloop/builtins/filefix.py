r"""builtins.filefix — payload 文件归位/占位 (builtins.shim C3 再拆叶)。

missing_file/missing_graphic payload 按 TeX 实际解析位
(``_resolve_site`` = ``main_dir/<rel>``) 落真身或占位:
稿自带件位错归位 ``fileset_relocate`` (+顶层目录整树镜像) /
驱动期私有 TFM 提升 ``driver_tfm_hoist`` / 运行期自产件与覆盖层空
stub ``generated_stub`` / e-print 缺席 .tex 的版本缀 sibling 搬真件否则
空 stub ``doc_absent_stub``。瞬态件 (``.aux/.bbl`` 族) 一律不搬——
缺位是上游病灶信号。
"""

from __future__ import annotations

import re
import shutil
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import (
    _in_wdir,
    _inject_write,
    _resolve_site,
    _safe_rel,
    _wdir_project_files,
)
from texlate.textutil import mask_tex, safe_is_file

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx


# ════════════════════════════════════════════════════════════════
# 运行期生成件 stub (W79/W18 孤儿裁决 mechmap-2026-09-17): filemap
# 索引外的自产件缺档, install_file 必 miss → order:9 自门谓词先截
# ════════════════════════════════════════════════════════════════

#: ``\openout<stream>=<name>`` 目标抽取 —— stream 可为 ``\cs`` 或裸数字
#: (plain ``\openout0=foo``), ``=`` 可省, 花括号/裸名两形; ``\immediate``
#: 前缀无关 (match 落在 ``\openout`` 本体)。
_OPENOUT_TARGET_RE = re.compile(
    r"\\openout\s*(?:\\[a-zA-Z@]+|\d+)\s*=?\s*(?:\{([^}]+)\}|([^\s{}\\=]+))"
)

#: xfig/inkscape 文字覆盖层扩展名缺省面 —— 运行期生成、不在任何 CTAN 索引。
_OVERLAY_EXTS = (".pstex_t", ".pdf_t", ".pdftex_t")


def _openout_targets(ctx: LoopCtx) -> set[str]:
    r"""遮盖视图扫 ``\openout\w=<name>`` → 目标 basename 集。

    ``\jobname``/宏展开构造名静态不可解 → 含 ``\`` 者跳过; 花括号形与
    裸名形同收 (hep-th/9703214 ``\openout\ftfile=foots.tmp`` 实证)。
    """
    names: set[str] = set()
    for m in _OPENOUT_TARGET_RE.finditer(mask_tex(ctx.source_blob())):
        name = (m.group(1) or m.group(2) or "").strip().strip("\"'")
        if not name or "\\" in name:
            continue
        names.add(PurePosixPath(name).name)
    return names


def generated_stub(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""运行期生成件缺档 → wdir 落空 stub 占位 (W79 rungen / W18 覆盖层)。

    ``params.faces`` 子集择检测面 (缺省全开):
      ``openout`` — payload basename ∈ 源内 ``\openout`` 目标集。非
        ``\immediate`` 的 ``\openout`` 推迟到 shipout, 同遍 ``\input`` 必
        miss; 空 stub 让本遍静默通过, compile_passes:2 下遍 ``\write`` 填实。
      ``overlay`` — payload 扩展名 ∈ ``params.exts`` (缺省
        ``_OVERLAY_EXTS``)。覆盖层常经宏体间接 ``\input #2.pstex_t``, 空
        文件惠及全部调用点且不动作者宏 (0707.1954 实证, 优于 IfFileExists 改写)。
    谓词不中/盘上有件/名不安全 → False 落 install_file(10)/vendored_fetch(11.5)。
    """
    del eng
    fname = (payload or "").strip()
    rel = _safe_rel(fname)
    if rel is None:
        return False, f"unsafe stub name {fname!r}"
    faces = {str(f) for f in (params.get("faces") or ("openout", "overlay"))}
    hit: str | None = None
    if "openout" in faces and rel.name in _openout_targets(ctx):
        hit = "openout"
    if hit is None and "overlay" in faces:
        exts = {str(e).lower() for e in (params.get("exts") or _OVERLAY_EXTS)}
        if rel.suffix.lower() in exts:
            hit = "overlay"
    if hit is None:
        return False, f"{fname} not a generated/overlay target"
    target = _resolve_site(ctx, rel)
    if target is None:
        return False, f"{fname}: escapes wdir"
    body = f"% fixloop: stub for runtime-generated {rel.name}\n"
    # 指纹闸: 外来生成件/稿自带覆盖层永不覆写; 旧代注入 stub 覆写刷新。
    done, _state = _inject_write(ctx, target, body, fname)
    if done is not None:
        # current/foreign/写败 —— 盘上已有(或写不进)则不占位, 交后续规则
        return False, done[1] if not done[0] else f"{fname} already on disk"
    return True, f"{hit}-stub {fname}"


# ════════════════════════════════════════════════════════════════
# 位错稿自带件归位 (failmine4-covgap: ifacconf/jmlr2e/fairmeta/acronyms1
# 4 格) —— e-print 有件但不在 TeX 解析位 (compile cwd = main_dir,
# 根部位件对子目录 main 不可见); install_file 探测 cwd=wdir 假命中
# → fired-unfixed。真件 verbatim 拷贝优于任何 stub/install。
# ════════════════════════════════════════════════════════════════

#: 编译自产瞬态件扩展名 —— 缺位是上游病灶信号 (2609.20323 main.aux =
#: unclosed ``\if`` 下游产物实证), 搬陈件会遮蔽真因, 不属「源档位错」面。
_RELOCATE_TRANSIENT_EXTS = frozenset(
    {
        ".aux",
        ".out",
        ".toc",
        ".lof",
        ".lot",
        ".bbl",
        ".blg",
        ".bcf",
        ".log",
        ".fls",
        ".nav",
        ".snm",
        ".vrb",
        ".idx",
        ".ind",
        ".ilg",
        ".glo",
        ".gls",
        ".acn",
        ".acr",
        ".xdy",
    }
)
#: 复合尾缀 (``suffix`` 只取末段, 按件名 endswitch 判)。
_RELOCATE_TRANSIENT_NAME_EXTS = (".run.xml", ".synctex.gz", ".fdb_latexmk")


def _is_transient_name(name: str, suffix: str) -> bool:
    """编译自产瞬态件判定 —— ``.aux``/``.bbl`` 族扩展名或复合尾缀命中即瞬态。

    瞬态缺位是上游病灶信号非源档位错, 搬陈件/stub 都遮蔽真因
    (``_RELOCATE_TRANSIENT_*`` 表注, 2609.20323 实证)。
    """
    return suffix.lower() in _RELOCATE_TRANSIENT_EXTS or name.lower().endswith(
        _RELOCATE_TRANSIENT_NAME_EXTS
    )


def _find_relocate_src(ctx: LoopCtx, rel: PurePosixPath) -> Path | None:
    r"""定位位错真身 —— wdir 内后缀路径匹配优先, basename 兜底, 浅者优先。

    ``**/payload`` 形命中 (如 payload ``templates/arxiv/fairmeta.cls`` 对
    深层同名位) 高于裸 basename; dot 段路径 (``./.git``/``.texmf`` 类)
    与引擎树 (``_texmf``/``_tect_out``) 剔除 —— 工程件不住隐藏目录与
    引擎封装树。多命中取 (rank, 深度, 路径) 最小者, 确定性排序。
    """
    want_tail = tuple(p.lower() for p in rel.parts)
    base = rel.name.lower()
    cands: list[tuple[int, int, str, Path]] = []
    for p, parts in _wdir_project_files(ctx):
        pl = tuple(part.lower() for part in parts)
        if pl[-len(want_tail) :] == want_tail:
            rank = 0
        elif p.name.lower() == base:
            rank = 1
        else:
            continue
        cands.append((rank, len(parts), str(p), p))
    if not cands:
        return None
    return min(cands, key=lambda t: t[:3])[3]


def fileset_relocate(  # noqa: PLR0911 - 逐门 decline note 即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""稿自带件在 wdir 但不在 TeX 解析位 → 逐字节拷贝到 ``<main_dir>/<payload>``。

    机理 (failmine4-covgap 4 格实证): e-print 把 ``\documentclass``/
    ``\input``/``\includegraphics`` 目标件放工程根, main 却住子目录
    (``Artigo/sbaconf.tex``/``sections/00_preamble.tex``/``IEEEtran/main.tex``
    形) —— 编译 cwd = ``main_path().parent`` 且无 TEXINPUTS 根注入,
    payload 按 cwd 解析 → missing_file/missing_graphic。``install_file``
    探测以 wdir 为 cwd 假命中、filemap 亦无收录 (ifacconf/jmlr2e 实测
    tlpdb 零命中) → fired-unfixed。修复不是装包而是归位: 目标
    ``<main_dir>/<payload>`` (TeX 实际解析位), 源序 ``wdir/<payload>``
    → ``_find_relocate_src`` rglob。序在 order:9 族首 —— 真件内容面
    即 e-print 钦定, rungen_stub/docstrip 让位。

    守卫: payload 非绝对/无 ``..``/无 ``\x00``; main 未知 → False
    (解析位不可定); 目标已在 → False (payload 可达, 缺件另有真因);
    瞬态扩展名 (``.aux/.bbl/.toc``…) 不搬 —— 编译自产件缺位是上游
    病灶信号非源档问题, 搬陈件遮蔽真因; 源目标同路径 → False。
    """
    del eng, params
    fname = (payload or "").strip().strip("'\"")
    rel = _safe_rel(fname)
    if rel is None:
        return False, f"unsafe relocate name {fname!r}"
    if _is_transient_name(rel.name, rel.suffix):
        return False, f"{fname}: transient artifact — not a source file"
    mp = ctx.main_path()
    if mp is None:
        return False, f"{fname}: main unknown — resolve site undetermined"
    target = mp.parent / Path(*rel.parts)
    if not _in_wdir(ctx, target):
        return False, f"{fname}: escapes wdir"
    if safe_is_file(target):
        return False, f"{fname}: already at resolve site"
    src = ctx.wdir / Path(*rel.parts)
    if not safe_is_file(src) or src.resolve() == target.resolve():
        src = _find_relocate_src(ctx, rel)
    if src is None or src.resolve() == target.resolve():
        return False, f"{fname}: not present in fileset"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        ctx.invalidate(target)
    except OSError as e:
        return False, f"{fname}: copy failed ({e})"
    src_rel = src.relative_to(ctx.wdir).as_posix()
    dst_rel = target.relative_to(ctx.wdir).as_posix()
    n_tree = _mirror_relocate_tree(ctx, rel, mp.parent, target)
    note = f"relocated {src_rel} → {dst_rel}"
    if n_tree:
        note += f" (+{n_tree} tree files)"
    return True, note


def _mirror_tree_skip(
    p: Path, pparts: tuple[str, ...], dst_top_res: Path, target_res: Path
) -> bool:
    """镜像源件逐项跳闸 —— 瞬态件/dot 段/目标自身/已处归位树内 (防递归)。"""
    if any(part.startswith(".") for part in pparts):
        return True
    if _is_transient_name(p.name, p.suffix):
        return True
    pres = p.resolve()
    if pres == target_res:
        return True
    try:
        pres.relative_to(dst_top_res)
    except ValueError:
        return False
    return True  # 已处归位树内 (嵌套镜像副本) —— 防 top/top/top 递归


def _mirror_relocate_tree(
    ctx: LoopCtx, rel: PurePosixPath, main_dir: Path, target: Path
) -> int:
    """Payload 顶层目录在 wdir 根成树 → 整树镜像到 ``<main_dir>/<top>/``。

    doc 按 e-print 坐标引用同前缀整族件 (``Content/a.tex``/``Content/b.tex``
    轮轮各缺一件) —— 逐轮一件归位烧轮次 (2609.20640 单件/轮 ×8 实证)。
    首个 payload 归位成功后同树镜像一次铺全; ``main_dir`` 与 ``<top>``
    同径时源恒在目标树下 → 全员跳过, 天然幂等。
    """
    if not rel.parent.parts:
        return 0
    top = rel.parts[0]
    src_top = ctx.wdir / top
    dst_top = main_dir / top
    if not src_top.is_dir() or src_top.resolve() == dst_top.resolve():
        return 0
    if not _in_wdir(ctx, dst_top):
        return 0
    dst_top_res = dst_top.resolve()
    target_res = target.resolve()
    n = 0
    for p in sorted(src_top.rglob("*")):
        if not safe_is_file(p):
            continue
        pparts = p.relative_to(ctx.wdir).parts
        if _mirror_tree_skip(p, pparts, dst_top_res, target_res):
            continue
        dst = dst_top / Path(*pparts[1:])
        if safe_is_file(dst):
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
            ctx.invalidate(dst)
            n += 1
        except OSError:
            continue
    return n


def driver_tfm_hoist(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``Unable to find TFM file "X"`` → 子目录稿自带 ``*.tfm`` 提升到扁平解析位。

    机理 (2606.02800 nvidiatechreport.cls / 2504.05118 bytedance_seed.cls
    residchk 面): 私有字体 e-print 自带 ``.tfm`` 在子目录 —— TeX 侧经
    路径限定字体名 (``\\DeclareFontShape`` ``seed/bytesans`` 形) 找得到;
    下游驱动 (xdvipdfmx 等) 按 ``\\pdfmapline`` 裸名走 TFMFONTS 查找,
    只认 ``.`` = compile cwd (``main_dir``) 的扁平位, 子目录够不到 →
    ``*: fatal:``。私有件非 CTAN → install_tfm filemap 必 miss, 归位
    是唯一真修。payload 触发名定位 font 目录后同目录 ``*.tfm`` 全量
    hoist (nvidia 7/seed 2 —— 逐轮单件烧轮次, 同 relocate tree-mirror
    教训); ``\\pdfmapline`` 的 ``.ttf`` 路径限定引用本来可达, 不搬。

    守卫同 relocate 系: payload 无 ``/`` ``\\`` ``..`` ``\\x00`` 非点前缀;
    main 未知 → False; ``{payload}.tfm`` 已扁平在解析位 → False (缺件
    另有真因); fileset 无同名 → False; 目标名已占逐件跳 (幂等复火)。
    """
    del eng, params
    name = (payload or "").strip().strip("'\"")
    if (
        not name
        or name.startswith(".")
        or any(tok in name for tok in ("/", "\\", "..", "\x00"))
    ):
        return False, f"unsafe tfm name {name!r}"
    mp = ctx.main_path()
    if mp is None:
        return False, "main unknown — driver resolve site undetermined"
    dst_dir = mp.parent
    dst_res = dst_dir.resolve()
    want = f"{name}.tfm"
    if safe_is_file(dst_dir / want):
        return False, f"{want}: already at driver resolve site"
    hits = [
        p
        for p, _parts in sorted(_wdir_project_files(ctx))
        if fnmatchcase(p.name, want) and p.parent.resolve() != dst_res
    ]
    if not hits:
        return False, f"{want}: not present in fileset"
    src_dir = hits[0].parent
    hoisted = []
    for src in sorted(src_dir.glob("*.tfm")):
        if not safe_is_file(src):
            continue
        target = dst_dir / src.name
        if safe_is_file(target):
            continue
        try:
            shutil.copyfile(src, target)
            ctx.invalidate(target)
        except OSError:
            continue
        hoisted.append(src.name)
    if not hoisted:
        return False, f"{name}.tfm: all resolve-site targets occupied"
    dst_rel = dst_dir.relative_to(ctx.wdir).as_posix()
    return True, f"hoisted {len(hoisted)} tfm → {dst_rel}: {', '.join(hoisted)}"


# ════════════════════════════════════════════════════════════════
# doc 引用但 e-print 未带的 .tex 片段 (m1kcensus2 衍生, covgap-C #205
# 复核): fileset 真无件 + filemap/vendor 无供 → 版本缀 sibling 搬真件,
# 否则解析位空 stub —— 丢该 \input 段保其余, 优于整格 unfixable。
# ════════════════════════════════════════════════════════════════

#: stem 尾部版本缀剥离形 —— ``12step_dynamics_new``→``12step_dynamics``
#: (2210.03294: doc 活引用 ``_new`` 件, e-print 只带改名件)。
_DOCABSENT_SUFFIX_RE = re.compile(
    r"^(?P<base>.+?)[_-](?:new|old|orig|final|draft|updated?|backup|bak|v\d+)$",
    re.IGNORECASE,
)
#: stem 加缀候选 —— doc 引旧名 e-print 带改名新件的反向漂移。
_DOCABSENT_SUFFIXES = ("_new", "_old", "_final", "_draft", "-new", "-old", "_v2", "_v1")


def _docabsent_sibling(ctx: LoopCtx, rel: PurePosixPath) -> Path | None:
    """Payload stem ± 版本缀的同目录唯一命中件 → 搬真件候选。

    搜索域 = ``wdir/<rel.parent>`` (e-print 坐标下同目录 —— sibling 语义
    即「引用件应在的位置的旁枝」)。剥缀形与加缀形双向候选, 同名件按
    文件名去重; 唯一文件名才返回 —— 多异名命中 = 版本族并存, 择一
    搬运是猜, 让位空 stub。
    """
    stems = {rel.stem}
    if m := _DOCABSENT_SUFFIX_RE.match(rel.stem):
        stems.add(m.group("base"))
    stems.update(rel.stem + s for s in _DOCABSENT_SUFFIXES)
    stems.discard(rel.stem)  # 同名件归 relocate/fileset —— 这里只看漂移形
    if not stems:
        return None
    base_dir = ctx.wdir / Path(*rel.parent.parts) if rel.parent.parts else ctx.wdir
    if not base_dir.is_dir():
        return None
    hits: dict[str, Path] = {}
    for p in base_dir.iterdir():
        if (
            safe_is_file(p)
            and p.suffix.lower() == rel.suffix.lower()
            and p.stem in stems
        ):
            hits.setdefault(p.name, p)
    if len(hits) != 1:
        return None
    return next(iter(hits.values()))


def doc_absent_stub(  # noqa: PLR0911 - 逐门 decline note 即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Doc 引用但 e-print 未带的 .tex → 版本缀 sibling 搬真件, 否则空 stub。

    机理 (m1kcensus2, covgap-C #205 逐格复核): ``\input``/``\include``
    目标在 e-print 里根本不存在 (作者本地件未打包/改名漂移) ——
    relocate 够不到 (fileset 无件), install/vendored/shim 亦无供
    (非 CTAN 件)。序在全真件臂后 (``pst-tools.tex`` 实证 .tex payload
    可以是真 CTAN 件, stub 必须是缺席实锤后的末位兜底)。

    两臂: (a) ``_docabsent_sibling`` 版本缀漂移唯一命中搬真件到解析位
    (真内容优于 stub); (b) 空 stub 落 ``_resolve_site`` —— 丢该
    ``\input`` 段保其余, 优于整格 unfixable。闸: 非 .tex 扩展名让位
    (.cls/.sty 走 install/shim 域); 瞬态件拒 (.aux/.bbl 缺位 = 上游
    病灶信号, stub 遮蔽真因 —— 2609.20323 main.aux 裁决沿); fileset
    内有同名件 → False (relocate 域防御性复核, dispatch 序漂移时仍
    安全); 外来同名件指纹闸不覆写。
    """
    del eng
    fname = (payload or "").strip().strip("'\"")
    rel = _safe_rel(fname)
    if rel is None:
        return False, f"unsafe stub name {fname!r}"
    if _is_transient_name(rel.name, rel.suffix):
        return False, f"{fname}: transient artifact — not a source file"
    exts = {str(e).lower() for e in (params.get("exts") or (".tex",))}
    if rel.suffix.lower() not in exts:
        return False, f"{fname}: not a doc-fragment ext"
    target = _resolve_site(ctx, rel)
    if target is None:
        return False, f"{fname}: escapes wdir"
    if safe_is_file(ctx.wdir / Path(*rel.parts)) or (
        _find_relocate_src(ctx, rel) is not None
    ):
        return False, f"{fname}: present in fileset — relocate domain"
    sib = _docabsent_sibling(ctx, rel)
    if sib is not None and sib.resolve() != target.resolve():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sib, target)
            ctx.invalidate(target)
        except OSError as e:
            return False, f"{fname}: sibling copy failed ({e})"
        s_rel = sib.relative_to(ctx.wdir).as_posix()
        d_rel = target.relative_to(ctx.wdir).as_posix()
        return True, f"rename-rescue {s_rel} → {d_rel}"
    body = f"% fixloop: doc-absent stub for {rel.name}\n"
    # 指纹闸: 外来件/稿自带件永不覆写; 旧代注入 stub 覆写刷新。
    done, _state = _inject_write(ctx, target, body, fname)
    if done is not None:
        # current/foreign/写败 —— 盘上已有(或写不进)则不占位, 交后续规则
        return False, done[1] if not done[0] else f"{fname} already on disk"
    return True, f"doc-absent stub {fname}"
