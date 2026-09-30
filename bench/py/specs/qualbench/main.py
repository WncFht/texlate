"""specs.qualbench.main — qualbench items/select/格函数/spec 装配叶。

frame jsonl → 格枚举（丢 frame 即炸）；_judge 格函数编排 mock/paid 双臂；
spec 单例 + judge 道 paid factory（devin-2api + stream_fallback）。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from kernel.spec import SC_OK_REJECT, Param, Spec, Stage

if TYPE_CHECKING:
    from pathlib import Path

from specs import _bootstrap

_bootstrap.ensure()

from specs import _select as _sel  # run 期收窄单源（ids/only/n 管道）
from specs._shared import (
    DEFAULT_BASE_URL,
    DEFAULT_PRICES,
    GatewayChat,
)
from specs.qualbench.const import EPOCH, JUDGE_TIMEOUT, NOMINATIONS, PROTOCOL_V
from specs.qualbench.judge import Pair, mock_judge, pair_signals, shape_judged
from specs.qualbench.paid import _judge_pair

# ---------------------------------------------------------------- frame → items
#: 选样层冻结产物——增删 lane = 改本元组 + 落新 jsonl（别原地改已冻结的）。
FRAMES = (
    "qualframe-mock-v1.jsonl",
    "qualframe-live-v1.jsonl",
)


def _iter_frame(path: Path):
    for ln, raw_ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_ln.strip()
        if line:
            yield ln, json.loads(line)


def _items() -> list[dict]:
    """frame jsonl → 格枚举：一行一格。丢 frame 即炸（选样层完整性，
    见头注）——别静默退化成「没东西可测」。"""
    items: list[dict] = []
    for name in FRAMES:
        path = NOMINATIONS / name
        if not path.is_file():
            msg = (
                f"qualbench frame missing: {path} — frames are tracked "
                "selection artifacts; bake via specs/_qualframe.py or "
                "trim FRAMES"
            )
            raise FileNotFoundError(msg)
        stem = path.stem
        for _ln, row in _iter_frame(path):
            items.append(
                {
                    "id": row["paper"],
                    "arm": row["model"],
                    "up": row["up"],
                    "variant": (
                        f"{PROTOCOL_V}@{EPOCH}|{row['judge']}|{row['chunk_id']}"
                    ),
                    "lane": stem,
                    "fp_input": str(row.get("sha") or ""),
                    "params": {
                        "src": row["src"],
                        "zh": row["zh"],
                        "kind": row["kind"],
                        "src_status": row["src_status"],
                        "chunk_id": row["chunk_id"],
                        "judge": row["judge"],
                    },
                }
            )
    return items


class _Select:
    """frames/ids/judges 过滤后按 frame 序取前 n（烘焙序即 seeded 序）。

    有态：``seen`` 只数通过过滤的格——spec 每进程加载一次，一次 plan
    遍历一次，无跨 run 污染面。"""

    def __init__(self) -> None:
        self.seen = 0

    def _dims(self, ctx: _sel.Ctx) -> bool:
        frames = _sel.csv_set(ctx.rp.get("frames"))
        if frames and str(ctx.item.get("lane") or "") not in frames:
            return False
        judges = _sel.csv_set(ctx.rp.get("judges"))
        return (
            not judges
            or str((ctx.item.get("params") or {}).get("judge") or "") in judges
        )

    def _take(self, ctx: _sel.Ctx) -> bool:
        if self.seen >= ctx.n:
            return False
        self.seen += 1
        return True

    def __call__(self, item: dict, rp: dict) -> bool:
        return _sel.select(
            item,
            rp,
            pre=self._dims,
            ids="gate",
            item_canon="safe",
            sample=self._take,
        )


# ---------------------------------------------------------------- 格函数
def _metric_view(out: dict) -> dict:
    """record → metrics 投影：标量 + 小列表，errors/raw/judge2 细节留给 case。"""
    m = {k: v for k, v in out.items() if k not in ("errors", "raw", "judge2")}
    j2 = out.get("judge2")
    if isinstance(j2, dict):
        m["judge2_model"] = j2.get("judge_model")
        m["judge2_stated100"] = j2.get("stated100")
        m["judge2_n_errors"] = j2.get("n_errors")
        if j2.get("judge2_error"):
            m["judge2_error"] = j2["judge2_error"]
    return m


def _judge(ctx):
    """一格：frame 行 → judge → ok/reject/error（状态映射见头注）。"""
    p = ctx.params
    pair = Pair(
        paper=ctx.idc,
        chunk_id=str(p.get("chunk_id") or ""),
        kind=str(p.get("kind") or "para"),
        model=ctx.arm,
        src=str(p.get("src") or ""),
        zh=str(p.get("zh") or ""),
        status=str(p.get("src_status") or "ok"),
    )
    sig = pair_signals(pair.src, pair.zh)
    lead = {  # 每种结局都带的分母键
        "kind": pair.kind,
        "chunk_id": pair.chunk_id,
        "src_status": pair.status,
        "sig": sig,
    }
    case = {
        "paper": pair.paper,
        "chunk_id": pair.chunk_id,
        "kind": pair.kind,
        "model": pair.model,
        "judge_param": str(p.get("judge") or ""),
        "src_status": pair.status,
        "sig": sig,
        "src": pair.src[:400],
        "zh": pair.zh[:400],
    }
    if not pair.src.strip() or not pair.zh.strip():
        case["verdict"] = "empty_pair"
        ctx.emit_case(case)
        return {
            "status": "reject",
            "errors": [{"cat": "empty_pair", "msg": "blank src/zh — nothing to judge"}],
            "metrics": {"verdict": "empty_pair", **lead},
        }
    if str(p.get("judge") or "") == "mock-judge":
        # 零网关自检臂——gateway() 懒构造即付费断言，mock 格永不触网。
        parsed = mock_judge(pair)
        out = {
            "judge_model_used": "mock-judge",
            **shape_judged(parsed, pair, sig),
        }
        case.update({"verdict": "judged", **out})
        ctx.emit_case(case)
        return {
            "status": "ok",
            "metrics": {"verdict": "judged", **_metric_view(out), **lead},
        }
    out = _judge_pair(ctx, pair, sig)
    jerr = out.get("judge_error")
    if jerr and str(jerr).startswith("no_eligible_judge"):
        case.update({"verdict": "no_eligible_judge", **out})
        ctx.emit_case(case)
        return {
            "status": "reject",
            "errors": [{"cat": "no_eligible_judge", "msg": str(jerr)[:300]}],
            "metrics": {"verdict": "no_eligible_judge", **lead},
        }
    if jerr or "stated100" not in out:
        case.update({"verdict": "judge_error", **out})
        ctx.emit_case(case)
        return {
            "status": "error",
            "errors": [
                {
                    "cat": "judge_error",
                    "msg": str(jerr or out.get("error") or "call_failed")[:300],
                }
            ],
            "metrics": {
                "verdict": "judge_error",
                "judge_model_used": out.get("judge_model_used"),
                "seconds": out.get("seconds"),
                **lead,
            },
        }
    case.update({"verdict": "judged", **out})
    ctx.emit_case(case)
    return {
        "status": "ok",
        "metrics": {"verdict": "judged", **_metric_view(out), **lead},
    }


# ---------------------------------------------------------------- spec
def _factory():
    """judge 道 paid factory：devin-2api + stream_fallback + 300s 超时。

    ``stream_fallback=True``：2026-09-19 网关非流式全模型 502、stream 独活
    的事故形态——judge 道必须能吃到流式臂（xlat 道同样理由）。模型参数
    给的是 client 默认模；每发请求显式传 judge 模型，默认值形同虚设。
    nslots=2 对齐旧 --concurrency 默认（网关 decode ~550 tok/s 自限）。"""
    from kernel import paid as paidmod

    from texlate.xlat.client import env_key_for_url

    key = env_key_for_url(DEFAULT_BASE_URL)

    def build(_ctx=None):
        return GatewayChat(
            DEFAULT_BASE_URL,
            key,
            "swe-2-max",
            stream_fallback=True,
            timeout=JUDGE_TIMEOUT,
        )

    return paidmod.GatewayFactory(build, prices=dict(DEFAULT_PRICES), nslots=2)


spec = Spec(
    kind="qualbench",
    eval=True,  # eval 全格：id 免 canon 闸、终态进 eval_records 道
    params={
        # cell 参数（frame 行 → item.params；fp=True 让内容陈旧度进 cell_fp）
        "src": Param(str, default=""),
        "zh": Param(str, default=""),
        "kind": Param(str, default="para"),
        "src_status": Param(str, default="ok"),
        # 已进 variant 的测量坐标——声明只为 schema 完整，fp=False 防双计
        "chunk_id": Param(str, default="", fp=False),
        "judge": Param(str, default="swe-2-max", fp=False),
        # 测量语义旋钮（fp=True——改动=新测量空间，不原地覆盖）
        "second_model": Param(str, default="swe-2-high"),
        "no_second": Param(bool, default=False),
        "judge_temperature": Param(float, default=0.1),
        "judge_max_tokens": Param(int, default=8192),
        # select 闸（fp=False；n 是 SELECTOR_PARAMS 自带排除）
        "frames": Param(str, default="", fp=False),
        "ids": Param(str, default="", fp=False),
        "judges": Param(str, default="", fp=False),
        "n": Param(int, default=0),
    },
    items=_items,
    select=_Select(),
    stages=[
        Stage(
            "judge",
            _judge,
            paid=True,
            eval=True,
            dedup_key=("idc", "arm", "variant"),
            status_class=SC_OK_REJECT,
        ),
    ],
    freeze_plan=True,
    executor="thread",
    same_id_serial=False,  # 格间零共享态（无 workspace/无 mutates）
    lake=False,  # frame 内联 src/zh——格函数不触湖
    code_deps=[
        "src/texlate/xlat/client.py",
        "src/texlate/xlat/_errors.py",
        "src/texlate/xlat/_dialects.py",
        "src/texlate/xlat/_discovery.py",
        "bench/py/specs/_shared.py",
        "bench/py/specs/qualbench/const.py",
        "bench/py/specs/qualbench/judge.py",
        "bench/py/specs/qualbench/paid.py",
        "bench/py/specs/qualbench/main.py",
    ],
    gateway_factory=_factory(),
)
