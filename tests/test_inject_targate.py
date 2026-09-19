r"""inject.py 的 tar 伪装 .tex 闸（``_tar_disguised`` 复用 ``normalize.py`` 字节面判定）。

``test_bininject_gate.py`` 的下游姊妹闸：normalize 侧挡支持件手术，inject 侧
挡「tar 被当文本 tex 消费」——``decode_tex`` 永不抛（latin-1 兜底），tar
成员文本里的 ``\documentclass``/``\begin{document}``/``figure`` 环境会让
伪装件被取为主文件/供进 ``\input`` 闭包/吃到 FLOAT_SIZING 拼接，写回即
腐蚀 blob。本闸逐点验证：伪装件不入 main 候选、不供闭包判据、不被拼接；
文本里出现 ``ustar`` 字样不假阳（chksum 轻校验挡）。
"""

from __future__ import annotations

import io
import tarfile
from typing import TYPE_CHECKING

import pytest

from texlate.compile.inject import (
    FLOAT_SIZING,
    InjectRejectError,
    classify_no_main,
    find_main_tex,
    inject_float_sizing,
    prepare_chinese,
)

if TYPE_CHECKING:
    from pathlib import Path

_DOC = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"


def _tar_blob(*members: tuple[str, bytes]) -> bytes:
    """ustar blob——成员文本默认含 dc/bd 文档形态（latin-1 解出即假阳面）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, data in members or [
            ("inner/doc.tex", _DOC.encode()),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_tar_tex_not_main_candidate(tmp_path: Path) -> None:
    """tar 伪装 .tex 与真稿同树：检出真稿，伪装件逐字节不动。"""
    blob = _tar_blob()
    (tmp_path / "bundle.tex").write_bytes(blob)
    (tmp_path / "paper.tex").write_text(_DOC, encoding="utf-8")
    assert find_main_tex(tmp_path) == tmp_path / "paper.tex"
    assert (tmp_path / "bundle.tex").read_bytes() == blob


def test_tar_tex_only_tree_no_main(tmp_path: Path) -> None:
    """唯一 .tex 是 tar：无 main 可取，归因 garbage（成员 bd 不算数）。"""
    (tmp_path / "main.tex").write_bytes(_tar_blob())
    assert find_main_tex(tmp_path) is None
    assert classify_no_main(tmp_path) == "garbage"


def test_tar_input_not_in_closure(tmp_path: Path) -> None:
    """编排壳 ``\\input`` 到 tar：成员 bd 不供闭包——壳判不出 main。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\input{chap}\n", encoding="utf-8"
    )
    (tmp_path / "chap.tex").write_bytes(_tar_blob())
    assert find_main_tex(tmp_path) is None


def test_real_input_supplies_bd(tmp_path: Path) -> None:
    """对照臂：真 .tex 成员照常供 bd——闸不误伤正常 ``\\input`` 闭包。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\input{chap}\n", encoding="utf-8"
    )
    (tmp_path / "chap.tex").write_text(
        "\\begin{document}\nbody\n\\end{document}\n", encoding="utf-8"
    )
    assert find_main_tex(tmp_path) == tmp_path / "main.tex"


def test_inject_float_sizing_skips_tar(tmp_path: Path) -> None:
    """FLOAT_SIZING 只缝真稿：含 figure 成员的 tar 不吃拼接、逐字节原样。"""
    blob = _tar_blob(
        (
            "fig.tex",
            (
                b"\\documentclass{article}\n\\begin{document}\n"
                b"\\begin{figure}x\\end{figure}\n\\end{document}\n"
            ),
        ),
    )
    (tmp_path / "figs.tex").write_bytes(blob)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{figure}x\\end{figure}\n\\end{document}\n",
        encoding="utf-8",
    )
    assert inject_float_sizing(tmp_path) == 1
    assert (tmp_path / "figs.tex").read_bytes() == blob
    assert FLOAT_SIZING in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_prepare_chinese_rejects_tar_main(tmp_path: Path) -> None:
    """绕开检出直传 tar main：inject 层兜底拒绝且不写回。"""
    blob = _tar_blob()
    (tmp_path / "main.tex").write_bytes(blob)
    with pytest.raises(InjectRejectError) as excinfo:
        prepare_chinese(tmp_path, "main.tex")
    assert excinfo.value.reason == "nontex"
    assert (tmp_path / "main.tex").read_bytes() == blob


def test_ustar_text_no_false_positive(tmp_path: Path) -> None:
    """正文含 ``ustar`` 字样（恰落魔数偏移 257）：chksum 校验挡假阳。"""
    head = b"\\documentclass{article}\n"
    blob = (
        head
        + b"x" * (257 - len(head))
        + b"ustar\n\\begin{document}\nx\n\\end{document}\n"
    )
    assert blob[257:262] == b"ustar"  # 魔数落正位——纯文本照过闸
    (tmp_path / "main.tex").write_bytes(blob)
    assert find_main_tex(tmp_path) == tmp_path / "main.tex"
    info = prepare_chinese(tmp_path, "main.tex")
    assert info["status"] == "injected"


def test_utf8_and_gbk_tex_unaffected(tmp_path: Path) -> None:
    """普通 UTF-8 与 GBK .tex：检出与注入语义不变。"""
    utf = tmp_path / "utf" / "main.tex"
    utf.parent.mkdir()
    utf.write_text(_DOC, encoding="utf-8")
    assert find_main_tex(tmp_path / "utf") == utf
    assert prepare_chinese(tmp_path / "utf", "main.tex")["status"] == "injected"

    gbk = tmp_path / "gbk" / "main.tex"
    gbk.parent.mkdir()
    gbk.write_bytes(_DOC.replace("x\n", "汉\n").encode("gbk"))
    assert find_main_tex(tmp_path / "gbk") == gbk
    info = prepare_chinese(tmp_path / "gbk", "main.tex")
    assert info["status"] == "injected"
    assert "\\usepackage[fontset=fandol,UTF8" in gbk.read_text(encoding="utf-8")
