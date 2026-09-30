"""seqpos.stream — 归一字母表 + PDF → 归一字符流抽取 (seqpos 子包叶)。

两侧归一原语：``_tex_strip``（LaTeX 源 → 渲染态近似，与前端
``copylatex.ts texStrip`` 同形——needle 侧）与 ``_norm_chars``
（纯 alnum 小写流——流/针/标内文本三侧共用）。两侧同形则字体丢
空格、断行连字符、标点渲染差全部免疫。

``_char_stream`` 双遍架构（pymupdf 可用时）——文本面与标记面各取最强
解码器；缺席/失败回落 ``_char_stream_pypdf`` 单遍老路。行界记
``(char_off,page,frac,x,x1)``——x/x1 是段左右缘页宽分位，栏判定/
阅读序键 ``(page,col,frac)`` 的原料 + 宽行 snap 幅面。
``_font_cache_ctx`` 按字体间接引用跨页缓存 pypdf Font（CMap 重解析
是抽取绝对大头），供调用方 ``compute_seqpos`` 包界。
"""

from __future__ import annotations

import contextlib
import logging
import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import Any

log = logging.getLogger(__name__)

#: 行聚类 y 容差（pt，底向上坐标同线合并）
_LINE_TOL = 2.5
# 锚 fraction 取行顶而非基线：tm 的 y 是基线原点，floor 语义下点击行
# 上半会漏回上一条 seq（实字形矩形仿真实证）——行顶=基线+ascender
_ASC = 0.8
#: CJK 全宽下界（_est_w 栏切宽度粗估）
_CJK_MIN = 0x2E7F
#: 双栏检测下限行数 / 中缝最小宽度（pt）
_COL_MIN_LINES = 8
_GUTTER_MIN_W = 10
_GUTTER_MIN_SIDE = 4
#: BDC 操作数个数（tag + properties）
_BDC_ARGC = 2

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


def _cluster_lines(
    runs: list[tuple[float, float, float, str, float | None]],
) -> list[Any]:
    """(y,x,size,text，实测宽|None) → [y, parts[(x,text,w)], x0, x1, max_sz]。

    pymupdf 路喂真实 span 宽——_est_w 估宽过冲会把同基线左右栏聚行
    的虚幅面推过中缝，跨缝拆分闸失效、bound x1 胀到 0.89 抢对栏点
    击（t_0c2574 p7 实证）。None 走 _est_w 兜底（pypdf 路）。
    """
    runs.sort(key=lambda r: (-r[0], r[1]))
    lines: list[Any] = []
    for y, x, sz, t, rw in runs:
        w = rw if rw is not None else _est_w(t, sz)
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


def _reading_order(  # noqa: C901, PLR0912 -- 中缝扫描/左右归类/跨栏行重排为同一排版启发式阶梯，拆散反失上下文
    lines: list[Any], width: float
) -> tuple[list[Any], tuple[float, float] | None]:
    """双栏检测 → (重排行，中缝带 (gl,gr) | None)。

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
        # 逐 part 投票：merged-row（同基线左右栏聚行）左/右 part 各投
        # 自栏幅面——真缝在它们之间零票当选；仅整带横跨的单 part
        # （真通栏标题 run）弃票（对所有 x 等权会顶过阈误杀真缝）。
        # 旧路按行 bbox 弃票把 merged-row 全部弃权 → 缝区零票、
        # best_x 钉在带缘 → MIN_SIDE 假阴性 → 整页栏文交错。
        return sum(
            1
            for ln in lines
            if any(
                px <= x <= px + pw and not (px < lo and px + pw > hi)
                for px, _t, pw in ln[1]
            )
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
    # 采样量化修正：探针撞 >thr 停步时缝缘真值落在相邻两样本之间，
    # 各侧外扩半步取中点估计——3pt 采样把 ~12pt 物理缝量成 9pt 会
    # 假阴性丢整页栏序（t_f748 en p13：带内 0 穿线两侧 45+ 实证）；
    # 探针撞 lo/hi 扫描界的方向不外扩（真界未知，保守不加）。
    gw = gr - gl
    if gl - 3 > lo:
        gw += 1.5
    if gr + 3 < hi:
        gw += 1.5
    if gw < _GUTTER_MIN_W:
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


def _char_stream(
    path: Path, *, collect_marks: bool = False
) -> tuple[
    str, list[tuple[int, int, float, float, float]], dict[int, list[dict[str, Any]]]
]:
    """PDF → (归一字符流，行界 [(char_off,page,frac,x,x1)], marks)。

    双遍架构（pymupdf 可用时）——文本面与标记面各取最强解码器：

    - 文本/行界走 pymupdf ``get_text("dict")``：CMap 回退链完整，无
      ToUnicode 的 CJK 字体也能出真码点（pypdf ``visitor_text`` 同档
      PDF 全错码点——zh 文本匹配整侧瘫死实证）。span 基线原点
      ``origin`` 翻转成底向上 y，run 元组与 pypdf 时代同形，下游
      ``_cluster_lines``/``_reading_order``/``_est_w`` 全不感
      知。行界 x/x1=段左右缘页宽分位（栏判定/阅读序键/宽行 snap
      原料）；跨缝多 part 行已在 ``_reading_order`` 拆成独立流段。
      pymupdf 是 AGPL 可选件（不入 wheel 依赖面）——缺席/开启失败
      回落 ``_char_stream_pypdf`` 单遍老路。

    - ``collect_marks`` 时第二遍走 pypdf ``visitor_operand_before``
      只读 TLXC 标记（``BDC /MCID=50000+seq``）——MCID/BDC 栈语义
      pymupdf 高层 API 不透出，pypdf 是唯一来源。occurrence 记
      page/fraction/x/chars + 标内 run 几何表；hyperref/TOC 重放
      产生同 MCID 双 BDC，全量收下由下游校验择优。BDC/EMC 配对用
      栈：嵌套/外来/无 MCID 的 BDC 压 None 占位，EMC 弹栈，归属=
      栈顶向下最近非 None 项。锚位取标内首个 text run 的 (x,y)——
      vob 里的 tm 是上一个文本对象的陈旧矩阵（全部标记偏高 ~1 行、
      栏首偏 82% 页高实证）；fraction 口径与行界统一 1-(y+asc)/h
      （行顶非基线——floor 语义下基线锚会把行首点击漏给上一条
      seq）。chars 是标内真字形数，供孤儿判定：页断处 BDC 只裹
      1~2 字形沉底、正文被推走。

    - occurrence 的 ``text`` 不由 pypdf 供给（zh 乱码会废掉
      ``_text_cov`` 校验）——收尾按标内 run 的 (页，frac 带，x 幅面)
      在归一流里取行界切片几何回填：行界落在标 y 带内且 x 交叠即
      认作标裹行。pymupdf 真文本下 zh mark 校验复活；回收为空时
      occurrence 校验自然不通过、落 needle 路（语义诚实降级）。
    """
    try:
        import pymupdf  # noqa: F401, PLC0415 -- AGPL 可选件探测
    except ImportError:
        pass
    else:
        try:
            stream, bounds, dims = _text_layer(path)
        except Exception as exc:  # noqa: BLE001 -- pymupdf 坏档不拖全链
            log.warning(
                "seqpos: %s pymupdf 文本面失败(%s)——回落 pypdf 单遍",
                path.name,
                exc,
            )
        else:
            marks = _marks_layer(path, dims) if collect_marks else {}
            if marks:
                _mark_text_geom(marks, stream, bounds, dims)
            return stream, bounds, marks
    return _char_stream_pypdf(path, collect_marks=collect_marks)


def _char_stream_pypdf(  # noqa: C901, PLR0915 -- 页循环 + 双 visitor 平铺是抽取语义本体
    path: Path, *, collect_marks: bool = False
) -> tuple[
    str, list[tuple[int, int, float, float, float]], dict[int, list[dict[str, Any]]]
]:
    """Pypdf 单遍老路（pymupdf 缺席兜底）——文本/行界/标记同一遍抽取。

    ``visitor_text`` 的 tm 是局部矩阵——绝对位须复合 cm：
    ``x=tm4*cm0+tm5*cm2+cm4, y=tm4*cm1+tm5*cm3+cm5``（底向上）。
    无 ToUnicode 的 CJK 字体出乱码码点——zh 文本匹配死路，下游
    ``zh_dead`` 判据兜底。标记 occurrence 的 ``text`` 直接收 vt
    run 文本（en 正常、zh 乱码由 dead 判定豁免 cov 校验）。
    """
    from pypdf import PdfReader  # noqa: PLC0415 -- 与 align.py 同例懒载

    reader = PdfReader(str(path))
    chars: list[str] = []
    bounds: list[tuple[int, int, float, float, float]] = []
    marks: dict[int, list[dict[str, Any]]] = {}
    mstack: list[dict[str, Any] | None] = []
    char_off = 0
    for pi, page in enumerate(reader.pages):
        runs: list[tuple[float, float, float, str, float | None]] = []
        height = float(page.mediabox.height)
        width = float(page.mediabox.width)
        mstack.clear()

        def vt(
            text: str,
            cm: list[float],
            tm: list[float],
            font: object,  # noqa: ARG001 -- 签名由 pypdf 定死
            size: float,
            _runs: list[tuple[float, float, float, str, float | None]] = runs,
            _st: list[dict[str, Any] | None] = mstack,
            _h: float = height,
            _w: float = width,
        ) -> None:
            if not text.strip():
                return
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            _runs.append((y, x, float(size or 10.0), text, None))
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
                    round(ln[3] / width, 5),
                )
            )
            chars.append(nc)
            char_off += len(nc)
    for occs in marks.values():
        for occ in occs:
            occ["text"] = "".join(occ["text"])
    return "".join(chars), bounds, marks


def _text_layer(  # noqa: C901 -- 页循环 + 行界发射是同一段语义平铺
    path: Path,
) -> tuple[str, list[tuple[int, int, float, float, float]], list[tuple[float, float]]]:
    """Pymupdf ``dict`` 抽取 → (流，行界，各页 (w,h))——真 unicode 文本面。

    span ``origin`` 是顶向下基线起点——y_bu=h-origin.y 与旧 pypdf
    tm·cm 复合口径同义；x 取 span bbox 左缘。行聚类/阅读序件全复用。
    """
    import pymupdf  # noqa: PLC0415 -- 与 pypdf 同例懒载

    doc = pymupdf.open(str(path))
    chars: list[str] = []
    bounds: list[tuple[int, int, float, float, float]] = []
    dims: list[tuple[float, float]] = []
    char_off = 0
    for pi in range(doc.page_count):
        page = doc[pi]
        width = float(page.rect.width) or 1.0
        height = float(page.rect.height) or 1.0
        dims.append((width, height))
        runs: list[tuple[float, float, float, str, float | None]] = []
        try:
            dd = page.get_text("dict")
        except Exception as exc:  # noqa: BLE001 -- 单页坏不拖全文档
            log.debug("seqpos: %s p%d pymupdf dict failed: %s", path.name, pi + 1, exc)
            continue
        for blk in dd["blocks"]:
            if blk.get("type") != 0:
                continue
            for ln in blk["lines"]:
                for sp in ln["spans"]:
                    t = sp["text"]
                    if not t.strip():
                        continue
                    org = sp.get("origin")
                    if org is not None:
                        y_bu = height - float(org[1])
                        x = float(org[0])
                    else:  # 防御：origin 缺席退 bbox 左下角
                        bb = sp["bbox"]
                        y_bu = height - float(bb[3])
                        x = float(bb[0])
                    bb = sp["bbox"]
                    real_w = float(bb[2]) - float(bb[0])
                    runs.append((y_bu, x, float(sp["size"] or 10.0), t, real_w))
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
                    round(ln[3] / width, 5),
                )
            )
            chars.append(nc)
            char_off += len(nc)
    return "".join(chars), bounds, dims


def _marks_layer(  # noqa: C901 -- 双 visitor 闭包 + 栈平铺是标记语义本体
    path: Path, dims: list[tuple[float, float]]
) -> dict[int, list[dict[str, Any]]]:
    """Pypdf ``visitor_operand_before`` 只读 BDC/EMC 栈 → seq→occurrence。

    occurrence: ``{page, fraction, x, chars, runs[(y,x,sz,w)]}``——
    runs 是标内 text run 几何（文本面由 ``_mark_text_geom`` 回填）。
    """
    from pypdf import PdfReader  # noqa: PLC0415 -- 与 align.py 同例懒载

    reader = PdfReader(str(path))
    marks: dict[int, list[dict[str, Any]]] = {}
    mstack: list[dict[str, Any] | None] = []
    for pi, page in enumerate(reader.pages):
        width, height = (
            dims[pi]
            if pi < len(dims)
            else (
                float(page.mediabox.width),
                float(page.mediabox.height),
            )
        )
        mstack.clear()

        def vt(
            text: str,
            cm: list[float],
            tm: list[float],
            font: object,  # noqa: ARG001 -- 签名由 pypdf 定死
            size: float,
            _st: list[dict[str, Any] | None] = mstack,
            _h: float = height,
            _w: float = width,
        ) -> None:
            if not text.strip():
                return
            occ = next((e for e in reversed(_st) if e is not None), None)
            if occ is None:
                return
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            t = text.strip()
            sz = float(size or 10.0)
            occ["runs"].append((y, x, sz, _est_w(t, sz)))
            occ["chars"] += len(t)
            if occ["fraction"] is None:
                occ["fraction"] = round(1 - (y + _ASC * sz) / _h, 5)
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
                "runs": [],
                "chars": 0,
            }
            _marks.setdefault(seq, []).append(occ)
            _st.append(occ)

        try:
            page.extract_text(visitor_text=vt, visitor_operand_before=vob)
        except Exception as exc:  # noqa: BLE001 -- 单页坏不拖全文档
            log.debug("seqpos: %s p%d extract_text failed: %s", path.name, pi + 1, exc)
            continue
    return marks


#: mark 几何回填的 frac 带 / x 幅面容差（行界行顶 vs 标基线带的落差）
_MARK_FTOL = 0.008
_MARK_XTOL_PT = 6.0


def _mark_text_geom(
    marks: dict[int, list[dict[str, Any]]],
    stream: str,
    bounds: list[tuple[int, int, float, float, float]],
    dims: list[tuple[float, float]],
) -> None:
    """标内文本几何回填——occurrence run 的 (页，frac 带，x 幅面) 取行界流切片。

    pypdf 侧 zh 标内文本是错码点垃圾——真实 unicode 只能从 pymupdf
    文本面取。标的 y 覆盖带 = run 行顶带 [1-(y+asc·sz)/h 最小，
    1-(y-desc·sz)/h 最大]；x 覆盖带 = [min run x, max run x+ 估宽]。
    行界 frac 落带内且 [x0,x1] 与标 x 带交叠 → 该行流切片计入标内
    文本。错栏防串：标 x 带在左栏时右栏行 x0 超出 xmax 自然排出。
    """
    by_page: dict[int, list[int]] = {}
    for i, b in enumerate(bounds):
        by_page.setdefault(b[1], []).append(i)
    for occs in marks.values():
        for occ in occs:
            runs = occ.pop("runs", None) or []
            text_parts: list[str] = []
            if runs and occ["fraction"] is not None and occ["page"] <= len(dims):
                w, h = dims[occ["page"] - 1]
                f_lo = min(1 - (y + _ASC * sz) / h for y, _x, sz, _wd in runs)
                f_hi = max(1 - (y - 0.25 * sz) / h for y, _x, sz, _wd in runs)
                x_lo = min(x for _y, x, _sz, _wd in runs)
                x_hi = max(x + wd for _y, x, _sz, wd in runs)
                for bi in by_page.get(occ["page"], []):
                    off, _pg, fr, x0, x1 = bounds[bi]
                    if not (f_lo - _MARK_FTOL <= fr <= f_hi + _MARK_FTOL):
                        continue
                    if x1 * w < x_lo - _MARK_XTOL_PT or x0 * w > x_hi + _MARK_XTOL_PT:
                        continue
                    end = bounds[bi + 1][0] if bi + 1 < len(bounds) else len(stream)
                    text_parts.append(stream[off:end])
            occ["text"] = "".join(text_parts)


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
