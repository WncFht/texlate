"""specs._layoutqc.textcheck — pdftotext 纯文本叶 (_layoutqc 拆分叶).

残留英文两级档 (家具剔除 + refs 尾截 + tex/verbatim 回查) + 退化
兜底 (FFFD/n-gram/空页/行内周期占位) + 断链 ?? + 骨架 LCS 件。
"""

from __future__ import annotations

import re
from collections import Counter

from specs import _bootstrap

_bootstrap.ensure()

from specs._layoutqc.pagekit import _struct_head, _verso_blank
from specs._layoutqc.thresh import (
    _ASCII_LINE_RX,
    _BIB_AY_RX,
    _BIB_CORRO_RX,
    _BIB_ID_RX,
    _BIB_LINE_RX,
    _BIB_MARK_RX,
    _BIB_NUM_RX,
    _BIB_TAGNUM_RX,
    _BROKEN_BRK_RX,
    _BROKEN_REF_RX,
    _CJK_RX,
    _DIGIT_RX,
    _FOLIO_RX,
    _NORM_RX,
    _PERIODIC_RX,
    _REFS_HEAD_RX,
    _SKELETON_RX,
    _WORD_CHAR_RX,
    BROKEN_REFS_MIN,
    DEGEN_FFFD_FUSE,
    DEGEN_NGRAM,
    DEGEN_NGRAM_MAX,
    DEGEN_PERIODIC_MIN_LINES,
    EMPTY_PAGE_CHARS,
    EMPTY_PAGE_MAX,
    RESIDUAL_EN_FURNITURE,
    RESIDUAL_EN_HEAVY_FRAC,
    RESIDUAL_EN_MASS_LINES,
    RESIDUAL_EN_MIN_FRAC,
    RESIDUAL_EN_MIN_LINES,
)
from texlate.textutil import _keep_verbatim_run


def _refs_cut(lines: list[str]) -> int:
    """参考文献区起始行：尾部 bib marker 稠密簇定位 + 锚定校验。

    marker 三族：``[N]``/``[S1]``/``[Auth19]`` 括形（自证）；``N.``/``N)``/
    裸 ``N`` 数字形（须同行 DOI|arXiv|et al.|(19|20)\\d\\d 佐证，防正文枚举
    误锚）；``et al.``/``(2019)``/``Smith, J.`` 作者年形（无数字锚用）。

    簇锚定：从最后 marker 倒序连回，相邻行距 >80 或数字回跳（前一标号
    比后一标号大 >2——双栏交错 ±1/±2 抖动容忍）即截断。锚条件：簇内含
    标号 1、或尾部 ≥3 数字标号严格递增、或（全簇无数字标号时）≥3 条
    author-year 行——正文密引伪簇（高标号无锚）被拒。

    判据：簇 marker 行 bib-ASCII 占比 ≥50%，或簇区 DOI/arXiv/ISBN 行密度
    ≥0.3（独立证据）。无命中返 len(lines)。"""
    marks: list[tuple[int, int | None, str]] = []
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        m = _BIB_MARK_RX.match(ln)
        if m:
            marks.append((i, int(_BIB_TAGNUM_RX.search(m.group(1)).group()), "brk"))
            continue
        m = _BIB_NUM_RX.match(ln)
        if m and _BIB_CORRO_RX.search(ln):
            marks.append((i, int(m.group(1)), "num"))
            continue
        if _BIB_AY_RX.search(ln):
            marks.append((i, None, "ay"))
    if len(marks) < 3:
        return len(lines)
    start = len(marks) - 1
    trunc_by_drop = False
    for k in range(len(marks) - 2, -1, -1):
        if marks[k + 1][0] - marks[k][0] > 80:
            break
        nk, nk1 = marks[k][1], marks[k + 1][1]
        if nk is not None and nk1 is not None and nk > nk1 + 2:
            trunc_by_drop = True
            break  # 正文 [N] 引用倒灌截断
        start = k
    cluster = marks[start:]
    if len(cluster) < 3:
        return len(lines)
    nums = [n for _, n, _ in cluster if n is not None]
    ays = sum(1 for *_, k in cluster if k == "ay")
    tail = nums[-3:]
    anchored = (
        any(n == 1 for n in nums)
        or (len(nums) >= 3 and len(tail) == 3 and tail[0] < tail[1] < tail[2])
        or (not nums and ays >= 3)
    )
    if anchored:
        ok = _bib_cluster_cut(lines, cluster)
        # numdrop 截断的簇可能把 cut 落在 bib 中段（双栏交错编号回跳
        # >2 顶破截断但幸存尾段仍严格递增 + 稠密——0928 实证两格漏切
        # 870/1387 起 bib 只切到 1114/1796）。改用纯行距回连扩簇，
        # 扩展簇仍过判据则取更深的 cut。
        if ok is not None and trunc_by_drop:
            ext = _tail_bib_cluster(lines, marks)
            if ext is not None:
                ok_ext = _bib_cluster_cut(lines, ext)
                if ok_ext is not None and ok_ext < ok:
                    return ok_ext
        return ok if ok is not None else len(lines)
    # 锚失败兜底（无 heading 稿 + 双栏交错把编号单调性顶破——
    # numdrop 截断导致 [1] 落簇外/尾段非严格递增，bib 客观在
    # 而 cut=len 全量计入正文域，0928 residual_en FP 三格实证）：
    # (a) 尾段稠密回扫——末 marker 在文末 ~15 非空行内即 bib 真在
    #     尾，只按行距 >80 截断回连（不做 numdrop）；
    # (b) 前向锚——首个标号 1 marker 后 30 行内再现 ≥2 marker 即
    #     bib 起点（正文 [1] 引用伪锚由簇区密度判据拒）。
    for cand in (_tail_bib_cluster(lines, marks), _fwd_anchor_cluster(marks)):
        if cand is None:
            continue
        ok = _bib_cluster_cut(lines, cand)
        if ok is not None:
            return ok
    return len(lines)


def _bib_cluster_cut(lines: list[str], cluster: list[tuple]) -> int | None:
    """簇区判据共享出口：marker 行 bib-ASCII 占比 ≥50% 或簇区
    DOI/arXiv/ISBN 行密度 ≥0.3 → 返 cut，否则 None。"""
    cut = cluster[0][0]
    mark_lines = [lines[i].strip() for i, _, _ in cluster]
    ascii_frac = sum(1 for ln in mark_lines if _BIB_LINE_RX.match(ln)) / max(
        len(mark_lines), 1
    )
    span = [ln for ln in lines[cut:] if ln.strip()]
    doi_frac = sum(1 for ln in span if _BIB_ID_RX.search(ln)) / max(len(span), 1)
    return cut if ascii_frac >= 0.5 or doi_frac >= 0.3 else None


def _tail_bib_cluster(lines: list[str], marks: list[tuple]) -> list[tuple] | None:
    """尾段稠密兜底簇：末 marker 须在文末 ~15 非空行内（bib 真在尾段），
    仅行距 >80 截断回连——双栏交错下编号回跳是常态，numdrop 不可用。"""
    last_nonempty = max((i for i, ln in enumerate(lines) if ln.strip()), default=-1)
    if last_nonempty - marks[-1][0] > 15:
        return None
    start = len(marks) - 1
    for k in range(len(marks) - 2, -1, -1):
        if marks[k + 1][0] - marks[k][0] > 80:
            break
        start = k
    cluster = marks[start:]
    return cluster if len(cluster) >= 3 else None


def _fwd_anchor_cluster(marks: list[tuple]) -> list[tuple] | None:
    """前向锚兜底簇：首个标号 1 的 brk/num marker，后 30 行内再现
    ≥2 marker 即候选 bib 起点。"""
    for j, (i, n, kind) in enumerate(marks):
        if n != 1 or kind not in ("brk", "num"):
            continue
        near = sum(1 for ii, _, _ in marks[j + 1 :] if ii - i <= 30)
        if near >= 2:
            return marks[j:]
        return None
    return None


def _plain_scan(
    text: str,
    base_text: str | None = None,
    *,
    zh_log: str | None = None,
    tex_hay: str | None = None,
    verb_hay: str | None = None,
    tex_fffd: bool = False,
    twoside: bool = False,
    blankpage_marker: bool = False,
    doc_title: str | None = None,
) -> tuple[list[dict], dict]:
    """pdftotext 纯文本层：退化兜底（olmOCR 系）+ 残留英文两级档
    （furniture 剔除后 frac≥RESIDUAL_EN_HEAVY_FRAC 升 heavy 档）。

    ``base_text``=en 对照臂全文（缺失→全部跨臂豁免退化单侧口径）；
    ``zh_log``=zh 编译日志（FFFD 臂的 Missing-character 佐证）；
    ``tex_hay``/``verb_hay``=splice tex 全文/verbatim 段内容的
    ``_NORM_RX`` 归一化 blob——残英行回查用；``tex_fffd``=splice
    tex 含字面 U+FFFD 字节（FFFD 臂的二号佐证：log 零 missing 时
    抽取 FFFD 全是嵌入图 ToUnicode 伪影，tex 字面量才是编译进
    PDF 的真豆腐）；``twoside``/``blankpage_marker`` 供 verso
    空页豁免（folio 奇偶/frontmatter 标记臂）；``doc_title``=
    splice ``\\title`` 参数 squash 串（标题页 verso 佐证）。"""
    findings: list[dict] = []
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()  # pdftotext 末页 \f 尾巴
    metrics: dict = {"chars": len(text), "npages_text": len(pages)}
    # 残留英文行：参考文献段本就保持英文——标题行起截断不计，只量
    # 正文域（无标题匹配 = 保守全计）。
    lines = text.splitlines()
    head_cut = next(
        (i for i, ln in enumerate(lines) if _REFS_HEAD_RX.match(ln)), len(lines)
    )
    cut = min(head_cut, _refs_cut(lines))
    body = lines[:cut]
    body_norm = [" ".join(ln.split()) for ln in body]
    # 页眉页脚 furniture——正文域内复现 ≥4 次的行（running head 每页
    # 复现属合法面）不计残英；频数只数 body——把 refs 尾算进来会把
    # 「正文残英 + refs 复现」的真残英行也冲进家具（verify 实证）。
    # 二闸：数字归一键跨 ≥4 个不同页 = 页码/年份变体页眉（2410.00043
    # 逐页异码头逃脱精确匹配的实证）；同页序列号行（编号列）页跨=1
    # 不会误坍成家具。
    freq = Counter(body_norm)
    norm_span: dict[str, set[int]] = {}
    for pi, ptxt in enumerate(pages):
        for ln in ptxt.splitlines():
            norm = _DIGIT_RX.sub("#", " ".join(ln.split()))
            if norm:
                norm_span.setdefault(norm, set()).add(pi)

    def _furniture(ln: str) -> bool:
        return (
            freq[ln] >= RESIDUAL_EN_FURNITURE
            or len(norm_span.get(_DIGIT_RX.sub("#", ln), ())) >= RESIDUAL_EN_FURNITURE
        )

    en_lines = [
        ln
        for ln in body_norm
        if _ASCII_LINE_RX.match(ln) and len(ln.split()) >= 4 and not _furniture(ln)
    ]
    text_lines = [ln for ln in body_norm if ln]
    # 发报口径三级豁免（metric 保留原始行数）：
    # - tex-hay 缺席：图内嵌字/includepdf/cls 套话——splice 只译 tex
    #   面，tex 里查无此行的英文不是译文债（figure_embedded 大头）。
    #   splice 缺失（tex_hay=None）时整层退化现行为。
    # - verbatim 环境回显：行落在 lstlisting/verbatim 原文段。
    # - author-run：署名/机构块的天然英文（_keep_verbatim_run 同口径）。
    en_eff: list[str] = []
    en_unreached = 0
    for ln in en_lines:
        blob = _NORM_RX.sub("", ln.lower())
        if tex_hay is not None and (len(blob) < 4 or blob not in tex_hay):
            en_unreached += 1
            continue
        if verb_hay is not None and len(blob) >= 4 and blob in verb_hay:
            continue
        if _keep_verbatim_run(ln):
            continue
        en_eff.append(ln)
    metrics["en_tail_cut"] = cut if cut < len(lines) else None
    metrics["residual_en_lines"] = len(en_lines)
    metrics["residual_en_eff"] = len(en_eff)
    metrics["en_unreached_lines"] = en_unreached
    frac = len(en_eff) / max(len(text_lines), 1)
    if len(en_eff) >= RESIDUAL_EN_MASS_LINES or (
        len(en_eff) >= RESIDUAL_EN_MIN_LINES and frac >= RESIDUAL_EN_MIN_FRAC
    ):
        findings.append(
            {
                "sig": (
                    "xlat_residual_en_heavy"
                    if frac >= RESIDUAL_EN_HEAVY_FRAC
                    else "xlat_residual_en"
                ),
                "lines": len(en_eff),
                "frac": round(frac, 3),
            }
        )
    # 退化：FFFD / 重复 n-gram / 空页——三臂跨 base 对拍（嵌入图
    # ToUnicode 缺口的 FFFD、running head n-gram、verso 白页在 en
    # 原件同形复现，差净才算 splice 产物）。
    fffd = text.count("\ufffd")
    fffd_net = fffd - (base_text.count("\ufffd") if base_text is not None else 0)
    # n-gram 同吃 refs 截断（ACM 版权块逐条参考文献重复是合法面）；
    # 非字母 token 剔除——矢量图散点 marker（1706.02386 298×●）、
    # 零矩阵/数据表数字连珠（2603.07101 75×"0"）都不是文本退化。
    toks = [t for t in " ".join(body).split() if _WORD_CHAR_RX.search(t)]
    ngrams = Counter(
        tuple(toks[i : i + DEGEN_NGRAM]) for i in range(len(toks) - DEGEN_NGRAM + 1)
    )
    base_empty = None
    if base_text is not None:
        btoks = [t for t in base_text.split() if _WORD_CHAR_RX.search(t)]
        ngrams -= Counter(
            tuple(btoks[i : i + DEGEN_NGRAM])
            for i in range(len(btoks) - DEGEN_NGRAM + 1)
        )
        bpages = base_text.split("\f")
        if bpages and not bpages[-1].strip():
            bpages.pop()
        base_empty = sum(1 for p in bpages if len(p.strip()) < EMPTY_PAGE_CHARS)
    # 获胜 n-gram 须含 ≥1 CJK token——Mandelstam 变量表/量子门记号/
    # CC 页脚的纯非 CJK 周期重复是合法内容（vis_degenerate 簇 0928
    # 裁定：10/10 触发格全是非 CJK，1404.0028 rep=183 实证）。
    top_rep = max(
        (c for g, c in ngrams.items() if any(_CJK_RX.search(t) for t in g)),
        default=0,
    )
    top_rep_all = max(ngrams.values(), default=0)
    # verso/分隔白页豁免三臂：页自带 folio 偶数/frontmatter+ 标记
    # （_verso_blank）；空页的下一非空页首行命中结构性标题
    # （Chapter/第 N 章/参考文献…）即章前隔页——openright/frontmatter
    # 常态排版非缺陷。
    empty_idx = [i for i, p in enumerate(pages) if len(p.strip()) < EMPTY_PAGE_CHARS]

    def _verso(pi: int) -> bool:
        if _verso_blank(pi, pages[pi], twoside, blankpage_marker):
            return True
        if pi == 1 and pages[0].strip():
            return True  # 扉页后 verso——frontmatter 常态空背
        for j in range(pi + 1, len(pages)):
            if pages[j].strip():
                head = next(
                    (
                        ln
                        for ln in pages[j].splitlines()
                        if ln.strip() and not _FOLIO_RX.match(ln)
                    ),
                    "",
                )
                return _struct_head(head, doc_title)
        return False

    empty_eff = [i for i in empty_idx if not _verso(i)]
    # 行内周期占位行数——CJK mock 译文整行无空格，词级 n-gram
    # 只反映局部重复（running head 放阈连它一起放走）；行内
    # 连珠才是真占位签名——页眉每页复现也不产生行内连珠。
    # 发射口径=CJK 周期单元行数（_CJK_RX 命中重复单元本身——图区
    # 刻度/CD 标签/括号 stretch 的非 CJK 连珠不点火）。
    periodic = sum(
        1
        for ln in body
        if any(_WORD_CHAR_RX.search(m.group(1)) for m in _PERIODIC_RX.finditer(ln))
    )
    periodic_cjk = sum(
        1
        for ln in body
        if any(
            _WORD_CHAR_RX.search(m.group(1)) and _CJK_RX.search(m.group(1))
            for m in _PERIODIC_RX.finditer(ln)
        )
    )
    metrics.update(
        {
            "fffd": fffd,
            "fffd_net": fffd_net,
            "top_ngram_rep": top_rep,
            "top_ngram_rep_all": top_rep_all,
            "empty_pages": len(empty_idx),
            "empty_pages_eff": len(empty_eff),
            "degen_periodic_lines": periodic,
            "degen_periodic_cjk": periodic_cjk,
        }
    )
    if base_empty is not None:
        metrics["empty_pages_base"] = base_empty
    # running head 每页复现标题 ≈ npages 次；真退化环单页就产出
    # 数百次——阈值按页数放。无 base 时再加家具地板 rep≤npages 免
    # （每页一次即家具），有 base 由差集承担。
    ngram_cap = max(3 * len(pages), DEGEN_NGRAM_MAX)
    ngram_fire = top_rep > ngram_cap and (base_text is not None or top_rep > len(pages))
    # FFFD 臂（verify 0928 裁定）：log 在档时 missing>0 一律照发
    # ——net≤2 的真缺字格实证存在（人名/数学 drop），而 missing==0
    # 时抽取 FFFD 全是嵌入图 ToUnicode 缺口/空格形/零宽 glyph 伪影
    # （net 438 亦伪影），仅 tex 含字面 FFFD 字节才发。log 缺席
    # 退回旧保险丝：net≥3 或 tex 字面量佐证。
    if zh_log is None:
        fffd_fire = fffd_net >= DEGEN_FFFD_FUSE or (tex_fffd and fffd_net > 0)
    else:
        missing = len(re.findall(r"Missing character", zh_log))
        metrics["missing_chars"] = missing
        fffd_fire = fffd_net > 0 and (missing > 0 or tex_fffd)
    empty_fire = (
        (len(empty_eff) - base_empty) if base_empty is not None else len(empty_eff)
    ) > EMPTY_PAGE_MAX
    if (
        fffd_fire
        or ngram_fire
        or empty_fire
        or periodic_cjk >= DEGEN_PERIODIC_MIN_LINES
    ):
        findings.append(
            {
                "sig": "vis_degenerate",
                "fffd": fffd,
                "fffd_net": fffd_net,
                "top_ngram_rep": top_rep,
                "empty_pages": len(empty_eff),
                "periodic_lines": periodic_cjk,
            }
        )
    # 断链引用：未解析 \cite/\ref 渲成 ?? run——编译 pass 不全的
    # 产物级签名（2505.21476 正文 646 个 ?? 字符实证）；中文全角
    # ？？天然不匹配，修辞性 ??/??? 够不到位点阈。裸 ?? 与括号形
    # 分别记账——跨臂/log 佐证降权在 qc_paper 收口（_plain_scan
    # 纯文本面保持原子口径）。
    broken = len(_BROKEN_REF_RX.findall(text))
    metrics["broken_refs"] = broken
    metrics["broken_refs_brk"] = len(_BROKEN_BRK_RX.findall(text))
    if broken >= BROKEN_REFS_MIN:
        findings.append({"sig": "xlat_broken_refs", "n": broken})
    return findings, metrics


def _skeleton(text: str) -> list[str]:
    """翻不动的骨架 token 流（数字/引用/arXiv/URL）——页序对拍用。"""
    return _SKELETON_RX.findall(text)


def _lcs(a: list[str], b: list[str]) -> int:
    """经典 LCS 长度（骨架流 ≤ 数千，O(nm) 可接受）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[-1]))
        prev = cur
    return prev[-1]
