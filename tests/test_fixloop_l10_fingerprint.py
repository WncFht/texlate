"""L10 (b3 工单汇流, 2026-09-18): 注入件指纹闸 + nonletter-cs payload 钉。

- b3a 工单: 注入件无版本/hash 闸, precheck 见件跳重投 → 旧代 stub 留存
  无辨 (hep-ph/0408075 stale espcrc2 实证: stub 缺 ``\\readRCS`` 而
  undefined_cs ×106 全 decline)。修: ``_builtins_common`` 指纹三件套
  (``_fingerprint``/``_mark_injected``/``_injected_state``) + 写面
  ``_inject_write`` —— 四分判 foreign(稿自带/真包, advisory+不覆写) /
  current(本代已注入, 跳) / stale(旧代注入件, 覆写刷新) / absent(写)。
- 注入点统一收口: vendored_fetch / legacy_pkg_shim /
  bundled_class_shadow / svjour_clo_stub / generated_stub。
- nonletter cs taxonomy: ``\\+``/``\\~`` 等单字符 cs 从 ``[a-zA-Z@]+``
  抓不到 → payload=None; 10-taxonomy.yaml undefined_cs 签扩交替
  (cond-mat/0111246 ``\\+`` payload=None → "+" 实证)。
"""

import re
from pathlib import Path

from _fixloopkit import mk_vendor, vendored_fetch

from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop._builtins_common import (
    _FINGERPRINT_RE,
    _inject_write,
    _injected_state,
    _mark_injected,
)
from texlate.compile.fixloop.builtins import TRANSFORM_FNS, generated_stub
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.logparse import parse_text


class _Eng:
    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del cwd, fname
        return None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return False


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


# ------------------------------------------------------- _injected_state 四分判


def test_injected_state_quads(tmp_path: Path) -> None:
    body = "% texlate vendored stub\n\\endinput\n"
    t = tmp_path / "x.sty"
    assert _injected_state(t, body) == "absent"
    t.write_text(_mark_injected(body), encoding="utf-8")
    assert _injected_state(t, body) == "current"
    # 指纹失配 (本代 body 变了 / 指纹被改) → stale
    assert _injected_state(t, body + "% extra\n") == "stale"
    # 旧代行头无指纹 → stale (认亲面)
    t.write_text("% texlate vendored stub — 原许可禁分发\nold\n", encoding="utf-8")
    assert _injected_state(t, body) == "stale"
    t.write_text("% fixloop: stripped \\usepackage{x}\nrest\n", encoding="utf-8")
    assert _injected_state(t, body) == "stale"
    # 全无名分 → foreign
    t.write_text("% author's own style\n\\newcommand\\y{2}\n", encoding="utf-8")
    assert _injected_state(t, body) == "foreign"


def test_mark_injected_format() -> None:
    marked = _mark_injected("body\n")
    m = _FINGERPRINT_RE.search(marked)
    assert m is not None
    assert re.fullmatch(r"[0-9a-f]{12}", m.group(1))
    assert marked.endswith("body\n")


# ------------------------------------------------------- _inject_write 闸+写


def test_inject_write_marks_and_caches(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    done, state = _inject_write(ctx, tmp_path / "x.sty", "BODY\n", "x.sty")
    assert done is None
    assert state == "absent"
    text = (tmp_path / "x.sty").read_text(encoding="utf-8")
    assert _FINGERPRINT_RE.search(text)
    # ctx.write 同步读缓存 —— 覆写后 ctx.read 见新内容
    assert ctx.read(tmp_path / "x.sty") == text


def test_inject_write_current_short_circuits(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _inject_write(ctx, tmp_path / "x.sty", "BODY\n", "x.sty")
    done, _ = _inject_write(ctx, tmp_path / "x.sty", "BODY\n", "x.sty")
    assert done is not None
    assert done[0]
    assert "already current" in done[1]


def test_inject_write_stale_refreshes(tmp_path: Path) -> None:
    t = tmp_path / "x.sty"
    t.write_text("% texlate vendored stub — 原许可禁分发\nOLD\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    done, state = _inject_write(ctx, t, "NEW\n", "x.sty")
    assert done is None
    assert state == "stale"
    assert _FINGERPRINT_RE.search(t.read_text(encoding="utf-8"))


def test_inject_write_foreign_protected(tmp_path: Path) -> None:
    t = tmp_path / "x.sty"
    sentinel = "% author's own file\n"
    t.write_text(sentinel, encoding="utf-8")
    ctx = _ctx(tmp_path)
    done, state = _inject_write(ctx, t, "STUB\n", "x.sty")
    assert done is not None
    assert done[0] is False
    assert state == "foreign"
    assert t.read_text(encoding="utf-8") == sentinel
    assert any("foreign" in a for a in ctx.advisories)


# ------------------------------------------------------- vendored_fetch 端到端


def test_vendored_fetch_absent_then_current(tmp_path: Path) -> None:
    """absent → 带指纹落盘; 同 payload 再投 → already current 不重写。

    current 翻 decline (vendorcwd): 零字节改动不算 apply —— True 会烧掉
    本轮 dispatch 并挡住同签名低 order 候选 (2609.19664 实证)。
    """
    root = mk_vendor(tmp_path)
    (root / "stubs" / "slashbox.sty").write_text("% stub\n", encoding="utf-8")
    ctx = _ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    ok, _ = vendored_fetch(ctx, "slashbox.sty", root)
    assert ok
    assert _FINGERPRINT_RE.search(
        (ctx.wdir / "slashbox.sty").read_text(encoding="utf-8")
    )
    ok, note = vendored_fetch(ctx, "slashbox.sty", root)
    assert not ok
    assert "already current" in note
    assert "no-op" in note


def test_vendored_fetch_legacy_stub_refreshed(tmp_path: Path) -> None:
    """旧代落盘 stub (无指纹行头认亲) → 覆写刷新, hep-ph/0408075 情景。"""
    root = mk_vendor(tmp_path)
    (root / "stubs" / "espcrc2.sty").write_text("% new stub\n", encoding="utf-8")
    ctx = _ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    (ctx.wdir / "espcrc2.sty").write_text(
        "% texlate vendored stub — 原许可禁分发\n% old gen\n", encoding="utf-8"
    )
    ok, note = vendored_fetch(ctx, "espcrc2.sty", root)
    assert ok
    assert "refreshed" in note
    assert (
        (ctx.wdir / "espcrc2.sty").read_text(encoding="utf-8").endswith("% new stub\n")
    )


def test_vendored_fetch_foreign_never_clobbered(tmp_path: Path) -> None:
    """稿自带同名件 → decline + advisory, 内容原样。"""
    root = mk_vendor(tmp_path)
    (root / "stubs" / "x.sty").write_text("% stub\n", encoding="utf-8")
    ctx = _ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    sentinel = "% shipped with the paper\n"
    (ctx.wdir / "x.sty").write_text(sentinel, encoding="utf-8")
    ok, note = vendored_fetch(ctx, "x.sty", root)
    assert not ok
    assert "foreign" in note
    assert (ctx.wdir / "x.sty").read_text(encoding="utf-8") == sentinel


# ------------------------------------------------------- legacy_pkg_shim 端到端


def _shim_params() -> dict:
    return {
        "shim_map": {
            "aa.cls": {"body": "\\LoadClassWithOptions{article}\n\\endinput\n"}
        }
    }


def test_legacy_shim_foreign_protected(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    sentinel = "% author-shipped aa.cls\n"
    (tmp_path / "aa.cls").write_text(sentinel, encoding="utf-8")
    ok, note = TRANSFORM_FNS["legacy_pkg_shim"](ctx, _Eng(), "aa.cls", _shim_params())
    assert not ok
    assert "foreign" in note
    assert (tmp_path / "aa.cls").read_text(encoding="utf-8") == sentinel


def test_legacy_shim_rerun_current(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["legacy_pkg_shim"](ctx, _Eng(), "aa.cls", _shim_params())
    assert ok
    ok, note = TRANSFORM_FNS["legacy_pkg_shim"](ctx, _Eng(), "aa.cls", _shim_params())
    assert ok
    assert "already current" in note


# ------------------------------------------------------- generated_stub 闸


def test_generated_stub_current_declines(tmp_path: Path) -> None:
    """overlay 面: 本代 stub 已在盘 → False 交后续规则 (不占位语义)。"""
    ctx = _ctx(tmp_path)
    ok, _ = generated_stub(ctx, _Eng(), "fig.pstex_t", {})
    assert ok
    assert _FINGERPRINT_RE.search(
        (tmp_path / "fig.pstex_t").read_text(encoding="utf-8")
    )
    ok, note = generated_stub(ctx, _Eng(), "fig.pstex_t", {})
    assert not ok
    assert "already on disk" in note


# ------------------------------------------------------- nonletter-cs taxonomy (④)


def test_taxonomy_nonletter_cs_payload() -> None:
    """``\\+`` 单字符 cs 进 payload (cond-mat/0111246 payload=None→"+" 实证);
    字母串/@-cs 照旧。"""
    rs = load_ruleset()

    def classify(blob: str) -> tuple[str | None, str | None]:
        return rs.taxonomy.classify(parse_text(blob))

    cat, pay = classify("! Undefined control sequence.\nl.449 \\+'s\n")
    assert (cat, pay) == ("undefined_cs", "+")
    cat, pay = classify("! Undefined control sequence.\nl.5 \\pdfmapfile\n")
    assert (cat, pay) == ("pdftex_prim", "pdfmapfile")
    cat, pay = classify("! Undefined control sequence.\nl.5 \\@xfootnotemark\n")
    assert (cat, pay) == ("undefined_cs", "@xfootnotemark")
