"""specs.qualbench.judge — qualbench 判定纯逻辑叶（Pair + 确定性信号 + ESA 解析/路由/shape）。

零网关零 I/O 面：mock_judge/parse_esa_json/route_judge 全部可离线复算；
付费调用在 ``qualbench.paid`` 叶。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from specs.qualbench.const import (
    CATEGORY_TO_FLAG,
    CRITICAL_CATS,
    CS_RX,
    DELTA_CONTEST,
    EN_RESIDUE_CONTEST,
    EN_WORD_RX,
    JSON_FENCE_RX,
    JSON_OBJ_RX,
    JUDGE_BANNED,
    JUDGE_POOL,
    KNOWN_CATEGORIES,
    MAX_ERRORS,
    MAX_ERRORS_KEPT,
    PH_TOKEN_RX,
    REPORT_ONLY_CATS,
    SEV_WEIGHT,
    STATED_CONTEST,
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
    """contested 触发：|Δ|>15 / stated≤55 / 任一 critical / rules 信号矛盾。"""
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
        "n_span_unverified": sum(1 for e in parsed["errors"] if not e["span_verified"]),
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
