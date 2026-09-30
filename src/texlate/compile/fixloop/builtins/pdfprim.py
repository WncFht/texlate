r"""builtins.pdfprim — pdfTeX 原语守卫 polyfill (builtins.shim C3 再拆叶)。

xelatex 下裸缺的 pdfTeX 原语按签名分臂补定义:
``_PRIM_COUNTISH``/``_PRIM_TOKSISH``/``_PRIM_DIMENISH``/``_PRIM_BOXISH``
寄存器族全真接管 (``\newcount``/``\newtoks``/``\newdimen``/``\newbox``),
``_PRIM_ARGFUL`` 取参族 ``\protected\def`` 吞参 noop, 余项
``\chardef=1``; 注入恒在主文件头 ``\ifdefined`` 守卫形。单入口
``pdftex_prim_polyfill``; ``@``-名包内别名裹 ``_AT_LETTER_*`` exact-restore。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import (
    _AT_LETTER_POST,
    _AT_LETTER_PRE,
    PDFTEX_PRIMS,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx


#: 整数值 pdfTeX 原语 (寄存器形) —— ``\newcount`` polyfill 全真接管：
#: 赋值型 ``\prim=val`` 落成合法寄存器赋值并保作者意图值，读取型
#: ``\ifnum\prim`` 读初值 1 与旧 ``\chardef=1`` 同义。集合外原语分
#: 三路：取参族 ``\pdfobj`` 系走 ``_PRIM_ARGFUL`` 吞参 noop, toks/
#: dimen 寄存器各走 ``\newtoks``/``\newdimen`` (下两表), 余项
#: (``\pdfstrcmp`` 展开族等) 留 ``\chardef`` 旧形。primofw 车道实证：
#: ``\chardef\pdfcompresslevel`` + axessibility.sty:349 裸写
#: ``\pdfcompresslevel=0`` → chardef cs 变排版字符 + ``=0`` 文本，
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
        # 只读整数面 (\ifnum/\the 读取，寄存器语义一致)
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

#: toks 寄存器形原语 —— ``\newtoks`` 全真接管：``\prim={...}`` 写型与
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
#: pdfpageheight xetex 原生已定义，``\ifdefined`` 闸自然跳过不误伤。
_PRIM_DIMENISH = frozenset(
    {"pdfpagewidth", "pdfpageheight", "pdfhorigin", "pdfvorigin", "pdfpxdimen"}
)

#: box 寄存器形原语 —— ``\newbox`` 全真接管 (``\sbox\<prim>{..}``/
#: ``\setbox\<prim>=``/``\wd\<prim>`` 各面合法)。2502.03387 colm 实证：
#: breakurl.sty:149 ``\sbox\pdf@box`` 在 pdftex 下自导绑定，xelatex 全缺;
#: chardef 下 ``\sbox`` 读不到 box 号 → Missing number 转嫁错类。
_PRIM_BOXISH = frozenset({"pdf@box"})

#: count 寄存器初值 —— 缺省 ``=1`` (读型 ``\ifnum\<prim>`` 与旧 chardef
#: 同义)。``pdfoutput=0`` 有意为之：存在探针 ``\ifx\pdfoutput\undefined``
#: 定义即翻 else 臂 (0712.1016 自产缺陷：polyfill=1 把 texmf 内不可改写
#: 的存在探针全翻成 pdftex 臂 → hyperref[pdftex] xetex GenericError);
#: 值探针 ``\ifnum\pdfoutput>0`` 在 ``=0`` 下保持诚实假 —— 「非 pdfTeX」
#: 是 xelatex 下两种探针的一致回答。``pdftexversion=140`` 对齐 TeX Live
#: 2025 pdftex 1.40.x: 缺省 1 会把 ``\ifnum\pdftexversion<120`` 版本探针
#: 翻成真臂 (microtype 系版本闸静默退役; 0812.1138 docsty 实证受害)。
_PRIM_INIT: dict[str, str] = {"pdfoutput": "0", "pdftexversion": "140"}

#: 取参型原语 —— ``\protected\def`` 吞参 noop (prim → 参数文本):
#: ``\prim{dict}``/``\prim<num>``/``\prim\<reg>`` 站点在 chardef 下实参
#: 落成排版文本 (``\pdfobj{<</...>>}`` 整个 PDF 字典进正文)。实证锚点：
#: spotcolor.sty:34-62 ``\pdfobj{dict}``/``\pdfrefobj\thecolorprofile``/
#: ``\pdfliteral{op}`` (1907.10410/2410.00012 ieeeaccess 族，guard 包不
#: 到 ``\prim\cs`` 无花括号形)。参数文本按原语签名主导形给足：单参
#: ``#1`` 吞花括号组或单 token, 双参 ``#1#2``, 零参 ``""``; 多 token
#: 关键字形 (``\pdfobj stream``/``\pdfdest name{..}``) 只吞首字符，残
#: 字母降级为排版噪声 —— 仍不劣于 chardef 整串残留。``@iffalse`` 哨兵：
#: 条件原语 ``\let→\iffalse`` 走 else 臂保 ``\fi`` 配对完整 (xelatex
#: 实测：``\pdfifprimitive\cs T\else F\fi`` → F 臂); csname 双写形是
#: 跳扫安全必需 —— 裸 ``\let\prim\iffalse`` 在 ``\ifdefined`` 真臂跳扫
#: 下被计成两个 if-token 吃掉 ``\fi``。``\protected`` 保 ``\edef``/
#: ``\write`` 语境不提前展开 (luatex85 同形惯例)。
_PRIM_ARGFUL: dict[str, str] = {
    # 对象/表单/图像 (void 输出原语，``{dict}``/``<num>``/``{file}`` 主导形)
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
    # 双参面：{name}{code} / <font>{chars} / {pat}{str}
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
#: 撞成 already-defined 错 (守卫内嵌语义的逆风险：注入先行于稿内定义位
#: 执行，稿内 ``\newcount\pdfoutput`` 撞我们注的寄存器)。``\def``/``\let``/
#: ``\edef``/``\chardef``/``\countdef`` 重绑无 already-defined 闸不收 —
#: 稿自带死定义位撞名只是无声覆盖，拒注反而丢真修。``renewcommand``/
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
    elif sig == "@iffalse":  # 条件原语：绑 \iffalse 走 else 臂
        # csname 双写裸 \let 不可用：\ifdefined 真臂时 else 臂被跳过，
        # 跳扫把裸 \prim(已定义为 if 类)/\iffalse 计入嵌套 → \fi 被吃成
        # Incomplete \ifdefined (primarg 探针 skip1 实测); csname 形
        # 跳扫面全是非条件 token, 执行面 \expandafter 链正确绑
        # (skip2/skip3 双路实测：定义路径过扫，未定义路径绑 iff→else)。
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
        # @-名注入文本在任意宿主 catcode 下自证：exact-restore @=11 包裹
        # (restore 放 \fi 后，两臂执行路径都复元 catcode); csname 形不可替
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
