r"""e2e 修复链接线——fixloop / L2 回灌 / engine_flags / env judge / 抄回修复。

与 ``test_e2e.py``（golden-path 直测）分工：本文件只覆盖**编译失败之后**的
编排——``ScriptedEngine`` 按剧本逐次出 log/pdf，断言报告结构与盘上副作用。
全离线：引擎/翻译器/judge 的 pdftotext 侧效果全部替身化。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from conftest import judge_mod, make_project

from texlate import e2e, repair_l2
from texlate.latex.model import Chunk, Span
from texlate.xlat.pipeline import ChunkIn, MockTranslator, XlatPipeline

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.compile.engine import CompRes

#: 未知 env（静态表外）——env judge 的目标输入
_UNK_ENV_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "\\section{Intro}\n"
    "\\begin{mybox}\n"
    "Some prose inside a custom box environment that the segmenter does not\n"
    "know about, so it falls open and the body becomes a chunk.\n"
    "\\end{mybox}\n"
    "\\end{document}\n"
)


@pytest.fixture(autouse=True)
def _clean_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    """三个开关 env 全部钉成缺省——本机/CI 环境差异免疫。"""
    for k in ("TEXLATE_NO_FIXLOOP", "TEXLATE_NO_L2", "TEXLATE_ENV_JUDGE"):
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------- 剧本引擎


def _fail_unattributable(_w: Path, _m: str) -> tuple[str, bool]:
    """不可归因的失败 log（无文件栈、无 ``l.NNN``）——L2 拿不到 chunk。"""
    return ("! Undefined control sequence.\n<argument> \\oops\n", False)


def _fail_at_last_zh(wdir: Path, main: str) -> tuple[str, bool]:
    """失败 log：file:line: 直指最后一处 ``这是译文`` 所在行（第二段译文）。"""
    lines = (wdir / main).read_text(encoding="utf-8").splitlines()
    n = max(i for i, ln in enumerate(lines) if "这是译文" in ln) + 1
    return (f"{main}:{n}: ! Undefined control sequence.\n", False)


def _clean(_w: Path, _m: str) -> tuple[str, bool]:
    """干净 log + pdf。"""
    return ("This is fake\nOutput written on disk.\n", True)


class ScriptedEngine:
    """按剧本出 log/pdf 的假引擎；第 n 次 ``compile`` 消费 ``scripts[n]``。

    剧本条目 = ``callable(wdir, main) -> (log_text, write_pdf)``——动态条目
    可在 splice 后读盘找译文行号。满足 fixloop 的 Engine Protocol 面
    （caps/probe/install/filemap 全空实现）。
    """

    def __init__(self, name: str, scripts: list[object]) -> None:
        """``scripts`` 用尽后重复末条。"""
        self.name = name
        self.caps: frozenset[str] = frozenset()
        self.scripts = list(scripts)
        self.calls: list[dict[str, object]] = []
        self.ctor_kwargs: dict[str, object] = {}

    def compile(  # noqa: PLR0913 -- 与 Engine.compile 同签名
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = 1,
        timeout: float | None = None,
        outdir: Path | None = None,  # noqa: ARG002
        sandbox: bool = True,  # noqa: ARG002
        env_extra: dict[str, str] | None = None,  # noqa: ARG002
        best_effort: bool = False,  # noqa: ARG002 -- fixloop salvage 会传
        flags: list[str] | None = None,
        should_cancel: Callable[[], bool] | None = None,  # noqa: ARG002
    ) -> CompRes:
        """按剧本写 ``<stem>.log``（+可选 pdf）→ CompRes。"""
        from texlate.compile.engine import CompRes  # noqa: PLC0415
        from texlate.compile.loginfo import parse_log  # noqa: PLC0415

        i = min(len(self.calls), len(self.scripts) - 1)
        spec = self.scripts[i]
        log_text, make_pdf = spec(wdir, main) if callable(spec) else spec
        stem = Path(main).stem
        log = wdir / f"{stem}.log"
        log.write_text(log_text, encoding="utf-8")
        pdf: Path | None = None
        pdf_bytes = 0
        if make_pdf:
            pdf = wdir / f"{stem}.pdf"
            pdf.write_bytes(b"%PDF-1.4\n% fake\n")
            pdf_bytes = pdf.stat().st_size
        self.calls.append(
            {"main": main, "timeout": timeout, "passes": passes, "flags": flags}
        )
        return CompRes(
            engine=self.name,
            ok=True,
            pdf=pdf,
            pdf_bytes=pdf_bytes,
            log_path=log,
            log=parse_log(log_text),
            log_text=log_text,
            rc=0,
            passes=passes,
            seconds=0.01,
        )

    def probe_file(self, fname: str, *, cwd: Path | None = None) -> None:
        """全 miss——fixloop scan_install 走 install_file 分支。"""

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:  # noqa: ARG002
        """装不上——advisories 记账但不阻塞。"""
        return False

    def rebuild_fontmaps(self) -> None:
        """noop。"""

    def filemap(self, fname: str) -> list[str]:  # noqa: ARG002
        """无索引。"""
        return []


@pytest.fixture
def engines(monkeypatch: pytest.MonkeyPatch) -> dict[str, ScriptedEngine]:
    """``e2e.engine_for`` 换剧本表 + judge CJK 计数钉 500。测试先注册引擎再跑。"""
    table: dict[str, ScriptedEngine] = {}

    def factory(name: str, **kwargs: object) -> ScriptedEngine:
        eng = table[name]
        if not eng.ctor_kwargs:
            eng.ctor_kwargs = kwargs
        return eng

    monkeypatch.setattr(e2e, "engine_for", factory)
    # 包级 re-export 的 judge 函数遮蔽同名子模块属性路径——按模块对象打
    monkeypatch.setattr(judge_mod(), "pdf_text_stats", lambda _p: (500, 0))
    return table


# ---------------------------------------------------------------- fixloop


def test_fixloop_runs_on_fail_and_recovers(
    tmp_path: Path, engines: dict[str, ScriptedEngine]
) -> None:
    """首编 fail（不可归因）→ L2 无命中直通 → fixloop r1 clean → 终态 clean。"""
    work = make_project(tmp_path / "p")
    engines["xelatex"] = ScriptedEngine("xelatex", [_fail_unattributable, _clean])

    report = e2e.pipeline_run(work, "xelatex", timeout=30.0)

    assert report["status"] == "clean"
    assert report["l2"]["note"] == "no chunk-level attribution"
    fl = report["fixloop"]
    assert fl["enabled"] is True
    assert fl["verdict"] == "clean"
    # rounds 视图带 {cat,pay,rule,result} 合并字段
    assert fl["rounds"][0]["pdf"] is True
    assert "cat" in fl["rounds"][0]
    assert "rule" in fl["rounds"][0]
    assert report["verdict"]["status"] == "clean"
    assert len(engines["xelatex"].calls) == 3  # noqa: PLR2004 -- 首编 + fixloop r1 (p1 探 + 全遍终编)
    # fixloop 分类轮 p1、收敛终编轮 passes=None 走引擎自适应门
    # (compile_passes=2 ≤ MAX_PASSES → rerun-hint 才升遍; perf-fix#1)
    assert [c["passes"] for c in engines["xelatex"].calls[1:]] == [1, None]


def test_fixloop_disabled_by_env(
    tmp_path: Path,
    engines: dict[str, ScriptedEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``TEXLATE_NO_FIXLOOP=1`` → fixloop 不跑，终态保持 fail。"""
    work = make_project(tmp_path / "p")
    engines["xelatex"] = ScriptedEngine("xelatex", [_fail_unattributable])
    monkeypatch.setenv("TEXLATE_NO_FIXLOOP", "1")

    report = e2e.pipeline_run(work, "xelatex", timeout=30.0)

    assert report["status"] == "fail"
    assert report["fixloop"] == {"enabled": False, "reason": "TEXLATE_NO_FIXLOOP"}
    assert len(engines["xelatex"].calls) == 1  # 只有首编


def test_fixloop_crash_does_not_atexit(
    tmp_path: Path, engines: dict[str, ScriptedEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    """fixloop 自身崩 → 记 error、终态仍是修复前 verdict（修复臂不毁报告）。"""
    work = make_project(tmp_path / "p")
    engines["xelatex"] = ScriptedEngine("xelatex", [_fail_unattributable])

    def boom(*_a: object, **_kw: object) -> dict:
        msg = "simulated fixloop crash"
        raise RuntimeError(msg)

    monkeypatch.setattr("texlate.repair.fixloop", boom)
    report = e2e.pipeline_run(work, "xelatex", timeout=30.0)

    assert report["status"] == "fail"
    assert "RuntimeError" in report["fixloop"]["error"]


# ---------------------------------------------------------------- L2 回灌


def test_l2_retranslate_then_recompile(
    tmp_path: Path, engines: dict[str, ScriptedEngine]
) -> None:
    """file:line: 命中译文 chunk → 重译 → resplice → 重编 clean → fixloop 不跑。"""
    work = make_project(tmp_path / "p")
    engines["xelatex"] = ScriptedEngine("xelatex", [_fail_at_last_zh, _clean])
    tr = MockTranslator()

    report = e2e.pipeline_run(work, "xelatex", timeout=30.0, translator=tr)

    assert report["status"] == "clean"
    l2 = report["l2"]
    assert l2["enabled"] is True
    assert l2["hits"], "log 错误应归因到 chunk"
    assert l2["retranslated"] == sorted(l2["hits"])
    assert l2["recompiled"] == "clean"
    assert "fixloop" not in report  # 已 clean 不进 fixloop
    # 重译请求确实带 [compile_error] 反馈字段
    fb_calls = [c for c in tr.calls if "[compile_error]" in c["user"]]
    assert len(fb_calls) == len(l2["retranslated"])


def test_l2_fallback_to_source(
    tmp_path: Path, engines: dict[str, ScriptedEngine]
) -> None:
    """重译产物仍不过 L0 → 该块回落原文（spec：再不过 → fallback 原文）。"""

    class BadFix(MockTranslator):
        async def translate(
            self,
            *,
            system: str,
            user: str,
            temperature: float,
            max_tokens: int,
            response_format: dict[str, str] | None = None,
        ) -> str:
            if "[compile_error]" in user:
                return "结果 [[MATH_999]] 残留"  # 多出幻觉 token → L0 必挂
            return await super().translate(
                system=system,
                user=user,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )

    work = make_project(tmp_path / "p")
    engines["xelatex"] = ScriptedEngine("xelatex", [_fail_at_last_zh, _clean])
    report = e2e.pipeline_run(work, "xelatex", timeout=30.0, translator=BadFix())

    l2 = report["l2"]
    assert l2["reverted_l0"], "L0 仍败的块应回落原文"
    assert l2["retranslated"] == []
    assert report["status"] == "clean"
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "paragraph" in out  # 回落后原文段回来


def test_l2_fallback_verified_fixloop_off(
    tmp_path: Path, engines: dict[str, ScriptedEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    """fixloop 关闭条件路径：回落态仍补裸编验证——zh-src.zip 不装未验证树。

    洞案（fallback_unverified 侦察）：旧码回落后置 flag 靠 fixloop 代验，
    ``TEXLATE_NO_FIXLOOP`` 时交付树零验证。新码回落后恒裸编并把第三态
    verdict 当终态。
    """
    work = make_project(tmp_path / "p")
    engines["xelatex"] = ScriptedEngine(
        "xelatex", [_fail_at_last_zh, _fail_at_last_zh, _clean]
    )
    monkeypatch.setenv("TEXLATE_NO_FIXLOOP", "1")

    report = e2e.pipeline_run(work, "xelatex", timeout=30.0)

    l2 = report["l2"]
    assert l2["fallback_src"], "重译态仍被点名的块应回落原文"
    assert l2["fallback_verdict"] == "clean", "回落态裸编应判 clean"
    assert "fallback_unverified" not in l2
    # 回落态即交付树——其 verdict 就是终态
    assert report["status"] == "clean"
    # 首编 + 重译态重编 + 回落态裸编 = 3 次
    assert len(engines["xelatex"].calls) == 3  # noqa: PLR2004


def test_l2_cap_limits_retranslate(
    tmp_path: Path, engines: dict[str, ScriptedEngine]
) -> None:
    """per-doc 上限：``l2_max_chunks=1`` 时多个命中也只重译第一块。"""
    work = make_project(tmp_path / "p")
    engines["xelatex"] = ScriptedEngine("xelatex", [_fail_at_last_zh, _clean])
    tr = MockTranslator()

    report = e2e.pipeline_run(
        work, "xelatex", timeout=30.0, translator=tr, l2_max_chunks=1
    )
    l2 = report["l2"]
    assert len(l2["retranslated"]) <= 1
    assert len([c for c in tr.calls if "[compile_error]" in c["user"]]) <= 1


# ---------------------------------------------------------------- engine_flags


def test_engine_flags_cross_engine_consumed(
    tmp_path: Path, engines: dict[str, ScriptedEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    """fixloop 产 engine_flags + tectonic 仍挂 → 换 xelatex 重编取优。"""
    work = make_project(tmp_path / "p")
    engines["tectonic"] = ScriptedEngine("tectonic", [_fail_unattributable])
    engines["xelatex"] = ScriptedEngine("xelatex", [_clean])

    def fake_fixloop(proj, eng, **kw) -> dict:  # noqa: ANN001, ANN003, ARG001
        return {
            "verdict": "unfixable:minted_froz",
            "main": "main.tex",
            "rounds": [
                {
                    "round": 1,
                    "category": "minted_frozencache",
                    "payload": "frozencache",
                    "pdf": False,
                    "n_errors": 1,
                }
            ],
            "actions": [
                {
                    "round": 1,
                    "rule": "minted_frozencache",
                    "detail": "rewrite + engine_flags",
                }
            ],
            "advisories": [],
            "installed": [],
            "engine_flags": ["-shell-escape"],
            "engine_flags_dropped": ["-shell-escape"],  # tectonic --untrusted 下不收
            "log_excerpt": "! stub",
        }

    monkeypatch.setattr("texlate.repair.fixloop", fake_fixloop)
    report = e2e.pipeline_run(work, "auto", timeout=30.0)

    fl = report["fixloop"]
    assert fl["engine_flags"] == ["-shell-escape"]
    assert fl["flags_unapplied"] is True
    assert fl["cross_engine"]["engine"] == "xelatex"
    assert fl["rounds"][0]["cat"] == "minted_frozencache"
    assert fl["rounds"][0]["rule"] == "minted_frozencache"
    assert report["status"] == "clean"  # xelatex 臂更优 → 采用
    assert any("engine_flags" in n for n in report["verdict"]["notes"])
    # 换编把全部请求 flag 经 seam 带给 xelatex（tectonic dropped 的项在内）
    assert engines["xelatex"].calls[-1]["flags"] == ["-shell-escape"]


@pytest.mark.parametrize(
    ("engine_opt", "expect_cross"), [("auto", True), ("tectonic", False)]
)
def test_route_engines_narrowed_by_explicit_engine(
    tmp_path: Path,
    engines: dict[str, ScriptedEngine],
    monkeypatch: pytest.MonkeyPatch,
    engine_opt: str,
    expect_cross: bool,  # noqa: FBT001 -- parametrize 差分臂
) -> None:
    """显式 ``--engine`` → ``route_engines`` 收窄为该引擎，跨引擎换编臂自熄。

    worker ``_build_base`` 同口径（``engines = route.engines if opt_engine ==
    "auto" else [opt_engine]``，parse.py:71-75）：route 候选里虽有 xelatex，
    dropped engine_flags 也不许把显式选型换掉；auto 则保留全量候选。
    """
    work = make_project(tmp_path / "p")
    engines["tectonic"] = ScriptedEngine("tectonic", [_fail_unattributable])
    engines["xelatex"] = ScriptedEngine("xelatex", [_clean])

    def fake_fixloop(proj, eng, **kw) -> dict:  # noqa: ANN001, ANN003, ARG001
        return {
            "verdict": "unfixable:minted_froz",
            "engine_flags": ["-shell-escape"],
            "engine_flags_dropped": ["-shell-escape"],  # tectonic 不收 → 换编原料
        }

    monkeypatch.setattr("texlate.repair.fixloop", fake_fixloop)
    report = e2e.pipeline_run(work, engine_opt, timeout=30.0)

    fl = report["fixloop"]
    assert fl["engine_flags_dropped"] == ["-shell-escape"]
    if expect_cross:
        assert fl["cross_engine"]["engine"] == "xelatex"
        assert engines["xelatex"].calls
    else:
        assert "cross_engine" not in fl
        assert engines["xelatex"].calls == []


@pytest.mark.parametrize(
    ("engine_opt", "expect_cross"), [("auto", True), ("tectonic", False)]
)
def test_reject_route_cross_engine_consumed(
    tmp_path: Path,
    engines: dict[str, ScriptedEngine],
    monkeypatch: pytest.MonkeyPatch,
    engine_opt: str,
    expect_cross: bool,  # noqa: FBT001 -- parametrize 差分臂
) -> None:
    """``reject_route=xelatex`` cell 令牌 → 跨引擎臂换编（无 dropped flag 也触发）。

    t_c9249919e8d7a13f 实证面：biber/biblatex bcf 错配是 tectonic bundle 内
    无解的工具链硬墙——fixloop 发 ``REJECT: route=xelatex``，repair 臂拿
    令牌换编取优；``verdict reject:*`` rank 0，xelatex 任何 ≥fail 判定即
    adopted。显式 engine= 收窄 route_engines 时臂自熄（尊重显式选型）。
    """
    work = make_project(tmp_path / "p")
    engines["tectonic"] = ScriptedEngine("tectonic", [_fail_unattributable])
    engines["xelatex"] = ScriptedEngine("xelatex", [_clean])

    def fake_fixloop(proj, eng, **kw) -> dict:  # noqa: ANN001, ANN003, ARG001
        return {
            "verdict": "reject:biber_biblatex_skew_route",
            "reject_route": "xelatex",
            "engine_flags": [],
            "engine_flags_dropped": [],
        }

    monkeypatch.setattr("texlate.repair.fixloop", fake_fixloop)
    report = e2e.pipeline_run(work, engine_opt, timeout=30.0)

    fl = report["fixloop"]
    if expect_cross:
        assert fl["cross_engine"]["engine"] == "xelatex"
        assert fl["cross_engine"]["adopted"] is True
        assert report["status"] == "clean"  # xelatex 臂更优 → 采用
    else:
        assert "cross_engine" not in fl
        assert engines["xelatex"].calls == []


def test_reject_verdict_without_route_no_cross(
    tmp_path: Path, engines: dict[str, ScriptedEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    """裸 ``reject:*``（无 route 令牌）→ 不触发跨引擎臂，死路标签原样。"""
    work = make_project(tmp_path / "p")
    engines["tectonic"] = ScriptedEngine("tectonic", [_fail_unattributable])
    engines["xelatex"] = ScriptedEngine("xelatex", [_clean])

    def fake_fixloop(proj, eng, **kw) -> dict:  # noqa: ANN001, ANN003, ARG001
        return {"verdict": "reject:latex209_reject", "engine_flags_dropped": []}

    monkeypatch.setattr("texlate.repair.fixloop", fake_fixloop)
    report = e2e.pipeline_run(work, "auto", timeout=30.0)

    assert "cross_engine" not in report["fixloop"]
    assert engines["xelatex"].calls == []


def test_fixloop_ruleset_receives_presplice_baseline(
    tmp_path: Path,
    engines: dict[str, ScriptedEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fixloop ruleset 的 ``restore_support_from_src`` 拿到 ``baseline_dir``。

    worker 注入 ``ctx.base_dir``（compile.py:95-110）；e2e 原地翻译无常驻
    base 树，baseline = normalize 后/翻译前的 pristine 快照（
    ``_baseline_snapshot``），fixloop 收敛后 tempdir 即回收。
    """
    work = make_project(tmp_path / "p")
    engines["xelatex"] = ScriptedEngine("xelatex", [_fail_unattributable])
    seen: dict[str, str] = {}

    def fake_fixloop(proj, eng, **kw) -> dict:  # noqa: ANN001, ANN003, ARG001
        for rule in kw["ruleset"].rules:
            act = rule.raw.get("action") or {}
            if act.get("function") == "restore_support_from_src":
                base = Path((act.get("params") or {})["baseline_dir"])
                seen["dir"] = str(base)
                seen["main"] = (base / "main.tex").read_text(encoding="utf-8")
        return {"verdict": "unfixable:probe"}

    monkeypatch.setattr("texlate.repair.fixloop", fake_fixloop)
    report = e2e.pipeline_run(work, "xelatex", timeout=30.0)

    assert report["fixloop"]["verdict"] == "unfixable:probe"
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "这是译文" in out  # 工作树已原地 splice
    assert "longer paragraph" in seen["main"]  # baseline 是译前 pristine 快照
    assert "这是译文" not in seen["main"]
    assert not Path(seen["dir"]).exists()  # TemporaryDirectory 已回收


# ---------------------------------------------------------------- env judge


class _JudgeVeto(MockTranslator):
    """env judge 一律 False（system 含 env-judge 标志句）→ 其余正常 mock。"""

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        if "whether it should be translated" in system:
            return "False"
        return await super().translate(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )


def test_env_judge_default_off(tmp_path: Path) -> None:
    """默认不开：未知 env 照常翻，stats 里 enabled=False。"""
    work = make_project(tmp_path / "p", main=_UNK_ENV_TEX)
    stats = e2e.translate_tree(work)
    assert stats["env_judge"]["enabled"] is False
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "这是译文" in out


def test_env_judge_reverts_false(tmp_path: Path) -> None:
    """开启后 judge=False 的未知 env 块回落原文，不进 splice。"""
    work = make_project(tmp_path / "p", main=_UNK_ENV_TEX)
    stats = e2e.translate_tree(work, translator=_JudgeVeto(), env_judge=True)
    ej = stats["env_judge"]
    assert ej["enabled"] is True
    assert ej["asked"] >= 1
    assert ej["reverted"], "judge=False 的块应记名"
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "custom box environment" in out  # 原文回来了


class _JudgeBadReturn(MockTranslator):
    """translate 返回非 str——``parse_env_judge_answer`` 必崩的形态。"""

    async def translate(
        self,
        *,
        system: str,  # noqa: ARG002
        user: str,  # noqa: ARG002
        temperature: float,  # noqa: ARG002
        max_tokens: int,  # noqa: ARG002
        response_format: dict[str, str] | None = None,  # noqa: ARG002
    ) -> str:
        return None  # type: ignore[return-value] -- 刻意违约测 fail-open


def test_env_judge_bad_answer_fails_open() -> None:
    """judge 调用/解析任何异常都重试到上限后 fail-open True——旁路臂
    不许把怪应答炸成管线崩溃（worker 复用同一 ``env_judge_all``）。"""
    pipe = XlatPipeline(_JudgeBadReturn())
    chunk = Chunk(id=0, content="body", context="para", span=Span(0, 4))
    assert asyncio.run(repair_l2._env_judge_one(pipe, chunk, "mybox")) is True  # noqa: SLF001


# ---------------------------------------------------------------- 抄回修复


class _CopyTranslator:
    """把 [[MATH_1]] 的受保护原文直接抄回译文（recover_copied_tokens 的目标形态）。"""

    async def translate(
        self,
        *,
        system: str,  # noqa: ARG002
        user: str,  # noqa: ARG002
        temperature: float,  # noqa: ARG002
        max_tokens: int,  # noqa: ARG002
        response_format: dict[str, str] | None = None,
    ) -> str:
        if response_format is not None:
            # slots 兜底路径：槽值里仍抄 fragment（凑数即可，到不了这步）
            return json.dumps({"⟪S0000⟫": "x", "⟪S0001⟫": "x"}, ensure_ascii=False)
        return "见 $x^2$ 如上"  # $x^2$ = [[MATH_1]] 的 fragment


def test_recover_copied_tokens_wired() -> None:
    """ph_fragments 带上 → 抄回原文在 validate 前换回 token → ok。"""
    c = ChunkIn(
        "0:0",
        "见 [[MATH_1]] 如上",
        ph_fragments={"[[MATH_1]]": "$x^2$"},
    )
    res = asyncio.run(XlatPipeline(_CopyTranslator()).run([c]))
    assert res[0].status == "ok"
    assert res[0].translation == "见 [[MATH_1]] 如上"
    assert any("recovered copied placeholders" in w for w in res[0].warnings)


def test_recover_copied_tokens_unarmed_without_fragments() -> None:
    """不带 ph_fragments → 修复臂不启用：同输入不再一发过（阶梯降级/三振）。"""
    c = ChunkIn("0:0", "见 [[MATH_1]] 如上")  # 无 ph_fragments
    res = asyncio.run(XlatPipeline(_CopyTranslator()).run([c]))
    assert res[0].status != "ok"


# ---------------------------------------------------------------- ToUnicode 注入


def test_tounicode_embed_after_clean(
    tmp_path: Path,
    engines: dict[str, ScriptedEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """clean 落地 → 对最终 ``<stem>.pdf`` 调一次 embed，计数进报告。"""
    work = make_project(tmp_path / "p")
    engines["xelatex"] = ScriptedEngine("xelatex", [_clean])
    calls: list[Path] = []

    def spy(pdf: Path) -> int:
        calls.append(pdf)
        return 2

    monkeypatch.setattr(e2e, "embed_cjk_mappings", spy)
    report = e2e.pipeline_run(work, "xelatex", timeout=30.0)

    assert report["status"] == "clean"
    assert calls == [work / "main.pdf"]
    assert report["tounicode_fonts"] == 2  # noqa: PLR2004 -- spy 钉值


def test_tounicode_embed_once_after_fixloop(
    tmp_path: Path,
    engines: dict[str, ScriptedEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """修复链收敛后才注：首编 fail → fixloop r1 clean → embed 仍只调一次。"""
    work = make_project(tmp_path / "p")
    engines["xelatex"] = ScriptedEngine("xelatex", [_fail_unattributable, _clean])
    calls: list[Path] = []
    monkeypatch.setattr(e2e, "embed_cjk_mappings", lambda pdf: calls.append(pdf) or 1)

    report = e2e.pipeline_run(work, "xelatex", timeout=30.0)

    assert report["status"] == "clean"
    assert len(engines["xelatex"].calls) == 3  # noqa: PLR2004 -- 首编 + fixloop r1 (p1 探 + 全遍终编)
    assert calls == [work / "main.pdf"]
    assert report["tounicode_fonts"] == 1


def test_tounicode_skipped_without_pdf(
    tmp_path: Path,
    engines: dict[str, ScriptedEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全链无 pdf 产出 → embed 不调、报告无 tounicode_fonts 键。"""
    work = make_project(tmp_path / "p")
    engines["xelatex"] = ScriptedEngine("xelatex", [_fail_unattributable])
    calls: list[Path] = []
    monkeypatch.setattr(e2e, "embed_cjk_mappings", lambda pdf: calls.append(pdf) or 1)

    report = e2e.pipeline_run(work, "xelatex", timeout=30.0)

    assert calls == []
    assert "tounicode_fonts" not in report


def test_tounicode_embed_best_effort(
    tmp_path: Path, engines: dict[str, ScriptedEngine]
) -> None:
    """真 embed 在假 pdf 字节上崩 → best-effort 壳吞掉，管线终态不受拖累。"""
    work = make_project(tmp_path / "p")
    engines["xelatex"] = ScriptedEngine("xelatex", [_clean])

    report = e2e.pipeline_run(work, "xelatex", timeout=30.0)

    assert report["status"] == "clean"
    assert report["tounicode_fonts"] == 0
