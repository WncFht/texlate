"""latex209 ds@ 桥——随源 ``<cls>.sty`` 当 2e 样式装载的桥体件专项钉。

桥体语义（``latex209._ds_at_bridge``）：未映射非标准类携随源 ``<cls>.sty`` 时，
``\\documentclass{article}`` 底 + ``\\makeatletter`` 窗内 ``\\input{<cls>.sty}``
（2.09 样式假设 @-letter 语境）+ ``\\@options`` polyfill 字面分发表——自耗式
恰好一次分发（样式自调/桥尾补调只取其一），未定义 ``ds@<opt>`` 处理器退回
``\\IfFileExists`` 装载。内核选项两路同付：类选项位吃真实版面效果、字面表
忠实 ds@ 分发；非内核选项（psfig 等 2.09 样式文件名）只进字面表——
``\\@options`` 的 ``\\input{<opt>.sty}`` 回退即原语义装载，不再经
``\\usepackage``。``\\@ifdefinable``/``\\@rc@ifdefinable`` 同窗口双放开：
``\\renewcommand`` 会把前者重绑回自恢复的 ``\\@rc@ifdefinable``（其执行即
还原内核版），单补一路护不住 ``\\input`` 窗。
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tarfile
from typing import TYPE_CHECKING

import pytest
from _latex209kit import target_always_resolvable  # noqa: F401

from texlate.compile.latex209 import _DS_AT_CLASSES, upgrade_209

if TYPE_CHECKING:
    from pathlib import Path

_DOC = "\\begin{document}\nx\n\\end{document}\n"


def _ship(root: Path, rel: str, body: str = "\\def\\ds@preprint{}\n") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def test_bridge_shipped_sty_converts(tmp_path: Path) -> None:
    """随源 ``<cls>.sty`` 在场 → article 底桥转换（不再 ``latex209_ds_at`` 拒）。"""
    _ship(tmp_path, "mycls.sty")
    out, info = upgrade_209("\\documentstyle{mycls}\n" + _DOC, root=tmp_path)
    assert info["status"] == "converted"
    assert info["ds_bridge"] is True
    assert info["bridge_sty"] == "mycls.sty"
    assert info["target"] == "article"
    assert "\\documentclass{article}" in out
    assert "\\documentstyle" not in out
    assert "\\makeatletter" in out
    assert "\\makeatother" in out
    assert "\\input{mycls.sty}" in out
    assert "\\def\\@options{" in out


def test_bridge_opt_split_kernel_vs_literal(tmp_path: Path) -> None:
    """内核选项两路同付；样式文件名选项只进字面分发表不进 ``\\usepackage``。"""
    _ship(tmp_path, "mycls.sty")
    out, info = upgrade_209(
        "\\documentstyle[twocolumn,psfig,sort&compress]{mycls}\n" + _DOC,
        root=tmp_path,
    )
    # twocolumn：类选项位 + 字面表双付；psfig：只进字面表（2.09 语义由
    # \@options 的 \input{psfig.sty} 回退装载）；sort&compress 含 & 非
    # glob 安全字符，字面表过滤。
    assert info["class_opts"] == ["twocolumn"]
    assert info["pkg_opts"] == []
    assert info["shipped"] == []
    assert info["stripped"] == []
    assert "\\documentclass[twocolumn]{article}" in out
    m = re.search(r"\\@for\\@tempa:=([^\n]*)\\do", out)
    assert m
    assert m.group(1) == "twocolumn,psfig"
    assert "\\usepackage{psfig}" not in out


def test_bridge_ds_at_named_class_with_sty(tmp_path: Path) -> None:
    """``_DS_AT_CLASSES`` 成员携随源 sty → 桥路优先于按名拒收。"""
    assert "julie" in _DS_AT_CLASSES
    _ship(tmp_path, "julie.sty", "\\def\\ds@l@@@{}\\@options\n")
    out, info = upgrade_209("\\documentstyle{julie}\n" + _DOC, root=tmp_path)
    assert info["status"] == "converted"
    assert info["ds_bridge"] is True
    assert "\\input{julie.sty}" in out


def test_ds_at_named_class_no_sty_still_rejects(tmp_path: Path) -> None:
    """``_DS_AT_CLASSES`` 成员无随源载体 → 维持 ``latex209_ds_at`` 拒。"""
    tex = "\\documentstyle{julie}\n" + _DOC
    out, info = upgrade_209(tex, root=tmp_path)
    assert out == tex
    assert info["status"] == "reject"
    assert info["reason"] == "latex209_ds_at"


def test_bridge_plain_sty_no_ds_at(tmp_path: Path) -> None:
    """随源 sty 无 ds@ 字样同样走桥——存在即载体，不强制分发机。"""
    _ship(tmp_path, "mycls.sty", "% plain 2.09 style, no dispatch\n")
    _out, info = upgrade_209("\\documentstyle{mycls}\n" + _DOC, root=tmp_path)
    assert info["status"] == "converted"
    assert info["ds_bridge"] is True


def test_bridge_subdir_sty_iffilesexists(tmp_path: Path) -> None:
    """sty 落子目录 → ``\\IfFileExists`` 裸名/相对路径双路回退装载行。"""
    _ship(tmp_path, "sub/mycls.sty")
    out, info = upgrade_209("\\documentstyle{mycls}\n" + _DOC, root=tmp_path)
    assert info["bridge_sty"] == "sub/mycls.sty"
    assert "\\IfFileExists{mycls.sty}" in out
    assert "\\IfFileExists{sub/mycls.sty}{\\input{sub/mycls.sty}}" in out


def test_bridge_opts_unsafe_chars_filtered(tmp_path: Path) -> None:
    """字面分发表只收 glob 安全字符集——``&``/CJK 等滤除（防 rglob/注入面）。"""
    _ship(tmp_path, "mycls.sty")
    out, _info = upgrade_209(
        "\\documentstyle[sort&compress,中,ok]{mycls}\n" + _DOC, root=tmp_path
    )
    m = re.search(r"\\@for\\@tempa:=([^\n]*)\\do", out)
    assert m
    assert m.group(1) == "ok"


def test_bridge_self_consuming_options(tmp_path: Path) -> None:
    r"""``\@options`` 分发后自耗成空 + 桥尾补调一次——恰好一次分发。"""
    _ship(tmp_path, "mycls.sty", "% no \\@options inside\n")
    out, _info = upgrade_209("\\documentstyle[preprint]{mycls}\n" + _DOC, root=tmp_path)
    assert "\\@ifundefined{ds@\\@tempa}" in out
    assert "\\@nameuse{ds@\\@tempa}" in out
    assert "\\gdef\\@options{}}" in out  # 自耗
    # 桥尾裸 \@options——样式不自调时兜底；已自调时命中上行的空体
    assert out.index("\\input{mycls.sty}") < out.index("\n\\@options\n")


def test_bridge_ifdefinable_patches_both(tmp_path: Path) -> None:
    r"""``\@ifdefinable`` + ``\@rc@ifdefinable`` 双放开双还原——``\renewcommand``
    的重绑陷阱须两路同护。"""
    _ship(tmp_path, "mycls.sty")
    out, _info = upgrade_209("\\documentstyle{mycls}\n" + _DOC, root=tmp_path)
    assert "\\let\\@ifdefinable@orig\\@ifdefinable" in out
    assert "\\let\\@rc@ifdefinable@orig\\@rc@ifdefinable" in out
    assert "\\def\\@ifdefinable#1#2{#2}" in out
    assert "\\def\\@rc@ifdefinable#1#2{#2}" in out
    assert "\\let\\@ifdefinable\\@ifdefinable@orig" in out
    assert "\\let\\@rc@ifdefinable\\@rc@ifdefinable@orig" in out
    # 装载行夹在两补丁之间——\input 窗口全期 lax
    assert out.index("\\def\\@ifdefinable") < out.index("\\input{mycls.sty}")
    assert out.index("\\input{mycls.sty}") < out.index(
        "\\let\\@ifdefinable\\@ifdefinable@orig"
    )


def test_bridge_idempotent(tmp_path: Path) -> None:
    """桥产物二次升级 ``no-docstyle`` 且字节不动——注释字样不命中声明面。"""
    _ship(tmp_path, "mycls.sty")
    out, info = upgrade_209("\\documentstyle{mycls}\n" + _DOC, root=tmp_path)
    assert info["status"] == "converted"
    out2, info2 = upgrade_209(out, root=tmp_path)
    assert info2["status"] == "no-docstyle"
    assert out2 == out


def test_bridge_info_shape(tmp_path: Path) -> None:
    """桥转换 info 契约：ds_bridge/bridge_sty + 三路分派字段恒空。"""
    _ship(tmp_path, "mycls.sty")
    _out, info = upgrade_209("\\documentstyle[12pt]{mycls}\n" + _DOC, root=tmp_path)
    assert info["status"] == "converted"
    assert info["class"] == "mycls"
    assert info["target"] == "article"
    assert info["ds_bridge"] is True
    assert info["bridge_sty"] == "mycls.sty"
    assert info["class_opts"] == ["12pt"]
    assert info["pkg_opts"] == info["shipped"] == info["stripped"] == []


def test_mapped_class_ignores_shipped_sty(tmp_path: Path) -> None:
    """已映射类不查随源 sty——``revtex`` 照常升 revtex4-2（桥不抢改名路）。"""
    _ship(tmp_path, "revtex.sty")
    out, info = upgrade_209("\\documentstyle{revtex}\n" + _DOC, root=tmp_path)
    assert info["ds_bridge"] is False
    assert info["bridge_sty"] is None
    assert info["target"] == "revtex4-2"
    assert "\\input{revtex.sty}" not in out


def test_std_class_ignores_shipped_sty(tmp_path: Path) -> None:
    """标准类不查随源 sty——``article`` 走原路（同名 sty 不劫持）。"""
    _ship(tmp_path, "article.sty")
    out, info = upgrade_209("\\documentstyle{article}\n" + _DOC, root=tmp_path)
    assert info["ds_bridge"] is False
    assert info["target"] == "article"
    assert "\\input{article.sty}" not in out


def test_jpsj_maps_jpsj2_not_bridge(tmp_path: Path) -> None:
    """jpsj → jpsj2 真 2e 继任类（映射路）；随源 jpsj.sty 不劫持桥路。"""
    _ship(tmp_path, "jpsj.sty")
    out, info = upgrade_209("\\documentstyle[seceq]{jpsj}\n" + _DOC, root=tmp_path)
    assert info["ds_bridge"] is False
    assert info["target"] == "jpsj2"
    assert "\\documentclass[seceq]{jpsj2}" in out
    assert "\\input{jpsj.sty}" not in out


def test_bridge_tar_sty_skipped(tmp_path: Path) -> None:
    """tar 伪装 ``<cls>.sty`` 不作载体——检出件须真样式文件（_tar_disguised 闸）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        payload = b"\\def\\ds@x{}\n"
        ti = tarfile.TarInfo("inner.tex")
        ti.size = len(payload)
        tf.addfile(ti, io.BytesIO(payload))
    (tmp_path / "mycls.sty").write_bytes(buf.getvalue())
    out, info = upgrade_209("\\documentstyle{mycls}\n" + _DOC, root=tmp_path)
    # 无载体可桥 → 原盲升路：未识别类名原样保留交 fixloop missing_file
    assert info["status"] == "converted"
    assert info["ds_bridge"] is False
    assert info["bridge_sty"] is None
    assert info["target"] == "mycls"
    assert "\\input{mycls.sty}" not in out


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("xelatex") is None, reason="xelatex not installed")
def test_bridge_real_xelatex(tmp_path: Path) -> None:
    r"""真编译：ds@ 自分发 sty + ``\@ifdefinable`` 双补丁窗口全链路。

    sty 编排鉴别三态：``\newcounter{section}``（article 已注册）走直接
    ``\@ifdefinable`` 臂；``\renewcommand`` 把 ``\@ifdefinable`` 重绑回
    ``\@rc@ifdefinable``；其后两个 ``\newcounter`` 证明 lax 窗口未塌回
    内核版（单补一路时：rc 臂执行并还原 strict → 第三个定义必炸
    "already defined"）。
    """
    (tmp_path / "my209.sty").write_text(
        "\\def\\ds@myopt{\\def\\myoptseen{SEEN}}\n"
        "\\newcounter{section}\n"
        "\\renewcommand{\\baselinestretch}{1.0}\n"
        "\\newcounter{subsection}\n"
        "\\newcounter{subsubsection}\n"
        "\\@options\n"
    )
    out, info = upgrade_209(
        "\\documentstyle[myopt]{my209}\n\\begin{document}\nopt: \\myoptseen.\n"
        "\\end{document}\n",
        root=tmp_path,
    )
    assert info["status"] == "converted"
    assert info["ds_bridge"] is True
    (tmp_path / "main.tex").write_text(out)
    xelatex = shutil.which("xelatex")
    assert xelatex is not None
    proc = subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [xelatex, "-interaction=nonstopmode", "main.tex"],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
    )
    log = (tmp_path / "main.log").read_text(encoding="utf-8", errors="replace")
    assert not re.search(r"^! ", log, re.MULTILINE), log
    assert "Undefined control sequence" not in log
    assert (tmp_path / "main.pdf").exists()
    assert proc.returncode == 0
