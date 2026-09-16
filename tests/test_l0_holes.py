"""L0 校验洞补丁测试：item_glue 粘合签名 + 注释区占位符逃逸。

实证背景：
- item_glue：译文把 ``\\item`` 与后随词粘成 ``\\itemFSU``/``\\itemNGA``/
  ``\\itemBalakrishnan`` 类未定义控制序列（8 篇 Undefined cs 编译炸弹，
  bench/results/l2-attr-probe-2026-09-16/probe.jsonl）。base 臂全 clean，
  纯属翻译侧产出 → zh 净多出计 warn。
- 注释区占位符：``_check_placeholder`` 对双侧 mask_comments 后比 multiset，
  ``%`` 行内臆造 ``[[MATH_966]]`` 不可见 → 放行 → splice 字面残留
  （mock-sabotage 实测逃逸 1012.5411 chunk 7:1）→ zh 注释区净多出计 error。
"""

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
