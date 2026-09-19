"""builtins — fixloop 命名函数注册表 (rules.yaml `function:` 的实现侧)。

两类签名:
  - REWRITE_FNS: ``(re.Match) -> str`` —— regex_rewrite 条目的逐 match 改写
    (spike 里 `px_to_bp`/`keep_latin_tokens`, 算术/集合变换非纯模板)
  - TRANSFORM_FNS: ``(ctx, eng, payload, params) -> (applied, note)`` ——
    builtin_transform 条目的文件级算法改写 (spike 里 `option_clash_merge`,
    新增 6 条按 docs/08 §5.2 实现)

社区贡献规则多数只需写 regex; 新算法型修复才需要往这里 PR 代码。

C3 拆分: 实现体按域拆进 ``_builtins_*`` 叶子模块, 本文件收敛为门面
re-export 保 ``builtins.X`` 公共面 (engine.py 属性消费 +
``from ... import X`` 测试面 + ``_vendor_root`` 等私名跨模块访问)。
B12: 回引注册表已按全仓实测消费收敛——叶子私名默认不回引,
缺名字的断链面请从叶子模块直取而非恢复批发回引。
monkeypatch 锚点注意: 图形/PS 域已出叶 ``_builtins_graphics``——
``_run_convert`` 的 patch 面随调用链迁走, 测试须 patch
``_builtins_graphics._run_convert`` 而非本门面同名回引。
"""

from __future__ import annotations

import re

from texlate.compile.fixloop._builtins_bib import (
    bbl_regen,
    bbl_stub_rewrite,
    biber_biblatex_skew_route,
    cite_in_math_mbox,
    citekey_sanitize,
)
from texlate.compile.fixloop._builtins_common import (
    _MC_TABLE,
    PDFTEX_PRIMS,
    _inject_after_docclass,
    _live_matches,
    _mc_hit,
    _mc_parse_log,
    _mc_plan,
)
from texlate.compile.fixloop._builtins_csfix import (
    _allocated_cs_names,
    cs_targeted_fix,
    ctlseq_undefine,
    if_phantom_protect,
    pdfstring_cs_disarm,
    undefine_for_redef,
)
from texlate.compile.fixloop._builtins_graphics import (
    _EPS_EXTS,
    _GRAPHIC_EXTS,
    _GRAPHICS_PKGS_RE,
    _GS_FLAGS,
    _INCLUDE_GFX_RE,
    _INCLUDE_PDF_RE,
    _INCLUDESVG_RE,
    _LOAD_OPT_RE,
    _NUMERIC_EXT_RE,
    _PS_DRIVERS,
    _SVG_CONVERTERS,
    _SVG_OPT_KEEP,
    _convert_one,
    _find_graphic_ci,
    _graphic_ref_hit,
    _norm_graphic_name,
    _opt_dim,
    _rewrite_case_refs,
    _rewrite_eps_refs,
    _rewrite_includesvg,
    _run_convert,
    _strip_ps_driver_opts,
    _stub_graphic_refs,
    _svg_convert_arm,
    _svg_convert_one,
    _try_gs_redistill,
    eps_to_pdf,
    graphic_case_link,
    graphic_repair,
    includepdf_missing_stub,
    pdf_asset_sanitize,
    pstricks_dvips_preflight,
    svg_prepare,
    xbb_pregen,
)
from texlate.compile.fixloop._builtins_misc import (
    docstrip_generate,
    extract_tar_blobs,
    harvest_build_directives,
    non_utf8_recode,
    plain_format_detect,
    purge_corrupt_intermediates,
    restore_support_from_src,
)
from texlate.compile.fixloop._builtins_misschar import (
    accent_mark_fix,
    font_fallback,
    missing_char_fix,
)
from texlate.compile.fixloop._builtins_pkgload import (
    _detach_physics_loads,
    font_sub_shim,
    option_clash_merge,
    physics_stub_detach,
    shipped_sty_input_wrap,
    strip_inputenc,
)
from texlate.compile.fixloop._builtins_shim import (
    bundled_class_shadow,
    cs_rebind,
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
from texlate.compile.fixloop._builtins_vendored import (
    _provides_date,
    _vendor_root,
    _vendored_source,
    find_vendored_shadows,
    vendored_fetch,
    vendored_shadow_isolate,
)

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
    "bbl_regen",
    "bbl_stub_rewrite",
    "biber_biblatex_skew_route",
    "bundled_class_shadow",
    "cite_in_math_mbox",
    "citekey_sanitize",
    "cs_rebind",
    "cs_targeted_fix",
    "ctlseq_undefine",
    "docstrip_generate",
    "eps_to_pdf",
    "extract_tar_blobs",
    "find_vendored_shadows",
    "font_cs_shim",
    "font_fallback",
    "font_sub_shim",
    "generated_stub",
    "graphic_case_link",
    "graphic_repair",
    "harvest_build_directives",
    "if_phantom_protect",
    "includepdf_missing_stub",
    "journal_cs_polyfill",
    "keep_latin_tokens",
    "legacy_pkg_shim",
    "missing_char_fix",
    "non_utf8_recode",
    "option_clash_merge",
    "pdf_asset_sanitize",
    "pdfstring_cs_disarm",
    "pdftex_prim_polyfill",
    "physics_stub_detach",
    "plain_format_detect",
    "pstricks_dvips_preflight",
    "purge_corrupt_intermediates",
    "px_to_bp",
    "restore_support_from_src",
    "revtex209_surface_polyfill",
    "shim_pkgs_in_use",
    "shipped_sty_input_wrap",
    "strip_inputenc",
    "svg_prepare",
    "svjour_clo_stub",
    "undefine_for_redef",
    "undefined_env_polyfill",
    "vendored_fetch",
    "vendored_shadow_isolate",
    "xbb_pregen",
]


# ════════════════════════════════════════════════════════════════
# regex_rewrite 逐 match 改写函数 —— (Match) -> str
# ════════════════════════════════════════════════════════════════


def px_to_bp(m: re.Match[str]) -> str:
    """``N px`` → ``N*0.75 bp`` (CSS 96dpi 换算, spike L369-373)。"""
    v = float(m.group(1)) * 0.75
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s + "bp"


def keep_latin_tokens(m: re.Match[str]) -> str:
    r"""``\\hyphenation{...}`` 参数只留 ``[a-zA-Z][a-zA-Z-]*`` token (spike L418-420)。"""
    toks = re.findall(r"[a-zA-Z][a-zA-Z-]*", m.group(1))
    return "\\hyphenation{" + " ".join(toks) + "}"


REWRITE_FNS = {"px_to_bp": px_to_bp, "keep_latin_tokens": keep_latin_tokens}


TRANSFORM_FNS = {
    "option_clash_merge": option_clash_merge,
    "pdftex_prim_polyfill": pdftex_prim_polyfill,
    "vendored_shadow_isolate": vendored_shadow_isolate,
    "non_utf8_recode": non_utf8_recode,
    "bbl_stub_rewrite": bbl_stub_rewrite,
    "bbl_regen": bbl_regen,
    "biber_biblatex_skew_route": biber_biblatex_skew_route,
    "cite_in_math_mbox": cite_in_math_mbox,
    "svjour_clo_stub": svjour_clo_stub,
    "font_sub_shim": font_sub_shim,
    "pstricks_dvips_preflight": pstricks_dvips_preflight,
    "eps_to_pdf": eps_to_pdf,
    "legacy_pkg_shim": legacy_pkg_shim,
    "journal_cs_polyfill": journal_cs_polyfill,
    "bundled_class_shadow": bundled_class_shadow,
    "strip_inputenc": strip_inputenc,
    "physics_stub_detach": physics_stub_detach,
    "undefine_for_redef": undefine_for_redef,
    "cs_targeted_fix": cs_targeted_fix,
    "ctlseq_undefine": ctlseq_undefine,
    "purge_corrupt_intermediates": purge_corrupt_intermediates,
    "missing_char_fix": missing_char_fix,
    "accent_mark_fix": accent_mark_fix,
    "font_fallback": font_fallback,
    "graphic_case_link": graphic_case_link,
    "graphic_repair": graphic_repair,
    "restore_support_from_src": restore_support_from_src,
    "citekey_sanitize": citekey_sanitize,
    "vendored_fetch": vendored_fetch,
    "generated_stub": generated_stub,
    "docstrip_generate": docstrip_generate,
    "extract_tar_blobs": extract_tar_blobs,
    "plain_format_detect": plain_format_detect,
    "harvest_build_directives": harvest_build_directives,
    "svg_prepare": svg_prepare,
    "includepdf_missing_stub": includepdf_missing_stub,
    "if_phantom_protect": if_phantom_protect,
    "undefined_env_polyfill": undefined_env_polyfill,
    "font_cs_shim": font_cs_shim,
    "cs_rebind": cs_rebind,
    "revtex209_surface_polyfill": revtex209_surface_polyfill,
    "pdfstring_cs_disarm": pdfstring_cs_disarm,
    "xbb_pregen": xbb_pregen,
    "pdf_asset_sanitize": pdf_asset_sanitize,
    "shipped_sty_input_wrap": shipped_sty_input_wrap,
}
