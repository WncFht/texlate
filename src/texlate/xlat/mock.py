r"""占位译文 Translator（mock 臂）：E2E/bench/干跑路径专用，不触网、确定性。

``MockTranslator`` 实现 ``pipeline.Translator`` 协议：占位符/控制字/括号
原位保留，非空散文段 → 按比例固定中文串——占位符契约天然成立，且批输入
（每行 ``[n]`` 开头）回显编号，保证批量解析路径被真实走到。护栏口径与
rules/cs-boundary 对齐：只替换行内字母 run，标点/空白/换行原样，防 ``\cs``+CJK
熔合成未定义控制序列。
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import prompts

#: mock 译文固定串（e2e mock_a 同款：散文段 → 固定中文，token 原位不动）
MOCK_ZH = "这是译文"

#: token 集 = 占位符 + 控制序列 + 括号 + rules 脆弱字符（``~`` 活动字符、``$``/``&``
#: 结构符——丢了会触发 cs_dropped/数学计数差，mock 与 rules 同口径才构成有效 E2E）
_MOCK_TOKEN_RX = re.compile(
    r"\[\[[A-Z_]+_\d+\]\]|\[\[[A-Z][A-Z_]*\]\]|\\[a-zA-Z@]+\*?|\\(?!\[\[).|[][(){}|~$&]"
)
#: 行内字母 run（mock 译文替换单位；``[^\n]`` 不跨行——保住换行布局）
#: 勘误 2026-09-17（登记不修）：ASCII 盲区——西里尔/希腊文等非 ASCII 散文
#: 原样回显不进译文（scout-triage-2026-09-17 F-echo 1 格，low）。
#: 本件是 bench ``specs/_qualframe._mock_translate`` 的同名同源单源——
#: bench 侧应 import 本叶而非自持副本（token/prose-run/zh 串三件套漂移面）。
_PROSE_RUN_RX = re.compile(r"[a-zA-Z][^\n]*[a-zA-Z]|[a-zA-Z]")
#: 批行 `[n]` 前缀识别（mock 回显编号用）——`[n] keep: ids |` 名单前缀是
#: 协议元数据非待译内容，剥到只剩序号（回显 ids 会成 extra-ph）。
_MOCK_NUM_RX = re.compile(
    r"^(\[\d+\])\s?(?:keep:(?:[ \t]*\[\[[A-Z][A-Z_]*_?\d*\]\])+[ \t]*\|?[ \t]*)?(.*)$",
    re.DOTALL,
)
#: 批输入判定：首行是序号头且全文 ≥2 个序号头行（单 chunk 开头字面 `[1]`
#: 只有 1 头仍走整体回译；批恒 ≥2 成员）
_MOCK_HEAD_RX = re.compile(r"^\[\d+\](?:[ \t]|$)")
_MOCK_BATCH_MIN_HEADS = 2

#: mock 译文密度：每 ~8 个英文字符折一倍 ``MOCK_ZH``——E24 token 比带
#: [0.3,3.0] 下 mock 输出须贴近真实 CJK 密度（4 字固定桩对任何
#: est≥10 的 src 都是坍缩比，会触发 length error 假 fault）。
_MOCK_ZH_PER_CHARS = 8


def _mock_zh(text: str, zh: str) -> str:
    """``zh`` 按 ``text`` 长度折倍——产出 CJK≈拉丁/2 的拟真密度。"""
    return zh * max(1, len(text) // _MOCK_ZH_PER_CHARS)


def _mock_translate_text(text: str, zh: str) -> str:
    r"""e2e mock_a 同款：token 原位保留，字母散文 run → 按比例中文串。

    护栏对齐 rules/cs-boundary 口径：只替换行内字母 run（``\eg, Caffe`` →
    ``\eg, 这是译文``），标点/空白/换行原样——否则 ``\cs``+CJK 熔合成
    未定义控制序列（macro 融合 cs/cs_dropped 是 error 级判据）。
    """
    out: list[str] = []
    pos = 0
    for m in _MOCK_TOKEN_RX.finditer(text):
        out.append(
            _PROSE_RUN_RX.sub(
                lambda m2: _mock_zh(m2.group(0), zh), text[pos : m.start()]
            )
        )
        out.append(m.group(0))
        pos = m.end()
    out.append(_PROSE_RUN_RX.sub(lambda m2: _mock_zh(m2.group(0), zh), text[pos:]))
    return "".join(out)


class MockTranslator:
    """占位译文：占位符/控制字/括号原位保留，非空散文段 → 固定中文串。

    供 E2E 与 bench 用——不触网、确定性、占位符契约天然成立。
    批输入（每行 `[n]` 开头）回显编号，保证批量解析路径被真实走到。
    """

    def __init__(self, zh: str = MOCK_ZH) -> None:
        """`zh` = 散文段替换成的固定中文串。"""
        self.zh = zh
        self.calls: list[dict[str, Any]] = []  # 测试可断言调用次数/内容

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """返回 mock 译文。"""
        self.calls.append(
            {
                "system": system,
                "user": user,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if response_format is not None and response_format.get("type") == "json_object":
            try:
                payload = json.loads(user)
                slots = payload.get("slots") or {}
                return json.dumps(
                    {k: _mock_zh(str(v), self.zh) for k, v in slots.items()},
                    ensure_ascii=False,
                )
            except (json.JSONDecodeError, AttributeError):
                return "{}"
        # user 尾挂的 [placeholder_values] 参考块（及其后 [compile_error] 等
        # 反馈段）不是待译内容——剥掉再回显，否则块内 token 二次出现触发
        # extra-placeholder 校验失败、批回显路径也走不到（整批退单翻）。
        body = user.partition("\n\n" + prompts.VALUE_CONTEXT_HEADER)[0]
        lines = body.split("\n")
        n_heads = sum(1 for ln in lines if _MOCK_HEAD_RX.match(ln))
        if lines and n_heads >= _MOCK_BATCH_MIN_HEADS and _MOCK_HEAD_RX.match(lines[0]):
            return "\n".join(
                f"{m.group(1)} {_mock_translate_text(m.group(2), self.zh)}"
                if (m := _MOCK_NUM_RX.match(ln))
                else _mock_translate_text(ln, self.zh)
                for ln in lines
            )
        return _mock_translate_text(body, self.zh)
