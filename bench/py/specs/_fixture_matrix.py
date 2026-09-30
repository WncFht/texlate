r"""B2 fixtures 陷阱断言矩阵（docs/spec/benchmark.md §B2）——原型 ``miniscanner_test``
断言矩阵移植到 ``texlate.latex``，从 ``tests/test_bench_regression.py`` _vendor 至此，
pytest 侧与跑分器 ``bench/py/specs/fixture_assert.py``
共享同一份单源。

底材 ``bench/fixtures/*.tex``（入库，逐字节即语义——永不格式化/润色）：

- ``tricky.tex``：T01–T29 单点陷阱 26 条断言 + ``_meta`` 残留计数 info 行；
- ``tricky-209.tex``：LaTeX 2.09 旧式组合 3 条（``\beq/\eeq``、``\documentstyle``、``\def``）+ parse_ok；
- ``tricky-multi/``：T14 ``\input/\include`` 展平 4 条；
- ``xlat-traps.tex``：xlat 契约压力形 4 条（``@Xn``——产品遮蔽口径
  ``[[BIB_n]]``/``\href[[HREF_n]]``/``[[URL_n]]``，与 xlatbench SYNTHETIC S1–S4 同源）；
- ``tricky-w.tex``：W 系列野机制 11 条（``@Wnn`` ↔ corpus mechanisms.jsonl 台账行，
  infix-over/unbraced-args/arg-next-line/eol-pct-join/range-cite/discretionary/
  pct-comment/comment-macro/spaced-env/enddoc-tail/usepackage-comment）；
- ``tricky-w73/``：``\input{../...}`` 路径逃逸两向断言（gullet C1 openin_any 等价闸）——
  出 main/ 进 shared/（paper 根内，``top_dir=tricky-w73``）照常 resolved inline；
  出 paper 根进 fixtures/（根外）被拒 → ``missing_input``，逃逸句不进 chunks；
- ``tricky-wenc.tex``：W72 混合编码字节件（合法 UTF-8 序列 + 孤立 latin1 字节共存），
  走 ``decode_tex`` 单码选定路径——identity 基准同源改用 ``decode_tex`` 而非
  ``errors="replace"``，断言只锁 latin1 侧 ``café``（单码不可救的 utf8 侧形态留给
  normalize 分档层演进）；
- ``tricky-dollar.tex``：D 系列 dollar 族 10 条（``@Dnn`` ↔ corpus ``$``-leak
  归因亚型——散文 ``\$`` 转义、``\section``/``\textit``/``\item``/footnote 组参内 ``\$``、
  ``$$..env..`` 区内空行照常配对、孤 ``$$``/孤 ``$`` → CMD ph + ``unpaired_dollar``、
  ``\$`` 与 ``$x$`` 同行混排 CMD+MATH 双路）；
- ``tricky-mask.tex``：M 系列 MASK 族 11 条（``@Mnn`` ↔ W07/W11/W84/W92 机制钉——
  comment env 死块三态行锚、docclass/usepackage 跨行夹注释参、行尾 ``%`` 拼接、
  注释内孤立 ``$`` 不参配对；``env_name_at``/``unescaped_dollar_odd`` 修复面）。

门槛（docs/spec/benchmark.md §B2）：72 条 dict 断言全 ``pass``——``partial`` 在原型里是容忍档，
但产品现状全 pass，退化到 partial 即回归，消费侧按 ``== "pass"`` 严判。

注意：本模块的 ``LEAK_PATTERNS``（宽 ``ref_family`` 口径）与
``specs/_leak.py``（corpus 0.040% 官方口径）是**有意不同的两表**——永不合并。

拆分: 实现体按断言族拆进同包私有叶 —— ``_fixture_matrix_base`` (底材
名单/LEAK_PATTERNS/FixtureScan/run_fixture + 断言小件),
``_fixture_matrix_tricky`` (assert_tricky/209/multi), ``_fixture_matrix_xw``
(assert_xlat/w/w73/wenc), ``_fixture_matrix_dm`` (assert_dollar/mask),
``_fixture_matrix_eval`` (模块级测量: _PARSED + 断言实算表 + ID 名单)。
本文件是 PEP 562 惰性门面 (同 ``kernel.vault``/``kernel.importer`` 形制) ——
平名经 ``_LEAF_EXPORTS`` 映射回叶子, ``__getattr__`` 首访解析并缓存,
``from specs._fixture_matrix import X`` 读面与拆分前逐名等价。叶子间互
引走全路径直跨 (``specs._fixture_matrix_*``), 不经本门面。

测量时机例外 —— 「import 即测量」语义不可惰性化: ``_fixture_matrix_eval``
在下方顶层 **eager 装载** (``run_fixture`` 的 SIGALRM 护栏只在主线程合
法; 纯惰性会把 ``_PARSED`` 首访推到 thread-executor worker 内,
``signal.signal`` 必炸)。门面装载完毕 = HEAD 单件 import 完毕 = 全部
fixture 测量与断言表就绪。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

from specs import _bootstrap

_bootstrap.ensure()

if TYPE_CHECKING:
    # __all__ 名单静态落地——F822 要名可解, F401 以 __all__ re-export 豁免;
    # 私有惰性名不在此列 (不在 __all__, 无 F822 需, 导入反吃 F401)。
    import difflib
    import re
    import signal
    import time
    from dataclasses import dataclass
    from pathlib import Path

    from specs._fixture_matrix_base import (
        FIXTURE_FILES,
        FIXTURES,
        LEAK_PATTERNS,
        FixtureScan,
        ParseTimeoutError,
        chunks_blob,
        classify_recon,
        fake_translation,
        run_fixture,
        scan_chunks,
    )
    from specs._fixture_matrix_dm import assert_dollar, assert_mask
    from specs._fixture_matrix_eval import (
        ALL_FIXTURE_NAMES,
        ASSERTS_209,
        D_IDS,
        DOLLAR_ASSERTS,
        IDS_209,
        M_IDS,
        MASK_ASSERTS,
        MULTI_ASSERTS,
        MULTI_IDS,
        TRICKY_ASSERTS,
        TRICKY_IDS,
        W73_ASSERTS,
        W73_IDS,
        W_ASSERTS,
        W_IDS,
        WENC_ASSERTS,
        WENC_IDS,
        XLAT_ASSERTS,
        XLAT_IDS,
    )
    from specs._fixture_matrix_tricky import (
        assert_209,
        assert_multi,
        assert_tricky,
    )
    from specs._fixture_matrix_xw import (
        assert_w,
        assert_w73,
        assert_wenc,
        assert_xlat,
    )
    from texlate.latex import parse_file, reconstruct
    from texlate.latex.placeholder import CHUNK_RX, PH_RX
    from texlate.textutil import DOCCLASS_DECL_RX, mask_tex

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_fixture_matrix_base": (
        "FIXTURE_FILES",
        "FIXTURES",
        "LEAK_PATTERNS",
        "FixtureScan",
        "ParseTimeoutError",
        "_alarm",
        "_all_re",
        "_meta_row",
        "_ph_roundtrip",
        "chunks_blob",
        "classify_recon",
        "fake_translation",
        "run_fixture",
        "scan_chunks",
    ),
    "_fixture_matrix_dm": (
        "assert_dollar",
        "assert_mask",
    ),
    "_fixture_matrix_eval": (
        "ALL_FIXTURE_NAMES",
        "ASSERTS_209",
        "DOLLAR_ASSERTS",
        "D_IDS",
        "IDS_209",
        "MASK_ASSERTS",
        "MULTI_ASSERTS",
        "MULTI_IDS",
        "M_IDS",
        "TRICKY_ASSERTS",
        "TRICKY_IDS",
        "W73_ASSERTS",
        "W73_IDS",
        "WENC_ASSERTS",
        "WENC_IDS",
        "W_ASSERTS",
        "W_IDS",
        "XLAT_ASSERTS",
        "XLAT_IDS",
        "_209",
        "_FIXTURE_TOPDIR",
        "_PARSED",
        "_d",
        "_m",
        "_mk",
        "_t",
        "_w",
        "_w73",
        "_wenc",
        "_x",
    ),
    "_fixture_matrix_tricky": (
        "assert_209",
        "assert_multi",
        "assert_tricky",
    ),
    "_fixture_matrix_xw": (
        "assert_w",
        "assert_w73",
        "assert_wenc",
        "assert_xlat",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# HEAD 单件期模块属性面——stdlib 模块名与 texlate 顶层绑定也按名惰性解析,
# 读面 (含 setattr 型 monkeypatch 缝, patch 落在共享 module 对象上) 与拆分
# 前逐名等价。
_STDLIB_MODS = ("difflib", "re", "signal", "time")
_EXTRA_BINDINGS = {
    "Path": "pathlib",
    "dataclass": "dataclasses",
}
_MODULE_ATTRS = {
    "_bootstrap": "specs._bootstrap",
}
_TEXLATE_EXPORTS = {
    "CHUNK_RX": "texlate.latex.placeholder",
    "DOCCLASS_DECL_RX": "texlate.textutil",
    "PH_RX": "texlate.latex.placeholder",
    "mask_tex": "texlate.textutil",
    "parse_file": "texlate.latex",
    "reconstruct": "texlate.latex",
}

# 「import 即测量」——本叶装载即跑完 9 fixture 的 parse+双重建+断言实算;
# SIGALRM 只在主线程合法, 必须钉在门面装载期 (spec load/pytest 收集都在
# 主线程), 不能等 worker 首访。
from specs import _fixture_matrix_eval  # noqa: F401

# 字面列表——拆分前 ``import *`` 面 (无 __all__ 期全量非下划线名) 逐名保留;
# 私有名经 _LAZY 进属性读面不进 __all__。ruff F401 re-export 判定要静态
# __all__; ``_export_drift`` 是三表同步闸。
__all__ = [
    "ALL_FIXTURE_NAMES",
    "ASSERTS_209",
    "CHUNK_RX",
    "DOCCLASS_DECL_RX",
    "DOLLAR_ASSERTS",
    "D_IDS",
    "FIXTURES",
    "FIXTURE_FILES",
    "IDS_209",
    "LEAK_PATTERNS",
    "MASK_ASSERTS",
    "MULTI_ASSERTS",
    "MULTI_IDS",
    "M_IDS",
    "PH_RX",
    "TRICKY_ASSERTS",
    "TRICKY_IDS",
    "W73_ASSERTS",
    "W73_IDS",
    "WENC_ASSERTS",
    "WENC_IDS",
    "W_ASSERTS",
    "W_IDS",
    "XLAT_ASSERTS",
    "XLAT_IDS",
    "FixtureScan",
    "ParseTimeoutError",
    "Path",
    "assert_209",
    "assert_dollar",
    "assert_mask",
    "assert_multi",
    "assert_tricky",
    "assert_w",
    "assert_w73",
    "assert_wenc",
    "assert_xlat",
    "chunks_blob",
    "classify_recon",
    "dataclass",
    "difflib",
    "fake_translation",
    "mask_tex",
    "parse_file",
    "re",
    "reconstruct",
    "run_fixture",
    "scan_chunks",
    "signal",
    "time",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性 / stdlib 绑定 / texlate 顶层名。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"specs.{leaf}"), name)
        globals()[name] = value
        return value
    if name in _STDLIB_MODS:
        value = importlib.import_module(name)
        globals()[name] = value
        return value
    extra = _EXTRA_BINDINGS.get(name)
    if extra is not None:
        value = getattr(importlib.import_module(extra), name)
        globals()[name] = value
        return value
    mod_path = _MODULE_ATTRS.get(name)
    if mod_path is not None:
        value = importlib.import_module(mod_path)
        globals()[name] = value
        return value
    texmod = _TEXLATE_EXPORTS.get(name)
    if texmod is not None:
        value = getattr(importlib.import_module(texmod), name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return sorted(
        set(globals())
        | set(__all__)
        | set(_LAZY)
        | set(_STDLIB_MODS)
        | set(_EXTRA_BINDINGS)
        | set(_MODULE_ATTRS)
        | set(_TEXLATE_EXPORTS)
    )


def _export_drift() -> list[str]:
    """``_LAZY``/``__all__``/叶子实体三表同步审计 → 漂移描述表。

    空表 = 同步, 测试断言 ``== []`` 即可。逐名 ``getattr`` 实解: 叶子断链
    (``_LEAF_EXPORTS`` 配名叶子不提供) 与幽灵条 (解析不到任何叶子或绑
    定) 在此曝, 是首访 ``AttributeError`` 唯一的提前闸。审计实载全部
    叶子, 只供测试调用, 装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = []
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    for name in _LAZY:
        try:
            getattr(mod, name)
        except Exception as exc:
            drift.append(f"_LEAF_EXPORTS entry {name} does not resolve: {exc}")
    for name in __all__:
        if name in _LAZY:
            continue  # 已解
        try:
            getattr(mod, name)
        except Exception as exc:
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and name not in _STDLIB_MODS
        and name not in _EXTRA_BINDINGS
        and name not in _MODULE_ATTRS
        and name not in _TEXLATE_EXPORTS
        and callable(v)
        and getattr(v, "__module__", None) == __name__
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
