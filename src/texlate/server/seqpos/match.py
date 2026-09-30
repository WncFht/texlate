r"""seqpos.match — needle ↔ 归一字符流匹配两遍 (seqpos 子包叶)。

``_match_side`` 两遍架构：A 顺序骨架——marked seq（``prior`` 有估计
位）候选限先验带 est±20%，未标记走光标窗口；B 漏跑段在相邻命中夹逼
界∩先验带内补缺；C 全流扫描兜底段级转置/漂移。锚定走 6-gram 位置
索引 + SM 覆盖率双闸（最长单块阈随针长收封顶 64——``\\cite`` 渲染把
长段切碎）。``_offset_at`` 是 marks↔流界 (page,frac,x) → 字符流
offset 的换算件，``_COL_SPLIT_X`` 栏判定口径与前端阅读序键同源。
"""

from __future__ import annotations

import bisect
import re
from difflib import SequenceMatcher
from itertools import pairwise

from texlate.server.seqpos.stream import _norm_chars

#: _min_cov 针长分档
_COV_SHORT = 30
_COV_MID = 80
#: 锚定 gram 长（字符）；needle 更短则取全长
_GRAM = 6
#: 单 gram 频度上限——超了没锚定价值（常见串）
_GRAM_FREQ = 240
#: 补缺候选打分上限
_CAND_CAP = 48
#: pass-C 无窗兜底的 cov 阈——无界 fuzzy 命中抬门槛宁缺勿滥
_PASSC_COV = 0.9
#: pass-A 接受命中允许的最大前跳（流字符）——超了宁可 miss 让
# pass-B 邻位夹逼判，防止一次误锚把 cursor 拖到 doc 尾连锁塌方
_JUMP_CAP = 6000
_SKIP_PROBE_MIN = 300
#: 针头验收：位置证据（标 occurrence / snap 命中位）必须裹针头——
#: 针深嵌标腹（引文汤裹标题、粗标跨块裹全段）或 snap 尾锚投影起点时，
#: 报位=标顶/臆造起点而非针位（bbb seq0 引文行裹标题、a7c5 zh seq1
#: snap 异文窗、a7c5 en seq76 针嵌 1525 字标深 900 实证）。LEAD=针头
#: 距证据起点容差（章/图表标签前缀 ~11 字）,N=校验针长，BLK=实块下限，
#: SKIP=头块针内偏移容差（头几字渲染变体）,COV=窗内针头覆盖阈。
_MARK_HEAD_LEAD = 12
_MARK_HEAD_N = 16
_MARK_HEAD_BLK = 6
_MARK_HEAD_SKIP = 4
_MARK_HEAD_COV = 0.6
#: 引文数字缝桥接的流侧缝宽上限（'[12,46,101,423]' 类连引实测 ~12 位）
_CITE_GAP = 20
#: 桥接缝里 ≥3 字母连跑 = 真词插入——渲染件残件（数字/bib 标签/符号）不桥
_GAP_WORD_RX = re.compile(r"[a-zA-Z]{3,}")
#: 栏判定 x 中点契约（col = x>=0.45 ? 1 : 0）——与前端阅读序键同口径
_COL_SPLIT_X = 0.45


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


def _gram_index(stream: str) -> dict[str, list[int]]:
    """构建归一字符流的 6-gram 位置索引（_match_bounded 锚定用）。"""
    gidx: dict[str, list[int]] = {}
    for i in range(len(stream) - _GRAM + 1):
        gidx.setdefault(stream[i : i + _GRAM], []).append(i)
    return gidx


def _sm_cov(stream: str, lo: int, hi: int, needle: str) -> tuple[float, int, int, int]:
    """窗口内 matching_blocks → (覆盖率，针起点投影位，匹配尾位，最长单块)。

    报告位是针起点投影 ``lo+blocks[0].a-blocks[0].b``（clamp 到 lo）——
    记首块位在针有前导残段时系统性偏后，跨页假锚实证。
    """
    if not needle:
        return 0.0, lo, lo, 0
    sm = SequenceMatcher(None, stream[lo:hi], needle, autojunk=False)
    blocks = sm.get_matching_blocks()
    cov = sum(b.size for b in blocks) / len(needle)
    # 渲染件缝桥接：相邻 block 在针上连续（needle 已剥 [[CITE_n]]/[[REF_n]]/
    # [[MATH_n]]）而流侧仅隔短渲染件——引文数字串 '124610142343'、bib 标签
    # 'b2'/'e1'、单枚数学符号 'θ' 皆是针剥占位后的流侧残件。含 ≥3 字母连
    # 跑的缝不桥（真词插入=别段文本）；超长缝/针侧有残段不桥（防回多跳
    # 拼接假锚）。
    longest = cur = 0
    prev_a = prev_b = 0
    for b in blocks:
        if not b.size:
            continue
        if (
            prev_a
            and b.b == prev_b
            and 0 < b.a - prev_a <= _CITE_GAP
            and not _GAP_WORD_RX.search(stream[lo + prev_a : lo + b.a])
        ):
            cur += b.size
        else:
            cur = b.size
        longest = max(longest, cur)
        prev_a, prev_b = b.a + b.size, b.b + b.size
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


def _head_ok(text: str, needle: str) -> bool:
    """针头验收：``text``（已归一、始于声位）头窗内须裹针头。

    位置证据（标内文本 / snap 命中报位下游流）只在针头在场时才认作
    针起点——深嵌命中裹针腹而针头缺席时，声位只是投影臆造。双闸：
    ≥BLK 实块的首个须压在针头上段（b≤SKIP——尾锚命中的实块都从针
    腹起，1~2 字散块占位只算噪声），全窗针头覆盖再过阈。
    """
    head = needle[:_MARK_HEAD_N]
    if not head:
        return False
    win = text[: _MARK_HEAD_LEAD + len(head) + _CITE_GAP]
    if not win:
        return False
    sm = SequenceMatcher(None, win, head, autojunk=False)
    bl = [b for b in sm.get_matching_blocks() if b.size]
    real = [b for b in bl if b.size >= min(_MARK_HEAD_BLK, len(head))]
    if not real or real[0].b > _MARK_HEAD_SKIP:
        return False
    return sum(b.size for b in bl) / len(head) >= _MARK_HEAD_COV


def _match_bounded(  # noqa: C901, PLR0912, PLR0915 -- gram 锚定 + 兜底 + 打分是同一段语义阶梯
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
    # 32 例跨页假锚；块阈随针长收但封顶 64——\cite 渲染成行内文本把长段
    # 切碎（实证 1133 字针 cov=1.0 而 blk 仅 73），0.3·ln 对长针不可达
    need_blk = min(ln, max(6, 0.3 * ln), 64)
    mcov = _min_cov(ln)
    # 候选超帽时按离窗心距离取——最小 offset 截断会把窗内真位挤出去
    mid = (lo + hi) / 2
    # 界内 verbatim 恒满分必先评：超帽截断会把窗沿 verbatim 逐出
    # 候选集（bbb seq5 实证：138 候选中 p1 verbatim 距窗心 12536 排
    # 百位外被截，fuzzy cov0.946 错锚顶位）
    verb: list[int] = []
    j = stream.find(needle, max(0, lo), hi) if ln else -1
    while j >= 0 and len(verb) < _CAND_CAP:
        verb.append(j)
        j = stream.find(needle, j + 1, hi)
    if verb:
        s0 = min(verb, key=lambda s: abs(s - mid))
        return s0, 1.0, s0 + ln
    for s0 in sorted(cand, key=lambda s: abs(s - mid))[:_CAND_CAP]:
        # cov 满分后无人能翻（strict >）——直接断，省尾部 SM 评估
        if best[1] >= 1.0:
            break
        # 整针落界内的精确命中先 memcmp 出分——免 3·ln 窗口 difflib
        # （profile：SM 占匹配侧 ~95% 耗时）。界沿外候选不可短路：
        # s0∈[lo-40,lo) 时旧路 SM 窗从 lo 截、返位≠s0，直返会破窗约
        if lo <= s0 and s0 + ln <= hi and stream[s0 : s0 + ln] == needle:
            cov, p, e, blk = 1.0, s0, s0 + ln, ln
        elif ln < _COV_SHORT:
            # 短针除 verbatim 外只收「纯插入」近似：匹配块在针上全序连续
            # （无替换/缺失）、流侧缝皆 ≤_CITE_GAP 渲染件——宏展开残件
            # （\ourmodelthree→'tabpfn3'）/引文数字插进流不是针错（t_25e3
            # seq22 zh 针 cov1.0 缝 'tabpfn3'/'1' 实证）；替换型近似仍弃
            # （'projectwho'≈'projectlead' 类碎块凑分毒锚实证）。
            lo2 = max(0, lo, s0 - 8)
            hi2 = min(hi, s0 + ln * 3 + 40)
            if hi2 <= lo2:
                continue
            sm2 = SequenceMatcher(None, stream[lo2:hi2], needle, autojunk=False)
            bl = [b for b in sm2.get_matching_blocks() if b.size]
            if not bl or not all(
                b.b == a.b + a.size and b.a - (a.a + a.size) <= _CITE_GAP
                for a, b in pairwise(bl)
            ):
                continue
            cov = sum(b.size for b in bl) / ln
            p = max(lo, lo2 + bl[0].a - bl[0].b)
            e = lo2 + bl[-1].a + bl[-1].size
            blk = ln  # 针侧全序连续链视同一个块
        else:
            lo2 = max(0, lo, s0 - 8)
            hi2 = min(hi, s0 + ln * 3 + 40)
            if hi2 <= lo2:
                continue
            cov, p, e, blk = _sm_cov(stream, lo2, hi2, needle)
        if blk >= need_blk and cov >= mcov and cov > best[1]:
            best = (p, cov, e)
    return best


def _match_all(  # noqa: C901, PLR0912 -- gram 锚定+find 兜底+SM 打分为同一阶梯，拆散反失上下文
    needle: str, stream: str, gidx: dict[str, list[int]]
) -> list[tuple[int, float, int]]:
    """全流扫描返回所有 (pos,cov,end) 达阈候选——pass-C 消歧用。"""
    ln = len(needle)
    g = min(_GRAM, ln)
    cand: set[int] = set()
    if g >= _GRAM:
        grams = sorted(
            (len(gidx[needle[i : i + g]]), i)
            for i in range(0, ln - g + 1, 4)
            if 0 < len(gidx.get(needle[i : i + g], [])) <= _GRAM_FREQ
        )
        for _cnt, i in grams[:8]:
            for p in gidx[needle[i : i + g]]:
                if p >= i:
                    cand.add(p - i)
    if not cand:
        start = 0
        while len(cand) < _CAND_CAP:
            j = stream.find(needle, start)
            if j < 0:
                break
            cand.add(j)
            start = j + 1
    need_blk = min(ln, max(6, 0.3 * ln), 64)
    mcov = _min_cov(ln)
    out: list[tuple[int, float, int]] = []
    for s0 in sorted(cand)[:_CAND_CAP]:
        if s0 >= 0 and stream[s0 : s0 + ln] == needle:
            out.append((s0, 1.0, s0 + ln))
            continue
        lo2 = max(0, s0 - 8)
        hi2 = min(len(stream), s0 + ln * 3 + 40)
        if hi2 <= lo2:
            continue
        cov, p, e, blk = _sm_cov(stream, lo2, hi2, needle)
        if blk >= need_blk and cov >= mcov:
            out.append((p, cov, e))
    # _CAND_CAP 升位截断会把高 offset verbatim 整类逐出（同
    # _match_bounded 窗沿 verbatim 被截实证）——全收并去重补回
    have = {p for p, _c, _e in out}
    j = stream.find(needle, 0, len(stream)) if ln else -1
    while j >= 0:
        if j not in have:
            out.append((j, 1.0, j + ln))
            have.add(j)
        j = stream.find(needle, j + 1, len(stream))
    return out


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
    bounds: list[tuple[int, int, float, float, float]],
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


def _match_side(  # noqa: C901, PLR0912, PLR0913, PLR0915, PLR0917 -- 两遍骨架 + 补缺是单算法阶梯，拆开反失上下文
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
    # 补缺重试的 est 用序位比例而非裸 key 比——``_doc_order`` 的
    # r*big+j 编码下 key/max_key 对早文件 seq 恒≈0，重试窗钉死文首
    # （t_e300 seq72 真位 33557 窗外 MISS 实证）
    sorted_keys = sorted(order.values()) if order else []
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
            # rank 序位比例估计带 est±band 再试一次
            est = int(
                bisect.bisect_left(sorted_keys, key(seq))
                / max(1, len(sorted_keys))
                * len(stream)
            )
            lo2, hi2 = max(0, est - band), min(len(stream), est + band)
            p, cov, e = _match_bounded(nd, stream, gidx, lo2, max(hi2, lo2 + 200))
        if p >= 0 and cov >= _min_cov(len(nd)):
            # e=SM 尾块端点会被噪声甩远（交错区命中实证 e 超 p+3ln），
            # 它要当后续缺口的夹逼下界——截到 p+3ln 防界膨胀塌窗
            hit[seq] = (p, min(e, p + 3 * len(nd)))

    # pass-C 全局兜底：段级转置/漂移让所有窗口假设同时失效时（dual 旧
    # 分段编号 vs 渲染序——t_e300 整段 19 针灭实证），对仍未中的针做
    # 全流扫描。短针只收 verbatim 命中，长针收 cov 达阈候选；多候选
    # 取离已命中邻位夹逼中点最近者消歧。阈值抬到 0.9——无窗先验下
    # 弱 fuzzy 命中宁缺勿滥。
    still = [(seq, nd) for seq, nd in miss if seq not in hit]
    for seq, nd in sorted(still, key=lambda sn: key(sn[0])):
        ln = len(nd)
        if ln < _COV_SHORT:
            occ: list[int] = []
            j = stream.find(nd)
            while j >= 0 and len(occ) < _CAND_CAP:
                occ.append(j)
                j = stream.find(nd, j + 1)
            cands = [(o, 1.0, o + ln) for o in occ]
        else:
            cands = [
                (p, cov, e)
                for p, cov, e in _match_all(nd, stream, gidx)
                if cov >= _PASSC_COV
            ]
        if not cands:
            continue
        if len(cands) > 1:
            k = key(seq)
            lo = max((e for s, (_p, e) in hit.items() if key(s) < k), default=0)
            hi = min(
                (p for s, (p, _e) in hit.items() if key(s) > k),
                default=len(stream),
            )
            if lo_known:
                lo = max(
                    lo,
                    max(
                        (o for s, o in lo_known.items() if key(s) < k),
                        default=0,
                    ),
                )
                hi = min(
                    hi,
                    min(
                        (o for s, o in lo_known.items() if key(s) > k),
                        default=len(stream),
                    ),
                )
            mid = (lo + hi) / 2
            cands.sort(key=lambda cpe: abs(cpe[0] - mid))
        p, _cov, e = cands[0]
        hit[seq] = (p, min(e, p + 3 * ln))
    return {seq: p for seq, (p, _) in hit.items()}
