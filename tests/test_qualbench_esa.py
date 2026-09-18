"""qualbench ESA 协议（esa2）确定性件回归。

``bench/py/qualbench.py`` 经 pyproject pythonpath 直进；全部用例离线确定性——
parse/normalize/derived/flags/span/contest/route/mock/record/manifest 十路钉死，
零网络（manifest 收集用 tmp_path 落三行冻结 jsonl）。
"""

from __future__ import annotations

import json
from argparse import Namespace
from typing import TYPE_CHECKING

import pytest
import qualbench

if TYPE_CHECKING:
    from pathlib import Path

# 钉内部规范化/记账件——SLF001 豁免集中在两处别名
_norm_parsed = qualbench._norm_parsed  # noqa: SLF001 -- 钉内部件需私有触达
_mk_rec = qualbench._mk_rec  # noqa: SLF001 -- 同上


def _pair(**kw: str) -> qualbench.Pair:
    """默认干净 chunk 对（无占位符/无残留英文），kwarg 覆盖单字段。"""
    base = {
        "paper": "p1",
        "chunk_id": "c1",
        "kind": "para",
        "model": "t-model",
        "src": "Source text here.",
        "zh": "译文在此。",
    }
    base.update(kw)
    return qualbench.Pair(**base)


def _err(cat: str, sev: str, *, span: str = "s", note: str = "") -> dict:
    """构造一条规范化形态的 error dict（与 _norm_parsed 输出同形）。"""
    return {"span": span, "category": cat, "severity": sev, "note": note}


def _parsed(
    errors: list[dict] | None = None, *, stated: int = 80, derived: int | None = None
) -> dict:
    """contest_reasons 输入的最小 parsed 块（derived 缺省取 stated → Δ=0）。"""
    d = stated if derived is None else derived
    return {
        "errors": errors or [],
        "stated100": stated,
        "derived100": d,
        "score_delta": stated - d,
    }


def _sig(*, ph_missing: int = 0, ph_invented: int = 0, en_residue: int = 0) -> dict:
    """contest_reasons 输入的最小 L0 确定性信号块。"""
    return {
        "ph_missing": ph_missing,
        "ph_invented": ph_invented,
        "en_residue": en_residue,
    }


# ---------------------------------------------------------------- parse_esa_json
def test_parse_esa_json_full_fields() -> None:
    """合法 ESA JSON → errors/stated100/derived100/score_delta 全字段落地。"""
    raw = json.dumps(
        {
            "errors": [
                {
                    "span": "错词",
                    "category": "fluency-grammar",
                    "severity": "minor",
                    "note": "n",
                },
                {
                    "span": "[[",
                    "category": "convention-placeholder",
                    "severity": "major",
                    "note": "m",
                },
            ],
            "score": 80,
        }
    )
    p = qualbench.parse_esa_json(raw)
    assert p is not None
    assert p["stated100"] == 80  # noqa: PLR2004 -- 钉 score 透传
    assert p["errors"] == [
        {
            "span": "错词",
            "category": "fluency-grammar",
            "severity": "minor",
            "note": "n",
        },
        {
            "span": "[[",
            "category": "convention-placeholder",
            "severity": "major",
            "note": "m",
        },
    ]
    assert p["derived100"] == 94  # noqa: PLR2004 -- minor1+major5
    assert p["score_delta"] == -14  # noqa: PLR2004 -- 80-94
    assert p["cats_extra"] == []
    assert p["sev_clamped"] == 0


def test_parse_esa_json_fence_stripped() -> None:
    """```json/```/```JSON 围栏剥皮后照常解析。"""
    body = json.dumps({"errors": [], "score": 95})
    for raw in (
        f"```json\n{body}\n```",
        f"```\n{body}\n```",
        f"  ```JSON\n{body}\n```  ",
    ):
        p = qualbench.parse_esa_json(raw)
        assert p is not None
        assert p["stated100"] == 95  # noqa: PLR2004 -- 钉 score


def test_parse_esa_json_fallback_and_rejects() -> None:
    """非 JSON 文本首个 {...} 兜底；结构性不合格一律 None。"""
    p = qualbench.parse_esa_json('解读如下：{"errors": [], "score": 70} 以上')
    assert p is not None
    assert p["stated100"] == 70  # noqa: PLR2004 -- 兜底抽取
    bad = (
        "no json at all",
        '{"errors": [], "score": 50} tail {"x": 1}',  # 贪婪 {...} 跨两对象 → 解析失败
        '[{"errors": [], "score": 50}]',  # 顶层非 dict
        '{"errors": {}, "score": 50}',  # errors 非 list
        '{"errors": "x", "score": 50}',
        '{"score": 50}',  # 缺 errors
        '{"errors": []}',  # 缺 score
    )
    for raw in bad:
        assert qualbench.parse_esa_json(raw) is None, raw


@pytest.mark.parametrize(
    ("score", "want"),
    [
        (0, 0),
        (100, 100),
        (92.0, 92),  # 整值 float 宽容转 int
        ("92", 92),  # 数字字符串宽容转 int
        (" 92 ", 92),  # 去空白
        ("092", 92),
        (92.5, None),
        ("92.0", None),  # isdigit 拒小数点
        ("-1", None),  # isdigit 拒负号
        (-1, None),
        (101, None),
        (True, None),  # bool 显式拒
        (None, None),
    ],
)
def test_parse_esa_json_score_coercion(score: object, want: int | None) -> None:
    """score 超界/非 int/bool → None；整值 float 与数字字符串宽容转 int。"""
    p = qualbench.parse_esa_json(json.dumps({"errors": [], "score": score}))
    if want is None:
        assert p is None
    else:
        assert p is not None
        assert p["stated100"] == want


# ---------------------------------------------------------------- _norm_parsed
def test_norm_parsed_severity_clamps() -> None:
    """severity 三档外钳 minor、critical 越界钳 major，各计 sev_clamped。"""
    p = _norm_parsed(
        [
            {
                "span": "a",
                "category": "fluency-grammar",
                "severity": "bogus",
                "note": "",
            },
            {
                "span": "b",
                "category": "fluency-grammar",
                "severity": "CRITICAL",
                "note": "",
            },
            {
                "span": "c",
                "category": "non-translation",
                "severity": "critical",
                "note": "",
            },
            {
                "span": "d",
                "category": "mystery-cat",
                "severity": "critical",
                "note": "",
            },
            {
                "span": "e",
                "category": "fluency-grammar",
                "note": "",
            },  # 缺省静默 minor 不计
            {"span": "f", "category": "fluency-grammar", "severity": 5, "note": ""},
        ],
        50,
    )
    assert [e["severity"] for e in p["errors"]] == [
        "minor",
        "major",
        "critical",
        "major",
        "minor",
        "minor",
    ]
    assert p["sev_clamped"] == 4  # noqa: PLR2004 -- bogus/越界×2/非串 四处钳
    assert p["cats_extra"] == ["mystery-cat"]


def test_norm_parsed_unknown_category_kept() -> None:
    """未知类目 verbatim 保留进 errors、计 cats_extra；severity 仍吃罚分。"""
    p = _norm_parsed(
        [
            {"span": "x", "category": "locale-style", "severity": "major", "note": ""},
            {"span": "y", "category": "locale-style", "severity": "minor", "note": ""},
            {"span": "z", "category": "other-weird", "severity": "minor", "note": ""},
        ],
        60,
    )
    assert [e["category"] for e in p["errors"]] == [
        "locale-style",
        "locale-style",
        "other-weird",
    ]
    assert p["cats_extra"] == ["locale-style", "other-weird"]  # sorted(set(...))
    assert p["derived100"] == 93  # noqa: PLR2004 -- major5+minor1+minor1


def test_norm_parsed_kept_cap_and_field_norm() -> None:
    """errors 截 MAX_ERRORS_KEPT=10 在先、非 dict 跳过后；note 截 80、字段 str 化。"""
    errs: list[object] = [
        {"span": str(i), "category": "terminology", "severity": "minor", "note": ""}
        for i in range(9)
    ]
    errs.insert(3, "junk")  # 前 10 项内 1 条非 dict → 跳过 → 9
    errs.extend(
        {"span": f"z{i}", "category": "terminology", "severity": "minor", "note": ""}
        for i in range(3)
    )
    p = _norm_parsed(errs, 10)
    assert len(p["errors"]) == 9  # noqa: PLR2004 -- 12 项截 10 去 1 junk
    p2 = _norm_parsed(
        [
            {
                "span": 7,
                "category": "terminology",
                "severity": "minor",
                "note": "n" * 100,
            }
        ],
        90,
    )
    assert len(p2["errors"][0]["note"]) == 80  # noqa: PLR2004 -- note 截 80 字
    assert p2["errors"][0]["span"] == "7"  # 非 str → str() 化


# ---------------------------------------------------------------- derived100
def test_derived100_weights_top5_floor() -> None:
    """minor1/major5/critical25 取权重最高 5 条；report-only 豁免；下限 0。"""
    errors = [
        _err("non-translation", "critical"),
        _err("accuracy-addition", "critical"),
    ] + [_err("fluency-grammar", "major")] * 4
    # 6 条罚分 {25,25,5,5,5,5} → top5=65 → 35；全计应为 30——top-5 截断实证
    assert qualbench.derived100(errors) == 35  # noqa: PLR2004 -- top-5 截断
    reg = [_err("fluency-register", "major"), _err("fluency-grammar", "minor")]
    assert qualbench.derived100(reg) == 99  # noqa: PLR2004 -- register 豁免罚分
    assert qualbench.derived100([_err("non-translation", "critical")] * 5) == 0
    assert qualbench.derived100([]) == 100  # noqa: PLR2004 -- 满分基线


# ---------------------------------------------------------------- flags_of
def test_flags_of_full_mapping() -> None:
    """9 个 KNOWN_CATEGORIES 全覆盖映射；omission/non-translation 共旗去重 → 8。"""
    assert set(qualbench.KNOWN_CATEGORIES) == set(qualbench.CATEGORY_TO_FLAG)
    errors = [_err(c, "minor") for c in qualbench.KNOWN_CATEGORIES]
    assert qualbench.flags_of(errors) == [
        "untranslated_spans",  # accuracy-omission；non-translation 重旗保序去重
        "mistranslation",
        "hallucinated_content",
        "term_inconsistency",
        "over_translation",
        "placeholder_broken",
        "grammar",
        "fluency_register",
    ]
    assert len(qualbench.KNOWN_FLAGS) == 8  # noqa: PLR2004 -- 9 类目 8 flag


def test_flags_of_order_and_unknown_skip() -> None:
    """保序去重——先出现者优先；未知类目跳过不出 flag。"""
    errors = [
        _err("mystery-cat", "minor"),
        _err("terminology", "minor"),
        _err("fluency-grammar", "major"),
        _err("terminology", "major"),  # 重旗去重
    ]
    assert qualbench.flags_of(errors) == ["term_inconsistency", "grammar"]


# ---------------------------------------------------------------- verify_spans
def test_verify_spans_in_place() -> None:
    """span 为 zh 逐字子串→True；空 span/非子串→False；就地写回并返回同表。"""
    zh = "这是一段译文包含错词"
    errors = [
        _err("fluency-grammar", "minor", span="错词"),
        _err("accuracy-omission", "major", span=""),
        _err("terminology", "minor", span="不在其中"),
    ]
    out = qualbench.verify_spans(errors, zh)
    assert out is errors
    assert [e["span_verified"] for e in errors] == [True, False, False]


# ---------------------------------------------------------------- contest_reasons
def test_contest_delta_boundary() -> None:
    """|Δ|>15 触发——15 边界不触发、±16 触发。"""
    assert qualbench.contest_reasons(_parsed(stated=80, derived=65), _sig()) == []
    assert qualbench.contest_reasons(_parsed(stated=80, derived=64), _sig()) == [
        "delta_gt15"
    ]
    assert qualbench.contest_reasons(_parsed(stated=60, derived=76), _sig()) == [
        "delta_gt15"
    ]


def test_contest_stated_boundary() -> None:
    """stated≤55 触发——55 触发、56 不触发。"""
    assert qualbench.contest_reasons(_parsed(stated=55), _sig()) == ["stated_le55"]
    assert qualbench.contest_reasons(_parsed(stated=56), _sig()) == []


def test_contest_critical_and_l0() -> None:
    """critical_present 与两条 L0 信号矛盾各自独立触发。"""
    assert qualbench.contest_reasons(
        _parsed([_err("non-translation", "critical")]), _sig()
    ) == ["critical_present"]
    # ph_missing/ph_invented 任一侧信号且未报 convention-placeholder → 触发
    assert "l0_ph_unreported" in qualbench.contest_reasons(
        _parsed(), _sig(ph_missing=1)
    )
    assert "l0_ph_unreported" in qualbench.contest_reasons(
        _parsed(), _sig(ph_invented=1)
    )
    assert "l0_ph_unreported" not in qualbench.contest_reasons(
        _parsed([_err("convention-placeholder", "major")]), _sig(ph_missing=1)
    )
    # en_residue≥8 且未报 accuracy-omission/non-translation → 触发；7 不触发
    assert "l0_en_unreported" in qualbench.contest_reasons(
        _parsed(), _sig(en_residue=8)
    )
    assert "l0_en_unreported" not in qualbench.contest_reasons(
        _parsed(), _sig(en_residue=7)
    )
    assert "l0_en_unreported" not in qualbench.contest_reasons(
        _parsed([_err("accuracy-omission", "minor")]), _sig(en_residue=8)
    )
    assert "l0_en_unreported" not in qualbench.contest_reasons(
        _parsed([_err("non-translation", "critical")]), _sig(en_residue=8)
    )


def test_contest_reasons_multi_ordered() -> None:
    """多触发并发——reasons 按固定序齐出。"""
    parsed = _parsed([_err("accuracy-addition", "critical")], stated=5, derived=75)
    sig = _sig(ph_missing=1, en_residue=8)
    assert qualbench.contest_reasons(parsed, sig) == [
        "delta_gt15",
        "stated_le55",
        "critical_present",
        "l0_ph_unreported",
        "l0_en_unreported",
    ]


# ---------------------------------------------------------------- route_judge
@pytest.mark.parametrize(
    ("translator", "preferred", "want"),
    [
        ("t-model", "swe-2-max", "swe-2-max"),  # 合法 preferred 即用
        ("t-model", "custom-judge", "custom-judge"),  # 自定义透传
        ("t-model", "t-model", "swe-2-max"),  # 同型自评禁 → 池顺位
        ("t-model", "swe-2-medium", "swe-2-max"),  # banned 名 → 池顺位
        ("t-model", "", "swe-2-max"),  # 空 preferred → 池首
        ("swe-2-max", "swe-2-max", "swe-2-high"),  # preferred 撞被评 → 跳次位
        ("swe-2-high", "swe-2-medium", "swe-2-max"),  # banned → 池首
        ("swe-2-medium", "swe-2-max", "swe-2-max"),  # 被评=medium 不污染池
    ],
)
def test_route_judge(translator: str, preferred: str, want: str) -> None:
    """judge 路由：preferred 非 banned 即用，否则 JUDGE_POOL 顺位；swe-2-medium 永不任。"""
    assert qualbench.route_judge(_pair(model=translator), preferred) == want


# ---------------------------------------------------------------- mock_judge
def test_mock_judge_returns_norm_shape() -> None:
    """返回 _norm_parsed 结构（errors/stated100/derived100/score_delta/cats_extra/sev_clamped）。"""
    j = qualbench.mock_judge(_pair())
    assert set(j) == {
        "errors",
        "stated100",
        "derived100",
        "score_delta",
        "cats_extra",
        "sev_clamped",
    }


def test_mock_judge_untranslated() -> None:
    """zh==src 或空译文 → non-translation critical + stated100=5。"""
    j = qualbench.mock_judge(_pair(src="The result holds.", zh="The result holds."))
    assert j["stated100"] == 5  # noqa: PLR2004 -- 钉死未翻罚分
    assert j["errors"][0]["category"] == "non-translation"
    assert j["errors"][0]["severity"] == "critical"
    assert j["errors"][0]["span"] == "The result holds."
    j2 = qualbench.mock_judge(_pair(src="x", zh="  "))
    assert j2["errors"][0]["category"] == "non-translation"
    assert j2["stated100"] == 5  # noqa: PLR2004 -- 同上


def test_mock_judge_placeholder() -> None:
    """占位符缺失 → convention-placeholder major；stated=100-10-15=75。"""
    j = qualbench.mock_judge(_pair(src="Eq [[MATH_1]] holds.", zh="公式成立。"))
    assert j["errors"] == [
        {
            "span": "[[",
            "category": "convention-placeholder",
            "severity": "major",
            "note": "placeholder mismatch",
        }
    ]
    assert j["stated100"] == 75  # noqa: PLR2004 -- 100-10*1-15


def test_mock_judge_en_residue() -> None:
    """en_residue≥8 → accuracy-omission major（span=首个残留词）；3-7 → minor。"""
    j8 = qualbench.mock_judge(
        _pair(src="src text here", zh="alpha beta gamma delta epsilon zeta theta kappa")
    )
    assert j8["errors"][0]["category"] == "accuracy-omission"
    assert j8["errors"][0]["severity"] == "major"
    assert j8["errors"][0]["span"] == "alpha"
    assert j8["errors"][0]["note"] == "en_residue=8"
    j3 = qualbench.mock_judge(_pair(src="src text here", zh="alpha beta gamma"))
    assert j3["errors"][0]["severity"] == "minor"
    assert j3["errors"][0]["span"] == "alpha beta gamma"  # zh[:40]
    assert j3["errors"][0]["note"] == "en_residue=3"


def test_mock_judge_clean_deterministic() -> None:
    """无错 chunk → errors=[]、derived=100、stated 由 key sha 确定性取 90/97。"""
    pair = _pair(src="The proof is complete.", zh="证明完毕。")
    j = qualbench.mock_judge(pair)
    assert j["errors"] == []
    assert j["derived100"] == 100  # noqa: PLR2004 -- 无错满分
    assert j["stated100"] in (90, 97)
    assert qualbench.mock_judge(pair)["stated100"] == j["stated100"]


# ---------------------------------------------------------------- pair_signals
def test_pair_signals_ph_and_residue() -> None:
    """ph_missing/ph_invented 差集计数；en_residue 剥占位符/控制序列后 ≥4 字母词。"""
    sig = qualbench.pair_signals(
        "See [[MATH_1]] and [[CITE_2]].", "见 [[MATH_1]] [[REF_9]]。"
    )
    assert (sig["ph_missing"], sig["ph_invented"]) == (1, 1)
    sig2 = qualbench.pair_signals("x", "结果是 good 且 correct \\cmd [[MATH_1]] end")
    assert sig2["en_residue"] == 2  # noqa: PLR2004 -- good/correct；\\cmd/end 不计


# ---------------------------------------------------------------- shape_judged
def test_shape_judged_field_block() -> None:
    """parsed+pair+sig → record 判定块：span 校验就地写回、flags/contested 合成。"""
    pair = _pair(src="S", zh="这是错词译文")
    parsed = _norm_parsed(
        [
            {
                "span": "错词",
                "category": "fluency-grammar",
                "severity": "minor",
                "note": "",
            },
            {
                "span": "不在",
                "category": "terminology",
                "severity": "major",
                "note": "",
            },
        ],
        94,
    )
    j = qualbench.shape_judged(parsed, pair, qualbench.pair_signals(pair.src, pair.zh))
    assert j["score"] == j["stated100"] == 94  # noqa: PLR2004 -- 主分=stated
    assert j["derived100"] == 94  # noqa: PLR2004 -- minor1+major5
    assert j["score_delta"] == 0
    assert j["n_errors"] == 2  # noqa: PLR2004 -- 两条 error
    assert j["n_span_unverified"] == 1
    assert j["sev_counts"] == {"minor": 1, "major": 1, "critical": 0}
    assert j["flags"] == ["grammar", "term_inconsistency"]
    assert j["contested"] is False
    assert j["contest_reasons"] == []
    assert parsed["errors"][0]["span_verified"] is True
    assert parsed["errors"][1]["span_verified"] is False


# ---------------------------------------------------------------- _mk_rec
def test_mk_rec_key_protocol_and_fields() -> None:
    """key 形如 {model}|{paper}|{chunk}|{judge}|esa2——protocol_v 入 key 防旧协议截留。"""
    pair = _pair(paper="hep/1", chunk_id="c7", model="m-x")
    rec = _mk_rec(pair, "judge-y", {"stated100": 88, "tok_in": None, "errors": []})
    assert rec["key"] == "m-x|hep/1|c7|judge-y|esa2"
    assert pair.key == "m-x|hep/1|c7"  # pair.key 无 judge/protocol（arm 亦不入）
    assert rec["protocol_v"] == "esa2"
    assert rec["judge_model"] == "judge-y"
    assert rec["stated100"] == 88  # noqa: PLR2004 -- 钉 judge 字段并入
    assert "tok_in" not in rec  # None 值字段不落账
    assert rec["arm"] is None  # 空 arm → None
    assert rec["ph_missing"] == 0  # 确定性信号并入
    assert rec["src_excerpt"] == pair.src[:160]
    assert rec["zh_excerpt"] == pair.zh[:160]


# ---------------------------------------------------------------- collect_manifest_pairs
def test_collect_manifest_pairs(tmp_path: Path) -> None:
    """冻结 sample.jsonl → Pair 字段落地；src/source、zh/translation 别名兼容。"""
    f = tmp_path / "sample.jsonl"
    rows = [
        {
            "paper": "p1",
            "chunk_id": "c1",
            "kind": "caption",
            "model": "m1",
            "src": "S1",
            "zh": "Z1",
            "arm": "a1",
            "status": "partial",
        },
        {"paper": "p2", "chunk_id": "c2", "source": "S2", "translation": "Z2"},
        {
            "paper": "p3",
            "chunk_id": "c3",
            "src": "",
            "source": "S3",
            "zh": "",
            "translation": "Z3",
        },  # 空串 falsy 同样回退别名
    ]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    pairs, meta = qualbench.collect_manifest_pairs(Namespace(manifest=str(f), n=0))
    p1, p2, p3 = pairs
    assert (
        p1.paper,
        p1.chunk_id,
        p1.kind,
        p1.model,
        p1.src,
        p1.zh,
        p1.arm,
        p1.status,
    ) == ("p1", "c1", "caption", "m1", "S1", "Z1", "a1", "partial")
    assert (p2.kind, p2.model, p2.src, p2.zh, p2.arm, p2.status) == (
        "para",
        "?",
        "S2",
        "Z2",
        "",
        "ok",
    )
    assert (p3.src, p3.zh) == ("S3", "Z3")
    assert meta["manifest"] == str(f)
    assert {e["id"]: e["n_pairs"] for e in meta["papers"]} == {
        "p1": 1,
        "p2": 1,
        "p3": 1,
    }
    pairs2, _ = qualbench.collect_manifest_pairs(Namespace(manifest=str(f), n=1))
    assert len(pairs2) == 1
