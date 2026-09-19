"""L0 校验洞补丁测试：item_glue 粘合签名 + 注释区占位符逃逸 + 注释尾段。

实证背景：
- item_glue：译文把 ``\\item`` 与后随词粘成 ``\\itemFSU``/``\\itemNGA``/
  ``\\itemBalakrishnan`` 类未定义控制序列（8 篇 Undefined cs 编译炸弹，
  bench/results/l2-attr-probe-2026-09-16/probe.jsonl）。base 臂全 clean，
  纯属翻译侧产出 → zh 净多出计 warn。
- 注释区占位符：``_check_placeholder`` 对双侧 mask_comments 后比 multiset，
  ``%`` 行内臆造 ``[[MATH_966]]`` 不可见 → 放行 → splice 字面残留
  （mock-sabotage 实测逃逸 1012.5411 chunk 7:1）→ zh 注释区净多出计 error。
- comment_eof：stagerun-rt1 ``\\@xdblarg`` runaway 族 ×4 cell 同形
  （1109.5754/0905.1718/1306.5799/2003.10917）——corrector 臂丢 chunk 尾
  ``[[COMMENT_n]]`` 的终结 ``\\n``，splice 把后随字面首行（含 ``\\caption{``
  的 ``}``）吞进注释行 → ``\\caption{`` 不闭合。``bare_token_audit`` 对
  未编码 src 的 ``[[SL]]`` 基线恒 0 看不见 → zh 尾段未终结注释计 error。
"""

import pytest

from texlate.validate.l0 import L0Report, Severity, validate_pair


def _issues(rep: L0Report, rule: str) -> list:
    return [i for i in rep.issues if i.rule == rule]


# ---------------------------------------------------------------- item_glue


def test_item_glue_single_hit() -> None:
    """``\\item FSU`` → ``\\itemFSU``：粘合产物报 item_glue warn。"""
    src = "\\begin{itemize}\n\\item FSU works.\n\\end{itemize}"
    zh = "\\begin{itemize}\n\\itemFSU 工作正常。\n\\end{itemize}"
    rep = validate_pair(src, zh)
    hits = _issues(rep, "item_glue")
    assert hits, str(rep)
    assert hits[0].severity is Severity.WARN
    assert "itemFSU" in hits[0].message


def test_item_glue_multi_count() -> None:
    """多处粘合聚成一条，N=净多出计数。"""
    src = "\\item FSU\n\\item NGA\n\\item Balakrishnan"
    zh = "\\itemFSU 甲\n\\itemNGA 乙\n\\itemBalakrishnan 丙"
    rep = validate_pair(src, zh)
    hits = _issues(rep, "item_glue")
    assert len(hits) == 1
    assert "×3" in hits[0].message


def test_item_glue_clean_item_no_hit() -> None:
    """正常 ``\\item 文本`` 不报。"""
    src = "\\begin{itemize}\n\\item First\n\\item Second\n\\end{itemize}"
    zh = "\\begin{itemize}\n\\item 第一\n\\item 第二\n\\end{itemize}"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "item_glue"), str(rep)


def test_item_glue_src_side_exempt() -> None:
    """src 自带同形（``\\itemsep`` 合法 cs / ``\\itemFSU`` 原文粘连）不追责。"""
    src = "\\setlength{\\itemsep}{2pt}\n\\item FSU"
    zh = "\\setlength{\\itemsep}{2pt}\n\\itemFSU 甲"
    rep = validate_pair(src, zh)
    # zh 多出 itemFSU×1、itemsep 双边抵消 → 只报 itemFSU 一枚
    hits = _issues(rep, "item_glue")
    assert len(hits) == 1
    assert "itemFSU" in hits[0].message
    assert "itemsep" not in hits[0].message
    # 双边同形完全保留 → 无 item_glue
    rep2 = validate_pair(src, src)
    assert not _issues(rep2, "item_glue"), str(rep2)


def test_item_glue_comment_exempt() -> None:
    """注释区里的 ``\\itemX`` 是死文本，不报。"""
    src = "\\item a\n\\item b"
    zh = "\\item 甲\n\\item 乙 % \\itemFSU 残留"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "item_glue"), str(rep)


def test_item_glue_double_backslash_not_misread() -> None:
    """``\\\\itemX`` 是 ``\\\\`` 断行 + 文本 itemX，非粘合 cs——_lex 口径不误判。"""
    src = "行一 \\\\\n行二"
    zh = "行一 \\\\\nitemFSU 文本"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "item_glue"), str(rep)


# ------------------------------------------------------- 注释区占位符逃逸


def test_comment_placeholder_hallucinated_caught() -> None:
    """zh 注释行臆造 ``[[MATH_966]]`` → error（sabotage 逃逸场景复现）。"""
    src = "公式 [[MATH_1]] 如下。"
    zh = "公式 [[MATH_1]] 如下。\n% 备注 [[MATH_966]]"
    rep = validate_pair(src, zh)
    assert not rep.ok
    hits = [i for i in _issues(rep, "placeholder") if "注释" in i.message]
    assert hits, str(rep)
    assert hits[0].severity is Severity.ERROR
    assert "MATH_966" in hits[0].message


def test_comment_placeholder_same_shape_clean() -> None:
    """src 注释区占位符被 zh 注释保留 → 净差为零，不报。"""
    src = "见 [[MATH_1]]。% TODO check [[MATH_3]]"
    zh = "见 [[MATH_1]]。% 待查 [[MATH_3]]"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "placeholder"), str(rep)


def test_comment_placeholder_dropped_with_comment_ok() -> None:
    """zh 整条丢掉含占位符注释 → 死文本丢弃不追责（注释豁免语义）。"""
    src = "见 [[MATH_1]]。% TODO check [[MATH_3]]"
    zh = "见 [[MATH_1]]。"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "placeholder"), str(rep)


def test_comment_plain_diff_no_fp() -> None:
    """正常注释差异（新增/改写纯文本注释）不触发占位符报错。"""
    src = "见 [[MATH_1]]。% a note"
    zh = "见 [[MATH_1]]。% 中文注释，不含任何占位符"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "placeholder"), str(rep)


def test_body_placeholder_moved_into_comment_still_missing() -> None:
    """正文占位符被挪进注释：masked multiset 的 missing 方向仍然抓得到。

    这是方案 (a)（全文未遮盖比对）会放行的反方向——注释区专项检查
    与 masked 主口径并行，两个方向都覆盖。
    """
    src = "公式 [[MATH_1]] 如下。"
    zh = "公式如下。% [[MATH_1]]"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("缺失" in i.message for i in _issues(rep, "placeholder"))


# ------------------------------------------- 真实逃逸样本回归（1012.5411）


def test_comment_placeholder_real_escape_1012_5411() -> None:
    """mock-sabotage recount 实际逃逸件原样回放。

    bench/results/mock-sabotage-v3-2026-09-16/v3/recount.jsonl：
    1012.5411 rngeo4.tex chunk 7:1，fabricate_ph ``[[MATH_966]]``@46——
    src 段几乎全为 ``%`` 注释（含 CRLF），zh 在 ``%`` 行内注入占位符。
    """
    src = (
        "% Body of paper goes here. Use proper sectioning commands. \r\n"
        "% References should be done using the \\cite, \\ref, and \\label commands\r\n"
        "\\section{} \n%\\label{}\r\n\\subsection{} \n\\subsubsection{}"
    )
    zh = (
        "% 这是译文. \n% 这是译文 \\cite, \\ref, 这是译文 \\label "
        "[[MATH_966]]这是译文\n\\section{} \n%\\label{}\n\\subsection{} "
        "\n\\subsubsection{}"
    )
    rep = validate_pair(src, zh)
    assert not rep.ok
    hits = [i for i in _issues(rep, "placeholder") if "注释" in i.message]
    assert hits, str(rep)
    assert "MATH_966" in hits[0].message


# ------------------------------------------------------- 注释区边缘变体


def test_comment_placeholder_midline_and_double_percent() -> None:
    """行中 ``%`` 与 ``%%`` 注释同样遮盖，藏入占位符均报错。"""
    src = "公式 [[MATH_1]] 如下。"
    for tail in ("% 注 [[MATH_966]]", "%% 注 [[MATH_966]]"):
        rep = validate_pair(src, f"公式 [[MATH_1]] 如下。{tail}")
        hits = [i for i in _issues(rep, "placeholder") if "注释" in i.message]
        assert hits, tail
        assert "MATH_966" in hits[0].message


def test_comment_placeholder_eof_no_newline() -> None:
    """注释延伸到 EOF 无换行，占位符仍被点算。"""
    src = "公式 [[MATH_1]] 如下。"
    zh = "公式 [[MATH_1]] 如下。\n% tail [[MATH_966]]"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("MATH_966" in i.message for i in _issues(rep, "placeholder"))


def test_comment_placeholder_multiple_tokens_each_reported() -> None:
    """注释内多枚臆造占位符逐枚报错。"""
    src = "公式 [[MATH_1]] 如下。"
    zh = "公式 [[MATH_1]] 如下。\n% [[MATH_966]] 与 [[ENV_7]]"
    rep = validate_pair(src, zh)
    hits = [i for i in _issues(rep, "placeholder") if "注释" in i.message]
    assert {i.found for i in hits} == {"[[MATH_966]]", "[[ENV_7]]"}
    assert all(i.severity is Severity.ERROR for i in hits)


def test_escaped_percent_body_placeholder_main_path() -> None:
    r"""``\%`` 不是注释：其后占位符走正文主口径（多余方向），不进注释专项。"""
    src = "占比 50\\% 见 [[MATH_1]]。"
    zh = "占比 50\\% 见 [[MATH_1]] 与 [[MATH_966]]。"
    rep = validate_pair(src, zh)
    hits = _issues(rep, "placeholder")
    assert not rep.ok
    assert any("多余" in i.message for i in hits)
    assert not any("注释" in i.message for i in hits)


def test_comment_env_placeholder_caught_by_main_path() -> None:
    r"""comment.sty ``\begin{comment}`` 环境**不被** mask_comments 遮盖——
    其内占位符走正文主口径报"多余"，src 已有同环境时亦不逃。"""
    src = "公式 [[MATH_1]]。\n\\begin{comment}\nold note\n\\end{comment}"
    zh = "公式 [[MATH_1]]。\n\\begin{comment}\nold note [[MATH_966]]\n\\end{comment}"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any(
        "多余" in i.message and "MATH_966" in i.message
        for i in _issues(rep, "placeholder")
    )


# --------------------------------- 畸形变体注释区逃逸（zh_fuzzy 未遮盖修复）


@pytest.mark.parametrize(
    "bad",
    ["[[math_966]]", "【MATH_966】", "[[MATH_966]", "[MATH_966]"],
    ids=["lowercase", "fullwidth", "missing-bracket", "single-bracket"],
)
def test_comment_placeholder_malformed_variant_caught(bad: str) -> None:
    """畸形占位符变体藏进 ``%`` 注释 → error。

    ``zh_fuzzy`` 曾扫 masked ``znc`` 致注释内变体不可见（残余洞）；
    改扫未遮盖 ``zh`` 后与 ``xlat.placeholders.diff`` 同口径，全部捕获。
    """
    src = "公式 [[MATH_1]] 如下。"
    zh = f"公式 [[MATH_1]] 如下。\n% 备注 {bad}"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert _issues(rep, "placeholder"), str(rep)


def test_comment_malformed_variant_feeds_lev_pairing() -> None:
    """注释内畸形 token 一样进 lev 配对：missing 方向拼错建议方向仍对。"""
    src = "公式 [[MATH_1]] 与 [[MATH_2]]。"
    zh = "公式 [[MATH_1]]。\n% [[MATH_2]"  # 缺右括号变体
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any(
        i.expected == "[[MATH_2]]" and i.found == "[[MATH_2]"
        for i in _issues(rep, "placeholder")
    ), str(rep)


def test_comment_plain_text_no_tag_shape_clean() -> None:
    """干净对回归：zh 注释正常文本（含 ``[RS80]`` 引用标号样式）不 FP。

    src 注释自带 ``[RS80]`` → ``src_literal`` 净差豁免；``Smith 2020``
    无 ``[Xn]``/``[[..]]`` 形同 token。
    """
    src = "见 [[MATH_1]]。% see [RS80] for details"
    zh = "见 [[MATH_1]]。% 参考 [RS80] 与 Smith 2020 的工作"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "placeholder"), str(rep)


def test_comment_zh_new_bracket_tag_is_residue() -> None:
    """zh 注释新增 src 没有的 ``[Xn]`` 形 token → 按多余占位符报。

    与正文口径一致（正文新增 ``[RS80]`` 本报"多余/未识别"）——
    注释文本 splice 后同样字面残留。
    """
    src = "见 [[MATH_1]]。% a note"
    zh = "见 [[MATH_1]]。% 参考 [RS80]"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("[RS80]" in i.message for i in _issues(rep, "placeholder"))


# ------------------------------------------------------- comment_eof 注释尾段


def test_comment_eof_rt1_shape_caught() -> None:
    """rt1 实证形态：src 尾 ``[[COMMENT_n]]\\n``、zh 尾丢 ``\\n`` → error。

    stagerun-rt1 1109.5754 chunk 0:6：corrector 二试把 chunk 尾注释的终结
    换行丢掉——placeholder multiset 吻合（token 本身在），brace/env 全平衡，
    唯独 splice 后紧随字面行被注释吞掉。
    """
    src = "如图 [[MATH_1]] 所示。% see note\n[[COMMENT_1]]\n"
    zh = "如图 [[MATH_1]] 所示。% 见注释\n[[COMMENT_1]]"
    rep = validate_pair(src, zh)
    assert not rep.ok
    hits = _issues(rep, "comment_eof")
    assert len(hits) == 1, str(rep)
    assert hits[0].severity is Severity.ERROR
    assert hits[0].found == "[[COMMENT_1]]"


def test_comment_eof_terminated_clean() -> None:
    """zh 尾 ``[[COMMENT_n]]\\n`` 终结正常 → 不报。"""
    src = "文 [[MATH_1]]。[[COMMENT_1]]\n"
    zh = "文 [[MATH_1]]。[[COMMENT_1]]\n"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "comment_eof"), str(rep)


def test_comment_eof_trailing_space_still_unterminated() -> None:
    """``[[COMMENT_n]]`` 后只余空格/制表符 → 仍未终结（空白非注释终结符）。"""
    src = "文 [[MATH_1]]。[[COMMENT_1]]\n"
    for tail in (" ", "\t", "  "):
        zh = f"文 [[MATH_1]]。[[COMMENT_1]]{tail}"
        rep = validate_pair(src, zh)
        hits = _issues(rep, "comment_eof")
        assert hits, repr(tail)
        assert hits[0].severity is Severity.ERROR


def test_comment_eof_trailing_newline_then_space_clean() -> None:
    """``[[COMMENT_n]]\\n  `` —— ``\\n`` 已终结注释，尾随空白无害。"""
    src = "文 [[MATH_1]]。[[COMMENT_1]]\n"
    zh = "文 [[MATH_1]]。[[COMMENT_1]]\n  "
    rep = validate_pair(src, zh)
    assert not _issues(rep, "comment_eof"), str(rep)


def test_comment_eof_literal_percent_caught() -> None:
    r"""字面 ``%`` 注释延伸到 zh EOF 无换行 → error（``_lex`` 末 token 判）。"""
    src = "文 [[MATH_1]]。\n% a note\n"
    zh = "文 [[MATH_1]]。\n% 中文注释"
    rep = validate_pair(src, zh)
    hits = _issues(rep, "comment_eof")
    assert len(hits) == 1, str(rep)
    assert hits[0].found == "%"


def test_comment_eof_escaped_percent_not_comment() -> None:
    r"""zh 尾 ``\%`` 是转义 bs token 非注释 → 不报。"""
    src = "占比 50\\%\n"
    zh = "占比 50\\%"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "comment_eof"), str(rep)


def test_comment_eof_src_same_shape_exempt() -> None:
    """src 尾段同形未终结注释 → zh 复现不追责（继承容忍，防恒等对 FP）。

    源 chunk 以未终结注释收尾时，其后随字面本就以该注释的 ``\\n`` 终结符
    起头——zh 同形即忠实复现该 seam。
    """
    src = "文 [[MATH_1]]。[[COMMENT_1]]"
    zh = "文 [[MATH_1]]。[[COMMENT_1]]"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "comment_eof"), str(rep)


def test_comment_eof_src_literal_percent_exempt() -> None:
    """src/zh 双尾皆为未终结字面 ``%`` → 豁免。"""
    src = "文 [[MATH_1]]。% tail note"
    zh = "文 [[MATH_1]]。% 尾注"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "comment_eof"), str(rep)


def test_comment_eof_ph_then_text_is_anchor_domain() -> None:
    """``[[COMMENT_n]]foo`` 尾段：token 后随非空白 → 非本规则判据。

    ``%`` 展开吞到 EOL 而后随文本仍在同一注释行——属 ``_check_ph_anchor``
    的 COMMENT 整行锚定混入判据，此处不重复报。
    """
    src = "文 [[MATH_1]]。[[COMMENT_1]]\n"
    zh = "文 [[MATH_1]]。[[COMMENT_1]]混入行"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "comment_eof"), str(rep)


def test_comment_eof_midbody_comment_then_text_clean() -> None:
    """注释在行中、其后还有正文行 → 尾段无未终结注释，不报。"""
    src = "% note\n文 [[MATH_1]]。"
    zh = "% 注\n文 [[MATH_1]]。"
    rep = validate_pair(src, zh)
    assert not _issues(rep, "comment_eof"), str(rep)
