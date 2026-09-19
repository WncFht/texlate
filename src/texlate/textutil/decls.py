r"""文档声明/结构探测正则族的单一事实源。

``\documentclass``/``\documentstyle`` 声明、包/类加载命令名、``\input``
族目标、``\begin{document}``/``\end{document}`` 边界、声明参数名清洗。

消费侧一律在遮盖/剥注释视图上判定——注释/verbatim 内的字面命中不算数；
本族只管 pattern，视图归调用方。
"""

from __future__ import annotations

import re
from typing import Final

#: ``\begin{document}`` 探测（``\begin {document}`` 空白合法）。消费侧一律
#: 在遮盖/剥注释视图上判定——注释/verbatim 内的字面命中不算数。
BEGIN_DOC_RX: Final = re.compile(r"\\begin\s*\{document\}")
#: ``\end{document}`` 探测——``BEGIN_DOC_RX`` 的对端，同视图约定。
END_DOC_RX: Final = re.compile(r"\\end\s*\{document\}")

# ------------------------------------------------------------------
# ``\documentclass``/``\documentstyle`` 声明探测族（单源：audit-2026-09 §2.2
# 「六站三方言」收编）。边界统一 ``@`` 排外——``\makeatletter`` 语境的
# ``\documentclass@foo`` 是异名 cs 而非声明命令；``\b``/``(?![a-zA-Z])`` 旧
# 写法分别误吞 ``@`` 后随、误拒 ``_``/数字后随，均弃。
#: 视图归调用方（visible_tex/mask_tex/剥注释面），本族只管 pattern。
CMD_BOUNDARY: Final = r"(?![a-zA-Z@])"

#: 探测用 cs 名集——token 层（segmenter mainloop）与正则层同源。
DOCCLASS_NAMES: Final = frozenset({"documentclass", "documentstyle"})

#: ``\documentclass``/``\documentstyle`` 命令名探测（无实参约束）。group(1)
#: 为命中命令名。
DOCCLASS_RX: Final = re.compile(r"\\(documentclass|documentstyle)" + CMD_BOUNDARY)
#: ``\documentstyle`` 单名版（209 检出/升级面专用）。
DOCSTYLE_RX: Final = re.compile(r"\\documentstyle" + CMD_BOUNDARY)
#: ``\documentclass`` 单名版。
DOCCLASS_ONLY_RX: Final = re.compile(r"\\documentclass" + CMD_BOUNDARY)

#: 声明实参尾形 ``[opts]{name}``——命令集不同的复合探测（probe/shadow 的
#: ``LoadClass`` 族）拿本片段拼自己的交替，尾形唯一事实源。自带两捕：
#: ``(opts, name)``——拼接方按 offset 读组。
DECL_TAIL: Final = r"\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}"
#: 完整声明形：``(cmd, opts, name)`` 三组。
DOCCLASS_DECL_RX: Final = re.compile(
    r"\\(documentclass|documentstyle)" + CMD_BOUNDARY + DECL_TAIL
)
DOCSTYLE_DECL_RX: Final = re.compile(r"\\documentstyle" + CMD_BOUNDARY + DECL_TAIL)
#: ``\documentclass`` 选项→``{`` 锚定形（opts 一捕）——svjour stub 与
#: legacy-latin 注入锚同形。
DOCCLASS_OPTS_RX: Final = re.compile(
    r"\\documentclass" + CMD_BOUNDARY + r"\s*(?:\[([^\]]*)\])?\s*\{"
)

#: ``\documentclass[..]{subfiles}`` —— subfiles 子档标记。母档 ``\subfile``
#: 拉入时子件 ``\documentclass`` 起至 ``\begin{document}`` 区间被吞，声明行
#: **之前**的文本却在母档 body 语境执行——前置块里 preamble-only cs
#: （``\PassOptionsTo*``）落 body 即 "Can be used only in preamble"
#: （2310.16788 birds_eye_view/side_view :1,14 实案）。消费侧同族约定：
#: 遮盖/剥注释视图判定。
SUBFILES_CHILD_RX: Final = re.compile(
    r"\\documentclass" + CMD_BOUNDARY + r"\s*(?:\[[^\]]*\])?\s*\{\s*subfiles\s*\}"
)

#: 包/类加载命令名集——全仓各站现有集合的并集单源化（fixloop actions
#: ``_DEP_DECL_RE`` / normalize ``_PACKAGE_USE_RX``·``_CLASS_USE_RX`` /
#: probe ``_PKG_RE``·``_CLS_RE`` / inject / fixloop.builtins /
#: segmenter ``_PKG_CMDS`` 逐站归并）。``documentclass``/``documentstyle``
#: 属文档声明族、``DOCCLASS_NAMES`` 已单源，不在此列。
LOADER_CMDS: Final = frozenset(
    {
        "usepackage",
        "RequirePackage",
        "RequirePackageWithOptions",
        "LoadClass",
        "LoadClassWithOptions",
        "PassOptionsToPackage",
        "PassOptionsToClass",
    }
)


#: ``\input`` 族目标扫描（compile probe/inject 同源口径：braced/bare 两形；
#: ``\b`` 词界使 ``\includegraphics`` 不误命中 ``\include``）。named
#: groups——``verb`` 给 ``\InputIfFileExists`` 的 optional 判定，``arg``
#: 是声明文件名；消费方按名取组、位序脱钩。
INPUT_BRACED_RX: Final = re.compile(
    r"\\(?P<verb>input|include|InputIfFileExists)\b\s*\{(?P<arg>[^}]+)\}"
)
INPUT_BARE_RX: Final = re.compile(r"\\input\s+(?P<arg>[^\s{}%\\]+)")
#: 更宽的 ``\input`` 族谱系（subfile/import/subimport/includestandalone/
#: CatchFileBetweenTags/bibliography）刻意不单源成一枚 ``*_RX``——import 系
#: 双参（dir+file）、CatchFileBetweenTags 前导 token 参、bibliography 逗号
#: 分片，per-command 参数组语义单正则承载不了；超集口径仍在
#: ``arxiv.locate._REF_RES``。

#: 声明名噪声过滤：``\w./+-`` 白名单字符集——含控制序列/括号/注释符的
#: 噪声 token 一律拒（``\input`` 巨参、``\@tempb`` 类误捕；fixloop
#: static_precheck 同款口径）。
DECL_NAME_RX: Final = re.compile(r"^[\w./+-]+$")


def clean_decl_name(raw: str) -> str | None:
    """声明参数 → 干净文件名；含控制序列/括号/注释符的噪声 token → ``None``。"""
    name = raw.strip().strip('"').strip()
    if not name or not DECL_NAME_RX.match(name):
        return None
    return name
