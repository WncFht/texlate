#!/usr/bin/env python3
r"""validbench — B6 校验段基准 harness（docs/10 §B6 产品化）.

测 ``texlate.validate`` 对 LLM 译文破坏的检出能力：校验器本身必须被语料验证。

流程:
  1. 底材: bench/corpus_v2/{id}/extracted/ 主文件 → ``texlate.latex.parse_file``
     抽干净 chunk → ph 层 (src=chunk.content 含 [[TYPE_n]]) / raw 层
     (占位符不动点展开回原文, 模拟组装后文档校验) 两层 src↔zh 对,
     zh = 构造性伪译文 (机械不变量全保留, 拉丁词→确定性汉字).
  2. 变异器: 10 类破坏照搬 tmp/exp/rule-validator/gen_cases.py (c01–c10),
     逐 (pair,level,kind) 落 cases.jsonl. 破坏类↔L0 规则覆盖核对:
     c01→brace c02→math c03/c04→env c05/c06/c10→placeholder
     c07→math c08→macro c09→key —— 七规则全被触达.
  3. 对抗探针: 边界行为逐条断言 (合法改写/src 自带不平衡/换序/带空格
     \cite/漏 key/全角【】/BIBITEM 脱锚/cs_dropped/融合 cs/奇数$继承/
     幻觉 key/丢可选参/env 继承/丢 \]) —— 与 tests/test_validate_l0.py
     同口径的防误报面.
  4. 跑测: L0 ``validate_pair`` 逐 case 计时; L1 ``TsValidator`` 常驻模式
     (sign(src)→baseline, validate(zh, baseline, expect)) —— node/bench/ts
     依赖在场才跑, 绝对/相对判定分开报.
  5. --replay 旧 cases.jsonl 可直接复评 (spike 1636 例回归集同 schema).

用法:
  uv run python bench/py/validbench.py [--corpus DIR] [--max-per-paper N]
      [--papers N] [--paper SUBSTR] [--out DIR] [--no-l1] [--check]
      [--replay cases.jsonl]
产出 (docs/10 §统一产出契约): OUT/{cases.jsonl,probes.jsonl,cells.json,summary.md}

门槛 (--check): 10 类破坏 L0 100% 检出、干净对 0 error-FP、探针全过、
L0 摊薄 ≤1ms/对 (总 wall/对数, 与 spike 0.57ms/对 同口径; 逐对计时
的长尾单列). 退出码 0/1.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import random
import re
import signal
import sys
import time
import zlib
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from texlate.latex import parse_file
from texlate.validate import l0
from texlate.validate.l0 import Severity, validate_pair

BENCH = ROOT / "bench"
CORPUS_V2 = BENCH / "corpus_v2"
BENCH_TS_NM = (
    BENCH / "ts" / "node_modules"
)  # dev 态 L1 依赖 (同 tests/test_validate_l1)

SEED = 20260915
MIN_LEN, MAX_LEN = 40, 4000
PARSE_TIMEOUT_S = 30

# ---------------------------------------------------------------- 伪译文
# (tmp/exp/rule-validator/gen_cases.py 原样移植; PH_RX 换产品 l0.PH_ANY_LIKE_RX —
# 产品版额外认 [[SL]]/[[PL]] 无数字后缀形态, 是 spike 正则的超集.)

VOCAB = (  # noqa: SIM905 — 紧凑词表, 200 元素 list 字面量反而难读
    "研究 方法 结果 模型 数据 分析 实验 表明 本文 提出 算法 网络 训练 参数 "
    "函数 定理 证明 引理 误差 分布 样本 优化 梯度 矩阵 向量 概率 随机 变量 "
    "近似 收敛 序列 空间 映射 算子 方程 维数 拓扑 流形 极限 连续 微分 积分 "
    "级数 变换 特征 性质 构造 存在 唯一 定义 假设 推论 注记 例子 应用 讨论 "
    "结论 文献 综述 问题 理论 框架 技术 过程 系统 结构 性能 精度 复杂度 "
    "规模 实例 条件 目标 策略 步骤 模块 测试 评估 比较 基线 提升 影响 机制 "
    "原理 方案 效果 优势 局限 贡献 概述 记号 约定 术语 单位 索引 摘要 引言 "
    "背景 动机 章节 图表 公式 段落 估计 观测 信号 频谱 信道 编码 译码"
).split()

# 参数必须原样保留的命令 (key/env名/文件路径 — 翻掉即机械错误)
KEEP_ARG_RX = re.compile(
    r"^(cite[a-zA-Z]*|[a-zA-Z@]*ref|crefrange|label|bibitem|nocite"
    r"|begin|end|documentclass|documentstyle|usepackage|RequirePackage"
    r"|input|include|includegraphics|bibliography|bibliographystyle"
    r"|newtheorem|newenvironment|newcounter|href|url|path|verb)$"
)

MATH_ENV_NAMES = {
    "equation",
    "align",
    "gather",
    "multline",
    "eqnarray",
    "displaymath",
    "math",
}


def _cjk_for(w: str) -> str:
    h = zlib.crc32(w.lower().encode())
    t = VOCAB[h % len(VOCAB)]
    if len(w) >= 7:
        t += VOCAB[(h >> 9) % len(VOCAB)]
    return t


def _find_env_end(s: str, i: int, env: str) -> int | None:
    pat = "\\end{" + env + "}"
    k = s.find(pat, i)
    return None if k < 0 else k + len(pat)


def pseudo_translate(src: str) -> str:
    """构造性伪译文: 拉丁词->确定性汉字, 其余机械要素原样保留."""
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        m = l0.PH_ANY_LIKE_RX.match(src, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        c = src[i]
        if c == "%":  # 注释原样
            k = src.find("\n", i)
            j = n if k < 0 else k
            out.append(src[i:j])
            i = j
            continue
        if c == "\\":
            j = i + 1
            if j < n and src[j].isalpha():
                k = j
                while k < n and (src[k].isalpha() or src[k] == "@"):
                    k += 1
                name = src[j:k]
                out.append(src[i:k])
                i = k
                if i < n and src[i] == "*":
                    out.append("*")
                    i += 1
                # key/结构参数原样保留
                if KEEP_ARG_RX.match(name):
                    for _ in range(4):
                        p = i
                        # TeX 控制字吞后续空白含换行 (\cite\n{k} ≡ \cite{k}),
                        # 与 l0.KEY_CMD_RX 的 \s*\{ 同口径 —— 不吃 \n 会把
                        # {key} 留给拉丁词翻译路径翻掉 (实测 key 误报来源)
                        while p < n and src[p] in " \t\n":
                            p += 1
                        if p < n and src[p] in "{[":
                            close = "}" if src[p] == "{" else "]"
                            depth = 0
                            q = p
                            while q < n:
                                if src[q] == "\\":
                                    q += 2
                                    continue
                                if src[q] == src[p]:
                                    depth += 1
                                elif src[q] == close:
                                    depth -= 1
                                    if depth == 0:
                                        break
                                q += 1
                            e = min(q + 1, n)
                            out.append(src[i:e])
                            i = e
                        else:
                            break
                    # 数学环境整体原样
                    if name == "begin":
                        m2 = re.search(r"\{([^{}]*)\}\s*$", "".join(out[-2:]))
                        env = m2.group(1).strip() if m2 else None
                        if env in MATH_ENV_NAMES:
                            e2 = _find_env_end(src, i, env)
                            if e2:
                                out.append(src[i:e2])
                                i = e2
                continue
            out.append(src[i : min(i + 2, n)])  # 控制符号 \{ \% \[ 原样
            i += 2
            continue
        if c == "$":  # 数学区间原样 ($..$ / $$..$$)
            dd = 2 if src.startswith("$$", i) else 1
            k = i + dd
            while k < n:
                if src[k] == "\\":
                    k += 2
                    continue
                if src.startswith("$" * dd, k):
                    break
                if src[k] == "\n" and k + 1 < n and src[k + 1] == "\n":
                    break
                k += 1
            if k < n and src.startswith("$" * dd, k):
                out.append(src[i : k + dd])
                i = k + dd
            else:
                out.append("$" * dd)
                i += dd
            continue
        if c.isascii() and c.isalpha():  # 拉丁词 -> 汉字
            j = i
            while j < n and src[j].isascii() and src[j].isalpha():
                j += 1
            out.append(_cjk_for(src[i:j]))
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def rehydrate(s: str, ph_map: dict[str, str]) -> str:
    r"""占位符不动点展开 -> 原始 LaTeX (含 \cite{key}/$/\begin)."""
    for _ in range(20):
        ns = s
        for ph, body in ph_map.items():
            if ph in ns:
                ns = ns.replace(ph, body)
        if ns == s:
            break
        s = ns
    return s


# ---------------------------------------------------------------- 破坏算子
# (gen_cases.py c01–c10 照搬; rv.PH_RX/KEY_CMD_RX → l0.PH_ANY_LIKE_RX/KEY_CMD_RX 同口径.
#  产品化修订 (全部有实测漏检出典): 候选一律限注释区外 (l0 规则经 _no_comments
#  豁免注释, 注释内破坏是语义 no-op); c06 修 `]` 补回合法 token 的自愈路径与
#  裸标记无数字回退; c07 用 _lex bs token 选真定界符 (\\[5pt] 的 \[ 不算);
#  c09 跳过空 key 匹配如 \bibitem[]{}; c08/c10 插入位按"前一字符在注释内即死".)


def _comment_spans(s: str) -> list[int]:
    """注释区间 [start,end) 排序扁平表 (l0._lex 的 cmt token), 供 bisect 查."""
    spans: list[int] = []
    for kind, text, pos in l0._lex(s):
        if kind == "cmt":
            spans += [pos, pos + len(text)]
    return spans


def _in_comment(spans: list[int], pos: int) -> bool:
    """``pos`` 落在注释区间 → True (spans 为扁平 [s0,e0,s1,e1,...])."""
    i = bisect.bisect_right(spans, pos)
    return bool(i % 2)


def _live_positions(positions: list[int], spans: list[int]) -> list[int]:
    """过滤掉注释内的候选位."""
    return [p for p in positions if not _in_comment(spans, p)]


def _live_insert_positions(s: str, spans: list[int]) -> list[int]:
    """可插入位: 落在 ``pos`` 的文本拼进 ``s[pos-1]`` 所在词法区 ——
    ``pos-1`` 在注释内即注释内插入 (含注释行尾 ``\\n`` 前位, 实测漏检来源)."""
    return [p for p in range(len(s) + 1) if p == 0 or not _in_comment(spans, p - 1)]


def _unescaped_positions(s: str, ch: str) -> list[int]:
    out = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == "%":
            k = s.find("\n", i)
            i = n if k < 0 else k
            continue
        if s[i] == ch:
            out.append(i)
        i += 1
    return out


def c01_drop_rbrace(zh: str, rng: random.Random) -> str | None:
    pos = _unescaped_positions(zh, "}")
    if not pos:
        return None
    p = pos[rng.randrange(len(pos))]
    return zh[:p] + zh[p + 1 :]


def c02_drop_dollar(zh: str, rng: random.Random) -> str | None:
    pos = _unescaped_positions(zh, "$")
    if not pos:
        return None
    p = pos[rng.randrange(len(pos))]
    return zh[:p] + zh[p + 1 :]


_END_RX = re.compile(r"\\end\{[^{}]*\}")


def c03_rename_end(zh: str, rng: random.Random) -> str | None:
    spans = _comment_spans(zh)
    ms = [m for m in _END_RX.finditer(zh) if not _in_comment(spans, m.start())]
    if not ms:
        return None
    begins = {m.group(1) for m in re.finditer(r"\\begin\{([^{}]*)\}", zh)}
    m = ms[rng.randrange(len(ms))]
    name = re.match(r"\\end\{([^{}]*)\}", m.group(0)).group(1)
    alts = [b for b in begins if b != name]
    new = rng.choice(alts) if alts else name + "*"
    return zh[: m.start()] + "\\end{" + new + "}" + zh[m.end() :]


def c04_drop_end(zh: str, rng: random.Random) -> str | None:
    spans = _comment_spans(zh)
    ms = [m for m in _END_RX.finditer(zh) if not _in_comment(spans, m.start())]
    if not ms:
        return None
    m = ms[rng.randrange(len(ms))]
    return zh[: m.start()] + zh[m.end() :]


def c05_drop_ph(zh: str, rng: random.Random) -> str | None:
    spans = _comment_spans(zh)
    ms = [
        m for m in l0.PH_ANY_LIKE_RX.finditer(zh) if not _in_comment(spans, m.start())
    ]
    if not ms:
        return None
    m = ms[rng.randrange(len(ms))]
    return zh[: m.start()] + zh[m.end() :]


def c06_typo_ph(zh: str, rng: random.Random) -> str | None:
    spans = _comment_spans(zh)
    ms = [
        m for m in l0.PH_ANY_LIKE_RX.finditer(zh) if not _in_comment(spans, m.start())
    ]
    if not ms:
        return None
    m = ms[rng.randrange(len(ms))]
    tok = m.group(0)
    inner = tok[2:-2]
    # 变体菜单; 某些变体在特定上下文是语义 no-op 要避开:
    #   v1 掉 ] —— 若 match 后紧跟 ] (如 [[REF_1]]] 外层括号), 截断后与残余 ]
    #       重新拼成合法 token → 自愈, 校验器正确地无报 → 该上下文禁选 v1
    #   v2 改数字 index —— 裸标记 ([[SL]] 无 \d+) 无 index 可改 → 回退 v0
    variants = []
    inner2 = inner[:-1] + ("Z" if inner[-1] != "Z" else "Y")
    variants.append("[[" + inner2 + "]]")  # v0: 内部末字符改字母 lev=1
    if zh[m.end() : m.end() + 1] != "]":
        variants.append(tok[:-1])  # v1: 掉一个 ] lev=1
    d = re.search(r"\d+", inner)
    if d:
        variants.append(
            "[[%s%d]]" % (inner[: d.start()], int(d.group(0)) + 7)
        )  # v2: 合法 token 集合错位 lev<=2
    new = variants[rng.randrange(len(variants))]
    return zh[: m.start()] + new + zh[m.end() :]


def c07_unpair_lbrack(zh: str, rng: random.Random) -> str | None:
    # 候选取 l0._lex 的 bs token —— 正则 \\\] 会把 \\[5pt] 的 \[ (linebreak
    # 可选参, 非 display 定界符) 算进来, 删了不在 math 词表 = 语义 no-op
    # (实测漏检来源); bs token 自带注释/转义豁免.
    rb = [pos for kind, text, pos in l0._lex(zh) if kind == "bs" and text == "\\]"]
    if rb:
        p = rb[rng.randrange(len(rb))]
        return zh[:p] + zh[p + 2 :]
    lb = [pos for kind, text, pos in l0._lex(zh) if kind == "bs" and text == "\\["]
    if not lb:
        return None
    p = lb[rng.randrange(len(lb))]
    return zh[:p] + zh[p + 2 :]


def c08_halluc_macro(zh: str, rng: random.Random) -> str | None:
    ins = "\\newcommand{\\zhxbox}[1]{\\fbox{#1}}\\zhxbox{译注}"
    live = _live_insert_positions(zh, _comment_spans(zh))
    pos = live[rng.randrange(len(live))]
    return zh[:pos] + "\n" + ins + "\n" + zh[pos:]


def c09_drop_key(zh: str, rng: random.Random) -> str | None:
    spans = _comment_spans(zh)
    ms = [
        m
        for m in l0.KEY_CMD_RX.finditer(zh)
        if not _in_comment(spans, m.start())
        and any(k.strip() for k in m.group(1).split(","))  # 空 key 不计多重集
    ]
    if not ms:
        return None
    m = ms[rng.randrange(len(ms))]
    return zh[: m.start()] + zh[m.end() :]


def c10_extra_ph(zh: str, rng: random.Random) -> str | None:
    live = _live_insert_positions(zh, _comment_spans(zh))
    pos = live[rng.randrange(len(live))]
    return zh[:pos] + "[[MATH_9999]]" + zh[pos:]


CORRUPTIONS = [
    ("c01_drop_rbrace", c01_drop_rbrace),
    ("c02_drop_dollar", c02_drop_dollar),
    ("c03_rename_end", c03_rename_end),
    ("c04_drop_end", c04_drop_end),
    ("c05_drop_ph", c05_drop_ph),
    ("c06_typo_ph", c06_typo_ph),
    ("c07_unpair_lbrack", c07_unpair_lbrack),
    ("c08_halluc_macro", c08_halluc_macro),
    ("c09_drop_key", c09_drop_key),
    ("c10_extra_ph", c10_extra_ph),
]

# ---------------------------------------------------------------- 对抗探针
# docs/10 §B6-2 清单 + test_validate_l0.py 防误报面; 每条断言 ok/error-rules/
# warn-rules. suggest= 要求至少一条 issue 带 expected+found 修复配对.

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


# ---------------------------------------------------------------- 语料底材

_DOCCLASS_RX = re.compile(
    r"\\(documentclass|documentstyle)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}",
    re.DOTALL,
)


def _paper_dirs(corpus: Path) -> list[Path]:
    """corpus 下含 extracted/ 的目录 (old-style 按 archive/name 嵌套一层)."""
    out = [p.parent for p in sorted(corpus.rglob("extracted")) if p.is_dir()]
    return sorted(out, key=lambda d: str(d.relative_to(corpus)))


def _pick_root(pdir: Path) -> Path | None:
    """剥注释含 \\documentclass/\\documentstyle 者为主文件; 无则最大 .tex."""
    texs = sorted((pdir / "extracted").rglob("*.tex"))
    if not texs:
        return None
    roots = []
    for f in texs:
        try:
            tex = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _DOCCLASS_RX.search(l0._no_comments(tex)):
            roots.append(f)
    if roots:
        return roots[0]
    return max(texs, key=lambda f: f.stat().st_size)


class _ParseTimeout(Exception):
    pass


def _alarm_handler(_sig, _frm) -> None:
    raise _ParseTimeout


def gen_cases(
    corpus: Path,
    *,
    max_per_paper: int,
    min_len: int,
    max_len: int,
    seed: int,
    paper_filter: str | None,
    papers_limit: int,
) -> tuple[list[dict], dict]:
    """逐 paper parse_file → 干净 chunk → ph/raw 两层对 × clean+10 类破坏."""
    rng = random.Random(seed)
    cases: list[dict] = []
    stats = {"papers_seen": 0, "papers_used": 0, "parse_fail": [], "pairs": 0}
    dirs = _paper_dirs(corpus)
    if paper_filter:
        dirs = [d for d in dirs if paper_filter in str(d.relative_to(corpus))]
    if papers_limit:
        dirs = dirs[:papers_limit]
    for pdir in dirs:
        pid = str(pdir.relative_to(corpus))
        stats["papers_seen"] += 1
        root = _pick_root(pdir)
        if root is None:
            continue
        old = signal.signal(signal.SIGALRM, _alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, PARSE_TIMEOUT_S)
        try:
            res = parse_file(root)
        except Exception as e:
            stats["parse_fail"].append({"paper": pid, "err": repr(e)[:200]})
            continue
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
        chunks = [c for c in res.chunks if min_len <= len(c.content) <= max_len]
        rng.shuffle(chunks)
        picked = chunks[:max_per_paper]
        n_pairs = 0
        for c in picked:
            for level, src in (
                ("ph", c.content),
                ("raw", rehydrate(c.content, res.ph_map)),
            ):
                if level == "raw" and src == c.content:
                    continue  # 无占位符 -> 与 ph 层重复
                zh = pseudo_translate(src)
                cid = f"{pid}/c{c.id}/{level}"
                cases.append(
                    {
                        "id": cid + "/clean",
                        "paper": pid,
                        "chunk": c.id,
                        "level": level,
                        "kind": "clean",
                        "src": src,
                        "zh": zh,
                    }
                )
                n_pairs += 1
                for kind, fn in CORRUPTIONS:
                    crng = random.Random(zlib.crc32((cid + kind).encode()))
                    bad = fn(zh, crng)
                    if bad is None:
                        continue
                    cases.append(
                        {
                            "id": f"{cid}/{kind}",
                            "paper": pid,
                            "chunk": c.id,
                            "level": level,
                            "kind": kind,
                            "src": src,
                            "zh": bad,
                        }
                    )
        stats["papers_used"] += 1 if n_pairs else 0
        stats["pairs"] += n_pairs
        print(
            f"  {pid}: root={root.name} chunks={len(res.chunks)} "
            f"picked={len(picked)} pairs+={n_pairs}"
        )
    return cases, stats


# ---------------------------------------------------------------- 评测


def _l0_eval(cases: list[dict]) -> float:
    """逐 case 跑 validate_pair, 结果+耗时写回 case['l0']; 返回总 wall (s)."""
    t_all = time.perf_counter()
    for cs in cases:
        t0 = time.perf_counter_ns()
        rep = validate_pair(cs["src"], cs["zh"])
        ms = (time.perf_counter_ns() - t0) / 1e6
        cs["l0"] = {
            "ok": rep.ok,
            "n_err": rep.n_error,
            "n_warn": rep.n_warn,
            "rules_err": sorted(
                {i.rule for i in rep.issues if i.severity is Severity.ERROR}
            ),
            "rules_warn": sorted(
                {i.rule for i in rep.issues if i.severity is Severity.WARN}
            ),
            "suggest": sum(1 for i in rep.issues if i.expected and i.found),
            "ms": round(ms, 4),
        }
    return time.perf_counter() - t_all


def _expect_names(src: str) -> list[str]:
    """src 内 [[TYPE_n]] → worker expect 契约名 (剥括号)."""
    return [m[2:-2] for m in l0.PH_ANY_LIKE_RX.findall(src)]


def _l1_eval(cases: list[dict]) -> str | None:
    """常驻 TsValidator 跑同口径; 返回不可用原因 (None=跑了)."""
    try:
        from texlate.validate.l1 import TsValidator
    except ImportError as e:
        return f"import l1 失败: {e}"
    node_path = BENCH_TS_NM if (BENCH_TS_NM / "tree-sitter").is_dir() else None
    v = TsValidator(node_path=node_path)
    if not v.available():
        return "node/tree-sitter 依赖不在场 (TEXLATE_TS_NODE_PATH 可指)"
    # baseline 缓存: 同 (paper,chunk,level) 组共享 src
    baselines: dict[tuple, object] = {}
    with v as daemon:
        for cs in cases:
            key = (cs["paper"], cs["chunk"], cs["level"])
            if key not in baselines:
                baselines[key] = daemon.sign(cs["src"], doc_id=f"{cs['id']}#src")
            res = daemon.validate(
                cs["zh"],
                baseline=baselines[key],
                expect=_expect_names(cs["src"]),
                doc_id=cs["id"],
            )
            ph = res.placeholders
            cs["l1"] = {
                "ok": res.ok,
                "ok_rel": res.ok_relative,
                "detected": not res.verdict_ok,
                "parse_ms": res.parse_ms,
                "signals": {
                    "err": len(res.parse_errors),
                    "env": len(res.env_mismatches),
                    "math": res.unclosed_math,
                    "brace": res.brace_balance,
                    "ph_miss": len(ph.get("missing", [])),
                    "ph_unexp": len(ph.get("unexpected", [])),
                    "ph_typo": len(ph.get("typos", [])),
                },
            }
            if res.error:
                cs["l1"]["error"] = res.error
    return None


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


# ---------------------------------------------------------------- 聚合/报告


def _pct(vals: list[float]) -> dict:
    """min/p50/p95/max/mean (最近秩分位)."""
    if not vals:
        return {}
    s = sorted(vals)

    def q(x: float) -> float:
        return s[max(0, math.ceil(x * len(s)) - 1)]

    return {
        "n": len(s),
        "mean": round(sum(s) / len(s), 4),
        "p50": round(q(0.50), 4),
        "p95": round(q(0.95), 4),
        "max": round(s[-1], 4),
    }


def aggregate(
    cases: list[dict], probe_rows: list[dict], l1_note: str | None, l0_wall_s: float
) -> dict:
    """kind×level 检出表 + 干净 FP + 探针 + 延迟 + 门槛."""
    agg: dict[tuple[str, str], list] = defaultdict(list)
    for cs in cases:
        agg[(cs["kind"], cs["level"])].append(cs)

    by_kind_level = []
    for kind in sorted({c["kind"] for c in cases}):
        for level in ("ph", "raw"):
            rs = agg.get((kind, level))
            if not rs:
                continue
            det = [c for c in rs if not c["l0"]["ok"]]
            rules = Counter(x for c in rs for x in c["l0"]["rules_err"])
            sugg = sum(1 for c in rs if c["l0"]["suggest"])
            row = {
                "kind": kind,
                "level": level,
                "n": len(rs),
                "detected": len(det),
                "rate": len(det) / len(rs),
                "rules_err": dict(rules.most_common()),
                "suggest_n": sugg,
                "missed": [c["id"] for c in rs if c["l0"]["ok"]],
            }
            if "l1" in rs[0]:
                row["l1"] = {
                    "det_rel": sum(1 for c in rs if c["l1"]["detected"]),
                    "det_abs": sum(1 for c in rs if not c["l1"]["ok"]),
                    "n": len(rs),
                }
            by_kind_level.append(row)

    clean = [c for c in cases if c["kind"] == "clean"]
    fp = [c for c in clean if not c["l0"]["ok"]]
    fp_rules = Counter(x for c in fp for x in c["l0"]["rules_err"])
    warn_only = [c for c in clean if c["l0"]["ok"] and c["l0"]["n_warn"]]
    lat = _pct([c["l0"]["ms"] for c in cases])
    lat_by_level = {
        lv: _pct([c["l0"]["ms"] for c in cases if c["level"] == lv])
        for lv in ("ph", "raw")
    }
    # 摊薄口径 = 总 wall/对数 (spike 0.57ms/对 同口径; 逐对计时的 max 长尾
    # 受 GC/缺页噪声主导, 门槛按摊薄判, 长尾单列展示)
    wall_per_pair_ms = l0_wall_s * 1000 / len(cases) if cases else 0.0

    l1_clean = [c for c in clean if "l1" in c]
    l1_info = None
    if l1_clean:
        l1_info = {
            "clean_fp_rel": sum(1 for c in l1_clean if c["l1"]["detected"]),
            "clean_fp_abs": sum(1 for c in l1_clean if not c["l1"]["ok"]),
            "clean_n": len(l1_clean),
            "fp_rel_ids": [c["id"] for c in l1_clean if c["l1"]["detected"]][:50],
            "parse_ms": _pct([c["l1"]["parse_ms"] for c in cases if "l1" in c]),
        }

    # —— 门槛: 10 类破坏全检出 / 0 error-FP / 探针全过 / L0 ≤1ms/对(均值) ——
    kind_pool: dict[str, dict] = {}
    for r in by_kind_level:
        if r["kind"] == "clean":
            continue
        k = kind_pool.setdefault(r["kind"], {"n": 0, "det": 0})
        k["n"] += r["n"]
        k["det"] += r["detected"]
    gates = {
        "corruption_100pct": all(
            k["det"] == k["n"] and k["n"] > 0 for k in kind_pool.values()
        )
        and len(kind_pool) == len(CORRUPTIONS),
        "clean_zero_error_fp": not fp,
        "probes_all_pass": all(r["pass"] for r in probe_rows),
        "l0_le_1ms_per_pair": wall_per_pair_ms <= 1.0,
    }
    return {
        "by_kind_level": by_kind_level,
        "clean": {
            "n": len(clean),
            "error_fp": len(fp),
            "warn_only": len(warn_only),
            "fp_rules": dict(fp_rules),
            "fp_ids": [c["id"] for c in fp][:50],
            "warn_ids": [c["id"] for c in warn_only][:50],
        },
        "probes": {
            "n": len(probe_rows),
            "pass": sum(1 for r in probe_rows if r["pass"]),
            "fail_ids": [r["id"] for r in probe_rows if not r["pass"]],
        },
        "latency_l0_ms": {
            "wall_per_pair": round(wall_per_pair_ms, 4),
            "per_case": lat,
            "by_level": lat_by_level,
        },
        "l1": l1_info,
        "l1_note": l1_note,
        "gates": gates,
        "gates_pass": all(gates.values()),
    }


def write_summary(
    out: Path,
    cases: list[dict],
    probe_rows: list[dict],
    cells: dict,
    gen_stats: dict,
    wall_s: float,
) -> str:
    """summary.md 报告; 返回渲染文本 (同时打印用)."""
    g = cells["gates"]
    lines = ["# validbench — B6 校验段基准\n"]
    lines.append(f"- date: {datetime.now(UTC):%Y-%m-%d %H:%M}Z · wall {wall_s:.1f}s")
    lines.append(
        f"- papers: {gen_stats.get('papers_used', '?')}/"
        f"{gen_stats.get('papers_seen', '?')} used "
        f"(parse_fail {len(gen_stats.get('parse_fail', []))}) · "
        f"pairs {gen_stats.get('pairs', '?')}"
    )
    n_corrupt = sum(1 for c in cases if c["kind"] != "clean")
    lines.append(
        f"- cases: {len(cases)} (clean {cells['clean']['n']} + corrupted {n_corrupt}) "
        f"+ probes {cells['probes']['n']}"
    )
    lat = cells["latency_l0_ms"]
    lines.append(
        f"- **gates**: corruption100%={'✅' if g['corruption_100pct'] else '❌'} · "
        f"0errorFP={'✅' if g['clean_zero_error_fp'] else '❌'} · "
        f"probes={'✅' if g['probes_all_pass'] else '❌'} · "
        f"L0≤1ms={'✅' if g['l0_le_1ms_per_pair'] else '❌'} "
        f"(摊薄 {lat['wall_per_pair']}ms/对 · 逐对 p50 {lat['per_case'].get('p50')} "
        f"p95 {lat['per_case'].get('p95')} max {lat['per_case'].get('max')})"
    )
    lines.append("")

    lines.append("## L0 检出率（kind × level）\n")
    lines.append("| kind | level | n | detected | rate | suggest | 触发规则(error) |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in cells["by_kind_level"]:
        top = ", ".join(f"{k}:{v}" for k, v in r["rules_err"].items())
        lines.append(
            f"| {r['kind']} | {r['level']} | {r['n']} | {r['detected']} "
            f"| {r['rate'] * 100:.1f}% | {r['suggest_n']} | {top or '-'} |"
        )
    lines.append("")

    c = cells["clean"]
    lines.append("## 干净对\n")
    lines.append(
        f"- n={c['n']} · error-FP={c['error_fp']} · warn-only={c['warn_only']}"
    )
    if c["fp_rules"]:
        top = ", ".join(f"{k}:{v}" for k, v in c["fp_rules"].items())
        lines.append(f"- FP 规则分布: {top}")
    lines.extend(f"  - FP: `{cid}`" for cid in c["fp_ids"][:15])
    lines.append("")

    lines.append("## 对抗探针\n")
    lines.append("| probe | expect_ok | got | err | warn | verdict |")
    lines.append("|---|---|---|---|---|---|")
    lines.extend(
        f"| {r['id']} | {r['expect_ok']} | {r['ok']} | {r['n_err']} "
        f"| {r['n_warn']} | {'pass' if r['pass'] else 'FAIL: ' + '; '.join(r['fails'])} |"
        for r in probe_rows
    )
    lines.append("")

    if cells["l1"]:
        l1 = cells["l1"]
        lines.append("## L1（tree-sitter, baseline-relative）\n")
        lines.append(
            f"- clean: n={l1['clean_n']} · FP(rel)={l1['clean_fp_rel']} · "
            f"FP(abs)={l1['clean_fp_abs']} · parse_ms {l1['parse_ms']}"
        )
        lines.append("")
        lines.append("| kind | level | n | det(rel) | det(abs) |")
        lines.append("|---|---|---|---|---|")
        lines.extend(
            f"| {r['kind']} | {r['level']} | {r['l1']['n']} "
            f"| {r['l1']['det_rel']} | {r['l1']['det_abs']} |"
            for r in cells["by_kind_level"]
            if "l1" in r
        )
        if l1["fp_rel_ids"]:
            lines.append("")
            lines.append("L1 干净对相对判定 FP（前 20）:")
            lines.extend(f"  - `{cid}`" for cid in l1["fp_rel_ids"][:20])
    else:
        lines.append(f"## L1\n\nskipped: {cells['l1_note']}")
    lines.append("")

    missed = [r for r in cells["by_kind_level"] if r["kind"] != "clean" and r["missed"]]
    lines.append("## 漏检\n")
    if missed:
        lines.extend(
            f"- MISS `{cid}` ({r['kind']}/{r['level']})"
            for r in missed
            for cid in r["missed"][:10]
        )
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## 延迟（L0 逐对计时，ms）\n")
    lines.append("| level | n | mean | p50 | p95 | max |")
    lines.append("|---|---|---|---|---|---|")
    for lv, st in cells["latency_l0_ms"]["by_level"].items():
        lines.append(
            f"| {lv} | {st['n']} | {st['mean']} | {st['p50']} "
            f"| {st['p95']} | {st['max']} |"
        )
    lines.append("")
    if gen_stats.get("parse_fail"):
        lines.append("## 解析失败\n")
        lines.extend(f"- `{f['paper']}`: {f['err']}" for f in gen_stats["parse_fail"])
        lines.append("")
    text = "\n".join(lines)
    (out / "summary.md").write_text(text + "\n", encoding="utf-8")
    return text


# ---------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser(description="B6 validbench — 校验器基准")
    ap.add_argument("--corpus", type=Path, default=CORPUS_V2)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--max-per-paper", type=int, default=6)
    ap.add_argument("--min-len", type=int, default=MIN_LEN)
    ap.add_argument("--max-len", type=int, default=MAX_LEN)
    ap.add_argument("--papers", type=int, default=0, help="0=全部")
    ap.add_argument("--paper", default=None, help="只跑 id 含此子串的 paper")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument(
        "--replay", type=Path, default=None, help="复评既有 cases.jsonl, 跳过生成"
    )
    ap.add_argument("--no-l1", action="store_true")
    ap.add_argument("--check", action="store_true", help="门槛断言, 失败退出码 1")
    args = ap.parse_args()

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    out = args.out or (BENCH / "results" / f"validbench-{args.corpus.name}-{today}")
    out = out if out.is_absolute() else Path.cwd() / out
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()

    if args.replay:
        cases = [
            json.loads(line)
            for line in args.replay.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        gen_stats = {
            "papers_seen": len({c["paper"] for c in cases}),
            "papers_used": len({c["paper"] for c in cases}),
            "pairs": sum(1 for c in cases if c["kind"] == "clean"),
            "parse_fail": [],
            "replay": str(args.replay),
        }
        print(f"replay {args.replay}: {len(cases)} cases")
    else:
        print(f"corpus: {args.corpus}")
        cases, gen_stats = gen_cases(
            args.corpus,
            max_per_paper=args.max_per_paper,
            min_len=args.min_len,
            max_len=args.max_len,
            seed=args.seed,
            paper_filter=args.paper,
            papers_limit=args.papers,
        )
        print(f"generated {len(cases)} cases from {gen_stats['pairs']} pairs")

    print("L0 eval ...")
    l0_wall_s = _l0_eval(cases)

    l1_note = "--no-l1"
    if not args.no_l1:
        print("L1 eval ...")
        l1_note = _l1_eval(cases)
        print(f"  L1: {'ran' if l1_note is None else 'skipped — ' + l1_note}")

    probe_rows = _probe_eval()
    cells = aggregate(cases, probe_rows, l1_note, l0_wall_s)
    cells["meta"] = {
        "corpus": str(args.corpus),
        "replay": str(args.replay) if args.replay else None,
        "seed": args.seed,
        "max_per_paper": args.max_per_paper,
        "date": today,
        "n_cases": len(cases),
        "gen": gen_stats,
    }

    wall_s = time.perf_counter() - t0
    with (out / "cases.jsonl").open("w", encoding="utf-8") as fh:
        for cs in cases:
            fh.write(json.dumps(cs, ensure_ascii=False) + "\n")
    with (out / "probes.jsonl").open("w", encoding="utf-8") as fh:
        for r in probe_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "cells.json").write_text(
        json.dumps(cells, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    text = write_summary(out, cases, probe_rows, cells, gen_stats, wall_s)
    print("\n" + text)
    print(f"wrote {out}/{{cases.jsonl,probes.jsonl,cells.json,summary.md}}")

    if args.check and not cells["gates_pass"]:
        print("GATE FAIL", [k for k, v in cells["gates"].items() if not v])
        sys.exit(1)


if __name__ == "__main__":
    main()
