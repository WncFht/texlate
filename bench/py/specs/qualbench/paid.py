"""specs.qualbench.paid — qualbench judge paid 通道叶（_judge_call/_judge_pair）。

每发 ``session.request`` 走 ChatClient 内层重试梯队；judge_fallback 闸拒
记降级响应；contested 触发二裁逐行移植。ctx/gateway 由格函数注入。
"""

from __future__ import annotations

import time

from specs.qualbench.const import JUDGE_RETRY_SUFFIX, JUDGE_SYSTEM
from specs.qualbench.judge import (
    Pair,
    flags_of,
    judge_user_prompt,
    parse_esa_json,
    route_judge,
    shape_judged,
    verify_spans,
)


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
            options=ChatOptions(temperature=temperature, max_tokens=max_tokens),
        )
    except ChatError as e:
        # 梯队已尽（retryable 内部翻身用过）→ judge_error 交格级重跑；
        # 非 ChatError（含 kernel paid 例外族）不外接，直穿内核映射。
        return {"error": f"{type(e).__name__}: {e}"[:300]}
    dt = round(time.monotonic() - t0, 2)
    if not isinstance(res, dict):
        return {"error": f"bad_session_result:{type(res).__name__}", "seconds": dt}
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
