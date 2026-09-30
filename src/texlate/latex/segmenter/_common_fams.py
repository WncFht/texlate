r"""``latex.segmenter._common_fams`` — 分派族表与行判据谓词（``_common`` god-file 机械拆分叶）。

族 tag → 行判据单源 ``_FAM_BIND`` + ``_fams`` 序列表投影：三面分派表
（``mainloop._DISPATCH_FAMS``/``pending._GRP_SURFACE_FAMS``/
``pending._PEND_SPEC_FAMS``）共享绑定。``_cite_ref_type``/``_accent_cs``/
``_inline_lit_cs`` 名级谓词 + ``_MATH_TEXTARG`` 数学内正文参族 + 行匹配
小常量（``_VERB_LIKE``/``_ENV_CS``/``_MATH_*_CS``）。
"""

from __future__ import annotations

from texlate.latex.model import PhType
from texlate.latex.tables import (
    ACCENT_CHARS,
    BOUNDARY_NAMES,
    BOX_TAIL_NAMES,
    CHUNK_ARG_NAMES,
    CITE_NAMES,
    COND_RX,
    DIMEN_TAIL_KIND,
    FONT_SWITCHES,
    INLINE_LITERAL_CMDS,
    INPUT_SCAN_CMDS,
    PAIR_BLOCK_ALL,
    PROTECT_BLOCK_NAMES,
    PROTECT_NAMES,
    REF_NAMES,
    TRANSPARENT_HEAD_SPEC,
    TRANSPARENT_NAMES,
)

# 数学内正文参命令：``{..}`` 参重进文本态，体内 ``$`` 属组内配对、不关外
# 层数学——``_on_math`` 体扫遇此族整参跳扫（``\text{...$x$...}`` 在内层
# ``$`` 截断外层 = 0806.3472 ``missing_character`` 残留面）。``parbox`` 类
# 多参命令不在列（正文非首参，定序跳扫够不着）。
_MATH_TEXTARG_OPT_CAP = 2  # ``makebox``/``framebox`` 式 ``[opt]`` 前缀上限
_MATH_TEXTARG = frozenset(
    {
        "text",
        "intertext",
        "shortintertext",
        "mbox",
        "hbox",
        "fbox",
        "makebox",
        "framebox",
        "emph",
        "textnormal",
        "textrm",
        "textit",
        "textbf",
        "textsf",
        "texttt",
        "textsc",
        "textsl",
        "textup",
        "textmd",
    }
)


def _cite_ref_type(name: str) -> PhType | None:
    r"""cite/ref 词族 → ``PhType``（``_dispatch`` 6/7 行与 ``_group_surface`` 共用）。

    ``href``/``hyperref`` 带可译 text 参不在 REF 列——``*ref`` 后缀规则会把
    ``[label]{text}`` 的 text 整吞进 ``[[REF]]``（两处分派必须同一排除集，
    单边漂移即丢 text 参）。
    """
    if name in CITE_NAMES or name.startswith("cite"):
        return PhType.CITE
    if name in REF_NAMES or (
        name.endswith("ref")
        and name not in TRANSPARENT_NAMES
        and name not in ("href", "hyperref")
    ):
        return PhType.REF
    return None


def _accent_cs(name: str) -> bool:
    r"""Accent 族行谓词：``\c{c}``/``\~n`` 单参保护——``_DISPATCH_FAMS``/``_GRP_SURFACE_FAMS``/``_PEND_SPEC_FAMS`` 三表与 ``_dispatch`` 16c 行同判据。"""
    return len(name) == 1 and name in ACCENT_CHARS


def _inline_lit_cs(name: str) -> bool:
    r"""行内字面行谓词：符号/品牌/旧式字体开关/无参单字符命令——三镜像表与 ``_dispatch`` 17 行同判据。"""
    return (
        name in INLINE_LITERAL_CMDS
        or name in FONT_SWITCHES
        or (len(name) == 1 and not name.isalpha())
    )


# ------------------------------------------------------------------ 分派族表

# 行匹配判据小常量——三面投影共享（原 mainloop/pending 各自本地定义重份）。
_VERB_LIKE = ("verb", "verb*", "lstinline")
_ENV_CS = ("begin", "end")
_MATH_OPEN_CS = ("[", "(")
_MATH_CLOSE_CS = ("]", ")")
_MATH_DELIM_CS = ("[", "(", "]", ")")

#: 族 tag → 行判据单源：名集 | ``str`` 单名 | 谓词 | ``None`` 动态行
#: （宏表/argspec/探针裁决——名级不可静态判定）。三面分派表
#: ``mainloop._DISPATCH_FAMS``/``pending._GRP_SURFACE_FAMS``/
#: ``pending._PEND_SPEC_FAMS`` 共享本绑定——各面**行序**是分派语义
#: 不可约（主流 ``math-open`` 殿后而组面抢先），绑定才是共享数据；
#: 新族只在本表登记一次，各面 ``_fams`` 序列表自行取舍。
_FAM_BIND: dict[str, object] = {
    "verb": _VERB_LIKE,
    "env": _ENV_CS,
    "cite-ref": _cite_ref_type,
    "protect": PROTECT_NAMES,
    "href": "href",
    "hyperref": "hyperref",
    "input-scan": INPUT_SCAN_CMDS,
    "chunk-arg": CHUNK_ARG_NAMES,
    "protect-block": PROTECT_BLOCK_NAMES,
    "transparent-head": TRANSPARENT_HEAD_SPEC,
    "box-tail": BOX_TAIL_NAMES,
    "transparent": TRANSPARENT_NAMES,
    "boundary": BOUNDARY_NAMES,
    "endinput": "endinput",
    "cond": COND_RX.match,
    "math-open": _MATH_OPEN_CS,
    "math-close": _MATH_CLOSE_CS,
    "math-delim": _MATH_DELIM_CS,
    "bsbs": "\\",
    "accent": _accent_cs,
    "inline-literal": _inline_lit_cs,
    "macro": None,  # 主流 row18：gullet 宏表 env_begin/env_end/opaque/math
    "env-macro": None,  # 组内对价：env_begin/env_end 宏端点
    "opaque": None,  # 组内对价：opaque/math 宏 spec 走参（_grp_spec_walk 余量臂）
    "pair-block": PAIR_BLOCK_ALL,  # cs 对界 DSL 块（W29 pinlabel）
    "argspec": None,
    "keyarg": None,  # _keyarg_tail 宏体尾 key-arg（pend 面独有）
    "tail": DIMEN_TAIL_KIND,  # 非 BOUNDARY 的 dimen/assign 尾参（组面独有）
    "unknown": None,  # 主流 row19：尾参扫→keyarg→argspec→探针→逐字
    "probe": None,  # 组面终端：_grp_probe_end → CMD/逐字
}


def _fams(*order: str) -> tuple[tuple[str, object], ...]:
    """族序列表 → 行投影：``(tag, _FAM_BIND[tag])``——未登记 tag 即 KeyError。"""
    return tuple((tag, _FAM_BIND[tag]) for tag in order)
