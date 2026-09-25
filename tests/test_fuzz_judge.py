r"""judge/cjkmap/latex209/redlines 四模块对抗性质 fuzz——判定组合/PDF 资源走查/2.09 升级/红线单源。

oracle 方法：判定树/窗口语义/选项路由按 docstring 承诺**独立重述**——judge
的 reasons/notes 序、misschar 限界窗的逐位停词扫描、latex209 的输出全文
重建都由本文件重算，不复用 impl 的组装路径；分类层 ``classify_error``/
``parse_log``/``visible_tex`` 与定位 regex ``_DOCSTYLE_RE`` 走共享件
（独立受测——oracle 只钉组合语义，不重复造词法）。misschar 限界窗 oracle
经 tmp/judge-fuzz 对拍实证：20 万随机汤 + 全边界格零分歧。

缺陷钉账（``xfail(strict=True)`` 钉**期望**契约——修复落地 XPASS 转红即拆钉）：

- J1 ``latex209._uses_ds_at`` ``ds@`` 裸子串过触发（原 latex209.py:280
  ``_DS_AT_RE = re.compile(r"ds@")``）：随源 ``<cls>.sty`` 里
  ``\def\mids@foo{bar}``、注释行 ``% ... ds@`` 这类**非选项分发**的
  ``ds@`` 字样即误判 ``reject/latex209_ds_at``。**已修**：``\bds@``
  词首边界锚（``\ds@``/``{ds@``/`` ds@`` 三形全收，``\mids@foo`` 类
  内嵌子串无界不中）+ 检索面走 ``visible_tex`` 遮盖（注释字样不计）。
- J2 ``cjkmap._iter_pdf_fonts`` 不沿页树继承 ``/Resources``：PDF 允许把
  Resources 挂 ``/Pages`` 父节点做全文档共享——该形态下 GB1 字体
  整棵漏走，embed 返回 0。**已修**：``_page_resources`` 沿 ``/Parent``
  逐层全收（页级空表不遮蔽祖先共享表——pypdf ``get_inherited``
  「键存在即返回」语义实证不适用），环/畸形链截断。
- J3 ``cjkmap._iter_pdf_fonts`` 畸形 ``/Resources``（非 dict 对象）→
  ``AttributeError`` 穿透 ``embed_cjk_mappings``：per-font 容错壳只包
  ``_font_needs_gb1_cmap``，资源级异常把整篇注入拖死（worker/e2e
  best-effort 壳吞成一行 log，静默不注入）。**已修**：资源级
  try/isinstance 闸与 per-ref 容错同粒度，畸形段各自坍弃。
- J4 l2 ``missing_glyph_nullfont`` 行内 ``.*`` 与 gate 限界窗双向分歧
  （redlines.py ``Missing character:.*in font nullfont``）：
  (a) 79 列折行把 ``in font nullfont`` 推进续行 → engine/judge 窗内
  豁免、l2 漏吃归 ``missing_glyph_cjk`` 判红——违「无一层判红」；
  (b) 已声明真字体后行尾挂 ``in font nullfont`` 字样 → engine 窗判红、
  l2 误豁免——违「已声明字体的消息不被后行误豁免」（logpipe pin#2）。
  **已修**：l2 pattern 换共享 ``_MISSCHAR_NULLFONT_PROBE``（窗口语义
  单源，J4b）+ ``l2.py`` misschar 行无 ``in font `` 时把续行拼进
  规则检索面（``next_ln``，记录面仍物理行，J4a）。

观测语义钉（非缺陷——当前行为即取舍，改动前先读这段）：

- ``_primary_docstyle`` 深度计数可负：声明点前的游离 ``}`` 使深度跌负 →
  其后所有 ``\documentstyle`` 命不中深度 0 → ``no-docstyle`` 原样放行
  （坏源保守不动）。
- ``\documentstyle{cls}[opts]`` 选项后置非 209 形态：``[opts]`` 留原位
  成正文文本，不进选项路由。
- cjkmap ``/ToUnicode`` 为 ``NullObject`` 按「已存在」处理跳过注入。
"""

from __future__ import annotations

import copy
import dataclasses
import re
from collections import Counter
from typing import TYPE_CHECKING, NamedTuple

import pytest
from _fuzzkit import fuzz_rng
from _latex209kit import target_always_resolvable  # noqa: F401
from conftest import judge_mod
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NullObject,
    NumberObject,
    TextStringObject,
)

from texlate.compile import latex209
from texlate.compile.cjkmap import _GB1_UCS2_CMAP, embed_cjk_mappings
from texlate.compile.engine import CompRes
from texlate.compile.judge import (
    CJK_MIN_CHARS,
    CLEAN_ERR_MAX,
    DIRTY_FIRST_CATEGORIES,
    Verdict,
    count_missing_chars,
    judge,
)
from texlate.compile.latex209 import (
    _CLASS_MAP,
    _DS_AT_CLASSES,
    _INCOMPAT_PKGS,
    _KERNEL_OPTS,
    _MULTICOLS_SHIM,
    _PKG_OPTS,
    _PRE_CLASS_SHIM,
    _REVTEX209_SHIM,
    _STD_CLASSES,
    COMPAT_SHIM,
    _ships_style,
    _split_opts,
    _uses_ds_at,
    upgrade_209,
)
from texlate.compile.loginfo import classify_error, parse_log
from texlate.compile.mask import visible_tex
from texlate.redlines import (
    L2_REDLINE_CLASSES,
    REDLINES,
    REDLINES_BY_ID,
    LayerSpec,
    name_pattern,
)
from texlate.textutil import DOCSTYLE_DECL_RX, DOCSTYLE_RX
from texlate.validate import l2

if TYPE_CHECKING:
    import random
    from pathlib import Path

# ================================================================ misschar 限界窗 oracle
#: 独立重述「本消息体内可达 in font nullfont」：逐位停词扫描，不走 regex。
_MISSCHAR_TAG = "Missing character:"
_MISSCHAR_NF = "in font nullfont"
_MISSCHAR_STOPS = ("Missing character", "in font ")
_MISSCHAR_LINE_MAX = 90


def _first_stop(line: str) -> int:
    """行内首个停词（``Missing character``/``in font ``）起点；无则行长。"""
    for j in range(len(line)):
        if any(line.startswith(t, j) for t in _MISSCHAR_STOPS):
            return j
    return len(line)


def _nf_reachable(scan: str) -> bool:
    """``scan`` = 冒号后文本；限界窗（≤90/行、至多跨一个 \\n）尾接 nullfont 与否。"""
    nl = scan.find("\n")
    line1 = scan if nl < 0 else scan[:nl]
    b1 = _first_stop(line1)
    if b1 <= _MISSCHAR_LINE_MAX and line1[b1:].startswith(_MISSCHAR_NF):
        return True
    # 跨行前提：第一行须全程无停词且 ≤90（被窗吃光到换行符）
    if nl >= 0 and b1 == len(line1) <= _MISSCHAR_LINE_MAX:
        rest = scan[nl + 1 :]
        nl2 = rest.find("\n")
        line2 = rest if nl2 < 0 else rest[:nl2]
        b2 = _first_stop(line2)
        return b2 <= _MISSCHAR_LINE_MAX and line2[b2:].startswith(_MISSCHAR_NF)
    return False


def _misschar_oracle(text: str) -> tuple[int, int]:
    """逐出现位分划 → ``(gate_hits, nullfont_hits)``；每位必居其一。"""
    gate = nf = 0
    pos = 0
    while True:
        i = text.find(_MISSCHAR_TAG, pos)
        if i < 0:
            break
        if _nf_reachable(text[i + len(_MISSCHAR_TAG) :]):
            nf += 1
        else:
            gate += 1
        pos = i + len(_MISSCHAR_TAG)
    return gate, nf


# ================================================================ judge 判定组合
_LOG_ATOMS = [
    "This is XeTeX, Version 3.141592653 (TeX Live 2024)",
    "noise line",
    "(./main.tex",
    ")",
    "l.12 \\foo",
    "! Undefined control sequence.",
    "! Missing number, treated as zero.",
    "! LaTeX Error: File `x.sty' not found.",
    '! Package fontspec Error: The font "X" cannot be found.',
    "! File `foo.sty' not found.",
    "./main.tex:10: Undefined control sequence",
    "./main.tex:4: LaTeX Warning: something",
    "File `fig.png' not found",
    "File `fig.mps' not found",
    "Invalid UTF-8 byte or sequence at line 9 replaced by U+FFFD.",
    "Missing character: There is no 中 (U+4E2D) in font cmr10",
    "Missing character: There is no 中 (U+4E2D) in font nullfont",
    "Missing character: There is no (U+FFFD) in font cmr10!",
    "Missing character: There is no 中 (U+4E2D) filler-past-seventy-nine-cols-xxxxx",
    " in font nullfont",
    "Package foo Warning: something",
    "Overfull \\hbox (12.0pt too wide) in paragraph",
]


def _gen_log_soup(rng: random.Random) -> str:
    """随机 log 汤——错误双格式/红线命中/nullfont/折行续行混合。"""
    lines = [rng.choice(_LOG_ATOMS) for _ in range(rng.randint(0, 20))]
    if rng.random() < 0.3:  # noqa: PLR2004 -- 汤配料概率
        # 系统 texmf 件产生的 invalid_utf8 → warnings_sys 观察项路径
        lines += [
            "(/usr/share/texmf-dist/tex/latex/base/uc.sty",
            "Invalid UTF-8 byte or sequence at line 3 replaced by U+FFFD.",
            ")",
        ]
    if rng.random() < 0.25:  # noqa: PLR2004
        # 79 列折行：nullfont 声明被推进续行
        lines += [
            "Missing character: There is no 中 (U+4E2D) " + "p" * rng.randint(0, 95),
            " in font nullfont",
        ]
    return "\n".join(lines)


class _Expect(NamedTuple):
    """oracle 重算的 judge 期望字段组。"""

    status: str
    reasons: list[str]
    notes: list[str]
    missing_chars: int
    cjk_chars: int
    category: str | None
    payload: str | None


def _oracle_judge(  # noqa: C901, PLR0912 -- 判定树逐支重述，压平伤读
    res: CompRes,
    *,
    expect_cjk: bool,
    log_arg: str,
    file_text: str | None,
    cjk: int,
) -> _Expect:
    """按 judge docstring（docs/spec/compile.md）独立重述判定树。

    ``file_text`` = res.log_path 可读文件内容（目录/缺席 → None——
    impl 侧 ``exists()``/``OSError`` 两支都坍成 ""）。
    """
    if res.timed_out:
        # impl 侧 judge 超时早退按 taxonomy 细分 category（vbox 刷屏
        # → runaway_output，否则 timeout）——oracle 同源复算。
        cat, _pay = classify_error(
            res.log.first_error, res.log.error_ctx, res.log.tail, timed_out=True
        )
        return _Expect("fail", ["timeout"], [], 0, -1, cat, None)
    reasons: list[str] = []
    notes: list[str] = []
    sig = res.killed_signal
    if sig is None and res.rc is not None and res.rc < 0:
        sig = -res.rc
    if sig is not None:
        notes.append(f"engine_killed:SIG{sig}")
        reasons.append(f"killed_by_signal:{sig}")
    if not res.has_pdf:
        reasons.append("no_pdf")
        cat, pay = classify_error(
            res.log.first_error, res.log.error_ctx, res.log.tail, timed_out=False
        )
        category, payload = ("other", None) if cat == "clean" else (cat, pay)
        return _Expect("fail", reasons, notes, 0, -1, category, payload)
    cat, pay = classify_error(
        res.log.first_error, res.log.error_ctx, res.log.tail, timed_out=False
    )
    if res.log.n_errors > CLEAN_ERR_MAX:
        reasons.append(f"errors>{CLEAN_ERR_MAX} ({res.log.n_errors})")
    if cat in DIRTY_FIRST_CATEGORIES:
        reasons.append(f"first_error={cat}:{pay}")
    reasons += [f"warn:{hit}" for hit in res.log.warnings_hit]
    notes += [f"sys_warn:{hit}" for hit in res.log.warnings_sys]
    full = log_arg or (file_text or "")
    missing, nf = _misschar_oracle(full)
    if nf:
        notes.append(f"missing_character_nullfont×{nf}")
    if expect_cjk and missing:
        reasons.append(f"missing_character×{missing}")
    cjk_chars = -1
    if expect_cjk:
        cjk_chars = cjk if res.pdf is not None else -1
        if cjk_chars == 0:
            reasons.append("cjk_chars=0")
        elif 0 < cjk_chars < CJK_MIN_CHARS:
            reasons.append(f"cjk_chars<{CJK_MIN_CHARS} ({cjk_chars})")
        elif cjk_chars < 0:
            if missing:
                reasons.append("cjk_unverified+missing_chars")
            else:
                notes.append("cjk_unverified(pdftotext absent)")
    if expect_cjk and cjk_chars == 0:
        # tofu 否决：出 pdf 但 0 中文字节 → fail（partial 不算交付面，
        # bench onfail _want_fix 只接 fail；impl 末位同判）。
        notes.append("tofu_veto")
        status = "fail"
    else:
        status = "clean" if not reasons else "partial"
    return _Expect(status, reasons, notes, missing, cjk_chars, cat, pay)


def _assert_composition_invariants(
    v: Verdict, res: CompRes, before: CompRes, ctx: str, *, expect_cjk: bool
) -> None:
    """verdict 组合结构不变量：账本一致性 + status 三分位 + 非变异。"""
    assert v.n_errors == res.log.n_errors, ctx
    assert v.warnings_hit == list(res.log.warnings_hit), ctx
    # 构成账本：逐错误行计数；error_pay ⊆ error_cats 且 payload 非空
    exp_cats = 0 if res.timed_out else len(res.log.errors)
    assert sum(v.error_cats.values()) == exp_cats, ctx
    assert set(v.error_pay) <= set(v.error_cats), ctx
    assert all(isinstance(p, str) and p for p in v.error_pay.values()), ctx
    # status 三分位互斥且由 reasons/has_pdf/tofu 否决完全决定
    vetoed = expect_cjk and v.cjk_chars == 0
    assert v.status in {"clean", "partial", "fail"}
    assert (v.status == "fail") == (res.timed_out or not res.has_pdf or vetoed), ctx
    assert (v.status == "clean") == (res.has_pdf and not v.reasons), ctx
    # 非变异
    assert res == before, ctx


class TestJudge:
    """judge.py——verdict 组合不变量 + 判定树全文 oracle 对拍。"""

    def test_oracle_flag_matrix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """旗标矩阵 × log 汤：status/reasons/notes 逐字段对拍 + 结构不变量。"""
        rng = fuzz_rng(20260917)
        jm = judge_mod()
        for it in range(400):
            soup = _gen_log_soup(rng)
            res = CompRes(engine=rng.choice(["xelatex", "tectonic"]))
            res.log = parse_log(soup)
            res.ok = rng.random() < 0.8  # noqa: PLR2004
            res.timed_out = rng.random() < 0.1  # noqa: PLR2004
            res.rc = rng.choice([None, 0, 0, 1, -9, -13])
            res.killed_signal = rng.choice([None, None, None, 9, 13])
            if rng.random() < 0.75:  # noqa: PLR2004
                p = tmp_path / f"o{it}.pdf"
                p.write_bytes(b"%PDF-x")
                res.pdf = p
                res.pdf_bytes = p.stat().st_size
                if rng.random() < 0.1:  # noqa: PLR2004
                    res.pdf_bytes = 0  # 空 pdf → has_pdf False
            file_text = None
            lp = rng.random()
            if lp < 0.35:  # noqa: PLR2004
                file_text = _gen_log_soup(rng)
                lp_path = tmp_path / f"l{it}.log"
                lp_path.write_text(file_text)
                res.log_path = lp_path
            elif lp < 0.45:  # noqa: PLR2004
                res.log_path = tmp_path / f"dir{it}"
                res.log_path.mkdir()  # 目录 → OSError → ""
            elif lp < 0.55:  # noqa: PLR2004
                res.log_path = tmp_path / f"missing{it}.log"  # 不存在
            log_arg = _gen_log_soup(rng) if rng.random() < 0.5 else ""  # noqa: PLR2004
            expect_cjk = rng.random() < 0.5  # noqa: PLR2004
            cjk = rng.choice([-1, 0, 5, 19, 20, 500])
            monkeypatch.setattr(
                jm, "pdf_text_stats", lambda _p, _v=cjk: None if _v < 0 else (_v, 0)
            )

            before = copy.deepcopy(res)
            v = judge(res, expect_cjk=expect_cjk, log_text=log_arg)
            exp = _oracle_judge(
                res,
                expect_cjk=expect_cjk,
                log_arg=log_arg,
                file_text=file_text,
                cjk=cjk,
            )
            ctx = f"it={it}\nsoup={soup!r}\nrc={res.rc} sig={res.killed_signal} to={res.timed_out}"
            assert v.status == exp.status, ctx
            assert v.reasons == exp.reasons, ctx
            assert v.notes == exp.notes, ctx
            assert v.missing_chars == exp.missing_chars, ctx
            assert v.cjk_chars == exp.cjk_chars, ctx
            assert v.category == exp.category, ctx
            assert v.payload == exp.payload, ctx
            _assert_composition_invariants(v, res, before, ctx, expect_cjk=expect_cjk)
            v2 = judge(res, expect_cjk=expect_cjk, log_text=log_arg)
            assert dataclasses.asdict(v2) == dataclasses.asdict(v), ctx

    def test_timeout_shortcircuit_exact(self) -> None:
        """超时早退：reasons 恰 ``["timeout"]``——自杀 SIGKILL 不报成引擎崩。

        warnings_hit 在早退前已拷贝；error_cats 不构成、cjk_chars 未测。
        """
        res = CompRes(engine="xelatex")
        res.timed_out = True
        res.killed_signal = 9  # 超时他杀留下的信号不顶包
        res.log = parse_log("! Undefined control sequence.\nl.1\n")
        res.log.warnings_hit.append("missing_chars")
        v = judge(res, expect_cjk=True, log_text="Missing character: x\n")
        assert v.status == "fail"
        assert v.reasons == ["timeout"]
        assert v.notes == []
        assert v.error_cats == {}
        assert v.cjk_chars == -1
        assert v.warnings_hit == ["missing_chars"]

    def test_log_text_param_wins_over_path(self, tmp_path: Path) -> None:
        """``log_text`` 实参优先于 ``res.log_path`` 回退读。"""
        logf = tmp_path / "main.log"
        logf.write_text("Missing character: There is no 中 (U+4E2D) in font cmr10\n")
        res = CompRes(engine="xelatex")
        res.log_path = logf
        p = tmp_path / "main.pdf"
        p.write_bytes(b"%PDF")
        res.pdf, res.pdf_bytes = p, 4
        v = judge(res, log_text="clean\n")
        assert v.missing_chars == 0  # 实参汤没有 misschar → 文件里的不计

    def test_log_path_fallback_and_oserror(self, tmp_path: Path) -> None:
        """实参空 → 读 log_path；目录/缺席 → 静默坍 ``""``。"""
        logf = tmp_path / "m.log"
        logf.write_text("Missing character: There is no 中 (U+4E2D) in font cmr10\n")
        res = CompRes(engine="xelatex")
        res.log_path = logf
        p = tmp_path / "m.pdf"  # misschar 检查只在 has_pdf 支跑
        p.write_bytes(b"%PDF")
        res.pdf, res.pdf_bytes = p, 4
        assert judge(res).missing_chars == 1
        res.log_path = tmp_path / "adir"
        res.log_path.mkdir()
        assert judge(res).missing_chars == 0
        res.log_path = tmp_path / "ghost.log"
        assert judge(res).missing_chars == 0

    def test_signal_priority_killed_over_rc(self) -> None:
        """``killed_signal`` 压 ``rc<0``——任一 pass 死亡不被末 pass 掩盖。"""
        res = CompRes(engine="xelatex")
        res.rc = -13
        res.killed_signal = 9
        v = judge(res)
        assert "killed_by_signal:9" in v.reasons
        assert "engine_killed:SIG9" in v.notes
        res.killed_signal = None
        v = judge(res)
        assert "killed_by_signal:13" in v.reasons  # rc<0 兜底

    def test_positive_rc_ignored(self, tmp_path: Path) -> None:
        """判据非修复：正 rc（引擎报警退出码）不进 reasons——看产物不看码。"""
        res = CompRes(engine="xelatex")
        res.rc = 5
        res.ok = False
        p = tmp_path / "m.pdf"
        p.write_bytes(b"%PDF")
        res.pdf, res.pdf_bytes = p, 4
        v = judge(res, log_text="clean\n")
        assert v.status == "clean"

    def test_missing_chars_no_reason_without_expect_cjk(self, tmp_path: Path) -> None:
        """缺字形只在 ``expect_cjk`` 下污染 status（中文静默丢失信号语义）。"""
        res = CompRes(engine="xelatex")
        p = tmp_path / "m.pdf"
        p.write_bytes(b"%PDF")
        res.pdf, res.pdf_bytes = p, 4
        log = "Missing character: There is no 中 (U+4E2D) in font cmr10\n"
        v = judge(res, log_text=log, expect_cjk=False)
        assert v.missing_chars == 1
        assert v.status == "clean"  # 计数照记，reason 不生
        v = judge(res, log_text=log, expect_cjk=True)
        assert "missing_character×1" in v.reasons
        assert v.status == "partial"

    def test_cjk_render_check_branches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cjk 检查四支：0 / <20 / absent+misschar / absent 净。"""
        res = CompRes(engine="xelatex")
        p = tmp_path / "m.pdf"
        p.write_bytes(b"%PDF")
        res.pdf, res.pdf_bytes = p, 4
        jm = judge_mod()
        monkeypatch.setattr(jm, "pdf_text_stats", lambda _p: (19, 0))
        v = judge(res, expect_cjk=True)
        assert v.reasons == [f"cjk_chars<{CJK_MIN_CHARS} (19)"]
        monkeypatch.setattr(jm, "pdf_text_stats", lambda _p: None)
        v = judge(
            res,
            expect_cjk=True,
            log_text="Missing character: There is no 中 in font cmr10\n",
        )
        assert "cjk_unverified+missing_chars" in v.reasons
        v = judge(res, expect_cjk=True, log_text="clean\n")
        assert "cjk_unverified(pdftotext absent)" in v.notes


# ================================================================ redlines 单源 + 跨层一致
class TestRedlines:
    """redlines.py——注册表结构不变量 + nullfont 跨层豁免口径。"""

    def test_registry_patterns_compile_and_ids_unique(self) -> None:
        """每条登记的 pattern 可编译；id 唯一；每条至少挂一层。"""
        ids = [r.id for r in REDLINES]
        assert len(ids) == len(set(ids))
        for r in REDLINES:
            layers = [r.engine, r.rules, r.l2, r.judge]
            assert any(spec is not None for spec in layers) or r.concept_only, r.id
            for spec in layers:
                if spec is not None and spec.pattern is not None:
                    re.compile(spec.pattern)
        # 派生类（无 pattern 的 l2 spec）必须在 l2_redline 语义里出现名
        derived = [
            r.l2.name for r in REDLINES if r.l2 is not None and r.l2.pattern is None
        ]
        assert set(derived) <= L2_REDLINE_CLASSES

    def test_name_pattern_valueerror(self) -> None:
        """``pattern=None``/``spec=None`` 属登记错误——ValueError 不静默。"""
        with pytest.raises(ValueError, match="lacks pattern"):
            name_pattern(None)
        with pytest.raises(ValueError, match="lacks pattern"):
            name_pattern(LayerSpec("x"))
        assert name_pattern(LayerSpec("x", "p")) == ("x", "p")

    def test_misschar_gate_probe_partition_oracle(self) -> None:
        """gate+probe 恰划分全部 misschar 出现位——oracle 逐位对拍。

        （logpipe 已钉划分不变量；本节加的是**逐位** oracle 等值——
        窗口边界语义本身的对拍。）
        """
        rng = fuzz_rng(20260918)
        gate_rx = re.compile(name_pattern(REDLINES_BY_ID["missing_char"].judge)[1])
        nf_rx = re.compile(
            name_pattern(REDLINES_BY_ID["missing_char_nullfont"].judge)[1]
        )
        alphabet = [
            "Missing character:",
            "Missing character",
            "in font ",
            "in font nullfont",
            "in font cmr10",
            "in font nullfontx",
            "中 (U+4E2D)",
            "x",
            " ",
            "\n",
            "\r",
        ]
        for _ in range(6000):
            s = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 12)))
            if rng.random() < 0.4:  # noqa: PLR2004 -- 边界偏置
                s += "x" * rng.randint(85, 95) + "in font nullfont"
            og, onf = _misschar_oracle(s)
            assert (len(gate_rx.findall(s)), len(nf_rx.findall(s))) == (og, onf), s
            assert count_missing_chars(s) == og, s

    def test_sameline_nullfont_all_layers_exempt(self) -> None:
        """同行 nullfont misschar 三层一致豁免（当前成立的口径区）。"""
        rng = fuzz_rng(20260919)
        for _ in range(500):
            ch = rng.choice(["中", "x", ";", "文"])
            ann = rng.choice(["(U+4E2D)", '("4E2D)', ""])
            line = f"Missing character: There is no {ch} {ann} in font nullfont"
            text = f"noise\n{line}\nmore"
            assert count_missing_chars(text) == 0
            info = parse_log(text)
            assert "missing_chars" not in info.warnings_hit
            v = l2.parse_log_text(text)
            assert v.warnings.by_class.get("missing_glyph_nullfont") == 1
            assert v.warnings.redlines == []

    def test_l2_wrapped_nullfont_should_not_redline(self) -> None:
        """J4a：``in font nullfont`` 落续行 → l2 应仍归观察类不判红。"""
        text = (
            "Missing character: There is no 中 (U+4E2D) "
            + "p" * 40
            + "\n in font nullfont\n"
        )
        # 对照面（成立）：engine gate 豁免、judge 不计
        assert count_missing_chars(text) == 0
        assert "missing_chars" not in parse_log(text).warnings_hit
        # 期望契约：l2 同样豁免
        v = l2.parse_log_text(text)
        assert v.warnings.by_class.get("missing_glyph_nullfont") == 1
        assert v.warnings.redlines == []

    def test_l2_trailing_nullfont_after_real_font_should_redline(self) -> None:
        """J4b：``in font cmr10 in font nullfont`` → 真字体先行 → 应判红。"""
        text = "Missing character: There is no 中 (U+4E2D) in font cmr10 in font nullfont\n"
        # 对照面（成立）：engine gate 命中、judge 计数
        assert count_missing_chars(text) == 1
        assert "missing_chars" in parse_log(text).warnings_hit
        # 期望契约：l2 不得豁免——落 missing_glyph_cjk 红线
        v = l2.parse_log_text(text)
        assert v.warnings.by_class.get("missing_glyph_cjk") == 1
        assert any("missing_glyph_cjk" in r for r in v.warnings.redlines)


# ================================================================ cjkmap PDF 走查
def _gb1_font(w: PdfWriter, **kw: object) -> DictionaryObject:
    """构造 GB1 Type0 字体 dict；kw: tu_ref/tu_null/ordering/encoding/desc。"""
    cid_sys = DictionaryObject(
        {
            NameObject("/Registry"): TextStringObject("Adobe"),
            NameObject("/Ordering"): TextStringObject(str(kw.get("ordering", "GB1"))),
            NameObject("/Supplement"): NumberObject(5),
        }
    )
    if kw.get("cid_indirect"):
        cid_sys = w._add_object(cid_sys)  # noqa: SLF001 -- 间接 CIDSystemInfo 形态
    cid_font = w._add_object(  # noqa: SLF001 -- pypdf 无公开 add-raw API
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/CIDFontType0"),
                NameObject("/CIDSystemInfo"): cid_sys,
            }
        )
    )
    desc = kw.get("desc", "normal")
    if desc == "normal":
        descendants = ArrayObject([cid_font])
    elif desc == "empty":
        descendants = ArrayObject([])
    elif desc == "name":
        descendants = ArrayObject([NameObject("/oops")])
    elif desc == "indirect":
        descendants = w._add_object(ArrayObject([cid_font]))  # noqa: SLF001
    else:
        descendants = None
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/Encoding"): NameObject(str(kw.get("encoding", "/Identity-H"))),
        }
    )
    if descendants is not None:
        font[NameObject("/DescendantFonts")] = descendants
    if kw.get("tu_ref"):
        tu = DecodedStreamObject()
        tu.set_data(b"begincmap\nendcmap\n")
        font[NameObject("/ToUnicode")] = w._add_object(tu.flate_encode())  # noqa: SLF001
    if kw.get("tu_null"):
        font[NameObject("/ToUnicode")] = NullObject()
    return font


def _write_pdf(w: PdfWriter, path: Path) -> None:
    with path.open("wb") as fh:
        w.write(fh)
    w.close()


def _page_fonts(reader: PdfReader, page_idx: int = 0) -> dict:
    return reader.pages[page_idx]["/Resources"]["/Font"]


class TestCjkmap:
    """cjkmap.py——页树/XObject 字体走查 + GB1 条件 + 原子写不变量。"""

    def test_embed_mixed_fonts_count_and_shared_stream(self, tmp_path: Path) -> None:
        """混合字体表：恰命中条件者注入；全部共享同一 cmap 流对象。"""
        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        page = w.pages[0]
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/GB1A"): _gb1_font(w),
                        NameObject("/GB1V"): _gb1_font(w, encoding="/Identity-V"),
                        NameObject("/TU"): _gb1_font(w, tu_ref=True),
                        NameObject("/JIS"): _gb1_font(w, ordering="Japan1"),
                        NameObject("/WIN"): _gb1_font(w, encoding="/WinAnsiEncoding"),
                        NameObject("/NOD"): _gb1_font(w, desc="none"),
                        NameObject("/T1"): DictionaryObject(
                            {
                                NameObject("/Type"): NameObject("/Font"),
                                NameObject("/Subtype"): NameObject("/Type1"),
                            }
                        ),
                    }
                )
            }
        )
        pdf = tmp_path / "mix.pdf"
        _write_pdf(w, pdf)
        n = embed_cjk_mappings(pdf)
        assert n == 2  # noqa: PLR2004 -- GB1A+GB1V
        fonts = _page_fonts(PdfReader(str(pdf)))
        expected_cmap = _GB1_UCS2_CMAP.read_bytes()
        refs = []
        for name in ("/GB1A", "/GB1V"):
            f = fonts[name].get_object()
            tu = f["/ToUnicode"]  # getitem 自动解引用 → 流对象
            assert tu.get_data() == expected_cmap
            raw = f.get("/ToUnicode")  # .get 不解引用 → IndirectObject
            refs.append((raw.idnum, raw.generation))
        assert refs[0] == refs[1]  # 共享单一 cmap 流对象
        for name in ("/TU", "/JIS", "/WIN", "/NOD", "/T1"):
            f = fonts[name].get_object()
            if name == "/TU":
                continue  # 自带 ToUnicode 保留
            assert "/ToUnicode" not in f, name

    def test_embed_idempotent_and_zero_count_no_write(self, tmp_path: Path) -> None:
        """幂等：二次注入 0 且文件字节不变；零命中不写盘不留孤儿。"""
        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        w.pages[0][NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F"): _gb1_font(w)})}
        )
        pdf = tmp_path / "once.pdf"
        _write_pdf(w, pdf)
        assert embed_cjk_mappings(pdf) == 1
        blob = pdf.read_bytes()
        assert embed_cjk_mappings(pdf) == 0  # 已有 ToUnicode → 全跳过
        assert pdf.read_bytes() == blob  # count==0 → 不落盘
        assert not (tmp_path / "once.mapped.pdf").exists()  # 无临时孤儿

        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        pdf2 = tmp_path / "none.pdf"
        _write_pdf(w, pdf2)
        blob2 = pdf2.read_bytes()
        assert embed_cjk_mappings(pdf2) == 0
        assert pdf2.read_bytes() == blob2
        assert not (tmp_path / "none.mapped.pdf").exists()

    def test_embed_indirect_everything(self, tmp_path: Path) -> None:
        """间接引用全形态：/Resources、/Font 表、DescendantFonts、CIDSystemInfo。"""
        w = PdfWriter()
        fonts_ref = w._add_object(  # noqa: SLF001
            DictionaryObject(
                {NameObject("/F"): _gb1_font(w, desc="indirect", cid_indirect=True)}
            )
        )
        res_ref = w._add_object(  # noqa: SLF001
            DictionaryObject({NameObject("/Font"): fonts_ref})
        )
        w.add_blank_page(width=200, height=200)
        w.pages[0][NameObject("/Resources")] = res_ref
        pdf = tmp_path / "ind.pdf"
        _write_pdf(w, pdf)
        assert embed_cjk_mappings(pdf) == 1
        f = _page_fonts(PdfReader(str(pdf)))["/F"].get_object()
        assert "/ToUnicode" in f

    def test_embed_xobject_recursion_self_loop(self, tmp_path: Path) -> None:
        """XObject /Resources 递归走查 + 自环不死循环（id 去重）。"""
        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        page = w.pages[0]
        xobj = DecodedStreamObject()
        xobj.set_data(b"q Q")
        xobj[NameObject("/Type")] = NameObject("/XObject")
        xobj[NameObject("/Subtype")] = NameObject("/Form")
        xobj_ref = w._add_object(xobj)  # noqa: SLF001
        xobj[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F9"): _gb1_font(w)}
                ),
                NameObject("/XObject"): DictionaryObject(
                    {NameObject("/SELF"): xobj_ref}
                ),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/XObject"): DictionaryObject({NameObject("/XO"): xobj_ref})}
        )
        pdf = tmp_path / "xo.pdf"
        _write_pdf(w, pdf)
        assert embed_cjk_mappings(pdf) == 1

    def test_perfont_faults_isolated(self, tmp_path: Path) -> None:
        """单字体结构异常不拖垮整篇——容错壳逐字体生效。"""
        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        w.pages[0][NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/JUNK"): NameObject("/NotARef"),
                        NameObject("/EMPTY"): _gb1_font(w, desc="empty"),
                        NameObject("/NAME"): _gb1_font(w, desc="name"),
                        NameObject("/GOOD"): _gb1_font(w),
                    }
                )
            }
        )
        pdf = tmp_path / "fault.pdf"
        _write_pdf(w, pdf)
        assert embed_cjk_mappings(pdf) == 1
        f = _page_fonts(PdfReader(str(pdf)))["/GOOD"].get_object()
        assert "/ToUnicode" in f

    def test_tounicode_null_treated_present(self, tmp_path: Path) -> None:
        """观测语义钉：``/ToUnicode = null`` 按「已存在」跳过注入。"""
        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        w.pages[0][NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F"): _gb1_font(w, tu_null=True)}
                )
            }
        )
        pdf = tmp_path / "null.pdf"
        _write_pdf(w, pdf)
        assert embed_cjk_mappings(pdf) == 0

    def test_inherited_resources_on_pages_node(self, tmp_path: Path) -> None:
        """J2：``/Pages`` 父节点继承 ``/Resources`` 下的 GB1 字体应命中。"""
        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        page = w.pages[0]
        pages_node = page["/Parent"].get_object()
        pages_node[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F"): _gb1_font(w)})}
        )
        pdf = tmp_path / "inherited.pdf"
        _write_pdf(w, pdf)
        assert embed_cjk_mappings(pdf) == 1
        fonts = PdfReader(str(pdf)).pages[0]["/Parent"]["/Resources"]["/Font"]
        assert "/ToUnicode" in fonts["/F"].get_object()

    def test_malformed_resources_should_not_kill_document(self, tmp_path: Path) -> None:
        """J3：畸形 ``/Resources`` 应按资源粒度跳过，好字体照常注入。"""
        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        w.pages[0][NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F"): _gb1_font(w)})}
        )
        w.add_blank_page(width=200, height=200)
        w.pages[1][NameObject("/Resources")] = ArrayObject([NameObject("/junk")])
        pdf = tmp_path / "malformed.pdf"
        _write_pdf(w, pdf)
        assert embed_cjk_mappings(pdf) == 1  # page0 字体应仍注入
        f = _page_fonts(PdfReader(str(pdf)), 0)["/F"].get_object()
        assert "/ToUnicode" in f


# ================================================================ latex209 受限升级
def _oracle_split(optspan: str | None) -> list[str]:
    """独立重述：非空白字符即选项文本，逗号切分丢空段。"""
    if not optspan:
        return []
    compact = "".join(c for c in optspan if not c.isspace())
    return [o for o in compact.split(",") if o]


def _oracle_primary(vis: str) -> re.Match[str] | None:
    """独立重述深度走查：首个 brace 深度 0 的 ``\\documentstyle``。

    语义钉：``\\`` 跳两字符（转义 brace 不计）；``}`` 无下界钳制——
    游离 ``}`` 把深度压负后其后声明命不中深度 0（保守不动坏源）。
    """
    depth = 0
    pos = 0
    for m in DOCSTYLE_DECL_RX.finditer(vis):
        while pos < m.start():
            c = vis[pos]
            if c == "\\":
                pos += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            pos += 1
        pos = m.end()
        if depth == 0:
            return m
    return None


class _Oracle209(NamedTuple):
    status: str
    reason: str | None
    cls: str | None
    target: str | None
    cls_opts: list[str]
    pkg_opts: list[str]
    shipped: list[str]
    stripped: list[str]
    out: str


def _oracle_209(  # noqa: C901, PLR0912 -- 分派链逐支重述
    tex: str, *, sty_stems: set[str], ds_at: set[str]
) -> _Oracle209:
    """独立重述 ``upgrade_209``——含输出全文重建（残token改名倒序回填）。"""
    vis = visible_tex(tex)
    m = _oracle_primary(vis)
    if m is None:
        return _Oracle209("no-docstyle", None, None, None, [], [], [], [], tex)
    cls = m.group(2).strip()
    if not cls:
        return _Oracle209("no-docstyle", None, None, None, [], [], [], [], tex)
    if cls in _DS_AT_CLASSES or (
        cls not in _CLASS_MAP and cls not in _STD_CLASSES and cls in ds_at
    ):
        return _Oracle209("reject", "latex209_ds_at", cls, None, [], [], [], [], tex)
    spec = _CLASS_MAP.get(cls)
    target = spec.target if spec is not None else cls
    # fuzz 臂 _target_resolvable 恒 True → 无 latex209_no_target 支
    incompat = _INCOMPAT_PKGS.get(target, frozenset())
    cls_opts: list[str] = []
    pkg_opts: list[str] = []
    shipped: list[str] = []
    stripped: list[str] = []
    for opt in _oracle_split(m.group(1)):
        o = spec.rename.get(opt, opt) if spec is not None else opt
        if o in incompat:
            stripped.append(o)
        elif o in _KERNEL_OPTS or (spec is not None and o in spec.options):
            cls_opts.append(o)
        elif o in _PKG_OPTS or (".." not in o and o in sty_stems):
            pkg_opts.append(o)
            if o not in _PKG_OPTS:
                shipped.append(o)
        else:
            cls_opts.append(o)
    lines = [
        _PRE_CLASS_SHIM,
        f"\\documentclass[{','.join(cls_opts)}]{{{target}}}"
        if cls_opts
        else f"\\documentclass{{{target}}}",
        COMPAT_SHIM,
    ]
    if target == "revtex4-2":
        lines.append(_REVTEX209_SHIM)
    if "multicol" in stripped:
        lines.append(_MULTICOLS_SHIM)
    if pkg_opts:
        lines.append("\\usepackage{" + ",".join(pkg_opts) + "}")
    out = tex[: m.start()] + "\n".join(lines) + tex[m.end() :]
    vis2 = visible_tex(out)
    for dm in reversed([*DOCSTYLE_RX.finditer(vis2)]):
        out = out[: dm.start()] + "\\documentclass" + out[dm.end() :]
    return _Oracle209(
        "converted", None, cls, target, cls_opts, pkg_opts, shipped, stripped, out
    )


_209_CLASSES = [
    "article",
    "report",
    "revtex",
    "mn",
    "jpsj",
    "elsart",
    "aipproc",
    "amsart",
    "ias",
    "jaa",
    "julie",
    "mycls",
    "weird-cls",
]
_209_OPTS = [
    "12pt",
    "a4paper",
    "twoside",
    "draft",
    "epsfig",
    "amsmath",
    "multicol",
    "cite",
    "mcite",
    "showkeys",
    "natbib",
    "tighten",
    "floats",
    "sort&compress",
    "reqno",
    "mypkg",
    "deepsty",
    "foo209",
    "中",
]


def _gen_209_doc(rng: random.Random) -> str:
    """随机 209 文档汤：声明点藏在注释/verbatim/宏体/游离括号之间。"""
    parts: list[str] = []
    for _ in range(rng.randint(0, 4)):
        r = rng.random()
        if r < 0.15:  # noqa: PLR2004
            parts.append("% \\documentstyle{commented}\n")
        elif r < 0.3:  # noqa: PLR2004
            parts.append("\\begin{verbatim}\n\\documentstyle{verb}\n\\end{verbatim}\n")
        elif r < 0.45:  # noqa: PLR2004
            parts.append("\\newcommand{\\dsx}{\\documentstyle{macrocls}}\n")
        elif r < 0.55:  # noqa: PLR2004
            parts.append(rng.choice(["}", "{", "}{", "{}", "{{"]) + " junk\n")
        else:
            parts.append("plain text\n")
    cls = rng.choice(_209_CLASSES)
    opts = [rng.choice(_209_OPTS) for _ in range(rng.randint(0, 5))]
    optspan = f"[{','.join(opts)}]" if opts or rng.random() < 0.2 else ""  # noqa: PLR2004
    parts.append(f"\\documentstyle{optspan}{{{cls}}}\n")
    parts.extend(
        rng.choice(
            [
                "body text\n",
                "\\newcommand{\\z}{\\documentstyle{tail}}\n",
                "% \\documentstyle{c2}\n",
                "stray }\n",
            ]
        )
        for _ in range(rng.randint(0, 3))
    )
    return "".join(parts)


class TestLatex209:
    """latex209.py——状态三分 + 输出全文重建对拍 + 选项三路分派不变量。"""

    def test_upgrade_oracle_full_reconstruction(self, tmp_path: Path) -> None:
        """随机文档汤：status/reason/字段/输出字节与 oracle 全等。"""
        rng = fuzz_rng(20260920)
        (tmp_path / "mypkg.sty").write_text("\\ProvidesPackage{mypkg}\n")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "deepsty.sty").write_text("% deep\n")
        # mycls 随源 ds@ 真分发标记（\\ds@/\\@namedef{ds@} 形态）
        (tmp_path / "mycls.sty").write_text("\\@namedef{ds@opta}{\\relax}\n")
        (tmp_path / "weird-cls.sty").write_text("\\def\\ds@epsfig{}\n")
        sty_stems = {p.stem for p in tmp_path.rglob("*.sty")}
        ds_at = {"mycls", "weird-cls"}
        for _ in range(300):
            tex = _gen_209_doc(rng)
            out, info = upgrade_209(tex, root=tmp_path)
            exp = _oracle_209(tex, sty_stems=sty_stems, ds_at=ds_at)
            ctx = f"tex={tex!r}\ninfo={info}\nexp={exp.status}"
            assert info["status"] == exp.status, ctx
            assert out == exp.out, ctx  # 全文重建等值（含残 token 改名）
            if exp.status == "converted":
                assert info["orig"] in tex
                assert info["class"] == exp.cls
                assert info["target"] == exp.target
                assert info["class_opts"] == exp.cls_opts
                assert info["pkg_opts"] == exp.pkg_opts
                assert info["shipped"] == exp.shipped
                assert info["stripped"] == exp.stripped
                vis = visible_tex(out)
                assert DOCSTYLE_RX.search(vis) is None  # 无活 docstyle 残留
                assert COMPAT_SHIM in out
                # 分派守恒：三路输出 == 改名后选项多重集
                renamed = [
                    (
                        _CLASS_MAP[exp.cls].rename.get(o, o)
                        if exp.cls in _CLASS_MAP
                        else o
                    )
                    for o in _oracle_split(_oracle_primary(visible_tex(tex)).group(1))
                ]
                assert Counter(exp.cls_opts) + Counter(exp.pkg_opts) + Counter(
                    exp.stripped
                ) == Counter(renamed), ctx
                assert set(exp.shipped) == set(exp.pkg_opts) - _PKG_OPTS, ctx
                assert set(exp.stripped) <= _INCOMPAT_PKGS.get(exp.target, frozenset())
                assert ("multicol" in exp.stripped) == (_MULTICOLS_SHIM in out), ctx
                assert (exp.target == "revtex4-2") == (_REVTEX209_SHIM in out), ctx
                if exp.pkg_opts:
                    # shim 必须先于路由出的 usepackage（2501.05407 实证）
                    assert out.index(COMPAT_SHIM) < out.index("\\usepackage{"), ctx
                # 幂等：二次升级 no-docstyle 且字节不动
                out2, info2 = upgrade_209(out, root=tmp_path)
                assert info2["status"] == "no-docstyle", ctx
                assert out2 == out, ctx
            else:
                assert out == tex  # reject/no-docstyle 原文不动
            # 确定性
            assert upgrade_209(tex, root=tmp_path)[0] == out, ctx

    def test_route_opts_precedence(self, tmp_path: Path) -> None:
        """三路分派判别序钉：类内建压同名宏包白名单（revtex showkeys）。"""
        (tmp_path / "mypkg.sty").write_text("x\n")
        out, info = upgrade_209(
            "\\documentstyle[showkeys,cite,multicol,tighten,epsfig,mypkg,zz]{revtex}\n",
            root=tmp_path,
        )
        assert info["status"] == "converted"
        # showkeys 同名 .sty 存在但类内建表先判 → 类选项
        assert "showkeys" in info["class_opts"]
        assert "showkeys" not in info["pkg_opts"]
        # rename：tighten→tightenlines 落类选项
        assert "tightenlines" in info["class_opts"]
        assert "tighten" not in info["class_opts"] + info["pkg_opts"]
        # incompat 剥除：cite/multicol 不进任何路由位
        assert set(info["stripped"]) == {"cite", "multicol"}
        assert "cite" not in info["class_opts"] + info["pkg_opts"]
        assert _MULTICOLS_SHIM in out
        # 白名单 + 随源 .sty → usepackage；未知名落类选项
        assert info["pkg_opts"] == ["epsfig", "mypkg"]
        assert info["shipped"] == ["mypkg"]
        assert "zz" in info["class_opts"]

    def test_no_target_reject(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """盲升闸：改名目标双侧不可解析 → reject/latex209_no_target。"""
        monkeypatch.setattr(latex209, "_target_resolvable", lambda *_a: False)
        out, info = upgrade_209("\\documentstyle{revtex}\nx\n")
        assert info == {
            "status": "reject",
            "reason": "latex209_no_target",
            "class": "revtex",
            "target": "revtex4-2",
        }
        assert out == "\\documentstyle{revtex}\nx\n"
        # 未映射类名 target==cls 不过闸（守卫只在改名时触发）
        out2, info2 = upgrade_209("\\documentstyle{myx}\nx\n")
        assert info2["status"] == "converted"
        assert info2["target"] == "myx"
        assert out2.startswith(_PRE_CLASS_SHIM + "\n\\documentclass{myx}\n")

    def test_ds_at_classes_always_reject(self) -> None:
        """``_DS_AT_CLASSES`` 名硬拒——无树可调也拒（ias/jaa/julie）。"""
        for cls in sorted(_DS_AT_CLASSES):
            out, info = upgrade_209(f"\\documentstyle{{{cls}}}\nx\n")
            assert info["status"] == "reject"
            assert info["reason"] == "latex209_ds_at"
            assert out == f"\\documentstyle{{{cls}}}\nx\n"

    def test_ds_at_true_positive_reject(self, tmp_path: Path) -> None:
        """随源 .sty/.cls 内真分发标记 → reject（对照组，当前即成立）。"""
        (tmp_path / "aa.sty").write_text("\\@namedef{ds@opta}{\\relax}\n")
        (tmp_path / "bb.cls").write_text("\\def\\ds@preprint{}\n")
        for cls in ("aa", "bb"):
            out, info = upgrade_209(f"\\documentstyle[opta]{{{cls}}}\n", root=tmp_path)
            assert info["status"] == "reject", cls
            assert info["reason"] == "latex209_ds_at"
            assert out == f"\\documentstyle[opta]{{{cls}}}\n"

    @pytest.mark.parametrize(
        "sty_body",
        [
            "\\def\\mids@foo{bar}\n",
            "% this style uses ds@ dispatch internally\n\\def\\x{1}\n",
            "\\def\\ods@x{y}\n\\let\\zds@w\\relax\n",
        ],
        ids=["mids-at-def", "comment-ds-at", "ods-at-let"],
    )
    def test_ds_at_substring_overtrigger(self, tmp_path: Path, sty_body: str) -> None:
        """J1：非分发形态的 ``ds@`` 子串不应触发 reject——应正常转换。"""
        (tmp_path / "mycls.sty").write_text(sty_body)
        out, info = upgrade_209("\\documentstyle[opta]{mycls}\nx\n", root=tmp_path)
        assert info["status"] == "converted"
        assert "\\documentclass" in out

    def test_negative_depth_hides_decl(self) -> None:
        """观测语义钉：声明点前的游离 ``}`` → 深度压负 → ``no-docstyle``。"""
        out, info = upgrade_209("title } stray\n\\documentstyle{article}\nx\n")
        assert info == {"status": "no-docstyle"}
        assert out == "title } stray\n\\documentstyle{article}\nx\n"
        # 配平后可见
        out2, info2 = upgrade_209("x } { y\n\\documentstyle{article}\nx\n")
        assert info2["status"] == "converted"
        assert out2.startswith(
            "x } { y\n" + _PRE_CLASS_SHIM + "\n\\documentclass{article}\n"
        )

    def test_post_brace_opts_inert(self) -> None:
        """观测语义钉：``{cls}[opts]`` 选项后置非 209 形态——留作正文文本。"""
        out, info = upgrade_209("\\documentstyle{article}[12pt]\nx\n")
        assert info["status"] == "converted"
        assert info["class_opts"] == []
        assert "[12pt]" in out  # 原样留存不参与路由

    def test_token_rename_no_collateral(self) -> None:
        """残 token 改名不误伤：``\\documentstyleX``/``@`` 变体与 verbatim 保留。"""
        tex = (
            "\\documentstyle{article}\n"
            "\\def\\documentstyleX{1}\n\\def\\documentstyle@{2}\n"
            "\\begin{verbatim}\n\\documentstyle{v}\n\\end{verbatim}\n"
            "\\newcommand{\\ds}{\\documentstyle{foo}}\n"
        )
        out, info = upgrade_209(tex)
        assert info["status"] == "converted"
        assert "\\documentstyleX" in out
        assert "\\documentstyle@" in out
        assert "\\documentstyle{v}" in out  # verbatim 遮蔽面不动
        assert "\\documentclass{foo}" in out  # 宏体残 token 已改名

    def test_split_opts_edge_inputs(self) -> None:
        """``_split_opts`` 怪异输入：空段丢弃、非空白即文本、永不返空串。"""
        for s, exp in [
            (None, []),
            ("", []),
            ("  ", []),
            (",,,", []),
            ("a,,b", ["a", "b"]),
            ("a={x}y", ["a={x}y"]),
            ("12 pt", ["12pt"]),
            ("中,文", ["中", "文"]),
            ("a,b,", ["a", "b"]),
        ]:
            assert _split_opts(s) == exp
        rng = fuzz_rng(20260921)
        pool = "ab,{} \t中%"
        for _ in range(500):
            s = "".join(rng.choice(pool) for _ in range(rng.randint(0, 15)))
            got = _split_opts(s)
            assert all(o and not any(c.isspace() for c in o) for o in got)
            assert Counter(got) <= Counter(
                o for o in "".join(c for c in s if not c.isspace()).split(",") if o
            )

    def test_ships_style_glob_safety(self, tmp_path: Path) -> None:
        """``_ships_style`` glob 闸：路径魔法字符名恒 False；随源名命中。"""
        (tmp_path / "nips.sty").write_text("x\n")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "deep.sty").write_text("x\n")
        assert _ships_style(tmp_path, "nips")
        assert _ships_style(tmp_path, "deep")  # rglob 递归命中
        for name in [
            "../etc/passwd",
            "a..b",
            "..",
            ".",
            "a/b",
            "a*b",
            "a?b",
            "a[b]",
            "",
            "x\x00y",
        ]:
            assert not _ships_style(tmp_path, name), name
        assert not _ships_style(None, "nips")

    def test_uses_ds_at_glob_safety(self, tmp_path: Path) -> None:
        """``_uses_ds_at`` 同款闸：魔法字符类名不触 rglob。"""
        (tmp_path / "real.sty").write_text("\\def\\ds@a{}\n")
        assert _uses_ds_at(tmp_path, "real")
        for cls in ["..", "a/b", "a*b", "a?b", "x\x00y", ""]:
            assert not _uses_ds_at(tmp_path, cls), cls
        assert not _uses_ds_at(None, "real")
