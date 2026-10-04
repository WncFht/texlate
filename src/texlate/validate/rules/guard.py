r"""validate.rules.guard — 交付守卫规则域叶 (validate.rules 域缝叶)。

两族交付面守卫：``_check_protocol_echo`` 协议字面回显（corrector
三段式节标/rules 反馈消息/``slot_validation_failures``/``[compile_error]``
被当正文交付——multiset 可吻合而载荷脏；词表 ``_ECHO_SIGS`` 单源，
bench ``DIRTY_SIGS`` 同源 import）、``_check_comment_eof`` 尾段未终结
注释（``[[COMMENT_n]]``/字面 ``%`` 到 EOF 无 ``\\n``，splice 接缝吞
后随字面首行 → ``\\@xdblarg`` runaway 族实证）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from texlate.validate.rules.ph import COMMENT_PH_RX
from texlate.validate.rules.report import Issue, Severity

if TYPE_CHECKING:
    from texlate.validate.rules.lex import _Ctx

#: 协议回显标记（repro-2410b §4b 交付守卫）：rules 反馈消息实际 emit 串 +
#: 重试协议字面（三段式节标/``previous_validation_error`` 尾拼/
#: ``slot_validation_failures`` 字段/``[compile_error]`` logfix 回灌标）。
#: 本表为唯一词表单源——bench ``DIRTY_SIGS``（``specs/_sabotage.py``）
#: 经 import 同源，勿再复抄副本（复抄面曾静默漂移：词表项的全角冒号
#: 改写脱离了 emit 串）。交付 zh 出现即 prompt/反馈被当正文回显；
#: ``[这是译文]``/``[word]`` 行内合法产出不在表内不误伤。
_ECHO_SIGS: Final = (
    "占位符缺失:",  # _pair_placeholder_typos
    "占位符疑似拼错",  # _pair_placeholder_typos lev 配对臂
    "多余/未识别占位符:",  # _check_placeholder
    "结构占位符",  # _check_ph_anchor "脱离行首位置"
    "注释区内臆造占位符",  # _check_placeholder 注释区专项
    "[Original]",  # prompts.corrector_user 三段式
    "[Translation]",  # prompts.corrector_user
    "[Error]",  # prompts.corrector_user
    "previous_validation_error",  # pipeline 阶梯重试尾拼
    "slot_validation_failures",  # pipeline 批模式失败槽字段
    "[compile_error]",  # pipeline logfix 回灌重译
)


def _tail_unterminated_comment(toks: list[tuple[str, str, int]], sm: str) -> str | None:
    r"""文本尾段未终结注释的标记（字面 ``%`` → ``"%"``、``[[COMMENT_n]]`` → token）；无 → ``None``。

    ``%`` 展开吞到 EOL——尾段注释未终结时，splice 后随字面首行被接进注释行。
    字面 ``%`` 走 ``_lex`` 末 token 判（``\%`` 转义天然豁免）；``[[COMMENT_n]]``
    形在遮盖视图上判——token 后只剩 ``[ \t]*`` 到 EOF 即未终结（``\n`` 是注释
    终结符；后随非空白属 ``_check_ph_anchor`` 混入判据，此处不重复报）。
    入参 ``toks``/``sm`` 分别为 ``_lex`` 流与 ``mask_comments`` 视图
    （``_Ctx.lex_*``/``masked_*`` 共享件）。
    """
    if toks and toks[-1][0] == "cmt":
        return "%"
    # 末个 ``[[COMMENT_`` 前缀位即候选——若非良形 token，则任一更早 token 的
    # 尾段都含该残码（非空白）必非未终结，无需往前再扫。
    i = sm.rfind("[[COMMENT_")
    if i < 0:
        return None
    m = COMMENT_PH_RX.match(sm, i)
    if m is not None and not sm[m.end() :].strip(" \t"):
        return m.group(0)
    return None


def _check_comment_eof(ctx: _Ctx) -> None:
    r"""译文尾段未终结注释 → error（rt1 ``\@xdblarg`` runaway 族实证，4 cell 同形）。

    ``[[COMMENT_n]]``/字面 ``%`` 到 zh EOF 无 ``\n``：splice 接缝把 chunk 后
    字面首行吞进注释——``\caption{`` 的 ``}`` 落进 ``%`` 行 → ``\@xdblarg``
    runaway（1109.5754/0905.1718/1306.5799/2003.10917：corrector 臂丢尾
    ``\n``，``bare_token_audit`` 对未编码 src 的 ``[[SL]]`` 基线恒 0 看不见）。
    src 尾段同形豁免——源 chunk 以未终结注释收尾时后随字面本就以该注释的
    ``\n`` 终结符起头，zh 同形即忠实复现。
    """
    tok = _tail_unterminated_comment(ctx.lex_zh, ctx.masked_zh)
    if (
        tok is None
        or _tail_unterminated_comment(ctx.lex_src, ctx.masked_src) is not None
    ):
        return
    ctx.issues.append(
        Issue(
            "comment_eof",
            Severity.ERROR,
            f"译文尾段注释未终结到行尾: {tok}"
            f"（splice 后紧随字面首行被注释吞掉——}} 类结构字节死字节化，"
            f"\\caption{{ 类参数不闭合 → runaway）",
            found=tok,
        )
    )


def _check_protocol_echo(ctx: _Ctx) -> None:
    r"""协议回显守卫：zh 净多出 corrector/rules 协议字面 → error。

    repro-2410b §4b：Mode-B mock 把三段式 prompt 当正文翻，交付块带
    节标 + ``占位符缺失:`` 反馈行 + body 重复——占位符 multiset 可吻合
    而载荷脏（反馈行里 ``[[COMMENT_14]]`` splice 出 ``%`` 吞掉 chunk 外
    ``}`` → early_eof）。真模型 parrot prompt furniture 是同款逃逸通道，
    与 ``pipeline._intercept_leftover_ph`` 同层（error → 重译/回退原文）。
    词表 ``_ECHO_SIGS`` 单源（bench ``DIRTY_SIGS`` 同源 import）——
    子串直配 + src↔zh 净差（src 自带同形串属忠实翻译不追责；校验行话
    + ASCII 冒号/节标形态合法译文不产出）。
    """
    for sig in _ECHO_SIGS:
        n = ctx.zh.count(sig) - ctx.src.count(sig)
        if n > 0:
            ctx.issues.append(
                Issue(
                    "protocol_echo",
                    Severity.ERROR,
                    f"协议字面 {sig!r} 进入交付译文 ×{n}"
                    f"（corrector 反馈/重试协议被当正文回显，载荷脏）",
                    ctx.zh.find(sig),
                    found=sig,
                )
            )
