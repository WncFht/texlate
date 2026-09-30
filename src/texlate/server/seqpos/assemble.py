"""seqpos.assemble — 双侧位置合成 + mark 校验 + 懒算缓存 (seqpos 子包叶)。

``compute_seqpos`` 装配阶梯：marks 校验（``_mark_trusted``——周期性
replay 剔出/needle SM 覆盖/针头验收/孤儿 snap/实标兜底）→ zh/en
双侧 ``_match_side`` 补缺 → 死区 seq 针配后滤 → ``_pos_at``/
``_row_extent`` 流 offset 投影 Pos → zh_dead 时 ``_interp_t``
alignment.pairs 插值兜底。``seqpos_for_task`` 懒算 + 缓存
``task_dir/seqpos.json``，输入件 mtime 更新即重算；dual.json 本体
不动（``?version=sha256`` 不可变）。
"""

from __future__ import annotations

import bisect
import json
import logging
from typing import TYPE_CHECKING

from texlate.server.seqpos.docorder import _doc_order
from texlate.server.seqpos.match import (
    _CITE_GAP,
    _COL_SPLIT_X,
    _MARK_HEAD_LEAD,
    _MARK_HEAD_N,
    _gram_index,
    _head_ok,
    _match_bounded,
    _match_side,
    _offset_at,
    _sm_cov,
    _text_cov,
)
from texlate.server.seqpos.stream import (
    _char_stream,
    _font_cache_ctx,
    _norm_chars,
    _tex_strip,
)
from texlate.xlat.state import atomic_json

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

log = logging.getLogger(__name__)

_CACHE = "seqpos.json"
_VERSION = 25

#: 孤儿 snap 判据：BDC 裹字形数下限（页断沉底错锚）/ 针长下限 / 双向寻位页窗
_ORPHAN_CHARS = 4
_ORPHAN_MIN_ND = 8
_ORPHAN_PAGES = 5
#: mark 校验 SM 覆盖阈——occurrence 标内文本对 zh needle 低于则不可信
_MARK_COV = 0.35
#: 实标兜底：裹字形数下限（目录/LOF 重放行达不到的量级）与针覆盖地板
#: （防 splice 错位裹进全无关段）。snap 寻不到针时末锚定标按位兜底。
_MARK_FALLBACK_CHARS = 48
_MARK_FB_COV = 0.10
#: 小碎片兜底副车道：页中区（f<0.92，folio 区之上）裹 ≥8 字形的锚定标
#: 免针地板——十几字形里针覆盖全是噪声（t_0c25 seq48 zh 15 字形段首
#: 残件实证）；folio 区小碎片多为页码残件（t_5248 seq87 "19" 实证）不兜。
_MARK_FB_CHARS_LO = 8
_MARK_FB_MAXFRAC = 0.92
#: 页眉页脚 replay 剔出：同 fraction 跨 ≥3 页的 occurrence = 模板运行头
#: 逐页同位重打（``\title`` 宏注锚被页眉引用每页回放——a7c5 seq0 实证
#: en/zh 各 ~10 个 fr0.040 occurrence 淹没真标；en 前缀 'emilylhun
#: tandsabinereffert' 26 字被 LEAD 拦、zh 'reffert' 7 字漏网——周期
#: 性与前缀长无关，是 replay 族的本质判据）。正文锚永不周期同位。
_MARK_REPLAY_PAGES = 3

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


def _nd_unmatchable(nd: str, *, starved: bool) -> bool:
    """CJK 重针在错码点饥荒流上必死——剔出免拖垮夹逼界（半译混合档）。"""
    if not starved:
        return False
    return sum(1 for ch in nd if "一" <= ch <= "鿿") > max(4, len(nd) // 2)


def _pos_at(
    bounds: list[tuple[int, int, float, float, float]],
    off: int,
) -> dict[str, Any] | None:
    """流 offset → 所在行界 Pos（针首字位 x + 行右缘 x1）。offset 落行内——上取该行。"""
    i = bisect.bisect_right([b[0] for b in bounds], off) - 1
    if i < 0:
        return None
    b = bounds[i]
    x = b[3]
    if i + 1 < len(bounds):
        ln = bounds[i + 1][0] - b[0]
        if ln > 0 and b[4] > b[3]:
            # 针首字按行内字位内插：同视觉行多 seq 锚（TOC 行/行内多标）
            # 行级 x0 并列时 x 序失效——containing 同排格段规取 x0≤点击
            # 最右者会吸错邻（bedd seq76/79 同 TOC 行同幅面锚实证）。
            # 栏身份钉死行左缘：col0 行内插越中缝会把通栏行针记成 col1。
            xi = x + (off - b[0]) / ln * (b[4] - b[3])
            x = min(xi, _COL_SPLIT_X - 0.001) if b[3] < _COL_SPLIT_X else xi
    return {"page": b[1], "fraction": b[2], "x": x, "x1": b[4]}


_ROW_EPS = 0.012  # 同视觉行判定：锚=行顶 frac、点击/标位=字形带中 → ~半行高容差
_ROW_EPSX = 0.03  # 行幅面 x 容差（est_w 估宽噪声 + 标首字形未必贴左缘）


def _row_extent(
    bounds: list[tuple[int, int, float, float, float]],
    page: int,
    frac: float,
    x: float | None,
) -> tuple[float, float] | None:
    """(page,frac) 最近行界 → (行左缘 x0, 行右缘 x1)——mark 锚补行幅面。

    锚行须同页且 |Δfrac|≤半行级容差；mark 自带 x 时还要求 x 落回该行
    ``[x0,x1]`` 内（防把标记 snap 到同 frac 的异行）。
    """
    cands = [b for b in bounds if b[1] == page]
    if not cands:
        return None
    # 先按 frac 收窄到同视觉行（双栏同线左右段常同 frac），行集里再按
    # x 行距（到 [x0,x1] 幅面距离）定栏——frac/eps 先取会把 x1 snap 到
    # 错栏行幅面（左栏行 x1+eps 糊住右栏标 x：0.514 vs 0.486+0.03 实证）；
    # x 全行不认领（>eps）即拒——防把标记 snap 到同 frac 的异行。
    near = [b for b in cands if abs(b[2] - frac) <= _ROW_EPS]
    if not near:
        return None
    if x is not None:
        b = min(near, key=lambda b: max(b[3] - x, x - b[4], 0.0))
        if max(b[3] - x, x - b[4], 0.0) > _ROW_EPSX:
            return None
    else:
        b = min(near, key=lambda b: abs(b[2] - frac))
    return b[3], b[4]


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


def _mark_trusted(  # noqa: C901, PLR0912, PLR0913 -- 双侧共用校验件，参面=校验输入全集
    marks: dict[int, list[dict[str, Any]]],
    nd_map: dict[int, str],
    stream: str,
    bounds: list[tuple[int, int, float, float, float]],
    *,
    dead: bool = False,
    n_needles: int = 0,
) -> tuple[dict[int, dict[str, Any]], dict[str, list[int]] | None]:
    """Validate marked seqs → trusted anchor occurrences（双侧同件：zh/en 共用校验+snap 链）。

    mark 校验：occurrence 先过周期性 replay 剔出——同 fraction 跨
    ≥``_MARK_REPLAY_PAGES`` 页的是页眉页脚模板重打（正文锚不周期）；
    再对 needle SM 覆盖 + 针头验收——cov≥阈 之外还要求针起点投影贴
    标头（``start ≤ _MARK_HEAD_LEAD``）且头窗实裹针头：深嵌标腹的
    occurrence（引文汤裹标题 verbatim、粗标跨块裹整段）标顶≠针位，
    剔出可信集落 snap 路寻真起点。同 MCID 重放（hyperref/TOC）首
    occurrence 常落目录页；可信集取末个（TOC 在前真标在后）；
    全低分/无锚 → 不可信，留待 snap/needle 路。

    孤儿 snap：标记不可信/裹字形过少（页断沉底 + fr≤0.85 中页错锚）
    → 语义匹配在标称页 ±5 页双向寻真位；命中同样过针头验收——尾锚
    投影起点的异文命中不换真位（a7c5 zh seq1 实证），救不回的
    留 needle 路。返回 ``(trusted, gidx)``——gidx 供调用方复用于
    ``_match_side``（未命中 needle 补缺同索引），无需时为 None。
    """
    trusted: dict[int, dict[str, Any]] = {}
    pools: dict[int, list[dict[str, Any]]] = {}
    for seq, occs in marks.items():
        anchored = [o for o in occs if o["fraction"] is not None]
        if not anchored:
            continue
        per: dict[float, set[int]] = {}
        for o in anchored:
            per.setdefault(round(o["fraction"], 2), set()).add(o["page"])
        replay = {f for f, pgs in per.items() if len(pgs) >= _MARK_REPLAY_PAGES}
        pool = [o for o in anchored if round(o["fraction"], 2) not in replay]
        pools[seq] = pool
        nd = nd_map.get(seq) or ""
        if nd and not dead:
            good = []
            for o in pool:
                m = _norm_chars(o["text"])
                cov, start, _e, _b = _sm_cov(m, 0, len(m), nd)
                if cov >= _MARK_COV and start <= _MARK_HEAD_LEAD and _head_ok(m, nd):
                    good.append(o)
        else:
            good = pool
        if good:
            trusted[seq] = good[-1]

    suspects = [
        seq
        for seq in marks
        if seq not in trusted or trusted[seq]["chars"] < _ORPHAN_CHARS
    ]
    gidx = (
        _gram_index(stream)
        if not dead and (suspects or n_needles > len(trusted))
        else None
    )
    if gidx is not None:
        for seq in suspects:
            nd = nd_map.get(seq) or ""
            if len(nd) >= _ORPHAN_MIN_ND:
                occ = trusted.get(seq) or (pools.get(seq) or marks[seq])[-1]
                lo = next(
                    (b[0] for b in bounds if b[1] >= occ["page"] - _ORPHAN_PAGES),
                    0,
                )
                hi = next(
                    (b[0] for b in bounds if b[1] > occ["page"] + _ORPHAN_PAGES),
                    len(stream),
                )
                p, _cov, _e = _match_bounded(nd, stream, gidx, lo, hi)
                if p >= 0 and _head_ok(
                    stream[p : p + _MARK_HEAD_LEAD + _MARK_HEAD_N + _CITE_GAP],
                    nd,
                ):
                    pos = _pos_at(bounds, p)
                    if pos is not None:
                        trusted[seq] = {
                            "page": pos["page"],
                            "fraction": pos["fraction"],
                            "x": pos["x"],
                            "chars": occ["chars"],
                        }
                        continue
            # 实标兜底：snap 寻不到针（数学符号/引文渲染汤把针切碎，
            # need_blk 不可达——t_5248 seq214 标内 351 字形 cov 0.26 实
            # 证）或针过短时，裹足量字形的末锚定 occurrence 按位兜底——
            # BDC/EMC 落点随字形走，cov 低是针被稀释而非位置错。TOC/LOF
            # 重放落文档前序故取末锚定即正文；裹字过少的小碎片（页断沉
            # 底 2 字符类）无位置证据不兜，针微命地板防裹进全无关段。
            # 兜底池同 replay 剔出——页眉 occurrence 无内容位证据不兜。
            if seq not in trusted:
                anch = pools.get(seq, [])
                if anch:
                    last = anch[-1]
                    n_ch = last.get("chars") or 0
                    if (
                        n_ch >= _MARK_FALLBACK_CHARS
                        and (
                            not nd
                            or _text_cov(last.get("text") or "", nd) >= _MARK_FB_COV
                        )
                    ) or (
                        n_ch >= _MARK_FB_CHARS_LO
                        and last["fraction"] < _MARK_FB_MAXFRAC
                    ):
                        trusted[seq] = {
                            "page": last["page"],
                            "fraction": last["fraction"],
                            "x": last.get("x"),
                            "chars": last["chars"],
                        }
    return trusted, gidx


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
        en_stream, en_bounds, en_marks = _char_stream(en_pdf, collect_marks=True)
        zh_stream, zh_bounds, zh_marks = _char_stream(zh_pdf, collect_marks=True)

    # 全 0 字形标 = 死区空壳（\iftoggle 吞参/弃置盒：BDC/EMC 执行了但
    # 标内零字形）——无位置证据，剥出标记层防孤儿 snap 拿针撞上近
    # 重复孪生段（t_f748 seq161：\icra{} 空壳 snap 到 \arxiv 段实证）。
    en_marks = {
        s: occs for s, occs in en_marks.items() if any(o.get("chars") for o in occs)
    }
    zh_marks = {
        s: occs for s, occs in zh_marks.items() if any(o.get("chars") for o in occs)
    }

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
    zh_starved = zh_cjk < max(100, len(zh_stream) // 20)
    # 死活判据看针面 CJK 占比而非 chunks any()——zh==en 未译任务流面
    # CJK 必饥荒，旧判据把可匹配的英文针全灭、锚全靠 _interp_t 猜
    # （t_e300 实证 zh 锚 0.45 frac 级错位）
    zh_nd_len = sum(len(nd) for _s, nd in zh_needles)
    zh_nd_cjk = sum(1 for _s, nd in zh_needles for ch in nd if "一" <= ch <= "鿿")
    zh_dead = zh_starved and zh_nd_cjk > max(100, zh_nd_len // 4)

    # zh/en 标记共走 ``_mark_trusted``：cov 校验 + 孤儿 snap——救回的
    # 不重走文本匹配（unmarked 在 snap 后算）
    trusted, zh_gidx = _mark_trusted(
        zh_marks,
        zh_nd,
        zh_stream,
        zh_bounds,
        dead=zh_dead,
        n_needles=len(zh_needles),
    )
    en_nd = dict(en_needles)
    en_trusted, en_gidx = _mark_trusted(
        en_marks,
        en_nd,
        en_stream,
        en_bounds,
        n_needles=len(en_needles),
    )

    # 双侧零标字形 = 死区候选（\iftoggle 吞参/弃置盒/声明点不渲染）：
    # 空壳标已剥出 marks，不在双侧标记层者进针配后滤——命中别家
    # trusted 标幅面 = 近重复孪生段误锚（t_f748 seq161/162→163/165
    # 实证）剥；命中无标自渲区（\maketitle 类收集 - 迟发文本，t_32fc
    # seq1 署名单实证）保留。整文档无标（遗产任务）不启用。
    if en_marks or zh_marks:
        dead_seqs = {
            s for s, _nd in en_needles if s not in en_marks and s not in zh_marks
        }
    else:
        dead_seqs = set()

    # zh：trusted mark 免匹配——换算成流 offset 当补缺界桩
    chunks_by_seq = {c.get("seq"): c for c in chunks if isinstance(c.get("seq"), int)}
    zh_off_known = {
        seq: _offset_at(zh_bounds, occ["page"], occ["fraction"], occ["x"])
        for seq, occ in trusted.items()
    }
    zh_unmarked = [
        (seq, nd)
        for seq, nd in zh_needles
        if seq not in trusted and not _nd_unmatchable(nd, starved=zh_starved)
    ]
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

    # en：en marks 自身即已知锚（lo_known 全走夹逼）——zh 锚按流长比
    # 映射的 est±band 先验带继续约束无标 seq（局部相似文本误锚实证）
    en_off_known = {
        seq: _offset_at(en_bounds, occ["page"], occ["fraction"], occ["x"])
        for seq, occ in en_trusted.items()
    }
    scale = len(en_stream) / max(1, len(zh_stream))
    en_prior = {seq: int(off * scale) for seq, off in zh_off_known.items()}
    for seq, off in zh_off.items():
        en_prior[seq] = int(off * scale)
    en_unmarked = [(seq, nd) for seq, nd in en_needles if seq not in en_trusted]
    en_off = (
        _match_side(
            en_unmarked,
            en_stream,
            en_prior,
            lo_known=en_off_known or None,
            order=order,
            gidx=en_gidx,
        )
        if en_unmarked
        else {}
    )

    # 死区 seq 针配后滤：命中落在别家 trusted 标幅面内 = 近重复孪生
    # 段误锚，剥（锚应属标主）；落无标区 = 声明点迟发文本真渲染，留。
    if dead_seqs:

        def _mk_spans(
            mk: dict[int, dict[str, Any]],
            bs: list[tuple[int, int, float, float, float]],
        ) -> list[tuple[int, int, int]]:
            return [
                (
                    s,
                    (o0 := _offset_at(bs, occ["page"], occ["fraction"], occ.get("x"))),
                    o0 + (occ.get("chars") or 0),
                )
                for s, occ in mk.items()
            ]

        zh_spans = _mk_spans(trusted, zh_bounds)
        en_spans = _mk_spans(en_trusted, en_bounds)
        zh_off = {
            s: o
            for s, o in zh_off.items()
            if s not in dead_seqs
            or not any(s2 != s and a <= o < b for s2, a, b in zh_spans)
        }
        en_off = {
            s: o
            for s, o in en_off.items()
            if s not in dead_seqs
            or not any(s2 != s and a <= o < b for s2, a, b in en_spans)
        }

    out: dict[str, Any] = {}
    # en_trusted 必须进并集——en-only seq（zh='' 未译 caption/abstract
    # 等：无 zh mark、无 zh needle、不在 en_unmarked）仅靠 en 标定位，
    # 漏集则整条 seq 从 seqpos 蒸发（t_f748 seq0/1 实证）
    for seq in sorted(set(en_off) | set(en_trusted) | set(trusted) | set(zh_off)):
        c = chunks_by_seq.get(seq) or {}
        if not c.get("en") and not c.get("zh"):
            continue
        if seq in en_trusted:
            m = en_trusted[seq]
            o_pos = {"page": m["page"], "fraction": m["fraction"]}
            if m.get("x") is not None:
                o_pos["x"] = m["x"]
            ext = _row_extent(en_bounds, m["page"], m["fraction"], m.get("x"))
            if ext is not None:
                o_pos["x1"] = ext[1]
        elif seq in en_off:
            o_pos = _pos_at(en_bounds, en_off[seq])
        else:
            o_pos = None
        if seq in trusted:
            m = trusted[seq]
            t_pos = {"page": m["page"], "fraction": m["fraction"]}
            if m.get("x") is not None:
                t_pos["x"] = m["x"]
            ext = _row_extent(zh_bounds, m["page"], m["fraction"], m.get("x"))
            if ext is not None:
                t_pos["x1"] = ext[1]
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
    """懒算 + 缓存 ``task_dir/seqpos.json``。

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
