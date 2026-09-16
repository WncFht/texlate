"""latex209.py 受限升级器 + inject 挂点的单测。"""

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from texlate.compile import latex209
from texlate.compile.inject import (
    CTEX_LINE,
    InjectRejectError,
    inject_cjk,
    prepare_chinese,
)
from texlate.compile.latex209 import (
    COMPAT_SHIM,
    _target_resolvable,
    upgrade_209,
)


@pytest.fixture(autouse=True)
def _target_always_resolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    """改名目标类默认放行——升级器结果不依赖测试机 texmf 内容。

    守卫本身的用例在本文件内对 ``_target_resolvable`` 或其缝另行打桩。
    """
    monkeypatch.setattr(latex209, "_target_resolvable", lambda *_a: True)


def test_upgrade_simple_article() -> None:
    tex = "\\documentstyle{article}\n\\begin{document}\nx\\end{document}\n"
    out, info = upgrade_209(tex)
    assert info["status"] == "converted"
    assert "\\documentclass{article}" in out
    assert "\\documentstyle" not in out
    assert COMPAT_SHIM in out
    assert "latexsym" in out


def test_upgrade_option_routing() -> None:
    """内核选项留类选项；宏包名进 usepackage；未识别默认落类选项。"""
    tex = "\\documentstyle[12pt,epsfig,mystropt]{article}\nx\n"
    out, info = upgrade_209(tex)
    assert "\\documentclass[12pt,mystropt]{article}" in out
    assert "\\usepackage{epsfig}" in out
    assert info["class_opts"] == ["12pt", "mystropt"]
    assert info["pkg_opts"] == ["epsfig"]


def test_upgrade_shim_before_usepackage() -> None:
    r"""COMPAT_SHIM 必须先于路由出的 \usepackage——209 .sty 加载期就要见到
    \footheight 等定义（2501.05407 nips.sty 实证）。"""
    tex = "\\documentstyle[epsfig]{article}\nx\n"
    out, _ = upgrade_209(tex)
    assert out.index("\\newlength{\\footheight}") < out.index("\\usepackage{epsfig}")


def test_upgrade_commented_documentstyle_ignored() -> None:
    r"""注释掉的 ``\documentstyle`` 不得命中（掩码视图定位）。"""
    tex = (
        "% \\documentstyle[12pt]{IEEEtran}\n"
        "\\documentstyle{article}\n\\begin{document}\nx\\end{document}\n"
    )
    out, info = upgrade_209(tex)
    assert info["status"] == "converted"
    assert out.startswith("% \\documentstyle[12pt]{IEEEtran}\n")
    assert "\\documentclass{article}" in out
    assert "\\documentstyle[12pt]{IEEEtran}" in out  # 注释行原样保留


def test_upgrade_revtex_map_and_rename() -> None:
    """revtex→revtex4-2 + 选项改名（tighten→tightenlines, floats→floatfix）。"""
    tex = "\\documentstyle[aps,prl,preprint,tighten,floats,epsfig]{revtex}\nx\n"
    out, info = upgrade_209(tex)
    assert "\\documentclass[aps,prl,preprint,tightenlines,floatfix]{revtex4-2}" in out
    assert "\\usepackage{epsfig}" in out
    assert info["target"] == "revtex4-2"
    assert info["pkg_opts"] == ["epsfig"]


def test_upgrade_comment_interleaved_options() -> None:
    """选项段内穿插注释（revtex 五选一形态）——掩码剔除注释选项。"""
    tex = "\\documentstyle[aps,%\n %jmp,%\n prl]{revtex}\nx\n"
    out, _info = upgrade_209(tex)
    assert "\\documentclass[aps,prl]{revtex4-2}" in out


def test_upgrade_showkeys_class_vs_pkg() -> None:
    """同名冲突：showkeys 是 revtex4-2 类内建（留类选项），article 下是宏包。"""
    out_r, _ = upgrade_209("\\documentstyle[showkeys]{revtex}\nx\n")
    assert "\\documentclass[showkeys]{revtex4-2}" in out_r
    assert "usepackage{showkeys}" not in out_r
    out_a, _ = upgrade_209("\\documentstyle[showkeys]{article}\nx\n")
    assert "\\usepackage{showkeys}" in out_a
    assert "\\documentclass{article}" in out_a


def test_upgrade_class_map() -> None:
    """映射类改名；未映射类名原样保留（缺 .cls 交 fixloop CTAN fetch）。"""
    for src, tgt in [("mn", "mnras"), ("jpsj", "jpsj3"), ("elsart", "elsarticle")]:
        out, info = upgrade_209(f"\\documentstyle{{{src}}}\nx\n")
        assert f"\\documentclass{{{tgt}}}" in out
        assert info["target"] == tgt
    out, _ = upgrade_209("\\documentstyle{amsart}\nx\n")
    assert "\\documentclass{amsart}" in out
    out, _ = upgrade_209("\\documentstyle{ptptex}\nx\n")
    assert "\\documentclass{ptptex}" in out


def test_upgrade_ds_at_static_reject() -> None:
    """实证 ds@ 选项机类按名硬拒（无树可调）。"""
    for cls in ("ias", "jaa", "julie"):
        out, info = upgrade_209(f"\\documentstyle[pramana]{{{cls}}}\nx\n")
        assert out == f"\\documentstyle[pramana]{{{cls}}}\nx\n"
        assert info["status"] == "reject"
        assert info["reason"] == "latex209_ds_at"


def test_upgrade_ds_at_dynamic(tmp_path: Path) -> None:
    r"""随源 ``<cls>.sty`` 内检出 ds@ 选项分发定义 → 拒。"""
    (tmp_path / "myj.sty").write_text("\\@namedef{ds@opta}{\\relax}\n")
    out, info = upgrade_209("\\documentstyle[opta]{myj}\nx\n", root=tmp_path)
    assert out == "\\documentstyle[opta]{myj}\nx\n"
    assert info["status"] == "reject"
    assert info["reason"] == "latex209_ds_at"


def test_upgrade_dynamic_check_skips_mapped_and_std(tmp_path: Path) -> None:
    """映射类/标准类不吃随源 ds@ 探测——shipped revtex.sty 不改变 revtex4-2 映射。"""
    (tmp_path / "revtex.sty").write_text("\\def\\ds@prl{\\relax}\n")
    out, info = upgrade_209("\\documentstyle{revtex}\nx\n", root=tmp_path)
    assert info["status"] == "converted"
    assert "\\documentclass{revtex4-2}" in out
    out, info = upgrade_209("\\documentstyle{article}\nx\n", root=tmp_path)
    assert info["status"] == "converted"


def test_upgrade_shipped_sty_routes_to_usepackage(tmp_path: Path) -> None:
    r"""随源样式选项（nips/jkas 型）→ ``\usepackage``——静默落类选项等于不加载。"""
    (tmp_path / "nips.sty").write_text("\\newcommand{\\nipshead}{x}\n")
    out, info = upgrade_209("\\documentstyle[nips]{article}\nx\n", root=tmp_path)
    assert "\\usepackage{nips}" in out
    assert info["shipped"] == ["nips"]


def test_upgrade_shipped_sty_loses_to_class_opt(tmp_path: Path) -> None:
    """随源文件不抢类内建选项（判别序：类表先于随源探测）。"""
    (tmp_path / "preprint.sty").write_text("% local preprint hacks\n")
    out, _ = upgrade_209("\\documentstyle[preprint]{revtex}\nx\n", root=tmp_path)
    assert "\\documentclass[preprint]{revtex4-2}" in out
    assert "usepackage{preprint}" not in out


def test_upgrade_revtex_strips_incompat_pkgs() -> None:
    r"""revtex4-2 ``\incompatible@package`` 名单（cite/mcite/multicol）从
    ``\usepackage`` 剥除——loaded 即 ``\ClassError``+``\stop``（cls:6453-55）。"""
    tex = "\\documentstyle[prb,aps,epsfig,multicol,cite,mcite]{revtex}\nx\n"
    out, info = upgrade_209(tex)
    assert "\\documentclass[prb,aps]{revtex4-2}" in out
    assert info["stripped"] == ["multicol", "cite", "mcite"]
    assert info["pkg_opts"] == ["epsfig"]
    assert "\\usepackage{epsfig}" in out
    assert "\\usepackage{multicol" not in out
    assert "\\usepackage{cite" not in out


def test_upgrade_revtex_multicol_passthrough_shim() -> None:
    r"""剥 multicol 后附 ``multicols`` 透传环境——209 revtex 文稿常用
    ``\begin{multicols}{2}`` 裹正文（cond-mat/9901156、9901347 实证）。"""
    tex = (
        "\\documentstyle[aps,multicol]{revtex}\n"
        "\\begin{document}\n\\begin{multicols}{2}\nx\n\\end{multicols}\n"
        "\\end{document}\n"
    )
    out, info = upgrade_209(tex)
    assert info["stripped"] == ["multicol"]
    assert "\\newenvironment{multicols}" in out
    assert "\\newcount\\col@number" in out
    assert "\\begin{multicols}{2}" in out  # 正文原样保留


def test_upgrade_multicol_kept_on_other_class() -> None:
    """非 revtex4-2 目标不剥 multicol——标准类下它是合法 ``\\usepackage``。"""
    out, info = upgrade_209("\\documentstyle[12pt,multicol]{article}\nx\n")
    assert "\\usepackage{multicol}" in out
    assert info["pkg_opts"] == ["multicol"]
    assert info["stripped"] == []
    assert "\\newenvironment{multicols}" not in out


def test_upgrade_direct_revtex42_also_strips() -> None:
    """``\\documentstyle{revtex4-2}`` 直写 2e 类名——按解析后 target 剥。"""
    out, info = upgrade_209("\\documentstyle[aps,multicol]{revtex4-2}\nx\n")
    assert "\\documentclass[aps]{revtex4-2}" in out
    assert info["stripped"] == ["multicol"]


def test_upgrade_shipped_incompat_sty_stripped(tmp_path: Path) -> None:
    """随源 ``cite.sty`` 在 revtex4-2 目标下同样剥除——shipped 不豁免硬不兼容。"""
    (tmp_path / "cite.sty").write_text("% local cite\n")
    out, info = upgrade_209("\\documentstyle[aps,cite]{revtex}\nx\n", root=tmp_path)
    assert info["stripped"] == ["cite"]
    assert "\\usepackage{cite" not in out


def _fake_kpse(rc: int, stdout: str = "") -> Callable[..., subprocess.CompletedProcess]:
    """造 ``subprocess.run`` 替身：模拟 kpsewhich 命中/未命中。"""

    def _run(*_a: object, **_k: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout)

    return _run


def test_target_resolvable_shipped_cls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """工程树内 ``<target>.cls`` 命中 → True（不依赖 kpsewhich）。"""
    (tmp_path / "jpsj3.cls").write_text("% vendored\n")
    monkeypatch.setattr(latex209.shutil, "which", lambda _n: None)
    assert _target_resolvable(tmp_path, "jpsj3") is True


def test_target_resolvable_kpse_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """工程树无命中但 kpsewhich 找到 → True。"""
    monkeypatch.setattr(latex209.shutil, "which", lambda _n: "/usr/bin/kpsewhich")
    monkeypatch.setattr(latex209.subprocess, "run", _fake_kpse(0, "/texmf/jpsj3.cls\n"))
    assert _target_resolvable(tmp_path, "jpsj3") is True


def test_target_resolvable_both_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """双侧无命中 → False（触发 ``latex209_no_target`` 的条件）。"""
    monkeypatch.setattr(latex209.shutil, "which", lambda _n: "/usr/bin/kpsewhich")
    monkeypatch.setattr(latex209.subprocess, "run", _fake_kpse(1))
    assert _target_resolvable(tmp_path, "jpsj3") is False


def test_target_resolvable_no_kpse_fails_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """kpsewhich 缺席/探测失败 fail-open → True（缺工具不阻断）。"""
    monkeypatch.setattr(latex209.shutil, "which", lambda _n: None)
    assert _target_resolvable(tmp_path, "jpsj3") is True

    def _raise_fnf(*_a: object, **_k: object) -> subprocess.CompletedProcess:
        raise FileNotFoundError

    monkeypatch.setattr(latex209.subprocess, "run", _raise_fnf)
    monkeypatch.setattr(latex209.shutil, "which", lambda _n: "/gone/kpsewhich")
    assert _target_resolvable(tmp_path, "jpsj3") is True


def test_upgrade_rename_target_missing_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """改名目标类双侧不可解析 → ``latex209_no_target`` 拒转（0111097 jpsj3 实证）。"""
    monkeypatch.setattr(latex209, "_target_resolvable", lambda *_a: False)
    tex = "\\documentstyle[epsfig,seceq,twocolumn]{jpsj}\nx\n"
    out, info = upgrade_209(tex, root=tmp_path)
    assert out == tex  # 拒转不改写原文
    assert info["status"] == "reject"
    assert info["reason"] == "latex209_no_target"
    assert info["target"] == "jpsj3"


def test_upgrade_target_guard_skips_unmapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未改名/未映射类不吃目标类守卫——aipproc 恒等映射、ptptex 未识别都放行。"""

    def _boom(*_a: object) -> bool:
        raise AssertionError

    monkeypatch.setattr(latex209, "_target_resolvable", _boom)
    out, info = upgrade_209("\\documentstyle{aipproc}\nx\n", root=tmp_path)
    assert info["status"] == "converted"
    assert "\\documentclass{aipproc}" in out
    out, info = upgrade_209("\\documentstyle{ptptex}\nx\n", root=tmp_path)
    assert info["status"] == "converted"
    assert "\\documentclass{ptptex}" in out


def test_inject_cjk_no_target_reject_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """reject reason 透传 inject 层 → ``InjectRejectError.reason`` 裸码。"""
    monkeypatch.setattr(latex209, "_target_resolvable", lambda *_a: False)
    with pytest.raises(InjectRejectError) as exc:
        inject_cjk("\\documentstyle{jpsj}\nx\n", root=tmp_path)
    assert exc.value.reason == "latex209_no_target"
    assert "inject_reject:latex209_no_target" in str(exc.value)


def test_upgrade_census_whitelist_names() -> None:
    """414 普查实证的真包名（曾静默落类选项位）必须进 ``\\usepackage``。"""
    names = (
        "tabularx",
        "multirow",
        "fullpage",
        "rotate",
        "pstricks",
        "flushrt",
        "dina4",
        "diagrams",
        "hangcaption",
        "amssym",
        "nato",
        "prabib",
        "espcrc2",
        "aas2pp4",
        "emulateapj",
    )
    out, info = upgrade_209("\\documentstyle[" + ",".join(names) + "]{article}\nx\n")
    assert info["pkg_opts"] == list(names)
    assert info["class_opts"] == []
    assert "\\usepackage{" + ",".join(names) + "}" in out


def test_upgrade_no_docstyle() -> None:
    tex = "\\documentclass{article}\nx\n"
    out, info = upgrade_209(tex)
    assert out == tex
    assert info["status"] == "no-docstyle"


def test_inject_cjk_converts_209() -> None:
    r"""可转 ``\documentstyle`` → 升级 + 正常注入；info 挂 upgrade209 台账。"""
    tex = "\\documentstyle[epsfig]{article}\n\\begin{document}\nx\\end{document}\n"
    out, info = inject_cjk(tex)
    assert info["status"] == "injected"
    assert info["upgrade209"]["status"] == "converted"
    assert "\\documentclass{article}" in out
    assert "\\usepackage{epsfig}" in out
    assert CTEX_LINE in out
    assert "latexsym" in out
    assert "\\documentstyle" not in out
    # 注入块落在 \documentclass 行后、转换出的 \usepackage 行前
    assert out.index(CTEX_LINE) > out.index("\\documentclass{article}")
    assert out.index(CTEX_LINE) < out.index("\\usepackage{epsfig}")


def test_inject_cjk_ds_at_reject_reason() -> None:
    tex = "\\documentstyle{ias}\n\\begin{document}\nx\\end{document}\n"
    with pytest.raises(InjectRejectError) as exc:
        inject_cjk(tex)
    assert exc.value.reason == "latex209_ds_at"


def test_inject_cjk_209_xecjk_mode() -> None:
    tex = "\\documentstyle{article}\n\\begin{document}\nx\\end{document}\n"
    out, info = inject_cjk(tex, mode="xecjk")
    assert info["mode"] == "xecjk"
    assert info["upgrade209"]["status"] == "converted"
    assert "\\documentclass{article}" in out
    assert "xeCJK" in out


def test_prepare_chinese_209(tmp_path: Path) -> None:
    """prepare_chinese 透传 root：随源 .sty 路由在工程级生效。"""
    (tmp_path / "nips.sty").write_text("\\newcommand{\\nipshead}{x}\n")
    (tmp_path / "main.tex").write_text(
        "\\documentstyle[12pt,nips]{article}\n\\begin{document}\nx\\end{document}\n"
    )
    info = prepare_chinese(tmp_path, "main.tex")
    assert info["status"] == "injected"
    assert info["upgrade209"]["shipped"] == ["nips"]
    out = (tmp_path / "main.tex").read_text()
    assert "\\documentclass[12pt]{article}" in out
    assert "\\usepackage{nips}" in out
    assert CTEX_LINE in out
