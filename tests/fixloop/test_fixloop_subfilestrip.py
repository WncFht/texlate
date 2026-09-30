"""subfile_docclass_strip — 非主 .tex 自带 \\documentclass → 剥至 body 区.

failmine3 #164b (3 格): standalone/subfiles 子文档被 \\input/\\subimport
进正文时 preamble-only cs 在 body 执行 → "Can be used only in preamble"。
剥至 \\begin..\\end{document} 内文是 \\subfile/\\includestandalone 包
skip 机制的恒等语义, 也是裸 \\input 唯一可编译形。与 #168 subfilegate
(normalize 注入侧门) 互补: 一侧挡新毒, 一侧清自带毒。

引用门 (2409.00265): 只剥被存活 input 族命令 (\\input/\\include/
\\subfile/\\import 族/\\InputIfFileExists) 引用的文件 —— 无引用的
docclass 持件 (独立第二文档/误判主档下的真主档) 永不进编译流。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins import subfile_docclass_strip
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.fixloop.ruleset import load_ruleset

if TYPE_CHECKING:
    from pathlib import Path

_MAIN = "\\documentclass{article}\n\\begin{document}\n\\input{sub}\n\\end{document}\n"
_SUB = (
    "\\documentclass{article}\n\\usepackage{amsmath}\n"
    "\\newcommand{\\x}{1}\n\\begin{document}\nSub body $a+b$.\n"
    "\\end{document}\n"
)


def _ctx(tmp_path: Path, files: dict[str, str], main: str = "main.tex") -> LoopCtx:
    for rel, txt in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel=main)


def test_docclass_subfile_stripped_to_body(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"main.tex": _MAIN, "sub.tex": _SUB})
    ok, note = subfile_docclass_strip(ctx, None, None, {"exts": [".tex"]})
    assert ok, note
    out = (tmp_path / "sub.tex").read_text(encoding="utf-8")
    assert "Sub body" in out
    assert "documentclass" not in out
    assert "usepackage" not in out
    assert "newcommand" not in out
    assert out.startswith("% fixloop:")


def test_main_file_never_touched(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"main.tex": _MAIN, "sub.tex": _SUB})
    subfile_docclass_strip(ctx, None, None, {"exts": [".tex"]})
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == _MAIN


def test_missing_end_document_keeps_tail(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": _MAIN,
            "sub.tex": "\\documentclass{standalone}\n\\begin{document}\nBody only.\n",
        },
    )
    ok, _note = subfile_docclass_strip(ctx, None, None, {"exts": [".tex"]})
    assert ok
    out = (tmp_path / "sub.tex").read_text(encoding="utf-8")
    assert out.endswith("Body only.\n")


def test_trailing_after_end_dropped(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"main.tex": _MAIN, "sub.tex": _SUB + "trailing junk\n"})
    ok, _note = subfile_docclass_strip(ctx, None, None, {"exts": [".tex"]})
    assert ok
    assert "trailing junk" not in (tmp_path / "sub.tex").read_text(encoding="utf-8")


def test_commented_docclass_not_live(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {"main.tex": _MAIN, "note.tex": "% \\documentclass{article}\nplain content\n"},
    )
    ok, _note = subfile_docclass_strip(ctx, None, None, {"exts": [".tex"]})
    assert not ok
    assert (tmp_path / "note.tex").read_text(encoding="utf-8").startswith("%")


def test_plain_input_file_untouched(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {"main.tex": _MAIN, "chap.tex": "Chapter content \\cite{a}.\n"},
    )
    ok, _note = subfile_docclass_strip(ctx, None, None, {"exts": [".tex"]})
    assert not ok
    assert (tmp_path / "chap.tex").read_text(encoding="utf-8") == (
        "Chapter content \\cite{a}.\n"
    )


def test_multiple_subfiles_all_stripped(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {
            # \\input{sub} braced + bare \\input a/app 两形引用臂同测
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\n"
                "\\input{sub}\n\\input a/app\n\\end{document}\n"
            ),
            "sub.tex": _SUB,
            "a/app.tex": _SUB.replace("Sub body", "Appendix body"),
        },
    )
    ok, note = subfile_docclass_strip(ctx, None, None, {"exts": [".tex"]})
    assert ok
    assert "2 file(s)" in note
    assert "Sub body" in (tmp_path / "sub.tex").read_text(encoding="utf-8")
    assert "Appendix body" in (tmp_path / "a/app.tex").read_text(encoding="utf-8")


def test_subimport_twoarg_reference(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\n"
                "\\subimport{a}{app}\n\\end{document}\n"
            ),
            "a/app.tex": _SUB,
        },
    )
    ok, _note = subfile_docclass_strip(ctx, None, None, {"exts": [".tex"]})
    assert ok
    assert "Sub body" in (tmp_path / "a/app.tex").read_text(encoding="utf-8")


def test_unreferenced_docclass_doc_untouched(tmp_path: Path) -> None:
    # 2409.00265: 无存活 input 族引用的 docclass 持件 (独立第二文档/
    # 误判主档下的真主档) 永不进编译流 —— 剥它是纯害, 门后跳过
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": _MAIN,
            "sub.tex": _SUB,
            "Biography.tex": _SUB.replace("Sub body", "Bio body"),
        },
    )
    ok, note = subfile_docclass_strip(ctx, None, None, {"exts": [".tex"]})
    assert ok
    assert "1 file(s)" in note
    bio = (tmp_path / "Biography.tex").read_text(encoding="utf-8")
    assert "documentclass" in bio
    assert "Bio body" in bio


def test_only_unreferenced_returns_false(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"main.tex": _MAIN, "Biography.tex": _SUB})
    ok, note = subfile_docclass_strip(ctx, None, None, {"exts": [".tex"]})
    assert not ok
    assert "input-referenced" in note
    assert "documentclass" in (tmp_path / "Biography.tex").read_text(encoding="utf-8")


def test_rule_sits_between_tar_extract_and_precheck() -> None:
    ids = [r.id for r in load_ruleset().phase("precheck")]
    i_tar = ids.index("tar_blob_extract")
    i_strip = ids.index("subfile_docclass_strip")
    i_wrap = ids.index("shipped_sty_input_wrap")
    i_scan = ids.index("static_precheck")
    assert i_tar < i_strip < i_wrap < i_scan


def test_includestandalone_opts_form_counts_as_reference(tmp_path: Path) -> None:
    # B5b: \includestandalone[width=..]{sub} — [opts] 曾使 _INPUT_EXEC1_RX
    # 失配, referenced 集为空 → 子文档 preamble 毒面存活 (0812.0615 族).
    main = (
        "\\documentclass{article}\n\\usepackage{standalone}\n"
        "\\begin{document}\n"
        "\\includestandalone[width=0.9\\textwidth]{sub}\n"
        "\\end{document}\n"
    )
    ctx = _ctx(tmp_path, {"main.tex": main, "sub.tex": _SUB})
    ok, note = subfile_docclass_strip(ctx, None, None, {"exts": [".tex"]})
    assert ok, note
    out = (tmp_path / "sub.tex").read_text(encoding="utf-8")
    assert "Sub body" in out
    assert "documentclass" not in out
