r"""``texlate.latex.prose`` 散文门 + ``e2e._translate_tree`` 接线。

support 文件（bundled pstricks/epsf/tikzlibrary、宏定义件、gnuplot 转储）
不进翻译集：``.code.tex`` 硬抛 + ``file_has_prose`` 判据双闸，落
``support_files`` 记名、原文逐字节保留（``support_skipped`` 计数）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate import e2e
from texlate.latex.model import Chunk
from texlate.latex.prose import file_has_prose, is_prose
from texlate.xlat.pipeline import MOCK_ZH, MockTranslator

if TYPE_CHECKING:
    from pathlib import Path

#: 最小可解析工程（对齐 test_e2e 惯例：两段散文保证出 chunk）。
#: 刻意不直接用 conftest.MINI_TEX / test_e2e._MAIN——本副本去掉了
#: ``\section{Intro}`` 行：``section`` ctx 走 PROSE_CONTEXTS 结构救回臂
#: （零功能词也算散文），留着它 main.tex 的 ``file_has_prose`` 判定就不
#: 依赖功能词臂，功能词门回归时本文件用例照样全绿——恰是本文件要钉的面。
_MAIN = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "This is a longer paragraph of English text that should definitely be\n"
    "segmented into at least one chunk for translation purposes.\n"
    "\n"
    "And a second paragraph here.\n"
    "\\end{document}\n"
)


def _project(root: Path) -> Path:
    """test_e2e._project 的裁剪版——本文件无用例覆盖 ``main`` 参数，故省。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.tex").write_text(_MAIN, encoding="utf-8")
    return root


def _chunk(content: str, context: str = "para") -> Chunk:
    return Chunk(id=0, content=content, context=context)


# ---------------------------------------------------------------- is_prose


def test_is_prose_struct_context_rescue() -> None:
    """零功能词短标题靠 STRUCT ctx 救回——缺这臂短 caption 全灭。"""
    assert is_prose(_chunk("TRIS antennas", "tablecaption")) is True
    assert is_prose(_chunk("XYZ", "section")) is True


def test_is_prose_struct_context_aliases() -> None:
    """``subsect``（ptptex 旧式）/``abst`` 在 CHUNK_ARG_NAMES 出 ctx——
    PROSE_CONTEXTS 缺名即召回缺口（S5）。"""
    assert is_prose(_chunk("XY", "subsect")) is True
    assert is_prose(_chunk("K", "abst")) is True


def test_is_prose_funcword_gate() -> None:
    """≥3 distinct 功能词 → 散文（大小写不敏感）。"""
    assert is_prose(_chunk("The results show that this method works well")) is True
    assert is_prose(_chunk("THE RESULTS SHOW THAT THIS WORKS")) is True


def test_is_prose_funcword_threshold() -> None:
    """<3 distinct 功能词不算散文——重复同一词只计一次。"""
    assert is_prose(_chunk("this and that")) is False
    assert is_prose(_chunk("the the the the")) is False


def test_is_prose_machinery_dropped() -> None:
    """PS/pstricks 机制块：def/set/moveto 类内容名词不算功能词。"""
    assert is_prose(_chunk(r"\psunit 1cm \pstVerb{2 copy}")) is False
    assert is_prose(_chunk("x neg y moveto def set")) is False


def test_is_prose_postscript_operators_excluded() -> None:
    """``and|not|or|if|for`` 是 PS 算子不入表——普查唯一实测泄漏源的回归钉。"""
    assert is_prose(_chunk("0 1 10 { dup mul } for")) is False
    assert is_prose(_chunk("and not or if for loop repeat")) is False


def test_is_prose_expl3_dropped() -> None:
    r"""expl3 宏体：``\keys_define``/``tl_set`` 切开仍零功能词。"""
    assert is_prose(_chunk(r"\keys_define:nn { foo } { left tl_set:N }")) is False


def test_is_prose_placeholder_strip() -> None:
    """``[[X_n]]`` token 先剥——marker 内部不计词。"""
    assert is_prose(_chunk("[[MATH_1]] [[REF_2]]")) is False
    assert is_prose(_chunk("[[CHUNK_0]]")) is False


# ---------------------------------------------------------------- file_has_prose


def test_file_has_prose_aggregates() -> None:
    """任一块是散文即送译；空 chunks → False。"""
    assert file_has_prose([]) is False
    assert file_has_prose([_chunk(r"\def\foo{bar}")]) is False
    assert file_has_prose([_chunk("x"), _chunk("short", "caption")]) is True


# ---------------------------------------------------------------- e2e 接线


def test_translate_tree_code_tex_skipped(tmp_path: Path) -> None:
    """``*.code.tex`` 硬抛：chunks 从未到 translator + 记名 support。"""
    _project(tmp_path)
    sentinel = "ZZCODESENTINEL"
    body = f"\\pgfkeys{{/{sentinel}/.code={{moveto def set}}}}\n"
    (tmp_path / "tikzlibraryzz.code.tex").write_text(body, encoding="utf-8")
    tr = MockTranslator()
    stats = e2e.translate_tree(tmp_path, translator=tr)

    assert stats["support_files"] == ["tikzlibraryzz.code.tex"]
    assert stats["support_skipped"] == 1
    assert all(sentinel not in str(c["user"]) for c in tr.calls)
    assert (tmp_path / "tikzlibraryzz.code.tex").read_text(encoding="utf-8") == body
    assert MOCK_ZH in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_translate_tree_support_file_dropped(tmp_path: Path) -> None:
    """无散文机制文件：落 ``support_files`` + 原文逐字节保留。"""
    _project(tmp_path)
    machinery = "\\psset{unit=1cm}\npstverb moveto neg def set newpath lineto stroke\n"
    (tmp_path / "pssupport.tex").write_text(machinery, encoding="utf-8")
    stats = e2e.translate_tree(tmp_path)

    assert stats["support_files"] == ["pssupport.tex"]
    assert stats["support_skipped"] == 1
    assert (tmp_path / "pssupport.tex").read_text(encoding="utf-8") == machinery
    assert stats["files"] == 1  # 只有 main.tex 改写
    assert MOCK_ZH in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_translate_tree_real_content_still_translated(tmp_path: Path) -> None:
    """内容文件照常翻译——散文门不误伤正文文件。"""
    _project(tmp_path)
    # ``body.tex`` 须可达——闭包裁剪后未被 ``\input`` 的散文件剔
    # unreachable→support 不译（本用例语义 = 可达正文件过散文门送译）。
    (tmp_path / "main.tex").write_text(
        _MAIN.replace("\\end{document}", "\\input{body}\n\\end{document}"),
        encoding="utf-8",
    )
    (tmp_path / "body.tex").write_text(
        "The results of this paper show that the proposed method is "
        "effective and that the theory holds.\n",
        encoding="utf-8",
    )
    stats = e2e.translate_tree(tmp_path)

    assert stats["support_files"] == []
    assert stats["support_skipped"] == 0
    assert stats["files"] == 2  # noqa: PLR2004 -- main + body 都改写
    assert MOCK_ZH in (tmp_path / "body.tex").read_text(encoding="utf-8")


def test_translate_tree_support_vs_fault_partition(tmp_path: Path) -> None:
    """support（有意跳过）与 fault（解析崩）分流记名——两表不混。"""
    _project(tmp_path)
    (tmp_path / "machinery.tex").write_text("\\psset{unit=1cm}\n", encoding="utf-8")
    stats = e2e.translate_tree(tmp_path)

    assert stats["support_files"] == ["machinery.tex"]
    assert stats["fault_files"] == []


def test_translate_tree_dotfile_silently_skipped(tmp_path: Path) -> None:
    """``.foo.tex`` 隐文件静默跳过——不进 support/fault 记名（worker 同）。"""
    _project(tmp_path)
    (tmp_path / ".hidden.tex").write_text(
        "This hidden file has prose that would otherwise be sent.\n",
        encoding="utf-8",
    )
    stats = e2e.translate_tree(tmp_path)

    assert stats["support_files"] == []
    assert stats["fault_files"] == []
    assert stats["files"] == 1
    assert (tmp_path / ".hidden.tex").read_text(encoding="utf-8").startswith("This")


def test_translate_tree_nonregular_tex_skipped(tmp_path: Path) -> None:
    """``foo.tex`` 目录名伪装：is_file 闸滤掉，不进 fault_files。"""
    _project(tmp_path)
    (tmp_path / "dirlike.tex").mkdir()
    stats = e2e.translate_tree(tmp_path)

    assert stats["fault_files"] == []
    assert stats["files"] == 1
