r"""``\input`` 多文件闭包 fuzz——``_resolve_input`` 候选序/出界闸 + ``_seen`` 祖先栈 + 深度闸。

契约基线（``src/texlate/latex/gullet/input.py`` + ``core.py`` 源栈账）：

- 解析序：including 目录（``file_dir``，含 ``\input`` token 所在文件的父目录）
  → ``root_dir`` → ``top_dir``；候选 real path 必须落在已解析根集内
  （openin_any 等价闸——``..``/绝对路径/根内 symlink 指出界一律按 miss）。
- 扩展名序：``fname`` 无扩展名 → 各根 ``.tex``/``.TEX``/裸名序补全，
  再各根 basename+``.tex``/``.TEX``（basename 回退会把 ``nodir/foo``
  抬到 ``root/foo.tex``）；带显式扩展名原样不追加。
- ``_seen`` 祖先栈：``push_source`` 压、``read()``/``\endinput`` 弹栈撤——
  环（A→B→A/自环）**静默**断（``_seen`` 命中不记 ``missing_input``），
  兄弟位重包含放行（同文件可被重复包含）。
- 深度闸：``len(inputs) > MAX_INPUTS(=8)`` 拒压栈 → ``missing_input``
  detail 含 ``depth>8:<fname>`` + 本体回吐；实测截断 = 嵌套第 9 层拒绝。
- 文件名为空/含 ``\``（计算式）→ 回吐走普通流不告警；缺件 →
  ``missing_input`` + 本体逐字回吐；命中目录 → ``read_bytes`` OSError
  → ``missing_input``；``\include`` 无 ``{}`` 组 → 静默回吐。
- 内存源（无路径）``file_dir`` 回落 ``root_dir``；根集全空 → 恒 miss。
- NUL 到不了本层——Mouth tokenize 期即丢（``\input{a<NUL>b}`` 实测读到
  ``ab``），直调 ``_resolve_input`` 的 soup 不收 NUL。

不变量断言：

- 有限步内返回：``_drive`` token 产出上界闸（超界即红，不靠 wallclock）。
- 确定性：同工程两趟 ``Gullet`` 展开投影（kind/text/pos + warnings）全等。
- 出界内容绝不进球：根外 secret + ``..``/abs/symlink 逃逸面全拒。
- ``input:`` marker 路径 ⊆ 根集且 ``is_file()``。
- 全存在边工程：``missing_input`` 只许 ``depth>`` 形（祖先断环静默）。

观察钉（pin observed——当前行为即取舍，定性留裁决）：

- ``\InputIfFileExists{f}{T}{E}`` 命中时 ``{T}{E}`` 两**组**都留在流面
  （无选支语义）；miss 时整个调用形逐字回吐 + ``missing_input``。
- basename 回退静默抬升（``nodir/foo`` → ``root/foo.tex``）。
- 环断静默 vs 缺件告警——观测性不对称（祖先断环无 warning 可查）。
- 根内 fifo/设备文件：``exists()`` 闸不查 ``is_file()`` → ``read_bytes``
  悬挂面；e-print 路径不可达（unpack ``isreg()`` 已滤），仅本地手造工程
  边角——不入钉，台账记档。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from _fuzzkit import (
    assert_deterministic,
    fuzz_rng,
    short,
    soup_join,
    soup_pick,
    write_findings,
)
from conftest import text_of

from texlate.latex.gullet import Gullet
from texlate.latex.tables import MAX_INPUTS

if TYPE_CHECKING:
    import random

    from texlate.latex.mouth import Tok

# ---------------------------------------------------------------- 常量与 soup

_FUZZ_ITERS_FS = 80  # 文件系统重构面——每迭代真落盘，量低于纯内存 fuzz
_FUZZ_ITERS_MED = 40
_TOKEN_CAP = 60_000  # 有限步闸：深度≤9 × 宽≤2 的工程展开远低于此
_SEED_RESOLVE = 2026091801
_SEED_PROJECT = 2026091802
_SEED_ALL_EXIST = 2026091803
_SEED_DEPTH = 2026091804
_SEED_SIBLING = 2026091805
_SEED_FORMS = 2026091806
_SEED_FNAME = 2026091807
_SEED_DET = 2026091808

#: 概率档常量（PLR2004 免 noqa 集中点）。
_P_ABS_IN_ROOT = 0.15  # fname 取根内绝对路径的概率位
_P_ABS_OUTSIDE = 0.22  # fname 取根外真实路径的概率位（roll < 此值且 ≥ 上档）
_P_FS_ENTRY = 0.5  # 每条 _FSYS_ENTRIES 落盘概率
_P_SYMLINK = 0.3  # 根内 symlink 出界/指内各一枚的概率

#: 文件系统条目汤——平名/子目录/大小写扩展名/裸名/带空格/点前缀/双扩展名。
#: ``x``+``x.tex``+``x.TEX`` 共存钉扩展名序；``sub`` 既是目录又是 stem。
_FSYS_ENTRIES = [
    "x.tex",
    "x.TEX",
    "x",
    "x.sty",
    "x.tex.tex",
    "y.tex",
    "z.TEX",
    "bare",
    "sub/y.tex",
    "sub/x.tex",
    "sub/deep/z.tex",
    "sp ace/s f.tex",
    "we-ird_.tex",
    ".hidden.tex",
    "up/UP.tex",
    "2.1_stem.tex",
    "sub/1.1_deep.tex",
]

#: ``\input`` 目标名汤——命中形/缺件/根内 ``..`` 穿越/出界 ``..``/怪名。
_FNAME_SOUP = [
    "x",
    "x.tex",
    "x.sty",
    "x.TEX",
    "y",
    "z",
    "bare",
    "sub/y",
    "sub/y.tex",
    "sub/x",
    "sub/deep/z",
    "sub/../x",
    "./x",
    "sp ace/s f",
    "we-ird_",
    ".hidden",
    "up/UP",
    "2.1_stem",
    "sub/1.1_deep",
    "missing",
    "nope.tex",
    "sub/missing",
    "nodir/x",
    "..",
    ".",
    "../escape",
    "../../escape",
    "a b c",
    "sub//x",
    "x\\y",  # 反斜杠是 posix 合法文件名字符——_do_input 层过滤，直调可达
]


# ---------------------------------------------------------------- 小件


def _drive(g: Gullet, cap: int = _TOKEN_CAP) -> list[Tok]:
    """有限步闸：抽干展开流；产出 token 超 ``cap`` 即判死循环/展开炸弹。"""
    out: list[Tok] = []
    while (t := g.next_expanded()) is not None:
        out.append(t)
        assert len(out) <= cap, f"unbounded expansion: >{cap} tokens"
    return out


def _proj(ts: list[Tok], g: Gullet) -> tuple:
    """确定性投影——token 三元组流 + warning 三元组流。"""
    return (
        tuple((t.kind, t.text, t.pos) for t in ts),
        tuple((w.kind, w.pos, w.detail) for w in g.warnings),
    )


def _expand(src: str, root: Path, top: Path | None = None) -> tuple:
    """``Gullet(src, root_dir, top_dir)`` → 有限步展开 → 投影。"""
    g = Gullet(src, root_dir=str(root), top_dir=str(top) if top else "")
    return _proj(_drive(g), g)


def _mkfile(path: Path, text: str) -> None:
    """建父目录 + 写文件（内容唯一 marker = 路径本身，断言进球即认）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _live_roots(file_dir: str, root_dir: str, top_dir: str) -> list[Path]:
    """契约根集：三级目录 resolve 去重（空串/不可 resolve 出局）。"""
    roots: list[Path] = []
    for d in (file_dir, root_dir, top_dir):
        if not d:
            continue
        try:
            r = Path(d).resolve()
        except (OSError, RuntimeError):
            continue
        if r not in roots:
            roots.append(r)
    return roots


def _oracle_resolve(
    fname: str, file_dir: str, root_dir: str, top_dir: str
) -> str | None:
    """``_resolve_input`` 规格直译 oracle——阶段序与命中闸逐条对契约。

    候选序：各根 × 名组（无 ``.tex`` 尾补 ``.tex``/``.TEX``/裸名；
    有 ``.tex`` 尾原样——词干点号不算扩展名，``2.1_x`` 族照补）
    → 各根 × basename+``.tex``/``.TEX``；首个 real path 存在且落根集内者胜。
    """
    roots = _live_roots(file_dir, root_dir, top_dir)
    names = (
        [fname]
        if fname.lower().endswith(".tex")
        else [fname + ".tex", fname + ".TEX", fname]
    )
    stem = Path(fname).name
    paths = [r / n for r in roots for n in names]
    paths += [r / (stem + ext) for r in roots for ext in (".tex", ".TEX")]
    for p in paths:
        try:
            rp = p.resolve()
        except (OSError, RuntimeError):
            continue
        if rp.exists() and any(rp.is_relative_to(r) for r in roots):
            return str(rp)
    return None


def _rand_fname(rng: random.Random, root: Path) -> str:
    """文件名汤 + 概率位：根内绝对路径/根外真实存在路径注入。"""
    roll = rng.random()
    if roll < _P_ABS_IN_ROOT:
        return str(root / soup_pick(rng, ["x.tex", "sub/y.tex", "missing.tex"]))
    if roll < _P_ABS_OUTSIDE:
        return soup_pick(rng, ["/etc/hostname", "/etc/passwd", str(Path.home())])
    return soup_pick(rng, _FNAME_SOUP)


def _build_fs(rng: random.Random, root: Path, top: Path, elsewhere: Path) -> None:
    """随机文件系统：root/top 各落 ``_FSYS_ENTRIES`` 随机子集 + 根外 secret。"""
    for base in (root, top):
        for rel in _FSYS_ENTRIES:
            if rng.random() < _P_FS_ENTRY:
                _mkfile(base / rel, f"F<{base.name}/{rel}>")
    _mkfile(elsewhere / "escape.tex", "SECRET-ESCAPE-CONTENT")
    _mkfile(elsewhere / "secret.tex", "SECRET-OUTSIDE")


def _rand_dir(rng: random.Random, *dirs: Path) -> str:
    """目录参汤：真目录/空串/不存在目录按权取。"""
    pool = [str(d) for d in dirs] + ["", str(dirs[0] / "nosuchdir")]
    return soup_pick(rng, pool)


def _input_markers(ts: list[Tok]) -> list[str]:
    """``input:``/``input_tag:`` consumed marker 中的解析后绝对路径。"""
    out: list[str] = []
    for t in ts:
        if t.kind != "consumed":
            continue
        if t.text.startswith("input:"):
            out.append(t.text[len("input:") :])
        elif t.text.startswith("input_tag:"):
            out.append(t.text.split(":", 2)[1])
    return out


def _rand_stmt(rng: random.Random, pool: list[str], *, safe: bool) -> str:
    """随机 ``\\input`` 族语句——形态 × 目标（汤表等权，重复条目即加权）。

    ``safe=True``（全存在边模式）只出恒可解析形态：平名 ``\\input`` 组/裸名
    与 ``\\include``——不出 ``../``/import/缺件名，保证 warning 只可能来自
    深度闸。
    """
    name = soup_pick(rng, pool)
    stem = Path(name).name
    if safe:
        return soup_pick(
            rng,
            [f"\\input {name} ", f"\\include{{{name}}}", f"\\input{{{name}}}"],
        )
    return soup_pick(
        rng,
        [
            f"\\input {name} ",  # 裸名形（FILENAME_CHARS 至空白）
            f"\\include{{{name}}}",
            f"\\import{{sub}}{{{stem}}}",
            f"\\subfile{{{name}}}",
            f"\\InputIfFileExists{{{name}}}{{T}}{{E}}",
            "\\endinput TAIL-DISCARDED",  # 本文件余下字节丢弃形
            f"\\input{{../{stem}}}",  # 根内/出界 .. 尝试
            f"\\input{{{name}}}",
        ],
    )


def _rand_project(rng: random.Random, root: Path, *, all_exist: bool) -> list[str]:
    """随机工程落盘：≤9 文件随机 ``\\input`` 边图。返回可用名池。

    ``all_exist=True`` 时 input 边只指向已落盘平名文件（环/自环允许）——
    供「missing_input 只许 depth> 形」不变量用。
    """
    n = rng.randint(2, 9)
    names = [f"f{i}" for i in range(n)]
    pool = list(names) if all_exist else [*names, "missing", "no/such", "../outside"]
    for name in names:
        body = f"C<{name}> " + soup_join(rng, ["w ", "more ", "txt "], 0, 4)
        for _ in range(rng.randint(0, 2)):
            body += _rand_stmt(rng, pool, safe=all_exist) + " "
        _mkfile(root / (name + ".tex"), body)
    return pool


# ---------------------------------------------------------------- _resolve_input 直调 fuzz


class TestResolveOracle:
    """``_resolve_input`` static 面——随机 fs × 敌意名，对规格 oracle + 出界闸。"""

    def test_fuzz_resolve_matches_oracle(self, tmp_path: Path) -> None:
        rng = fuzz_rng(_SEED_RESOLVE)
        for i in range(_FUZZ_ITERS_FS):
            base = tmp_path / f"r{i}"
            root, top, elsewhere = base / "root", base / "top", base / "out"
            _build_fs(rng, root, top, elsewhere)
            # 根内 symlink 出界/指内各半概率落一枚
            if rng.random() < _P_SYMLINK:
                (root / "linkout.tex").symlink_to(elsewhere / "secret.tex")
            if rng.random() < _P_SYMLINK:
                (root / "linkin.tex").symlink_to(root / "x.tex")
            fd = _rand_dir(rng, root, root / "sub", top)
            rd = _rand_dir(rng, root, top)
            td = _rand_dir(rng, top, root)
            fname = _rand_fname(rng, root)
            got = Gullet._resolve_input(fname, fd, rd, top_dir=td)  # noqa: SLF001 -- fuzz 钉的就是这个 static 契约面
            assert got == _oracle_resolve(fname, fd, rd, td), short((fname, fd, rd, td))
            # 直调确定性：同参两调同值
            assert (
                Gullet._resolve_input(fname, fd, rd, top_dir=td) == got  # noqa: SLF001
            )

    def test_fuzz_resolve_never_escapes_roots(self, tmp_path: Path) -> None:
        """出界闸独立断言：返回值非 None → 必落在某根内（不依赖 oracle 序）。"""
        rng = fuzz_rng(_SEED_RESOLVE + 1)
        for i in range(_FUZZ_ITERS_FS):
            base = tmp_path / f"e{i}"
            root, top, elsewhere = base / "root", base / "top", base / "out"
            _build_fs(rng, root, top, elsewhere)
            (root / "evil.tex").symlink_to(elsewhere / "secret.tex")
            fd = _rand_dir(rng, root, root / "sub")
            fname = soup_pick(
                rng,
                [
                    "../out/escape",
                    "../out/secret",
                    "../../etc/passwd",
                    "evil",
                    str(elsewhere / "escape.tex"),
                    str(elsewhere / "secret.tex"),
                    "/etc/passwd",
                    soup_pick(rng, _FNAME_SOUP),
                ],
            )
            hit = Gullet._resolve_input(fname, fd, str(root), top_dir=str(top))  # noqa: SLF001
            if hit is None:
                continue
            hp = Path(hit)
            assert hp.exists(), short((fname, hit))
            roots = _live_roots(fd, str(root), str(top))
            assert any(hp.is_relative_to(r) for r in roots), short((fname, hit))


# ---------------------------------------------------------------- 工程级 fuzz


def test_fuzz_random_graph_closure(tmp_path: Path) -> None:
    """随机有向图工程：链/环/自环/缺件/逃逸边混合——有限步 + 白名单 + 界内。"""
    rng = fuzz_rng(_SEED_PROJECT)
    for i in range(_FUZZ_ITERS_MED):
        root = tmp_path / f"g{i}"
        _mkfile(tmp_path / f"sec{i}" / "outside.tex", "SECRET-NEVER")
        pool = _rand_project(rng, root, all_exist=False)
        entry = soup_pick(rng, [*pool, "missing_entry"])
        g = Gullet(f"\\input{{{entry}}}", root_dir=str(root))
        ts = _drive(g)
        surf = text_of(ts)
        assert "SECRET-NEVER" not in surf, short(entry)
        for w in g.warnings:
            assert w.kind == "missing_input", short((entry, w.kind, w.detail))
        root_r = root.resolve()
        for m in _input_markers(ts):
            mp = Path(m)
            assert mp.is_file(), short((entry, m))
            assert mp.is_relative_to(root_r), short((entry, m))


def test_fuzz_all_edges_exist_only_depth_warns(tmp_path: Path) -> None:
    """全存在边（含环/自环/深链）：``missing_input`` 只许 ``depth>`` 形。

    祖先栈断环是静默的——凡是告警的 missing_input 只能是深度闸拒压。
    """
    rng = fuzz_rng(_SEED_ALL_EXIST)
    for i in range(_FUZZ_ITERS_MED):
        root = tmp_path / f"a{i}"
        pool = _rand_project(rng, root, all_exist=True)
        g = Gullet(f"\\input{{{soup_pick(rng, pool)}}}", root_dir=str(root))
        _drive(g)
        for w in g.warnings:
            assert w.kind == "missing_input", short(w.detail)
            assert "depth>" in w.detail, short(w.detail)


def test_fuzz_depth_gate_cutoff(tmp_path: Path) -> None:
    """链深 1..MAX_INPUTS+4：前 ``min(d, MAX_INPUTS)`` 层内容进流，越界留 literal。"""
    rng = fuzz_rng(_SEED_DEPTH)
    for i in range(_FUZZ_ITERS_MED):
        root = tmp_path / f"d{i}"
        depth = rng.randint(1, MAX_INPUTS + 4)
        for j in range(depth):
            nxt = f"\\input{{f{j + 1}}}" if j + 1 < depth else ""
            _mkfile(root / f"f{j}.tex", f"C{j} {nxt} E{j}")
        g = Gullet("\\input{f0}", root_dir=str(root))
        surf = text_of(_drive(g))
        landed = min(depth, MAX_INPUTS)
        for j in range(landed):
            assert f"C{j}" in surf, short((depth, j))
        for j in range(landed, depth):
            assert f"C{j}" not in surf, short((depth, j))
        warns = [w for w in g.warnings if w.kind == "missing_input"]
        if depth > MAX_INPUTS:
            assert any("depth>" in w.detail for w in warns), short(depth)
            assert f"\\input{{f{landed}}}" in surf  # 被拒层本体回吐逐字
        else:
            assert not warns, short((depth, [w.detail for w in warns]))


def test_fuzz_sibling_reinclude(tmp_path: Path) -> None:
    """兄弟位重包含：祖先栈弹撤后同文件可再进——出现次数精确等于引用数。"""
    rng = fuzz_rng(_SEED_SIBLING)
    for i in range(_FUZZ_ITERS_MED):
        root = tmp_path / f"s{i}"
        _mkfile(root / "c.tex", f"CHILD{i}X")
        k = rng.randint(1, 4)
        src = " mid ".join("\\input{c}" for _ in range(k))
        surf = text_of(_drive(Gullet(src, root_dir=str(root))))
        assert surf.count(f"CHILD{i}X") == k, short(src)
        # 双亲同包含：p/q 各 \input{c} → 兄弟位两侧各进一次
        _mkfile(root / "p.tex", "P \\input{c} P2")
        _mkfile(root / "q.tex", "Q \\input{c} Q2")
        surf2 = text_of(_drive(Gullet("\\input{p} \\input{q}", root_dir=str(root))))
        assert surf2.count(f"CHILD{i}X") == 2, short(surf2)  # noqa: PLR2004 -- p/q 双亲各进一次


def test_fuzz_input_forms_hit_miss(tmp_path: Path) -> None:
    r"""八形态 × 命中/缺件矩阵：``\input``/``\include``/``\import``/``\subimport``/
    ``\subfile``/``\includestandalone``/``\InputIfFileExists``/
    ``\CatchFileBetweenTags``。"""
    rng = fuzz_rng(_SEED_FORMS)
    for i in range(_FUZZ_ITERS_MED):
        root = tmp_path / f"m{i}"
        _mkfile(root / "hit.tex", f"HIT{i}")
        _mkfile(root / "sub" / "imp.tex", f"IMP{i}")
        _mkfile(
            root / "shell.tex",
            "\\documentclass{art}\n\\begin{document}\n"
            f"SHELL{i}\n\\end{{document}}\n",
        )
        _mkfile(
            root / "tags.tex",
            f"pre %<*tg>TAG{i}%</tg> post %<*other>NO{i}%</other>",
        )
        # (命中形，缺件/缺签对照形，命中 marker) 三元组——盲 replace 会伤命令名
        cases = [
            ("\\input{hit}", "\\input{nosuch}", f"HIT{i}"),
            ("\\input hit ", "\\input nosuch ", f"HIT{i}"),  # 裸名形
            ("\\include{hit}", "\\include{nosuch}", f"HIT{i}"),
            ("\\import{sub}{imp}", "\\import{sub}{nosuch}", f"IMP{i}"),
            ("\\subimport{sub}{imp}", "\\subimport{sub}{nosuch}", f"IMP{i}"),
            ("\\subfile{shell}", "\\subfile{nosuch}", f"SHELL{i}"),
            ("\\includestandalone{shell}", "\\includestandalone{nosuch}", f"SHELL{i}"),
            (
                "\\InputIfFileExists{hit}{T}{E}",
                "\\InputIfFileExists{nosuch}{T}{E}",
                f"HIT{i}",
            ),
            (
                "\\CatchFileBetweenTags\\cs{tags}{tg}",
                "\\CatchFileBetweenTags\\cs{nosuch}{tg}",  # 缺件
                f"TAG{i}",
            ),
            (
                "\\CatchFileBetweenTags\\cs{tags}{tg}",
                "\\CatchFileBetweenTags\\cs{tags}{notag}",  # 件存签缺
                f"TAG{i}",
            ),
        ]
        form, miss, expected = soup_pick(rng, cases)
        g = Gullet(form, root_dir=str(root))
        surf = text_of(_drive(g))
        assert expected in surf, short((form, surf))
        assert not any(w.kind == "missing_input" for w in g.warnings), short(form)
        g2 = Gullet(miss, root_dir=str(root))
        surf2 = text_of(_drive(g2))
        assert any(w.kind == "missing_input" for w in g2.warnings), short(miss)
        assert expected not in surf2


# ---------------------------------------------------------------- 文件名怪形 fuzz


def test_fuzz_filename_shapes(tmp_path: Path) -> None:
    r"""怪名边界：组内空格/连字符/点前缀/``..`` 根内穿越/多级点/双斜杠。

    组形 ``{…}`` 文件名面放宽（空格合法）；裸名形 ``FILENAME_CHARS`` 外字符
    截断——``\input a b`` 只读 ``a``。
    """
    rng = fuzz_rng(_SEED_FNAME)
    for i in range(_FUZZ_ITERS_MED):
        root = tmp_path / f"n{i}"
        shapes = {
            "a b.tex": f"SP{i}",
            "hy-phen_ok.tex": f"HY{i}",
            ".dotfile.tex": f"DT{i}",
            "multi.part.name.tex": f"MP{i}",
            "inner/sib.tex": f"SIB{i}",
            "inner/deep/down.tex": f"DN{i}",
        }
        for rel, marker in shapes.items():
            _mkfile(root / rel, marker)
        # 组形命中：oracle 说可解析 → marker 进球
        fname = soup_pick(rng, [*list(shapes), "inner/../a b", "inner//sib"])
        g = Gullet(f"\\input{{{fname}}}", root_dir=str(root))
        ts = _drive(g)
        surf = text_of(ts)
        want = _oracle_resolve(fname, str(root), str(root), str(root))
        if want is None:
            assert any(w.kind == "missing_input" for w in g.warnings), short(fname)
        else:
            hit_marker = shapes.get(str(Path(want).relative_to(root.resolve())), "")
            if hit_marker:
                assert hit_marker in surf, short((fname, surf))
        # 裸名截断面对照：``\input a b`` 只读 a——``a`` 无对应文件 → 缺件告警
        g2 = Gullet("\\input a b", root_dir=str(root))
        _drive(g2)
        assert any(w.kind == "missing_input" for w in g2.warnings), short(i)


# ---------------------------------------------------------------- 确定性 fuzz


def test_fuzz_deterministic(tmp_path: Path) -> None:
    """同工程两趟展开投影全等（含 warnings 序）。"""
    rng = fuzz_rng(_SEED_DET)
    for i in range(_FUZZ_ITERS_MED):
        root = tmp_path / f"dt{i}"
        pool = _rand_project(rng, root, all_exist=False)
        src = f"pre \\input{{{soup_pick(rng, pool)}}} post"
        assert_deterministic(lambda: _expand(src, root))  # noqa: B023 -- 闭包只吃 src/root 无循环依赖


# ---------------------------------------------------------------- 契约 corner 钉


class TestContractCorners:
    """fuzz 撒不到/需精确断的契约角——确定性钉（非迭代）。"""

    def test_chain_order_abc(self, tmp_path: Path) -> None:
        r"""``A→B→C`` 链序展开：内容按嵌套序进球。"""
        _mkfile(tmp_path / "a.tex", "AA \\input{b} A2")
        _mkfile(tmp_path / "b.tex", "BB \\input{c} B2")
        _mkfile(tmp_path / "c.tex", "CC")
        surf = text_of(_drive(Gullet("\\input{a}", root_dir=str(tmp_path))))
        assert surf.index("AA") < surf.index("BB") < surf.index("CC")
        assert surf.index("CC") < surf.index("B2") < surf.index("A2")

    def test_cycle_silent_no_warning(self, tmp_path: Path) -> None:
        r"""``A→B→A`` 祖先断环**静默**：``\input`` 逐字回吐，零 warning。"""
        _mkfile(tmp_path / "a.tex", "Aa \\input{b} a2")
        _mkfile(tmp_path / "b.tex", "Bb \\input{a} b2")
        g = Gullet("\\input{a}", root_dir=str(tmp_path))
        surf = text_of(_drive(g))
        assert "Bb" in surf
        assert "\\input{a}" in surf
        assert not g.warnings  # 断环不告警——与缺件路径不对称（观察钉）

    def test_main_self_input_silent(self, tmp_path: Path) -> None:
        r"""``push_source`` 带路径 → 主文件入 ``_seen``——``\input{main}`` 自环静默断。"""
        main = tmp_path / "main.tex"
        _mkfile(main, "M \\input{main} E")
        g = Gullet(root_dir=str(tmp_path))
        g.push_source(main.read_text(encoding="utf-8"), str(main))
        surf = text_of(_drive(g))
        assert "\\input{main}" in surf
        assert not g.warnings

    def test_dir_as_input_warns_missing(self, tmp_path: Path) -> None:
        r"""命中目录 → ``read_bytes`` OSError → ``missing_input`` + 本体回吐。"""
        (tmp_path / "adir").mkdir()
        g = Gullet("\\input{adir}", root_dir=str(tmp_path))
        surf = text_of(_drive(g))
        assert any(w.kind == "missing_input" for w in g.warnings)
        assert "\\input{adir}" in surf

    def test_cs_name_passthrough_silent(self, tmp_path: Path) -> None:
        r"""``\input{\jobname}`` 计算式名 → 静默回吐（不计 missing_input）。"""
        g = Gullet("\\input{\\jobname}", root_dir=str(tmp_path))
        surf = text_of(_drive(g))
        assert "\\input" in surf
        assert not g.warnings

    def test_empty_group_passthrough_silent(self, tmp_path: Path) -> None:
        r"""``\input{}`` 空名 → 静默回吐。"""
        g = Gullet("\\input{}", root_dir=str(tmp_path))
        assert "\\input{}" in text_of(_drive(g))
        assert not g.warnings

    def test_unclosed_group_passthrough_silent(self, tmp_path: Path) -> None:
        r"""``\input{a`` 流尽未闭 → ``ArgMismatch`` 回吐，静默。"""
        g = Gullet("\\input{a", root_dir=str(tmp_path))
        surf = text_of(_drive(g))
        assert "\\input" in surf
        assert not g.warnings

    def test_no_roots_always_miss(self) -> None:
        r"""内存源 + 全空根集 → 恒 miss：``missing_input`` + 本体回吐。"""
        g = Gullet("\\input{x}")
        surf = text_of(_drive(g))
        assert any(w.kind == "missing_input" for w in g.warnings)
        assert "\\input{x}" in surf

    def test_basename_lift_quirk(self, tmp_path: Path) -> None:
        r"""观察钉：``\input{nodir/foo}`` → basename 回退命中 ``root/foo.tex``。"""
        _mkfile(tmp_path / "foo.tex", "BASE-LIFT")
        g = Gullet("\\input{nodir/foo}", root_dir=str(tmp_path))
        surf = text_of(_drive(g))
        assert "BASE-LIFT" in surf
        assert not g.warnings

    def test_iife_groups_stay_in_stream(self, tmp_path: Path) -> None:
        r"""观察钉：``\InputIfFileExists`` 命中后 ``{then}{else}`` 双组留流面。"""
        _mkfile(tmp_path / "h.tex", "HH")
        g = Gullet("\\InputIfFileExists{h}{YES}{NO}", root_dir=str(tmp_path))
        surf = text_of(_drive(g))
        assert "HH" in surf
        assert "{YES}{NO}" in surf
        assert not g.warnings


# ---------------------------------------------------------------- findings 台账落盘


def test_write_findings_ledger() -> None:
    """台账写出——``tmp/input-closure-fuzz/findings.txt``。"""
    write_findings(
        Path("tmp/input-closure-fuzz/findings.txt"),
        title="input-closure-fuzz — \\input 多文件闭包台账",
        scope=(
            "gullet _resolve_input 候选序/openin_any 等价闸（file_dir→root→top，"
            "real path 落根集）/ _seen 祖先栈断环静默/ MAX_INPUTS=8 深度闸/"
            "八形态参数语法/怪名与逃逸面"
        ),
        test_file="tests/fuzz/test_fuzz_input_closure.py",
        status="0 CONFIRMED / 观察钉一簇（直调 oracle 全等 + 工程级不变量全绿）",
        observed=[
            (
                "\\InputIfFileExists 命中后 {then}{else} 双组留流面"
                "（无选支语义）；miss 时整个调用形逐字回吐 + missing_input"
            ),
            "basename 回退静默抬升：\\input{nodir/foo} → root/foo.tex",
            (
                "祖先栈断环静默（零 warning）vs 缺件告警 missing_input——"
                "观测性不对称，环点只能靠表面 \\input literal 识别"
            ),
            (
                "命中目录 → read_bytes OSError → missing_input（与缺件同"
                " kind，detail 无法区分目录/不存在）"
            ),
        ],
        notes=[
            (
                "NUL 文件名到不了 _resolve_input——Mouth tokenize 期即丢"
                "（\\input{a<NUL>b} 读到 ab）；直调 static 面 soup 不收 NUL。"
            ),
            (
                "根内 fifo/设备文件：_hit 只查 exists() 不查 is_file() → "
                "命中后 read_bytes 悬挂；e-print 路径不可达（unpack.py "
                "isreg() 已滤 fifo/device/symlink 成员），仅本地手造工程"
                "边角，不入钉。"
            ),
        ],
        scratch="tmp/input-closure-fuzz",
    )
