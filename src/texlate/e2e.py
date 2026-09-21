"""mock E2E 驱动（docs/spec/benchmark.md B5 Mode A 的产品化扶正）。

全链走产品 API：``route_project → normalize_project → XlatPipeline(MockTranslator)
+ L0 校验 → splice 写回 → prepare_chinese → engine.compile → judge``。
bench harness（e2e_mock_bench）与 CLI ``texlate run`` 共用同一实现——
评测条件矩阵在 bench 侧，单工程驱动在这里。扫描/翻译/编译/修复的
policy 脊单源在 ``texlate.pipecore``（worker/bench 共享），本模块只留
编排顶与 e2e 私有缝（``engine_for``/``_embed_tounicode`` 的
monkeypatch 面）。

编译失败后的两级修复（docs/spec/validate.md 接线）：

1. **L2 回灌**（先跑）——log 解析把错误定位到 chunk（file:line: 或文件栈
   归因），只重译被点名的块（每块限 1 次、per-doc 有上限），resplice 后
   重编一次；仍被点名且本轮重译过的块回落原文（"再不过 → fallback 原文"）。
   先修自家译文伤——fixloop 的 regex_rewrite 会直接改盘上文件，若先跑
   fixloop 再 resplice 会把它的修复冲掉。
2. **fixloop**（后跑）——yaml 规则引擎修源/基建类问题（缺包、preamble、
   字体……）。``TEXLATE_NO_FIXLOOP=1`` 关闭（测试/对照臂）；轮数上限沿用
   rules/ ``meta.loop.max_rounds``。产出 ``engine_flags`` 在此消费：
   当前引擎没法直接吃 CLI 旗标（引擎 seam 未开），先落 advisory + 触发
   跨引擎换编（tectonic 上收到 flag → 换 xelatex 再编，取更优 verdict）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from texlate.compile import engine as _engine_mod
from texlate.compile.cjkmap import embed_cjk_mappings
from texlate.compile.engine import route_project
from texlate.compile.inject import (
    InjectRejectError,
    classify_no_main,
    find_main_tex,
    prepare_chinese,
)
from texlate.compile.normalize import normalize_project
from texlate.pipecore import (
    NULL_SINK,
    PipeJob,
    RepairPolicy,
    baseline_snapshot,
    compile_judge_tail,
    default_front_matter,
    delivered,
    probe_report,
    repair_chain,
    tail_dict,
    translate_tree_run,
)
from texlate.pipecore import scan_tree as _scan_tree
from texlate.repair import embed_tounicode_quiet
from texlate.repair_l2 import ENV_ENV_JUDGE, L2_MAX_CHUNKS
from texlate.textutil import env_flag
from texlate.textutil.osutil import ENV_AUTO_GLOSSARY
from texlate.validate.l0 import validate_pair

if TYPE_CHECKING:
    from texlate.compile.engine import Engine
    from texlate.pipecore import ReportSink
    from texlate.repair_l2 import TreeRun
    from texlate.xlat.pipeline import Translator

log = logging.getLogger(__name__)

#: 逐篇 LLM 术语抽取臂开关（``TEXLATE_AUTO_GLOSSARY``，默认关——frozen-300
#: 回归裁决⑦未定前不开产线；开时抽取臂与翻译同模）——名本体注册在
#: ``textutil.osutil``，同名回引

# 兼容绑定：测试钉住的本模块私有名（pipecore 单源实体的别名——``_delivered``
# 由 test_e2e 直调、``_tail_dict`` 是 test_bench_harness 的 judge_dict 键集对拍面）
_delivered = delivered
_tail_dict = tail_dict


def env_switch(name: str, *, explicit: bool | None, default: bool) -> bool:
    """三态开关归一：显式参数优先，``None`` 才读 ``env_flag``。

    本模块就地副本——共享单源应为 ``texlate.textutil.osutil.env_switch``
    （hoist 后删此定义、改从 ``texlate.textutil`` 导入，调用点不变）。
    env 仍在调用时读取，``monkeypatch.setenv`` 缝不受影响。
    """
    return explicit if explicit is not None else env_flag(name, default=default)


def engine_for(name: str, **kw: object) -> Engine:
    """``compile.engine.engine_for`` 调用时委托——同名同签名。

    本模块全局是 ~8 处测试的 monkeypatch 面（``e2e.engine_for`` 钉
    RecordingEngine 系假引擎）；经 ``_engine_mod.`` 属性解析转发让
    ``texlate.compile.engine.engine_for`` 的补丁同样可截——worker
    ``seams.*`` 同款调用时查名。
    """
    return _engine_mod.engine_for(name, **kw)


# ---------------------------------------------------------------- 翻译树


def _translate_tree(  # noqa: PLR0913 -- 注入面穿透（translator/开关/sink 各臂缝）
    root: Path,
    *,
    translator: Translator | None = None,
    env_judge: bool = False,
    auto_glossary: bool = False,
    front_matter: frozenset[str] | None = None,
    sink: ReportSink = NULL_SINK,
) -> tuple[dict, TreeRun]:
    """目录树翻译 + splice 写回 → (stats, 运行态)——脊在 ``pipecore.translate_tree_run``。

    ``scan_fn``/``validator`` 显式透传本模块全局：``e2e._scan_tree``
    （fuzz spy）与 ``e2e.validate_pair``（test_e2e 钉）的 monkeypatch
    缝随件保活——调用时查名才吃补丁。``front_matter`` = preamble 前置
    发射集（None → ``TEXLATE_FRONT_MATTER``/缺省 ``abstract,title``）。
    ``sink`` 透传 ``translate_tree_run`` 的 ``translate`` 实况帧。
    """
    fm = default_front_matter() if front_matter is None else front_matter
    stats, run, _results = translate_tree_run(
        root,
        translator=translator,
        env_judge=env_judge,
        auto_glossary=auto_glossary,
        scan_fn=lambda r: _scan_tree(r, front_matter=fm),
        validator=lambda s, z: validate_pair(s, z).feedback(),
        sink=sink,
    )
    return stats, run


def translate_tree(  # noqa: PLR0913 -- 同上：注入面穿透到 _translate_tree
    root: Path,
    *,
    translator: Translator | None = None,
    env_judge: bool | None = None,
    auto_glossary: bool | None = None,
    front_matter: frozenset[str] | None = None,
    sink: ReportSink = NULL_SINK,
) -> dict:
    """目录树内全部 .tex 走 XlatPipeline → splice 写回。

    单 pipeline 跨文件编排（chunk_id = ``{file_idx}:{chunk.id}``），
    校验器注入 L0 ``validate_pair``。返回 per-tree 汇总统计。
    ``translator`` 缺省 ``MockTranslator``（链路自检臂），可注入真网关
    Translator；``env_judge`` 缺省读 ``TEXLATE_ENV_JUDGE``（默认关——
    静态表外 env 的可译性 LLM 判定）；``auto_glossary`` 缺省读
    ``TEXLATE_AUTO_GLOSSARY``（默认关）；``front_matter`` = preamble
    前置发射集（None → ``TEXLATE_FRONT_MATTER``/缺省 ``abstract,title``）。
    """
    ej = env_switch(ENV_ENV_JUDGE, explicit=env_judge, default=False)
    ag = env_switch(ENV_AUTO_GLOSSARY, explicit=auto_glossary, default=False)
    stats, _run = _translate_tree(
        root,
        translator=translator,
        env_judge=ej,
        auto_glossary=ag,
        front_matter=front_matter,
        sink=sink,
    )
    return stats


# ---------------------------------------------------------------- 编译尾段


def _probe_flags_of(work: Path, main_rel: str) -> tuple[str, ...]:
    """``probe_report`` 的旗标投影：声明侧编译旗标（minted→-shell-escape 等）。

    worker._probe_target 同款旁路语义——探针崩只空旗标返回，不阻塞编译。
    """
    rep = probe_report(work, main_rel)
    return tuple(rep.flags) if rep is not None else ()


def _embed_tounicode(pdf: Path) -> int:
    """``repair.embed_tounicode_quiet`` 委托——bench(``e2e_mock_bench``) 钉住名保签名。

    显式传本模块 ``embed_cjk_mappings`` 全局名——调用时查名使
    ``monkeypatch.setattr(e2e, "embed_cjk_mappings", …)`` 缝继续生效
    （test_e2e_wiring 三钉）。
    """
    return embed_tounicode_quiet(pdf, embed_fn=embed_cjk_mappings)


# ---------------------------------------------------------------- 条件臂


def pipe_condition(  # noqa: PLR0913 -- 修复链开关面（env 缺省，显式可覆盖）
    work: Path,
    eng_name: str,
    main_rel: str,
    timeout: float,
    *,
    translator: Translator | None = None,
    env_judge: bool | None = None,
    l2_on: bool | None = None,
    fixloop_on: bool | None = None,
    auto_glossary: bool | None = None,
    l2_max_chunks: int = L2_MAX_CHUNKS,
    route_engines: list[str] | None = None,
    front_matter: frozenset[str] | None = None,
    sink: ReportSink = NULL_SINK,
) -> dict:
    """跑 pipe 条件：normalize → 翻译 → ctex 注入 → 编译 → 判定 → 修复链。

    非 clean 时先 L2 回灌（译文归因重译）再 fixloop（规则修源）。开关：
    ``TEXLATE_ENV_JUDGE`` / ``TEXLATE_NO_L2`` / ``TEXLATE_NO_FIXLOOP`` /
    ``TEXLATE_AUTO_GLOSSARY``（显式参数优先于 env）。``route_engines`` 供
    engine_flags 跨引擎消费，
    缺省 ``[eng_name]``（bench 直调不跨界）。fixloop 启用时翻译前先抓
    baseline 快照（worker ``ctx.base_dir`` 同位——e2e 原地翻译，snapshot
    即 pristine 源），供 restore_support_from_src 复原被写脏的 support 件。
    ``sink`` 收 ``stage`` 边界帧 + ``translate``/``l2``/``fixloop`` 实况
    （CLI ``CliSink`` 渲染；bench/测试臂 NULL 静默同重构前）。
    """
    rec: dict[str, object] = {"engine": eng_name}
    rec["normalize"] = normalize_project(work, eng_name, main_rel)
    sink.event("stage", {"stage": "normalize"})
    ej = env_switch(ENV_ENV_JUDGE, explicit=env_judge, default=False)
    fl = RepairPolicy.resolve(fixloop_on=fixloop_on).fixloop
    ag = env_switch(ENV_AUTO_GLOSSARY, explicit=auto_glossary, default=False)
    # baseline 快照在翻译写回前抓（pipecore.baseline_snapshot 单件——normalize
    # 过的英文 pristine 树 → fixloop restore_support_from_src 的复原源）；
    # ``td`` 须活到修复链收敛——局部绑定持到函数返回即随帧清理（bench
    # ``_td`` 同法），快照寿命 = 修复链全程。
    td = baseline_snapshot(work, enabled=fl)
    baseline_dir = Path(td.name) / "base" if td is not None else None
    sink.event("stage", {"stage": "translate"})
    stats, run = _translate_tree(
        work,
        translator=translator,
        env_judge=ej,
        auto_glossary=ag,
        front_matter=front_matter,
        sink=sink,
    )
    rec["translate"] = stats
    sink.event("stage", {"stage": "inject"})
    try:
        rec["inject"] = prepare_chinese(work, main_rel)
    except InjectRejectError as e:
        # 策略拒绝 → partial (降级链交付), reject_at+reason 留审计 (F3)
        rec["status"] = "partial"
        rec["reject_at"] = "inject"  # inject_reject 类: 与 route reject 分流
        rec["verdict"] = {"status": "partial", "reasons": [e.reason]}
        return rec
    job = PipeJob(
        work,
        main_rel,
        eng_name,
        timeout,
        probe_flags=_probe_flags_of(work, main_rel),
    )
    # 0-chunk 主文档 (includepdf 壳等) 无译文产出 → 不期待 CJK 渲染,
    # cjk_chars=0 是其正确终态而非静默失败 (scout-cjk0 F 桶 11 格假阳)
    expect_cjk = stats.get("chunks") != 0
    sink.event("stage", {"stage": "compile", "engine": eng_name})
    tail, res = compile_judge_tail(job, expect_cjk=expect_cjk, engine_fn=engine_for)
    rec.update(tail)

    if rec["status"] != "clean":
        # 修复链 = pipecore.repair_chain 单件（precheck → L2 回灌 → fixloop，
        # 与 bench 同一条链）；``engine_fn=engine_for`` 调用时查名保
        # ``e2e.engine_for`` monkeypatch 缝（conftest RecordingEngine）。
        res = repair_chain(
            rec,
            job,
            run,
            res,
            expect_cjk=expect_cjk,
            l2_on=l2_on,
            fixloop_on=fl,
            l2_max_chunks=l2_max_chunks,
            route_engines=route_engines,
            baseline_dir=baseline_dir,
            engine_fn=engine_for,
            sink=sink,
        )
    # ToUnicode 注入在修复链收敛之后——L2 重编/fixloop 换编都会重写同一
    # <stem>.pdf，只对最终落盘产物注一次（worker _embed_tounicode 同位）
    if res.has_pdf and res.pdf is not None:
        sink.event("stage", {"stage": "tounicode"})
        rec["tounicode_fonts"] = _embed_tounicode(res.pdf)
    return rec


def base_condition(work: Path, eng_name: str, main_rel: str, timeout: float) -> dict:
    """跑 base 条件：不动源码直接编译+判定（管线引入 vs 原生失败的归因对照）。"""
    rec: dict[str, object] = {"engine": eng_name}
    job = PipeJob(
        work,
        main_rel,
        eng_name,
        timeout,
        probe_flags=_probe_flags_of(work, main_rel),
    )
    tail, _res = compile_judge_tail(job, expect_cjk=False, engine_fn=engine_for)
    rec.update(tail)
    return rec


def pipeline_run(  # noqa: PLR0913 -- 同上：开关面穿透到 pipe_condition
    work: Path,
    engine_opt: str,
    timeout: float,
    *,
    translator: Translator | None = None,
    env_judge: bool | None = None,
    l2_on: bool | None = None,
    fixloop_on: bool | None = None,
    l2_max_chunks: int = L2_MAX_CHUNKS,
    front_matter: frozenset[str] | None = None,
    sink: ReportSink = NULL_SINK,
) -> dict:
    """工程目录上的端到端全链（对齐 e2e_mock_bench 的 pipe 条件语义）。

    ``engine_opt``：``auto`` 取路由首选，或显式引擎名。返回结构化报告 dict
    （route/normalize/translate/inject/compile/verdict + 修复链 + 终态）。
    ``front_matter`` = preamble 前置发射集（None → env/缺省）。
    ``sink`` 收 ``stage``/``translate``/``l2``/``fixloop`` 实况帧——CLI
    ``run`` 挂 ``CliSink``，bench/测试臂 NULL 静默（与重构前一致）。
    """
    report: dict[str, object] = {"work": str(work)}
    route = route_project(work)
    report["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
        "latex209_suspect": route.latex209_suspect,
    }
    sink.event(
        "stage",
        {
            "stage": "route",
            "engines": route.engines,
            "message": f"reject: {route.reject}" if route.reject else "",
        },
    )
    if route.reject:
        report["status"] = "partial"  # 策略拒绝 → partial (F3), reject_at 审计
        report["reject_at"] = "route"
        return report
    main_path = find_main_tex(work)
    if main_path is None:
        sub = classify_no_main(work)
        report["status"] = "partial"
        report["reject_at"] = "route"
        report["route"]["reasons"] = [
            *route.reasons,
            f"no main tex:{sub}" if sub else "no main tex",
        ]
        return report
    main_rel = main_path.relative_to(work).as_posix()
    report["main"] = main_rel

    eng_name = engine_opt if engine_opt != "auto" else route.engines[0]
    report.update(
        pipe_condition(
            work,
            eng_name,
            main_rel,
            timeout,
            translator=translator,
            env_judge=env_judge,
            l2_on=l2_on,
            fixloop_on=fixloop_on,
            l2_max_chunks=l2_max_chunks,
            # 显式 engine 收窄到该引擎——跨引擎换编臂自熄（worker
            # _build_base 同口径：engines = route.engines if auto else
            # [opt_engine]，持久化进 options.route_engines）
            route_engines=route.engines if engine_opt == "auto" else [eng_name],
            front_matter=front_matter,
            sink=sink,
        )
    )
    return report
