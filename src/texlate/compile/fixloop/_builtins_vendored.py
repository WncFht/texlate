r"""_builtins_vendored — 工程内遮蔽探测/隔离 + 随包 vendored 件取放 (C3 拆分)。

``\\ProvidesX`` 日期面比对确证工程内 .sty/.cls 更旧遮蔽系统件;
``vendor/`` 随包件 (files/ 真件 + stubs/ 最小宏面) 平铺救 off-CTAN
绝版宏。``_vendor_root``/``_vendored_source`` 被 engine.vendored 查件
复用 (同语义 basename 查件)。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.textutil import safe_is_file

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx

_DATE_RE = re.compile(
    r"\\Provides(?:Package|Class|ExplPackage|ExplClass)\s*\{[^}]*\}\s*\[(\d{4})[/.-](\d{2})[/.-](\d{2})"
)
#: 日期面宏间址——``\ProvidesPackage{x}[\abx@date\space v...]`` 形（biblatex
#: v3.12 实证：字面日期不在 bracket 而在同文件 ``\def\abx@date{2018/11/02}``）。
_DATE_INDIRECT_RE = re.compile(
    r"\\Provides(?:Package|Class|ExplPackage|ExplClass)\s*\{[^}]*\}\s*\[\s*\\([a-zA-Z@]+)"
)


def _provides_date(text: str) -> tuple[int, int, int] | None:
    r"""``\ProvidesX{..}[YYYY/MM/DD]`` 字面日期 → ``(y, m, d)``。

    字面缺时 bracket 首 cs 走同文件 ``\def\<cs>{YYYY/MM/DD}`` 宏间址兜底
    （biblatex v3.12 ``[\abx@date ...]`` 实证；vendored/系统两侧同法，
    比较仍成立）。
    """
    m = _DATE_RE.search(text)
    if m is None:
        ind = _DATE_INDIRECT_RE.search(text)
        if ind is None:
            return None
        m = re.search(
            r"\\def\\"
            + re.escape(ind.group(1))
            + r"\s*\{(\d{4})[/.-](\d{2})[/.-](\d{2})\}",
            text,
        )
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
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    except OSError as e:
        return False, f"vendored copy {src.name} failed: {e}"
    tier = "files" if src.parent.name == "files" else "stubs"
    return True, f"vendored[{tier}] {src.name} -> {dst.relative_to(ctx.wdir)}"
