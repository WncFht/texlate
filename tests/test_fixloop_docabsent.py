"""docabsent 车道双臂单测 —— doc 引用但 e-print 未带的 .tex 片段末位兜底。

实证背景 (m1kcensus2 衍生, covgap-C #205 候选逐格复核):

A) ``doc_absent_stub`` builtin (order 12.95 —— install/vendored/shim/
   relocate 全真件臂均 decline 后的末位兜底):
   - 版本缀漂移 sibling 唯一命中搬真件 (2210.03294: doc 活引用
     ``4Num_Example/12step_dynamics_new.tex``, e-print 只带同目录
     ``12step_dynamics.tex`` 改名件) —— 真内容优于 stub;
   - 无 sibling → ``_resolve_site`` 空 stub 占位, 丢该 ``\\input`` 段
     保其余, 优于整格 unfixable。
   闸: 非 .tex 扩展名让位 (.cls/.sty 走 install/shim 域); 瞬态件拒
   (.aux/.bbl 缺位 = 上游病灶信号 —— 2609.20323 main.aux 裁决沿);
   fileset 内有同名件 → relocate 域; 外来同名件指纹闸不覆写。

B) ``fileset_relocate`` 批量树镜像: payload 顶层目录在 wdir 根成树
   (``Content/a.tex`` 逐轮一件缺档烧轮次 —— 2609.20640 单件/轮 ×8
   实证), 首个 payload 归位后整树镜像 ``wdir/<top>/`` →
   ``<main_dir>/<top>/``; 瞬态件/dot 段/已存在目标/已处镜像树内
   源件全跳过 (防 ``top/top/top`` 递归)。
"""

from pathlib import Path

from _fixloopkit import EngStub, mk_ctx, rs, rule

from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx

_RULE_STUB = "doc_absent_stub"
_RULE_RELOC = "fileset_relocate"


def _stub(ctx: LoopCtx, payload: str | None) -> tuple[bool, str]:
    """``doc_absent_stub`` 直驱 —— 经 ruleset 实载 params (同 ``_stub_wired``)。

    旧版 ``{}`` 空参: builtin 退回 ``exts=('.tex',)`` 内兜, yaml 接线的
    7-扩展名表被旁路 —— 委托 ``_stub_wired`` 保真。"""
    return _stub_wired(ctx, payload)


def _reloc(ctx: LoopCtx, payload: str | None) -> tuple[bool, str]:
    return TRANSFORM_FNS[_RULE_RELOC](ctx, EngStub(), payload, {})


def _mkfile(p: Path, body: str = "x\n") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# ════════════════════════════ A: doc_absent_stub 序位 + 闸 ════


def test_rule_stub_order_after_real_content_arms() -> None:
    """序自洽: relocate(9) < install(10) < vendored(11.5) < shim(12.9) < stub —
    .tex payload 可以是真 CTAN 件 (pst-tools.tex 实证), stub 必须末位。"""
    orders = {r.id: r.order for r in rs().phase("loop")}
    assert orders["fileset_relocate"] < orders["install_file"]
    assert orders["install_file"] < orders["vendored_fetch"]
    assert orders["vendored_fetch"] < orders["legacy_pkg_shim_c3"]
    assert orders["legacy_pkg_shim_c3"] < orders[_RULE_STUB]


def test_stub_rename_rescue_strips_new_suffix(tmp_path: Path) -> None:
    """payload ``sub/x_new.tex`` 缺席 + 同目录 ``x.tex`` → 搬真件 (2210.03294 形)。"""
    _mkfile(tmp_path / "sub" / "main.tex")
    real = _mkfile(tmp_path / "sub" / "x.tex", "\\section{Real}\\label{s:x}\n")
    ctx = mk_ctx(tmp_path, "sub/main.tex")
    ok, note = _stub(ctx, "sub/x_new.tex")
    assert ok, note
    assert "rename-rescue" in note
    dst = tmp_path / "sub" / "sub" / "x_new.tex"  # 解析位 = main_dir/<payload>
    assert dst.read_text() == real.read_text()


def test_stub_rename_rescue_adds_suffix(tmp_path: Path) -> None:
    """反向漂移: payload ``x.tex`` 缺席 + 同目录 ``x_new.tex`` → 搬真件。"""
    _mkfile(tmp_path / "main.tex")
    real = _mkfile(tmp_path / "x_new.tex", "real content\n")
    ctx = mk_ctx(tmp_path)
    ok, note = _stub(ctx, "x.tex")
    assert ok, note
    assert "rename-rescue" in note
    assert (tmp_path / "x.tex").read_text() == real.read_text()


def test_stub_ambiguous_siblings_fall_to_empty(tmp_path: Path) -> None:
    """多异名版本缀命中 = 版本族并存 → 不择一猜, 空 stub 兜底。"""
    _mkfile(tmp_path / "main.tex")
    _mkfile(tmp_path / "x_new.tex")
    _mkfile(tmp_path / "x_old.tex")
    ctx = mk_ctx(tmp_path)
    ok, note = _stub(ctx, "x.tex")
    assert ok, note
    assert "doc-absent stub" in note
    t = (tmp_path / "x.tex").read_text()
    assert "texlate-fixloop-injected" in t


def test_stub_empty_fallback_writes_resolve_site(tmp_path: Path) -> None:
    """无 sibling → 空 stub 落 ``main_dir/<payload>`` 解析位 (嵌套 main 形)。"""
    _mkfile(tmp_path / "4Num_Example" / "main.tex")
    ctx = mk_ctx(tmp_path, "4Num_Example/main.tex")
    ok, note = _stub(ctx, "4Num_Example/12step_dynamics_new.tex")
    assert ok, note
    dst = tmp_path / "4Num_Example" / "4Num_Example" / "12step_dynamics_new.tex"
    assert "doc-absent stub" in dst.read_text()


def test_stub_ext_gate_declines_cls_sty(tmp_path: Path) -> None:
    """非 .tex 让位 —— .cls/.sty 走 install/shim 域, 不该轮到本臂。"""
    _mkfile(tmp_path / "main.tex")
    ctx = mk_ctx(tmp_path)
    ok, _ = _stub(ctx, "foo.cls")
    assert not ok
    ok, _ = _stub(ctx, "bar.sty")
    assert not ok


def test_stub_transient_gate_declines(tmp_path: Path) -> None:
    """.aux/.bbl 缺位 = 上游病灶信号 (2609.20323 main.aux) —— stub 遮蔽真因。"""
    _mkfile(tmp_path / "main.tex")
    ctx = mk_ctx(tmp_path)
    ok, note = _stub(ctx, "main.aux")
    assert not ok
    assert "transient" in note


def test_stub_fileset_presence_declines(tmp_path: Path) -> None:
    """fileset 内有同名件 → relocate 域 (防御性复核, dispatch 序漂移安全)。"""
    _mkfile(tmp_path / "main.tex")
    _mkfile(tmp_path / "elsewhere" / "deep" / "frag.tex")
    ctx = mk_ctx(tmp_path)
    ok, note = _stub(ctx, "frag.tex")
    assert not ok
    assert "relocate" in note


def test_stub_foreign_at_site_not_overwritten(tmp_path: Path) -> None:
    """解析位已有外来件 → 指纹闸拒覆写, decline 交后续规则。"""
    _mkfile(tmp_path / "main.tex")
    site = _mkfile(tmp_path / "frag.tex", "author's own file\n")
    ctx = mk_ctx(tmp_path)
    ok, _note = _stub(ctx, "frag.tex")
    assert not ok
    assert site.read_text() == "author's own file\n"


def test_stub_unsafe_names_decline(tmp_path: Path) -> None:
    """绝对径/.. 逃逸/空 payload → decline。"""
    _mkfile(tmp_path / "main.tex")
    ctx = mk_ctx(tmp_path)
    for bad in (None, "", "/etc/x.tex", "../x.tex", "a/../../x.tex"):
        ok, _ = _stub(ctx, bad)
        assert not ok, bad


def test_stub_rescue_unique_among_noise(tmp_path: Path) -> None:
    """同目录噪声文件不扰: 唯一版本缀命中仍搬 (stem 集合精确匹配)。"""
    _mkfile(tmp_path / "sub" / "main.tex")
    _mkfile(tmp_path / "sub" / "12step_dynamics.tex", "real\n")
    _mkfile(tmp_path / "sub" / "other.tex")
    _mkfile(tmp_path / "sub" / "12step_dynamics_new.sty")  # 异扩展名不算
    ctx = mk_ctx(tmp_path, "sub/main.tex")
    ok, note = _stub(ctx, "sub/12step_dynamics_new.tex")
    assert ok, note
    assert "rename-rescue" in note
    dst = tmp_path / "sub" / "sub" / "12step_dynamics_new.tex"
    assert dst.read_text() == "real\n"


# ════════════════════════════ B: fileset_relocate 批量树镜像 ════


def test_relocate_batch_mirrors_top_tree(tmp_path: Path) -> None:
    """payload 顶层成树 → 首件归位 + 整树镜像 (2609.20640 Content/ 形)。"""
    _mkfile(tmp_path / "IEEEtran" / "main.tex")
    _mkfile(tmp_path / "Content" / "a.tex")
    _mkfile(tmp_path / "Content" / "b.tex")
    _mkfile(tmp_path / "Content" / "sub" / "c.tex")
    ctx = mk_ctx(tmp_path, "IEEEtran/main.tex")
    ok, note = _reloc(ctx, "Content/a.tex")
    assert ok, note
    assert "+2 tree files" in note
    assert (tmp_path / "IEEEtran" / "Content" / "a.tex").is_file()
    assert (tmp_path / "IEEEtran" / "Content" / "b.tex").is_file()
    assert (tmp_path / "IEEEtran" / "Content" / "sub" / "c.tex").is_file()


def test_relocate_batch_skips_transient_and_dot(tmp_path: Path) -> None:
    """镜像树内瞬态件/dot 段不搬。"""
    _mkfile(tmp_path / "sub" / "main.tex")
    _mkfile(tmp_path / "Content" / "a.tex")
    _mkfile(tmp_path / "Content" / "main.aux")  # 瞬态
    _mkfile(tmp_path / "Content" / ".hidden" / "x.tex")  # dot 段
    ctx = mk_ctx(tmp_path, "sub/main.tex")
    ok, note = _reloc(ctx, "Content/a.tex")
    assert ok, note
    assert "tree files" not in note  # 只剩瞬态+dot, 零镜像
    assert not (tmp_path / "sub" / "Content" / "main.aux").exists()
    assert not (tmp_path / "sub" / "Content" / ".hidden").exists()


def test_relocate_batch_no_recursive_nesting(tmp_path: Path) -> None:
    """再触发不递归: 镜像树内源件跳过 —— 无 ``top/top/top`` 逐轮嵌套。"""
    _mkfile(tmp_path / "4Num" / "main.tex")
    _mkfile(tmp_path / "4Num" / "a.tex")
    _mkfile(tmp_path / "4Num" / "b.tex")
    ctx = mk_ctx(tmp_path, "4Num/main.tex")
    ok, _ = _reloc(ctx, "4Num/a.tex")
    assert ok
    assert (tmp_path / "4Num" / "4Num" / "b.tex").is_file()  # 首轮已镜像
    # 第二轮 payload 变体 —— src 在镜像树内命中须跳过, 不得再生一层
    ok2, _ = _reloc(ctx, "4Num/c.tex")
    assert not ok2  # c.tex 全树缺席 → decline (doc_absent_stub 域)
    assert not (tmp_path / "4Num" / "4Num" / "4Num").exists()


def test_relocate_batch_flat_payload_noop(tmp_path: Path) -> None:
    """裸件名 payload (无顶层目录) 不触发镜像。"""
    _mkfile(tmp_path / "sub" / "main.tex")
    _mkfile(tmp_path / "frag.tex")
    ctx = mk_ctx(tmp_path, "sub/main.tex")
    ok, note = _reloc(ctx, "frag.tex")
    assert ok, note
    assert "tree files" not in note


def test_relocate_single_still_works_no_top_dir(tmp_path: Path) -> None:
    """顶层目录缺席时单件归位行为不变 (basename rglob 臂)。"""
    _mkfile(tmp_path / "sub" / "main.tex")
    _mkfile(tmp_path / "elsewhere" / "frag.tex")
    ctx = mk_ctx(tmp_path, "sub/main.tex")
    ok, note = _reloc(ctx, "frag.tex")
    assert ok, note
    assert (tmp_path / "sub" / "frag.tex").is_file()
    assert "tree files" not in note


# ════════════ 2026-09-20 taxon2/pdfex+gapmine: exts 表扩位 ════
# \input{X.pdf_tex} 双缺席形 (无 pdf_tex 且无 pdf/eps sibling ——
# 2508.03897/2606.18450/2508.04813/2503.10148 普查 4 格) 与 doc-absent
# .tikzstyles (2606.19622) 同归空 stub 诚实降级; exts 表外名仍让位。
# 同日 eraimpl 批 (failmine7 普查, eracls2 车道 candidates)
# 再扩 .pgf (2506.05065 figures/legendre.pgf 子目录位) / .tikz
# (2603.07778 vanilla.tikz) / .latex (chao-dyn/9412002 scheme2.latex)
# / .cfg (2604.03663 econsocart.cls :67 \input{econsocart.cfg} 伴生缺档)。


def _stub_wired(ctx: LoopCtx, payload: str | None) -> tuple[bool, str]:
    """经 ruleset 实载 ``rule.action.params`` 直驱 —— 钉 yaml→builtin 接线。"""
    r = rule(_RULE_STUB)
    return TRANSFORM_FNS[_RULE_STUB](
        ctx, EngStub(), payload, r.action.get("params") or {}
    )


def test_stub_exts_param_table() -> None:
    """params.exts 钉死表内容 —— 回退 yaml 即红。"""
    params = rule(_RULE_STUB).action.get("params") or {}
    assert set(params.get("exts") or ()) == {
        ".tex",
        ".pdf_tex",
        ".tikzstyles",
        ".pgf",
        ".tikz",
        ".latex",
        ".cfg",
    }


def test_stub_pdf_tex_writes_empty_stub(tmp_path: Path) -> None:
    """``\\input{figure2a.pdf_tex}`` 双缺席 → 空 stub 落解析位。"""
    _mkfile(tmp_path / "main.tex")
    ctx = mk_ctx(tmp_path)
    ok, note = _stub_wired(ctx, "figure2a.pdf_tex")
    assert ok, note
    assert "doc-absent stub" in (tmp_path / "figure2a.pdf_tex").read_text()


def test_stub_tikzstyles_writes_empty_stub(tmp_path: Path) -> None:
    _mkfile(tmp_path / "main.tex")
    ctx = mk_ctx(tmp_path)
    ok, note = _stub_wired(ctx, "my.tikzstyles")
    assert ok, note
    assert "doc-absent stub" in (tmp_path / "my.tikzstyles").read_text()


def test_stub_ext_gate_still_declines_unlisted(tmp_path: Path) -> None:
    """表外扩展名经真 params 仍让位 (.cls/.sty/.def → install/shim 域)。"""
    _mkfile(tmp_path / "main.tex")
    ctx = mk_ctx(tmp_path)
    ok, _ = _stub_wired(ctx, "foo.cls")
    assert not ok
    ok, _ = _stub_wired(ctx, "bar.def")
    assert not ok
