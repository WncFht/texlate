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

from texlate.compile.fixloop._builtins_common import _live_matches, _map_tex_files
from texlate.compile.fixloop._builtins_graphics import (
    _EPS_EXTS,
    _EPS_KV_RE,
    _GRAPHIC_EXTS,
    _INCLUDE_GFX_RE,
    _KV_FILE_RE,
    _NUMERIC_EXT_RE,
    _norm_graphic_name,
)
from texlate.compile.inject import _walk_inputs
from texlate.compile.latex209 import upgrade_209
from texlate.compile.normalize import normalize_legacy_cjk
from texlate.compile.transcode import INTERMEDIATE_SUFFIXES
from texlate.latex.api import NAME_GATED_TEX_SUFFIXES, parse_file
from texlate.latex.prose import file_has_prose
from texlate.textutil import (
    _TAR_HEADER_LEN,
    CJK_RX,
    DOCCLASS_RX,
    INPUT_BARE_RX,
    _tar_disguised,
    _tar_header_ok,
    decode_tex,
    mask_tex,
    safe_is_file,
)

if TYPE_CHECKING:
    from collections.abc import Callable

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
                ctx.write(f, raw.decode(enc))
                recoded.append(f"{f.name}({enc})")
                break
    return (bool(recoded)), f"recode to utf-8: {', '.join(recoded)}"


def cjk_env_relax(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``Package CJK Error: Invalid character code`` → 旧 CJK env+pkg 换装 xeCJK。

    ``normalize_legacy_cjk`` 同口径: ``\begin{CJK*?}{enc}{fam}`` → 分组
    ``{…}``, ``CJK``/``CJKutf8`` 包 → ``xeCJK``+Fandol 字体组。
    8-bit CJK env 只收声明编码槽内码位 —— zh 臂 normalize 全件预中和,
    本臂兜 normalize 漏网面 (base 对照档/replay/fileset 边缘件)。字节级
    ``decode_tex`` 读档: GBK/Big5 档 (1607.00157 形) 转码保真进改写,
    ``ctx.read`` 的 utf-8+replace 会先把汉字读成 U+FFFD 再写回毁档。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    changed = []
    for f in ctx.tex_files(exts):
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        text = decode_tex(raw)
        nt = normalize_legacy_cjk(text, ctx.engine_name)
        if nt != text:
            ctx.write(f, nt)
            changed.append(f.name)
    return bool(changed), f"legacy CJK → xeCJK+group: {', '.join(changed)}"


def _payload_purge_re(
    payload: str | None, allow: object, pay_exts: set[str]
) -> re.Pattern[bytes] | None:
    r"""白名单放行的机械族 cs → 字节搜索式 (含 ``(?![A-Za-z@])`` 边界, ``\b`` 对 @ 失效)。"""
    if not (payload and allow and pay_exts):
        return None
    name = str(payload).strip().lstrip("\\")
    if not re.fullmatch(str(allow), name):
        return None
    pat = rb"\\" + re.escape(name.encode("utf-8")) + rb"(?![A-Za-z@])"
    return re.compile(pat)


def _corrupt_intermediate(raw: bytes) -> bool:
    r"""Strict utf-8 解码失败, 或末行不完整 (TeX 写出的完整行必以 ``\n`` 收尾)。"""
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return not raw.endswith(b"\n")


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

    payload 锚定臂 (scaneof lane, m1k aux-malformed 簇): runaway_scan/
    undefined_cs 时 payload 是 TeX 回读卡住的 cs —— 行界齐整、括号
    闭合、utf-8 合法的 .aux 仍可为毒件 (旧宏包写端遗迹的版本错配:
    aux 里 ``\abx@aux@cite{0}{key}`` 两实参对不上新版 biblatex 一元
    arity, 第二组花括号吞行级联至 EOF; 或残留 ``\abx@*`` 已不被定义)。
    损坏谓词整类放行这种件 → params ``payload_purge_cs`` 白名单内的
    机械族 cs (abx@/blx@/zref@ 等) 命中即按内容删 ``payload_purge_exts``
    件。通用内容 cs (bibcite/newlabel/\@writefile) 每个健康 aux 都有,
    不入白名单 —— 防误删 xr 外链/shipped aux。
    """
    del eng
    exts = {str(e).lower() for e in (params.get("exts") or INTERMEDIATE_SUFFIXES)}
    pay_exts = {str(e).lower() for e in (params.get("payload_purge_exts") or ())}
    pay_re = _payload_purge_re(payload, params.get("payload_purge_cs"), pay_exts)
    purged, skewed = [], []
    for f in sorted(ctx.wdir.rglob("*")):
        if not f.is_file():
            continue
        suf = f.suffix.lower()
        if suf not in exts and not (pay_re and suf in pay_exts):
            continue
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        corrupt = suf in exts and _corrupt_intermediate(raw)
        skew = bool(pay_re and suf in pay_exts and not corrupt and pay_re.search(raw))
        if not (corrupt or skew):
            continue
        f.unlink()
        ctx.invalidate(f)
        ctx.io.written.add(f)  # 自产删除入 authored 账 —— 非外部落件, 不稀释 dedup
        (purged if corrupt else skewed).append(str(f.relative_to(ctx.wdir)))
    note = []
    if purged:
        note.append(f"purged corrupt intermediates: {', '.join(purged)}")
    if skewed:
        note.append(f"purged skewed aux (contains \\{payload}): {', '.join(skewed)}")
    return (bool(purged or skewed)), "; ".join(note)


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


def latex209_upgrade(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""主档 ``\documentstyle`` → ``latex209.upgrade_209`` 有界升 2e 形态。

    ``latex209_reject`` gate 此前对 2.09 方言一律路由拒绝——但 inject 侧
    同函数实证绝大多数可转 (m1k base 臂 21 格 upgrade+fixloop: 21/21
    converted → 20 clean + 1 partial)。precheck 前置转换后, 选项拆分出
    的 ``\usepackage`` 缺件由 static_precheck 同轮装包接住, gate 只兜
    不可转形态。

    读档走字节级 ``decode_tex``——209 老档多非 UTF-8, ``ctx.read`` 的
    utf-8/replace 会把非 ASCII 字符蚀成 U+FFFD 再写回 = 二次毒化; 写回
    utf-8 与 inject 同口径。``no-docstyle`` (条件命中的是子件、主档无
    存活 docstyle) → False 让位不耗轮; ``reject`` (ds@ 选项机类 / 盲升
    守卫) → ``REJECT: route=latex+dvips`` 携 upgrade 细分 reason——与
    gate 同路由语义但归因更准。
    """
    del eng, payload, params
    main = ctx.main_path()
    if main is None:
        return False, "no main file"
    try:
        blob = main.read_bytes()
    except OSError:
        return False, f"main unreadable: {main.name}"
    tex, conv = upgrade_209(decode_tex(blob), root=ctx.wdir)
    status = str(conv.get("status") or "")
    if status == "converted":
        ctx.write(main, tex)
        cls = str(conv.get("class") or "?")
        target = str(conv.get("target") or cls)
        pkgs = [str(p) for p in (conv.get("pkg_opts") or ())]
        note = f"\\documentstyle{{{cls}}} → \\documentclass{{{target}}}"
        if pkgs:
            note += f" +\\usepackage{{{','.join(pkgs)}}}"
        return True, f"latex209 upgraded: {note}"
    if status == "reject":
        reason = str(conv.get("reason") or "latex209")
        extra = f" class={conv['class']}" if conv.get("class") else ""
        extra += f" target={conv['target']}" if conv.get("target") else ""
        return True, f"REJECT: route=latex+dvips {reason}{extra}"
    return False, f"upgrade_209: {status or 'no-docstyle'}"


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


def _wdir_fingerprint(wdir: Path) -> dict[Path, tuple[int, int]]:
    """工作树文件 ``(mtime_ns, size)`` 指纹——``run_tool`` 改盘面快照 diff 用。"""
    fp: dict[Path, tuple[int, int]] = {}
    for p in wdir.rglob("*"):
        try:
            st = p.stat()
        except OSError:
            continue
        if p.is_file():
            fp[p] = (st.st_mtime_ns, st.st_size)
    return fp


def _invalidate_changed(ctx: LoopCtx, before: dict[Path, tuple[int, int]]) -> int:
    """快照后新增/改写/删除路径全 invalidate → 失效数。

    docstrip 类 ``run_tool`` 一次写多件的通用补: 请求件之外的兄弟产出
    同步失效 ``_texts``——pre-run 读过缺件会缓存 miss→None 毒化条目,
    产出落地后缓存仍答 None, 下游规则当缺件 (同 logcache 病族)。
    不触 ``_texts`` 私有面, 指纹 diff 即全覆盖 (真写必换指纹)。
    """
    after = _wdir_fingerprint(ctx.wdir)
    changed = [p for p in set(before) | set(after) if before.get(p) != after.get(p)]
    for p in changed:
        ctx.invalidate(p)
    return len(changed)


def docstrip_generate(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""包内自带 ``.ins`` → docstrip 抽取缺件 (W102; bundled dtx 是作者钦定版本)。

    定位序: ``.ins`` basename stem == payload stem (``aipproc.ins``→
    ``aipproc.cls``), 或包内唯一 ``.ins`` 兜底。``latex -interaction=
    nonstopmode <ins>`` 跑抽取 (bbl_regen ``run_tool`` 先例; web2c 会把主
    输入件所在目录并入搜索路径, ins/dtx 同目录自然可解), 复核 payload
    落盘后 applied; 生成失败 → False 同轮续扫落 install_file(10) 装 TL 版。

    每发 ``run_tool`` 前后走 ``_invalidate_changed`` 指纹 diff——docstrip
    一抽多件 (``.sty``/``.cls``/``.cfg`` 同批出), 请求件外兄弟产出与
    miss→None 毒化条目同步失效 ``_texts`` (同 logcache 病族)。
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
        before = _wdir_fingerprint(ctx.wdir)
        rc, _out, to = ctx.run_tool(
            [driver, "-interaction=nonstopmode", rel_ins], timeout
        )
        ctx.events.append(f"docstrip {rel_ins} -> rc={rc}{' TIMEOUT' if to else ''}")
        _invalidate_changed(ctx, before)
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

#: 魔数探测窗——我方 splice/zh 对 ``.sty`` 一律前置 prologue 注入
#: (``\PassOptionsToPackage``/``\providecommand`` 块), tar 魔数被推离 257
#: (0707.0382 实案: 注入 ~600B 后 ``ustar`` 落 ~偏移 870, 定点探测漏检);
#: 前 64KB 扫描兼容原生与变异 blob。
_TAR_SCAN_WINDOW = 65536

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


def _tar_header_start(f: Path) -> int | None:
    r"""Tar 头起点探测——前 ``_TAR_SCAN_WINDOW`` 内找 ``ustar``, 回推 257 得头起点。

    None = 非 tar; 0 = 原生 tar; >0 = 被前置注入推位的变异 tar
    (注入件仍以 tar 为主体, 同须退役)。逐候选过 textutil
    ``_tar_header_ok`` 双校验 (name 非 NUL + 魔数+版本域 + 512B 校验和)
    ——免 ``\mustar``/``\mustarh`` 类宏名内 ``ustar`` 字样误中真 .tex
    (2410.17904 ``paper.tex``→missing_file 实案)。多读
    ``_TAR_HEADER_LEN`` 让窗尾命中仍见全头。
    """
    try:
        with f.open("rb") as fh:
            head = fh.read(_TAR_SCAN_WINDOW + _TAR_HEADER_LEN)
    except OSError:
        return None
    p = head.find(_TAR_MAGIC)
    while p != -1:
        hdr = p - _TAR_MAGIC_OFF
        if hdr >= 0 and _tar_header_ok(head, hdr):
            return hdr
        p = head.find(_TAR_MAGIC, p + 1)
    return None


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


def _slot_hit(rel: PurePosixPath, expected: Path) -> int:
    r"""成员对期待槽位 ``expected`` 的命中级: 0 无 / 1 stem 兄弟 / 2 basename 精确。

    stem 兄弟限 ``.cls`` 槽位 ← ``.sty`` 成员——2.09 时代 class 本体就以
    .sty 发行, ``\\documentstyle``/compat ``\\documentclass`` 读本名槽位
    (astro-ph/0104007 ``aipproc.cls`` tar 内含 ``aipproc.sty`` 实案);
    反向 (.cls 成员冒写 .sty 槽位) 不开——class 件不是 package 实现。
    """
    if rel.name.lower() == expected.name.lower():
        return 2
    sib = (
        expected.suffix.lower() == ".cls"
        and rel.suffix.lower() == ".sty"
        and rel.stem.lower() == expected.stem.lower()
    )
    return int(sib)


def _slot_payload(f: Path, hdr_start: int, expected: Path) -> bytes | None:
    """二扫 tar 成员找期待槽位 ``expected`` 的补写字节 (basename 精确 > stem 兄弟)。

    独立 BytesIO 重扫——成员字节已在盘内 tar 里, 扫序同一遍损坏边界,
    确定性等价。``hit > best_rank`` 让后到的精确件盖过先到的兄弟件。
    """
    import io  # noqa: PLC0415
    import tarfile  # noqa: PLC0415

    best_rank = 0
    payload: bytes | None = None
    try:
        stream = io.BytesIO(f.read_bytes()[hdr_start:])
        with tarfile.open(fileobj=stream) as tf:
            for m in tf:
                if not m.isreg():
                    continue
                rel = _safe_member_name(m.name)
                if rel is None:
                    continue
                hit = _slot_hit(rel, expected)
                if hit <= best_rank:
                    continue
                src = tf.extractfile(m)
                if src is not None:
                    best_rank, payload = hit, src.read()
    except (tarfile.TarError, OSError):
        pass
    return payload


def _extract_members(
    ctx: LoopCtx, f: Path, hdr_start: int, expected: Path | None = None
) -> int:
    r"""抽 tar ``f`` (头起点 ``hdr_start``) 的 regular-file 成员补缺 → 落地数。

    顺序迭代 (非 getmembers 全扫)——变异 tar 内层被 recode 改写可能中段
    损坏, 顺序读让头部完好成员先落地, 遇坏头即收。

    ``expected`` = 伪装件原名槽位 (blob 已先改名让出): 与槽位同名成员
    (任意深度 basename) 自然落地即占槽位; 槽位仍缺则由 ``_slot_payload``
    二扫补写——basename 命中或同 stem ``.sty`` 兄弟件, 让 class/``\\input``
    解析拿到 tar 内真实实现而非落入 missing_file→stub。
    """
    import io  # noqa: PLC0415 — 冷路径: 命中伪装件才用, 不污染常规启动
    import tarfile  # noqa: PLC0415

    extracted = 0
    try:
        stream = io.BytesIO(f.read_bytes()[hdr_start:])
        with tarfile.open(fileobj=stream) as tf:
            for m in tf:
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
        pass
    if expected is not None and not expected.exists():
        payload = _slot_payload(f, hdr_start, expected)
        if payload is not None:
            expected.write_bytes(payload)
            ctx.invalidate(expected)
            extracted += 1
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
    命中 tar 魔数即改名 ``{name}.tarblob`` 退役 (移出 TeX 解析路径、
    留现场可审计)——tar 归档在 ``.sty``/``.cls`` 名下绝不是合法 TeX,
    0 新成员 (=语料已带全部成员, 0707.0382 实案) 或魔数被前置注入推位
    的变异件也必须退役。**先改名再抽**——blob 让出原名槽位后, 与槽位
    同名或同 stem 的 ``.sty`` 兄弟成员才能补写回 ``{name}`` 本身
    (旧序先抽后改: 槽位被 tar 本体占着, 同名成员永远被 no-clobber
    跳过, 改名后期待文件名彻底缺席 → missing_file)。抽取按头起点切片
    喂 tarfile, 顺序迭代容忍变异件中段损坏 (头段完好成员照补)。
    """
    del eng, payload
    exts = {str(e).lower() for e in (params.get("exts") or _TARBLOB_EXTS)}
    done: list[str] = []
    for f in sorted(ctx.wdir.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in exts:
            continue
        hdr = _tar_header_start(f)
        if hdr is None:
            continue
        blob = f.with_name(f.name + ".tarblob")
        f.rename(blob)
        ctx.invalidate(f)
        extracted = _extract_members(ctx, blob, hdr, expected=f)
        done.append(f"{f.name}({extracted} members)")
    return (bool(done)), f"tar blobs extracted: {', '.join(done)}"


# ════════════════════════════════════════════════════════════════
# standalone/subfiles 子文档导言剥除 (failmine3 #164b)
# ════════════════════════════════════════════════════════════════

#: document 环境边界 —— ``\begin{document}``/``\end{document}`` (遮盖视图定位)。
_BEGIN_DOC_RE = re.compile(r"\\begin\s*\{document\}")
_END_DOC_RE = re.compile(r"\\end\s*\{document\}")

#: 单参 input 族执行面 —— 这些命令真把目标文件吸进编译流
#: (``\includegraphics`` 等非同族词干由 ``\s*\{`` 紧随约束排除)。
_INPUT_EXEC1_RX = re.compile(
    r"\\(?:input|include|subfile|subfileinclude|includestandalone"
    r"|InputIfFileExists)\s*\{([^}]*)\}"
)
#: 双参 import 族 —— 第一参目录前缀, 第二参文件名。
_INPUT_EXEC2_RX = re.compile(
    r"\\(?:import|subimport|includefrom|subincludefrom|inputfrom)"
    r"\s*\{([^}]*)\}\s*\{([^}]*)\}"
)


def _input_targets(arg: str) -> list[str]:
    r"""Input 族参数 → 候选相对路径 (空 = 构造名/宏名, 不可静态解析)。"""
    a = arg.strip().strip('"').strip()
    if not a or any(c in a for c in "{}\\"):
        return []
    if a.lower().endswith(".tex"):
        return [a]
    return [a, a + ".tex"]


def _exec_referenced_paths(ctx: LoopCtx) -> set[Path]:
    r"""全工程存活 input 族引用 → resolve 绝对路径集 (2409.00265 门)。

    遮盖视图扫描全 .tex/.sty/.cls: 注释/verbatim 内引用不算位; 宏体
    内引用过近似收 (宏可能永不被调 —— 宁多勿少, 漏引才是 2409.00265
    式灾难方向)。
    """
    refs: set[Path] = set()
    for src in ctx.tex_files((".tex", ".sty", ".cls")):
        t = ctx.read(src)
        if t is None:
            continue
        masked = mask_tex(t)
        for m in _INPUT_EXEC1_RX.finditer(masked):
            for cand in _input_targets(m.group(1)):
                refs.add((src.parent / cand).resolve())
        for m in _INPUT_EXEC2_RX.finditer(masked):
            d = m.group(1).strip().strip('"')
            if any(c in d for c in "{}\\"):
                continue  # 目录参含宏/构造 —— 不可静态解析, 弃
            for cand in _input_targets(m.group(2)):
                refs.add((src.parent / d / cand).resolve())
        for m in INPUT_BARE_RX.finditer(masked):
            for cand in _input_targets(m.group("arg")):
                refs.add((src.parent / cand).resolve())
    return refs


def subfile_docclass_strip(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""被 input 族引用的非主 ``.tex`` 含存活 ``\documentclass`` → 剥至 body。

    inject 前导块 (``\PassOptionsToPackage{no-math}{fontspec}`` +
    ``\AddToHook`` 能力适配串) 逐文件打进全部 .tex —— 落在自带
    ``\documentclass`` 的 standalone/subfiles 类子文档头上时, 包的
    preamble-skip 机制 (``\includestandalone``/``\subfile``) 只中和
    ``\documentclass``..``\begin{document}`` 区间, 注入行在其前 = 正文区
    活代码 → ``Can be used only in preamble`` @子文件:1 (2410.00111/
    2003.03508/2310.16788 三格同机理, splice 面逐格核实)。

    剥至纯 body 区后语义: ``\subfile``/``\includestandalone`` 包机制
    本就跳过整个 preamble 区 (恒等); ``\subimport``/裸 ``\input`` 得
    唯一可编译形。子文档 preamble 里的 ``\usepackage``/``\newcommand``
    在载入语义下本就够不着 body, 剥离无功能损失。

    遮盖视图复核: 注释/verbatim 内的 ``\documentclass``/``\begin{document}``
    不算位; ``DOCCLASS_RX`` 兼收 ``\documentstyle`` (2.09 子文档同机理)。
    无 ``\begin{document}`` 的异形制不动 (无可剥区)。主档经
    ``ctx.main_path()`` 排除 —— resolve 双端比对防路径形态差。

    引用门 (2409.00265): 只剥被存活 input 族命令引用的文件 —— 无引用
    的 docclass 持件 (独立第二文档, 或 main 误判下的真主档) 永远进不了
    编译流, 剥它是纯害 (2409.00265: precheck 误选 Biography 为主档,
    真主档 Main 被剥成 body → env_undefined|frontmatter + 1326 错级联)。
    """
    del eng, payload
    main = ctx.main_path()
    main_res = main.resolve() if main is not None else None
    exts = tuple(params.get("exts") or (".tex",))
    cands: list[tuple[Path, str, re.Match[str], re.Match[str] | None]] = []
    for f in ctx.tex_files(exts):
        if main_res is not None and f.resolve() == main_res:
            continue
        t = ctx.read(f)
        if t is None:
            continue
        masked = mask_tex(t)
        if not DOCCLASS_RX.search(masked):
            continue  # 无存活 docclass —— 普通被 input 件, 不动
        mb = _BEGIN_DOC_RE.search(masked)
        if mb is None:
            continue  # 无 body 区 —— 非输入式子文档, 不动
        cands.append((f, t, mb, _END_DOC_RE.search(masked, mb.end())))
    if not cands:
        return False, "no docclass-bearing non-main .tex"
    referenced = _exec_referenced_paths(ctx)
    changed = 0
    for f, t, mb, me in cands:
        if f.resolve() not in referenced:
            continue  # 无存活引用 —— 独立第二文档/误判主档, 剥了也进不了编译流
        body = t[mb.end() : me.start() if me is not None else len(t)]
        ctx.write(
            f,
            "% fixloop: stripped to body (docclass-bearing subfile)\n" + body,
        )
        changed += 1
    if not changed:
        return False, "no input-referenced docclass-bearing non-main .tex"
    return True, f"body-only strip in {changed} file(s)"


# ════════════════════════════════════════════════════════════════
# fragment 误判主档 → \input wrapper 提升 (2609.19170)
# ════════════════════════════════════════════════════════════════


def _closure_scan(ctx: LoopCtx, main: Path, masked_text: str) -> tuple[set[Path], bool]:
    r"""收集 ``(main, 遮盖文本)`` 的 ``\input`` 传递闭包成员与 ``\end{document}`` 可达性。

    inject ``_closure_has_document`` 的修复层镜像: 同一 ``_walk_inputs``
    口径 (声明目录→工程根两跳、tar 伪装闸、环引 visited、规模上界
    ``_MASS_FILE_CAP``); 种子本体计入成员集 (walk 只产下游目标)。
    """
    root = ctx.io.wdir.resolve()
    members = {main.resolve()}
    has_end = bool(_END_DOC_RE.search(masked_text))
    for tgt, sub in _walk_inputs(root, [(main.resolve(), masked_text)]):
        members.add(tgt)
        if not has_end and _END_DOC_RE.search(sub):
            has_end = True
    return members, has_end


def _wrapper_candidates(ctx: LoopCtx, main_res: Path) -> list[Path]:
    r"""合格 wrapper: ``\input`` 闭包吞 ``main_res`` 且闭包达 ``\end{document}``。

    候选种子的 tar 伪装闸 —— 成员字节可含 ``\input``/``\end{document}``
    假信号 (inject scanned 同闸); 现主档自身经 resolve 比对排除。
    """
    winners: list[Path] = []
    for f in ctx.tex_files((".tex", ".ltx")):
        if f.resolve() == main_res:
            continue
        try:
            if _tar_disguised(f.read_bytes()):
                continue
        except OSError:
            continue
        t = ctx.read(f)
        if t is None:
            continue
        members, has_end = _closure_scan(ctx, f, mask_tex(t))
        if main_res in members and has_end:
            winners.append(f)
    return winners


def main_wrapper_promote(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Fragment 误判主档收容: 把吞进现主档且闭包达 ``\end{document}`` 的 wrapper 提为 main。

    ``find_main_tex`` pass-1 只收字面 ``\documentclass`` 件 —— 裸
    ``\input`` 编排壳永不入池; 池内若只剩 fragment (无 ``\end{document}``
    无 ``\input``) 即编译 ``*** (job aborted, no legal \end found)``
    (2609.19170: ``sections/00_preamble.tex`` 止于 ``\maketitle``, 真入口
    是根目录 9 行 ``\input`` 列表)。W99 闭包档因池非空被跳过 —— 修复层
    直接换 main 比动 inject 探测面爆炸半径小。

    提拨判据 (全经 ``_closure_scan`` 遮盖视图, 注释/verbatim 内不计):
    候选 ``\input`` 传递闭包含现主档 **且** 闭包任一文件见字面
    ``\end{document}``。守卫: 现主档自身闭包已达 ``\end{document}`` 时
    非 fragment 误判让位; 恰一个合格 wrapper 才动 —— 零个无救, 多个
    歧义让位。``ctx.io.main_rel`` 可变 (engine.py:611/1094 先例),
    编译面逐轮活读 ``main_rel`` 无派生缓存要失效; 翻转落
    ``ledger.advisories`` + 动作账本。
    """
    del eng, payload, params
    main = ctx.main_path()
    if main is None or not main.is_file():
        return False, "no main"
    text = ctx.read(main)
    if text is None:
        return False, "main unreadable"
    main_res = main.resolve()
    _, main_end = _closure_scan(ctx, main, mask_tex(text))
    if main_end:
        return False, "main closure already reaches \\end{document}"
    winners = _wrapper_candidates(ctx, main_res)
    if not winners:
        return False, "no \\end{document}-reaching wrapper inputs current main"
    if len(winners) > 1:
        names = ", ".join(f.relative_to(ctx.io.wdir).as_posix() for f in winners)
        return False, f"ambiguous wrappers: {names}"
    rel = winners[0].relative_to(ctx.io.wdir).as_posix()
    old = ctx.io.main_rel
    ctx.io.main_rel = rel
    ctx.ledger.advisories.append(
        f"main_wrapper_promote: main_rel {old} -> {rel} "
        "(fragment rescued by \\input wrapper)"
    )
    return True, f"main_rel {old} -> {rel}"


# ════════════════════════════════════════════════════════════════
# \include/\input{*.<gfx>} 非 TeX 目标剥除 (math/0501227)
# ════════════════════════════════════════════════════════════════

#: input 族把目标当 TeX 源吸进编译流——花括号目标落图形扩展名时必为
#: ``\include``↔``\includegraphics`` 类笔误 (math/0501227 preamble 期
#: ``\include{triangle_dots.eps}`` 把 EPS 头按 TeX 展开 → Missing
#: ``\begin{document}`` 爆流; 同位 ``\includegraphics{triangle_dots}``
#: 在 body 另有正解, 剥除零语义损失)。
_GFX_INPUT_EXTS = frozenset(
    {
        ".eps",
        ".ps",
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".svg",
    }
)


def graphics_include_strip(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``\(include|input|InputIfFileExists){<name>.<gfxext>}`` → 剥除命令位。

    单参 input 族命令只可能吸 TeX 源; 目标扩展名落图形族时该行必错,
    剥掉命令 span (保行内其余内容)。遮盖视图定位——注释/verbatim 内
    同形串不算位。
    """
    del eng, payload
    exts = {str(e).lower() for e in (params.get("gfx_exts") or _GFX_INPUT_EXTS)}
    done: list[str] = []
    for f in ctx.tex_files((".tex",)):
        t = ctx.read(f)
        if t is None:
            continue
        masked = mask_tex(t)
        spans = [
            m.span()
            for m in _INPUT_EXEC1_RX.finditer(masked)
            if PurePosixPath(m.group(1).strip().strip('"')).suffix.lower() in exts
        ]
        if not spans:
            continue
        out = t
        for start, end in reversed(spans):
            out = out[:start] + out[end:]
        ctx.write(f, out)
        done.append(f"{f.name}×{len(spans)}")
    return (bool(done)), f"gfx-target input sites stripped: {', '.join(done)}"


# ════════════════════════════════════════════════════════════════
# xdvipdfmx .pfa 硬墙: ASCII Type1 → usertree .pfb + map 遮蔽 (1907.03923)
# ════════════════════════════════════════════════════════════════

#: eexec 段起始锚 —— ASCII 头/密文边界。
_EEXEC_MARK_RX = re.compile(rb"currentfile eexec[ \t]*\r?\n")

#: map 行内 ``<name.pfa``/``<<name.pfa`` 引用 token —— ``<`` 前缀锚定
#: 免 stem 后缀误吃 (``<pen.pfa`` 不会中 ``<pigpen.pfa``); 扩展名大小写兼收。
_MAP_PFA_RX = re.compile(r"<<?([^\s\"'<>]+\.pfa)\b", re.IGNORECASE)

#: pdftex.map 分块源注释 ``% <pkg>.map`` —— updmap 合并逐块标源, 反查
#: 字体条目所属 dvips map 名 (供 usertree 同位遮蔽)。头部 ``% /path/....map:``
#: 注释带冒号尾/路径, ``\S+\.map`` 尾锚同排。
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
    """Map token 名卫: 拒绝对路径/``..``/空名 —— 只信 basename 级引用。"""
    rel = PurePosixPath(name)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    return rel


def _convert_map_pfas(
    ctx: LoopCtx, probe: Callable[..., str | None], texmf: Path, names: list[str]
) -> list[str]:
    """Map 引用的 .pfa 逐个 probe+转换 → usertree ``home/fonts/type1/`` 落 .pfb。

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
#: epsffile/epsfbox 是裸 PS 装载点, ``{X}`` 无扩展名不解析, 不剥。
_EPS_KV_STRIP_CMDS = frozenset({"epsfig", "psfig"})

#: 别名受理的显式扩展名 —— eps 族 + ``.pdf`` (conv 件本来就是
#: eps→pdf 产物; ``.png/.jpg`` 显式缺件与 conv 件无语义对应不落)。
_EPS_CONV_ALIAS_EXTS = frozenset((*_EPS_EXTS, ".pdf"))


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
    hits = []
    for p in ctx.wdir.rglob("*"):
        if not p.is_file() or p.name.lower() != low:
            continue
        parts = p.relative_to(ctx.wdir).parts
        if any(part.startswith(".") for part in parts) or parts[0] in {
            "_texmf",
            "_tect_out",
        }:
            continue
        hits.append(p)
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
        if p.is_absolute() or ".." in p.parts:
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
            try:
                target.resolve().relative_to(ctx.wdir.resolve())
            except ValueError:
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
        if p.is_absolute() or ".." in p.parts:
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
        for s, e, new in sorted(spans, reverse=True):
            t = t[:s] + new + t[e:]
        ctx.write(f, t)
        edited.append(f"{f.name}×{len(spans)}")
    if not made and not edited:
        return False, "no shipped -eps-converted-to.pdf sibling for missing refs"
    note = []
    if made:
        note.append(f"alias: {', '.join(made)}")
    if edited:
        note.append(f"eps-ext stripped: {', '.join(edited)}")
    return True, "; ".join(note)


# ════════════════════════════════════════════════════════════════
# runaway_output 修复面: 不可断盒 > \textheight → \output 空页死循环
# (killsem census 单机理族: sentry:page_flood SIGKILL 前泛洪签名)
# ════════════════════════════════════════════════════════════════


def _brace_end(t: str, i: int) -> int | None:
    r"""``t[i] == "{"`` → 配对 ``}`` 位 (``\{`` 转义不算)。"""
    depth = 0
    j = i
    while j < len(t):
        c = t[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return None


def _bracket_end(t: str, i: int) -> int | None:
    """``t[i] == "["`` → 配对 ``]`` 位; ``{…}`` 嵌套内与转义的 ``]`` 不收。"""
    brace = 0
    j = i
    while j < len(t):
        c = t[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            brace += 1
        elif c == "}":
            if brace:
                brace -= 1
        elif c == "]" and brace == 0:
            return j
        j += 1
    return None


def _skip_ws(t: str, j: int) -> int:
    """空白/换行跳过 → 首个非空格位。"""
    while j < len(t) and t[j] in " \t\n":
        j += 1
    return j


def _skip_bracket(t: str, j: int) -> int | None:
    """``t[j] == "["`` → 配对组后空白归位; 非 ``[`` → ``j`` 原样; 未配对 → None。"""
    if j >= len(t) or t[j] != "[":
        return j
    e = _bracket_end(t, j)
    return None if e is None else _skip_ws(t, e + 1)


#: ``\begin{tcolorbox}`` env 站。
_TCB_BEGIN_RX = re.compile(r"\\begin\s*\{tcolorbox\}")
#: ``\newtcolorbox`` 定义站。
_TCB_DEF_RX = re.compile(r"\\newtcolorbox\b")
#: tcolorbox 装载点 (usepackage/RequirePackage; 选项组/包名单组)。
_TCB_LOAD_RX = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[([^\]\n]*)\])?\s*\{([^}]*)\btcolorbox\b[^}]*\}"
)
#: ``\tcbuselibrary{…}`` 库声明点。
_TCB_LIB_RX = re.compile(r"\\tcbuselibrary\s*\{([^}]*)\}")
#: 含 breakable 的库名单 token——many/most/all 是 bundles
#: (tcolorbox.sty ``\tcb@add@library@style``: many→…breakable…, most/all→many)。
_TCB_BREAKABLE_LIBS = frozenset({"breakable", "many", "most", "all"})
#: 选项组内 breakable 键探测 (``unbreakable`` 前缀不沾——``\b`` 挡 ``n``)。
_TCB_BREAKABLE_KEY_RX = re.compile(r"\bbreakable\b")
#: 否定形键——``breakable=false``/``unbreakable`` 在泛洪格是肇事者, 翻正。
_TCB_NEG_KEY_RX = re.compile(r"\bbreakable\s*=\s*false\b|\bunbreakable\b")


def _tcb_lib_state(ctx: LoopCtx) -> tuple[bool, tuple[Path, int] | None]:
    r"""``(breakable 库已载, tcolorbox 装载点 (file, match_end))`` —— 遮盖视图。

    装载点用于 ``\tcbuselibrary{breakable}`` 注入缝 (须在包载后);
    usepackage 选项组与 ``\tcbuselibrary`` 参数的逗号成员级 token 判定。
    """
    loaded = False
    site: tuple[Path, int] | None = None
    for f in ctx.tex_files((".tex", ".sty", ".cls")):
        t = ctx.read(f)
        if t is None:
            continue
        masked = mask_tex(t)
        for m in _TCB_LOAD_RX.finditer(masked):
            if site is None:
                site = (f, m.end())
            libs = {x.strip() for x in (m.group(1) or "").split(",")}
            if libs & _TCB_BREAKABLE_LIBS:
                loaded = True
        for m in _TCB_LIB_RX.finditer(masked):
            if site is None:
                site = (f, m.end())
            libs = {x.strip() for x in m.group(1).split(",")}
            if libs & _TCB_BREAKABLE_LIBS:
                loaded = True
    return loaded, site


def _tcb_opts_edits(start: int, inner: str) -> tuple[int, int, str] | None:
    """选项组 ``inner`` → breakable 化编辑 ``(s, e, new)``; 无需动 → None。"""
    new_inner = _TCB_NEG_KEY_RX.sub("breakable", inner)
    if new_inner != inner:
        return (start + 1, start + 1 + len(inner), new_inner)
    if _TCB_BREAKABLE_KEY_RX.search(inner):
        return None
    return (start + 1, start + 1, "breakable,")


def _tcb_def_opts_span(t: str, i: int) -> tuple[int, int] | None:
    r"""``\newtcolorbox`` 签名的末位 ``{options}`` 组 ``(start, end)``。

    形: ``\newtcolorbox[init]{name}[num][default]{options}`` —— 首个 ``[``
    组与 ``{name}`` 后零或多个 ``[`` 组跳过, 余下首个 ``{`` 即 options。
    """
    j = _skip_bracket(t, _skip_ws(t, i))  # [init]
    if j is None:
        return None
    if t[j : j + 1] != "{":  # {name}
        return None
    e = _brace_end(t, j)
    if e is None:
        return None
    j = _skip_ws(t, e + 1)
    while t[j : j + 1] == "[":  # [num][default]…
        j = _skip_bracket(t, j)
        if j is None:
            return None
    if t[j : j + 1] != "{":  # {options}
        return None
    e = _brace_end(t, j)
    return None if e is None else (j, e)


def _tcb_edits(t: str) -> list[tuple[int, int, str]]:
    """单文件 tcolorbox env/def 选项组补 ``breakable`` 的编辑表 (遮盖视图定位)。"""
    edits: list[tuple[int, int, str]] = []
    for m in _live_matches(_TCB_BEGIN_RX, t):
        j = m.end()
        while j < len(t) and t[j] in " \t\n":
            j += 1
        if j < len(t) and t[j] == "[":
            e = _bracket_end(t, j)
            if e is None:
                continue
            if ed := _tcb_opts_edits(j, t[j + 1 : e]):
                edits.append(ed)
        else:
            edits.append((m.end(), m.end(), "[breakable]"))
    for m in _live_matches(_TCB_DEF_RX, t):
        span = _tcb_def_opts_span(t, m.end())
        if span is None:
            continue
        s, e = span
        if ed := _tcb_opts_edits(s, t[s + 1 : e]):
            edits.append(ed)
    return edits


def _tcb_patch_text(t: str) -> tuple[str, int]:
    """``_map_tex_files`` 适配: ``_tcb_edits`` 逆序落盘 → (新文本, 编辑数)。"""
    edits = _tcb_edits(t)
    for s, e, new in sorted(edits, reverse=True):
        t = t[:s] + new + t[e:]
    return t, len(edits)


def tcolorbox_breakable_inject(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``\begin{tcolorbox}``/``\newtcolorbox`` 选项组补 ``breakable`` (runaway_output 臂)。

    killsem census 双格实证 (2311.04163 zh→57p rc=0; 2504.11741 zh→47p):
    不可断 tcolorbox 超 ``\textheight`` 卡死 ``\output`` → page_flood。
    ``breakable`` 键把整盒翻为多页可断盒, 能放下的盒排版零变。

    键生效前提是 breakable 库已载——库探测按 ``_tcb_lib_state``:
    ``breakable``/``many``/``most``/``all`` 成员级 token (bundles 含
    breakable, texmf tcolorbox.sty 实证)。未载则须见 tcolorbox 装载点
    才能补 ``\tcbuselibrary{breakable}`` —— 无装载点 (cls 内载等)
    时补键会产 unknown-key 新错, 整体让位。已带 ``breakable`` 的站
    幂等跳过; ``breakable=false``/``unbreakable`` 否定形翻正
    (泛洪格否定键即肇事者)。遮盖视图定位——注释/verbatim 内
    ``\begin{tcolorbox}``/``\newtcolorbox`` 不算站。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex",))
    if not any(
        _tcb_edits(t) for f in ctx.tex_files(exts) if (t := ctx.read(f)) is not None
    ):
        return False, "no unbreakable tcolorbox env/def sites"
    lib_loaded, site = _tcb_lib_state(ctx)
    if not lib_loaded and site is None:
        return False, "breakable lib absent and no tcolorbox load site to attach"
    lib_note = ""
    if not lib_loaded:
        f, pos = site
        t = ctx.read(f) or ""
        ctx.write(f, t[:pos] + "\n\\tcbuselibrary{breakable} % fixloop\n" + t[pos:])
        lib_note = f" +\\tcbuselibrary{{breakable}} in {f.name}"
    n = _map_tex_files(ctx, exts, _tcb_patch_text)
    return True, f"breakable opts in {n} file(s){lib_note}"


#: ``[H]`` 降级的默认浮体 env 面 (params.envs 可扩)——kernel 浮体
#: figure/table (+星形) 与常见具名浮体 algorithm (algorithm/algorithm2e
#: 包)/listing (minted); ``H`` 是 float 宏包给一切浮体的锚。
_FLOAT_H_ENVS = (
    "figure",
    "table",
    "figure*",
    "table*",
    "algorithm",
    "algorithm*",
    "listing",
)
#: 合法浮体 placement 字符集——组内出现他字符即非纯 placement 表, 不动。
_FLOAT_OPT_CHARS = frozenset("!htbpH")


def _float_demote_opts(inner: str) -> str | None:
    r"""浮体选项组 ``inner`` 含 ``H`` → 降级形; 非纯 placement 表/无 H → None。

    ``H`` = float 宏包绝对锚 (退化为非浮体盒, 超高即卡 page builder)。
    降级 = 去 ``H`` + ``!`` 前缀 (放宽浮体参数限——超高盒靠它才进
    float page) + 保证 ``p`` (超高盒唯一可靠落点) + 无 h/t/b 时补
    ``ht`` 保近位意图。``[H]``→``[!htp]``, ``[H!tbp]``→``[!tbp]``,
    ``[Hb]``→``[!bp]``。
    """
    if "H" not in inner or any(c not in _FLOAT_OPT_CHARS for c in inner):
        return None
    body = inner.replace("H", "").replace("!", "")
    if not any(c in body for c in "htb"):
        body += "ht"
    if "p" not in body:
        body += "p"
    return "!" + body


def _float_h_edits(t: str, rx: re.Pattern[str]) -> list[tuple[int, int, str]]:
    r"""单文件 ``\begin{<env>}[<opts 含 H>]`` 降级编辑表 (遮盖视图定位)。"""
    edits: list[tuple[int, int, str]] = []
    for m in _live_matches(rx, t):
        j = _skip_ws(t, m.end())
        if t[j : j + 1] != "[":
            continue
        e = _bracket_end(t, j)
        if e is None:
            continue
        if (new := _float_demote_opts(t[j + 1 : e])) is not None:
            edits.append((j, e + 1, "[" + new + "]"))
    return edits


def float_h_demote(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""浮体 ``[H]`` 系选项组降级为 ``!``+placement (runaway_output 臂)。

    与 ``float_opt_h_pkgload`` (70-pkgopt, float_opt|H 签名补
    ``\usepackage{float}``) 零重叠: 该格 float 已载, 失败模态是
    ``[H]`` 把超高内容钉成非浮体不可断盒 → page builder 死循环
    (2608.09867 base: figure[H]+~755pt 图 > ~731pt \textheight)。
    降级翻回真浮体即交给 float page 出盒 (超限也落 overfull 而非死循环)。

    遮盖视图定位 ``\begin{<env>}\s*[`` 站, 组内容限 ``!htbpH`` 字符
    (placement 表白名单——含他字符的括号组非浮体选项, 不动); 无 H
    即幂等跳过。env 面默认 ``_FLOAT_H_ENVS``, ``params.envs`` 可扩。
    """
    del eng, payload
    envs = tuple(str(x) for x in (params.get("envs") or _FLOAT_H_ENVS))
    rx = re.compile(r"\\begin\s*\{(?:" + "|".join(re.escape(x) for x in envs) + r")\}")
    exts = tuple(params.get("exts") or (".tex",))
    changed = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        edits = _float_h_edits(t, rx)
        for s, e, new in sorted(edits, reverse=True):
            t = t[:s] + new + t[e:]
        if edits:
            ctx.write(f, t)
            changed += 1
    if not changed:
        return False, "no [H] float option sites"
    return True, f"[H] demoted in {changed} file(s)"
