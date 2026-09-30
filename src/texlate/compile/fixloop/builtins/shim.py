r"""builtins.shim — shim_map stub/遮蔽注入原语 (C3 拆分)。

``shim_map[payload]`` spec 驱动的注入件落位 (``_shim_spec``/
``_install_needs``/``_inject_named`` 一条龙): 退役包 cls/sty stub
``legacy_pkg_shim`` / svjour .clo noop ``svjour_clo_stub`` / 期刊宏
``\providecommand`` 整表 ``journal_cs_polyfill`` / 引擎 bundle 内建
类遮蔽 stub ``bundled_class_shadow``; ``shim_pkgs_in_use`` 是 shim_map
键的工程在用量查询 (engine shim_known 条件实现);
``revtex209_surface_polyfill`` 是 209 升级稿踩 revtex4-2 删除面的
整块守卫注入。

再拆出叶: pdfTeX 原语 polyfill ``builtins.pdfprim`` / payload 文件
归位占位 ``builtins.filefix`` / env noop ``builtins.envpoly`` / cs
重绑 ``builtins.csbind``; payload 名卫 ``_safe_rel`` 收进
``builtins.common``。
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import (
    _AT_LETTER_POST,
    _AT_LETTER_PRE,
    _inject_after_docclass,
    _inject_write,
    _live_matches,
    _resolve_site,
)
from texlate.compile.latex209 import REVTEX209_CORE
from texlate.textutil import DOCCLASS_OPTS_RX, mask_tex

if TYPE_CHECKING:
    from collections.abc import Iterable

    from texlate.compile.fixloop.engine import Engine, LoopCtx


def _shim_spec(
    shim_map: dict[str, Any], payload: str | None
) -> tuple[str, dict[str, Any] | None]:
    """``payload`` → ``(归一文件名，spec)``。裸名 payload 补 ``.tex`` 再查。"""
    fname = payload or ""
    spec = shim_map.get(fname)
    if spec is None and not Path(fname).suffix:
        # `I can't find file `X'` 裸 payload (\input 系): 实体是 X.tex ——
        # shim 键与 stub 落点都用归一名 (epsf→epsf.tex 实证)。
        fname = f"{fname}.tex"
        spec = shim_map.get(fname)
    return fname, spec


def _install_needs(ctx: LoopCtx, eng: Engine, needs: Iterable[str] | None) -> list[str]:
    """stub/shadow 的 ``needs`` 依赖逐件补装 → 仍缺名表。

    解析位已有件 / ``probe_file`` 可探 / ``install_file`` 可装三者任一即不缺;
    缺者照记进 note (下轮 missing_file 自然归因), 不阻塞本体注入。
    """
    missing = []
    for dep in needs or []:
        dep_site = _resolve_site(ctx, PurePosixPath(dep))
        if (
            (dep_site is not None and dep_site.is_file())
            or eng.probe_file(dep)
            or eng.install_file(dep)
        ):
            continue
        missing.append(dep)
    return missing


def _inject_named(
    ctx: LoopCtx, rel: PurePosixPath, body: str, name: str, why: str = ""
) -> tuple[bool, str]:
    """``_resolve_site`` → ``_inject_write`` 一条龙 → ``(ok, note)``。

    site 逃出 wdir / 外来件指纹闸 / 写失败 / 盘上已 current 各终局 note
    直冒泡 (``False`` 调用方 decline, ``True`` 已 current 免重写); 写成功
    拼 ``"<name> injected"`` (旧代件为 ``"refreshed (stale injected)"``),
    ``why`` 非空加 ``(<why>)`` 尾注。
    """
    site = _resolve_site(ctx, rel)
    if site is None:
        return False, f"{rel}: escapes wdir"
    done, state = _inject_write(ctx, site, body, name)
    if done is not None:
        return done
    note = f"{name} {'refreshed (stale injected)' if state == 'stale' else 'injected'}"
    if why:
        note += f" ({why})"
    return True, note


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
            # 版本串必须以 YYYY/MM/DD 日期开头：\\documentclass 装载时
            # \\@ifl@t@r 会解析 ver@*.cls, 裸文字 "fixloop ..." 让
            # \\@parse@version@ 读出 `f' → "Missing = inserted for \\ifnum"
            # (1806.06690 实证; 无 halt-on-error 时可恢复故有 pdf 假象)。
            f"\\ProvidesClass{{{stem}}}[2026/09/15 fixloop legacy shim -> {loads}]\n"
            f"\\LoadClassWithOptions{{{loads}}}\n"
            "\\endinput\n"
        )
    if not stub:
        return False, f"shim spec for {payload} has neither body nor loads"
    missing = _install_needs(ctx, eng, spec.get("needs"))
    # 指纹闸：稿自带同名件不覆写; 旧代注入件覆写刷新。
    ok, note = _inject_named(
        ctx,
        PurePosixPath(fname),
        stub,
        f"stub {fname}",
        why=f"\\LoadClassWithOptions{{{loads}}}" if loads else "",
    )
    if ok and missing:
        note += f"; deps still missing: {', '.join(missing)}"
    return ok, note


#: ``svjour_clo_stub`` 写入体：真 .clo 内嵌 size10.clo 复刻本
#: (corpus/1107.0209 svepj.clo:46-72 抄值，``dd`` 归一为 ``pt``)。
#: 纯 ``\endinput`` noop 遮蔽真件 → size-family 永不播种，
#: ``\normalsize`` 停在 kernel error-stub (latex.ltx ``\@latex@error``)
#: → fontspec-xetex:443 / ctex:715 "font size command \normalsize is
#: not defined" (2505.06598 实证)。``\renewcommand`` 必要——kernel 预置
#: error-stub 视为已定义，``\providecommand`` 不覆盖; 兄弟尺寸宏 kernel
#: 未预置，``\providecommand`` 播了不撞稿自带真件序。
_SVJOUR_CLO_BODY = (
    "% fixloop: svjour option stub — noop + size-family seed\n"
    "\\renewcommand\\normalsize{%\n"
    "   \\@setfontsize\\normalsize\\@xpt\\@xiipt\n"
    "   \\abovedisplayskip 10\\p@ \\@plus2\\p@ \\@minus5\\p@\n"
    "   \\abovedisplayshortskip \\z@ \\@plus3\\p@\n"
    "   \\belowdisplayshortskip 6\\p@ \\@plus3\\p@ \\@minus3\\p@\n"
    "   \\belowdisplayskip \\abovedisplayskip}\n"
    "\\normalsize\n"
    "\\providecommand\\small{\\@setfontsize\\small\\@ixpt{10.5pt}}\n"
    "\\providecommand\\footnotesize{\\@setfontsize\\footnotesize\\@viiipt{9.5pt}}\n"
    "\\providecommand\\scriptsize{\\@setfontsize\\scriptsize\\@viipt\\@viiipt}\n"
    "\\providecommand\\tiny{\\@setfontsize\\tiny\\@vpt\\@vipt}\n"
    "\\providecommand\\large{\\@setfontsize\\large\\@xiipt\\@xivpt}\n"
    "\\providecommand\\Large{\\@setfontsize\\Large\\@xivpt{16pt}}\n"
    "\\providecommand\\LARGE{\\@setfontsize\\LARGE\\@xviipt{18pt}}\n"
    "\\providecommand\\huge{\\@setfontsize\\huge\\@xxpt{25pt}}\n"
    "\\providecommand\\Huge{\\@setfontsize\\Huge\\@xxvpt{30pt}}\n"
    # PACS 面：svepj.clo:224-225/254-256 抄值 (嵌套位 ## 归一为顶层 #);
    # 稿面 \PACS{...} + \@@PACS 放出链缺件即 undefined_cs (2505.06598 实证)。
    "\\def\\pacsstart#1#2{#1\\hskip5pt plus2ptminus2pt#2}%\n"
    "\\def\\and#1#2{\\unskip\\ -- #1\\hskip5pt plus2ptminus2pt#2}%\n"
    "\\def\\PACS#1{\\gdef\\@PACS{#1}}\n"
    "\\def\\@@PACS{\\par\\addvspace\\baselineskip\\noindent{\\sffamily\\bfseries\n"
    "PACS.\\enspace}\\ignorespaces\\expandafter\\pacsstart\\@PACS\\par}\n"
    "\\endinput\n"
)


def svjour_clo_stub(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""svjour.cls 零 .clo 伴船 → 按 ``\documentclass`` 选项写 ``sv<opt>.clo`` stub。

    实证根因 (0905.0193): e-print 捆绑 svjour.cls (2003, Springer) 但不带
    任何 .clo, TeX Live 亦不收录 svjour → ``\DeclareOption*`` 里
    ``\InputIfFileExists{sv\CurrentOption.clo}`` 逐选项落空,
    ``\journalopt`` 停在 ``\@empty`` → ``\ClassError{No valid journal
    specified}`` + ``\stop``。stub 让 InputIfFileExists 走真臂置
    ``\journalopt`` 为选项名即过; 盘上已有真 .clo 不覆盖。
    stub 体 = ``_SVJOUR_CLO_BODY`` (noop + size-family 播种)。
    """
    del eng, payload, params
    main = ctx.main_path()
    t = ctx.read(main) if main is not None else None
    if t is None:
        return False, "no main tex"
    vis = mask_tex(t)  # 注释掉的 %\documentclass 的选项不得入 stub 表
    if not DOCCLASS_OPTS_RX.search(vis):
        return False, "no \\documentclass in main"
    opts = [
        o.strip()
        for m in DOCCLASS_OPTS_RX.finditer(vis)
        for o in (m.group(1) or "").split(",")
        if o.strip()
    ]
    if not opts:
        return False, "no documentclass options"
    written = []
    body = _SVJOUR_CLO_BODY
    for opt in dict.fromkeys(opts):
        if "/" in opt or "\\" in opt:
            continue  # 防选项里的路径分隔符穿出 wdir / write_text 炸 OSError
        target = _resolve_site(ctx, PurePosixPath(f"sv{opt}.clo"))
        if target is None:
            continue  # main_rel 怪径逃出 wdir —— 不落件也不炸
        # 指纹闸：外来 .clo (稿自带) 永不覆写; 旧代注入件覆写刷新。
        done, _state = _inject_write(ctx, target, body, target.name)
        if done is not None:
            continue
        written.append(target.name)
    if not written:
        return False, "all sv*.clo already present, nothing written"
    return True, f"svjour .clo stubs written: {', '.join(written)}"


#: AAS 期刊缩写宏表 —— emulateapj.cls L1201-1256 ``\ref@jnl`` 全表抄录
#: (去壳成纯文本展开)。实证锚点：tectonic bundle 内置 aastex 5.0rc3.1 (1999)
#: 没有这批宏，老 aastex 文档 \bibitem 里的 ``\actaa`` 族全成 undefined_cs
#: (1806.06690 tectonic 臂)。\providecommand 语义：类里已有定义时不覆盖。
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
    if main is None or t is None:
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
    if not target or not body:
        return False, f"{payload} not in bundle-shadow set"
    if not cs or cs not in cs_set:
        return False, f"{payload} not in bundle-shadow set"
    missing = _install_needs(ctx, eng, params.get("needs"))
    # 指纹闸：稿自带同名件不覆写; 旧代注入件覆写刷新。
    ok, note = _inject_named(
        ctx,
        PurePosixPath(str(target)),
        str(body),
        f"shadow {target}",
        why=f"\\{cs} missing from bundled class",
    )
    if ok and missing:
        note += f"; deps still missing: {', '.join(missing)}"
    return ok, note


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


# ═══ 209→revtex4-2 升级稿面 polyfill (revtex209_surface/revtex_pacs 13 格) ═══

#: latex209 ``upgrade_209`` 落盘的 COMPAT_SHIM 首行面包屑——该串唯一出处
#: 即 latex209.py 兼容垫块，字面在 = 209 升级跑过。它本身是注释行 (遮盖
#: 视图遮没), 只能在原文判。
_209_SHIM_MARK = "% texlate: LaTeX 2.09 compatibility shim"

#: live ``\documentclass{revtex4-2}``——遮盖视图定位 + span 逐段复核
#: (``_live_matches``): 注释/verbatim 内假装载不锚; ``{revtex4}``/
#: ``{revtex4-1}`` 邻名不中。
_REVTEX42_DOCCLASS_RE = re.compile(
    r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{\s*revtex4-2\s*\}"
)

#: 注入面——与 ``vendor/shims/revtex.cls`` 替身 stub 面同义
#: (90-shim-legacy.yaml ``shim_map.revtex.cls`` 槽已删：vendored 先中),
#: 剥去 cls 装载件 (``\LoadClassWithOptions`` 已由升级稿 docclass 行完成),
#: 补 exact-restore @=11 包装 (``_AT_LETTER_*``: ``\edef`` 存现值→=11 读
#: →复元; @=letter 宿主恒等，裸 ``\makeatletter`` 对会把 letter 宿主
#: 尾段强翻回 12 —— 1803.02902 csfix 串实证)。
#: ``\AtBeginDocument`` 参数内用单 ``#1``——hook 逐字存 token、
#: ``\begin{document}`` 时才执行内层 ``\def``; ``##`` 只用于 def 嵌 def
#: 的替换文本，此处的 ``\def\pacs`` 不嵌在任何 def 里，双写会字面留下
#: ``##`` 炸 "Parameters must be numbered consecutively" (guardsmoke
#: 两格实证，2026-09-18)。
_REVTEX209_POLYFILL = (
    "% fixloop: revtex 2.09 surface polyfill (upgraded doc on revtex4-2)\n"
    + _AT_LETTER_PRE
    + "\n\\frontmatter@init\n"
    "\\let\\frontmatter@init\\relax\n"
    # ``\twocolumn``/``\@makecol``/``\pacs`` 三行共享负载核单源在
    # latex209.REVTEX209_CORE (``_REVTEX209_SHIM`` 同引) —— 行内
    # ``\long\def``/单 ``#1`` 契约注记见彼侧。
     + REVTEX209_CORE + _AT_LETTER_POST
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
    ``\pacs`` 在 ``\maketitle`` 后 ClassError (cls:2530)。corpus 13 格
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
