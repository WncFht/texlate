"""fixloop 主循环端到端单测 —— 合成 log + mock engine (不跑真编译)。

MockEngine 对齐 impl-compile ``compile/engine.py`` 的 CompRes/Engine 字段名
(pdf: Path|None / has_pdf / pdf_bytes / seconds / stdout_tail / caps frozenset),
顺带回归 _probe(cwd=) / _report_of(stdout_tail) 适配层。
"""

from collections.abc import Iterable
from pathlib import Path

from texlate.compile.fixloop import Ruleset, fixloop, load_ruleset
from texlate.compile.fixloop.ctan import CtanFetcher
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.fixloop.logparse import ErrReport

RS = load_ruleset()

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
        self.pdf = wdir / f"{stem}.pdf" if spec.get("pdf") else None
        if self.pdf is not None:
            self.pdf.write_bytes(b"%PDF-1.4 fake")
        self.pdf_bytes = self.pdf.stat().st_size if self.pdf else 0
        self.timed_out = bool(spec.get("timed_out"))
        self.seconds = 0.05
        self.stdout_tail = spec.get("tail", "")

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
    # 第 3 轮在 match 前就判 stuck: 只应有 2 条 apply 记录
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
