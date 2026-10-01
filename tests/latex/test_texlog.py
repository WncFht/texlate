"""texlog 文件栈原语单测——消费方（logattr/engine/logparse）之外的边界直测。"""

from __future__ import annotations

from pathlib import Path

from texlate.texlog import (
    file_stack_at,
    is_project_file,
    looks_like_input_file,
    update_file_stack,
)


def _run(lines: list[str]) -> list[str | None]:
    stack: list[str | None] = []
    for ln in lines:
        update_file_stack(ln, stack)
    return stack


# ---------------------------------------------------------- missing char 字形括弧


def test_missing_char_close_paren_keeps_file_frame() -> None:
    """``Missing character: There is no ) in font`` 的字面 ``)`` 不弹真文件帧。"""
    stack = _run(
        [
            "(./main.tex",
            "Missing character: There is no ) in font nullfont!",
        ]
    )
    assert stack == ["./main.tex"]


def test_missing_char_open_paren_no_phantom() -> None:
    """字面 ``(`` 字形不留幻影帧——后续真闭括弧仍弹文件本身。"""
    popped: list[str | None] = []
    stack: list[str | None] = []
    for ln in [
        "(./main.tex",
        "Missing character: There is no ( in font nullfont!",
        ")",
    ]:
        update_file_stack(ln, stack, popped)
    assert stack == []
    assert popped == ["./main.tex"]


def test_missing_char_codepoint_parens_stay_balanced() -> None:
    """码位形态 ``(U+0029)``/``("0029)`` 括号自带配对，不被字形规则误吃。"""
    stack = _run(
        [
            "(./main.tex",
            "Missing character: There is no 字 (U+5B57) in font nullfont!",
            'Missing character: There is no 字 ("5B57) in font nullfont!',
            "Missing character: There is no (U+FFFD) in font cmr10",
        ]
    )
    assert stack == ["./main.tex"]


def test_missing_char_paren_glyph_with_codepoint() -> None:
    """字形为括弧且带码位：``no ) (U+0029)`` 只跳字形位，码位对仍平衡。"""
    stack = _run(
        [
            "(./main.tex",
            "Missing character: There is no ) (U+0029) in font nullfont!",
            "Missing character: There is no ( (U+0028) in font nullfont!",
        ]
    )
    assert stack == ["./main.tex"]


# ---------------------------------------------------------- 栈配对不变量


def test_stray_close_empty_stack() -> None:
    assert _run([")stray", "(./a.tex"]) == ["./a.tex"]


def test_unclosed_open_keeps_frame() -> None:
    assert _run(["(./main.tex", "(./sub/chap.tex", "! boom"]) == [
        "./main.tex",
        "./sub/chap.tex",
    ]


def test_paren_at_eol_is_none_placeholder() -> None:
    """行尾裸 ``(``（79 列折行）→ None 占位；下一行 ``)`` 弹掉它而非真文件。"""
    stack = _run(["(./main.tex", "(", "./wrapped.tex)"])
    assert stack == ["./main.tex"]


def test_nonfile_parens_balanced() -> None:
    assert _run(["(./main.tex", "output written on x.pdf (1 page, 3k)."]) == [
        "./main.tex"
    ]


def test_no_paren_line_is_noop() -> None:
    """无括弧行不进扫描——popped 也不被触碰。"""
    stack: list[str | None] = ["./main.tex", None]
    popped: list[str | None] = ["sentinel"]
    update_file_stack("plain text no parens", stack, popped)
    assert stack == ["./main.tex", None]
    assert popped == ["sentinel"]


def test_popped_records_pop_order() -> None:
    pops: list[str | None] = []
    stack: list[str | None] = []
    update_file_stack("(./a.tex(./b.sty)x)y)", stack, pops)
    assert stack == []
    assert pops == ["./b.sty", "./a.tex"]


def test_quoted_name_falls_to_none_placeholder() -> None:
    """带空格路径 TeX 打引号——token 截在空格处落 None 占位，配对不破。"""
    stack = _run(["(./main.tex", '(./"sub dir/chap.tex"', "x)"])
    assert stack == ["./main.tex"]


def test_paren_inside_filename_pairs_off() -> None:
    """文件名内嵌 ``(``（``a(b).tex`` 稀有形态）：内层 ``(b)`` 自配对、
    外层 ``(./sub/a`` 落 None 占位——文件不可见但配对不破，外层 ``)``
    不错弹真文件帧。"""
    stack = _run(["(./main.tex", "(./sub/a(b).tex content)"])
    assert stack == ["./main.tex"]


def test_two_opens_one_line() -> None:
    """同行双开：``(./a.tex (./b.tex)``——b 闭合后 a 仍在栈。"""
    assert _run(["(./a.tex (./b.tex) tail"]) == ["./a.tex"]


def test_double_open_inner_token_is_file() -> None:
    """``((x.tex``——外层 ``(`` 落 None、内层 ``(`` 的文件 token 正常入栈。"""
    stack: list[str | None] = []
    popped: list[str | None] = []
    update_file_stack("((x.tex", stack, popped)
    assert stack == [None, "x.tex"]


def test_deep_unclosed_nesting() -> None:
    """深层未闭合嵌套线性增长——无上限保护也不需要（log 有界）。"""
    depth = 2000
    stack = _run([f"(./f{i}.tex" for i in range(depth)])
    assert len(stack) == depth
    assert stack[-1] == f"./f{depth - 1}.tex"


def test_missing_char_glyph_before_non_space_not_skipped() -> None:
    """字形 ``)`` 后紧跟非空格/非 ``(`` 字符不在豁免 lookahead 内——
    仍按配对符处理（真实 TeX 输出字形后恒跟 `` in font``，此行为假想形留档）。"""
    stack = _run(
        [
            "(./main.tex",
            "Missing character: There is no )x in font nullfont!",
        ]
    )
    assert stack == []


def test_file_stack_at_replays_before_stop() -> None:
    lines = ["(./main.tex", "(./sub/a.tex", ")close", "(./b.tex"]
    assert file_stack_at(lines, 3) == ["./main.tex"]
    assert file_stack_at(lines, 4) == ["./main.tex", "./b.tex"]


def test_file_stack_at_popped_captures_runaway() -> None:
    """runaway 形态：stop 行前 ``)`` 已弹真肇事件——popped 全程史找回（#78）。"""
    lines = [
        "(./main.tex",
        "(./sub/bad.tex",
        "Runaway argument? )",
        "! File ended while scanning use of \\foo.",
    ]
    popped: list[str | None] = []
    assert file_stack_at(lines, 3, popped) == ["./main.tex"]
    assert popped == ["./sub/bad.tex"]


def test_file_stack_at_popped_keeps_none_frames() -> None:
    """原语层透传 ``None`` 配对帧（滤除是消费端职责）。"""
    lines = ["(./main.tex", "(draft", "x ) y )", "! err"]
    popped: list[str | None] = []
    assert file_stack_at(lines, 3, popped) == []
    assert popped == [None, "./main.tex"]


def test_file_stack_at_popped_default_untouched() -> None:
    """不传 popped → 行为与旧签名一致（out-param 纯增量）。"""
    lines = ["(./a.tex", ")x", "(./b.tex"]
    assert file_stack_at(lines, 3) == ["./b.tex"]


# ---------------------------------------------------------- is_project_file 直测


def test_is_project_file_none_is_project() -> None:
    assert is_project_file(None, Path("/w"))


def test_is_project_file_relative_escape_still_project(tmp_path: Path) -> None:
    """``../`` 相对 token 按 cwd 相对语义归工程（用户写的相对引用）。"""
    assert is_project_file("../outside.tex", tmp_path)


def test_is_project_file_absolute_escape_via_dotdot(tmp_path: Path) -> None:
    """绝对路径带 ``..`` 解析出 root → 系统侧（resolve 归一化生效）。"""
    assert not is_project_file(str(tmp_path / ".." / "x.tex"), tmp_path)


def test_is_project_file_bare_name_with_root(tmp_path: Path) -> None:
    """裸名（tectonic bundle 日志形态）：``root`` 内存在 → 工程，缺席 → 系统。"""
    (tmp_path / "main.tex").write_text("x", encoding="utf-8")
    assert is_project_file("main.tex", tmp_path)
    assert not is_project_file("missing.sty", tmp_path)


def test_is_project_file_usertree_inside_root_is_sys(tmp_path: Path) -> None:
    """``root/_texmf`` usertree 件在 root 之内仍是系统语义——texmf 段标记先于
    root 前缀判（fixloop usertree 落 ``wdir/_texmf`` 是承重场景）。"""
    f = tmp_path / "_texmf" / "x.sty"
    f.parent.mkdir()
    f.write_text("x", encoding="utf-8")
    assert not is_project_file(str(f), tmp_path)


def test_is_project_file_tectonic_case_sensitive() -> None:
    """``/Tectonic/`` 大写缓存目录 → 系统；小写 ``tectonic/`` 是 fixloop 编译
    工作段名（``wdir/tectonic``），root 缺席时保守归工程不误吃。"""
    assert not is_project_file("/home/u/.cache/Tectonic/bundle/x.sty")
    assert is_project_file("/work/tectonic/x.tex")


def test_is_project_file_nul_token_conservative(tmp_path: Path) -> None:
    """含 NUL 的 token 不可能是真实路径（``resolve`` 会炸 ValueError）——
    保守归工程，不掉红线也不炸归因面。"""
    assert is_project_file("/abs/a\x00b.tex", tmp_path)
    assert is_project_file("a\x00b.tex", tmp_path)


def test_looks_like_input_file_edge() -> None:
    assert looks_like_input_file("./a.TEX")
    assert not looks_like_input_file("./a.")
    assert not looks_like_input_file("nodotfile")
    assert not looks_like_input_file("./dir/")


def test_looks_like_input_file_non_tex_exts() -> None:
    """白名单外扩展名按形状收——graphic/``.lbx``/pgf 内部件具名入栈。"""
    assert looks_like_input_file("./fig.eps")
    assert looks_like_input_file("./x.lbx")
    assert looks_like_input_file("./pgf.code")
    # 形状拒收：数字开头假扩展名（尺寸/版本号转储）、逗号基名（坐标对）。
    assert not looks_like_input_file("52.00102pt")
    assert not looks_like_input_file("v2.0")
    assert not looks_like_input_file("x,y.epsz")
