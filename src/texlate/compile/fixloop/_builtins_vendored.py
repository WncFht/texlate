r"""_builtins_vendored — 工程内遮蔽探测/隔离 + 随包 vendored 件取放 (C3 拆分)。

``\\ProvidesX`` 日期面比对确证工程内 .sty/.cls 更旧遮蔽系统件;
``vendor/`` 随包件 (files/ 真件 + stubs/ 最小宏面) 平铺救 off-CTAN
绝版宏。``_vendor_root``/``_vendored_source`` 被 engine.vendored 查件
复用 (同语义 basename 查件)。
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_common import (
    _FINGERPRINT_RE,
    _LEGACY_INJECTED_HEADS,
    _inject_write,
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
    for f in ctx.tex_files(exts):
        resolved = eng.probe_file(f.name)
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
    resolved = eng.probe_file(core.name)
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
    return f"{core.name} (paired core {ld} < {sd})"


def vendored_shadow_isolate(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    """确证更旧的工程内 .sty/.cls → rename ``<f>.fixloop-iso`` 隔离 (docs/08:269)。

    ``sd=None`` 的 tectonic 索引候选是 advisory 级 —— 无日期面确证新旧,
    不 rename, 记 ``bundle provides <pkg>`` advisory (幂等去重)。

    ``params.cohort_map``：``sty 名 → 同包伴船 glob 表``——确证更旧的包其
    vendored 伴船件（.def/.bbx/.cbx/.lbx 等）一并隔离，否则留下旧伴船与
    系统新主件混栈（1907.00257 半栈 biblatex/2003.10727 全栈实证——只隔
    biblatex.sty 会留 vendored *.def 继续遮蔽系统件）。

    wrapper+core 一体件 (pst-* 族 X.sty/X.tex): 退役 wrapper 后同 stem
    稿自带 .tex 核同道闸确证一并退役 (``_retire_paired_tex_core``)。
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
        paired = _retire_paired_tex_core(ctx, eng, f, suffix)
        if paired:
            moved.append(paired)
        for pat in cohort_map.get(f.name, ()):
            for sib in ctx.wdir.rglob(str(pat)):
                if not sib.is_file() or sib.name.endswith(suffix) or sib == f:
                    continue
                sib.rename(sib.with_name(sib.name + suffix))
                moved.append(f"{sib.relative_to(ctx.wdir)} (cohort)")
    if not moved:
        return False, "无确证更旧的可隔离遮蔽"
    return True, f"isolate vendored: {', '.join(moved)}"


#: repo 随发 vendored 件子层 —— ``files/`` 真件 (许可逐件核过) 先于
#: ``stubs/`` 最小宏面 stub; disposition 路由在 inventory 侧已结清。
_VENDOR_SUBDIRS = ("files", "stubs")


def _vendor_root(params: dict[str, Any]) -> Path:
    """Repo vendored 件根: ``params.dir`` 覆盖, 默认包内 ``vendor/``。"""
    d = params.get("dir")
    return Path(d) if d else Path(__file__).resolve().parent / "vendor"


def _vendored_source(root: Path, fname: str) -> Path | None:
    """Basename 查件: files/ → stubs/ 序; 命中返回源路径否则 None。"""
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
    dst = ctx.wdir / Path(*rel.parts)
    tier = "files" if src.parent.name == "files" else "stubs"
    body = src.read_text(encoding="utf-8", errors="replace")
    # 指纹闸 (b3a): 同名片四分判——外来件(稿自带/真包)永不覆写; 旧代
    # 注入件 (无指纹但带 vendored/fixloop 行头标记) 覆写刷新。
    done, state = _inject_write(ctx, dst, body, fname)
    if done is not None:
        return done
    tag = "refreshed (stale injected)" if state == "stale" else "->"
    return (
        True,
        f"vendored[{tier}] {src.name} {tag} {dst.relative_to(ctx.wdir)}",
    )
