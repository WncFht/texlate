r"""文本小件单源 —— 遮盖视图/校验签名/env 读取的跨层宿主包。

``textutil.py`` C1 拆分产物：公共面经本 facade 全量 re-export——
``from texlate.textutil import X`` 与 ``textutil.X`` 属性面逐名守恒，
``__all__`` 原样。实现按域分叶，叶间单向引用不回引 facade：

- ``decls``：文档声明/结构探测正则族（docclass/docstyle/input/声明名清洗）。
- ``cite``：cite/bib 键面词法——``\cite`` 族/``\bibitem``/aux 陈旧键的
  键表抽取正则（跨层共享件，C3 归位预置）。
- ``mask``：``mask_comments``/``mask_tex`` 等长遮盖机 + 逐字/失活环境
  注册表（``VERBATIM_ENVS``/``DEAD_ENVS``）+ 遮盖视图迭代件 +
  死尾截断面（``DEAD_TAIL_RX``/``dead_tail_view``/``live_tex``）。
- ``cjk``：排序不相交区间的 bisect 判定件 + ``CJK_RANGES``/``CJK_RX``/
  ``is_cjk_cp`` 码点面。
- ``encoding``：arXiv 源码字节 → 编码判定/解码簇（``sniff_tex_encoding``/
  ``decode_tex``/``decode_tex_with``/``EncodingVerdict``）。
- ``ifscan``：条件栈字面扫描器（``scan_ifs``/``IfScan``——fixloop
  ``unclosed_if_close*`` 共用件）。
- ``jsonl``：flock 串行化 jsonl 追加件（``append_jsonl``——share 索引
  与 fixloop CaseSink 共用）。
- ``nets``：校验域知识件——``*_net`` 缺陷签名检测簇（``bare_cs_net``/
  ``ph_in_cs_net``/``residual_en_net``）+ ``MATH_CS``/``cs_events_spans``
  支撑件 + ``JSON_FENCE_RX``/``PH_*``/``prose_text``/``est_tokens``/
  ``lev_capped`` 共享口径 + 接缝判据（``cs_letter_tail_rx``/
  ``needs_seam_space``——原 ``segmenter/_common`` 下沉）。消费方在
  validate/xlat/fixloop 层，迁往任一消费层都会破坏 import 面
  （validate 不能 import xlat），故宿于底叶。
- ``osutil``：os 边界小件——``env_flag``/``env_str``/``env_float``/
  ``env_raw``/``env_opt`` 读取族 + ``data_root``/``set_data_dir`` +
  ``safe_resolve``/``safe_is_file``/``safe_is_dir``/``safe_rel`` 路径防御 +
  ``utc_now``/``filtered_env``/``DEFAULT_BIND_*`` 派生共享件。
- ``secrets``：secret 形态脱敏表两档单源——``SECRET_PATTERNS``（严档，
  ``xlat._errors`` 错误文本道）+ ``SECRET_LOG_PATTERNS``（宽档，
  ``logsetup``/``logredact`` 日志道），共享行字面只定义一次。
- ``targate``：tar 伪装二进制闸（``_tar_disguised``/``_tar_header_ok``
  ——compile/latex 两层共用，不能锚在消费层）。
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
    SUBDOC_CHILD_RX,
    clean_decl_name,
)

# 私有转口——tests/ 钉点经 ``from texlate.textutil import _x`` 与
# ``textutil._x`` 属性面消费（各带 noqa: SLF001）；nets/osutil 私有名
# 出叶前本属 facade 模块级，同面转口保属性面逐名守恒，拆分后口径不变。
from .encoding import (  # noqa: F401
    EncodingVerdict,
    _char_class,
    _declared_name,
    _decode_tex_with_memo,
    _eol_norm,
    _scrub_c1_mojibake,
    decode_tex,
    decode_tex_with,
    sniff_tex_encoding,
)
from .ifscan import IfScan, scan_ifs
from .jsonl import append_jsonl
from .mask import (  # noqa: F401
    _MEMO_MAX_INPUT,
    _VERBATIM_BEGIN_RX,
    DEAD_ENVS,
    DEAD_TAIL_RX,
    VERBATIM_ENVS,
    _mask_tex_memo,
    dead_end_anchored,
    dead_env_end,
    dead_tail_view,
    iter_depth,
    iter_depth0,
    live_tex,
    mask_comments,
    mask_tex,
)
from .nets import (  # noqa: F401
    _BARE_CS_SCAN_RX,
    _LETTER_TAIL_RX,
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
    DANGEROUS_CS,
    JSON_FENCE_RX,
    MATH_CS,
    PH_ANY_LIKE_RX,
    PH_FUZZY_RX,
    PH_RX,
    PhIssuer,
    _cs_out_of_math,
    _keep_verbatim_run,
    _math_spans,
    bare_cs_net,
    cs_events_spans,
    cs_letter_tail_rx,
    dangerous_cs_net,
    est_tokens,
    lev_capped,
    name_list_prose,
    needs_seam_space,
    ph_in_cs_net,
    prose_text,
    residual_en_net,
)
from .osutil import (  # noqa: F401
    _TRUE_WORDS,
    DEFAULT_BIND_HOST,
    DEFAULT_BIND_PORT,
    data_root,
    env_flag,
    env_float,
    env_opt,
    env_raw,
    env_str,
    filtered_env,
    safe_is_dir,
    safe_is_file,
    safe_rel,
    safe_resolve,
    set_data_dir,
    utc_now,
)
from .secrets import SECRET_LOG_PATTERNS, SECRET_PATTERNS
from .targate import _TAR_HEADER_LEN, _tar_disguised, _tar_header_ok  # noqa: F401

__all__ = [
    "AUX_CITEKEY_RE",
    "BEGIN_DOC_RX",
    "BIBITEM_KEY_RE",
    "CITE_FAMILY_RE",
    "CJK_RANGES",
    "CJK_RX",
    "CMD_BOUNDARY",
    "CS_OR_SYM_RX",
    "DANGEROUS_CS",
    "DEAD_ENVS",
    "DEAD_TAIL_RX",
    "DECL_NAME_RX",
    "DECL_TAIL",
    "DEFAULT_BIND_HOST",
    "DEFAULT_BIND_PORT",
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
    "SECRET_LOG_PATTERNS",
    "SECRET_PATTERNS",
    "SUBDOC_CHILD_RX",
    "VERBATIM_ENVS",
    "EncodingVerdict",
    "IfScan",
    "PhIssuer",
    "append_jsonl",
    "bare_cs_net",
    "clean_decl_name",
    "cs_events_spans",
    "cs_letter_tail_rx",
    "dangerous_cs_net",
    "data_root",
    "dead_end_anchored",
    "dead_env_end",
    "dead_tail_view",
    "decode_tex",
    "decode_tex_with",
    "env_flag",
    "env_float",
    "env_opt",
    "env_raw",
    "env_str",
    "est_tokens",
    "filtered_env",
    "is_cjk_cp",
    "iter_depth",
    "iter_depth0",
    "lev_capped",
    "live_tex",
    "mask_comments",
    "mask_tex",
    "name_list_prose",
    "needs_seam_space",
    "ph_in_cs_net",
    "prose_text",
    "residual_en_net",
    "safe_is_dir",
    "safe_is_file",
    "safe_rel",
    "safe_resolve",
    "scan_ifs",
    "set_data_dir",
    "sniff_tex_encoding",
    "utc_now",
]
