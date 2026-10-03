r"""flatten 边界契约钉（L4 车道）：W19/W51/W73/W104/B03 五机制。

- W73 ``openin_any`` 等价闸：候选 real path 须落根集（file_dir/root_dir/
  top_dir）内——``..``/绝对路径/根内 symlink 指出界一律 miss + 告警
  （与 v2 ``gullet/input.py`` ``_resolve_input`` 同口径）。
- W19 dist 依赖：``\input{amssym.def}`` 等发行版文件不在 tarball → 字面
  透传 + ``missing_input``——编译期由 texmf-dist 解析（0806.1728
  compile:clean 实证），不改写 ``\usepackage``。
- W51 显式非 .tex 扩展名：``\input{Definition.def}``/``{contr.latex}``
  原样命中（2203.13060/1003.1550 实证）；裸名不补 ``.ltx/.latex``——
  TeX 引擎亦不补，语料零案例（对齐 TeX 语义而非 locate 枚举口径）。
- W104 ``\openin/\ifeof`` 守卫的 ``\input``：宏参/计算式文件名静态不可
  判定 → 字面透传不瞎猜、不告警（1012.1032 ``\input#1`` 实证）。
- B03 深度/广度压力面：深度 ≥3 链与单层 ≥10 扇出全落地，深度闸边界明确。
"""

from pathlib import Path
from typing import TYPE_CHECKING

from conftest import write_tex as _w

from texlate.latex.flatten import _resolve, flatten_inputs
from texlate.latex.tables import MAX_INPUTS

if TYPE_CHECKING:
    from texlate.latex.model import ScanWarning

_DEEP = 5  # 深链钉的层数（≥3 即 B03 深度面）


class TestEscapeGate:
    """W73：根集闸——出界候选按 miss（字面透传 + ``missing_input``）。"""

    def test_dotdot_outside_root_miss(self, tmp_path: Path) -> None:
        r"""``\input{../outside/secret}`` 指向根外 → 不内联 + 告警。"""
        root = tmp_path / "root"
        root.mkdir(parents=True)
        _w(tmp_path / "outside", "secret.tex", "SECRET-ESC")
        warns: list[ScanWarning] = []
        out = flatten_inputs(
            "\\input{../outside/secret}", str(root), str(root), warnings=warns
        )
        assert "SECRET-ESC" not in out
        assert "\\input{../outside/secret}" in out
        assert any(w.kind == "missing_input" for w in warns)

    def test_abs_path_outside_miss(self, tmp_path: Path) -> None:
        r"""根外绝对路径候选 → miss（``/etc`` 类读本机文件面）。"""
        root = tmp_path / "root"
        root.mkdir(parents=True)
        secret = _w(tmp_path / "outside", "secret.tex", "SECRET-ABS")
        warns: list[ScanWarning] = []
        out = flatten_inputs(
            # win32 str(Path) 出 '\' —— TeX 面 \input 参数是 / 语法
            f"\\input{{{secret.as_posix()}}}",
            str(root),
            str(root),
            warnings=warns,
        )
        assert "SECRET-ABS" not in out
        assert any(w.kind == "missing_input" for w in warns)

    def test_abs_path_inside_root_hits(self, tmp_path: Path) -> None:
        r"""根内绝对路径合法——闸只判界不拒形态。"""
        root = tmp_path / "root"
        inner = _w(root, "sub/deep.tex", "INNER-ABS")
        out = flatten_inputs(f"\\input{{{inner.as_posix()}}}", str(root), str(root))
        assert "INNER-ABS" in out

    def test_symlink_out_miss(self, tmp_path: Path) -> None:
        r"""根内 symlink 指出界 → miss（real path 判界）。"""
        root = tmp_path / "root"
        root.mkdir(parents=True)
        _w(tmp_path / "outside", "secret.tex", "SECRET-LINK")
        (root / "linkout.tex").symlink_to(tmp_path / "outside" / "secret.tex")
        warns: list[ScanWarning] = []
        out = flatten_inputs("\\input{linkout}", str(root), str(root), warnings=warns)
        assert "SECRET-LINK" not in out
        assert "\\input{linkout}" in out
        assert any(w.kind == "missing_input" for w in warns)

    def test_symlink_inside_hits(self, tmp_path: Path) -> None:
        r"""根内 symlink 指根内 → 正常内联。"""
        root = tmp_path / "root"
        _w(root, "real.tex", "REAL-TARGET")
        (root / "alias.tex").symlink_to(root / "real.tex")
        out = flatten_inputs("\\input{alias}", str(root), str(root))
        assert "REAL-TARGET" in out

    def test_import_dotdot_miss(self, tmp_path: Path) -> None:
        r"""``\import{../outside}{secret}`` 前缀拼接逃逸同闸。"""
        root = tmp_path / "root"
        root.mkdir(parents=True)
        _w(tmp_path / "outside", "secret.tex", "SECRET-IMPORT")
        warns: list[ScanWarning] = []
        out = flatten_inputs(
            "\\import{../outside}{secret}", str(root), str(root), warnings=warns
        )
        assert "SECRET-IMPORT" not in out
        assert any(w.kind == "missing_input" for w in warns)

    def test_dotdot_within_topdir_hits(self, tmp_path: Path) -> None:
        r"""界内 ``../`` 合法：e-print 内跨目录引用（cond-mat/0501221 拓扑）。

        ``paper/macros.tex`` 内 ``\input{../BiblioMacros/x}``——相对 file_dir
        出界但落在 ``top_dir``（e-print 根）内 → 正常内联。
        """
        paper = tmp_path / "paper"
        _w(paper / "BiblioMacros", "x.tex", "SIBLING-CONTENT")
        sub = paper / "sub"
        sub.mkdir(parents=True)  # including 文件目录须在（OS 遍历 ../ 前提）
        warns: list[ScanWarning] = []
        out = flatten_inputs(
            "\\input{../BiblioMacros/x}",
            str(sub),
            str(sub),
            warnings=warns,
            top_dir=str(paper),
        )
        assert "SIBLING-CONTENT" in out
        assert not warns

    def test_empty_dirs_no_cwd_leak(self, tmp_path: Path) -> None:
        r"""空串 dir 不作根——``Path("")`` 按 cwd 解析同属泄漏面。"""
        probe = tmp_path / "probe.tex"
        probe.write_text("PROBE", encoding="utf-8")
        assert _resolve("probe", "", "") is None
        assert _resolve("probe", "", "", top_dir="") is None
        # 真根在场时空串 dir 不顶替 cwd 之外的查找序
        hit = _resolve("probe", "", str(tmp_path))
        assert hit is not None
        assert Path(hit).resolve() == probe.resolve()

    def test_resolve_returns_inroot_form(self, tmp_path: Path) -> None:
        r"""界内 ``..`` 非逃逸（``sub/../x``）→ 命中，返回原形态串。"""
        root = tmp_path / "root"
        _w(root, "x.tex", "XMARK")
        (root / "sub").mkdir(parents=True)
        hit = _resolve("sub/../x", str(root), str(root))
        assert hit is not None
        assert Path(hit).resolve() == (root / "x.tex").resolve()


class TestDistInputPassthrough:
    r"""W19：发行版文件 ``\input`` 不在 tarball → 字面透传留引擎解析。"""

    def test_brace_dist_file_literal(self, tmp_path: Path) -> None:
        r"""``\input{amssym.def}``/``{amssym.tex}`` 缺席 → 原文保留 + 告警。"""
        warns: list[ScanWarning] = []
        out = flatten_inputs(
            "\\input{amssym.def}\n\\input{amssym.tex}",
            str(tmp_path),
            str(tmp_path),
            warnings=warns,
        )
        assert "\\input{amssym.def}" in out
        assert "\\input{amssym.tex}" in out
        assert len([w for w in warns if w.kind == "missing_input"]) == 2  # noqa: PLR2004 -- 两枚 dist input 各一记

    def test_bare_dist_file_literal(self, tmp_path: Path) -> None:
        r"""``\input epsf`` 裸名形（1003.2039）缺席 → 原文保留。"""
        warns: list[ScanWarning] = []
        out = flatten_inputs("\\input epsf\nBODY", str(tmp_path), warnings=warns)
        assert "\\input epsf" in out
        assert "BODY" in out
        assert any(w.kind == "missing_input" for w in warns)

    def test_dist_dep_inside_inlined_tex(self, tmp_path: Path) -> None:
        r"""vendored .tex 内部的 dist 依赖（0707.4206 ``pstricks.con`` 拓扑）。

        ``pstricks.tex`` 在 tarball 正常内联；其内 ``\input pstricks.con``
        缺席 → 字面透传（编译期 texmf-dist 兜底）。
        """
        _w(tmp_path, "pstricks.tex", "PSTRICKS-BODY\n\\input pstricks.con\nTAIL")
        warns: list[ScanWarning] = []
        out = flatten_inputs("\\input{pstricks}", str(tmp_path), warnings=warns)
        assert "PSTRICKS-BODY" in out
        assert "\\input pstricks.con" in out
        assert any(
            w.kind == "missing_input" and "pstricks.con" in w.detail for w in warns
        )


class TestExplicitNonTexExt:
    """W51：显式非 .tex 扩展名原样命中；裸名不补 ``.ltx/.latex``。"""

    def test_def_ext_inline(self, tmp_path: Path) -> None:
        r"""``\input{Definition.def}``（2203.13060）→ 内联。"""
        _w(tmp_path, "Definition.def", "DEF-CONTENT")
        out = flatten_inputs("\\input{Definition.def}", str(tmp_path))
        assert "DEF-CONTENT" in out

    def test_latex_ext_inline(self, tmp_path: Path) -> None:
        r"""``\input{contr.latex}``（1003.1550）→ 内联。"""
        _w(tmp_path, "contr.latex", "LATEX-EXT-CONTENT")
        out = flatten_inputs("\\input{contr.latex}", str(tmp_path))
        assert "LATEX-EXT-CONTENT" in out

    def test_sty_ext_inline(self, tmp_path: Path) -> None:
        r"""``\input{epsf.sty}`` 显式 .sty → 在 tarball 即内联。"""
        _w(tmp_path, "epsf.sty", "EPSF-STY")
        out = flatten_inputs("\\input{epsf.sty}", str(tmp_path))
        assert "EPSF-STY" in out

    def test_bare_name_no_ltx_completion(self, tmp_path: Path) -> None:
        r"""裸名 ``\input{contr}`` 只有 ``contr.latex`` → 不补全（TeX 同语义）。

        引擎对无扩展名 ``\input`` 只追加 ``.tex``——补 ``.ltx/.latex`` 会
        偏离引擎真实行为；corpus 全量零裸名→.ltx 案例实证无需此面。
        """
        _w(tmp_path, "contr.latex", "NO-LTX-COMPLETION")
        warns: list[ScanWarning] = []
        out = flatten_inputs("\\input{contr}", str(tmp_path), warnings=warns)
        assert "NO-LTX-COMPLETION" not in out
        assert "\\input{contr}" in out
        assert any(w.kind == "missing_input" for w in warns)


class TestIfeofConditional:
    r"""W104：``\openin/\ifeof`` 守卫的 ``\input`` 静态不可判定 → 诚实降级。"""

    def test_openin_ifeof_macro_arg_passthrough(self, tmp_path: Path) -> None:
        r"""1012.1032 原型：``\input#1`` 宏参名 → 宏定义完整透传零告警。"""
        src = (
            "\\def\\maybeinput#1{\n"
            "\\openin\\testin=#1\n"
            "\\ifeof\\testin\\typeout{Warning: input #1 not found}"
            "\\else\\input#1\\fi\\closein\\testin}\n"
        )
        warns: list[ScanWarning] = []
        out = flatten_inputs(src, str(tmp_path), str(tmp_path), warnings=warns)
        assert out == src  # 宏定义逐字节透传——运行时由引擎判存否
        assert not warns

    def test_cs_fname_silent(self, tmp_path: Path) -> None:
        r"""``\input{\jobname}`` 计算式名 → 透传不告警（v2 ``_do_input`` 同点滤）。"""
        warns: list[ScanWarning] = []
        out = flatten_inputs(
            "\\input{\\jobname} tail", str(tmp_path), str(tmp_path), warnings=warns
        )
        assert "\\input{\\jobname}" in out
        assert not warns

    def test_ifeof_literal_name_resolves(self, tmp_path: Path) -> None:
        r"""``\ifeof`` 包裹的字面名 ``\input``：文件在 → 内联，条件壳保留。"""
        _w(tmp_path, "realfile.tex", "IFEOF-REAL")
        src = "\\ifeof\\testin T\\else\\input realfile \\fi"
        out = flatten_inputs(src, str(tmp_path), str(tmp_path))
        assert "IFEOF-REAL" in out
        assert "\\ifeof" in out  # 条件壳逐字留——语义交引擎
        assert "\\fi" in out


class TestDepthBreadth:
    """B03：深度 ≥3 链 / 单层 ≥10 扇出 / ``MAX_INPUTS`` 闸边界。"""

    def test_deep_chain_lands(self, tmp_path: Path) -> None:
        r"""深度 5 链全部落地。"""
        for j in range(_DEEP):
            nxt = f"\\input{{f{j + 1}}}" if j + 1 < _DEEP else ""
            _w(tmp_path, f"f{j}.tex", f"C{j} {nxt} E{j}")
        out = flatten_inputs("\\input{f0}", str(tmp_path), str(tmp_path))
        for j in range(_DEEP):
            assert f"C{j}" in out

    def test_wide_fanout_lands(self, tmp_path: Path) -> None:
        r"""单层 12 扇出全部落地（n_tex ≥10 面）。"""
        for j in range(12):
            _w(tmp_path, f"w{j}.tex", f"W{j}")
        src = "\n".join(f"\\input{{w{j}}}" for j in range(12))
        out = flatten_inputs(src, str(tmp_path), str(tmp_path))
        for j in range(12):
            assert f"W{j}" in out

    def test_depth_gate_boundary(self, tmp_path: Path) -> None:
        r"""深度闸边界：``MAX_INPUTS+1`` 层内容裸落地，更深层不进流。

        第 ``MAX_INPUTS+1`` 层文件内容照常内联但其内 ``\input`` 不再展开
        （``depth > MAX_INPUTS`` 层原文返回）。
        """
        chain = MAX_INPUTS + 3
        for j in range(chain):
            nxt = f"\\input{{f{j + 1}}}" if j + 1 < chain else ""
            _w(tmp_path, f"f{j}.tex", f"C{j} {nxt}")
        out = flatten_inputs("\\input{f0}", str(tmp_path), str(tmp_path))
        for j in range(MAX_INPUTS + 1):
            assert f"C{j}" in out
        for j in range(MAX_INPUTS + 1, chain):
            assert f"C{j}" not in out
        # 被拒层的 \input 字面留流——边界可见性
        assert f"\\input{{f{MAX_INPUTS + 1}}}" in out
