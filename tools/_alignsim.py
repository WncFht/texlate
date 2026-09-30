"""对齐仿真抽取件——pymupdf rawdict 逐字位流单一事实源。

seqpos_verify_mask/mark_bias 原各长一份 rawdict→逐字位表拷贝，本件收
单源。与 ``_seqpos_lib._char_stream``（texlate.server.seqpos 转口）分工：
后者是行界 (char_off, page, frac, x, x1) 契约，供锚位/栏序审计；本件是
逐字 offset→(page,frac) 反查契约——``stream.find(probe)`` 命中位须同
下标取位，行界粒度答不了「针中第 k 字落在哪」。

用法：``for pno, stream, fracs in char_pos_pages(doc): ...``
"""

from _seqpos_lib import _norm_chars


def char_pos_pages(doc) -> list[tuple[int, str, list[float]]]:
    """pymupdf rawdict → [(page1, 归一字符流，逐字 frac)]。

    frac = 字形 bbox 顶/页高，clamp [0, 0.999]——与 seqpos fraction
    顶向下契约同口径（mark_bias 原拷贝未 clamp，两侧 frac 都只做
    近距挑选，clamp 差在页外字形才可见，统一到 seqpos 口径更稳）。
    CMap 归一走 ``_seqpos_lib._norm_chars``。跨页搜索用
    ``char_pos_stream`` 全档平铺，单页搜索按下标取页。
    """
    out = []
    for pno in range(doc.page_count):
        page = doc[pno]
        h = page.rect.height or 1
        chars, pos = [], []
        for blk in page.get_text("rawdict").get("blocks", []):
            for ln in blk.get("lines", []):
                for sp in ln.get("spans", []):
                    for ch in sp.get("chars", []):
                        n = _norm_chars(ch.get("c", ""))
                        if not n:
                            continue
                        chars.extend(n)
                        pos.extend([max(0.0, min(0.999, ch["bbox"][1] / h))] * len(n))
        out.append((pno + 1, "".join(chars), pos))
    return out


def char_pos_stream(doc) -> tuple[str, list[tuple[int, float]]]:
    """全档平铺版——("".join 各页字符流，[(page1, frac)] 逐字）。

    seqpos_verify_mask.locate_off 契约：``stream.find(probe)`` 的
    offset 直接索引位表拿 (page1, frac)。跨页缝处的假命中与旧拷贝
    同规（针 ≤30 字、命中位翻页即偏 1 页内，骨架窗校验容忍）。
    """
    s, p = [], []
    for pno, st, fr in char_pos_pages(doc):
        s.append(st)
        p.extend((pno, f) for f in fr)
    return "".join(s), p
