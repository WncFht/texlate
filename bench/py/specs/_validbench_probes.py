"""specs._validbench_probes — 对抗探针叶 (validbench 拆分叶).

docs/spec/benchmark.md §B6-2 清单 + test_validate_l0.py 防误报面; 每条断言
ok/error-rules/warn-rules. suggest= 要求至少一条 issue 带 expected+found
修复配对。``_probe_eval`` 逐条断言 → rows (pass/fail + 详情)。
"""

from __future__ import annotations

from specs import _bootstrap

_bootstrap.ensure()

from texlate.validate.l0 import Severity, validate_pair

PROBES: list[dict] = [
    {
        "id": "probe/emph_drop",
        "src": "the \\emph{key} idea",
        "zh": "关键 idea",
        "ok": True,
        "warn": ["brace", "macro"],
        "note": "合法改写掉 \\emph{...} 组: 净额一致 → warn 不阻塞",
    },
    {
        "id": "probe/src_imbalance",
        "src": "公式 ${x$ 残文。",
        "zh": "公式 ${x$ 残文（中文）。",
        "ok": True,
        "note": "src 自带 brace 不平衡被原样继承 → 不追责",
    },
    {
        "id": "probe/ph_reorder",
        "src": "the loss [[MATH_1]] of model [[REF_2]] under [[CITE_3]]",
        "zh": "模型 [[REF_2]] 的损失 [[MATH_1]] 在 [[CITE_3]] 下",
        "ok": True,
        "warn": ["placeholder"],
        "note": "of X→X 的 合法中文换序: multiset 一致 → 只 warn",
    },
    {
        "id": "probe/cite_space",
        "src": "\\cite {vaswani2017} 提出。",
        "zh": "\\cite {vaswani2017} 提出（译）。",
        "ok": True,
        "note": "\\cite {k} 命令与 { 间带空格 → key 照常计",
    },
    {
        "id": "probe/cite_key_missing",
        "src": "见 \\cite{a,b,c} 与 \\label{sec:x}。",
        "zh": "见 \\cite{a,b} 与 \\label{sec:x}。",
        "ok": False,
        "err": ["key"],
        "note": "\\cite{a,b,c}→{a,b} 漏 key → error 且点名 'c'",
        "msg_has": "'c'",
    },
    {
        "id": "probe/fullwidth_ph",
        "src": "见 [[MATH_1]]。",
        "zh": "见 【MATH_1】。",
        "ok": False,
        "err": ["placeholder"],
        "suggest": "[[MATH_1]]",
        "note": "全角【MATH_1】→ error + lev 配对修复建议",
    },
    {
        "id": "probe/bibitem_anchor",
        "src": "[[BIBITEM_1]] Vaswani et al., attention is all you need.",
        "zh": "Vaswani 等人提出注意力即一切 [[BIBITEM_1]]。",
        "ok": False,
        "err": ["placeholder"],
        "msg_has": "行首",
        "note": "BIBITEM 结构占位符脱行首 → error (E22 硬判据余量)",
    },
    {
        "id": "probe/cs_dropped",
        "src": "Bahdanau\\ et al.\\ \\cite{x} 提出。",
        "zh": "Bahdanau et al. \\cite{x} 提出。",
        "ok": False,
        "err": ["macro"],
        "msg_has": "cs_dropped",
        "note": "脆弱间距命令 \\ 丢失 → error (E22 升硬判据)",
    },
    {
        "id": "probe/fused_cs",
        "src": "Vaswani\\ 等人提出。",
        "zh": "Vaswani\\和 等人提出。",
        "ok": False,
        "err": ["macro"],
        "note": "\\ +中文熔成 \\和 = 非 ASCII 未定义 cs → error",
    },
    {
        "id": "probe/odd_dollar_inherited",
        "src": "成本是 $5 美元。",
        "zh": "成本是 $5 美元（译）。",
        "ok": True,
        "warn": ["math"],
        "note": "src 奇数 $ 被继承 → 计数一致 ok + 行内未闭合 warn",
    },
    {
        "id": "probe/halluc_key",
        "src": "见 \\cite{a}。",
        "zh": "见 \\cite{a} 和 \\cite{bogus2024}。",
        "ok": True,
        "warn": ["key"],
        "note": "幻觉新增 cite key → warn 不阻塞",
    },
    {
        "id": "probe/cite_optarg_drop",
        "src": "\\citep[see][ch.2]{vaswani2017} 所述。",
        "zh": "\\citep{vaswani2017} 所述。",
        "ok": True,
        "note": "丢可选参不追责 (key 保留)",
    },
    {
        "id": "probe/env_inherited",
        "src": "\\begin{a}x\\end{b}",
        "zh": "\\begin{a}x（译）\\end{b}",
        "ok": True,
        "note": "src 自身 begin/end 不匹配 → 继承容忍",
    },
    {
        "id": "probe/display_unpaired",
        "src": "公式 \\[ E=mc^2 \\] 如上。",
        "zh": "公式 \\[ E=mc^2 如上。",
        "ok": False,
        "err": ["math"],
        "note": "丢 \\] → \\[ \\] 计数不同 error",
    },
]


def _probe_eval() -> list[dict]:
    """逐条探针断言 → rows (pass/fail + 详情)."""
    rows = []
    for p in PROBES:
        rep = validate_pair(p["src"], p["zh"])
        fails = []
        if rep.ok != p["ok"]:
            fails.append(f"ok: expected {p['ok']} got {rep.ok}")
        fails.extend(
            f"missing error rule {rule}"
            for rule in p.get("err", [])
            if not any(
                i.rule == rule and i.severity is Severity.ERROR for i in rep.issues
            )
        )
        fails.extend(
            f"missing warn rule {rule}"
            for rule in p.get("warn", [])
            if not any(
                i.rule == rule and i.severity is Severity.WARN for i in rep.issues
            )
        )
        if "suggest" in p and not any(
            i.expected == p["suggest"] and i.found for i in rep.issues
        ):
            fails.append(f"missing suggestion for {p['suggest']}")
        if "msg_has" in p and not any(p["msg_has"] in i.message for i in rep.issues):
            fails.append(f"no message contains {p['msg_has']!r}")
        rows.append(
            {
                "id": p["id"],
                "note": p["note"],
                "expect_ok": p["ok"],
                "ok": rep.ok,
                "n_err": rep.n_error,
                "n_warn": rep.n_warn,
                "pass": not fails,
                "fails": fails,
                "issues": [i.to_dict() for i in rep.issues],
            }
        )
    return rows
