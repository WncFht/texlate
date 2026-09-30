"""自动术语抽取（auto-extract-glossary）：masked chunk 文列 → LLM 域名词表 → 多数表决 ``{en: zh}``。

仿 BabelDOC ``automatic_term_extractor.py`` 的 prompt（≤5 词域名词短语 + 具名实体、
排数学项、JSON ``[{"src","tgt"}]`` 出）+ ``translation_config.
finalize_auto_extracted_glossary`` 的逐 src ``Counter.most_common`` 多数表决。
L1 探针（5 篇跨域 113 词 ~96% 正确）与 L2 A/B
（term_inconsistency 100%→43%）定案后产品化。

调用约定（抽取臂、非 judge 面）：默认模型 ``swe-2-medium``、temperature 0.1、
max_tokens 8192（reasoning 预算下限）；传输错误 ``call_with_backoff`` 3 试，
read timeout 沿用 ``ChatClient`` 默认 300s。网关地址/密钥不进本模块——
``client`` 由调用方注入。

失败降级：单批坏 JSON（``TermParseError``）或重试尽败（``ChatError``）只丢
该批，不炸整篇；零命中返 ``{}``；``max_batches`` 封顶防巨篇烧量（超量时按
等距抽样保整篇广度，照 L2 探针的 strided subset）。返回键保留 src 原文形——
``Glossary.doc_filter`` 的词边界匹配要吃文中实形；大小写/复数/空白差异只
在表决归一键（``_norm_key``）里折合。
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from functools import partial
from typing import TYPE_CHECKING

from .client import DEFAULT_MODEL, REASONING_MIN_MAX_TOKENS, ChatError, ChatOptions
from .retry import RetryPolicy, call_with_backoff

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .client import ChatClient, ChatResult

log = logging.getLogger(__name__)

#: 抽取臂默认模型——非 judge 面（judge 用 swe-2-max）；引 ``DEFAULT_MODEL``
#: 钉在免费集池首，防 preference 轮换后字面量漂移（client.py 常量注同约定）
EXTRACT_MODEL = DEFAULT_MODEL
#: 一批打包上限（字）。L1 探针 2400 / L2 4000 两档实测均净，产品取保守档
EXTRACT_BATCH_CHARS = 2400
#: 单篇抽取调用封顶——巨篇防烧量（L2 实测 ~6 calls/paper）
EXTRACT_MAX_BATCHES = 6
#: 枚举任务低温即可（探针定案值）
EXTRACT_TEMPERATURE = 0.1
#: reasoning 模型思考也吃预算——单源引 client 下限
EXTRACT_MAX_TOKENS = REASONING_MIN_MAX_TOKENS
#: 单批传输重试上限（探针定案值）
EXTRACT_TRIES = 3
#: 单条 src 长度上限——BabelDOC 同款 100 字闸（更长 = 句子泄漏非术语）
SRC_MAX_CHARS = 100
#: src==tgt 保原语条目的最短长度（``"AI"→"AI"`` 类短回显当噪音弃）
MIN_KEEP_CHARS = 3
#: 归一化去尾 s 的最短词长（更短的词去尾会削掉词干）
_MIN_SINGULAR_LEN = 4
#: 这些词尾的 s 不是复数（business/class/analysis/status 词干防削）
_PLURAL_SAFE_TAILS = ("ss", "us", "is")
#: prompt 占位符条款的约定关键词——钉测与 prompt 引同一常量，防条款漂移
MASK_CLAUSE_KEYWORD = "opaque"

#: 抽取 prompt——L1 探针定案原文（zh 目标、无参照表、含 [[X_n]] 掩码条款）。
#: 组装走 ``.replace("{text_to_process}", …)``——模板内含 JSON 花括号，
#: 不能用 ``.format``。
PROMPT_TEMPLATE = """
You are an expert multilingual terminologist. Extract key terms from the text and translate them into Simplified Chinese.

### Extraction Rules
1. Include only: named entities (people, orgs, locations, theorem/algorithm names, dates) and domain-specific nouns/noun phrases essential to meaning.
2. No full sentences. Ignore function words.
3. Use minimal noun phrases (<=5 words unless a named entity). No generic academic nouns (e.g., model, case, property) unless part of a standard term.
4. No mathematical items: variables (X1, a, epsilon), symbols, subscripts/superscripts, formula fragments, mappings (T: H1->H2), etc. Keep only natural-language concepts.
5. The text contains masked placeholders of the form [[WORD_n]] (e.g. [[MATH_12]], [[CITE_34]]). Treat them as opaque tokens: do not extract them, and do not emit them in "src" or "tgt".
6. Extract each term once. Keep order of first appearance.

### Translation Rules
1. Translate each term into Simplified Chinese.
2. Keep proper names in original language unless a well-known translation exists.
3. Ensure consistent translations.

### Output Format
- Return ONLY a valid JSON array.
- Each element: {"src": "...", "tgt": "..."}.
- No comments, no backticks, no extra text.
- If no terms: [].

### Example
For terms "LLM", "GPT":
[
  {"src": "LLM", "tgt": "大语言模型"},
  {"src": "GPT", "tgt": "GPT"}
]

Input Text:
```
{text_to_process}
```

Return JSON ONLY. NO OTHER TEXT.
Result:
"""

#: 调用参数包（frozen dataclass，全批共享）
_EXTRACT_OPTIONS = ChatOptions(
    temperature=EXTRACT_TEMPERATURE, max_tokens=EXTRACT_MAX_TOKENS
)

#: 围栏标签剥除序——``<json>``/``````json``/`````` 前缀 + ``</json>``/`````` 尾
_FENCE_HEADS = ("<json>", "```json", "```")
_FENCE_TAILS = ("</json>", "```")


class TermParseError(ValueError):
    """抽取应答非约定 JSON 形态（坏 JSON / 非 list / 无 ``[…]`` 段）。"""


def _clean_json_output(raw: str) -> str:
    """剥 ``<json>``/`````` 围栏（BabelDOC ``_clean_json_output`` 同款，顺序先 ``json`` 后缀形）。"""
    s = raw.strip()
    for tag in _FENCE_HEADS:
        s = s.removeprefix(tag)
    for tag in _FENCE_TAILS:
        s = s.removesuffix(tag)
    return s.strip()


def _json_span(cleaned: str) -> object:
    """前后散文包裹形的兜底：取最外 ``[…]`` 切片 strict loads；无片/坏片 → ``TermParseError``。"""
    i, j = cleaned.find("["), cleaned.rfind("]")
    if i == -1 or j <= i:
        msg = f"no JSON array span in response: {cleaned[:120]!r}"
        raise TermParseError(msg)
    try:
        return json.loads(cleaned[i : j + 1])
    except (json.JSONDecodeError, RecursionError) as e:
        msg = f"JSON array span decode failed: {e}"
        raise TermParseError(msg) from e


def _parse_pairs(content: str) -> list[tuple[str, str]]:
    """模型应答 → ``(src, tgt)`` 对列；整体形态非约定 → ``TermParseError``。

    接受裸数组 / `````` 围栏 / ``<json>`` 围栏 / 前后散文包裹四形态（散文形
    走 ``_json_span`` 最外 ``[…]`` 切片）。逐条校验：dict+src/tgt、
    src<SRC_MAX_CHARS、无 ``[[`` 占位符泄漏、src==tgt 短回显丢弃——单条
    畸形跳过不炸批，整批 JSON 坏才抛。
    """
    cleaned = _clean_json_output(content)
    try:
        data: object = json.loads(cleaned)
    except (json.JSONDecodeError, RecursionError):
        data = _json_span(cleaned)
    if not isinstance(data, list):
        msg = f"extractor response is not a list: {type(data).__name__}"
        raise TermParseError(msg)
    pairs: list[tuple[str, str]] = []
    for item in data:
        if not isinstance(item, dict) or "src" not in item or "tgt" not in item:
            continue
        src, tgt = str(item["src"]).strip(), str(item["tgt"]).strip()
        if not src or not tgt or len(src) >= SRC_MAX_CHARS:
            continue
        if src == tgt and len(src) < MIN_KEEP_CHARS:
            continue
        if "[[" in src or "[[" in tgt:
            # 占位符泄漏——[[X_n]] 进术语表会原样污染 system prompt
            continue
        pairs.append((src, tgt))
    return pairs


def _norm_key(src: str) -> str:
    """表决归一键：小写 + 空白折叠 + 末词复数去尾 s（返回键不走此键，保留原文形）。

    ``System size`` / ``system sizes`` / ``system  size`` → 同键。
    ``_PLURAL_SAFE_TAILS`` 词尾（ss/us/is）不是复数 s，词干防削。只动末词——
    短语中部复数属原文差异，归一过狠会把真异词并票。
    """
    s = re.sub(r"\s+", " ", src.strip().lower())
    head, _, last = s.rpartition(" ")
    if (
        len(last) >= _MIN_SINGULAR_LEN
        and last.endswith("s")
        and not last.endswith(_PLURAL_SAFE_TAILS)
    ):
        last = last[:-1]
    return f"{head} {last}".strip()


def _pick_corpus(texts: list[str], cap: int) -> list[str]:
    """全篇等距抽 chunk 到 ~cap 字符——保整篇广度（胜于顺序头截断，L2 探针同款）。

    首条等距候选恒进料（``picked`` 空时不查 cap）——``_pack_batches`` 的
    oversized-singleton 同合同：整篇只有一号超大块也产一批，不把全篇
    静默丢成 ``{}``。
    """
    total = sum(len(t) for t in texts)
    if total <= cap:
        return list(texts)
    stride = max(1, -(-total // cap))  # ceil
    picked, acc = [], 0
    for t in texts[::stride]:
        if picked and acc + len(t) > cap:
            break
        picked.append(t)
        acc += len(t)
    return picked


def _pack_batches(texts: list[str], batch_chars: int) -> list[str]:
    """文列贪心打包：空行相接、每批 ≤batch_chars（单条超长独占一批）。"""
    batches, cur = [], ""
    for t in texts:
        if cur and len(cur) + len(t) + 2 > batch_chars:
            batches.append(cur)
            cur = t
        else:
            cur = f"{cur}\n\n{t}" if cur else t
    if cur:
        batches.append(cur)
    return batches


async def _ask(client: ChatClient, model: str, batch: str) -> ChatResult:
    """单批一次抽取调用（prompt 组装 + chat）；重试由调用方 ``call_with_backoff`` 包。"""
    prompt = PROMPT_TEMPLATE.replace("{text_to_process}", batch)
    return await client.chat(
        model, [{"role": "user", "content": prompt}], options=_EXTRACT_OPTIONS
    )


async def extract_terms(
    texts: Iterable[str],
    client: ChatClient,
    *,
    model: str = EXTRACT_MODEL,
    batch_chars: int = EXTRACT_BATCH_CHARS,
    max_batches: int = EXTRACT_MAX_BATCHES,
) -> dict[str, str]:
    """Masked chunk 文列 → ``{en: zh}`` 术语表（``Glossary.doc_filter`` 可直接消费）。

    流程：``_pick_corpus`` 等距抽样到 ``batch_chars*max_batches`` 字内 →
    ``_pack_batches`` 打包 → 逐批 ``_ask``（``call_with_backoff`` 3 试）→
    ``_parse_pairs`` 解析 → 归一键下逐 src 多数表决
    （``Counter.most_common``，BabelDOC finalize 同款）；返回键取归一组内
    最常见的 src 原文形（并列取首见——``doc_filter`` 匹配要实形）。

    单批失败（``ChatError`` 重试尽 / ``TermParseError``）记 warning 跳过，
    不炸整篇；一篇至多 ``max_batches`` 次调用；零命中返 ``{}``。
    """
    if batch_chars < 1 or max_batches < 1:
        msg = f"batch_chars={batch_chars} / max_batches={max_batches} must be >= 1"
        raise ValueError(msg)
    srcs = [t for t in texts if t and t.strip()]
    if not srcs:
        return {}
    batches = _pack_batches(_pick_corpus(srcs, batch_chars * max_batches), batch_chars)[
        :max_batches
    ]
    policy = RetryPolicy(max_tries=EXTRACT_TRIES)
    votes: dict[str, list[str]] = {}
    forms: dict[str, list[str]] = {}
    for i, batch in enumerate(batches):
        try:
            r = await call_with_backoff(
                partial(_ask, client, model, batch), policy=policy
            )
            pairs = _parse_pairs(r.content)
        except (ChatError, TermParseError) as e:
            log.warning("autogloss: 第 %d/%d 批放弃（%s）", i + 1, len(batches), e)
            continue
        for src, tgt in pairs:
            key = _norm_key(src)
            if not key:
                continue
            votes.setdefault(key, []).append(tgt)
            forms.setdefault(key, []).append(src)
    table: dict[str, str] = {}
    for key, tgts in votes.items():
        win_tgt = Counter(tgts).most_common(1)[0][0]
        win_src = Counter(forms[key]).most_common(1)[0][0]
        table[win_src] = win_tgt
    log.info("autogloss: %d 批 → %d 词", len(batches), len(table))
    return table
