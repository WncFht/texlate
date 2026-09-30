r"""L0 规则校验层 —— stdlib always-on，src↔zh 相对判定（规格 docs/spec/validate.md）。

定位：校验链第一层，LLM 每返回一个 chunk 立即校验（实测 0.57ms/对）。
独立于任何 LaTeX 解析器（pylatexenc 静默截断的教训——校验器必须异构），
也是 node 不可用时的兜底路径。

设计原则 = "译文不得比原文更坏"：每条检查都是 src↔zh 比较而非 zh 绝对判定，
src 自带的不平衡/不一致不追责（继承容忍），只报 zh 相对 src 的新增损伤。

十四条规则（docs/spec/validate.md 表 + E21/E22 修订口径 + 注释区/粘合/回显/ph_in_cs/裸 cs/注释尾段/残英补丁）：

  placeholder  ``[[TYPE_n]]``/``[[SL]]``/``[[PL]]`` multiset diff + lev≤2 修复建议；
               E22：严格序守恒降为 warn（``of X``→``X 的`` 合法换序占违例 ~95%），
               硬判据留结构占位符脱位（BIBITEM 行首锚定 + COMMENT 整行锚定：
               ``%`` 展开吞到 EOL，同行非注释邻居皆死字节/splice 残留）。
               注释豁免只盖内容差异——zh 注释区净多出的占位符是 splice 字面
               残留，仍报 error（sabotage 实测逃逸：臆造 ``[[MATH_966]]``
               写进 ``%`` 行）。
  brace        ``{}`` 平衡（``\\{`` ``\\}`` 转义、``%`` 注释豁免）。
  env          ``\\begin/\\end`` 栈配对 + 环境名 multiset 签名差分。
  key          ``\\cite*/\\*ref/\\label/\\bibitem/\\bibliography`` key multiset。
  math         未转义 ``$`` 计数 + ``\\(\\)`` ``\\[\\]`` 成对。
  length       剥占位符/cs 后 token 代理比带 [0.3,3.0] 外 → error（退化
               坍缩/膨胀拒收，E24——char 级旧口径因 CJK 密度 241 假离群
               弃用，token 代理带经 qualbase-2026-09-18 全池标定零误伤）；
               人名/专名列 src 上界放宽 4.0（音译+原文括号注释合法膨胀）；
               剥占位符后 CJK 占比「疑似未翻译」仍 warn。
  same_source  剥占位符/cs + 空白折叠 + 小写后 src==zh 整段回显 → error
               （``[[BIB_`` bib 直通/剥后 <10 token 短残段豁免——输出=输入
               是正确态；人名/专名列 verbatim 回显豁免——名单留拉丁原名
               即正确态；仅规范化等值比较，近似匹配会误伤邮箱/数学残段）。
  residual_en  zh prose 按 CJK 切非 CJK run，verbatim ⊆src（est≥10）或
               混血长句（≥8 词且 ≥40 拉丁字母）→ error（seq-49/51 实证：
               行级修复原文回退/模型半译在中文段里留整句英文，same_source
               只拦整段回显、length 的 CJK 占比 warn 不闸）；``[[BIB_`` 与
               零 CJK zh 豁免归 same_source/length 管辖，人名/专名列
               （≥70% 首字母大写）豁免。判定口径 = ``textutil.residual_en_net``，
               与 pipeline ``_intercept_residual_en`` 逐字节一致。
  macro        zh 新增控制序列 diff=error（E24 全档拒收：texglot 同口径
               ``\\[a-zA-Z@]`` 控制词可携 prompt-injection 直进 .tex；
               ``\\.`` 转义族是 bs 类本不入 cs 计数天然豁免；含非 ASCII
               融合 cs ``\\和`` 与结构族同档）；E21/E22：src→zh 方向
               脆弱间距命令（``\\ `` ``\\,`` ``\\;`` ``\\:`` ``\\!`` ``~``）
               计数差升硬判据 cs_dropped，其余丢失 cs 报 warn。
  item_glue    ``\\item`` 紧跟 ASCII 字母粘成 ``\\itemFSU`` 类非法 cs（管线引入
               签名，8 篇实证 Undefined cs 编译炸弹）——zh 净多出计数 → warn；
               ``\\itemsep`` 等合法 cs 与 src 自带粘连靠 src↔zh 净差豁免。
  ph_in_cs     ``\\cs名[[PH]]字母`` 双侧夹持签名 → error（splice 逐字节替换
               后断 cs 成未定义命令、载荷不可复原——不进 fixloop，走重译/
               回退；``\\cs[[PH]]`` 尾邻是合法高频形不判，注释区豁免，
               src 同形按净差豁免）。
  bare_cs     译文裸 cs 注入两子类 → error（realpostfix2 0905.4907：
               ``\alpha 发射体`` 数学 cs 落文本域 → Missing $ 炸弹；
               ``\itemOC``/``\linebreakGF`` 前缀+含大写后缀粘合 → 未定义
               cs 炸弹）。泛新增 cs E24 起归 macro error，本规则只管
               编译即炸的位置签名——命中名在 macro 泛 error 报表同现
               一条（有意分层双报：泛条目不带文本域/粘合前缀定位）。
  protocol_echo 交付 zh 净多出协议字面 → error（repro-2410b §4b：corrector
               三段式节标/L0 反馈消息/``slot_validation_failures``/
               ``[compile_error]`` 被当正文回显——multiset 可吻合而载荷脏，
               回显行里 ``[[COMMENT_n]]`` splice 出 ``%`` 吞掉同行结构 ``}``
               实测 early_eof）。词表与 bench ``DIRTY_SIGS`` 同款同序；
               ``[这是译文]``/``[word]`` 合法产出不在表内不误伤。
  comment_eof  zh 尾段未终结注释（``[[COMMENT_n]]``/字面 ``%`` 到 EOF 无
               ``\n``）→ error（stagerun-rt1 ``\@xdblarg`` runaway 族 ×4
               cell 同形：corrector 臂丢注释终结换行，splice 接缝把 ``}``
               吞进 ``%`` 行）；src 尾段同形豁免。

实测基线（1636 例）：10 类破坏 100% 检出、
313 干净对 0 error-FP。

god-split: 实现体按域拆进同包 8 叶——``l0.report``（Severity/Issue/
L0Report verdict 类型）、``l0.lex``（``_lex`` 词法扫描 + ``_Ctx``
共享预处理视图）、``l0.ph``（占位符全域：multiset/lev 配对/行锚定/
注释区专项）、``l0.struct``（brace/env/key/math 结构配对）、
``l0.prose``（same_source/length/residual_en 散文质量）、``l0.cs``
（macro/item_glue/ph_in_cs/bare_cs/dangerous_cs 控制序列安全）、
``l0.guard``（protocol_echo/comment_eof 交付守卫）、``l0.main``
（``_CHECKERS`` 全表 + ``CACHE_VETO_RULES`` + 对外入口）。本文件是
PEP 562 惰性门面（同 ``seqpos/__init__``/``worker/compile`` 形制）
——平名经 ``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析
并缓存，``l0.X`` 公共面与 ``from  import X``/``l0._x`` 属性读面
不变。monkeypatch 锚点注意：patch 叶子不 patch 门面
（docs/dev/seams.md §1）——``facade.name`` 读到的恒是叶子对象，但
``setattr(facade, ...)`` 只遮蔽门面不改叶子内部互引。叶子间互引走
全路径直跨（``texlate.validate.l0_<叶>``），不经本门面。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.validate.l0.cs import (
        _NONASCII_RX,
        FRAGILE_BS,
        FRAGILE_CHARS,
        MATH_CS,
        STRUCT_CMDS,
        _check_bare_cs,
        _check_dangerous_cs,
        _check_item_glue,
        _check_macro,
        _check_ph_in_cs,
        _cs_names,
        _cs_names_toks,
        _macro_new_issues,
        bare_cs_net,
        dangerous_cs_net,
        ph_in_cs_net,
    )
    from texlate.validate.l0.guard import (
        _ECHO_SIGS,
        _check_comment_eof,
        _check_protocol_echo,
        _tail_unterminated_comment,
    )
    from texlate.validate.l0.lex import (
        _Ctx,
        _est_tokens,
        _lex,
        _prose,
        cached_property,
        mask_comments,
        re,
    )
    from texlate.validate.l0.main import (
        _CHECKERS,
        CACHE_VETO_RULES,
        pair_feedback,
        validate_pair,
    )
    from texlate.validate.l0.ph import (
        _COMMENT_LINE_RX,
        _COMMENT_TAIL_RX,
        _LEV_CAP,
        _PH_CORE_RX,
        COMMENT_PH_RX,
        PH_ANY_LIKE_RX,
        PH_FUZZY_RX,
        STRUCTURAL_PH_RX,
        Counter,
        _check_ph_anchor,
        _check_placeholder,
        _line_of,
        _line_tail,
        _pair_placeholder_typos,
        _ph_in_comments,
        _ph_max_pairs,
        _ph_typo_adjacency,
        lev_capped,
    )
    from texlate.validate.l0.prose import (
        _MIN_LATIN_FOR_CJK_CHECK,
        _MIN_PROSE_TOKENS,
        _NONLING_RX,
        _RESID_EN_SHOW,
        CJK_RX,
        CJK_SHARE_MIN,
        TOKEN_RATIO_HI,
        TOKEN_RATIO_HI_NAMELIST,
        TOKEN_RATIO_LO,
        _check_length,
        _check_residual_en,
        _check_same_source,
        _cjk_latin_counts,
        name_list_prose,
        residual_en_net,
    )
    from texlate.validate.l0.report import (
        Issue,
        L0Report,
        Severity,
        StrEnum,
        annotations,
        dataclass,
        field,
    )
    from texlate.validate.l0.struct import (
        _BRACE_SEQ_RX,
        _ENV_CHECK_TAIL_LIMIT,
        ENV_RX,
        KEY_CMD_RX,
        Final,
        _brace_profile,
        _brace_profile_toks,
        _check_brace,
        _check_env,
        _check_key,
        _check_math,
        _env_signature,
        _env_signature_masked,
        _env_tokens,
        _key_multiset,
        _key_multiset_masked,
        _math_profile,
        _math_profile_toks,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "cs": (
        "FRAGILE_BS",
        "FRAGILE_CHARS",
        "MATH_CS",
        "STRUCT_CMDS",
        "_NONASCII_RX",
        "_check_bare_cs",
        "_check_dangerous_cs",
        "_check_item_glue",
        "_check_macro",
        "_check_ph_in_cs",
        "_cs_names",
        "_cs_names_toks",
        "_macro_new_issues",
        "bare_cs_net",
        "dangerous_cs_net",
        "ph_in_cs_net",
    ),
    "guard": (
        "_ECHO_SIGS",
        "_check_comment_eof",
        "_check_protocol_echo",
        "_tail_unterminated_comment",
    ),
    "lex": (
        "TYPE_CHECKING",
        "_Ctx",
        "_est_tokens",
        "_lex",
        "_prose",
        "cached_property",
        "mask_comments",
        "re",
    ),
    "main": (
        "CACHE_VETO_RULES",
        "_CHECKERS",
        "pair_feedback",
        "validate_pair",
    ),
    "ph": (
        "COMMENT_PH_RX",
        "Counter",
        "PH_ANY_LIKE_RX",
        "PH_FUZZY_RX",
        "STRUCTURAL_PH_RX",
        "_COMMENT_LINE_RX",
        "_COMMENT_TAIL_RX",
        "_LEV_CAP",
        "_PH_CORE_RX",
        "_check_ph_anchor",
        "_check_placeholder",
        "_line_of",
        "_line_tail",
        "_pair_placeholder_typos",
        "_ph_in_comments",
        "_ph_max_pairs",
        "_ph_typo_adjacency",
        "lev_capped",
    ),
    "prose": (
        "CJK_RX",
        "CJK_SHARE_MIN",
        "TOKEN_RATIO_HI",
        "TOKEN_RATIO_HI_NAMELIST",
        "TOKEN_RATIO_LO",
        "_MIN_LATIN_FOR_CJK_CHECK",
        "_MIN_PROSE_TOKENS",
        "_NONLING_RX",
        "_RESID_EN_SHOW",
        "_check_length",
        "_check_residual_en",
        "_check_same_source",
        "_cjk_latin_counts",
        "name_list_prose",
        "residual_en_net",
    ),
    "report": (
        "Issue",
        "L0Report",
        "Severity",
        "StrEnum",
        "annotations",
        "dataclass",
        "field",
    ),
    "struct": (
        "ENV_RX",
        "Final",
        "KEY_CMD_RX",
        "_BRACE_SEQ_RX",
        "_ENV_CHECK_TAIL_LIMIT",
        "_brace_profile",
        "_brace_profile_toks",
        "_check_brace",
        "_check_env",
        "_check_key",
        "_check_math",
        "_env_signature",
        "_env_signature_masked",
        "_env_tokens",
        "_key_multiset",
        "_key_multiset_masked",
        "_math_profile",
        "_math_profile_toks",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "CACHE_VETO_RULES",
    "CJK_RX",
    "CJK_SHARE_MIN",
    "COMMENT_PH_RX",
    "ENV_RX",
    "FRAGILE_BS",
    "FRAGILE_CHARS",
    "KEY_CMD_RX",
    "MATH_CS",
    "PH_ANY_LIKE_RX",
    "PH_FUZZY_RX",
    "STRUCTURAL_PH_RX",
    "STRUCT_CMDS",
    "TOKEN_RATIO_HI",
    "TOKEN_RATIO_HI_NAMELIST",
    "TOKEN_RATIO_LO",
    "TYPE_CHECKING",
    "_BRACE_SEQ_RX",
    "_CHECKERS",
    "_COMMENT_LINE_RX",
    "_COMMENT_TAIL_RX",
    "_ECHO_SIGS",
    "_ENV_CHECK_TAIL_LIMIT",
    "_LEV_CAP",
    "_MIN_LATIN_FOR_CJK_CHECK",
    "_MIN_PROSE_TOKENS",
    "_NONASCII_RX",
    "_NONLING_RX",
    "_PH_CORE_RX",
    "_RESID_EN_SHOW",
    "Counter",
    "Final",
    "Issue",
    "L0Report",
    "Severity",
    "StrEnum",
    "_Ctx",
    "_brace_profile",
    "_brace_profile_toks",
    "_check_bare_cs",
    "_check_brace",
    "_check_comment_eof",
    "_check_dangerous_cs",
    "_check_env",
    "_check_item_glue",
    "_check_key",
    "_check_length",
    "_check_macro",
    "_check_math",
    "_check_ph_anchor",
    "_check_ph_in_cs",
    "_check_placeholder",
    "_check_protocol_echo",
    "_check_residual_en",
    "_check_same_source",
    "_cjk_latin_counts",
    "_cs_names",
    "_cs_names_toks",
    "_env_signature",
    "_env_signature_masked",
    "_env_tokens",
    "_est_tokens",
    "_key_multiset",
    "_key_multiset_masked",
    "_lex",
    "_line_of",
    "_line_tail",
    "_macro_new_issues",
    "_math_profile",
    "_math_profile_toks",
    "_pair_placeholder_typos",
    "_ph_in_comments",
    "_ph_max_pairs",
    "_ph_typo_adjacency",
    "_prose",
    "_tail_unterminated_comment",
    "annotations",
    "bare_cs_net",
    "cached_property",
    "dangerous_cs_net",
    "dataclass",
    "field",
    "lev_capped",
    "mask_comments",
    "name_list_prose",
    "pair_feedback",
    "ph_in_cs_net",
    "re",
    "residual_en_net",
    "validate_pair",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"{__package__}.{leaf}"), name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return __all__


def _export_drift() -> list[str]:
    """``__all__``/``_LEAF_EXPORTS``/本地公共名三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。三向覆盖：

    - ``_LAZY`` 键全进 ``__all__``;
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链 (``_LEAF_EXPORTS``
      配名叶子不提供) 与幽灵条 (既非叶子名也非本地名) 在此曝，是首访
      ``AttributeError`` 唯一的提前闸;
    - 本地公共名 (本模块定义的函数/类) 全进 ``__all__``。

    审计实载全部叶子，只供测试调用，装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = [
        f"{name} in _LEAF_EXPORTS but missing from __all__"
        for name in _LAZY
        if name not in __all__
    ]
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    drift += [
        f"leaf stem {stem!r} shadows an exported name (rename the leaf)"
        for stem in _LEAF_EXPORTS
        if stem in _LAZY
    ]
    for name in __all__:
        try:
            getattr(mod, name)
        except Exception as exc:  # noqa: BLE001 -- 审计兜全漂移，非首错即死
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and (
            isinstance(v, dict)
            or (callable(v) and getattr(v, "__module__", None) == __name__)
        )
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
