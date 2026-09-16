"""L0 七规则正反例 + 已知误报陷阱用例（B6 变异器防误报面）。"""

from texlate.validate.l0 import L0Report, Severity, validate_pair


def _sev(rep: L0Report, rule: str) -> list[Severity]:
    return [i.severity for i in rep.issues if i.rule == rule]


# ---------------------------------------------------------------- 干净对


def test_clean_pair_passes() -> None:
    src = (
        "We propose a method [[MATH_1]] following \\cite{vaswani2017} "
        "and \\ref{fig:arch}; see \\eqref{eq:loss}."
    )
    zh = (
        "我们提出一种方法 [[MATH_1]]，遵循 \\cite{vaswani2017} "
        "和 \\ref{fig:arch}；见 \\eqref{eq:loss}。"
    )
    rep = validate_pair(src, zh)
    assert rep.ok, str(rep)
    assert rep.n_error == 0


def test_clean_pair_with_env() -> None:
    src = "\\begin{theorem}\nIf [[MATH_1]] then $x>0$.\n\\end{theorem}"
    zh = "\\begin{theorem}\n若 [[MATH_1]] 则 $x>0$。\n\\end{theorem}"
    rep = validate_pair(src, zh)
    assert rep.ok, str(rep)


def test_pure_placeholder_chunk() -> None:
    rep = validate_pair("[[ENV_4]]", "[[ENV_4]]")
    assert rep.ok, str(rep)


# ---------------------------------------------------------------- placeholder


def test_placeholder_missing() -> None:
    src = "见 [[MATH_1]] 与 [[CITE_2]]。"
    zh = "见 [[MATH_1]]。"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert Severity.ERROR in _sev(rep, "placeholder")
    assert any("CITE_2" in i.message for i in rep.issues)


def test_placeholder_extra() -> None:
    rep = validate_pair("见 [[MATH_1]]。", "见 [[MATH_1]] 和 [[MATH_9]]。")
    assert not rep.ok
    assert any("多余" in i.message for i in rep.issues)


def test_placeholder_typo_suggestion() -> None:
    src = "见 [[MATH_12]]。"
    zh = "见 [[MTH_12]]。"  # lev(核心)=1 → 修复建议
    rep = validate_pair(src, zh)
    assert not rep.ok
    typos = [i for i in rep.issues if i.expected == "[[MATH_12]]"]
    assert typos, str(rep)
    assert "拼错" in typos[0].message


def test_placeholder_fullwidth_variant_detected() -> None:
    src = "见 [[MATH_1]]。"
    zh = "见 【MATH_1】。"  # 全角变体：检出 + 核心相同给修复建议
    rep = validate_pair(src, zh)
    assert not rep.ok
    hits = [i for i in rep.issues if i.rule == "placeholder"]
    assert any("MATH_1" in i.message for i in hits)


def test_placeholder_reorder_is_warn_not_error() -> None:
    """E22 防误报用例：`of X`→`X 的` 合法中文换序只占 warn。"""
    src = "the loss [[MATH_1]] of model [[REF_2]] under [[CITE_3]]"
    zh = "模型 [[REF_2]] 的损失 [[MATH_1]] 在 [[CITE_3]] 下"
    rep = validate_pair(src, zh)
    assert rep.ok, str(rep)  # 多重集一致 → 无 error
    assert Severity.WARN in _sev(rep, "placeholder")


def test_placeholder_bibitem_offline_error() -> None:
    """E22 硬判据余量：BIBITEM 结构占位符脱行首 → error。"""
    src = "[[BIBITEM_1]] Vaswani et al., attention is all you need."
    zh = "Vaswani 等人提出注意力即一切 [[BIBITEM_1]]。"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("行首" in i.message for i in rep.issues)


def test_placeholder_bibitem_anchored_ok() -> None:
    src = "[[BIBITEM_1]] Vaswani et al."
    zh = "[[BIBITEM_1]] Vaswani 等人。"
    assert validate_pair(src, zh).ok


def test_placeholder_sl_marker() -> None:
    """[[SL]] 无数字后缀也按占位符契约计。"""
    src = "第一行[[SL]]第二行 [[MATH_1]]"
    zh = "第一行第二行 [[MATH_1]]"  # 丢了 [[SL]]
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("SL" in i.message for i in rep.issues)


# ---------------------------------------------------------------- brace


def test_brace_net_imbalance() -> None:
    src = "用 \\emph{method} 说明。"
    zh = "用 \\emph{method 说明。"  # 丢 }
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert Severity.ERROR in _sev(rep, "brace")


def test_brace_overdraw() -> None:
    src = "正常 {组} 文本。"
    zh = "正常 {组}} 文本。"  # 多 }
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("透支" in i.message for i in rep.issues)


def test_brace_inherited_imbalance_tolerated() -> None:
    """src 自带不平衡被 zh 原样继承 → 不追责。"""
    src = "公式 ${x$ 残文。"  # src 自带不平衡
    zh = "公式 ${x$ 残文（中文）。"
    rep = validate_pair(src, zh)
    assert Severity.ERROR not in _sev(rep, "brace")


def test_brace_count_diff_but_balanced_warn() -> None:
    """合法删 \\emph{...}：净额一致 → 设计性 warn，非 error。"""
    src = "the \\emph{key} idea"
    zh = "关键 idea"  # 掉 \\emph 组
    rep = validate_pair(src, zh)
    assert rep.ok, str(rep)
    assert Severity.WARN in _sev(rep, "brace")


def test_brace_escaped_and_comment_exempt() -> None:
    src = "100\\% 增长 % 注释里有 { 不平衡\n结束 \\{ok\\}"
    zh = "100\\% 增长 % 注释里有 { 不平衡\n结束 \\{ok\\}（中文）"
    rep = validate_pair(src, zh)
    assert Severity.ERROR not in _sev(rep, "brace")


# ---------------------------------------------------------------- env


def test_env_rename_end() -> None:
    src = "\\begin{equation}\nE=mc^2\n\\end{equation}"
    zh = "\\begin{equation}\nE=mc^2\n\\end{equationx}"  # \end 改名
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert Severity.ERROR in _sev(rep, "env")


def test_env_deleted_end() -> None:
    src = "\\begin{itemize}\n\\item a\n\\end{itemize}"
    zh = "\\begin{itemize}\n\\item a"
    rep = validate_pair(src, zh)
    assert not rep.ok


def test_env_new_in_zh() -> None:
    src = "普通段落。"
    zh = "\\begin{table}\nx\n\\end{table}\n普通段落。"  # 幻觉环境
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("新增环境" in i.message for i in rep.issues)


def test_env_inherited_mismatch_tolerated() -> None:
    src = "\\begin{a}x\\end{b}"  # src 自身不匹配
    zh = "\\begin{a}x（译）\\end{b}"
    rep = validate_pair(src, zh)
    assert Severity.ERROR not in _sev(rep, "env")


# ---------------------------------------------------------------- key


def test_key_dropped() -> None:
    src = "见 \\cite{a,b,c} 与 \\label{sec:x}。"
    zh = "见 \\cite{a,b} 与 \\label{sec:x}。"  # 漏 c
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("'c'" in i.message for i in rep.issues)


def test_key_hallucinated_warn_only() -> None:
    src = "见 \\cite{a}。"
    zh = "见 \\cite{a} 和 \\cite{bogus2024}。"
    rep = validate_pair(src, zh)
    assert rep.ok  # 新增 key 是 warn（幻觉引用）
    assert Severity.WARN in _sev(rep, "key")


def test_key_space_before_brace() -> None:
    src = "\\cite {vaswani2017} 提出。"
    zh = "\\cite {vaswani2017} 提出（译）。"
    rep = validate_pair(src, zh)
    assert Severity.ERROR not in _sev(rep, "key")


def test_key_optional_arg_exempt() -> None:
    src = "\\citep[see][ch.2]{vaswani2017} 所述。"
    zh = "\\citep{vaswani2017} 所述。"  # 丢可选参不追责（key 保留）
    rep = validate_pair(src, zh)
    assert Severity.ERROR not in _sev(rep, "key")


# ---------------------------------------------------------------- math


def test_math_dollar_dropped() -> None:
    src = "其中 $x>0$ 且 $y<1$。"
    zh = "其中 $x>0$ 且 y<1。"  # 丢一对 $
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert Severity.ERROR in _sev(rep, "math")


def test_math_display_unpaired() -> None:
    src = "公式 \\[ E=mc^2 \\] 如上。"
    zh = "公式 \\[ E=mc^2 如上。"  # 丢 \]
    rep = validate_pair(src, zh)
    assert not rep.ok


def test_math_odd_dollar_inherited_warn() -> None:
    src = "成本是 $5 美元。"  # src 奇数 $
    zh = "成本是 $5 美元（译）。"
    rep = validate_pair(src, zh)
    assert rep.ok
    assert Severity.WARN in _sev(rep, "math")


# ---------------------------------------------------------------- length


def test_length_ratio_cjk_compression_ok() -> None:
    """E21 防误报：0.25–0.30 区间的正常中文压缩不再告警。"""
    src = (
        "We present a comprehensive evaluation of the proposed approach "
        "on several benchmark datasets."
    )  # 94ch
    zh = "我们在多个基准数据集上综合评估了所提方法。"  # 22ch ≈ 0.23 → 应出 warn? 见下
    rep = validate_pair(src, zh)
    # 22/94 ≈ 0.234 < 0.25 → warn 允许存在；这里断言不误报 error
    assert rep.ok
    # 更典型：≥0.25 的压缩应无 length warn
    zh2 = "我们在多个基准数据集上对所提方法进行了综合评估与验证。"  # 27ch ≈ 0.287
    rep2 = validate_pair(src, zh2)
    assert not _sev(rep2, "length"), str(rep2)


def test_length_ratio_too_short() -> None:
    src = "x" * 100 + " 的长段落说明文字，包含足够的上下文内容。"
    zh = "短。"
    rep = validate_pair(src, zh)
    assert Severity.WARN in _sev(rep, "length")


def test_length_cjk_share_low() -> None:
    src = "the transformer architecture uses attention mechanisms."
    zh = "the transformer architecture uses attention mechanisms."  # 未翻译
    rep = validate_pair(src, zh)
    assert Severity.WARN in _sev(rep, "length")
    assert any("未翻译" in i.message for i in rep.issues)


# ---------------------------------------------------------------- macro


def test_macro_structural_hallucination() -> None:
    src = "普通文本一段。"
    zh = "普通文本一段。\\newcommand{\\foo}{bar}"
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("幻觉结构" in i.message for i in rep.issues)


def test_macro_new_nonstructural_warn() -> None:
    src = "普通文本一段，长度足够用于检查各种情况才行。"
    zh = "普通文本一段，长度足够用于检查各种情况才行。\\foo{bar}"
    rep = validate_pair(src, zh)
    assert rep.ok
    assert Severity.WARN in _sev(rep, "macro")


def test_macro_cs_dropped_fragile() -> None:
    """E22 升硬判据：`\\ ` 脆弱间距命令丢失 → error。"""
    src = "Bahdanau\\ et al.\\ \\cite{x} 提出。"
    zh = "Bahdanau et al. \\cite{x} 提出。"  # 丢两个 \
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("cs_dropped" in i.message or "脆弱间距" in i.message for i in rep.issues)


def test_macro_fused_cjk_cs_error() -> None:
    """E22 实测炸弹：`\\ `+中文熔成 `\\和` → error。"""
    src = "Vaswani\\ 等人提出。"
    zh = "Vaswani\\和 等人提出。"  # \ 后中文熔合成 \和
    rep = validate_pair(src, zh)
    assert not rep.ok
    assert any("和" in i.message for i in rep.issues)


def test_macro_tilde_dropped() -> None:
    src = "Figure~\\ref{fig:x} shows~it."
    zh = "图 \\ref{fig:x} 展示了它。"  # 丢两个 ~
    rep = validate_pair(src, zh)
    assert not rep.ok


def test_macro_emph_drop_warn_not_error() -> None:
    """合法改写掉非脆弱命令 → warn 不阻塞（B6 防误报面）。"""
    src = "the \\emph{key} contribution"
    zh = "核心贡献"
    rep = validate_pair(src, zh)
    assert rep.ok, str(rep)


# ---------------------------------------------------------------- 聚合/序列化


def test_report_serialization() -> None:
    rep = validate_pair("见 [[MATH_1]]。", "见。")
    d = rep.to_dict()
    assert d["ok"] is False
    assert isinstance(d["issues"], list)
    assert rep.feedback()


def test_report_by_rule() -> None:
    rep = validate_pair("\\cite{a,b} 见 [[M_1]]。", "\\cite{a} 见。")
    d = rep.by_rule()
    assert "key" in d
    assert "placeholder" in d


# ---------------------------------------------------------------- ph_in_cs


def test_ph_in_cs_fused_error() -> None:
    r"""``\fo[[CMD_1]]o`` 双侧夹持——splice 后断 cs，error 拦送。"""
    src = "Text \\footnote{note words} more."
    zh = "文本 \\fo[[CMD_1]]o 注记其余。"
    rep = validate_pair(src, zh)
    assert _sev(rep, "ph_in_cs") == [Severity.ERROR]
    assert not rep.ok


def test_ph_in_cs_tail_adjacent_legit() -> None:
    r"""``\protect[[REF_1]]``/``\em[[CMD_1]]`` 尾邻无字母是合法高频形。"""
    src = "See \\protect[[REF_1]] and \\em[[CMD_1]] words."
    zh = "见 \\protect[[REF_1]] 与 \\em[[CMD_1]] 词。"
    rep = validate_pair(src, zh)
    assert not _sev(rep, "ph_in_cs")


def test_ph_in_cs_comment_masked() -> None:
    r"""注释体内的签名是 splice 字面区——mask 后不计。"""
    src = "Text words here."
    zh = "文本词 % \\fo[[CMD_1]]o 注释内不算\n其余。"
    rep = validate_pair(src, zh)
    assert not _sev(rep, "ph_in_cs")


def test_ph_in_cs_net_diff_inherited_exempt() -> None:
    r"""src 自带同形（占位符贴命令名落位）→ Counter 净差豁免。"""
    src = "Head \\fo[[CMD_1]]o tail words."
    zh = "头 \\fo[[CMD_1]]o 尾词。"
    rep = validate_pair(src, zh)
    assert not _sev(rep, "ph_in_cs")


def test_ph_in_cs_control_symbol_not_hit() -> None:
    r"""``\\[[MATH_1]]`` 控制符号形——``[a-zA-Z@]+`` 必需字母排除。"""
    src = "Line \\\\[[MATH_1]] break."
    zh = "行 \\\\[[MATH_1]] 断。"
    rep = validate_pair(src, zh)
    assert not _sev(rep, "ph_in_cs")


def test_ph_in_cs_at_letter_and_count() -> None:
    r"""``@`` 计入 cs 字母集；多处命中聚合进单条 issue 的 ×N。"""
    src = "Text \\foo{x} and \\bar{y} end."
    zh = "文本 \\fo[[CMD_1]]o 甲 \\b[[CMD_2]]@r 乙。"
    rep = validate_pair(src, zh)
    assert _sev(rep, "ph_in_cs") == [Severity.ERROR]
    [issue] = [i for i in rep.issues if i.rule == "ph_in_cs"]
    assert "×2" in issue.message


# ---------------------------------------------------------------- bare_cs
# realpostfix2 0905.4907："alpha emitters"→``\alpha 发射体``，caption 两处
# 裸数学 cs → Missing $×4。mock 臂同族：itemOC/itemSPELL/linebreakGF 粘合名。


def test_bare_cs_math_in_text_error() -> None:
    r"""``\alpha`` 落文本域（src 无此 cs）→ error。"""
    src = "The flux of alpha emitters is large."
    zh = "\\alpha 发射体的通量很大。"
    rep = validate_pair(src, zh)
    assert _sev(rep, "bare_cs") == [Severity.ERROR]
    [issue] = [i for i in rep.issues if i.rule == "bare_cs"]
    assert "\\alpha" in issue.message


def test_bare_cs_math_multiple_aggregate() -> None:
    r"""同 chunk 两处 ``\alpha`` + 一处 ``\to`` 聚合 ×N 计数。"""
    src = "Alpha particles decay to lead over time."
    zh = "\\alpha 粒子经 \\to 衰变后 \\alpha 变铅。"
    rep = validate_pair(src, zh)
    assert _sev(rep, "bare_cs") == [Severity.ERROR]
    [issue] = [i for i in rep.issues if i.rule == "bare_cs"]
    assert "×3" in issue.message
    assert "\\to" in issue.message


def test_bare_cs_inside_zh_math_exempt() -> None:
    r"""``$\\alpha$``——zh 自包数学域是合法修正方向，裸 cs 不报
    （``$`` 计数差另由 math 规则承接）。"""
    src = "Alpha emitters decay."
    zh = "$\\alpha$ 发射体衰变。"
    rep = validate_pair(src, zh)
    assert not _sev(rep, "bare_cs")


def test_bare_cs_display_math_exempt() -> None:
    r"""``$$x$$`` display 定界——``$$`` 不切两对空单符区间。"""
    src = "Alpha emitters decay."
    zh = "$$\\alpha$$ 发射体衰变。"
    rep = validate_pair(src, zh)
    assert not _sev(rep, "bare_cs")


def test_bare_cs_inherited_src_same_count() -> None:
    r"""src 文本域自带裸 ``\\alpha``——zh 同计数继承豁免。"""
    src = "Text \\alpha emitters decay."
    zh = "文本 \\alpha 发射体衰变。"
    rep = validate_pair(src, zh)
    assert not _sev(rep, "bare_cs")


def test_bare_cs_net_delta_counts() -> None:
    r"""src ×1 zh ×2 → 净多 ×1 才炸（继承一枚豁免）。"""
    src = "Text \\alpha here."
    zh = "文本 \\alpha 甲 \\alpha 乙。"
    rep = validate_pair(src, zh)
    assert _sev(rep, "bare_cs") == [Severity.ERROR]


def test_bare_cs_comment_masked() -> None:
    r"""zh 注释里的 ``\\alpha`` 遮盖豁免。"""
    src = "Alpha emitters decay."
    zh = "% \\alpha 注记\n发射体衰变。"
    rep = validate_pair(src, zh)
    assert not _sev(rep, "bare_cs")


def test_bare_cs_fused_item_oc_error() -> None:
    r"""``\\itemOC``（itemOC/itemSPELL 族）：src ``\\item`` 前缀 + 大写尾
    粘合 → 未定义 cs 炸弹。"""
    src = "\\item First point words here enough."
    zh = "\\itemOC 第一条要点文字。"
    rep = validate_pair(src, zh)
    assert _sev(rep, "bare_cs") == [Severity.ERROR]
    [issue] = [i for i in rep.issues if i.rule == "bare_cs"]
    assert "item" in issue.message
    assert "OC" in issue.message


def test_bare_cs_fused_linebreak_gf() -> None:
    r"""``\\linebreakGF``：前缀 ``\\linebreak`` + ``GF`` → error。"""
    src = "Line \\linebreak break here."
    zh = "行 \\linebreakGF 断处。"
    rep = validate_pair(src, zh)
    assert _sev(rep, "bare_cs") == [Severity.ERROR]


def test_bare_cs_fused_csname_bibitem() -> None:
    r"""``\\csnamebibitemNoStop``：前缀 ``\\csname`` + 驼峰尾 → error。"""
    src = "See \\csname x\\endcsname here."
    zh = "见 \\csnamebibitemNoStop 处。"
    rep = validate_pair(src, zh)
    assert _sev(rep, "bare_cs") == [Severity.ERROR]


def test_bare_cs_lowercase_suffix_legit() -> None:
    r"""保守面：``\\cite``→``\\citep`` 全小写尾是真实 cs——不炸
    （新增名仍走 macro warn，本规则不重复报）。"""
    src = "See \\cite{a} here."
    zh = "见 \\citep{a} 处。"
    rep = validate_pair(src, zh)
    assert not _sev(rep, "bare_cs")


def test_bare_cs_refname_legit() -> None:
    r"""``\\ref``→``\\refname``：全小写真实 cs 延申不报。"""
    src = "See \\ref{a} here."
    zh = "见 \\refname 处。"
    rep = validate_pair(src, zh)
    assert not _sev(rep, "bare_cs")


def test_bare_cs_textbf_not_fusion() -> None:
    r"""``\\text``→``\\textbf``：全小写尾不判粘合。"""
    src = "A \\text{x} here."
    zh = "一 \\textbf{x} 处。"
    rep = validate_pair(src, zh)
    assert not _sev(rep, "bare_cs")


def test_bare_cs_text_mode_cs_no_flag() -> None:
    r"""文本族新 cs（``\\LaTeX``/``\\url`` 类）不属数学表也不含大写尾——
    本规则静默，归 macro warn 承担。"""
    src = "The project site is online."
    zh = "该项目 \\LaTeX 站已上线。"
    rep = validate_pair(src, zh)
    assert not _sev(rep, "bare_cs")


# ---------------------------------------------------------------- 审计修复面


def test_fuzzy_ph_fullwidth_cjk_bracket_not_flagged() -> None:
    r"""``【图1】``/``【1】`` 是中文正文自然全角括号用法——非占位符变体，
    不得报多余占位符（validbench 正文 FP 修复）。"""
    src = "Results in [Fig 1] and [2] show [[MATH_1]]."
    zh = "结果见【图1】和【2】，显示 [[MATH_1]]。"
    rep = validate_pair(src, zh)
    assert not _sev(rep, "placeholder"), str(rep)


def test_fuzzy_ph_fullwidth_variant_pairs() -> None:
    r"""``【MATH_1】`` 全角括号变体仍是占位符拼错——lev 配对给修复建议。"""
    rep = validate_pair("见 [[MATH_1]] 式。", "见【MATH_1】式。")
    sev = _sev(rep, "placeholder")
    assert sev == [Severity.ERROR]
    iss = next(i for i in rep.issues if i.rule == "placeholder")
    assert iss.expected == "[[MATH_1]]"
    assert iss.found == "【MATH_1】"


def test_fuzzy_ph_lowercase_variant_pairs() -> None:
    r"""``[[math_1]]`` 小写变体——大小写折叠 lev=0 配对成拼错而非缺失+多余双报。"""
    rep = validate_pair("见 [[MATH_1]] 式。", "见 [[math_1]] 式。")
    iss = [i for i in rep.issues if i.rule == "placeholder"]
    assert len(iss) == 1
    assert "拼错" in iss[0].message
    assert iss[0].expected == "[[MATH_1]]"
    assert iss[0].found == "[[math_1]]"


def test_key_cite_suffix_family() -> None:
    r"""``*cite`` 后缀族（biblatex ``\\parencite``/``\\footcite``/``\\textcite``）
    key 丢失同样 error——只认 ``\\cite*`` 前缀会漏掉整族。"""
    src = "见 \\parencite{vaswani2017} 与 \\footcite{kingma2015}。"
    zh = "见文中引用。"
    rep = validate_pair(src, zh)
    iss = [i for i in rep.issues if i.rule == "key" and i.severity is Severity.ERROR]
    assert {i.expected for i in iss} == {"vaswani2017", "kingma2015"}


def test_key_refrange_two_args() -> None:
    r"""``\\crefrange{a}{b}`` 第二个 key 参数也点算。"""
    rep = validate_pair(
        "见 \\crefrange{sec:a}{sec:b}。", "见 \\crefrange{sec:a}{sec:b}。"
    )
    assert rep.ok, str(rep)
    rep2 = validate_pair("见 \\crefrange{sec:a}{sec:b}。", "见 \\crefrange{sec:a}。")
    iss = [i for i in rep2.issues if i.rule == "key" and i.severity is Severity.ERROR]
    assert {i.expected for i in iss} == {"sec:b"}


def test_key_addbibresource() -> None:
    r"""biblatex ``\\addbibresource{x.bib}`` 是 key 承载命令。"""
    rep = validate_pair("\\addbibresource{refs.bib} 文本。", "文本。")
    iss = [i for i in rep.issues if i.rule == "key" and i.severity is Severity.ERROR]
    assert {i.expected for i in iss} == {"refs.bib"}


def test_item_glue_legit_item_cs_no_flag() -> None:
    r"""``\\itemsep``/``\\itemize``/``\\itemindent`` 全小写延申是真实 cs——
    与 ``bare_cs_net`` 同口径豁免，不误报"编译炸弹"。"""
    src = "\\item a\n\\item b"
    zh = "\\item 甲\n\\itemsep 2pt\n\\item 乙"
    rep = validate_pair(src, zh)
    assert not _sev(rep, "item_glue"), str(rep)


def test_item_glue_uppercase_suffix_flagged() -> None:
    r"""``\\itemFSU`` 大写尾粘合仍是编译炸弹签名。"""
    rep = validate_pair("\\item First", "\\itemFSU 第一")
    assert _sev(rep, "item_glue") == [Severity.WARN]


def test_fragile_space_newline_equiv() -> None:
    r"""``\\ ``↔``\\<newline>`` 是 TeX 等价控制空格——互换不报 cs_dropped。"""
    src = "Bahdanau\\ et al.\\ propose."
    zh = "Bahdanau\\\net al.\\ 提出。"
    rep = validate_pair(src, zh)
    assert not [
        i for i in rep.issues if i.rule == "macro" and i.severity is Severity.ERROR
    ], str(rep)


def test_fragile_space_dropped_still_flagged() -> None:
    r"""``\\ `` 真正丢失（非换成等价形）仍报 cs_dropped error。"""
    rep = validate_pair("Bahdanau\\ et al.", "Bahdanau et al.")
    iss = [i for i in rep.issues if i.rule == "macro" and i.severity is Severity.ERROR]
    assert any("脆弱间距" in i.message for i in iss)


def test_env_end_warn_cap_after_filter() -> None:
    r"""end 名偏多 warn：先过滤（begin 净增覆盖的不报）再截断——
    被过滤条目不消耗 50 条上限。"""
    pairs = "".join(f"\\begin{{f{i}}}\\end{{f{i}}}" for i in range(50))
    orphans = "".join(f"\\end{{g{i}}}" for i in range(10))
    rep = validate_pair("x", pairs + orphans)
    warns = [i for i in rep.issues if i.rule == "env" and i.severity is Severity.WARN]
    assert len(warns) == 10  # noqa: PLR2004 - 50 个被 begin 覆盖的 f* 不吞额度，g* 全报
