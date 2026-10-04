"""specs._layoutqc.rastercheck — T1 raster/pdfimages 叶 (_layoutqc 拆分叶).

系统 python 渲染子进程 (``_raster_pages``) + pdfimages 位图计数
(``_images_per_page``) + 空白/寡行/墨团/空洞/tofu zh 单侧 +
栏数/规则/墨量回归跨臂对拍 (``_raster_scan``)。
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from typing import TYPE_CHECKING

from specs._layoutqc.pagekit import _run, _struct_head, _verso_blank
from specs._layoutqc.thresh import (
    _FOLIO_RX,
    _RASTER_CHILD,
    _RASTER_PY,
    BLANK_INK_MAX,
    INK_DROP_RATIO,
    INK_SELF_OUTLIER,
    INKBLOB_CC_MIN,
    KEEP_DPI,
    KEEP_TIMEOUT,
    RASTER_DPI,
    RASTER_TIMEOUT,
    TABLE_RULE_LOST,
    TOFU_MIN_PAGE,
    VOID_FRAC_MIN,
    VOID_FRAME_ART_MIN,
    VOID_INT_INK_MIN,
    WIDOW_INK_MAX,
)

if TYPE_CHECKING:
    from pathlib import Path


def _images_per_page(pdf: Path) -> dict[int, int]:
    """``pdfimages -list`` → {page: n_images}（免抽取锚点近似）。"""
    out = _run(["pdfimages", "-list", pdf.name], cwd=pdf.parent)
    per: dict[int, int] = {}
    for ln in out.splitlines():
        # stencil/smask 位图也算墨——1-bit stencil 图版页曾被漏计失去
        # curves/void 豁免（0928 pdf_integrity 簇实证）。
        m = re.match(r"\s*(\d+)\s+\d+\s+(?:image|stencil|smask)\s", ln)
        if m:
            per[int(m.group(1))] = per.get(int(m.group(1)), 0) + 1
    return per


def _raster_pages(
    pdf: Path, *, keep_dir: Path | None = None, keep_pages: list[int] | None = None
) -> dict:
    """T1 子进程调用 → {pages:[…]} 或 {error:…}（pillow 缺席静默降级）。

    keep_dir+keep_pages 时走收割专道：只渲标记页 PNG 复制进
    keep_dir（§11.2 flagged_pages 目检素材，不产出度量）。
    """
    if not _RASTER_CHILD.exists():
        return {"error": "child_missing"}
    harvest = keep_dir is not None and bool(keep_pages)
    argv = [
        _RASTER_PY,
        str(_RASTER_CHILD),
        pdf.name,
        KEEP_DPI if harvest else RASTER_DPI,
    ]
    if harvest:
        argv.append(f"keep:{keep_dir}:{','.join(str(p) for p in keep_pages)}")
    out = _run(
        argv, cwd=pdf.parent, timeout=KEEP_TIMEOUT if harvest else RASTER_TIMEOUT
    )
    try:
        return json.loads(out) if out else {"error": "empty"}
    except ValueError:
        return {"error": "bad_json"}


def _raster_scan(
    zh_pages: list[dict],
    base_pages: list[dict] | None,
    zh_images: dict[int, int] | None = None,
    *,
    zh_text_pages: list[str] | None = None,
    zh_geo: list[dict] | None = None,
    twoside: bool = False,
    blankpage_marker: bool = False,
    doc_title: str | None = None,
) -> tuple[list[dict], dict]:
    """raster 检查：空白/墨团/空洞/tofu（zh 单侧）+ 栏数/规则
    对拍（跨臂）。

    ``zh_images`` = _images_per_page 页→嵌入位图数——含位图页跳过
    ink_blob（星系格/照片类深色位图天然产出巨大 dark CC，与
    text_as_curves 同一豁免族：位图页的大墨块是内容不是泼溅）。
    ``zh_text_pages``=pdftotext 逐页文本（verso/孤行判定）；``zh_geo``
    =_bbox_pages 页 dict（frames 键给 void 的封印框兜底闸）；
    ``twoside``=文档双面排版（偶数 verso 空白页合法）；
    ``blankpage_marker``=tex 含 \\blankpage 族显式造白页标记
    （frontmatter 域佐证，全篇不放大）；``doc_title``=splice
    ``\\title`` squash 串（标题页 verso 佐证）。

    空白页抑制四层：base ±1 窗同空白（源承）/下一非白页首行结构性
    标题（章前分隔）/verso（folio 偶数优先、PDF 序数兜底、
    frontmatter+blankpage 标记佐证）/末页 folio-only（收尾）。
    近空页（墨量过空白地板但 <WIDOW_INK_MAX 且正文 ≤2 行）降为
    ``vis_widow_page``（INFO）——孤行页是排版丑态非缺陷面。"""
    findings: list[dict] = []
    metrics: dict = {"raster_pages": len(zh_pages)}
    blank = blob = void = blank_supp = widow = 0
    tofu_pages: list[int] = []
    n_zh = len(zh_pages)
    n_tx = len(zh_text_pages) if zh_text_pages is not None else 0
    for i, pg in enumerate(zh_pages):
        if pg["ink"] < BLANK_INK_MAX:
            # 近空白页上有 1-2 行非 folio 文字 → 孤行/孤题残留页
            # （stub 孤 preprint 页/pstricks 垃圾页/浮体搁浅的孤零零
            # 标题页实证）→ 降 vis_widow_page（INFO），不占 HARD 档。
            body_ls = None
            if i < n_tx:
                body_ls = [
                    ln
                    for ln in zh_text_pages[i].splitlines()
                    if ln.strip() and not _FOLIO_RX.match(ln)
                ]
            if body_ls is not None and 0 < len(body_ls) <= 2:
                widow += 1
                findings.append(
                    {
                        "sig": "vis_widow_page",
                        "page": i + 1,
                        "ink": pg["ink"],
                        "lines": len(body_ls),
                    }
                )
            else:
                supp = False
                if base_pages:
                    lo, hi = max(0, i - 1), min(len(base_pages), i + 2)
                    if any(base_pages[j]["ink"] < BLANK_INK_MAX for j in range(lo, hi)):
                        supp = True  # en 原件同页位留白——源承非缺陷
                if not supp and zh_text_pages is not None:
                    for j in range(i + 1, n_tx):
                        if zh_text_pages[j].strip():
                            head = next(
                                (
                                    ln
                                    for ln in zh_text_pages[j].splitlines()
                                    if ln.strip() and not _FOLIO_RX.match(ln)
                                ),
                                "",
                            )
                            if _struct_head(head, doc_title):
                                supp = True  # 章/部/附录前分隔白页
                            break
                if not supp and _verso_blank(
                    i,
                    zh_text_pages[i] if i < n_tx else "",
                    twoside,
                    blankpage_marker,
                ):
                    supp = True  # folio 偶数/序数兜底/frontmatter 标记 verso
                if (
                    not supp
                    and i == 1
                    and zh_text_pages is not None
                    and zh_text_pages[0].strip()
                ):
                    supp = True  # 扉页后 verso——frontmatter 常态空背
                if not supp and i == n_zh - 1 and zh_text_pages is not None:
                    tail_ls = [ln for ln in zh_text_pages[i].splitlines() if ln.strip()]
                    if all(_FOLIO_RX.match(ln) for ln in tail_ls):
                        supp = True  # 末页仅页码——收尾留白
                if supp:
                    blank_supp += 1
                else:
                    blank += 1
                    findings.append({"sig": "vis_blank_page", "page": i + 1})
        elif pg["ink"] < WIDOW_INK_MAX:
            nlines = (
                sum(1 for ln in zh_text_pages[i].splitlines() if ln.strip())
                if i < n_tx
                else None
            )
            if nlines is None or nlines <= 2:
                widow += 1
                findings.append(
                    {
                        "sig": "vis_widow_page",
                        "page": i + 1,
                        "ink": pg["ink"],
                        "lines": nlines,
                    }
                )
        if pg["dark_cc"] > INKBLOB_CC_MIN and not (zh_images or {}).get(i + 1, 0):
            blob += 1
            findings.append({"sig": "vis_ink_blob", "page": i + 1, "cc": pg["dark_cc"]})
        # 内部洞（四周皆有墨）才是真掉图窟窿；贴边留白是结构性
        # （目录收尾/末页早收/栏尾空行，2605.25645 p3 实证）。
        # void_ink 闸（raster 子进程新版输出）：封印框内墨率 ≥2% =
        # 有内容的 tcolorbox/listing/axis 白内腔，非掉图。缓存 JSON
        # 无 void_ink 时退 frames 兜底：≥15% 页面积矢量框簇内有词心
        # 或 ≥8 小矢量件 → 合法封印框不报。
        v_int = pg.get("void_int", pg["void_frac"])
        if (
            i < n_zh - 1
            and v_int > VOID_FRAC_MIN
            and not (zh_images or {}).get(i + 1, 0)
        ):
            if "void_ink" in pg:
                void_hit = pg["void_ink"] < VOID_INT_INK_MIN
            else:
                frames = (
                    zh_geo[i].get("frames")
                    if zh_geo is not None and i < len(zh_geo)
                    else None
                )
                void_hit = not any(
                    fr["words"] > 0 or fr["art"] >= VOID_FRAME_ART_MIN
                    for fr in (frames or [])
                )
            if void_hit:
                void += 1
                findings.append({"sig": "vis_void", "page": i + 1, "frac": v_int})
        if pg.get("tofu", 0) >= TOFU_MIN_PAGE:
            tofu_pages.append(i + 1)
    if tofu_pages:
        findings.append({"sig": "vis_tofu_box", "pages": tofu_pages})
    metrics.update(
        {
            "blank": blank,
            "blank_suppressed": blank_supp,
            "widow_pages": widow,
            "ink_blob": blob,
            "void": void,
            "tofu_pages": tofu_pages,
            "rules_zh": sum(p.get("rules", 0) for p in zh_pages),
        }
    )
    if base_pages:
        metrics["rules_base"] = sum(p.get("rules", 0) for p in base_pages)
        # 规则丢失：zh 比 base 少 ≥40% 且 base 有 ≥3 条——tabular 网格
        # 被 splice 破坏（规则线消失）的代理信号；图内轴线两臂同构
        # 天然对消。BIoU/cell 级错位仍属 T2。
        if (
            metrics["rules_base"] >= 3
            and metrics["rules_zh"] < metrics["rules_base"] * TABLE_RULE_LOST
        ):
            findings.append(
                {
                    "sig": "geo_table_lost",
                    "zh": metrics["rules_zh"],
                    "base": metrics["rules_base"],
                }
            )
        # 栏数按文档众数对拍——逐页 i 对拍在 zh/base 页数不齐时纯属
        # 错位噪声（2512.01407 实证 42p vs 44p 假 collapse）；要抓的
        # 缺陷类是「双栏模板渲成单栏」的全局坍缩。
        zh_mode = Counter(p["cols"] for p in zh_pages if p.get("cols") is not None)
        base_mode = Counter(p["cols"] for p in base_pages if p.get("cols") is not None)
        if zh_mode and base_mode:
            zm, bm = zh_mode.most_common(1)[0][0], base_mode.most_common(1)[0][0]
            metrics["col_mode"] = {"zh": zm, "base": bm}
            if zm != bm:
                findings.append(
                    {"sig": "geo_column_collapse", "zh_mode": zm, "base_mode": bm}
                )
        ink_ratio = sum(p["ink"] for p in zh_pages) / max(
            sum(p["ink"] for p in base_pages), 1e-9
        )
        metrics["ink_ratio"] = round(ink_ratio, 3)
        # 逐页墨量回归：矢量图（tikz/pgfplots）掉图不进 pdfimages
        # 计数——image 对拍盲区的补位面。zh 页墨量崩到 base 邻窗峰值
        # 35% 以下、base 邻窗确有内容（>8%）、且该页在自身文档内也是
        # 离群低点（< 全 zh 页中位数×INK_SELF_OUTLIER——重排错位的
        # 「比 base 稀但非离群」页不报）才报。末页豁免（收尾留白
        # 合法），blank 检出页已由 vis_blank_page 认领。
        ink_drops = []
        # 中位数只过非空页——空页已由 vis_blank_page 认领，计入会把
        # 中位数压到 ~0 使离群闸在「半空白文档」里永不触发；全空文档
        # zh_med=0 天然不报警（空页标记已逐页认领）。
        nz = [p["ink"] for p in zh_pages if p["ink"] >= BLANK_INK_MAX]
        zh_med = statistics.median(nz) if nz else 0.0
        for i, pg in enumerate(zh_pages[:-1]):
            if pg["ink"] < BLANK_INK_MAX:
                continue
            lo = max(0, i - 2)
            hi = min(len(base_pages), i + 3)
            bw = max((base_pages[j]["ink"] for j in range(lo, hi)), default=0)
            if (
                bw > 0.08
                and pg["ink"] < bw * INK_DROP_RATIO
                and pg["ink"] < zh_med * INK_SELF_OUTLIER
            ):
                ink_drops.append(i + 1)
        if ink_drops:
            findings.append({"sig": "regress_ink_profile", "pages": ink_drops})
            metrics["ink_drop_pages"] = ink_drops
    return findings, metrics
