r"""builtins._common_cslet — catcode-agnostic 注入形 (common 拆分)。

spacefactor 车道 (2026-09-19) 的 ``\let``/undefine/exact-restore 包裹
串单源 —— ``\csname`` 侧壳使 @ 名在任意宿主 catcode 下成 token。
"""

from __future__ import annotations

__all__ = [
    "_AT_LETTER_POST",
    "_AT_LETTER_PRE",
    "_AT_LETTER_SEG",
    "_UNDEF_MARK",
    "_exact_restore_wrap",
    "_let_cs",
    "_undefine_cs",
]

#: 永不定义的纯字母 cs —— ``\let\X\TeXlateUndefCs`` 的右操作数。
#: ``\csname @undefined\endcsname`` 会把 ``\@undefined`` 冻结成 ``\relax``
#: (csname 未定义名副作用), 产 ``\relax`` 值而非真 undefined ——
#: ``\ifcsname``/expl3 ``\cs_if_exist`` 存在性检查下仍算 defined
#: (freeze_test 实证)。纯字母名任何宿主 @ catcode 下成 token, 且不冻名。
_UNDEF_MARK = "TeXlateUndefCs"


def _let_cs(target: str, source: str) -> str:
    r"""``\let\<target>\<source>`` 的 catcode-agnostic 形 (两侧均可含 ``@``)。

    ``\csname`` 侧壳使 @ 名在任意宿主 catcode 下成 token —— 裸
    ``\makeatletter``/``\makeatother`` 对的尾段会把 @=letter 宿主尾段
    强翻回 12 (1803.02902 csfix 清位串实证), def 体内字面 ``\@`` 亦
    无法重读 (@=12 下已成 ``\@``+裸字母 → spacefactor 签); csname 形
    两语境皆免 catcode。
    """
    return (
        rf"\expandafter\let\csname {target}\expandafter\endcsname"
        rf"\csname {source}\endcsname"
    )


def _undefine_cs(name: str) -> str:
    r"""``\let\<name>\@undefined`` 的 catcode-agnostic 形 → 清位串。

    右操作数用 ``_UNDEF_MARK`` (永不定义纯字母名): 产**真** undefined,
    ``\ifdefined``/``\cs_if_exist``/``\@ifdefinable`` 三代检查通吃;
    ``\csname @undefined\endcsname`` 形只得 ``\relax`` 值, 存在性检查
    下破防 (ctlseq_undefine 的 ``\cs_new`` 撞名格实证需求)。
    """
    return rf"\expandafter\let\csname {name}\endcsname\{_UNDEF_MARK}"


def _exact_restore_wrap(cs: str) -> tuple[str, str]:
    r"""exact-restore @=11 包裹对的裸段 → ``(pre_seg, post_seg)``。

    ``pre_seg`` = ``\edef\<cs>{\catcode 64=\the\catcode 64\relax}\catcode 64=11\relax``
    (``\edef`` 存 ``\catcode 64`` 现值 → ``=11`` 读本族 @-cs), ``post_seg``
    = ``\<cs>`` (复元恒回原位)。分隔符 (空格/换行) 归属调用方拼 —
    ``_SHIP_WRAP_*``/``_AT_LETTER_*`` 尾空/头空, ``_SIU_PEACE_*`` 换行。
    (自 builtins.pkgload 归位 —— 两侧包裹对字面量单源。)

    隐式耦合: 传入 ``cs`` 必须已登记进 ambient-@ 事件表的 restore 交替
    组 (pkgload ``_AMBIENT_AT_RE``/docfix ``_ATDEF_EVENT_RE`` 均
    ``TeXlate(?:At|StyIn)Restore``) —— 否则组作用域走查的 at_letter
    跟踪把该 cs 当普通字符消费, ``\catcode 64=11`` 事件配平丢失致状态
    误记。
    """
    return (
        rf"\edef\{cs}{{\catcode 64=\the\catcode 64\relax}}\catcode 64=11\relax",
        rf"\{cs}",
    )


#: 多 @-cs 注入块的宿主不可知 @=11 包裹对 (svglov3.clo exact-restore
#: idiom, 同 builtins.pkgload._SHIP_WRAP_*): ``\edef`` 存 ``\catcode 64``
#: 现值 → ``=11`` 读块 → 复元; @=letter 宿主恒等变换，@=other 亦回原位。
#: restore cs 名纯字母 —— 宿主正处 @=other 时名里带 ``@`` 自断签名。
_AT_LETTER_SEG = _exact_restore_wrap("TeXlateAtRestore")
_AT_LETTER_PRE = _AT_LETTER_SEG[0] + " "
_AT_LETTER_POST = " " + _AT_LETTER_SEG[1]
