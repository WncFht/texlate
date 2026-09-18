r"""_builtins_shim — stub/遮蔽/polyfill 注入原语 (C3 拆分)。

往 wdir/主文件注入新件或 prologue: 退役包 cls/sty stub (legacy_pkg_shim) /
svjour .clo noop stub / pdfTeX 读取原语 polyfill / 期刊宏 ``\\providecommand``
整表注入 / 引擎 bundle 内建类遮蔽 stub; ``shim_pkgs_in_use`` 是 shim_map
键的工程在用量查询 (engine shim_known 条件实现)。
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_common import (
    _FB_FONT,
    _MATH_SHIM_CS,
    PDFTEX_PRIMS,
    _fixloop_log,
    _inject_after_docclass,
    _inject_write,
    _live_matches,
    _mc_chr,
    _mc_parse_log,
    _mc_table,
)
from texlate.latex.tables import MATH_ENVS
from texlate.textutil import DOCCLASS_OPTS_RX, mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx


def pdftex_prim_polyfill(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""读取型 pdfTeX 原语补定义: ``\\ifdefined\\<prim>\\else\\chardef\\<prim>=1\\fi``。

    guard 规则只管 ``\\pdfX=val``/``\\pdfX{..}`` 赋值型; ``\\ifnum\\pdfoutput``
    这类读取型需要原语已定义 (docs/08:268)。注入点恒在主文件头——
    cls/sty 内部读取发生在 ``\\documentclass`` 加载期间, 类行后注入太晚
    (2410.00012: ieeeaccess.cls:128 内 ``\\pdfobj``); ``ifdefined``
    前缀天然幂等。
    """
    del eng  # 签名面统一; 注入发生在主文件源文本
    prim = str(params.get("prim") or payload or "")
    if prim not in PDFTEX_PRIMS:
        return False, f"{prim} not in pdfTeX prim list"
    guard = f"\\ifdefined\\{prim}\\else\\chardef\\{prim}=1\\fi"
    main = ctx.main_path()
    if main is None:
        return False, "no main tex"
    t = ctx.read(main) or ""
    if f"\\ifdefined\\{prim}" in t:
        return False, f"{prim} already guarded"
    ctx.write(main, guard + " % fixloop polyfill\n" + t)
    return True, f"polyfill \\{prim} at file head"


def _shim_spec(
    shim_map: dict[str, Any], payload: str | None
) -> tuple[str, dict[str, Any] | None]:
    """``payload`` → ``(归一文件名, spec)``。裸名 payload 补 ``.tex`` 再查。"""
    fname = payload or ""
    spec = shim_map.get(fname)
    if spec is None and not Path(fname).suffix:
        # `I can't find file `X'` 裸 payload (\input 系): 实体是 X.tex ——
        # shim 键与 stub 落点都用归一名 (epsf→epsf.tex 实证)。
        fname = f"{fname}.tex"
        spec = shim_map.get(fname)
    return fname, spec


def legacy_pkg_shim(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""退役/改名包的 shim: ``shim_map[payload]`` → 往 wdir 注入同名 stub + 装依赖。

    spec 键:
      ``loads: <pkg-base>`` — cls 类 stub 模板 ``\\LoadClassWithOptions{<pkg>}``;
      ``body: <tex>``       — 自定义 stub 全文 (sty 桥接, 如 psfig→epsfig);
      ``needs: [files]``    — stub 依赖文件, 先 install_file 补齐 (缺则照记, 下轮
                              missing_file 自然归因)。
    实证锚点 (fixloop-v2): aastex→emulateapj 救回 1806.06690 (aastex701 删了
    ``\\altaffilmark`` 族, 非 drop-in; emulateapj 为 arXiv 投稿仿 aastex 接口);
    psfig→epsfig 桥可用因 epsfig 的 Gin key 同收 ``figure=``/``file=``。
    """
    fname, spec = _shim_spec(params.get("shim_map") or {}, payload)
    if not spec:
        return False, f"no legacy shim for {payload}"
    stub = spec.get("body")
    loads = spec.get("loads")
    if not stub and loads:
        stem = fname.rsplit(".", 1)[0]
        stub = (
            "\\NeedsTeXFormat{LaTeX2e}\n"
            # 版本串必须以 YYYY/MM/DD 日期开头: \\documentclass 装载时
            # \\@ifl@t@r 会解析 ver@*.cls, 裸文字 "fixloop ..." 让
            # \\@parse@version@ 读出 `f' → "Missing = inserted for \\ifnum"
            # (1806.06690 实证; 无 halt-on-error 时可恢复故有 pdf 假象)。
            f"\\ProvidesClass{{{stem}}}[2026/09/15 fixloop legacy shim -> {loads}]\n"
            f"\\LoadClassWithOptions{{{loads}}}\n"
            "\\endinput\n"
        )
    if not stub:
        return False, f"shim spec for {payload} has neither body nor loads"
    missing = []
    for dep in spec.get("needs") or []:
        if ctx.wdir.joinpath(dep).is_file():
            continue
        if eng.probe_file(dep) or eng.install_file(dep):
            continue
        missing.append(dep)
    done, state = _inject_write(ctx, ctx.wdir / fname, stub, f"stub {fname}")
    if done is not None:
        return done
    note = f"stub {fname} {'refreshed (stale injected)' if state == 'stale' else 'injected'}"
    if loads:
        note += f" (\\LoadClassWithOptions{{{loads}}})"
    if missing:
        note += f"; deps still missing: {', '.join(missing)}"
    return True, note


#: ``\documentclass`` 选项表提取 —— 选项可缺省, 方括号内允跨行空白。
#: 单源 ``textutil.DOCCLASS_OPTS_RX``；私名仍挂 builtins 门面 ``__all__``
#: 再导出位, 但门面路径零消费 (B12 死回引在册)——唯一用点是本叶
#: ``svjour_clo_stub``。
_DOCCLASS_OPTS_RE = DOCCLASS_OPTS_RX


def svjour_clo_stub(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""svjour.cls 零 .clo 伴船 → 按 ``\documentclass`` 选项写 ``sv<opt>.clo`` noop stub。

    实证根因 (0905.0193): e-print 捆绑 svjour.cls (2003, Springer) 但不带
    任何 .clo, TeX Live 亦不收录 svjour → ``\DeclareOption*`` 里
    ``\InputIfFileExists{sv\CurrentOption.clo}`` 逐选项落空,
    ``\journalopt`` 停在 ``\@empty`` → ``\ClassError{No valid journal
    specified}`` + ``\stop``。noop ``\endinput`` stub 让 InputIfFileExists
    走真臂置 ``\journalopt`` 为选项名即过; 盘上已有真 .clo 不覆盖。
    """
    del eng, payload, params
    main = ctx.main_path()
    t = ctx.read(main) if main is not None else None
    if t is None:
        return False, "no main tex"
    vis = mask_tex(t)  # 注释掉的 %\documentclass 的选项不得入 stub 表
    if not _DOCCLASS_OPTS_RE.search(vis):
        return False, "no \\documentclass in main"
    opts = [
        o.strip()
        for m in _DOCCLASS_OPTS_RE.finditer(vis)
        for o in (m.group(1) or "").split(",")
        if o.strip()
    ]
    if not opts:
        return False, "no documentclass options"
    written = []
    body = "% fixloop: svjour option stub (noop)\n\\endinput\n"
    for opt in dict.fromkeys(opts):
        if "/" in opt or "\\" in opt:
            continue  # 防选项里的路径分隔符穿出 wdir / write_text 炸 OSError
        target = ctx.wdir / f"sv{opt}.clo"
        # 指纹闸: 外来 .clo (稿自带) 永不覆写; 旧代注入件覆写刷新。
        done, _state = _inject_write(ctx, target, body, target.name)
        if done is not None:
            continue
        written.append(target.name)
    if not written:
        return False, "all sv*.clo already present, nothing written"
    return True, f"svjour .clo stubs written: {', '.join(written)}"


#: AAS 期刊缩写宏表 —— emulateapj.cls L1201-1256 ``\ref@jnl`` 全表抄录
#: (去壳成纯文本展开)。实证锚点: tectonic bundle 内置 aastex 5.0rc3.1 (1999)
#: 没有这批宏, 老 aastex 文档 \bibitem 里的 ``\actaa`` 族全成 undefined_cs
#: (1806.06690 tectonic 臂)。\providecommand 语义: 类里已有定义时不覆盖。
_JOURNAL_MACROS: dict[str, str] = {
    "aj": "AJ",
    "araa": "ARA\\&A",
    "apj": "ApJ",
    "apjl": "ApJ~Lett.",
    "apjs": "ApJS",
    "ao": "Appl.~Opt.",
    "apss": "Ap\\&SS",
    "aap": "A\\&A",
    "aapr": "A\\&A~Rev.",
    "aaps": "A\\&AS",
    "azh": "AZh",
    "baas": "BAAS",
    "icarus": "Icarus",
    "jrasc": "JRASC",
    "memras": "MmRAS",
    "mnras": "MNRAS",
    "pra": "Phys.~Rev.~A",
    "prb": "Phys.~Rev.~B",
    "prc": "Phys.~Rev.~C",
    "prd": "Phys.~Rev.~D",
    "pre": "Phys.~Rev.~E",
    "prl": "Phys.~Rev.~Lett.",
    "pasp": "PASP",
    "pasj": "PASJ",
    "qjras": "QJRAS",
    "skytel": "S\\&T",
    "solphys": "Sol.~Phys.",
    "sovast": "Soviet~Ast.",
    "ssr": "Space~Sci.~Rev.",
    "zap": "ZAp",
    "nat": "Nature",
    "iaucirc": "IAU~Circ.",
    "aplett": "Astrophys.~Lett.",
    "apspr": "Astrophys.~Space~Phys.~Res.",
    "bain": "Bull.~Astron.~Inst.~Netherlands",
    "fcp": "Fund.~Cosmic~Phys.",
    "gca": "Geochim.~Cosmochim.~Acta",
    "grl": "Geophys.~Res.~Lett.",
    "jcp": "J.~Chem.~Phys.",
    "jgr": "J.~Geophys.~Res.",
    "jqsrt": "J.~Quant.~Spec.~Radiat.~Transf.",
    "memsai": "Mem.~Soc.~Astron.~Italiana",
    "nphysa": "Nucl.~Phys.~A",
    "physrep": "Phys.~Rep.",
    "physscr": "Phys.~Scr.",
    "planss": "Planet.~Space~Sci.",
    "procspie": "Proc.~SPIE",
    "actaa": "Acta Astron.",
    "caa": "Chinese Astron. Astrophys.",
    "cjaa": "Chinese J. Astron. Astrophys.",
    "jcap": "J.~Cosmology Astropart.~Phys.",
    "na": "New~A",
    "nar": "New~A~Rev.",
    "pasa": "PASA",
    "rmxaa": "Rev.~Mexicana Astron.~Astrofis.",
}
_DOCCLASS_LINE_RE = re.compile(r"(?m)^[ \t]*\\document(?:class|style)[^\n]*\n?")


def journal_cs_polyfill(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""期刊缩写宏 polyfill: payload cs 命中表 → 全表 ``\providecommand`` 注入主文件。

    一次注入整表而非单宏 —— ``\bibitem`` 里期刊宏成串出现, 逐宏救火要打
    whack-a-mole 轮次; ``\providecommand`` 幂等, 重复注入无副作用。
    payload 未命中 → False 落到 undefined_cs_guess。
    """
    del eng
    table = dict(_JOURNAL_MACROS)
    table.update(params.get("macros") or {})
    cs = (payload or "").lstrip("\\")
    if cs not in table:
        return False, f"{payload} not a known journal macro"
    main = ctx.main_path()
    t = ctx.read(main) if main is not None else None
    if t is None:
        return False, "no main tex"
    block = "% fixloop: AAS journal-macro polyfills (类文件过老缺定义)\n" + "\n".join(
        rf"\providecommand{{\{name}}}{{{exp}}}" for name, exp in sorted(table.items())
    )
    m = _DOCCLASS_LINE_RE.search(mask_tex(t))  # 等长遮盖 → offset 对原文有效
    at = m.end() if m else 0
    ctx.write(main, t[:at] + block + "\n" + t[at:])
    return True, f"journal-macro polyfill injected (\\{cs} 命中, 全表 {len(table)} 宏)"


def bundled_class_shadow(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""引擎 bundle 内建类太老 → wdir 注入同名 stub 遮蔽 (wdir 优先于 bundle)。

    实证: tectonic 内置 aastex 5.0rc3.1 (1999) 缺 ``\actaa``/deluxetable
    宏族 —— missing_file 永远打不到 (bundle 能解析), 只能 undefined_cs 确证后
    遮蔽换 emulateapj。``cs_set`` 命中 + ``include_journal_table`` 并集判
    payload; stub ``body`` 由 rules/ 分片条目提供 (85-shim.yaml 三处 +
    55-prim.yaml; 版本串须日期开头, 见 legacy_pkg_shim 注)。
    """
    cs = (payload or "").lstrip("\\")
    cs_set = {str(x).lstrip("\\") for x in params.get("cs_set") or []}
    if params.get("include_journal_table"):
        cs_set |= set(_JOURNAL_MACROS)
    target = params.get("target")
    body = params.get("body")
    if not cs or cs not in cs_set or not target or not body:
        return False, f"{payload} not in bundle-shadow set"
    missing = []
    for dep in params.get("needs") or []:
        if (
            ctx.wdir.joinpath(dep).is_file()
            or eng.probe_file(dep)
            or eng.install_file(dep)
        ):
            continue
        missing.append(dep)
    t = ctx.wdir / str(target)
    # 指纹闸: 稿自带同名件不覆写; 旧代注入件覆写刷新。
    done, state = _inject_write(ctx, t, str(body), f"shadow {target}")
    if done is not None:
        return done
    note = (
        f"shadow {target} {'refreshed (stale injected)' if state == 'stale' else 'injected'}"
        f" (\\{cs} missing from bundled class)"
    )
    if missing:
        note += f"; deps still missing: {', '.join(missing)}"
    return True, note


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
    rel = PurePosixPath(fname)
    if not fname or rel.is_absolute() or ".." in rel.parts or "\x00" in fname:
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
    target = ctx.wdir / Path(*rel.parts)
    body = f"% fixloop: stub for runtime-generated {rel.name}\n"
    # 指纹闸: 外来生成件/稿自带覆盖层永不覆写; 旧代注入 stub 覆写刷新。
    done, _state = _inject_write(ctx, target, body, fname)
    if done is not None:
        # current/foreign/写败 —— 盘上已有(或写不进)则不占位, 交后续规则
        return False, done[1] if not done[0] else f"{fname} already on disk"
    return True, f"{hit}-stub {fname}"


def shim_pkgs_in_use(ctx: LoopCtx, shim_map: dict[str, Any]) -> list[str]:
    r"""工程源码里实际引用的 shim_map 键 (shim_known 条件实现)。

    键可带扩展名 (install_file 系 map 形如 ``revtex4-1.cls``)——按 stem
    匹 ``\\usepackage``/``\\RequirePackage``/``\\documentclass``/``\\documentstyle``
    花括号名单, 否则 ``\\bspotcolor\\.sty\\b`` 对裸名 ``{spotcolor}`` 永不中。
    """
    blob = mask_tex(ctx.source_blob())  # 注释掉的假装载点不算在用
    hits = []
    for pkg in shim_map:
        stem = re.sub(r"\.(?:sty|cls|clo|tex|def|cfg)$", "", str(pkg))
        if re.search(
            rf"\\(?:usepackage|RequirePackage|documentclass|documentstyle)"
            rf"\s*(?:\[[^\]]*\])?\s*\{{[^}}]*\b{re.escape(stem)}\b",
            blob,
        ):
            hits.append(pkg)
    return hits


# ════════════════════════════════════════════════════════════════
# o2-builtin-cs 面 (m1b-residue-routes-2026-09-17): env_undefined
# polyfill / AMS 上古字体 cs shim / produced-by-cs 缺字 cs_rebind
# ════════════════════════════════════════════════════════════════

#: log 内 env_undefined 签名 —— ``LaTeX Error: Environment X undefined``。
_ENV_UNDEF_RE = re.compile(r"Environment\s+([A-Za-z@*]+)\s+undefined")

#: ``\begin/\end{env}`` 使用面扫 (单遍全取)。
_ENV_USE_RE = re.compile(r"\\(?:begin|end)\s*\{\s*([A-Za-z@*]+)\s*\}")

#: in-doc 环境定义证据 —— ``\newenvironment``/``\newtheorem``/xparse 族 +
#: ``\def\e``/``\def\ende``/``\let\e`` 裸绑。命中即不扩 (可能是活定义;
#: 死块证据最多迟一轮, 由 log-proven 路径接回)。
_ENV_DEF_RE = re.compile(
    r"\\(?:new|renew)environment\*?\s*\{\s*([A-Za-z@*]+)\s*\}"
    r"|\\(?:newtheorem|declaretheorem)\*?\s*\{\s*([A-Za-z@*]+)\s*\}"
    r"|\\(?:Declare|New|Renew|Provide)DocumentEnvironment\s*\{\s*([A-Za-z@*]+)\s*\}"
    r"|\\def\\(?:end)?([A-Za-z@*]+)\b|\\let\\(?:end)?([A-Za-z@*]+)\b"
)

#: 内核/近全类通用环境 —— 批扩 cosmetic 降噪表 (守卫行本就语义无操作,
#: 漏列只多一行守卫不坏事; 真缺时 log-proven 路径照样兜回)。amsmath
#: 数学环境故意不收 —— 缺 amsmath 正是要 ``\[..\]`` 壳救的面。
_KERNEL_ENVS: frozenset[str] = frozenset(
    {
        "abstract",
        "array",
        "center",
        "description",
        "displaymath",
        "document",
        "enumerate",
        "eqnarray",
        "eqnarray*",
        "equation",
        "equation*",
        "figure",
        "figure*",
        "filecontents",
        "filecontents*",
        "flushleft",
        "flushright",
        "itemize",
        "letter",
        "list",
        "math",
        "minipage",
        "picture",
        "quotation",
        "quote",
        "samepage",
        "tabular",
        "tabular*",
        "thebibliography",
        "theindex",
        "titlepage",
        "trivlist",
        "verbatim",
        "verbatim*",
        "verse",
    }
)


def _inject_before_begindoc(ctx: LoopCtx, snippet: str) -> bool:
    r"""主文件首个 live ``\begin{document}`` 行首注入 snippet (幂等)。

    与 docclass 缝位的本质差别: 全部 ``\usepackage``/cls 内装载已执行,
    ``\ifcsname`` 守卫在此点才能正确见包/类已定义名 —— env polyfill
    批扩依赖这个时序 (docclass 位守卫会把后载包定义的环境误判成缺,
    注成 noop 再被包的 ``\newenvironment`` 反撞 already_def)。
    无 live ``\begin{document}`` (片断稿/死区命中) 退 docclass 缝。
    """
    main = ctx.main_path()
    t = ctx.read(main) if main is not None else None
    if t is None or snippet in t:
        return False
    masked = mask_tex(t)
    m = re.search(r"\\begin\s*\{\s*document\s*\}", masked)
    if m is None or masked[m.start() : m.end()] != t[m.start() : m.end()]:
        return _inject_after_docclass(ctx, snippet)
    # 行首锚 —— \begin{document} 若裹在宏参死块 (\doit{0}{...}) 里,
    # 行首注入仍落活区顶位
    at = t.rfind("\n", 0, m.start()) + 1
    ctx.write(main, t[:at] + snippet + "\n" + t[at:])
    return True


def _env_noop_line(env: str) -> str:
    r"""``\ifcsname`` 守卫的 noop ``\newenvironment`` 行; 数学 env 给 ``\[..\]`` 壳。"""
    pre, post = (r"\[", r"\]") if env in MATH_ENVS else ("", "")
    return (
        rf"\ifcsname {env}\endcsname\else"
        rf"\newenvironment{{{env}}}{{{pre}}}{{{post}}}\fi"
    )


#: env polyfill 对偶件表 —— env 名 → (源内使用证据 rx, 同补 stub 行)。
#: 缺 proof env 的稿多伴 ``\QED`` 收尾标记 (amsthm 对偶件; 0707.1588
#: IEEEtran 实证: proof noop 后 ``undefined_cs:QED`` 即浮面) —— polyfill
#: proof 同轮补 ``\providecommand{\QED}`` 省一轮。stub 形 = amsthm
#: ``\qedsymbol`` 纯原语开口盒, 不依赖 amssymb ``\square``。
_ENV_COMPANIONS: dict[str, tuple[str, str]] = {
    "proof": (
        r"\\QED\b",
        (
            r"\providecommand{\QED}{\leavevmode\hbox to.77778em{\hfil\vrule"
            r"\vbox to.675em{\hrule width.6em\vfil\hrule}\vrule}}"
        ),
    ),
}


#: renew 族环境再定义站点 —— ``\renewenvironment{X}`` 对未定义 env 报同一
#: ``Environment X undefined`` 签 (0806.0904/0806.2953 ``\renewenvironment{proof}``
#: 于 preamble :743 实证, pre-begindoc 注入 :1069 晚 325 行救不到);
#: 须在站点行首前置守卫 noop 让 renew 的 ``\@ifundefined`` 闸通过, renew 随
#: 即以稿自带定义覆盖 noop —— 比批扩位多保住 renew 语义。xparse
#: ``\RenewDocumentEnvironment`` 未定义时报 ``cmd Error`` 异签 (不产本类
#: payload), 同名站点同面顺手覆盖。
_RENEW_ENV_SITE_RE = re.compile(
    r"\\(?:renewenvironment|RenewDocumentEnvironment)"
    r"\s*\*?\s*\{\s*([A-Za-z@*]+)\s*\}"
)


def _live_renew_sites(t: str, envs: set[str]) -> dict[str, int]:
    r"""``envs`` 各名在 ``t`` 的首个 live renew 站点偏移 (env→pos)。

    遮盖 span 复核剔注释/verbatim 死区; 其后同名站点见到的 env 已被
    首站点 renew 定义, 无需再前置。
    """
    masked = mask_tex(t)
    sites: dict[str, int] = {}
    for m in _RENEW_ENV_SITE_RE.finditer(masked):
        name = m.group(1)
        if name not in envs or name in sites:
            continue
        if masked[m.start() : m.end()] != t[m.start() : m.end()]:
            continue  # 注释/verbatim 死区内站点不动
        sites[name] = m.start()
    return sites


def _prepend_env_renew_sites(
    ctx: LoopCtx, envs: set[str], companions: dict[str, str]
) -> set[str]:
    r"""``envs`` 的 live renew 站点行首前置 ``\ifcsname`` noop → 已处理 env 集。

    行首锚 —— 站点裹 ``\AtBeginDocument``/宏参死块时前置仍落活区且先于
    执行点; 站点在 body 内同样覆盖 (renew 合法出现在任何位置)。
    ``companions`` (env→stub 行, 调用方已按源内使用证据过滤) 随 noop
    同块下落 —— 站点多在 preamble, ``\QED`` 类对偶件若被序言调用
    同样够得着。``ins in nt[:pos]`` 幂等: 上轮前置或 pre-begindoc 批块
    行已先于站点者不再重复 (批块在 preamble 站点之后, 不误伤本轮需求)。
    """
    done: set[str] = set()
    for f in ctx.tex_files((".tex", ".sty", ".cls")):
        t = ctx.read(f)
        if t is None:
            continue
        sites = _live_renew_sites(t, envs)
        if not sites:
            continue
        nt = t
        # 降序插 —— 先动高偏移站点, nt[:pos] 对已处理插入免疫
        for name, pos in sorted(sites.items(), key=lambda kv: -kv[1]):
            ins = _env_noop_line(name)
            if ins in nt[:pos]:
                continue
            block = ins + " % fixloop: pre-renew noop\n"
            if comp := companions.get(name):
                block += comp + "\n"
            at = nt.rfind("\n", 0, pos) + 1
            nt = nt[:at] + block + nt[at:]
            done.add(name)
        if nt != t:
            ctx.write(f, nt)
    return done


def undefined_env_polyfill(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``Environment X undefined`` → ``\begin{document}`` 前 ``\newenvironment`` noop。

    proven = payload ∪ 本轮 log ``Environment X undefined`` 全扫。
    halt_on_error 每轮只见首缺 env (1012.1059 8 env 同缺实测) ——
    批扩到 "blob 内 ``\begin/\end`` 在用 ∪ 无 in-doc 定义证据" 的
    全 env 面, 一轮全清: ``\ifcsname`` 守卫在 pre-begindoc 注入位对
    包/类已定义名自动死化, 真缺名拿 noop (数学 env 给 ``\[..\]`` 壳)。
    修复面: svjour/siamltex/aasms4 等老类不产现内核定理环境, 或定义躺
    ``\\ifnfssone``/``\\doit{0}`` 死条件块 (math/0104275 tcilatex 族)。
    ``params.deny`` (缺省 ``document``) 排不可 noop 化的环境名。

    站点前置臂 (0806.0904/0806.2953): proven env 若带 live
    ``\renewenvironment{X}`` 站点 (序言或正文皆可), 在站点行首前置同款
    守卫 noop —— renew 报错点先于 pre-begindoc 位, 批扩够不到; 前置后
    renew 闸通过并以稿自带定义覆盖 noop。站点臂处理的 env 不再占
    ``\begin``-used 门 (renew 本身即消费点); 站点在主文件者自动出
    fresh 批块 (``\ifcsname`` 已落盘), 在他文件者批块照注兜底
    (站点文件可能不被 ``\input`` 抵达, 双保险不误伤)。

    对偶件臂 (``_ENV_COMPANIONS``, 0707.1588): proof 被 polyfill 且源内
    ``\QED`` 在用 → 同块补 ``\providecommand{\QED}`` (amsthm 对偶件,
    缺 proof env 的稿多伴此标记); 独立 ``undefined_cs:QED`` (proof 已
    定义稿) 由 cs_targeted_fix ``cs_table.QED`` polyfill 兜。
    """
    del eng
    proven: set[str] = set()
    if payload and re.fullmatch(r"[A-Za-z@*]+", payload):
        proven.add(payload)
    proven.update(_ENV_UNDEF_RE.findall(_fixloop_log(ctx)))
    deny = {str(d) for d in (params.get("deny") or ())} | {"document"}
    proven -= deny
    if not proven:
        return False, "no undefined env to polyfill"
    # blob 须在注入前取 —— 对偶件证据 (``\QED`` 在用) 与 defined 判
    # 都不能看见自己即将注入的行 (stub 文本含 ``\QED`` 字面会自证)。
    blob = mask_tex(ctx.source_blob())
    companions = {
        e: _ENV_COMPANIONS[e][1]
        for e in proven
        if e in _ENV_COMPANIONS and re.search(_ENV_COMPANIONS[e][0], blob)
    }
    # renew 站点前置先行 —— preamble ``\renewenvironment{X}`` 的报错点在
    # pre-begindoc 注入位之前, 批扩永远够不到 (0806.0904/0806.2953);
    # 站点消费点注入后 renew 以稿自带定义覆盖 noop, 语义优于批扩 noop。
    site_envs = _prepend_env_renew_sites(ctx, proven, companions)
    used = set(_ENV_USE_RE.findall(blob)) - deny
    if not (proven & used) and not site_envs:
        return False, f"env(s) {sorted(proven)} not \\begin-used in source"
    defined = {n for m in _ENV_DEF_RE.finditer(blob) for n in m.groups() if n}
    targets = (proven & used) | (used - defined - _KERNEL_ENVS)
    main = ctx.main_path()
    main_masked = mask_tex(ctx.read(main) or "") if main is not None else ""
    fresh = [
        e for e in sorted(targets) if f"\\ifcsname {e}\\endcsname" not in main_masked
    ]
    notes: list[str] = []
    if site_envs:
        notes.append(f"pre-renew noop: {', '.join(sorted(site_envs))}")
    if fresh:
        lines = ["% fixloop: undefined env polyfill (noop env)"]
        for e in fresh:
            lines.append(_env_noop_line(e))
            if e in companions:
                lines.append(companions[e])
        if _inject_before_begindoc(ctx, "\n".join(lines)):
            notes.append(f"env polyfill: {', '.join(fresh)}")
    if not notes:
        return False, "undefined envs already polyfilled"
    return True, "; ".join(notes)


#: AMS 上古字体 cs 名 ``<size><fam>`` 全词锚 —— ``\\fivmi``/``\\tenmib``
#: 族 (hep-th/9703214: ``\\doit{0}`` 死块内 ``\\font`` 定义不执行, 活
#: ``\\skewchar\\fivmi`` 全链 undefined_cs ×83)。缩拼 + 全拼双写
#: (``\\fivemib`` 同稿实证)。``i`` 尾收 plain ``\\teni`` (cmmi10 惯名)。
#: 匹配模式由 ``_AMS_FONT_SIZE`` × ``_AMS_FONT_FAM`` 键合成 (params 可扩)。
#: 尺寸词 → pt (elv/frtn/... 是 LaTeX ``\\@xpt`` 族的 scaled-10 惯例值)。
_AMS_FONT_SIZE: dict[str, float] = {
    "fiv": 5,
    "six": 6,
    "sev": 7,
    "egt": 8,
    "nin": 9,
    "ten": 10,
    "elv": 10.95,
    "twl": 12,
    "frtn": 14.4,
    "svtn": 17.28,
    "twty": 20.74,
    "twfv": 24.88,
    "five": 5,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "eleven": 10.95,
    "twelve": 12,
}
#: 族尾 → CM/AMS 字体 base (10pt 设计尺寸恒在, ``at <sz>pt`` 兜底)。
_AMS_FONT_FAM: dict[str, str] = {
    "mi": "cmmi",
    "i": "cmmi",
    "mib": "cmmib",
    "sy": "cmsy",
    "bsy": "cmbsy",
    "ex": "cmex",
    "bf": "cmbx",
    "rm": "cmr",
    "it": "cmti",
    "sl": "cmsl",
    "tt": "cmtt",
    "sc": "cmcsc",
    "ss": "cmss",
    "msa": "msam",
    "msb": "msbm",
    "euf": "eufm",
    "eub": "eufb",
    "eur": "eurm",
    "eus": "eusm",
}
#: log 内 undefined_cs 报错行 → l.N 顶行末 cs (出错点 cs) 提取 —
#: taxonomy ``Undefined control sequence`` payload 同口径。
_UNDEF_CS_LINE_RE = re.compile(
    r"Undefined control sequence[^\n]*\n[^\n]*\\([a-zA-Z@]+)[^\\\n]*(?:\n|$)"
)
#: 源内字体位使用点 —— ``\\skewchar\\X`` / ``\\textfont\\d=\\X`` /
#: ``\\font\\X=``。dead-block ``\\font`` 定义 (``\\doit{0}`` 宏参) 不在
#: 遮盖面 —— 正合此修需求 (定义不执行才需 shim)。
_FONT_POS_RE = re.compile(
    r"\\(?:skewchar|(?:scriptscript|script|text)?font)"
    r"\s*(?:\d+\s*=\s*)?\\([A-Za-z@]+)"
)
#: 非 ``\\font`` 的定义证据 —— 命中的 ``<size><fam>`` 名若另有 \\def/\\let
#: 系定义则是真宏撞名 (font shim 抢名会把它毁掉), 不接管。
_NONFONT_DEF_RE = re.compile(
    r"\\(?:[egx]?def|let|newcommand|renewcommand|providecommand|"
    r"DeclareRobustCommand|newif|newcount|newbox|newdimen|newskip|"
    r"newmuskip|newtoks|newlength|newsavebox|newread|newwrite)"
    r"\s*\*?\s*\{?\s*\\([A-Za-z@]+)"
)


def _ams_font_rhs(
    eng: Engine | None, m: re.Match[str], sizes: dict[str, float], fams: dict[str, str]
) -> str:
    r"""``fivmi`` 匹配 → ``cmmi5`` / ``elvrm`` → ``cmr10 at 10.95pt``。

    eng 在且整数设计尺寸的 ``<base><size>.tfm`` 可探 → 设计尺寸绑定
    (字重/侧衬最优); 否则 ``<base>10 at <size>pt`` —— base10 全族恒在。
    """
    size, base = sizes[m.group(1)], fams[m.group(2)]
    if (
        eng is not None
        and size == int(size)
        and eng.probe_file(f"{base}{int(size)}.tfm")
    ):
        return f"{base}{int(size)}"
    return f"{base}10 at {size:g}pt"


def font_cs_shim(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""AMS 上古字体 cs 缺定义 → ``\\font\\<cs>=<cm 等价>`` 注入。

    窄谓词: payload ∈ ``<size><fam>`` 模式。收集面 = log undefined_cs 撞名
    (l.N 顶行末 cs) ∩ 模式 ∪ 源内字体位 (``\\skewchar``/``\\textfont``/
    ``\\font``) 现身且无 ``\\def`` 系定义证据者 —— 一次性整批, 免 83 错
    逐名烧轮。注入点在 docclass 后: 稿内后到的活 ``\\font``/``\\def``
    定义仍覆盖我们的早期绑定 (先绑定后定义赢序), 只对真缺定义位生效。
    ``params.sizes``/``params.fams`` 可扩映射表。
    """
    cs = (payload or "").lstrip("\\")
    sizes = dict(_AMS_FONT_SIZE)
    fams = dict(_AMS_FONT_FAM)
    for k, v in (params.get("sizes") or {}).items():
        sizes[str(k)] = float(v)
    for k, v in (params.get("fams") or {}).items():
        fams[str(k)] = str(v)
    pat = re.compile(r"(" + "|".join(sizes) + r")(" + "|".join(fams) + r")\Z")
    if not pat.fullmatch(cs):
        return False, f"{payload} not an AMS-era font name"
    log = _fixloop_log(ctx)
    undef = {n for n in _UNDEF_CS_LINE_RE.findall(log) if pat.fullmatch(n)}
    blob_masked = mask_tex(ctx.source_blob())
    defined_elsewhere = set(_NONFONT_DEF_RE.findall(blob_masked))
    pos_used = {
        m.group(1)
        for m in _FONT_POS_RE.finditer(blob_masked)
        if pat.fullmatch(m.group(1))
    }
    cands = sorted(undef | {c for c in pos_used if c not in defined_elsewhere})
    if not cands:
        return False, "no AMS font cs to shim"
    main = ctx.main_path()
    main_t = (ctx.read(main) or "") if main is not None else ""
    # 文本上已有 \font\<cs>= 的 (活定义/死块定义/上轮 shim) 且本轮未报错
    # → 跳过; 在报错集里的无条件重注 (可见 \font 定义必为死定义)。
    fresh = [
        c
        for c in cands
        if c in undef or not re.search(rf"\\font\s*\\{c}\b\s*=", main_t)
    ]
    if not fresh:
        return False, "AMS font cs already shimmed"
    lines = ["% fixloop: AMS-era font cs -> CM equivalents"]
    lines += [
        rf"\font\{c}={_ams_font_rhs(eng, m, sizes, fams)}"
        for c in fresh
        if (m := pat.fullmatch(c)) is not None
    ]
    if not _inject_after_docclass(ctx, "\n".join(lines)):
        return False, "font shim block already present"
    return True, f"font-cs shim: {', '.join(fresh)}"


# ═══ missing_char 第三子路: produced-by-cs 缺字 → cs 重绑回退字体 ═══


def _producer_map(params: dict[str, Any]) -> dict[int, str]:
    r"""码位 → 产出 cs 名: ``_MATH_SHIM_CS`` 反转 ∪ char_table ``produced_by`` ∪ ``params.producers`` hex 键。"""
    producers = {cp: cs for cs, cp in _MATH_SHIM_CS.items()}
    for e in _mc_table(params).values():
        if pb := e.get("produced_by"):
            for cp in e.get("cps") or ():
                producers[int(cp)] = str(pb).lstrip("\\")
    for k, v in (params.get("producers") or {}).items():
        producers[int(str(k), 16)] = str(v).lstrip("\\")
    return producers


def cs_rebind(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""TFM 字体下 ``\\S``/``\\o`` 等 cs 产出字符缺字 → ``\\protected\\def`` 绑回退字体。

    ``\\S``→§ 在 cmr10 下字面缺字 (2403.15096, 31 处 ``\\S`` 无一个字面 §):
    literal-replace 够不到 cs 产出面, ``\\newunicodechar`` 只管字面输入 ——
    missing_char_fix(25)/font_fallback(26) 都治不了, 缺第三子路。
    窄谓词 (全部成立才动):
      - 码位 ∈ 产出表 (``_MATH_SHIM_CS`` 反转 ∪ char_table ``produced_by``
        键 ∪ ``params.producers`` ``{"A7": "S"}`` hex 键);
      - 字面字符 *不* 在遮盖源 (在则 literal 面先修);
      - ``\\<cs>`` 在遮盖源现身 (cs 确为该缺字的生产者)。
    ``\\protected`` 保 moving-arg 安全 (physics/9901057 ``\\markboth{...\\o...}``
    实证); ``\\ifmmode\\mbox`` 分支数学/文本双域兼容。回退族名
    ``params.fallback_cs`` (缺省 txlatefallback) 与 font_fallback 共享
    ``\\ifdefined`` 守卫面 —— 先后注入不互踩 ``\\newfontfamily``。
    """
    del eng, payload
    log = _fixloop_log(ctx)
    if "Missing character" not in log:
        return False, "no Missing character in compile log"
    seen = _mc_parse_log(log)
    if not seen:
        return False, "Missing character lines but no codepoint parsed"
    producers = _producer_map(params)
    blob = mask_tex(ctx.source_blob())
    todo = [
        (cp, cs)
        for cp in sorted(seen)
        if (ch := _mc_chr(cp)) is not None
        and (cs := producers.get(cp)) is not None
        and ch not in blob
        and re.search(rf"\\{cs}(?![a-zA-Z@])", blob)
    ]
    if not todo:
        return False, "no produced-by-cs missing chars"
    main = ctx.main_path()
    main_masked = mask_tex(ctx.read(main) or "") if main is not None else ""
    fresh = [
        (cp, cs)
        for cp, cs in todo
        if not re.search(rf"\\protected\\def\\{cs}(?![a-zA-Z@])", main_masked)
    ]
    if not fresh:
        return False, "producer cs already rebound"
    font = str(params.get("fallback_font") or _FB_FONT)
    fam = str(params.get("fallback_cs") or "txlatefallback")
    lines = [
        "% fixloop: cs-rebind — missing chars produced by cs under TFM fonts",
        "\\ifdefined\\newfontfamily\\else\\usepackage{fontspec}\\fi",
        f"\\ifdefined\\{fam}\\else\\newfontfamily\\{fam}{{{font}}}\\fi",
    ]
    for cp, cs in fresh:
        ch = _mc_chr(cp)
        lines.append(
            rf"\protected\def\{cs}"
            rf"{{\ifmmode\mbox{{\{fam} {ch}}}\else{{\{fam} {ch}}}\fi}}"
        )
    if not _inject_after_docclass(ctx, "\n".join(lines)):
        return False, "cs-rebind block already present"
    names = ", ".join(f"\\{cs}->U+{cp:04X}" for cp, cs in fresh)
    return True, f"cs rebind: {names}"


# ═══ 209→revtex4-2 升级稿面 polyfill (revtex209_surface/revtex_pacs 13 格) ═══

#: latex209 ``upgrade_209`` 落盘的 COMPAT_SHIM 首行面包屑——该串唯一出处
#: 即 latex209.py 兼容垫块, 字面在 = 209 升级跑过。它本身是注释行 (遮盖
#: 视图遮没), 只能在原文判。
_209_SHIM_MARK = "% texlate: LaTeX 2.09 compatibility shim"

#: live ``\documentclass{revtex4-2}``——遮盖视图定位 + span 逐段复核
#: (``_live_matches``): 注释/verbatim 内假装载不锚; ``{revtex4}``/
#: ``{revtex4-1}`` 邻名不中。
_REVTEX42_DOCCLASS_RE = re.compile(
    r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{\s*revtex4-2\s*\}"
)

#: 注入面——与 90-shim-legacy.yaml ``shim_map.revtex.cls`` stub body 同义,
#: 剥去 cls 装载件 (``\LoadClassWithOptions`` 已由升级稿 docclass 行完成),
#: 补 ``\makeatletter`` 包装 (主文件语境 ``@`` 是 catcode-12, cls 内免费)。
#: ``\AtBeginDocument`` 参数内用单 ``#1``——hook 逐字存 token、
#: ``\begin{document}`` 时才执行内层 ``\def``; ``##`` 只用于 def 嵌 def
#: 的替换文本, 此处的 ``\def\pacs`` 不嵌在任何 def 里, 双写会字面留下
#: ``##`` 炸 "Parameters must be numbered consecutively" (guardsmoke
#: 两格实证, 2026-09-18)。
_REVTEX209_POLYFILL = (
    "% fixloop: revtex 2.09 surface polyfill (upgraded doc on revtex4-2)\n"
    "\\makeatletter\n"
    "\\frontmatter@init\n"
    "\\let\\frontmatter@init\\relax\n"
    "\\providecommand{\\twocolumn}[1][]{#1}\n"
    "\\@ifundefined{@makecol}"
    "{\\def\\@makecol{\\setbox\\@outputbox\\vbox{\\unvbox\\@cclv}}}{}\n"
    "\\AtBeginDocument{\\def\\pacs#1{\\par\\noindent\\textbf{PACS:} #1\\par}}\n"
    "\\makeatother"
)


def revtex209_surface_polyfill(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``\documentstyle{revtex}`` 209 升级稿 → revtex4-2 删除面整块 polyfill。

    ``upgrade_209`` 把 ``\documentstyle{revtex}`` 改写成
    ``\documentclass{revtex4-2}`` + COMPAT_SHIM——改写稿不再经 revtex.cls
    stub (90-shim-legacy ``legacy_pkg_shim`` 只答 ``missing_file``, 升级稿
    的类装载链里没有 revtex.cls 可缺), 却照样踩 revtex4-2 刻意删掉的 2.09
    宏面: ``\twocolumn``/``\@makecol`` 被 ``\let\@undefined`` (cls:4512/
    3912), frontmatter 机原生 ``\begin{document}`` 才武装而序言 ``\author``
    先炸 (``\collaboration@sw`` 生于 ``\frontmatter@init``, cls:2145),
    ``\pacs`` 在 ``\maketitle`` 后 ClassError (cls:2530)。corpus_v3 13 格
    实证簇: revtex209_surface 8 格 (undefined_cs 首错) + revtex_pacs 5 格
    (other 首错)。

    锚定双条件缺一不可: 原文含 ``_209_SHIM_MARK`` 面包屑 (∧) 遮盖视图存在
    live ``\documentclass{revtex4-2}`` (span 复核排死区——注释掉的 docclass
    不算, 直写 ``\documentclass{revtex4-2}`` 的非 209 稿无面包屑不中)。

    注入位 ``_inject_after_docclass``——类装载缝是最早合法点: 序言
    ``\author`` 调用须先看到已武装的 frontmatter 机, ``\begin{document}``
    前注入太晚 (chao-dyn/9901009 ``\author``:207 vs ``\begin{document}``:237
    实证)。``snippet in t`` 幂等 + 注入体全 ``\providecommand``/guard 面,
    重入与叠加安全。
    """
    del eng, payload, params  # 锚定全在主文件源码面; 无 params 键
    main = ctx.main_path()
    t = ctx.read(main) if main is not None else None
    if t is None:
        return False, "no main tex"
    if _209_SHIM_MARK not in t:
        return False, "no 209-upgrade breadcrumb"
    if not _live_matches(_REVTEX42_DOCCLASS_RE, t):
        return False, "live docclass target not revtex4-2"
    if not _inject_after_docclass(ctx, _REVTEX209_POLYFILL):
        return False, "polyfill block already present"
    return True, "revtex 2.09 surface polyfill injected after docclass"
