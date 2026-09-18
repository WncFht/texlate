r"""批量协议（docs/08 §1.3 + batchmodel-2026-09-18 修订）：全量入批 + K 量化等大装箱 + `[n]` 编号 + `@@` 兜底 + 整批退单翻。

- 分桶：**取消 short/long 分桶，全量入批**——产线 129K chunk 对账：批成员
  per-placeholder 错率 0.32% vs 单发 8.93%，批质量全面 ≥ 单发；34% 单发
  chunk 占 89% 请求数纯烧 ~2.9s/发 的固定开销。
- 装箱：顺序等大填充——``n_req`` 由 ``cap`` 下限与 ``workers`` 并行填充
  共同决定，>workers 时向上取 workers 整数倍（K 量化，不留半空波次），
  批目标大小 ``total/n_req``。字符硬顶 12000（实测 [n] 协议 19K/53 条
  干净解析；12K 字符 ≈ 4.2K 输出 token，8192 max_tokens 留足 reasoning
  余量），条数软顶 32（只为整批退单翻的爆炸半径兜底，非协议需要）。
- 协议：请求 `[1] xxx\n[2] yyy`；响应按行首锚定 `[n]` 解析，`@@` 独占行
  分隔兜底；数量不符/序号越界/解析歧义 → `None`，调用方整批退化逐条单翻。
- 跳过：纯占位符 chunk（`placeholders.is_placeholder_only`）不发请求。
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, TypeVar

from .placeholders import EOL_RX, encode_newlines

if TYPE_CHECKING:
    from collections.abc import Sequence

#: 单批 payload 硬顶（含 `[n] ` 编号开销；12K 字符 ≈ 4.2K 输出 token——
#: out_tok/字符产线 p90=0.348，max_tokens=8192 下 reasoning+content 留足余量；
#: 再大逼近上限且 decode 主导下对 makespan 无补，见 batchmodel-2026-09-18 §8/9）
BATCH_MAX_CHARS = 12000
#: 单批成员软顶——`[n]` 协议对条数不敏感（实测 53 条干净解析、产线 40+ 条
#: 全过），此值只为整批退单翻的爆炸半径兜底
BATCH_MAX_ITEMS = 32
#: 每批有效负载下限——低于此拆批不如少发：单请求 ~2.9s 固定开销与平行
#: decode 收益的盈亏平衡点量级（D/批 ≈ 5.3ms×字符，拆批省 decode 须 >2.9s）
BATCH_MIN_CHARS = 2500
#: `[n] ` 编号开销估计（用于装箱容量计算）
BATCH_ITEM_OVERHEAD = 8
#: 超大原子 chunk 的切分阈值（> 此值先切分再入批/单翻）
CHUNK_HARD_LIMIT = 6000

T = TypeVar("T")

#: 响应解析主协议：`[n]` 序号节——只认行首锚定（译文里 `[12]` 引用号遍地
#: 都是，行内 `[k]` 与协议序号在 token 层不可区分，非锚定切分是错配面）。
_NUM_LINE_RX = re.compile(r"^\s*\[(\d+)\]", re.MULTILINE)
#: `@@` 兜底分隔（独占一行的 @@；模型不按编号时 spec 允许此退路）
_ATAT_LINE_RX = re.compile(r"^\s*@@\s*$", re.MULTILINE)
#: 单行 `@@` 判定——编号段内协议残码剥除用
_ATAT_ONLY_RX = re.compile(r"\s*@@\s*")
#: `@@` 段的空槽判定：裸 `[n]` 序号桩 = 实质空译——同
#: export.common.STUB_ONLY_RE 语义（xlat 不反向依赖 export，正则不贵）。
_STUB_ONLY_RX = re.compile(r"\s*(?:\[\d+\]\s*)+")
#: `@@` 段内的协议序号泄漏闸：非嵌套 `[k]`——`[[k]]` 双括号属占位符族字面、
#: 不吃内层（`[k]` k∉{1..n} 不可能是序号分隔符，按引用号内容放行，见
#: parse_batch_response 安全侧裁定）。
_LEAKED_MARK_RX = re.compile(r"(?<!\[)\[(\d+)\](?!\])")
#: 响应侧行界归一——单源在 ``placeholders.EOL_RX``（decode_newlines 自带
#: 此步；批解析幂等复跑，口径同 anchor 行界全形态）。
_EOL_RX = EOL_RX  # 单源在 placeholders.EOL_RX——decode_newlines 自带归一，批解析幂等复跑


def pack_batches(  # noqa: PLR0913 -- 装箱旋钮面即 PipelineConfig.batch_* 四件 + workers
    contents: Sequence[str],
    *,
    max_chars: int = BATCH_MAX_CHARS,
    max_items: int = BATCH_MAX_ITEMS,
    min_chars: int = BATCH_MIN_CHARS,
    item_overhead: int = BATCH_ITEM_OVERHEAD,
    workers: int = 1,
) -> list[list[int]]:
    r"""顺序等大装箱 + K 量化波次对齐 → 每批是 contents 的下标列表（保持原序）。

    目标批数 ``n_req`` 取三者最大：``ceil(total/max_chars)``（payload 硬顶）、
    ``min(workers, total//min_chars)``（并行填充——总负载太小不硬凑 K，
    低于 ``min_chars``/批 的拆分发不如少发）；``n_req > workers`` 时向上取
    workers 整数倍（K 量化——13 请求在 K=10 上留 3-worker 半空波次，
    取 20 反而每批更小、波次整齐）。随后按 ``target = total/n_req`` 顺序
    等大填充；``max_chars``/``max_items`` 是硬顶，任何时候都可提前封批
    （等大只是目标，硬顶优先）。单成员超 ``max_chars`` 的原子块不拆——
    独占一批原样放行（>hard_limit 的上游已切分，此处纯防御）。
    """
    lens = [len(t) + item_overhead for t in contents]
    if not lens:
        return []
    total = sum(lens)
    n_req = max(
        math.ceil(total / max(max_chars, 1)),
        min(max(workers, 1), max(1, total // max(min_chars, 1))),
    )
    n_req = min(n_req, len(lens))
    w = max(workers, 1)
    if n_req > w:
        n_req = min(math.ceil(n_req / w) * w, len(lens))
    target = total / n_req
    batches: list[list[int]] = []
    cur: list[int] = []
    cur_len = 0
    for i, need in enumerate(lens):
        if cur and (
            cur_len + need > max_chars
            or len(cur) >= max_items
            or (cur_len + need > target and len(batches) < n_req - 1)
        ):
            batches.append(cur)
            cur, cur_len = [], 0
        cur.append(i)
        cur_len += need
    if cur:
        batches.append(cur)
    return batches


def encode_batch(contents: Sequence[str]) -> str:
    r"""`[1] xxx\n[2] yyy`——内容先经 `encode_newlines` 换行编码。"""
    lines = []
    for i, text in enumerate(contents, 1):
        encoded, _counts = encode_newlines(text)
        lines.append(f"[{i}] {encoded}")
    return "\n".join(lines)


def _parse_numbered(text: str, n: int, rx: re.Pattern[str]) -> list[str] | None:
    """按 ``rx`` 标号切：序号多重集须恰为 {1..n}（乱序归位），段段非空。

    段内 ``@@`` 独占行按协议残码剥除——``@@`` 是 spec 兜底分隔符而非译文
    内容，编号响应里混入的 ``@@`` 行保留原文即字面泄漏进 PDF；剥除后段空
    视同空段，整批拒收。
    """
    matches = list(rx.finditer(text))
    if not matches:
        return None
    idxs = [int(m.group(1)) for m in matches]
    if sorted(idxs) != list(range(1, n + 1)):
        return None
    out = [""] * n
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        seg = text[m.end() : end]
        seg = "\n".join(ln for ln in seg.split("\n") if not _ATAT_ONLY_RX.fullmatch(ln))
        out[int(m.group(1)) - 1] = seg.strip()
    return out if all(out) else None


def parse_batch_response(text: str, n: int) -> list[str] | None:
    """解析批量响应为 n 段译文；失败返回 `None`（调用方整批退单翻）。

    主协议 `[n]`：只认行首锚定匹配（行内 `[12]` 引用号天然免疫）；编号
    缺席时 `@@` 独占行兜底切分。

    安全侧裁定——歧义一律 `None` 退单翻（烧调用），绝不静默错配/泄漏：

    - 行内 `[k]` 不做编号解析：协议序号与正文引用号在 token 层不可区分
      （`[1] 结果如文献 [2] 所示` 中 `[2]` 恰好凑齐多重集时，引用残段会
      被静默配给成员 2 落进 PDF）。单行全挤/行内混编响应整体拒收。
    - `@@` 段内出现非嵌套 `[k]`（1≤k≤n）按序号泄漏判歧义拒收——剥掉会
      腐蚀真实引用号、保留则协议标记原文进译文，两头都不可接受；
      `[0]`/`[k]`（k>n）/`[[k]]` 非序号形态，按内容字面放行。
    """
    text = _EOL_RX.sub("\n", text).strip()
    if not text or n <= 0:
        return None

    out = _parse_numbered(text, n, _NUM_LINE_RX)
    if out is not None:
        return out

    parts = [p.strip() for p in _ATAT_LINE_RX.split(text)]
    # 裸 `[n]` 桩段按空槽丢弃——否则 n=1 时 `[1]` 回显会原样漏成译文
    parts = [p for p in parts if p and not _STUB_ONLY_RX.fullmatch(p)]
    if len(parts) != n:
        return None
    for part in parts:
        if any(1 <= int(m.group(1)) <= n for m in _LEAKED_MARK_RX.finditer(part)):
            return None
    return parts


def split_long_chunk(text: str, *, max_chars: int = CHUNK_HARD_LIMIT) -> list[str]:
    """超大原子 chunk 按句界二分（闭合 scope 边界 + 句号优先、大写开头次优）。

    docs/08 §1.3「超大原子 chunk 先切分再入批」——不切会爆单请求上下文
    （实测 109K/77K 原子块，cost-model §5.3）。返回保持顺序的片段列表。
    """
    if max_chars < 1 or len(text) <= max_chars:
        return [text]  # max_chars<1 时不可切——原样返回胜过死循环
    out: list[str] = []
    rest = text
    while len(rest) > max_chars:
        cut = _best_split(rest, max_chars)
        out.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    if rest:
        out.append(rest)
    return out


#: 切点避让的原子 span：占位符（``[[X_n]]``/``[[SL]]`` 系）与控制字/转义
#: （``\cmd``/``\%``）——切开占位符两半都过不了对账；切开 ``\cmd`` 会在
#: 重组译文里留下 ``\``+CJK 熔合或 ``%`` 起头注释吞行（undefined cs/吞文本）。
#: ``\cmd`` 后随的 ``[opt]``/``{arg}`` 参数组并入同一原子（可叠多组、允许
#: 空白间隔、仅罩非嵌套组——TeX 参数扫描本就跳过组间空白）——cs 名与参数组
#: 切开会让前片悬 ``\cmd`` 收尾、后片孤儿 ``{arg}`` 起头，两半独立送翻都
#: 失去配对结构。嵌套/未闭合组的接缝残余由 ``_safe_cut`` 兜底。
_ATOMIC_CUT_RX = re.compile(
    r"\[\[[A-Z][A-Z_]*\]\]|\[\[[A-Z_]+_\d+\]\]"
    r"|\\[a-zA-Z@]+\*?(?:\s*\[[^\[\]]*\])?(?:\s*\{[^{}]*\})*"
    r"|\\."
)
#: cs 名收尾判定（``_safe_cut`` 复合原子兜底用——组头前窗口 rstrip 后以
#: ``\cmd`` 结尾即 cs↔参数组接缝）。
_CS_TAIL_RX = re.compile(r"\\[a-zA-Z@]+\*?$")


def _group_end(text: str, start: int, cap: int) -> int | None:
    r"""``text[start]``（``{``/``[``）起的配对括号组尾后位置。

    ``\\`` 转义双跳；超 ``cap`` 或未闭合 → ``None``。
    """
    close = "}" if text[start] == "{" else "]"
    depth = 0
    i, n = start, min(len(text), cap)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == text[start]:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _cs_arg_heads(text: str, cut: int, w: int) -> list[int]:
    r"""``cut`` 处的候选参数组头（内→外）。

    - ``cut`` 自身是 ``{``/``[``（组缝/组开头切点）；
    - ``[w, cut)`` 内未闭合的组头栈（``cut`` 在组内的切点，含嵌套——
      ``_ATOMIC_CUT_RX`` 只罩非嵌套组的残余面）；
    - 紧邻 ``cut`` 左侧刚闭合的组头（``}{``/``]{`` 参数组链接缝，组间
      空白跳过——TeX 参数扫描本就忽略组间空白）。

    ``\\`` 转义双跳；配型错位的闭括号忽略。
    """
    heads: list[int] = []
    if cut < len(text) and text[cut] in "{[":
        heads.append(cut)
    stack: list[tuple[str, int]] = []
    last_closed: tuple[int, int] | None = None  # (头, 尾后)
    i = w
    while i < cut:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c in "{[":
            stack.append((c, i))
        elif c in "}]":
            want = "{" if c == "}" else "["
            if stack and stack[-1][0] == want:
                last_closed = (stack.pop()[1], i + 1)
        i += 1
    heads.extend(pos for _c, pos in reversed(stack))
    if last_closed is not None and not text[last_closed[1] : cut].strip():
        heads.append(last_closed[0])
    return heads


def _safe_cut(text: str, cut: int, lo: int) -> int:
    """``cut`` 落在原子 span 内部时退到 span 头（头越不过 ``lo`` 则进到 span 尾）。

    span 都很短（≤40 字符），只在 cut 附近 ±64 窗口里找——不切实际的长 span
    也不会被漏（``[[`` token/控制字没有 >40 字符的形态）。cs 复合原子的
    嵌套/未闭合组残余由 ``_cs_arg_heads`` 兜底同则退/进。
    """
    for m in _ATOMIC_CUT_RX.finditer(text, max(0, cut - 64), min(len(text), cut + 64)):
        if m.start() < cut < m.end():
            return m.start() if m.start() >= lo else m.end()
    for head in _cs_arg_heads(text, cut, max(0, cut - 128)):
        m = _CS_TAIL_RX.search(text[max(0, head - 128) : head].rstrip())
        if m is None:
            continue
        cs = max(0, head - 128) + m.start()
        if cs >= lo:
            return cs
        end = _group_end(text, head, cut + 64)
        if end is not None:
            return end
        if cs >= 1:
            return cs
    return cut


#: 切点前尾词——``Fig.``/``e.g.``/``et al.``/``Sec.`` 缩写位识别用
_ABBREV_TAIL_RX = re.compile(r"([A-Za-z][A-Za-z.]*)$")
#: 无点尾词的缩写长度上界（texglot llm.py:85-90 同款：``Fig``/``Sec``/``Dr``）
_ABBREV_MAX_WORD = 3


def _abbrev_cut(text: str, i: int) -> bool:
    """``text[i]``（``.!?`` 位）是缩写尾点则不切——劈开产碎头 + 语义半截块。

    texglot llm.py:85-90 同款：尾词含 ``.``（``e.g.``/``al.``）或 ≤3 字母
    （``Fig``/``Sec``/``Eq``/``Dr``）→ 缩写位。保守向偏欠切——``is.``/``wow!``
    这类真句尾小词也被放过，欠切只让块偏大，过切才毁句。
    """
    m = _ABBREV_TAIL_RX.search(text[:i])
    if m is None:
        return False
    w = m.group(1)
    return "." in w or len(w) <= _ABBREV_MAX_WORD


def _best_split(text: str, limit: int) -> int:
    """在 [limit//2, limit] 窗口里找最右闭合-scope 句号切点；找不到退化到 limit。"""
    depth = 0
    i, n = 0, min(len(text), limit)
    lo = max(1, limit // 2)
    best = -1
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        elif (
            c in ".!?"
            and depth == 0
            and i + 1 < n
            and text[i + 1] in " \n"
            and not _abbrev_cut(text, i)
        ):
            best = i + 1  # 句号后切（含句号）
        i += 1
    if best >= lo:
        return _safe_cut(text, best, lo)
    # 兜底：找 limit 内最后一个换行/空格，再不行硬切
    for j in range(n, lo, -1):
        if text[j - 1] in " \n":
            return _safe_cut(text, j, lo)
    return _safe_cut(text, n, lo)
