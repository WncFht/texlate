r"""dedupexpiry (task #254): builtin 自产编辑不落外部落件档 —— 键面零过期钉。

``_landing_sync`` 的基线前烧键过期只为「外部落件把新站点引进 fileset」
(defcensus E-route) 而设; 规则自产编辑走 ``ctx.write``/``io.written``
authored 账, 不稀释 dedup (stucksem 实证: 无差别过期让先火规则非幂等
重派, 抢后位凭据门窗口)。两处 builtin 此前绕 authored 账被判外部落件:

- ``non_utf8_recode`` 裸 ``write_text`` 就地转码 —— 同件同站点纯重编码
  (``ctx.read`` errors=replace 下 ASCII 站点转码前已全可见, 无新站点);
- ``purge_corrupt_intermediates`` 裸 ``unlink`` 删引擎可再生中间件 ——
  删件只减站点, 且 .aux 族无 install/vendored 供件臂需借过期重供。

修复 = recode 走 ``ctx.write``; purge 删路径入 ``io.written`` 账。
对照面保留: 真外部落件 (install/vendor/run_tool 裸写) 依旧全量过期。
"""

from pathlib import Path

from _fixloopkit import mk_ctx

from texlate.compile.fixloop.builtins.misc import (
    _wdir_fingerprint,
    non_utf8_recode,
    purge_corrupt_intermediates,
)
from texlate.compile.fixloop.engine import _landing_sync


def test_recode_is_authored_preserves_dedup(tmp_path: Path) -> None:
    """cp1252 源转码 = 自产编辑：落件同步零外部件，基线前烧键全存活。

    旧态裸 ``write_text`` → 指纹 diff 判外部落件 → ``applied`` 全过期 +
    ``_texts`` 失效; 修复后 ``ctx.write`` 记账 → 键面不动且缓存同步新文。
    """
    src = tmp_path / "main.tex"
    src.write_bytes("\\documentclass{article}\n\\title{café}\n".encode("latin-1"))
    ctx = mk_ctx(tmp_path)
    ctx.io.written.clear()  # 派发窗开始：自产写从零计账 (与三处 wrap 点同约)
    ctx.ledger.applied.update({"ruleA:x", "ruleB:y"})
    before = _wdir_fingerprint(tmp_path)
    pre = set(ctx.ledger.applied)
    applied, _note = non_utf8_recode(ctx, None, None, {})
    assert applied
    assert _landing_sync(ctx, before, pre) == 0
    assert ctx.ledger.applied == {"ruleA:x", "ruleB:y"}
    src.read_bytes().decode("utf-8")  # 盘上真转成 utf-8 (旧态抛 DecodeError)
    assert ctx.read(src) == "\\documentclass{article}\n\\title{café}\n"


def test_purge_is_authored_preserves_dedup(tmp_path: Path) -> None:
    """截断 aux 删除 = 自产编辑：落件同步零外部件，基线前烧键全存活。

    旧态裸 ``unlink`` → 指纹 diff 判外部落件 → ``applied`` 全过期; 修复后
    删路径入 ``io.written`` authored 账 → 键面不动，``_texts`` 条目仍失效
    (purge 自带 invalidate, 不靠落件同步补)。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\nx\n", encoding="utf-8"
    )
    aux = tmp_path / "main.aux"
    aux.write_bytes(b"\\newlabel{x}{{1}{1}}\xc3")  # 多字节劈断 → 判腐蚀
    ctx = mk_ctx(tmp_path)
    assert ctx.read(aux) is not None  # errors=replace 下腐蚀件仍可读入缓存
    ctx.io.written.clear()
    ctx.ledger.applied.update({"ruleA:x", "ruleB:y"})
    before = _wdir_fingerprint(tmp_path)
    pre = set(ctx.ledger.applied)
    applied, _note = purge_corrupt_intermediates(ctx, None, None, {"exts": (".aux",)})
    assert applied
    assert not aux.exists()
    assert _landing_sync(ctx, before, pre) == 0
    assert ctx.ledger.applied == {"ruleA:x", "ruleB:y"}
    assert ctx.read(aux) is None


def test_external_landing_still_expires(tmp_path: Path) -> None:
    """对照钉：同窗真外部落件 (install/vendor/run_tool 裸写同形) 依旧全量
    过期基线前烧键 —— authored 账只收编自产编辑，不放水真落件。"""
    ctx = mk_ctx(tmp_path)
    ctx.io.written.clear()
    ctx.ledger.applied.update({"ruleA:x", "ruleB:y"})
    before = _wdir_fingerprint(tmp_path)
    pre = set(ctx.ledger.applied)
    (tmp_path / "qux.sty").write_text("\\ProvidesPackage{qux}\n", encoding="utf-8")
    assert _landing_sync(ctx, before, pre) == 1
    assert ctx.ledger.applied == set()
