r"""slot_arg_revert inferkv 机位 —— kvcen: mathpartir ``\inferrule*[kv]`` (2026-09-19)。

``\infer``/``\infer*``/``\inferrule*`` opt 位 kv 键 zh 化 → spec 域
ident 配对还原; premise/conclusion 多层花括号 mand 参非机位不碰;
空 ``[]`` 双侧一致不占改写。
"""

from pathlib import Path

from _fixloopkit import mk_ctx

from texlate.compile.fixloop.builtins import slot_arg_revert


def _trees(root: Path) -> tuple[Path, Path]:
    """wdir + baseline 双子树 —— baseline 必须在 wdir 外。"""
    work, base = root / "work", root / "baseline"
    work.mkdir()
    base.mkdir()
    return work, base


def _pair(work: Path, base: Path, name: str, src: str, zh: str) -> None:
    (base / name).write_text(src, encoding="utf-8")
    (work / name).write_text(zh, encoding="utf-8")


def _run(work: Path, base: Path) -> tuple[bool, str]:
    return slot_arg_revert(mk_ctx(work), None, None, {"baseline_dir": str(base)})


def test_inferkv_opt_kv_reverted(tmp_path: Path) -> None:
    r"""mathpartir ``\inferrule*[left = \rlabel{Rec}]`` opt kv 键 zh 化
    (1708.07366 实证) —— opt 位 spec 域 ident 整体还原; premise 多层
    花括号/跨行参 ``_ARG`` 吃不进, kv 行盖不到 → inferkv opt-only 独盖;
    空 ``[]`` 双侧一致不占改写。"""
    work, base = _trees(tmp_path)
    src = (
        "\\inferrule*[left = \\rlabel{Rec}]\n"
        "{\n  \\inferrule*[left = \\rlabel{Alt}]{P\\to Q}{C}\n}\n{D}\n"
        "\\inferrule*[]\n{A}\n{B}\n"
    )
    zh = (
        "\\inferrule*[这是译文 = \\rlabel{Rec}]\n"
        "{\n  \\inferrule*[这是译文 = \\rlabel{Alt}]{P\\to Q}{C}\n}\n{D}\n"
        "\\inferrule*[]\n{A}\n{B}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_inferkv_bare_infer_covered(tmp_path: Path) -> None:
    r"""``\infer``/``\infer*`` 同族 opt 位同盖 (mathpartir ``\mpr@infer``
    双形同收 ``[opt]``)。"""
    work, base = _trees(tmp_path)
    src = "\\infer[lab = \\u{X}]{P}{C}\n\\infer*[right = \\u{Y}]{Q}{D}\n"
    zh = "\\infer[这是译文 = \\u{X}]{P}{C}\n\\infer*[这是译文 = \\u{Y}]{Q}{D}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_inferkv_no_opt_sites_not_slots(tmp_path: Path) -> None:
    r"""无 ``[]`` 的 ``\infer{a}{b}`` mand 参非机位 (premise/conclusion
    是数学面) —— zh 化也不还原; 一致 opt 不改写。"""
    work, base = _trees(tmp_path)
    src = "\\inferrule*[l=x]{P}{C}\n\\infer{A}{B}\n\\label{s}\n"
    zh = "\\inferrule*[l=x]{P}{C}\n\\infer{文}{B}\n\\label{文}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "\\infer{文}{B}" in out  # mand 参非机位, zh 保留
    assert "\\inferrule*[l=x]{P}{C}" in out  # 双侧一致 opt 未动
    assert "\\label{s}" in out


def test_inferkv_cjk_src_opt_not_reverted(tmp_path: Path) -> None:
    """baseline opt 自带 CJK (合法中文 label) → 非 ASCII, 不碰。"""
    work, base = _trees(tmp_path)
    _pair(
        work,
        base,
        "main.tex",
        "\\inferrule*[left = 归纳]{P}{C}\n",
        "\\inferrule*[left = 假设]{P}{C}\n",
    )
    ok, _note = _run(work, base)
    assert not ok
