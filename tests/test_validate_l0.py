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
