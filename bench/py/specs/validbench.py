"""validbench — B6 validator-coverage spec (docs/spec/benchmark.md §B6).

Measures ``texlate.validate``'s detection of corrupted LLM translations:
the validator itself is benchmarked against constructed corruptions.

Cells (two disjoint item families pinned by ``item["stage"]``):

- ``vb_run`` — one cell per lake catalog idc: ``ctx.src_path()`` → root
  pick → subprocess parse (30s isolation — SIGALRM is banned in worker
  threads and kernel's process executor is unpicklable, G8) → chunk
  window [min_len,max_len] → per (chunk, level∈{ph,raw}) clean + c01–c10
  corruption cases → per-case L0 ``validate_pair`` (+L1 TsValidator when
  node/tree-sitter present) → compact verdict rows via ctx.emit_case.
- ``vb_probes`` — single synthetic cell (``__probes__``): the 14
  adversarial PROBES assertions vs validate_pair.

Epoch / re-measurement: cross-run dedup is forever — a DONE cell key
never re-measures. ``EPOCH`` rides every variant (``run@<EPOCH>`` /
``p@<EPOCH>``); bump it to open a new measurement generation. Content
knobs (max_per_paper/min_len/max_len/gen_seed/no_l1) are fp=True params —
they mark same-key cells stale on change but cannot themselves trigger
re-measurement (items() is zero-arg; variant is fixed at enumeration).

Determinism contract: chunk pick uses a per-paper seed
``Random(f"{gen_seed}:{pid}")`` — cell results are stable under subset
runs, a DELIBERATE DELTA from the old driver whose global-rng shuffle
made a paper's picked chunks depend on the other papers in the run.
Per-case corruption rng is ``crc32(cid+kind)`` exactly as before, so the
same (chunk,level,kind) produces the same corruption under any layout.

Aggregation/gates do NOT live here (Wave-D verbs) — the cell emits every
field needed to rebuild by_kind_level + clean-FP + the four gates:
n_cases, per (kind,level) n/detected/missed ids, clean error_fp ids,
l0_wall_s, l1 coverage. error(retriable) cells are UNEVALUATED — any
downstream gate must count them as undetected (fail-closed), never drop
them from the denominator.

Full src/zh case text is written to ``rundir.derived()/validbench-cases/
{safe}.jsonl`` (replay substrate — the old --replay lane's corpus).
"""

from __future__ import annotations

import bisect
import json
import random
import re
import subprocess
import sys
import threading
import time
import zlib
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from kernel import fsutil, lake
from kernel.spec import Param, Spec, Stage

from texlate.validate import l0
from texlate.validate.l0 import Severity, validate_pair

REPO = Path(__file__).resolve().parents[3]
BENCH_TS_NM = REPO / "bench" / "ts" / "node_modules"

#: Measurement generation marker — folded into every cell's variant.
#: Cross-run dedup makes DONE cells immortal; bump to re-measure.
EPOCH = "v1"

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
#  产品化修订 (全部有实测漏检出典): 候选一律限注释区外 (l0 规则经 mask_comments
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


def _live_insert_positions(s: str, spans: list[int]) -> list[int]:
    """可插入位: 落在 ``pos`` 的文本拼进 ``s[pos-1]`` 所在词法区 ——
    ``pos-1`` 在注释内即注释内插入 (含注释行尾 ``\\n`` 前位, 实测漏检来源)."""
    return [p for p in range(len(s) + 1) if p == 0 or not _in_comment(spans, p - 1)]


def _unescaped_positions(s: str, ch: str) -> list[int]:
    """``ch`` 的非转义/非注释出现位——``l0._lex`` ch token 自带豁免
    (bs/cmt 不进 ch), 且注释止于 ``[\\r\\n]`` 比手扫的 ``\\n`` 更严."""
    return [pos for kind, text, pos in l0._lex(s) if kind == "ch" and text == ch]


def _pick_uncommented(
    zh: str, rx: re.Pattern, rng: random.Random, keep=None
) -> re.Match | None:
    """注释区外候选随机取一 (l0 规则经 mask_comments 豁免注释 —— 注释内
    破坏是语义 no-op); ``keep`` 附加过滤 (如 c09 空 key 不计多重集)."""
    spans = _comment_spans(zh)
    ms = [
        m
        for m in rx.finditer(zh)
        if not _in_comment(spans, m.start()) and (keep is None or keep(m))
    ]
    return None if not ms else ms[rng.randrange(len(ms))]


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
    m = _pick_uncommented(zh, _END_RX, rng)
    if m is None:
        return None
    begins = {m.group(1) for m in re.finditer(r"\\begin\{([^{}]*)\}", zh)}
    name = re.match(r"\\end\{([^{}]*)\}", m.group(0)).group(1)
    alts = [b for b in begins if b != name]
    new = rng.choice(alts) if alts else name + "*"
    return zh[: m.start()] + "\\end{" + new + "}" + zh[m.end() :]


def c04_drop_end(zh: str, rng: random.Random) -> str | None:
    m = _pick_uncommented(zh, _END_RX, rng)
    if m is None:
        return None
    return zh[: m.start()] + zh[m.end() :]


def c05_drop_ph(zh: str, rng: random.Random) -> str | None:
    m = _pick_uncommented(zh, l0.PH_ANY_LIKE_RX, rng)
    if m is None:
        return None
    return zh[: m.start()] + zh[m.end() :]


def c06_typo_ph(zh: str, rng: random.Random) -> str | None:
    m = _pick_uncommented(zh, l0.PH_ANY_LIKE_RX, rng)
    if m is None:
        return None
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
    # 空 key 不计多重集; KEY_CMD_RX 三臂的 key 落在不同 group —— 逐组扫
    # (原 m.group(1) 对 \cite/\label 臂恒 None, 实测直接 AttributeError)
    m = _pick_uncommented(
        zh,
        l0.KEY_CMD_RX,
        rng,
        keep=lambda m: any(k.strip() for g in m.groups() if g for k in g.split(",")),
    )
    if m is None:
        return None
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
# docs/spec/benchmark.md §B6-2 清单 + test_validate_l0.py 防误报面; 每条断言 ok/error-rules/
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


def _pick_root(src: Path) -> Path | None:
    """find_main_tex 定主档 (产品同款启发式); 无候选退最大 .tex."""
    from texlate.compile.mainfile import find_main_tex

    m = find_main_tex(src)
    if m is not None:
        return m
    texs = sorted(src.rglob("*.tex"))
    return max(texs, key=lambda f: f.stat().st_size) if texs else None


class _ParseFail(Exception):
    """子进程解析失败（超时/崩溃/输出缺）——旧 _ParseTimeout+异常同桶."""


_CHILD_SRC = r"""
import json, sys
from pathlib import Path
from texlate.latex import parse_file
res = parse_file(Path(sys.argv[1]))
out = {"chunks": [{"id": c.id, "content": c.content} for c in res.chunks],
       "ph_map": res.ph_map}
sys.stdout.write(json.dumps(out, ensure_ascii=False))
"""


def _parse_subprocess(root: Path, timeout: int) -> tuple[list, dict]:
    """30s 隔离解析——worker 线程禁 SIGALRM 且内核 process executor 是
    不可 pickle 闭包 (G8)，超时壳只能由 subprocess 承载。"""
    try:
        res = subprocess.run(
            [sys.executable, "-c", _CHILD_SRC, str(root)],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        msg = f"Timeout(>{timeout}s)"
        raise _ParseFail(msg) from e
    if res.returncode != 0:
        tail = res.stderr.decode("utf-8", "replace")[-200:]
        msg = f"rc={res.returncode}: {tail}"
        raise _ParseFail(msg)
    try:
        d = json.loads(res.stdout)
    except ValueError as e:
        msg = f"bad child stdout: {e}"
        raise _ParseFail(msg) from e
    chunks = [SimpleNamespace(id=c["id"], content=c["content"]) for c in d["chunks"]]
    return chunks, d["ph_map"]


def _gen_paper_cases(
    pid: str,
    src: Path,
    *,
    max_per_paper: int,
    min_len: int,
    max_len: int,
    seed: int,
) -> tuple[list[dict], dict]:
    """单篇 case 生成：窗过滤 → per-paper rng shuffle → ph/raw × clean+c10。

    返回 (cases, stats)。stats 带 attempted/none_skips/raw_skipped ——
    「应产 case 集」与「实产」双计数 (None-able 算子的分母守恒口径)。
    """
    root = _pick_root(src)
    if root is None:
        return [], {"root": None}
    chunks_all, ph_map = _parse_subprocess(root, PARSE_TIMEOUT_S)
    windowed = [c for c in chunks_all if min_len <= len(c.content) <= max_len]
    # per-paper 播种：cell 结果不随同跑 paper 集漂移（旧全局 rng 语义见 docstring）
    prng = random.Random(f"{seed}:{pid}")
    prng.shuffle(windowed)
    picked = windowed[:max_per_paper]
    cases: list[dict] = []
    none_skips: Counter = Counter()
    n_pairs = n_raw_skip = 0
    for c in picked:
        for level, csrc in (
            ("ph", c.content),
            ("raw", rehydrate(c.content, ph_map)),
        ):
            if level == "raw" and csrc == c.content:
                n_raw_skip += 1
                continue  # 无占位符 -> 与 ph 层重复（守恒键 raw_skipped）
            zh = pseudo_translate(csrc)
            cid = f"{pid}/c{c.id}/{level}"
            cases.append(
                {
                    "id": cid + "/clean",
                    "paper": pid,
                    "chunk": c.id,
                    "level": level,
                    "kind": "clean",
                    "src": csrc,
                    "zh": zh,
                }
            )
            n_pairs += 1
            for kind, fn in CORRUPTIONS:
                crng = random.Random(zlib.crc32((cid + kind).encode()))
                bad = fn(zh, crng)
                if bad is None:
                    none_skips[kind] += 1
                    continue
                cases.append(
                    {
                        "id": f"{cid}/{kind}",
                        "paper": pid,
                        "chunk": c.id,
                        "level": level,
                        "kind": kind,
                        "src": csrc,
                        "zh": bad,
                    }
                )
    stats = {
        "root": root.name,
        "chunks": len(chunks_all),
        "windowed": len(windowed),
        "picked": len(picked),
        "pairs": n_pairs,
        "raw_skipped": n_raw_skip,
        "none_skips": dict(none_skips),
        # 应产 = 实产 + none 剔除（分母对拍键）
        "n_attempted": len(cases) + sum(none_skips.values()),
    }
    return cases, stats


# ---------------------------------------------------------------- 评测


def _l0_one(cs: dict) -> dict:
    """单 case 跑 validate_pair → 紧凑判定行 (emit_case 负载)."""
    t0 = time.perf_counter_ns()
    rep = validate_pair(cs["src"], cs["zh"])
    ms = (time.perf_counter_ns() - t0) / 1e6
    return {
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


def _expect_names(src: str) -> list[str]:
    """src 内 [[TYPE_n]] → worker expect 契约名 (剥括号)."""
    return [m[2:-2] for m in l0.PH_ANY_LIKE_RX.findall(src)]


def _l1_daemon():
    """TsValidator 常驻实例（未 enter）→ (v|None, 不可用原因|None)."""
    try:
        from texlate.validate.l1 import TsValidator
    except ImportError as e:
        return None, f"import l1 失败: {e}"
    node_path = BENCH_TS_NM if (BENCH_TS_NM / "tree-sitter").is_dir() else None
    v = TsValidator(node_path=node_path)
    if not v.available():
        return None, "node/tree-sitter 依赖不在场 (TEXLATE_TS_NODE_PATH 可指)"
    return v, None


# thread executor 下的 L1 形态：每 worker 线程一个懒单例（= jobs 个常驻
# node 进程，对齐旧「每进程单例×jobs」语义）。未 close —— 进程退出即收。
_L1_LOCAL = threading.local()


def _l1_here():
    tried = getattr(_L1_LOCAL, "tried", False)
    if not tried:
        _L1_LOCAL.tried = True
        _L1_LOCAL.daemon, _L1_LOCAL.why = _l1_daemon()
    return getattr(_L1_LOCAL, "daemon", None), getattr(_L1_LOCAL, "why", None)


def _l1_one(daemon, cs: dict, baselines: dict) -> dict:
    """常驻 daemon 跑单 case L1 同口径; baseline 缓存按 (paper,chunk,level) 共享 src."""
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
    out = {
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
        out["error"] = res.error
    return out


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


# ---------------------------------------------------------------- items/select


def _items() -> list[dict]:
    """湖 catalog 全格 + 一条合成探针格（eval=True → 免 canon 闸）。

    catalog 行不预过滤：skeleton/failed 格也产 item，stage 内 src_path()
    拿不到 → skip（manifest 有湖没有这一类保持显式行可见）。
    """
    cat = lake.LakeCatalog.load()
    items = [
        {
            "id": idc,
            "stage": "vb_run",
            "variant": f"run@{EPOCH}",
            # cell.layer 须标量（compile_checks 的 EVAL_LAYERS 隶属判定）；
            # 全量 layers 另键携带供 select 多属过滤.
            "layer": (row.get("layers") or [""])[0] or "",
            "layers": sorted(row.get("layers") or []),
        }
        for idc, row in sorted(cat.rows().items())
    ]
    items.append(
        {
            "id": "__probes__",
            "stage": "vb_probes",
            "variant": f"p@{EPOCH}",
        }
    )
    return items


def _select(item: dict, rp: dict) -> bool:
    """窄化面：ids 逗列 / only 子串 / layers 层滤 / n+seed 湖内抽样。

    probes 格：无窄化或窄化显式命中时选入；n 抽样只圈 vb_run 池，
    探针格不被抽走（它是 B6 gate 的一部分，不是样本）。
    """
    is_probe = item.get("stage") == "vb_probes"
    ids_p = str(rp.get("ids") or "").strip()
    only = str(rp.get("only") or "").strip()
    if is_probe:
        if ids_p:
            return "__probes__" in {t.strip() for t in ids_p.split(",") if t.strip()}
        if only:
            return only in "__probes__"
        return True
    pid = str(item.get("id") or "")
    if ids_p:
        want = {t.strip() for t in ids_p.split(",") if t.strip()}
        if pid not in want:
            return False
    layers = {s.strip() for s in str(rp.get("layers") or "").split(",") if s.strip()}
    if layers:
        il = item.get("layers") or [item.get("layer")]
        if not set(il) & layers:
            return False
    if only and only not in pid:
        return False
    n = int(rp.get("n") or 0)
    if n > 0:
        seed = int(rp.get("seed") or 0)
        pool = sorted(
            str(it["id"]) for it in _ITEMS_POOL if it.get("stage") == "vb_run"
        )
        keep = set(random.Random(seed).sample(pool, min(n, len(pool))))
        return pid in keep
    return True


_ITEMS_POOL: list[dict] = []  # select 的 n 抽样池（items() 物化后回填）


def _items_full() -> list[dict]:
    global _ITEMS_POOL  # noqa: PLW0603
    its = _items()
    _ITEMS_POOL = its
    return its


# ---------------------------------------------------------------- stages


def _vb_run(ctx) -> dict | str:
    """单篇：投影子进程解析 → case 生成 → L0(+L1) 逐判 → emit_case."""
    src = ctx.src_path()
    if src is None:
        ctx.emit({"metrics": {"reason": "lake_absent"}})
        return "skip"
    try:
        cases, stats = _gen_paper_cases(
            ctx.idc,
            src,
            max_per_paper=int(ctx.params["max_per_paper"]),
            min_len=int(ctx.params["min_len"]),
            max_len=int(ctx.params["max_len"]),
            seed=int(ctx.params["gen_seed"]),
        )
    except _ParseFail as e:
        return {
            "status": "fail",
            "errors": [{"cat": "parse", "msg": str(e)[:300]}],
            "metrics": {"parse_fail": 1},
        }
    if not cases:
        # 无 root / 窗内零 chunk / 全对 none-skipped —— 合法的零产出终态
        ctx.emit({"metrics": {**stats, "n_cases": 0}})
        return "clean"

    no_l1 = bool(ctx.params.get("no_l1"))
    daemon, l1_note = (None, "--no-l1") if no_l1 else _l1_here()
    baselines: dict = {}
    l0_wall_s = 0.0
    det = ncorr = clean_fp = warn_only = 0
    missed: list[str] = []
    fp_ids: list[str] = []
    l1_n = l1_det_rel = l1_det_abs = l1_clean_fp_rel = 0
    full_path = (
        ctx.rundir.derived() / "validbench-cases" / f"{ctx.safe}.jsonl"
        if ctx.rundir is not None
        else None
    )
    full_rows: list[str] = []

    for cs in cases:
        t0 = time.perf_counter_ns()
        verdict = _l0_one(cs)
        l0_wall_s += (time.perf_counter_ns() - t0) / 1e9
        if daemon is not None:
            cs["l1"] = _l1_one(daemon, cs, baselines)
            l1_n += 1
            l1_det_rel += int(cs["l1"]["detected"])
            l1_det_abs += int(not cs["l1"]["ok"])
            if cs["kind"] == "clean" and cs["l1"]["detected"]:
                l1_clean_fp_rel += 1
        # 紧凑判定行进 cases 表（分母守恒的逐 case 键面）
        ctx.emit_case(
            {
                "id": cs["id"],
                "paper": cs["paper"],
                "chunk": cs["chunk"],
                "level": cs["level"],
                "kind": cs["kind"],
                "l0": verdict,
                **({"l1": cs["l1"]} if "l1" in cs else {}),
            }
        )
        full_rows.append(json.dumps({**cs, "l0": verdict}, ensure_ascii=False))
        if cs["kind"] == "clean":
            if not verdict["ok"]:
                clean_fp += 1
                fp_ids.append(cs["id"])
            elif verdict["n_warn"]:
                warn_only += 1
        else:
            ncorr += 1
            if verdict["ok"]:
                missed.append(cs["id"])
            else:
                det += 1

    if full_path is not None:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        fsutil.atomic_write(full_path, ("\n".join(full_rows) + "\n").encode())

    metrics = {
        **stats,
        "n_cases": len(cases),
        "corrupt_n": ncorr,
        "corrupt_detected": det,
        "missed": missed[:50],
        "clean_n": len(cases) - ncorr,
        "clean_error_fp": clean_fp,
        "clean_fp_ids": fp_ids[:50],
        "clean_warn_only": warn_only,
        "l0_wall_s": round(l0_wall_s, 3),
        "l0_wall_per_pair_ms": round(l0_wall_s * 1000 / len(cases), 4),
        "cases_file": str(full_path) if full_path else None,
    }
    if daemon is None:
        metrics["l1_note"] = l1_note or "unavailable"
    else:
        metrics["l1"] = {
            "n": l1_n,
            "det_rel": l1_det_rel,
            "det_abs": l1_det_abs,
            "clean_fp_rel": l1_clean_fp_rel,
        }
    errors = []
    if missed:
        errors.append({"cat": "validator_miss", "msg": ";".join(missed[:8])})
    if clean_fp:
        errors.append({"cat": "clean_fp", "msg": ";".join(fp_ids[:8])})
    status = "fail" if errors else "ok"
    return {"status": status, "metrics": metrics, "errors": errors}


def _vb_probes(ctx) -> dict:
    """14 条对抗探针断言格."""
    rows = _probe_eval()
    n_pass = sum(1 for r in rows if r["pass"])
    fails = [r for r in rows if not r["pass"]]
    for r in rows:
        ctx.emit_case(
            {
                "id": r["id"],
                "probe": True,
                "expect_ok": r["expect_ok"],
                "ok": r["ok"],
                "n_err": r["n_err"],
                "n_warn": r["n_warn"],
                "pass": r["pass"],
                "fails": r["fails"],
            }
        )
    metrics = {
        "n": len(rows),
        "pass": n_pass,
        "fail_ids": [r["id"] for r in fails],
        "detail": [
            {"id": r["id"], "pass": r["pass"], "fails": r["fails"]} for r in rows
        ],
    }
    errors = [
        {"cat": "probe_fail", "msg": f"{r['id']}: {'; '.join(r['fails'])[:160]}"}
        for r in fails[:8]
    ]
    return {
        "status": "fail" if fails else "ok",
        "metrics": metrics,
        "errors": errors,
    }


spec = Spec(
    kind="validbench",
    params={
        "ids": Param(default="", fp=False),
        "only": Param(default="", fp=False),
        "layers": Param(default="", fp=False),
        "n": Param(type=int, default=0),
        "seed": Param(type=int, default=0),
        "max_per_paper": Param(type=int, default=6),
        "min_len": Param(type=int, default=MIN_LEN),
        "max_len": Param(type=int, default=MAX_LEN),
        "gen_seed": Param(type=int, default=SEED),
        "no_l1": Param(type=bool, default=False),
    },
    items=_items_full,
    select=_select,
    stages=[
        Stage(
            "vb_run",
            _vb_run,
            eval=True,
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "clean": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
        ),
        Stage(
            "vb_probes",
            _vb_probes,
            eval=True,
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "error": "retriable",
            },
        ),
    ],
    eval=True,
    lake=True,
    env_probes=["python", "node"],
    code_deps=[
        "src/texlate/validate",
        "src/texlate/latex",
        "src/texlate/compile/mainfile.py",
    ],
)
