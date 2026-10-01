"""texlate.repair — 修复机械包（fixloop 低层件 + 日志归因回灌簇）。

``e2e``/``pipecore`` 与 ``server.worker`` 双编排器共享的修复侧单源——
两臂各自保留编排（报告形状、事件、回灌副作用不同），本包承载：

- ``mech``：fixloop 调用包装 ``run_fixloop``/``run_precheck``、
  ``ResProxy`` CompRes 记录代理、``fixloop_cell_parts`` 轮次归并、
  dropped ``engine_flags`` 的 tectonic→xelatex 跨引擎重试取优
  ``cross_engine_retry``/``VERDICT_RANK``、``ruleset_with_baseline``
  baseline 注入、``merge_flags``/``consume_engine_flags`` 审计尾、
  ``resolve_glossary_path`` confine kernel、``embed_tounicode_quiet``
  ToUnicode best-effort 壳。``fixloop``/``precheck_pass`` 调用点经
  ``compile.patchseams`` 查名——patch 打 ``patchseams.X`` 或
  ``repair.X`` 同拦（回指语义见 patchseams docstring）。
- ``runstate``：``TreeRun``/``split_cid`` 回灌运行态。
- ``envjudge``：env 可译性判定（``_env_judge_one``/``env_judge_all``
  + 目标谓词 ``unknown_env_of``）。
- ``attr``：log 错误签名（``err_signature``/``err_signatures``）+
  归因桶（``_BUCKETS``/``_bucket_rx``）+ ``chunk_spans``/
  ``_resolve_fidx``/``LogAttr``/``_attr_localize`` 归因面。
- ``rounds``：``retranslate_hits`` + resplice 簇 + ``logfix_round``
  回灌阶梯。

本文件是 PEP 562 惰性门面（同 ``fixloop/ruleset`` 形制）——平名经
``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``repair.X`` 公共面与 ``from ... import X``/``M._x`` 属性读面不变。
``ENV_*`` 开关名是字面量常量、零成本，直接 eager 回引钉点面。
monkeypatch 锚点注意：patch 叶子不 patch 门面（docs/dev/seams.md §1）
——``repair.name`` 读到的恒是叶子对象，但 ``setattr(repair, ...)``
只遮蔽门面不改叶子内部互引。叶子间互引走全路径直跨
（``texlate.repair.<叶>``），不经本门面。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

from texlate.textutil.osutil import (
    ENV_ENV_JUDGE,
    ENV_NO_LOGFIX,
    ENV_NO_SEQ_MARKS,
)

if TYPE_CHECKING:
    from texlate.repair.attr import (
        _ARM_FLAG_RX,
        _ATTR_MAX_ERRORS,
        _ATTR_WINDOW,
        _BUCKET_RX_CACHE,
        _BUCKETS,
        _FILELEVEL_CATS,
        _FILELEVEL_EXTRA,
        _INFRA_CATS,
        _INFRA_EXTRA,
        _STRUCT_CATS,
        _STRUCT_EXTRA,
        _UNDEF_CS_CULPRIT_RXS,
        _UNDEF_CS_HEAD_RX,
        LOGFIX_MAX_CHUNKS,
        LogAttr,
        _attr_localize,
        _bucket_rx,
        _log_parse,
        _resolve_fidx,
        _sig_head,
        _sig_set,
        _undef_cs_culprit,
        chunk_spans,
        err_signature,
        err_signatures,
        err_signatures_text,
    )
    from texlate.repair.envjudge import (
        _ENV_JUDGE_MAX_CHARS,
        _KNOWN_ENVS,
        _env_judge_one,
        env_judge_all,
        unknown_env_of,
    )
    from texlate.repair.mech import (
        ENV_FIXLOOP_LLM,
        ENV_NO_FIXLOOP,
        VERDICT_RANK,
        CrossRetry,
        ResProxy,
        consume_engine_flags,
        cross_engine_retry,
        embed_tounicode_quiet,
        fixloop,
        fixloop_cell_parts,
        log_text_of,
        merge_flags,
        precheck_pass,
        resolve_glossary_path,
        ruleset_with_baseline,
        run_fixloop,
        run_precheck,
    )
    from texlate.repair.rounds import (
        _resplice,
        _resplice_and_diffs,
        _slot_diffs,
        logfix_round,
        retranslate_hits,
    )
    from texlate.repair.runstate import TreeRun, split_cid

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "mech": (
        "VERDICT_RANK",
        "CrossRetry",
        "ResProxy",
        "consume_engine_flags",
        "cross_engine_retry",
        "embed_tounicode_quiet",
        "fixloop",
        "fixloop_cell_parts",
        "log_text_of",
        "merge_flags",
        "precheck_pass",
        "resolve_glossary_path",
        "ruleset_with_baseline",
        "run_fixloop",
        "run_precheck",
        "ENV_NO_FIXLOOP",
        "ENV_FIXLOOP_LLM",
    ),
    "runstate": (
        "TreeRun",
        "split_cid",
    ),
    "envjudge": (
        "env_judge_all",
        "unknown_env_of",
        "_env_judge_one",
        "_ENV_JUDGE_MAX_CHARS",
        "_KNOWN_ENVS",
    ),
    "attr": (
        "LogAttr",
        "LOGFIX_MAX_CHUNKS",
        "chunk_spans",
        "err_signature",
        "err_signatures",
        "err_signatures_text",
        "_bucket_rx",
        "_attr_localize",
        "_log_parse",
        "_resolve_fidx",
        "_sig_head",
        "_sig_set",
        "_undef_cs_culprit",
        "_ARM_FLAG_RX",
        "_BUCKETS",
        "_BUCKET_RX_CACHE",
        "_FILELEVEL_CATS",
        "_FILELEVEL_EXTRA",
        "_INFRA_CATS",
        "_INFRA_EXTRA",
        "_ATTR_WINDOW",
        "_ATTR_MAX_ERRORS",
        "_STRUCT_CATS",
        "_STRUCT_EXTRA",
        "_UNDEF_CS_CULPRIT_RXS",
        "_UNDEF_CS_HEAD_RX",
    ),
    "rounds": (
        "logfix_round",
        "retranslate_hits",
        "_resplice",
        "_resplice_and_diffs",
        "_slot_diffs",
    ),
}

_LAZY: dict[str, str] = {
    name: leaf for leaf, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集 +
# eager ENV_* 钉点面，新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "ENV_ENV_JUDGE",
    "ENV_FIXLOOP_LLM",
    "ENV_NO_FIXLOOP",
    "ENV_NO_LOGFIX",
    "ENV_NO_SEQ_MARKS",
    "LOGFIX_MAX_CHUNKS",
    "VERDICT_RANK",
    "_ARM_FLAG_RX",
    "_ATTR_MAX_ERRORS",
    "_ATTR_WINDOW",
    "_BUCKETS",
    "_BUCKET_RX_CACHE",
    "_ENV_JUDGE_MAX_CHARS",
    "_FILELEVEL_CATS",
    "_FILELEVEL_EXTRA",
    "_INFRA_CATS",
    "_INFRA_EXTRA",
    "_KNOWN_ENVS",
    "_STRUCT_CATS",
    "_STRUCT_EXTRA",
    "_UNDEF_CS_CULPRIT_RXS",
    "_UNDEF_CS_HEAD_RX",
    "CrossRetry",
    "LogAttr",
    "ResProxy",
    "TreeRun",
    "_attr_localize",
    "_bucket_rx",
    "_env_judge_one",
    "_log_parse",
    "_resolve_fidx",
    "_resplice",
    "_resplice_and_diffs",
    "_sig_head",
    "_sig_set",
    "_slot_diffs",
    "_undef_cs_culprit",
    "chunk_spans",
    "consume_engine_flags",
    "cross_engine_retry",
    "embed_tounicode_quiet",
    "env_judge_all",
    "err_signature",
    "err_signatures",
    "err_signatures_text",
    "fixloop",
    "fixloop_cell_parts",
    "log_text_of",
    "logfix_round",
    "merge_flags",
    "precheck_pass",
    "resolve_glossary_path",
    "retranslate_hits",
    "ruleset_with_baseline",
    "run_fixloop",
    "run_precheck",
    "split_cid",
    "unknown_env_of",
]


def __getattr__(name: str) -> object:
    leaf = _LAZY.get(name)
    if leaf is None:
        raise AttributeError(name)
    mod = importlib.import_module(f"{__package__}.{leaf}")
    val = getattr(mod, name)
    globals()[name] = val  # 首访后缓存成真 attr——__getattr__ 只付一次
    return val


def __dir__() -> list[str]:
    return sorted(__all__)


def _export_drift() -> list[str]:
    """三表一致性自检：``_LEAF_EXPORTS`` ∪ eager ``ENV_*`` vs ``__all__``。

    返回错配名清单（``[]`` = 无漂移）——给开发期断言/测试钩用，
    运行期零成本（不 eager import 任何叶子）。
    """
    declared = set(_LAZY) | {"ENV_ENV_JUDGE", "ENV_NO_LOGFIX", "ENV_NO_SEQ_MARKS"}
    return sorted(set(__all__) ^ declared)


if __name__ == "__main__":  # 漂移自检直连：python -m texlate.repair
    drift = _export_drift()
    sys.stdout.write(f"drift={drift}\n")
    sys.exit(1 if drift else 0)
