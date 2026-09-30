"""bib 中间趟钉 —— ``XelatexEngine._bib_pass`` 文件态触发（bibpass 车道）。

设计（bibpass 车道文档）：上游 arXiv latexmk 在 latex 趟间跑
bibtex/biber 再生 ``.bbl``，本引擎此前不跑 → ~30% clean 格 ``[?]`` 引用缺。

钉:
  a) aux 含 ``\\citation``+``\\bibdata`` 且同侪 .bbl 缺席 → bibtex 触发，
     自适应档延至 3 趟（bibcite→aux→[n]）;
  b) ``passes=1`` 永不触发（classify/probe 纯单趟契约）;
  c) bundled .bbl 在席 → 永不 clobber（bibtex/biber 两臂同闸）;
  d) 截断 bbl（缺尾标）→ 不采纳且删除，不毒下趟;
  e) ``.bcf`` 在席 + .bbl 缺席 → biber 臂（adoption 须 rc==0）;
  f) 死趟（超时）与无 bib 态不触发；显式 ``passes=N`` 趟间补但不延趟。
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from texlate.compile.engine import XelatexEngine

_XE = "/x/xelatex"
_AUX_CITE = "\\relax\n\\citation{a}\n\\bibstyle{plain}\n\\bibdata{refs}\n"
_BBL_OK = "\\begin{thebibliography}{1}\n\\bibitem{a} A.\n\\end{thebibliography}\n"
_BBL_TRUNC = "\\begin{thebibliography}{1}\n\\bibitem{a} A."
_HINT = "LaTeX Warning: There were undefined references."


def _fake_run(  # noqa: PLR0913 -- mock 签名对齐 run_process
    calls: dict,
    *,
    aux: str | None = _AUX_CITE,
    extra_aux: dict[str, str] | None = None,
    bcf: bool = False,
    bbl: str | None = _BBL_OK,
    tool_rc: int = 0,
    out_s: str = "",
    first_to: bool = False,
) -> Callable:
    """run_process 替身：xelatex 趟写 aux/pdf(+bcf)，工具趟按参数写 bbl。

    ``calls`` 收集 ``{"xelatex": n, "tools": [argv...]}``；``bbl=None``
    表示工具不落 .bbl（rc 失败形）；``extra_aux`` 追加 ``\\include`` 子件
    aux（``{相对径: 内容}``，与 main.aux 同趟落盘）。产物落 argv 内
    ``-output-directory=`` 目标——``outdir`` 编译下 aux/bbl 面仍在 ``out``。
    """

    def run(  # noqa: PLR0913
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        out_cap: int = 8 * 1024 * 1024,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[int | None, str, float, bool]:
        _ = (env, timeout, out_cap, should_cancel)
        if cmd[0] == _XE:
            calls["xelatex"] += 1
            out = Path(
                next(
                    t.split("=", 1)[1]
                    for t in cmd
                    if t.startswith("-output-directory=")
                )
            )
            if aux is not None:
                (out / "main.aux").write_text(aux, encoding="utf-8")
            for rel, body in (extra_aux or {}).items():
                sub_aux = out / rel
                sub_aux.parent.mkdir(parents=True, exist_ok=True)
                sub_aux.write_text(body, encoding="utf-8")
            if bcf:
                (out / "main.bcf").write_text("<bcf/>", encoding="utf-8")
            (out / "main.pdf").write_bytes(b"%PDF-fake")
            (out / "main.log").write_text("Output written\n", encoding="utf-8")
            to = first_to and calls["xelatex"] == 1
            return 0, out_s, 0.1, to
        calls["tools"].append(cmd)
        if bbl is not None:
            stem = cmd[1]
            tgt = cwd / f"{stem}.bbl"
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_text(bbl, encoding="utf-8")
        return tool_rc, "", 0.1, False

    return run


def _eng(
    monkeypatch: pytest.MonkeyPatch, run: Callable, *, tools: bool = True
) -> XelatexEngine:
    """patch 引擎缝 + 返回 binary 钉死的引擎实例。"""
    monkeypatch.setattr("texlate.compile.engine.run_process", run)
    monkeypatch.setattr(
        "texlate.compile.engine.find_tool",
        lambda n: f"/x/{n}" if tools and n in {"bibtex", "biber"} else None,
    )
    return XelatexEngine(binary=_XE)


def test_bibtex_fires_and_extends_to_three_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pin a: aux citation 态 → bibtex 趟间补 + 自适应档 3 趟。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(monkeypatch, _fake_run(calls))
    res = eng.compile(tmp_path, "main.tex", sandbox=False)
    assert calls["xelatex"] == 3  # noqa: PLR2004 - bib 采纳延趟：2→3
    assert calls["tools"] == [["/x/bibtex", "main"]]
    assert res.bib_ran == ["bibtex:main"]
    assert res.passes == 3  # noqa: PLR2004
    assert (tmp_path / "main.bbl").read_text(encoding="utf-8") == _BBL_OK


def test_passes_one_never_fires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pin b: passes=1 纯单趟契约——bib 不触发（classify/probe 零成本）。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(monkeypatch, _fake_run(calls))
    res = eng.compile(tmp_path, "main.tex", passes=1, sandbox=False)
    assert calls["xelatex"] == 1
    assert calls["tools"] == []
    assert res.bib_ran == []


def test_bundled_bbl_never_clobbered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pin c: bundled .bbl 在席 → bibtex 不跑、原件不动（cargo bbl 护闸）。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    bundled = tmp_path / "main.bbl"
    bundled.write_text("% cargo bbl, no .bib shipped\n", encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    # 给 rerun hint 让环续趟——证明在席 bbl 在续趟下仍不触发 bib。
    eng = _eng(monkeypatch, _fake_run(calls, out_s=_HINT))
    res = eng.compile(tmp_path, "main.tex", sandbox=False)
    assert calls["tools"] == []
    assert res.bib_ran == []
    assert bundled.read_text(encoding="utf-8") == "% cargo bbl, no .bib shipped\n"


def test_truncated_bbl_deleted_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pin d: bibtex 产出缺尾标 → 不采纳、删除残件、不计续趟信号。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(monkeypatch, _fake_run(calls, bbl=_BBL_TRUNC))
    res = eng.compile(tmp_path, "main.tex", sandbox=False)
    assert calls["tools"] == [["/x/bibtex", "main"]]
    assert res.bib_ran == []
    assert res.passes == 1  # 未采纳 → 无 hint → 自适应即收
    assert not (tmp_path / "main.bbl").exists()


def test_biber_arm_on_bcf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """pin e: .bcf 在席 + .bbl 缺席 → biber 臂；datalist ``\\endinput`` 尾标可采纳。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(
        monkeypatch,
        _fake_run(calls, aux=None, bcf=True, bbl="\\endrefsection\n\\endinput\n"),
    )
    res = eng.compile(tmp_path, "main.tex", sandbox=False)
    assert calls["tools"] == [["/x/biber", "main"]]
    assert res.bib_ran == ["biber:main"]
    assert calls["xelatex"] == 3  # noqa: PLR2004


def test_biber_skipped_on_bundled_bbl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """biber 臂同护 bundled .bbl——败北自删 poison 实证（bbl_regen）。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    bundled = tmp_path / "main.bbl"
    bundled.write_text("% bundled biber bbl\n", encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(monkeypatch, _fake_run(calls, aux=None, bcf=True, out_s=_HINT))
    res = eng.compile(tmp_path, "main.tex", sandbox=False)
    assert calls["tools"] == []
    assert res.bib_ran == []
    assert bundled.read_text(encoding="utf-8") == "% bundled biber bbl\n"


def test_biber_rc_fail_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """biber rc!=0 → 不采纳；其残件（若有）删除，下趟不吃 poison。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(
        monkeypatch,
        _fake_run(calls, aux=None, bcf=True, bbl=_BBL_TRUNC, tool_rc=2),
    )
    res = eng.compile(tmp_path, "main.tex", sandbox=False)
    assert calls["tools"] == [["/x/biber", "main"]]
    assert res.bib_ran == []
    assert not (tmp_path / "main.bbl").exists()


def test_no_bib_state_no_fire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """pin f: aux 无 ``\\bibdata`` → 不触发（零 bib 需求零成本）。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(monkeypatch, _fake_run(calls, aux="\\relax\n\\citation{a}\n"))
    res = eng.compile(tmp_path, "main.tex", sandbox=False)
    assert calls["tools"] == []
    assert res.bib_ran == []
    assert res.passes == 1


def test_timed_out_pass_no_bib_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """死趟不补 bib：超时恒收，工具零调用。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(monkeypatch, _fake_run(calls, first_to=True))
    res = eng.compile(tmp_path, "main.tex", sandbox=False)
    assert calls["tools"] == []
    assert res.bib_ran == []
    assert res.passes == 1
    assert res.timed_out is True


def test_explicit_passes_fires_without_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """显式 passes=2：趟间补 bib 但不延趟——caller 钉了 N。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(monkeypatch, _fake_run(calls))
    res = eng.compile(tmp_path, "main.tex", passes=2, sandbox=False)
    assert calls["xelatex"] == 2  # noqa: PLR2004 - 不延趟
    assert calls["tools"] == [["/x/bibtex", "main"]]
    assert res.bib_ran == ["bibtex:main"]
    assert res.passes == 2  # noqa: PLR2004


def test_multi_aux_each_gets_bibtex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """逐 aux 算法：``\\include`` 子件 aux 同吃（multibib/章节 .aux）。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(monkeypatch, _fake_run(calls, extra_aux={"sub/ch1.aux": _AUX_CITE}))
    res = eng.compile(tmp_path, "main.tex", sandbox=False)
    assert calls["tools"] == [["/x/bibtex", "main"], ["/x/bibtex", "sub/ch1"]]
    assert res.bib_ran == ["bibtex:main", "bibtex:sub/ch1"]
    assert (tmp_path / "sub" / "ch1.bbl").exists()


def test_bibtex_rc_fail_complete_bbl_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """bibtex 臂 rc 钝感：完整 .bbl 落盘即采纳（纯文件态闸，rc 不参与）——
    biber 臂 ``rc!=0`` 必弃的对照面（败北自删 poison 是 biber 独有行为）。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(monkeypatch, _fake_run(calls, tool_rc=1, bbl=_BBL_OK))
    res = eng.compile(tmp_path, "main.tex", sandbox=False)
    assert calls["tools"] == [["/x/bibtex", "main"]]
    assert res.bib_ran == ["bibtex:main"]
    assert res.passes == 3  # noqa: PLR2004 - 采纳同延趟
    assert (tmp_path / "main.bbl").read_text(encoding="utf-8") == _BBL_OK


def test_outdir_bib_pass_fires(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """outdir 落点：aux 扫描与 bbl 采纳走 ``out`` 面——bibtex 照常触发。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    outdir = tmp_path / "build"
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(monkeypatch, _fake_run(calls))
    res = eng.compile(tmp_path, "main.tex", outdir=outdir, sandbox=False)
    assert calls["tools"] == [["/x/bibtex", "main"]]
    assert res.bib_ran == ["bibtex:main"]
    assert (outdir / "main.bbl").read_text(encoding="utf-8") == _BBL_OK
    assert not (tmp_path / "main.bbl").exists()  # 产物全落 outdir，源树不染


def test_aux_scan_sorted_truncated_at_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """9+ aux 截断：``sorted(rglob)[:_BIB_AUX_SCAN_MAX]`` 序首 8 件吃 bibtex。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    for letter in "abcdefghij":  # 10 件 > _BIB_AUX_SCAN_MAX=8
        (tmp_path / f"{letter}.aux").write_text(_AUX_CITE, encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(monkeypatch, _fake_run(calls, aux=None))
    res = eng.compile(tmp_path, "main.tex", passes=2, sandbox=False)
    assert calls["tools"] == [["/x/bibtex", letter] for letter in "abcdefgh"]
    assert res.bib_ran == [f"bibtex:{letter}" for letter in "abcdefgh"]
    assert not (tmp_path / "i.bbl").exists()  # 截断面外 —— sorted 尾两件不扫
    assert not (tmp_path / "j.bbl").exists()


def test_missing_tool_no_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """bibtex/biber 缺席 → 不触发不炸，编译照常收。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(monkeypatch, _fake_run(calls, out_s=_HINT), tools=False)
    res = eng.compile(tmp_path, "main.tex", sandbox=False)
    assert calls["tools"] == []
    assert res.bib_ran == []
    assert res.passes == 2  # noqa: PLR2004 - hint 续趟照旧


def test_empty_bbl_treated_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """空 .bbl 视同缺席（无物可失）→ bibtex 触发重生。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    (tmp_path / "main.bbl").write_text("", encoding="utf-8")
    calls: dict = {"xelatex": 0, "tools": []}
    eng = _eng(monkeypatch, _fake_run(calls))
    res = eng.compile(tmp_path, "main.tex", sandbox=False)
    assert calls["tools"] == [["/x/bibtex", "main"]]
    assert res.bib_ran == ["bibtex:main"]
