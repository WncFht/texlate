r"""builtins.assetfix — 随稿资产改形补缺 (builtins.misc C3 再拆叶)。

缺的引用的资产件不从索引装包、而从 wdir 内既有资产改形落位:
``pfa_to_pfb`` 把 pdftex.map 引用的 ASCII Type1 ``.pfa`` 转 usertree
``.pfb`` + map 同位遮蔽; ``eps_converted_alias`` 把随稿
``X-eps-converted-to.pdf`` 落 ``<stem>.pdf`` 别名 + eps 族显式引用剥名。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path, PurePath, PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import (
    _in_wdir,
    _live_matches,
    _safe_rel,
    _splice,
    _wdir_project_files,
)
from texlate.compile.fixloop.builtins.gfx_missing import (
    _EPS_KV_RE,
    _GRAPHIC_EXTS,
    _INCLUDE_GFX_RE,
    _KV_FILE_RE,
)
from texlate.compile.fixloop.builtins.graphics import (
    _EPS_EXTS,
    _NUMERIC_EXT_RE,
    _norm_graphic_name,
)
from texlate.textutil import safe_is_file

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.compile.fixloop.engine import Engine, LoopCtx


# ════════════════════════════════════════════════════════════════
# xdvipdfmx .pfa 硬墙：ASCII Type1 → usertree .pfb + map 遮蔽 (1907.03923)
# ════════════════════════════════════════════════════════════════

#: eexec 段起始锚 —— ASCII 头/密文边界。
_EEXEC_MARK_RX = re.compile(rb"currentfile eexec[ \t]*\r?\n")

#: map 行内 ``<name.pfa``/``<<name.pfa`` 引用 token —— ``<`` 前缀锚定
#: 免 stem 后缀误吃 (``<pen.pfa`` 不会中 ``<pigpen.pfa``); 扩展名大小写兼收。
_MAP_PFA_RX = re.compile(r"<<?([^\s\"'<>]+\.pfa)\b", re.IGNORECASE)

#: pdftex.map 分块源注释 ``% <pkg>.map`` —— updmap 合并逐块标源，反查
#: 字体条目所属 dvips map 名 (供 usertree 同位遮蔽)。头部 ``% /path/....map:``
#: 注释带冒号尾/路径，``\S+\.map`` 尾锚同排。
_MAP_SRC_RX = re.compile(r"^%[ \t]+(\S+\.map)[ \t]*$")


def _pfa_to_pfb_bytes(data: bytes) -> bytes | None:
    r"""ASCII Type1 (.pfa) → PFB 三段包封; 非 eexec 形返回 None。

    t1binary 的纯 python 等价: seg1 = 头到 ``currentfile eexec`` 行止
    (ASCII), seg2 = eexec 密文 hex 解码原样 (PFB 段二存的就是密文本身,
    无需解密), seg3 = ``cleartomark`` 前连 ``0`` 填充起的 ASCII 尾巴
    (t1binary 同口径: 连 ``0`` run 属 ASCII 段)。帧 = ``0x80|01``
    + LE32 + seg1, ``0x80|02`` + LE32 + seg2, ``0x80|01`` + LE32 + seg3,
    ``0x80|03`` 收尾。
    """
    m = _EEXEC_MARK_RX.search(data)
    if m is None:
        return None
    seg1 = data[: m.end()]
    rest = data[m.end() :]
    j = rest.find(b"cleartomark")
    if j < 0:
        return None
    while j > 0 and rest[j - 1] in b"0 \t\r\n":
        j -= 1
    hexs = bytes(c for c in rest[:j] if c in b"0123456789abcdefABCDEF")
    seg2 = bytes.fromhex(hexs.decode("ascii"))
    seg3 = rest[j:]

    def _frame(tag: int, blob: bytes) -> bytes:
        return b"\x80" + bytes([tag]) + len(blob).to_bytes(4, "little") + blob

    return _frame(1, seg1) + _frame(2, seg2) + _frame(1, seg3) + b"\x80\x03"


def _safe_map_name(name: str) -> PurePosixPath | None:
    """Map token 名卫：拒绝对路径/``..``/空名/含 NUL —— 只信 basename 级引用。"""
    return _safe_rel(name)


def _convert_map_pfas(
    ctx: LoopCtx, probe: Callable[..., str | None], texmf: Path, names: list[str]
) -> list[str]:
    """Map 引用的 .pfa 逐个 probe+ 转换 → usertree ``home/fonts/type1/`` 落 .pfb。

    返回转换成功的 token 名表 (保序); probe 不到/读不了/非 eexec 形跳过。
    """
    converted: list[str] = []
    for name in names:
        rel = _safe_map_name(name)
        if rel is None:
            continue
        hit = probe(name, cwd=ctx.wdir)
        if not hit:
            continue
        try:
            pfb = _pfa_to_pfb_bytes(Path(hit).read_bytes())
        except OSError:
            continue
        if pfb is None:
            continue
        dest = texmf / "home" / "fonts" / "type1" / rel.with_suffix(".pfb")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not safe_is_file(dest) or dest.read_bytes() != pfb:
            dest.write_bytes(pfb)
        converted.append(name)
    return converted


def _shadow_src_maps(
    ctx: LoopCtx,
    probe: Callable[..., str | None],
    texmf: Path,
    map_text: str,
    converted: list[str],
) -> int:
    r"""``% <pkg>.map`` 块注释反查各 .pfa 所属源 map → usertree 同路径遮蔽。

    updmap 再生 pdftex.map 走 dvips map 面扫描 —— ``texmf/home/fonts/map/``
    下同路径副本先于系统树被扫, 保后续 ``updmap-user`` run_tool 重建后
    遮蔽仍生效 (missing_pfb_updmap 同波序保险)。返回落地遮蔽数。
    """
    src_of: dict[str, str] = {}
    cur = ""
    for ln in map_text.split("\n"):
        if cm := _MAP_SRC_RX.match(ln):
            cur = cm.group(1)
        elif (pm := _MAP_PFA_RX.search(ln)) and cur:
            src_of.setdefault(pm.group(1), cur)
    shadows = 0
    for src_name in sorted(set(src_of.values())):
        hit = probe(src_name, cwd=ctx.wdir)
        if not hit:
            continue
        sp = Path(hit)
        try:
            stext = sp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        patched = stext
        for name in converted:
            if src_of.get(name) == src_name:
                patched = patched.replace("<" + name, "<" + name[:-4] + ".pfb")
        if patched == stext:
            continue
        posix = sp.as_posix()
        i = posix.find("/fonts/map/")
        rel = posix[i + len("/fonts/map/") :] if i >= 0 else "dvips/" + sp.name
        dest = texmf / "home" / "fonts" / "map" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(patched, encoding="utf-8")
        ctx.invalidate(dest)
        shadows += 1
    return shadows


def pfa_to_pfb(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Xdvipdfmx ``pfa format not supported`` fatal → usertree .pfb + map 遮蔽。

    xdvipdfmx 拒 ASCII Type1 按扩展名非内容嗅探 (1907.03923 pigpen 实证:
    ``\\usepackage{pigpen}`` → ``pigpen.map`` 行 ``pigpen <pigpen.pfa``
    折进 pdftex.map → fatal); fatal 行只落 stdout_tail (.log 干净) 归一
    成 ``!`` 后按 ``other`` 派发, 字体名不随签名 —— 修面 = 解析到的
    ``pdftex.map`` 全量 ``<X.pfa`` 引用。产物全落 usertree
    (``eng.texmfhome``) 不动宿主树:

    - 转换 .pfb → ``texmf/home/fonts/type1/<token 相对径>`` —— T1FONTS
      usertree-home 先于系统树;
    - 改写 ``pdftex.map`` → ``texmf/var/fonts/map/pdftex/updmap/`` ——
      TEXFONTMAPS 的 TEXMFVAR 位先于 sysvar/dist (非 ``!!`` 段免 ls-R);
      map 本体在工程内 (``.`` 首位) 则就地改写;
    - 各 ``<X.pfa`` 所属源 ``<pkg>.map`` 同路径遮蔽 →
      ``texmf/home/fonts/map/dvips/…`` (``_shadow_src_maps``)。

    texmfhome/probe 缺席 / pdftex.map 不可解 / 无 .pfa 引用 / 全部转换
    失败 → False 让位, 不消耗轮次。
    """
    del payload, params
    texmf = getattr(eng, "texmfhome", None)
    probe = getattr(eng, "probe_file", None)
    if texmf is None or probe is None:
        return False, "engine lacks texmfhome/probe_file usertree surface"
    texmf = Path(texmf)
    map_hit = probe("pdftex.map", cwd=ctx.wdir)
    if not map_hit:
        return False, "pdftex.map unresolvable"
    map_path = Path(map_hit)
    try:
        text = map_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False, f"pdftex.map unreadable: {map_path}"
    names = list(dict.fromkeys(m.group(1) for m in _MAP_PFA_RX.finditer(text)))
    if not names:
        return False, "no .pfa refs in resolved pdftex.map"
    converted = _convert_map_pfas(ctx, probe, texmf, names)
    if not converted:
        return False, f"no convertible .pfa among {len(names)} ref(s)"
    patched = text
    for name in converted:
        patched = patched.replace("<" + name, "<" + name[:-4] + ".pfb")
    try:
        in_wdir = map_path.resolve().is_relative_to(ctx.wdir.resolve())
    except OSError:
        in_wdir = False
    dest_map = (
        map_path
        if in_wdir
        else texmf / "var" / "fonts" / "map" / "pdftex" / "updmap" / "pdftex.map"
    )
    dest_map.parent.mkdir(parents=True, exist_ok=True)
    dest_map.write_text(patched, encoding="utf-8")
    ctx.invalidate(dest_map)
    shadows = _shadow_src_maps(ctx, probe, texmf, text, converted)
    return True, (
        f"pfa->pfb {len(converted)} font(s): {', '.join(converted)} "
        f"(map shadow +{shadows} src .map)"
    )


# ════════════════════════════════════════════════════════════════
# *-eps-converted-to.pdf 随稿别名臂 (firedunfixed item5)
# ════════════════════════════════════════════════════════════════

#: 上游 epstopdf 自动转换产物尾缀 —— ``epstopdf X.eps`` 落
#: ``X-eps-converted-to.pdf`` 与源并置; arXiv 处理链产物常随 e-print
#: 分发而 ``X.eps`` 本体不随稿 (与 .eps 缺件同族的反方向)。
_EPS_CONV_TAIL = "-eps-converted-to.pdf"

#: 提名回收正则 —— other|None / payload 缺席轮从 err_head 重导文件名;
#: ``File `X' not found`` 收无扩展名变体 (taxonomy 条目要求 ``\.\w+``)。
_FILE_NF_RX = re.compile(r"File `([^']+)' not found")
_UNABLE_LOAD_RX = re.compile(r"Unable to load picture or PDF file '([^']+)'")
_IMG_FAIL_RX = re.compile(r'image inclusion failed for "([^"]+)"')

#: kv 形里允许剥名的宿主命令 —— epsfig/psfig 走 graphicx 补全机制;
#: epsffile/epsfbox 是裸 PS 装载点，``{X}`` 无扩展名不解析，不剥。
_EPS_KV_STRIP_CMDS = frozenset({"epsfig", "psfig"})

#: 别名受理的显式扩展名 —— eps 族 + ``.pdf`` (conv 件本来就是
#: eps→pdf 产物; ``.png/.jpg`` 显式缺件与 conv 件无语义对应不落)。
_EPS_CONV_ALIAS_EXTS = frozenset((*_EPS_EXTS, ".pdf"))


def _is_rel_escape(rel: PurePath) -> bool:
    """相对名逃逸判——绝对路径 ∨ ``..`` 段 (待 hoist ``textutil.osutil.is_rel_escape``)。"""
    return rel.is_absolute() or ".." in rel.parts


def _verbatim_graphic_hit(base: Path, want: str) -> bool:
    r"""引用串按 TeX 字面解析位已有档。

    带扩展名查原名; 无扩展名查 graphicx ``\Gin@extensions`` 全族补全
    (``base`` = compile cwd)。
    """
    if PurePosixPath(want).suffix:
        return safe_is_file(base / want)
    return any(safe_is_file(base / (want + e)) for e in _GRAPHIC_EXTS)


def _conv_sibling(ctx: LoopCtx, base: Path, stem: PurePosixPath) -> Path | None:
    r"""定位 ``<stem>-eps-converted-to.pdf``。

    引用同目录 → cwd 根 → wdir 全树 basename ci (``arvix/`` 类旁置
    子目录兜底; 多命中取深度+路径序首件保确定性; 引擎树/隐藏件不算)。
    """
    name = stem.name + _EPS_CONV_TAIL
    for cand in (base / stem.parent / name, base / name):
        if safe_is_file(cand):
            return cand
    low = name.lower()
    hits = [p for p, _parts in _wdir_project_files(ctx) if p.name.lower() == low]
    if not hits:
        return None
    return min(hits, key=lambda p: (len(p.parts), p.as_posix()))


def eps_converted_alias(  # noqa: C901, PLR0912, PLR0915  # 逐门 decline note 即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``*-eps-converted-to.pdf`` 随稿件 → ``<stem>.pdf`` 别名 + eps 族引用剥名。

    firedunfixed 普查 item5 (2403.05444/2308.04278): e-print 随带
    ``X-eps-converted-to.pdf`` (上游 epstopdf 产物) 而 ``X.eps`` 不在盘;
    稿面未载 epstopdf —— 显式 ``{X.eps}`` 报 ``missing_file|X.eps``
    (graphic_ext_relax sibling 闸收进 stem 域后 conv 件 ``X-eps-converted-to``
    ≠ ``X`` 不再放行), 裸 ``{X}`` 报无扩展名 ``File `X' not found`` 归
    ``other|None`` 死路。两臂资产侧修复不改语义:

    - 提名 = payload + err_head 双句式 + 存活引用全扫
      (``\includegraphics``/``\epsfig``-kv; 首轮 halt_on_error 只报首件,
      扫描臂一次铺全免逐件逐轮)。字面可解的引用跳过 —— 真图在盘 /
      epstopdf 在位的 clean 稿不触;
    - ``<stem>-eps-converted-to.pdf`` 在盘 → ``shutil.copyfile`` 落
      ``<cwd>/<refdir>/<stem>.pdf`` —— 裸 ``{X}``/``{X.pdf}`` 经
      ``.pdf`` 补全即解;
    - eps 族显式引用 ``{X.eps}`` → 剥扩展名改写 ``{X}`` 让别名接管
      (eps_to_pdf 「转换+改写」同 builtin 先例; epsffile/epsfbox 无
      ``\Gin@extensions`` 机制不剥)。``X.pdf`` 已在位时无 conv 件也剥。

    ``..``/绝对路径/NUL 拒 + resolve 后须在 wdir 内 (fileset_relocate
    同轨双层守卫)。
    """
    del eng
    mp = ctx.main_path()
    base = mp.parent if mp is not None else ctx.wdir
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    names: list[str] = [payload] if payload else []
    head = ctx.err_head or ""
    for rx in (_FILE_NF_RX, _UNABLE_LOAD_RX, _IMG_FAIL_RX):
        names.extend(m.group(1) for m in rx.finditer(head))
    live: list[tuple[Path, tuple[int, int], str, bool]] = []
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        for m in _live_matches(_INCLUDE_GFX_RE, t):
            live.append((f, m.span(2), m.group(2), True))
            names.append(m.group(2))
        for m in _live_matches(_EPS_KV_RE, t):
            cmd = m.group(0)[1 : m.group(0).index("{")].strip()
            kv = _KV_FILE_RE.search(m.group(1))
            if cmd in _EPS_KV_STRIP_CMDS and kv:
                span = (m.start(1) + kv.start(1), m.start(1) + kv.end(1))
                live.append((f, span, kv.group(1), True))
                names.append(kv.group(1))
    served: dict[str, Path] = {}
    tried: set[str] = set()
    made: list[str] = []
    for raw in names:
        want = _norm_graphic_name(raw or "")
        if not want or "\x00" in want:
            continue
        p = PurePosixPath(want)
        if _is_rel_escape(p):
            continue
        suffix = p.suffix.lower()
        if (
            suffix
            and suffix not in _EPS_CONV_ALIAS_EXTS
            and not _NUMERIC_EXT_RE.match(suffix)
        ):
            continue
        stem = p.parent / p.stem
        key = stem.as_posix().lower()
        if key in tried:
            continue
        tried.add(key)
        if _verbatim_graphic_hit(base, want):
            continue
        target = base / (stem.as_posix() + ".pdf")
        if not safe_is_file(target):
            conv = _conv_sibling(ctx, base, stem)
            if conv is None:
                continue
            if not _in_wdir(ctx, target):
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(conv, target)
            except OSError:
                continue
            ctx.invalidate(target)
            made.append(
                f"{stem.as_posix()}.pdf<-{conv.relative_to(ctx.wdir).as_posix()}"
            )
        served[key] = target
    strips: dict[Path, list[tuple[int, int, str]]] = {}
    for f, span, arg, stripable in live:
        if not stripable:
            continue
        want = _norm_graphic_name(arg)
        if not want:
            continue
        p = PurePosixPath(want)
        suffix = p.suffix.lower()
        if suffix not in _EPS_EXTS and not _NUMERIC_EXT_RE.match(suffix):
            continue
        if _is_rel_escape(p):
            continue
        stem = p.parent / p.stem
        if stem.as_posix().lower() not in served:
            continue
        tail = arg.rstrip()
        if not tail.endswith(p.suffix):
            continue
        new_arg = arg[: len(tail) - len(p.suffix)] + arg[len(tail) :]
        strips.setdefault(f, []).append((span[0], span[1], new_arg))
    edited: list[str] = []
    for f, spans in strips.items():
        t = ctx.read(f)
        if t is None:
            continue
        ctx.write(f, _splice(t, spans))
        edited.append(f"{f.name}×{len(spans)}")
    if not made and not edited:
        return False, "no shipped -eps-converted-to.pdf sibling for missing refs"
    note = []
    if made:
        note.append(f"alias: {', '.join(made)}")
    if edited:
        note.append(f"eps-ext stripped: {', '.join(edited)}")
    return True, "; ".join(note)
