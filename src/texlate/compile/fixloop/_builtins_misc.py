"""_builtins_misc — 编码转码 / 中间件清场 / support 文件腐蚀复原 / 格式门 (C3 拆分)。

``non_utf8_recode`` 非 UTF-8 源就地转码; ``purge_corrupt_intermediates``
删引擎自产的截断 aux 族; ``restore_support_from_src`` 把被翻译写脏的
support 件从 pristine baseline 逐字节复原; ``plain_format_detect``
纯 plain/amsTeX 稿门判; ``harvest_build_directives`` 收割 arara/``!TEX``
注释指令; ``docstrip_generate`` 跑包内 .ins 抽取缺件。
"""

from __future__ import annotations

import contextlib
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.compile.transcode import INTERMEDIATE_SUFFIXES
from texlate.latex.api import NAME_GATED_TEX_SUFFIXES, parse_file
from texlate.latex.prose import file_has_prose
from texlate.textutil import CJK_RX, DOCCLASS_RX, mask_tex, safe_is_file

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx


def non_utf8_recode(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""非 UTF-8 源文件就地转码 UTF-8 (docs/08:272; iconv 等价物, stdlib 版)。

    只对 utf-8 解码真失败的文件动刀; cp1252 是 latin-1 超集, 兼容
    西文 smart quote。能 utf-8 解码的文件绝不重写。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls", ".bib"))
    recoded = []
    for f in ctx.tex_files(exts):
        raw = f.read_bytes()
        try:
            raw.decode("utf-8")
            continue
        except UnicodeDecodeError:
            pass
        for enc in ("cp1252", "latin-1"):
            with contextlib.suppress(UnicodeDecodeError):
                f.write_text(raw.decode(enc), encoding="utf-8")
                recoded.append(f"{f.name}({enc})")
                ctx.invalidate(f)
                break
    return (bool(recoded)), f"recode to utf-8: {', '.join(recoded)}"


def purge_corrupt_intermediates(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""删损坏的可再生中间件 (aux 族), 下遍引擎自动重生成 (2211.13013 同族)。

    XeTeX 写缓冲在 8192B 边界劈断多字节字符 → 自产 .aux/.toc 带非法
    UTF-8 → 下遍回读 "Invalid UTF-8 byte" + ``\@newl@bel`` EOF
    (docs/research/latex/2026-09-16-aux-cjk-truncation.md)。
    损坏谓词 = strict utf-8 解码失败 (字节劈断) 或末行不完整
    (边界恰好落在字符缝上时文件仍可解码但停在某宏参数中间——
    TeX 写出的完整行必以 \n 收尾)。健康件含 xr ``\externaldocument``
    外链 aux 一律保留; shipped 侧归 normalize 转码兜底, 本函数只管
    引擎自产件的运行时截断。
    """
    del eng, payload
    exts = {str(e).lower() for e in (params.get("exts") or INTERMEDIATE_SUFFIXES)}
    purged = []
    for f in sorted(ctx.wdir.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in exts:
            continue
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        try:
            raw.decode("utf-8")
            corrupt = not raw.endswith(b"\n")
        except UnicodeDecodeError:
            corrupt = True
        if not corrupt:
            continue
        f.unlink()
        ctx.invalidate(f)
        purged.append(str(f.relative_to(ctx.wdir)))
    return (bool(purged)), f"purged corrupt intermediates: {', '.join(purged)}"


# ════════════════════════════════════════════════════════════════
# support 文件腐蚀兜底: 偏离 pristine baseline 且被注入 CJK → 逐字节复原
# ════════════════════════════════════════════════════════════════

#: 自有写入标记 —— ``% texlate`` (inject/normalize/latex209 注入头) 与
#: ``% fixloop`` (本表各 transform 就地改写注记)。带标记的偏离是有意修复,
#: 回滚会撤销 deliberate fix。
_OWN_MARKERS = ("% texlate", "% fixloop")

#: support 判定的文件名闸 —— 单源 ``latex.api.NAME_GATED_TEX_SUFFIXES``
#: (``.rtx.tex`` REVTeX 运行时转储 / ``.code.tex`` tikzlibrary 机制件),
#: 命中即 support 免散文判；私名保留为 facade 回引柄。
_SUPPORT_SUFFIXES = NAME_GATED_TEX_SUFFIXES


def _is_support_baseline(path: Path) -> bool:
    """Baseline 件判 support: 名闸命中 ∨ 解析后无散文; 解析崩 → False (不碰)。"""
    if path.name.lower().endswith(_SUPPORT_SUFFIXES):
        return True
    try:
        res = parse_file(path, flatten=False)
    except Exception:  # noqa: BLE001 — 无法分类即按内容件处理, 绝不回滚
        return False
    return not file_has_prose(res.chunks)


def _corrupted_by_xlat(f: Path, base: Path) -> bytes | None:
    """单件判定 → 命中返回 baseline 字节 (供 verbatim 复原), 否则 None。

    条件序: 字节有偏 ∧ 无自有标记 ∧ CJK 计数超 baseline ∧ baseline 判
    support (``parse_file`` 最贵殿后)。
    """
    try:
        wb, bb = f.read_bytes(), base.read_bytes()
    except OSError:
        return None
    if wb == bb:
        return None
    wt = wb.decode("utf-8", errors="replace")
    if any(m in wt for m in _OWN_MARKERS):
        return None
    bt = bb.decode("utf-8", errors="replace")
    if len(CJK_RX.findall(wt)) <= len(CJK_RX.findall(bt)):
        return None
    return bb if _is_support_baseline(base) else None


def restore_support_from_src(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""被翻译写脏的 support 文件 → 从 ``params.baseline_dir`` pristine 树逐字节复原。

    prose gate (e2e._scan_tree) 只前向挡 bundled 机制件进翻译集; 本 builtin 收
    gate 落地前已被注入 CJK 的残案 (scout-supportfiles: pstricks/epsf/
    tikzlibrary ``*.code.tex``/宏件/gnuplot 转储)。五条件全中才动 (全
    conjunctive, 便宜的先查, ``parse_file`` 殿后): baseline 同名件在 ∧
    工作件字节有偏 ∧ 无 ``% texlate``/``% fixloop`` 自有标记 ∧ 工作件 CJK
    计数超 baseline (baseline 自带 CJK 照容) ∧ baseline 判 support。
    ``baseline_dir`` 缺失/非目录 → False fail-safe, 不抛。
    """
    del eng, payload
    base_dir = params.get("baseline_dir")
    if not base_dir:
        return False, "no baseline_dir param"
    base_root = Path(str(base_dir))
    if not base_root.is_dir():
        return False, f"baseline_dir not a directory: {base_root}"
    restored: list[str] = []
    for f in ctx.tex_files((".tex",)):
        base = base_root / f.relative_to(ctx.wdir)
        if not base.is_file() or (bb := _corrupted_by_xlat(f, base)) is None:
            continue
        f.write_bytes(bb)
        ctx.invalidate(f)
        restored.append(f.relative_to(ctx.wdir).as_posix())
    if not restored:
        return False, "no corrupted support files"
    return True, f"restored: {', '.join(restored)}"


# ════════════════════════════════════════════════════════════════
# 格式/构建指令信号面 (W37/W68/W58/W102 孤儿裁决 mechmap-2026-09-17)
# ════════════════════════════════════════════════════════════════

#: plain/amsTeX 签名池 —— 遮盖视图上评估, 活 ``\documentclass``/
#: ``\documentstyle`` 在场即整体短路 (LaTeX2.09 归 latex209_reject 收)。
#: 签名沿 inject._PLAIN_TEX_RE 口径: 装载原语 ``^\magnification`` /
#: ``\font\cs=cm*`` 族字模 / 终止符 ``^\bye$`` / 裸行 ``^\end$`` /
#: ``\input amstex`` 系宏包。
_PLAIN_SIGS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("magnification", re.compile(r"(?m)^[ \t]*\\magnification\b")),
    ("font-cm", re.compile(r"\\font\\[a-zA-Z@]+\s*=\s*cm[a-z0-9]*\b")),
    ("bye", re.compile(r"(?m)^[ \t]*\\bye[ \t]*$")),
    ("end", re.compile(r"(?m)^[ \t]*\\end[ \t]*$")),
    (
        "input-amstex",
        re.compile(r"\\input\s*\{?\s*(?:amstex|amsppt|harvmac|phyzzx|jytex|texinfo)\b"),
    ),
)


def plain_format_detect(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""纯 plain/amsTeX 稿判定 → ``REJECT: route=tex-plain`` (W37/W68 孤儿裁决)。

    遮盖视图双条件全中才拒: 无活 ``\documentclass``/``\documentstyle`` ∧
    ≥1 plain 行锚签名。可达场景 = 主检出宽松档 ``find_main_tex`` 扫 raw
    头 60KB, 被注释伪装行 (``%\documentstyle``) 骗入主 —— 纯 plain 零主
    档案已由 ``classify_no_main`` 归 ``no_main_tex:plain_tex`` 不经过此。
    判定不中 → False 让位 loop, 不消耗轮次。
    """
    del eng, payload
    blob = mask_tex(ctx.source_blob())
    if DOCCLASS_RX.search(blob):
        return False, "live \\documentclass/\\documentstyle present — not plain"
    hits = [name for name, rx in _PLAIN_SIGS if rx.search(blob)]
    if not hits:
        return False, "no plain-format signatures"
    route = str(params.get("route") or "tex-plain")
    return True, f"REJECT: route={route} plain-format doc (sigs: {', '.join(hits)})"


#: 注释内构建指令锚 —— 与全局注释遮盖惯例相反: 本族注释本体即信号。
_ARARA_LINE_RE = re.compile(r"(?im)^[ \t]*%+\s*arara:\s*([^\n]+)")
_TEX_PROGRAM_RE = re.compile(
    r"(?im)^[ \t]*%+\s*!\s*TEX\s+(?:TS-)?program\s*=\s*([^\s%]+)"
)
_TEX_OPTIONS_RE = re.compile(
    r"(?im)^[ \t]*%+\s*!\s*TEX\s+(?:TS-)?options?\s*=\s*([^\n]+)"
)
#: shell 逃逸诉求: arara ``{shell: on|yes|true}`` 或直书 ``--shell-escape``
#: /``-enable-write18`` (miktex 名同收)。
_SHELL_HINT_RE = re.compile(
    r"(?i)(?:shell\s*:\s*(?:on|yes|true)|--?shell-escape|--?enable-write18)"
)


def _scan_build_directives(blob: str) -> tuple[list[str], list[str], bool]:
    r"""未遮盖 blob 扫三类指令 → (arara 规则行, ``!TEX program`` 列表, shell 诉求)。

    注释本体即信号 —— 调用方传 raw blob (与全局 mask 惯例相反)。
    """
    arara_rules: list[str] = []
    want_shell = False
    for m in _ARARA_LINE_RE.finditer(blob):
        rule_line = m.group(1).strip()
        arara_rules.append(rule_line)
        want_shell |= bool(_SHELL_HINT_RE.search(rule_line))
    programs = [m.group(1).strip() for m in _TEX_PROGRAM_RE.finditer(blob)]
    for m in _TEX_OPTIONS_RE.finditer(blob):
        want_shell |= bool(_SHELL_HINT_RE.search(m.group(1)))
    return arara_rules, programs, want_shell


def harvest_build_directives(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""arara/``!TEX`` 注释指令收割 → advisory/``engine_flags`` 建议 (W58 孤儿裁决)。

    信号收割型不改源: ``% arara: <rule>: {shell: on}`` / ``!TEX program=X``
    是作者明示构建需求但编译循环无人收割。shell 诉求 → 往
    ``ctx.engine_flags`` 请 ``-shell-escape`` (引擎 seam 自管拒放:
    tectonic/无沙箱 xelatex 落 ``flags_dropped``); ``!TEX program`` 与
    arara 规则名 → 记 ``ctx.advisories`` 账本 (重路由权在 reject_route,
    收割只记不动)。无 actionable 信号 → False。
    """
    del eng, payload, params
    arara_rules, programs, want_shell = _scan_build_directives(ctx.source_blob())
    actions: list[str] = []
    if want_shell and "-shell-escape" not in ctx.engine_flags:
        ctx.engine_flags.append("-shell-escape")
        actions.append("engine_flags +(-shell-escape)")
    for line in arara_rules:
        adv = f"build-directive arara: {line}"
        if adv not in ctx.advisories:
            ctx.advisories.append(adv)
    for prog in programs:
        adv = f"build-directive !TEX program={prog} (engine={ctx.engine_name})"
        if adv not in ctx.advisories:
            ctx.advisories.append(adv)
    if programs:
        actions.append("!TEX program=" + ",".join(dict.fromkeys(programs)))
    if arara_rules:
        actions.append(f"arara x{len(arara_rules)}")
    if not actions:
        return False, "directive anchor hit but no actionable signal"
    return True, "harvested " + "; ".join(actions)


#: docstrip 驱动器序 —— ``latex`` 为规范名, 缺则退 pdftex 系/裸 tex。
_DOCSTRIP_DRIVERS = ("latex", "pdflatex", "xelatex", "tex")


def docstrip_generate(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""包内自带 ``.ins`` → docstrip 抽取缺件 (W102; bundled dtx 是作者钦定版本)。

    定位序: ``.ins`` basename stem == payload stem (``aipproc.ins``→
    ``aipproc.cls``), 或包内唯一 ``.ins`` 兜底。``latex -interaction=
    nonstopmode <ins>`` 跑抽取 (bbl_regen ``run_tool`` 先例; web2c 会把主
    输入件所在目录并入搜索路径, ins/dtx 同目录自然可解), 复核 payload
    落盘后 applied; 生成失败 → False 同轮续扫落 install_file(10) 装 TL 版。
    """
    del eng
    want = (payload or "").strip()
    rel = PurePosixPath(want)
    if not want or rel.is_absolute() or ".." in rel.parts or "\x00" in want:
        return False, f"unsafe payload {want!r}"
    ins_all = sorted(p for p in ctx.wdir.rglob("*.ins") if p.is_file())
    stem = rel.stem.lower()
    cands = [p for p in ins_all if p.stem.lower() == stem]
    if not cands and len(ins_all) == 1:
        cands = ins_all  # 唯一 ins 兜底 (stem 不对应也试一次)
    if not cands:
        return False, f"no .ins matching {want}"
    driver = next(
        (d for d in params.get("drivers") or _DOCSTRIP_DRIVERS if shutil.which(d)),
        None,
    )
    if driver is None:
        return False, "no latex-family driver for docstrip"
    timeout = int(params.get("timeout", 60))
    for ins in cands:
        rel_ins = ins.relative_to(ctx.wdir).as_posix()
        rc, _out, to = ctx.run_tool(
            [driver, "-interaction=nonstopmode", rel_ins], timeout
        )
        ctx.events.append(f"docstrip {rel_ins} -> rc={rc}{' TIMEOUT' if to else ''}")
        hit = ctx.wdir / Path(*rel.parts)
        if not safe_is_file(hit):
            alt = next((p for p in ctx.wdir.rglob(rel.name) if p.is_file()), None)
            hit = alt if alt is not None else hit
        if safe_is_file(hit):
            ctx.invalidate(hit)
            return True, f"docstrip {rel_ins} generated {hit.relative_to(ctx.wdir)}"
    return False, f"docstrip ran but {want} not produced"


# ════════════════════════════════════════════════════════════════
# tar 伪装件解包: e-print 内嵌 tar 以 .sty/.cls 名落盘 → 抽成员补缺
# ════════════════════════════════════════════════════════════════

#: POSIX ustar 魔数 ``ustar`` 驻留偏移 257 (tar header magic field)。
_TAR_MAGIC_OFF = 257
_TAR_MAGIC = b"ustar"

#: 伪装判定扩展名集——tar blob 只在文本类名下才有害 (二进制件 .eps/.pdf
#: 不查；``.tarblob`` 是本方改名件, 重扫须免再命中)。
_TARBLOB_EXTS = frozenset(
    {
        ".tex",
        ".sty",
        ".cls",
        ".clo",
        ".def",
        ".fd",
        ".cfg",
        ".bst",
        ".bib",
        ".ins",
        ".dtx",
        ".ltx",
        ".stytxt",
    }
)


def _is_tar_blob(f: Path) -> bool:
    """Tar 魔数探针——读 262B 判 POSIX tar (ustar) 伪装件。"""
    try:
        with f.open("rb") as fh:
            fh.seek(_TAR_MAGIC_OFF)
            return fh.read(len(_TAR_MAGIC)) == _TAR_MAGIC
    except OSError:
        return False


def _safe_member_name(name: str) -> PurePosixPath | None:
    """成员名卫: 剥 ``./`` 前缀后拒绝对路径/``..``/空名/含 NUL。"""
    n = name
    while n.startswith("./"):
        n = n[2:]
    if not n or "\x00" in n:
        return None
    rel = PurePosixPath(n)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    return rel


def _extract_members(ctx: LoopCtx, f: Path) -> int:
    """抽 tar ``f`` 的 regular-file 成员补缺落 ``f.parent`` → 落地数 (0=非本机制案)。"""
    import tarfile  # noqa: PLC0415 — 冷路径: 命中伪装件才用, 不污染常规启动

    extracted = 0
    try:
        with tarfile.open(f) as tf:
            for m in tf.getmembers():
                if not m.isreg():
                    continue
                rel = _safe_member_name(m.name)
                if rel is None:
                    continue
                dest = f.parent / Path(*rel.parts)
                if dest.exists():
                    continue
                src = tf.extractfile(m)
                if src is None:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(src.read())
                ctx.invalidate(dest)
                extracted += 1
    except (tarfile.TarError, OSError):
        return 0
    return extracted


def extract_tar_blobs(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""工作树内 tar 伪装件 → 成员补缺解包 + blob 改名 ``*.tarblob`` 退役。

    arXiv e-print 偶发把整包源码以嵌套 tar 随投稿——外层解包后 tar 以
    ``.sty``/``.cls`` 名落进工作树 (0707.0382 ``AMSbsy.sty``=全 bundle tar、
    astro-ph/0104007 ``aipproc.cls``=aipproc.sty+figs+symposium.tex tar,
    loop2 fixloop 实证): TeX ``\input`` 读 tar 头成排版文本 →
    ``Missing \begin{document}`` 于伪装件第 N 行 (``l.30 AMSfonts.sty^^@``)。

    解包纪律: 仅 regular file 成员 (tarfile.extractfile 逐件读字节自写,
    不依赖平台 filter 语义); 名卫拒 ``..``/绝对/``./`` 残件/NUL;
    **no-clobber**——目标已存在跳过 (真件优先, tar 只补缺); blob 本体
    只在抽中 ≥1 成员后改名 ``{name}.tarblob`` 退役 (移出 TeX 解析路径、
    留现场可审计; 0 成员说明非本机制案, 原样放回)。
    """
    del eng, payload
    exts = {str(e).lower() for e in (params.get("exts") or _TARBLOB_EXTS)}
    done: list[str] = []
    for f in sorted(ctx.wdir.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in exts:
            continue
        if not _is_tar_blob(f):
            continue
        extracted = _extract_members(ctx, f)
        if extracted:
            blob_name = f.name + ".tarblob"
            f.rename(f.with_name(blob_name))
            ctx.invalidate(f)
            done.append(f"{f.name}({extracted} members)")
    return (bool(done)), f"tar blobs extracted: {', '.join(done)}"
