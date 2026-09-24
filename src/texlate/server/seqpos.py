"""seq 级 PDF 位置对位——``GET /reader`` 响应注入 ``seqpos`` 字段。

zh.pdf 有 TLXC 标记（``BDC /MCID=50000+seq``，``latex/reconstruct.py`` 注锚）→
pypdf ``visitor_operand_before`` 直读精确点锚；en.pdf（base 编译链无标记）
与未标记 zh seq 走文本匹配：chunk 文本 texstrip+alnum 归一成 needle，PDF
``extract_text`` 聚行成归一化字符流（行界记 page/fraction）。匹配两遍——
光标窗口快路建单调骨架，漏跑段在相邻命中夹逼的流区间内 6-gram 锚定补缺
（浮动体出序/字体丢空格粘连都能救回）。结果缓存 ``task_dir/seqpos.json``，
输入件 mtime 更新即重算；dual.json 本体不动（``?version=sha256`` 不可变）。
"""

from __future__ import annotations

import bisect
import json
import logging
import posixpath
import re
import unicodedata
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

from texlate.xlat.state import atomic_json

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger(__name__)

__all__ = ["seqpos_for_task"]

_CACHE = "seqpos.json"
_VERSION = 5

#: 行聚类 y 容差（pt，底向上坐标同线合并）
_LINE_TOL = 2.5
#: CJK 全宽下界（_est_w 栏切宽度粗估）
_CJK_MIN = 0x2E7F
#: _min_cov 针长分档
_COV_SHORT = 30
_COV_MID = 80
#: 双栏检测下限行数 / 中缝最小宽度（pt）
_COL_MIN_LINES = 8
_GUTTER_MIN_W = 10
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
#: 孤儿标记判据：BDC 裹字形数下限 / 页底分位阈 / 针长下限 / 后寻页数
_ORPHAN_CHARS = 4
_ORPHAN_FRAC = 0.85
_ORPHAN_MIN_ND = 8
_ORPHAN_PAGES = 3

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
    """(y,x,size,text) → [y, parts[(x,text)], x0, x1]，y 降序聚行。"""
    runs.sort(key=lambda r: (-r[0], r[1]))
    lines: list[Any] = []
    for y, x, sz, t in runs:
        w = _est_w(t, sz)
        if lines and abs(lines[-1][0] - y) <= _LINE_TOL:
            ln = lines[-1]
            ln[1].append((x, t))
            ln[2] = min(ln[2], x)
            ln[3] = max(ln[3], x + w)
        else:
            lines.append([y, [(x, t)], x, x + w])
    for ln in lines:
        ln[1].sort()
    return lines


def _reading_order(lines: list[Any], width: float) -> list[Any]:  # noqa: C901
    """双栏检测。

    页宽中段 28%~72% 扫最少穿线的竖带作中缝，跨缝行（通栏标题/页眉）
    当区界——区内先左栏顶到底、再右栏。无可靠中缝 → 单栏原序。
    整带跨越行（标题/跨栏图题）对所有候选 x 等权计数——只抬高基线
    且会把计数顶过阈值误杀真缝（IEEE 首页实证），穿越计数一律排除。
    """
    if len(lines) < _COL_MIN_LINES:
        return lines
    lo, hi = width * 0.28, width * 0.72
    thr = max(2, int(len(lines) * 0.10))

    def cross(x: float) -> int:
        return sum(
            1 for ln in lines if ln[2] < x < ln[3] and not (ln[2] < lo and ln[3] > hi)
        )

    best_x, best_c = -1.0, 1 << 30
    x = lo
    while x < hi:
        c = cross(x)
        if c < best_c:
            best_x, best_c = x, c
        x += 3.0
    if best_x < 0 or best_c > thr:
        return lines
    gl = gr = best_x
    while gl - 3 > lo and cross(gl - 3) <= thr:
        gl -= 3.0
    while gr + 3 < hi and cross(gr + 3) <= thr:
        gr += 3.0
    if gr - gl < _GUTTER_MIN_W:
        return lines
    spans = sorted(
        (ln for ln in lines if ln[2] < gl and ln[3] > gr), key=lambda ln: -ln[0]
    )
    col = [ln for ln in lines if not (ln[2] < gl and ln[3] > gr)]
    g = (gl + gr) / 2

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
    return out


def _char_stream(  # noqa: C901 -- 页循环+双 visitor 平铺是抽取语义本体
    path: Path, *, collect_marks: bool = False
) -> tuple[
    str, list[tuple[int, int, float]], dict[int, tuple[int, float]], dict[int, int]
]:
    """PDF → (归一字符流, 行界 [(char_offset, page, frac_top_down)], marks, mark字形数)。

    ``visitor_text`` 的 tm 是局部矩阵——绝对位须复合 cm：
    ``x=tm4*cm0+tm5*cm2+cm4, y=tm4*cm1+tm5*cm3+cm5``（底向上）。

    ``collect_marks`` 时同遍经 ``visitor_operand_before`` 直读 TLXC 标记
    （``BDC /MCID=50000+seq``）→ seq→(page,frac)——单遍双 visitor 省一趟
    extract_text（CMap 解析是主成本，39pp 实测省 ~1/3 耗时）。mark字形数
    供孤儿判定：页断处 BDC 只裹 1~2 字形沉底、正文被推走（+1~3 页错位实证）。
    """
    from pypdf import PdfReader  # noqa: PLC0415 -- 与 align.py 同例懒载

    reader = PdfReader(str(path))
    chars: list[str] = []
    bounds: list[tuple[int, int, float]] = []
    marks: dict[int, tuple[int, float]] = {}
    mark_chars: dict[int, int] = {}
    cur_mark: list[int | None] = [None]
    char_off = 0
    for pi, page in enumerate(reader.pages):
        runs: list[tuple[float, float, float, str]] = []
        height = float(page.mediabox.height)
        width = float(page.mediabox.width)
        cur_mark[0] = None

        def vt(
            text: str,
            cm: list[float],
            tm: list[float],
            font: object,  # noqa: ARG001 -- 签名由 pypdf 定死
            size: float,
            _runs: list[tuple[float, float, str, str]] = runs,
            _cur: list[int | None] = cur_mark,
        ) -> None:
            if text.strip():
                if _cur[0] is not None:
                    mark_chars[_cur[0]] = mark_chars.get(_cur[0], 0) + len(text.strip())
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                _runs.append((y, x, float(size or 10.0), text))

        def vob(
            op: bytes,
            args: list[object],
            cm: list[float],
            tm: list[float],
            _pi: int = pi,
            _height: float = height,
            _cur: list[int | None] = cur_mark,
        ) -> None:
            if op == b"EMC":
                _cur[0] = None
                return
            if op != b"BDC" or len(args) < _BDC_ARGC:
                return
            prop = args[1]
            d = prop.get_object() if hasattr(prop, "get_object") else prop
            mcid = d.get("/MCID") if hasattr(d, "get") else None
            try:
                seq = int(mcid) - 50000  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return
            if seq < 0:
                return
            _cur[0] = seq
            mark_chars.setdefault(seq, 0)
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            marks.setdefault(seq, (_pi + 1, round(1 - (y + 6) / _height, 5)))

        try:
            page.extract_text(
                visitor_text=vt,
                visitor_operand_before=vob if collect_marks else None,
            )
        except Exception as exc:  # noqa: BLE001 -- 单页坏不拖全文档
            log.debug("seqpos: %s p%d extract_text failed: %s", path.name, pi + 1, exc)
            continue
        for ln in _reading_order(_cluster_lines(runs), width):
            nc = _norm_chars("".join(t for _, t in ln[1]))
            if not nc:
                continue
            bounds.append((char_off, pi + 1, round(1 - ln[0] / height, 5)))
            chars.append(nc)
            char_off += len(nc)
    return "".join(chars), bounds, marks, mark_chars


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


def _sm_cov(stream: str, lo: int, hi: int, needle: str) -> tuple[float, int, int]:
    """窗口内 matching_blocks 覆盖率 + 匹配首尾流位。"""
    sm = SequenceMatcher(None, stream[lo:hi], needle, autojunk=False)
    blocks = sm.get_matching_blocks()
    cov = sum(b.size for b in blocks) / len(needle)
    return cov, lo + blocks[0].a, lo + blocks[-1].a + blocks[-1].size


def _match_bounded(  # noqa: C901 -- gram 锚定+兜底+打分是同一段语义阶梯
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
    for s0 in sorted(cand)[:_CAND_CAP]:
        lo2 = max(lo, s0 - 8)
        hi2 = min(hi, s0 + ln * 3 + 40)
        if hi2 <= lo2:
            continue
        cov, p, e = _sm_cov(stream, lo2, hi2, needle)
        if cov > best[1]:
            best = (p, cov, e)
    return best


def _offset_at(
    bounds: list[tuple[int, int, float]],
    keys: list[tuple[int, float]],
    page: int,
    frac: float,
) -> int:
    """(page,frac) → 最近行界的字符流 offset（marks↔流界换算用）。"""
    i = bisect.bisect_right(keys, (page, frac + 1e-6))
    j = max(0, i - 1)
    if (
        i < len(bounds)
        and bounds[i][1] == page
        and abs(bounds[i][2] - frac) < abs(bounds[j][2] - frac)
    ):
        j = i
    return bounds[j][0]


def _match_side(  # noqa: C901, PLR0912, PLR0915 -- 两遍骨架+补缺是单算法阶梯，拆开反失上下文
    needles: list[tuple[int, str]],
    stream: str,
    prior: dict[int, int] | None = None,
    lo_known: dict[int, int] | None = None,
    order: dict[int, int] | None = None,
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

    gidx: dict[str, list[int]] = {}
    for i in range(len(stream) - _GRAM + 1):
        gidx.setdefault(stream[i : i + _GRAM], []).append(i)
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
        for seq, nd in needles:
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
                    prev_end = max(prev_end, p + ln)
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
                    # 声块甩远（seq3 e=3003 盖过 seq4 起点 2189 实证）
                    prev_end = max(prev_end, p + ln)
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
    bounds: list[tuple[int, int, float]],
    off: int,
) -> dict[str, Any] | None:
    """流 offset → 所在行界 Pos。offset 落在行内——上取该行（行界记行首）。"""
    i = bisect.bisect_right([b[0] for b in bounds], off) - 1
    if i < 0:
        return None
    return {"page": bounds[i][1], "fraction": bounds[i][2]}


def _interp_t(
    pairs: list[dict[str, Any]] | None, o_pos: dict[str, Any]
) -> dict[str, Any] | None:
    """O Pos → t Pos 分段线性插值（``alignment.pairs`` 地标杆）。

    zh.pdf textLayer 无 ToUnicode 时 CJK 全错码点、文本匹配是死路——
    pairs 的 (original,translated) 点列按 page+frac 线性化后分段映射。
    范围外取端点（参考文献尾部漂移可容忍——只作跳转锚不闪烁）。
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
    return {"page": max(1, page), "fraction": round(min(0.999, max(0.0, frac)), 5)}


def compute_seqpos(  # noqa: C901, PLR0912 -- 装配阶梯单流：marks→snap→双侧匹配→降级
    en_pdf: Path,
    zh_pdf: Path,
    chunks: list[dict[str, Any]],
    task_dir: Path | None = None,
    pairs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """两侧位置合成 → ``{"seq": {"o": Pos, "t": Pos}}``（seq 字符串键）。"""
    en_stream, en_bounds, _, _mc = _char_stream(en_pdf)
    zh_stream, zh_bounds, marks, mark_chars = _char_stream(zh_pdf, collect_marks=True)

    order = _doc_order(task_dir, chunks) if task_dir is not None else {}
    en_needles = _needles(chunks, "en")
    zh_needles = _needles(chunks, "zh")
    if order:
        big = 1 << 30
        en_needles.sort(key=lambda sn: order.get(sn[0], big + sn[0]))
        zh_needles.sort(key=lambda sn: order.get(sn[0], big + sn[0]))

    zh_keys = [(b[1], b[2]) for b in zh_bounds]

    # 孤儿标记 snap——页断处 BDC 只裹 <4 字形沉在页底（frac>0.85），
    # 正文被推到后续 1~3 页（中间浮动页跳过，实证 +1/+2/+3 都有）：
    # 取 zh needle 头 40 字在后 3 页文本里找真位，找着就改锚
    zh_nd = dict(zh_needles)
    for seq, (pg, fr) in list(marks.items()):
        if fr <= _ORPHAN_FRAC or mark_chars.get(seq, 0) >= _ORPHAN_CHARS:
            continue
        nd = zh_nd.get(seq) or ""
        if len(nd) < _ORPHAN_MIN_ND:
            continue
        lo = next((b[0] for b in zh_bounds if b[1] > pg), len(zh_stream))
        hi = next(
            (b[0] for b in zh_bounds if b[1] > pg + _ORPHAN_PAGES), len(zh_stream)
        )
        j = zh_stream.find(nd[:40], lo, hi)
        if j >= 0:
            pos = _pos_at(zh_bounds, j)
            if pos:
                marks[seq] = (pos["page"], pos["fraction"])

    # zh：marked seq 免匹配——但把它们换算成流 offset 当补缺界桩
    chunks_by_seq = {c.get("seq"): c for c in chunks if isinstance(c.get("seq"), int)}
    zh_off_known = {
        seq: _offset_at(zh_bounds, zh_keys, pg, fr) for seq, (pg, fr) in marks.items()
    }
    # en 侧先验：zh 标记 offset 按流长比映射——marked seq 的候选被限在
    # 估计带内，局部相似文本（TOC↔章节题/参考文献惯用句）不再能误锚
    scale = len(en_stream) / max(1, len(zh_stream))
    en_prior = {seq: int(off * scale) for seq, off in zh_off_known.items()}
    en_off = _match_side(en_needles, en_stream, en_prior, order=order)

    # zh 乱码降级：textLayer 无 ToUnicode 时 CJK 全错码点，文本匹配
    # 死路——未标记 seq 的 t 走 alignment.pairs 分段线性插值。
    # 判定用密度阈而非 any()——错码点面也会零星撞上 CJK 区（实证
    # 85234 字符里混 156 个 CJK 照样全废）
    zh_cjk = sum(1 for ch in zh_stream if "一" <= ch <= "鿿")
    zh_dead = zh_cjk < max(100, len(zh_stream) // 20) and any(
        "一" <= ch <= "鿿" for c in chunks for ch in (c.get("zh") or "")
    )
    zh_unmarked = [(seq, nd) for seq, nd in zh_needles if seq not in marks]
    zh_off = (
        {}
        if zh_dead
        else _match_side(zh_unmarked, zh_stream, lo_known=zh_off_known, order=order)
    )

    out: dict[str, Any] = {}
    for seq in sorted(set(en_off) | set(marks) | set(zh_off)):
        c = chunks_by_seq.get(seq) or {}
        if not c.get("en") and not c.get("zh"):
            continue
        o_pos = _pos_at(en_bounds, en_off[seq]) if seq in en_off else None
        if seq in marks:
            pg, fr = marks[seq]
            t_pos: dict[str, Any] | None = {"page": pg, "fraction": fr}
        elif seq in zh_off:
            t_pos = _pos_at(zh_bounds, zh_off[seq])
        elif zh_dead and o_pos:
            t_pos = _interp_t(pairs, o_pos)
        else:
            t_pos = None
        if o_pos and t_pos:
            out[str(seq)] = {"o": o_pos, "t": t_pos}
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
