"""e2e_real 帧/items 叶——冻结帧装载 + 帧 sha 戳 + --ids/--only 窄化。"""

from __future__ import annotations

import functools
import hashlib
from pathlib import Path

from specs import _benchlite as benchlib
from specs import _select as _sel  # run 期收窄单源（ids/only 管道）

ROOT = Path(__file__).resolve().parents[4]

#: 冻结抽样帧——benchlib.pick_sample 等价口径（seed=42 n=40）烘于
#: 2026-09-23，抽样池=非 eval 层∧湖可水化格∧有源指纹
#: （blob_sha256|main_tex_sha256 非空——无 fp 的 cell 输入同一性无从钉；
#: 旧 core 层 manifest 的 extracted 已清盘，帧池即当前 dev 可用集
#: 682 格）。帧即锁：同帧重跑样本集逐 id 相等（旧 run_meta.sample_ids
#: 防漂移语义）。
FRAME = ROOT / "bench" / "nominations" / "e2e_real_frame.jsonl"

#: 测量世代——forever-dedup 下换代靠变体升档而非 rerun 旗标。
EPOCH = "v1"

#: 付费臂名——与 mock 兄弟臂/soak 生产臂隔开 (idc,arm,variant) vault+claim
#: 键域（soak 用 '-' 默认臂，本 spec 恒 'real'）。
ARM = "real"

# _gate/_swap_in/_ensure_kind/_xlat_marker/_compile_judge/case_bridge 单源在
# specs/_shared.py（soak/fixloop_bench 同款——勿再长本地副本）。

# ---------------------------------------------------------------- items/select


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _frame_sha_of(frame: Path) -> str:
    """任一冻结帧的 provenance 戳（不进 cell 键域，帧改版只改戳不烧
    dedup）——兄弟 eval spec 经各自帧路径调本函数。"""
    return _sha256(frame)[:12] if frame.is_file() else "absent"


@functools.cache
def _frame_sha() -> str:
    """本帧 sha 缓存——route metrics.frame 的 provenance 戳。"""
    return _frame_sha_of(FRAME)


def _items_of(frame: Path, arm: str, epoch: str) -> list[dict]:
    """冻结帧装载通用件——帧缺席=空；行自带 id/layer/cat_group/era/
    bytes/fp_input，arm/variant 由本函数盖章（帧只管选样不管键域）。"""
    if not frame.is_file():
        return []
    rows: list[dict] = []
    for row in benchlib.iter_jsonl(frame):
        if not isinstance(row, dict) or not row.get("id"):
            continue
        rows.append(
            {
                "id": str(row["id"]),
                "layer": row.get("layer"),
                "cat_group": row.get("cat_group"),
                "era": row.get("era"),
                "bytes": row.get("bytes"),
                "fp_input": row.get("fp_input"),
                "arm": arm,
                "variant": epoch,
            }
        )
    return rows


def _items() -> list[dict]:
    """本帧 items——compile_checks 物化一次。"""
    return _items_of(FRAME, ARM, EPOCH)


def _select(item: dict, rp: dict) -> bool:
    """G1 plan-filter：--ids 直选（canon 双拼写+cat 别名折叠归一）→
    --only canon 子串——旧驱动 --ids/--only 窄化的 run 级等价物。"""
    return _sel.select(item, rp, ids="decisive", only="canon")
