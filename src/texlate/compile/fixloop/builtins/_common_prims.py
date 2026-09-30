r"""builtins._common_prims — pdfTeX 原语清单 (common 拆分)。

``ruleset._FAMILY_TOKENS`` 与 ``pdftex_prim_polyfill`` 双侧消费的
``\pdf*`` 原语名表 (含 ``pdf@`` 包内别名族)。
"""

from __future__ import annotations

__all__ = [
    "PDFTEX_PRIMS",
]

# pdfTeX 原语清单 (原型 + 2410.00012 实证扩: 文档面对象/注释/资源族)
PDFTEX_PRIMS = (
    "pdfoutput",
    "pdfminorversion",
    "pdfoptionpdfminorversion",  # axessibility.sty:350 实证 (旧拼形整参)
    "pdfcompresslevel",
    "pdfobjcompresslevel",  # 同族整参 (老包常与 pdfcompresslevel 连写)
    "pdfinfo",
    "pdfpagewidth",
    "pdfpageheight",
    "pdfhorigin",
    "pdfvorigin",
    "pdfsuppressptexinfo",
    "pdftrailer",
    "pdfpxdimen",
    "pdflastxpos",
    "pdflastypos",
    # 对象/表单/图像
    "pdfobj",
    "pdflastobj",
    "pdfrefobj",
    "pdfxform",
    "pdflastxform",
    "pdfrefxform",
    "pdfximage",
    "pdflastximage",
    "pdfrefximage",
    # 注释/链接/书签
    "pdfannot",
    "pdflastannot",
    "pdfdest",
    "pdflink",
    "pdfstartlink",
    "pdfendlink",
    "pdfoutline",
    "pdfcatalog",
    "pdfnames",
    # 文字流/页面资源
    "pdfliteral",
    "pdfcolorstack",
    "pdfcolorstackinit",
    "pdfsavepos",
    "pdfpageref",
    "pdfpageattr",
    "pdfpagesattr",
    "pdfpageresources",
    "pdfdraftmode",
    # 读取/工具原语
    "pdfescapestring",
    "pdfescapename",
    "pdfescapehex",
    "pdfunescapehex",
    "pdffilesize",
    "pdffilemoddate",
    "pdffiledump",
    "pdfmdfivesum",
    "pdfelapsedtime",
    "pdfresettimer",
    "pdfuniformdeviate",
    "pdfnormaldeviate",
    "pdfrandomseed",
    "pdfmatch",
    "pdflastmatch",
    "pdfstrcmp",
    "pdfprimitive",
    "pdfifprimitive",
    "pdfcreationdate",
    # 字体/微排/映射
    "pdffontname",
    "pdffontobjnum",
    "pdffontsize",
    "pdfincludechars",
    "pdfmapfile",
    "pdfmapline",
    "pdfglyphtounicode",
    "pdfgentounicode",
    "pdfadjustspacing",
    "pdfprotrudechars",
    "pdftracingfonts",
    "pdfdecimaldigits",
    "pdftexversion",
    "pdftexrevision",
    "pdfinclusionerrorlevel",
    "pdfinclusioncopyfonts",  # 2403.15085: 稿面 \prim=1 写形, guard 包裹位
    "pdfsuppresswarningpagegroup",
    # `pdf@` 包内别名族 (breakurl/pdfmark.def/pdftexcmds 系包体在 pdftex
    # 下自导原语绑定, xelatex 下全族裸缺) —— @-名只能存在于 @=11 包体
    # 语境, pdftex_prim|<@名> 报错定义上即包内宏展开帧 (file_stack 归
    # doc 侧, err_outside_fileset 不见), 主文件头补定义是唯一治法。
    "pdf@box",  # breakurl.sty \sbox\pdf@box scratch box (2502.03387 colm)
    "pdf@toks",
    "pdf@defaulttoks",
    "pdf@draftmode",
    "pdf@inclusionerrorlevel",
    "pdf@lastxpos",
    "pdf@lastypos",
    "pdf@lastxform",
    "pdf@lastximage",
    "pdf@addtoks",
    "pdf@addtoksx",
    "pdf@docset",
    "pdf@linktype",
    "pdf@majorminor",
    "pdf@objdef",
    "pdf@rect",
    "pdf@type",
    "pdf@xform",
    "pdf@refxform",
    "pdf@ximage",
    "pdf@refximage",
    "pdf@escapestring",
    "pdf@escapename",
    "pdf@escapehex",
    "pdf@unescapehex",
    "pdf@filemoddate",
    "pdf@filedump",
    "pdf@filesize",
    "pdf@mdfivesum",
    "pdf@pageref",
    "pdf@lastmatch",
    "pdf@strcmp",
    "pdf@match",
    "pdf@ifdraftmode",
)
