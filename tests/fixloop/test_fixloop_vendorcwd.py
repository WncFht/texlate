"""vendorcwd 车道 (2609.19664 autopsy, 2026-09-19):

- 落点修复：vendored 件落 kpathsea 解析位 ``main_dir/<payload>`` 而非
  wdir 根 —— 编译 cwd = ``main_path().parent`` (engine/_xelatex),
  嵌套 main (``templates/arxiv/main.tex``) 下 wdir 根平铺对 kpathsea
  不可见，apply 形成功能 no-op (fired-unfixed)。``_resolve_site``
  与 fileset_relocate 同口径; main 未知退 wdir 根 (旧行为)。
- no-op 修复：``_inject_write`` ``current`` 态 (同名片已是本代注入件)
  翻成 decline —— 零字节改动返 True 会烧掉本轮 dispatch 并把同签名
  低 order 候选 (fileset_relocate 类) 挡在门外。
"""

import sys
from pathlib import Path

import pytest
from _fixloopkit import mk_ctx, mk_vendor, vendored_fetch

from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx


def _nested_ctx(tmp_path: Path) -> LoopCtx:
    """``templates/arxiv/main.tex`` 嵌套 main 工程 (2609.19664 同构)。"""
    wdir = tmp_path / "w"
    main_dir = wdir / "templates" / "arxiv"
    main_dir.mkdir(parents=True)
    (main_dir / "main.tex").write_text("\\documentclass{article}\n")
    return mk_ctx(wdir, "templates/arxiv/main.tex")


# ------------------------------------------------------- 落点：nested main


def test_vendored_fetch_nested_main_lands_at_main_dir(tmp_path: Path) -> None:
    """嵌套 main: 落 ``<main_dir>/x.sty`` (kpathsea 解析位), 不落 wdir 根。"""
    root = mk_vendor(tmp_path)
    (root / "files" / "fixes.sty").write_text("% fixes\n", encoding="utf-8")
    ctx = _nested_ctx(tmp_path)
    ok, note = vendored_fetch(ctx, "fixes.sty", root)
    assert ok, note
    assert (ctx.wdir / "templates" / "arxiv" / "fixes.sty").is_file()
    assert not (ctx.wdir / "fixes.sty").exists()
    assert "templates/arxiv/fixes.sty" in note


def test_vendored_fetch_nested_payload_relpath(tmp_path: Path) -> None:
    """payload 相对径在 main_dir 下保持 (``\\input{sub/x}`` 期径)。"""
    root = mk_vendor(tmp_path)
    (root / "files" / "x.sty").write_text("% x\n", encoding="utf-8")
    ctx = _nested_ctx(tmp_path)
    ok, _ = vendored_fetch(ctx, "sub/x.sty", root)
    assert ok
    assert (ctx.wdir / "templates" / "arxiv" / "sub" / "x.sty").is_file()


def test_vendored_fetch_flat_main_unchanged(tmp_path: Path) -> None:
    """平铺 main 回归：main_dir == wdir → 仍落 wdir 根。"""
    root = mk_vendor(tmp_path)
    (root / "files" / "aastex.cls").write_text("% real\n", encoding="utf-8")
    wdir = tmp_path / "w"
    wdir.mkdir()
    (wdir / "main.tex").write_text("\\documentclass{aastex}\n")
    ctx = mk_ctx(wdir)
    ok, _ = vendored_fetch(ctx, "aastex.cls", root)
    assert ok
    assert (wdir / "aastex.cls").is_file()


def test_vendored_fetch_no_main_falls_back_wdir(tmp_path: Path) -> None:
    """main 未知 (main_rel=None): 退 wdir 根平铺 (harness/无 main 旧行为)。"""
    root = mk_vendor(tmp_path)
    (root / "files" / "x.sty").write_text("% x\n", encoding="utf-8")
    wdir = tmp_path / "w"
    wdir.mkdir()
    ctx = mk_ctx(wdir, None)
    ok, _ = vendored_fetch(ctx, "x.sty", root)
    assert ok
    assert (wdir / "x.sty").is_file()


def test_vendored_fetch_main_rel_escape_declines(tmp_path: Path) -> None:
    """怪 main_rel 致解析位逃出 wdir → decline, 不泄出工程外。"""
    root = mk_vendor(tmp_path)
    (root / "files" / "x.sty").write_text("% x\n", encoding="utf-8")
    wdir = tmp_path / "w"
    wdir.mkdir()
    ctx = mk_ctx(wdir, "../evil.tex")
    ok, note = vendored_fetch(ctx, "x.sty", root)
    assert not ok
    assert "escapes wdir" in note
    assert not (tmp_path / "x.sty").exists()


# ------------------------------------------------------- no-op re-fire 修复


def test_vendored_fetch_already_current_declines(tmp_path: Path) -> None:
    """同名片已是本代注入件 → (False, no-op): 不烧 dispatch。

    2609.19664 缺陷链：fileset_relocate 字节拷贝触发 _landing_sync 清
    dedup → 同规则 refire → (True, "already current") 占位 → 更低 order
    候选整轮被挡。
    """
    root = mk_vendor(tmp_path)
    (root / "files" / "x.sty").write_text("% x\n", encoding="utf-8")
    ctx = mk_ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    ok, _ = vendored_fetch(ctx, "x.sty", root)
    assert ok
    ok2, note2 = vendored_fetch(ctx, "x.sty", root)
    assert not ok2
    assert "already current" in note2
    assert "no-op" in note2


def test_vendored_fetch_stale_still_applies(tmp_path: Path) -> None:
    """旧代注入件 (stale) 仍覆写刷新 —— no-op 翻译只挡 current。"""
    root = mk_vendor(tmp_path)
    (root / "files" / "x.sty").write_text("% new body\n", encoding="utf-8")
    ctx = mk_ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    ok, _ = vendored_fetch(ctx, "x.sty", root)
    assert ok
    # 篡改落盘件 → 指纹失配成 stale
    (ctx.wdir / "x.sty").write_text(
        "% texlate-fixloop-injected: 000000000000\n% old body\n"
    )
    ctx.invalidate(ctx.wdir / "x.sty")
    ok2, note2 = vendored_fetch(ctx, "x.sty", root)
    assert ok2, note2
    assert "refreshed" in note2
    assert (ctx.wdir / "x.sty").read_text().endswith("% new body\n")


def test_vendored_fetch_foreign_still_declines(tmp_path: Path) -> None:
    """外来件 (稿自带无指纹) → foreign decline 路径不受 no-op 翻译影响。"""
    root = mk_vendor(tmp_path)
    (root / "files" / "x.sty").write_text("% vendored\n", encoding="utf-8")
    ctx = mk_ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    (ctx.wdir / "x.sty").write_text("% author shipped\n")
    ok, note = vendored_fetch(ctx, "x.sty", root)
    assert not ok
    assert "foreign" in note
    assert (ctx.wdir / "x.sty").read_text() == "% author shipped\n"


def test_vendored_fetch_casefold_source(tmp_path: Path) -> None:
    """大小写回退：vendor 仓 ``IEEEconf.cls`` 供 ``ieeeconf.cls`` payload。

    2310.16788 实证：CTAN 原名件带大写骆驼名，稿面 ``\\documentclass``
    小写请求精确查件 miss; casefold 补扫命中，落盘仍写 payload 原名
    (kpathsea 按请求名找件，源名只作字节出处)。
    """
    root = mk_vendor(tmp_path)
    (root / "files" / "IEEEconf.cls").write_text("% ieeeconf real\n", encoding="utf-8")
    ctx = mk_ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    ok, note = vendored_fetch(ctx, "ieeeconf.cls", root)
    assert ok, note
    dst = ctx.wdir / "ieeeconf.cls"
    assert dst.is_file()
    body = dst.read_text()
    assert body.startswith("% texlate-fixloop-injected:")
    assert "% ieeeconf real" in body


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="win32 NTFS 大小写折叠——x.sty 与 X.sty 不可两存，前提不可构造",
)
def test_vendored_fetch_exact_beats_casefold(tmp_path: Path) -> None:
    """精确命中优先于 casefold——同名异写两存时取字面匹配源。"""
    root = mk_vendor(tmp_path)
    (root / "files" / "x.sty").write_text("% exact\n", encoding="utf-8")
    (root / "files" / "X.sty").write_text("% cased\n", encoding="utf-8")
    ctx = mk_ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    ok, _ = vendored_fetch(ctx, "x.sty", root)
    assert ok
    assert (ctx.wdir / "x.sty").read_text().endswith("% exact\n")


# ------------------------------------------------------- vendored_fetch_multi


def test_vendored_fetch_multi_nested_main(tmp_path: Path) -> None:
    """multi 字节平铺同走解析位：嵌套 main 落 main_dir; 已存在 → skip。"""
    root = mk_vendor(tmp_path)
    (root / "files" / "lamsarrow.tfm").write_bytes(b"\x00\x01binary")
    ctx = _nested_ctx(tmp_path)
    params = {"dir": str(root), "files": ["lamsarrow.tfm"]}
    ok, note = TRANSFORM_FNS["vendored_fetch_multi"](ctx, None, None, params)
    assert ok, note
    dst = ctx.wdir / "templates" / "arxiv" / "lamsarrow.tfm"
    assert dst.read_bytes() == b"\x00\x01binary"
    assert not (ctx.wdir / "lamsarrow.tfm").exists()
    # 二轮：全 present → decline (幂等不烧 dispatch)
    ok2, note2 = TRANSFORM_FNS["vendored_fetch_multi"](ctx, None, None, params)
    assert not ok2
    assert "present" in note2


# ------------------------------------------------------- revtex root delegate


class _ShadowEng:
    """probe: revtex4-2 系统有件 (递补源), revtex4 本机查无 (走 _texmf 判)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:  # noqa: ARG002
        if fname == "revtex4-2.cls":
            return "/sys/texmf/tex/latex/revtex/revtex4-2.cls"
        return None


_V40A = "\\ProvidesClass{revtex4}\n\\def\\@uclcnotmath#1{#1}\n"


def test_revtex_delegate_nested_main(tmp_path: Path) -> None:
    """``_texmf`` v4.0a 遮蔽 → delegate 落 main_dir (树外件遮蔽的解析位)。"""
    ctx = _nested_ctx(tmp_path)
    texmf = ctx.wdir / "_texmf"
    texmf.mkdir()
    (texmf / "revtex4.cls").write_text(_V40A)
    ok, note = TRANSFORM_FNS["revtex_era_retire"](ctx, _ShadowEng(), None, {})
    assert ok, note
    delegate = ctx.wdir / "templates" / "arxiv" / "revtex4.cls"
    assert delegate.is_file()
    assert "revtex4-2" in delegate.read_text()
    assert not (ctx.wdir / "revtex4.cls").exists()


def test_revtex_delegate_flat_main_unchanged(tmp_path: Path) -> None:
    """平铺 main: delegate 仍落 wdir 根 (回归)。"""
    wdir = tmp_path / "w"
    wdir.mkdir()
    (wdir / "main.tex").write_text("\\documentclass{revtex4}\n")
    (wdir / "_texmf").mkdir()
    (wdir / "_texmf" / "revtex4.cls").write_text(_V40A)
    ctx = mk_ctx(wdir)
    ok, note = TRANSFORM_FNS["revtex_era_retire"](ctx, _ShadowEng(), None, {})
    assert ok, note
    assert (wdir / "revtex4.cls").is_file()
