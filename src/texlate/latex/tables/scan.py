r"""``latex.tables.scan`` — 扫描层共享表与 \\if 两档（``tables`` god-file 机械拆分叶）。

\\if 两档分族（``COND_RX``/``IF_CONST*``）、``PROTECTED_PARAM_CMDS``
保护位参数启发、scan 层 \\input 触发面（``INPUT_SCAN_CMDS``/
``IMPORT2_CMDS``/``FILENAME_CHARS``/``strip_fname_quotes``）、cs 对界
DSL 块 ``PAIR_BLOCK_*``。
"""

from __future__ import annotations

import re

from texlate.latex.tables.names import CITE_NAMES, REF_NAMES

# ---------------------------------------------------------------- \if 两档

COND_RX = re.compile(r"^(if[a-zA-Z@]*|else|fi|or)$")

# 恒值 \if 族（可求值，docs/spec/latex-pipeline.md）
# 真值以 plasTeX 为准（Primitives.py:247-258 硬编码 ifvmode=False/
# ifhmode=True——展开语境恒按"正在水平排版"处理）；此前写反会让
# 顶层 \ifhmode/\ifvmode 选中死分支进 chunk。
IF_CONST_FALSE = {"ifeof", "ifinner", "ifvoid", "ifhbox", "ifvbox"}
IF_CONST = {"ifhmode": True, "ifvmode": False}

# 保护位参数启发：#i 落在这些命令参数位 → 该位 [[KEY]]
PROTECTED_PARAM_CMDS = CITE_NAMES | REF_NAMES | {"label", "url", "includegraphics"}

_WS_CHARS = " \t\n"

# ---------------------------------------------------------------- 扫描层共享表

# scan 层登记的 \input 触发面（gullet 未解析成功时记 inputs[]）。
# 与 ``INPUT_CMDS`` 的差 = ``CatchFileBetweenTags``：其形为
# ``\CatchFileBetweenTags\cs{file}{tag}``，只由 gullet ``_do_input``/
# flatten 的 tag 区提取处理；scan 层 ``_handle_input_cs`` 只认
# ``{file}``/import 双参/裸名三形——登记进来会把 ``{file}`` 位读错。
INPUT_SCAN_CMDS = {
    "input",
    "@input",  # 字节层 read_cmd_name 的 \@input 特判形
    "include",
    "InputIfFileExists",
    "subfile",
    "includestandalone",
    "import",
    "subimport",
}

# ``\import{dir}{file}``/``\subimport{dir}{file}`` 双参族——``INPUT_CMDS``/
# ``INPUT_SCAN_CMDS`` 成员中唯二吃两参的名（``{dir}`` 前缀拼 ``{file}``）。
# gullet ``_do_input``、flatten、segmenter 主流/组内四路同款 tuple 的单源；
# segmenter ``grpscan._IMPORT2`` 旧私有名废弃，一律归本表。
IMPORT2_CMDS = ("import", "subimport")

FILENAME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
)


def strip_fname_quotes(fname: str) -> str:
    r"""剥一层成对双引号——``"a b.tex"`` → ``a b.tex``。

    web2c 引号文件名约定（``\input{"a b.tex"}``/``\input"a b.tex"``，带空格
    文件名）；latexpand ``$ARGQUOTED`` 同款。不成对的引号按字面名处理。
    """
    if fname.startswith('"') and fname.endswith('"') and len(fname) > 1:
        return fname[1:-1]
    return fname


# cs 对界 DSL 块（非 ``\begin/\end`` 形）：开 cs 名 → 闭 cs 名。
# ``\labellist…\endlabellist``（pinlabel，W29）——体按保护环境走
# ``_env_with_mined`` mined 子扫：``\pinlabel {tex}`` 标签文照挖、
# ``at x y`` 坐标脚手架不外泄进 chunk。闭名 cs 孤现 → ``[[CMD]]``。
PAIR_BLOCK_CMDS: dict[str, str] = {
    "labellist": "endlabellist",
}
PAIR_BLOCK_ALL = frozenset(PAIR_BLOCK_CMDS) | frozenset(PAIR_BLOCK_CMDS.values())
