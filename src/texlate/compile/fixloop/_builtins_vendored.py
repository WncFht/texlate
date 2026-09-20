r"""_builtins_vendored — 工程内遮蔽探测/隔离 + 随包 vendored 件取放 (C3 拆分)。

``\\ProvidesX`` 日期面比对确证工程内 .sty/.cls 更旧遮蔽系统件;
``vendor/`` 随包件 (files/ 真件 + stubs/ 最小宏面 + shims/ .cls 替身)
平铺救 off-CTAN 绝版宏。``_vendor_root``/``_vendored_source`` 被
engine.vendored 查件复用 (同语义 basename 查件)。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_common import (
    _FINGERPRINT_RE,
    _LEGACY_INJECTED_HEADS,
    _inject_write,
    _live_matches,
    _mark_injected,
    _resolve_site,
)
from texlate.textutil import safe_is_file

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx

#: ``\ProvidesX`` 变元间分隔符——空白 + ``%`` 注释到行尾 (TeX 词法同语义:
#: ``{n} %^^A comment\n{d}`` docstrip 续行实证, clistmap/lambdax)。
_SEP = r"(?:\s|%[^\n]*)*"
_DATE_RE = re.compile(
    r"\\Provides(?:Package|Class|File|ExplPackage|ExplClass|ExplFile)"
    + _SEP
    + r"\{[^}]*\}"
    + _SEP
    + r"\[(\d{4})[/.-](\d{2})[/.-](\d{2})"
)
#: expl3 自署约定——``\ProvidesExplX{n}{YYYY-MM-DD}{v}`` 日期在花括号第二槽
#: (texmf 237 处字面实证; csvsimple-l3.sty ``{2024/09/27}{2.7.0}``)。
_BRACED_DATE_RE = re.compile(
    r"\\ProvidesExpl(?:Package|Class|File)"
    + _SEP
    + r"\{[^}]*\}"
    + _SEP
    + r"\{"
    + _SEP
    + r"(\d{4})[/.-](\d{2})[/.-](\d{2})"
)
#: 日期面宏间址——``\ProvidesPackage{x}[\abx@date\space v...]`` 形（biblatex
#: v3.12 实证：字面日期不在 bracket 而在同文件 ``\def\abx@date{2018/11/02}``）。
#: ``[%`` 注释续行形亦收 (expl3.sty ``[%\n \ExplFileDate`` —— texmf 61 处)。
_DATE_INDIRECT_RE = re.compile(
    r"\\Provides(?:Package|Class|File|ExplPackage|ExplClass|ExplFile)"
    + _SEP
    + r"\{[^}]*\}"
    + _SEP
    + r"\["
    + _SEP
    + r"\\([a-zA-Z@_:]+)"
)
#: expl3 brace 槽位间址——``\ProvidesExplX{n}{\cs}{v}`` (texmf 52 处:
#: \ExplFileDate/\ltlab*date/\g@*@date@tl 等, 皆 \def/\tl_* 族赋值或
#: \GetIdInfo 设定, ctex.sty 实证)。
_BRACED_INDIRECT_RE = re.compile(
    r"\\ProvidesExpl(?:Package|Class|File)"
    + _SEP
    + r"\{[^}]*\}"
    + _SEP
    + r"\{"
    + _SEP
    + r"\\([a-zA-Z@_:]+)"
)
#: pst-* 族 .tex 核的日期面约定——``\def\filedate{YYYY/MM/DD}`` (pstricks.tex
#: v1.15 实证)。\ProvidesX 两径全空时兜底, 同 ``_provides_date`` 口径。
_FILEDATE_RE = re.compile(r"\\def\\filedate\s*\{(\d{4})[/.-](\d{2})[/.-](\d{2})\}")
#: ``\GetIdInfo $Id: name.ext ver YYYY-MM-DD ...$`` → ``\ExplFileDate``
#: (expl3-code.tex auxii/auxiii 实证语义; ctex.sty:31 实证形)。ver==-1 时
#: expl3 置 ``0000/00/00`` 不可用伪日期 → 不取, 保守 None。
_GETIDINFO_RE = re.compile(
    r"\\GetIdInfo\s*\$Id:\s*\S+\s+(\S+)\s+(\d{4})[/.-](\d{2})[/.-](\d{2})"
)


def _cs_date(text: str, csname: str) -> tuple[int, int, int] | None:
    r"""宏间址取日期: ``\def``/``\tl_*``/``\*command`` 字面赋值 → ``\GetIdInfo`` (仅 ``ExplFileDate``)。

    保守口径: 查不到字面日期即 None, 绝不猜——错日期会静默毒化 ld<sd
    遮蔽比对。
    """
    date = r"\s*\{\s*(\d{4})[/.-](\d{2})[/.-](\d{2})"
    m = re.search(r"\\[egx]?def\s*\\" + re.escape(csname) + date, text)
    if m is None:
        # expl3 tl 赋值面: \tl_const:Nn/\tl_(g)set:Nn \c_*_date_tl {d}
        # (acro/exsheets/xsim 族实证)。
        m = re.search(
            r"\\tl_(?:const|g?set):N[a-zA-Z]\s*\\" + re.escape(csname) + date,
            text,
        )
    if m is None:
        # LaTeX2e 面: \newcommand*\pgfmxfpDate{YYYY-MM-DD} (pgfmath-xfp 实证)。
        m = re.search(
            r"\\(?:new|renew|provide)command\*?\s*\{?\\"
            + re.escape(csname)
            + r"\}?"
            + date,
            text,
        )
    if m is not None:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if csname == "ExplFileDate":
        m = _GETIDINFO_RE.search(text)
        if m is not None and m.group(1) != "-1":
            return (int(m.group(2)), int(m.group(3)), int(m.group(4)))
    return None


def _provides_date(text: str) -> tuple[int, int, int] | None:
    r"""``\ProvidesX`` 自署日期 → ``(y, m, d)``, 无证 → ``None``。

    抽取径 (先字面后间址, 与既有口径一致——字面日期面即确证):
    ``{n}[YYYY/MM/DD]`` bracket 字面 (六变体含 ``File``) → expl3
    ``{n}{YYYY-MM-DD}`` brace 第二槽 → bracket/brace 首 cs 宏间址
    (``_cs_date``: ``\def``/``\tl_*``/``\*command`` 字面赋值 +
    ``\GetIdInfo``→``\ExplFileDate``; 两形谁文本在前解谁) →
    ``\def\filedate`` 兜底 (pst-* 核约定, pstricks.tex v1.15)。
    """
    m = _DATE_RE.search(text) or _BRACED_DATE_RE.search(text)
    if m is not None:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    ind = _DATE_INDIRECT_RE.search(text)
    br = _BRACED_INDIRECT_RE.search(text)
    if ind is not None and (br is None or ind.start() <= br.start()):
        target = ind
    else:
        target = br
    if target is not None:
        d = _cs_date(text, target.group(1))
        if d is not None:
            return d
    m = _FILEDATE_RE.search(text)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _index_providers(eng: Engine, fname: str) -> list[str]:
    """``filemap`` + ``ctan_fetch.peek_index`` 查 ``fname`` 的 bundle/TL 提供包。

    只收 ``query`` 精确命中 —— ``suggest`` 前缀猜测面太宽, 不足以佐证
    撞名遮蔽。
    """
    pkgs = list(eng.filemap(fname))
    if not pkgs:
        fetcher = getattr(eng, "ctan_fetch", None)
        peek = getattr(fetcher, "peek_index", None)
        idx = peek() if callable(peek) else None
        if idx is not None:
            pkgs = idx.query(fname)
    return pkgs


def find_vendored_shadows(
    ctx: LoopCtx, eng: Engine, exts: tuple[str, ...]
) -> list[tuple[Path, tuple[int, int, int] | None, tuple[int, int, int] | None, str]]:
    r"""工程内 .sty/.cls 遮蔽候选 → ``(file, 本地日期, 系统日期, 提供方)``。

    xelatex: ``probe_file`` 命中系统副本且 ``\\ProvidesPackage``/``\\ProvidesClass``
    日期 ``ld < sd`` 确证才列 (盲删必死 —— 同目录 cls 可能是唯一来源)。
    tectonic: ``probe_file`` 无 cwd 恒 None —— 改查 filemap/tlpdb 索引,
    撞名被收录 (bundle/TL 有现行副本) 即列 ``sd=None`` advisory 级候选;
    bundle 内文件无日期面, 提供方记 ``bundle provides <pkg>``, 不走
    ``ld < sd`` 判据。
    """
    cands = []
    tectonic = ctx.engine_name == "tectonic"
    wdir_r = ctx.wdir.resolve()
    neutral = _neutral_probe_dir(ctx)
    for f in ctx.tex_files(exts):
        resolved = eng.probe_file(f.name, cwd=neutral)
        if not resolved:
            if tectonic:
                pkgs = _index_providers(eng, f.name)
                if pkgs:
                    local_txt = ctx.read(f)
                    ld = _provides_date(local_txt) if local_txt else None
                    prov = f"bundle provides {', '.join(pkgs)}"
                    cands.append((f, ld, None, prov))
            continue
        rp = Path(resolved) if isinstance(resolved, str) else resolved
        try:
            rpv = rp.resolve()
            if rpv == f.resolve() or rpv.is_relative_to(wdir_r):
                continue  # 命中工程自身/工程内同名副本（kpsewhich 搜 cwd——
                # 进程 cwd 落在 workdir 内时探到的是 vendored 自件）→ 非遮蔽
        except (OSError, RuntimeError, ValueError):
            continue  # symlink loop/NUL/巨名 → 按非遮蔽计
        local_txt = ctx.read(f)
        try:
            sys_txt = Path(rp).read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        if local_txt is None:
            continue
        ld, sd = _provides_date(local_txt), _provides_date(sys_txt)
        if ld is not None and sd is not None and ld < sd:
            cands.append((f, ld, sd, str(rp)))
    return cands


def _retire_paired_tex_core(  # noqa: PLR0911  # 保守闸逐条一处, 缺一不碰
    ctx: LoopCtx, eng: Engine, f: Path, suffix: str
) -> str | None:
    r"""退役 wrapper 同名 .tex 核 (pst-* 族 wrapper+core 一体件) → 隔离 note。

    X.sty 确证更旧退役后, 同目录稿自带 X.tex 若留盘, wrapper 的
    ``\input{X}`` 搜 cwd 先中 stale 核 (0707.4206: vendored pstricks.tex
    v1.15/2006 配系统 pstricks.sty v0.75 → ``\pst@cntm`` undefined)。
    与 .sty 同道保守闸: 系统 probe 命中 wdir 外现行副本 ∧ 双侧日期面
    ``ld < sd`` 确证 ∧ 非本引擎注入件 (指纹/旧代头认亲) —— 缺一不碰。
    """
    core = f.with_suffix(".tex")
    if core == f or not safe_is_file(core):
        return None
    resolved = eng.probe_file(core.name, cwd=_neutral_probe_dir(ctx))
    if not resolved:
        return None  # 系统无核可递补——rename 即造 missing_file, 不动
    rp = Path(resolved) if isinstance(resolved, str) else resolved
    try:
        rpv = rp.resolve()
        if rpv == core.resolve() or rpv.is_relative_to(ctx.wdir.resolve()):
            return None  # probe 命中工程自身 (kpsewhich cwd 毒化) → 非遮蔽
    except (OSError, RuntimeError, ValueError):
        return None
    local_txt = ctx.read(core)
    if local_txt is None:
        return None
    head = local_txt.lstrip()[:200]
    if _FINGERPRINT_RE.search(local_txt) or head.startswith(_LEGACY_INJECTED_HEADS):
        return None  # 本引擎注入件非稿自带——退役即自拆台
    try:
        sys_txt = rp.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    ld, sd = _provides_date(local_txt), _provides_date(sys_txt)
    if ld is None or sd is None or ld >= sd:
        return None  # 无日期面确证新旧——盲删必死, 保留
    core.rename(core.with_name(core.name + suffix))
    note = f"{core.name} (paired core {ld} < {sd})"
    shim = _path_shim_for(ctx, eng, core, str(rp))
    if shim:
        note += f"; {shim}"
    return note


#: 路径限定装载点扫描面——可含 ``\usepackage``/``\input`` 等装载命令的
#: tex 系文件 (主稿/子件/宏包互载)。``.fixloop-iso`` 件后缀不入集, 天然跳过。
_SITE_SCAN_EXTS = (
    ".tex",
    ".ltx",
    ".dtx",
    ".ins",
    ".sty",
    ".cls",
    ".def",
    ".cfg",
    ".clo",
)

#: 一参装载命令——变元为文件名 (``\usepackage`` 族逗号分枚, 逐枚再拆)。
#: 覆盖 paper 见过的全部形: ``./x``/``x/y``/``x\y`` 三族路径限定 +
#: documentclass/LoadClass (.cls 同机退役)。
_PATHQUAL_LOAD1_RE = re.compile(
    r"\\(?:usepackage|RequirePackage|RequirePackageWithOptions|documentclass"
    r"|LoadClass|LoadClassWithOptions|input|include|InputIfFileExists"
    r"|IfFileExists|subfile)\s*(?:\[[^\]\n]*\]\s*)?\{([^{}\n]*)\}"
)
#: import 族二参形——``\import{dir}{file}``/``\inputfrom``/``\includefrom``
#: dir 对 cwd 解; ``\subimport``/``\subincludefrom`` dir 对源文件目录解。
_PATHQUAL_IMPORT_CWD_RE = re.compile(
    r"\\(?:import|inputfrom|includefrom)\s*\{([^{}\n]*)\}\s*\{([^{}\n]*)\}"
)
_PATHQUAL_IMPORT_SUB_RE = re.compile(
    r"\\sub(?:import|includefrom)\s*\{([^{}\n]*)\}\s*\{([^{}\n]*)\}"
)


def _norm_load_path(arg: str, base: str = "") -> str | None:
    """装载变元 → 词法归一 posix 相对径; 绝对径/逃逸 ``..``/空 → ``None``。

    引号/反斜杠/``./`` 前缀/``a/./b``/``a/../b`` 全归一。``base`` 仅
    subimport 族用 (源文件目录)——kpathsea 其余相对径恒对 cwd (=wdir) 解。
    """
    a = arg.strip().strip('"').strip().replace("\\", "/")
    if not a or a.startswith("/") or ":" in a:
        return None
    parts = [p for p in base.split("/") if p and p != "."]
    for seg in a.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(seg)
    return "/".join(parts) if parts else None


def _pathqual_hit(ctx: LoopCtx, rel: str) -> bool:
    r"""工程内存在指向 ``rel`` (wdir 相对 posix) 的路径限定装载点。

    判定径: 遮盖视图下扫一参装载/import 族变元——变元须带显式目录分量
    (``/``/``\``; 裸名走 texmf 序天然有递补, 不算)。归一后与 ``rel`` 及
    去缀 stem 比对 (``./style/x`` ≡ ``style/x.sty``)。
    """
    suffix = PurePosixPath(rel).suffix
    stem_rel = rel[: -len(suffix)] if suffix else rel
    targets = (rel, stem_rel)
    for src in ctx.tex_files(_SITE_SCAN_EXTS):
        txt = ctx.read(src)
        if not txt:
            continue
        src_dir = src.relative_to(ctx.wdir).parent.as_posix()
        base = "" if src_dir == "." else src_dir
        for m in _live_matches(_PATHQUAL_LOAD1_RE, txt):
            for item in m.group(1).split(","):
                if ("/" in item or "\\" in item) and (_norm_load_path(item) in targets):
                    return True
        for m in _live_matches(_PATHQUAL_IMPORT_CWD_RE, txt):
            if _norm_load_path(m.group(1) + "/" + m.group(2)) in targets:
                return True
        for m in _live_matches(_PATHQUAL_IMPORT_SUB_RE, txt):
            if _norm_load_path(m.group(1) + "/" + m.group(2), base) in targets:
                return True
    return False


def _neutral_probe_dir(ctx: LoopCtx) -> Path:
    """``probe_file`` ``cwd`` 中立基——wdir 外恒存且不含工程件的锚目录。

    进程 cwd 落 wdir 内时默认 ``Path.cwd()`` 基让 ``safe_is_file`` 直查
    命中 vendored 自件 → "wdir 外系统副本" 探测全灭 (seki era 件全
    self-hit → vendored_shadow 条件死面实证)。``/`` 同名件概率实零,
    在场亦属系统面 (语义仍对)。
    """
    return Path(ctx.wdir.resolve().anchor or "/")


def _probe_external(ctx: LoopCtx, eng: Engine, name: str) -> str | None:
    """``probe_file(name)`` 命中 wdir 外系统副本 → 路径串; 否则 ``None``。"""
    resolved = eng.probe_file(name, cwd=_neutral_probe_dir(ctx))
    if not resolved:
        return None
    try:
        if Path(resolved).resolve().is_relative_to(ctx.wdir.resolve()):
            return None  # 命中工程内件——shim 转发即再中毒
    except (OSError, RuntimeError, ValueError):
        return None
    return str(resolved)


def _write_path_shim(ctx: LoopCtx, f: Path, sys_path: str) -> str:
    r"""原径回填薄 shim: ``\input`` 直指已解析系统副本 → note 段。

    ``\input{<abs>}`` 不经 kpathsea 复解——根位自指/TEXINPUTS 歧义/另一
    vendored 撞名件三径全免 (``\RequirePackage{stem}`` 三径全中)。
    ``\ProvidesX{stem}`` 与原载名一致, 选项经 ``opt@<stem>.<ext>`` 自动续传。
    """
    try:
        abs_s = Path(sys_path).resolve().as_posix()
    except (OSError, RuntimeError, ValueError):
        abs_s = str(sys_path)
    ext = f.suffix.lower()
    # 选项由 \@fileswith@ptions 按 filename@parse 裸名挂 ``opt@<stem>.<ext>``
    # ——内层真件 \ProcessOptions 同键直读, 无需 DeclareOption 续传 (e2e 实
    # 证: 续传把 opt 表复制两份 → 未声明项双报)。shim 与内层真件的
    # \ProvidesX{stem} 对全限定请求名各出一条 requested/provides mismatch
    # 警告——与退役前稿自带件产出的警告同文 (妆饰级, 无功能面差)。
    if ext == ".cls":
        head = (
            "\\NeedsTeXFormat{LaTeX2e}\n"
            f"\\ProvidesClass{{{f.stem}}}[2026/09/19 fixloop path-shim]\n"
        )
    elif ext == ".sty":
        head = (
            "\\NeedsTeXFormat{LaTeX2e}\n"
            f"\\ProvidesPackage{{{f.stem}}}[2026/09/19 fixloop path-shim]\n"
        )
    else:
        head = "% fixloop path-shim\n"
    body = f"{head}\\input{{{abs_s}}}\n\\endinput\n"
    ctx.write(f, _mark_injected(body))
    return f"{f.name} (path-shim -> {abs_s})"


def _path_shim_for(
    ctx: LoopCtx, eng: Engine, f: Path, sys_path: str | None
) -> str | None:
    """``f`` 刚 rename 隔离; 路径限定装载点命中 ∧ 有递补源 → 原径回填 shim。"""
    try:
        rel = f.relative_to(ctx.wdir).as_posix()
    except ValueError:
        return None
    if not _pathqual_hit(ctx, rel):
        return None
    sp = sys_path or _probe_external(ctx, eng, f.name)
    if sp is None:
        return None
    return _write_path_shim(ctx, f, sp)


def _isolate_cohort_sib(ctx: LoopCtx, eng: Engine, sib: Path, suffix: str) -> list[str]:
    """单伴船件隔离 → note 表; 路径限定命中但系统无递补 → 保留 + advisory。"""
    srel = sib.relative_to(ctx.wdir).as_posix()
    if _pathqual_hit(ctx, srel):
        sp = _probe_external(ctx, eng, sib.name)
        if sp is None:
            adv = f"{srel}: 路径限定装载但系统无递补, 保留"
            if adv not in ctx.advisories:
                ctx.advisories.append(adv)
            return []
        sib.rename(sib.with_name(sib.name + suffix))
        return [f"{srel} (cohort)", _write_path_shim(ctx, sib, sp)]
    sib.rename(sib.with_name(sib.name + suffix))
    return [f"{srel} (cohort)"]


def vendored_shadow_isolate(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""确证更旧的工程内 .sty/.cls → rename ``<f>.fixloop-iso`` 隔离 (docs/08:269)。

    ``sd=None`` 的 tectonic 索引候选是 advisory 级 —— 无日期面确证新旧,
    不 rename, 记 ``bundle provides <pkg>`` advisory (幂等去重)。

    ``params.cohort_map``：``sty 名 → 同包伴船 glob 表``——确证更旧的包其
    vendored 伴船件（.def/.bbx/.cbx/.lbx 等）一并隔离，否则留下旧伴船与
    系统新主件混栈（1907.00257 半栈 biblatex/2003.10727 全栈实证——只隔
    biblatex.sty 会留 vendored *.def 继续遮蔽系统件）。

    wrapper+core 一体件 (pst-* 族 X.sty/X.tex): 退役 wrapper 后同 stem
    稿自带 .tex 核同道闸确证一并退役 (``_retire_paired_tex_core``)。

    路径限定装载点回填 (``_path_shim_for``): ``\\usepackage{./style/x}``
    形只对字面相对径解析, texmf 裸名递补够不到 —— rename 后原径留薄
    shim ``\\input`` 直指系统副本 (1803.03185 实证: optidef.sty 隔离 →
    ``File './style/optidef.sty' not found`` → unfixable)。伴船件路径限
    定命中但系统无递补 → 不 rename 直保留 (rename 即造 missing_file)。
    """
    del payload
    exts = tuple(params.get("exts") or (".sty", ".cls"))
    suffix = str(params.get("suffix") or ".fixloop-iso")
    cohort_map: dict[str, Any] = params.get("cohort_map") or {}
    moved = []
    for f, ld, sd, prov in find_vendored_shadows(ctx, eng, exts):
        if sd is None:
            adv = f"{f.name}: {prov}——vendored 撞名未确证新旧, 保留"
            if adv not in ctx.advisories:
                ctx.advisories.append(adv)
            continue
        f.rename(f.with_name(f.name + suffix))
        moved.append(f"{f.name} ({ld} < {sd})")
        shim = _path_shim_for(ctx, eng, f, prov)
        if shim:
            moved.append(shim)
        paired = _retire_paired_tex_core(ctx, eng, f, suffix)
        if paired:
            moved.append(paired)
        for pat in cohort_map.get(f.name, ()):
            for sib in ctx.wdir.rglob(str(pat)):
                if not sib.is_file() or sib.name.endswith(suffix) or sib == f:
                    continue
                moved.extend(_isolate_cohort_sib(ctx, eng, sib, suffix))
    if not moved:
        return False, "无确证更旧的可隔离遮蔽"
    return True, f"isolate vendored: {', '.join(moved)}"


#: repo 随发 vendored 件子层 —— ``files/`` 真件 (许可逐件核过) 先于
#: ``stubs/`` 最小宏面 stub; ``shims/`` 收 .cls 替身 stub (aa.cls 暂寄
#: stubs/)。basename 跨层唯一, 序只文档义。
_VENDOR_SUBDIRS = ("files", "stubs", "shims")


def _vendor_root(params: dict[str, Any]) -> Path:
    """Repo vendored 件根: ``params.dir`` 覆盖, 默认包内 ``vendor/``。"""
    d = params.get("dir")
    return Path(d) if d else Path(__file__).resolve().parent / "vendor"


def _vendored_source(root: Path, fname: str) -> Path | None:
    """Basename 查件: files/ → stubs/ → shims/ 序; 命中返回源路径否则 None。"""
    base = PurePosixPath(fname).name
    if not base:
        return None
    for sub in _VENDOR_SUBDIRS:
        cand = root / sub / base
        if safe_is_file(cand):
            return cand
    return None


def vendored_fetch(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""missing_file 命中 repo vendored 件 → 平铺进 wdir (两臂同式)。

    off-CTAN 绝版宏 (aastex/psfig/iopart/elsart/svjour…) 无包可装,
    ``ctan_fetch`` 的 cwd 平铺遮蔽已是实证通路 —— 本动作同源, 只是把
    取件点从 tlnet 换成随包 ``vendor/`` (零网络零安装)。落盘保 payload
    相对径 (``\input{sub/x}`` 期径); basename 查件。
    """
    del eng
    fname = (payload or "").strip()
    rel = PurePosixPath(fname)
    if not fname or rel.is_absolute() or ".." in rel.parts or "\x00" in fname:
        return False, f"unsafe vendored name {fname!r}"
    src = _vendored_source(_vendor_root(params), fname)
    if src is None:
        return False, f"{fname} not vendored"
    dst = _resolve_site(ctx, rel)
    if dst is None:
        return False, f"{fname}: escapes wdir"
    tier = src.parent.name  # files/stubs/shims 三层 note 标源——cls 替身记 shims
    body = src.read_text(encoding="utf-8", errors="replace")
    # 指纹闸 (b3a): 同名片四分判——外来件(稿自带/真包)永不覆写; 旧代
    # 注入件 (无指纹但带 vendored/fixloop 行头标记) 覆写刷新。
    done, state = _inject_write(ctx, dst, body, fname)
    if done is not None:
        if state == "current":
            # 零字节改动不算 apply —— True 会烧掉本轮 dispatch 并把
            # 同签名低 order 候选 (fileset_relocate 类) 挡在门外。
            return False, f"{done[1]} (no-op)"
        return done
    tag = "refreshed (stale injected)" if state == "stale" else "->"
    return (
        True,
        f"vendored[{tier}] {src.name} {tag} {dst.relative_to(ctx.wdir)}",
    )


#: pre-2019 amsmath 指纹——``\@saveprimitive`` 对 \leqno/\eqno 的调用在
#: v2.17e (2019-11) 起被 ``\let\@@leqno\leqno`` 直绑取代 (kernel 把 \leqno
#: 等改成 \protected 宏, 旧件的 primitive 判据必炸 "no longer primitive");
#: 有此调用即旧件, 改名件 (amsmath2.sty v2.13) 同中——probe 探不到的改名
#: 遮蔽靠它收网。
_SAVEPRIM_CALL_RE = re.compile(r"\\@saveprimitive\s*\\(?:leqno|eqno)\b")

#: 改名件 delegate——退役后同名件把载名接回系统/bundle amsmath。
#: ``{stem}`` 槽留原名注册 (amsmath2 → \ProvidesPackage{amsmath2})。
#: 尾部 \let-undef 两行: iopart.cls:778 ``\@namedef{equation*}{\[}`` 类
#: 宿主类预占撞现代 amsmath ``\newenvironment{equation*}`` (:2941) ——
#: 语义等价 (iopart 的 def 字面即 \[...\], amsmath equation* 就是 \[
#: 的 env 形), 预清让 env 正名; 未定义件上 \let\@undefined 恒无害。
_AMS_DELEGATE_TMPL = (
    "\\NeedsTeXFormat{LaTeX2e}\n"
    "\\ProvidesPackage{%s}[2026/09/19 fixloop delegate -> amsmath]\n"
    "\\DeclareOption*{\\PassOptionsToPackage{\\CurrentOption}{amsmath}}\n"
    "\\ProcessOptions\\relax\n"
    "\\expandafter\\let\\csname equation*\\endcsname\\@undefined\n"
    "\\expandafter\\let\\csname endequation*\\endcsname\\@undefined\n"
    "\\RequirePackage{amsmath}\n"
    "\\endinput\n"
)


def amsmath_family_retire(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``\@saveprimitive`` 指纹 amsmath*.sty → mv ``.fixloop-iso`` + ams* 伴船退役。

    pass 1 指纹直判 (不走 probe——改名件 amsmath2.sty 无系统同名, ld<sd
    判据够不到): 本名 ``amsmath.sty`` 退役后系统/bundle/tlmgr 同名递补;
    改名件 (stem != amsmath) 写 delegate stub 保持载名可解。pass 2 ams*
    伴船复用 ``find_vendored_shadows`` ld<sd 确证 (同 snapshot 整族退役,
    防 2003/2025 混栈); tectonic advisory 候选 (sd=None) 不动。
    """
    del payload
    suffix = str(params.get("suffix") or ".fixloop-iso")
    moved = []
    for f in ctx.tex_files((".sty",)):
        txt = ctx.read(f) or ""
        if _SAVEPRIM_CALL_RE.search(txt) is None:
            continue
        f.rename(f.with_name(f.name + suffix))
        if f.stem == "amsmath":
            moved.append(f"{f.name} (saveprimitive-era, system serves)")
        else:
            ctx.write(f, _mark_injected(_AMS_DELEGATE_TMPL % f.stem))
            moved.append(f"{f.name} (renamed copy -> amsmath delegate)")
    for f, ld, sd, _prov in find_vendored_shadows(ctx, eng, (".sty",)):
        if sd is None or not f.name.startswith("ams"):
            continue
        f.rename(f.with_name(f.name + suffix))
        moved.append(f"{f.name} (cohort {ld} < {sd})")
    if not moved:
        return False, "无 saveprimitive 指纹 ams* 件"
    return True, f"retire ams family: {', '.join(moved)}"


#: revtex4 v4.0a 双锚指纹——``\ProvidesClass{revtex4}`` 本名精确 (revtex4-1/
#: 4-2/4b4 各自署 ``{revtex4-1}``/``{revtex4-2}``/``{revtex4b4}``, 唯 v4.0a
#: 占本名) ∧ ``\@uclcnotmath`` (内嵌 textcase v0.06 大写机, :3737-3750;
#: 现代 textcase.sty:49 有同名机但走 ``\AddToNoCaseChangeList`` expl3 分支
#: 永不触此件 → uclc 单锚必误伤现代件, 双锚才确证 v4.0a)。
_REVTEX40_NAME_RE = re.compile(r"\\ProvidesClass\s*\{revtex4\}")
_REVTEX40_UCLC_RE = re.compile(r"\\@uclcnotmath")

#: delegate——与 90-shim-legacy.yaml shim_map.revtex4.cls 同体 (revtex4-2
#: 同名桥 + frontmatter 提前武装)。``{stem}`` 槽留原名注册: 本名件退笔名
#: 接续, 改名件 (revtex4x.cls 等) 保 stem 可解。系统 TL 不署 ``revtex4``
#: 包名 (唯 revtex4-2) —— 本名退役无 delegate 即 missing_file/再中毒。
_REV_DELEGATE_TMPL = (
    "\\NeedsTeXFormat{LaTeX2e}\n"
    "\\ProvidesClass{%s}[2026/09/19 fixloop delegate -> revtex4-2]\n"
    "\\LoadClassWithOptions{revtex4-2}\n"
    "\\frontmatter@init\n"
    "\\let\\frontmatter@init\\relax\n"
    "\\endinput\n"
)


def _is_revtex40a(text: str) -> bool:
    r"""v4.0a 双锚: 本名 ``{revtex4}`` ∧ 内嵌 ``\@uclcnotmath`` 机。"""
    return (
        _REVTEX40_NAME_RE.search(text) is not None
        and _REVTEX40_UCLC_RE.search(text) is not None
    )


def _read_utf8(f: Path) -> str:
    """utf-8 直读 (指纹探测用, 树外件不走 ctx 缓存); 不可读 → ``""``。"""
    try:
        return f.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


def _retire_revtex40a_files(
    ctx: LoopCtx, suffix: str, *, repl_ok: bool, moved: list[str]
) -> None:
    r"""Pass 1: 工程内 .cls 双锚直判 → mv ``suffix`` + 同 stem delegate。

    ``_texmf`` 引擎 usermode 树跳过 (非稿自带, 由 pass 2 根 delegate 遮蔽);
    本名件同写 delegate —— 系统 TL 无 ``revtex4`` 名递补, 裸退役即
    missing_file/再中毒。本引擎注入件 (delegate/shim 亦署 {revtex4}) 经
    指纹/旧代行头认亲排除。
    """
    for f in ctx.tex_files((".cls",)):
        if "_texmf" in f.relative_to(ctx.wdir).parts:
            continue
        txt = ctx.read(f) or ""
        if not _is_revtex40a(txt):
            continue
        head = txt.lstrip()[:200]
        if _FINGERPRINT_RE.search(txt) or head.startswith(_LEGACY_INJECTED_HEADS):
            continue
        if not repl_ok:
            adv = f"{f.name}: revtex4-2 递补源缺席, v4.0a 退役搁置"
            if adv not in ctx.advisories:
                ctx.advisories.append(adv)
            continue
        f.rename(f.with_name(f.name + suffix))
        ctx.write(f, _mark_injected(_REV_DELEGATE_TMPL % f.stem))
        moved.append(f"{f.name} (v4.0a -> revtex4-2 delegate)")


def _revtex_shadowed_externally(ctx: LoopCtx, eng: Engine) -> bool:
    """Pass 2 探测: wdir 外/``_texmf`` 内存在 v4.0a revtex4.cls 遮蔽件。"""
    resolved = eng.probe_file("revtex4.cls")
    if resolved:
        try:
            rpv = Path(resolved).resolve()
            external = not rpv.is_relative_to(ctx.wdir.resolve())
        except (OSError, RuntimeError, ValueError):
            rpv = Path(resolved)
            external = True
        if external and _is_revtex40a(_read_utf8(rpv)):
            return True
    texmf = ctx.wdir / "_texmf"
    if not texmf.is_dir():
        return False
    return any(
        f.is_file() and _is_revtex40a(_read_utf8(f)) for f in texmf.rglob("revtex4.cls")
    )


def _drop_revtex_root_delegate(
    ctx: LoopCtx, eng: Engine, *, repl_ok: bool, moved: list[str]
) -> None:
    r"""Pass 2: 树外 TEXMFHOME 遮蔽命中 → cwd 根 delegate (树外件只读不 mv)。

    mnras-retire 裁定形: ``~/texmf`` 跨任务持久可写树, mv 是越界突变且
    install_file(10) 会回投同毒成死循环 —— kpathsea cwd 序天然遮蔽,
    根 delegate 即最小充分面。``./revtex4.cls`` 在场则 pass 1 已决断。
    """
    root = _resolve_site(ctx, PurePosixPath("revtex4.cls"))
    if root is None or root.exists() or not _revtex_shadowed_externally(ctx, eng):
        return
    if not repl_ok:
        adv = "revtex4.cls: texmf 遮蔽命中但 revtex4-2 缺席, 搁置"
        if adv not in ctx.advisories:
            ctx.advisories.append(adv)
        return
    done, _state = _inject_write(
        ctx, root, _REV_DELEGATE_TMPL % "revtex4", "revtex4.cls"
    )
    if done is None:
        moved.append("revtex4.cls (texmf shadow -> root delegate)")
    elif done[0]:
        moved.append(done[1])
    elif done[1] not in ctx.advisories:
        ctx.advisories.append(done[1])


def revtex_era_retire(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""v4.0a revtex4.cls (内嵌 textcase v0.06 ``\@uclcnotmath``) → 退役/遮蔽。

    死因 (0806.4149/1003.0910/1907.00131 实证): v4.0a 把
    ``\MakeUppercase`` 绑死 ``\MakeTextUppercase``→``\@uclcnotmath``,
    内嵌 ``\protected@edef\reserved@a`` 在现代 kernel 上炸
    ``Illegal parameter number in definition of \reserved@a`` /
    ``Use of \@citex doesn't match`` (\Citeauthor/thebibliography/
    sectionmark 三径同机)。递补闸: revtex4-2.cls probe/vendor 双空 →
    拒动 (delegate 死路)。
    """
    del payload
    suffix = str(params.get("suffix") or ".fixloop-iso")
    repl_ok = bool(eng.probe_file("revtex4-2.cls")) or (
        _vendored_source(_vendor_root(params), "revtex4-2.cls") is not None
    )
    moved: list[str] = []
    _retire_revtex40a_files(ctx, suffix, repl_ok=repl_ok, moved=moved)
    _drop_revtex_root_delegate(ctx, eng, repl_ok=repl_ok, moved=moved)
    if not moved:
        return False, "无 v4.0a revtex4 指纹件"
    return True, f"retire revtex4-era: {', '.join(moved)}"


def vendored_fetch_multi(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    """``params.files`` 名单 → vendor/{files,stubs,shims} basename 字节平铺 wdir。

    ``vendored_fetch`` 的文本指纹注入不适用二进制资产 (lams*.tfm 等:
    utf-8 读+``%`` 指纹行头毁 TFM 二进制头) —— 本动作 ``shutil.copyfile``
    字节级落盘; dst 在场 (稿自带/前轮已投) 跳过不覆 → 幂等。
    """
    del eng, payload
    files = [str(x) for x in (params.get("files") or [])]
    if not files:
        return False, "params.files 空"
    root = _vendor_root(params)
    dropped, notes = [], []
    for fname in files:
        rel = PurePosixPath(fname)
        if not fname or rel.is_absolute() or ".." in rel.parts or "\x00" in fname:
            notes.append(f"{fname}: unsafe")
            continue
        src = _vendored_source(root, fname)
        if src is None:
            notes.append(f"{fname}: not vendored")
            continue
        dst = _resolve_site(ctx, rel)
        if dst is None:
            notes.append(f"{fname}: escapes wdir")
            continue
        if dst.exists():
            notes.append(f"{fname}: present")
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        except OSError as e:
            notes.append(f"{fname}: {e}")
            continue
        dropped.append(dst.relative_to(ctx.wdir).as_posix())
    if not dropped:
        return False, f"vendored drop 全落空: {'; '.join(notes)}"
    note = f"vendored drop: {', '.join(dropped)}"
    if notes:
        note += f" (skip: {'; '.join(notes)})"
    return True, note
