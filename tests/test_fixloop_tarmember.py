"""tar 伪装件成员补写期待文件名槽位回归 (tarmember lane, shipclscen census)。

bug 机制: 旧序先 ``_extract_members`` 后 ``rename``——tar blob 全程占着
自己的文件名, 与槽位同名的成员被 no-clobber ``dest.exists()`` 永远跳过,
改名 ``*.tarblob`` 后期待文件名彻底缺席 → ``\\documentclass``/``\\input``
落空 → missing_file→stub 或 Missing ``\\begin{document}``。

修复 = **先改名再抽**: blob 让出槽位后, basename 命中槽位的成员 (任意
深度) 或与槽位同 stem 的 ``.sty`` 兄弟件 (槽位限 ``.cls``——2.09 时代
class 本体即以 .sty 发行) 补写回期待路径。实案: astro-ph/0104007
``aipproc.cls`` tar 内含 ``aipproc.sty`` (``\\documentstyle{aipproc}``
compat 读 ``aipproc.cls``); 0707.0382 ``AMSbsy.sty`` tar 无同名成员
→ 不写不错位, texlive 真件兜 ``\\usepackage{AMSbsy}``。
"""

import io
import tarfile
from pathlib import Path

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop.engine import LoopCtx


def _write_tar(path: Path, members: dict[str, bytes]) -> None:
    """POSIX tar 写出 (ustar 格式——``ustar`` 魔数 @257 必现)。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    path.write_bytes(buf.getvalue())


def _extract(wdir: Path) -> tuple[bool, str]:
    ctx = LoopCtx(wdir=wdir, engine_name="xelatex")
    return builtins.TRANSFORM_FNS["extract_tar_blobs"](ctx, None, None, {})


# ------------------------------------------------------------ 同名成员 → 槽位
def test_same_name_member_lands_at_expected(tmp_path: Path) -> None:
    """核心回归: tar ``x.cls`` 含成员 ``x.cls`` → 补写 ``x.cls``。

    旧序: 成员 dest==blob 本体 ``exists()`` → 跳过; 改名后 ``x.cls``
    彻底缺席。新序先改名让位, 成员自然落地即槽位。
    """
    payload = b"\\ProvidesClass{x}\n"
    _write_tar(tmp_path / "x.cls", {"./x.cls": payload, "./x-fig.eps": b"%!PS\n"})
    ok, note = _extract(tmp_path)
    assert ok, note
    assert (tmp_path / "x.cls").read_bytes() == payload
    assert (tmp_path / "x.cls.tarblob").is_file()
    assert (tmp_path / "x-fig.eps").is_file()


def test_subdir_basename_member_writes_expected(tmp_path: Path) -> None:
    """成员在子目录但 basename 命中槽位 → 自然落地 + 槽位补写双落。"""
    payload = b"\\ProvidesPackage{x}\n"
    _write_tar(tmp_path / "x.sty", {"./pkg/x.sty": payload})
    ok, note = _extract(tmp_path)
    assert ok, note
    assert (tmp_path / "pkg" / "x.sty").read_bytes() == payload
    assert (tmp_path / "x.sty").read_bytes() == payload  # 槽位同补
    assert (tmp_path / "x.sty.tarblob").is_file()


# ---------------------------------------------------------- .sty 兄弟 → .cls
def test_sty_sibling_fills_cls_slot(tmp_path: Path) -> None:
    """aipproc 实案: tar ``aipproc.cls`` 无同名成员, 含 ``aipproc.sty``
    → stem 兄弟补写 ``aipproc.cls`` (2.09 本体即 .sty 发行)。

    盘上已有真 ``aipproc.sty`` (语料常自带全部成员): 自然落地 no-clobber
    不碰, 槽位补写取 **成员字节** (自洽不依赖盘件内容)。
    """
    member = b"% real aipproc impl (member)\n"
    (tmp_path / "aipproc.sty").write_bytes(b"% preexisting real file\n")
    _write_tar(
        tmp_path / "aipproc.cls",
        {"./aipproc.sty": member, "./symposium.tex": b"\\bye\n"},
    )
    ok, note = _extract(tmp_path)
    assert ok, note
    assert (tmp_path / "aipproc.sty").read_bytes() == b"% preexisting real file\n"
    assert (tmp_path / "aipproc.cls").read_bytes() == member
    assert (tmp_path / "aipproc.cls.tarblob").is_file()


def test_exact_member_beats_sty_sibling(tmp_path: Path) -> None:
    """同名成员与 stem 兄弟并存 → 同名精确件赢槽位。"""
    cls_payload = b"\\ProvidesClass{x} % real cls\n"
    _write_tar(
        tmp_path / "x.cls",
        {"./x.sty": b"% sty impl\n", "./x.cls": cls_payload},
    )
    ok, note = _extract(tmp_path)
    assert ok, note
    assert (tmp_path / "x.cls").read_bytes() == cls_payload
    assert (tmp_path / "x.sty").read_bytes() == b"% sty impl\n"


# --------------------------------------------------------------- 安全/闸侧
def test_no_matching_member_expected_absent(tmp_path: Path) -> None:
    """0707.0382 反毒化: tar ``AMSbsy.sty`` 无 ``AMSbsy.*`` 成员 →
    槽位留空给 texlive 真件, 绝不拿错名成员 (``AMSfonts.sty``) 冒写。"""
    _write_tar(
        tmp_path / "AMSbsy.sty",
        {
            "./AMSfonts.sty": b"\\ProvidesPackage{AMSfonts}\n",
            "./iaus.cls": b"\\ProvidesClass{iaus}\n",
        },
    )
    ok, note = _extract(tmp_path)
    assert ok, note
    assert not (tmp_path / "AMSbsy.sty").exists()  # 槽位缺席→texlive 兜
    assert (tmp_path / "AMSbsy.sty.tarblob").is_file()
    assert (tmp_path / "AMSfonts.sty").is_file()
    assert (tmp_path / "iaus.cls").is_file()


def test_cls_member_not_written_to_sty_slot(tmp_path: Path) -> None:
    """反向不开: tar ``foo.sty`` 含 ``foo.cls`` → ``foo.cls`` 自然落地,
    不冒写 ``foo.sty`` (class 件不是 package 实现)。"""
    _write_tar(tmp_path / "foo.sty", {"./foo.cls": b"\\ProvidesClass{foo}\n"})
    ok, note = _extract(tmp_path)
    assert ok, note
    assert (tmp_path / "foo.cls").read_bytes() == b"\\ProvidesClass{foo}\n"
    assert not (tmp_path / "foo.sty").exists()
    assert (tmp_path / "foo.sty.tarblob").is_file()


def test_traversal_member_rejected_sibling_still_fills(tmp_path: Path) -> None:
    """``../evil.cls`` 名卫拒——basename 命中也先过名卫; 合法兄弟件照补。"""
    payload = b"% legit impl\n"
    _write_tar(
        tmp_path / "evil.cls",
        {"../evil.cls": b"escape", "./evil.sty": payload},
    )
    ok, note = _extract(tmp_path)
    assert ok, note
    assert not (tmp_path.parent / "evil.cls").exists()  # 不逃逸
    assert (tmp_path / "evil.cls").read_bytes() == payload  # 兄弟补位


def test_displaced_magic_variant_writes_expected(tmp_path: Path) -> None:
    """前置注入变异件同补: prologue 推位 tar 的同名/stem 成员仍落槽位。"""
    member = b"% aipproc impl\n"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        info = tarfile.TarInfo("./aipproc.sty")
        info.size = len(member)
        tf.addfile(info, io.BytesIO(member))
    prologue = b"\\PassOptionsToPackage{no-math}{fontspec}\n% injected\n"
    (tmp_path / "aipproc.cls").write_bytes(prologue + buf.getvalue())
    ok, note = _extract(tmp_path)
    assert ok, note
    assert (tmp_path / "aipproc.cls").read_bytes() == member
    assert (tmp_path / "aipproc.cls.tarblob").is_file()


# ------------------------------------------- docstrip 兄弟产出缓存失效 (logcache 病族)
def _docstrip(ctx: LoopCtx, payload: str) -> tuple[bool, str]:
    return builtins.TRANSFORM_FNS["docstrip_generate"](
        ctx, None, payload, {"drivers": ["sh"]}
    )


def test_docstrip_sibling_outputs_invalidated(tmp_path: Path) -> None:
    """None-poison 主案: pre-run 读过缺件缓存 miss→None, docstrip 一次
    抽多件落地后, 请求件与兄弟产出的缓存同让位 (旧码只 invalidate hit,
    兄弟 stale-None 毒化下游)。runner 注入面写两件, 不跑真 latex。"""
    (tmp_path / "foo.ins").write_text("\\input docstrip\n", encoding="utf-8")

    def _runner(_argv: list[str], _timeout: int, wdir: Path) -> tuple:
        (wdir / "foo.cls").write_text("\\ProvidesClass{foo}\n", encoding="utf-8")
        (wdir / "foosub.sty").write_text(
            "\\ProvidesPackage{foosub}\n", encoding="utf-8"
        )
        return 0, "ok", 0.0, False

    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", runner=_runner)
    assert ctx.read(tmp_path / "foo.cls") is None
    assert ctx.read(tmp_path / "foosub.sty") is None  # miss→None 毒化入缓存
    ok, note = _docstrip(ctx, "foo.cls")
    assert ok, note
    assert ctx.read(tmp_path / "foo.cls") == "\\ProvidesClass{foo}\n"
    assert ctx.read(tmp_path / "foosub.sty") == "\\ProvidesPackage{foosub}\n"


def test_docstrip_rewritten_sibling_invalidated(tmp_path: Path) -> None:
    """改写臂: 既有件 v1 已入缓存, docstrip 重写 v2 → 缓存让位见新文
    (mtime+size 指纹 diff 命中改写, 不只新建)。"""
    (tmp_path / "foo.ins").write_text("\\input docstrip\n", encoding="utf-8")
    sibling = tmp_path / "foo.cfg"
    sibling.write_text("% v1\n", encoding="utf-8")

    def _runner(_argv: list[str], _timeout: int, wdir: Path) -> tuple:
        (wdir / "foo.cls").write_text("\\ProvidesClass{foo}\n", encoding="utf-8")
        (wdir / "foo.cfg").write_text("% v2 rewritten\n", encoding="utf-8")
        return 0, "ok", 0.0, False

    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", runner=_runner)
    assert ctx.read(sibling) == "% v1\n"  # 旧文入缓存
    ok, note = _docstrip(ctx, "foo.cls")
    assert ok, note
    assert ctx.read(sibling) == "% v2 rewritten\n"
