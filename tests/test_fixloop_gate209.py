r"""gatenarrow 钉 —— latex209_reject gate v4 收窄 (eracls2 普查 2026-09-20)。

v3 ``when.any[1] = {category: missing_file, main_head_contains: \documentstyle}``
在升级稿上纯 FP: 注释态 ``%\documentstyle`` 残留命中 mhc raw 子串, COMPAT_SHIM
面包屑满足 condition 第二选 → missing_file 载荷被 gate 吞掉, shim/install/
doc_absent 臂全部够不到 (aas2pp4.sty/flushrt.sty/laa.cls ~5 格实证)。
``latex209_upgrade`` precheck 已把活 ``\documentstyle`` 稿转化或内携 REJECT,
gate 的 missing_file 支无真可达群体 → 整支删除, 只留 latex209 类错误籍。
"""

from pathlib import Path

from test_fixloop_loop import CLEAN_LOG, MockEngine, make_proj

from texlate.compile.fixloop import fixloop

#: 升级稿形态: 注释态 \documentstyle 残留 (mhc raw 子串命中) + COMPAT_SHIM
#: 面包屑 (condition 第二选命中) —— 源码不引用 aas2pp4, 让缺件只由 log 报,
#: static_precheck 扫不到 → 放行后由 loop install 臂实证可达。
POST_UPGRADE_TEX = (
    "%\\documentstyle[aaspp4]{article}\n"
    "\\documentclass{article}\n"
    "% texlate: LaTeX 2.09 compatibility shim\n"
    "\\begin{document}\nhi\n\\end{document}\n"
)
MISSING_AAS2PP4_LOG = (
    "! LaTeX Error: File `aas2pp4.sty' not found.\nl.3 \\usepackage{aas2pp4}\n"
)

L209_TEX = "\\documentstyle{article}\n\\begin{document}\nhi\n\\end{document}\n"
L209_LOG = "! LaTeX2e command \\usepackage in LaTeX 2.09 document.\n"


def test_missing_file_payload_passes_gate(tmp_path: Path) -> None:
    """升级稿 missing_file 载荷不再被 gate 吞 —— install 臂可达, 装上即 clean。"""
    eng = MockEngine(
        [{"log": MISSING_AAS2PP4_LOG}, {"log": CLEAN_LOG, "pdf": True}],
        installable={"aas2pp4.sty"},
    )
    cell = fixloop(make_proj(tmp_path, POST_UPGRADE_TEX), eng)
    assert cell["gate_fired"] == []
    assert "aas2pp4.sty" in eng.install_calls
    assert cell["verdict"] == "clean"


def test_true_209_doc_still_gate_rejected(tmp_path: Path) -> None:
    """活 ``\\documentstyle`` 稿仍拒 —— upgrade 转化后面包屑续保 condition。"""
    eng = MockEngine([{"log": L209_LOG}])
    cell = fixloop(make_proj(tmp_path, L209_TEX), eng)
    assert cell["verdict"] == "reject:latex209_reject"
    assert cell["gate_fired"] == ["latex209_reject"]
    assert cell["reject_route"] == "latex+dvips"


def test_post_upgrade_209_residue_still_rejected(tmp_path: Path) -> None:
    """升级稿冒 compat-mode 残错 (latex209 类) 仍拒 —— v3 面包屑籍判语义保全。"""
    eng = MockEngine([{"log": L209_LOG}])
    cell = fixloop(make_proj(tmp_path, POST_UPGRADE_TEX), eng)
    assert cell["verdict"] == "reject:latex209_reject"
    assert cell["gate_fired"] == ["latex209_reject"]
