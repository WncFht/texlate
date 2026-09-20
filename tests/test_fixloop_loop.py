"""fixloop 主循环端到端单测 —— 合成 log + mock engine (不跑真编译)。

MockEngine 对齐 impl-compile ``compile/engine.py`` 的 CompRes/Engine 字段名
(pdf: Path|None / has_pdf / pdf_bytes / seconds / stdout_tail / caps frozenset),
顺带回归 _probe(cwd=) / _report_of(stdout_tail) 适配层。
"""

import threading
import time
from collections.abc import Iterable
from pathlib import Path

import regex

from texlate.compile.ctan import CtanFetcher
from texlate.compile.fixloop import Ruleset, actions, builtins, fixloop
from texlate.compile.fixloop.engine import (
    LoopCtx,
    _dep_stems,
    _report_of,
    find_main_tex,
)
from texlate.compile.logparse import ErrReport

CLEAN_LOG = "This is pdfTeX\nOutput written on main.pdf (1 page).\n"
MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nhi\n\\end{document}\n"


class MockRes:
    """impl CompRes 的 duck-type 替身 (compile/engine.py:56)。"""

    def __init__(self, wdir: Path, main: str, spec: dict | str) -> None:
        if isinstance(spec, str):
            spec = {"log": spec}
        stem = Path(main).stem
        self.log_path = wdir / f"{stem}.log"
        self.log_path.write_text(spec.get("log", ""), encoding="utf-8")
        if spec.get("wipe_pdf"):  # 镜像真引擎 stale-unlink (compile/engine.py:948)
            (wdir / f"{stem}.pdf").unlink(missing_ok=True)
        self.pdf = wdir / f"{stem}.pdf" if spec.get("pdf") else None
        if self.pdf is not None:
            self.pdf.write_bytes(b"%PDF-1.4 fake")
        if spec.get("aux") is not None:  # 模拟被杀编译驻留的 aux
            (wdir / f"{stem}.aux").write_text(spec["aux"], encoding="utf-8")
        self.pdf_bytes = self.pdf.stat().st_size if self.pdf else 0
        self.timed_out = bool(spec.get("timed_out"))
        #: 镜像 CompRes.killed_signal (任一 pass 被信号杀死记信号号)。
        self.killed_signal = spec.get("killed_signal")
        #: 镜像 CompRes.rc (末 pass 退出码; 驱动 fatal 形 = rc>0 非信号)。
        self.rc = spec.get("rc")
        self.seconds = 0.05
        self.stdout_tail = spec.get("tail", "")
        #: 镜像 CompRes.log_text (编译期已读 .log 原文)——缺省 "" 走文件读。
        self.log_text = spec.get("log_text", "")

    @property
    def has_pdf(self) -> bool:
        return self.pdf is not None and self.pdf_bytes > 0


class MockEngine:
    """script 逐轮吐 spec; 耗尽后重放末条。"""

    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr", "updmap"})

    def __init__(
        self,
        script: list,
        *,
        installable: Iterable[str] = (),
        available: Iterable[str] = (),
    ) -> None:
        self.script = list(script)
        self.installable = set(installable)
        self.available = set(available)
        self.filemap_tbl: dict[str, list[str]] = {}
        self.rounds = 0
        self.fontmaps = 0
        self.install_calls: list[str] = []

    def compile(
        self, wdir: Path, main: str, *, passes: int = 2, **_kw: object
    ) -> MockRes:
        del passes, _kw  # mock 不需要
        i = min(self.rounds, len(self.script) - 1)
        self.rounds += 1
        return MockRes(Path(wdir), main, self.script[i])

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        if cwd is not None and (Path(cwd) / fname).is_file():
            return str(Path(cwd) / fname)
        if fname in self.available:
            return f"/texmf/{fname}"
        return None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del font_related
        self.install_calls.append(fname)
        if fname in self.installable:
            self.available.add(fname)
            return True
        return False

    def rebuild_fontmaps(self) -> bool:
        self.fontmaps += 1
        return True

    def filemap(self, fname: str) -> list[str]:
        return self.filemap_tbl.get(fname, [])


class MockTectonic(MockEngine):
    name = "tectonic"
    caps = frozenset({"bundle"})

    def __init__(self, script: list, **kw: object) -> None:
        super().__init__(script, **kw)
        self.ctan_fetch = None  # fixloop 应注入 CtanFetcher
        self.filemap_index: dict[str, list[str]] = {}


def make_proj(tmp_path: Path, main: str = MAIN_TEX) -> Path:
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    return tmp_path


def mini_rs(
    rules: list[dict], taxonomy: list[dict], loop_cfg: dict | None = None
) -> Ruleset:
    """合成 ruleset: 机械性 verdict 测试用 (stuck/max_rounds 等)。"""
    return Ruleset(
        {
            "version": 1,
            "meta": {
                "loop": {
                    "max_rounds": 4,
                    "stuck_sig_repeat": 3,
                    "clean_err_max": 3,
                    "compile_passes": 2,
                    **(loop_cfg or {}),
                }
            },
            "taxonomy": taxonomy,
            "rules": rules,
        }
    )


# ---------------------------------------------------------------- 基本流转
def test_clean_first_round(tmp_path: Path) -> None:
    cell = fixloop(make_proj(tmp_path), MockEngine([{"log": CLEAN_LOG, "pdf": True}]))
    assert cell["verdict"] == "clean"
    assert len(cell["rounds"]) == 1
    assert cell["final_pdf"] is True
    assert cell["started_fail"] is False


def test_no_main_tex(tmp_path: Path) -> None:
    cell = fixloop(tmp_path, MockEngine([{"log": CLEAN_LOG, "pdf": True}]))
    assert cell["verdict"] == "no_main_tex:garbage"


def test_no_main_tex_plain(tmp_path: Path) -> None:
    """plain-TeX 树 → ``classify_no_main`` 子码落 verdict 后缀。"""
    (tmp_path / "note.tex").write_text("\\magnification=1200\ntext\n\\bye\n")
    cell = fixloop(tmp_path, MockEngine([{"log": CLEAN_LOG, "pdf": True}]))
    assert cell["verdict"] == "no_main_tex:plain_tex"


def test_no_main_tex_ambiguous(tmp_path: Path) -> None:
    r"""``\begin{document}`` 裸存（无 dc/ds）→ 存疑，verdict 不挂子码。"""
    (tmp_path / "body.tex").write_text("\\begin{document}\nx\n\\end{document}\n")
    cell = fixloop(tmp_path, MockEngine([{"log": CLEAN_LOG, "pdf": True}]))
    assert cell["verdict"] == "no_main_tex"


def test_missing_file_install_then_clean(tmp_path: Path) -> None:
    eng = MockEngine(
        [
            {"log": "! LaTeX Error: File `zhnumber.sty' not found.\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable={"zhnumber.sty"},
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert len(cell["rounds"]) == 2  # noqa: PLR2004 - 装包一轮 + clean 一轮
    assert cell["rounds"][0]["category"] == "missing_file"
    assert cell["rounds"][0]["payload"] == "zhnumber.sty"
    assert "zhnumber.sty" in cell["installed"]
    assert any(a["rule"] == "install_file" for a in cell["actions"])


def test_install_unavailable_then_unfixable(tmp_path: Path) -> None:
    eng = MockEngine([{"log": "! LaTeX Error: File `nosuchpkg.sty' not found.\n"}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "unfixable:missing_file"
    assert any("nosuchpkg.sty" in a for a in cell["advisories"])


def test_install_already_present(tmp_path: Path) -> None:
    (tmp_path / "local.sty").write_text("% vendored")
    eng = MockEngine(
        [
            {"log": "! LaTeX Error: File `local.sty' not found.\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ],
        available={"article.cls"},  # 喂饱 static_precheck 扫描, 保持 install_calls 干净
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    detail = next(a["detail"] for a in cell["actions"] if a["rule"] == "install_file")
    assert "already-present" in detail
    assert eng.install_calls == []  # 探测命中即不重装


def test_install_requester_fanout(tmp_path: Path) -> None:
    """pst-all meta-wrapper 实证 (delta): 要求方 ``\\RequirePackage`` 连发一轮补齐。

    file:line 锚 ``./pst-all.sty:25:`` 解出要求方 → 其依赖全表批量装,
    不再一轮撞一个成员包。"""
    (tmp_path / "pst-all.sty").write_text(
        "\\RequirePackage{pst-node}\n\\RequirePackage{pst-arrow}\n"
    )
    eng = MockEngine(
        [
            {"log": "./pst-all.sty:25: LaTeX Error: File `pst-node.sty' not found.\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable={"pst-node.sty", "pst-arrow.sty"},
        available={"article.cls"},
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["payload"] == "pst-node.sty"
    assert set(eng.install_calls) >= {"pst-node.sty", "pst-arrow.sty"}
    detail = next(a["detail"] for a in cell["actions"] if a["rule"] == "install_file")
    assert "requester deps" in detail


def test_install_requester_fanout_tail_preempt(tmp_path: Path) -> None:
    """tail missing_file preempt 抢路由后, 要求方扇出同样生效。"""
    (tmp_path / "pst-all.sty").write_text(
        "\\RequirePackage{pst-node}\n\\RequirePackage{pst-poly}\n"
    )
    tail = (
        "pad line\n" * 12
        + "./pst-all.sty:25: LaTeX Error: File `pst-node.sty' not found.\n"
        + "Enter file name: \n! Emergency stop.\n"
    )
    eng = MockEngine(
        [
            {"log": "! Undefined control sequence.\nl.9 \\foo\n" + tail},
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable={"pst-node.sty", "pst-poly.sty"},
        available={"article.cls"},
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "missing_file"
    assert set(eng.install_calls) >= {"pst-node.sty", "pst-poly.sty"}


def test_install_requester_fanout_popped_fallback(tmp_path: Path) -> None:
    r"""file_stack 滤空时 ``popped_files`` 尾段递补要求方（runaway 先弹肇事帧）。

    ``\@iiiparbox``/``\next`` 扫描族实证（#78 契约）：请求方 ``req.sty``
    在错误行前被 ``)`` 弹进 popped_files，栈里只剩 ``./main.tex``（滤后
    为空）——旧锚序拿不到要求方 → 成员包逐轮撞；popped 递补让扇出一轮补齐。
    """
    (tmp_path / "req.sty").write_text(
        "\\RequirePackage{dep-a}\n\\RequirePackage{dep-b}\n"
    )
    eng = MockEngine(
        [
            {
                "log": "(./main.tex\n(./req.sty\n)\n"
                "! LaTeX Error: File `dep-a.sty' not found.\n"
            },
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable={"dep-a.sty", "dep-b.sty"},
        available={"article.cls"},
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert set(eng.install_calls) >= {"dep-a.sty", "dep-b.sty"}
    detail = next(a["detail"] for a in cell["actions"] if a["rule"] == "install_file")
    assert "requester deps" in detail


def test_install_requester_fanout_input_chain(tmp_path: Path) -> None:
    r"""pstricks-add.tex 实证 (scout-pst): ``\\input`` 行内裸名链扇出。

    generic .tex 的 ``\\ifx\\else \\input stem \\fi`` 顺序链不被
    ``\\RequirePackage`` 行首扫描覆盖——裸名逐轮暴露烧光 max_rounds;
    行内 ``\\input`` 扫描让要求方扇出一轮补齐整条链。要求方落在 texmf
    (生产形态), 由 file:line 锚 + probe fallback 解析——不放 wdir 是刻意的,
    否则 static_precheck 先扫到它就测不到扇出。"""
    texmf = tmp_path / "texmf"
    texmf.mkdir()
    (texmf / "pstricks-add.tex").write_text(
        "\\ifx\\PSTnodesLoaded\\endinput\\else \\input pst-node \\fi\n"
        "\\ifx\\PSTarrowsLoaded\\endinput\\else \\input pst-arrow \\fi\n"
        "% \\input pst-notreal\n"
    )
    (tmp_path / "proj").mkdir()
    proj = make_proj(tmp_path / "proj")

    class TexmfEngine(MockEngine):
        def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
            if cwd is not None and (Path(cwd) / fname).is_file():
                return str(Path(cwd) / fname)
            p = texmf / fname
            return str(p) if p.is_file() else super().probe_file(fname)

        def install_file(self, fname: str, *, font_related: bool = False) -> bool:
            del font_related
            self.install_calls.append(fname)
            if fname in self.installable:
                (texmf / fname).write_text("")
                return True
            return False

    eng = TexmfEngine(
        [
            {"log": "./pstricks-add.tex:27: I can't find file `pst-node'.\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable={"pst-node.tex", "pst-arrow.tex"},
        available={"article.cls"},
    )
    cell = fixloop(proj, eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["payload"] == "pst-node"
    assert set(eng.install_calls) >= {"pst-node.tex", "pst-arrow.tex"}
    assert not any("pst-notreal" in c for c in eng.install_calls)
    # 裸名候选 miss 后 .tex fallback 命中——不出 "no package provides" 噪音
    assert not any("no package provides" in a for a in cell["advisories"])


def test_missing_tfm_installs_and_rebuilds_fontmap(tmp_path: Path) -> None:
    eng = MockEngine(
        [
            {
                "log": "! Font \\iclrtenhv=phvb at 8.0pt not loadable: Metric (TFM) file\n"
            },
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable={"phvb.tfm"},
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert "phvb.tfm" in cell["installed"]
    assert eng.fontmaps == 1  # font_related → rebuild_fontmaps


def test_file_line_error_log_e2e(tmp_path: Path) -> None:
    # impl xelatex 的 -file-line-error log 形态全程跑通
    eng = MockEngine(
        [
            {
                "log": "./main.tex:5: File `xifthen.sty' not found.\nl.5 \\usepackage{xifthen}\n"
            },
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable={"xifthen.sty"},
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["payload"] == "xifthen.sty"


def test_pdftex_prim_guard_e2e(tmp_path: Path) -> None:
    main = "\\documentclass{article}\n\\pdfoutput=1\n\\begin{document}\nx\n\\end{document}\n"
    eng = MockEngine(
        [
            {"log": "! Undefined control sequence.\nl.2 \\pdfoutput=1\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(make_proj(tmp_path, main), eng)
    assert cell["verdict"] == "clean"
    assert "\\ifdefined\\pdfoutput" in (tmp_path / "main.tex").read_text()
    assert any(a["rule"] == "pdftex_prim_guard" for a in cell["actions"])


def test_latex209_gate_reject(tmp_path: Path) -> None:
    main = "\\documentstyle{article}\n\\begin{document}\nx\n\\end{document}\n"
    eng = MockEngine(
        [{"log": "! LaTeX2e command \\usepackage in LaTeX 2.09 document.\n"}]
    )
    cell = fixloop(make_proj(tmp_path, main), eng)
    assert cell["verdict"] == "reject:latex209_reject"
    assert cell["final_pdf"] is False
    assert len(cell["rounds"]) == 1


# tectonic xdvipdfmx PS 硬墙签名 (v2: 由 stdout_tail 的 error: 行归一成 ! 行)。
PS_WALL_TAIL = (
    "error: something bad happened inside xdvipdfmx\n"
    'caused by: pdf: image inclusion failed for "fig.eps"\n'
)


def test_eps_route_rejects_on_tectonic(tmp_path: Path) -> None:
    """v2: 仅当 log 确证 PS 硬墙且 eps_to_pdf 救不动才拒 (loop 兜底)。"""
    (tmp_path / "fig.eps").write_text("%!PS")
    eng = MockTectonic([{"log": CLEAN_LOG, "tail": PS_WALL_TAIL}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "reject:eps_route"
    # 先编译一轮拿到 ps_image 确证, 再拒 (旧契约是 precheck 零轮即拒)
    assert cell["rounds"][0]["category"] == "ps_image"
    assert isinstance(eng.ctan_fetch, CtanFetcher)  # 降级原语已注入


def test_eps_route_fileset_only_clean_on_tectonic(tmp_path: Path) -> None:
    """v2 关键回归: fileset 含 .eps 但编译干净 → 不拒 (旧版此处即误拒)。"""
    (tmp_path / "fig.eps").write_text("%!PS")
    eng = MockTectonic([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"


def test_eps_route_skipped_on_xelatex(tmp_path: Path) -> None:
    (tmp_path / "fig.eps").write_text("%!PS")
    eng = MockEngine([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"


def test_static_precheck_scan_install(tmp_path: Path) -> None:
    main = (
        "\\documentclass{article}\n\\usepackage{foo,bar}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    eng = MockEngine(
        [{"log": CLEAN_LOG, "pdf": True}],
        installable={"bar.sty"},
        available={"article.cls"},
    )
    cell = fixloop(make_proj(tmp_path, main), eng)
    assert cell["verdict"] == "clean"
    pre = next(a for a in cell["actions"] if a["rule"] == "static_precheck")
    assert pre["round"] == 0
    assert "bar.sty" in cell["installed"]
    assert "foo.sty" in eng.install_calls  # 尝试装但不在白名单


def test_static_precheck_skips_commented_input(tmp_path: Path) -> None:
    """``% \\input ghost`` 注释行不触发安装 (pst-notreal 实证噪音)。"""
    main = (
        "\\documentclass{article}\n% \\input ghost\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    eng = MockEngine(
        [{"log": CLEAN_LOG, "pdf": True}],
        installable={"ghost.tex"},
        available={"article.cls"},
    )
    cell = fixloop(make_proj(tmp_path, main), eng)
    assert cell["verdict"] == "clean"
    assert not any("ghost" in c for c in eng.install_calls)


def test_warn_utf8_drives_recode_round(tmp_path: Path) -> None:
    # latin-1 源码 + U+FFFD warning (无 '!' 错) → warn_utf8 → non_utf8_recode
    (tmp_path / "main.tex").write_bytes(
        "\\documentclass{article}\n\\begin{document}\ncaf\xe9\n\\end{document}\n".encode(
            "latin-1"
        )
    )
    eng = MockEngine(
        [
            {
                "log": "Missing character: There is no  (U+FFFD) in font cmr10\n",
                "pdf": True,
            },
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(tmp_path, eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "warn_utf8"
    assert "café" in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_undefined_cs_escalate_hook(tmp_path: Path) -> None:
    calls = []

    def hook(ctx: LoopCtx, rep: ErrReport) -> tuple[bool, str]:
        del ctx  # hook 只看 rep
        calls.append(rep.first)
        return True, "llm patched \\mycs"

    eng = MockEngine(
        [
            {"log": "! Undefined control sequence.\nl.5 \\mycs\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(make_proj(tmp_path), eng, llm_hook=hook)
    assert cell["verdict"] == "clean"
    assert calls
    assert "Undefined control sequence" in calls[0]
    assert any(a["rule"] == "undefined_cs_guess" for a in cell["actions"])


def test_undefined_cs_no_hook_unfixable(tmp_path: Path) -> None:
    eng = MockEngine([{"log": "! Undefined control sequence.\nl.5 \\mycs\n"}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "unfixable:undefined_cs"


def test_dirty_pdf_demoted_to_acceptable(tmp_path: Path) -> None:
    eng = MockEngine([{"log": "! Bizarre unexplained\n", "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "acceptable_pdf"  # pdf 在 + 错 ≤3 → 降级
    assert cell["final_pdf"] is True


def test_missing_pfb_runs_updmap(tmp_path: Path) -> None:
    runs = []

    def runner(
        argv: list[str], timeout: int, wdir: Path
    ) -> tuple[int, str, float, bool]:
        del timeout, wdir  # mock 只看 argv
        runs.append(argv)
        return 0, "maps rebuilt", 0.1, False

    eng = MockEngine(
        [
            {
                "log": '! xdvipdfmx:fatal: Cannot proceed without .vf or "physical" font\n'
            },
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(make_proj(tmp_path), eng, runner=runner)
    assert cell["verdict"] == "clean"
    assert runs == [["updmap-user"]]
    assert any(a["rule"] == "missing_pfb_updmap" for a in cell["actions"])


def test_timeout_is_unfixable(tmp_path: Path) -> None:
    eng = MockEngine([{"log": "partial\n", "timed_out": True}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "unfixable:timeout"


def test_tectonic_stdout_tail_fallback(tmp_path: Path) -> None:
    # tectonic 不写 .log: log_path 文件为空 → stdout_tail 的 error: 行兜底
    eng = MockTectonic([{"log": "", "tail": "error: File `zhnumber.sty' not found\n"}])
    # CtanFetcher 会真注入; 直接让它"装不到"验证 unfixable 路径
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["rounds"][0]["category"] == "missing_file"
    assert cell["rounds"][0]["payload"] == "zhnumber.sty"


# ---------------------------------------------------------------- verdict 机械 (合成 ruleset)
def test_stuck_after_sig_repeat_3(tmp_path: Path) -> None:
    make_proj(tmp_path)
    rs = mini_rs(
        rules=[
            {
                "id": f"fix{i}",
                "phase": "loop",
                "order": i,
                "when": {"category": "boom"},
                "action": {"kind": "run_tool", "params": {"argv": ["true"]}},
            }
            for i in (1, 2)
        ],
        taxonomy=[{"id": "boom", "scope": "head", "pattern": "BOOM"}],
    )
    eng = MockEngine([{"log": "! BOOM every time\n"}])
    cell = fixloop(
        tmp_path, eng, ruleset=rs, runner=lambda _a, _t, _w: (0, "", 0.0, False)
    )
    assert cell["verdict"] == "stuck"
    # salvage 兜底轮挂 rounds 尾 (salvage=True 标记), 不占地正式轮数
    non_salvage = [r for r in cell["rounds"] if not r.get("salvage")]
    assert len(non_salvage) == 3  # noqa: PLR2004 - sig×3 触发线
    # 第 3 轮派发后结算 stuck (fix1/fix2 均 dedup → miss): 只应有 2 条 apply 记录
    applied = [
        a for a in cell["actions"] if isinstance(a.get("round"), int) and a["round"] > 0
    ]
    assert [a["rule"] for a in applied] == ["fix1", "fix2"]


def test_max_rounds_with_varying_payload(tmp_path: Path) -> None:
    make_proj(tmp_path)
    rs = mini_rs(
        rules=[
            {
                "id": "noop",
                "phase": "loop",
                "order": 1,
                "when": {"category": "missing_file"},
                "action": {"kind": "run_tool", "params": {"argv": ["true"]}},
            }
        ],
        taxonomy=[
            {
                "id": "missing_file",
                "scope": "head",
                "payload_group": 1,
                "pattern": "File `([^']+)' not found",
            }
        ],
        loop_cfg={"max_rounds": 4},
    )
    script = [{"log": f"! File `f{i}.sty' not found.\n"} for i in range(8)]
    cell = fixloop(
        tmp_path,
        MockEngine(script),
        ruleset=rs,
        runner=lambda _a, _t, _w: (0, "", 0.0, False),
    )
    assert cell["verdict"] == "max_rounds"
    non_salvage = [r for r in cell["rounds"] if not r.get("salvage")]
    assert len(non_salvage) == 4  # noqa: PLR2004 - mini_rs max_rounds=4


def test_dedup_same_rule_same_payload(tmp_path: Path) -> None:
    make_proj(tmp_path)
    rs = mini_rs(
        rules=[
            {
                "id": "only",
                "phase": "loop",
                "order": 1,
                "when": {"category": "missing_file"},
                "action": {"kind": "run_tool", "params": {"argv": ["true"]}},
            }
        ],
        taxonomy=[
            {
                "id": "missing_file",
                "scope": "head",
                "payload_group": 1,
                "pattern": "File `([^']+)' not found",
            }
        ],
    )
    eng = MockEngine([{"log": "! File `same.sty' not found.\n"}])
    cell = fixloop(
        tmp_path, eng, ruleset=rs, runner=lambda _a, _t, _w: (0, "", 0.0, False)
    )
    # r1 应用; r2 同 sig sig_n=2, dedup 阻断唯一规则 → unfixable (到不了 stuck)
    assert cell["verdict"] == "unfixable:missing_file"
    non_salvage = [r for r in cell["rounds"] if not r.get("salvage")]
    assert len(non_salvage) == 2  # noqa: PLR2004


def test_unsupported_mode_falls_to_llm(tmp_path: Path) -> None:
    make_proj(tmp_path)
    rs = mini_rs(
        rules=[
            {
                "id": "upx",
                "phase": "loop",
                "order": 1,
                "when": {"category": "boom"},
                "action": {"kind": "run_tool", "params": {"argv": ["updmap-user"]}},
                "engines": {
                    "xelatex": {"mode": "unsupported", "fallback": "escalate_llm"}
                },
            }
        ],
        taxonomy=[{"id": "boom", "scope": "head", "pattern": "BOOM"}],
    )
    hook_calls = []

    def hook(ctx: LoopCtx, rep: ErrReport) -> tuple[bool, str]:
        del ctx, rep  # 只记调用次数
        hook_calls.append(1)
        return True, "llm handled"

    eng = MockEngine([{"log": "! BOOM\n"}, {"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(tmp_path, eng, ruleset=rs, llm_hook=hook)
    assert cell["verdict"] == "clean"
    assert hook_calls == [1]
    assert any("escalated" in a.get("detail", "") for a in cell["actions"])


# ---------------------------------------------------------------- best-effort 兜底
class SalvageMockEngine(MockEngine):
    """best_effort 感知: 兜底轮 (best_effort=True) 放残页 pdf 出来。"""

    def compile(
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = 2,
        best_effort: bool = False,
        **_kw: object,
    ) -> MockRes:
        del passes
        if best_effort:
            self.rounds += 1
            return MockRes(
                Path(wdir),
                main,
                {"log": "! Undefined control sequence.\n", "pdf": True},
            )
        return super().compile(wdir, main, passes=1, **_kw)


def test_salvage_best_effort_rescues(tmp_path: Path) -> None:
    """规则耗尽且无 pdf → nonstopmode 兜底 pass 救残页 → best_effort_pdf。"""
    eng = SalvageMockEngine([{"log": "! Undefined control sequence.\nl.5 \\mycs\n"}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "best_effort_pdf"
    assert cell["final_pdf"] is True
    last = cell["rounds"][-1]
    assert last["salvage"] is True
    assert last["pdf"] is True
    assert any(a["rule"] == "_best_effort_pass" for a in cell["actions"])


def test_salvage_no_pdf_keeps_verdict(tmp_path: Path) -> None:
    """兜底也出不了 pdf → 保留原失败 verdict, salvage 轮留痕。"""
    eng = MockEngine([{"log": "! Undefined control sequence.\nl.5 \\mycs\n"}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "unfixable:undefined_cs"
    assert cell["final_pdf"] is False
    assert cell["rounds"][-1]["salvage"] is True


def test_salvage_skips_reject(tmp_path: Path) -> None:
    """reject:* 是语义拒绝——不跑兜底 (latex209 gate 拒的不救)。"""
    main = "\\documentstyle{article}\n\\begin{document}\nx\n\\end{document}\n"
    eng = SalvageMockEngine(
        [{"log": "! LaTeX2e command \\usepackage in LaTeX 2.09 document.\n"}]
    )
    cell = fixloop(make_proj(tmp_path, main), eng)
    assert cell["verdict"] == "reject:latex209_reject"
    assert not any(r.get("salvage") for r in cell["rounds"])


def test_salvage_skips_clean(tmp_path: Path) -> None:
    """clean/已有 pdf 的终态不跑兜底。"""
    eng = SalvageMockEngine([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert len(cell["rounds"]) == 1


# ---------------------------------------------------------------- 不退化底板 (#20)
MISSING_LOG = (
    "! LaTeX Error: File `zzz-nonexistent.sty' not found.\n"
    "l.3 \\usepackage{zzz-nonexistent}\n"
)


def test_floor_restores_entry_pdf(tmp_path: Path) -> None:
    """入口有 pdf、规则/编译把树打死 → 拷回入口快照, verdict 按既有公式落成。"""
    proj = make_proj(tmp_path)
    (proj / "main.pdf").write_bytes(b"%PDF-1.4 entry")
    eng = MockEngine([{"log": MISSING_LOG, "wipe_pdf": True}])
    cell = fixloop(proj, eng)
    assert cell["floor_restored"] is True
    assert cell["floor_from"]  # 兜底前 verdict 留痕 (unfixable:*/stuck/…)
    assert not cell["floor_from"].startswith("reject:")
    assert cell["final_pdf"] is True
    assert cell["verdict"] in ("dirty_pdf", "acceptable_pdf", "clean")
    # 首轮 wipe 删过 → 末态在盘即证明拷回发生
    assert (proj / "main.pdf").read_bytes() == b"%PDF-1.4 entry"


def test_floor_snapshots_round1_when_no_entry_pdf(tmp_path: Path) -> None:
    """入口无现存产物 → rounds[0] 出 pdf 时快照该轮产物作底板。"""
    eng = MockEngine(
        [
            {"log": MISSING_LOG, "pdf": True},
            {"log": MISSING_LOG, "wipe_pdf": True},
        ],
        installable={"zzz-nonexistent.sty"},  # r1 规则真应用 → 才有 r2 杀树
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["floor_restored"] is True
    assert cell["final_pdf"] is True
    assert (tmp_path / "main.pdf").read_bytes() == b"%PDF-1.4 fake"


def test_floor_never_without_snapshot(tmp_path: Path) -> None:
    """入口无 pdf 且全程没出过 pdf → 无底可兜, 原样失败。"""
    eng = MockEngine([{"log": MISSING_LOG}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["floor_restored"] is False
    assert cell["final_pdf"] is False
    assert cell["verdict"].startswith(("unfixable:", "stuck", "max_rounds"))


def test_floor_skips_reject(tmp_path: Path) -> None:
    """reject:* 是语义拒绝——入口 pdf 在盘也不兜 (latex209 gate 实证)。"""
    proj = make_proj(
        tmp_path, "\\documentstyle{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    (proj / "main.pdf").write_bytes(b"%PDF-1.4 entry")
    eng = MockEngine(
        [{"log": "! LaTeX2e command \\usepackage in LaTeX 2.09 document.\n"}]
    )
    cell = fixloop(proj, eng)
    assert cell["verdict"] == "reject:latex209_reject"
    assert cell["floor_restored"] is False
    assert cell["final_pdf"] is False
    assert (proj / "main.pdf").read_bytes() == b"%PDF-1.4 entry"


def test_shim_pkgs_in_use_extension_keys(tmp_path: Path) -> None:
    r"""shim_map 键可带扩展名——按 stem 匹 ``\usepackage``/``\documentclass``。

    旧实现 ``\bspotcolor\.sty\b`` 对裸名 ``{spotcolor}`` 永不中, shim_known
    条件对扩展名键形同虚设 (peer1 审计项)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{revtex4-1}\n\\usepackage{spotcolor,hyperref}\n",
        encoding="utf-8",
    )
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    hits = builtins.shim_pkgs_in_use(
        ctx,
        {
            "spotcolor.sty": "xespotcolor",
            "revtex4-1.cls": "revtex4-2",
            "absent.sty": "x",
        },
    )
    assert set(hits) == {"spotcolor.sty", "revtex4-1.cls"}


def test_pdftex_prim_polyfill_object_family(tmp_path: Path) -> None:
    r"""对象/注释族原语扩列后读取型也吃 polyfill (2410.00012 配套)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\ifnum\\pdflastobj=0 \\fi\n",
        encoding="utf-8",
    )
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, note = builtins.pdftex_prim_polyfill(ctx, None, "pdflastobj", {})
    assert ok, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifdefined\\pdflastobj" in out
    # 恒头注入: cls 内部读取发生在 \documentclass 加载期间, 类行后太晚
    assert out.index("\\ifdefined\\pdflastobj") < out.index("\\documentclass")


def test_find_main_tex_loose_tier_uppercase(tmp_path: Path) -> None:
    r"""宽松档同样认 ``.TEX``——缺 ``\begin{document}`` 的待修工程不再落空。"""
    (tmp_path / "BROKEN.TEX").write_text(
        "\\documentclass{article}\nbody without begin-document\n",
        encoding="utf-8",
    )
    assert find_main_tex(tmp_path) == tmp_path / "BROKEN.TEX"


# ---------------------------------------------------------------- main_rel 指定主档 (#191)
def test_main_rel_overrides_language_demotion(tmp_path: Path) -> None:
    r"""ds209diag #191: 译后 splice 树 CJK 主档被 ``language_rank`` 降权,
    ``find_main_tex`` 误选 standalone 英文档——显式 ``main_rel`` 必须胜出。
    主档用非标名 (paper_zh.tex)：标名档排序已先于语种档, 盖不了此面。"""
    (tmp_path / "paper_zh.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "你好世界你好世界你好世界\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "tab1.tex").write_text(
        "\\documentclass{standalone}\n\\begin{document}\n"
        "English table body\n\\end{document}\n",
        encoding="utf-8",
    )
    eng = MockEngine([{"log": CLEAN_LOG, "pdf": True}])
    # 自动探测复现误选 (CJK 主档输给 standalone 英文档)
    assert find_main_tex(tmp_path) == tmp_path / "tab1.tex"
    cell = fixloop(tmp_path, eng, main_rel="paper_zh.tex")
    assert cell["main"] == "paper_zh.tex"
    assert cell["main_fallback"] is None
    assert cell["verdict"] == "clean"


def test_find_main_tex_canonical_name_beats_language(tmp_path: Path) -> None:
    r"""标名档先于语种档：译后树 ``main.tex`` (CJK 众数) 仍胜 standalone
    英文档——ds209diag #191 的 detect 侧修复 (main_rel 是调用方侧保险)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "你好世界你好世界你好世界\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "tab1.tex").write_text(
        "\\documentclass{standalone}\n\\begin{document}\n"
        "English table body\n\\end{document}\n",
        encoding="utf-8",
    )
    assert find_main_tex(tmp_path) == tmp_path / "main.tex"


def test_main_rel_missing_falls_back(tmp_path: Path) -> None:
    """指定主档缺件 → 回退 ``find_main_tex`` 且 ``main_fallback`` 留痕。"""
    make_proj(tmp_path)
    eng = MockEngine([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(tmp_path, eng, main_rel="ghost.tex")
    assert cell["main"] == "main.tex"
    assert cell["main_fallback"] == "ghost.tex"
    assert cell["verdict"] == "clean"
    assert any("ghost.tex" in a for a in cell["advisories"])


def test_main_rel_docclass_less_honored(tmp_path: Path) -> None:
    r"""指定档无 ``\documentclass`` 也照用——缺 dc 正是待修形态, 信调用方。"""
    make_proj(tmp_path)
    (tmp_path / "frag.tex").write_text("broken body fragment\n", encoding="utf-8")
    eng = MockEngine([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(tmp_path, eng, main_rel="frag.tex")
    assert cell["main"] == "frag.tex"
    assert cell["verdict"] == "clean"


def test_ctx_tex_files_case_insensitive(tmp_path: Path) -> None:
    r"""``LoopCtx.tex_files`` 扩展名匹配大小写不敏感——``.TEX`` 进 source_blob。"""
    (tmp_path / "PAPER.TEX").write_text("x", encoding="utf-8")
    (tmp_path / "a.tex").write_text("x", encoding="utf-8")
    (tmp_path / "STYLE.STY").write_text("x", encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    assert {p.name for p in ctx.tex_files()} == {"PAPER.TEX", "a.tex", "STYLE.STY"}


# ---------------------------------------------------------------- aux 截断清场
def test_aux_sweep_entry_poison(tmp_path: Path) -> None:
    r"""1511.06744 型: 被杀编译驻留的 ``\citation{`` 半行 aux → r1 编译前清扫。"""
    proj = make_proj(tmp_path)
    (proj / "main.aux").write_text("\\relax \n\\citation{", encoding="utf-8")
    cell = fixloop(proj, MockEngine([{"log": CLEAN_LOG, "pdf": True}]))
    assert cell["verdict"] == "clean"
    assert not (proj / "main.aux").exists()
    assert any("aux-sweep" in e and "main.aux" in e for e in cell["log"])


def test_aux_sweep_midloop(tmp_path: Path) -> None:
    """round1 崩留截断 aux → round2 编译前清, 不毒化后续轮。"""
    proj = make_proj(tmp_path)
    eng = MockEngine(
        [
            {
                "log": "! LaTeX Error: File `zhnumber.sty' not found.\n",
                "aux": "\\citation{",
            },
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable={"zhnumber.sty"},
    )
    cell = fixloop(proj, eng)
    assert cell["verdict"] == "clean"
    assert not (proj / "main.aux").exists()
    assert any("aux-sweep" in e for e in cell["log"])


def test_aux_sweep_healthy_kept(tmp_path: Path) -> None:
    """完整 aux (尾换行 + 花括号闭合) 不动——行界齐整缺行同。"""
    proj = make_proj(tmp_path)
    good = "\\relax \n\\citation{key1}\n\\newlabel{sec}{{1}{1}}\n"
    (proj / "main.aux").write_text(good, encoding="utf-8")
    cell = fixloop(proj, MockEngine([{"log": CLEAN_LOG, "pdf": True}]))
    assert cell["verdict"] == "clean"
    assert (proj / "main.aux").read_text(encoding="utf-8") == good


def test_aux_sweep_escaped_braces_healthy(tmp_path: Path) -> None:
    r"""``\{``/``\}`` 转义不计深——含转义的健康 aux 不误删。"""
    proj = make_proj(tmp_path)
    good = "\\newlabel{a}{{\\{x\\}}{1}}\n"
    (proj / "main.aux").write_text(good, encoding="utf-8")
    fixloop(proj, MockEngine([{"log": CLEAN_LOG, "pdf": True}]))
    assert (proj / "main.aux").exists()


def test_aux_sweep_toc_family(tmp_path: Path) -> None:
    r"""``.toc`` 同机制件: 截断 ``\contentsline`` 半行一样毒。"""
    proj = make_proj(tmp_path)
    (proj / "main.toc").write_text("\\contentsline{section}{", encoding="utf-8")
    fixloop(proj, MockEngine([{"log": CLEAN_LOG, "pdf": True}]))
    assert not (proj / "main.toc").exists()


def test_aux_sweep_final_round_leftover(tmp_path: Path) -> None:
    """末轮被杀留截断 aux → return 前清场, 格后 post 复判不吃毒。"""
    proj = make_proj(tmp_path)
    eng = MockEngine([{"log": "partial\n", "timed_out": True, "aux": "\\citation{"}])
    cell = fixloop(proj, eng)
    assert cell["verdict"] == "unfixable:timeout"
    assert not (proj / "main.aux").exists()
    assert any("final aux-sweep" in e for e in cell["log"])


def test_static_precheck_skips_constructed_input(tmp_path: Path) -> None:
    r"""``\input sv\X``/``\InputIfFileExists{aip-\X.tex}`` 构造名不产 sv.tex/aip-.tex 噪音。"""
    main = (
        "\\documentclass{article}\n"
        "\\input sv\\CurrentOption.clo\n"
        "\\InputIfFileExists{aip-\\CurrentOption.tex}{}{}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    eng = MockEngine(
        [{"log": CLEAN_LOG, "pdf": True}],
        installable={"sv.tex", "aip-.tex", "sv\\CurrentOption.clo"},
        available={"article.cls"},
    )
    cell = fixloop(make_proj(tmp_path, main), eng)
    assert cell["verdict"] == "clean"
    assert not eng.install_calls


def test_dep_stems_constructed_names_skipped(tmp_path: Path) -> None:
    r"""``_dep_stems``: 构造名/裸名 \ 截断不产 stem, 真名照收。"""
    f = tmp_path / "m.tex"
    f.write_text(
        "\\input aip-\\CurrentOption.tex\n"
        "\\input {sv\\CurrentOption.clo}\n"
        "\\input realdep\n"
        "\\input sub/fig\n",
        encoding="utf-8",
    )
    assert _dep_stems(f) == ["realdep", "sub/fig"]


# ---------------------------------------------------------------- passes 分层 (perf-fix: 分类轮 p1 / 终编轮全遍)
class PassRecordingEngine(MockEngine):
    """每次 compile 的 ``(passes, best_effort)`` 落表供分层断言。"""

    def __init__(self, script: list, **kw: object) -> None:
        super().__init__(script, **kw)
        self.calls: list[dict[str, object]] = []

    def compile(
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = 2,
        best_effort: bool = False,
        **kw: object,
    ) -> MockRes:
        self.calls.append({"passes": passes, "best_effort": best_effort})
        return super().compile(wdir, main, passes=passes, best_effort=best_effort, **kw)


class PassRecordingTectonic(MockTectonic):
    """同上的 tectonic 臂——``del passes`` 自定遍数引擎的复编豁免断言。"""

    def __init__(self, script: list, **kw: object) -> None:
        super().__init__(script, **kw)
        self.calls: list[dict[str, object]] = []

    def compile(
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = 2,
        best_effort: bool = False,
        **kw: object,
    ) -> MockRes:
        self.calls.append({"passes": passes, "best_effort": best_effort})
        return super().compile(wdir, main, passes=passes, best_effort=best_effort, **kw)


def test_classify_rounds_pass1_final_pass2(tmp_path: Path) -> None:
    """修复轮分类只需 pass-1 log；收敛轮同轮 ``compile_passes`` 终编定稿。"""
    eng = PassRecordingEngine(
        [
            {"log": "! LaTeX Error: File `zhnumber.sty' not found.\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable={"zhnumber.sty"},
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert len(cell["rounds"]) == 2  # noqa: PLR2004 - 修复轮 + 收敛轮
    # r1 分类轮 p1; r2 收敛轮 p1 探 + 终编——compile_passes=2 ≤自适应上限
    # → passes=None (rerun-hint 才升遍, 引擎 MAX_PASSES=2 同值语义)
    assert [c["passes"] for c in eng.calls] == [1, 1, None]
    assert not any(c["best_effort"] for c in eng.calls)


def test_first_round_clean_probes_then_finalizes(tmp_path: Path) -> None:
    """首轮即收敛: p1 探到 clean → 同轮全遍复编——成品仍经第二遍 \\write 填实。"""
    eng = PassRecordingEngine([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert len(cell["rounds"]) == 1
    assert [c["passes"] for c in eng.calls] == [1, None]


def test_nonconverging_cell_all_pass1(tmp_path: Path) -> None:
    """不产成品的格: 分类轮 + salvage 兜底全 p1——无收敛终编轮。"""
    eng = PassRecordingEngine([{"log": "! Undefined control sequence.\nl.5 \\mycs\n"}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "unfixable:undefined_cs"
    assert eng.calls, "至少一轮分类编译"
    assert [c["passes"] for c in eng.calls] == [1] * len(eng.calls)
    assert eng.calls[-1]["best_effort"] is True  # 末次是 salvage 兜底轮


def test_tectonic_converge_no_finalize_recompile(tmp_path: Path) -> None:
    """tectonic 自定遍数 (impl ``del passes``)——收敛轮不复编, 全程一次 compile。"""
    eng = PassRecordingTectonic([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng, engine_name="tectonic")
    assert cell["verdict"] == "clean"
    assert [c["passes"] for c in eng.calls] == [1]


def test_finalize_recompile_resurfaces_errors(tmp_path: Path) -> None:
    """pass-2-emergent: p1 探收敛但终编复编出新错 → 重分类回流修复路径。

    r2 p1 clean → 全遍复编冒出 missing_file:other.sty → 装包续轮；
    r3 再收敛终编 → clean。终编轮错误不吞、轮记账按全遍结果。
    """
    eng = PassRecordingEngine(
        [
            {"log": "! LaTeX Error: File `zhnumber.sty' not found.\n"},
            {"log": CLEAN_LOG, "pdf": True},
            {"log": "! LaTeX Error: File `other.sty' not found.\n", "pdf": True},
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable={"zhnumber.sty", "other.sty"},
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert len(cell["rounds"]) == 3  # noqa: PLR2004 - r1修 + r2终编浮err修 + r3收敛
    assert cell["rounds"][1]["category"] == "missing_file"
    assert cell["rounds"][1]["payload"] == "other.sty"
    assert [c["passes"] for c in eng.calls] == [1, 1, None, 1, None]
    assert {"zhnumber.sty", "other.sty"} <= set(cell["installed"])


def test_finalize_compile_passes_gt2_passthrough(tmp_path: Path) -> None:
    """``compile_passes > 2`` 超自适应上限的显式诉求——原样透传不吞成 None。"""
    rs = mini_rs(rules=[], taxonomy=[], loop_cfg={"compile_passes": 3})
    eng = PassRecordingEngine([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng, ruleset=rs)
    assert cell["verdict"] == "clean"
    assert [c["passes"] for c in eng.calls] == [1, 3]


def test_report_of_prefers_compres_log_text(tmp_path: Path) -> None:
    """``_report_of`` 复用 ``res.log_text`` (fix#10)——盘面 .log 不再二次开读。

    log_text 与 .log 文件分歧时以 log_text (编译期读到的原文) 为准。
    """
    res = MockRes(tmp_path, "main.tex", {"log": "! BOOM on-disk\n", "pdf": True})
    res.log_text = "! CACHED in-memory\nl.9 \\x\n"
    rep = _report_of(res, [])
    assert rep.first == "! CACHED in-memory"
    assert rep.n_bang == 1


def test_bounded_sub_timeout_returns_none_no_leak() -> None:
    r"""病态 pattern 超时 → ``None`` 且零线程泄漏（``regex`` 原生 timeout 臂）。

    旧 daemon-thread 弃守形把 spinner 泄漏进进程——泄漏线程在 C 层回溯
    不放 GIL，整进程冻结（guardsmoke fixloop 格 Thread-4 utime 29min
    实证，2026-09-18）。``regex`` 的匹配环内 deadline 检查是真中断。
    """
    pat = regex.compile(r"(a|a)*$")
    before = threading.enumerate()
    t0 = time.monotonic()
    assert actions._bounded_sub(pat, "x", "a" * 30 + "b", timeout_s=0.5) is None  # noqa: SLF001
    assert time.monotonic() - t0 < 10  # noqa: PLR2004 -- 上限即超时闸本身
    assert threading.enumerate() == before


# ---------------------------------------------------------------- tar 伪装件
def _write_tar(path: Path, members: dict[str, bytes]) -> None:
    """POSIX tar 写出 (ustar 格式——``ustar`` 魔数 @257 必现)。"""
    import io  # noqa: PLC0415
    import tarfile  # noqa: PLC0415

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    path.write_bytes(buf.getvalue())


def _extract(wdir: Path) -> tuple[bool, str]:
    ctx = LoopCtx(wdir=wdir, engine_name="xelatex")
    return builtins.TRANSFORM_FNS["extract_tar_blobs"](ctx, None, None, {})


def test_tar_blob_extracts_members_and_retires(tmp_path: Path) -> None:
    r"""0707.0382/0104007 型: ``.sty`` 名 tar → 成员补缺 + blob 改名退役。"""
    _write_tar(
        tmp_path / "AMSbsy.sty",
        {"./iaus.cls": b"\\ProvidesClass{iaus}\n", "figs/f1.eps": b"%!PS\n"},
    )
    ok, note = _extract(tmp_path)
    assert ok, note
    assert (tmp_path / "iaus.cls").read_bytes() == b"\\ProvidesClass{iaus}\n"
    assert (tmp_path / "figs" / "f1.eps").is_file()
    assert not (tmp_path / "AMSbsy.sty").exists()
    assert (tmp_path / "AMSbsy.sty.tarblob").is_file()  # 退役留证, 移出解析路径


def test_tar_blob_no_clobber_keeps_real_files(tmp_path: Path) -> None:
    """成员名撞真件 → 真件不动 (tar 只补缺)。"""
    (tmp_path / "aipproc.sty").write_bytes(b"\\ProvidesPackage{real}\n")
    _write_tar(
        tmp_path / "aipproc.cls",
        {"./aipproc.sty": b"% stale dup\n", "./symposium.tex": b"\\bye\n"},
    )
    ok, _ = _extract(tmp_path)
    assert ok
    assert (tmp_path / "aipproc.sty").read_bytes() == b"\\ProvidesPackage{real}\n"
    assert (tmp_path / "symposium.tex").is_file()  # 缺的补上


def test_tar_blob_unsafe_members_rejected(tmp_path: Path) -> None:
    """``..``/绝对路径/非常规成员全拒——只合法件落地。"""
    _write_tar(
        tmp_path / "evil.sty",
        {"../escape.tex": b"x", "/abs.tex": b"y", "ok/inner.sty": b"z\n"},
    )
    ok, _ = _extract(tmp_path)
    assert ok  # ok/inner.sty 一件落地即抽中
    assert not (tmp_path.parent / "escape.tex").exists()
    assert not Path("/abs.tex").exists()
    assert (tmp_path / "ok" / "inner.sty").is_file()


def test_tar_blob_ignores_real_files(tmp_path: Path) -> None:
    """健康 .sty/.tex 不误判。"""
    (tmp_path / "real.sty").write_bytes(b"\\ProvidesPackage{real}\n")
    (tmp_path / "main.tex").write_bytes(b"\\documentclass{article}\n")
    ok, _ = _extract(tmp_path)
    assert not ok
    assert (tmp_path / "real.sty").is_file()
    assert not (tmp_path / "real.sty.tarblob").exists()


def test_tar_blob_retires_when_all_members_exist(tmp_path: Path) -> None:
    """0707.0382 实案: 语料已带全部成员 → 0 新成员, blob 仍须退役。

    tar 归档在 ``.sty``/``.cls`` 名下绝不是合法 TeX——退役判据是
    tar 魔数本身, 与补缺落地数解耦 (旧逻辑 0 成员原样放回 → blob
    残留毒化编译)。
    """
    (tmp_path / "iaus.cls").write_bytes(b"\\ProvidesClass{iaus}\n")
    _write_tar(tmp_path / "AMSbsy.sty", {"./iaus.cls": b"% stale dup\n"})
    ok, note = _extract(tmp_path)
    assert ok, note
    assert "0 members" in note
    assert not (tmp_path / "AMSbsy.sty").exists()
    assert (tmp_path / "AMSbsy.sty.tarblob").is_file()
    assert (tmp_path / "iaus.cls").read_bytes() == b"\\ProvidesClass{iaus}\n"


def test_tar_blob_detects_prologue_displaced_magic(tmp_path: Path) -> None:
    """0707.0382 实案二阶: 我方 prologue 前置注入把魔数推离 257 → 扫窗检测。

    splice/zh 构建对 ``.sty`` 一律前置 ``\\PassOptionsToPackage`` 注入块
    (~600B), ``ustar`` 落 ~偏移 870——定点 257 探测漏检, blob 原地毒化。
    扫窗检出后从头起点切片抽取, 成员照常补缺, blob 退役。
    """
    import io  # noqa: PLC0415
    import tarfile  # noqa: PLC0415

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        info = tarfile.TarInfo("./missing.sty")
        payload = b"\\ProvidesPackage{missing}\n"
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    prologue = b"\\PassOptionsToPackage{no-math}{fontspec}\n% injected\n"
    (tmp_path / "AMSbsy.sty").write_bytes(prologue + buf.getvalue())
    ok, note = _extract(tmp_path)
    assert ok, note
    assert "1 members" in note
    assert (tmp_path / "missing.sty").read_bytes() == payload
    assert not (tmp_path / "AMSbsy.sty").exists()
    assert (tmp_path / "AMSbsy.sty.tarblob").is_file()


def test_tar_blob_ustar_word_in_text_not_false_positive(tmp_path: Path) -> None:
    """文本/注释里的 ``ustar`` 字样不误中——回推 257 处 name 字段须非 NUL。"""
    (tmp_path / "doc.tex").write_bytes(
        b"\\documentclass{article}\n% this file mentions ustar format\n"
    )
    ok, _ = _extract(tmp_path)
    assert not ok
    assert (tmp_path / "doc.tex").is_file()


# ------------------------------------------------------- physics detach @catcode
def test_detach_input_letter_wrap_per_host() -> None:
    r"""``\\input{physics.sty}`` 在 .tex 宿主带 @ 存复包裹——

    裸 ``\\input`` 不设 @=letter, stub 内 ``\\@undefined`` 碎成 ``\\@``+裸
    字母 → 排版文本泄 preamble 炸 Missing ``\\begin{document}`` (1706.00240
    physics.sty:13 实证)。包裹走 exact-restore (svglov3.clo idiom):
    ``\\catcode 64=11`` 读件后 ``\\TeXlateStyInRestore`` 复原。
    .sty/.cls 宿主 @ 本即 letter 走裸 ``\\input``。
    """
    from texlate.compile.fixloop._builtins_pkgload import (  # noqa: PLC0415
        _detach_physics_loads,
    )

    src = "\\documentclass{article}\n\\usepackage{physics}\n"
    tex_out, n = _detach_physics_loads(src, add_input=True, letter_wrap=True)
    assert n == 1
    assert (
        "\\edef\\TeXlateStyInRestore{\\catcode 64=\\the\\catcode 64\\relax}"
        "\\catcode 64=11\\relax \\input{physics.sty} \\TeXlateStyInRestore" in tex_out
    )
    assert "\\makeatletter" not in tex_out
    sty_out, _ = _detach_physics_loads(src, add_input=True, letter_wrap=False)
    assert "\\input{physics.sty}" in sty_out
    assert "\\TeXlateStyInRestore" not in sty_out
