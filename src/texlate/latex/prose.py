r"""散文门（prose gate）：文件级「含可译散文」判别——support 文件不进翻译集。

背景（scout-supportfiles 普查）：e-print 树里的 bundled 机制文件
（pstricks/epsf/tcilatex/tikzlibrary*.code.tex）、论文自有宏件
（defs/macros_*.tex）、gnuplot PostScript 转储（gtoutput/fig*.tex）会被
``_translate_tree`` 无差别送译——para 块里的 PS 算子/宏体产出伪译文，
splice 写回即腐蚀（``\\psunit 1cm`` → ``1这是译文``）。普查实测本判据
20/20 腐蚀件 DROP、20+ 内容件 KEEP、假阳 1/120。

chunk 级 ``is_prose`` 判据（满足其一即散文）：

- **结构上下文救回**：``chunk.context ∈ PROSE_CONTEXTS``（caption/section/
  footnote 等标题脚注类命令名）——短真标题（"TRIS antennas"）零功能词也收，
  缺这臂短 caption 全灭；
- **功能词计数**：剥 ``[[X_n]]`` 占位符后，正文中 ≥3 字母的词里有
  ≥ ``_MIN_FUNCWORDS`` 个**不同**功能词 ∈ ``FUNCWORDS``。

``FUNCWORDS`` 严格只收冠词/介词/连词/助动词：``and|not|or|if|for`` 是
PostScript 算子（普查唯一实测泄漏源）不入表；``def/set/end/use/new/left/right``
类内容名词同不收。候选词须 ≥3 字母——``of`` 在表但受此约束永不命中
（留作口径记录，阈值若降到 2 自动生效）。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from texlate.latex.placeholder import PH_RX
from texlate.latex.tables import CHUNK_ARG_NAMES

if TYPE_CHECKING:
    from collections.abc import Iterable

    from texlate.latex.model import Chunk

#: ``argspec.json`` ``chunk-arg`` 登记项中属文档结构的 context 名——
#: beamer/exam/hyperref/amsmath 的标题、题干、行间批注位（硬编码面之外
#: 的查表路径生产；context = argspec 条目名）。手工策展子集：
#: ``resizebox``/``rotatebox``/``scalebox``/``reflectbox``/``multirow``/
#: ``multicolumn``/``mbox`` 等盒/表参名不收——它们的 args 是机制碎片，
#: 收进来会重开此门要防的假阳腐蚀。
_ARGSPEC_STRUCT_CTX: frozenset[str] = frozenset(
    {
        "CorrectChoice",
        "alert",
        "answerline",
        "choice",
        "fillin",
        "framesubtitle",
        "frametitle",
        "intertext",
        "pdfbookmark",
        "question",
        "shortintertext",
        "structure",
        "subpart",
        "texorpdfstring",
        "textenv",
    }
)

#: 环境内部语境：aastex deluxetable 表注（``tablenotetext``/
#: ``tablecomments``）与 pinlabel ``labellist`` 标签——只在保护
#: 环境挖掘面内产生的 context；仅含这类块的文件更像 bundled
#: 表格件而非散文文档，维持显式排除（历史名单漏收→复核保留，
#: 不是默认漂移）。
_ENV_INTERNAL_CTX: frozenset[str] = frozenset(
    {
        "tablenotetext",
        "tablecomments",
        "pinlabel",
    }
)

#: 结构上下文白名单：这些 context 的块本身是标题/脚注/关键词类正文——
#: 短到零功能词也算散文。派生不自抄：``CHUNK_ARG_NAMES``（硬编码
#: chunk-arg 命令面，context = 命令名）∪ ``{"abstract"}``（env 派生
#: 语境——core.py 按 env_stack 顶位赋）∪ ``_ARGSPEC_STRUCT_CTX``
#: − ``_ENV_INTERNAL_CTX``。新增 chunk-arg 命令/结构调整项在各自
#: 登记表改一次即生效，不再双表漂移。
PROSE_CONTEXTS: frozenset[str] = (
    frozenset(CHUNK_ARG_NAMES | {"abstract"} | _ARGSPEC_STRUCT_CTX) - _ENV_INTERNAL_CTX
)

#: 严格功能词表（冠词/介词/连词/助动词）——PS 算子与内容名词不入。
FUNCWORDS: frozenset[str] = frozenset(
    {
        "about",
        "after",
        "again",
        "against",
        "all",
        "almost",
        "already",
        "also",
        "although",
        "always",
        "among",
        "any",
        "are",
        "because",
        "been",
        "before",
        "being",
        "between",
        "both",
        "but",
        "can",
        "cannot",
        "could",
        "does",
        "during",
        "each",
        "especially",
        "even",
        "finally",
        "firstly",
        "few",
        "from",
        "furthermore",
        "generally",
        "had",
        "has",
        "have",
        "hence",
        "here",
        "how",
        "however",
        "instead",
        "into",
        "its",
        "just",
        "many",
        "may",
        "meanwhile",
        "might",
        "more",
        "moreover",
        "most",
        "much",
        "must",
        "namely",
        "nearly",
        "never",
        "now",
        "of",
        "often",
        "once",
        "only",
        "other",
        "otherwise",
        "our",
        "over",
        "own",
        "particularly",
        "per",
        "quite",
        "rather",
        "respectively",
        "same",
        "secondly",
        "shall",
        "should",
        "since",
        "some",
        "still",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "therefore",
        "these",
        "they",
        "this",
        "those",
        "though",
        "through",
        "thus",
        "together",
        "too",
        "upon",
        "usually",
        "very",
        "via",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "why",
        "will",
        "with",
        "within",
        "without",
        "would",
        "yet",
    }
)

#: 散文判据：正文 ≥3 字母词中不同功能词数下限。
_MIN_FUNCWORDS = 3

#: 候选词切分：连续字母 run（非字母即边界——反斜杠/下划线/数字都切开）。
_WORD_RX = re.compile(r"[a-z]{3,}")


def is_prose(chunk: Chunk) -> bool:
    """单块散文判定：结构 ctx 救回 ∨ ≥3 distinct 功能词。"""
    if chunk.context in PROSE_CONTEXTS:
        return True
    text = PH_RX.sub(" ", chunk.content).lower()
    hits = {w for w in _WORD_RX.findall(text) if w in FUNCWORDS}
    return len(hits) >= _MIN_FUNCWORDS


def file_has_prose(chunks: Iterable[Chunk]) -> bool:
    """文件级判定：任一块是散文即送译；空 ``chunks`` → False。"""
    return any(is_prose(c) for c in chunks)
