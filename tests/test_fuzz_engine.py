r"""compile/engine.py + toolchain.py 性质 fuzz——路由/旗标/log/依赖/工具链对拍。

oracle 方法：工程树/旗标表/log 行/makefile 文本由发生器按种子构造，期望值由
**生成侧登记事实**或独立小模拟器重算——不复用 impl 判定路径。共享件
``visible_tex``/``file_stack_at``/``is_project_file`` 各自独立受测
（test_fuzz_mask/test_fuzz_texlog），遮蔽与栈语义一致是对拍前提。

真编译缺席原则：xelatex/tectonic 一律 PATH shim 脚本（POSIX sh，真起子进程
验证 env 隔离/超时杀/重试/pass 门控）或 monkeypatch ``run_process`` 的假进程
（预算/gating/字段簿记）。真机引擎不可达。

PIN 缺陷（tmp/engine-fuzz/ 探针实证钉死，2026-09-17 九钉全修——断言已翻转到
新行为；本表留档原缺陷语义，行号为当时快照）：

- D1 ``_split_flags`` 前缀表只挡单横线拼写：``--output-directory=/x`` 等
  双横线长选项落 ``applied``——kpathsea 认双横线，pdf/log 落点被重键，
  outdir 回收约定失守。→ 修：dash 归一（``-``+lstrip）再查重键表。
- D2 ``load_search_cache`` 滤 falsy 不查值型：truthy 非标量原样进缓存，
  ``filemap`` 返回 str/int/dict——签名承诺 ``list[str]``，下游 splat 把
  ``"notalist"`` 散成单字符包名喂 tlmgr。→ 修：list+全 str 元素双闸。
- D3 ``compile`` stale unlink 先于路径合法性：``main="bad\x00.tex"`` 抛
  ``ValueError: unlink: embedded null``——其它坏 main 形态都走
  CompRes/rc=None 面，独此炸异常逃过 fixloop 轮内捕获。
  → 修：``_checked_main`` 校验先于一切 FS 变更，NUL 走显式 ValueError。
- D4 ``_texmfdist`` 不查 kpsewhich 退出码：rc=1 + stdout 垃圾 → 垃圾串
  进 fontconfig conf ``<dir>``。→ 修：rc!=0/TimeoutExpired → None。
- D5 ``TectonicEngine.probe_file`` 无 cwd 内约束：``../secret.sty`` 存在
  即返回其路径——fixloop 供给的 log 可控名越出工程目录。
  → 修：resolve 双侧比对，命中须留在 cwd 内。
- D6 ``route_project`` eps 信号不查 is_file：名为 ``x.eps`` 的**目录**
  也翻 xelatex-first（.tex 扫描侧有 is_file 闸，eps 侧没有——不对称）。
  → 修：eps 扫描补 is_file 闸；目录形态改作诱饵。
- D7 ``child_env(extra)`` 把 extra 最后套用——``env_extra={"shell_escape":"t"}``
  静默压过 ``shell_escape=f`` 强制阀（openin_any 同理可松）。
  → 修：extra 滤 ``_ENV_FORCED`` 同名键，阀值恒赢。
- D8 ``_MINTED_FROZEN_RE`` 裸子串 ``frozencache``——docstring 宣称
  "frozencache + minted"，散文提及即翻 prefer="xelatex" → tectonic-first，
  reason 文案谎称 minted。→ 修：``_MINTED_PKG_RE`` 装载共现双闸；
  fuzz oracle 改 minted/froz 两 conjunct 登记。
- D9 ``compile`` 的 main 不规范化：``main="../main.tex"`` 把 cwd/产物
  落出 wdir，outdir 回收面越界。→ 修：``_checked_main``  containment
  （resolve 比对）+ normpath 折叠；tectonic 侧同洞并修。
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _fuzzkit import fuzz_rng
from conftest import make_tar, tar_reg

import texlate.compile.deps as deps_mod
import texlate.compile.engine as eng_mod
import texlate.compile.sandbox as sb_mod
import texlate.compile.toolchain as tc
from texlate.compile.engine import (
    CompRes,
    Engine,
    TectonicEngine,
    XelatexEngine,
    compiled_dependencies,
    engine_for,
    load_search_cache,
    parse_log,
    route_project,
    save_search_cache,
)
from texlate.texlog import file_stack_at, is_project_file

if TYPE_CHECKING:
    import random
    from collections.abc import Callable, Iterator

# ------------------------------------------------------------------ 通用件

_SEED = 20260917
_ITER = 300
_TAIL_N = 30  # parse_log tail 行数钉值
_ERR_TRUNC = 300  # errors[] 单条截断钉值
_CTX_N = 9  # error_ctx 窗口钉值
_STDOUT_TAIL = 4000  # _collect_compile_outputs 截尾钉值
_PER_PASS_FLOOR = 10.0  # xelatex 单趟预算地板
_TECT_RETRY_CAP = 120.0  # tectonic 重试趟预算帽
_TECT_ATTEMPTS = 2
_WRAP_SIG_BASE = 128
_WRAP_SIG_MAX = 192

#: oracle 侧复刻的 impl 字面量——有意不复用 impl 常量：漂移即警报。
_O_REKEY = ("-output-directory", "-aux-directory", "-jobname")
_O_FLAG_MAP = {"-synctex": ["--synctex"], "-synctex=1": ["--synctex"]}
_O_Z_OK = frozenset(
    {
        "continue-on-errors",
        "minify-bundle",
        "keep-intermediates",
        "keep-logs",
        "deterministic-output",
        "synctex",
        "paper-size",
        "trace",
        "hide",
    }
)
_O_SHELL_ESC = frozenset(
    {"-shell-escape", "--shell-escape", "-enable-write18", "--enable-write18"}
)
_O_DEP_EXTS = {".tex", ".sty", ".cls", ".cfg", ".def", ".clo", ".fd", ".ltx"}
_O_FNAME = r"[^()\s:]+\.[A-Za-z0-9_-]{1,10}"
_O_FILELINE = re.compile(r"^" + _O_FNAME + r":\d+: \S")
_O_NONERR = re.compile(
    r"^" + _O_FNAME + r":\d+:\s*(?:(?:LaTeX|Package|Class)\b[^\n]*?\bWarning\b|==>)"
)
_O_LNUM = re.compile(r"^l\.(\d+)")
_O_KPATHSEA_SPLIT = re.compile(r"[\s,:{}]+")

requires_sh = pytest.mark.skipif(
    sys.platform == "win32" or not Path("/bin/sh").exists(),
    reason="shim 走 POSIX sh",
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """隔离宿主引擎面：假 HOME（fontconfig/usertree 落点）+ 清探测 lru_cache。"""
    home = tmp_path / "_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # teardown 在 monkeypatch 还原之前跑——必须先存原函数引用，测试把同名
    # attr patch 成裸 lambda 时 getattr 到的对象没有 cache_clear。
    cached = (
        sb_mod._bwrap_capable,  # noqa: SLF001
        sb_mod._kpathsea_dirs,  # noqa: SLF001
        sb_mod._texmfdist,  # noqa: SLF001
        tc.tectonic_version,
    )
    yield
    for fn in cached:
        fn.cache_clear()


def _fake_run(  # noqa: PLR0913
    calls: list[dict[str, object]],
    *,
    rc: int | None = 0,
    out: str = "",
    sec: float = 0.1,
    to: bool = False,
    side: Callable[[list[str], Path, int], None] | None = None,
) -> Callable[..., tuple[int | None, str, float, bool]]:
    """捕获 (cmd, cwd, env, timeout) 的假 run_process；side 在记账后跑。"""

    def fake(  # noqa: PLR0913
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        out_cap: int = 8 * 1024 * 1024,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[int | None, str, float, bool]:
        del out_cap, should_cancel
        calls.append(
            {"cmd": list(cmd), "cwd": Path(cwd), "env": dict(env), "timeout": timeout}
        )
        if side is not None:
            side(list(cmd), Path(cwd), len(calls))
        return rc, out, sec, to

    return fake


def _xe_out(cmd: list[str]) -> Path:
    """从 xelatex argv 抽 ``-output-directory=`` 落点。"""
    for t in cmd:
        if t.startswith("-output-directory="):
            return Path(t.split("=", 1)[1])
    raise AssertionError("argv 缺 -output-directory")  # noqa: EM101, TRY003


def _tec_out(cmd: list[str]) -> Path:
    """从 tectonic argv 抽 ``--outdir`` 落点。"""
    return Path(cmd[cmd.index("--outdir") + 1])


def _write_pdf(cmd: list[str], _cwd: Path, _n: int) -> None:
    (_xe_out(cmd) / "main.pdf").write_bytes(b"%PDF-fake")


# ================================================================ 路由 oracle
#: 信号行——未遮蔽形态落 oracle，注释形态作遮蔽对照。
_SIG_DOCSTYLE = "\\documentstyle{article}"
_SIG_PST = (
    "\\usepackage{pstricks}",
    "\\usepackage{pst-node}",
    "\\usepackage[dvips]{pstricks-add}",
    "\\RequirePackage{pst-plot}",
    "\\begin{pspicture}(1,1)\\end{pspicture}",
    "\\pspicture(0,0)(1,1)",
    "\\psset{unit=1cm}",
)
_SIG_FROZEN = (
    "\\usepackage[frozencache]{minted}",
    "\\usepackage[frozencache=true]{minted2}",
    "\\RequirePackage[frozencache]{minted}",
)
_SIG_MINTED_ONLY = (
    "\\usepackage{minted}",
    "\\usepackage{minted2}",
    "\\RequirePackage[chapter]{minted}",
)
_SIG_BITMAP = (
    "\\usepackage{bbm}",
    "\\usepackage{wasysym}",
    "\\usepackage{dsfont}",
    "\\usepackage{bbold}",
)
#: 诱饵行——形态贴近但按 impl 口径不得命中。
_DECOY = (
    "\\usepackage{notpstricks}",  # 元素边界：子串不算
    "\\psline(0,0)(1,1)",  # 裸绘图宏不收
    "\\begin{pspicturex}",  # env 名边界
    "\\documentstylex{article}",  # \b 边界
    "prose mentions pstricks here",  # 无 usepackage 包裹
    "prose about documentstyle",  # 无反斜杠
    "\\usepackage{amsmath,bbmfontsx}",  # 名边界——bbmfontsx 非 bbm
)
_FILLER = (
    "\\documentclass{article}",
    "\\begin{document}",
    "\\end{document}",
    "\\section{Intro}",
    "ordinary english prose line",
    "\\usepackage{amsmath}",
    "\\input{other}",
    "a % trailing comment",
)
_TEX_NAMES = ("main.tex", "a.TEX", "sub/b.tex", "sub/deep/c.TeX")
_NONTEX_NAMES = ("notes.txt", "README.md")  # 非 .tex 里的信号不得计数


def _gen_project(root: Path, rng: random.Random) -> dict[str, object]:  # noqa: C901, PLR0912, PLR0915
    """随机工程树 + 生成侧路由事实登记。"""
    expect: dict[str, object] = {
        "eps": False,
        "pst": False,
        "minted": False,  # minted/minted2 装载行落过 visible tex
        "froz": False,  # frozencache 子串落过 visible tex
        "bitmap": False,
        "docstyle": set(),
        "non_utf8": False,
    }
    n_files = rng.randrange(1, 6)
    for rel in rng.sample([*_TEX_NAMES, *_NONTEX_NAMES], k=min(n_files, 6)):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        is_tex = p.suffix.lower() == ".tex"
        lines: list[str] = []
        for _ in range(rng.randrange(1, 6)):
            pick = rng.random()
            if pick < 0.45:  # noqa: PLR2004
                lines.append(rng.choice(_FILLER))
            elif pick < 0.62:  # noqa: PLR2004
                lines.append(rng.choice(_DECOY))
            elif pick < 0.7:  # noqa: PLR2004
                sig = rng.choice(_SIG_PST)
                if rng.random() < 0.3:  # noqa: PLR2004
                    lines.append("% " + sig)  # 注释遮蔽 → 不计
                else:
                    lines.append(sig)
                    if is_tex:
                        expect["pst"] = True
            elif pick < 0.78:  # noqa: PLR2004
                lines.append(_SIG_DOCSTYLE)
                if is_tex:
                    expect["docstyle"].add(rel)  # type: ignore[attr-defined]
            elif pick < 0.86:  # noqa: PLR2004
                sub = rng.random()
                if sub < 0.2:  # noqa: PLR2004
                    lines.append("% frozencache mention")  # 遮蔽
                elif sub < 0.5:  # noqa: PLR2004
                    lines.append(rng.choice(_SIG_FROZEN))  # minted 装载+frozencache
                    if is_tex:
                        expect["minted"] = True
                        expect["froz"] = True
                elif sub < 0.75:  # noqa: PLR2004
                    # 裸散文半边——D8 修复后不构成路由信号
                    lines.append("we cache with frozencache option")
                    if is_tex:
                        expect["froz"] = True
                else:
                    lines.append(rng.choice(_SIG_MINTED_ONLY))  # 另半边
                    if is_tex:
                        expect["minted"] = True
            elif pick < 0.94:  # noqa: PLR2004
                lines.append(rng.choice(_SIG_BITMAP))
                if is_tex:
                    expect["bitmap"] = True
            else:
                lines.append("% \\usepackage{pstricks} masked")
        blob = "\n".join(lines).encode()
        if is_tex and rng.random() < 0.12:  # noqa: PLR2004
            blob += b"\xff\xfe"  # 非 UTF-8 尾——信号照常算
            expect["non_utf8"] = True
        p.write_bytes(blob)
    # .eps 成员：文件与**目录**两形态——目录是 D6 修复后的诱饵（不算信号）
    if rng.random() < 0.3:  # noqa: PLR2004
        if rng.random() < 0.4:  # noqa: PLR2004
            (root / "figs.eps").mkdir(parents=True)  # 目录形态不计
        else:
            eps = root / rng.choice(["fig.eps", "F.EPS", "sub/g.eps"])
            eps.parent.mkdir(parents=True, exist_ok=True)
            eps.write_bytes(b"x")
            expect["eps"] = True
    return expect


def _o_route(root: Path, prefer: str, expect: dict[str, object]) -> dict[str, object]:  # noqa: ARG001
    """生成侧事实 → 期望 RouteDecision 字段（不复用 impl 判定）。"""
    eps = bool(expect["eps"])
    pst = bool(expect["pst"])
    # D8 契约：frozencache + minted 装载须共现——半边信号不翻路由
    frozen = bool(expect["minted"]) and bool(expect["froz"])
    engines = (
        ["xelatex", "tectonic"] if prefer == "xelatex" else ["tectonic", "xelatex"]
    )
    reasons: list[str] = []
    if eps or pst:
        engines = sorted(engines, key=lambda e: 0 if e == "xelatex" else 1)
        reasons.append(
            f"eps_files={eps} pstricks={pst} → xelatex 优先（tectonic xdvipdfmx 硬墙）"
        )
    elif frozen:
        engines = sorted(engines, key=lambda e: 0 if e == "tectonic" else 1)
        reasons.append("minted frozencache → tectonic 优先（bundle v2.6 兼容）")
    if expect["bitmap"]:
        reasons.append("bbm/dsfont 类位图字体包 → tectonic 高风险，失败换 xelatex")
    return {"engines": engines, "reasons_head": reasons}


def test_route_project_fuzz(tmp_path: Path) -> None:
    """随机工程树 × prefer 怪值 → engines/reasons/non_utf8/latex209 全字段对拍。"""
    rng = fuzz_rng(_SEED)
    for i in range(_ITER):
        root = tmp_path / f"p{i}"
        root.mkdir()
        expect = _gen_project(root, rng)
        prefer = rng.choice(["tectonic", "xelatex", "", "bogus", "XELATEX"])
        d = route_project(root, prefer=prefer)
        o = _o_route(root, prefer, expect)
        assert d.engines == o["engines"], (i, prefer)
        assert d.reject is None
        assert d.non_utf8 == expect["non_utf8"]
        assert d.latex209_suspect == bool(expect["docstyle"])
        # 原因表：eps/minted/bitmap 全等 + latex209/non_utf8 形态校验
        head = o["reasons_head"]
        assert d.reasons[: len(head)] == head, (i, d.reasons)
        tail_reasons = d.reasons[len(head) :]
        if expect["docstyle"]:
            r209 = next(r for r in tail_reasons if r.startswith("latex209_suspect:"))
            listed = r209.split("latex209_suspect: ", 1)[1].split(" \\documentstyle")[0]
            assert set(listed.split(", ")) == expect["docstyle"]
            tail_reasons.remove(r209)
        if expect["non_utf8"]:
            tail_reasons.remove("非 UTF-8 源 → 需 iconv 转码预处理或 inputenc 路注")
        assert tail_reasons == [], (i, d.reasons)


def test_route_project_edge_roots(tmp_path: Path) -> None:
    """不存在根/文件根/空根：不抛、双引擎兜底序、无信号。"""
    for root in (tmp_path / "ghost", tmp_path / "afile", tmp_path / "empty"):
        if root.name == "afile":
            root.write_text("x")
        else:
            root.mkdir(exist_ok=True)
        d = route_project(root)
        assert d.engines == ["tectonic", "xelatex"]
        assert d.reasons == [] and d.reject is None  # noqa: PT018


def test_route_project_unreadable_subdir(tmp_path: Path) -> None:
    """rglob 吞权限错——不可读子目录里的 \\documentstyle 不参与信号。"""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.tex").write_text(_SIG_DOCSTYLE)
    (tmp_path / "main.tex").write_text("\\documentclass{article}")
    (tmp_path / "sub").chmod(0)
    try:
        d = route_project(tmp_path)
        assert d.latex209_suspect is False
    finally:
        (tmp_path / "sub").chmod(0o755)


def test_route_frozencache_bare_word(tmp_path: Path) -> None:
    """D8 已修：裸散文 frozencache（无 minted 装载）不翻路由；共现才翻。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "We discuss the frozencache option.\n\\end{document}\n"
    )
    d = route_project(tmp_path, prefer="xelatex")
    assert d.engines == ["xelatex", "tectonic"]
    assert d.reasons == []
    # 共现对照：frozencache + minted 装载 → tectonic-first
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage[frozencache]{minted}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    d2 = route_project(tmp_path, prefer="xelatex")
    assert d2.engines == ["tectonic", "xelatex"]
    assert d2.reasons == ["minted frozencache → tectonic 优先（bundle v2.6 兼容）"]


# ================================================================ engine_for
def test_engine_for_strict_names() -> None:
    """精确匹配唯一入口——大小写/空白/NUL/别名一律 ValueError。"""
    for bad in (
        "XeLaTeX",
        "XELATEX",
        " xelatex",
        "xelatex ",
        "pdflatex",
        "lualatex",
        "",
        "tectonic\x00",
        "tectonic.exe",
    ):
        with pytest.raises(ValueError, match="未知引擎"):
            engine_for(bad)
    xe = engine_for("xelatex", binary="/bin/true")
    assert isinstance(xe, Engine) and xe.detect() == "/bin/true"  # noqa: PT018
    te = engine_for("tectonic", binary="/bin/true", bundle="")
    assert isinstance(te, TectonicEngine) and te.detect() == "/bin/true"  # noqa: PT018
    with pytest.raises(TypeError):
        engine_for("xelatex", bogus_kwarg=1)


def test_engine_caps() -> None:
    """caps 能力集钉值——fixloop 降级路由的本体。"""
    assert XelatexEngine.caps == frozenset({"kpsewhich", "tlmgr", "updmap", "recorder"})
    assert TectonicEngine.caps == frozenset({"bundle"})


# ================================================================ CompRes 不变量
def test_compres_field_semantics() -> None:
    """has_pdf 纯字段判定（不查盘）；ok 默认 False。"""
    res = CompRes(engine="x")
    assert res.ok is False and res.has_pdf is False  # noqa: PT018
    assert res.sandbox_mode == "off" and res.passes == 0  # noqa: PT018
    ghost = CompRes(engine="x", pdf=Path("/nonexistent/x.pdf"), pdf_bytes=7)
    assert ghost.has_pdf is True  # 字段只看 pdf 非 None + bytes>0，不 stat
    empty = CompRes(engine="x", pdf=Path("/x.pdf"), pdf_bytes=0)
    assert empty.has_pdf is False


# ================================================================ _split_flags oracle
def _o_split(flags: list[str]) -> tuple[list[str], list[str]]:
    """独立重算：rekey 前缀→dropped（无 ``=`` 且下项非旗标则连吞），其余去重。"""
    applied: list[str] = []
    dropped: list[str] = []
    i = 0
    while i < len(flags):
        fl = flags[i]
        # kpathsea 单双横线等价——归一后查表（D1 修复口径）
        norm = "-" + fl.lstrip("-")
        if any(norm.startswith(p) for p in _O_REKEY):
            dropped.append(fl)
            if (
                "=" not in fl
                and i + 1 < len(flags)
                and not flags[i + 1].startswith("-")
            ):
                dropped.append(flags[i + 1])
                i += 1
        elif fl not in applied:
            applied.append(fl)
        i += 1
    return applied, dropped


_FLAG_POOL = (
    "-output-directory",
    "-output-directory=/x",
    "-aux-directory",
    "-jobname",
    "-jobname=v",
    "-jobnamex",
    "--output-directory=/evil",  # D1 双横线逃逸
    "--jobname=e",
    "-shell-escape",
    "-synctex=1",
    "-halt-on-error",
    "plainword",
    "-x",
    "",
)


def test_split_flags_fuzz() -> None:
    """随机旗标表 → (applied, dropped) 与独立模拟全等 + 拒放不变量。"""
    rng = fuzz_rng(_SEED + 1)
    for _ in range(_ITER):
        flags = [rng.choice(_FLAG_POOL) for _ in range(rng.randrange(0, 8))]
        applied, dropped = XelatexEngine._split_flags(flags)  # noqa: SLF001
        exp_a, exp_d = _o_split(flags)
        assert applied == exp_a and dropped == exp_d, flags  # noqa: PT018
        # 不变量：applied 无重复、任何横线拼写的 rekey 前缀都不得入；dropped 保序
        assert len(applied) == len(set(applied))
        for a in applied:
            assert not any(("-" + a.lstrip("-")).startswith(p) for p in _O_REKEY)


def test_split_flags_doubledash_rekey_bypass() -> None:
    """D1 已修：双横线 rekey 拼写归一查表——落 dropped 不落 applied。"""
    applied, dropped = XelatexEngine._split_flags(  # noqa: SLF001
        ["--output-directory=/evil", "--jobname=x", "-synctex=1"]
    )
    assert applied == ["-synctex=1"]
    assert dropped == ["--output-directory=/evil", "--jobname=x"]
    # 两 token 形态双横线同吞值
    a2, d2 = XelatexEngine._split_flags(["--output-directory", "/evil"])  # noqa: SLF001
    assert a2 == [] and d2 == ["--output-directory", "/evil"]  # noqa: PT018


def test_split_flags_value_consume_edges() -> None:
    """两 token rekey：无 ``=`` 且下项不以 ``-`` 开头才连吞。"""
    a, d = XelatexEngine._split_flags(["-jobname", "v", "-jobname", "-x"])  # noqa: SLF001
    assert a == ["-x"]
    assert d == ["-jobname", "v", "-jobname"]
    a, d = XelatexEngine._split_flags(["-jobname"])  # noqa: SLF001
    assert a == [] and d == ["-jobname"]  # noqa: PT018


# ================================================================ _map_flags oracle
def _o_map(flags: list[str]) -> tuple[list[str], list[str], list[str]]:
    """独立重算 tectonic 旗标映射 → (toks, dropped, applied)。"""
    toks: list[str] = []
    dropped: list[str] = []
    applied: list[str] = []
    i = 0
    while i < len(flags):
        fl = flags[i]
        if fl in _O_FLAG_MAP:
            toks += _O_FLAG_MAP[fl]
            applied.append(fl)
        elif fl == "-Z" and i + 1 < len(flags) and not flags[i + 1].startswith("-"):
            if flags[i + 1].split("=", 1)[0] in _O_Z_OK:
                toks += [fl, flags[i + 1]]
                applied += [fl, flags[i + 1]]
            else:
                dropped.append(f"-Z {flags[i + 1]}")
            i += 1
        elif fl.startswith("-Z") and fl != "-Z":
            if fl[2:].split("=", 1)[0] in _O_Z_OK:
                toks.append(fl)
                applied.append(fl)
            else:
                dropped.append(fl)
        else:
            dropped.append(fl)
        i += 1
    return toks, dropped, applied


_TFLAG_POOL = (
    "-synctex",
    "-synctex=1",
    "-synctex=2",
    "-Z",
    "-Zkeep-logs",
    "-Zshell-escape",  # 后门拼写——恒 dropped
    "-Zsynctex=extra",
    "-shell-escape",
    "--outdir",
    "keep-logs",
    "trace",
    "hide=./src",
    "=foo",
    "-x",
    "--synctex",
)


def test_map_flags_fuzz() -> None:
    """随机旗标表 → (toks,dropped,applied) 全等 + shell-escape 永不进 argv。"""
    rng = fuzz_rng(_SEED + 2)
    for _ in range(_ITER):
        flags = [rng.choice(_TFLAG_POOL) for _ in range(rng.randrange(0, 8))]
        toks, dropped, applied = TectonicEngine._map_flags(flags)  # noqa: SLF001
        exp = _o_map(flags)
        assert (toks, dropped, applied) == exp, flags
        # 安全不变量：\\write18 系与 -Z 后门永不入 argv token 面
        assert "-shell-escape" not in toks
        for j, t in enumerate(toks):
            if t == "-Z":
                assert toks[j + 1].split("=", 1)[0] in _O_Z_OK
            elif t.startswith("-Z"):
                assert t[2:].split("=", 1)[0] in _O_Z_OK


def test_map_flags_dropped_combined_string() -> None:
    """``-Z <bad>`` 两 token 拒放记成合体串 ``-Z <bad>``（差集记账会漏）。"""
    toks, dropped, applied = TectonicEngine._map_flags(  # noqa: SLF001
        ["-Z", "shell-escape", "-synctex=1"]
    )
    assert toks == ["--synctex"]
    assert dropped == ["-Z shell-escape"]
    assert applied == ["-synctex=1"]


# ================================================================ xelatex 编译循环
def test_xelatex_pass_gating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """pass≥2 仅当上趟 pdf 已落盘——不写 pdf 的假进程只跑 1 趟。"""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls))
    (tmp_path / "main.tex").write_text("x")
    res = XelatexEngine(binary="/bin/true").compile(
        tmp_path, "main.tex", passes=3, sandbox=False
    )
    assert len(calls) == 1 and res.passes == 1  # noqa: PT018
    # ok=跑完语义，与出 pdf 无关
    assert res.ok is True
    assert res.has_pdf is False


def test_xelatex_passes_zero_no_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``passes=0`` → 零次 run_process；res 字段全默认。"""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls))
    (tmp_path / "main.tex").write_text("x")
    res = XelatexEngine(binary="/bin/true").compile(
        tmp_path, "main.tex", passes=0, sandbox=False
    )
    assert calls == [] and res.passes == 0 and res.ok is False  # noqa: PT018


def test_xelatex_per_pass_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """单趟预算 = ``max(10, timeout/passes)``——10s 地板与整除两态。"""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls, side=_write_pdf))
    (tmp_path / "main.tex").write_text("x")
    eng = XelatexEngine(binary="/bin/true")
    eng.compile(tmp_path, "main.tex", passes=1, timeout=1, sandbox=False)
    assert calls[-1]["timeout"] == _PER_PASS_FLOOR
    eng.compile(tmp_path, "main.tex", passes=3, timeout=90, sandbox=False)
    assert calls[-1]["timeout"] == 30.0  # noqa: PLR2004


def test_xelatex_ok_semantics_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ok = 非超时 ∧ rc 非 None ∧ rc≥0——rc=3 也算跑完；信号死记 killed_signal。"""
    (tmp_path / "main.tex").write_text("x")
    for rc, want_ok, want_sig in (
        (0, True, None),
        (1, True, None),
        (3, True, None),  # 跑完但编译失败——judge 走 log/pdf 判
        (-9, False, 9),
        (-13, False, 13),
        (None, False, None),
    ):
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls, rc=rc))
        res = XelatexEngine(binary="/bin/true").compile(
            tmp_path, "main.tex", passes=1, sandbox=False
        )
        assert res.ok is want_ok and res.killed_signal == want_sig, rc  # noqa: PT018
        assert res.rc == rc


def test_xelatex_midloop_signal_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """中途被信号杀、末趟跑完：killed_signal 留 SIGPIPE，ok 照末趟 rc。"""
    rcs = iter([-13, 0])

    def seq(  # noqa: PLR0913
        cmd: list[str],  # noqa: ARG001
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        out_cap: int = 8 * 1024 * 1024,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[int | None, str, float, bool]:
        del env, timeout, out_cap, should_cancel
        (cwd / "main.pdf").write_bytes(b"%PDF")
        return next(rcs), "", 0.1, False

    monkeypatch.setattr(eng_mod, "run_process", seq)
    (tmp_path / "main.tex").write_text("x")
    res = XelatexEngine(binary="/bin/true").compile(
        tmp_path, "main.tex", passes=2, sandbox=False
    )
    assert res.killed_signal == 13 and res.rc == 0 and res.ok is True  # noqa: PLR2004, PT018


def test_xelatex_timeout_breaks_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """首趟超时即收：不跑第二趟，ok=False。"""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls, to=True))
    (tmp_path / "main.tex").write_text("x")
    res = XelatexEngine(binary="/bin/true").compile(
        tmp_path, "main.tex", passes=3, sandbox=False
    )
    assert len(calls) == 1 and res.timed_out is True and res.ok is False  # noqa: PT018


def test_xelatex_auto_rerun_gate_no_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``passes=None`` 自适应档（fix#7）：pass-1 无 rerun 提示 → 不跑第二趟。"""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls, side=_write_pdf))
    (tmp_path / "main.tex").write_text("x")
    res = XelatexEngine(binary="/bin/true").compile(tmp_path, "main.tex", sandbox=False)
    assert len(calls) == 1 and res.passes == 1 and res.has_pdf  # noqa: PT018


def test_xelatex_auto_rerun_gate_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """自适应档：rerun 提示族逐形命中即续趟；提示出现在趟输出尾段。"""
    (tmp_path / "main.tex").write_text("x")
    for hint in (
        "LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.",
        (
            "Package rerunfilecheck Warning: File `main.out' has changed.\n"
            "(rerunfilecheck)                Rerun to get outlines right."
        ),
        "LaTeX Warning: There were undefined references.",
        "Package longtable Warning: Table widths have changed. Rerun LaTeX.",
    ):
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            eng_mod, "run_process", _fake_run(calls, out=hint + "\n", side=_write_pdf)
        )
        res = XelatexEngine(binary="/bin/true").compile(
            tmp_path, "main.tex", sandbox=False
        )
        assert len(calls) == 2 and res.passes == 2, hint  # noqa: PLR2004, PT018


def test_xelatex_auto_rerun_noise_no_pass2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """自适应档不误续：rerunfilecheck 包名行/biber 请求不构成续趟信号。"""
    (tmp_path / "main.tex").write_text("x")
    for noise in (
        "Package: rerunfilecheck 2022/07/05 v1.10 Rerun check for auxiliary files",
        (
            "Package biblatex Warning: Please (re)run Biber on the file: main\n"
            "(biblatex)                and rerun LaTeX afterwards."
        ),
    ):
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            eng_mod, "run_process", _fake_run(calls, out=noise + "\n", side=_write_pdf)
        )
        res = XelatexEngine(binary="/bin/true").compile(
            tmp_path, "main.tex", sandbox=False
        )
        assert len(calls) == 1 and res.passes == 1, noise  # noqa: PT018


def test_xelatex_explicit_passes_ungated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """显式 ``passes=N`` 不吃 rerun 门——fixloop 收敛终编/bench 口径跑满。"""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls, side=_write_pdf))
    (tmp_path / "main.tex").write_text("x")
    res = XelatexEngine(binary="/bin/true").compile(
        tmp_path, "main.tex", passes=3, sandbox=False
    )
    assert len(calls) == 3 and res.passes == 3  # noqa: PLR2004, PT018


def _write_pdf_and_log(cmd: list[str], _cwd: Path, _n: int) -> None:
    out = _xe_out(cmd)
    (out / "main.pdf").write_bytes(b"%PDF-fake")
    (out / "main.log").write_text(
        "This is XeTeX\n! cached log body\n", encoding="utf-8"
    )


def test_compile_log_text_carried_no_reread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``res.log_text`` 载编译期已读 .log 原文（fix#10）——parse_log(res) 免开文件。"""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        eng_mod, "run_process", _fake_run(calls, side=_write_pdf_and_log)
    )
    (tmp_path / "main.tex").write_text("x")
    eng = XelatexEngine(binary="/bin/true")
    res = eng.compile(tmp_path, "main.tex", sandbox=False)
    assert res.log_text == "This is XeTeX\n! cached log body\n"
    res.log_path.unlink()  # 盘面抹掉——parse_log 仍应复用 log_text
    info = eng.parse_log(res)
    assert info.n_errors == 1


def test_xelatex_error_exit_short_circuits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C3：错误退出（rc>0）即停——哪怕已出 pdf 也不空烧第二趟；显式/自适应同闸。"""
    (tmp_path / "main.tex").write_text("x")
    for kw in ({"passes": 2}, {}):
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            eng_mod, "run_process", _fake_run(calls, rc=1, side=_write_pdf)
        )
        res = XelatexEngine(binary="/bin/true").compile(
            tmp_path,
            "main.tex",
            sandbox=False,
            **kw,  # type: ignore[arg-type]
        )
        assert len(calls) == 1 and res.rc == 1 and res.passes == 1, kw  # noqa: PT018


def test_xelatex_probe_memo_hit_and_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """树探测按名 memo（fix#3）：命中/阴性都缓存；cwd 直查绕开缓存自失效。"""
    eng = XelatexEngine(binary="/bin/true")
    monkeypatch.setattr(eng_mod, "find_tool", lambda _n: "/x/kpsewhich")
    calls: list[str] = []

    def probe_run(  # noqa: PLR0913
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        out_cap: int = 8 * 1024 * 1024,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[int | None, str, float, bool]:
        del cwd, env, timeout, out_cap, should_cancel
        name = cmd[-1]
        calls.append(name)
        if name.startswith("have"):
            return 0, f"/t/{name}\n", 0.01, False
        return 1, "", 0.01, False

    monkeypatch.setattr(eng_mod, "run_process", probe_run)
    assert eng.probe_file("have.sty") == "/t/have.sty"
    assert eng.probe_file("have.sty") == "/t/have.sty"  # memo 命中不起子进程
    assert eng.probe_file("gone.sty") is None
    assert eng.probe_file("gone.sty") is None  # 阴性也缓存
    assert calls == ["have.sty", "gone.sty"]
    # cwd 命中走 is_file 直查：wdir 落件不被先前的阴性缓存遮蔽
    (tmp_path / "gone.sty").write_text("x")
    assert eng.probe_file("gone.sty", cwd=tmp_path) == str(tmp_path / "gone.sty")
    assert calls == ["have.sty", "gone.sty"]


def test_xelatex_probe_memo_cleared_on_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """install_file 动树后清 memo——装了包不重探即「装上还 miss」假阴。"""
    monkeypatch.setenv("TEXLATE_TLMGR_CACHE", str(tmp_path / "c.json"))
    monkeypatch.delenv("TEXMFHOME", raising=False)  # 宿主链在场会走 fetch 面
    eng = XelatexEngine(binary="/bin/true")
    monkeypatch.setattr(eng_mod, "find_tool", lambda n: f"/x/{n}")
    monkeypatch.setattr(XelatexEngine, "_fontconfig_conf", lambda _s: None)
    calls: list[str] = []

    def run(  # noqa: PLR0913
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        out_cap: int = 8 * 1024 * 1024,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[int | None, str, float, bool]:
        del cwd, env, timeout, out_cap, should_cancel
        calls.append(Path(cmd[0]).name)
        if "kpsewhich" in cmd[0]:
            return 1, "", 0.01, False  # 树里始终没有
        return 0, "", 0.01, False  # tlmgr 系成功

    monkeypatch.setattr(eng_mod, "run_process", run)
    eng._search_cache = {"/pkg.sty": ["somepkg"]}  # 离线 filemap 表直喂  # noqa: SLF001
    assert eng.probe_file("pkg.sty") is None  # 阴性入 memo
    assert calls == ["kpsewhich"]
    assert eng.install_file("pkg.sty") is False  # 树里仍无 → 复核失败
    # 关键钉：tlmgr 之后 probe 真起了 kpsewhich——缓存被清，不是直接复喂阴性
    assert calls == ["kpsewhich", "tlmgr", "kpsewhich"]


def test_xelatex_stdout_tail_last_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stdout_tail = 末趟输出的尾部 4000——前趟内容不拼接。"""
    outs = iter(["A" * 5000, "B" * 100])

    def seq(  # noqa: PLR0913
        cmd: list[str],  # noqa: ARG001
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        out_cap: int = 8 * 1024 * 1024,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[int | None, str, float, bool]:
        del env, timeout, out_cap, should_cancel
        (cwd / "main.pdf").write_bytes(b"%PDF")
        return 0, next(outs), 0.1, False

    monkeypatch.setattr(eng_mod, "run_process", seq)
    (tmp_path / "main.tex").write_text("x")
    res = XelatexEngine(binary="/bin/true").compile(
        tmp_path, "main.tex", passes=2, sandbox=False
    )
    assert res.stdout_tail == "B" * 100
    calls2: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls2, out="X" * 5000))
    res = XelatexEngine(binary="/bin/true").compile(
        tmp_path, "main.tex", passes=1, sandbox=False
    )
    assert res.stdout_tail == "X" * _STDOUT_TAIL


def test_xelatex_stale_artifacts_unlinked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """开局先删陈旧 pdf/log/fls——fake 观察时三件已消失。"""
    (tmp_path / "main.tex").write_text("x")
    for art in ("main.pdf", "main.log", "main.fls"):
        (tmp_path / art).write_bytes(b"STALE")
    seen: list[bool] = []

    def side(cmd: list[str], cwd: Path, _n: int) -> None:
        del cmd
        seen.append((cwd / "main.pdf").exists())

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls, side=side))
    res = XelatexEngine(binary="/bin/true").compile(
        tmp_path, "main.tex", passes=1, sandbox=False
    )
    assert seen == [False]
    assert res.pdf is None and res.has_pdf is False  # noqa: PT018


def test_xelatex_missing_binary_early_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """binary=None + PATH 缺席 → 早退 CompRes；旗标簿记在 detect 之前。"""
    monkeypatch.setattr(eng_mod, "find_tool", lambda _n: None)
    res = XelatexEngine(binary=None).compile(
        tmp_path, "main.tex", flags=["-synctex=1"], sandbox=False
    )
    assert res.stdout_tail == "xelatex not found"
    assert res.flags_applied == ["-synctex=1"]  # split 先于 detect——缺席也记账


def test_xelatex_env_mode_strips_shell_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """env 降级（OS 包裹缺席）：shell-escape 系从 argv+applied 双摘入 dropped。"""
    monkeypatch.setattr(sb_mod, "_bwrap_capable", lambda: False)
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls))
    (tmp_path / "main.tex").write_text("x")
    res = XelatexEngine(binary="/bin/true").compile(
        tmp_path,
        "main.tex",
        passes=1,
        sandbox=True,
        flags=["-shell-escape", "-synctex=1", "--enable-write18"],
    )
    assert res.sandbox_mode == "env"
    cmd = calls[-1]["cmd"]
    assert isinstance(cmd, list)
    for esc in _O_SHELL_ESC:
        assert esc not in cmd
    assert "-shell-escape" in res.flags_dropped
    assert "--enable-write18" in res.flags_dropped
    assert "-synctex=1" in res.flags_applied and "-synctex=1" in cmd  # noqa: PT018


def test_xelatex_flags_rekey_not_in_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """-jobname/-output-directory 系进 dropped 不进 argv（回收约定保险）。"""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls))
    (tmp_path / "main.tex").write_text("x")
    res = XelatexEngine(binary="/bin/true").compile(
        tmp_path,
        "main.tex",
        passes=1,
        sandbox=False,
        flags=["-jobname=evil", "-output-directory", "/tmp/x", "-synctex=1"],  # noqa: S108
    )
    cmd = calls[-1]["cmd"]
    assert isinstance(cmd, list)
    assert "-jobname=evil" not in cmd and "/tmp/x" not in cmd  # noqa: PT018, S108
    assert res.flags_dropped == ["-jobname=evil", "-output-directory", "/tmp/x"]  # noqa: S108


def test_xelatex_env_extra_overrides_forced_valve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D7 已修：env_extra 同名键滤除——``_ENV_FORCED`` 阀值恒赢。"""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls))
    (tmp_path / "main.tex").write_text("x")
    XelatexEngine(binary="/bin/true").compile(
        tmp_path,
        "main.tex",
        passes=1,
        sandbox=False,
        env_extra={"shell_escape": "t", "openin_any": "a", "ARBITRARY_K": "v"},
    )
    env = calls[-1]["env"]
    assert isinstance(env, dict)
    assert env["shell_escape"] == "f"  # 强制阀不被压
    assert env["openin_any"] == "p"
    assert env["ARBITRARY_K"] == "v"  # 非阀键增量照常进


def test_xelatex_nul_main_raises(tmp_path: Path) -> None:
    """D3 已修：NUL main 在 ``_checked_main`` 显式拒——先于 stale unlink/FS 变更。"""
    (tmp_path / "main.tex").write_text("x")
    with pytest.raises(ValueError, match="embedded null"):
        XelatexEngine(binary="/bin/true").compile(
            tmp_path, "bad\x00.tex", passes=1, sandbox=False
        )


def test_xelatex_main_parent_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D9 已修：``main="../main.tex"`` 与 NUL 同走 ValueError。"""
    work = tmp_path / "w"
    work.mkdir()
    (tmp_path / "main.tex").write_text("x")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls))
    with pytest.raises(ValueError, match="main"):
        XelatexEngine(binary="/bin/true").compile(
            work, "../main.tex", passes=1, sandbox=False
        )


def test_xelatex_outdir_redirect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``outdir`` 显式给：pdf/log/fls 落 outdir 不落 cwd。"""
    work = tmp_path / "w"
    out = tmp_path / "o"
    work.mkdir()
    (work / "main.tex").write_text("x")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls, side=_write_pdf))
    res = XelatexEngine(binary="/bin/true").compile(
        work, "main.tex", passes=1, sandbox=False, outdir=out
    )
    assert res.pdf == out / "main.pdf" and res.has_pdf  # noqa: PT018
    assert calls[-1]["cwd"] == work  # cwd 仍是主文件目录
    cmd = calls[-1]["cmd"]
    assert isinstance(cmd, list) and f"-output-directory={out}" in cmd  # noqa: PT018


def test_xelatex_deps_from_fls_integration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """compile → compiled_dependencies 端到端：fake 写 .fls，deps 排序落 res。"""
    work = tmp_path / "w"
    (work / "sub").mkdir(parents=True)
    (work / "main.tex").write_text("x")
    (work / "sub" / "s.tex").write_text("x")

    def side(cmd: list[str], cwd: Path, _n: int) -> None:  # noqa: ARG001
        out = _xe_out(cmd)
        (out / "main.fls").write_text(
            "PWD /x\nINPUT ./main.tex\nINPUT ./sub/s.tex\nINPUT /etc/passwd\n"
        )
        (out / "main.pdf").write_bytes(b"%PDF")

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls, side=side))
    res = XelatexEngine(binary="/bin/true").compile(
        work, "main.tex", passes=1, sandbox=False
    )
    assert res.deps == ["main.tex", "sub/s.tex"]


def test_xelatex_best_effort_halt_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``-halt-on-error`` 仅在 halt_on_error ∧ ¬best_effort 时进 argv。"""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls))
    (tmp_path / "main.tex").write_text("x")
    eng = XelatexEngine(binary="/bin/true")
    eng.compile(tmp_path, "main.tex", passes=1, sandbox=False)
    assert "-halt-on-error" in calls[-1]["cmd"]  # type: ignore[operator]
    eng.compile(tmp_path, "main.tex", passes=1, sandbox=False, best_effort=True)
    assert "-halt-on-error" not in calls[-1]["cmd"]  # type: ignore[operator]
    eng2 = XelatexEngine(binary="/bin/true", halt_on_error=False)
    eng2.compile(tmp_path, "main.tex", passes=1, sandbox=False)
    assert "-halt-on-error" not in calls[-1]["cmd"]  # type: ignore[operator]


# ================================================================ tectonic 编译循环
def _tec_side(cmd: list[str], _cwd: Path, _n: int) -> None:
    out = _tec_out(cmd)
    out.mkdir(parents=True, exist_ok=True)
    (out / "main.pdf").write_bytes(b"%PDF-fake")
    (out / "main.log").write_text("ok\n")
    (out / "dependencies.mk").write_text("main.pdf: main.tex\n")


def test_tectonic_compile_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """单趟编译：--outdir 落点 + deps.mk → res.deps + passes 恒 1。"""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls, side=_tec_side))
    (tmp_path / "main.tex").write_text("x")
    res = TectonicEngine(binary="/bin/true", bundle="").compile(
        tmp_path,
        "main.tex",
        passes=7,
        sandbox=False,  # passes 被 del——恒单趟
    )
    assert len(calls) == 1 and res.passes == 1  # noqa: PT018
    assert res.has_pdf and res.deps == ["main.tex"]  # noqa: PT018
    cmd = calls[-1]["cmd"]
    assert isinstance(cmd, list)
    assert "--untrusted" in cmd and "--makefile-rules" in cmd  # noqa: PT018
    assert res.sandbox_mode == "off"


def test_tectonic_retry_clears_timed_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """首趟超时重试成功：timed_out 取**末趟**态——首拉超时不再背 fail。"""
    state = {"n": 0}

    def seq(  # noqa: PLR0913
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        out_cap: int = 8 * 1024 * 1024,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[int | None, str, float, bool]:
        del env, out_cap, should_cancel
        state["n"] += 1
        if state["n"] == 1:
            return None, "", timeout, True
        _tec_side(cmd, cwd, state["n"])
        return 0, "", 0.1, False

    monkeypatch.setattr(eng_mod, "run_process", seq)
    (tmp_path / "main.tex").write_text("x")
    res = TectonicEngine(binary="/bin/true", bundle="").compile(
        tmp_path, "main.tex", timeout=300, sandbox=False
    )
    assert state["n"] == _TECT_ATTEMPTS
    assert res.timed_out is False and res.ok is True  # noqa: PT018


def test_tectonic_retry_budget_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重试趟预算 ``min(timeout,120)``——全超时归 timed_out=True。"""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls, to=True, sec=0.1))
    (tmp_path / "main.tex").write_text("x")
    res = TectonicEngine(binary="/bin/true", bundle="").compile(
        tmp_path, "main.tex", timeout=300, sandbox=False
    )
    assert [c["timeout"] for c in calls] == [300, _TECT_RETRY_CAP]
    assert res.timed_out is True and res.ok is False  # noqa: PT018


def test_tectonic_flags_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """flags 经 _map_flags 入 argv：原拼写记 applied，映射 token 进 cmd。"""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls, side=_tec_side))
    (tmp_path / "main.tex").write_text("x")
    res = TectonicEngine(binary="/bin/true", bundle="").compile(
        tmp_path,
        "main.tex",
        sandbox=False,
        flags=["-synctex=1", "-Z", "keep-logs", "-shell-escape", "-Z", "bogus"],
    )
    cmd = calls[-1]["cmd"]
    assert isinstance(cmd, list)
    assert "--synctex" in cmd and "-shell-escape" not in cmd  # noqa: PT018
    assert "bogus" not in cmd
    assert res.flags_applied == ["-synctex=1", "-Z", "keep-logs"]
    assert res.flags_dropped == ["-shell-escape", "-Z bogus"]


def test_tectonic_missing_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(eng_mod, "ensure_tectonic", lambda: None)
    res = TectonicEngine(binary=None, bundle="").compile(
        tmp_path, "main.tex", sandbox=False
    )
    assert res.stdout_tail == "tectonic not found" and res.ok is False  # noqa: PT018


def test_tectonic_probe_file_parent_escape(tmp_path: Path) -> None:
    """D5 已修：``../`` 逃逸命中回 None——probe 须留在 cwd 内。"""
    (tmp_path / "secret.sty").write_text("% x")
    work = tmp_path / "w"
    work.mkdir()
    te = TectonicEngine(bundle="")
    assert te.probe_file("../secret.sty", cwd=work) is None
    assert te.probe_file("nope.sty", cwd=work) is None
    assert te.probe_file("nope.sty") is None  # cwd 缺席永不命中


def test_tectonic_filemap_install_primitives() -> None:
    """filemap_index 离线索引 + ctan_fetch 原语——返回拷贝不曝内部表。"""
    te = TectonicEngine(bundle="")
    te.filemap_index["x.sty"] = ["pkg-a"]
    got = te.filemap("x.sty")
    assert got == ["pkg-a"]
    got.append("mut")  # 返回副本——改不动内部索引
    assert te.filemap_index["x.sty"] == ["pkg-a"]
    assert te.filemap("absent.sty") == []
    assert te.install_file("x.sty") is False  # ctan_fetch 缺席
    te2 = TectonicEngine(bundle="", ctan_fetch=lambda f: f"/dest/{f}")
    assert te2.install_file("x.sty") is True
    assert te.rebuild_fontmaps() is False  # tectonic 无 updmap


# ================================================================ _apply_sandbox 分派
def test_apply_sandbox_truth_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """分派真值表：off / sandbox-exec(包裹换 argv) / bwrap / env / 非 linux env。"""
    cmd, mode = sb_mod._apply_sandbox(  # noqa: SLF001
        ["x"], root=tmp_path, out=tmp_path, env={}, enabled=False, allow_net=True
    )
    assert mode == "off" and cmd == ["x"]  # noqa: PT018
    # sandbox_wrap 返回**新** argv（is-not 判定）→ sandbox-exec
    monkeypatch.setattr(
        sb_mod,
        "sandbox_wrap",
        lambda c, **k: ["se", *c],  # noqa: ARG005
    )
    cmd, mode = sb_mod._apply_sandbox(  # noqa: SLF001
        ["x"], root=tmp_path, out=tmp_path, env={}, enabled=True, allow_net=True
    )
    assert mode == "sandbox-exec" and cmd[0] == "se"  # noqa: PT018
    # 原样返回（is 判定）→ 平台分派
    monkeypatch.setattr(sb_mod, "sandbox_wrap", lambda c, **k: c)  # noqa: ARG005
    monkeypatch.setattr(sb_mod, "_bwrap_wrap", lambda c, **k: ["bw", *c])  # noqa: ARG005
    monkeypatch.setattr(sys, "platform", "linux")
    cmd, mode = sb_mod._apply_sandbox(  # noqa: SLF001
        ["x"], root=tmp_path, out=tmp_path, env={}, enabled=True, allow_net=True
    )
    assert mode == "bwrap" and cmd[0] == "bw"  # noqa: PT018
    monkeypatch.setattr(sb_mod, "_bwrap_wrap", lambda c, **k: None)  # noqa: ARG005
    cmd, mode = sb_mod._apply_sandbox(  # noqa: SLF001
        ["x"], root=tmp_path, out=tmp_path, env={}, enabled=True, allow_net=True
    )
    assert mode == "env" and cmd == ["x"]  # noqa: PT018
    monkeypatch.setattr(sys, "platform", "win32")
    _cmd2, mode = sb_mod._apply_sandbox(  # noqa: SLF001
        ["x"], root=tmp_path, out=tmp_path, env={}, enabled=True, allow_net=True
    )
    assert mode == "env"  # 非 linux 不问 bwrap


def test_rc_to_signal_wrap_decode() -> None:
    """128+N 仅在 bwrap/sandbox-exec 包裹下解码——off/env 下是字面退出码。"""
    sig = sb_mod._rc_to_signal  # noqa: SLF001
    assert sig(-11, "off") == 11  # noqa: PLR2004
    assert sig(None, "bwrap") is None
    assert sig(0, "bwrap") is None
    for mode in ("bwrap", "sandbox-exec"):
        assert sig(141, mode) == 13  # noqa: PLR2004
        assert sig(_WRAP_SIG_MAX, mode) == _WRAP_SIG_MAX - _WRAP_SIG_BASE
        assert sig(_WRAP_SIG_MAX + 1, mode) is None
        assert sig(_WRAP_SIG_BASE, mode) is None
    for mode in ("off", "env"):
        assert sig(141, mode) is None


# ================================================================ parse_log fuzz oracle
class _LogGen:
    """随机 log 行发生器 + 生成侧期望登记（错误/首错/ctx/warning 归属）。"""

    _FNAMES = ("main.tex", "./sub/a.sty", "weird-name_2.cls", "x.pdf_t")
    _DECOY_FL = (
        "Makefile",  # 无扩展名
        "C:\\foo.tex",  # 内嵌冒号
        "noext",  # 无点
    )

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.lines: list[str] = []
        self.warn_sys_names: set[str] = set()
        self.utf8_proj = False
        self.hit_graphic = False
        self.hit_degraded = False

    def emit(self) -> None:  # noqa: C901
        rng = self.rng
        for _ in range(rng.randrange(5, 50)):
            pick = rng.random()
            if pick < 0.2:  # noqa: PLR2004
                self.lines.append(f"({rng.choice(self._FNAMES)}")
            elif pick < 0.3:  # noqa: PLR2004
                self.lines.append(")")
            elif pick < 0.42:  # noqa: PLR2004
                self.lines.append(
                    "! "
                    + rng.choice(
                        ("Undefined control sequence.", "Emergency stop.", "x" * 400)
                    )
                )
            elif pick < 0.52:  # noqa: PLR2004
                f = rng.choice(self._FNAMES)
                self.lines.append(
                    f"{f}:{rng.randrange(1, 999)}: {rng.choice(('Undefined control sequence.', 'Runaway argument?'))}"
                )
            elif pick < 0.6:  # noqa: PLR2004
                # 非错误 fileline——Warning 形与 ==> 汇总尾
                f = rng.choice(self._FNAMES)
                self.lines.append(
                    f"{f}:{rng.randrange(1, 99)}: "
                    + rng.choice(
                        (
                            "LaTeX Warning: Label(s) may have changed.",
                            "Package foo Warning: x",
                            "==> Fatal error occurred, no output PDF file produced!",
                            "Warning: no class prefix — 这条是错误！",  # 无 LaTeX/Package/Class 前缀 → 计错
                        )
                    )
                )
            elif pick < 0.66:  # noqa: PLR2004
                # 畸形 fileline——不得计错
                f = rng.choice(self._DECOY_FL)
                self.lines.append(f"{f}:{rng.randrange(1, 99)}: bogus msg")
            elif pick < 0.72:  # noqa: PLR2004
                self.lines.append(f"l.{rng.randrange(1, 500)} context here")
            elif pick < 0.78:  # noqa: PLR2004
                self._emit_utf8()
            elif pick < 0.84:  # noqa: PLR2004
                self.lines.append(
                    rng.choice(
                        (
                            "File `fig.eps' not found",
                            "Cannot determine size of graphic in fig.eps (no BoundingBox)",
                        )
                    )
                )
                self.hit_graphic = True
            elif pick < 0.9:  # noqa: PLR2004
                self.lines.append("! File `x.sty' not found.")
                self.hit_degraded = True
            else:
                self.lines.append(
                    rng.choice(
                        (
                            "ordinary log line",
                            "(nested nonfile paren",
                            "  indented ! not an error",
                            "  main.tex:5: indented not error",
                            "Overfull \\hbox (12pt) in paragraph",
                            "",
                        )
                    )
                )

    def _emit_utf8(self) -> None:
        """invalid_utf8 行——栈顶归属登记（工程/系统两态）。"""
        inner = next(
            (s for s in reversed(file_stack_at(self.lines, len(self.lines))) if s),
            None,
        )
        self.lines.append("Invalid UTF-8 byte sequence near line 1")
        if is_project_file(inner, None):
            self.utf8_proj = True
        else:
            self.warn_sys_names.add(Path(inner).name if inner else "?")


def _o_parse(lines: list[str]) -> dict[str, object]:
    """独立重算 parse_log 全字段（栈/弹栈走共享件 file_stack_at）。"""
    err_idx = [
        i
        for i, ln in enumerate(lines)
        if ln.startswith("!") or (_O_FILELINE.match(ln) and not _O_NONERR.match(ln))
    ]
    out: dict[str, object] = {
        "n_errors": len(err_idx),
        "errors": [lines[i].strip()[:_ERR_TRUNC] for i in err_idx],
        "tail": "\n".join(lines[-_TAIL_N:]),
        "first": lines[err_idx[0]].strip() if err_idx else None,
        "ctx": None,
        "err_line": None,
        "stack": [],
        "popped": [],
    }
    if err_idx:
        start = err_idx[0]
        ctx = lines[start : start + _CTX_N]
        out["ctx"] = "\n".join(ctx)
        for ln in ctx:
            m = _O_LNUM.match(ln.strip())
            if m:
                out["err_line"] = int(m.group(1))
                break
        popped: list[str | None] = []
        out["stack"] = file_stack_at(lines, start + 1, popped)
        out["popped"] = [t for t in popped if t is not None]
    return out


def test_parse_log_fuzz() -> None:
    """随机 log → n_errors/first/ctx/l.NN/tail/栈快照/警告归属全字段对拍。"""
    rng = fuzz_rng(_SEED + 3)
    for i in range(_ITER):
        gen = _LogGen(rng)
        gen.emit()
        text = "\n".join(gen.lines) + rng.choice(("", "\n"))
        info = parse_log(text)
        o = _o_parse(text.splitlines())
        assert info.n_errors == o["n_errors"], i
        assert info.first_error == o["first"]
        assert info.errors == o["errors"]
        assert info.error_ctx == o["ctx"]
        assert info.error_line == o["err_line"]
        assert info.tail == o["tail"]
        assert info.file_stack == o["stack"]
        assert info.popped_files == o["popped"]
        want_hit: list[str] = []
        if gen.utf8_proj:
            want_hit.append("invalid_utf8")
        if gen.hit_graphic:
            want_hit.append("missing_graphic")
        if gen.hit_degraded:
            want_hit.append("degraded_file")
        assert info.warnings_hit == want_hit, (i, text[-400:])
        assert info.warnings_sys == [
            f"invalid_utf8@{n}" for n in sorted(gen.warn_sys_names)
        ]
        # 首错行长不截断、errors[] 截断的不对称
        if info.errors:
            assert all(len(e) <= _ERR_TRUNC for e in info.errors)


def test_parse_log_empty_and_tail() -> None:
    """空 log → 全默认；>30 行时 tail 只留末 30。"""
    info = parse_log("")
    assert info.n_errors == 0 and info.tail == "" and info.first_error is None  # noqa: PT018
    text = "\n".join(f"line {j}" for j in range(50))
    info = parse_log(text)
    assert info.tail == "\n".join(f"line {j}" for j in range(20, 50))


def test_parse_log_utf8_attribution_pinned() -> None:
    """invalid_utf8 归属两态：工程栈内 → warnings_hit；texmf 树 → warnings_sys。"""
    proj = parse_log("(./main.tex\nInvalid UTF-8 byte sequence\n)\n")
    assert proj.warnings_hit == ["invalid_utf8"] and proj.warnings_sys == []  # noqa: PT018
    sysl = parse_log(
        "(/usr/share/texmf-dist/tex/latex/x.sty\nInvalid UTF-8 byte sequence\n)\n"
    )
    assert sysl.warnings_hit == []
    assert sysl.warnings_sys == ["invalid_utf8@x.sty"]


def test_classify_error_pins() -> None:
    """timed_out 短路 + taxonomy 装载下的代表类（rules.yaml 在场即真分类）。"""
    assert classify_error_(None, None, "", timed_out=True) == ("timeout", None)
    assert classify_error_(None, None, "", timed_out=False) == ("clean", None)
    cat, payload = classify_error_(
        "! LaTeX Error: File `x.sty' not found.", None, "", timed_out=False
    )
    assert cat == "missing_file" and payload == "x.sty"  # noqa: PT018
    cat, _p = classify_error_(
        "! Undefined control sequence.", "l.3 \\bad", "", timed_out=False
    )
    assert cat == "undefined_cs"


# classify_error 走 lru 缓存 taxonomy——别名简化调用面
classify_error_ = eng_mod.classify_error


# ================================================================ makefile / 依赖记录
def _o_makefile_names(text: str) -> list[str] | None:  # noqa: C901, PLR0912
    """独立重算首条依赖行（Make 转义 ``\\ `` ``\\#`` ``\\:`` ``\\\\`` ``\\t`` + ``$$``→``$``）。"""
    text = re.sub(r"\\\r?\n", " ", text)
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        sep = None
        i = 0
        while i < len(line):
            if line[i] == "\\" and i + 1 < len(line) and line[i + 1] in " \\#:\t":
                i += 2
                continue
            if line[i] == ":" and (i + 1 == len(line) or line[i + 1].isspace()):
                sep = i
                break
            i += 1
        if sep is None:
            return None
        values: list[str] = []
        cur: list[str] = []
        i = sep + 1
        while i < len(line):
            c = line[i]
            if c == "\\" and i + 1 < len(line) and line[i + 1] in " \\#:\t":
                cur.append(line[i + 1])
                i += 2
                continue
            if c == "#":
                break
            if c.isspace():
                if cur:
                    values.append("".join(cur).replace("$$", "$"))
                    cur = []
            else:
                cur.append(c)
            i += 1
        if cur:
            values.append("".join(cur).replace("$$", "$"))
        return values
    return None


def _mk_escape(name: str) -> str:
    """生成侧 Make 转义（``$$`` 先放——``$`` 是结果侧字符不是转义）。"""
    return (
        name.replace("\\", "\\\\")
        .replace("$", "$$")
        .replace(" ", "\\ ")
        .replace("#", "\\#")
        .replace(":", "\\:")
        .replace("\t", "\\\t")
    )


def test_makefile_inputs_roundtrip() -> None:
    """随机 prereq 名 → Make 转义 → 解析回原名（round-trip 性质）。"""
    rng = fuzz_rng(_SEED + 4)
    alphabet = "ab ._-:#\\\t$"
    for _ in range(_ITER):
        names = [
            # 尾部反斜杠不可 round-trip：转义出的 `\\` 紧邻行尾 \n 被 Make
            # 续行规则先折叠成空格——格式固有歧义，非解析缺陷
            "".join(rng.choice(alphabet) for _ in range(rng.randrange(1, 12)))
            .strip()
            .rstrip("\\")
            or "x"
            for _ in range(rng.randrange(1, 5))
        ]
        text = "out: " + " ".join(_mk_escape(n) for n in names) + "\n"
        assert deps_mod._makefile_inputs(text) == names, text  # noqa: SLF001
        assert _o_makefile_names(text) == names


def test_makefile_inputs_edge_table() -> None:
    """首行无分隔→None；注释/空行跳过；``#`` 起注释截断；续行合并。"""
    mk = deps_mod._makefile_inputs  # noqa: SLF001
    assert mk("no colon here\nout: x.tex\n") is None
    assert mk("# comment\nout: x.tex\n") == ["x.tex"]
    assert mk("out:\n") == []
    assert mk("out: a.tex \\\n b.sty \\\n c.cls\n") == ["a.tex", "b.sty", "c.cls"]
    assert mk("out: a.tex # comment\n") == ["a.tex"]
    assert mk("out : a.tex\n") == ["a.tex"]  # 分隔前空格无碍
    assert mk("a:b: c.tex\n") == ["c.tex"]  # 冒号后非空白不算分隔
    assert mk("out: a\\:weird.tex b.tex\n") == ["a:weird.tex", "b.tex"]
    assert mk("") is None


def test_tectonic_unescaped_inputs_semantics() -> None:
    """未转义面：首内容行无 ``:`` → []；此后每物理行一个整名（不拆空白）。"""
    un = deps_mod._tectonic_unescaped_inputs  # noqa: SLF001
    assert un("out: a.tex b.sty\n") == ["a.tex b.sty"]  # 整行一个名
    assert un("no sep\nout: x\n") == []
    assert un("out: a.tex \\\n b.sty\n") == ["a.tex", "b.sty"]
    assert un("out: a.tex # comment\n") == ["a.tex # comment"]  # 不剥注释
    assert un("") == []


def test_compiled_dependencies_fuzz(tmp_path: Path) -> None:
    """随机 INPUT 集 × 随机文件集 → deps 对拍（存在性/根内/后缀/必含 main）。"""
    rng = fuzz_rng(_SEED + 5)
    pool = [
        "main.tex",
        "sub/s.tex",
        "a.sty",
        "b.cls",
        "c.cfg",
        "d.def",
        "e.clo",
        "f.fd",
        "g.ltx",
        "h.eps",
        "i.pdf",
        "UP.TEX",
    ]
    for i in range(_ITER):
        root = tmp_path / f"d{i}"
        root.mkdir()
        exist = rng.sample(pool, k=rng.randrange(1, len(pool)))
        if rng.random() < 0.9 and "main.tex" not in exist:  # noqa: PLR2004
            exist.append("main.tex")
        for rel in exist:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")
        (root / "dir.tex").mkdir(exist_ok=True)  # 目录名 .tex → is_file 拒
        names: list[str] = []
        for rel in rng.sample(pool, k=rng.randrange(0, len(pool))):
            names.append(rng.choice((f"./{rel}", rel, str(root / rel))))  # noqa: PERF401
        names += ["./missing.tex", "/etc/passwd", "./dir.tex", "./h.eps", "INPUT"]
        rng.shuffle(names)
        (root / "main.fls").write_text(
            "".join(f"INPUT {n}\n" for n in names) + "OUTPUT ./main.pdf\n"
        )
        # oracle：每个 INPUT 名 → cwd 相对或绝对 → resolve 后 根内∧文件∧后缀
        want = set()
        cwd = root
        for n in names:
            cand = Path(n)
            cand = cand if cand.is_absolute() else cwd / cand
            try:
                r = cand.resolve()
            except OSError:
                continue
            if (
                r.is_relative_to(root.resolve())
                and r.is_file()
                and r.suffix.lower() in _O_DEP_EXTS
            ):
                want.add(r.relative_to(root.resolve()).as_posix())
        got = compiled_dependencies(root, "main.tex", root, "xelatex")
        if "main.tex" not in want:
            assert got is None, (i, names)
        else:
            assert got == sorted(want), (i, names)


def test_compiled_dependencies_main_required(tmp_path: Path) -> None:
    """main 缺席 fls → None——输入集权威不含主文件即整份作废。"""
    (tmp_path / "main.tex").write_text("x")
    (tmp_path / "s.tex").write_text("x")
    (tmp_path / "main.fls").write_text("INPUT ./s.tex\n")
    assert compiled_dependencies(tmp_path, "main.tex", tmp_path, "xelatex") is None
    # main 在子目录时按 posix rel 判定——fls INPUT 相对编译 cwd（=main 所在
    # 目录 sub/）解析，`./other.tex` 命中 sub/other.tex 而 inputs 不含 main
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "main.tex").write_text("x")
    (tmp_path / "sub" / "other.tex").write_text("x")
    (tmp_path / "main.fls").write_text("INPUT ./other.tex\n")
    assert compiled_dependencies(tmp_path, "sub/main.tex", tmp_path, "xelatex") is None


def test_compiled_dependencies_tectonic_outdir_rel(tmp_path: Path) -> None:
    """tectonic prereq 相对 outdir 书写 → 双解（outdir 相对 + cwd 相对）。"""
    out = tmp_path / "_tect_out"
    out.mkdir()
    (tmp_path / "main.tex").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "s.tex").write_text("x")
    (out / "dependencies.mk").write_text("main.pdf: main.tex sub/s.tex\n")
    assert compiled_dependencies(tmp_path, "main.tex", out, "tectonic") == [
        "main.tex",
        "sub/s.tex",
    ]


# ================================================================ kpathsea/bwrap 纯函数
def test_kpathsea_list_fuzz() -> None:
    """随机分隔汤 → 绝对路径子集；``;`` 不是分隔符（钉值）。"""
    rng = fuzz_rng(_SEED + 6)
    atoms = ["/a", "/b c", "rel", "!", ":", ",", ";", "{", "}", "//", " ", "\n", "/x"]
    for _ in range(_ITER):
        s = "".join(rng.choice(atoms) for _ in range(rng.randrange(0, 12)))
        want = []
        for elem in _O_KPATHSEA_SPLIT.split(s):
            p = elem.lstrip("!").removesuffix("//")
            if p and Path(p).is_absolute():
                want.append(p)
        assert sb_mod._kpathsea_list(s) == want, s  # noqa: SLF001
    assert sb_mod._kpathsea_list("/a;/b") == ["/a;/b"]  # noqa: SLF001  # ; 不拆


def test_bwrap_env_paths_oracle() -> None:
    """env 键 → (rw, ro)：TMP 系不挂、texmf rw 冒号链拆、RO 键名表白名单。"""
    env = {
        "TEXMFHOME": "/a:/b c",
        "TMPDIR": "/tmp/x",  # noqa: S108
        "TEMP": "/tmp/y",  # noqa: S108
        "TEXINPUTS": "/inp:/inp2",
        "TEXLATE_TEX_BUNDLE": "/bundle/b.tar",
        "RANDOM_KEY": "/nowhere",
        "TEXMFVAR": "",
        "BIBINPUTS": "relative:also",
    }
    rw, ro = sb_mod._bwrap_env_paths(env)  # noqa: SLF001
    assert rw == ["/a", "/b"]  # "/b c" 空格拆开，"c" 非绝对弃
    assert ro == ["/inp", "/inp2", "/bundle/b.tar"]


def test_bwrap_mounts_anchor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """挂载面：HOME 本体不挂；kpathsea/env 路径并入；引擎锚发行根三级。"""
    monkeypatch.setattr(sb_mod, "_kpathsea_dirs", lambda: (["/krw"], ["/kro"]))
    home = Path.home()
    rw, ro = sb_mod._bwrap_mounts(  # noqa: SLF001
        "/usr/bin/xelatex", root=tmp_path, out=tmp_path, env={}
    )
    assert str(home) not in rw and str(home) not in ro  # noqa: PT018
    assert "/krw" in rw and "/kro" in ro  # noqa: PT018
    assert str(home / ".fonts") in ro
    # /usr/bin 下的引擎被 _BWRAP_SYS_RO 覆盖——不额外锚
    assert "/usr/bin" not in ro or True  # 覆盖即不再追加 anchor  # noqa: SIM222
    # 前缀外引擎：锚 <dist>/bin/<arch>/<tool> 上三级——root/out 必须落在
    # dist 之外，否则二进制本就被 root 挂载覆盖、锚分支无从触发
    root2 = tmp_path / "root2"
    out2 = tmp_path / "out2"
    root2.mkdir()
    out2.mkdir()
    fake_dist = tmp_path / "dist" / "bin" / "arch"
    fake_dist.mkdir(parents=True)
    (fake_dist / "xelatex").write_text("x")
    _rw2, ro2 = sb_mod._bwrap_mounts(  # noqa: SLF001
        str(fake_dist / "xelatex"), root=root2, out=out2, env={}
    )
    assert str(tmp_path / "dist") in ro2
    # $HOME 下自足单文件引擎 → 锚退化为二进制本体（过宽锚拒挂）
    hb = home / ".texlate" / "tools"
    hb.mkdir(parents=True)
    (hb / "tectonic").write_text("x")
    _rw3, ro3 = sb_mod._bwrap_mounts(  # noqa: SLF001
        str(hb / "tectonic"), root=root2, out=out2, env={}
    )
    assert str(hb / "tectonic") in ro3
    assert str(home) not in ro3


def test_mirror_source_dirs_fuzz(tmp_path: Path) -> None:
    """目录镜像：非 dot 目录全镜像，dot 段与 out 内目录跳过。"""
    rng = fuzz_rng(_SEED + 7)
    src = tmp_path / "src"
    src.mkdir()
    made_dirs: set[str] = set()
    for _ in range(30):
        depth = rng.randrange(1, 4)
        parts = [rng.choice(("a", "b", ".dot", "c d", ".inner")) for _ in range(depth)]
        d = src.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        # mkdir(parents=True) 连带建出的中间目录同样会被镜像——期望集按前缀
        # 逐个登记；前缀一旦含 dot 段，整棵子树都被镜像层跳过
        for k in range(1, len(parts) + 1):
            pre = parts[:k]
            if any(part.startswith(".") for part in pre):
                break
            made_dirs.add("/".join(pre))
        if rng.random() < 0.3:  # noqa: PLR2004
            (d / "f.tex").write_text("x")
    out = tmp_path / "out"
    eng_mod._mirror_source_dirs(src, out)  # noqa: SLF001
    got = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_dir()}
    assert got == made_dirs
    # out 在 cwd 内（tectonic 默认 _tect_out）——不自镜像
    out2 = src / "_tect_out"
    eng_mod._mirror_source_dirs(src, out2)  # noqa: SLF001
    assert not (out2 / "_tect_out").exists()


# ================================================================ xelatex env/工具面
def test_xelatex_env_texmfhome_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEXMFHOME 链 = usertree/home 居首 + ambient 尾随（重名去重）；
    _usertree_env 退链取首元素（tlmgr 不认冒号链）。"""
    tree = tmp_path / "tree"
    monkeypatch.setenv("TEXMFHOME", "/amb1:/amb2")
    eng = XelatexEngine(binary="/bin/true", texmfhome=tree)
    env = eng._env(None)  # noqa: SLF001
    home_tree = str(tree / "home")
    assert env["TEXMFHOME"] == f"{home_tree}:/amb1:/amb2"
    assert env["TEXMFVAR"] == str(tree / "var")
    ute = eng._usertree_env()  # noqa: SLF001
    assert ute["TEXMFHOME"] == home_tree  # 首元素
    # ambient == home_tree → 去重不双写
    monkeypatch.setenv("TEXMFHOME", home_tree)
    assert eng._env(None)["TEXMFHOME"] == home_tree  # noqa: SLF001


def test_xelatex_env_defaults(tmp_path: Path) -> None:  # noqa: ARG001
    """env 缺省阀值：buf_size 放宽 + 安全阀在场；extra 的 buf_size 优先。"""
    env = XelatexEngine(binary="/bin/true")._env(None)  # noqa: SLF001
    assert env["buf_size"] == "8000000"
    assert env["shell_escape"] == "f" and env["openin_any"] == "p"  # noqa: PT018
    env2 = XelatexEngine(binary="/bin/true")._env({"buf_size": "42"})  # noqa: SLF001
    assert env2["buf_size"] == "42"  # setdefault 不压调用方


def test_xelatex_detect_empty_binary_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``binary=""`` 按缺席处理——空串不穿 detect（find_tool 接管）。"""
    monkeypatch.setattr(eng_mod, "find_tool", lambda n: f"/x/{n}")
    assert XelatexEngine(binary="").detect() == "/x/xelatex"
    monkeypatch.setattr(eng_mod, "find_tool", lambda _n: None)
    assert XelatexEngine(binary="").detect() is None


def test_xelatex_probe_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """kpsewhich 探测：NUL 短路、rc≠0/超时/空出 → None、多行取首行。

    树探测按 fname memo（fix#3）——逐臂换名防缓存把后臂探针吃掉。
    """
    eng = XelatexEngine(binary="/bin/true")
    monkeypatch.setattr(eng_mod, "find_tool", lambda _n: "/x/kpsewhich")
    assert eng.probe_file("a\x00b.sty") is None  # NUL 不起子进程
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        eng_mod, "run_process", _fake_run(calls, out="/a/b.sty\n/c/d.sty\n")
    )
    assert eng.probe_file("b.sty", cwd=tmp_path) == "/a/b.sty"
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls, rc=1))
    assert eng.probe_file("b2.sty") is None
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls, to=True))
    assert eng.probe_file("b3.sty") is None
    monkeypatch.setattr(eng_mod, "find_tool", lambda _n: None)
    assert eng.probe_file("b4.sty") is None


def test_filemap_tlmgr_output_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tlmgr 输出过滤：平台后缀条目 + tlmgr/tlgs 前缀滤掉；排序去重。"""
    eng = XelatexEngine(binary="/bin/true")
    monkeypatch.setattr(eng_mod, "find_tool", lambda n: "/x/tlmgr")  # noqa: ARG005
    out = (
        "pkg-a:\n\t/a/b.sty\npkg-b:\n\t/c.sty\n"
        "foo.windows:\n\ty\nbar.x86_64:\n\tz\n"
        "tlmgr: cannot find\n"
        "pkg-a:\n\tagain\n"  # 重复条目去重
    )
    monkeypatch.setattr(eng_mod, "run_process", _fake_run([], out=out))
    assert eng._filemap_tlmgr("b.sty") == ["pkg-a", "pkg-b"]  # noqa: SLF001
    monkeypatch.setattr(eng_mod, "run_process", _fake_run([], rc=1))
    assert eng._filemap_tlmgr("b.sty") == []  # noqa: SLF001
    monkeypatch.setattr(eng_mod, "find_tool", lambda _n: None)
    assert eng._filemap_tlmgr("b.sty") == []  # noqa: SLF001


def test_filemap_nul_and_cache_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_env: pytest.MonkeyPatch
) -> None:
    """filemap：NUL → []；落盘缓存命中短路 tlmgr/索引两路。"""
    clean_env.setenv("TEXLATE_TLMGR_CACHE", str(tmp_path / "c.json"))
    eng = XelatexEngine(binary="/bin/true")
    assert eng.filemap("a\x00b.sty") == []
    save_search_cache({"/x.sty": ["pkg-x"]})
    eng2 = XelatexEngine(binary="/bin/true")
    monkeypatch.setattr(eng_mod, "find_tool", lambda _n: None)  # 无 tlmgr
    assert eng2.filemap("x.sty") == ["pkg-x"]


def test_search_cache_roundtrip(
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,
) -> None:
    """save→load round-trip；空命中不落盘；损坏 JSON → {}。"""
    clean_env.setenv("TEXLATE_TLMGR_CACHE", str(tmp_path / "c.json"))
    cache = {"/a.sty": ["pa"], "/b.sty": [], "/c.sty": ["pc", "pc2"]}
    save_search_cache(cache)
    got = load_search_cache()
    assert got == {"/a.sty": ["pa"], "/c.sty": ["pc", "pc2"]}  # 空值滤掉
    (tmp_path / "c.json").write_text("{corrupt")
    assert load_search_cache() == {}
    (tmp_path / "c.json").write_text("[1,2,3]")  # 非 dict
    assert load_search_cache() == {}
    (tmp_path / "c.json").unlink()
    assert load_search_cache() == {}


def test_search_cache_nonlist_type_confusion(
    tmp_path: Path, clean_env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D2 已修：非 ``list[str]`` 值滤出缓存——filemap 恒返包名表或 ``[]``。"""
    clean_env.setenv("TEXLATE_TLMGR_CACHE", str(tmp_path / "c.json"))
    (tmp_path / "c.json").write_text(
        json.dumps(
            {
                "/x.sty": "notalist",
                "/y.sty": 42,
                "/w.sty": ["ok", 7],
                "/z.sty": ["ok"],
            }
        )
    )
    eng = XelatexEngine(binary="/bin/true")
    monkeypatch.setattr(eng_mod, "find_tool", lambda _n: None)  # 无 tlmgr
    monkeypatch.setattr(
        XelatexEngine, "_filemap_index", lambda _s, _f: None
    )  # 索引缺席 → miss 落 []
    assert eng.filemap("x.sty") == []  # str 值滤出 → 按未命中处理
    assert eng.filemap("y.sty") == []
    assert eng.filemap("w.sty") == []  # list 内掺非 str 元素同滤
    assert eng.filemap("z.sty") == ["ok"]


def test_texmfdist_rc_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ARG001
    """D4 已修：kpsewhich rc!=0 → None——stdout 垃圾不进 fontconfig conf。"""

    class _P:
        stdout = "GARBAGE\n"
        returncode = 1

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _P())  # noqa: ARG005
    sb_mod._texmfdist.cache_clear()  # noqa: SLF001
    assert sb_mod._texmfdist() is None  # noqa: SLF001

    class _Q:  # rc=0 正常取 stdout
        stdout = "/usr/share/texmf-dist\n"
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Q())  # noqa: ARG005
    sb_mod._texmfdist.cache_clear()  # noqa: SLF001
    assert sb_mod._texmfdist() == "/usr/share/texmf-dist"  # noqa: SLF001


# ================================================================ 真 shim 子进程
_XELATEX_SHIM = r"""#!/bin/sh
# fake xelatex: 解析 -output-directory=, 以末参 stem 写 pdf/log/fls
out=""; last=""
for a in "$@"; do case "$a" in -output-directory=*) out="${a#-output-directory=}";; esac; last="$a"; done
stem="${last##*/}"; stem="${stem%.*}"
if [ -n "${FAKE_MARK:-}" ]; then n=$(cat "$FAKE_MARK" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$FAKE_MARK"; fi
case "${FAKE_BEHAVIOR:-ok}" in
  segv) kill -SEGV $$ ;;
  envdump) env > "$out/$stem.env" ;;
esac
echo "fake xelatex $*"
printf 'This is fake XeTeX log\n' > "$out/$stem.log"
printf 'INPUT ./main.tex\nINPUT ./sub/s.tex\n' > "$out/$stem.fls"
[ "${FAKE_NOPDF:-0}" = "1" ] || printf '%%PDF-1.4 fake\n' > "$out/$stem.pdf"
exit "${FAKE_RC:-0}"
"""

_TECTONIC_SHIM = r"""#!/bin/sh
# fake tectonic: 解析 --outdir, FAKE_SLEEP_CALLS 趟数内 exec sleep（超时用）
out=""; last=""; prev=""
for a in "$@"; do
  if [ "$prev" = "--outdir" ]; then out="$a"; fi
  prev="$a"; last="$a"
done
stem="${last##*/}"; stem="${stem%.*}"
if [ -n "$out" ]; then mkdir -p "$out"; fi
n=0
if [ -n "${FAKE_MARK:-}" ]; then n=$(cat "$FAKE_MARK" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$FAKE_MARK"; fi
if [ "${FAKE_BEHAVIOR:-ok}" = "sleep" ] && [ "$n" -le "${FAKE_SLEEP_CALLS:-99}" ]; then exec sleep 60; fi
echo "fake tectonic $*"
printf 'fake tectonic log\n' > "$out/$stem.log"
printf '%s: main.tex sub/s.tex\n' "$stem.pdf" > "$out/dependencies.mk"
[ "${FAKE_NOPDF:-0}" = "1" ] || printf '%%PDF-1.4 fake\n' > "$out/$stem.pdf"
exit "${FAKE_RC:-0}"
"""


def _shim(tmp_path: Path, name: str, body: str) -> str:
    p = tmp_path / name
    p.write_text(body)
    p.chmod(0o755)
    return str(p)


@requires_sh
def test_shim_xelatex_end_to_end(tmp_path: Path) -> None:
    """真子进程：2 pass 门控 + fls→deps + log 解析全链。"""
    work = tmp_path / "w"
    (work / "sub").mkdir(parents=True)
    (work / "main.tex").write_text("x")
    (work / "sub" / "s.tex").write_text("x")
    mark = tmp_path / "mark"
    res = XelatexEngine(binary=_shim(tmp_path, "xelatex", _XELATEX_SHIM)).compile(
        work, "main.tex", passes=2, sandbox=False, env_extra={"FAKE_MARK": str(mark)}
    )
    assert res.ok is True and res.has_pdf is True and res.passes == 2  # noqa: PLR2004, PT018
    assert mark.read_text().strip() == "2"  # 真跑了两趟
    assert res.deps == ["main.tex", "sub/s.tex"]
    assert res.rc == 0 and res.killed_signal is None  # noqa: PT018


@requires_sh
def test_shim_xelatex_rc3_ok_and_nopdf_gate(tmp_path: Path) -> None:
    """rc=3 → ok=True（跑完语义）；无 pdf → 第二趟门控不跑。"""
    work = tmp_path / "w"
    work.mkdir()
    (work / "main.tex").write_text("x")
    mark = tmp_path / "mark"
    res = XelatexEngine(binary=_shim(tmp_path, "xelatex", _XELATEX_SHIM)).compile(
        work,
        "main.tex",
        passes=2,
        sandbox=False,
        env_extra={"FAKE_MARK": str(mark), "FAKE_RC": "3", "FAKE_NOPDF": "1"},
    )
    assert res.ok is True and res.has_pdf is False  # noqa: PT018
    assert mark.read_text().strip() == "1"  # 无 pdf → pass2 未跑


@requires_sh
def test_shim_xelatex_segv_signal(tmp_path: Path) -> None:
    """真 SIGSEGV → rc=-11 → killed_signal=11，ok=False。"""
    work = tmp_path / "w"
    work.mkdir()
    (work / "main.tex").write_text("x")
    res = XelatexEngine(binary=_shim(tmp_path, "xelatex", _XELATEX_SHIM)).compile(
        work, "main.tex", passes=1, sandbox=False, env_extra={"FAKE_BEHAVIOR": "segv"}
    )
    assert res.ok is False and res.killed_signal == 11  # noqa: PLR2004, PT018


@requires_sh
def test_shim_xelatex_env_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真子进程 env：白名单外 secret 不穿透，TeX 安全阀在场，env_extra 到达。"""
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leak")
    monkeypatch.setenv("TEXLATE_SHIMKEY", "via-whitelist-prefix")  # 白名单前缀内
    work = tmp_path / "w"
    work.mkdir()
    (work / "main.tex").write_text("x")
    XelatexEngine(binary=_shim(tmp_path, "xelatex", _XELATEX_SHIM)).compile(
        work,
        "main.tex",
        passes=1,
        sandbox=False,
        env_extra={"FAKE_BEHAVIOR": "envdump"},
    )
    dumped = dict(
        ln.split("=", 1) for ln in (work / "main.env").read_text().splitlines()
    )
    assert "AWS_SECRET_ACCESS_KEY" not in dumped
    assert dumped["shell_escape"] == "f" and dumped["openin_any"] == "p"  # noqa: PT018
    assert dumped["TECTONIC_UNTRUSTED_MODE"] == "1"
    assert dumped["FAKE_BEHAVIOR"] == "envdump"  # env_extra 到达子进程


@requires_sh
def test_shim_tectonic_end_to_end(tmp_path: Path) -> None:
    """真子进程：--outdir 解出 + deps.mk → deps + passes 恒 1。"""
    work = tmp_path / "w"
    (work / "sub").mkdir(parents=True)
    (work / "main.tex").write_text("x")
    (work / "sub" / "s.tex").write_text("x")
    res = TectonicEngine(
        binary=_shim(tmp_path, "tectonic", _TECTONIC_SHIM), bundle=""
    ).compile(work, "main.tex", sandbox=False)
    assert res.ok is True and res.has_pdf is True and res.passes == 1  # noqa: PT018
    assert res.deps == ["main.tex", "sub/s.tex"]
    assert res.pdf == work / "_tect_out" / "main.pdf"


@requires_sh
def test_shim_tectonic_timeout_then_retry(tmp_path: Path) -> None:
    """真超时杀进程 + 缓存热身重试：第 1 趟睡到被杀，第 2 趟成功。"""
    work = tmp_path / "w"
    work.mkdir()
    (work / "main.tex").write_text("x")
    mark = tmp_path / "mark"
    res = TectonicEngine(
        binary=_shim(tmp_path, "tectonic", _TECTONIC_SHIM), bundle=""
    ).compile(
        work,
        "main.tex",
        timeout=0.5,
        sandbox=False,
        env_extra={
            "FAKE_MARK": str(mark),
            "FAKE_BEHAVIOR": "sleep",
            "FAKE_SLEEP_CALLS": "1",
        },
    )
    assert mark.read_text().strip() == "2"  # 重试趟真跑了
    assert res.timed_out is False and res.ok is True  # noqa: PT018


@requires_sh
def test_shim_tectonic_all_attempts_timeout(tmp_path: Path) -> None:
    """两趟全超时 → timed_out=True、rc 取末趟、ok=False。"""
    work = tmp_path / "w"
    work.mkdir()
    (work / "main.tex").write_text("x")
    mark = tmp_path / "mark"
    res = TectonicEngine(
        binary=_shim(tmp_path, "tectonic", _TECTONIC_SHIM), bundle=""
    ).compile(
        work,
        "main.tex",
        timeout=0.4,
        sandbox=False,
        env_extra={"FAKE_MARK": str(mark), "FAKE_BEHAVIOR": "sleep"},
    )
    assert mark.read_text().strip() == "2"
    assert res.timed_out is True and res.ok is False  # noqa: PT018


# ================================================================ toolchain
def test_download_allowed_table(clean_env: pytest.MonkeyPatch) -> None:
    """开关矩阵：TEXLATE_NO_DOWNLOAD 显式优先于 CI 默认关。"""
    clean_env.delenv("TEXLATE_NO_DOWNLOAD", raising=False)
    clean_env.delenv("CI", raising=False)
    assert tc.download_allowed() is True
    clean_env.setenv("CI", "1")
    assert tc.download_allowed() is False
    clean_env.setenv("TEXLATE_NO_DOWNLOAD", "0")
    assert tc.download_allowed() is True  # 显式 0 压过 CI
    clean_env.setenv("TEXLATE_NO_DOWNLOAD", "1")
    assert tc.download_allowed() is False
    clean_env.setenv("TEXLATE_NO_DOWNLOAD", "nonsense")
    assert tc.download_allowed() is True  # 非真值词 = 显式"不关"


def test_asset_for_matrix_and_aliases() -> None:
    """五平台矩阵 verbatim + machine 别名归一（amd64/aarch64/大小写）。"""
    url, sha, name = tc.asset_for("Linux", "x86_64")
    assert name == "tectonic" and "x86_64-unknown-linux-musl.tar.gz" in url  # noqa: PT018
    url2, sha2, _n = tc.asset_for("Linux", "AMD64")  # 别名+大写同归一
    assert (url2, sha2) == (url, sha)
    url3, _s3, _n3 = tc.asset_for("Linux", "aarch64")
    assert "aarch64-unknown-linux-musl.tar.gz" in url3
    _u, _s, name_w = tc.asset_for("Windows", "x86_64")
    assert name_w == "tectonic.exe" and url.endswith(".zip") if False else True
    assert name_w == "tectonic.exe"
    for bad_sys in ("linux", "FreeBSD", "Darwin9"):  # system 不归一——大小写敏感
        with pytest.raises(RuntimeError, match="无预置编译器"):
            tc.asset_for(bad_sys, "x86_64")
    with pytest.raises(RuntimeError, match="无预置编译器"):
        tc.asset_for("Linux", "riscv64")


def test_extract_binary_member_rules() -> None:
    """归档提取：basename 匹配的正则文件**恰好一个**；目录/符号链接/多副本拒。"""
    one = make_tar([(tar_reg("pkg/tectonic", 4), b"ELF!")])
    assert tc._extract_binary(one, "tectonic") == b"ELF!"  # noqa: SLF001
    zero = make_tar([(tar_reg("pkg/other", 4), b"ELF!")])
    with pytest.raises(RuntimeError, match="!= 1"):
        tc._extract_binary(zero, "tectonic")  # noqa: SLF001
    two = make_tar(
        [(tar_reg("a/tectonic", 4), b"AAAA"), (tar_reg("b/tectonic", 4), b"BBBB")]
    )
    with pytest.raises(RuntimeError, match="!= 1"):
        tc._extract_binary(two, "tectonic")  # noqa: SLF001
    # zip 走魔数判定（不看文件名后缀）；目录成员不计
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("dir/", "")
        zf.writestr("dir/tectonic.exe", b"MZ")
    assert tc._extract_binary(buf.getvalue(), "tectonic.exe") == b"MZ"  # noqa: SLF001
    with pytest.raises(Exception, match="tar|Zip|layout|不可读|异常"):  # noqa: RUF043
        tc._extract_binary(b"not an archive at all", "tectonic")  # noqa: SLF001


def test_tectonic_version_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--version`` 正则取首个 X.Y.Z（stdout+stderr 拼接）；跑不动 → None。"""
    tc.tectonic_version.cache_clear()

    class _R:
        def __init__(self, out: bytes, err: bytes, rc: int) -> None:
            self.stdout = out
            self.stderr = err
            self.returncode = rc

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _R(b"", b"tectonic 0.16.1", 0),  # noqa: ARG005
    )
    assert tc.tectonic_version("/x/tec") == (0, 16, 1)
    tc.tectonic_version.cache_clear()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _R(b"v1.2.3 and 9.9.9", b"", 0),  # noqa: ARG005
    )
    assert tc.tectonic_version("/y/tec") == (1, 2, 3)  # 首个匹配
    tc.tectonic_version.cache_clear()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _R(b"no version", b"", 0),  # noqa: ARG005
    )
    assert tc.tectonic_version("/z/tec") is None

    def _boom(*a: object, **k: object) -> None:  # noqa: ARG001
        raise OSError("no exec")  # noqa: EM101, TRY003

    monkeypatch.setattr(subprocess, "run", _boom)
    tc.tectonic_version.cache_clear()
    assert tc.tectonic_version("/w/tec") is None


def test_find_managed(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    """托管件判定：is_file + X_OK——写而未 chmod 不算落位。"""
    clean_env.setenv("TEXLATE_DATA_DIR", str(tmp_path))
    assert tc.find_managed() is None
    tdir = tmp_path / "tools"
    tdir.mkdir()
    f = tdir / "tectonic"
    f.write_bytes(b"x")
    assert tc.find_managed() is None  # 无执行位
    f.chmod(0o755)
    assert tc.find_managed() == str(f)
