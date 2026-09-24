"""seq 级 PDF 位置对位——``GET /reader`` 响应注入 ``seqpos`` 字段。

zh.pdf 有 TLXC 标记（``BDC /MCID=50000+seq``，``latex/reconstruct.py`` 注锚）→
pypdf ``visitor_operand_before`` 直读精确点锚；en.pdf（base 编译链无标记）
与未标记 zh seq 走文本匹配：chunk 文本 texstrip+alnum 归一成 needle，PDF
``extract_text`` 聚行成归一化字符流（行界记 page/fraction）。匹配两遍——
光标窗口快路建单调骨架，漏跑段在相邻命中夹逼的流区间内 6-gram 锚定补缺
（浮动体出序/字体丢空格粘连都能救回）。行界记 ``(char_off,page,frac,x)``
——x 是段左缘页宽分位，栏判定/阅读序键 ``(page,col,frac)`` 的原料。
结果缓存 ``task_dir/seqpos.json``，
输入件 mtime 更新即重算；dual.json 本体不动（``?version=sha256`` 不可变）。
"""

from __future__ import annotations

import bisect
import contextlib
import json
import logging
import posixpath
import re
import unicodedata
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

from texlate.xlat.state import atomic_json

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

log = logging.getLogger(__name__)

__all__ = ["seqpos_for_task"]

_CACHE = "seqpos.json"
_VERSION = 9

#: 行聚类 y 容差（pt，底向上坐标同线合并）
_LINE_TOL = 2.5
# 锚 fraction 取行顶而非基线：tm 的 y 是基线原点，floor 语义下点击行
# 上半会漏回上一条 seq（实字形矩形仿真实证）——行顶=基线+ascender
_ASC = 0.8
#: CJK 全宽下界（_est_w 栏切宽度粗估）
_CJK_MIN = 0x2E7F
#: _min_cov 针长分档
_COV_SHORT = 30
_COV_MID = 80
#: 双栏检测下限行数 / 中缝最小宽度（pt）
_COL_MIN_LINES = 8
_GUTTER_MIN_W = 10
_GUTTER_MIN_SIDE = 4
#: BDC 操作数个数（tag + properties）
_BDC_ARGC = 2


def _min_cov(ln: int) -> float:
    """SM 覆盖率阈值——低于则判 miss 进补缺遍。

    短 needle 匹配太廉价（0.55×13 字≈7 字符重合就过）会锚到无关位、
    拖死顺序光标级联塌方——阈值随长度收：短针近乎要全中。
    """
    if ln < _COV_SHORT:
        return 0.92
    if ln < _COV_MID:
        return 0.7
    return 0.55


#: 锚定 gram 长（字符）；needle 更短则取全长
_GRAM = 6
#: 单 gram 频度上限——超了没锚定价值（常见串）
_GRAM_FREQ = 240
#: 补缺候选打分上限
_CAND_CAP = 48
#: pass-A 接受命中允许的最大前跳（流字符）——超了宁可 miss 让
# pass-B 邻位夹逼判，防止一次误锚把 cursor 拖到 doc 尾连锁塌方
_JUMP_CAP = 6000
_SKIP_PROBE_MIN = 300
#: 孤儿 snap 判据：BDC 裹字形数下限（页断沉底错锚）/ 针长下限 / 双向寻位页窗
_ORPHAN_CHARS = 4
_ORPHAN_MIN_ND = 8
_ORPHAN_PAGES = 5
#: mark 校验 SM 覆盖阈——occurrence 标内文本对 zh needle 低于则不可信
_MARK_COV = 0.35
#: 栏判定 x 中点契约（col = x>=0.45 ? 1 : 0）——与前端阅读序键同口径
_COL_SPLIT_X = 0.45

#: 与前端 ``copylatex.ts texStrip`` 同形——LaTeX 源 → 渲染态近似
_TEX_STRIP = (
    (re.compile(r"\[\[[A-Z]+_\d+\]\]"), " "),
    (re.compile(r"\$[^$]*\$|\\\([^)]*\\\)|\\\[[^\]]*\\\]"), " "),
    (re.compile(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?"), " "),
    (re.compile(r"[{}]"), " "),
    (re.compile(r"~"), " "),
    (re.compile(r"\\([%&#_])"), r"\1"),
    (re.compile(r"\\+"), " "),
)


def _tex_strip(s: str) -> str:
    for rx, rep in _TEX_STRIP:
        s = rx.sub(rep, s)
    return s


def _norm_chars(s: str) -> str:
    """归一到纯字母数字小写流。

    空格/标点全剥，两侧同形则字体丢空格、断行连字符、标点渲染差
    全部免疫（NFKD 顺带折叠连字/兼容形）。
    """
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return "".join(c for c in s if c.isalnum())


# ---------------------------------------------------------------- 字符流抽取


def _est_w(text: str, size: float) -> float:
    """Run 宽度粗估（仅栏切分用）——CJK 全宽、其余 ~0.55em。"""
    return sum(1.0 if ord(c) > _CJK_MIN else 0.55 for c in text) * size


def _cluster_lines(runs: list[tuple[float, float, float, str]]) -> list[Any]:
    """(y,x,size,text) → [y, parts[(x,text,w)], x0, x1, max_sz]，y 降序聚行。"""
    runs.sort(key=lambda r: (-r[0], r[1]))
    lines: list[Any] = []
    for y, x, sz, t in runs:
        w = _est_w(t, sz)
        if lines and abs(lines[-1][0] - y) <= _LINE_TOL:
            ln = lines[-1]
            ln[1].append((x, t, w))
            ln[2] = min(ln[2], x)
            ln[3] = max(ln[3], x + w)
            ln[4] = max(ln[4], sz)
        else:
            lines.append([y, [(x, t, w)], x, x + w, sz])
    for ln in lines:
        ln[1].sort()
    return lines


def _reading_order(  # noqa: C901
    lines: list[Any], width: float
) -> tuple[list[Any], tuple[float, float] | None]:
    """双栏检测 → (重排行, 中缝带 (gl,gr) | None)。

    页宽中段 28%~72% 扫最少穿线的竖带作中缝——穿线按 part 覆盖计：
    同基线左右栏被聚成一行时其 bbox 横贯整带，按行 bbox 计数会把所有
    候选 x 顶过阈值误杀真缝（merged-row 双栏页实证）。整带跨越行
    （标题/跨栏图题）对所有候选 x 等权计数，穿越计数一律排除（IEEE
    首页实证）。跨缝多 part 行先在缝带拆成两条独立行再分类——左右栏
    文字永不 join 进同一 run；part 自身跨缝（通栏标题 run）不拆，留
    给 span 判为区界。区内先左栏顶到底、再右栏。无可靠中缝 → 单栏原序。
    """
    if len(lines) < _COL_MIN_LINES:
        return lines, None
    lo, hi = width * 0.28, width * 0.72
    thr = max(2, int(len(lines) * 0.10))

    def cross(x: float) -> int:
        return sum(
            1
            for ln in lines
            if not (ln[2] < lo and ln[3] > hi)
            and any(px <= x <= px + pw for px, _t, pw in ln[1])
        )

    best_x, best_c = -1.0, 1 << 30
    x = lo
    while x < hi:
        c = cross(x)
        if c < best_c:
            best_x, best_c = x, c
        x += 3.0
    if best_x < 0 or best_c > thr:
        return lines, None
    gl = gr = best_x
    while gl - 3 > lo and cross(gl - 3) <= thr:
        gl -= 3.0
    while gr + 3 < hi and cross(gr + 3) <= thr:
        gr += 3.0
    if gr - gl < _GUTTER_MIN_W:
        return lines, None
    g = (gl + gr) / 2
    # 跨缝多 part 行（同基线左右栏合并行）拆成左/右两条独立行——
    # 拆分后各行自带 x0，发射侧自然落成两个带各自 bounds 的流段
    split: list[Any] = []
    for ln in lines:
        if (
            len(ln[1]) > 1
            and ln[2] < gl
            and ln[3] > gr
            and not any(px < gl and px + pw > gr for px, _t, pw in ln[1])
        ):
            left = [p for p in ln[1] if p[0] + p[2] / 2 < g]
            right = [p for p in ln[1] if p[0] + p[2] / 2 >= g]
            if left and right:
                split.append(
                    [
                        ln[0],
                        left,
                        min(p[0] for p in left),
                        max(p[0] + p[2] for p in left),
                        ln[4],
                    ]
                )
                split.append(
                    [
                        ln[0],
                        right,
                        min(p[0] for p in right),
                        max(p[0] + p[2] for p in right),
                        ln[4],
                    ]
                )
                continue
        split.append(ln)
    # 臆造中缝闸：单栏 ragged 页的右浮动行（落款/右对齐块）会把留白
    # 撑成假缝，少数浮动行被划进右栏沉底重排——拆分后双侧行数任一
    # 侧过少即非真双栏（对抗复核探针实证 y=365 行被排到页尾）
    if (
        sum(1 for ln in split if ln[3] <= gl) < _GUTTER_MIN_SIDE
        or sum(1 for ln in split if ln[2] >= gr) < _GUTTER_MIN_SIDE
    ):
        return lines, None
    lines = split
    spans = sorted(
        (ln for ln in lines if ln[2] < gl and ln[3] > gr), key=lambda ln: -ln[0]
    )
    col = [ln for ln in lines if not (ln[2] < gl and ln[3] > gr)]

    def cols(prev_y: float, next_y: float) -> list[Any]:
        reg = [ln for ln in col if next_y < ln[0] < prev_y]
        left = sorted(
            (ln for ln in reg if (ln[2] + ln[3]) / 2 < g), key=lambda ln: -ln[0]
        )
        right = sorted(
            (ln for ln in reg if (ln[2] + ln[3]) / 2 >= g), key=lambda ln: -ln[0]
        )
        return left + right

    out: list[Any] = []
    prev = float("inf")
    for s in spans:
        out.extend(cols(prev, s[0]))
        out.append(s)
        prev = s[0]
    out.extend(cols(prev, float("-inf")))
    return out, (gl, gr)


def _char_stream(  # noqa: C901, PLR0915 -- 页循环+双 visitor 平铺是抽取语义本体
    path: Path, *, collect_marks: bool = False
) -> tuple[str, list[tuple[int, int, float, float]], dict[int, list[dict[str, Any]]]]:
    """PDF → (归一字符流, 行界 [(char_off,page,frac,x)], marks)。

    ``visitor_text`` 的 tm 是局部矩阵——绝对位须复合 cm：
    ``x=tm4*cm0+tm5*cm2+cm4, y=tm4*cm1+tm5*cm3+cm5``（底向上）。
    行界 x=段左缘页宽分位（栏判定/阅读序键原料）；跨缝多 part 行已
    在 ``_reading_order`` 拆成独立流段，各带自己的 bounds 条目。

    ``collect_marks`` 时同遍经 ``visitor_operand_before`` 直读 TLXC
    标记（``BDC /MCID=50000+seq``）→ seq→occurrence 列表（每条记
    page/fraction/x/text/chars）——hyperref/TOC 重放会产生同 MCID
    双 BDC，只记首个必锚到目录页，全量收下由下游校验择优。
    BDC/EMC 配对用栈：嵌套/外来/无 MCID 的 BDC 压 None 占位，EMC
    弹栈，归属=栈顶向下最近非 None 项（单标量会被嵌套击穿实证）。
    锚位取标内首个 text run 的 (x,y)——vob 里的 tm 是上一个文本
    对象的陈旧矩阵（全部标记偏高 ~1 行、栏首偏 82% 页高实证）；
    fraction 口径与行界统一 1-(y+asc)/h（行顶非基线——floor 语义
    下基线锚会把行首点击漏给上一条 seq）。chars 供孤儿判定：页断处 BDC
    只裹 1~2 字形沉底、正文被推走。
    """
    from pypdf import PdfReader  # noqa: PLC0415 -- 与 align.py 同例懒载

    reader = PdfReader(str(path))
    chars: list[str] = []
    bounds: list[tuple[int, int, float, float]] = []
    marks: dict[int, list[dict[str, Any]]] = {}
    mstack: list[dict[str, Any] | None] = []
    char_off = 0
    for pi, page in enumerate(reader.pages):
        runs: list[tuple[float, float, float, str]] = []
        height = float(page.mediabox.height)
        width = float(page.mediabox.width)
        mstack.clear()

        def vt(
            text: str,
            cm: list[float],
            tm: list[float],
            font: object,  # noqa: ARG001 -- 签名由 pypdf 定死
            size: float,
            _runs: list[tuple[float, float, float, str]] = runs,
            _st: list[dict[str, Any] | None] = mstack,
            _h: float = height,
            _w: float = width,
        ) -> None:
            if not text.strip():
                return
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            _runs.append((y, x, float(size or 10.0), text))
            occ = next((e for e in reversed(_st) if e is not None), None)
            if occ is not None:
                t = text.strip()
                occ["text"].append(t)
                occ["chars"] += len(t)
                if occ["fraction"] is None:
                    occ["fraction"] = round(
                        1 - (y + _ASC * float(size or 10.0)) / _h, 5
                    )
                    occ["x"] = round(x / _w, 5)

        def vob(
            op: bytes,
            args: list[object],
            cm: list[float],  # noqa: ARG001 -- 签名由 pypdf 定死
            tm: list[float],  # noqa: ARG001 -- 同上；锚位改由 vt 首 run 记
            _pi: int = pi,
            _st: list[dict[str, Any] | None] = mstack,
            _marks: dict[int, list[dict[str, Any]]] = marks,
        ) -> None:
            if op == b"EMC":
                if _st:
                    _st.pop()
                return
            if op != b"BDC":
                return
            seq = -1
            if len(args) >= _BDC_ARGC:
                prop = args[1]
                d = prop.get_object() if hasattr(prop, "get_object") else prop
                mcid = d.get("/MCID") if hasattr(d, "get") else None
                try:
                    seq = int(mcid) - 50000  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    seq = -1
            if seq < 0:
                _st.append(None)  # 外来/无 MCID BDC 占位——配对 EMC 不吃里层 mark
                return
            occ: dict[str, Any] = {
                "page": _pi + 1,
                "fraction": None,
                "x": None,
                "text": [],
                "chars": 0,
            }
            _marks.setdefault(seq, []).append(occ)
            _st.append(occ)

        try:
            page.extract_text(
                visitor_text=vt,
                visitor_operand_before=vob if collect_marks else None,
            )
        except Exception as exc:  # noqa: BLE001 -- 单页坏不拖全文档
            log.debug("seqpos: %s p%d extract_text failed: %s", path.name, pi + 1, exc)
            continue
        ordered, _gut = _reading_order(_cluster_lines(runs), width)
        for ln in ordered:
            nc = _norm_chars("".join(p[1] for p in ln[1]))
            if not nc:
                continue
            bounds.append(
                (
                    char_off,
                    pi + 1,
                    round(1 - (ln[0] + _ASC * ln[4]) / height, 5),
                    round(ln[2] / width, 5),
                )
            )
            chars.append(nc)
            char_off += len(nc)
    for occs in marks.values():
        for occ in occs:
            occ["text"] = "".join(occ["text"])
    return "".join(chars), bounds, marks


# ---------------------------------------------------------------- 文档序

_INPUT_RX = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")


def _read_tex(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _dfs_flat(texs: dict[str, Path], root: str) -> list[str]:
    r"""``\documentclass`` 根起 DFS 展平 ``\input/\include/\subfile`` → 文件阅读序。"""
    seen: set[str] = set()
    flat: list[str] = []

    def resolve(tgt: str, base: str) -> str | None:
        # \input{sec} 无后缀；目标对根相对，少数对含入文件目录相对
        tgt = tgt.strip().replace("\\", "/")
        base_dir = posixpath.dirname(base)
        for t in (tgt, f"{tgt}.tex"):
            for c_ in (t, posixpath.normpath(f"{base_dir}/{t}")):
                if c_ in texs:
                    return c_
        return None

    def dfs(rel: str) -> None:
        if rel in seen:
            return
        seen.add(rel)
        flat.append(rel)
        for m in _INPUT_RX.finditer(_read_tex(texs[rel])):
            r = resolve(m.group(1), rel)
            if r is not None:
                dfs(r)

    dfs(root)
    return flat


def _doc_order(task_dir: Path, chunks: list[dict[str, Any]]) -> dict[int, int]:
    r"""Chunk seq → 文档序 rank。

    dual.json 的 chunk 序是 ``src_file`` 字母序——abstract/conclusions/
    experiments/introduction 的字典序 ≠ PDF 阅读序，pass-A 光标与
    pass-B ``s < seq`` 夹逼全建立在线性假设上，乱序即级联塌方（实测
    2/85 覆盖）。这里从 ``base/``（缺则 ``zh/``）源码树重建真序：
    ``\documentclass`` 根起 DFS 展平 ``\input/\include``，文件序 ×
    文件内 seq 序合成全局 rank。无根 → 文件按 min-seq 兜底排。
    """
    by_file: dict[str, list[int]] = {}
    for c in chunks:
        seq, sf = c.get("seq"), c.get("src_file")
        if isinstance(seq, int) and isinstance(sf, str):
            by_file.setdefault(sf.replace("\\", "/"), []).append(seq)
    if not by_file:
        return {}
    for seqs in by_file.values():
        seqs.sort()

    flat: list[str] = []
    for root_dir in (task_dir / "base", task_dir / "zh"):
        if not root_dir.is_dir():
            continue
        texs = {p.relative_to(root_dir).as_posix(): p for p in root_dir.rglob("*.tex")}
        doc_root = next(
            (rel for rel, p in texs.items() if "\\documentclass" in _read_tex(p)),
            None,
        )
        if doc_root is not None:
            flat = _dfs_flat(texs, doc_root)
            break

    # 未入 DFS 链的文件（游离 \input 链外/无根兜底）按 min-seq 追加尾部
    rest = sorted(
        (sf for sf in by_file if sf not in flat), key=lambda sf: by_file[sf][0]
    )
    rank_of = {rel: i for i, rel in enumerate(flat)}
    rank_of.update({sf: len(flat) + i for i, sf in enumerate(rest)})
    big = 1 << 20
    order: dict[int, int] = {}
    for sf, seqs in by_file.items():
        r = rank_of.get(sf, len(flat) + len(rest))
        for j, s in enumerate(seqs):
            order[s] = r * big + j
    return order


# ---------------------------------------------------------------- 匹配


def _gram_index(stream: str) -> dict[str, list[int]]:
    """构建归一字符流的 6-gram 位置索引（_match_bounded 锚定用）。"""
    gidx: dict[str, list[int]] = {}
    for i in range(len(stream) - _GRAM + 1):
        gidx.setdefault(stream[i : i + _GRAM], []).append(i)
    return gidx


def _sm_cov(stream: str, lo: int, hi: int, needle: str) -> tuple[float, int, int, int]:
    """窗口内 matching_blocks → (覆盖率, 针起点投影位, 匹配尾位, 最长单块)。

    报告位是针起点投影 ``lo+blocks[0].a-blocks[0].b``（clamp 到 lo）——
    记首块位在针有前导残段时系统性偏后，跨页假锚实证。
    """
    if not needle:
        return 0.0, lo, lo, 0
    sm = SequenceMatcher(None, stream[lo:hi], needle, autojunk=False)
    blocks = sm.get_matching_blocks()
    cov = sum(b.size for b in blocks) / len(needle)
    longest = max((b.size for b in blocks), default=0)
    first = blocks[0]
    pos = max(lo, lo + first.a - first.b) if first.size else lo
    real = [b for b in blocks if b.size]
    end = lo + real[-1].a + real[-1].size if real else lo
    return cov, pos, end, longest


def _text_cov(marked: str, needle: str) -> float:
    """标内文本归一化后对 needle 的 SM 覆盖率（mark 校验口径）。"""
    m = _norm_chars(marked)
    if not m or not needle:
        return 0.0
    return _sm_cov(m, 0, len(m), needle)[0]


def _match_bounded(  # noqa: C901, PLR0912 -- gram 锚定+兜底+打分是同一段语义阶梯
    needle: str,
    stream: str,
    gidx: dict[str, list[int]],
    lo: int,
    hi: int,
) -> tuple[int, float, int]:
    """[lo,hi] 界内 gram 锚定 + SM 打分 → (pos, cov, end)；无候选或低分 → (-1,·)。"""
    ln = len(needle)
    g = min(_GRAM, ln)
    cand: set[int] = set()
    if g >= _GRAM:
        # 缺席 gram（cnt=0）先滤再取稀——否则长 needle 的 absent gram
        # 占满 top-8 名额全被跳、候选空集（seq20/68 实证：785 字 needle
        # 全流扫描零候选）
        grams = sorted(
            (len(gidx[needle[i : i + g]]), i)
            for i in range(0, ln - g + 1, 4)
            if 0 < len(gidx.get(needle[i : i + g], [])) <= _GRAM_FREQ
        )
        for _cnt, i in grams[:8]:
            for p in gidx[needle[i : i + g]]:
                s0 = p - i
                if lo - 40 <= s0 <= hi + 40:
                    cand.add(s0)
    if not cand:
        # 短 needle（<6）无 gram 可锚；或全 gram 缺席/过频——整针 find 兜底
        start = max(0, lo)
        while len(cand) < _CAND_CAP:
            j = stream.find(needle, start, hi + ln)
            if j < 0:
                break
            cand.add(j)
            start = j + 1
    best = (-1, 0.0, 0)
    # 双闸：最长单匹配块 + sum-cov——碎块凑数（多跳拼接高 cov）曾产出
    # 32 例跨页假锚；块阈随针长收但封顶针长（短针整串命中仍算数）
    need_blk = min(ln, max(6, 0.3 * ln))
    mcov = _min_cov(ln)
    # 候选超帽时按离窗心距离取——最小 offset 截断会把窗内真位挤出去
    mid = (lo + hi) / 2
    for s0 in sorted(cand, key=lambda s: abs(s - mid))[:_CAND_CAP]:
        # cov 满分后无人能翻（strict >）——直接断，省尾部 SM 评估
        if best[1] >= 1.0:
            break
        # 整针落界内的精确命中先 memcmp 出分——免 3·ln 窗口 difflib
        # （profile：SM 占匹配侧 ~95% 耗时）。界沿外候选不可短路：
        # s0∈[lo-40,lo) 时旧路 SM 窗从 lo 截、返位≠s0，直返会破窗约
        if lo <= s0 and s0 + ln <= hi and stream[s0 : s0 + ln] == needle:
            cov, p, e, blk = 1.0, s0, s0 + ln, ln
        else:
            lo2 = max(0, lo, s0 - 8)
            hi2 = min(hi, s0 + ln * 3 + 40)
            if hi2 <= lo2:
                continue
            cov, p, e, blk = _sm_cov(stream, lo2, hi2, needle)
        if blk >= need_blk and cov >= mcov and cov > best[1]:
            best = (p, cov, e)
    return best


def _skips_pending(  # noqa: PLR0913, PLR0917 -- 探针参数即上下文六件，拆包反损可读
    stream: str,
    needles: list[tuple[int, str]],
    ni: int,
    gidx: dict[str, list[int]],
    prev_end: int,
    p: int,
) -> bool:
    """命中 p 相对光标是大前跳、且后续针在跳段里有真命中 → 浮动/重排块。

    pass-A 光标假设「针序≈流序」——浮动体/栏重排会让一针的真位越过
    后续数针：无探针的 prev_end 前推把中间针饿死（seq39 跨跳饿死
    seq43-45 实证）。判据是跳段内跑真 _match_bounded 过阈——单 gram
    出现太弱（英文跳段里常见 gram 必在场，探针常开冻结光标实证）。
    探后 3 针容错紧邻的空针/漏网针；跳段无待匹配文（真鸿沟：图表/
    公式区）才放行推进。
    """
    if p - prev_end <= _SKIP_PROBE_MIN:
        return False
    for _s, nxt in needles[ni + 1 : ni + 4]:
        np_, ncv, _ = _match_bounded(nxt, stream, gidx, prev_end, p)
        if np_ >= 0 and ncv >= _min_cov(len(nxt)):
            return True
    return False


def _offset_at(
    bounds: list[tuple[int, int, float, float]],
    page: int,
    frac: float,
    x: float | None = None,
) -> int:
    """(page,frac,x) → 同栏最近行界的字符流 offset（marks↔流界换算）。

    双栏页 bounds 的 (page,frac) 非单调（先左栏到底再右栏），bisect
    无定义——候选=同页同栏（x 两侧 col 一致）里 |Δfrac| 最小者；x 缺席
    退化全页最近；页缺退化全文档最近。
    """

    def col(v: float | None) -> int:
        return 1 if v is not None and v >= _COL_SPLIT_X else 0

    cands = [b for b in bounds if b[1] == page]
    if x is not None:
        same = [b for b in cands if col(b[3]) == col(x)]
        if same:
            cands = same
    if not cands:
        cands = bounds
    if not cands:
        return 0
    return min(cands, key=lambda b: (abs(b[1] - page), abs(b[2] - frac)))[0]


def _match_side(  # noqa: C901, PLR0912, PLR0913, PLR0915, PLR0917 -- 两遍骨架+补缺是单算法阶梯，拆开反失上下文
    needles: list[tuple[int, str]],
    stream: str,
    prior: dict[int, int] | None = None,
    lo_known: dict[int, int] | None = None,
    order: dict[int, int] | None = None,
    gidx: dict[str, list[int]] | None = None,
) -> dict[int, int]:
    """Needle 序列 → seq→流 offset（命中起点）。

    两遍：A 顺序骨架——marked seq（``prior`` 有估计位）候选限先验带
    est±20%，未标记走光标窗口；接受条件 cov≥阈 + 局部不回退 +
    （无先验时）跳距上限。B 漏跑段在相邻命中夹逼界∩先验带内补缺。
    ``lo_known`` 预置已知锚（zh marks）时跳过 A 全走夹逼。
    ``order``（seq→文档序 rank，``_doc_order`` 产出）给定时的前后
    比较全走 rank——chunk 序是 src_file 字母序非阅读序，直接比 seq
    会把夹逼界算反（乱序塌方实证 2/85）。缺省落 seq 序旧行为。

    先验带的存在理由：局部窗口无法识别「贴脸的误锚」——seq174 在
    cursor 后 200 字符处以 cov 0.55+ 命中相似文本，把补缺上界钉死在
    57k、78k+ 的补充材料 TOC 全灭（实证）。zh marks 是序真值，按
    流长比例映射到本侧后 est±20% 足以排掉 40k 级错位。
    """
    if order:
        big = 1 << 30

        def key(s: int) -> int:
            return order.get(s, big + s)
    else:

        def key(s: int) -> int:
            return s

    if gidx is None:
        gidx = _gram_index(stream)
    band = max(6000, len(stream) // 5)

    hit: dict[int, tuple[int, int]] = {}  # seq → (pos, end)
    miss: list[tuple[int, str]] = []
    max_key = max(order.values()) if order else 0
    if lo_known:
        # 有已知锚才够格全走夹逼；空锚（marks=0 的任务）走 pass-A
        # 光标骨架——空表 is-not-None 判定曾把全量针丢进无界夹逼（9/85）
        miss = list(needles)
    else:
        prev_end = 0
        for ni, (seq, nd) in enumerate(needles):
            ln = len(nd)
            est = prior.get(seq) if prior else None
            if est is not None:
                # marked：先验带即位置约束，不加顺序检查——浮动体合法出序
                # （seq1 图题在 p2 而 seq2-4 正文在 p1，回退检查会杀真锚）
                lo_b, hi_b = est - band, est + band
                p, cov, _e = _match_bounded(
                    nd, stream, gidx, max(0, lo_b), min(len(stream), hi_b)
                )
                if p >= 0 and cov >= _min_cov(ln):
                    hit[seq] = (p, min(_e, p + 3 * ln))
                    # 命中位才推光标；跳过 pending 针的远跳不跟（浮动体）
                    if p >= prev_end and not _skips_pending(
                        stream, needles, ni, gidx, prev_end, p
                    ):
                        prev_end = p + ln
                else:
                    miss.append((seq, nd))
            else:
                p, cov, _e = _match_bounded(
                    nd,
                    stream,
                    gidx,
                    max(0, prev_end - 300),
                    min(len(stream), prev_end + ln * 3 + 4000),
                )
                if (
                    p >= 0
                    and cov >= _min_cov(ln)
                    and p >= prev_end - 300
                    and p - prev_end <= max(_JUMP_CAP, ln * 4)
                ):
                    hit[seq] = (p, min(_e, p + 3 * ln))
                    # 前进量用 needle 长而非 match 尾块——SM 尾块常被噪
                    # 声块甩远（seq3 e=3003 盖过 seq4 起点 2189 实证）；
                    # 且只在命中位 >= prev_end 时推进——出序命中不拖光标；
                    # 前跳越过 pending 针（浮动/重排）不跟，防饿死中间针
                    if p >= prev_end and not _skips_pending(
                        stream, needles, ni, gidx, prev_end, p
                    ):
                        prev_end = p + ln
                else:
                    miss.append((seq, nd))

    for seq, nd in sorted(miss, key=lambda sn: key(sn[0])):
        if prior is not None and seq in prior:
            # marked 补缺只吃先验带——邻位界对浮动体是错约束
            lo, hi = prior[seq] - band, prior[seq] + band
        else:
            k = key(seq)
            prevs = [hit[s] for s in hit if key(s) < k]
            nexts = [hit[s] for s in hit if key(s) > k]
            lo = max((e for _, e in prevs), default=0)
            hi = min((p for p, _ in nexts), default=len(stream))
        if lo_known:
            k = key(seq)
            lo = max(lo, max((o for s, o in lo_known.items() if key(s) < k), default=0))
            hi = min(
                hi,
                min(
                    (o for s, o in lo_known.items() if key(s) > k),
                    default=len(stream),
                ),
            )
        if hi <= lo:
            # 邻位夹逼窗倒置——浮动体让锚位在流中不单调（seq161：前邻锚
            # 53742 > 后邻锚 53073，真位 54269 在窗外）。退化为以两界
            # 中点为心的局部窗，长度吃 needle 余量。
            mid = (lo + hi) // 2
            pad = max(4000, len(nd) * 3)
            lo, hi = mid - pad, mid + pad
        p, cov, e = _match_bounded(nd, stream, gidx, lo, max(hi, lo + 200))
        if not (p >= 0 and cov >= _min_cov(len(nd))) and order:
            # 夹逼窗全斥——邻锚是假锚或整段浮动体重排（实证：单一假锚
            # 把整文件区钉死在窗外，114 针全真位 cov≈1 全灭）。退到
            # rank 比例估计带 est±band 再试一次
            est = int(key(seq) / max(max_key, 1) * len(stream))
            lo2, hi2 = max(0, est - band), min(len(stream), est + band)
            p, cov, e = _match_bounded(nd, stream, gidx, lo2, max(hi2, lo2 + 200))
        if p >= 0 and cov >= _min_cov(len(nd)):
            # e=SM 尾块端点会被噪声甩远（交错区命中实证 e 超 p+3ln），
            # 它要当后续缺口的夹逼下界——截到 p+3ln 防界膨胀塌窗
            hit[seq] = (p, min(e, p + 3 * len(nd)))
    return {seq: p for seq, (p, _) in hit.items()}


@contextlib.contextmanager
def _font_cache_ctx() -> Iterator[None]:
    """缓存 pypdf Font——extract 每页重建页内全部 Font。

    CJK ToUnicode CMap 10 万级逐项重解析是 ``_char_stream`` 的绝对大头
    （profile 实证 19s/29s）。按字体间接引用 (pdf,idnum,generation)
    跨页/跨文档缓存，extract 完即还原。
    """
    from pypdf._font import Font  # noqa: PLC0415 -- 与 PdfReader 同例懒载

    orig = Font.__dict__["from_font_resource"]  # classmethod 本体——还原用
    call = orig.__func__  # 裸函数——__dict__ 取出的 classmethod 不可直接调
    fcache: dict[tuple[int, int, int], Any] = {}

    def _ffr(cls: Any, d: Any) -> Any:  # noqa: ANN401 -- pypdf 内部型不在仓内契约
        ref = getattr(d, "indirect_reference", None)
        if ref is None:
            return call(cls, d)
        key = (id(ref.pdf), ref.idnum, ref.generation)
        if key not in fcache:
            fcache[key] = call(cls, d)
        return fcache[key]

    Font.from_font_resource = classmethod(_ffr)
    try:
        yield
    finally:
        Font.from_font_resource = orig


# ---------------------------------------------------------------- 装配


def _needles(chunks: list[dict[str, Any]], side: str) -> list[tuple[int, str]]:
    # zh 侧单字信息量高——2 字 CJK needle（「推理」式 \textit 短题）在
    # 邻位夹逼窗内仍有辨识度；en 侧 4 以下几乎必误锚
    min_len = 2 if side == "zh" else 4
    out: list[tuple[int, str]] = []
    for c in chunks:
        seq = c.get("seq")
        if not isinstance(seq, int):
            continue
        txt = c.get(side) or ""
        if not txt:
            continue
        nd = _norm_chars(_tex_strip(txt))
        if len(nd) >= min_len:
            out.append((seq, nd))
    return out


def _pos_at(
    bounds: list[tuple[int, int, float, float]],
    off: int,
) -> dict[str, Any] | None:
    """流 offset → 所在行界 Pos（含栏位 x）。offset 落行内——上取该行。"""
    i = bisect.bisect_right([b[0] for b in bounds], off) - 1
    if i < 0:
        return None
    b = bounds[i]
    return {"page": b[1], "fraction": b[2], "x": b[3]}


def _interp_t(
    pairs: list[dict[str, Any]] | None, o_pos: dict[str, Any]
) -> dict[str, Any] | None:
    """O Pos → t Pos 分段线性插值（``alignment.pairs`` 地标杆）。

    zh.pdf textLayer 无 ToUnicode 时 CJK 全错码点、文本匹配是死路——
    pairs 的 (original,translated) 点列按 page+frac 线性化后分段映射。
    低于首地标取首值；超出末地标 → None（钳位会把整尾 seq 塌缩到
    同一锚——单侧 emit 兜底比假锚强）。
    """
    pts: list[tuple[float, float]] = []
    for p in pairs or []:
        o, t = p.get("original"), p.get("translated")
        if not isinstance(o, dict) or not isinstance(t, dict):
            continue
        try:
            pts.append(
                (
                    float(o["page"]) + float(o["fraction"]),
                    float(t["page"]) + float(t["fraction"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    if not pts:
        return None
    pts.sort()
    x = float(o_pos["page"]) + float(o_pos["fraction"])
    if x > pts[-1][0]:
        return None
    if x <= pts[0][0]:
        y = pts[0][1]
    elif x >= pts[-1][0]:
        y = pts[-1][1]
    else:
        i = bisect.bisect_right(pts, (x, 1e9)) - 1
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        y = y0 + (y1 - y0) * (x - x0) / max(1e-9, x1 - x0)
    page = int(y)
    frac = y - page
    if frac < 0:
        page, frac = page - 1, frac + 1
    t_pos: dict[str, Any] = {
        "page": max(1, page),
        "fraction": round(min(0.999, max(0.0, frac)), 5),
    }
    # zh_dead 无字形可锚——沿用 o_pos 的 x 近似栏位（同模板栏结构）
    if o_pos.get("x") is not None:
        t_pos["x"] = o_pos["x"]
    return t_pos


def compute_seqpos(  # noqa: C901, PLR0912, PLR0915 -- 装配阶梯单流：marks 校验→snap→双侧匹配→降级
    en_pdf: Path,
    zh_pdf: Path,
    chunks: list[dict[str, Any]],
    task_dir: Path | None = None,
    pairs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """两侧位置合成 → ``{"seq": {"o"?: Pos, "t"?: Pos}}``（seq 字符串键）。

    Pos = ``{page, fraction, x}``——x 是锚行左缘/标内首字形的页宽分位
    （栏判定 + 阅读序键 ``(page,col,frac)`` 的消费原料）。单侧命中也入
    库——双要条件在无标记任务上丢 36~43% seq（实证）。
    """
    with _font_cache_ctx():
        en_stream, en_bounds, _en_marks = _char_stream(en_pdf)
        zh_stream, zh_bounds, zh_marks = _char_stream(zh_pdf, collect_marks=True)

    order = _doc_order(task_dir, chunks) if task_dir is not None else {}
    en_needles = _needles(chunks, "en")
    zh_needles = _needles(chunks, "zh")
    if order:
        big = 1 << 30
        en_needles.sort(key=lambda sn: order.get(sn[0], big + sn[0]))
        zh_needles.sort(key=lambda sn: order.get(sn[0], big + sn[0]))

    zh_nd = dict(zh_needles)

    # zh 乱码降级判定提前（snap/匹配共用短路）：textLayer 无 ToUnicode
    # 时 CJK 全错码点，文本匹配是死路。密度阈而非 any()——错码点面也
    # 会零星撞上 CJK 区（85234 字符混 156 个 CJK 照样全废实证）
    zh_cjk = sum(1 for ch in zh_stream if "一" <= ch <= "鿿")
    zh_dead = zh_cjk < max(100, len(zh_stream) // 20) and any(
        "一" <= ch <= "鿿" for c in chunks for ch in (c.get("zh") or "")
    )

    # mark 校验：occurrence 标内文本对 zh needle SM 覆盖——同 MCID 重放
    # （hyperref/TOC）首 occurrence 常落目录页；可信集（cov≥阈）取末个
    # （TOC 在前真标在后）；全低分/无锚 → 不可信，留待 snap/needle 路
    trusted: dict[int, dict[str, Any]] = {}
    for seq, occs in zh_marks.items():
        anchored = [o for o in occs if o["fraction"] is not None]
        if not anchored:
            continue
        nd = zh_nd.get(seq) or ""
        good = (
            [o for o in anchored if _text_cov(o["text"], nd) >= _MARK_COV]
            if nd and not zh_dead
            else anchored
        )
        if good:
            trusted[seq] = good[-1]

    # 孤儿 snap：标记不可信/裹字形过少（页断沉底 + fr≤0.85 中页错锚）
    # → 语义匹配在标称页 ±5 页双向寻真位，命中行界为新锚；救不回的
    # 留 needle 路（zh_unmarked 在 snap 后算——救回的不重走文本匹配）
    suspects = [
        seq
        for seq in zh_marks
        if seq not in trusted or trusted[seq]["chars"] < _ORPHAN_CHARS
    ]
    zh_gidx = (
        _gram_index(zh_stream)
        if not zh_dead and (suspects or len(zh_needles) > len(trusted))
        else None
    )
    if zh_gidx is not None:
        for seq in suspects:
            nd = zh_nd.get(seq) or ""
            if len(nd) < _ORPHAN_MIN_ND:
                continue
            occ = trusted.get(seq) or zh_marks[seq][-1]
            lo = next(
                (b[0] for b in zh_bounds if b[1] >= occ["page"] - _ORPHAN_PAGES), 0
            )
            hi = next(
                (b[0] for b in zh_bounds if b[1] > occ["page"] + _ORPHAN_PAGES),
                len(zh_stream),
            )
            p, _cov, _e = _match_bounded(nd, zh_stream, zh_gidx, lo, hi)
            if p < 0:
                continue
            pos = _pos_at(zh_bounds, p)
            if pos is not None:
                trusted[seq] = {
                    "page": pos["page"],
                    "fraction": pos["fraction"],
                    "x": pos["x"],
                    "chars": occ["chars"],
                }

    # zh：trusted mark 免匹配——换算成流 offset 当补缺界桩
    chunks_by_seq = {c.get("seq"): c for c in chunks if isinstance(c.get("seq"), int)}
    zh_off_known = {
        seq: _offset_at(zh_bounds, occ["page"], occ["fraction"], occ["x"])
        for seq, occ in trusted.items()
    }
    zh_unmarked = [(seq, nd) for seq, nd in zh_needles if seq not in trusted]
    zh_off = (
        _match_side(
            zh_unmarked,
            zh_stream,
            lo_known=zh_off_known,
            order=order,
            gidx=zh_gidx,
        )
        if zh_unmarked and not zh_dead
        else {}
    )

    # en 侧先验：zh 锚 offset（trusted marks + zh 文本命中）按流长比
    # 映射成 est±band 窗——局部相似文本（TOC↔章节题/参考文献惯用句）
    # 误锚实证；双侧锚越多约束越紧
    scale = len(en_stream) / max(1, len(zh_stream))
    en_prior = {seq: int(off * scale) for seq, off in zh_off_known.items()}
    for seq, off in zh_off.items():
        en_prior[seq] = int(off * scale)
    en_off = _match_side(en_needles, en_stream, en_prior, order=order)

    out: dict[str, Any] = {}
    for seq in sorted(set(en_off) | set(trusted) | set(zh_off)):
        c = chunks_by_seq.get(seq) or {}
        if not c.get("en") and not c.get("zh"):
            continue
        o_pos = _pos_at(en_bounds, en_off[seq]) if seq in en_off else None
        if seq in trusted:
            m = trusted[seq]
            t_pos = {"page": m["page"], "fraction": m["fraction"]}
            if m.get("x") is not None:
                t_pos["x"] = m["x"]
        elif seq in zh_off:
            t_pos = _pos_at(zh_bounds, zh_off[seq])
        elif zh_dead and o_pos:
            t_pos = _interp_t(pairs, o_pos)
        else:
            t_pos = None
        entry: dict[str, Any] = {}
        if o_pos is not None:
            entry["o"] = o_pos
        if t_pos is not None:
            entry["t"] = t_pos
        if entry:
            out[str(seq)] = entry
    return out


def seqpos_for_task(task_dir: Path, dual: dict[str, Any]) -> dict[str, Any] | None:
    """懒算+缓存 ``task_dir/seqpos.json``。

    输入件（dual/en.pdf/zh.pdf）任一更新即重算；不可算（缺 PDF/无
    chunks）→ None，调用方降级。
    """
    chunks = dual.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        return None
    en_pdf, zh_pdf = task_dir / "en.pdf", task_dir / "zh.pdf"
    if not en_pdf.is_file() or not zh_pdf.is_file():
        return None
    cache = task_dir / _CACHE
    src_mtime = max(
        en_pdf.stat().st_mtime,
        zh_pdf.stat().st_mtime,
        (task_dir / "dual.json").stat().st_mtime
        if (task_dir / "dual.json").is_file()
        else 0,
    )
    try:
        if cache.is_file() and cache.stat().st_mtime >= src_mtime:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("v") == _VERSION:
                sp = cached.get("seqpos")
                return sp if isinstance(sp, dict) else None
    except (OSError, json.JSONDecodeError):
        pass  # 缓存坏→重算
    al = dual.get("alignment")
    pairs = al.get("pairs") if isinstance(al, dict) else None
    try:
        seqpos = compute_seqpos(en_pdf, zh_pdf, chunks, task_dir=task_dir, pairs=pairs)
    except Exception as exc:  # noqa: BLE001 -- 对位失败降级不炸 reader
        log.warning("seqpos: compute failed for %s: %s", task_dir.name, exc)
        return None
    try:
        atomic_json(cache, {"v": _VERSION, "seqpos": seqpos})
    except OSError as exc:
        log.debug("seqpos: cache write failed: %s", exc)
    return seqpos
