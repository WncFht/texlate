r"""specs._fixture_matrix.eval — 模块级测量叶 (_fixture_matrix 拆分叶).

装载即跑完 9 个 fixture 的 parse+双重建 (``_PARSED``) 并实算全部断言
表——``run_fixture`` 的 SIGALRM 护栏只在**主线程**合法，故本叶由门面
``_fixture_matrix/__init__.py`` 顶层 eager 装载（「import 即测量」的 HEAD 单件
同语义）；若被惰性首访拖到 thread-executor worker 内才导入，
``signal.signal`` 会抛 ValueError。
"""

from __future__ import annotations

from specs import _bootstrap

_bootstrap.ensure()

from specs._fixture_matrix.base import FIXTURE_FILES, FIXTURES, run_fixture
from specs._fixture_matrix.dm import assert_dollar, assert_mask
from specs._fixture_matrix.tricky import assert_209, assert_multi, assert_tricky
from specs._fixture_matrix.xw import (
    assert_w,
    assert_w73,
    assert_wenc,
    assert_xlat,
)

#: 需要非缺省 ``top_dir`` 的 fixture（w73：paper 根 = tricky-w73/，``../shared``
#: 在根内可解析、``../../escape-outside`` 出根被 C1 闸拒）。
_FIXTURE_TOPDIR: dict = {
    "tricky-w73/main/main.tex": FIXTURES / "tricky-w73",
}

_PARSED = {
    name: run_fixture(name, path, top_dir=_FIXTURE_TOPDIR.get(name))
    for name, path in FIXTURE_FILES
}
_t = _PARSED["tricky.tex"]
_209 = _PARSED["tricky-209.tex"]
_m = _PARSED["tricky-multi/main.tex"]
_x = _PARSED["xlat-traps.tex"]
_w = _PARSED["tricky-w.tex"]
_w73 = _PARSED["tricky-w73/main/main.tex"]
_wenc = _PARSED["tricky-wenc.tex"]
_d = _PARSED["tricky-dollar.tex"]
_mk = _PARSED["tricky-mask.tex"]

TRICKY_ASSERTS = assert_tricky(_t.res, _t.recon, _t.recon_fake) if _t.res else {}
ASSERTS_209 = assert_209(_209.res, _209.recon)
MULTI_ASSERTS = assert_multi(_m.recon) if _m.res else {}
XLAT_ASSERTS = assert_xlat(_x.res)
W_ASSERTS = assert_w(_w.res, _w.recon, _w.recon_fake) if _w.res else {}
W73_ASSERTS = assert_w73(_w73.res) if _w73.res else {}
WENC_ASSERTS = assert_wenc(_wenc.res) if _wenc.res else {}
DOLLAR_ASSERTS = assert_dollar(_d.res, _d.recon, _d.recon_fake) if _d.res else {}
MASK_ASSERTS = assert_mask(_mk.res, _mk.recon, _mk.recon_fake) if _mk.res else {}

# tricky.tex 的断言全集（docs/spec/benchmark.md：新增断言只增不减——T14 在 multi，T15/T28 不存在）
TRICKY_IDS = [
    f"T{n:02d}"
    for n in (
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        29,
    )
]
IDS_209 = ["beq_eeq_trap", "documentstyle", "def_macros"]
MULTI_IDS = [
    "T14_input_expanded",
    "T14_include_expanded",
    "T14_nested_input",
    "T14_commented_input",
]
XLAT_IDS = [
    "@X1-bibitem-lead",
    "@X2-multikey-cite",
    "@X3-verbatim-pct",
    "@X4-dense-math",
]
# tricky-w.tex 的断言全集（Wnn ↔ bench/corpus/mechanisms.jsonl 台账行）
W_IDS = [
    "W11",
    "W15",
    "W50",
    "W67",
    "W75",
    "W82",
    "W83",
    "W84",
    "W90",
    "W91",
    "W92",
]
W73_IDS = [
    "W73_within_paper_escape",
    "W73_beyond_root_escape",
]
WENC_IDS = ["W72_mixed_decoded"]
# tricky-dollar.tex 的断言全集（@Dnn ↔ corpus $-leak 归因亚型钉）
D_IDS = [f"D{n:02d}" for n in range(1, 11)]
# tricky-mask.tex 的断言全集（@Mnn ↔ W07/W11/W84/W92 机制钉）
M_IDS = [f"M{n:02d}" for n in range(1, 12)]
ALL_FIXTURE_NAMES = [n for n, _ in FIXTURE_FILES]
