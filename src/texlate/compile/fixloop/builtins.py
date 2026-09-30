"""builtins — fixloop 命名函数注册表 (rules.yaml `function:` 的实现侧)。

两类签名:
  - REWRITE_FNS: ``(re.Match) -> str`` —— regex_rewrite 条目的逐 match 改写
    (原型 `px_to_bp`/`keep_latin_tokens`, 算术/集合变换非纯模板)
  - TRANSFORM_FNS: ``(ctx, eng, payload, params) -> (applied, note)`` ——
    builtin_transform 条目的文件级算法改写 (原型 `option_clash_merge`,
    新增 6 条按 docs/spec/compile.md 实现)

社区贡献规则多数只需写 regex; 新算法型修复才需要往这里 PR 代码。

C3 拆分: 实现体按域拆进 ``_builtins_*`` 叶子模块, 本文件是 PEP 562 惰性
门面 (同 ``fixloop/__init__`` 形制) —— 平名经 ``_LEAF_EXPORTS`` 映射回
叶子, ``__getattr__`` 首访解析并缓存, ``builtins.X`` 公共面与
``from ... import X`` 测试面不变。叶子私名默认不回引, 缺名字的断链
面请从叶子模块直取而非恢复批发回引。
monkeypatch 锚点注意: 图形/PS 域已出叶 ``_builtins_graphics``——
``_run_convert`` 的 patch 面随调用链迁走, 测试须 patch
``_builtins_graphics._run_convert`` 而非本门面同名回引 (惰性解析下
``builtins._run_convert`` 仍可读, 但 setattr 只遮蔽门面不改叶子)。
TRANSFORM_FNS 首次访问时按 ``_TRANSFORM_KEYS`` 构建并缓存成真 dict——
``monkeypatch.setitem`` 消费面语义不变。
"""

from __future__ import annotations

import importlib
import re
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.compile.fixloop._builtins_bib import (
        bbl_format_version_rewrite,
        bbl_regen,
        bbl_stub_rewrite,
        biber_biblatex_skew_route,
        cite_in_math_mbox,
        citekey_sanitize,
        tectonic_bib_stall_route,
    )
    from texlate.compile.fixloop._builtins_common import (
        _MC_TABLE,
        PDFTEX_PRIMS,
        _inject_after_docclass,
        _live_matches,
        _mc_hit,
        _mc_parse_log,
        _mc_plan,
        _resolve_site,
    )
    from texlate.compile.fixloop._builtins_csfix import (
        _allocated_cs_names,
        cs_targeted_fix,
        ctlseq_undefine,
        primitive_clobber_rename,
        undefine_for_redef,
    )
    from texlate.compile.fixloop._builtins_docfix import (
        cs_delim_tail_fix,
        if_phantom_protect,
        pdfstring_cs_disarm,
        premature_cs_guard,
        spacefactor_atdef_wrap,
    )
    from texlate.compile.fixloop._builtins_gfx_missing import (
        _GRAPHIC_EXTS,
        _INCLUDE_GFX_RE,
        _INCLUDE_PDF_RE,
        _find_graphic_ci,
        _graphic_ref_hit,
        _opt_dim,
        _rewrite_case_refs,
        _stub_graphic_refs,
        driver_missing_image_stub,
        graphic_case_link,
        graphic_missing_placeholder,
        graphic_repair,
        includepdf_missing_stub,
        raster_pdf_rename,
    )
    from texlate.compile.fixloop._builtins_graphics import (
        _EPS_EXTS,
        _GRAPHICS_PKGS_RE,
        _GS_FLAGS,
        _INCLUDESVG_RE,
        _LOAD_OPT_RE,
        _NUMERIC_EXT_RE,
        _PS_DRIVERS,
        _SVG_CONVERTERS,
        _SVG_OPT_KEEP,
        _convert_one,
        _norm_graphic_name,
        _rewrite_eps_refs,
        _rewrite_includesvg,
        _run_convert,
        _strip_ps_driver_opts,
        _svg_convert_arm,
        _svg_convert_one,
        _try_gs_redistill,
        eps_to_pdf,
        pdf_asset_sanitize,
        pstricks_dvips_preflight,
        rotatebox_caption_pad,
        svg_prepare,
        xbb_pregen,
    )
    from texlate.compile.fixloop._builtins_layoutfix import (
        display_math_shrink,
        fffd_context_fix,
        gfx_width_clamp,
        legacy_clamp_purge,
        math_run_break,
        section_skip_floor,
        tabular_fit,
    )
    from texlate.compile.fixloop._builtins_misc import (
        aux_seed_undefined_refs,
        cjk_env_relax,
        docstrip_generate,
        eps_converted_alias,
        extract_tar_blobs,
        float_h_demote,
        float_opt_cs_expand,
        graphics_include_strip,
        harvest_build_directives,
        latex209_upgrade,
        main_wrapper_promote,
        non_utf8_recode,
        para_loosen,
        pfa_to_pfb,
        plain_format_detect,
        purge_corrupt_intermediates,
        restore_support_from_src,
        subfile_docclass_strip,
        tcolorbox_breakable_inject,
    )
    from texlate.compile.fixloop._builtins_misschar import (
        accent_mark_fix,
        caret_utf8_fix,
        font_fallback,
        fontenc_enc_relax,
        fontspec_clone_sub,
        macro_glyph_fix,
        missing_char_fix,
        nfss_cmd_enc_polyfill,
        nfss_enc_scheme_relax,
        nfss_fam_declare,
        umath_doc_cs_restore,
    )
    from texlate.compile.fixloop._builtins_paralong import (
        para_longize,
    )
    from texlate.compile.fixloop._builtins_pkgload import (
        _detach_physics_loads,
        font_sub_shim,
        option_clash_merge,
        physics_stub_detach,
        shipped_sty_input_wrap,
        siunitx_incompat_peace,
        strip_inputenc,
        xy_option_load,
    )
    from texlate.compile.fixloop._builtins_shim import (
        bm_mathchar_wrap,
        bundled_class_shadow,
        cs_rebind,
        doc_absent_stub,
        driver_tfm_hoist,
        fileset_relocate,
        font_cs_shim,
        generated_stub,
        journal_cs_polyfill,
        legacy_pkg_shim,
        pdftex_prim_polyfill,
        revtex209_surface_polyfill,
        shim_pkgs_in_use,
        svjour_clo_stub,
        undefined_env_polyfill,
    )
    from texlate.compile.fixloop._builtins_slotrev import (
        slot_arg_revert,
    )
    from texlate.compile.fixloop._builtins_vendored import (
        _provides_date,
        _vendor_root,
        _vendored_source,
        amsmath_family_retire,
        find_vendored_shadows,
        fontspec_kernel_shadow_retire,
        revtex_era_retire,
        vendored_fetch,
        vendored_fetch_multi,
        vendored_shadow_isolate,
    )

    TRANSFORM_FNS: dict[str, Callable[..., tuple[bool, str]]]

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_builtins_bib": (
        "bbl_format_version_rewrite",
        "bbl_regen",
        "bbl_stub_rewrite",
        "biber_biblatex_skew_route",
        "cite_in_math_mbox",
        "citekey_sanitize",
        "tectonic_bib_stall_route",
    ),
    "_builtins_common": (
        "_MC_TABLE",
        "PDFTEX_PRIMS",
        "_inject_after_docclass",
        "_live_matches",
        "_mc_hit",
        "_mc_parse_log",
        "_mc_plan",
        "_resolve_site",
    ),
    "_builtins_csfix": (
        "_allocated_cs_names",
        "cs_targeted_fix",
        "ctlseq_undefine",
        "primitive_clobber_rename",
        "undefine_for_redef",
    ),
    "_builtins_docfix": (
        "cs_delim_tail_fix",
        "if_phantom_protect",
        "pdfstring_cs_disarm",
        "premature_cs_guard",
        "spacefactor_atdef_wrap",
    ),
    "_builtins_gfx_missing": (
        "_GRAPHIC_EXTS",
        "_INCLUDE_GFX_RE",
        "_INCLUDE_PDF_RE",
        "_find_graphic_ci",
        "_graphic_ref_hit",
        "_opt_dim",
        "_rewrite_case_refs",
        "_stub_graphic_refs",
        "driver_missing_image_stub",
        "graphic_case_link",
        "graphic_missing_placeholder",
        "graphic_repair",
        "includepdf_missing_stub",
        "raster_pdf_rename",
    ),
    "_builtins_graphics": (
        "_EPS_EXTS",
        "_GRAPHICS_PKGS_RE",
        "_GS_FLAGS",
        "_INCLUDESVG_RE",
        "_LOAD_OPT_RE",
        "_NUMERIC_EXT_RE",
        "_PS_DRIVERS",
        "_SVG_CONVERTERS",
        "_SVG_OPT_KEEP",
        "_convert_one",
        "_norm_graphic_name",
        "_rewrite_eps_refs",
        "_rewrite_includesvg",
        "_run_convert",
        "_strip_ps_driver_opts",
        "_svg_convert_arm",
        "_svg_convert_one",
        "_try_gs_redistill",
        "eps_to_pdf",
        "pdf_asset_sanitize",
        "pstricks_dvips_preflight",
        "rotatebox_caption_pad",
        "svg_prepare",
        "xbb_pregen",
    ),
    "_builtins_layoutfix": (
        "display_math_shrink",
        "fffd_context_fix",
        "gfx_width_clamp",
        "legacy_clamp_purge",
        "math_run_break",
        "section_skip_floor",
        "tabular_fit",
    ),
    "_builtins_misc": (
        "aux_seed_undefined_refs",
        "cjk_env_relax",
        "docstrip_generate",
        "eps_converted_alias",
        "extract_tar_blobs",
        "float_h_demote",
        "float_opt_cs_expand",
        "graphics_include_strip",
        "harvest_build_directives",
        "latex209_upgrade",
        "main_wrapper_promote",
        "non_utf8_recode",
        "para_loosen",
        "pfa_to_pfb",
        "plain_format_detect",
        "purge_corrupt_intermediates",
        "restore_support_from_src",
        "subfile_docclass_strip",
        "tcolorbox_breakable_inject",
    ),
    "_builtins_misschar": (
        "accent_mark_fix",
        "caret_utf8_fix",
        "font_fallback",
        "fontenc_enc_relax",
        "fontspec_clone_sub",
        "macro_glyph_fix",
        "missing_char_fix",
        "nfss_cmd_enc_polyfill",
        "nfss_enc_scheme_relax",
        "nfss_fam_declare",
        "umath_doc_cs_restore",
    ),
    "_builtins_paralong": ("para_longize",),
    "_builtins_pkgload": (
        "_detach_physics_loads",
        "font_sub_shim",
        "option_clash_merge",
        "physics_stub_detach",
        "shipped_sty_input_wrap",
        "siunitx_incompat_peace",
        "strip_inputenc",
        "xy_option_load",
    ),
    "_builtins_shim": (
        "bm_mathchar_wrap",
        "bundled_class_shadow",
        "cs_rebind",
        "doc_absent_stub",
        "driver_tfm_hoist",
        "fileset_relocate",
        "font_cs_shim",
        "generated_stub",
        "journal_cs_polyfill",
        "legacy_pkg_shim",
        "pdftex_prim_polyfill",
        "revtex209_surface_polyfill",
        "shim_pkgs_in_use",
        "svjour_clo_stub",
        "undefined_env_polyfill",
    ),
    "_builtins_slotrev": ("slot_arg_revert",),
    "_builtins_vendored": (
        "_provides_date",
        "_vendor_root",
        "_vendored_source",
        "amsmath_family_retire",
        "find_vendored_shadows",
        "fontspec_kernel_shadow_retire",
        "revtex_era_retire",
        "vendored_fetch",
        "vendored_fetch_multi",
        "vendored_shadow_isolate",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

#: ``builtin_transform`` 词表——键序即原 TRANSFORM_FNS 字面序 (注册表消费
#: 面不依赖序, 保序只为 diff 可读); 值经 ``_LAZY`` 逐名惰性解析。
_TRANSFORM_KEYS: tuple[str, ...] = (
    "option_clash_merge",
    "pdftex_prim_polyfill",
    "vendored_shadow_isolate",
    "non_utf8_recode",
    "bbl_stub_rewrite",
    "bbl_regen",
    "biber_biblatex_skew_route",
    "tectonic_bib_stall_route",
    "bm_mathchar_wrap",
    "cite_in_math_mbox",
    "svjour_clo_stub",
    "font_sub_shim",
    "pstricks_dvips_preflight",
    "eps_to_pdf",
    "legacy_pkg_shim",
    "journal_cs_polyfill",
    "bundled_class_shadow",
    "strip_inputenc",
    "physics_stub_detach",
    "undefine_for_redef",
    "cs_delim_tail_fix",
    "cs_targeted_fix",
    "ctlseq_undefine",
    "purge_corrupt_intermediates",
    "aux_seed_undefined_refs",
    "missing_char_fix",
    "macro_glyph_fix",
    "accent_mark_fix",
    "caret_utf8_fix",
    "font_fallback",
    "fontspec_clone_sub",
    "fontenc_enc_relax",
    "nfss_cmd_enc_polyfill",
    "nfss_enc_scheme_relax",
    "nfss_fam_declare",
    "umath_doc_cs_restore",
    "graphic_case_link",
    "graphic_repair",
    "restore_support_from_src",
    "citekey_sanitize",
    "vendored_fetch",
    "vendored_fetch_multi",
    "fontspec_kernel_shadow_retire",
    "amsmath_family_retire",
    "revtex_era_retire",
    "generated_stub",
    "fileset_relocate",
    "driver_tfm_hoist",
    "driver_missing_image_stub",
    "doc_absent_stub",
    "docstrip_generate",
    "extract_tar_blobs",
    "plain_format_detect",
    "harvest_build_directives",
    "latex209_upgrade",
    "svg_prepare",
    "includepdf_missing_stub",
    "if_phantom_protect",
    "undefined_env_polyfill",
    "font_cs_shim",
    "cs_rebind",
    "revtex209_surface_polyfill",
    "pdfstring_cs_disarm",
    "premature_cs_guard",
    "primitive_clobber_rename",
    "xbb_pregen",
    "pdf_asset_sanitize",
    "shipped_sty_input_wrap",
    "siunitx_incompat_peace",
    "spacefactor_atdef_wrap",
    "para_longize",
    "graphic_missing_placeholder",
    "subfile_docclass_strip",
    "slot_arg_revert",
    "pfa_to_pfb",
    "graphics_include_strip",
    "main_wrapper_promote",
    "eps_converted_alias",
    "raster_pdf_rename",
    "cjk_env_relax",
    "xy_option_load",
    "tcolorbox_breakable_inject",
    "float_h_demote",
    "float_opt_cs_expand",
    "para_loosen",
    "tabular_fit",
    "math_run_break",
    "section_skip_floor",
    "display_math_shrink",
    "gfx_width_clamp",
    "fffd_context_fix",
    "bbl_format_version_rewrite",
    "rotatebox_caption_pad",
    "legacy_clamp_purge",
)

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集 +
# 本地注册表名, 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "PDFTEX_PRIMS",
    "REWRITE_FNS",
    "TRANSFORM_FNS",
    "_EPS_EXTS",
    "_GRAPHICS_PKGS_RE",
    "_GRAPHIC_EXTS",
    "_GS_FLAGS",
    "_INCLUDESVG_RE",
    "_INCLUDE_GFX_RE",
    "_INCLUDE_PDF_RE",
    "_LOAD_OPT_RE",
    "_MC_TABLE",
    "_NUMERIC_EXT_RE",
    "_PS_DRIVERS",
    "_SVG_CONVERTERS",
    "_SVG_OPT_KEEP",
    "_allocated_cs_names",
    "_convert_one",
    "_detach_physics_loads",
    "_find_graphic_ci",
    "_graphic_ref_hit",
    "_inject_after_docclass",
    "_live_matches",
    "_mc_hit",
    "_mc_parse_log",
    "_mc_plan",
    "_norm_graphic_name",
    "_opt_dim",
    "_provides_date",
    "_resolve_site",
    "_rewrite_case_refs",
    "_rewrite_eps_refs",
    "_rewrite_includesvg",
    "_run_convert",
    "_strip_ps_driver_opts",
    "_stub_graphic_refs",
    "_svg_convert_arm",
    "_svg_convert_one",
    "_try_gs_redistill",
    "_vendor_root",
    "_vendored_source",
    "accent_mark_fix",
    "amsmath_family_retire",
    "aux_seed_undefined_refs",
    "bbl_format_version_rewrite",
    "bbl_regen",
    "bbl_stub_rewrite",
    "biber_biblatex_skew_route",
    "bm_mathchar_wrap",
    "bundled_class_shadow",
    "caret_utf8_fix",
    "cite_in_math_mbox",
    "citekey_sanitize",
    "cjk_env_relax",
    "cs_delim_tail_fix",
    "cs_rebind",
    "cs_targeted_fix",
    "ctlseq_undefine",
    "display_math_shrink",
    "doc_absent_stub",
    "docstrip_generate",
    "driver_missing_image_stub",
    "driver_tfm_hoist",
    "eps_converted_alias",
    "eps_to_pdf",
    "extract_tar_blobs",
    "fffd_context_fix",
    "fileset_relocate",
    "find_vendored_shadows",
    "float_h_demote",
    "float_opt_cs_expand",
    "font_cs_shim",
    "font_fallback",
    "font_sub_shim",
    "fontenc_enc_relax",
    "fontspec_clone_sub",
    "fontspec_kernel_shadow_retire",
    "generated_stub",
    "gfx_width_clamp",
    "graphic_case_link",
    "graphic_missing_placeholder",
    "graphic_repair",
    "graphics_include_strip",
    "graphics_kv_strip_obsolete",
    "harvest_build_directives",
    "if_phantom_protect",
    "includepdf_missing_stub",
    "journal_cs_polyfill",
    "keep_latin_tokens",
    "latex209_upgrade",
    "legacy_clamp_purge",
    "legacy_pkg_shim",
    "macro_glyph_fix",
    "main_wrapper_promote",
    "math_run_break",
    "missing_char_fix",
    "nfss_cmd_enc_polyfill",
    "nfss_enc_scheme_relax",
    "nfss_fam_declare",
    "non_utf8_recode",
    "option_clash_merge",
    "para_longize",
    "para_loosen",
    "pdf_asset_sanitize",
    "pdfstring_cs_disarm",
    "pdftex_prim_polyfill",
    "pfa_to_pfb",
    "physics_stub_detach",
    "plain_format_detect",
    "premature_cs_guard",
    "primitive_clobber_rename",
    "pstricks_dvips_preflight",
    "purge_corrupt_intermediates",
    "px_to_bp",
    "raster_pdf_rename",
    "restore_support_from_src",
    "revtex209_surface_polyfill",
    "revtex_era_retire",
    "rotatebox_caption_pad",
    "section_skip_floor",
    "shim_pkgs_in_use",
    "shipped_sty_input_wrap",
    "siunitx_incompat_peace",
    "slot_arg_revert",
    "spacefactor_atdef_wrap",
    "strip_inputenc",
    "subfile_docclass_strip",
    "svg_prepare",
    "svjour_clo_stub",
    "tabular_fit",
    "tcolorbox_breakable_inject",
    "tectonic_bib_stall_route",
    "umath_doc_cs_restore",
    "undefine_for_redef",
    "undefined_env_polyfill",
    "vendored_fetch",
    "vendored_fetch_multi",
    "vendored_shadow_isolate",
    "xbb_pregen",
    "xy_option_load",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性; TRANSFORM_FNS 首访按键表构建真 dict。"""
    if name == "TRANSFORM_FNS":
        mod = sys.modules[__name__]
        fns = {key: getattr(mod, key) for key in _TRANSFORM_KEYS}
        globals()[name] = fns
        return fns
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

    空表 = 同步, 测试断言 ``== []`` 即可。三向覆盖:

    - ``_LAZY`` 键与 ``_TRANSFORM_KEYS`` 全进 ``__all__``;
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链 (``_LEAF_EXPORTS``
      配名叶子不提供) 与幽灵条 (既非叶子名也非本地名) 在此曝, 是首访
      ``AttributeError`` 唯一的提前闸;
    - 本地公共名 (本模块定义的函数/类 + 注册表 dict) 全进 ``__all__``
      —— ``graphics_kv_strip_obsolete`` 漏列即此类漂移。

    审计实载全部叶子, 只供测试调用, 装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = [
        f"{name} in _LEAF_EXPORTS but missing from __all__"
        for name in _LAZY
        if name not in __all__
    ]
    drift += [
        f"{key} in _TRANSFORM_KEYS but not in _LAZY"
        for key in _TRANSFORM_KEYS
        if key not in _LAZY
    ]
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    for name in __all__:
        try:
            getattr(mod, name)
        except Exception as exc:  # noqa: BLE001 -- 审计兜全漂移, 非首错即死
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


# ════════════════════════════════════════════════════════════════
# regex_rewrite 逐 match 改写函数 —— (Match) -> str
# ════════════════════════════════════════════════════════════════


def px_to_bp(m: re.Match[str]) -> str:
    r"""``N px`` → ``N bp`` —— pdfTeX 忠实换算.

    缺省 ``\pdfpxdimen``=65782sp=1bp: 源档在 pdfTeX 下产出的尺寸即
    1:1; normalize 侧同口径, 旧 CSS 96dpi ×0.75 是屏幕域语义错配。
    """
    v = float(m.group(1))
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s + "bp"


def keep_latin_tokens(m: re.Match[str]) -> str:
    r"""``\\hyphenation{...}`` 参数只留 ``[a-zA-Z][a-zA-Z-]*`` token (原型)。"""
    toks = re.findall(r"[a-zA-Z][a-zA-Z-]*", m.group(1))
    return "\\hyphenation{" + " ".join(toks) + "}"


#: 时代 graphicx key——``type=``/``ext=``/``read=`` 现代走 ``\csname Gin@rule@..``
#: 链 (``Missing \endcsname`` + 名字毒化 missing_graphic 级联, 0812.0324/365 实证)。
_GIN_OBSOLETE_KEYS = frozenset({"type", "ext", "read"})


def graphics_kv_strip_obsolete(m: re.Match[str]) -> str:
    r"""``\includegraphics[...]`` opt 表剥 ``type=``/``ext=``/``read=`` 成员。

    组1 = ``\includegraphics`` 头 (含 ``*``), 组2 = 括号 opt 表。成员级
    ``key=`` 比对 (``subtype``/``breadth`` 类前缀不沾); 剥空即整括号摘除。
    顶层逗号切分单源 = ``_builtins_misschar._split_kv``。
    """
    from texlate.compile.fixloop._builtins_misschar import (  # noqa: PLC0415
        _split_kv,  # 延迟: 本门面不 eager 拉叶链, 调用点已到运行期
    )

    keep = [
        kv
        for kv in _split_kv(m.group(2))
        if kv.split("=", 1)[0].strip() not in _GIN_OBSOLETE_KEYS
    ]
    return m.group(1) + ("[" + ",".join(keep) + "]" if keep else "")


REWRITE_FNS = {
    "px_to_bp": px_to_bp,
    "keep_latin_tokens": keep_latin_tokens,
    "graphics_kv_strip_obsolete": graphics_kv_strip_obsolete,
}
