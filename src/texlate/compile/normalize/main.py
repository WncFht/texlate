r"""compile.normalize.main — 归一化主编排叶 (compile.normalize 域缝叶)。

``normalize_engine`` 单文件无条件手术编排（清单 1–10 文件内部分 +
兼容前导块注入闸）；``_normalize_tex_files`` 逐 tex 件主手术
（转码 + normalize_engine + bbl 替换）；``normalize_project`` 工程级
编排（junk stub → tex 手术 → 支持件转码 → latin → rebase → shadow）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from texlate.compile.mask import TEX_SOURCE_SUFFIXES, visible_tex
from texlate.compile.normalize.bbl import use_bundled_bibliography
from texlate.compile.normalize.blocks import (
    PIXEL_COMPATIBILITY,
    TECTONIC_FONT_COMPATIBILITY,
    XETEX_COMPATIBILITY,
    _splice_early_defs,
)
from texlate.compile.normalize.guard import _prologue_ok, _strip_lead_junk
from texlate.compile.normalize.junk import _neutralize_junk_files
from texlate.compile.normalize.latin import prepare_legacy_latin_fonts
from texlate.compile.normalize.paths import rebase_project_paths
from texlate.compile.normalize.text import (
    normalize_comment_terminators,
    normalize_float_positions,
    normalize_legacy_cjk,
    normalize_manual_hyphens,
    normalize_pdf_primitives,
    normalize_pdftex_features,
    normalize_pixel_dimensions,
    strip_input_encodings,
)
from texlate.compile.shadow import _shadow_broken_system_packages
from texlate.compile.transcode import (
    _hidden_path,
    _iter_files,
    _record_verdict,
    _transcode_support_files,
)
from texlate.textutil import (
    BEGIN_DOC_RX,
    SUBDOC_CHILD_RX,
    _tar_disguised,
    decode_tex_with,
    iter_depth0,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

# logger 名钉死拆分前模块名——消息面 (record.name) 不变。
log = logging.getLogger("texlate.compile.normalize")


# ---------------------------------------------------------------- 主编排
#: 文档源后缀——``\pdfinfo``/``\pdfoutput``/输出设置等文档级手术只适用
#: 文档源；``.def/.sty/.clo`` 支持件里同名原语是条件装载的驱动实现，
#: 删除即腐蚀 bundled 件 (1306.0294 hpdftex.def)。
_DOC_SOURCE_SUFFIXES = frozenset({".tex", ".ltx"})


def normalize_engine(
    text: str, engine: str, *, doc_source: bool = True, prologue: bool = True
) -> str:
    r"""单文件无条件手术编排（docs/spec/compile.md 清单 1–10 的文件内部分）。

    ``doc_source=False`` 按支持件处理：文档级输出控制删除
    （``\pdfinfo``/``\pdfoutput``/输出设置/``\DisableLigatures``）与
    px 像素改写跳过；驱动 token、microtype 降级、编码剥离等
    装载期语义改写仍生效。``prologue=False`` 再闸掉兼容前导块注入
    （PIXEL/XETEX/TECTONIC 兼容块 + XETEX_EARLY_DEFS + fontspec
    ``no-math`` 选项）——``has_document`` 命中二进制 blob 解出的成员
    文本时不许前置注入（0707.0382 tar 伪装 .sty 实案），调用方按
    字节面判据传闸。
    """
    text = normalize_comment_terminators(text)
    text = normalize_float_positions(text)
    text = normalize_manual_hyphens(text)
    if engine in ("tectonic", "xelatex"):
        text = normalize_pdftex_features(text, engine, doc_source=doc_source)
        if doc_source:
            text = normalize_pixel_dimensions(text)
        if prologue:
            visible = visible_tex(text)
            has_document = BEGIN_DOC_RX.search(visible)
            if r"\pdfpxdimen" in visible and PIXEL_COMPATIBILITY not in text:
                # 用 \pdfpxdimen 的文件就要带定义——子文件被 \input 进主文档时
                # 主文档前导块不一定存在（px 只在子件时主件无注入面），
                # \ifdefined 幂等闸保证多件重复注入也安全。
                text = PIXEL_COMPATIBILITY + text
                visible = visible_tex(text)
            # ``\documentclass[..]{subfiles|standalone}`` 子档：母档 ``\subfile``/
            # standalone 包补丁 ``\input``/``\includestandalone`` 拉入时
            # ``\documentclass`` 起至 bd 区间被吞，声明行**之前**的文本却在
            # 母档 body 语境执行——前置块内 preamble-only ``\PassOptionsTo*``
            # 落 body 即 "Can be used only in preamble"（2310.16788
            # birds_eye_view/side_view :1,14；2609.19210/2609.20069 standalone
            # 图件 :1 实案）。``iter_depth0`` 与 find_docclass_ends 同口径——
            # 宏体/实参内 depth>0 命中不算真声明点。PIXEL 仅
            # \ifdefined/\newdimen（body 合法）且保子件 \pdfpxdimen 覆盖，放行。
            preamble_ok = bool(has_document) and not any(
                iter_depth0(SUBDOC_CHILD_RX, visible)
            )
            if preamble_ok and XETEX_COMPATIBILITY not in text:
                text = XETEX_COMPATIBILITY + text
            if (
                engine == "tectonic"
                and preamble_ok
                and TECTONIC_FONT_COMPATIBILITY not in text
            ):
                text = TECTONIC_FONT_COMPATIBILITY + text
            if (
                preamble_ok
                and r"\PassOptionsToPackage{no-math}{fontspec}" not in visible_tex(text)
            ):
                text = "\\PassOptionsToPackage{no-math}{fontspec}\n" + text
            # preamble 消费的仿真定义落 ``\documentclass`` 缝后（全部用户
            # preamble 代码之前）——限 doc_source：支持件里的声明字样是
            # 条件装载/示例文本而非文档起点，且 GBK 支持件逐跑转码后
            # ``_prologue_ok`` 翻转会二次注入（fuzz 幂等面实证）。
            if doc_source:
                text = _splice_early_defs(text)
        text = strip_input_encodings(text)
        text = normalize_pdf_primitives(text, doc_source=doc_source)
    if engine in ("tectonic", "xelatex", "lualatex"):
        text = normalize_legacy_cjk(text, engine)
    return text


def _normalize_tex_files(
    root: Path,
    engine: str,
    main: str | None,
    stats: dict[str, Any],
    encodings: dict[str, dict[str, str | None]],
) -> None:
    """逐 tex 件主手术：转码 + `normalize_engine` + bbl 替换；累计 files/rewritten。"""
    # skip_hidden=False：隐藏件照计 ``stats["files"]``（先计后跳旧口径），
    # 隐藏路径整体豁免手术的手动闸保留在增量之后。
    for path in _iter_files(root, TEX_SOURCE_SUFFIXES, skip_hidden=False):
        stats["files"] = int(stats["files"]) + 1
        if _hidden_path(path, root):
            continue  # 隐藏路径整体豁免手术（同 _transcode 口径）
        try:
            original = path.read_bytes()
            if _tar_disguised(original):
                # tar 伪装件逐字节不动——转码/手术都腐蚀成员数据；
                # fixloop tar 解包臂（同口径扫描窗）在编译侧兜底补缺
                log.debug("归一化跳过 tar 伪装件 %s", path)
                continue
            blob = _strip_lead_junk(original)
            if blob is not original:
                stats.setdefault("lead_junk_stripped", []).append(
                    path.relative_to(root).as_posix()
                )
            text, verdict = decode_tex_with(blob)
            _record_verdict(encodings, root, path, verdict)
            doc_source = path.suffix.lower() in _DOC_SOURCE_SUFFIXES
            text = normalize_engine(
                text,
                engine,
                doc_source=doc_source,
                prologue=doc_source or _prologue_ok(blob, verdict),
            )
            if path.suffix.lower() == ".tex":
                text = use_bundled_bibliography(
                    text, path, cwd=(root / main).parent if main else None
                )
            if text.encode("utf-8") != original:
                path.write_text(text, encoding="utf-8", newline="")
                stats["rewritten"] = int(stats["rewritten"]) + 1
        except OSError as e:
            # 单件读/写失败（只读件、权限边界）不拖垮整树——跳过硬保留原样
            log.debug("归一化跳过不可读写件 %s: %s", path, e)


def normalize_project(root: Path, engine: str, main: str | None = None) -> dict:
    """工程级归一化：逐文件 `normalize_engine` + 文件级手术（9/11/12）。

    返回改动统计 dict。`main` 给 rebase/bbl 判定用；缺省时只按文件名猜。
    非平凡解码判定（非 strict-utf8 / 有声明出入注记）逐文件落
    ``stats["encodings"]``——worker 日志与 rec["normalize"] 由此可回溯
    「该文件原来是什么编码、按哪档判定的」。
    """
    stats: dict[str, object] = {"files": 0, "rewritten": 0}
    encodings: dict[str, dict[str, str | None]] = {}
    _neutralize_junk_files(root, stats)
    _normalize_tex_files(root, engine, main, stats, encodings)
    stats.update(_transcode_support_files(root, encodings))
    if encodings:
        stats["encodings"] = encodings
    latin = prepare_legacy_latin_fonts(root)
    if latin:
        stats["legacy_latin_files"] = latin
    if main:
        rebased = rebase_project_paths(root, main)
        if rebased:
            stats["rebased_paths"] = rebased
    shadows = _shadow_broken_system_packages(root, main, engine)
    if shadows:
        stats["package_shadows"] = shadows
    return stats
