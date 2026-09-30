"""kernel._vault_rekey — variant 跨纪元采用 (kernel.vault 拆分叶).

variant 是 dedup 键第四维：换纪元后旧纪元字节物理健在但新键域查无，
ledger-verdict dedup 又让上游格跳跑不再产出 → 消费端 restore 饿死
(e2e_real 09-24 qc_no_input 99 格实证)。``rekey`` 逐 (idc,arm) 把
src-variant 完好 kind 经 ``harvest`` 提交进 dst —— 同字节新凭证，
manifest op='rekey' 记源出处; 源副本不动 (hardlink 共 inode, 零字节
复制)。
"""

from __future__ import annotations

from kernel._vault_commit import harvest
from kernel._vault_cred import (
    _ZONE_RANK,
    DEDUP_VERDICTS,
    KINDS,
    _comp,
    _norm_zone,
    leaf_dir,
)
from kernel._vault_intact import _kind_intact
from kernel._vault_io import _iter_metas, _require_sentinel

#: rekey 默认只搬付费侧产物：zh/state 是花钱产物，失即须 regen; splice/
#: layoutqc 是免费再生品，且 slim 过的 splice 进 dst 会把消费端字节闸喂成
#: verified, 永远锁死重生成 (2609.20519 实证——slim 留 3 件，.txlm 已丢)。
REKEY_KINDS = frozenset({"zh", "state"})

#: rekey 源副本资格——quar 嫌疑件不进新纪元; pending/tombstone 判词不背书。
_REKEY_ZONES = frozenset({"primary", "alt", "pending"})


def rekey(
    src_variant,
    dst_variant,
    *,
    arm=None,
    idc=None,
    kinds=None,
    dry: bool = False,
    sink=None,
    run_dir=None,
) -> list[dict]:
    """完好 src-variant 副本的付费产物收进 dst-variant 键域 (§3.10.4)。

    variant 是 dedup 键第四维：换纪元后旧纪元字节物理健在但新键域查无，
    ledger-verdict dedup 又让上游格跳跑不再产出 → 消费端 restore 饿死
    (e2e_real 09-24 qc_no_input 99 格实证)。rekey 逐 (idc,arm) 把
    src 完好 kind 经 harvest 提交进 dst —— 同字节新凭证，manifest
    op='rekey' 记源出处; 源副本不动 (hardlink 共 inode, 零字节复制)。

    粒度按 kind: dst 已有完好副本的 kind 跳过，一格多 src 副本时按
    (zone_rank, altseq) 取最优。quar 源不搬 (嫌疑不入新纪元)。
    返回逐格结果行 (dry 时只预演不落地)。
    """
    src_variant = _comp(src_variant)
    dst_variant = _comp(dst_variant)
    if src_variant == dst_variant:
        msg = f"rekey src == dst variant {src_variant!r}"
        raise ValueError(msg)
    want = set(kinds) if kinds is not None else set(REKEY_KINDS)
    unknown = want - KINDS
    if unknown:
        msg = f"unknown rekey kinds {sorted(unknown)}"
        raise ValueError(msg)
    arm_f = _comp(arm) if arm is not None else None
    idc_f = str(idc) if idc is not None else None
    _require_sentinel()

    src_best: dict[tuple, dict[str, tuple[int, str, dict]]] = {}
    dst_have: dict[tuple, set] = {}
    for _mp, key, meta in _iter_metas():
        if key is None or meta is None:
            continue
        c_idc, c_arm, c_var, c_alt = key
        if (arm_f is not None and c_arm != arm_f) or (
            idc_f is not None and c_idc != idc_f
        ):
            continue
        try:
            zone = _norm_zone(meta.get("zone", "pending"))
        except ValueError:
            continue
        if c_var == dst_variant:
            for k in meta.get("files", {}) or ():
                if k in want and _kind_intact(meta, k):
                    dst_have.setdefault((c_idc, c_arm), set()).add(k)
        elif c_var == src_variant:
            if zone not in _REKEY_ZONES:
                continue
            if meta.get("verdict") not in DEDUP_VERDICTS:
                continue
            rank = _ZONE_RANK.get(zone, 4)
            for k in meta.get("files", {}) or ():
                if k not in want or not _kind_intact(meta, k):
                    continue
                slot = src_best.setdefault((c_idc, c_arm), {})
                cur = slot.get(k)
                if cur is None or (rank, c_alt) < (cur[0], cur[1]):
                    slot[k] = (rank, c_alt, meta)

    out: list[dict] = []
    for (c_idc, c_arm), slot in sorted(src_best.items()):
        have = dst_have.get((c_idc, c_arm), set())
        todo = {k: v for k, v in slot.items() if k not in have}
        if not todo:
            continue
        src_meta = next(iter(todo.values()))[2]
        row = {
            "idc": c_idc,
            "arm": c_arm,
            "kinds": sorted(todo),
            "skipped_kinds": sorted(have & set(slot)),
            "src_variant": src_variant,
            "dst_variant": dst_variant,
        }
        if dry:
            row["dry"] = True
            out.append(row)
            continue
        assets = {
            k: leaf_dir(
                _norm_zone(m.get("zone", "pending")),
                k,
                c_idc,
                c_arm,
                src_variant,
                str(m.get("altseq", "0")),
            )
            for k, (_r, _a, m) in todo.items()
        }
        try:
            mpath = harvest(
                c_idc,
                c_arm,
                dst_variant,
                assets,
                source_run=(
                    f"rekey:{src_variant}->{dst_variant}:"
                    f"{src_meta.get('source_run', '')}"
                ),
                verdict=str(src_meta.get("verdict", "verified")),
                zone="primary",
                id=c_idc,
                sink=sink,
                run_dir=run_dir,
                _op="rekey",
            )
            row["meta"] = str(mpath)
        except Exception as exc:  # 逐格隔离，一格失败不拖全批
            row["error"] = f"{type(exc).__name__}: {exc}"
        out.append(row)
    return out
