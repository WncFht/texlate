r"""批量协议（docs/08 §1.3）：short 桶贪心装箱 + `[n]` 编号 + `@@` 兜底 + 整批退单翻。

- 分桶：`content < 300` 字符入批（short），否则逐条单翻（long）。
- 装箱：short 桶顺序贪心 ≤2000 字符/批（含编号开销；按 token 控可放宽到 ~8000
  字符——成本实测 prompt 摊销占输入 68%，批阈值是最大杠杆，见 cost-model §4）。
- 协议：请求 `[1] xxx\n[2] yyy`；响应优先按 `[n]` 解析，`@@` 分隔兜底；
  数量不符/序号越界/解析失败 → `None`，调用方整批退化逐条单翻。
- 跳过：纯占位符 chunk（`placeholders.is_placeholder_only`）不发请求。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, TypeVar

from .placeholders import encode_newlines

if TYPE_CHECKING:
    from collections.abc import Sequence

#: <300 字符入批
SHORT_CHAR_LIMIT = 300
#: 单批 payload 上限（含 `[n] ` 编号开销；token 口径放宽见模块 docstring）
BATCH_MAX_CHARS = 2000
#: `[n] ` 编号开销估计（用于装箱容量计算）
BATCH_ITEM_OVERHEAD = 8
#: 超大原子 chunk 的切分阈值（> 此值先切分再入批/单翻）
CHUNK_HARD_LIMIT = 6000

T = TypeVar("T")

#: 响应解析主协议：`[n]` 序号节
_NUM_RX = re.compile(r"\[(\d+)\]")
#: `@@` 兜底分隔（独占一行的 @@；模型不按编号时 spec 允许此退路）
_ATAT_LINE_RX = re.compile(r"^\s*@@\s*$", re.MULTILINE)


def pack_batches(
    contents: Sequence[str],
    *,
    max_chars: int = BATCH_MAX_CHARS,
    item_overhead: int = BATCH_ITEM_OVERHEAD,
) -> list[list[int]]:
    """Short 桶顺序贪心装箱 → 每批是 contents 的下标列表（保持原序）。"""
    batches: list[list[int]] = []
    cur: list[int] = []
    cur_len = 0
    for i, text in enumerate(contents):
        need = len(text) + item_overhead
        if cur and cur_len + need > max_chars:
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


def parse_batch_response(text: str, n: int) -> list[str] | None:
    """解析批量响应为 n 段译文；失败返回 `None`（调用方整批退单翻）。

    主协议 `[n]`：序号多重集须恰为 {1..n}（乱序可接受——按下标归位）。
    兜底 `@@`：独占一行的 @@ 切分，段数恰为 n 才算成功。
    """
    text = text.strip()
    if not text or n <= 0:
        return None

    # 主协议：按 [n] 标号切
    matches = list(_NUM_RX.finditer(text))
    if matches:
        idxs = [int(m.group(1)) for m in matches]
        if sorted(idxs) == list(range(1, n + 1)):
            out = [""] * n
            for i, m in enumerate(matches):
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                out[int(m.group(1)) - 1] = text[m.end() : end].strip()
            if all(s for s in out):
                return out
        # 标号不齐 → 尝试 @@ 兜底，仍败 → None

    parts = [p.strip() for p in _ATAT_LINE_RX.split(text)]
    parts = [p for p in parts if p]
    if len(parts) == n and all(parts):
        return parts
    return None


def split_long_chunk(text: str, *, max_chars: int = CHUNK_HARD_LIMIT) -> list[str]:
    """超大原子 chunk 按句界二分（闭合 scope 边界 + 句号优先、大写开头次优）。

    docs/08 §1.3「超大原子 chunk 先切分再入批」——不切会爆单请求上下文
    （实测 109K/77K 原子块，cost-model §5.3）。返回保持顺序的片段列表。
    """
    if len(text) <= max_chars:
        return [text]
    out: list[str] = []
    rest = text
    while len(rest) > max_chars:
        cut = _best_split(rest, max_chars)
        out.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    if rest:
        out.append(rest)
    return out


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
        elif c in ".!?" and depth == 0 and i + 1 < n and text[i + 1] in " \n":
            best = i + 1  # 句号后切（含句号）
        i += 1
    if best >= lo:
        return best
    # 兜底：找 limit 内最后一个换行/空格，再不行硬切
    for j in range(n, lo, -1):
        if text[j - 1] in " \n":
            return j
    return n
