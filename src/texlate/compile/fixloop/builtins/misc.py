r"""builtins.misc — 编码转码 / 中间件清场 / support 文件腐蚀复原 / 格式门 (C3 拆分)。

``non_utf8_recode`` 非 UTF-8 源就地转码; ``cjk_env_relax`` 旧 CJK env
换装 xeCJK; ``purge_corrupt_intermediates`` 删引擎自产的截断 aux 族;
``aux_seed_undefined_refs`` aux 补 ``\newlabel`` 空桩;
``restore_support_from_src`` 把被翻译写脏的 support 件从 pristine
baseline 逐字节复原; ``plain_format_detect`` 纯 plain/amsTeX 稿门判;
``latex209_upgrade`` ``\documentstyle`` 有界升 2e;
``harvest_build_directives`` 收割 arara/``!TEX`` 注释指令;
``docstrip_generate`` 跑包内 .ins 抽取缺件。

再拆出叶: tar 伪装件解包 ``builtins.tarblob`` / input 族引用图外科
``builtins.inputfix`` / env 选项组与排版参数外科 ``builtins.optfix`` /
随稿资产改形补缺 ``builtins.assetfix``。
"""

from __future__ import annotations

import contextlib
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import (
    _fixloop_log,
    _fp_diff,
    _safe_rel,
    _wdir_fingerprint,
)
from texlate.compile.latex209 import upgrade_209
from texlate.compile.normalize import normalize_legacy_cjk
from texlate.compile.transcode import INTERMEDIATE_SUFFIXES
from texlate.latex.api import NAME_GATED_TEX_SUFFIXES, parse_file
from texlate.latex.prose import file_has_prose
from texlate.textutil import (
    CJK_RX,
    DOCCLASS_RX,
    decode_tex,
    mask_tex,
    safe_is_file,
)

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx


def non_utf8_recode(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""非 UTF-8 源文件就地转码 UTF-8 (docs/spec/compile.md §6.6; iconv 等价物, stdlib 版)。

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

    payload 锚定臂 (scaneof 车道, m1k aux-malformed 簇): runaway_scan/
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


_UNDEF_REF_WARN_RE = re.compile(
    r"LaTeX Warning: Reference [`']([^'\n]+)' on page \d+ undefined"
)
#: ``\thanksnewlabel`` (imsart) / ``\@newl@bel`` 等派生写入器同归 ``\r@`` ——
#: 子串匹配 ``newlabel{`` 而非锚 ``\newlabel``, 否则 dedup 看不见已定义名。
_NEWLABEL_NAME_RE = re.compile(r"newlabel\{([^{}]*)\}")
#: 可安全落 ``\newlabel{...}`` 的键面 —— csname 语境容空格/@/冒号;
#: 反斜线/花括号/hash 类入键即碎的键名跳过 (它们本也过不了 label 写入)。
_LABEL_SAFE_RE = re.compile(r"^[^\\{}&#%$^_~\n]+$")


def aux_seed_undefined_refs(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""未定义 ``\r@`` 引用 → ``\newlabel`` 空桩落 .aux, 斩 edef 炸弹。

    实证根因 (pairbun 车道, 1107.0312/1106.5915): imsart 系 ``\printead``
    把 ``\saferef`` 输出喂进 ``\href`` URL 参 —— hyperref
    ``\hyper@@normalise`` 的 ``\edef\Hy@tempa`` 全展开 URL; 未定义引用走
    ``\@setref`` ``??`` 臂 ``\nfss@text{\reset@font\bfseries ??}`` → 现代
    内核 ``\bfseries`` 展开 ``\expand@font@defaults`` →
    ``\series@maybe@drop@one@m@x`` 替换文本内嵌 ``\def\in@@ ##1`` →
    ``#1`` 参 token 撞零参 ``\Hy@tempa`` 定义 → ``Illegal parameter
    number``。同根级联: ``\@ifundefined{r@...}`` 全 YES → ``\ead@text``/
    ``\ead@type``/``\ead@prefix`` 不置 → undefined_cs ×N。

    主战场是**首遍真空**: workdir 无 .aux → 所有 ``\@setref`` 走 ``??`` 臂
    → end-of-doc ``\printead``/``\printaddresses`` 连环爆 (1107.0312 实测
    100 errors → 补 aux 后重编 rc=0/0 err, ``\@ifundefined`` 查的
    ``r@e1@email`` 与 ``\thanksnewlabel`` 写名一致, 源里 ``\ead@ref @``
    间空格 tokenize 时已被吃掉)。doc 自写覆盖不到的引用 (警告名) 由桩
    补齐 —— 桩 ``\r@<label>`` 使 ``\@setref`` 走 else 臂 +
    ``\@ifundefined`` 走定义臂, 一根双斩; .aux 每遍被 doc 重写, 不扰。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".aux",))
    refs: list[str] = []
    for m in _UNDEF_REF_WARN_RE.finditer(_fixloop_log(ctx)):
        name = m.group(1).strip()
        if name and _LABEL_SAFE_RE.match(name) and name not in refs:
            refs.append(name)
    if not refs:
        return False, "no undefined refs in log"
    changed: list[str] = []
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        have = set(_NEWLABEL_NAME_RE.findall(t))
        missing = [r for r in refs if r not in have]
        if not missing:
            continue
        seeds = "".join("\\newlabel{" + r + "}{{}{}{}{}{}}\n" for r in missing)
        body = t if t.endswith("\n") else t + "\n"
        ctx.write(f, body + "% fixloop: seed undefined refs\n" + seeds)
        changed.append(f"{f.name}(+{len(missing)})")
    if not changed:
        return False, "all undefined refs already labelled"
    return True, f"seed \\newlabel stubs: {', '.join(changed)}"


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


def _invalidate_changed(ctx: LoopCtx, before: dict[Path, tuple[int, int]]) -> int:
    """快照后新增/改写/删除路径全 invalidate → 失效数。

    docstrip 类 ``run_tool`` 一次写多件的通用补: 请求件之外的兄弟产出
    同步失效 ``_texts``——pre-run 读过缺件会缓存 miss→None 毒化条目,
    产出落地后缓存仍答 None, 下游规则当缺件 (同 logcache 病族)。
    不触 ``_texts`` 私有面, 指纹 diff 即全覆盖 (真写必换指纹)。
    """
    after = _wdir_fingerprint(ctx.wdir)
    changed = _fp_diff(before, after)
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
    rel = _safe_rel(want)
    if rel is None:
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
