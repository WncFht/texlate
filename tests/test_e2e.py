r"""``texlate.e2e`` 产品编排层直测——不经 bench harness、不复制影子链。

覆盖：

- ``mock_translate_tree``：per-tree 汇总（files/chunks/fault_chunks/
  fault_files/leftover_ph）、单文件解析崩不拖垮整树、译文写回原地；
- ``mock_pipeline_run``：route → find_main_tex → pipe_condition 全链
  结构化报告（engine_for 换记录型假引擎，judge 的 pdftotext 侧效果
  monkeypatch 成确定值）；
- reject 分流：``reject_at == "route"``（route_project 拒绝）与
  ``reject_at == "inject"``（``\documentstyle`` → InjectRejectError）
  在报告里是不同终态；
- ``base_condition``：不动源码直接编译+判定（expect_cjk=False）；
- 引擎 kwargs 契约：xelatex 拿 ``halt_on_error=False``，tectonic 无额外参数。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from conftest import RecordingEngine

from texlate import e2e
from texlate.compile.engine import RouteDecision
from texlate.xlat.pipeline import MOCK_ZH, MockTranslator

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

#: 最小可解析工程：两段散文保证出 chunk（单行 body 可能零 chunk）。
_MAIN = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "\\section{Intro}\n"
    "This is a longer paragraph of English text that should definitely be\n"
    "segmented into at least one chunk for translation purposes.\n"
    "\n"
    "And a second paragraph here.\n"
    "\\end{document}\n"
)

_DOCSTYLE = (
    "\\documentstyle{ias}\n"
    "\\begin{document}\n"
    "Old LaTeX 2.09 body text that still needs translation.\n"
    "\\end{document}\n"
)


def _project(root: Path, main: str = _MAIN) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.tex").write_text(main, encoding="utf-8")
    return root


# ---------------------------------------------------------------- mock_translate_tree


def test_translate_tree_two_files(tmp_path: Path) -> None:
    """两文件树：per-file chunk_id 前缀隔离、译文写回、占位符零残留。"""
    _project(tmp_path)
    (tmp_path / "sub.tex").write_text(
        "A third paragraph in a second file for translation.\n",
        encoding="utf-8",
    )
    stats = e2e.mock_translate_tree(tmp_path)

    assert stats["fault_files"] == []
    assert stats["fault_chunks"] == 0
    assert stats["chunks"] > 0
    assert stats["files"] == 2  # noqa: PLR2004 -- 两文件都改写
    assert stats["leftover_ph"] == 0
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert MOCK_ZH in out
    assert "\\section{" in out  # 命令名原样（标题正文是 chunk 会被翻）


def test_translate_tree_glossary_ph_injection(tmp_path: Path) -> None:
    r"""spec-xlat#10：文件模式链挂 glossary——段内 ``[[X_n]]`` 恒等注入进 system prompt。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "A paragraph with inline math $E=mc^2$ inside it for translation here.\n"
        "\n"
        "And a second paragraph to keep the chunker honest.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    tr = MockTranslator()
    stats = e2e.mock_translate_tree(tmp_path, translator=tr)

    assert stats["chunks"] > 0
    systems = [str(c["system"]) for c in tr.calls]
    assert any(re.search(r"\[\[[A-Z]+_\d+\]\]", s) for s in systems)


def test_translate_tree_parse_fault_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """单文件 parse 崩 → 记名进 fault_files，其余文件照常翻译写回。"""
    _project(tmp_path)
    (tmp_path / "broken.tex").write_text("Anything\n", encoding="utf-8")

    real_parse_file = e2e.parse_file

    def flaky_parse(path: Path, **kw: object) -> object:
        if path.name == "broken.tex":
            msg = "simulated parse crash"
            raise RuntimeError(msg)
        return real_parse_file(path, **kw)

    monkeypatch.setattr(e2e, "parse_file", flaky_parse)
    stats = e2e.mock_translate_tree(tmp_path)

    assert stats["fault_files"] == ["broken.tex"]
    assert stats["files"] == 1  # main.tex 仍写回
    assert (tmp_path / "broken.tex").read_text(encoding="utf-8") == "Anything\n"


def test_translate_tree_validator_fault_keeps_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """校验器恒败 → 全 chunk fault → 不写回（文件保持原文）。"""
    _project(tmp_path)

    class AlwaysBad:
        def feedback(self) -> str:
            return "always fails"

    monkeypatch.setattr(e2e, "validate_pair", lambda _s, _z: AlwaysBad())
    stats = e2e.mock_translate_tree(tmp_path)

    assert stats["fault_chunks"] == stats["chunks"] > 0
    assert stats["files"] == 0
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == _MAIN


def test_translate_tree_uppercase_ext(tmp_path: Path) -> None:
    """``.TEX`` 主文件进翻译集——不再被 rglob 大小写盲点跳过。"""
    (tmp_path / "PAPER.TEX").write_text(_MAIN, encoding="utf-8")
    stats = e2e.mock_translate_tree(tmp_path)

    assert stats["fault_files"] == []
    assert stats["files"] == 1
    assert MOCK_ZH in (tmp_path / "PAPER.TEX").read_text(encoding="utf-8")


def test_translate_tree_rtx_dump_uppercase_still_excluded(tmp_path: Path) -> None:
    """``.RTX.TEX`` 运行时转储依旧排除——枚举变宽不放大排除例外。"""
    (tmp_path / "main.tex").write_text(_MAIN, encoding="utf-8")
    (tmp_path / "paper.RTX.TEX").write_text("runtime dump\n", encoding="utf-8")
    stats = e2e.mock_translate_tree(tmp_path)

    assert stats["files"] == 1
    assert (tmp_path / "paper.RTX.TEX").read_text(encoding="utf-8") == "runtime dump\n"


# ---------------------------------------------------------------- mock_pipeline_run


def test_pipeline_run_happy(
    tmp_path: Path, fake_engine: dict[str, RecordingEngine]
) -> None:
    """全链：route → normalize → mock 翻译 → ctex 注入 → fake 编译 → clean。"""
    work = _project(tmp_path / "p")
    report = e2e.mock_pipeline_run(work, "auto", timeout=60.0)

    assert report["status"] == "clean"
    assert report["main"] == "main.tex"
    assert report["route"]["reject"] is None
    assert report["route"]["engines"][0] == "tectonic"  # 默认 prefer
    assert report["translate"]["files"] >= 1
    assert report["translate"]["leftover_ph"] == 0
    assert report["inject"]["status"] == "injected"
    assert report["compile"]["ok"] is True
    assert report["verdict"]["cjk_chars"] == 500  # noqa: PLR2004 -- 钉住的假计数

    out = (work / "main.tex").read_text(encoding="utf-8")
    assert MOCK_ZH in out
    assert "{ctex}" in out  # ctex 注入生效

    eng = fake_engine["tectonic"]  # auto → 路由首选
    assert eng.ctor_kwargs == {}  # tectonic 无 halt_on_error 旋钮
    assert eng.calls[0]["timeout"] == 60.0  # noqa: PLR2004 -- timeout 透传


def test_pipeline_run_xelatex_halt_flag(
    tmp_path: Path, fake_engine: dict[str, RecordingEngine]
) -> None:
    """engine_opt='xelatex'：构造 kwargs 带 halt_on_error=False（best-effort 语义）。"""
    work = _project(tmp_path / "p")
    report = e2e.mock_pipeline_run(work, "xelatex", timeout=30.0)

    assert report["engine"] == "xelatex"
    assert fake_engine["xelatex"].ctor_kwargs == {"halt_on_error": False}


def test_pipeline_run_route_reject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """route.reject 非空 → 短路终态 reject，不进 normalize/编译。"""
    work = _project(tmp_path / "p")
    monkeypatch.setattr(
        e2e,
        "route_project",
        lambda _w: RouteDecision(engines=["xelatex"], reject="gate", reasons=["r"]),
    )
    report = e2e.mock_pipeline_run(work, "auto", timeout=10.0)

    assert report["status"] == "partial"  # F3: 策略拒绝 → partial, reject_at 审计
    assert report["reject_at"] == "route"
    assert "compile" not in report
    assert "inject" not in report


def test_pipeline_run_no_main_tex(tmp_path: Path) -> None:
    """无 documentclass+document 环境 → find_main_tex None → partial+reject_at。"""
    work = tmp_path / "p"
    work.mkdir()
    (work / "frag.tex").write_text("just a fragment\n", encoding="utf-8")

    report = e2e.mock_pipeline_run(work, "auto", timeout=10.0)

    assert report["status"] == "partial"
    assert report["reject_at"] == "route"
    assert "no main tex" in report["route"]["reasons"]
    assert "compile" not in report


def test_pipeline_run_inject_reject_documentstyle(
    tmp_path: Path, fake_engine: dict[str, RecordingEngine]
) -> None:
    r"""``\documentstyle`` → route 只打 suspect、inject 层真拒（分流可审计）。"""
    work = _project(tmp_path / "p", main=_DOCSTYLE)
    report = e2e.mock_pipeline_run(work, "auto", timeout=10.0)

    assert report["status"] == "partial"  # F3: inject 拒绝合成 partial
    assert report["reject_at"] == "inject"
    assert report["verdict"]["status"] == "partial"
    assert report["verdict"]["reasons"] == ["latex209_ds_at"]
    assert report["route"]["latex209_suspect"] is True  # route 不拒、只标记
    assert fake_engine == {}  # 拒在编译前——引擎没被构造


def test_base_condition(
    tmp_path: Path,
    fake_engine: dict[str, RecordingEngine],  # noqa: ARG001 -- fixture 副作用
) -> None:
    """base：不动源码编译+判定（expect_cjk=False → 无 CJK 检查）。"""
    work = _project(tmp_path / "p")
    rec = e2e.base_condition(work, "tectonic", "main.tex", timeout=45.0)

    assert rec["status"] == "clean"
    assert rec["compile"]["ok"] is True
    assert rec["verdict"]["cjk_chars"] == -1  # expect_cjk=False → 未测
    assert "translate" not in rec
    assert "inject" not in rec
    # 源码未被改写（对照臂语义）
    assert (work / "main.tex").read_text(encoding="utf-8") == _MAIN


def test_pipeline_run_repair_chain_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非 clean → L2 回灌 + fixloop 修复链真跑：无 pdf 引擎 → 终态 fail。

    RecordingEngine 带全协议桩（caps/probe/install/filemap/best_effort），
    fixloop 真跑自然收敛而非走 ``_run_fixloop`` 的 error 兜底。
    """
    work = _project(tmp_path / "p")

    def factory(name: str, **kw: object) -> RecordingEngine:
        eng = RecordingEngine(name, **kw)
        eng.produce_pdf = False
        return eng

    monkeypatch.setattr(e2e, "engine_for", factory)
    for key in ("TEXLATE_ENV_JUDGE", "TEXLATE_NO_L2", "TEXLATE_NO_FIXLOOP"):
        monkeypatch.delenv(key, raising=False)
    report = e2e.mock_pipeline_run(work, "auto", timeout=10.0)

    assert report["status"] == "fail"
    l2 = report["l2"]
    assert l2["enabled"] is True
    assert l2["errors"] == 0  # 假 log 无 chunk 级可归因错误
    fl = report["fixloop"]
    assert fl["enabled"] is True
    assert "error" not in fl  # 协议桩齐 → fixloop 真跑不抛
