"""specs._layoutqc.assemble — T0 全检总装叶 (_layoutqc 拆分叶).

``qc_paper`` 驱动全通道 (log/marks/text/bbox/raster) 并把跨臂收口
(broken_refs 加权净差/offpage 渲染佐证/geo 抑制窗), ``_tier_of``
findings → clean|warn|hard 门档，出 ``{findings, metrics, qc_tier,
sig_counts, flagged_pages}`` 契约 (§11.2)。
"""

from __future__ import annotations

import re
from collections import Counter
from contextlib import suppress
from pathlib import Path

from specs import _bootstrap

_bootstrap.ensure()

from specs._layoutqc.geocheck import _bbox_pages, _bbox_scan, _page_word_stats
from specs._layoutqc.logcheck import _collect_overfull, _frontmatter_lines, _logscan
from specs._layoutqc.markcheck import _marks_scan
from specs._layoutqc.pagekit import _run
from specs._layoutqc.rastercheck import _images_per_page, _raster_pages, _raster_scan
from specs._layoutqc.textcheck import _lcs, _missing_char_counts, _plain_scan, _skeleton
from specs._layoutqc.thresh import (
    _BLANKPAGE_RX,
    _BROKEN_BRK_RX,
    _BROKEN_REF_RX,
    _HARD_SIGS,
    _INFO_SIGS,
    _NEWLABEL_RX,
    _NORM_RX,
    _TEX_CMD_RX,
    _TEX_HAY_MAX,
    _TITLE_ARG_RX,
    _UNDEF_KEY_RX,
    _UNDEF_WHITE_RX,
    _VERB_ENV_RX,
    BROKEN_BARE_W,
    BROKEN_REFS_MIN,
    CURVES_INK_MIN,
    EMPTY_PAGE_CHARS,
    HEADER_LOST_FRAC,
    HEADER_MIN_FRAC,
    HEADER_ZONE_FRAC,
    PAGE_RATIO_HI,
    PAGE_RATIO_LO,
    SKELETON_LCS_MIN,
)
from texlate.compile.marks import parse_txlm


def _tier_of(findings: list[dict], *, marks_era: bool = False) -> str:
    """findings → ``clean|warn|hard``（§11.1 三档）。

    ``marks_era``=双臂注入编译语境时 ``marks_absent`` 升 WARN
    （注入缺席=仪表链断）；存量无注入期胞格它是 INFO 恒发。
    未分类新 sig 保守按 WARN——硬档须显式进 _HARD_SIGS。
    """
    tier = 0
    for f in findings:
        sig = f.get("sig", "")
        if sig in _HARD_SIGS:
            return "hard"
        if sig == "layout:marks_absent":
            if marks_era:
                tier = 1
            continue
        if sig in _INFO_SIGS:
            continue
        tier = max(tier, 1)
    return ("clean", "warn", "hard")[tier]


def qc_paper(
    *,
    splice_dir: Path,
    main_rel: str,
    base_dir: Path | None = None,
    src_dir: Path | None = None,
    marks_era: bool = False,
    marks_expected: bool | None = None,
    flag_dir: Path | None = None,
) -> dict:
    """一篇的 T0 全检。返回 ``{findings, metrics, qc_tier,
    sig_counts, flagged_pages}``——stage 侧直接消化。

    splice_dir/main_rel 定位 zh 产物；base_dir 缺席→跨臂项全降级为
    单侧（marks_absent/page_count/skeleton 只记 zh 侧度量）。
    ``marks_era``=双臂注入编译语境（marks_absent 升 WARN）；
    ``marks_expected``=账本出处（compile metrics inject.layout_marks
    ≥1→True、记录在而无注入→False、无记录→None）——marks_absent
    的 artifact-only 兜底闸，sentinel 可验时让位；
    ``flag_dir`` 非空且 tier≥warn 时把标记页 PNG 收割进该目录
    （§11.2 分诊素材契约）。
    """
    findings: list[dict] = []
    metrics: dict = {}
    mp = Path(main_rel)
    zh_dir = splice_dir / mp.parent
    stem = mp.stem
    # zh_pdf 解析链：{stem}.pdf → .fixloop-entry.pdf 地板快照。
    # 「最大非 fig」兜底已撤——它会把矢量图件当正文喂全部检测面
    # （geo/vis/curves 全面打偏，pdf_integrity 簇 0928 实证）；产物
    # 不在预期名位直出 no_pdf，比假 sig 诚实。
    zh_pdf = zh_dir / f"{stem}.pdf"
    if not zh_pdf.exists():
        alt = zh_dir / ".fixloop-entry.pdf"
        if alt.exists():
            zh_pdf = alt
    if zh_pdf.name != f"{stem}.pdf":
        metrics["pdf_fallback"] = zh_pdf.name
    zh_log = zh_dir / f"{stem}.log"
    zh_txlm = zh_dir / f"{stem}.txlm"

    # splice tex haystack：残英行 tex-hit 回查 + verbatim 段豁免 +
    # \maketitle/titlepage 行号集（overfull 降权）+ documentclass
    # 双面判定共用一份拼合体。
    try:
        tex_files = sorted(
            p for p in splice_dir.rglob("*") if p.suffix.lower() == ".tex"
        )[:_TEX_HAY_MAX]
    except OSError:
        tex_files = []
    parts = []
    for t in tex_files:
        with suppress(OSError):
            parts.append(t.read_text(encoding="utf-8", errors="replace"))
    src_blob = "\n".join(parts)
    tex_hay = verb_hay = None
    if src_blob:
        tex_hay = _NORM_RX.sub("", _TEX_CMD_RX.sub(" ", src_blob).lower())
        verb_hay = (
            _NORM_RX.sub(
                "",
                " ".join(m.group(2) for m in _VERB_ENV_RX.finditer(src_blob)).lower(),
            )
            or None
        )
    dc = re.search(r"\\documentclass\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}", src_blob)
    twoside = bool(
        dc
        and (
            re.search(r"twoside|openright", dc.group(1) or "")
            or dc.group(2).strip() in {"book", "scrbook", "memoir", "amsbook"}
        )
    )
    # blob 派生佐证三面：marks 注入哨兵（txlm@out/TeXlateLayoutMarks
    # 任一成注入时代编译）/tex 字面 U+FFFD 字节/\blankpage 族标记。
    # 无 tex 可验 → sentinel None（artifact-only，退回账本出处闸）。
    marks_sentinel = (
        ("txlm@out" in src_blob or "TeXlateLayoutMarks" in src_blob)
        if src_blob
        else None
    )
    tex_fffd = "\ufffd" in src_blob
    blankpage_marker = bool(src_blob) and bool(_BLANKPAGE_RX.search(src_blob))
    # \title \u53c2\u6570 squash\u2014\u2014\u6807\u9898\u9875 verso \u4f50\u8bc1\uff08_struct_head \u9875\u9996\u6bd4\u5bf9\uff09\u3002
    _tm = _TITLE_ARG_RX.search(src_blob)
    doc_title = (
        re.sub(r"\\[a-zA-Z@]+\*?|[{}\s]|\\\\", "", _tm.group(1)) if _tm else None
    )

    log_text = ""
    try:
        if zh_log.exists():
            log_text = zh_log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    btx = None
    base_pdf = None
    base_undef: set[str] = set()
    base_missing: Counter | None = None
    base_ov = None
    if base_dir is not None:
        bdir = base_dir / mp.parent
        btx = bdir / f"{stem}.txlm"
        base_pdf = bdir / f"{stem}.pdf"
        blog = bdir / f"{stem}.log"
        try:
            if blog.exists():
                blog_text = blog.read_text(encoding="utf-8", errors="replace")
                base_undef = set(_UNDEF_KEY_RX.findall(blog_text))
                # base 臂缺字集——FFFD 臂佐证差净用（源稿内嵌外文
                # 缺字源承剔出，只报管线新引入的缺字洞）。
                base_missing = _missing_char_counts(blog_text)
                # base 臂 overfull 采集——正文域条目差净用（源承溢出
                # 抵销口径见 _logscan）。
                base_ov = _collect_overfull(blog_text)
        except OSError:
            pass
    title_lines = (
        _frontmatter_lines(tex_files) if "Overfull" in log_text and tex_files else None
    )
    f, m = _logscan(log_text, title_lines, base_ov=base_ov)
    findings += f
    metrics["log"] = m
    # zh 新增悬空键 = zh − base（源承）− 类内白名单 − \Newlabel 衍生
    # 标签（elsarticle cor/addr 系）——喂 xlat_broken_refs 佐证面。
    zh_undef = set(metrics["log"].get("undef_ref_keys") or [])
    newlabel_keys = set(_NEWLABEL_RX.findall(src_blob))
    try:
        for aux in zh_dir.glob("*.aux"):
            newlabel_keys |= set(
                _NEWLABEL_RX.findall(aux.read_text(encoding="utf-8", errors="replace"))
            )
    except OSError:
        pass
    zh_new_undef = (
        zh_undef
        - base_undef
        - newlabel_keys
        - {k for k in zh_undef if _UNDEF_WHITE_RX.match(k)}
    )
    metrics["log"]["undef_new"] = sorted(zh_new_undef)
    zh_geom = parse_txlm(zh_txlm)["geom"] if zh_txlm.exists() else {}

    pages: list[dict] = []
    if zh_pdf.exists():
        zh_text = _run(["pdftotext", zh_pdf.name, "-"], cwd=zh_pdf.parent)
        zh_text_pages = zh_text.split("\f")
        if zh_text_pages and not zh_text_pages[-1].strip():
            zh_text_pages.pop()
        # 整篇 \f 切分在含图页丢假空页（2212.00026 实证：p4-7 全空、
        # -f/-l 逐页重抽有完整正文）——可疑空页逐页复核，重抽出文字
        # 则补回（degen-empty 与 raster verso 两路共用这份页列表）。
        reex = 0
        for i, ptxt in enumerate(zh_text_pages):
            if len(ptxt.strip()) >= EMPTY_PAGE_CHARS or reex >= 16:
                continue
            per = _run(
                [
                    "pdftotext",
                    "-f",
                    str(i + 1),
                    "-l",
                    str(i + 1),
                    zh_pdf.name,
                    "-",
                ],
                cwd=zh_pdf.parent,
            )
            if len(per.strip()) >= EMPTY_PAGE_CHARS:
                # 单页重抽自带尾部 \f——不剥会在回并时造幻影空页
                zh_text_pages[i] = per.rstrip("\f")
                reex += 1
        if reex:
            zh_text = "\f".join(zh_text_pages)
            metrics["text_reextracted_pages"] = reex
        base_text = None
        if base_pdf is not None and base_pdf.exists():
            base_text = _run(["pdftotext", base_pdf.name, "-"], cwd=base_pdf.parent)
        f, m = _plain_scan(
            zh_text,
            base_text or None,
            zh_log=log_text if zh_log.exists() else None,
            base_missing=base_missing,
            tex_hay=tex_hay,
            verb_hay=verb_hay,
            tex_fffd=tex_fffd,
            twoside=twoside,
            blankpage_marker=blankpage_marker,
            doc_title=doc_title,
        )
        findings += f
        metrics["text"] = m
        zh_images = _images_per_page(zh_pdf)
        pages = _bbox_pages(zh_pdf)
        f, m = _bbox_scan(pages, zh_geom, zh_images)
        findings += f
        metrics["bbox"] = m
        # 断链 ?? 收口：括号形 (?) /[?] 全权，裸 ?? 半权（tikz-cd 箭头
        # 字形与源字面 ?? 都抽成裸形）；net = zh 加权 − base 加权。
        # zh 侧取家具剔除后位点（running head 白名单键渲出的每页 ??
        # 不参与加权）；base 侧无家具信息按原值，净差方向偏保守。
        # net<MIN 且（zh log 缺席 或 zh 新增 undefined 键集空）→ 抑制
        # ——log 有真悬空键佐证时 net 不足也照报。
        bbrk = metrics["text"].get("broken_refs_brk_eff", 0)
        btot = metrics["text"].get("broken_refs_eff", 0)
        w_zh = bbrk + BROKEN_BARE_W * (btot - bbrk)
        w_base = 0.0
        if base_text:
            ebrk = len(_BROKEN_BRK_RX.findall(base_text))
            etot = len(_BROKEN_REF_RX.findall(base_text))
            w_base = ebrk + BROKEN_BARE_W * (etot - ebrk)
        bnet = w_zh - w_base
        metrics["text"]["broken_refs_net"] = round(bnet, 1)
        if bnet < BROKEN_REFS_MIN and (not zh_log.exists() or not zh_new_undef):
            before = len(findings)
            findings[:] = [f_ for f_ in findings if f_.get("sig") != "xlat_broken_refs"]
            metrics["text"]["broken_refs_suppressed"] = before - len(findings)
        if base_text:
            base_pages = base_text.split("\f")
            if base_pages and not base_pages[-1].strip():
                base_pages.pop()
            metrics["base_pages"] = len(base_pages)
            # 页数漂移
            zh_np = metrics["text"].get("npages_text") or 0
            bp = len(base_pages)
            if bp:
                ratio = zh_np / bp
                metrics["page_ratio"] = round(ratio, 3)
                if not PAGE_RATIO_LO <= ratio <= PAGE_RATIO_HI:
                    findings.append(
                        {
                            "sig": "align_page_count",
                            "zh": zh_np,
                            "base": bp,
                            "ratio": round(ratio, 3),
                        }
                    )
            # 骨架序对拍——-raw 抽（内容流序）。默认几何序在 CJK 双栏
            # 面上按基线交错抽取左右栏（2211.00151 实证：LCS 0.286→0.994
            # 全伪影），同一页内浮体垂直移位也被读成乱序（2306.00118）。
            zs_raw = _run(["pdftotext", "-raw", zh_pdf.name, "-"], cwd=zh_pdf.parent)
            bs_raw = _run(
                ["pdftotext", "-raw", base_pdf.name, "-"], cwd=base_pdf.parent
            )
            zs, bs = _skeleton(zs_raw), _skeleton(bs_raw)
            cov = _lcs(zs, bs) / max(len(bs), 1)
            metrics["skeleton_lcs"] = round(cov, 3)
            if bs and cov < SKELETON_LCS_MIN:
                findings.append(
                    {
                        "sig": "align_order_break",
                        "lcs_cov": round(cov, 3),
                        "zh_skel": len(zs),
                        "base_skel": len(bs),
                    }
                )
            # 丢图：image count 对拍
            base_images = _images_per_page(base_pdf)
            zh_imgs = sum(zh_images.values())
            base_imgs = sum(base_images.values())
            metrics["zh_images"] = zh_imgs
            metrics["base_images"] = base_imgs
            if base_imgs and zh_imgs < base_imgs:
                findings.append(
                    {"sig": "align_figure_lost", "zh": zh_imgs, "base": base_imgs}
                )
            # 页眉丢失：base 过半页有页眉而 zh 低于阈
            base_bbox = _bbox_pages(base_pdf)
            base_head = sum(
                1
                for pg in base_bbox[1:]
                if pg["h"]
                and any(
                    (y0 + y1) / 2 < pg["h"] * HEADER_ZONE_FRAC
                    for x0, y0, x1, y1, _ in pg["words"]
                )
            )
            zh_head = metrics["bbox"].get("header_pages", 0)
            bfrac = base_head / max(len(base_bbox) - 1, 1)
            zfrac = zh_head / max(len(pages) - 1, 1)
            metrics["header_frac"] = {"base": round(bfrac, 3), "zh": round(zfrac, 3)}
            if bfrac >= HEADER_MIN_FRAC and zfrac < HEADER_LOST_FRAC:
                findings.append(
                    {
                        "sig": "geo_header_lost",
                        "base_frac": round(bfrac, 3),
                        "zh_frac": round(zfrac, 3),
                    }
                )
            # 越界/重叠跨臂抑制：矢量图内部标注文字两臂同构（2609.20519
            # 实证 1805 对全在 figure 内、base 侧同数），zh ≤ base×1.5+3
            # 视为底噪不升级——只报 zh 新引入的版面碰撞。
            # base 侧 cjk_gate=False 全量计 en×en（全英原件的固有碰撞
            # 才是真底噪）；±1 页漂移窗吃 zh/base 分页错位（0812.0424
            # zh p18 vs base p19 实证）——窗内取峰值比较，
            # suppressed_with_drift 记峰值落在邻页的抑制数防窗宽误掩。
            base_geom = (
                parse_txlm(btx)["geom"] if btx is not None and btx.exists() else {}
            )
            base_stats = [
                _page_word_stats(pg, base_geom, ascii_run_exempt=False, cjk_gate=False)
                for pg in base_bbox
            ]
            kept: list[dict] = []
            suppressed = suppressed_drift = 0
            for f_ in findings:
                sig_, pg_ = f_.get("sig"), f_.get("page")
                if (
                    sig_ in ("geo_margin_breach", "geo_text_overlap")
                    and isinstance(pg_, int)
                    and base_stats
                    and 1 <= pg_ <= len(base_stats) + 1
                ):
                    lo = max(0, pg_ - 2)
                    hi = min(len(base_stats), pg_ + 1)
                    win = base_stats[lo:hi]
                    vals = [
                        (bn if sig_ == "geo_margin_breach" else bo)
                        for bn, _boff, bo, _bx, _by in win
                    ]
                    zval = f_["words"] if sig_ == "geo_margin_breach" else f_["pairs"]
                    bval = max(vals, default=0)
                    if zval <= max(bval * 1.5, bval + 3):
                        suppressed += 1
                        same_pos = (pg_ - 1) - lo
                        if 0 <= same_pos < len(vals) and bval > vals[same_pos]:
                            suppressed_drift += 1
                        continue
                kept.append(f_)
            findings[:] = kept
            metrics["base_word_stats"] = {
                "breach_by_page": [n for n, _, _ in base_stats],
                "overlap_by_page": [o for _, _, o in base_stats],
                "suppressed": suppressed,
                "suppressed_with_drift": suppressed_drift,
            }
            # 公式漂移：marks 数学 env 对拍（无 marks 时用文本侧
            # 行级近似已并入 skeleton；此处只认 marks 口径）
            if btx is not None and btx.exists() and zh_txlm.exists():
                zm = parse_txlm(zh_txlm)["marks"]
                bm = parse_txlm(btx)["marks"]
                maths = ("equation", "align", "gather", "multline", "eqnarray")
                zc = sum(
                    1
                    for v in zm.values()
                    if v["uid"].rsplit("-", 2)[0].rstrip("*") in maths
                    and v["uid"].endswith("-e")
                )
                bc = sum(
                    1
                    for v in bm.values()
                    if v["uid"].rsplit("-", 2)[0].rstrip("*") in maths
                    and v["uid"].endswith("-e")
                )
                metrics["math_envs"] = {"zh": zc, "base": bc}
                if bc and zc < bc:
                    findings.append({"sig": "align_math_drift", "zh": zc, "base": bc})
        # T1 raster：zh 单侧 + base 栏数对拍（pillow 子进程缺席时降级）
        rz = _raster_pages(zh_pdf)
        if rz.get("pages"):
            rb = (
                _raster_pages(base_pdf)
                if base_pdf is not None and base_pdf.exists()
                else {}
            )
            f, m = _raster_scan(
                rz["pages"],
                rb.get("pages"),
                zh_images,
                zh_text_pages=zh_text_pages,
                zh_geo=pages,
                twoside=twoside,
                blankpage_marker=blankpage_marker,
                doc_title=doc_title,
            )
            findings += f
            metrics["raster"] = m
            # 曲线化文本页：有墨（非空页）+ 几乎零可提取词 + 无位图
            # 对象 → 文字被渲成曲线/路径（不可复制检索，olmOCR/babeldoc
            # 族已知缺陷类）。位图图版页被 images>0 排除；带页码的空页
            # ink 极低自然不过阈。矢量图不可提取文本页仍会过——罕见，
            # 留人工分诊。
            ccs = metrics["bbox"].get("char_counts", [])
            curves = [
                i + 1
                for i, pg in enumerate(rz["pages"])
                if pg["ink"] > CURVES_INK_MIN
                and i < len(ccs)
                and ccs[i] < 10
                and zh_images.get(i + 1, 0) == 0
            ]
            if curves:
                findings.append({"sig": "geo_text_as_curves", "pages": curves})
                metrics["raster"]["curves_pages"] = curves
        elif rz.get("error") and rz["error"] != "no_pillow":
            metrics["raster_error"] = rz["error"]
            # poppler 渲染级失败 = 文件体损坏（坏 xref/断 stream，
            # 2404.14219 实证）——区别于 "empty"（父侧超时）与
            # pdftoppm:<exc>（子进程内渲染超时），按 HARD sig 立档。
            if str(rz["error"]).startswith("pdftoppm_rc"):
                findings.append({"sig": "layout:pdf_corrupt", "err": rz["error"]})
    else:
        findings.append({"sig": "layout:no_pdf"})

    # marks 查表殿后——页数比外推期望落点需要 npages 已入账
    f, m = _marks_scan(
        zh_txlm,
        btx,
        splice_dir,
        src_dir,
        zh_pages=metrics.get("text", {}).get("npages_text"),
        base_pages=metrics.get("base_pages"),
        marks_sentinel=marks_sentinel,
        marks_expected=marks_expected,
        base_dir=base_dir,
        compile_dead=bool(metrics["log"].get("compile_died")),
    )
    findings += f
    metrics["marks"] = m
    # offpage 锚渲染佐证：savepos 在变换容器内（rotatebox/resizebox/
    # sidewaystable/负 y 抬升盒）报变换前坐标——渲染在框内也判出页
    # （pdf_integrity 簇 0928 实证；offpage 簇 2026-10 复核 11 篇
    # 200 命中全是幻锚）。佐证要求「整词出纸」（x1<0|x0>w|y1<0|y0>h）
    # ——词尾 CJK 标点/Greek 的 ~4pt 探边毛刺是局部越界伤，归
    # geo_margin_breach 管，不构成锚出页佐证。页词 <3（图版/近空
    # 页）佐证力不足，保留 finding。
    if pages:
        n_supp = 0
        kept: list[dict] = []
        for f_ in findings:
            if f_.get("sig") != "layout:offpage":
                kept.append(f_)
                continue
            p_ = f_.get("p")
            if not isinstance(p_, int) or not (1 <= p_ <= len(pages)):
                kept.append(f_)
                continue
            pg = pages[p_ - 1]
            has_off_word = any(
                w_[2] < -2.0
                or w_[0] > pg["w"] + 2.0
                or w_[3] < -2.0
                or w_[1] > pg["h"] + 2.0
                for w_ in pg["words"]
            )
            if len(pg["words"]) >= 3 and not has_off_word:
                n_supp += 1
                continue
            kept.append(f_)
        if n_supp:
            findings[:] = kept
            metrics["marks"]["offpage_suppressed"] = n_supp
    # §11.2 契约键：tier/flagged/sig_counts——保留扫描器与分诊
    # 直接消费；tier≥warn 时标记页 PNG 收割（目检素材随 QC 报告走）。
    sig_counts = Counter(f_["sig"] for f_ in findings)
    flagged = sorted(
        {
            p
            for f_ in findings
            for p in (
                [f_["page"]]
                if isinstance(f_.get("page"), int)
                else f_.get("pages") or []
            )
        }
    )
    tier = _tier_of(findings, marks_era=marks_era)
    if flag_dir is not None and tier != "clean" and flagged and zh_pdf.exists():
        _raster_pages(zh_pdf, keep_dir=flag_dir, keep_pages=flagged)
    return {
        "findings": findings,
        "metrics": metrics,
        "qc_tier": tier,
        "sig_counts": dict(sig_counts),
        "flagged_pages": flagged,
    }
