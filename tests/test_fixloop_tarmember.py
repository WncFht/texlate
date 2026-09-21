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

from pathlib import Path

from _fixloopkit import mk_ctx
from conftest import tar_bytes

from texlate.compile.fixloop import builtins


def _write_tar(path: Path, members: dict[str, bytes]) -> None:
    path.write_bytes(tar_bytes(members))


def _extract(wdir: Path) -> tuple[bool, str]:
    ctx = mk_ctx(wdir, main_rel=None)
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
    prologue = b"\\PassOptionsToPackage{no-math}{fontspec}\n% injected\n"
    (tmp_path / "aipproc.cls").write_bytes(
        prologue + tar_bytes({"./aipproc.sty": member})
    )
    ok, note = _extract(tmp_path)
    assert ok, note
    assert (tmp_path / "aipproc.cls").read_bytes() == member
    assert (tmp_path / "aipproc.cls.tarblob").is_file()


# --------------------------------------------- ustar 字样假阳 (2410.17904)
def test_ustar_macro_name_not_renamed(tmp_path: Path) -> None:
    r"""宏名内 ``ustar`` 字样假阳实案: ``\mustar``/``\mustarh`` 回推 257
    落文本非 NUL → 旧闸误改 ``paper.tex``→.tarblob → missing_file。
    魔数+版本域全宽 8B 校验首关即拒。"""
    tex = (
        "\\documentclass{article}\n% "
        + "x" * 400
        + "\n\\newcommand{\\mustar}{\\mu^\\star}\n"
        + "\\newcommand{\\mustarh}{\\mu^{\\star h}}\n"
        + "\\begin{document}\n$\\mustar(x,a)+\\mustarh(x,a)$\n\\end{document}\n"
    )
    (tmp_path / "paper.tex").write_bytes(tex.encode())
    ok, note = _extract(tmp_path)
    assert not ok, note
    assert (tmp_path / "paper.tex").is_file()
    assert not (tmp_path / "paper.tex.tarblob").exists()


def test_ustar_magic_field_bad_checksum_not_renamed(tmp_path: Path) -> None:
    """校验和层独测: 文本内嵌 POSIX 魔数+版本全形 ``ustar\\0`` + ``00``
    且 chksum 位恰呈八进制形 (``012345␣␣``)——值不等于头余字节和仍拒。"""
    body = (
        b"% "
        + b"y" * 190
        + b"012345  "  # 恰落 hdr+148: 八进制形态正确但值必不等于头校验和
        + b"y" * 101
        + b"ustar\x0000"
        + b"z" * 400
    )
    (tmp_path / "fake.tex").write_bytes(body)
    ok, note = _extract(tmp_path)
    assert not ok, note
    assert (tmp_path / "fake.tex").is_file()
    assert not (tmp_path / "fake.tex.tarblob").exists()
