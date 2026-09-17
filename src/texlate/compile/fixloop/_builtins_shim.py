r"""_builtins_shim — stub/遮蔽/polyfill 注入原语 (C3 拆分)。

往 wdir/主文件注入新件或 prologue: 退役包 cls/sty stub (legacy_pkg_shim) /
svjour .clo noop stub / pdfTeX 读取原语 polyfill / 期刊宏 ``\\providecommand``
整表注入 / 引擎 bundle 内建类遮蔽 stub; ``shim_pkgs_in_use`` 是 shim_map
键的工程在用量查询 (engine shim_known 条件实现)。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_common import PDFTEX_PRIMS
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
    shim_map = params.get("shim_map") or {}
    fname = payload or ""
    spec = shim_map.get(fname)
    if spec is None and not Path(fname).suffix:
        # `I can't find file `X'` 裸 payload (\input 系): 实体是 X.tex ——
        # shim 键与 stub 落点都用归一名 (epsf→epsf.tex 实证)。
        fname = f"{fname}.tex"
        spec = shim_map.get(fname)
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
    target = ctx.wdir / fname
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(stub, encoding="utf-8")
    note = f"stub {fname} injected"
    if loads:
        note += f" (\\LoadClassWithOptions{{{loads}}})"
    if missing:
        note += f"; deps still missing: {', '.join(missing)}"
    return True, note


#: ``\documentclass`` 选项表提取 —— 选项可缺省, 方括号内允跨行空白。
#: 单源 ``textutil.DOCCLASS_OPTS_RX``；私名保留为 builtins 门面回引柄。
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
    for opt in dict.fromkeys(opts):
        if "/" in opt or "\\" in opt:
            continue  # 防选项里的路径分隔符穿出 wdir / write_text 炸 OSError
        target = ctx.wdir / f"sv{opt}.clo"
        if target.exists():
            continue  # 盘上真 .clo 优先, 不覆盖
        ctx.write(target, "% fixloop: svjour option stub (noop)\n\\endinput\n")
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
    payload; stub ``body`` 由 rules.yaml 提供 (版本串须日期开头, 见
    legacy_pkg_shim 注)。
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
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text(body, encoding="utf-8")
    note = f"shadow {target} injected (\\{cs} missing from bundled class)"
    if missing:
        note += f"; deps still missing: {', '.join(missing)}"
    return True, note


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
