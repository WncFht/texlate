r"""``latex.segmenter._common.slots`` — 待绑参槽列 ↔ 归一走参元（``_common`` god-file 机械拆分叶）。

槽字母表（``_PEND_CALL*``/``_PEND_PROBE``/``_HYPERREF_SLOTS``/``_BSBS_SLOTS``/
``_ACCENT_SLOTS``/``_KEYARG_*``/``_COND_GROUP_ARGS``）与 ``_WSpec`` 归一投影
（``_slot_elem``/``_aspec_elem``/``_gspec_elem``/``_pend_slot_of``）——
三字母表到 ``_WSpec`` 的投影单源，走参本体在 ``group._walk_spec_toks``。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from texlate.latex.gullet import Arg
    from texlate.latex.model import ArgSpec
    from texlate.latex.mouth import Tok

# ---- 跨边界待绑参（key-arg 泄漏修复）：展开组尾 cs 的调用点参数吸回组内 ----
# ``\def\r{\ref}``+``\r{key}``：``\ref`` 是展开产物（pos=定义体、origin=
# 调用区间），``{key}`` 是 gen=0 调用点 token（pos==origin 末——`_in_group`
# 的 ``a < o[2]`` 开区间把它挡在组外）→ 无吸纳则 ``{key}`` 落 chunk 被译。
# 槽形字母 → ``_slot_elem`` 归一投影成 ``_WSpec``——列扫走参本体只有一份
# （``group._walk_spec_toks``：``_slots_walk_toks``/``_grp_call_end``/
# ``_grp_probe_end``/``_grp_spec_args_end``/``_grp_spec_walk`` 共用）；
# 流侧拉取对价是 ``pending._absorb_slots``（read/unread 账本不同构，不统一）：
#   s   = 紧邻 ``*``（不跳 ws——``\ref *{k}`` 的星不是星参，call_end 同规）
#   o   = ws + ``[..]`` 平衡组（可选——失配过给下一槽）
#   m   = ws + ``{..}`` 平衡组（失配即调用终止）
#   e   = ws + ``{..}``|``[..]`` 任选一组（hyperref 首参形；失配终止）
#   a   = accent 参（``{..}``|单 letter/other|单字符名 cs；失配终止）
#   b   = ws + ``[dimen]``（``\\`` 尾参；内容须 fullmatch _GRP_BSBS_CONTENT_RX）
#   n   = ws + 单 cs token 或 ``{..}``/``[..]`` 组（``\setlength\parskip``
#         裸名参；强制——失配即调用终止）
#   dXY = ws + ``X..Y`` 定界对（argspec d/D/r/R；可选——失配过槽）
#   tC  = ws + 单测试字符（argspec t；可选）
_PEND_CALL1 = ("s", "o", "o", "o", "m")  # ``_grp_call_end`` mand=1 形
_PEND_CALL2 = ("s", "o", "o", "o", "m", "m")  # inputminted 双 ``{m}``
_PEND_PROBE = ("o", "m", "m", "m", "m", "m", "m")  # ``_grp_probe_end`` 形
_SLOT_PAIR_LEN = 3  # ``dXY`` 槽宽（d + 开/闭定界符）
_SLOT_TEST_LEN = 2  # ``tC`` 槽宽（t + 测试字符）

# ---- ``_pend_spec_of`` 槽列 ↔ ``_grp_scan``/``_grp_bsbs``/``_grp_call_end``
# 走参元的同形单源：名→槽形改动只改一处（``_slot_elem`` 逐位归一投影进
# ``_walk_spec_toks``）。
_HYPERREF_SLOTS: tuple[str, ...] = ("s", "e")  # hyperref 行（key,text 首参形）
_BSBS_SLOTS: tuple[str, ...] = ("s", "b")  # ``\\`` 行（``group._grp_bsbs`` 同形）
_ACCENT_SLOTS: tuple[str, ...] = ("a",)  # accent 行


def _cond_slots(name: str) -> list[str]:
    r"""``\iftoggle`` 族名/表达式槽列——``_pend_spec_of``/``_grp_scan`` COND 行同形。"""
    return ["m"] * _COND_GROUP_ARGS.get(name, 0)


def _call_slots(tail: list[str]) -> list[str]:
    r"""``_grp_call_end`` 整调用形槽列：``["s","o","o","o"]`` 前缀 + 强制参尾列。

    ``_pend_spec_of`` cite-ref/boundary/argspec 整调用行与组内
    ``_grp_call_end`` 同形（``_PEND_CALL*``/``_pend_call_slots`` 同族）。
    """
    return ["s", "o", "o", "o", *tail]


# 字符串宏体尾 cs 提取（``_keyarg_tail`` 的 str-body 臂）
_KEYARG_TAIL_RX = re.compile(r"\\([a-zA-Z@]+)\s*$")
_KEYARG_TAIL_DEPTH = 4  # ``\a``→``\b``→``\ref`` 别名链递归上限（防环）


def _pend_call_slots(name: str) -> list[str]:
    r"""Key-arg 名 → 待绑参槽列（``_grp_call_end`` 同形）。

    ``url``/``path`` 只认 ``{..}`` 形（定界形参无法 token 配对回吸）。
    """
    if name in ("url", "path"):
        return ["m"]
    return list(_PEND_CALL2 if name == "inputminted" else _PEND_CALL1)


def _pend_slot_of(s: ArgSpec) -> str | None:  # noqa: PLR0911 — 槽字母各一分支，平铺即映射表
    r"""``ArgSpec`` → 待绑参槽字母；``e``/``b``/无 delim 形 → ``None``（槽形截尾）。"""
    k = s.kind
    if k in ("m", "v"):
        return "m"
    if k == "n":
        return "n"
    if k in ("o", "O"):
        return "o"
    if k == "s":
        return "s"
    if k == "t" and s.delim:
        return "t" + s.delim[0]
    if k in ("d", "D", "r", "R") and s.delim:
        return "d" + s.delim[0] + s.delim[-1]
    return None


# ------------------------------------------------- 归一走参元（_walk_spec_toks）
# 物化 token 列上的 spec 走参曾是五份平行实现（``_slots_walk_toks`` 槽字母、
# ``_grp_call_end``/``_grp_probe_end`` 定形槽列、``_grp_spec_args_end`` argspec、
# ``_grp_spec_walk`` gullet Arg+ka 尾段）——三字母表到 ``_WSpec`` 的投影单源
# 化后，走参本体只剩 ``group._walk_spec_toks`` 一份。流侧（read/unread 账本）
# 对价仍是 ``_absorb_slots``/``_absorb_spec``/``_args_tok``——拉取/回放语义
# 不同构（fid/gen 界、ws 计入消费位），不做强行统一。


class _WSpec(NamedTuple):
    r"""归一走参元——三字母表（slot/``ArgSpec``/gullet ``Arg``）的公共槽型。

    ``kind``：``star``=``*`` 可选修饰、``opt``=``[..]`` 可选组、``mand``=
    ``{..}`` 强制组、``egrp``=``{..}``|``[..]`` 任选强制组（slot ``e``/
    hyperref 首参形）、``name``=cs 单 token 或组（``n`` 裸名参）、``marg``=
    ``m``/``v``（组或单 token、cs 止）、``bsbs``=``\\`` 的 ``[dimen]``
    （内容闸）、``accent``=``\c{c}`` 单参、``test``=``t`` 测试字符、
    ``dpair``=``d/D/r/R`` 定界对、``embell``=``e{^_}`` 逐枚修饰参、
    ``dseq``=滑窗定界参、``ugroup``=``#{`` 读到 ``lbrace`` 不消费、
    ``zero``=零宽位。
    """

    kind: str
    ws: bool = True  # 前置 space 跳读——slot ``s``/``_grp_call_end`` ``*`` 唯 False
    req: bool = False  # ``dpair`` r/R 强制位：开符失配即整走终止（d/D/槽 d 过槽）
    single_ok: bool = True  # ``marg`` 单 token 参闸（主流 ``allow_single_token``）
    role: str = "skip"  # ``text``/``opt-text`` → 不消费停界（主流回吐同位）
    env: str | None = None  # ``opt``/``dpair`` 的 ``env_opt_is_format`` 闸
    cont_ok: bool = (
        False  # 组未闭 → ``_grp_open_tail`` 跨界续扫态（spec_walk/ka-``o`` 面）
    )
    no_cs: bool = False  # ``test`` 的 cs 禁配——slot ``tC`` 有、``_grp_spec_args_end`` 无（原判差保留）
    open_c: str = ""
    close_c: str = ""
    test_c: str = ""
    e_chars: tuple[str, ...] = ()  # ``embell`` 修饰符表（``e{^_}`` 的逐枚序）
    delim_toks: tuple[Tok, ...] = ()  # ``dseq`` 滑窗目标列（gullet ``Arg.delim`` 原样）


class _WalkRes(NamedTuple):
    r"""``_walk_spec_toks`` 走参结果——三列扫面各自投影自身约定。"""

    end: int  # 实消费后界
    cand: list[
        tuple[int, int, int]
    ]  # (实参序，``{``/``[`` 位，闭后位)——``opt``/``marg``/``bsbs`` 组参
    rem: int | None  # toks 走尽/真跨界时未完元下标；``None`` = 走完或失配终止
    cont: (
        tuple | None
    )  # 跨界续扫态 ``("grp",族，残深)``/``("delim",尾列)``/``("e-arg",)``
    e_rest: tuple[str, ...] | None  # ``embell`` 走尽残符列（``_PendRem`` ``e`` 残件料）


_SLOT_ELEMS: dict[tuple[str, bool], _WSpec] = {}


def _slot_elem(s: str, *, cont_ok: bool = False) -> _WSpec:  # noqa: C901 — 槽字母各一分支，平铺即映射表
    r"""待绑参槽字母 → ``_WSpec``（上方槽形表的归一投影；``(槽, cont_ok)`` 缓存）。

    ``cont_ok`` 只给 ``_grp_spec_walk`` 的 ka-``o`` 槽——``[`` 组未闭承
    ``_grp_open_tail`` 跨界续收态；``_slots_walk_toks`` 面未闭即终止。
    """
    key = (s, cont_ok)
    el = _SLOT_ELEMS.get(key)
    if el is None:
        if s == "s":
            el = _WSpec("star", ws=False)
        elif s == "o":
            el = _WSpec("opt", cont_ok=cont_ok)
        elif s == "b":
            el = _WSpec("bsbs")
        elif s == "m":
            el = _WSpec("mand", cont_ok=cont_ok)
        elif s == "n":
            el = _WSpec("name")
        elif s == "e":
            el = _WSpec("egrp", cont_ok=cont_ok)
        elif s == "a":
            el = _WSpec("accent")
        elif s.startswith("d") and len(s) == _SLOT_PAIR_LEN:
            el = _WSpec("dpair", open_c=s[1], close_c=s[2])
        elif s.startswith("t") and len(s) == _SLOT_TEST_LEN:
            el = _WSpec("test", test_c=s[1], no_cs=True)
        else:
            el = _WSpec("zero")  # 未识槽字母——保守零宽（不产生消费）
        _SLOT_ELEMS[key] = el
    return el


def _aspec_elem(  # noqa: PLR0911 — 字母各一分支，平铺即映射表
    s: ArgSpec, role: str, env: str | None, *, single_ok: bool
) -> _WSpec:
    r"""``ArgSpec`` → ``_WSpec``（``_grp_spec_args_end`` 归一投影）。

    ``e``/``b``/``u``/``g``/无 delim 形 → ``zero``——组内不消费的原判
    （这些字母只在 ``_args_tok`` 流侧有对价）。
    """
    k = s.kind
    if k in ("m", "v"):
        return _WSpec("marg", single_ok=single_ok, role=role)
    if k == "n":
        return _WSpec("name", role=role)
    if k in ("o", "O"):
        return _WSpec("opt", role=role, env=env)
    if k == "s":
        return _WSpec("star")
    if k == "t" and s.delim:
        return _WSpec("test", test_c=s.delim[0])
    if k in ("d", "D", "r", "R") and s.delim:
        return _WSpec(
            "dpair",
            req=k in ("r", "R"),
            open_c=s.delim[0],
            close_c=s.delim[-1],
            role=role,
            env=env if s.delim != "<>" else None,  # ``d<>`` 叠层恒版式——原判豁免
        )
    return _WSpec("zero")


def _gspec_elem(a: Arg) -> _WSpec:  # noqa: PLR0911 — 字母各一分支，平铺即映射表
    r"""Gullet ``Arg`` → ``_WSpec``（``_grp_spec_walk`` 归一投影）。

    ``literal_match``/``eq``/空 delim/``brace_after`` 形 → ``zero``。
    ``m``/``o`` 组未闭承 ``_grp_open_tail`` 跨界续收态（``cont_ok``）。
    """
    k = a.kind
    if k == "m":
        return _WSpec("marg", cont_ok=True)
    if k == "o":
        return _WSpec("opt", cont_ok=True)
    if k == "star":
        return _WSpec("star")
    if k == "e" and a.delim:
        return _WSpec("embell", e_chars=tuple(dict.fromkeys(d.text for d in a.delim)))
    if k == "delim" and a.delim:
        return _WSpec("dseq", delim_toks=tuple(a.delim))
    if k == "until_group":
        return _WSpec("ugroup")
    return _WSpec("zero")


#: ``if*`` 界标路径的名/表达式槽组数——etoolbox/boolexpr/biblatex 测试族
#: 的首 N 个 ``{..}`` 是机器槽（toggle/bool/cs/field/比较元），不是散文；
#: 吸收进界标覆盖后 ``{T}{F}`` 支仍留 surface 照译。``\newif`` 旗标
#: （``\ifdraft``/``\ifmmode`` 等）与 ``\ifx`` 比较没有花括号参——不入表。
_COND_GROUP_ARGS = {
    "iftoggle": 1,
    "ifbool": 1,
    "ifboolexpr": 1,
    "ifboolexpe": 1,
    "ifthenelse": 1,
    "ifcsdef": 1,
    "ifcsundef": 1,
    "ifcsempty": 1,
    "ifcsvoid": 1,
    "ifcsmacro": 1,
    "ifstrempty": 1,
    "ifblank": 1,
    "ifnumodd": 1,
    "ifundef": 1,
    "ifdefempty": 1,
    "ifdefvoid": 1,
    "iffieldundef": 1,
    "iflistundef": 1,
    "ifnameundef": 1,
    "ifentrytype": 1,
    "ifentryseen": 1,
    "ifkeyword": 1,
    "ifcategory": 1,
    "ifnodedefined": 1,
    "ifundefined": 1,
    "ifstrequal": 2,
    "ifcsstring": 2,
    "ifdefstring": 2,
    "ifdefequal": 2,
    "ifnumequal": 2,
    "ifnumgreater": 2,
    "ifnumless": 2,
    "ifdimequal": 2,
    "ifdimgreater": 2,
    "ifdimless": 2,
    "ifnumcomp": 3,
    "ifdimcomp": 3,
}
