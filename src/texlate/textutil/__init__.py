r"""文本小件单源 —— 遮盖视图/校验签名/env 读取的跨层宿主包。

``textutil.py`` C1 拆分产物：公共面经本 facade 全量 re-export——
``from texlate.textutil import X`` 与 ``textutil.X`` 属性面逐名守恒，
``__all__`` 原样。实现按域分叶，叶间单向引用不回引 facade：

- ``decls``：文档声明/结构探测正则族（docclass/docstyle/input/声明名清洗）。
- ``cite``：cite/bib 键面词法——``\cite`` 族/``\bibitem``/aux 陈旧键的
  键表抽取正则（跨层共享件，C3 归位预置）。
- ``mask``：``mask_comments``/``mask_tex`` 等长遮盖机 + 逐字/失活环境
  注册表（``VERBATIM_ENVS``/``DEAD_ENVS``）+ 遮盖视图迭代件。
- ``cjk``：排序不相交区间的 bisect 判定件 + ``CJK_RANGES``/``CJK_RX``/
  ``is_cjk_cp`` 码点面。
- ``encoding``：arXiv 源码字节 → 编码判定/解码簇（``sniff_tex_encoding``/
  ``decode_tex``/``decode_tex_with``/``EncodingVerdict``）。
- ``ifscan``：条件栈字面扫描器（``scan_ifs``/``IfScan``——fixloop
  ``unclosed_if_close*`` 共用件）。
- ``nets``：校验域知识件——``*_net`` 缺陷签名检测簇（``bare_cs_net``/
  ``ph_in_cs_net``/``residual_en_net``）+ ``MATH_CS``/``cs_events_spans``
  支撑件 + ``JSON_FENCE_RX``/``PH_*``/``prose_text``/``est_tokens``/
  ``lev_capped`` 共享口径。消费方在 validate/xlat/fixloop 层，迁往任一
  消费层都会破坏 import 面（validate 不能 import xlat），故宿于底叶。
- ``osutil``：os 边界小件——``env_flag``/``env_str``/``env_float``/
  ``env_raw``/``env_opt`` 读取族 + ``data_root`` + ``safe_resolve``/
  ``safe_is_file`` 路径防御。
"""

from __future__ import annotations

from .cite import AUX_CITEKEY_RE, BIBITEM_KEY_RE, CITE_FAMILY_RE
from .cjk import CJK_RANGES, CJK_RX, is_cjk_cp
from .decls import (
    BEGIN_DOC_RX,
    CMD_BOUNDARY,
    DECL_NAME_RX,
    DECL_TAIL,
    DOCCLASS_DECL_RX,
    DOCCLASS_NAMES,
    DOCCLASS_ONLY_RX,
    DOCCLASS_OPTS_RX,
    DOCCLASS_RX,
    DOCSTYLE_DECL_RX,
    DOCSTYLE_RX,
    END_DOC_RX,
    INPUT_BARE_RX,
    INPUT_BRACED_RX,
    LOADER_CMDS,
    SUBFILES_CHILD_RX,
    clean_decl_name,
)

# 私有转口——tests/ 钉点经 ``from texlate.textutil import _x`` 与
# ``textutil._x`` 属性面消费（各带 noqa: SLF001）；nets/osutil 私有名
# 出叶前本属 facade 模块级，同面转口保属性面逐名守恒，拆分后口径不变。
from .encoding import (  # noqa: F401
    _TAR_HEADER_LEN,
    EncodingVerdict,
    _char_class,
    _declared_name,
    _decode_tex_with_memo,
    _eol_norm,
    _scrub_c1_mojibake,
    _tar_disguised,
    _tar_header_ok,
    decode_tex,
    decode_tex_with,
    sniff_tex_encoding,
)
from .ifscan import IfScan, scan_ifs
from .mask import (  # noqa: F401
    _MEMO_MAX_INPUT,
    _VERBATIM_BEGIN_RX,
    DEAD_ENVS,
    VERBATIM_ENVS,
    _mask_tex_memo,
    dead_end_anchored,
    dead_env_end,
    iter_depth0,
    mask_comments,
    mask_tex,
)
from .nets import (  # noqa: F401
    _BARE_CS_SCAN_RX,
    _MIN_FUSED_PREFIX,
    _PH_IN_CS_RX,
    _RESID_EN_ADDR_RX,
    _RESID_EN_EDGE_RX,
    _RESID_EN_MIN_EST,
    _RESID_EN_MIN_LATIN,
    _RESID_EN_MIN_WORDS,
    _RESID_EN_NAME_CAP_SHARE,
    _RESID_EN_NAME_MIN_TOKENS,
    _RESID_EN_WORD_RX,
    CS_OR_SYM_RX,
    JSON_FENCE_RX,
    MATH_CS,
    PH_ANY_LIKE_RX,
    PH_FUZZY_RX,
    PH_RX,
    _cs_out_of_math,
    _keep_verbatim_run,
    _math_spans,
    bare_cs_net,
    cs_events_spans,
    est_tokens,
    lev_capped,
    ph_in_cs_net,
    prose_text,
    residual_en_net,
)
from .osutil import (  # noqa: F401
    _TRUE_WORDS,
    data_root,
    env_flag,
    env_float,
    env_opt,
    env_raw,
    env_str,
    safe_is_file,
    safe_resolve,
)

__all__ = [
    "AUX_CITEKEY_RE",
    "BEGIN_DOC_RX",
    "BIBITEM_KEY_RE",
    "CITE_FAMILY_RE",
    "CJK_RANGES",
    "CJK_RX",
    "CMD_BOUNDARY",
    "CS_OR_SYM_RX",
    "DEAD_ENVS",
    "DECL_NAME_RX",
    "DECL_TAIL",
    "DOCCLASS_DECL_RX",
    "DOCCLASS_NAMES",
    "DOCCLASS_ONLY_RX",
    "DOCCLASS_OPTS_RX",
    "DOCCLASS_RX",
    "DOCSTYLE_DECL_RX",
    "DOCSTYLE_RX",
    "END_DOC_RX",
    "INPUT_BARE_RX",
    "INPUT_BRACED_RX",
    "JSON_FENCE_RX",
    "LOADER_CMDS",
    "MATH_CS",
    "PH_ANY_LIKE_RX",
    "PH_FUZZY_RX",
    "PH_RX",
    "SUBFILES_CHILD_RX",
    "VERBATIM_ENVS",
    "EncodingVerdict",
    "IfScan",
    "bare_cs_net",
    "clean_decl_name",
    "cs_events_spans",
    "data_root",
    "dead_end_anchored",
    "dead_env_end",
    "decode_tex",
    "decode_tex_with",
    "env_flag",
    "env_float",
    "env_opt",
    "env_raw",
    "env_str",
    "est_tokens",
    "is_cjk_cp",
    "iter_depth0",
    "lev_capped",
    "mask_comments",
    "mask_tex",
    "ph_in_cs_net",
    "prose_text",
    "residual_en_net",
    "safe_is_file",
    "safe_resolve",
    "scan_ifs",
    "sniff_tex_encoding",
]
