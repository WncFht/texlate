"""xlat.placeholders.diff 注释区占位符洞补丁测试（与 L0 l0.py 同口径）。

masked 主比对看不见 ``%`` 行内容——zh 注释内臆造 ``[[MATH_966]]`` 逃逸 →
splice 字面残留（mock-sabotage 实测 1012.5411）。补丁口径：zh 注释区净多出
计 ``extra``；src 注释同形豁免、zh 丢注释不追责；正文占位符被挪进注释仍走
masked missing（双向都覆盖，全文未遮盖单方案做不到的半边）。
"""

from texlate.xlat.placeholders import diff

# ------------------------------------------------------- 注释区占位符逃逸


def test_comment_hallucinated_lands_in_extra() -> None:
    """zh 注释行臆造 ``[[MATH_966]]`` → 计 extra（sabotage 逃逸场景复现）。"""
    src = "公式 [[MATH_1]] 如下。"
    zh = "公式 [[MATH_1]] 如下。\n% 备注 [[MATH_966]]"
    d = diff(src, zh)
    assert not d.ok
    assert "[[MATH_966]]" in d.extra
    assert "MATH_966" in d.describe()


def test_comment_same_shape_both_sides_clean() -> None:
    """src 注释区占位符被 zh 注释保留 → 净差为零，不报。"""
    src = "见 [[MATH_1]]。% TODO check [[MATH_3]]"
    zh = "见 [[MATH_1]]。% 待查 [[MATH_3]]"
    d = diff(src, zh)
    assert d.ok, d.describe()


def test_comment_dropped_with_placeholder_ok() -> None:
    """zh 整条丢掉含占位符注释 → 死文本丢弃不追责（注释豁免语义）。"""
    src = "见 [[MATH_1]]。% TODO check [[MATH_3]]"
    zh = "见 [[MATH_1]]。"
    d = diff(src, zh)
    assert d.ok, d.describe()


def test_comment_plain_diff_no_fp() -> None:
    """正常注释差异（新增/改写纯文本注释）不触发。"""
    src = "见 [[MATH_1]]。% a note"
    zh = "见 [[MATH_1]]。% 中文注释，不含任何占位符"
    d = diff(src, zh)
    assert d.ok, d.describe()


def test_body_placeholder_moved_into_comment() -> None:
    """正文占位符被挪进注释：missing（masked 主口径）与 extra（注释区）同时报。"""
    src = "公式 [[MATH_1]] 如下。"
    zh = "公式如下。% [[MATH_1]]"
    d = diff(src, zh)
    assert not d.ok
    assert "[[MATH_1]]" in d.missing
    assert "[[MATH_1]]" in d.extra


def test_comment_extra_not_lev_paired() -> None:
    """注释区 token 不喂 lev 拼错配对——独立缺陷，不算 missing 的候选。"""
    src = "公式 [[MATH_1]] 与 [[MATH_2]]。"
    zh = "公式 [[MATH_1]]。\n% [[MATH_9]]"
    d = diff(src, zh)
    assert "[[MATH_2]]" in d.missing
    assert "[[MATH_9]]" in d.extra
    assert not d.misspelled


def test_describe_feedback_mentions_comment_extra() -> None:
    """corrector 反馈路径（retry/pipeline 走 describe()）能看到注释残留。"""
    src = "见 [[MATH_1]]。"
    zh = "见 [[MATH_1]]。% tail [[ENV_7]]"
    d = diff(src, zh)
    assert "extra/unrecognized placeholder: [[ENV_7]]" in d.describe()
