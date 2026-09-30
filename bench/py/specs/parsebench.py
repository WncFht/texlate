r"""parsebench — ``texlate.latex`` 产品管线语料评测器 (docs/spec/benchmark.md §B1) 的 Spec v2 移植。

对 ``bench/corpus/manifest*.jsonl`` 框架内每篇湖格做逐 .tex 测量：
decode_tex + flatten_inputs + parse_file（产品路径）→ parse ok/error/ms、
chunk 字符 median/p90/max、6 族泄漏正则命中与逐条 examples、identity
往返三档（strict/normalized/diverged + first_diff + quick_ratio）、
fake-translation splice 残留（chunk_ph/protect_ph）与孤儿 chunk、
vtex_vs_src 展开足迹、bug1 ph_tail 探针、warn_kinds、unresolved_inputs；
论文级 roots/multi_doc/primary/roles(root|input_reached|orphan|no_root)/
路由标签{reject,xelatex,minted,non-utf8,no-hyperref}/non_utf8/flatten 覆盖。

两 stage（census 先例的 probe+eval 对）：

- ``pb_probe``  — 湖格分类 + extracted 枚举计量（**纯读零湖写**——catalog
  先分类再读盘，``empty`` 锚 dir 会伪装成可枚举空树）。ok=extracted 完整
  可读且已枚举；partial=raw_only / 已登记 empty_payload（合法残缺层
  终态永不重测——旧口径这批论文不在 extracted/ 扫描面，同义「不进
  files.jsonl」）；skip=cell 缺席/skeleton 锚（后续水化可救）；
  error=meta torn/读异常。
- ``pb_eval``   — needs pb_probe.ok；逐文件测量全量走 **per-paper
  subprocess worker**：thread executor 下 ``signal.signal`` 抛
  ValueError，而 30s/文件的 SIGALRM 超时是口径本体——worker 主线程内
  SIGALRM 合法，父侧 outer timeout = timeout_s×n_tex×2+300 兜底
  C 级悬挂（sre 检查点外的真死循环）。ok=全部文件测完（行级
  ok=False 的 parse fail 是测量结果不是 cell 失败）；clean=paper 零
  .tex；partial=批中断（worker 被杀/崩时 files.jsonl 已有残留行——
  行在=测成的旧续跑语义在 cell 内复刻）；fail=拓扑已产但零测量行；
  skip=两 stage 间 extracted 消失；error=worker 崩/输出不可读/零行被杀。

覆盖率口径换代（对拍差集显式锚记）：v1 flatten 可达集经
``flatten_mod._read_file`` monkeypatch 收集——thread executor 下并发互毒。
v2 改读 ``res.inputs``（parse_file 自己登记的 ``(vpos, resolved realpath)``
输入事件流，``isabs`` 过滤即本次展开实际拉入集）——**失 v1
``top_dir=pdir`` 论文顶层兜底一维**：parse_file 按 v1 ``parse_one`` 原样
不传 top_dir 以保测量口径，同一 res 的 inputs 即新 reach 口径；
``metrics.reach_source="res.inputs"`` 锚记换代面。resolved 项是
``Path.resolve()`` realpath——身份集比较一律 resolve() 对齐（symlink
父目录下 abspath 会错配成全 orphan）。

- **EPOCH**：forever-dedup 下「重测一代」的唯一结构杠杆——模块常量折进
  ``variant``（本 spec 无 arm/variant 业务轴），换代=改 EPOCH。旧
  ``--rerun``/``vtex_len`` 换代戳在 v2 无对应物（cli 无 --recode）；
  ``fp_input=blob_sha256|main_tex_sha256`` 接 byte-drift 的 stale 标记职责。
- **report 不是 stage**：files.jsonl/papers.json/summary.md 聚合（Wilson
  CI / cluster bootstrap B=2000 seed=20260915 / frame 加权三口径）归
  derive 分析动词读 eval_records+records 重建——needs 是 per-cell
  边表达不了全语料聚合。分母守恒：Σcells ``metrics.n_files`` ≡ 旧
  files.jsonl 行数；``metrics.tot.*`` 逐键与旧 ``aggregate()`` 同名
  同式，Σ 即旧 ``tot[*]``；terminal eval cell 数 ≡ papers.json 行数。
- **measure_error 纪律原样**：判定层异常是行级 flag 不判 parse fail；
  cell 仍按测成数定 status。
- ``prefetch=False``：测量 run 零湖写——probe/eval 都以 ``is_complete``
  先闸，complete 格 ``src_path`` 走 hydrate fast-path 永不触发水化写。
- **item params 带 manifest 全字段**（stratum_cell/cluster_id/yymm/era/
  archive/cat_group/layer/channel/n_tex/n_files/bytes/mech_tags）——derive
  verb 加权/簇 bootstrap 重建原料；未声明 Param 故不进 fp（``cell_fp``
  只数 spec.params 声明位）。

拆分: 实现体按职域拆进同包私有叶 —— ``_parsebench_measure`` (SIGALRM
parse_one + 泄漏/孤儿/identity/fake-splice/ph_tail 判定件 + file_metrics),
``_parsebench_topology`` (非 UTF-8 判定 / find_roots / 路由标签 /
_topology), ``_parsebench_worker`` (子进程测量体 + --worker cli),
``_parsebench_items`` (manifest 行→item 源 + catalog 签名缓存 +
sample/select), ``_parsebench_eval`` (pb_probe/pb_eval 双 stage + spec
装配)。本文件是 PEP 562 惰性门面 (同 ``kernel.vault`` 形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子, ``__getattr__`` 首访解析并缓存,
``getattr(module, "spec")`` 与 ``from specs.parsebench import X`` 读面与
拆分前逐名等价; HEAD 期模块属性面 (stdlib 模块名/kernel·texlate 顶层
绑定) 同样惰性解析。叶子间互引走全路径直跨 (``specs._parsebench_*``),
不经本门面。spec 文件经 load_spec exec (非包内导入, ``__package__``
为空) —— 叶名一律写死 ``specs.`` 前缀, 不靠 ``__package__``。

worker 自查: ``_eval`` 拉起 ``python <门面路径> --worker`` —— 父侧 argv
目标必须是本文件 (``with_name("parsebench.py")`` 已校正), ``__main__``
尾块经 ``__getattr__`` 解到 ``_parsebench_worker._worker_cli``。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# worker 裸跑 ``python specs/x.py --worker`` 时 bench/py 不在
# sys.path——先立起才够得着 specs.*（load_spec 径下幂等）。
_BENCH_PY = str(Path(__file__).resolve().parents[1])
if _BENCH_PY not in sys.path:
    sys.path.insert(0, _BENCH_PY)

from specs import _bootstrap

_bootstrap.ensure()

if TYPE_CHECKING:
    # __all__ 名单静态落地——F822 要名可解，F401 以 __all__ re-export 豁免;
    # 私有惰性名不在此列 (不在 __all__, 无 F822 需，导入反吃 F401)。
    import difflib
    import json
    import math
    import os
    import re
    import shutil
    import signal
    import statistics
    import subprocess
    import time
    import traceback

    from kernel import lake, paths
    from kernel.spec import EVAL_LAYERS, SC_OK_PARTIAL, Param, Spec, Stage

    from specs import _benchlite as benchlib
    from specs._leak import LEAK_PATTERNS
    from specs._parsebench_eval import TIMEOUT_S, spec
    from specs._parsebench_items import CORPUS, EPOCH, ROOT
    from specs._parsebench_measure import (
        PH_TOKEN_RX,
        ParseTimeout,
        classify_recon,
        fake_translation,
        file_metrics,
        orphan_chunk_ids,
        parse_one,
        percentile,
        ph_tail_risk,
        rebuild_metrics,
        scan_chunks,
    )
    from specs._parsebench_topology import (
        DOCCLASS_RX,
        RX_EPS_PS,
        RX_HYPERREF,
        RX_MINTED,
        find_roots,
        is_non_utf8,
        is_tex,
        paper_tags,
        rglob_tex,
    )
    from texlate.latex import (
        flatten_inputs,
        parse_file,
        reconstruct,
        validate_result,
    )
    from texlate.textutil import decode_tex

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_parsebench_eval": (
        "TIMEOUT_S",
        "_eval",
        "_gate",
        "_probe",
        "_read_json",
        "_read_rows",
        "_tot",
        "spec",
    ),
    "_parsebench_items": (
        "CORPUS",
        "EPOCH",
        "ROOT",
        "_CAT_MEMO",
        "_ITEMS",
        "_catalog",
        "_corpus_rows",
        "_items",
        "_n_sample",
        "_sample_ids",
        "_sampleable",
        "_select",
    ),
    "_parsebench_measure": (
        "PH_TOKEN_RX",
        "ParseTimeout",
        "_alarm",
        "classify_recon",
        "fake_translation",
        "file_metrics",
        "orphan_chunk_ids",
        "parse_one",
        "percentile",
        "ph_tail_risk",
        "rebuild_metrics",
        "scan_chunks",
    ),
    "_parsebench_topology": (
        "DOCCLASS_RX",
        "RX_EPS_PS",
        "RX_HYPERREF",
        "RX_MINTED",
        "_topology",
        "find_roots",
        "is_non_utf8",
        "is_tex",
        "paper_tags",
        "rglob_tex",
    ),
    "_parsebench_worker": (
        "_worker_cli",
        "_worker_run",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# HEAD 单件期模块属性面——stdlib 模块名与 kernel/texlate/specs 顶层绑定也按名
# 惰性解析，``parsebench.lake``/``parsebench.benchlib`` 等读面 (含 setattr 型
# monkeypatch 缝，patch 落在共享 module 对象上) 与拆分前逐名等价。
# ``sys``/``Path``/``_bootstrap`` 是门面自身实绑定 (shim/ensure 所需),
# globals 命中在先不进惰性道。
_STDLIB_MODS = (
    "difflib",
    "json",
    "math",
    "os",
    "re",
    "shutil",
    "signal",
    "statistics",
    "subprocess",
    "sys",
    "time",
    "traceback",
)
_MODULE_ATTRS = {
    "_bootstrap": "specs._bootstrap",
    "_sel": "specs._select",
    "benchlib": "specs._benchlite",
    "lake": "kernel.lake",
    "paths": "kernel.paths",
}
_EXTRA_BINDINGS = {
    "EVAL_LAYERS": "kernel.spec",
    "LEAK_PATTERNS": "specs._leak",
    "Param": "kernel.spec",
    "SC_OK_PARTIAL": "kernel.spec",
    "Spec": "kernel.spec",
    "Stage": "kernel.spec",
    "decode_tex": "texlate.textutil",
    "flatten_inputs": "texlate.latex",
    "parse_file": "texlate.latex",
    "reconstruct": "texlate.latex",
    "validate_result": "texlate.latex",
}

# 字面列表——拆分前 ``import *`` 面 (无 __all__ 期全量非下划线名) 逐名保留;
# 私有名经 _LAZY/_MODULE_ATTRS 进属性读面不进 __all__。ruff F401 re-export
# 判定要静态 __all__; ``_export_drift`` 是三表同步闸。
__all__ = [
    "CORPUS",
    "DOCCLASS_RX",
    "EPOCH",
    "EVAL_LAYERS",
    "LEAK_PATTERNS",
    "PH_TOKEN_RX",
    "ROOT",
    "RX_EPS_PS",
    "RX_HYPERREF",
    "RX_MINTED",
    "SC_OK_PARTIAL",
    "TIMEOUT_S",
    "Param",
    "ParseTimeout",
    "Path",
    "Spec",
    "Stage",
    "benchlib",
    "classify_recon",
    "decode_tex",
    "difflib",
    "fake_translation",
    "file_metrics",
    "find_roots",
    "flatten_inputs",
    "is_non_utf8",
    "is_tex",
    "json",
    "lake",
    "math",
    "orphan_chunk_ids",
    "os",
    "paper_tags",
    "parse_file",
    "parse_one",
    "paths",
    "percentile",
    "ph_tail_risk",
    "re",
    "rebuild_metrics",
    "reconstruct",
    "rglob_tex",
    "scan_chunks",
    "shutil",
    "signal",
    "spec",
    "statistics",
    "subprocess",
    "sys",
    "time",
    "traceback",
    "validate_result",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性 / stdlib 绑定 / kernel·texlate·specs 顶层名。

    spec 文件经 ``load_spec`` 以 ``spec_from_file_location`` exec——此时
    ``__package__`` 为空串，叶名必须写死 ``specs.`` 前缀 (正常
    ``import specs.parsebench`` 径下等价)。
    """
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
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return sorted(
        set(globals())
        | set(__all__)
        | set(_LAZY)
        | set(_STDLIB_MODS)
        | set(_MODULE_ATTRS)
        | set(_EXTRA_BINDINGS)
    )


def _export_drift() -> list[str]:
    """``_LAZY``/``__all__``/叶子实体三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。逐名 ``getattr`` 实解：叶子断链
    (``_LEAF_EXPORTS`` 配名叶子不提供) 与幽灵条 (解析不到任何叶子或绑
    定) 在此曝，是首访 ``AttributeError`` 唯一的提前闸。审计实载全部
    叶子，只供测试调用，装载期不自检。

    注意：本模块经 load_spec exec 装载后被弹出 ``sys.modules``, 审计只在
    正常 ``import specs.parsebench`` 的常驻对象上有效。
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
        and name not in _MODULE_ATTRS
        and name not in _EXTRA_BINDINGS
        and callable(v)
        and getattr(v, "__module__", None) == __name__
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift


if __name__ == "__main__":
    from specs._parsebench_worker import _worker_cli

    raise SystemExit(_worker_cli())
