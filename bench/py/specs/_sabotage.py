r"""Mode B/C 破坏注入层 —— e2e mock / translators 两臂唯一事实源。

docs/spec/benchmark.md §B5: Mode B 幻觉 mock (译文丢/造占位符 → 校验链编译前 100% 捕获);
Mode C 位置扰动 mock (随机挪 ~10% 占位符 → 量化 splice 鲁棒性)。
扰动决策 = f(段内容哈希) → 确定性可复现，批/单块/阶梯重试同决策。

共享件落点：本层自旧驱动 e2e_mock_bench.py 抽出——e2e_mock 经
re-export 保持 ``emb.X`` 面（fuzz spy 钉 ``emb._scan_tree``、
test_sabotage_arms 钉 ``emb._plan_b/_apply_*``），tests/_translators
台账臂直引本模块。
"""

from __future__ import annotations

import hashlib
import re

from specs import _bootstrap

_bootstrap.ensure()

from texlate.latex.placeholder import PH_RX
from texlate.validate.rules import _ECHO_SIGS
from texlate.xlat.pipeline import MockTranslator
from texlate.xlat.placeholders import decode_newlines, is_placeholder_only

MODE_B_RATE = 30  # 每段 ~30% 注一次幻觉破坏
MODE_C_RATE = 10  # 每占位符 ~10% 挪位
_NUM_LINE_RX = re.compile(r"^(\[\d+\])\s?(.*)$", re.DOTALL)

#: Mode-B 内容通道签名（repro-2410b）：交付 zh 命中任一 → dirty。
#: rules 反馈行字面 = ``Issue.message`` 原文（``RulesReport.feedback`` 直拼进
#: corrector ``[Error]`` 段 / 阶梯 ``[previous_validation_error]`` 尾拼，mock
#: 臂 CJK 非散文 run 原样残留进交付）；节标/字段名 = 重试协议字面（mock 会
#: 翻成 ``[这是译文]`` 不命中，真模型 parrot prompt furniture 同款通道兜底）。
#: ``[这是译文]`` 独行**不**作签名——源 ``[word]`` 合法产出同款。
#: 词表即 ``rules._ECHO_SIGS`` 本体（同源 import 同一对象，非复抄——复抄面曾
#: 静默漂移成全角冒号脱离 emit 串）；src 自带签名的 delivered 块 echo 与
#: 忠实译文裸包含不可区分 → armed（结构性盲区，记账只观测不进门槛）。
DIRTY_SIGS: tuple[str, ...] = _ECHO_SIGS


def _dirty_hits(text: str) -> list[str]:
    """文本命中的协议签名列表（序同 ``DIRTY_SIGS``；空 = 无签名；src/zh 通用）。"""
    return [s for s in DIRTY_SIGS if s in text]


def _h(*parts: str) -> int:
    return int.from_bytes(hashlib.blake2s("|".join(parts).encode()).digest()[:4], "big")


def _unwrap_seg(user: str) -> str:
    """单块/阶梯/corrector 调用面里恢复被译段原文。

    translate_fn 收到的是 encode_newlines 后文本 (retry.py ``ctx.encoded``),
    重试尾部拼 ``\\n\\n[previous_validation_error]\\n...``; corrector =
    ``[Original]\\n{original}\\n[Translation]...`` (original 是未编码原文)。
    """
    if user.startswith("[Original]\n"):
        return user[len("[Original]\n") :].split("\n[Translation]", 1)[0]
    return user.split("\n\n[previous_validation_error]", 1)[0].split(
        "\n\n[compile_error]", 1
    )[0]


def _canon(seg: str) -> str:
    """段原文归一：编码形态剥回 \\n——ladder 各阶段 (encoded / corrector raw)
    对同块得到同一哈希输入，破坏决策跨重试一致."""
    return decode_newlines(seg)


def _plan_b(seg: str) -> str | None:
    """Mode B: 该段是否注破坏 + 哪种 (丢占位符 / 造占位符)."""
    canon = _canon(seg)
    if is_placeholder_only(canon.strip()):
        return None  # 纯占位符块路由不走 translator, 无从注入
    h = _h("B", canon)
    if h % 100 >= MODE_B_RATE:
        return None
    if PH_RX.search(canon) and (h >> 8) & 1:
        return "drop_ph"
    return "fabricate_ph"


def _apply_b(out: str, seg: str, kind: str) -> tuple[str, str]:
    """对译文段执行破坏，返回 (破坏后文本，细节)."""
    canon = _canon(seg)
    if kind == "drop_ph":
        ms = list(PH_RX.finditer(out))
        if not ms:
            kind = "fabricate_ph"
        else:
            m = ms[_h("Bi", canon) % len(ms)]
            return out[: m.start()] + out[m.end() :], f"drop {m.group(0)}"
    # fabricate: 源 chunk 占位符编号是 0..k, 9xx 永不与真占位符碰撞
    tag = f"[[MATH_9{_h('Bt', canon) % 90 + 10}]]"
    pos = _h("Bp", canon) % (len(out) + 1)
    sp = out.find(" ", pos)
    pos = sp + 1 if sp >= 0 else len(out)
    return f"{out[:pos]}{tag}{out[pos:]}", f"fab {tag}@{pos}"


def _apply_c(out: str, seg: str) -> tuple[str, int]:
    """Mode C: 每占位符 ~10% 概率挪到段内随机字符位 (multiset 不变 → rules 静默).

    按 token 值定位 (chunk 内占位符名唯一); 插入点 = 不在任何占位符 span 内
    的随机字符边界——可落词中，模拟真实幻觉错位。落回原位不计 moved。
    """
    canon = _canon(seg)
    ms = list(PH_RX.finditer(out))
    flagged = [
        m.group(0)
        for i, m in enumerate(ms)
        if _h("C", canon, str(i)) % 100 < MODE_C_RATE
    ]
    moved = 0
    for k, ph in enumerate(flagged):
        j = out.find(ph)
        if j < 0:
            continue
        out = out[:j] + out[j + len(ph) :]
        spans = [m.span() for m in PH_RX.finditer(out)]
        allowed = [
            p for p in range(len(out) + 1) if all(not a <= p < b for a, b in spans)
        ]
        if not allowed:
            out += ph
            continue
        pos = allowed[_h("Cp", canon, str(k)) % len(allowed)]
        out = out[:pos] + ph + out[pos:]
        moved += pos != j
    return out, moved


def _is_batch_user(lines_u: list[str]) -> bool:
    """与 MockTranslator 批判别同口径：全部非空行都是 ``[n] `` 前缀."""
    return bool(lines_u) and all(_NUM_LINE_RX.match(ln) for ln in lines_u if ln.strip())


class SabotageTranslator(MockTranslator):
    """Mode B: mock 译文上叠加幻觉破坏 (丢/造占位符); events 逐次记账."""

    def __init__(self, **kw: object) -> None:
        super().__init__(**kw)
        self.events: list[dict] = []

    async def translate(self, *, user: str, response_format=None, **kw):
        raw = await super().translate(user=user, response_format=response_format, **kw)
        if response_format is not None:
            return raw
        lines_u, lines_o = user.split("\n"), raw.split("\n")
        if _is_batch_user(lines_u) and len(lines_u) == len(lines_o):
            for i, lu in enumerate(lines_u):
                mu = _NUM_LINE_RX.match(lu)
                if not mu:
                    continue
                seg = mu.group(2)
                kind = _plan_b(seg)
                if not kind:
                    continue
                mo = _NUM_LINE_RX.match(lines_o[i])
                body = mo.group(2) if mo else lines_o[i]
                new, detail = _apply_b(body, seg, kind)
                lines_o[i] = f"{mo.group(1)} {new}" if mo else new
                self.events.append({"seg": seg, "kind": kind, "detail": detail})
            return "\n".join(lines_o)
        seg = _unwrap_seg(user)
        kind = _plan_b(seg)
        if kind:
            raw, detail = _apply_b(raw, seg, kind)
            self.events.append({"seg": seg, "kind": kind, "detail": detail})
        return raw


class PerturbTranslator(MockTranslator):
    """Mode C: mock 译文上叠加占位符挪位 (multiset 保持 → 过 rules 后 splice 错位)."""

    def __init__(self, **kw: object) -> None:
        super().__init__(**kw)
        self.events: list[dict] = []

    async def translate(self, *, user: str, response_format=None, **kw):
        raw = await super().translate(user=user, response_format=response_format, **kw)
        if response_format is not None:
            return raw
        lines_u, lines_o = user.split("\n"), raw.split("\n")
        if _is_batch_user(lines_u) and len(lines_u) == len(lines_o):
            for i, lu in enumerate(lines_u):
                mu = _NUM_LINE_RX.match(lu)
                if not mu:
                    continue
                seg = mu.group(2)
                mo = _NUM_LINE_RX.match(lines_o[i])
                body = mo.group(2) if mo else lines_o[i]
                new, n_moved = _apply_c(body, seg)
                if n_moved:
                    lines_o[i] = f"{mo.group(1)} {new}" if mo else new
                    self.events.append({"seg": seg, "moved": n_moved})
            return "\n".join(lines_o)
        seg = _unwrap_seg(user)
        raw, n_moved = _apply_c(raw, seg)
        if n_moved:
            self.events.append({"seg": seg, "moved": n_moved})
        return raw


def _seg_of(r_source: str, seg: str) -> bool:
    """事件段 ↔ 块：段可能是 encoded 全段/行切片 (batch+ladder) 或原文 (corrector).

    两侧统一 ``\\r\\n→\\n``——CRLF 源里 ``[[SL]]`` 解回 ``\\n`` 对不上原文，
    旧口径漏账 (sabotaged/escaped 双降; v3 recount 实证 sabotaged +33).
    """
    src_n = r_source.replace("\r\n", "\n")
    cands = {seg, decode_newlines(seg)}
    cands |= {c.replace("\r\n", "\n") for c in cands}
    return src_n in cands or any(len(c) > 8 and c in src_n for c in cands)
