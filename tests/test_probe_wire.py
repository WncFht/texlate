"""``target_probe`` 接 worker 编译链：log 事件播报、flags 透传、fail-open。

探针是编译旁路诊断——``_compile_zh``/``_compile_en`` 在 engine 编译前跑
``target_probe``（deps_index 注入面走 ``PipelineWorker(deps_index=...)``），
missing 集与路由信号进 log 事件、``rep.flags`` 透传 ``compile(flags=…)``、
编译后 ``deps_diff`` 对拍权威输入集。本文件用合成 work_dir + 记录型假引擎
断言：探针被调用、missing 依赖进 log、探针崩溃编译照常。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")

from texlate.compile.engine import CompRes
from texlate.compile.fixloop.ctan import TlpdbIndex
from texlate.server.events import EventBus
from texlate.server.store import Store
from texlate.server.worker import PipelineWorker, Secrets, TaskCtx

if TYPE_CHECKING:
    from collections.abc import Iterable

#: minted → ``-shell-escape`` flag；ghostpkg 本地/tlpdb 两空 → missing
_TEX_MINTED = (
    "\\documentclass{article}\n"
    "\\usepackage{minted}\n"
    "\\usepackage{ghostpkg}\n"
    "\\begin{document}\n"
    "Body paragraph long enough to matter.\n"
    "\\end{document}\n"
)

#: pstricks → prefer_engine=xelatex 信号（与默认 tectonic 路由分歧）
_TEX_PSTRICKS = (
    "\\documentclass{article}\n"
    "\\usepackage{pstricks}\n"
    "\\begin{document}\n"
    "Body paragraph long enough to matter.\n"
    "\\end{document}\n"
)

#: ``\\input{sub}`` 本地命中 + ``\\input{ghost}`` 缺失 → inputs 图差分料
_TEX_INPUT = (
    "\\documentclass{article}\n"
    "\\usepackage{amsmath}\n"
    "\\begin{document}\n"
    "Body paragraph long enough to matter.\n"
    "\\input{sub}\n"
    "\\input{ghost}\n"
    "\\end{document}\n"
)


class _ProbeEngine:
    """``engine_factory`` 注入件：记录 ``flags`` 请求 + 可控 ``res.deps``。

    conftest ``FakeEngine`` 不吃 flags/deps 字段——接线断言需要看到
    ``compile(flags=…)`` 实参与权威集差分行为，故自带假引擎。
    """

    name = "probe-fake"

    def __init__(self, deps: list[str] | None = None) -> None:
        """deps=None → 引擎未产依赖记录（authoritative=False 路径）。"""
        self._deps = deps
        self.calls: list[dict[str, object]] = []

    def compile(  # noqa: PLR0913 -- 与 Engine.compile 同签名，kwarg 名是接口
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = 1,  # noqa: ARG002
        timeout: float | None = None,  # noqa: ARG002
        outdir: Path | None = None,  # noqa: ARG002
        sandbox: bool = True,  # noqa: ARG002
        env_extra: dict[str, str] | None = None,  # noqa: ARG002
        best_effort: bool = False,  # noqa: ARG002
        flags: Iterable[str] | None = None,
    ) -> CompRes:
        """写假 pdf 返回 CompRes；``deps`` 按构造参数回填。"""
        pdf = wdir / f"{Path(main).stem}.pdf"
        pdf.write_bytes(b"%PDF-1.4\n% fake pdf for probe-wire tests\n")
        self.calls.append({"wdir": str(wdir), "flags": list(flags or ())})
        return CompRes(
            engine="fake",
            ok=True,
            pdf=pdf,
            pdf_bytes=pdf.stat().st_size,
            rc=0,
            deps=self._deps,
        )


def _ctx(
    tmp_path: Path,
    *,
    index: TlpdbIndex | None = None,
    engine: _ProbeEngine | None = None,
) -> tuple[TaskCtx, PipelineWorker, Store]:
    """最小 TaskCtx + worker：真 Store/EventBus，l2/fixloop 关闭。

    ``options.l2/fixloop=False`` 把修复链两臂钉死——judge 对假 pdf 的
    partial 判定不触发 ``_l2_repair_zh``/``_run_fixloop``（它们要真
    translator/fixloop 环境，非本测试目标）。
    """
    store = Store(tmp_path / "t.db")
    store.open()
    bus = EventBus(store)
    eng = engine or _ProbeEngine()
    worker = PipelineWorker(
        store,
        bus,
        tmp_path,
        engine_factory=lambda _name: eng,
        deps_index=index,
    )
    row = store.create_task(
        task_id="t_probe",
        kind="upload_tex",
        target_lang="zh-CN",
        model="m",
        options={"l2": False, "fixloop": False},
    )
    root = tmp_path / "task"
    ctx = TaskCtx(
        store=store,
        bus=bus,
        task_id="t_probe",
        row=row,
        secrets=Secrets(),
        root=root,
    )
    ctx.main_rel = "main.tex"
    return ctx, worker, store


def _log_lines(store: Store, task_id: str) -> list[str]:
    """``task_events`` 里 type=log 的行文本序列（``_log`` 的落点）。"""
    return [
        str(e["data"]["line"])
        for e in store.events_since(task_id, 0)
        if e["type"] == "log"
    ]


def _zh_tree(ctx: TaskCtx, tex: str) -> None:
    """``zh/`` 最小工程：单 main.tex（``_compile_zh`` copytree 起点）。"""
    ctx.zh_dir.mkdir(parents=True)
    (ctx.zh_dir / "main.tex").write_text(tex, encoding="utf-8")


class TestCompileZhProbe:
    """``_compile_zh`` 侧接线：probe 预扫 + flags 透传 + 编译后差分。"""

    def test_probe_summary_and_missing_logged(self, tmp_path: Path) -> None:
        """article.cls/minted.sty 走 tl_pkg，ghostpkg 两空 → missing=1。"""
        index = TlpdbIndex({"article.cls": ["latex"], "minted.sty": ["minted"]})
        ctx, worker, store = _ctx(tmp_path, index=index, engine=_ProbeEngine())
        _zh_tree(ctx, _TEX_MINTED)
        ok = worker._compile_zh(ctx)  # noqa: SLF001 -- 接线点即被测对象
        assert ok
        lines = _log_lines(store, ctx.task_id)
        summary = [line for line in lines if line.startswith("probe: deps=")]
        assert summary, f"probe 摘要行缺席: {lines}"
        assert "missing=1" in summary[0]
        assert "tl_pkg=2" in summary[0]
        assert "flags=-shell-escape" in summary[0]
        assert any("ghostpkg.sty" in line for line in lines)

    def test_probe_flags_reach_engine(self, tmp_path: Path) -> None:
        """``rep.flags`` 透传 ``compile(flags=…)``——minted 的 -shell-escape。"""
        eng = _ProbeEngine()
        ctx, worker, _store = _ctx(tmp_path, index=TlpdbIndex({}), engine=eng)
        _zh_tree(ctx, _TEX_MINTED)
        worker._compile_zh(ctx)  # noqa: SLF001
        assert eng.calls
        assert eng.calls[0]["flags"] == ["-shell-escape"]

    def test_probe_prefer_engine_divergence_logged(self, tmp_path: Path) -> None:
        """pstricks → prefer_engine=xelatex 与 ctx.engine_name=tectonic 分歧记行。"""
        ctx, worker, store = _ctx(tmp_path, index=TlpdbIndex({}), engine=_ProbeEngine())
        _zh_tree(ctx, _TEX_PSTRICKS)
        worker._compile_zh(ctx)  # noqa: SLF001
        lines = _log_lines(store, ctx.task_id)
        assert any("prefer_engine=xelatex" in line for line in lines)
        assert any("不一致" in line and "tectonic" in line for line in lines)

    def test_deps_diff_authoritative(self, tmp_path: Path) -> None:
        """``res.deps`` 权威集在场 → seen/unread/undeclared 聚合行 + missing 复核。"""
        eng = _ProbeEngine(deps=["main.tex", "sub.tex", "texlive/amsmath.sty"])
        ctx, worker, store = _ctx(tmp_path, index=TlpdbIndex({}), engine=eng)
        _zh_tree(ctx, _TEX_INPUT)
        (ctx.zh_dir / "sub.tex").write_text(
            "Sub file body paragraph.\n", encoding="utf-8"
        )
        worker._compile_zh(ctx)  # noqa: SLF001
        lines = _log_lines(store, ctx.task_id)
        diff = [line for line in lines if line.startswith("probe diff:")]
        assert diff, f"差分行缺席: {lines}"
        assert "seen=2" in diff[0]  # main.tex + sub.tex
        assert "undeclared=1" in diff[0]  # texlive/amsmath.sty 期望集外
        # ghost.tex 未被权威集记录 → 真缺失；amsmath.sty 被记录 → 路径/时序
        assert any("ghost.tex=unseen" in line for line in lines)
        assert any("amsmath.sty=recorded" in line for line in lines)

    def test_deps_diff_not_authoritative(self, tmp_path: Path) -> None:
        """``res.deps=None`` → 差分不可判行（非全缺误报）。"""
        ctx, worker, store = _ctx(
            tmp_path, index=TlpdbIndex({}), engine=_ProbeEngine(deps=None)
        )
        _zh_tree(ctx, _TEX_MINTED)
        worker._compile_zh(ctx)  # noqa: SLF001
        lines = _log_lines(store, ctx.task_id)
        assert any("差分不可判" in line for line in lines)

    def test_probe_crash_fail_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """探针崩溃 → 编译照常、无 flags、crash 记行（绝不阻塞编译）。"""
        import texlate.server.worker as worker_mod  # noqa: PLC0415

        def _boom(*_a: object, **_k: object) -> None:
            msg = "probe exploded"
            raise RuntimeError(msg)

        monkeypatch.setattr(worker_mod, "target_probe", _boom)
        eng = _ProbeEngine()
        ctx, worker, store = _ctx(tmp_path, engine=eng)
        _zh_tree(ctx, _TEX_MINTED)
        ok = worker._compile_zh(ctx)  # noqa: SLF001
        assert ok
        assert eng.calls
        assert eng.calls[0]["flags"] == []
        lines = _log_lines(store, ctx.task_id)
        assert any("probe crashed" in line for line in lines)
        assert not any(line.startswith("probe diff:") for line in lines)


class TestCompileEnProbe:
    """``_compile_en`` 侧接线：base/ 树同款预扫（en 失败归因的 missing 情报）。"""

    def test_en_side_probe_and_flags(self, tmp_path: Path) -> None:
        eng = _ProbeEngine()
        ctx, worker, store = _ctx(tmp_path, index=TlpdbIndex({}), engine=eng)
        ctx.base_dir.mkdir(parents=True)
        (ctx.base_dir / "main.tex").write_text(_TEX_MINTED, encoding="utf-8")
        worker._compile_en(ctx)  # noqa: SLF001
        lines = _log_lines(store, ctx.task_id)
        assert any(line.startswith("probe: deps=") for line in lines)
        assert any("ghostpkg.sty" in line for line in lines)
        assert eng.calls[0]["flags"] == ["-shell-escape"]
        assert (ctx.root / "en.pdf").is_file()

    def test_en_skip_when_pdf_registered(self, tmp_path: Path) -> None:
        """en_pdf 已登记 → 整段跳过，探针不跑（幂等面）。"""
        eng = _ProbeEngine()
        ctx, worker, store = _ctx(tmp_path, index=TlpdbIndex({}), engine=eng)
        ctx.base_dir.mkdir(parents=True)
        (ctx.base_dir / "main.tex").write_text(_TEX_MINTED, encoding="utf-8")
        (ctx.root / "en.pdf").write_bytes(b"%PDF-1.4\nfake\n")
        worker._register(ctx, "en_pdf", "en.pdf")  # noqa: SLF001
        worker._compile_en(ctx)  # noqa: SLF001
        assert eng.calls == []
        lines = _log_lines(store, ctx.task_id)
        assert not any(line.startswith("probe:") for line in lines)


class TestProbeIndexReuse:
    """``deps_index`` 注入面：显式索引透传探针（tl_pkg 命中路径）。"""

    def test_tl_pkg_hit_via_injected_index(self, tmp_path: Path) -> None:
        """注入表命中 → tl_pkg 计数 + tl_packages 进 notes 行。"""
        index = TlpdbIndex({"amsmath.sty": ["amsmath"]})
        ctx, worker, store = _ctx(tmp_path, index=index, engine=_ProbeEngine())
        _zh_tree(ctx, _TEX_INPUT)
        worker._compile_zh(ctx)  # noqa: SLF001
        lines = _log_lines(store, ctx.task_id)
        summary = [line for line in lines if line.startswith("probe: deps=")]
        assert summary
        assert "tl_pkg=1" in summary[0]
        assert any("amsmath" in line and "tl_pkg" in line for line in lines)
