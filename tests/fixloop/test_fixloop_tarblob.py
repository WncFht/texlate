r"""tar 伪装件检测/补缺/退役 —— ``extract_tar_blobs`` builtin 直驱 (0707.0382 型)。

``.sty``/``.cls`` 名下 POSIX tar: ustar 魔数扫窗检测 (splice/zh prologue
前置注入把魔数推离 257 —— 定点探测漏检, 文本 ``ustar`` 字样不误中),
成员补缺落地 (撞名真件不覆/``..``/绝对路径成员拒), blob 改名
``.tarblob`` 退役——退役判据是魔数本身, 与补缺落地数解耦。
"""

import io
import tarfile
from pathlib import Path

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop.engine import LoopCtx


# ---------------------------------------------------------------- tar 伪装件
def _tar_bytes(members: dict[str, bytes]) -> bytes:
    """POSIX tar 字节 (ustar 格式——``ustar`` 魔数 @257 必现)。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _write_tar(path: Path, members: dict[str, bytes]) -> None:
    path.write_bytes(_tar_bytes(members))


def _extract(wdir: Path) -> tuple[bool, str]:
    ctx = LoopCtx(wdir=wdir, engine_name="xelatex")
    return builtins.TRANSFORM_FNS["extract_tar_blobs"](ctx, None, None, {})


def test_tar_blob_extracts_members_and_retires(tmp_path: Path) -> None:
    r"""0707.0382/0104007 型: ``.sty`` 名 tar → 成员补缺 + blob 改名退役。"""
    _write_tar(
        tmp_path / "AMSbsy.sty",
        {"./iaus.cls": b"\\ProvidesClass{iaus}\n", "figs/f1.eps": b"%!PS\n"},
    )
    ok, note = _extract(tmp_path)
    assert ok, note
    assert (tmp_path / "iaus.cls").read_bytes() == b"\\ProvidesClass{iaus}\n"
    assert (tmp_path / "figs" / "f1.eps").is_file()
    assert not (tmp_path / "AMSbsy.sty").exists()
    assert (tmp_path / "AMSbsy.sty.tarblob").is_file()  # 退役留证，移出解析路径


def test_tar_blob_no_clobber_keeps_real_files(tmp_path: Path) -> None:
    """成员名撞真件 → 真件不动 (tar 只补缺)。"""
    (tmp_path / "aipproc.sty").write_bytes(b"\\ProvidesPackage{real}\n")
    _write_tar(
        tmp_path / "aipproc.cls",
        {"./aipproc.sty": b"% stale dup\n", "./symposium.tex": b"\\bye\n"},
    )
    ok, _ = _extract(tmp_path)
    assert ok
    assert (tmp_path / "aipproc.sty").read_bytes() == b"\\ProvidesPackage{real}\n"
    assert (tmp_path / "symposium.tex").is_file()  # 缺的补上


def test_tar_blob_unsafe_members_rejected(tmp_path: Path) -> None:
    """``..``/绝对路径/非常规成员全拒——只合法件落地。"""
    _write_tar(
        tmp_path / "evil.sty",
        {"../escape.tex": b"x", "/abs.tex": b"y", "ok/inner.sty": b"z\n"},
    )
    ok, _ = _extract(tmp_path)
    assert ok  # ok/inner.sty 一件落地即抽中
    assert not (tmp_path.parent / "escape.tex").exists()
    assert not Path("/abs.tex").exists()
    assert (tmp_path / "ok" / "inner.sty").is_file()


def test_tar_blob_ignores_real_files(tmp_path: Path) -> None:
    """健康 .sty/.tex 不误判。"""
    (tmp_path / "real.sty").write_bytes(b"\\ProvidesPackage{real}\n")
    (tmp_path / "main.tex").write_bytes(b"\\documentclass{article}\n")
    ok, _ = _extract(tmp_path)
    assert not ok
    assert (tmp_path / "real.sty").is_file()
    assert not (tmp_path / "real.sty.tarblob").exists()


def test_tar_blob_retires_when_all_members_exist(tmp_path: Path) -> None:
    """0707.0382 实案：语料已带全部成员 → 0 新成员，blob 仍须退役。

    tar 归档在 ``.sty``/``.cls`` 名下绝不是合法 TeX——退役判据是
    tar 魔数本身，与补缺落地数解耦 (旧逻辑 0 成员原样放回 → blob
    残留毒化编译)。
    """
    (tmp_path / "iaus.cls").write_bytes(b"\\ProvidesClass{iaus}\n")
    _write_tar(tmp_path / "AMSbsy.sty", {"./iaus.cls": b"% stale dup\n"})
    ok, note = _extract(tmp_path)
    assert ok, note
    assert "0 members" in note
    assert not (tmp_path / "AMSbsy.sty").exists()
    assert (tmp_path / "AMSbsy.sty.tarblob").is_file()
    assert (tmp_path / "iaus.cls").read_bytes() == b"\\ProvidesClass{iaus}\n"


def test_tar_blob_detects_prologue_displaced_magic(tmp_path: Path) -> None:
    """0707.0382 实案二阶：我方 prologue 前置注入把魔数推离 257 → 扫窗检测。

    splice/zh 构建对 ``.sty`` 一律前置 ``\\PassOptionsToPackage`` 注入块
    (~600B), ``ustar`` 落 ~偏移 870——定点 257 探测漏检，blob 原地毒化。
    扫窗检出后从头起点切片抽取，成员照常补缺，blob 退役。
    """
    payload = b"\\ProvidesPackage{missing}\n"
    prologue = b"\\PassOptionsToPackage{no-math}{fontspec}\n% injected\n"
    (tmp_path / "AMSbsy.sty").write_bytes(
        prologue + _tar_bytes({"./missing.sty": payload})
    )
    ok, note = _extract(tmp_path)
    assert ok, note
    assert "1 members" in note
    assert (tmp_path / "missing.sty").read_bytes() == payload
    assert not (tmp_path / "AMSbsy.sty").exists()
    assert (tmp_path / "AMSbsy.sty.tarblob").is_file()


def test_tar_blob_ustar_word_in_text_not_false_positive(tmp_path: Path) -> None:
    """文本/注释里的 ``ustar`` 字样不误中——回推 257 处 name 字段须非 NUL。"""
    (tmp_path / "doc.tex").write_bytes(
        b"\\documentclass{article}\n% this file mentions ustar format\n"
    )
    ok, _ = _extract(tmp_path)
    assert not ok
    assert (tmp_path / "doc.tex").is_file()
