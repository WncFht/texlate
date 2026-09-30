"""validate.l0.prose — 散文质量规则域叶 (validate.l0 域缝叶)。

剥占位符/cs 后散文本体的三族判定：``_check_same_source`` 整段原文
回显（规范化等值 + 拉丁主导，BIB 直通/短残段/纯非语言成分/人名专名列
豁免）、``_check_length`` token 代理长度比带 + CJK 占比疑似未翻译
warn、``_check_residual_en`` 段内残英 run（行级修复原文回退/半译
签名，判定口径 ``textutil.residual_en_net`` 与 pipeline 逐字节一致）。
``_cjk_latin_counts`` 双侧计数口径与长度带/豁免常量同域共置。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from texlate.textutil import CJK_RX, name_list_prose, residual_en_net
from texlate.validate.l0.report import Issue, Severity

if TYPE_CHECKING:
    from texlate.validate.l0.lex import _Ctx

#: 长度比带（E24 token 代理口径）：剥占位符/cs 后 est_token 比出带 →
#: error。char 级旧带 [0.25,2.5] 因 CJK 密度 241 假离群弃用；本带经
#: qualbase-2026-09-18 全池标定（p0=0.76 / p50=1.18 / p99.5=1.80），
#: 合法件双侧留 ~4x 余量，带外即退化坍缩/膨胀。
TOKEN_RATIO_LO: Final = 0.30
TOKEN_RATIO_HI: Final = 3.00
#: 人名/专名列 src 的长度比上界——音译 + 原文括号注释风格（每名 →
#: 中文音译+``(拉丁原名)``）合法膨胀 ~2.6-3.4x，标准 3.0 上界误杀
#: （web t_25e3f4d1 seq-67..77 实测 3.04-3.32）。下界不放宽——
#: 名单译空/截断仍是退化。
TOKEN_RATIO_HI_NAMELIST: Final = 4.00
#: 剥后 src est_token 下界——之下按纯占位符/短残段豁免（输出=输入是正确态，
#: babeldoc ``input_token_count>10`` 同口径）。
_MIN_PROSE_TOKENS: Final = 10
CJK_SHARE_MIN: Final = 0.30
_MIN_LATIN_FOR_CJK_CHECK: Final = 8

#: 非语言成分 span（same_source 恒等豁免用）：已包裹 ``\url/\href/\doi/\path``、
#: 裸 URL、裸 DOI（``doi:`` 前缀与 ``10.NNNN/`` 两形）、邮箱。整段剥净这些后
#: 无拉丁字母残量 → 输出=输入是正确态而非回显——est 阈值挡不住裸链的 token
#: 计数（t_887e62c5f741ccbe 实证：裸 huggingface 链 est=12 越线被死锁）。
_NONLING_RX: Final = re.compile(
    r"\\(?:url|href|doi|path)\{[^{}]*\}(?:\{[^{}]*\})?"
    r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
    r"|(?:https?://|www\.)[^\s{}\[\]()<>'\"]+"
    r"|\bdoi:\s*\S+"
    r"|\b10\.\d{4,9}/[^\s{}\[\]()<>'\"]+"
)

#: 残英 issue 消息的 run 展示截断。
_RESID_EN_SHOW: Final = 80


def _cjk_latin_counts(s: str) -> tuple[int, int]:
    """``(CJK 字符数，ASCII 拉丁字母数)``——same_source/length 的 CJK 占比判定共用口径。"""
    return len(CJK_RX.findall(s)), sum(1 for c in s if c.isascii() and c.isalpha())


def _check_same_source(ctx: _Ctx) -> None:
    r"""整段原文回显拒收（E24）：规范化等值 src==zh 且拉丁主导 → error。

    豁免：``[[BIB_`` bib 直通块（留英合法）、剥后 src <10 est_token
    （纯占位符/短残段——输出=输入是正确态，babeldoc ``input_token_count>10``
    同口径）、整段纯非语言成分（URL/DOI/邮箱/``\url`` 包裹类——恒等即
    正确译文，裸链 est 可越 10 线）、人名/专名列 src（verbatim 回显即
    正确态——``name_list_prose`` 判据，与 ``residual_en`` run 级豁免
    同签名；web t_4000988e seq-234 est=629 贡献者名单实证）。仅规范化
    等值比较不取近似度——qualbase 实测 >0.85 相似档唯一命中是合法邮箱块；
    拉丁主导门槛豁免 ``zh==en`` 含 CJK 的合法恒等译文（share.py 收录
    口径同款情形）。
    """
    if "[[BIB_" in ctx.src:
        return
    # ``est_tokens`` 只数 CJK + 非空白字符，大小写不变——共享未小写视图的
    # est 与 ``ss`` 上重算同值（length 臂消费同一 ``ctx.est_src``）。
    # ``name_list_prose`` 须吃未小写 ``prose_src``——首字母大写占比是判据本体。
    ss, sz = ctx.prose_src.lower(), ctx.prose_zh.lower()
    if ctx.est_src < _MIN_PROSE_TOKENS or ss != sz or name_list_prose(ctx.prose_src):
        return
    if not re.search(r"[a-z]", _NONLING_RX.sub("", ss)):
        return
    cjk, lat = _cjk_latin_counts(ss)
    if lat >= _MIN_LATIN_FOR_CJK_CHECK and cjk / (cjk + lat) < CJK_SHARE_MIN:
        ctx.issues.append(
            Issue(
                "same_source",
                Severity.ERROR,
                f"整段原文回显（剥占位符规范化后 src==zh，est={ctx.est_src:.0f}）",
            )
        )


def _check_length(ctx: _Ctx) -> None:
    """长度比 sanity（E24 token 代理口径）+ 疑似未翻译（拉丁字符占比）。

    长度比：剥后 est_token 比出 [0.3,3.0] → error 拒收（src est<10 豁免）。
    CJK 占比：zh 剥后拉丁主导（share<0.30）→ warn 疑似未翻译。
    """
    issues = ctx.issues
    sz = ctx.prose_zh
    ts = ctx.est_src
    if ts >= _MIN_PROSE_TOKENS:
        tz = ctx.est_zh
        r = tz / ts
        hi = (
            TOKEN_RATIO_HI_NAMELIST
            if name_list_prose(ctx.prose_src)
            else TOKEN_RATIO_HI
        )
        if not TOKEN_RATIO_LO <= r <= hi:
            issues.append(
                Issue(
                    "length",
                    Severity.ERROR,
                    f"长度比(token 代理) {r:.2f} 超出 "
                    f"[{TOKEN_RATIO_LO},{hi}] "
                    f"(src~{ts:.0f} zh~{tz:.0f})",
                )
            )
    cjk, lat = _cjk_latin_counts(sz)
    if lat >= _MIN_LATIN_FOR_CJK_CHECK:
        share = cjk / (cjk + lat)
        if share < CJK_SHARE_MIN:
            issues.append(
                Issue(
                    "length",
                    Severity.WARN,
                    f"CJK 占比 {share:.0%} <{CJK_SHARE_MIN:.0%} "
                    f"(lat={lat} cjk={cjk}) — 疑似未翻译",
                )
            )


def _check_residual_en(ctx: _Ctx) -> None:
    """段内残英句拒收（seq-49/51 实证补网）：zh 夹未翻译英文 run → error。

    ``_check_same_source`` 只拦整段回显、``_check_length`` CJK 占比是
    warn 且要拉丁主导——行级修复把 audit 失败的行按原文装回、或模型
    半译应答，都会在中文段里留下整句英文而两网全盲（阶梯 ``recovered``
    落 DB ``ok`` 静默出货）。判定口径全在 ``textutil.residual_en_net``
    （CJK 切 run / verbatim 子串 + 混血长句 / 人名豁免 / BIB 直通豁免），
    与 pipeline ``_intercept_residual_en`` 逐字节一致。
    """
    ctx.issues.extend(
        Issue(
            "residual_en",
            Severity.ERROR,
            f"译文残留未翻译英文 run: {run[:_RESID_EN_SHOW]}"
            f"{'…' if len(run) > _RESID_EN_SHOW else ''}"
            "（行级修复原文回退/半译签名）",
            found=run,
        )
        for run in residual_en_net(ctx.src, ctx.zh)
    )
