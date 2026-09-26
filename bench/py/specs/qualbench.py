r"""qualbench spec — LLM-judge 翻译质量评测（原 ``bench/py/qualbench.py`` spec 化）。

测量面逐行移植：ESA esa2 协议（judge 先标错误 span 再赋 0-100 分；
规格见 docs/research/methods/2026-09-18-xlat-quality-eval.md §7）、
九类目 MQM 化表 + 六 flag 派生 + stated100/derived100 双分 +
contested 触发二裁。格模型重做——一 frame 行（paper, chunk_id, judge）
一格：idc=paper、arm=被评翻译模型、variant=``esa2@{EPOCH}|{judge}|
{chunk_id}``、up=frame 行 provenance。``dedup_key``=(idc,arm,variant)
显式声明（付费段强制）；测量行进 eval_records 道 + emit_case 全量
record。跨 run dedup 永驻——协议/测具变化靠 PROTOCOL_V/EPOCH 升号挪
claim 空间，绝不原地覆盖。

chunk 对来源 = **frame**（冻结选样层）：``bench/nominations/qualframe-
*.jsonl`` 每行一对，由 ``specs/_qualframe.py`` 烘焙——旧 ``--source``
三道的正身：``mock``（湖格 mock 译文 + ``judge=mock-judge`` 零网关自检）、
``state``（``xlat-state/{arm}/state.json`` 树→ok/partial∧zh≠src 行，
judge 烘焙时按 route_judge 路由）、``manifest``（qualsample 冻结
sample.jsonl 直收）。frame 行 ``sha`` 进 ``fp_input``；src/zh/kind/
src_status 四参 fp=True（frame 重烘焙同键改内容→新测量）。
**frame 丢失 = spec 加载即炸**——选样层是被测对象的一部分，静默退化
会把「没测」读成「测了」。

状态映射（status_class 逐格声明；audit 三件套之 status 映射）：
  judge 出分（含 contested、含 judge2 内部失败）→ ``ok``
  传输/协议错或两次输出均不可解析          → ``error``（retriable——
      网关抖动/模型暂缺可回；旧 done-error 行的正身）
  网关把请求降级到非路由模型（fallback）   → ``error`` + judge_fallback
      （retriable——路由禁则被破坏宁可重测不记账；见下 DELTA）
  ``route_judge`` 全员被禁                 → ``reject`` + no_eligible_judge
      （terminal——池不变不会自愈，重跑无义）
  src/zh 任一空                          → ``reject`` + empty_pair
      （terminal——确定性终态）

done 定义（audit 三件套之二）：每格恰一条 terminal/retriable 行；
测量分母 = 全部格（reject 格也算分母——frame 选了就该交代结果；
empty/no_eligible 是「测量对象自证不合法」，与「未测」分开计数）。
分母守恒对拍：frame 行数 == 格数 == 终态+可重试行数，无静默丢格。

参数面：src/zh/kind/src_status fp=True（cell 侧内容指纹）；chunk_id/
judge fp=False（已在 variant，声明只为参数 schema 完整）；second_model/
no_second/judge_temperature/judge_max_tokens fp=True（测量语义旋钮，
改动=新测量空间）；frames/ids/judges/n 为 select 闸（fp=False，n 为
selector 自带排除）。select 语义：frame 序即烘焙序（seeded），过滤器
先过再取前 n。

DELIBERATE DELTAS（对旧驱动的刻意迁移，均已核对语义）：
- judge 调压栈由「裸 httpx 3-try 指数退避」改为 ``session.request`` 一
  发——ChatClient 内部已是同 taxonomy 的重试梯队（retryable/
  max_tries/retry_after），外层再套循环会双倍预算。ChatError 逃逸 =
  梯队已尽 → judge_error（retriable），不再就地退避。
- 新增 **judge_fallback 闸**：ChatClient.chat 带免费集降级臂（loopback
  网关 ``is_free_gateway_url``=True，swe-2-max 失败可静默换 swe-2-medium
  ——被禁同型自评）。每发响应 ``res.model != 请求模型`` → judge_error，
  不记账。旧裸 httpx 无此臂，本闸是 spec 化必须的等价防线。
- ``--judge-timeout`` 参数被删：ChatOptions 无 timeout 字段、factory 是
  spec 级（params 解析前即建）——参数在结构上不可达。超时烘焙进
  factory 的 ``GatewayChat(timeout=300.0)``（值同旧默认）。
- ``--judge-model`` 从 run 参数挪进 frame 行 ``judge`` 列（烘焙时路由，
  进 variant）——「谁裁」是测量坐标不是运行旋钮；换主裁=换 frame=
  新 claim 空间，不重测旧键。
- no_eligible_judge / empty_pair 由「done-error 无限重跑」改 terminal
  reject（retry 无出口的状态不应挂 retriable）。
- 并发面：driver ``--concurrency 2`` → factory ``nslots=2``；网关全局
  decode ~550 tok/s 自限不变。
- ``--mock-judge`` 开关改 frame 行 ``judge="mock-judge"``——fn 在
  ctx.gateway() **之前** 分流（懒构造=付费断言，mock 格零请求零花费），
  但仍走完整付费段 claim/dedup 机械（刻意：全链自检不豁免）。
- ``pairs``/``report`` 子命令与抽样 CLI 整体消失——选样下沉
  ``specs/_qualframe.py``（烘焙产物即 frame），聚合属 Wave-D 动词。
- record 落点：records.jsonl append → emit_case（cases 表 + cases.jsonl
  与终态批量原子落）；key={model}|{paper}|{chunk}|{judge}|{proto} 的
  五元组由 (idc,arm,variant) 三键承载（proto/epoch 在 variant 前段）。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from kernel.spec import Param, Spec, Stage

from specs._shared import (
    DEFAULT_BASE_URL,
    DEFAULT_PRICES,
    GatewayChat,
)

REPO = Path(__file__).resolve().parents[3]
NOMINATIONS = REPO / "bench" / "nominations"

# ---------------------------------------------------------------- 常量（逐行移植）

#: 占位符 token 同 ANY_PH_RX 口径（独立实现——本 spec 不 import texlate.* 于判定面）
PH_TOKEN_RX = re.compile(r"\[\[[A-Z_]+_\d+\]\]|\[\[[A-Z][A-Z_]*\]\]")
#: zh 中残留英文散文词（≥4 字母，占位符/控制序列先剥掉）——漏翻确定性信号
EN_WORD_RX = re.compile(r"[A-Za-z]{4,}")
CS_RX = re.compile(r"\\[a-zA-Z@]+\*?")
#: ```json 围栏剥皮（网关忽略 response_format，模型可能仍包 fence）
JSON_FENCE_RX = re.compile(
    r"^\s*```[A-Za-z]*\s*\n(?P<body>.*?)\n?\s*```\s*$", re.DOTALL
)
#: 首个平衡 JSON 对象兜底抽取（fence 剥不掉时扫 {...}）
JSON_OBJ_RX = re.compile(r"\{.*\}", re.DOTALL)

#: 协议版本——进 variant，协议切换不静默截留旧测量
PROTOCOL_V = "esa2"
#: spec 测具代次——spec 内部修复（非协议变化）挪 claim 空间用；
#: 两者都进 variant 前段：``esa2@v1|…``
EPOCH = "v1"

#: ESA/MQM 化类目表（六 flag 的 MQM 化 + fluency-register report-only +
#: accuracy-mistranslation 补「在译但错」收容位 + non-translation 整段未翻）
KNOWN_CATEGORIES = (
    "accuracy-omission",
    "accuracy-mistranslation",
    "accuracy-addition",
    "non-translation",
    "terminology",
    "convention-do_not_translate",
    "convention-placeholder",
    "fluency-grammar",
    "fluency-register",
)

#: report-only：不入 derived 罚分、不进 critical 触发
REPORT_ONLY_CATS = frozenset({"fluency-register"})

#: critical 收窄到枚举致命类目（整段未翻/占位符结构报废/增译翻转含义）——
#: 越界 critical 解析侧钳回 major 并计 sev_clamped
CRITICAL_CATS = frozenset(
    {"non-translation", "convention-placeholder", "accuracy-addition"}
)

SEV_WEIGHT = {"minor": 1, "major": 5, "critical": 25}
#: ESA/Freitag 惯例：每段最多记 5 错（derived 取权重最高 5 条）
MAX_ERRORS = 5
#: record 侧最多保留的错误条数（防 judge 超发撑爆 case 行）
MAX_ERRORS_KEPT = 10

#: MQM 类目 → flag 词表（下游 repair/M8 消费口径；保序去重）
CATEGORY_TO_FLAG = {
    "accuracy-omission": "untranslated_spans",
    "non-translation": "untranslated_spans",
    "accuracy-addition": "hallucinated_content",
    "accuracy-mistranslation": "mistranslation",
    "terminology": "term_inconsistency",
    "convention-do_not_translate": "over_translation",
    "convention-placeholder": "placeholder_broken",
    "fluency-grammar": "grammar",
    "fluency-register": "fluency_register",
}

#: judge flag 全集（六 flag + mistranslation/fluency_register 派生值；
#: 未知类目 verbatim 落 cats_extra 留痕）
KNOWN_FLAGS = tuple(dict.fromkeys(CATEGORY_TO_FLAG.values()))

#: judge 池顺位（swe-2-medium 与被评同型自评病灶，永不任 judge）
JUDGE_POOL = ("swe-2-max", "swe-2-high")
JUDGE_BANNED = "swe-2-medium"

#: contested 触发阈值（xlat-quality-eval §7 冻结值）
DELTA_CONTEST = 15
STATED_CONTEST = 55
EN_RESIDUE_CONTEST = 8

#: judge 调用超时（烘焙进 factory——ChatOptions 无 timeout 字段，见头注 DELTA）
JUDGE_TIMEOUT = 300.0

JUDGE_SYSTEM = """\
You are a meticulous bilingual (English to Chinese) translation-quality
annotator for academic LaTeX texts, following the ESA error-annotation
protocol. You will receive:
- Kind: the fragment's role (para | caption | section_title | abstract |
  table_text | env_text).
- Source: the original English LaTeX fragment. [[TYPE_n]] tokens (e.g.
  [[MATH_12]], [[CITE_3]], [[REF_7]], [[SL]], [[PL]]) are opaque placeholders
  for protected LaTeX/math/citation fragments — they must appear verbatim in
  the translation.
- Translation: the Chinese translation produced by a machine translator.

Step 1 — identify EVERY error span in the TRANSLATION (at most 5: report
the 5 most severe). For each error report:
- "span": the exact substring of the Translation where the error occurs
  (copy it verbatim; for whole-segment errors repeat the full translation).
- "category": exactly one of
  "accuracy-omission" (source content dropped or left untranslated),
  "accuracy-mistranslation" (meaning distorted vs the source),
  "accuracy-addition" (content invented, absent from the source),
  "non-translation" (the whole segment left untranslated),
  "terminology" (technical term mistranslated or used inconsistently),
  "convention-do_not_translate" (content that must stay unchanged was
    translated: person names, citation/bibliography entries, math or LaTeX
    commands),
  "convention-placeholder" (a [[TYPE_n]] placeholder missing, invented,
    renamed, or its immediate surroundings garbled),
  "fluency-grammar" (ungrammatical or garbled Chinese),
  "fluency-register" (register/style mismatch for academic prose, e.g.
    machine-translation flavor — report only, does not affect the score).
- "severity": "minor" (doesn't change meaning; slight awkwardness),
  "major" (changes or obscures meaning, breaks readability, or violates a
    hard convention such as a lost placeholder),
  "critical" (ONLY for: non-translation of the whole segment; broken
    placeholders leaving the text structurally unusable; added content
    that inverts the source meaning).
- "note": <=40 chars describing the error.

Rules:
- Judge ONLY translation quality (faithfulness + fluency), not LaTeX
  compilability. Judge against the Kind's expectations (a section_title is
  a concise heading, a caption a compact legend).
- Do NOT mark an error for content correctly left in English (person
  names, citation/bibliography entries, math placeholders).
- A Source fragment containing [[BIB_n]] tokens is a bibliography
  region the pipeline intentionally keeps in English: a Translation
  identical to the Source there is CORRECT — do not flag
  non-translation or any other error for it.
- If the translation is fully correct, return an empty error list.

Step 2 — after the error list, give "score": your overall 0-100 quality
score for the translation (100 = perfect; use the full scale).

Output STRICT JSON only — no markdown fence, no commentary:
{"errors": [{"span": "...", "category": "...", "severity": "...", "note": "..."}], "score": <int 0-100>}"""

JUDGE_RETRY_SUFFIX = (
    "\n\nYour previous reply was not parseable JSON. Reply with ONLY the JSON "
    'object: {"errors": [{"span": "...", "category": "...", "severity": '
    '"...", "note": "..."}], "score": <int 0-100>}'
)


# ---------------------------------------------------------------- chunk 对（逐行移植）
@dataclass
class Pair:
    """一个待评 chunk 对。``model`` 是产出该译文的翻译模型。"""

    paper: str
    chunk_id: str
    kind: str
    model: str
    src: str
    zh: str
    arm: str = ""
    status: str = "ok"

    @property
    def key(self) -> str:
        return f"{self.model}|{self.paper}|{self.chunk_id}"


# ---------------------------------------------------------------- 确定性信号
def pair_signals(src: str, zh: str) -> dict:
    """每对都算的免费确定性特征——judge flag 的对照底账。"""
    from collections import Counter

    src_ph = Counter(PH_TOKEN_RX.findall(src))
    zh_ph = Counter(PH_TOKEN_RX.findall(zh))
    missing = src_ph - zh_ph
    invented = zh_ph - src_ph
    zh_clean = CS_RX.sub(" ", PH_TOKEN_RX.sub(" ", zh))
    return {
        "ph_missing": sum(missing.values()),
        "ph_invented": sum(invented.values()),
        "en_residue": len(EN_WORD_RX.findall(zh_clean)),
        "src_bib": "[[BIB_" in src,
        "src_chars": len(src),
        "zh_chars": len(zh),
    }


# ---------------------------------------------------------------- judge（逐行移植）
def _norm_parsed(errs_raw: object, score: int) -> dict:
    """errors 列表规范化 + 衍生字段（parse_esa_json 与 mock 路径共用）。

    - 类目不在 KNOWN_CATEGORIES → verbatim 保留 + 计 cats_extra
    - severity 不在三档 → 钳 minor 计 sev_clamped；critical 落在
      CRITICAL_CATS 外 → 钳 major 计 sev_clamped
    - derived100 = 100 − Σ 权重最高 MAX_ERRORS 条（report-only 类豁免）
    """
    errors: list[dict] = []
    cats_extra: list[str] = []
    sev_clamped = 0
    for e in (errs_raw if isinstance(errs_raw, list) else [])[:MAX_ERRORS_KEPT]:
        if not isinstance(e, dict):
            continue
        cat = str(e.get("category") or "?")
        sev = str(e.get("severity") or "minor").lower()
        if sev not in SEV_WEIGHT:
            sev = "minor"
            sev_clamped += 1
        elif sev == "critical" and cat not in CRITICAL_CATS:
            sev = "major"
            sev_clamped += 1
        if cat not in KNOWN_CATEGORIES:
            cats_extra.append(cat)
        errors.append(
            {
                "span": str(e.get("span") or ""),
                "category": cat,
                "severity": sev,
                "note": str(e.get("note") or "")[:80],
            }
        )
    derived = derived100(errors)
    return {
        "errors": errors,
        "stated100": score,
        "derived100": derived,
        "score_delta": score - derived,
        "cats_extra": sorted(set(cats_extra)),
        "sev_clamped": sev_clamped,
    }


def derived100(errors: list[dict]) -> int:
    """规则聚合：100 − Σ severity 权重（权重最高 MAX_ERRORS 条，report-only 豁免）。"""
    pen = sorted(
        (
            SEV_WEIGHT[e["severity"]]
            for e in errors
            if e["category"] not in REPORT_ONLY_CATS
        ),
        reverse=True,
    )[:MAX_ERRORS]
    return max(0, 100 - sum(pen))


def flags_of(errors: list[dict]) -> list[str]:
    """errors 类目 → flag 词表（下游消费口径；保序去重）。"""
    out: list[str] = []
    for e in errors:
        f = CATEGORY_TO_FLAG.get(e["category"])
        if f and f not in out:
            out.append(f)
    return out


def verify_spans(errors: list[dict], zh: str) -> list[dict]:
    """就地写 span_verified——span 须为译文逐字子串。"""
    for e in errors:
        e["span_verified"] = bool(e["span"]) and e["span"] in zh
    return errors


def contest_reasons(parsed: dict, sig: dict) -> list[str]:
    """contested 触发：|Δ|>15 / stated≤55 / 任一 critical / L0 信号矛盾。"""
    reasons: list[str] = []
    if abs(parsed["score_delta"]) > DELTA_CONTEST:
        reasons.append("delta_gt15")
    if parsed["stated100"] <= STATED_CONTEST:
        reasons.append("stated_le55")
    if any(e["severity"] == "critical" for e in parsed["errors"]):
        reasons.append("critical_present")
    cats = {e["category"] for e in parsed["errors"]}
    if (sig["ph_missing"] or sig["ph_invented"]) and (
        "convention-placeholder" not in cats
    ):
        reasons.append("l0_ph_unreported")
    if (
        sig["en_residue"] >= EN_RESIDUE_CONTEST
        and not ({"accuracy-omission", "non-translation"} & cats)
        and not sig["src_bib"]
    ):
        reasons.append("l0_en_unreported")
    return reasons


def mock_judge(pair: Pair) -> dict:
    """确定性 mock judge（ESA 形态）：按确定性信号出 errors+stated100。"""
    sig = pair_signals(pair.src, pair.zh)
    raw_errors: list[dict] = []
    if sig["src_bib"]:
        # bib 直通语境：zh≡src 是正确态——占位符守恒外零错误。
        if sig["ph_missing"] or sig["ph_invented"]:
            raw_errors.append(
                {
                    "span": "[[",
                    "category": "convention-placeholder",
                    "severity": "major",
                    "note": "placeholder mismatch",
                }
            )
            return _norm_parsed(raw_errors, 70)
        return _norm_parsed(raw_errors, 95)
    if pair.zh.strip() == pair.src.strip() or not pair.zh.strip():
        raw_errors.append(
            {
                "span": pair.zh[:80] or " ",
                "category": "non-translation",
                "severity": "critical",
                "note": "zh==src",
            }
        )
        return _norm_parsed(raw_errors, 5)
    if sig["ph_missing"] or sig["ph_invented"]:
        raw_errors.append(
            {
                "span": "[[",
                "category": "convention-placeholder",
                "severity": "major",
                "note": "placeholder mismatch",
            }
        )
    if sig["en_residue"] >= 8:
        w = EN_WORD_RX.search(CS_RX.sub(" ", PH_TOKEN_RX.sub(" ", pair.zh)))
        raw_errors.append(
            {
                "span": w.group(0) if w else pair.zh[:40],
                "category": "accuracy-omission",
                "severity": "major",
                "note": f"en_residue={sig['en_residue']}",
            }
        )
    elif sig["en_residue"] >= 3:
        raw_errors.append(
            {
                "span": pair.zh[:40],
                "category": "accuracy-omission",
                "severity": "minor",
                "note": f"en_residue={sig['en_residue']}",
            }
        )
    if not raw_errors:
        # sha 奇偶给 90/97 的确定性分布——聚合面能被真实走到
        stated = (
            90
            if int(hashlib.sha256(pair.key.encode()).hexdigest(), 16) % 3 == 0
            else 97
        )
    else:
        stated = (
            100
            - 10 * len(raw_errors)
            - (15 if sig["ph_missing"] or sig["ph_invented"] else 0)
        )
    return _norm_parsed(raw_errors, max(0, stated))


def parse_esa_json(raw: str) -> dict | None:
    """judge ESA 输出 → parsed dict；fence 剥皮 + {...} 兜底；不合格 None。"""
    m = JSON_FENCE_RX.match(raw)
    body = m.group("body") if m else raw
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        m2 = JSON_OBJ_RX.search(body)
        if not m2:
            return None
        try:
            data = json.loads(m2.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("errors"), list):
        return None
    score = data.get("score")
    if isinstance(score, float) and score.is_integer():
        score = int(score)
    if isinstance(score, str) and score.strip().isdigit():
        score = int(score.strip())
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
        return None
    return _norm_parsed(data["errors"], score)


def route_judge(pair: Pair, preferred: str) -> str | None:
    """judge 路由：preferred 非 banned（与被评同型/swe-2-medium）即用，否则池内顺位。"""
    banned = {pair.model, JUDGE_BANNED}
    if preferred and preferred not in banned:
        return preferred
    for m in JUDGE_POOL:
        if m not in banned:
            return m
    return None


def judge_user_prompt(pair: Pair) -> str:
    """结构化 user 消息：Kind/Source/Translation 三段。"""
    return f"[Kind]\n{pair.kind}\n\n[Source]\n{pair.src}\n\n[Translation]\n{pair.zh}"


def shape_judged(parsed: dict, pair: Pair, sig: dict) -> dict:
    """parsed ESA + pair/确定性信号 → record 判定字段块（span 校验 + contested）。"""
    verify_spans(parsed["errors"], pair.zh)
    reasons = contest_reasons(parsed, sig)
    return {
        "stated100": parsed["stated100"],
        "score": parsed["stated100"],
        "derived100": parsed["derived100"],
        "score_delta": parsed["score_delta"],
        "errors": parsed["errors"],
        "n_errors": len(parsed["errors"]),
        "n_span_unverified": sum(
            1 for e in parsed["errors"] if not e["span_verified"]
        ),
        "sev_counts": {
            s: sum(1 for e in parsed["errors"] if e["severity"] == s)
            for s in SEV_WEIGHT
        },
        "sev_clamped": parsed.get("sev_clamped", 0),
        "cats_extra": parsed.get("cats_extra", []),
        "flags": flags_of(parsed["errors"]),
        "contested": bool(reasons),
        "contest_reasons": reasons,
    }


# ---------------------------------------------------------------- paid 通道
def _judge_call(
    ctx,
    pair: Pair,
    model: str,
    *,
    max_tokens: int,
    user_suffix: str = "",
) -> dict:
    """一次 judge 调用＝一发 ``session.request``（ChatClient 内层已是
    retryable/max_tries/retry_after 的重试梯队——外层不套第二循环）。

    **judge_fallback 闸**：ChatClient 对 loopback 网关开免费集降级臂
    （swe-2-max 失败可静默换 swe-2-medium——被禁同型）。响应 model 与
    请求不符 → judge_error 不记账。返回形态对齐旧 call_judge：
    content/reasoning_chars/finish/seconds/tok_in/tok_out 或 {error}。"""
    from texlate.xlat._dialects import ChatOptions
    from texlate.xlat._errors import ChatError

    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": judge_user_prompt(pair) + user_suffix},
    ]
    temperature = float(ctx.params.get("judge_temperature") or 0.1)
    t0 = time.monotonic()
    try:
        res = ctx.gateway().request(
            "chat",
            model,
            messages,
            options=ChatOptions(
                temperature=temperature, max_tokens=max_tokens
            ),
        )
    except ChatError as e:
        # 梯队已尽（retryable 内部翻身用过）→ judge_error 交格级重跑；
        # 非 ChatError（含 kernel paid 例外族）不外接，直穿内核映射。
        return {"error": f"{type(e).__name__}: {e}"[:300]}
    dt = round(time.monotonic() - t0, 2)
    if not isinstance(res, dict):
        return {"error": f"bad_session_result:{type(res).__name__}",
                "seconds": dt}
    actual = str(res.get("model") or "")
    if actual and actual != model:
        return {
            "error": f"judge_fallback:{actual}!={model}",
            "seconds": dt,
        }
    usage = res.get("usage") or {}
    return {
        "content": str(res.get("text") or ""),
        "reasoning_chars": len(res.get("reasoning") or ""),
        "finish": str(res.get("finish_reason") or ""),
        "seconds": dt,
        "tok_in": usage.get("in_tok"),
        "tok_out": usage.get("out_tok"),
    }


def _judge_pair(ctx, pair: Pair, sig: dict) -> dict:
    """ESA 流程：主裁一发 → parse/verify/contest → 触规则二裁（逐行移植）。"""
    p = ctx.params
    max_tokens = int(p.get("judge_max_tokens") or 8192)
    jm = route_judge(pair, str(p.get("judge") or ""))
    if jm is None:
        return {"judge_error": f"no_eligible_judge(translator={pair.model})"}
    r = _judge_call(ctx, pair, jm, max_tokens=max_tokens)
    if "content" not in r:
        return {**r, "judge_model_used": jm}
    parsed = parse_esa_json(r["content"])
    if parsed is None:
        # 补问一次：user 带严格 JSON 提醒后缀
        r2 = _judge_call(
            ctx,
            pair,
            jm,
            max_tokens=max_tokens,
            user_suffix=JUDGE_RETRY_SUFFIX,
        )
        if "content" in r2:
            parsed = parse_esa_json(r2["content"])
            r = {**r2, "reparsed": True, "raw_first": r["content"][:200]}
    if parsed is None:
        return {
            **{k: v for k, v in r.items() if k != "content"},
            "judge_model_used": jm,
            "judge_error": "unparseable",
            "raw": r.get("content", "")[:300],
        }
    out = {
        "judge_model_used": jm,
        **shape_judged(parsed, pair, sig),
        "seconds": r.get("seconds"),
        "tok_in": r.get("tok_in"),
        "tok_out": r.get("tok_out"),
        "reasoning_chars": r.get("reasoning_chars"),
        "finish": r.get("finish"),
        "reparsed": r.get("reparsed"),
        "raw_first": r.get("raw_first"),
        "raw": r.get("content", "")[:500],
    }
    # contested → 二裁（judge2 块落 record 备查，主分仍取主裁 stated）
    if out["contested"] and not p.get("no_second"):
        jm2 = route_judge(pair, str(p.get("second_model") or "swe-2-high"))
        if jm2 is None or jm2 == jm:
            out["judge2"] = {"judge2_error": "no_eligible_second"}
        else:
            r2nd = _judge_call(ctx, pair, jm2, max_tokens=max_tokens)
            if "content" in r2nd:
                p2 = parse_esa_json(r2nd["content"])
                if p2 is not None:
                    verify_spans(p2["errors"], pair.zh)
                    out["judge2"] = {
                        "judge_model": jm2,
                        "stated100": p2["stated100"],
                        "derived100": p2["derived100"],
                        "score_delta": p2["score_delta"],
                        "n_errors": len(p2["errors"]),
                        "errors": p2["errors"],
                        "flags": flags_of(p2["errors"]),
                        "seconds": r2nd.get("seconds"),
                        "tok_in": r2nd.get("tok_in"),
                        "tok_out": r2nd.get("tok_out"),
                    }
                else:
                    out["judge2"] = {
                        "judge_model": jm2,
                        "judge2_error": "unparseable",
                    }
            else:
                out["judge2"] = {
                    "judge_model": jm2,
                    "judge2_error": r2nd.get("error", "call_failed"),
                }
    return out


# ---------------------------------------------------------------- frame → items
#: 选样层冻结产物——增删 lane = 改本元组 + 落新 jsonl（别原地改已冻结的）。
FRAMES = (
    "qualframe-mock-v1.jsonl",
    "qualframe-live-v1.jsonl",
)


def _iter_frame(path: Path):
    for ln, raw_ln in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        line = raw_ln.strip()
        if line:
            yield ln, json.loads(line)


def _items() -> list[dict]:
    """frame jsonl → 格枚举：一行一格。丢 frame 即炸（选样层完整性，
    见头注）——别静默退化成「没东西可测」。"""
    items: list[dict] = []
    for name in FRAMES:
        path = NOMINATIONS / name
        if not path.is_file():
            msg = (
                f"qualbench frame missing: {path} — frames are tracked "
                "selection artifacts; bake via specs/_qualframe.py or "
                "trim FRAMES"
            )
            raise FileNotFoundError(msg)
        stem = path.stem
        for _ln, row in _iter_frame(path):
            items.append(
                {
                    "id": row["paper"],
                    "arm": row["model"],
                    "up": row["up"],
                    "variant": (
                        f"{PROTOCOL_V}@{EPOCH}|{row['judge']}|"
                        f"{row['chunk_id']}"
                    ),
                    "lane": stem,
                    "fp_input": str(row.get("sha") or ""),
                    "params": {
                        "src": row["src"],
                        "zh": row["zh"],
                        "kind": row["kind"],
                        "src_status": row["src_status"],
                        "chunk_id": row["chunk_id"],
                        "judge": row["judge"],
                    },
                }
            )
    return items


class _Select:
    """frames/ids/judges 过滤后按 frame 序取前 n（烘焙序即 seeded 序）。

    有态：``seen`` 只数通过过滤的格——spec 每进程加载一次，一次 plan
    遍历一次，无跨 run 污染面。"""

    def __init__(self) -> None:
        self.seen = 0

    def __call__(self, item: dict, rp: dict) -> bool:
        frames_p = str(rp.get("frames") or "").strip()
        if frames_p:
            want = {s.strip() for s in frames_p.split(",") if s.strip()}
            if want and str(item.get("lane") or "") not in want:
                return False
        ids_p = str(rp.get("ids") or "").strip()
        if ids_p:
            from kernel import idnorm

            want: set[str] = set()
            for tok0 in ids_p.split(","):
                tok = tok0.strip()
                if not tok:
                    continue
                want.add(tok)
                r = idnorm.canon_id(tok)
                if r.ok and r.idc:
                    want.add(r.idc)
            raw = str(item.get("id") or "")
            if raw not in want and raw.replace("--", "/") not in want:
                return False
        judges_p = str(rp.get("judges") or "").strip()
        if judges_p:
            want_j = {s.strip() for s in judges_p.split(",") if s.strip()}
            if want_j and str(
                (item.get("params") or {}).get("judge") or ""
            ) not in want_j:
                return False
        n = int(rp.get("n") or 0)
        if n > 0 and self.seen >= n:
            return False
        self.seen += 1
        return True


# ---------------------------------------------------------------- 格函数
def _metric_view(out: dict) -> dict:
    """record → metrics 投影：标量+小列表，errors/raw/judge2 细节留给 case。"""
    m = {k: v for k, v in out.items() if k not in ("errors", "raw", "judge2")}
    j2 = out.get("judge2")
    if isinstance(j2, dict):
        m["judge2_model"] = j2.get("judge_model")
        m["judge2_stated100"] = j2.get("stated100")
        m["judge2_n_errors"] = j2.get("n_errors")
        if j2.get("judge2_error"):
            m["judge2_error"] = j2["judge2_error"]
    return m


def _judge(ctx):
    """一格：frame 行 → judge → ok/reject/error（状态映射见头注）。"""
    p = ctx.params
    pair = Pair(
        paper=ctx.idc,
        chunk_id=str(p.get("chunk_id") or ""),
        kind=str(p.get("kind") or "para"),
        model=ctx.arm,
        src=str(p.get("src") or ""),
        zh=str(p.get("zh") or ""),
        status=str(p.get("src_status") or "ok"),
    )
    sig = pair_signals(pair.src, pair.zh)
    lead = {  # 每种结局都带的分母键
        "kind": pair.kind,
        "chunk_id": pair.chunk_id,
        "src_status": pair.status,
        "sig": sig,
    }
    case = {
        "paper": pair.paper,
        "chunk_id": pair.chunk_id,
        "kind": pair.kind,
        "model": pair.model,
        "judge_param": str(p.get("judge") or ""),
        "src_status": pair.status,
        "sig": sig,
        "src": pair.src[:400],
        "zh": pair.zh[:400],
    }
    if not pair.src.strip() or not pair.zh.strip():
        case["verdict"] = "empty_pair"
        ctx.emit_case(case)
        return {
            "status": "reject",
            "errors": [{"cat": "empty_pair",
                        "msg": "blank src/zh — nothing to judge"}],
            "metrics": {"verdict": "empty_pair", **lead},
        }
    if str(p.get("judge") or "") == "mock-judge":
        # 零网关自检臂——gateway() 懒构造即付费断言，mock 格永不触网。
        parsed = mock_judge(pair)
        out = {
            "judge_model_used": "mock-judge",
            **shape_judged(parsed, pair, sig),
        }
        case.update({"verdict": "judged", **out})
        ctx.emit_case(case)
        return {
            "status": "ok",
            "metrics": {"verdict": "judged", **_metric_view(out), **lead},
        }
    out = _judge_pair(ctx, pair, sig)
    jerr = out.get("judge_error")
    if jerr and str(jerr).startswith("no_eligible_judge"):
        case.update({"verdict": "no_eligible_judge", **out})
        ctx.emit_case(case)
        return {
            "status": "reject",
            "errors": [{"cat": "no_eligible_judge", "msg": str(jerr)[:300]}],
            "metrics": {"verdict": "no_eligible_judge", **lead},
        }
    if jerr or "stated100" not in out:
        case.update({"verdict": "judge_error", **out})
        ctx.emit_case(case)
        return {
            "status": "error",
            "errors": [{
                "cat": "judge_error",
                "msg": str(jerr or out.get("error") or "call_failed")[:300],
            }],
            "metrics": {
                "verdict": "judge_error",
                "judge_model_used": out.get("judge_model_used"),
                "seconds": out.get("seconds"),
                **lead,
            },
        }
    case.update({"verdict": "judged", **out})
    ctx.emit_case(case)
    return {
        "status": "ok",
        "metrics": {"verdict": "judged", **_metric_view(out), **lead},
    }


# ---------------------------------------------------------------- spec
def _factory():
    """judge 道 paid factory：devin-2api + stream_fallback + 300s 超时。

    ``stream_fallback=True``：2026-09-19 网关非流式全模型 502、stream 独活
    的事故形态——judge 道必须能吃到流式臂（xlat 道同样理由）。模型参数
    给的是 client 默认模；每发请求显式传 judge 模型，默认值形同虚设。
    nslots=2 对齐旧 --concurrency 默认（网关 decode ~550 tok/s 自限）。"""
    from kernel import paid as paidmod

    from texlate.xlat.client import env_key_for_url

    key = env_key_for_url(DEFAULT_BASE_URL)

    def build(_ctx=None):
        return GatewayChat(
            DEFAULT_BASE_URL,
            key,
            "swe-2-max",
            stream_fallback=True,
            timeout=JUDGE_TIMEOUT,
        )

    return paidmod.GatewayFactory(
        build, prices=dict(DEFAULT_PRICES), nslots=2
    )


spec = Spec(
    kind="qualbench",
    eval=True,  # eval 全格：id 免 canon 闸、终态进 eval_records 道
    params={
        # cell 参数（frame 行 → item.params；fp=True 让内容陈旧度进 cell_fp）
        "src": Param(str, default=""),
        "zh": Param(str, default=""),
        "kind": Param(str, default="para"),
        "src_status": Param(str, default="ok"),
        # 已进 variant 的测量坐标——声明只为 schema 完整，fp=False 防双计
        "chunk_id": Param(str, default="", fp=False),
        "judge": Param(str, default="swe-2-max", fp=False),
        # 测量语义旋钮（fp=True——改动=新测量空间，不原地覆盖）
        "second_model": Param(str, default="swe-2-high"),
        "no_second": Param(bool, default=False),
        "judge_temperature": Param(float, default=0.1),
        "judge_max_tokens": Param(int, default=8192),
        # select 闸（fp=False；n 是 SELECTOR_PARAMS 自带排除）
        "frames": Param(str, default="", fp=False),
        "ids": Param(str, default="", fp=False),
        "judges": Param(str, default="", fp=False),
        "n": Param(int, default=0),
    },
    items=_items,
    select=_Select(),
    stages=[
        Stage(
            "judge",
            _judge,
            paid=True,
            eval=True,
            dedup_key=("idc", "arm", "variant"),
            status_class={
                "ok": "terminal",
                "reject": "terminal",
                "error": "retriable",
            },
        ),
    ],
    freeze_plan=True,
    executor="thread",
    same_id_serial=False,  # 格间零共享态（无 workspace/无 mutates）
    lake=False,  # frame 内联 src/zh——格函数不触湖
    code_deps=[
        "src/texlate/xlat/client.py",
        "src/texlate/xlat/_errors.py",
        "src/texlate/xlat/_dialects.py",
        "src/texlate/xlat/_discovery.py",
        "bench/py/specs/_shared.py",
    ],
    gateway_factory=_factory(),
)
