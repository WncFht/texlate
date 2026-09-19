"""eps_converted_alias — ``*-eps-converted-to.pdf`` 随稿件别名臂.

firedunfixed 普查 item5 (2403.05444/2308.04278): e-print 随带上游
epstopdf 产物 ``X-eps-converted-to.pdf`` 而 ``X.eps``/``X`` 不在盘,
稿面未载 epstopdf —— 显式 ``{X.eps}`` 归 missing_file|X.eps、裸 ``{X}``
归 other|None。builtin 落 ``<stem>.pdf`` 别名 + eps 族引用剥名。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins import eps_converted_alias
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.fixloop.ruleset import load_ruleset

if TYPE_CHECKING:
    from pathlib import Path

_PDF = b"%PDF-1.4 fake conv bytes\n"
_HEAD = "! File `Fig1' not found.\nl.12 \\includegraphics{Fig1}\n"


def _ctx(
    tmp_path: Path,
    files: dict[str, str | bytes],
    main: str = "main.tex",
    err_head: str = _HEAD,
) -> LoopCtx:
    for rel, data in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            p.write_bytes(data)
        else:
            p.write_text(data, encoding="utf-8")
    return LoopCtx(
        wdir=tmp_path, engine_name="xelatex", main_rel=main, err_head=err_head
    )


def test_bare_ref_gets_pdf_alias(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\begin{document}\n\\includegraphics{Fig1}\n\\end{document}\n"
            ),
            "Fig1-eps-converted-to.pdf": _PDF,
        },
    )
    ok, note = eps_converted_alias(ctx, None, "Fig1", {})
    assert ok, note
    assert (tmp_path / "Fig1.pdf").read_bytes() == _PDF


def test_eps_ref_aliased_and_stripped(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\begin{document}\n\\includegraphics{Fig2.eps}\n\\end{document}\n"
            ),
            "Fig2-eps-converted-to.pdf": _PDF,
        },
        err_head="! File `Fig2.eps' not found.\nl.12 x\n",
    )
    ok, note = eps_converted_alias(ctx, None, "Fig2.eps", {})
    assert ok, note
    assert (tmp_path / "Fig2.pdf").read_bytes() == _PDF
    assert "\\includegraphics{Fig2}" in (tmp_path / "main.tex").read_text()


def test_epsfig_kv_aliased_and_stripped(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{epsfig}\n"
                "\\begin{document}\n\\epsfig{file=plot.eps,height=3cm}\n"
                "\\end{document}\n"
            ),
            "plot-eps-converted-to.pdf": _PDF,
        },
    )
    ok, note = eps_converted_alias(ctx, None, "plot.eps", {})
    assert ok, note
    assert (tmp_path / "plot.pdf").is_file()
    assert "file=plot" in (tmp_path / "main.tex").read_text()


def test_err_head_name_recovers_when_payload_none(tmp_path: Path) -> None:
    # other|None 轮 —— payload 缺席, err_head 提名驱动 (裸名无 ext 签名)
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\begin{document}\n\\includegraphics{Fig1}\n\\end{document}\n"
            ),
            "Fig1-eps-converted-to.pdf": _PDF,
        },
    )
    ok, note = eps_converted_alias(ctx, None, None, {})
    assert ok, note
    assert (tmp_path / "Fig1.pdf").is_file()


def test_conv_in_offpath_subdir_found(tmp_path: Path) -> None:
    # 2403.05444 形态: conv 件在 cwd 根, .eps 在 arvix/ 旁置 ——
    # 反向 (conv 自身落子目录) 同由 rglob basename 兜底
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\begin{document}\n\\includegraphics{Fig3}\n\\end{document}\n"
            ),
            "arvix/Fig3-eps-converted-to.pdf": _PDF,
        },
    )
    ok, note = eps_converted_alias(ctx, None, "Fig3", {})
    assert ok, note
    assert (tmp_path / "Fig3.pdf").read_bytes() == _PDF


def test_main_in_subdir_resolves_relative_to_main(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {
            "src/main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\begin{document}\n\\includegraphics{pic}\n\\end{document}\n"
            ),
            "src/pic-eps-converted-to.pdf": _PDF,
        },
        main="src/main.tex",
    )
    ok, note = eps_converted_alias(ctx, None, "pic", {})
    assert ok, note
    assert (tmp_path / "src/pic.pdf").is_file()


def test_verbatim_resolvable_ref_untouched(tmp_path: Path) -> None:
    # {Fig1} 已可解 (Fig1.png 在盘) —— clean 稿不落重复别名
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\begin{document}\n\\includegraphics{Fig1}\n\\end{document}\n"
            ),
            "Fig1.png": _PDF,
            "Fig1-eps-converted-to.pdf": _PDF,
        },
        err_head="",
    )
    ok, _note = eps_converted_alias(ctx, None, "Fig1", {})
    assert not ok
    assert not (tmp_path / "Fig1.pdf").exists()


def test_no_conv_shipped_declines(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\begin{document}\n\\includegraphics{Fig1}\n\\end{document}\n"
            )
        },
    )
    ok, note = eps_converted_alias(ctx, None, "Fig1", {})
    assert not ok
    assert "no shipped" in note
    assert not (tmp_path / "Fig1.pdf").exists()


def test_commented_ref_not_live(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": "% \\includegraphics{Fig1}\nx\n",
            "Fig1-eps-converted-to.pdf": _PDF,
        },
        err_head="",
    )
    ok, _note = eps_converted_alias(ctx, None, None, {})
    assert not ok
    assert not (tmp_path / "Fig1.pdf").exists()


def test_png_ref_no_alias(tmp_path: Path) -> None:
    # .png 显式缺件与 conv 件无语义对应 —— 不落无关 .pdf
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\begin{document}\n\\includegraphics{Fig1.png}\n\\end{document}\n"
            ),
            "Fig1-eps-converted-to.pdf": _PDF,
        },
        err_head="! File `Fig1.png' not found.\n",
    )
    ok, _note = eps_converted_alias(ctx, None, "Fig1.png", {})
    assert not ok
    assert not (tmp_path / "Fig1.pdf").exists()


def test_path_traversal_refused(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": "x\n",
            "sub/x-eps-converted-to.pdf": _PDF,
        },
        err_head="! File `../evil' not found.\n",
    )
    ok, _note = eps_converted_alias(ctx, None, "../evil.eps", {})
    assert not ok
    assert not (tmp_path.parent / "evil.pdf").exists()


def test_epsfbox_not_stripped(tmp_path: Path) -> None:
    # epsfbox 是裸 PS 装载点无 \Gin@extensions —— 剥名臂不动它
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\input epsf\n"
                "\\begin{document}\n\\epsfbox{p.eps}\n\\end{document}\n"
            ),
            "p-eps-converted-to.pdf": _PDF,
        },
        err_head="",
    )
    ok, _note = eps_converted_alias(ctx, None, None, {})
    assert not ok
    assert "\\epsfbox{p.eps}" in (tmp_path / "main.tex").read_text()


def test_rule_order_between_relax_and_eps_to_pdf() -> None:
    # order 8.6: fileset_relocate(9) 前拿派发窗 —— 2403.05444 实证 relocate
    # 逐轮搬一张 .eps, 13 图 > 8 轮预算饿死; conv 家须一轮全愈。
    ids = [r.id for r in load_ruleset().phase("loop")]
    assert ids.index("main_wrapper_promote") < ids.index("eps_converted_alias")
    assert ids.index("eps_converted_alias") < ids.index("fileset_relocate")
    assert ids.index("eps_converted_alias") < ids.index("eps_to_pdf")
    rules = {r.id: r for r in load_ruleset().phase("loop")}
    when = rules["eps_converted_alias"].when
    assert when == {
        "any": [
            {"category": "missing_file", "payload_required": True},
            {"category": "missing_graphic", "payload_required": True},
            {"category": "ps_image", "payload_required": True},
            {"category": "other"},
        ]
    }
