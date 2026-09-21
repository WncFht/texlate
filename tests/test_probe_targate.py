r"""probe.py 的 tar 伪装 .tex 闸（``_tar_disguised`` 同 ``normalize._tex_sources`` 字节面判定）。

``test_inject_targate.py`` 的 census 侧姊妹闸：``_scan_file`` 对 main 与
``\input`` 闭包内每件 ``read_bytes`` → ``decode_tex``（永不抛，latin-1
兜底）——tar 成员文本里的 ``\documentclass``/``\usepackage`` 会被当真声明
收进 census（deps/missing/tl_packages/flags 全污染）。本闸逐点验证：tar
main/tar ``\input`` 目标的成员声明不入账、文件本身照常登记、note 记名；
真 .tex 对照臂不误伤；文本含 ``ustar`` 字样不假阳（chksum 轻校验挡）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from _tarkit import _tar_blob
from conftest import _write

from texlate.compile.ctan import TlpdbIndex
from texlate.compile.probe import target_probe

if TYPE_CHECKING:
    from pathlib import Path

_INDEX = TlpdbIndex(
    {
        "amsmath.sty": ["amsmath"],
        "article.cls": ["latex"],
        "minted.sty": ["minted"],
    }
)

#: tar 成员文本——memoir.cls/totallybogus.sty 两空（若被解码必落 missing）、
#: minted 命中索引且产 ``-shell-escape``：一件覆盖 deps/missing/flags 三面。
_MEMBER_TEX = (
    "\\documentclass{memoir}\n"
    "\\usepackage{amsmath,minted,totallybogus}\n"
    "\\begin{document}\nmember body\n\\end{document}\n"
)


def test_tar_main_members_not_scanned(tmp_path: Path) -> None:
    """唯一 .tex 是 tar：main 照常进 inputs，成员声明全部不入 census。"""
    (tmp_path / "main.tex").write_bytes(
        _tar_blob(("inner/doc.tex", _MEMBER_TEX.encode()))
    )
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert rep.inputs == ["main.tex"]
    assert rep.deps == []
    assert rep.missing == []
    assert rep.tl_packages == []
    assert rep.flags == []
    assert rep.prefer_engine is None
    assert any("tar" in n and "main.tex" in n for n in rep.notes)


def test_tar_input_members_not_scanned(tmp_path: Path) -> None:
    r"""``\input{chap}`` 命中 tar 伪装件：dep 按真实文件登 local + 入 inputs，
    成员声明不污染 deps/missing/flags。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\input{chap}\n\\begin{document}x\\end{document}\n",
    )
    (tmp_path / "chap.tex").write_bytes(
        _tar_blob(("inner/doc.tex", _MEMBER_TEX.encode()))
    )
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    by_name = {d.fname: d for d in rep.deps}
    assert by_name["chap.tex"].resolved == "local"
    assert rep.inputs == ["main.tex", "chap.tex"]
    # 成员 memoir.cls/amsmath.sty/minted.sty/totallybogus.sty 一个不入账
    assert "amsmath.sty" not in by_name
    assert "minted.sty" not in by_name
    assert rep.missing == []
    assert rep.tl_packages == ["latex"]  # 仅 main 自身 \documentclass{article}
    assert "-shell-escape" not in rep.flags
    assert any("tar" in n and "chap.tex" in n for n in rep.notes)


def test_real_input_still_scanned(tmp_path: Path) -> None:
    r"""对照臂：真 .tex ``\input`` 目标照常供声明——闸不误伤正常闭包。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\input{chap}\n\\begin{document}x\\end{document}\n",
    )
    _write(tmp_path, "chap.tex", "\\usepackage{amsmath}\n内容\n")
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    by_name = {d.fname: d for d in rep.deps}
    assert by_name["amsmath.sty"].resolved == "tl_pkg"
    assert by_name["amsmath.sty"].declared_in == "chap.tex"
    assert rep.inputs == ["main.tex", "chap.tex"]


def test_ustar_text_no_false_positive(tmp_path: Path) -> None:
    """正文含 ``ustar`` 字样（恰落魔数偏移 257）：chksum 校验挡假阳。"""
    head = b"\\documentclass{article}\n"
    blob = (
        head
        + b"x" * (257 - len(head))
        + b"ustar\n\\usepackage{amsmath}\n\\begin{document}\nx\n\\end{document}\n"
    )
    assert blob[257:262] == b"ustar"  # 魔数落正位——纯文本照过闸
    (tmp_path / "main.tex").write_bytes(blob)
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    by_name = {d.fname: d for d in rep.deps}
    assert by_name["amsmath.sty"].resolved == "tl_pkg"
    assert not any("tar" in n for n in rep.notes)
