"""fixture_assert — B2 陷阱断言评测器（原 ``bench/py/fixture_assert.py`` spec 化）。

底材 ``bench/fixtures/`` 9 个手造 .tex；断言矩阵与 pytest 单源共享
``specs._fixture_matrix``（tricky T01–T29 / 209 / multi / xlat-traps /
w / w73 / wenc / dollar / mask）。

形态要点（调研底稿裁决）:

- **import 即测量**——``specs._fixture_matrix`` 在 spec load 时（主线程）
  完成全部 9 fixture 的 parse+双重建（SIGALRM 护栏只在主线程合法，
  thread-executor worker 内 ``signal.signal`` 必炸）。stage fn 只做
  断言分派+聚合+emit，零 signal 调用。代价：任何 spec load（含
  ``bench plan``/``spec list``）都跑产品解析器——ms 级，fail-loud 可接受。
- **spec.eval=True 硬要求**——'tricky.tex' 类 id 过不了 canon 闸
  （invalid:shape），非 eval 会整批 drop 成空 plan；eval 同时把终态行
  送进 eval_records 车道。
- **EPOCH 届别**——免费格跨 run forever-dedup（last DONE 即跳），内核无
  --recode/--stale-only。``EPOCH`` 编进 variant：要新一轮测量就 bump
  模块常量（新 cell 键自然绕过 dedup），同届 resume 照旧幂等。
- **分母守恒**——逐断言 case 走 ``ctx.emit_case``（index.cases +
  cases.jsonl）：77 行 = 73 n_assert + 4 info（_meta 行不进分母），
  逐 fixture {26,4,4,4,11,2,1,10,11}；格级 metrics.asserts 同集备份
  （>4KB 时 kernel $blob 卸载，读面须 unblob）。
- ``'identical'→'strict'`` 标签改写是 cells.json 既有契约，保留。
- 旧 summary.md/cells.json 报表面不进城——由 derive/report 投影承接
  （§5.2 分析动词道）。

用法::

    bench plan fixture_assert            # 9 格报价
    bench run fixture_assert             # 全量（秒级）
    bench run fixture_assert fixture=tricky-w   # 子串子集
    bench run fixture_assert ids=tricky.tex,xlat-traps.tex
"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from kernel.spec import Param, Spec, Stage

from specs import _fixture_matrix as fm

if TYPE_CHECKING:
    from pathlib import Path

FIXTURES = fm.FIXTURES

#: 测量届别——bump 即开启新一轮（新 variant → 新 cell 键 → 绕过 forever-dedup）。
EPOCH = "v1"


def _guarded(fn, *fields: str):
    """p.ok 门包装：parse 失败 → 单条 ``_parse`` fail 行，不跑断言函数。

    ``fields`` 是 FixtureScan 的字段名序——按序解出传给 ``fn``。
    （旧驱动同形平移——分派三态语义不许改。）
    """

    def run(p: fm.FixtureScan) -> dict:
        if not p.ok:
            return {"_parse": {"status": "fail", "detail": p.error}}
        return fn(*(getattr(p, f) for f in fields))

    return run


#: fixture → 断言函数分派表。表外 fixture = 零断言格（clean+warn，非 skip）。
#: tricky-209 有意不走 _guarded：assert_209 自理 res=None。
_ASSERTS = {
    "tricky.tex": _guarded(fm.assert_tricky, "res", "recon", "recon_fake"),
    "tricky-209.tex": lambda p: fm.assert_209(p.res if p.ok else None, p.recon),
    "tricky-multi/main.tex": _guarded(fm.assert_multi, "recon"),
    "xlat-traps.tex": _guarded(fm.assert_xlat, "res"),
    "tricky-w.tex": _guarded(fm.assert_w, "res", "recon", "recon_fake"),
    "tricky-w73/main/main.tex": _guarded(fm.assert_w73, "res"),
    "tricky-wenc.tex": _guarded(fm.assert_wenc, "res"),
    "tricky-dollar.tex": _guarded(fm.assert_dollar, "res", "recon", "recon_fake"),
    "tricky-mask.tex": _guarded(fm.assert_mask, "res", "recon", "recon_fake"),
}


def _fixture_sha(name: str, path: Path) -> str:
    """item fp_input：fixture 顶层子树字节 sha（dir fixture 整树排序哈希）。

    文件 fixture 哈希自身字节；目录 fixture（tricky-multi/、tricky-w73/）
    哈希 ``FIXTURES/<top>/`` 下全部成员（rel 路径+字节，序确定）。
    """
    top = FIXTURES / name.split("/", 1)[0]
    h = hashlib.sha256()
    if top.is_dir():
        for f in sorted(p for p in top.rglob("*") if p.is_file()):
            h.update(f.relative_to(top).as_posix().encode())
            h.update(b"\x00")
            h.update(f.read_bytes())
    else:
        h.update(path.read_bytes())
    return h.hexdigest()


def _items() -> list[dict]:
    """FIXTURE_FILES 名单派生（与 pytest 自动同步——矩阵只增不减契约）。"""
    return [
        {
            "id": name,
            "variant": EPOCH,
            "fp_input": _fixture_sha(name, path),
            "params": {"fixture": name},
        }
        for name, path in fm.FIXTURE_FILES
    ]


def _select(item: dict, rp: dict) -> bool:
    """run 期子集化：ids= 精确逗分 → fixture= 子串 → only= 子串。"""
    name = str(item.get("id") or "")
    ids = str(rp.get("ids") or "").strip()
    if ids:
        return name in {t.strip() for t in ids.split(",") if t.strip()}
    for key in ("fixture", "only"):
        needle = str(rp.get(key) or "").strip()
        if needle and needle not in name:
            return False
    return True


def _fx_assert(ctx) -> dict:
    """断言分派+聚合（测量包已在 spec load 时主线程完成，此处零 signal）。"""
    name = ctx.id
    p = fm._PARSED[name]

    fn = _ASSERTS.get(name)
    if fn is None:
        ctx.emit_note(f"{name}: no assertion mapping — zero-assert cell",
                      level="warn")
        ctx.emit({"metrics": {"parse_ok": p.ok, "wall_ms": p.wall_ms,
                              "error": p.error or None, "n_assert": 0}})
        return "clean"

    asserts = fn(p)

    if p.ok:
        status0, _ratio, _first = fm.classify_recon(p.res.vtex, p.recon)
        identity = {"identical": "strict"}.get(status0, status0)
        n_chunks = len(p.res.chunks) if p.res else 0
        n_ph = len(p.res.ph_map) if p.res else 0
    else:
        identity, n_chunks, n_ph = None, None, None

    metrics = {
        "parse_ok": p.ok,
        "wall_ms": p.wall_ms,
        "error": p.error or None,
        "identity": identity,
        "n_chunks": n_chunks,
        "n_placeholders": n_ph,
        "n_assert": 0,
        "pass": 0,
        "partial": 0,
        "fail": 0,
        "info": 0,
        "residue_chunk_ph": p.residue_chunk_ph,
        "residue_protect_ph": p.residue_protect_ph,
        "asserts": {},
    }
    errors: list[dict] = []

    for aid, v in asserts.items():
        if isinstance(v, dict):
            st, detail = v.get("status", "?"), str(v.get("detail", ""))
        else:  # assert_209 的 parse_ok 是 bool——折算 pass/fail 且计入 n_assert
            st, detail = ("pass" if v else "fail"), str(v)
        ctx.emit_case({
            "case": f"{name}::{aid}",
            "fixture": name,
            "id": aid,
            "status": st,
            "detail": detail,
            "parse_ok": p.ok,
            "wall_ms": p.wall_ms,
        })
        metrics["asserts"][aid] = {"status": st, "detail": detail}
        if st in ("pass", "partial", "fail"):
            metrics[st] += 1
            metrics["n_assert"] += 1
        else:  # info 级（tricky/w/dollar/mask 的 _meta 行）不进分母
            metrics["info"] += 1
        if st in ("fail", "partial"):
            errors.append({
                "cat": f"assert_{st}",
                "code": aid,
                "msg": f"{name}::{aid} {detail[:200]}",
            })

    if metrics["fail"] > 0:
        status = "fail"
    elif metrics["partial"] > 0:
        status = "partial"
    else:
        status = "ok"
    return {"status": status, "metrics": metrics, "errors": errors or None}


spec = Spec(
    kind="fixture_assert",
    eval=True,  # 'tricky.tex' 过不了 canon；终态行进 eval_records
    items=_items,
    select=_select,
    params={
        "ids": Param(type=str, default="", fp=False),
        "fixture": Param(type=str, default="", fp=False),
        "only": Param(type=str, default="", fp=False),
    },
    stages=[
        Stage("fx_assert", _fx_assert, eval=True,
              status_class={
                  "ok": "terminal",
                  "partial": "terminal",
                  "fail": "terminal",
                  "clean": "terminal",
                  "error": "retriable",
              }),
    ],
    freeze_plan=True,
    executor="thread",
    env_probes=["python"],
    code_deps=[
        "bench/py/specs/_fixture_matrix.py",
        "src/texlate/latex",
        "src/texlate/textutil.py",
        "bench/fixtures",
    ],
)
