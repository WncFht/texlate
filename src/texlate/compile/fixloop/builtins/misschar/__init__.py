"""builtins.misschar — missing_char F4 族修复原语 (C3 拆分)。

log「Missing character」行 → 码位分级 → 按类修复：表驱动字面替换
(``missing_char_fix``) / 组合附加符 accent cs 站点改写 (``accent_mark_fix``) /
``newunicodechar`` 逐字回退 + 数学域双模修 (``font_fallback``)。

读侧/规划侧机制 (``_mc_parse_log``/``_mc_table``/``_mc_hit``/``_mc_plan``
+ ``_MC_TABLE``/``_FB_FONT``/``_MATH_SHIM_CS`` 常量) 归位
``builtins.common`` —— shim 叶同消费，本叶只留修复动作本体。

C5 拆叶：实现体按修复域拆进九个 ``_mc*`` 私有兄弟叶，本文件化纯
PEP 562 惰性门面 (同 ``fixloop/engine`` 形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``misschar.X`` 公共面与 ``from ... import X``/``M._x`` 属性读面不变。
monkeypatch 锚点注意：patch 叶子不 patch 门面 —— ``misschar.name``
读到的恒是叶子对象，但 ``setattr(misschar, ...)`` 只遮蔽门面不改
叶子内部互引。叶子间互引走全路径直跨
(``texlate.compile.fixloop.builtins._mc<叶>``), 不经本门面。

叶谱：``misschar.cjk`` missing_char_fix 主体+hangul 路由+warmup /
``misschar.fallback`` font_fallback 基座 (fb 表/数学域/字体解析) /
``misschar.accent`` accent 站点改写 / ``misschar.glyph`` 宏字形/OT1 槽 /
``misschar.caret`` ``^^XX`` 字节记法 / ``misschar.fontspec`` fontspec 克隆名替 /
``misschar.fontenc`` fontenc enc 摘除 / ``misschar.nfss`` NFSS enc 三臂 /
``misschar.umath`` unicode-math 遮蔽复位。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.compile.fixloop.builtins.misschar.accent import (
        _ACCENT_CS,
        _accent_fix_text,
        _accent_site_re,
        accent_mark_fix,
    )
    from texlate.compile.fixloop.builtins.misschar.caret import (
        _C1_HI,
        _C1_LO,
        _CARET_RUN_RE,
        _CARET_TOK_RE,
        _LEAD2,
        _LEAD3,
        _LEAD4,
        _caret_decode_run,
        _caret_utf8_text,
        caret_utf8_fix,
    )
    from texlate.compile.fixloop.builtins.misschar.cjk import (
        _CJK_MECH_RE,
        _HANGUL_BANDS,
        _KO_FONT_CANDS,
        _KO_FONT_NOT,
        _KO_MECH_RE,
        _MC_WARMUP_SIZES,
        _inject_before_begindoc,
        _ko_route_snippet,
        _map_tex_files,
        _mc_apply_hangul_route,
        _mc_apply_warmup,
        _mc_plan,
        _mc_seen,
        _mc_table,
        _splice,
        _sub_literal_chars,
        mask_tex,
        missing_char_fix,
    )
    from texlate.compile.fixloop.builtins.misschar.fallback import (
        _FB_FONT,
        _FB_RANGES,
        _FONT_FILE_RE,
        _MATH_GUARD_BEGIN_RE,
        _MATH_SHIM_ARG_CS,
        _MATH_SHIM_CS,
        MATH_ENVS,
        _fb_font_resolve,
        _fb_snippet_lines,
        _in_spans,
        _inject_after_docclass,
        _inject_fallback_lines,
        _inject_math_cs_shims,
        _math_cs_shim_names,
        _math_guard_spans,
        _mc_chr,
        _mc_hit,
        _resolve_font_cands,
        cs_events_spans,
        font_fallback,
    )
    from texlate.compile.fixloop.builtins.misschar.fontenc import (
        _ENC_DEF_RE,
        _FONTENC_LOAD_RE,
        _comment_enc_decl,
        _enc_use_res,
        _strip_enc_opts,
        fontenc_enc_relax,
    )
    from texlate.compile.fixloop.builtins.misschar.fontspec import (
        _CLONE_TABLE,
        _FAM_SITE_RE,
        _FONTSPEC_FAM_CS,
        _FONTSPEC_FILEBIND_KEYS,
        _FONTSPEC_NAME_CS,
        _FS_OPT,
        _NAME_SITE_RE,
        _WEIGHT_TAIL_RE,
        _clone_fix_text,
        _font_stem,
        _is_live,
        _split_kv,
        _strip_filebind_opts,
        fontspec_clone_sub,
    )
    from texlate.compile.fixloop.builtins.misschar.glyph import (
        _CHAR_NUM_RE,
        _MACRO_GLYPH_CS,
        _OT1_CHAR_SLOTS,
        _char_num_value,
        _macro_glyph_fix_text,
        macro_glyph_fix,
    )
    from texlate.compile.fixloop.builtins.misschar.nfss import (
        _CYR_PAIRS,
        _NFSS_GLYPH_TABLES,
        _NFSS_TU_BODY,
        _NFSS_UNAVAIL_RE,
        _T2A_GLYPHS,
        _ch,
        _cs,
        _glyph_uses,
        _nfss_enc_site_re,
        _nfss_glyph_re,
        _polyfill_snippet,
        _rewrite_enc_sites,
        _scan_sites,
        nfss_cmd_enc_polyfill,
        nfss_enc_scheme_relax,
        nfss_fam_declare,
    )
    from texlate.compile.fixloop.builtins.misschar.umath import (
        _UMATH_CACHE,
        _UMATH_DEF_RX,
        _UMATH_LOAD_RX,
        _UMATH_ROW_RX,
        _brace_end,
        _cs_tok_end,
        _skip_ws,
        _umath_doc_defs,
        _umath_names,
        umath_doc_cs_restore,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "accent": (
        "_ACCENT_CS",
        "_accent_fix_text",
        "_accent_site_re",
        "accent_mark_fix",
    ),
    "caret": (
        "_C1_HI",
        "_C1_LO",
        "_CARET_RUN_RE",
        "_CARET_TOK_RE",
        "_LEAD2",
        "_LEAD3",
        "_LEAD4",
        "_caret_decode_run",
        "_caret_utf8_text",
        "caret_utf8_fix",
    ),
    "cjk": (
        "_CJK_MECH_RE",
        "_HANGUL_BANDS",
        "_KO_FONT_CANDS",
        "_KO_FONT_NOT",
        "_KO_MECH_RE",
        "_MC_WARMUP_SIZES",
        "_inject_before_begindoc",
        "_ko_route_snippet",
        "_map_tex_files",
        "_mc_apply_hangul_route",
        "_mc_apply_warmup",
        "_mc_plan",
        "_mc_seen",
        "_mc_table",
        "_splice",
        "_sub_literal_chars",
        "mask_tex",
        "missing_char_fix",
    ),
    "fallback": (
        "MATH_ENVS",
        "_FB_FONT",
        "_FB_RANGES",
        "_FONT_FILE_RE",
        "_MATH_GUARD_BEGIN_RE",
        "_MATH_SHIM_ARG_CS",
        "_MATH_SHIM_CS",
        "_fb_font_resolve",
        "_fb_snippet_lines",
        "_in_spans",
        "_inject_after_docclass",
        "_inject_fallback_lines",
        "_inject_math_cs_shims",
        "_math_cs_shim_names",
        "_math_guard_spans",
        "_mc_chr",
        "_mc_hit",
        "_resolve_font_cands",
        "cs_events_spans",
        "font_fallback",
    ),
    "fontenc": (
        "_ENC_DEF_RE",
        "_FONTENC_LOAD_RE",
        "_comment_enc_decl",
        "_enc_use_res",
        "_strip_enc_opts",
        "fontenc_enc_relax",
    ),
    "fontspec": (
        "_CLONE_TABLE",
        "_FAM_SITE_RE",
        "_FONTSPEC_FAM_CS",
        "_FONTSPEC_FILEBIND_KEYS",
        "_FONTSPEC_NAME_CS",
        "_FS_OPT",
        "_NAME_SITE_RE",
        "_WEIGHT_TAIL_RE",
        "_clone_fix_text",
        "_font_stem",
        "_is_live",
        "_split_kv",
        "_strip_filebind_opts",
        "fontspec_clone_sub",
    ),
    "glyph": (
        "_CHAR_NUM_RE",
        "_MACRO_GLYPH_CS",
        "_OT1_CHAR_SLOTS",
        "_char_num_value",
        "_macro_glyph_fix_text",
        "macro_glyph_fix",
    ),
    "nfss": (
        "_CYR_PAIRS",
        "_NFSS_GLYPH_TABLES",
        "_NFSS_TU_BODY",
        "_NFSS_UNAVAIL_RE",
        "_T2A_GLYPHS",
        "_ch",
        "_cs",
        "_glyph_uses",
        "_nfss_enc_site_re",
        "_nfss_glyph_re",
        "_polyfill_snippet",
        "_rewrite_enc_sites",
        "_scan_sites",
        "nfss_cmd_enc_polyfill",
        "nfss_enc_scheme_relax",
        "nfss_fam_declare",
    ),
    "umath": (
        "_UMATH_CACHE",
        "_UMATH_DEF_RX",
        "_UMATH_LOAD_RX",
        "_UMATH_ROW_RX",
        "_brace_end",
        "_cs_tok_end",
        "_skip_ws",
        "_umath_doc_defs",
        "_umath_names",
        "umath_doc_cs_restore",
    ),
}

_LAZY: dict[str, str] = {
    name: leaf for leaf, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "MATH_ENVS",
    "_ACCENT_CS",
    "_C1_HI",
    "_C1_LO",
    "_CARET_RUN_RE",
    "_CARET_TOK_RE",
    "_CHAR_NUM_RE",
    "_CJK_MECH_RE",
    "_CLONE_TABLE",
    "_CYR_PAIRS",
    "_ENC_DEF_RE",
    "_FAM_SITE_RE",
    "_FB_FONT",
    "_FB_RANGES",
    "_FONTENC_LOAD_RE",
    "_FONTSPEC_FAM_CS",
    "_FONTSPEC_FILEBIND_KEYS",
    "_FONTSPEC_NAME_CS",
    "_FONT_FILE_RE",
    "_FS_OPT",
    "_HANGUL_BANDS",
    "_KO_FONT_CANDS",
    "_KO_FONT_NOT",
    "_KO_MECH_RE",
    "_LEAD2",
    "_LEAD3",
    "_LEAD4",
    "_MACRO_GLYPH_CS",
    "_MATH_GUARD_BEGIN_RE",
    "_MATH_SHIM_ARG_CS",
    "_MATH_SHIM_CS",
    "_MC_WARMUP_SIZES",
    "_NAME_SITE_RE",
    "_NFSS_GLYPH_TABLES",
    "_NFSS_TU_BODY",
    "_NFSS_UNAVAIL_RE",
    "_OT1_CHAR_SLOTS",
    "_T2A_GLYPHS",
    "_UMATH_CACHE",
    "_UMATH_DEF_RX",
    "_UMATH_LOAD_RX",
    "_UMATH_ROW_RX",
    "_WEIGHT_TAIL_RE",
    "_accent_fix_text",
    "_accent_site_re",
    "_brace_end",
    "_caret_decode_run",
    "_caret_utf8_text",
    "_ch",
    "_char_num_value",
    "_clone_fix_text",
    "_comment_enc_decl",
    "_cs",
    "_cs_tok_end",
    "_enc_use_res",
    "_fb_font_resolve",
    "_fb_snippet_lines",
    "_font_stem",
    "_glyph_uses",
    "_in_spans",
    "_inject_after_docclass",
    "_inject_before_begindoc",
    "_inject_fallback_lines",
    "_inject_math_cs_shims",
    "_is_live",
    "_ko_route_snippet",
    "_macro_glyph_fix_text",
    "_map_tex_files",
    "_math_cs_shim_names",
    "_math_guard_spans",
    "_mc_apply_hangul_route",
    "_mc_apply_warmup",
    "_mc_chr",
    "_mc_hit",
    "_mc_plan",
    "_mc_seen",
    "_mc_table",
    "_nfss_enc_site_re",
    "_nfss_glyph_re",
    "_polyfill_snippet",
    "_resolve_font_cands",
    "_rewrite_enc_sites",
    "_scan_sites",
    "_skip_ws",
    "_splice",
    "_split_kv",
    "_strip_enc_opts",
    "_strip_filebind_opts",
    "_sub_literal_chars",
    "_umath_doc_defs",
    "_umath_names",
    "accent_mark_fix",
    "caret_utf8_fix",
    "cs_events_spans",
    "font_fallback",
    "fontenc_enc_relax",
    "fontspec_clone_sub",
    "macro_glyph_fix",
    "mask_tex",
    "missing_char_fix",
    "nfss_cmd_enc_polyfill",
    "nfss_enc_scheme_relax",
    "nfss_fam_declare",
    "umath_doc_cs_restore",
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
