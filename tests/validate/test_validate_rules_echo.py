"""rules 交付守卫：protocol_echo 协议回显 + COMMENT 占位符行锚定。

实证背景（bench/results/repro-2410b-2026-09-16/report.md §4b/§4c）：

- §4b 协议回显：Mode-B mock 把三段式 corrector prompt 当正文翻，交付 zh
  带 ``[这是译文]`` 节标 + ``占位符缺失:`` 反馈行 + body 重复——占位符
  multiset 吻合、载荷脏（内容载荷通道逃逸）。真模型 parrot prompt
  furniture 是同款通道 → zh 净多出协议字面即 error → 阶梯回退原文。
- §4c COMMENT 锚定：``[[COMMENT_n]]`` 展开是 ``%`` 注释吞到 EOL——src
  独占整行的 ph 在 zh 同行混入任何非注释内容，前缀是 splice 残留垃圾、
  后缀成死字节（该例反馈行前缀 + chunk 外 ``}`` 后缀双杀 ``\\caption``）。
"""

import pytest
from conftest import _issues

from texlate.validate.rules import _ECHO_SIGS, Severity, validate_pair

# ---------------------------------------------------------------- protocol_echo


@pytest.mark.parametrize("sig", _ECHO_SIGS)
def test_echo_each_literal_caught(sig: str) -> None:
    """``_ECHO_SIGS`` 全标记逐个入 zh → protocol_echo error（子串口径）。"""
    src = "结果见 [[MATH_1]] 与 [[MATH_2]]。"
    zh = f"结果见 [[MATH_1]] 与 [[MATH_2]]。\n{sig} 若干内容"
    rep = validate_pair(src, zh)
    assert not rep.ok, sig
    hits = _issues(rep, "protocol_echo")
    assert hits
    assert all(i.severity is Severity.ERROR for i in hits)
    assert any(sig in i.message for i in hits)


def test_echo_section_markers_caught() -> None:
    """三段式节标齐入 zh → error（mock/真模型 echo 形态）。"""
    src = "结果见 [[MATH_1]]。"
    zh = "[Original]\n[Translation]\n结果见 [[MATH_1]]\n[Error]\n无错误"
    rep = validate_pair(src, zh)
    assert not rep.ok
    toks = {i.found for i in _issues(rep, "protocol_echo")}
    assert {"[Original]", "[Translation]", "[Error]"} <= toks


def test_echo_previous_validation_error_marker() -> None:
    """字段化反馈节标 ``[previous_validation_error]`` → 命中裸标记 → error。"""
    src = "结果见 [[MATH_1]]。"
    zh = "结果见 [[MATH_1]]\n[previous_validation_error]\n占位符缺失: x"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any(
        "previous_validation_error" in i.message for i in _issues(rep, "protocol_echo")
    )


def test_echo_repro_2410b_shape() -> None:
    """repro 现场形状：multiset 吻合仅载荷脏 → 仍 FAIL（反馈行 + COMMENT 锚定双杀）。"""
    src = "段一 [[MATH_1]]。\n[[COMMENT_1]]\n段二收尾。"
    zh = "段一 [[MATH_1]]。\n占位符缺失: [[COMMENT_1]]\n段二收尾。"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert _issues(rep, "protocol_echo")
    # 同一行也是 COMMENT 锚定违例——两层守卫各自独立命中
    assert any("注释占位符" in i.message for i in _issues(rep, "placeholder"))


def test_echo_only_issue_blocks_delivery() -> None:
    """仅回显一项即 ok=False 且 feedback() 非空——阶梯据此走重译/fallback。"""
    src = "结果见 [[MATH_1]]。"
    zh = "结果见 [[MATH_1]]\n[Error]"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert rep.feedback()


def test_echo_multi_count_aggregated() -> None:
    """同字面多次回显聚成 ×N；src 自带量先净差抵扣。"""
    src = "字段说明。\n[Error]\n结果见 [[MATH_1]]。"
    zh = "字段说明。\n[Error]\n结果见 [[MATH_1]]\n[Error]\n[Error]"
    rep = validate_pair(src, zh)
    hits = [i for i in _issues(rep, "protocol_echo") if i.found == "[Error]"]
    assert hits
    assert "×2" in hits[0].message, str(rep)


# ------------------------------------------------------- protocol_echo 防误报


def test_echo_zh_bracket_line_no_fp() -> None:
    """``[这是译文]`` 独行不作标记（report §4a：``[word]`` 合法产出同款）。"""
    src = "Results [Ours] are shown [[MATH_1]]."
    zh = "结果见 [[MATH_1]]。\n[这是译文]\n收尾。"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "protocol_echo"), str(rep)


def test_echo_inline_marker_no_fp() -> None:
    """src 同数含 ``[Error]``/``[Translation]`` → zh 照搬净差为零不报。"""
    src = "The field [Error] and [Translation] show status [[MATH_1]]."
    zh = "字段 [Error] 和 [Translation] 显示状态 [[MATH_1]]。"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "protocol_echo"), str(rep)


def test_echo_inline_extra_marker_caught() -> None:
    """zh 行内凭空多出节标（src 无对应）→ error——子串口径不要求独行。"""
    src = "状态字段显示 [[MATH_1]]。"
    zh = "状态字段 [Error] 显示 [[MATH_1]]。"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any(i.found == "[Error]" for i in _issues(rep, "protocol_echo"))


def test_echo_bare_duoyu_no_fp() -> None:
    """裸 ``多余`` 不是标记（合并字面才入表）——普通译文词汇不误伤。"""
    src = "We drop the redundant token [[MATH_1]]."
    zh = "我们丢弃多余的 token [[MATH_1]]。"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "protocol_echo"), str(rep)


def test_echo_other_rules_stems_out_of_vocab() -> None:
    """``未闭合`` 等其余 rules error 词干不在词表（留扩展位，暂不命中）。"""
    src = "环境见 [[MATH_1]]。"
    zh = "环境见 [[MATH_1]]。\n未闭合 ×2"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "protocol_echo"), str(rep)


def test_echo_src_inherited_marker_exempt() -> None:
    """src 自带独立节标行（协议讨论稿）→ zh 保留是忠实翻译，净差不报。"""
    src = "Format:\n[Error]\ndetails follow [[MATH_1]]."
    zh = "格式：\n[Error]\n细节见 [[MATH_1]]。"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "protocol_echo"), str(rep)


def test_echo_src_inherited_literal_exempt() -> None:
    """src 正文自带同形反馈字面（本系统自述论文边角）→ 净差豁免。"""
    src = "规则 占位符缺失: 表示丢 token，见 [[MATH_1]]。"
    zh = "规则 占位符缺失: 表示丢 token，见 [[MATH_1]]。"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "protocol_echo"), str(rep)


def test_echo_clean_pair_no_fp() -> None:
    """干净对零命中。"""
    src = "We propose [[MATH_1]] following \\cite{a}."
    zh = "我们提出 [[MATH_1]]，遵循 \\cite{a}。"
    rep = validate_pair(src, zh)
    assert rep.ok, str(rep)


# ------------------------------------------------------- COMMENT ph 行锚定


def test_comment_ph_standalone_clean() -> None:
    """src/zh 均独占整行 → 干净。"""
    src = "段一。\n[[COMMENT_1]]\n段二 [[MATH_1]]。"
    zh = "段一译。\n[[COMMENT_1]]\n段二译 [[MATH_1]]。"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "placeholder"), str(rep)


def test_comment_ph_indented_standalone_clean() -> None:
    """缩进整行仍算独占（``[ \\t]`` 豁免）。"""
    src = "段一。\n    [[COMMENT_1]]\n段二。"
    zh = "段一译。\n  [[COMMENT_1]]\n段二译。"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "placeholder"), str(rep)


def test_comment_ph_prefix_junk_caught() -> None:
    """src 独占整行，zh 前缀混入文本 → error（splice 残留注入注释槽位）。"""
    src = "段一。\n[[COMMENT_1]]\n段二。"
    zh = "段一译。\n残留垃圾 [[COMMENT_1]]\n段二译。"
    rep = validate_pair(src, zh)
    assert not rep.ok
    hits = [i for i in _issues(rep, "placeholder") if "注释占位符" in i.message]
    assert hits
    assert hits[0].severity is Severity.ERROR


def test_comment_ph_suffix_junk_caught() -> None:
    """src 独占整行，zh 后缀混入文本 → error（``%`` 吃掉成死字节）。"""
    src = "段一。\n[[COMMENT_1]]\n段二。"
    zh = "段一译。\n[[COMMENT_1]] 死字节尾巴\n段二译。"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("注释占位符" in i.message for i in _issues(rep, "placeholder"))


def test_comment_ph_mixed_ph_line_caught() -> None:
    """同行混非注释占位符 → 后者会被 ``%`` 吃掉 → error。"""
    src = "见 [[MATH_1]]。\n[[COMMENT_1]]\n收尾。"
    zh = "见。\n[[COMMENT_1]] [[MATH_1]]\n收尾。"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("注释占位符" in i.message for i in _issues(rep, "placeholder"))


def test_comment_ph_multi_pure_line_ok() -> None:
    """多枚注释占位符共行合法——``%`` 相连仍是注释，输出等价。"""
    src = "段一。\n[[COMMENT_1]]\n[[COMMENT_2]]\n段二。"
    zh = "段一译。\n[[COMMENT_1]] [[COMMENT_2]]\n段二译。"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "placeholder"), str(rep)


def test_comment_ph_src_midline_exempt() -> None:
    """src 行中注释 ph（参数内 ``%`` 提取，恒处行尾）→ zh 同款行中不追责。

    对照 ``test_segmenter_semantics``：``Title [[COMMENT_1]]\\nrest words``
    是合法 chunk 形态——src 非整行锚定 → 前缀不限制，只查尾段。
    """
    src = "Title text [[COMMENT_1]]\nrest words"
    zh = "标题文字 [[COMMENT_1]]\n其余词"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "placeholder"), str(rep)


def test_comment_ph_src_midline_zh_suffix_caught() -> None:
    """src 行中（行尾）ph → zh 后随非注释内容 = 死字节 → error。"""
    src = "Title text [[COMMENT_1]]\nrest words"
    zh = "标题 [[COMMENT_1]] 尾巴\n其余词"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("注释占位符" in i.message for i in _issues(rep, "placeholder"))


def test_comment_ph_zh_trailing_comment_exempt() -> None:
    """zh ph 后随 ``%`` 注释：mask 后行尾只剩空白，且 splice 同样全死 → 不报。"""
    src = "段一。\n[[COMMENT_1]]\n段二。"
    zh = "段一译。\n[[COMMENT_1]] % 译注\n段二译。"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "placeholder"), str(rep)


def test_comment_ph_crlf_clean() -> None:
    """CRLF 行尾 ``\\r`` 不破坏独占整行判定。"""
    src = "段一。\r\n[[COMMENT_1]]\r\n段二。"
    zh = "段一译。\r\n[[COMMENT_1]]\r\n段二译。"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "placeholder"), str(rep)


def test_comment_ph_crlf_junk_caught() -> None:
    """CRLF 下同上判据生效。"""
    src = "段一。\r\n[[COMMENT_1]]\r\n段二。"
    zh = "段一译。\r\n残留 [[COMMENT_1]]\r\n段二译。"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("注释占位符" in i.message for i in _issues(rep, "placeholder"))


def test_bibitem_anchor_regression() -> None:
    """BIBITEM 行首锚定旧行为不变（COMMENT 扩展不影响）。"""
    src = "[[BIBITEM_1]] Vaswani et al., attention is all you need."
    zh = "Vaswani 等人 [[BIBITEM_1]]。"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("行首" in i.message for i in _issues(rep, "placeholder"))
