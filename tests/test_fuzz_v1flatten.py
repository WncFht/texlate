r"""v1 ``flatten_inputs``/``_resolve``/``parse_file_v1`` 多文件闭包 fuzz。

与 ``test_fuzz_input_closure``（v2 ``gullet/input.py`` 面）的分工：本文件钉
v1 臂自带的独立展平实现（``latex/flatten.py``——``TEXLATE_NO_EXPAND=1``
回退路径与 bench ``flatten_reach`` 消费的同一低层件）。``test_fuzz_v1arm``
撒的是 ``parse_tex_v1`` 内存态面，文件级闭包只有四个单点钉——本文件补
性质面。

契约基线（``src/texlate/latex/flatten.py`` 源账，全部经 tmp/ 探针实证）：

- ``_resolve`` 候选序：``dirs=(file_dir, root_dir[, top_dir])`` 按字符串
  去重保序 × cands（``fname`` 以 ``.tex`` 结尾〔不区分大小写〕→ 原样单
  候选；否则 ``[fname, fname.tex, fname.TEX]``）→ 各 dir × basename
  ``stem+.tex/.TEX`` 回退（``nodir/foo`` 抬到 ``root/foo.tex``）→ 首个
  ``exists()`` 者胜。**openin_any 等价闸（W73 已修）**：候选 real path
  须落 ``file_dir/root_dir/top_dir`` 解析根集——``..``/绝对路径/根内
  symlink 出界一律按 miss；空串 dir 不作根（``Path("")``=cwd 泄漏面）。
- 触发面八形态 + 裸文件名：``input``/``@input`` 组形或裸名
  （``FILENAME_CHARS`` 至其外字符）；``include`` 仅组形；``subfile``/
  ``includestandalone`` 剥 document 壳；``import``/``subimport`` 双组
  ``{subdir}{file}`` 前缀拼接；``InputIfFileExists`` 命中后 ``{T}{E}``
  留流面；``CatchFileBetweenTags\cs{file}{tag}`` 抽 ``%<*tag>…%</tag>``
  区。``\includeonly``/``\INPUT``（大小写敏感）非触发名留字面。
- 遮盖面：``%`` 注释至行尾、VERBATIM_ENVS（DEAD_ENVS 行锚、filecontents
  行首锚）、``\verb``/``\lstinline`` 跳读——内 ``\input`` 不触发。
- ``\endinput`` 丢弃当前文件余下字节（``\endinput`` 字面本体回吐）。
- ``_seen`` 祖先栈（resolved path）：环→静默回吐（不记 warning）；
  兄弟位重包含放行；``parse_file_v1`` 预种主文件路径——自环直断。
- 深度闸：call 层 ``depth > MAX_INPUTS(=8)`` → 该层**原文返回**——被拒
  层内容照常内联（其内 ``\input`` 不再展开），**无 warning**（v2 同点
  拒压栈 + ``missing_input depth>`` 告警——两臂截断语义分歧见观察钉）。
- miss 面：``_resolve`` None → ``missing_input``（warnings 表在场时）
  + 本体逐字回吐；resolve 命中但 ``read_bytes`` OSError（目录等）→ 静默
  回吐不告警（v2 同点告警 missing_input）；tag 缺 → 静默回吐。
- 文件名为空/含 ``\`` 计算式名（``\jobname``）→ ``_try_input`` 即滤，
  静默回吐零告警（W104 口径与 v2 ``_do_input`` 同点）。
- NUL 文件名：``Path.exists`` 吞 ``ValueError`` 按 miss 处理 → 告警
  （v2 在 Mouth tokenize 期丢 NUL 字符读到 ``ab``——行为分歧）。
- 恒等律：无 ``\endinput`` 且全部 ``\input`` 族 miss → 输出逐字节等于
  输入（逐字符拷贝 + 本体逐字回吐的构造级不变量）。

已修复缺陷（原 ``xfail(strict=True)`` CONFIRMED 钉——W73 修复落地
XPASS 转红，已拆钉转正为普通断言）：

- D1 FIXED ``_resolve`` 加 openin_any 等价闸：候选 real path 须落
  ``file_dir/root_dir/top_dir`` 解析根集——``../`` 穿越、绝对路径、
  根内 symlink 指出界、``\import{../}`` 前缀、空串 dir=cwd 全按 miss
  （``missing_input`` + 本体回吐），与 v2 ``_resolve_input``
  （``gullet/input.py:158``）同闸。原逃逸期 ``parse_file_v1`` 层逃逸
  内容落 chunks 实证。

观察钉（pin 现行行为——与 v2 的观测性/截断语义分歧，定性留裁决）：

- 深度截断静默：第 9 层内容裸内联零告警（v2 拒压栈 + ``depth>`` 告警）。
- 命中目录 → 静默回吐（v2 告警 ``missing_input``）。
- NUL 文件名 → ``missing_input`` 告警（v2 NUL 早夭读到 ``ab``）。
- tag 缺 → 静默回吐（文件在、标签缺与文件缺同形回吐但观测不对称）。

台账：``tmp/v1flatten-fuzz/findings.txt``（``test_write_findings_ledger``
写出）。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from _fuzzkit import (
    Finding,
    assert_deterministic,
    fuzz_rng,
    short,
    soup_join,
    soup_pick,
    write_findings,
)

from texlate.latex.api import parse_file_v1
from texlate.latex.flatten import _resolve, flatten_inputs
from texlate.latex.tables import MAX_INPUTS

if TYPE_CHECKING:
    import random

    from texlate.latex.model import ScanWarning

# ---------------------------------------------------------------- 常量与 soup

_FUZZ_ITERS_FS = 60  # _resolve oracle——每迭代真落盘，量低于纯内存 fuzz
_FUZZ_ITERS_GRAPH = 40
_FUZZ_ITERS_MEM = 400
_SEED_RESOLVE = 2026091811
_SEED_GRAPH = 2026091812
_SEED_MEM = 2026091813
_SEED_DEPTH = 2026091814
_SEED_MASK = 2026091815
_SEED_FORMS = 2026091816
_SEED_DET = 2026091818
_SEED_REINCLUDE = 2026091819

#: 概率档常量（PLR2004 免 noqa 集中点）。
_P_FS_ENTRY = 0.5  # 每条 _FSYS_ENTRIES 落盘概率
_P_SYMLINK = 0.3  # 根内 symlink 出界/指内各一枚的概率
_P_ABS = 0.2  # fname 取绝对路径（根内/根外各半）的概率位

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
]

#: ``\input`` 目标名汤——命中形/缺件/根内 ``..`` 穿越/出界 ``..``/怪名。
#: 逃逸名入汤撒的是 oracle 对拍 + openin_any 闸拒界（D1 FIXED 转正钉同约）。
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
    "x\\y",
    "",
]

#: 纯内存语句汤——触发形/未闭形/怪名/遮盖形/非触发名；``\endinput``
#: 不入汤（截断语义破恒等律，由专钉覆盖）。
_STMT_SOUP = [
    "plain words ",
    "\\input{nosuch}",
    "\\input nosuch ",
    "\\include{nosuch}",
    "\\include nosuch ",
    "\\@input{nosuch}",
    "\\subfile{nosuch}",
    "\\includestandalone{nosuch}",
    "\\import{sub}{nosuch}",
    "\\subimport{sub}{nosuch}",
    "\\InputIfFileExists{nosuch}{T}{E}",
    "\\CatchFileBetweenTags\\cs{nosuch}{tg}",
    "\\input{}",
    "\\input{a",
    "\\input{\\jobname}",
    "\\input{a\\x00b}",
    "\\includeonly{a,b}",
    "\\INPUT{x}",
    "{\\input{nosuch}}",
    "\\input{nodir/foo}",
    "\\verb|\\input{x}|",
    "\\verb|unclosed",
    "% \\input{x} comment-masked\n",
    "\\begin{verbatim}\\input{x}\\end{verbatim}",
    "\\begin{comment}\\input{x}\\end{comment}",
    "\\begin{filecontents}{f}\\input{x}\n\\end{filecontents}",
    "\\begin{document}",
    "\\end{document}",
    "{",
    "}",
    "\\",
    "%\n",
    "\n\n",
    "中",
    "\x00",
    "\\def\\a#1{#1}",
    "\\\\",
    "\\%",
    "~",
    "^_",
    "$x$",
]


# ---------------------------------------------------------------- 小件


def _mkfile(path: Path, text: str) -> None:
    """建父目录 + 写文件（内容唯一 marker = 路径本身，断言进球即认）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _flat(s: str, r: Path) -> str:
    """``flatten_inputs`` 调用面收窄——determinism 投影与单行 lambda 用。"""
    return flatten_inputs(s, str(r), str(r), warnings=[])


def _dirs(file_dir: str, root_dir: str, top_dir: str | None) -> list[str]:
    """契约目录集：``(file_dir, root_dir[, top_dir])`` 按字符串去重保序。"""
    seq = (file_dir, root_dir) if top_dir is None else (file_dir, root_dir, top_dir)
    return list(dict.fromkeys(seq))


def _oracle_resolve(
    fname: str, file_dir: str, root_dir: str, top_dir: str | None
) -> str | None:
    """``_resolve`` 查找序直译 oracle——候选序逐条对源账（无闸镜）。

    oracle 镜**修复前**查找序（出界也报命中）——openin_any 闸语义在对
    拍处补：oracle 命中出界时实现须 miss 或 basename 回退根内另中
    （``TestEscapeConfined`` 转正钉同约）。候选序/扩展名序/basename
    回退三段仍全对拍。
    """
    cands = (
        [fname]
        if fname.lower().endswith(".tex")
        else [fname, fname + ".tex", fname + ".TEX"]
    )
    dirs = _dirs(file_dir, root_dir, top_dir)
    for d in dirs:
        for c in cands:
            p = Path(d) / c
            if p.exists():
                return str(p)
    stem = Path(fname).name
    for d in dirs:
        for ext in (".tex", ".TEX"):
            p = Path(d) / (stem + ext)
            if p.exists():
                return str(p)
    for d in dirs:
        p = Path(d) / fname
        if p.exists():
            return str(p)
    return None


def _in_roots(hit: str | None, *dirs: str) -> bool:
    """``hit`` real path 是否落在任一 dir real path 内（出界判定件）。"""
    if hit is None:
        return False
    hp = Path(hit).resolve()
    return any(hp.is_relative_to(Path(d).resolve()) for d in dirs if d)


def _rand_fname(rng: random.Random, root: Path, elsewhere: Path) -> str:
    """文件名汤 + 概率位：根内/根外绝对路径注入。"""
    if rng.random() < _P_ABS:
        pool = [
            str(root / "x.tex"),
            str(root / "sub" / "y.tex"),
            str(elsewhere / "secret.tex"),
            "/etc/hostname",
        ]
        return soup_pick(rng, pool)
    return soup_pick(rng, _FNAME_SOUP)


def _rand_dir(rng: random.Random, *dirs: Path) -> str:
    """目录参汤：真目录/空串/不存在目录按权取。"""
    pool = [str(d) for d in dirs] + ["", str(dirs[0] / "nosuchdir")]
    return soup_pick(rng, pool)


def _build_fs(rng: random.Random, root: Path, top: Path, elsewhere: Path) -> None:
    """随机文件系统：root/top 各落 ``_FSYS_ENTRIES`` 随机子集 + 根外 secret。"""
    for base in (root, top):
        for rel in _FSYS_ENTRIES:
            if rng.random() < _P_FS_ENTRY:
                _mkfile(base / rel, f"F<{base.name}/{rel}>")
    _mkfile(elsewhere / "escape.tex", "SECRET-ESCAPE")
    _mkfile(elsewhere / "secret.tex", "SECRET-OUTSIDE")


def _rand_project(
    rng: random.Random, root: Path, *, allow_missing: bool
) -> tuple[list[str], dict[str, list[str]]]:
    """随机工程落盘：≤8 文件随机 ``\\input`` 组形边图。

    返回 ``(文件名池, {文件: [input 目标]})``——目标全组形、全相对平名，
    逃逸面不入图（D1 钉独立承载）。``allow_missing`` 掺缺件名。
    """
    n = rng.randint(2, 8)
    names = [f"f{i}" for i in range(n)]
    pool = list(names)
    if allow_missing:
        pool += ["missing", "no/such"]
    edges: dict[str, list[str]] = {}
    for name in names:
        targets = [soup_pick(rng, pool) for _ in range(rng.randint(0, 2))]
        body = f"C<{name}> " + soup_join(rng, ["w ", "more ", "txt "], 0, 4)
        for t in targets:
            body += f"\\input{{{t}}} "
        _mkfile(root / (name + ".tex"), body)
        edges[name] = targets
    return names, edges


def _reachable(edges: dict[str, list[str]], entry: str) -> set[str]:
    """落地集 oracle：``entry`` 起 ≤9 边简单路径可达的文件名集。

    祖先栈断环 ⇒ 路径须无重复节点（BFS 最短路天然简单）；深度闸 ⇒
    边数 ≤ ``MAX_INPUTS + 1``（第 9 边文件裸内联落地，其 ``\\input``
    不再展开）。缺件名不在 edges 键集天然不可达。
    """
    seen: dict[str, int] = {entry: 0}
    frontier = [entry]
    while frontier:
        nxt: list[str] = []
        for cur in frontier:
            d = seen[cur]
            if d >= MAX_INPUTS:  # cur 的 \input 在 depth d+1 处理——闸在 d+1>8
                continue
            for t in edges.get(cur, []):
                if t not in seen:
                    seen[t] = d + 1
                    nxt.append(t)
        frontier = nxt
    return set(seen)


# ---------------------------------------------------------------- _resolve oracle fuzz


class TestResolveOracle:
    """``_resolve`` 直调面——随机 fs × 敌意名，对规格 oracle + 确定性。"""

    def test_fuzz_resolve_matches_oracle(self, tmp_path: Path) -> None:
        rng = fuzz_rng(_SEED_RESOLVE)
        for i in range(_FUZZ_ITERS_FS):
            base = tmp_path / f"r{i}"
            root, top, elsewhere = base / "root", base / "top", base / "out"
            _build_fs(rng, root, top, elsewhere)
            if rng.random() < _P_SYMLINK:
                (root / "linkout.tex").symlink_to(elsewhere / "secret.tex")
            if rng.random() < _P_SYMLINK:
                (root / "linkin.tex").symlink_to(root / "x.tex")
            fd = _rand_dir(rng, root, root / "sub", top)
            rd = _rand_dir(rng, root, top)
            td = soup_pick(rng, [None, str(top), str(root), ""])
            fname = _rand_fname(rng, root, elsewhere)
            want = _oracle_resolve(fname, fd, rd, td)
            got = _resolve(fname, fd, rd, top_dir=td)
            if want is not None and not _in_roots(want, fd, rd, *(td or "",)):
                # 逃逸面：openin_any 闸（W73）后实现须拒出界候选——miss 或
                # basename 回退根内另中（oracle 序早退拦不到后者）
                assert got is None or _in_roots(got, fd, rd, *(td or "",)), short(
                    (fname, fd, rd, td, got, want)
                )
                continue
            assert got == want, short((fname, fd, rd, td, got, want))
            # 直调确定性：同参两调同值
            assert _resolve(fname, fd, rd, top_dir=td) == got

    def test_fuzz_resolve_never_raises(self, tmp_path: Path) -> None:
        """铁规：任意 fname/dir 组合 ``_resolve`` 不抛（NUL 经 exists 吞）。"""
        rng = fuzz_rng(_SEED_RESOLVE + 1)
        for i in range(_FUZZ_ITERS_FS):
            base = tmp_path / f"e{i}"
            root = base / "root"
            _mkfile(root / "x.tex", "X")
            fname = soup_join(rng, _FNAME_SOUP, 0, 3)
            td = soup_pick(rng, [None, "", str(base / "top")])
            _resolve(fname, str(root), str(root), top_dir=td)


# ---------------------------------------------------------------- flatten 工程级 fuzz


class TestFlattenGraph:
    """随机 ``\\input`` 图闭包——可达集 oracle + 缺件告警白名单 + 确定性。"""

    def test_fuzz_random_graph_closure(self, tmp_path: Path) -> None:
        """落地集断言：≤9 边可达文件 marker 进球；不可达不进；告警只报缺件。"""
        rng = fuzz_rng(_SEED_GRAPH)
        missing_pool = {"missing", "no/such"}
        for i in range(_FUZZ_ITERS_GRAPH):
            root = tmp_path / f"g{i}"
            names, edges = _rand_project(rng, root, allow_missing=True)
            entry = soup_pick(rng, [*names, "missing_entry"])
            warns: list[ScanWarning] = []
            out = flatten_inputs(
                f"\\input{{{entry}}}", str(root), str(root), warnings=warns
            )
            landed = _reachable(edges, entry)
            for name in names:
                marker = f"C<{name}>"
                if name in landed:
                    assert marker in out, short((entry, name, out))
                else:
                    assert marker not in out, short((entry, name, out))
            for w in warns:
                assert w.kind == "missing_input", short(w.kind)
                assert w.detail.split(":", 1)[1] in missing_pool | {entry}, short(
                    w.detail
                )

    def test_fuzz_deterministic(self, tmp_path: Path) -> None:
        """同工程两趟 ``flatten_inputs`` 输出逐字节等。"""
        rng = fuzz_rng(_SEED_DET)
        for i in range(_FUZZ_ITERS_GRAPH):
            root = tmp_path / f"dt{i}"
            names, _edges = _rand_project(rng, root, allow_missing=True)
            src = f"pre \\input{{{soup_pick(rng, names)}}} post"
            assert_deterministic(lambda: _flat(src, root))  # noqa: B023 -- 闭包只吃 src/root 无循环依赖

    def test_fuzz_sibling_reinclude(self, tmp_path: Path) -> None:
        """兄弟位重包含：祖先栈弹撤后同文件可再进——出现次数等于引用数。"""
        rng = fuzz_rng(_SEED_REINCLUDE)
        for i in range(_FUZZ_ITERS_GRAPH):
            root = tmp_path / f"s{i}"
            _mkfile(root / "c.tex", f"CHILD{i}X")
            k = rng.randint(1, 4)
            src = " mid ".join("\\input{c}" for _ in range(k))
            out = flatten_inputs(src, str(root), str(root))
            assert out.count(f"CHILD{i}X") == k, short(src)
            # 双亲同包含：p/q 各 \input{c} → 兄弟位两侧各进一次
            _mkfile(root / "p.tex", "P \\input{c} P2")
            _mkfile(root / "q.tex", "Q \\input{c} Q2")
            out2 = flatten_inputs("\\input{p} \\input{q}", str(root), str(root))
            assert out2.count(f"CHILD{i}X") == 2, short(out2)  # noqa: PLR2004 -- p/q 双亲各进一次

    def test_fuzz_depth_gate_truncation(self, tmp_path: Path) -> None:
        """v1 深度闸观察钉：前 ``min(d, 9)`` 层内容进流，越界层留 literal。

        与 v2 分歧：v1 第 9 层**裸内联**（内容进球、``\\input`` 不展开）且
        **零告警**；v2 拒压栈 + ``missing_input depth>``。pin v1 现行语义。
        """
        rng = fuzz_rng(_SEED_DEPTH)
        for i in range(_FUZZ_ITERS_GRAPH):
            root = tmp_path / f"d{i}"
            depth = rng.randint(1, MAX_INPUTS + 4)
            for j in range(depth):
                nxt = f"\\input{{f{j + 1}}}" if j + 1 < depth else ""
                _mkfile(root / f"f{j}.tex", f"C{j} {nxt} E{j}")
            warns: list[ScanWarning] = []
            out = flatten_inputs("\\input{f0}", str(root), str(root), warnings=warns)
            landed = min(depth, MAX_INPUTS + 1)
            for j in range(landed):
                assert f"C{j}" in out, short((depth, j))
            for j in range(landed, depth):
                assert f"C{j}" not in out, short((depth, j))
            assert not warns, short((depth, [w.detail for w in warns]))
            if depth > MAX_INPUTS + 1:
                assert f"\\input{{f{landed}}}" in out  # 被拒层 input 留字面


# ---------------------------------------------------------------- 遮盖 / \endinput


class TestMasking:
    """遮盖面 fuzz——注释/verbatim/filecontents/``\\verb`` 内 ``\\input`` 不触发。"""

    def test_fuzz_masked_input_never_fires(self, tmp_path: Path) -> None:
        """各遮盖形内 ``\\input{masked}``：masked 唯一 marker 绝不进球。"""
        rng = fuzz_rng(_SEED_MASK)
        for i in range(_FUZZ_ITERS_GRAPH):
            root = tmp_path / f"m{i}"
            _mkfile(root / "masked.tex", f"MASKED{i}")
            _mkfile(root / "open.tex", f"OPEN{i}")
            masked_forms = [
                "% \\input{masked}\n\\input{open}",
                "pre % \\input{masked} tail\n\\input{open}",
                "\\begin{verbatim}\\input{masked}\\end{verbatim}\\input{open}",
                # DEAD_ENVS 行锚语义：\end{comment} 须独占成行才闭合
                ("\\begin{comment}\\input{masked}\n\\end{comment}\n\\input{open}"),
                (
                    "\\begin{filecontents}{dump}\\input{masked}\n"
                    "\\end{filecontents}\\input{open}"
                ),
                "\\verb|\\input{masked}| \\input{open}",
            ]
            src = soup_pick(rng, masked_forms)
            warns: list[ScanWarning] = []
            out = flatten_inputs(src, str(root), str(root), warnings=warns)
            assert f"MASKED{i}" not in out, short((src, out))
            assert f"OPEN{i}" in out, short((src, out))
            assert not warns, short((src, [w.detail for w in warns]))

    def test_fuzz_endinput_truncates(self, tmp_path: Path) -> None:
        """``\\endinput`` 截断：其后文本与 ``\\input`` 边全死（本文件内）。"""
        for i in range(_FUZZ_ITERS_GRAPH):
            root = tmp_path / f"e{i}"
            _mkfile(root / "tail.tex", f"TAIL{i}")
            _mkfile(
                root / "f.tex",
                f"BEFORE{i} \\input{{tail}} \\endinput \\input{{tail}} AFTER{i}",
            )
            out = flatten_inputs("\\input{f}", str(root), str(root))
            assert f"BEFORE{i}" in out, short(out)
            assert f"AFTER{i}" not in out, short(out)
            assert out.count(f"TAIL{i}") == 1, short(out)  # 尾段 \input 不触发
            # 主层 \endinput 同语义：入口串本身截断
            out2 = flatten_inputs(
                f"HEAD{i}\\endinput \\input{{tail}} TAILMORE{i}",
                str(root),
                str(root),
            )
            assert out2 == f"HEAD{i}\\endinput", short(out2)


# ---------------------------------------------------------------- 纯内存 soup


class TestInMemory:
    """无 fs 面——恒等律 + 铁规 + miss 告警面。"""

    def test_fuzz_miss_only_identity(self, tmp_path: Path) -> None:
        """恒等律：无 ``\\endinput`` 且全 miss → 输出逐字节等于输入。"""
        rng = fuzz_rng(_SEED_MEM)
        root = tmp_path / "empty"
        root.mkdir()
        for _ in range(_FUZZ_ITERS_MEM):
            src = soup_join(rng, _STMT_SOUP, 0, 12)
            warns: list[ScanWarning] = []
            out = flatten_inputs(src, str(root), str(root), warnings=warns)
            assert out == src, short((src, out))
            for w in warns:
                assert w.kind == "missing_input", short(w.kind)

    def test_fuzz_never_raises(self, tmp_path: Path) -> None:
        """铁规：soup + ``\\endinput`` 乱入也不抛（截断语义合法破恒等）。"""
        rng = fuzz_rng(_SEED_MEM + 1)
        root = tmp_path / "empty"
        root.mkdir()
        # 逃逸形（可能真命中本机文件）+ \endinput 截断——只钉不抛不断恒等
        soup = [
            *_STMT_SOUP,
            "\\input{../outside}",
            "\\input{/etc/hostname}",
            "\\input{/etc/passwd}",
            "\\endinput",
            "\\endinput discarded",
        ]
        for _ in range(_FUZZ_ITERS_MEM):
            src = soup_join(rng, soup, 0, 12)
            out = flatten_inputs(src, str(root), str(root), warnings=[])
            assert isinstance(out, str)


# ---------------------------------------------------------------- 形态矩阵


class TestForms:
    """八形态 + 裸名/非触发名矩阵——命中/缺件各半（逐形态契约钉）。"""

    def test_fuzz_forms_hit_miss(self, tmp_path: Path) -> None:
        rng = fuzz_rng(_SEED_FORMS)
        for i in range(_FUZZ_ITERS_GRAPH):
            root = tmp_path / f"f{i}"
            _mkfile(root / "hit.tex", f"HIT{i}")
            _mkfile(root / "sub" / "imp.tex", f"IMP{i}")
            _mkfile(
                root / "shell.tex",
                "\\documentclass{art}\n\\begin{document}\n"
                f"SHELL{i}\n\\end{{document}}\n",
            )
            _mkfile(root / "tags.tex", f"pre %<*tg>TAG{i}%</tg> post")
            # (命中形, 缺件形, 命中 marker)——盲 replace 会伤命令名
            cases = [
                ("\\input{hit}", "\\input{nosuch}", f"HIT{i}"),
                ("\\input hit ", "\\input nosuch ", f"HIT{i}"),
                ("\\@input{hit}", "\\@input{nosuch}", f"HIT{i}"),
                ("\\include{hit}", "\\include{nosuch}", f"HIT{i}"),
                ("\\import{sub}{imp}", "\\import{sub}{nosuch}", f"IMP{i}"),
                ("\\subimport{sub}{imp}", "\\subimport{sub}{nosuch}", f"IMP{i}"),
                ("\\subfile{shell}", "\\subfile{nosuch}", f"SHELL{i}"),
                (
                    "\\includestandalone{shell}",
                    "\\includestandalone{nosuch}",
                    f"SHELL{i}",
                ),
                (
                    "\\InputIfFileExists{hit}{T}{E}",
                    "\\InputIfFileExists{nosuch}{T}{E}",
                    f"HIT{i}",
                ),
                (
                    "\\CatchFileBetweenTags\\cs{tags}{tg}",
                    "\\CatchFileBetweenTags\\cs{nosuch}{tg}",
                    f"TAG{i}",
                ),
            ]
            form, miss, expected = soup_pick(rng, cases)
            warns: list[ScanWarning] = []
            out = flatten_inputs(form, str(root), str(root), warnings=warns)
            assert expected in out, short((form, out))
            assert not warns, short((form, [w.detail for w in warns]))
            warns2: list[ScanWarning] = []
            out2 = flatten_inputs(miss, str(root), str(root), warnings=warns2)
            assert expected not in out2
            assert any(w.kind == "missing_input" for w in warns2), short(miss)

    def test_fuzz_non_trigger_names_literal(self, tmp_path: Path) -> None:
        """非触发名留字面无告警：``\\includeonly``/``\\INPUT``/``\\include`` 裸形。"""
        rng = fuzz_rng(_SEED_FORMS + 1)
        for i in range(_FUZZ_ITERS_GRAPH):
            root = tmp_path / f"n{i}"
            _mkfile(root / "x.tex", f"X{i}")
            form = soup_pick(
                rng,
                [
                    "\\includeonly{x}",
                    "\\INPUT{x}",
                    "\\include x ",
                    "\\Input{x}",
                ],
            )
            warns: list[ScanWarning] = []
            out = flatten_inputs(form, str(root), str(root), warnings=warns)
            assert out == form, short((form, out))
            assert f"X{i}" not in out
            assert not warns


# ---------------------------------------------------------------- CONFIRMED 缺陷钉


class TestEscapeConfined:
    r"""D1 FIXED（W73）：``_resolve``/``flatten_inputs`` openin_any 等价闸。

    修复前 ``../``/绝对路径/根内 symlink 指出界/``\import{../}`` 六路全
    内联根外内容进翻译流（原 ``xfail(strict)`` CONFIRMED 钉，修复落地
    XPASS 转红已拆钉转正）。现候选 real path 须落 ``file_dir/root_dir/
    top_dir`` 解析根集，越界按 miss——与 v2 ``_resolve_input``
    （``gullet/input.py:158``）同闸。
    """

    def test_resolve_escapes_confined(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside"
        _mkfile(outside / "secret.tex", "SECRET")
        (root / "linkout.tex").symlink_to(outside / "secret.tex")
        root_r = root.resolve()
        vectors = [
            "../outside/secret",  # .. 穿越
            str(outside / "secret"),  # 绝对路径
            str(outside / "secret.tex"),  # 绝对路径带扩展名
            "linkout",  # 根内 symlink 指出界
            "../../outside/secret",  # 多级 ..
        ]
        for fname in vectors:
            hit = _resolve(fname, str(root), str(root))
            assert hit is None or Path(hit).resolve().is_relative_to(root_r), short(
                (fname, hit)
            )

    def test_flatten_escape_not_inlined(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside"
        _mkfile(outside / "secret.tex", "SECRET-ESC")
        (root / "linkout.tex").symlink_to(outside / "secret.tex")
        stmts = [
            "\\input{../outside/secret}",
            f"\\input{{{outside}/secret}}",
            "\\input{linkout}",
            "\\import{../outside}{secret}",
            "\\include{../outside/secret}",
            "\\InputIfFileExists{../outside/secret}{T}{E}",
        ]
        for stmt in stmts:
            warns: list[ScanWarning] = []
            out = flatten_inputs(stmt, str(root), str(root), warnings=warns)
            assert "SECRET-ESC" not in out, short((stmt, out))
            assert any(w.kind == "missing_input" for w in warns), short(stmt)
        # api 层：parse_file_v1 逃逸内容落 chunks 实证
        main = root / "main.tex"
        main.write_text(
            "\\input{../outside/secret}\n\nprose words words words",
            encoding="utf-8",
        )
        res = parse_file_v1(main)
        surface = res.protected_tex + "".join(c.content for c in res.chunks)
        assert "SECRET-ESC" not in surface


# ---------------------------------------------------------------- 观察钉


class TestObservedDivergence:
    """v1↔v2 观测性/截断语义分歧——pin 现行行为（非缺陷声明，定性留裁决）。"""

    def test_dir_hit_silent(self, tmp_path: Path) -> None:
        r"""命中目录 → ``read_bytes`` OSError → 静默回吐（v2 告警）。"""
        (tmp_path / "adir").mkdir()
        warns: list[ScanWarning] = []
        out = flatten_inputs(
            "\\input{adir}", str(tmp_path), str(tmp_path), warnings=warns
        )
        assert "\\input{adir}" in out
        assert not warns

    def test_nul_fname_warns(self, tmp_path: Path) -> None:
        r"""NUL 文件名 → ``Path.exists`` 吞 ``ValueError`` 按 miss → 告警。"""
        warns: list[ScanWarning] = []
        out = flatten_inputs(
            "\\input{a\x00b}", str(tmp_path), str(tmp_path), warnings=warns
        )
        assert "\\input{a\x00b}" in out
        assert any(w.kind == "missing_input" for w in warns)

    def test_tag_miss_silent(self, tmp_path: Path) -> None:
        r"""``\CatchFileBetweenTags`` 文件在、tag 缺 → 静默回吐（零告警）。"""
        _mkfile(tmp_path / "tags.tex", "pre %<*tg>TT%</tg> post")
        warns: list[ScanWarning] = []
        out = flatten_inputs(
            "\\CatchFileBetweenTags\\cs{tags}{nope}",
            str(tmp_path),
            str(tmp_path),
            warnings=warns,
        )
        assert "TT" not in out
        assert not warns

    def test_basename_lift_quirk(self, tmp_path: Path) -> None:
        r"""basename 回退静默抬升：``\input{nodir/foo}`` → ``root/foo.tex``。"""
        _mkfile(tmp_path / "foo.tex", "BASE-LIFT")
        warns: list[ScanWarning] = []
        out = flatten_inputs(
            "\\input{nodir/foo}", str(tmp_path), str(tmp_path), warnings=warns
        )
        assert "BASE-LIFT" in out
        assert not warns


# ---------------------------------------------------------------- 契约 corner 钉


class TestContractCorners:
    """fuzz 撒不到/需精确断的契约角——确定性钉（非迭代）。"""

    def test_self_cycle_silent_via_parse_file(self, tmp_path: Path) -> None:
        r"""``parse_file_v1`` 预种主文件路径 → ``\input{main}`` 自环静默断。"""
        main = tmp_path / "main.tex"
        main.write_text("M \\input{main} E", encoding="utf-8")
        res = parse_file_v1(main)
        assert not any(w.kind == "missing_input" for w in res.warnings)

    def test_ab_cycle_silent(self, tmp_path: Path) -> None:
        r"""``A→B→A`` 祖先断环**静默**：``\input`` 逐字回吐，零 warning。"""
        _mkfile(tmp_path / "a.tex", "Aa \\input{b} a2")
        _mkfile(tmp_path / "b.tex", "Bb \\input{a} b2")
        warns: list[ScanWarning] = []
        out = flatten_inputs("\\input{a}", str(tmp_path), str(tmp_path), warnings=warns)
        assert "Bb" in out
        assert "\\input{a}" in out  # 断环点本体回吐
        assert not warns

    def test_empty_group_silent(self, tmp_path: Path) -> None:
        r"""``\input{}`` 空名 → 静默回吐不告警。"""
        warns: list[ScanWarning] = []
        out = flatten_inputs("\\input{}", str(tmp_path), str(tmp_path), warnings=warns)
        assert out == "\\input{}"
        assert not warns

    def test_cs_name_silent_echo(self, tmp_path: Path) -> None:
        r"""``\input{\jobname}`` 计算式名 → 静默回吐零告警（W104 与 v2 ``_do_input`` 同点滤）。"""
        warns: list[ScanWarning] = []
        out = flatten_inputs(
            "\\input{\\jobname} tail", str(tmp_path), str(tmp_path), warnings=warns
        )
        assert "\\input{\\jobname}" in out
        assert not warns

    def test_unclosed_group_silent(self, tmp_path: Path) -> None:
        r"""``\input{a`` 未闭组 → ``match_brace`` 缺 → 静默回吐。"""
        warns: list[ScanWarning] = []
        out = flatten_inputs("\\input{a", str(tmp_path), str(tmp_path), warnings=warns)
        assert out == "\\input{a"
        assert not warns

    def test_iife_groups_stay(self, tmp_path: Path) -> None:
        r"""``\InputIfFileExists`` 命中后 ``{then}{else}`` 双组留流面。"""
        _mkfile(tmp_path / "h.tex", "HH")
        out = flatten_inputs(
            "\\InputIfFileExists{h}{YES}{NO}", str(tmp_path), str(tmp_path)
        )
        assert "HH" in out
        assert "{YES}{NO}" in out

    def test_bare_filename_chars_boundary(self, tmp_path: Path) -> None:
        r"""裸名形读 ``FILENAME_CHARS`` 至其外字符：``\input a b`` 只读 ``a``。"""
        _mkfile(tmp_path / "a.tex", "AAA")
        warns: list[ScanWarning] = []
        out = flatten_inputs(
            "\\input a b", str(tmp_path), str(tmp_path), warnings=warns
        )
        assert "AAA" in out
        assert not warns


# ---------------------------------------------------------------- findings 台账落盘


def test_write_findings_ledger() -> None:
    """台账写出——``tmp/v1flatten-fuzz/findings.txt``。"""
    write_findings(
        Path("tmp/v1flatten-fuzz/findings.txt"),
        title="v1flatten-fuzz — v1 flatten_inputs/\\input 多文件闭包台账",
        scope=(
            "latex/flatten.py：_resolve 候选序/扩展名序/basename 回退、八形态"
            "+裸名触发面、遮盖面（comment/verbatim/filecontents/\\verb）、"
            "_seen 祖先栈断环、MAX_INPUTS=8 深度闸（裸内联语义）、"
            "parse_file_v1 文件级入口、根集出界逃逸面"
        ),
        test_file="tests/test_fuzz_v1flatten.py",
        status=(
            "D1 FIXED（W73 修复落地 xfail-strict 拆钉转正）/ "
            "观察钉一簇（v1↔v2 观测性分歧）"
        ),
        confirmed=[
            Finding(
                fid="D1",
                title=(
                    "_resolve/flatten_inputs 无 openin_any 等价闸——根外内容进翻译流"
                ),
                body=(
                    "repro: tmp/lane-c9-fuzz/probe_v1_escape2.py——"
                    "\\input{../outside/secret}、\\input{/abs/secret}、"
                    "根内 symlink 指出界、\\import{../outside}{sec}、"
                    "\\include{../}、\\InputIfFileExists{../} 六路全内联 "
                    "SECRET；parse_file_v1 层逃逸内容落 chunks。\n"
                    "reachability: TEXLATE_NO_EXPAND=1 回退臂 + bench "
                    "flatten_reach 消费同一低层件；e-print 解包只滤成员类型，"
                    "\\input 名来自文件内容面——敌意 e-print 可读本机任意文件。\n"
                    "对照: v2 _resolve_input（gullet/input.py:158）明文"
                    "「openin_any 等价闸（C1）」——候选 real path 须落根集。\n"
                    "修复（W73）: _resolve 命中后 resolve() ⊆ dirs resolve "
                    "判界（含空串 dir 过滤），越界按 miss（missing_input + "
                    "本体回吐）——TestEscapeConfined 两钉转正绿。"
                ),
                status=" [FIXED]",
            )
        ],
        observed=[
            (
                "深度截断静默：第 9 层（depth>8）内容裸内联零告警，其内 \\input "
                "不再展开（v2 拒压栈 + missing_input depth> 告警——截断点早一层"
                "且可观测）"
            ),
            "命中目录 → read_bytes OSError → 静默回吐（v2 告警 missing_input）",
            (
                "NUL 文件名 → Path.exists 吞 ValueError 按 miss 告警"
                "（v2 Mouth tokenize 期丢 NUL 读到 ab——\\input{a<NUL>b} "
                "v2 读 ab.tex、v1 告警）"
            ),
            "tag 缺（CatchFileBetweenTags）→ 静默回吐（文件在、标签缺不告警）",
            "basename 回退静默抬升：\\input{nodir/foo} → root/foo.tex（v2 同款）",
        ],
        notes=[
            (
                "W73 修复顺手清了 _resolve 第三循环（dirs × 裸 fname）——原对"
                "现有候选表恒死代码（fname 恒在 cands[0]，首轮已查）。"
            ),
            (
                "空串 dir（file_dir/root_dir/top_dir=''）修复前按 cwd 相对解析"
                "（Path('')/'x'='x' 命中 cwd 文件，tmp 探针实证 top_dir='' 命中"
                "repo pyproject.toml）——W73 已随闸过滤（v2 _live_roots 同款）。"
            ),
            (
                "cs 名 \\input{\\jobname}：修复前 v1 报 missing_input、v2 静默"
                "——W104 口径落地后 v1 同点滤除（_try_input 含 \\\\ 即非输入尝试），"
                "两臂对齐，钉转 TestContractCorners.test_cs_name_silent_echo。"
            ),
            (
                "oracle 设计：_oracle_resolve 镜修复前查找序（出界也报命中），"
                "闸语义在对拍处补——oracle 命中出界时断言实现 miss 或落根内。"
            ),
        ],
        scratch="tmp/v1flatten-fuzz + tmp/lane-c9-fuzz",
    )
