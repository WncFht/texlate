"""specs._layoutqc.geocheck — 词面/bbox 几何叶 (_layoutqc 拆分叶).

pymupdf clip-aware 词面 (缺席退 pdftotext -bbox) + 封印框聚簇 +
textblock 矩形 + 越界/离页/跨行重叠/页眉判定——word-bbox 通道全检。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from specs._layoutqc.pagekit import _run
from specs._layoutqc.thresh import (
    _ASCII_RUN_GAP,
    _ASCII_RUN_MIN,
    _CJK_PUNCT_L,
    _CJK_PUNCT_R,
    _CJK_RX,
    _FRAME_CLUSTER_MAX,
    _MATH_RX,
    _NONCHAR_RX,
    HEADER_ZONE_FRAC,
    MARGIN_BREACH_MIN,
    MARGIN_BREACH_PT,
    OVERLAP_GRAZE_HI,
    OVERLAP_GRAZE_IY,
    OVERLAP_IOU,
    OVERLAP_MIN_PAIRS,
    PT2BP,
    VOID_FRAME_MIN_FRAC,
)

if TYPE_CHECKING:
    from pathlib import Path


#: zh 参与判定——CJK 命中且不含 U+FFFD 或 noncharacter（图内坏 cmap
#: 字体抽出的 ``푣 ``/`` 푥￿`` 类 token 不算 zh 墨，2503.05281 实证）。
def _zh_tok(t: str) -> bool:
    return (
        _CJK_RX.search(t) is not None
        and "\ufffd" not in t
        and _NONCHAR_RX.search(t) is None
    )


def _page_frames(pg, words: list[tuple]) -> list[dict]:
    """矢量框线聚簇 → 每页「封印框」候选 [{rect, words, art}]——
    vis_void 的 frames 兜底闸：tcolorbox/lstlisting/axis 框把白连通块
    封出内部洞形是合法排版，框内有词或有小矢量件即非掉图窟窿。

    pymupdf get_drawings 把框拆成逐边独立 path（2605.27680 实证 4 条
    边线分列），须 union-find 把「相交或 ≤2pt 间隙」的 path rect 聚簇；
    聚出 rect 占页 ≥15% 才算框（散点小件不聚出大簇）。簇内数：
    词 = 词心落入数；art = 严格内嵌的小矢量件数（坐标轴刻度/ticks）。
    """
    try:
        rects = [d["rect"] for d in pg.get_drawings() if d.get("rect")]
    except Exception:  # 个别页 drawings 解码失败不毙整篇
        return []
    # 退化 rect（零高/零宽的框边线）不能丢——框就是四条边线聚簇
    # 出来的（2605.27680 p17 实证：tcolorbox 4 条 is_empty 边线）。
    rects = [r for r in rects if r is not None]
    pw = pg.rect.width
    ph = pg.rect.height
    dil = 2.0

    # 共线游程合并：listings 系把框侧边渲成逐行 \\vrule 短段堆叠
    # （1812.00089 p44 实证 ~40 段 14pt 竖段链成 605pt 边），先沿
    # 主轴把「同车道且首尾相接 ≤2pt」的段并成一条，否则短段聚簇
    # 全对配是 O(n²) 炸弹且框认不出。排序键=垂直车道中心；run
    # 中心钉首个成员——连锁漂移限 2·dil 带宽。
    def _merge_runs(idx: list[int], horiz: bool) -> list:
        if horiz:
            order = sorted(idx, key=lambda i: (rects[i].y0 + rects[i].y1) / 2)
        else:
            order = sorted(idx, key=lambda i: (rects[i].x0 + rects[i].x1) / 2)
        runs: list[list] = []  # [lane_center, x0,y0,x1,y1]
        for i in order:
            r = rects[i]
            c = (r.y0 + r.y1) / 2 if horiz else (r.x0 + r.x1) / 2
            lo = r.x0 if horiz else r.y0
            hi = r.x1 if horiz else r.y1
            axis_lo = 1 if horiz else 2  # run 里沿轴起/端坐标槽位
            axis_hi = 3 if horiz else 4
            for run in reversed(runs[-3:]):
                if (
                    abs(c - run[0]) <= dil
                    and lo <= run[axis_hi] + dil
                    and hi + dil >= run[axis_lo]
                ):
                    run[1] = min(run[1], r.x0)
                    run[2] = min(run[2], r.y0)
                    run[3] = max(run[3], r.x1)
                    run[4] = max(run[4], r.y1)
                    break
            else:
                runs.append([c, r.x0, r.y0, r.x1, r.y1])
        return [tuple(run[1:]) for run in runs]

    horiz = [i for i, r in enumerate(rects) if r.width >= r.height]
    vert = [i for i, r in enumerate(rects) if r.width < r.height]
    merged = _merge_runs(horiz, True) + _merge_runs(vert, False)
    # 聚簇对配：合并后仍密（矢量散点页数千小件互不并合）时只过
    # 长边——封印框的边必是长条（≥12% 页长），小件聚不出 15%
    # 面积簇，只作簇内 art 计数。
    if len(merged) > _FRAME_CLUSTER_MAX:
        cand = [
            i
            for i, r in enumerate(merged)
            if max(r[2] - r[0], r[3] - r[1]) >= 0.12 * max(pw, ph)
        ]
    else:
        cand = list(range(len(merged)))
    if not cand:
        return []
    par = {i: i for i in cand}

    def find(i: int) -> int:
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    for a, i in enumerate(cand):
        ri = merged[i]
        for j in cand[a + 1 :]:
            rj = merged[j]
            if not (
                ri[2] + dil < rj[0]
                or rj[2] + dil < ri[0]
                or ri[3] + dil < rj[1]
                or rj[3] + dil < ri[1]
            ):
                par[find(i)] = find(j)
    clusters: dict[int, list] = {}
    for i in cand:
        clusters.setdefault(find(i), []).append(i)
    out: list[dict] = []
    for ids in clusters.values():
        # 手算并 bbox——pymupdf ``|`` 对退化（零面积）rect 返回空
        # 操作数（1.28.2 实证），框边线聚簇必须用坐标 min/max。
        x0 = min(merged[i][0] for i in ids)
        y0 = min(merged[i][1] for i in ids)
        x1 = max(merged[i][2] for i in ids)
        y1 = max(merged[i][3] for i in ids)
        if (x1 - x0) * (y1 - y0) < pw * ph * VOID_FRAME_MIN_FRAC:
            continue
        nw = sum(
            1
            for wx0, wy0, wx1, wy1, _ in words
            if x0 <= (wx0 + wx1) / 2 <= x1 and y0 <= (wy0 + wy1) / 2 <= y1
        )
        art = sum(
            1
            for i in range(len(merged))
            if i not in ids
            and x0 < merged[i][0]
            and merged[i][2] < x1
            and y0 < merged[i][1]
            and merged[i][3] < y1
        )
        out.append({"rect": (x0, y0, x1, y1), "words": nw, "art": art})
    return out


def _bbox_pages_mupdf(pdf: Path) -> list[dict] | None:
    """pymupdf 词面（可选件缺席/坏档 → None 回落 poppler）——clip-aware：
    splice 常把整页源内容封成 Form XObject 裁框当矢量图用，被裁掉部分的
    en 词 poppler 仍全数报出（幻影层），mupdf 与渲染器同口径不收录
    （2609.05962 p11 实证 pdftotext 460 词 vs mupdf 82 词，幻影 en 行
    压在 zh 行上成 96 对假重叠）。
    /Rotate 页：get_text("words") 出未旋转坐标——乘 rotation_matrix
    映射回显示轴（1003.5197 p25 实证），否则 rot 页 margin/overlap 全
    在错轴上量。"""
    try:
        import pymupdf
    except ImportError:
        return None
    try:
        with pymupdf.open(str(pdf)) as doc:
            pages: list[dict] = []
            for pg in doc:
                rot = pg.rotation
                ws = [tuple(w[:5]) for w in pg.get_text("words")]
                if rot:
                    rm = pg.rotation_matrix
                    ws = [
                        (r.x0, r.y0, r.x1, r.y1, w[4])
                        for w in ws
                        for r in (pymupdf.Rect(w[:4]) * rm,)
                    ]
                pages.append(
                    {
                        "w": pg.rect.width,
                        "h": pg.rect.height,
                        "rot": rot,
                        "words": ws,
                        "frames": _page_frames(pg, ws),
                    }
                )
            return pages
    except Exception:
        return None


def _bbox_pages(pdf: Path) -> list[dict]:
    """[{w,h,words:[(x0,y0,x1,y1,text)]}]（pt 轴、原点左上）——词源
    pymupdf 优先（clip-aware），缺席退 ``pdftotext -bbox``（clip-blind，
    幻影源文面会虚报 overlap/margin）。"""
    mp = _bbox_pages_mupdf(pdf)
    if mp is not None:
        return mp
    xml = _run(["pdftotext", "-bbox", pdf.name, "-"], cwd=pdf.parent)
    if not xml:
        return []
    pages: list[dict] = []
    cur: dict | None = None
    for m in re.finditer(
        r'<page\s+width="([\d.]+)"\s+height="([\d.]+)"|'
        r'<word\s+xMin="([\d.]+)"\s+yMin="([\d.]+)"\s+xMax="([\d.]+)"\s+'
        r'yMax="([\d.]+)"[^>]*>([^<]*)</word>|</page>',
        xml,
    ):
        if m.group(1) is not None:
            cur = {"w": float(m.group(1)), "h": float(m.group(2)), "words": []}
            pages.append(cur)
        elif m.group(3) is not None and cur is not None:
            cur["words"].append(
                (
                    float(m.group(3)),
                    float(m.group(4)),
                    float(m.group(5)),
                    float(m.group(6)),
                    m.group(7),
                )
            )
        else:
            cur = None
    return pages


def _textblock(geom: dict, page_w: float, page_h: float) -> tuple:
    """GEOM → textblock 矩形（bp，原点左上，与 pdftotext 同系）。
    GEOM 各量单位 TeX pt（72.27/in），mediabox 单位 bp（72/in）——
    letter 两侧分别是 614.295pt / 612bp，不换算会伪报纸型失配。
    GEOM 缺席或纸型真失配（本身即是缺陷信号，marks 坐标轴同受害）
    退 92% 页框。"""
    keys = ("pw", "ph", "tw", "th", "tm", "hh", "hs", "ho", "vo", "oi")
    if (
        geom
        and all(k in geom for k in keys)
        and abs(geom["pw"] * PT2BP - page_w) < 2.0
        and abs(geom["ph"] * PT2BP - page_h) < 2.0
    ):
        left = (72.27 + geom["ho"] + geom["oi"]) * PT2BP
        top = (72.27 + geom["vo"] + geom["tm"] + geom["hh"] + geom["hs"]) * PT2BP
        return left, top, left + geom["tw"] * PT2BP, top + geom["th"] * PT2BP
    m = 0.04
    return page_w * m, page_h * m, page_w * (1 - m), page_h * (1 - m)


def _sym_tok(t: str) -> bool:
    """数学符号 token——≤2 字符且全为非字母数字（√ ∼ ± → ∫ ∑ 等
    bbox 瘦高符号；\\stackrel{iid}{\\sim} 堆叠的 iid×∼ 假重叠对
    即此类）。CJK 在 Python 里算 alnum，不受影响。"""
    return len(t) <= 2 and not any(c.isalnum() for c in t)


def _math_tok(t: str) -> bool:
    """重叠判定的数学 token——_sym_tok 之外再收：含数学字符的 token
    （math-alnum 𝑖𝛼𝜃、letterlike ℝ𝔼ℏℓ、组合重音 Q̂/ˆ、算子 ∫∑∏√∂∇、
    希腊字母等）。pymupdf 把公式堆叠/上下标与 CJK 合 unionbox，含数学
    字符的合并簇（``⟨n⟩为一个强 C`` 形）整体豁免——同时覆盖
    「CJK+ 数学字符」merged-cluster 臂。"""
    return _sym_tok(t) or _MATH_RX.search(t) is not None


def _word_overlap_pairs(words: list[tuple], cjk_gate: bool = True) -> int:
    """跨行词重叠对数——同行相邻词天然贴近不算，只数「y 中心差 > 半词高
    且 bbox IoU > 阈」对（#615 重叠对法）。扫线法 O(n log n + k)。
    数学 token 不参与——瘦高 bbox 天然与邻行堆叠；含数学字符的合并簇
    （math+CJK unionbox）同豁免。
    CJK 参与闸（cjk_gate，zh 侧默认）：splice 只产 zh 墨——en×en 对非
    本管线产物（图内源侧碰撞）；base 侧（纯 en 文档对拍）传 False 全量
    计，否则 src-inherent 碰撞永远 suppress 不掉。
    对级豁免两层：堆叠（小盒 x 区间被大盒包含 ±2pt 且小 token ≤4 字符
    无 CJK——frac 分子/上下标原子）与相擦带（IoU∈[0.30,0.45) 且纵向
    重叠 <2.5pt 或 <小盒高 20%——bbox 相擦非墨触）。"""
    ws = sorted(words, key=lambda w: (w[1] + w[3]) / 2)
    n = 0
    for i, a in enumerate(ws):
        if _math_tok(a[4]):
            continue
        acy = (a[1] + a[3]) / 2
        ah = max(a[3] - a[1], 1e-6)
        for b in ws[i + 1 :]:
            bcy = (b[1] + b[3]) / 2
            if bcy - acy > max(ah, b[3] - b[1]) * 2:
                break  # y 序扫出窗
            if abs(bcy - acy) < ah * 0.5:
                continue  # 同行
            if _math_tok(b[4]):
                continue  # 数学 token/合并簇
            if cjk_gate and not (_zh_tok(a[4]) or _zh_tok(b[4])):
                continue  # en×en——非 splice 产物（图内源侧/残留 en 面）
            ix = min(a[2], b[2]) - max(a[0], b[0])
            iy = min(a[3], b[3]) - max(a[1], b[1])
            if ix <= 0 or iy <= 0:
                continue
            inter = ix * iy
            sa = (a[2] - a[0]) * (a[3] - a[1])
            sb = (b[2] - b[0]) * (b[3] - b[1])
            small = min(sa, sb)
            if small <= 0 or inter / small <= OVERLAP_IOU:
                continue
            # 堆叠豁免：小盒被大盒 x 向包含（±2pt）且是 ≤4 字符非 CJK
            # 原子——frac 分子/上下标 bbox 上探行盒是合法排版
            s, g = (a, b) if sa <= sb else (b, a)
            if (
                g[0] - 2.0 <= s[0]
                and s[2] <= g[2] + 2.0
                and len(s[4]) <= 4
                and not _CJK_RX.search(s[4])
            ):
                continue
            # 相擦带：阈上低 IoU + 纵向重叠极薄 → bbox 相擦非墨触
            if inter / small < OVERLAP_GRAZE_HI and (
                iy < OVERLAP_GRAZE_IY or iy < 0.2 * (s[3] - s[1])
            ):
                continue
            n += 1
    return n


def _page_word_stats(
    pg: dict, geom: dict, ascii_run_exempt: bool = True, cjk_gate: bool = True
) -> tuple[int, int, int]:
    """单页 (越界词数，离页词数，跨行重叠对数)——跨臂按页对拍的最小单位。
    越界只数正文带内的词：running head / 页码等页眉页脚家具本就
    骑在 textblock 之外（2608.25736 p7 实证——页眉行触发全页
    breach），cy < t 或 cy > b+20 的词不算。``ascii_run_exempt``
    开（zh 侧）：越界词在 ≥_ASCII_RUN_MIN 词 ASCII 连跑内即免——
    verbatim 附录行溢出归 en 原文同形。base 侧（纯 en 文档）传
    False 全量计——跨臂抑制要的是 en 原件的固有溢出量，豁免会
    把 base 侧压成 0 使抑制退化。
    离页词数 = 越界词中 bbox 真正出纸面的子集（x0<-tol|x1>w+tol|
    y0<-tol|y1>h+tol）——页内深带（folio 家具/源置 geometry）是另
    一类；``cjk_gate`` 传给重叠对判定，base 侧 False。"""
    left, t, r, b = _textblock(geom, pg["w"], pg["h"])
    tol = MARGIN_BREACH_PT
    words = pg["words"]
    run_len: dict[int, int] = {}
    if ascii_run_exempt:
        # cy 序贪心聚行成横带（cy 差 < 行高×0.5 归一带），带内 x 序
        # 切 ASCII 连跑：相邻 ASCII 词间距 ≤_ASCII_RUN_GAP 续跑，
        # CJK/符号词或大空隙断跑
        wline = [-1] * len(words)
        nlines = 0
        cur_cy = cur_h = 0.0
        for i in sorted(
            range(len(words)), key=lambda j: (words[j][1] + words[j][3]) / 2
        ):
            cy = (words[i][1] + words[i][3]) / 2
            h = max(words[i][3] - words[i][1], 1e-6)
            if nlines == 0 or cy - cur_cy >= max(cur_h, h) * 0.5:
                nlines += 1
                cur_cy, cur_h = cy, h
            wline[i] = nlines - 1
        for ln in range(nlines):
            cur: list[int] = []
            prev_x1 = -1e18
            for i in sorted(
                (j for j in range(len(words)) if wline[j] == ln),
                key=lambda j: words[j][0],
            ):
                x0, x1, wtext = words[i][0], words[i][2], words[i][4]
                if wtext.isascii():
                    if cur and x0 - prev_x1 > _ASCII_RUN_GAP:
                        for j in cur:
                            run_len[j] = len(cur)
                        cur = []
                    cur.append(i)
                elif not _sym_tok(wtext):
                    # CJK 等实质非 ASCII 词断跑；数学符号 token 透明
                    # 穿透——``x ≥ t → a`` 伪码行不被劈成短跑误计
                    for j in cur:
                        run_len[j] = len(cur)
                    cur = []
                prev_x1 = x1
            for j in cur:
                run_len[j] = len(cur)
    nb = off = 0
    pw, ph = pg["w"], pg["h"]
    for i, (x0, y0, x1, y1, wtext) in enumerate(words):
        cy = (y0 + y1) / 2
        if not (t - 2 <= cy <= b + 20.0):
            continue
        if _sym_tok(wtext) or run_len.get(i, 0) >= _ASCII_RUN_MIN:
            continue  # 数学符号 token / verbatim 英文段越界豁免
        h = max(y1 - y0, 1e-6)
        bx0 = x0 + (h * 0.6 if wtext[:1] in _CJK_PUNCT_L else 0.0)
        bx1 = x1 - (h * 0.6 if wtext[-1:] in _CJK_PUNCT_R else 0.0)
        if bx0 < left - tol or bx1 > r + tol or y1 > b + tol:
            nb += 1
            if bx0 < -tol or bx1 > pw + tol or y0 < -tol or y1 > ph + tol:
                off += 1
    return nb, off, _word_overlap_pairs(words, cjk_gate=cjk_gate)


def _bbox_scan(
    pages: list[dict], geom: dict, images_per_page: dict[int, int]
) -> tuple[list[dict], dict]:
    """word-bbox 层：越界/重叠/浮体挤页/页眉丢失（页眉判读在
    cross-arm 段——此处只产 per-page 度量）。"""
    findings: list[dict] = []
    metrics: dict = {"pages": len(pages)}
    # 纸型失配：GEOM pw/ph（\paperwidth，TeX pt）vs PDF 全页众数尺寸
    # （bp）——只比 pages[0] 会把期刊 trim-size special 的合法单页
    # 偏离升 HARD（0928 实证）；众数失配才是真的纸型错，偶发单页
    # 偏离仅记账。
    if pages and geom.get("pw") and geom.get("ph"):
        sizes = Counter((round(p["w"], 1), round(p["h"], 1)) for p in pages)
        (mw, mh), n_mode = sizes.most_common(1)[0]
        odd = [
            i + 1
            for i, p in enumerate(pages)
            if (round(p["w"], 1), round(p["h"], 1)) != (mw, mh)
        ]
        if odd:
            metrics["paper_size_odd_pages"] = odd
        if abs(geom["pw"] * PT2BP - mw) >= 2.0 or abs(geom["ph"] * PT2BP - mh) >= 2.0:
            findings.append(
                {
                    "sig": "layout:paper_mismatch",
                    "geom": [geom["pw"], geom["ph"]],
                    "pdf": [mw, mh],
                    "mode_pages": n_mode,
                }
            )
    breach_n = overlap_n = band_n = 0
    word_counts: list[int] = []
    char_counts: list[int] = []
    head_hits = 0
    breach_by_page: list[int] = []
    overlap_by_page: list[int] = []
    for pi, pg in enumerate(pages):
        words = pg["words"]
        word_counts.append(len(words))
        # CJK 无空格文本按空格计词天然 <3 词/页——text_as_curves
        # 改吃字符数（0928 pdf_integrity 簇：可读正文页被误判曲线化）
        char_counts.append(sum(len(w[4]) for w in words))
        nb, off, op = _page_word_stats(pg, geom)
        breach_by_page.append(nb)
        overlap_by_page.append(op)
        if nb >= MARGIN_BREACH_MIN and off >= 1:
            breach_n += nb
            findings.append(
                {
                    "sig": "geo_margin_breach",
                    "page": pi + 1,
                    "words": nb,
                    "off": off,
                }
            )
        elif nb >= MARGIN_BREACH_MIN:
            # 全量「越界」词其实都在纸面内——只是骑进 textblock 深带：
            # 源置 geometry（revtex 窄栏 folio）、页码/running head
            # 残词等非离页现象；INFO 立档不报警。
            band_n += nb
            findings.append({"sig": "geo_deep_band", "page": pi + 1, "words": nb})
        if op >= OVERLAP_MIN_PAIRS:
            overlap_n += op
            findings.append({"sig": "geo_text_overlap", "page": pi + 1, "pairs": op})
        if (
            pi >= 1
            and pg["h"]
            and any(
                (y0 + y1) / 2 < pg["h"] * HEADER_ZONE_FRAC
                for x0, y0, x1, y1, _ in words
            )
        ):
            head_hits += 1
    metrics["margin_breach_words"] = breach_n
    metrics["deep_band_words"] = band_n
    metrics["overlap_pairs"] = overlap_n
    metrics["breach_by_page"] = breach_by_page
    metrics["overlap_by_page"] = overlap_by_page
    metrics["header_pages"] = head_hits
    metrics["word_counts"] = word_counts
    metrics["char_counts"] = char_counts
    return findings, metrics
