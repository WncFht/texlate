r"""``latex.segmenter._common_prose`` — 散文参门控（``_common`` god-file 机械拆分叶）。

调用点散文参判定的单源管线：keyval/逗号名单/裸键列形状门 +
``\\index``/``\\label`` 零宽调用剥除 + ≥4 连词词链判据 +
吞块/死文本名闸（``_SWALLOW_ARG_NAMES``/``_DEAD_*``）。流侧
``_opaque_arg_prose``、组内 ``_prose_arg_hit``/``_grp_opaque_args``、
``_grp_arg_prose`` 三面共享。
"""

from __future__ import annotations

import re

# ------------------------------------------------------------- 散文参门控
# 调用点散文参判定的单源管线：流侧 ``_opaque_arg_prose``（``file_texts``
# 切片喂 ``_prose_text_hit``）、组内 ``_prose_arg_hit``/``_grp_opaque_args``
# （``_grp_surfs`` join 喂同一管线）、``_grp_arg_prose``（token 级重建文本
# 直喂 ``_prose_word_hit``）三面共享本节判据。

# ``{key=val,..}``/``{flag,key=..}`` 起头的 keyval 组形状——键名字符面取宽
# （字母数字 ``_@*.-``），逗号前缀只收裸键位，``{散文}``/``{key 散文}`` 不中。
_KEYVAL_GROUP_RX = re.compile(r"\s*(?:[\w@*.\-]+[ \t]*,[ \t]*)*[\w@*.\-]+[ \t]*=")

# 逗号分隔机读名单形状——``\usetikzlibrary{arrows, automata, backgrounds,
# calendar}``/``\includeonly{ch1, ch2}``/``\bibliography{r1.bib, r2.bib}`` 类
# 标识符/文件名/路径列：≥4 连词判据会被 ``a, b, c, d`` 误判成散文，抠出
# 翻译会把库名/包名/文件名译断。纯名单槽位逐项 ``[\w@*.\-/]+`` 逗号相连
# 才收——真散文词间缺逗号即不中（``{word, word, word}`` 散文罕见，宁漏
# 不译名单）。
_COMMA_LIST_RX = re.compile(r"\s*[\w@*.\-/]+\s*(?:,\s*[\w@*.\-/]+\s*)*,?\s*")

# ``{..}`` 组判形前的 ``%`` 注释剥离——keyval/名单组常以注释行起头
# （``\lstdefinelanguage{lean}{\n% c\nmathescape=false,..}``），裸套
# ``_KEYVAL_GROUP_RX``/``_COMMA_LIST_RX`` 在 ``%`` 处即断 → 组判成散文
# → 键位译成 ``这是译文`` → ``Package keyval Error``（2105.00041
# lstlean.tex 实证）。``\%`` 转义不剥。
_KV_COMMENT_RX = re.compile(r"(?<!\\)%[^\n\r]*")


# 键值/裸键逗号列判形（``_KEYVAL_GROUP_RX`` 的宽口径版）：tikz/pgf 键值列常
# 裸键起头或全裸键——``[rectangle, draw, text width=8em, text centered,
# rounded corners, minimum height=4em]``（2009.03715）、``[draw, -latex]``、
# ``[black!10]``、``[orcid=,email=]``（2410.17963/2403.01255 实证）。逐项
# 逗号切分后：任一项 ``key=`` 形（``text width=8em`` 的 ``width=``、
# ``key =v`` 的空格皆中）即键值列；或全项皆机读键 token——``-latex``
# 箭头名、``blue!50`` 色阶、``/`` 路径键、``.`` 缀名皆收——亦判键值列。
# ``[see Fig. 1]``/``{散文}`` 单项含空格且无 ``=`` 不中；``_KEYVAL_GROUP_RX``
# 锚定形被本判据完全覆盖（首项 ``key=`` 即任一项 ``key=`` 的特例）。
_KEYVAL_ITEM_RX = re.compile(r"[\w@*.\-/!]+[ \t]*=")
_KEY_TOKEN_RX = re.compile(r"[\w@*.\-/!]+")


def _kv_list_shaped(ftext: str, cs: int, ce: int) -> bool:
    r"""``ftext[cs:ce]`` 剥注释后是否键值/裸键逗号列（宽口径）。"""
    items = _KV_COMMENT_RX.sub(" ", ftext[cs:ce]).split(",")
    return any(_KEYVAL_ITEM_RX.search(it) for it in items) or all(
        bool(it.strip()) and _KEY_TOKEN_RX.fullmatch(it.strip()) is not None
        for it in items
    )


# 参内零宽命令整调用剥除——``\index``/``\label`` 不产生可见文本，但其
# ``{..}`` 组在词链判据里当隔墙（``{inflation \index{x} and the epoch}``
# 左右各不到 4 词被误判非散文，W85 实形）。判形前整段剔走让词链连通；
# 抠出后 ``_subscan_render`` 仍照常把 ``\index`` 折 ``[[CMD]]`` 保真。
_ZERO_WIDTH_ARG_RX = re.compile(r"\\(?:index|label)\s*(?:\[[^\]\n]*\]\s*)?\{[^{}]*\}")

# opaque 宏 ``{..}`` 参的调用点散文判据（gullet-at scout 口径）：检测文本先
# 剔 ``%`` 注释与 cs（``\emph`` 类名不计词），再要 ≥4 个 ``[A-Za-z]{2,}``
# 连词（容标点分隔）、非全大写缩写列——``\sortbibitem{KEY}``/``\bibinfo{f}``
# 的 cite-key/字段名参天然不命中，逐参内容判定（参位白名单会断 key 链）。
_OPAQUE_ARG_STRIP_RX = re.compile(r"%[^\n]*|\\[A-Za-z@]+|\\.")
_OPAQUE_ARG_PROSE_RX = re.compile(
    r"[A-Za-z]{2,}(?:[ \t]*[,;:'’\-–—()/&]*[ \t\n]+[A-Za-z]{2,}){3,}"
)
_OPAQUE_ARG_WORD_RX = re.compile(r"[A-Za-z]{2,}")

#: 吞块宏名闸（opaque 臂 + 探针臂同罩）：``\comment{...}`` 按惯例是隐藏批注
#: 宏（comment.sty / 作者自定义 ``\newcommand{\comment}[1]{}``），参内散文
#: 抬进译文面会把源 PDF 本不显示的内部注记印进译文 PDF（W50 语义）。
#: ``todo``/``fixme``/``note`` 不收——todonotes/fixme 包默认内联渲染参数，
#: 误收会把真可见文本藏起来；``comment`` 是唯一不歧义的吞块约定名。
_SWALLOW_ARG_NAMES = frozenset({"comment"})

#: 死文本参名闸（changes 族 W27）：``\deleted``/``\removed`` 参是被删
#: 文本——抠出翻译会把终稿不显示的删改内容印进译文面。与吞块闸不同：
#: 吞块是源文本就隐藏，死文本是修订标记语义下的非终稿内容。
_DEAD_ARG_NAMES = frozenset({"deleted", "removed"})

#: 尾参死文本名闸：``\replaced{新}{旧}`` 首参（新文本）可见可译、
#: 次参起（``{旧}``）是被替换的死文本不译——只放首个实参。
_DEAD_TAIL_NAMES = frozenset({"replaced"})


def _prose_word_hit(text: str) -> bool:
    r"""剔净文本的词链判据：≥4 个 ``[A-Za-z]{2,}`` 连词、非全大写 → 散文。

    ``_grp_arg_prose``（token 级重建文本——cs token 已剔为空白、注释
    在 token 流本无）直喂本判据；文本口径走 ``_prose_text_hit``。
    """
    for mm in _OPAQUE_ARG_PROSE_RX.finditer(text):
        words = _OPAQUE_ARG_WORD_RX.findall(mm.group(0))
        if len(words) >= 4 and not all(  # noqa: PLR2004 - scout 散文判据连词下限
            w == w.upper() for w in words
        ):
            return True
    return False


def _prose_text_hit(text: str) -> bool:
    r"""参内容文本 → 散文判中（形状门 + 词链判据；名闸在 ``_prose_arg_hit``）。

    ``key=`` 起头的 keyval 组、逗号分隔机读名单、裸键起头/全裸键键值列
    （``{rectangle, draw, text width=8em}`` 面）皆是机读槽位——键位/库
    名抬进译文面即断链炸面（``\setkeys`` 同规）；``\index``/``\label``
    零宽调用先剥除不当词链隔墙，剔注释+cs 后过词链判据。
    """
    stripped = _KV_COMMENT_RX.sub(" ", text)
    if _KEYVAL_GROUP_RX.match(stripped) is not None:
        return False  # ``{key=..}`` 组——键位非散文，整参保持 opaque
    if _COMMA_LIST_RX.fullmatch(stripped):
        return False  # 逗号名单（库/包/文件列）——机读槽位不挖
    if _kv_list_shaped(text, 0, len(text)):
        return False  # 裸键起头/全裸键键值列——宽口径键值判形同罩
    text = _ZERO_WIDTH_ARG_RX.sub(" ", text)
    text = _OPAQUE_ARG_STRIP_RX.sub(" ", text)
    return _prose_word_hit(text)


def _prose_arg_hit(name: str, nth: int, text: str) -> bool:
    r"""散文参判定的单源管线（渲染文本口径）——名闸 + 形状门 + 词链判据。

    流侧对价 = ``_opaque_arg_prose``（``file_texts[fid][cs:ce]`` 切片喂同
    管线）；组内 ``text`` = ``_grp_surfs`` join——gen>0 token 无本段字节，
    token 级重建文本走同一判据集。``_SWALLOW_ARG_NAMES``（吞块 W50）/
    ``_DEAD_ARG_NAMES``（被删死文本）整调用不挖；``_DEAD_TAIL_NAMES``
    只放首参——``\replaced{新}{旧}`` 的 ``{旧}`` 是被替换死文本不译。
    """
    if name in _SWALLOW_ARG_NAMES or name in _DEAD_ARG_NAMES:
        return False
    if name in _DEAD_TAIL_NAMES and nth != 0:
        return False
    return _prose_text_hit(text)
