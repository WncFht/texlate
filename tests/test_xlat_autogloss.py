"""autogloss：JSON 解析四态 / 多数表决 / 归一化 / 分批封顶 / mock e2e / 掩码条款。

mock 面照 test_xlat_client 的 httpx.MockTransport 模式；base_url 用非
loopback/tailnet 地址——``chat`` 的免费集降级臂不触发，HTTP 请求数精确可钉。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from texlate.xlat import autogloss as ag
from texlate.xlat import client as cl

_BASE = "http://mock.local:3033"


def _chat_payload(content: str) -> dict[str, Any]:
    return {
        "model": "swe-2-medium",
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def _ok(content: str) -> httpx.Response:
    return httpx.Response(200, json=_chat_payload(content))


def _mock(plan: list[httpx.Response]) -> tuple[cl.ChatClient, list[httpx.Request]]:
    """按请求序回放 plan；耗尽后重复末条（批内重试同答）。返回 (client, 已收请求)。"""
    reqs: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        reqs.append(r)
        return plan[min(len(reqs), len(plan)) - 1]

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return cl.ChatClient(_BASE, "k", http=http), reqs


class TestParsePairs:
    def test_bare_array(self) -> None:
        got = ag._parse_pairs('[{"src":"OBC","tgt":"开放边界条件"}]')  # noqa: SLF001
        assert got == [("OBC", "开放边界条件")]

    def test_markdown_fence(self) -> None:
        body = '```json\n[{"src":"DMRG","tgt":"密度矩阵重整化群"}]\n```'
        assert ag._parse_pairs(body) == [("DMRG", "密度矩阵重整化群")]  # noqa: SLF001
        body2 = '```\n[{"src":"ED","tgt":"精确对角化"}]\n```'
        assert ag._parse_pairs(body2) == [("ED", "精确对角化")]  # noqa: SLF001
        body3 = '<json>[{"src":"AFC","tgt":"自动售检票"}]</json>'
        assert ag._parse_pairs(body3) == [("AFC", "自动售检票")]  # noqa: SLF001

    def test_prose_wrapped(self) -> None:
        body = 'Here are the terms:\n[{"src":"PBC","tgt":"周期边界条件"}]\nDone.'
        assert ag._parse_pairs(body) == [("PBC", "周期边界条件")]  # noqa: SLF001

    def test_bad_json_raises(self) -> None:
        with pytest.raises(ag.TermParseError):
            ag._parse_pairs("not json at all")  # noqa: SLF001
        # 可控异常——TermParseError 是 ValueError 家族
        assert issubclass(ag.TermParseError, ValueError)

    def test_non_list_raises(self) -> None:
        with pytest.raises(ag.TermParseError):
            ag._parse_pairs('{"src":"x","tgt":"y"}')  # noqa: SLF001

    def test_item_filters(self) -> None:
        body = json.dumps(
            [
                {"src": "OBC", "tgt": "开放边界条件"},
                {"src": "AI", "tgt": "AI"},  # src==tgt 短回显 → 弃
                {"src": "GPT", "tgt": "GPT"},  # src==tgt 但 ≥3 字 → 留
                {"src": "x" * 100, "tgt": "长"},  # ≥100 字 → 弃
                {"src": "[[MATH_1]]", "tgt": "数"},  # 占位符泄漏 → 弃
                {"src": "", "tgt": "空"},
                {"tgt": "缺src"},
                "junk",
            ],
            ensure_ascii=False,
        )
        got = ag._parse_pairs(body)  # noqa: SLF001
        assert got == [("OBC", "开放边界条件"), ("GPT", "GPT")]


class TestNormKey:
    def test_case_plural_whitespace_same_key(self) -> None:
        k = ag._norm_key  # noqa: SLF001
        assert k("System size") == k("system sizes") == k("system  size")

    def test_plural_guard_tails(self) -> None:
        k = ag._norm_key  # noqa: SLF001
        assert k("business") == "business"  # ss 尾不削
        assert k("analysis") == "analysis"  # is 尾不削
        assert k("status") == "status"  # us 尾不削
        assert k("sizes") == "size"  # 单词复数照样归一


class TestBatches:
    def test_two_oversize_texts_two_batches(self) -> None:
        got = ag._pack_batches(["a" * 2500, "b" * 2500], 2400)  # noqa: SLF001
        assert len(got) == 2  # noqa: PLR2004

    def test_joined_under_limit(self) -> None:
        got = ag._pack_batches(["a" * 1000, "b" * 1000], 2400)  # noqa: SLF001
        assert len(got) == 1

    def test_pick_corpus_strides_when_over_cap(self) -> None:
        srcs = ["a" * 2000, "b" * 2000, "c" * 2000]
        got = ag._pick_corpus(srcs, 4800)  # noqa: SLF001
        assert got == [srcs[0], srcs[2]]  # 等距抽样保头尾广度
        assert sum(len(t) for t in got) <= 4800  # noqa: PLR2004

    def test_pick_corpus_under_cap_passthrough(self) -> None:
        srcs = ["a" * 100, "b" * 100]
        assert ag._pick_corpus(srcs, 4800) == srcs  # noqa: SLF001


class TestExtractTerms:
    def test_merge_and_majority_vote(self) -> None:
        """同 src 三批两译 → 多数决胜（2:1）；全部批合并。"""
        plan = [
            _ok('[{"src":"OBC","tgt":"开放边界条件"}]'),
            _ok(
                '[{"src":"OBC","tgt":"开放边界"},'
                '{"src":"DMRG","tgt":"密度矩阵重整化群"}]'
            ),
            _ok('[{"src":"OBC","tgt":"开放边界条件"}]'),
        ]
        client, reqs = _mock(plan)
        texts = ["a" * 2000, "b" * 2000, "c" * 2000]
        got = asyncio.run(ag.extract_terms(texts, client, batch_chars=2400))
        assert len(reqs) == 3  # noqa: PLR2004 -- 3 批各 1 调用
        assert got == {"OBC": "开放边界条件", "DMRG": "密度矩阵重整化群"}

    def test_normalization_votes_and_keeps_original_form(self) -> None:
        """三种写法归一表决（甲 2:1 胜）；返回键留最常见原文形。"""
        plan = [
            _ok(
                '[{"src":"System size","tgt":"系统尺寸"},'
                '{"src":"system sizes","tgt":"系统尺寸"}]'
            ),
            _ok('[{"src":"system  size","tgt":"体系大小"}]'),
        ]
        client, _ = _mock(plan)
        got = asyncio.run(
            ag.extract_terms(["a" * 2000, "b" * 2000], client, batch_chars=2400)
        )
        assert got == {"System size": "系统尺寸"}

    def test_single_vote_passthrough(self) -> None:
        client, _ = _mock([_ok('[{"src":"DMRG","tgt":"密度矩阵重整化群"}]')])
        got = asyncio.run(ag.extract_terms(["a" * 500], client))
        assert got == {"DMRG": "密度矩阵重整化群"}

    def test_batch_failure_skips_not_crash(self) -> None:
        """第 2 批 500×EXTRACT_TRIES（重试尽）→ 只丢该批；第 1 批结果保留。"""
        plan = [_ok('[{"src":"OBC","tgt":"开放边界条件"}]')] + [
            httpx.Response(500, json={"e": 1})
        ] * (ag.EXTRACT_TRIES + 1)
        client, reqs = _mock(plan)
        got = asyncio.run(
            ag.extract_terms(["a" * 2000, "b" * 2000], client, batch_chars=2400)
        )
        assert got == {"OBC": "开放边界条件"}
        assert len(reqs) == 1 + ag.EXTRACT_TRIES

    def test_prompt_mask_clause_and_params(self) -> None:
        """user prompt 含掩码条款关键词 + [[X_n]] 样例；temperature/max_tokens 钉住。"""
        client, reqs = _mock([_ok("[]")])
        asyncio.run(ag.extract_terms(["a" * 100], client))
        body = json.loads(reqs[0].content)
        assert body["temperature"] == ag.EXTRACT_TEMPERATURE
        assert body["max_tokens"] == ag.EXTRACT_MAX_TOKENS
        prompt = body["messages"][0]["content"]
        assert body["messages"][0]["role"] == "user"
        assert ag.MASK_CLAUSE_KEYWORD in prompt
        assert "[[" in prompt  # [[WORD_n]] 样例在条款里

    def test_zero_results(self) -> None:
        client, reqs = _mock([_ok("[]")])
        assert asyncio.run(ag.extract_terms([], client)) == {}
        assert reqs == []  # 空输入零调用
        assert asyncio.run(ag.extract_terms(["a" * 100], client)) == {}

    def test_max_batches_caps_calls(self) -> None:
        client, reqs = _mock([_ok('[{"src":"T","tgt":"译"}]')] * 4)
        texts = ["a" * 2000, "b" * 2000, "c" * 2000, "d" * 2000]
        got = asyncio.run(
            ag.extract_terms(texts, client, batch_chars=2400, max_batches=2)
        )
        assert len(reqs) == 2  # noqa: PLR2004
        assert got == {"T": "译"}

    def test_bad_params_raise(self) -> None:
        client, _ = _mock([_ok("[]")])
        with pytest.raises(ValueError, match="batch_chars"):
            asyncio.run(ag.extract_terms(["x"], client, batch_chars=0))
        with pytest.raises(ValueError, match="max_batches"):
            asyncio.run(ag.extract_terms(["x"], client, max_batches=0))
