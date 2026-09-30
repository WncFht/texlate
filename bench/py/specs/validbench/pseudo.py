"""specs.validbench.pseudo — 构造性伪译文叶 (validbench 拆分叶).

(rule-validator 原型 gen_cases.py 原样移植; PH_RX 换产品 l0.PH_ANY_LIKE_RX —
产品版额外认 [[SL]]/[[PL]] 无数字后缀形态，是原型正则的超集.)
"""

from __future__ import annotations

import re
import zlib

from specs import _bootstrap

_bootstrap.ensure()

from texlate.validate import l0

VOCAB = (  # noqa: SIM905 — 紧凑词表，200 元素 list 字面量反而难读
    "研究 方法 结果 模型 数据 分析 实验 表明 本文 提出 算法 网络 训练 参数 "
    "函数 定理 证明 引理 误差 分布 样本 优化 梯度 矩阵 向量 概率 随机 变量 "
    "近似 收敛 序列 空间 映射 算子 方程 维数 拓扑 流形 极限 连续 微分 积分 "
    "级数 变换 特征 性质 构造 存在 唯一 定义 假设 推论 注记 例子 应用 讨论 "
    "结论 文献 综述 问题 理论 框架 技术 过程 系统 结构 性能 精度 复杂度 "
    "规模 实例 条件 目标 策略 步骤 模块 测试 评估 比较 基线 提升 影响 机制 "
    "原理 方案 效果 优势 局限 贡献 概述 记号 约定 术语 单位 索引 摘要 引言 "
    "背景 动机 章节 图表 公式 段落 估计 观测 信号 频谱 信道 编码 译码"
).split()

# 参数必须原样保留的命令 (key/env 名/文件路径 — 翻掉即机械错误)
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
    """构造性伪译文：拉丁词->确定性汉字，其余机械要素原样保留."""
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
