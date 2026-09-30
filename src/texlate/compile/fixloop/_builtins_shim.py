r"""_builtins_shim — stub/遮蔽/polyfill 注入原语 (C3 拆分)。

往 wdir/主文件注入新件或 prologue, 或把位错稿自带件归位到解析位
(fileset_relocate/driver_tfm_hoist): 退役包 cls/sty stub (legacy_pkg_shim) /
svjour .clo noop stub / pdfTeX 读取原语 polyfill / 期刊宏 ``\\providecommand``
整表注入 / 引擎 bundle 内建类遮蔽 stub; ``shim_pkgs_in_use`` 是 shim_map
键的工程在用量查询 (engine shim_known 条件实现)。
"""

from __future__ import annotations

import re
import shutil
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast

from texlate.compile.fixloop._builtins_common import (
    _AT_LETTER_POST,
    _AT_LETTER_PRE,
    _FB_FONT,
    _MATH_SHIM_CS,
    PDFTEX_PRIMS,
    _fb_font_body,
    _fb_preamble_lines,
    _fixloop_log,
    _in_wdir,
    _inject_after_docclass,
    _inject_before_begindoc,
    _inject_write,
    _is_live,
    _live_matches,
    _mc_chr,
    _mc_seen,
    _mc_table,
    _resolve_site,
    _wdir_project_files,
)
from texlate.compile.fixloop._builtins_csfix import _ensure_usepackage
from texlate.compile.latex209 import REVTEX209_CORE
from texlate.latex.tables import MATH_ENVS
from texlate.textutil import DOCCLASS_OPTS_RX, mask_tex, safe_is_file, safe_rel

if TYPE_CHECKING:
    from collections.abc import Iterable

    from texlate.compile.fixloop.engine import Engine, LoopCtx


#: 整数值 pdfTeX 原语 (寄存器形) —— ``\newcount`` polyfill 全真接管:
#: 赋值型 ``\prim=val`` 落成合法寄存器赋值并保作者意图值, 读取型
#: ``\ifnum\prim`` 读初值 1 与旧 ``\chardef=1`` 同义。集合外原语分
#: 三路: 取参族 ``\pdfobj`` 系走 ``_PRIM_ARGFUL`` 吞参 noop, toks/
#: dimen 寄存器各走 ``\newtoks``/``\newdimen`` (下两表), 余项
#: (``\pdfstrcmp`` 展开族等) 留 ``\chardef`` 旧形。primofw 车道实证:
#: ``\chardef\pdfcompresslevel`` + axessibility.sty:349 裸写
#: ``\pdfcompresslevel=0`` → chardef cs 变排版字符 + ``=0`` 文本,
#: Missing \begin{document} 转嫁错类; ``\newcount`` 同点合法过编译。
_PRIM_COUNTISH = frozenset(
    {
        # 可赋整型参数 (write-form \prim=val)
        "pdfoutput",
        "pdfminorversion",
        "pdfoptionpdfminorversion",
        "pdfcompresslevel",
        "pdfobjcompresslevel",
        "pdfgentounicode",
        "pdfsuppressptexinfo",
        "pdfadjustspacing",
        "pdfprotrudechars",
        "pdftracingfonts",
        "pdfdecimaldigits",
        "pdfinclusionerrorlevel",
        # 2403.15085: \pdfinclusioncopyfonts=1 docclass 前写形 —— guard 表
        # 扩名后整站包裹; 读形 (\ifnum) 归 count 寄存器臂全真接管
        "pdfinclusioncopyfonts",
        "pdfsuppresswarningpagegroup",
        "pdfdraftmode",
        # 只读整数面 (\ifnum/\the 读取, 寄存器语义一致)
        "pdflastxpos",
        "pdflastypos",
        "pdflastobj",
        "pdflastxform",
        "pdflastximage",
        "pdflastannot",
        "pdffontobjnum",
        "pdfpageref",
        "pdftexversion",
        "pdfrandomseed",
        "pdfelapsedtime",
        "pdffilesize",
        # `pdf@` 包内别名族的寄存器形成员 (镜像同名裸原语的整数语义)
        "pdf@draftmode",
        "pdf@inclusionerrorlevel",
        "pdf@lastxpos",
        "pdf@lastypos",
        "pdf@lastxform",
        "pdf@lastximage",
    }
)

#: toks 寄存器形原语 —— ``\newtoks`` 全真接管: ``\prim={...}`` 写型与
#: ``\the\prim`` 读型皆合法 (spotcolor.sty:48 ``\edef\act{\noexpand
#: \pdfpageresources={\the\pdfpageresources...}}`` 双形态同句实证;
#: chardef 下 ``\the`` 读出 char code、``={..}`` 整串落正文)。
_PRIM_TOKSISH = frozenset(
    {
        "pdfpageresources",
        "pdfpageattr",
        "pdfpagesattr",
        # `pdf@` 族 toks 寄存器 (pdfmark.def 系 ``\pdf@toks={..}`` 写形)
        "pdf@toks",
        "pdf@defaulttoks",
    }
)

#: dimen 寄存器形原语 —— ``\newdimen`` 全真接管 (``\prim=210mm`` 对
#: ``\newcount`` 是非法单位、对 ``\newdimen`` 全真)。pdfpagewidth/
#: pdfpageheight xetex 原生已定义, ``\ifdefined`` 闸自然跳过不误伤。
_PRIM_DIMENISH = frozenset(
    {"pdfpagewidth", "pdfpageheight", "pdfhorigin", "pdfvorigin", "pdfpxdimen"}
)

#: box 寄存器形原语 —— ``\newbox`` 全真接管 (``\sbox\<prim>{..}``/
#: ``\setbox\<prim>=``/``\wd\<prim>`` 各面合法)。2502.03387 colm 实证:
#: breakurl.sty:149 ``\sbox\pdf@box`` 在 pdftex 下自导绑定, xelatex 全缺;
#: chardef 下 ``\sbox`` 读不到 box 号 → Missing number 转嫁错类。
_PRIM_BOXISH = frozenset({"pdf@box"})

#: count 寄存器初值 —— 缺省 ``=1`` (读型 ``\ifnum\<prim>`` 与旧 chardef
#: 同义)。``pdfoutput=0`` 有意为之: 存在探针 ``\ifx\pdfoutput\undefined``
#: 定义即翻 else 臂 (0712.1016 自产缺陷: polyfill=1 把 texmf 内不可改写
#: 的存在探针全翻成 pdftex 臂 → hyperref[pdftex] xetex GenericError);
#: 值探针 ``\ifnum\pdfoutput>0`` 在 ``=0`` 下保持诚实假 —— 「非 pdfTeX」
#: 是 xelatex 下两种探针的一致回答。``pdftexversion=140`` 对齐 TeX Live
#: 2025 pdftex 1.40.x: 缺省 1 会把 ``\ifnum\pdftexversion<120`` 版本探针
#: 翻成真臂 (microtype 系版本闸静默退役; 0812.1138 docsty 实证受害)。
_PRIM_INIT: dict[str, str] = {"pdfoutput": "0", "pdftexversion": "140"}

#: 取参型原语 —— ``\protected\def`` 吞参 noop (prim → 参数文本):
#: ``\prim{dict}``/``\prim<num>``/``\prim\<reg>`` 站点在 chardef 下实参
#: 落成排版文本 (``\pdfobj{<</...>>}`` 整个 PDF 字典进正文)。实证锚点:
#: spotcolor.sty:34-62 ``\pdfobj{dict}``/``\pdfrefobj\thecolorprofile``/
#: ``\pdfliteral{op}`` (1907.10410/2410.00012 ieeeaccess 族, guard 包不
#: 到 ``\prim\cs`` 无花括号形)。参数文本按原语签名主导形给足: 单参
#: ``#1`` 吞花括号组或单 token, 双参 ``#1#2``, 零参 ``""``; 多 token
#: 关键字形 (``\pdfobj stream``/``\pdfdest name{..}``) 只吞首字符, 残
#: 字母降级为排版噪声 —— 仍不劣于 chardef 整串残留。``@iffalse`` 哨兵:
#: 条件原语 ``\let→\iffalse`` 走 else 臂保 ``\fi`` 配对完整 (xelatex
#: 实测: ``\pdfifprimitive\cs T\else F\fi`` → F 臂); csname 双写形是
#: 跳扫安全必需 —— 裸 ``\let\prim\iffalse`` 在 ``\ifdefined`` 真臂跳扫
#: 下被计成两个 if-token 吃掉 ``\fi``。``\protected`` 保 ``\edef``/
#: ``\write`` 语境不提前展开 (luatex85 同形惯例)。
_PRIM_ARGFUL: dict[str, str] = {
    # 对象/表单/图像 (void 输出原语, ``{dict}``/``<num>``/``{file}`` 主导形)
    "pdfobj": "#1",
    "pdfrefobj": "#1",
    "pdfxform": "#1",
    "pdfrefxform": "#1",
    "pdfximage": "#1",
    "pdfrefximage": "#1",
    # 注释/链接/书签/目录资源
    "pdfannot": "#1",
    "pdfdest": "#1",
    "pdflink": "#1",
    "pdfstartlink": "#1",
    "pdfoutline": "#1",
    "pdfcatalog": "#1",
    "pdfnames": "#1",
    "pdfinfo": "#1",
    "pdftrailer": "#1",
    # 文字流/色彩栈/字体映射
    "pdfliteral": "#1",
    "pdfcolorstack": "#1",
    "pdfcolorstackinit": "#1",
    "pdfmapfile": "#1",
    "pdfmapline": "#1",
    # 双参面: {name}{code} / <font>{chars} / {pat}{str}
    "pdfglyphtounicode": "#1#2",
    "pdfincludechars": "#1#2",
    "pdfmatch": "#1#2",
    # 单参展开族 ({..}/<cs>/<num>/<font> 一参吞)
    "pdfprimitive": "#1",
    "pdfescapestring": "#1",
    "pdfescapename": "#1",
    "pdfescapehex": "#1",
    "pdfunescapehex": "#1",
    "pdffilemoddate": "#1",
    "pdffiledump": "#1",
    "pdfmdfivesum": "#1",
    "pdflastmatch": "#1",
    "pdffontname": "#1",
    "pdffontsize": "#1",
    "pdfuniformdeviate": "#1",
    "pdfnormaldeviate": "#1",
    # 零参面 (void/no-op 原语)
    "pdfsavepos": "",
    "pdfendlink": "",
    "pdfresettimer": "",
    "pdfcreationdate": "",
    # 条件原语 —— ``\let→\iffalse`` 哨兵 (非 ``\def`` 形)
    "pdfifprimitive": "@iffalse",
    # `pdf@` 包内别名族 —— 形参镜像同名裸原语签名; 未知 arity 一律
    # ``#1`` 吞单 token/花括号组 (pdftexcmds/pdfmark 系成员多是带参宏)。
    "pdf@addtoks": "#1",
    "pdf@addtoksx": "#1",
    "pdf@docset": "#1",
    "pdf@linktype": "#1",
    "pdf@majorminor": "#1",
    "pdf@objdef": "#1",
    "pdf@rect": "#1",
    "pdf@type": "#1",
    "pdf@xform": "#1",
    "pdf@refxform": "#1",
    "pdf@ximage": "#1",
    "pdf@refximage": "#1",
    "pdf@escapestring": "#1",
    "pdf@escapename": "#1",
    "pdf@escapehex": "#1",
    "pdf@unescapehex": "#1",
    "pdf@filemoddate": "#1",
    "pdf@filedump": "#1",
    "pdf@filesize": "#1",
    "pdf@mdfivesum": "#1",
    "pdf@pageref": "#1",
    "pdf@lastmatch": "#1",
    "pdf@strcmp": "#1#2",
    "pdf@match": "#1#2",
    "pdf@ifdraftmode": "@iffalse",
}


#: ``\@ifdefinable`` 系定义位扫描 —— doc 侧已有活 ``\newX\<prim>``/
#: ``\newcommand{\<prim>}`` 定义时头注 ``\newcount`` 会把稿自带定义位
#: 撞成 already-defined 错 (守卫内嵌语义的逆风险: 注入先行于稿内定义位
#: 执行, 稿内 ``\newcount\pdfoutput`` 撞我们注的寄存器)。``\def``/``\let``/
#: ``\edef``/``\chardef``/``\countdef`` 重绑无 already-defined 闸不收 —
#: 稿自带死定义位撞名只是无声覆盖, 拒注反而丢真修。``renewcommand``/
#: ``providecommand`` 对未定义名不报错也不拒 (前者本就要求已定义)。
_PRIM_ALLOC_DEF_RE = (
    r"\\(?:newcount|newdimen|newtoks|newbox|newskip|newmuskip|newread|"
    r"newwrite|newlength|newsavebox|newif|newcommand|newenvironment|"
    r"DeclareRobustCommand|newrobustcmd|DeclareTextCommand|DeclareMathSymbol)"
    r"\s*\*?\s*\{?\s*\\"
)


def _prim_alloc_defined(prim: str, t: str) -> bool:
    r"""遮盖视图内存在 ``\\<alloc>\<prim>`` 活定义位 → True (拒注入)。"""
    pat = _PRIM_ALLOC_DEF_RE + re.escape(prim) + r"(?![a-zA-Z@])"
    return re.search(pat, mask_tex(t)) is not None


def _prim_guard_text(prim: str) -> str:
    r"""Payload prim → ``\\ifdefined\\<prim>\\else<def形>\\fi`` 守卫文本。

    分派: countish ``\\newcount\\{prim}={_PRIM_INIT|1}`` / toksish
    ``\\newtoks`` / dimenish ``\\newdimen`` / boxish ``\\newbox`` / argful
    ``\\protected\\def<sig>`` (``@iffalse`` 哨兵→csname-let ``\\iffalse``) /
    余项 ``\\chardef=1``。
    """
    if prim in _PRIM_COUNTISH:
        init = _PRIM_INIT.get(prim, "1")
        body = f"\\newcount\\{prim}\\{prim}={init}"
    elif prim in _PRIM_TOKSISH:
        body = f"\\newtoks\\{prim}"
    elif prim in _PRIM_DIMENISH:
        body = f"\\newdimen\\{prim}"
    elif prim in _PRIM_BOXISH:
        body = f"\\newbox\\{prim}"
    elif (sig := _PRIM_ARGFUL.get(prim)) is None:
        body = f"\\chardef\\{prim}=1"
    elif sig == "@iffalse":  # 条件原语: 绑 \iffalse 走 else 臂
        # csname 双写裸 \let 不可用: \ifdefined 真臂时 else 臂被跳过,
        # 跳扫把裸 \prim(已定义为 if 类)/\iffalse 计入嵌套 → \fi 被吃成
        # Incomplete \ifdefined (primarg 探针 skip1 实测); csname 形
        # 跳扫面全是非条件 token, 执行面 \expandafter 链正确绑
        # (skip2/skip3 双路实测: 定义路径过扫, 未定义路径绑 iff→else)。
        body = (
            f"\\expandafter\\let\\csname {prim}\\expandafter\\endcsname"
            f"\\csname iffalse\\endcsname"
        )
    elif sig:
        body = f"\\protected\\long\\def\\{prim}{sig}{{}}"
    else:
        body = f"\\protected\\def\\{prim}{{}}"  # 零参原语
    return f"\\ifdefined\\{prim}\\else{body}\\fi"


def pdftex_prim_polyfill(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""对 pdfTeX 原语补定义: ``\\ifdefined\\<prim>\\else<形>\\<prim>\\fi``。

    guard 规则只管 ``\\pdfX=val``/``\\pdfX{..}`` 赋值型且在 fileset 内;
    ``\\ifnum\\pdfoutput`` 读取型、``\\pdfrefobj\\<reg>`` 无花括号取参型
    与 fileset 外 (系统 texmf sty/cls) 站点都要原语已定义 (docs/spec/compile.md
    + verifymiss axessibility.sty:349 实证)。臂按原语签名分派:
    整数值原语 (``_PRIM_COUNTISH``) 走 ``\\newcount`` —— 赋值型站点
    ``\\prim=val`` 全真接管, 初值查 ``_PRIM_INIT`` (``pdfoutput=0``:
    值探针 ``\\ifnum\\pdfoutput>0`` 诚实假, 存在探针定义即翻的坑由
    pdftex_gate_collapse 先塌); toks/dimen/box 寄存器各走 ``\\newtoks``/
    ``\\newdimen``/``\\newbox``; 取参族 (``_PRIM_ARGFUL``) 走
    ``\\protected\\def\\<prim><sig>{}`` 吞参 noop —— 实参按主导形消费,
    不落排版文本; 余项留 ``\\chardef=1`` 旧形 (读取型兼容)。
    ``pdf@`` 别名族 (breakurl/pdfmark/pdftexcmds 系包内自导绑定, @=11
    包体语境限定) 注入文本裹 ``_AT_LETTER_PRE/POST`` exact-restore
    @=11 对 —— 裸 ``\ifdefined\pdf@box`` 在 @=12 宿主下读成 ``\ifdefined
    \pdf``+残字 ``@box``; ``\csname``/``\ifcsname`` 形不可用 (未定义名
    冻结成 ``\relax``, 后随 ``\@ifdefinable`` 闸的 ``\newbox``/``\newcount``
    报 already-defined)。注入点恒在主文件头——cls/sty 内部使用发生在
    ``\\documentclass`` 加载期间, 类行后注入太晚 (2410.00012:
    ieeeaccess.cls:128 内 ``\\pdfobj``); ``ifdefined`` 前缀天然幂等。
    """
    del eng  # 签名面统一; 注入发生在主文件源文本
    prim = str(params.get("prim") or payload or "")
    if prim not in PDFTEX_PRIMS:
        return False, f"{prim} not in pdfTeX prim list"
    guard = _prim_guard_text(prim)
    if "@" in prim:
        # @-名注入文本在任意宿主 catcode 下自证: exact-restore @=11 包裹
        # (restore 放 \fi 后, 两臂执行路径都复元 catcode); csname 形不可替
        # —— \ifcsname 把未定义名冻结成 \relax, \@ifdefinable 闸即炸。
        guard = _AT_LETTER_PRE + guard + _AT_LETTER_POST
    main = ctx.main_path()
    if main is None:
        return False, "no main tex"
    t = ctx.read(main) or ""
    if f"\\ifdefined\\{prim}" in t or f"\\ifcsname {prim}\\endcsname" in t:
        return False, f"{prim} already guarded"
    if _prim_alloc_defined(prim, t):
        return False, f"{prim} already defined"
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


def _safe_rel(name: str) -> PurePosixPath | None:
    """``payload`` 名 → ``PurePosixPath``; 空名/绝对路径/``..`` 段/NUL → ``None``。

    各注入/归位 builtin 统一的 payload 拒收口——非相对安全名一律 decline,
    绝不把 ``../x``/``/etc/x`` 写进 wdir。词法单源
    ``texlate.textutil.osutil.safe_rel`` (misc 叶经本件回引)。
    """
    return safe_rel(name)


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
    missing = _install_needs(ctx, eng, spec.get("needs"))
    # 指纹闸: 稿自带同名件不覆写; 旧代注入件覆写刷新。
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


#: ``svjour_clo_stub`` 写入体: 真 .clo 内嵌 size10.clo 复刻本
#: (corpus/1107.0209 svepj.clo:46-72 抄值, ``dd`` 归一为 ``pt``)。
#: 纯 ``\endinput`` noop 遮蔽真件 → size-family 永不播种,
#: ``\normalsize`` 停在 kernel error-stub (latex.ltx ``\@latex@error``)
#: → fontspec-xetex:443 / ctex:715 "font size command \normalsize is
#: not defined" (2505.06598 实证)。``\renewcommand`` 必要——kernel 预置
#: error-stub 视为已定义, ``\providecommand`` 不覆盖; 兄弟尺寸宏 kernel
#: 未预置, ``\providecommand`` 播了不撞稿自带真件序。
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
    # PACS 面: svepj.clo:224-225/254-256 抄值 (嵌套位 ## 归一为顶层 #);
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
    # 指纹闸: 稿自带同名件不覆写; 旧代注入件覆写刷新。
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
    rel = _safe_rel(fname)
    if rel is None:
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
    target = _resolve_site(ctx, rel)
    if target is None:
        return False, f"{fname}: escapes wdir"
    body = f"% fixloop: stub for runtime-generated {rel.name}\n"
    # 指纹闸: 外来生成件/稿自带覆盖层永不覆写; 旧代注入 stub 覆写刷新。
    done, _state = _inject_write(ctx, target, body, fname)
    if done is not None:
        # current/foreign/写败 —— 盘上已有(或写不进)则不占位, 交后续规则
        return False, done[1] if not done[0] else f"{fname} already on disk"
    return True, f"{hit}-stub {fname}"


# ════════════════════════════════════════════════════════════════
# 位错稿自带件归位 (failmine4-covgap: ifacconf/jmlr2e/fairmeta/acronyms1
# 4 格) —— e-print 有件但不在 TeX 解析位 (compile cwd = main_dir,
# 根部位件对子目录 main 不可见); install_file 探测 cwd=wdir 假命中
# → fired-unfixed。真件 verbatim 拷贝优于任何 stub/install。
# ════════════════════════════════════════════════════════════════

#: 编译自产瞬态件扩展名 —— 缺位是上游病灶信号 (2609.20323 main.aux =
#: unclosed ``\if`` 下游产物实证), 搬陈件会遮蔽真因, 不属「源档位错」面。
_RELOCATE_TRANSIENT_EXTS = frozenset(
    {
        ".aux",
        ".out",
        ".toc",
        ".lof",
        ".lot",
        ".bbl",
        ".blg",
        ".bcf",
        ".log",
        ".fls",
        ".nav",
        ".snm",
        ".vrb",
        ".idx",
        ".ind",
        ".ilg",
        ".glo",
        ".gls",
        ".acn",
        ".acr",
        ".xdy",
    }
)
#: 复合尾缀 (``suffix`` 只取末段, 按件名 endswitch 判)。
_RELOCATE_TRANSIENT_NAME_EXTS = (".run.xml", ".synctex.gz", ".fdb_latexmk")


def _is_transient_name(name: str, suffix: str) -> bool:
    """编译自产瞬态件判定 —— ``.aux``/``.bbl`` 族扩展名或复合尾缀命中即瞬态。

    瞬态缺位是上游病灶信号非源档位错, 搬陈件/stub 都遮蔽真因
    (``_RELOCATE_TRANSIENT_*`` 表注, 2609.20323 实证)。
    """
    return suffix.lower() in _RELOCATE_TRANSIENT_EXTS or name.lower().endswith(
        _RELOCATE_TRANSIENT_NAME_EXTS
    )


def _find_relocate_src(ctx: LoopCtx, rel: PurePosixPath) -> Path | None:
    r"""定位位错真身 —— wdir 内后缀路径匹配优先, basename 兜底, 浅者优先。

    ``**/payload`` 形命中 (如 payload ``templates/arxiv/fairmeta.cls`` 对
    深层同名位) 高于裸 basename; dot 段路径 (``./.git``/``.texmf`` 类)
    与引擎树 (``_texmf``/``_tect_out``) 剔除 —— 工程件不住隐藏目录与
    引擎封装树。多命中取 (rank, 深度, 路径) 最小者, 确定性排序。
    """
    want_tail = tuple(p.lower() for p in rel.parts)
    base = rel.name.lower()
    cands: list[tuple[int, int, str, Path]] = []
    for p, parts in _wdir_project_files(ctx):
        pl = tuple(part.lower() for part in parts)
        if pl[-len(want_tail) :] == want_tail:
            rank = 0
        elif p.name.lower() == base:
            rank = 1
        else:
            continue
        cands.append((rank, len(parts), str(p), p))
    if not cands:
        return None
    return min(cands, key=lambda t: t[:3])[3]


def fileset_relocate(  # noqa: PLR0911 - 逐门 decline note 即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""稿自带件在 wdir 但不在 TeX 解析位 → 逐字节拷贝到 ``<main_dir>/<payload>``。

    机理 (failmine4-covgap 4 格实证): e-print 把 ``\documentclass``/
    ``\input``/``\includegraphics`` 目标件放工程根, main 却住子目录
    (``Artigo/sbaconf.tex``/``sections/00_preamble.tex``/``IEEEtran/main.tex``
    形) —— 编译 cwd = ``main_path().parent`` 且无 TEXINPUTS 根注入,
    payload 按 cwd 解析 → missing_file/missing_graphic。``install_file``
    探测以 wdir 为 cwd 假命中、filemap 亦无收录 (ifacconf/jmlr2e 实测
    tlpdb 零命中) → fired-unfixed。修复不是装包而是归位: 目标
    ``<main_dir>/<payload>`` (TeX 实际解析位), 源序 ``wdir/<payload>``
    → ``_find_relocate_src`` rglob。序在 order:9 族首 —— 真件内容面
    即 e-print 钦定, rungen_stub/docstrip 让位。

    守卫: payload 非绝对/无 ``..``/无 ``\x00``; main 未知 → False
    (解析位不可定); 目标已在 → False (payload 可达, 缺件另有真因);
    瞬态扩展名 (``.aux/.bbl/.toc``…) 不搬 —— 编译自产件缺位是上游
    病灶信号非源档问题, 搬陈件遮蔽真因; 源目标同路径 → False。
    """
    del eng, params
    fname = (payload or "").strip().strip("'\"")
    rel = _safe_rel(fname)
    if rel is None:
        return False, f"unsafe relocate name {fname!r}"
    if _is_transient_name(rel.name, rel.suffix):
        return False, f"{fname}: transient artifact — not a source file"
    mp = ctx.main_path()
    if mp is None:
        return False, f"{fname}: main unknown — resolve site undetermined"
    target = mp.parent / Path(*rel.parts)
    if not _in_wdir(ctx, target):
        return False, f"{fname}: escapes wdir"
    if safe_is_file(target):
        return False, f"{fname}: already at resolve site"
    src = ctx.wdir / Path(*rel.parts)
    if not safe_is_file(src) or src.resolve() == target.resolve():
        src = _find_relocate_src(ctx, rel)
    if src is None or src.resolve() == target.resolve():
        return False, f"{fname}: not present in fileset"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        ctx.invalidate(target)
    except OSError as e:
        return False, f"{fname}: copy failed ({e})"
    src_rel = src.relative_to(ctx.wdir).as_posix()
    dst_rel = target.relative_to(ctx.wdir).as_posix()
    n_tree = _mirror_relocate_tree(ctx, rel, mp.parent, target)
    note = f"relocated {src_rel} → {dst_rel}"
    if n_tree:
        note += f" (+{n_tree} tree files)"
    return True, note


def _mirror_tree_skip(
    p: Path, pparts: tuple[str, ...], dst_top_res: Path, target_res: Path
) -> bool:
    """镜像源件逐项跳闸 —— 瞬态件/dot 段/目标自身/已处归位树内 (防递归)。"""
    if any(part.startswith(".") for part in pparts):
        return True
    if _is_transient_name(p.name, p.suffix):
        return True
    pres = p.resolve()
    if pres == target_res:
        return True
    try:
        pres.relative_to(dst_top_res)
    except ValueError:
        return False
    return True  # 已处归位树内 (嵌套镜像副本) —— 防 top/top/top 递归


def _mirror_relocate_tree(
    ctx: LoopCtx, rel: PurePosixPath, main_dir: Path, target: Path
) -> int:
    """Payload 顶层目录在 wdir 根成树 → 整树镜像到 ``<main_dir>/<top>/``。

    doc 按 e-print 坐标引用同前缀整族件 (``Content/a.tex``/``Content/b.tex``
    轮轮各缺一件) —— 逐轮一件归位烧轮次 (2609.20640 单件/轮 ×8 实证)。
    首个 payload 归位成功后同树镜像一次铺全; ``main_dir`` 与 ``<top>``
    同径时源恒在目标树下 → 全员跳过, 天然幂等。
    """
    if not rel.parent.parts:
        return 0
    top = rel.parts[0]
    src_top = ctx.wdir / top
    dst_top = main_dir / top
    if not src_top.is_dir() or src_top.resolve() == dst_top.resolve():
        return 0
    if not _in_wdir(ctx, dst_top):
        return 0
    dst_top_res = dst_top.resolve()
    target_res = target.resolve()
    n = 0
    for p in sorted(src_top.rglob("*")):
        if not safe_is_file(p):
            continue
        pparts = p.relative_to(ctx.wdir).parts
        if _mirror_tree_skip(p, pparts, dst_top_res, target_res):
            continue
        dst = dst_top / Path(*pparts[1:])
        if safe_is_file(dst):
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
            ctx.invalidate(dst)
            n += 1
        except OSError:
            continue
    return n


def driver_tfm_hoist(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``Unable to find TFM file "X"`` → 子目录稿自带 ``*.tfm`` 提升到扁平解析位。

    机理 (2606.02800 nvidiatechreport.cls / 2504.05118 bytedance_seed.cls
    residchk 面): 私有字体 e-print 自带 ``.tfm`` 在子目录 —— TeX 侧经
    路径限定字体名 (``\\DeclareFontShape`` ``seed/bytesans`` 形) 找得到;
    下游驱动 (xdvipdfmx 等) 按 ``\\pdfmapline`` 裸名走 TFMFONTS 查找,
    只认 ``.`` = compile cwd (``main_dir``) 的扁平位, 子目录够不到 →
    ``*: fatal:``。私有件非 CTAN → install_tfm filemap 必 miss, 归位
    是唯一真修。payload 触发名定位 font 目录后同目录 ``*.tfm`` 全量
    hoist (nvidia 7/seed 2 —— 逐轮单件烧轮次, 同 relocate tree-mirror
    教训); ``\\pdfmapline`` 的 ``.ttf`` 路径限定引用本来可达, 不搬。

    守卫同 relocate 系: payload 无 ``/`` ``\\`` ``..`` ``\\x00`` 非点前缀;
    main 未知 → False; ``{payload}.tfm`` 已扁平在解析位 → False (缺件
    另有真因); fileset 无同名 → False; 目标名已占逐件跳 (幂等复火)。
    """
    del eng, params
    name = (payload or "").strip().strip("'\"")
    if (
        not name
        or name.startswith(".")
        or any(tok in name for tok in ("/", "\\", "..", "\x00"))
    ):
        return False, f"unsafe tfm name {name!r}"
    mp = ctx.main_path()
    if mp is None:
        return False, "main unknown — driver resolve site undetermined"
    dst_dir = mp.parent
    dst_res = dst_dir.resolve()
    want = f"{name}.tfm"
    if safe_is_file(dst_dir / want):
        return False, f"{want}: already at driver resolve site"
    hits = [
        p
        for p, _parts in sorted(_wdir_project_files(ctx))
        if fnmatchcase(p.name, want) and p.parent.resolve() != dst_res
    ]
    if not hits:
        return False, f"{want}: not present in fileset"
    src_dir = hits[0].parent
    hoisted = []
    for src in sorted(src_dir.glob("*.tfm")):
        if not safe_is_file(src):
            continue
        target = dst_dir / src.name
        if safe_is_file(target):
            continue
        try:
            shutil.copyfile(src, target)
            ctx.invalidate(target)
        except OSError:
            continue
        hoisted.append(src.name)
    if not hoisted:
        return False, f"{name}.tfm: all resolve-site targets occupied"
    dst_rel = dst_dir.relative_to(ctx.wdir).as_posix()
    return True, f"hoisted {len(hoisted)} tfm → {dst_rel}: {', '.join(hoisted)}"


# ════════════════════════════════════════════════════════════════
# doc 引用但 e-print 未带的 .tex 片段 (m1kcensus2 衍生, covgap-C #205
# 复核): fileset 真无件 + filemap/vendor 无供 → 版本缀 sibling 搬真件,
# 否则解析位空 stub —— 丢该 \input 段保其余, 优于整格 unfixable。
# ════════════════════════════════════════════════════════════════

#: stem 尾部版本缀剥离形 —— ``12step_dynamics_new``→``12step_dynamics``
#: (2210.03294: doc 活引用 ``_new`` 件, e-print 只带改名件)。
_DOCABSENT_SUFFIX_RE = re.compile(
    r"^(?P<base>.+?)[_-](?:new|old|orig|final|draft|updated?|backup|bak|v\d+)$",
    re.IGNORECASE,
)
#: stem 加缀候选 —— doc 引旧名 e-print 带改名新件的反向漂移。
_DOCABSENT_SUFFIXES = ("_new", "_old", "_final", "_draft", "-new", "-old", "_v2", "_v1")


def _docabsent_sibling(ctx: LoopCtx, rel: PurePosixPath) -> Path | None:
    """Payload stem ± 版本缀的同目录唯一命中件 → 搬真件候选。

    搜索域 = ``wdir/<rel.parent>`` (e-print 坐标下同目录 —— sibling 语义
    即「引用件应在的位置的旁枝」)。剥缀形与加缀形双向候选, 同名件按
    文件名去重; 唯一文件名才返回 —— 多异名命中 = 版本族并存, 择一
    搬运是猜, 让位空 stub。
    """
    stems = {rel.stem}
    if m := _DOCABSENT_SUFFIX_RE.match(rel.stem):
        stems.add(m.group("base"))
    stems.update(rel.stem + s for s in _DOCABSENT_SUFFIXES)
    stems.discard(rel.stem)  # 同名件归 relocate/fileset —— 这里只看漂移形
    if not stems:
        return None
    base_dir = ctx.wdir / Path(*rel.parent.parts) if rel.parent.parts else ctx.wdir
    if not base_dir.is_dir():
        return None
    hits: dict[str, Path] = {}
    for p in base_dir.iterdir():
        if (
            safe_is_file(p)
            and p.suffix.lower() == rel.suffix.lower()
            and p.stem in stems
        ):
            hits.setdefault(p.name, p)
    if len(hits) != 1:
        return None
    return next(iter(hits.values()))


def doc_absent_stub(  # noqa: PLR0911 - 逐门 decline note 即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Doc 引用但 e-print 未带的 .tex → 版本缀 sibling 搬真件, 否则空 stub。

    机理 (m1kcensus2, covgap-C #205 逐格复核): ``\input``/``\include``
    目标在 e-print 里根本不存在 (作者本地件未打包/改名漂移) ——
    relocate 够不到 (fileset 无件), install/vendored/shim 亦无供
    (非 CTAN 件)。序在全真件臂后 (``pst-tools.tex`` 实证 .tex payload
    可以是真 CTAN 件, stub 必须是缺席实锤后的末位兜底)。

    两臂: (a) ``_docabsent_sibling`` 版本缀漂移唯一命中搬真件到解析位
    (真内容优于 stub); (b) 空 stub 落 ``_resolve_site`` —— 丢该
    ``\input`` 段保其余, 优于整格 unfixable。闸: 非 .tex 扩展名让位
    (.cls/.sty 走 install/shim 域); 瞬态件拒 (.aux/.bbl 缺位 = 上游
    病灶信号, stub 遮蔽真因 —— 2609.20323 main.aux 裁决沿); fileset
    内有同名件 → False (relocate 域防御性复核, dispatch 序漂移时仍
    安全); 外来同名件指纹闸不覆写。
    """
    del eng
    fname = (payload or "").strip().strip("'\"")
    rel = _safe_rel(fname)
    if rel is None:
        return False, f"unsafe stub name {fname!r}"
    if _is_transient_name(rel.name, rel.suffix):
        return False, f"{fname}: transient artifact — not a source file"
    exts = {str(e).lower() for e in (params.get("exts") or (".tex",))}
    if rel.suffix.lower() not in exts:
        return False, f"{fname}: not a doc-fragment ext"
    target = _resolve_site(ctx, rel)
    if target is None:
        return False, f"{fname}: escapes wdir"
    if safe_is_file(ctx.wdir / Path(*rel.parts)) or (
        _find_relocate_src(ctx, rel) is not None
    ):
        return False, f"{fname}: present in fileset — relocate domain"
    sib = _docabsent_sibling(ctx, rel)
    if sib is not None and sib.resolve() != target.resolve():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sib, target)
            ctx.invalidate(target)
        except OSError as e:
            return False, f"{fname}: sibling copy failed ({e})"
        s_rel = sib.relative_to(ctx.wdir).as_posix()
        d_rel = target.relative_to(ctx.wdir).as_posix()
        return True, f"rename-rescue {s_rel} → {d_rel}"
    body = f"% fixloop: doc-absent stub for {rel.name}\n"
    # 指纹闸: 外来件/稿自带件永不覆写; 旧代注入 stub 覆写刷新。
    done, _state = _inject_write(ctx, target, body, fname)
    if done is not None:
        # current/foreign/写败 —— 盘上已有(或写不进)则不占位, 交后续规则
        return False, done[1] if not done[0] else f"{fname} already on disk"
    return True, f"doc-absent stub {fname}"


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
        if not _is_live(m, masked, t):
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


def _serve_env_pkg_map(
    ctx: LoopCtx,
    eng: Engine,
    proven: set[str],
    pkg_map: dict[str, Any],
) -> tuple[set[str], list[str]]:
    """env→pkg 臂: 表内 proven env 装真包/注 polyfill → (served, notes)。"""
    notes: list[str] = []
    served: set[str] = set()
    for e in sorted(proven & set(pkg_map)):
        spec = pkg_map.get(e) or {}
        dones: list[str] = []
        if use := spec.get("usepackage"):
            dones.extend(_ensure_usepackage(ctx, eng, str(use)))
        if spec.get("polyfill") and _inject_after_docclass(ctx, str(spec["polyfill"])):
            dones.append("pkg polyfill injected")
        if dones:
            notes.append(f"{e}→pkg {'; '.join(dones)}")
            served.add(e)
    return served, notes


def undefined_env_polyfill(  # noqa: C901  # pkg_map/站点/对偶件/批扩多臂 dispatcher
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

    env→pkg 臂 (``params.pkg_map``, 1306.0281 tikzpicture 族): 表内
    proven env 装真包替代 noop —— noop 吞整个图体且体内 pgf cs
    (``\node``/``\draw``/``\addplot``) 连锁 undefined_cs 白烧轮次,
    cs_table 无对应条目者 (axis/tikzcd) 更是唯一活路。spec 复用
    cs_targeted_fix 键形: ``usepackage`` 走 ``_ensure_usepackage``
    (注入+装文件); ``polyfill`` 注 docclass 缝后且须自足
    ``\usepackage{pkg}`` 前缀 —— 注缝 LIFO 下裸 ``\usetikzlibrary``
    会落在臂注入 usepackage 行之前 → 新 undefined_cs (95-targeted
    cs_table tikz 族头注同机理)。命中 env 出 noop/站点/批扩全池:
    真包就位后 ``\ifcsname`` 守卫自然死化, 双份注入无谓。

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
    served, notes = _serve_env_pkg_map(ctx, eng, proven, params.get("pkg_map") or {})
    proven -= served
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
        if notes:
            return True, "; ".join(notes)
        return False, f"env(s) {sorted(proven)} not \\begin-used in source"
    defined = {n for m in _ENV_DEF_RE.finditer(blob) for n in m.groups() if n}
    targets = (proven & used) | (used - defined - _KERNEL_ENVS) - served
    main = ctx.main_path()
    main_masked = mask_tex(ctx.read(main) or "") if main is not None else ""
    fresh = [
        e for e in sorted(targets) if f"\\ifcsname {e}\\endcsname" not in main_masked
    ]
    if site_envs:
        notes.append(f"pre-renew noop: {', '.join(sorted(site_envs))}")
    if fresh:
        lines = ["% fixloop: undefined env polyfill (noop env)"]
        for e in fresh:
            lines.append(_env_noop_line(e))
            if e in companions:
                lines.append(companions[e])
        if _inject_before_begindoc(
            ctx, "\n".join(lines), strict_first=True, fallback=_inject_after_docclass
        ):
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
    def 裹 ``\\AtBeginDocument`` 迟延: ctex+hyperref 宿主下 hyperref 在
    ``begindocument/before`` 重声明 text-cs 族, 回卷 preamble 即时
    ``\\protected\\def`` (1404.0332 ``\\i`` 垫在仍缺实证) —— top-level 钩
    排在重声明后, 迟延绑定存活。
    """
    del eng, payload
    seen = _mc_seen(ctx)
    if seen is None:
        return False, "no Missing character in compile log"
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
        *_fb_preamble_lines(fam, font),
    ]
    for cp, cs in fresh:
        ch = cast("str", _mc_chr(cp))  # fresh ⊆ todo——上游已滤 ch is not None
        lines.append(
            rf"\AtBeginDocument{{\protected\def\{cs}{{{_fb_font_body(fam, ch)}}}}}"
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

#: 注入面——与 ``vendor/shims/revtex.cls`` 替身 stub 面同义
#: (90-shim-legacy.yaml ``shim_map.revtex.cls`` 槽已删: vendored 先中),
#: 剥去 cls 装载件 (``\LoadClassWithOptions`` 已由升级稿 docclass 行完成),
#: 补 exact-restore @=11 包装 (``_AT_LETTER_*``: ``\edef`` 存现值→=11 读
#: →复元; @=letter 宿主恒等, 裸 ``\makeatletter`` 对会把 letter 宿主
#: 尾段强翻回 12 —— 1803.02902 csfix 串实证)。
#: ``\AtBeginDocument`` 参数内用单 ``#1``——hook 逐字存 token、
#: ``\begin{document}`` 时才执行内层 ``\def``; ``##`` 只用于 def 嵌 def
#: 的替换文本, 此处的 ``\def\pacs`` 不嵌在任何 def 里, 双写会字面留下
#: ``##`` 炸 "Parameters must be numbered consecutively" (guardsmoke
#: 两格实证, 2026-09-18)。
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


# ════════════════════════════════════════════════════════════════
# bm 族宏 atom-walk 撞 XeTeX 15-bit mathchar 扫描墙 (failmine3 census)
# ════════════════════════════════════════════════════════════════

#: bm 族守卫式重定义注入块 —— bm.sty ``\bm@test@token`` 对实参内每个
#: catcode-11/12 token 做 ``\count@\mathcode`#1`` 原子遍历; XeTeX 的
#: ``\mathcode`` 旧式操作数扫描对 >0xFF 字符 (xeCJK CJK 字/扩展 mathcode)
#: 必炸 "Extended mathchar used as mathchar" (hep-ph/0605174 GLUON.tex:464
#: 四值循环 83922905=0x05008FD9=这 / 83912239=是 / 83921873=译 /
#: 83912071=文; mathchar 探针实证 ``\count@=\mathcode`这`` 文本
#: 态同炸、``\the\mathcode`` 读取不炸; t1-t6 实证裸 ``$这$``/``{\rm 这}``/
#: ``\tilde``/上下标全不炸 —— 修复面只锁 ``\bm`` 族)。
#: ``\bm#1 → \TeXlateBM{{#1}}`` 双花括号把实参改走 bm 自带 ``\bm@gr@@p``→
#: ``\boldmath`` 组路径 (遍历被跳过且粗体语义保留; fix3/fix4 全形零错)。
#: ``\b``/``\unit`` 等 ``\newcommand`` 别名调用点重展开 ``\bm`` 自动受益;
#: ``\boldsymbol``/``\heavysymbol`` 是 bm.sty 末行 ``\let`` 别名,
#: ``\ifx`` 等义复核后才重绑新 ``\bm``/``\hm`` (amsbsy 自带 ``\boldsymbol``
#: 非 bm 别名不误伤)。``\ifdefined\TeXlateBM`` 幂等防自捕环 (若 ``\let``
#: 重捕到新 ``\bm``, ``\TeXlateBM{{#1}}`` 无穷递归)。
_BM_MATHCHAR_WRAP = (
    "% fixloop: bm-family atom-walk reads \\mathcode of every char token —\n"
    "% XeTeX 15-bit mathchar scan rejects >0xFF chars (CJK/extended mathcodes).\n"
    "% Re-route the argument through bm's own group path (\\bm@group->\\boldmath).\n"
    "\\ifdefined\\bm\n"
    "  \\ifdefined\\TeXlateBM\\else\n"
    "    \\let\\TeXlateBM\\bm\n"
    "    \\protected\\def\\bm#1{\\TeXlateBM{{#1}}}\n"
    "    \\ifx\\boldsymbol\\TeXlateBM\\let\\boldsymbol\\bm\\fi\n"
    "  \\fi\n"
    "\\fi\n"
    "\\ifdefined\\hm\n"
    "  \\ifdefined\\TeXlateHM\\else\n"
    "    \\let\\TeXlateHM\\hm\n"
    "    \\protected\\def\\hm#1{\\TeXlateHM{{#1}}}\n"
    "    \\ifx\\heavysymbol\\TeXlateHM\\let\\heavysymbol\\hm\\fi\n"
    "  \\fi\n"
    "\\fi"
)

#: bm 族在用量粗探 —— ``\bm``/``\hm``/``\boldsymbol``/``\heavysymbol`` 字面。
#: ``\b``/``\unit`` 等 ``\newcommand`` 别名定义体内含 ``\bm`` 字面同中;
#: ``\let``-别名调用点不含字面但本修也够不到 (旧 ``\bm`` 快照不走新定义)。
_BM_FAMILY_USE_RE = re.compile(r"\\(?:bm|hm|boldsymbol|heavysymbol)(?![a-zA-Z@])")


def bm_mathchar_wrap(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``\bm{<CJK>}`` 撞 Extended mathchar 墙 → 序言守卫式 ``\bm`` 族重定义。

    实证根因 (failmine3 census ~6 格, hep-ph/0605174 + 1206.0485 +
    2112.00003 全 ``\usepackage{bm}``): bm.sty 原子遍历对实参内 catcode-11
    token 逐个 ``\count@\mathcode`#1`` —— >0xFF 字符在 XeTeX legacy
    mathchar 扫描位必炸 (probe5.tex 实证 ``\mathcode`Ω``=31458217 同炸,
    非 CJK 专属)。``\bm{arg} → \bm{{arg}}`` 双花括号改走 bm 自带组路径
    (``\bm@group`` 分支 ``\bm@mchoice``→``\boldmath`` 直排不遍历, 粗体经
    math version 照常生效)。

    注入点 ``_inject_before_begindoc``: 全部 ``\usepackage``/cls 装载已毕,
    ``\ifdefined\bm``/``\ifdefined\hm`` 守卫对未用 bm.sty 的稿纯空转;
    ``\b``/``\unit`` 宏别名运行时重展开 ``\bm`` 同愈。遮盖源无 bm 族字面
    → False (别名缺口见 ``_BM_FAMILY_USE_RE`` 注); ``snippet in t`` +
    ``\ifdefined\TeXlateBM`` 双幂等。
    """
    del eng, payload, params
    if not _BM_FAMILY_USE_RE.search(mask_tex(ctx.source_blob())):
        return False, "no bm-family macro use in source"
    if not _inject_before_begindoc(
        ctx, _BM_MATHCHAR_WRAP, strict_first=True, fallback=_inject_after_docclass
    ):
        return False, "bm wrap block already present"
    return True, "bm-family group-wrap polyfill injected"
