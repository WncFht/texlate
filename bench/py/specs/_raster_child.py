"""T1 raster 子进程（系统 python3 + pillow，bench .venv 无 pillow）。

用法：``python3 _raster_child.py <pdf> <dpi> [keep:<outdir>:<p1,p2,...>]``
→ stdout 单行 JSON：``{pages: [{w,h,ink,dark_cc,tofu,void_frac,cols,rules}], error?}``。
keep 模式 = 收割专道：只渲指定页（-f/-l 连续段批）复制 PNG 进
outdir，不算度量、不需 pillow——二遍调用只付标记页渲染钱（176p
全扫超时实证）。

- ink：非白像素占比（<240 阈值）。
- dark_cc：最大深色连通块（<80）占页面积比（downsample 栅格 BFS）。
- void_frac：textblock 近似区（页框去 4% 边）内最大全白矩形占比
  （二值矩阵 maximal-rectangle）。
- cols：x 投影低谷法栏数（textblock 区，低谷=投影 <8% 峰值且连续
  ≥1.5% 页宽）——双栏塌陷检测用。

pdftoppm -gray -png 落临时目录（调用方管 paper_dir 下 scratch）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

_PDFTOPPM = shutil.which("pdftoppm") or "pdftoppm"
_PAGE_RX = re.compile(r"-(\d+)\.png$")


def _ink_mask(img, thr: int = 240):
    px = img.load()
    w, h = img.size
    return px, w, h, thr


def _ink_frac(img) -> float:
    w, h = img.size
    px = img.load()
    n = tot = 0
    for y in range(h):
        for x in range(w):
            tot += 1
            if px[x, y] < 240:
                n += 1
    return n / max(tot, 1)


def _cc_scan(img) -> tuple[float, int]:
    """深色连通块一次 BFS 出两口径：(最大深色块占比，tofu 空心框数)。

    tofu = .notdef 缺字框（边框有墨内部全白的小矩形）——字形尺寸
    bbox（缩图栅格 4–40px、纵横比 0.4–2.5）、**四条边沿墨率各
    ≥70%**、内部墨率 ≤15%。四边分算是为了把 O/0 字形挡掉——
    椭圆顶/底边只占 ~半宽；散点 ●/■ 实心块被内部墨率挡；偶发
    单框不簇，阈值在父级聚簇判（≥4/页）。
    """
    w, h = img.size
    scale = min(1.0, 200.0 / w)
    if scale < 1.0:
        img = img.resize((max(int(w * scale), 1), max(int(h * scale), 1)))
        w, h = img.size
    px = img.load()
    dark = [[px[x, y] < 80 for x in range(w)] for y in range(h)]
    seen = [[False] * w for _ in range(h)]
    best = 0
    tofu = 0
    for y0 in range(h):
        for x0 in range(w):
            if not dark[y0][x0] or seen[y0][x0]:
                continue
            q = [(x0, y0)]
            seen[y0][x0] = True
            n = 0
            bx0, by0, bx1, by1 = x0, y0, x0, y0
            cells = []
            while q:
                x, y = q.pop()
                n += 1
                cells.append((x, y))
                bx0, by0 = min(bx0, x), min(by0, y)
                bx1, by1 = max(bx1, x), max(by1, y)
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if (
                        0 <= nx < w
                        and 0 <= ny < h
                        and dark[ny][nx]
                        and not seen[ny][nx]
                    ):
                        seen[ny][nx] = True
                        q.append((nx, ny))
            best = max(best, n)
            bw, bh = bx1 - bx0 + 1, by1 - by0 + 1
            if not (4 <= bw <= 40 and 4 <= bh <= 40 and 0.4 <= bw / bh <= 2.5):
                continue
            cellset = set(cells)
            top = sum(1 for x in range(bx0, bx1 + 1) if (x, by0) in cellset)
            bot = sum(1 for x in range(bx0, bx1 + 1) if (x, by1) in cellset)
            lft = sum(1 for y in range(by0, by1 + 1) if (bx0, y) in cellset)
            rgt = sum(1 for y in range(by0, by1 + 1) if (bx1, y) in cellset)
            inner = inner_ink = 0
            for y in range(by0 + 1, by1):
                for x in range(bx0 + 1, bx1):
                    inner += 1
                    if (x, y) in cellset:
                        inner_ink += 1
            if (
                top >= bw * 0.7
                and bot >= bw * 0.7
                and lft >= bh * 0.7
                and rgt >= bh * 0.7
                and inner
                and inner_ink / inner <= 0.15
            ):
                tofu += 1
    return best / max(w * h, 1), tofu


def _rules(img) -> int:
    """长横线规则行数——textblock 近似区内连续墨 run ≥30% 区宽的
    行段（相邻规则行合并为一条）。booktabs 三线上下的真规则；
    跨臂比对吃图内轴线（坐标轴两臂同构），单臂只出度量。

    分析宽度必须 ≥300px：200px 栅格下拉丁整行文字糊成 ≥30% 连墨
    伪规则（en 摘要段逐行误计，2403.05143 base 26 vs zh 11 实证
    ——两臂同为 2 真规则），400px 字形间隙复现、两臂口径对齐。"""
    w, h = img.size
    scale = min(1.0, 400.0 / w)
    if scale < 1.0:
        img = img.resize((max(int(w * scale), 1), max(int(h * scale), 1)))
        w, h = img.size
    px = img.load()
    m = int(w * 0.04), int(h * 0.04)
    x0, x1 = m[0], w - m[0]
    y0, y1 = m[1], h - m[1]
    thr = (x1 - x0) * 0.30
    rules = 0
    in_run = False
    for y in range(y0, y1):
        run = best = 0
        for x in range(x0, x1):
            run = run + 1 if px[x, y] < 240 else 0
            best = max(best, run)
        if best >= thr:
            if not in_run:
                rules += 1
                in_run = True
        else:
            in_run = False
    return rules


def _void_frac(img) -> tuple[float, float, float]:
    """textblock 近似区内白区三口径。返 (最大白矩形占比，最大内部
    白连通块占比，块内墨率)——内部白块要求连通块不贴测量区任何边
    （真「掉图窟窿」语义：洞四周皆有墨；目录收尾/末页留白必贴底边，
    天然不报警；页底背景是一个贴边巨连通块，不进内部口径）。
    块内墨率 = 最大内部白 CC 的包围盒内墨像素占比——tcolorbox/
    listing/坐标框封出的白内腔装着文字/图件（墨>0），真空洞≈0
    （0928 blank_void 簇：12/12 void 格全是框内白腔误报）。"""
    w, h = img.size
    scale = min(1.0, 160.0 / w)
    if scale < 1.0:
        img = img.resize((max(int(w * scale), 1), max(int(h * scale), 1)))
        w, h = img.size
    px = img.load()
    m = int(w * 0.04), int(h * 0.04)
    cols = list(range(m[0], w - m[0]))
    rows = list(range(m[1], h - m[1]))
    if not cols or not rows:
        return 0.0, 0.0, 0.0
    nc, nr = len(cols), len(rows)
    white = [[px[x, y] >= 240 for x in cols] for y in rows]
    # 口径一：最大白矩形（histogram maximal-rectangle）——栈存
    # (左界，高) 对：弹出高度须随左界回传，存索引会读到原位
    # 陈旧 heights 致整页虚报 1.0（2403.05234 实证）。
    heights = [0] * nc
    best = 0
    for row in white:
        for c, cell in enumerate(row):
            heights[c] = heights[c] + 1 if cell else 0
        stack: list[tuple[int, int]] = []
        for i in range(nc + 1):
            cur = heights[i] if i < nc else 0
            start = i
            while stack and stack[-1][1] > cur:
                idx, hh = stack.pop()
                best = max(best, hh * (i - idx))
                start = idx
            stack.append((start, cur))
    # 口径二：不贴区边的最大白色连通块（4-邻接 BFS）——顺手记下
    # 冠军块的包围盒，供口径三量块内墨率。
    seen = [[False] * nc for _ in range(nr)]
    best_int = 0
    best_box: tuple[int, int, int, int] | None = None
    for y0 in range(nr):
        for x0 in range(nc):
            if not white[y0][x0] or seen[y0][x0]:
                continue
            q = [(x0, y0)]
            seen[y0][x0] = True
            n = 0
            touches = False
            bx0 = by0 = nc + nr
            bx1 = by1 = -1
            while q:
                x, y = q.pop()
                n += 1
                bx0, by0 = min(bx0, x), min(by0, y)
                bx1, by1 = max(bx1, x), max(by1, y)
                if x == 0 or y == 0 or x == nc - 1 or y == nr - 1:
                    touches = True
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if (
                        0 <= nx < nc
                        and 0 <= ny < nr
                        and white[ny][nx]
                        and not seen[ny][nx]
                    ):
                        seen[ny][nx] = True
                        q.append((nx, ny))
            if not touches and n > best_int:
                best_int = n
                best_box = (bx0, by0, bx1, by1)
    tot = max(nc * nr, 1)
    void_ink = 0.0
    if best_box is not None:
        bx0, by0, bx1, by1 = best_box
        area = max((bx1 - bx0 + 1) * (by1 - by0 + 1), 1)
        ink = sum(
            1
            for y in range(by0, by1 + 1)
            for x in range(bx0, bx1 + 1)
            if not white[y][x]
        )
        void_ink = ink / area
    return best / tot, best_int / tot, void_ink


def _columns(img) -> int:
    """x 投影低谷栏数——横带众数法（textblock 近似区分 ~6 横带各算
    栏数取众数）。整页投影会被跨栏通图把栏沟填满而误判 1 栏
    （2502.15152 base 实证：通栏大图占上半页 → 沟内全图墨）；横带
    化后图带报 1、文带报真栏数，众数胜出。稀疏带跳过。"""
    w, h = img.size
    px = img.load()
    m = int(w * 0.04), int(h * 0.04)
    x0, x1 = m[0], w - m[0]
    y0, y1 = m[1], h - m[1]
    nband = 6
    bh = max((y1 - y0) // nband, 1)
    votes = []
    for b in range(nband):
        by0 = y0 + b * bh
        by1 = y1 if b == nband - 1 else min(by0 + bh, y1)
        proj = [0] * w
        for x in range(x0, x1):
            for y in range(by0, by1):
                if px[x, y] < 240:
                    proj[x] += 1
        peak = max(proj) or 1
        ink_thr = peak * 0.08
        inked = [x for x in range(x0, x1) if proj[x] >= ink_thr]
        ink_px = sum(proj)
        if len(inked) < w * 0.05 or ink_px < (x1 - x0) * (by1 - by0) * 0.005:
            continue  # 稀疏带——词间空隙会伪充栏沟
        lo, hi = inked[0], inked[-1]
        valleys = 0
        run = 0
        for x in range(lo, hi + 1):
            if proj[x] < ink_thr:
                run += 1
            else:
                if run >= w * 0.015:
                    valleys += 1
                run = 0
        votes.append(min(valleys + 1, 4))
    if not votes:
        return None  # 全页稀疏——栏数无意义
    return Counter(votes).most_common(1)[0][0]


def _ranges(pages: list[int]) -> list[tuple[int, int]]:
    """连续页号并段——pdftoppm -f/-l 批渲用。"""
    out: list[tuple[int, int]] = []
    for p in sorted(pages):
        if out and p == out[-1][1] + 1:
            out[-1] = (out[-1][0], p)
        else:
            out.append((p, p))
    return out


def main() -> int:
    pdf = Path(sys.argv[1])
    dpi = sys.argv[2] if len(sys.argv) > 2 else "60"
    keep_dir = keep_pages = None
    for a in sys.argv[3:]:
        if a.startswith("keep:"):
            _, kd, kp = a.split(":", 2)
            keep_dir = Path(kd)
            keep_pages = {int(x) for x in kp.split(",") if x}
    # pdf.parent 可只读（vault 固化格 0555）→ 退回系统 tempdir
    scratch = pdf.parent if os.access(pdf.parent, os.W_OK) else None
    if keep_dir is not None and keep_pages:
        # 收割专道：只渲标记页（连续段 -f/-l 批），不算度量、不需
        # pillow——二遍调用不重复全篇渲染 + 扫描的钱。
        keep_dir.mkdir(parents=True, exist_ok=True)
        kept: list[str] = []
        with tempfile.TemporaryDirectory(dir=scratch) as td:
            for lo, hi in _ranges(sorted(keep_pages)):
                prefix = str(Path(td) / "pg")
                try:
                    r = subprocess.run(
                        [
                            _PDFTOPPM,
                            "-gray",
                            "-r",
                            dpi,
                            "-png",
                            "-f",
                            str(lo),
                            "-l",
                            str(hi),
                            pdf.name,
                            prefix,
                        ],
                        cwd=pdf.parent,
                        capture_output=True,
                        timeout=180,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    continue
                if r.returncode != 0:
                    continue
                for p in sorted(Path(td).glob("pg-*.png")):
                    m = _PAGE_RX.search(p.name)
                    if m is None:
                        continue
                    dst = keep_dir / f"{pdf.stem}-p{int(m.group(1)):03d}.png"
                    dst.write_bytes(p.read_bytes())
                    p.unlink()
                    kept.append(dst.name)
        print(json.dumps({"pages": [], "kept": kept}))
        return 0
    try:
        from PIL import Image
    except ImportError:
        print(json.dumps({"error": "no_pillow"}))
        return 0
    out = {"pages": []}
    with tempfile.TemporaryDirectory(dir=scratch) as td:
        prefix = str(Path(td) / "pg")
        try:
            r = subprocess.run(
                [_PDFTOPPM, "-gray", "-r", dpi, "-png", pdf.name, prefix],
                cwd=pdf.parent,
                capture_output=True,
                timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            print(json.dumps({"error": f"pdftoppm:{e}"}))
            return 0
        if r.returncode != 0:
            print(json.dumps({"error": f"pdftoppm_rc:{r.returncode}"}))
            return 0
        for p in sorted(Path(td).glob("pg-*.png")):
            try:
                img = Image.open(p).convert("L")
            except Exception:  # noqa: S112 — 单页 PNG 解码失败跳过（页级降级不毙整篇；stdout 是 JSON 协议面不能 log）
                continue
            w, h = img.size
            vf, vi, vink = _void_frac(img)
            dark, tofu = _cc_scan(img)
            out["pages"].append(
                {
                    "w": w,
                    "h": h,
                    "ink": round(_ink_frac(img), 4),
                    "dark_cc": round(dark, 4),
                    "tofu": tofu,
                    "rules": _rules(img),
                    "void_frac": round(vf, 4),
                    "void_int": round(vi, 4),
                    "void_ink": round(vink, 4),
                    "cols": _columns(img),
                }
            )
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
