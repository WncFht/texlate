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
_VERSION = 4

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


def _reading_order(lines: list[Any], width: float) -> list[Any]:
    """双栏检测。

    页宽中段 28%~72% 扫最少穿线的竖带作中缝，跨缝行（通栏标题/页眉）
    当区界——区内先左栏顶到底、再右栏。无可靠中缝 → 单栏原序。
    """
    if len(lines) < _COL_MIN_LINES:
        return lines
    lo, hi = width * 0.28, width * 0.72
    thr = max(2, int(len(lines) * 0.10))
    best_x, best_c = -1.0, 1 << 30
    x = lo
    while x < hi:
        c = sum(1 for ln in lines if ln[2] < x < ln[3])
        if c < best_c:
            best_x, best_c = x, c
        x += 3.0
    if best_x < 0 or best_c > thr:
        return lines
    gl = gr = best_x
    while gl - 3 > lo and sum(1 for ln in lines if ln[2] < gl - 3 < ln[3]) <= thr:
        gl -= 3.0
    while gr + 3 < hi and sum(1 for ln in lines if ln[2] < gr + 3 < ln[3]) <= thr:
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
) -> tuple[str, list[tuple[int, int, float]], dict[int, tuple[int, float]]]:
    """PDF → (归一字符流, 行界 [(char_offset, page, frac_top_down)], marks)。

    ``visitor_text`` 的 tm 是局部矩阵——绝对位须复合 cm：
    ``x=tm4*cm0+tm5*cm2+cm4, y=tm4*cm1+tm5*cm3+cm5``（底向上）。

    ``collect_marks`` 时同遍经 ``visitor_operand_before`` 直读 TLXC 标记
    （``BDC /MCID=50000+seq``）→ seq→(page,frac)——单遍双 visitor 省一趟
    extract_text（CMap 解析是主成本，39pp 实测省 ~1/3 耗时）。
    """
    from pypdf import PdfReader  # noqa: PLC0415 -- 与 align.py 同例懒载

    reader = PdfReader(str(path))
    chars: list[str] = []
    bounds: list[tuple[int, int, float]] = []
    marks: dict[int, tuple[int, float]] = {}
    char_off = 0
    for pi, page in enumerate(reader.pages):
        runs: list[tuple[float, float, float, str]] = []
        height = float(page.mediabox.height)
        width = float(page.mediabox.width)

        def vt(
            text: str,
            cm: list[float],
            tm: list[float],
            font: object,  # noqa: ARG001 -- 签名由 pypdf 定死
            size: float,
            _runs: list[tuple[float, float, float, str]] = runs,
        ) -> None:
            if text.strip():
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
        ) -> None:
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
    return "".join(chars), bounds, marks


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


def _match_side(  # noqa: C901, PLR0912 -- 两遍骨架+补缺是单算法阶梯，拆开反失上下文
    needles: list[tuple[int, str]],
    stream: str,
    prior: dict[int, int] | None = None,
    lo_known: dict[int, int] | None = None,
) -> dict[int, int]:
    """Needle 序列 → seq→流 offset（命中起点）。

    两遍：A 顺序骨架——marked seq（``prior`` 有估计位）候选限先验带
    est±20%，未标记走光标窗口；接受条件 cov≥阈 + 局部不回退 +
    （无先验时）跳距上限。B 漏跑段在相邻命中夹逼界∩先验带内补缺。
    ``lo_known`` 预置已知锚（zh marks）时跳过 A 全走夹逼。

    先验带的存在理由：局部窗口无法识别「贴脸的误锚」——seq174 在
    cursor 后 200 字符处以 cov 0.55+ 命中相似文本，把补缺上界钉死在
    57k、78k+ 的补充材料 TOC 全灭（实证）。zh marks 是序真值，按
    流长比例映射到本侧后 est±20% 足以排掉 40k 级错位。
    """
    gidx: dict[str, list[int]] = {}
    for i in range(len(stream) - _GRAM + 1):
        gidx.setdefault(stream[i : i + _GRAM], []).append(i)
    band = max(6000, len(stream) // 5)

    hit: dict[int, tuple[int, int]] = {}  # seq → (pos, end)
    miss: list[tuple[int, str]] = []
    if lo_known is not None:
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
                    hit[seq] = (p, _e)
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
                    hit[seq] = (p, _e)
                    # 前进量用 needle 长而非 match 尾块——SM 尾块常被噪
                    # 声块甩远（seq3 e=3003 盖过 seq4 起点 2189 实证）
                    prev_end = max(prev_end, p + ln)
                else:
                    miss.append((seq, nd))

    for seq, nd in miss:
        if prior is not None and seq in prior:
            # marked 补缺只吃先验带——邻位界对浮动体是错约束
            lo, hi = prior[seq] - band, prior[seq] + band
        else:
            prevs = [hit[s] for s in hit if s < seq]
            nexts = [hit[s] for s in hit if s > seq]
            lo = max((e for _, e in prevs), default=0)
            hi = min((p for p, _ in nexts), default=len(stream))
        if lo_known:
            lo = max(lo, max((o for s, o in lo_known.items() if s < seq), default=0))
            hi = min(
                hi,
                min((o for s, o in lo_known.items() if s > seq), default=len(stream)),
            )
        if hi <= lo:
            # 邻位夹逼窗倒置——浮动体让锚位在流中不单调（seq161：前邻锚
            # 53742 > 后邻锚 53073，真位 54269 在窗外）。退化为以两界
            # 中点为心的局部窗，长度吃 needle 余量。
            mid = (lo + hi) // 2
            pad = max(4000, len(nd) * 3)
            lo, hi = mid - pad, mid + pad
        p, cov, e = _match_bounded(nd, stream, gidx, lo, max(hi, lo + 200))
        if p >= 0 and cov >= _min_cov(len(nd)):
            hit[seq] = (p, e)
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


def compute_seqpos(
    en_pdf: Path, zh_pdf: Path, chunks: list[dict[str, Any]]
) -> dict[str, Any]:
    """两侧位置合成 → ``{"seq": {"o": Pos, "t": Pos}}``（seq 字符串键）。"""
    en_stream, en_bounds, _ = _char_stream(en_pdf)
    zh_stream, zh_bounds, marks = _char_stream(zh_pdf, collect_marks=True)

    zh_keys = [(b[1], b[2]) for b in zh_bounds]

    # zh：marked seq 免匹配——但把它们换算成流 offset 当补缺界桩
    chunks_by_seq = {c.get("seq"): c for c in chunks if isinstance(c.get("seq"), int)}
    zh_off_known = {
        seq: _offset_at(zh_bounds, zh_keys, pg, fr) for seq, (pg, fr) in marks.items()
    }
    # en 侧先验：zh 标记 offset 按流长比映射——marked seq 的候选被限在
    # 估计带内，局部相似文本（TOC↔章节题/参考文献惯用句）不再能误锚
    scale = len(en_stream) / max(1, len(zh_stream))
    en_prior = {seq: int(off * scale) for seq, off in zh_off_known.items()}
    en_off = _match_side(_needles(chunks, "en"), en_stream, en_prior)
    zh_unmarked = [(seq, nd) for seq, nd in _needles(chunks, "zh") if seq not in marks]
    zh_off = _match_side(zh_unmarked, zh_stream, lo_known=zh_off_known)

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
    try:
        seqpos = compute_seqpos(en_pdf, zh_pdf, chunks)
    except Exception as exc:  # noqa: BLE001 -- 对位失败降级不炸 reader
        log.warning("seqpos: compute failed for %s: %s", task_dir.name, exc)
        return None
    try:
        atomic_json(cache, {"v": _VERSION, "seqpos": seqpos})
    except OSError as exc:
        log.debug("seqpos: cache write failed: %s", exc)
    return seqpos
