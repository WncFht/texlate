"""ctan version_guard — format/包版本 floor 闸覆盖族单测 (批六 ctanre)。

实证锚点 (e2ereal 2308.12712 + vendor/files/nicematrix.sty v7.11a):
- ``\\IfFormatAtLeastTF{2026-06-01}`` 是 v7.11c abort 的真闸形 ——
  旧 ``_NEEDFMT_RE`` 只认 ``\\NeedsTeXFormat``, 完全漏检。
- v7.11a 真件写法 ``\\IfFormatAtLeastTF { 2025-06-01 }`` /
  ``\\IfPackageAtLeastF { array }\\n  { 2025/09/25 }`` —— 实参带空白/换行。
- ``\\providecommand { \\IfFormatAtLeastTF } { \\@ifl@t@r \\fmtversion }``
  shim 定义行无日期 —— 不得误判。
- ``\\ProvidesX{name}[date]`` 是包自署日期非 floor —— 明确不接线
  (expl3 件走 ``{\\ExplFileDate}``/``\\GetIdInfo`` 间址, 字面也兜不住)。
texmf 普查: ``\\RequirePackage{expl3}[date]`` loader 闸 408 件,
``\\@ifpackagelater`` 目标非 expl3 系过半 (hyperref/csquotes/graphics)。
"""

import io
import lzma
import tarfile
from pathlib import Path

import pytest

from texlate.compile.ctan import (
    TlpdbIndex,
    check_version_compat,
    ctan_fetch,
)

EPOCH = "2022-07-14"
MIRROR = "https://m.test/tlnet"


def _sty(tmp_path: Path, body: str) -> Path:
    f = tmp_path / "gate.sty"
    f.write_text(body + "\n", encoding="utf-8")
    return f


def _compat(tmp_path: Path, body: str, epoch: str = EPOCH) -> bool:
    return check_version_compat([_sty(tmp_path, body)], epoch)[0]


def make_tarxz(members: dict[str, bytes]) -> bytes:
    """内存构造 ``archive/<pkg>.tar.xz`` 响应体 (同 test_fixloop_ctan 口径)。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return lzma.compress(buf.getvalue())


# ---------------------------------------------------------------- 单参闸族
@pytest.mark.parametrize(
    "body",
    [
        "\\IfFormatAtLeastTF{2026-06-01}",  # v7.11c abort 闸 (实证形态)
        "\\IfFormatAtLeastTF { 2026-06-01 }",  # v7.11a 带空白形
        "\\IfFormatAtLeastF{2026-06-01}",
        "\\IfFormatAtLeastT{2026-06-01}",
        "\\IfExplAtLeastTF{2025-01-01}",  # expl3 loader 闸
        "\\@ifl@t@r\\fmtversion{2025-01-01}",  # 原语直用 (texmf 66 件)
        "\\@ifl@t@r \\fmtversion { 2025-01-01 }",
        "\\@ifl@t@r\\ExplLoaderFileDate{2025-01-01}",
        "\\@ifl@t@r \\csname ver@hyperref.sty\\endcsname { 2025-01-01 }",
        "\\NeedsTeXFormat{LaTeX2e}[2023/05/01]",  # 旧形回归
        "\\NeedsTeXFormat{LaTeX2e} [2023-05-01]",
    ],
)
def test_single_arg_format_gates_reject(tmp_path: Path, body: str) -> None:
    assert _compat(tmp_path, body) is False


@pytest.mark.parametrize(
    "body",
    [
        "\\IfFormatAtLeastTF{2020-01-01}",  # 闸要求早于 epoch → 放行
        "\\IfExplAtLeastTF{2019/01/01}",
        "\\@ifl@t@r\\fmtversion{2020/01/01}",
        "\\NeedsTeXFormat{LaTeX2e}[2020/01/01]",  # 旧形回归
    ],
)
def test_single_arg_gates_below_epoch_pass(tmp_path: Path, body: str) -> None:
    assert _compat(tmp_path, body) is True


# ---------------------------------------------------------------- 双参闸族
@pytest.mark.parametrize(
    "body",
    [
        "\\IfPackageAtLeastF { array }\n  { 2025/09/25 }",  # v7.11a 真件换行形
        "\\IfPackageAtLeastTF{expl3}{2024/02/01}",
        "\\IfPackageAtLeastF{siunitx}{2026/03/26}",  # v7.11a siunitx 闸
        "\\IfClassAtLeastTF{foo}{2025/01/01}",
        "\\IfClassAtLeastF{foo}{2025/01/01}",
        "\\IfFileAtLeastTF{foo.sty}{2025/01/01}",
        "\\@ifpackagelater{expl3}{2024/02/01}{}{}",  # 旧形回归
        "\\@ifpackagelater{hyperref}{2024/02/01}",  # 非 expl3 系名槽
        "\\@ifclasslater{book}{2024/02/01}",
        "\\@ifl@ter\\@pkgextension{foo}{2024/02/01}",  # 原语形
        "\\@ifl@ter \\@clsextension { foo } { 2024/02/01 }",
        "\\RequirePackage{expl3}[2023/01/01]",  # loader 闸 (texmf 408 件)
        "\\RequirePackage[opts]{expl3}[2023/01/01]",
        "\\RequirePackageWithOptions{expl3}[2023/01/01]",
        "\\usepackage{foo,bar}[2023-06-01]",  # 逗号多名
        "\\documentclass[12pt]{article}[2023/01/01]",
        "\\LoadClass{book}[2023/01/01]",
        "\\LoadClassWithOptions{book}[2023/01/01]",
    ],
)
def test_two_arg_gates_reject(tmp_path: Path, body: str) -> None:
    assert _compat(tmp_path, body) is False


@pytest.mark.parametrize(
    "body",
    [
        "\\@ifpackagelater{expl3}{2020/01/01}",  # 早于 epoch → 放行
        "\\IfPackageAtLeastTF{array}{2020/01/01}",
        "\\RequirePackage{expl3}[2020/01/01]",
        "\\usepackage{foo,bar}[2021-06-01]",
    ],
)
def test_two_arg_gates_below_epoch_pass(tmp_path: Path, body: str) -> None:
    assert _compat(tmp_path, body) is True


# ---------------------------------------------------------------- 非闸形不误伤
@pytest.mark.parametrize(
    "body",
    [
        # v7.11a shim 定义行 —— 无日期实参, 不算 floor
        "\\providecommand { \\IfFormatAtLeastTF } { \\@ifl@t@r \\fmtversion }",
        "\\providecommand\\IfFormatAtLeastTF{\\@ifl@t@r\\fmtversion}",
        # \\ProvidesX 自署日期非 floor (expl3 间址形更兜不住) —— 不接线
        "\\ProvidesPackage{foo}[2025/01/01]",
        "\\ProvidesClass{foo}[2025/01/01]",
        "\\ProvidesExplPackage{\\ExplFileName}{\\ExplFileDate}{2.5.10}{d}",
        "\\ProvidesExplPackage{foo}{2026/01/01}{v1}{d}",
        # 非日期 bracket: 版本钉/间址/纯选项
        "\\usepackage{siunitx}[=v2]",
        "\\usepackage{glossaries}[=v4.46]",
        "\\RequirePackage{foo}[\\KOMAScriptVersion]",
        "\\RequirePackage{foo}[v1.2]",
        "\\usepackage[utf8]{inputenc}",
        "\\documentclass[12pt]{article}",
        # 裸调用无日期实参
        "\\RequirePackage{expl3}",
        "\\usepackage{hyperref}",
    ],
)
def test_non_gate_forms_not_floors(tmp_path: Path, body: str) -> None:
    assert _compat(tmp_path, body) is True


# ---------------------------------------------------------------- 聚合/跨文件
def test_max_date_wins_across_gates(tmp_path: Path) -> None:
    """同文件新老闸并存 → 取 max (2026 闸胜过 2020 闸)。"""
    body = (
        "\\IfFormatAtLeastTF{2020-01-01}{a}{b}\n"
        "\\IfPackageAtLeastF{array}{2025/09/25}{c}\n"
        "\\IfFormatAtLeastTF{2026-06-01}{}{\\msg_critical:nn { x } { y }}\n"
    )
    ok, why = check_version_compat([_sty(tmp_path, body)], EPOCH)
    assert ok is False
    assert "2026-06-01" in why


def test_max_date_wins_across_files(tmp_path: Path) -> None:
    """多落盘件并扫 → max 跨文件聚合。"""
    a = _sty(tmp_path, "\\IfFormatAtLeastTF{2020-01-01}")
    b = tmp_path / "b.sty"
    b.write_text("\\RequirePackage{expl3}[2024/02/01]\n")
    assert check_version_compat([a, b], EPOCH)[0] is False


def test_feature_conditional_counts_as_floor(tmp_path: Path) -> None:
    """``\\IfFormatAtLeastTF`` 带 fallback 分支也计 floor —— 有意保守:
    正则不分辨 abort/降级意图, 宁可拒装不放进过新件 (v7.11a 自身
    ``{ 2026-04-01 }`` 特性闸同计; 该件本需 format>=2025-06-01, 结论一致)。"""
    body = "\\IfFormatAtLeastTF{2026-04-01}{\\NewThing}{\\OldFallback}"
    assert _compat(tmp_path, body, epoch="2025-11-01") is False


def test_epoch_boundary_equal_date_passes(tmp_path: Path) -> None:
    """闸日期恰等于 epoch → 不拒 (bundle 快照恰含该日版)。"""
    assert _compat(tmp_path, "\\IfFormatAtLeastTF{2022-07-14}") is True
    assert _compat(tmp_path, "\\@ifpackagelater{expl3}{2022/07/14}") is True


def test_unreadable_and_datefree_files_skipped(tmp_path: Path) -> None:
    """无 floor 声明的文件 → (True, None)。"""
    assert check_version_compat([_sty(tmp_path, "\\ProvidesPackage{foo}")], EPOCH) == (
        True,
        None,
    )


# ---------------------------------------------------------------- ctan_fetch 端到端
def test_ctan_fetch_rejects_ifformat_gate(tmp_path: Path) -> None:
    """nicematrix 场景端到端: fetched 件含 ``\\IfFormatAtLeastTF{2026-06-01}``
    → version_guard 拒装 + 已落盘撤回 —— 修复前此形穿透守卫。"""
    idx = TlpdbIndex({"nicematrix.sty": ["nicematrix"]})
    body = make_tarxz(
        {
            "texmf-dist/tex/latex/n/nicematrix.sty": (
                b"\\ProvidesExplPackage{nicematrix}{2026/07/22}{7.11c}{d}\n"
                b"\\IfFormatAtLeastTF{2026-06-01}{}"
                b"{\\msg_critical:nn { nicematrix } { latex-too-old }}\n"
            )
        }
    )
    res = ctan_fetch(
        "nicematrix.sty",
        tmp_path,
        idx,
        mirror=MIRROR,
        epoch=EPOCH,
        fetcher=lambda _u: body,
    )
    assert not res.ok
    assert not (tmp_path / "nicematrix.sty").exists()
    assert "requires" in (res.advisory or "")


def test_ctan_fetch_clean_gate_passes(tmp_path: Path) -> None:
    """闸要求全部早于 epoch → 正常落盘。"""
    idx = TlpdbIndex({"foo.sty": ["foo"]})
    body = make_tarxz(
        {
            "texmf-dist/tex/latex/f/foo.sty": (
                b"\\IfFormatAtLeastTF{2020-01-01}{\\New}{\\Old}\n"
                b"\\RequirePackage{expl3}[2021/01/01]\n"
            )
        }
    )
    res = ctan_fetch(
        "foo.sty", tmp_path, idx, mirror=MIRROR, epoch=EPOCH, fetcher=lambda _u: body
    )
    assert res.ok
    assert (tmp_path / "foo.sty").exists()
