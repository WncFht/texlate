"""specs._layoutqc.markcheck — marks 查表叶 (_layoutqc 拆分叶).

.txlm 跨臂对照 + 单侧 offpage + splice/src env 覆盖记账
(marks_absent/marks_coverage/dropped_env)。texlate.compile.marks
真值层全量依赖走本叶。
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from specs import _bootstrap

_bootstrap.ensure()

from texlate.compile.marks import (
    _MARK_ENVS,
    compare_marks,
    env_inventory,
    env_sequence,
    fls_tex_files,
    parse_txlm,
)

if TYPE_CHECKING:
    from pathlib import Path


def _live_files(fls: Path, fls_root: Path, tree_root: Path) -> list[Path] | None:
    """``<stem>.fls`` → 编译读档序的活 ``.tex`` 集（映射到 tree_root 下）。

    fls 缺席 → ``None``（调用方退回全树口径）。INPUT 行相对 fls_root
    解析成 relpath 再映射——base 侧 fls 长在 build-base 树而期望面
    扫 src 树，两树同构时 relpath 直接换根。
    """
    rels = fls_tex_files(fls, fls_root)
    if rels is None:
        return None
    return [tree_root / r for r in rels]


def _marks_scan(
    zh_txlm: Path | None,
    base_txlm: Path | None,
    splice_dir: Path | None,
    src_dir: Path | None,
    zh_pages: int | None = None,
    base_pages: int | None = None,
    marks_sentinel: bool | None = None,
    marks_expected: bool | None = None,
    base_dir: Path | None = None,
    compile_dead: bool = False,
) -> tuple[list[dict], dict]:
    """marks 查表层：跨臂对照 + 单侧 offpage + 双层覆盖记账。

    - ``marks_absent``：zh 侧 txlm 缺席/零 mark → 注入层真洞；base 侧
      ``base_txlm=None`` 的「未建对照臂」只是参数事实（base=onfail
      时 clean 不编 base 臂），metrics 记账不出 finding——但臂已建
      （base_dir 传入）而 txlm 缺席/零 mark 仍是注入链断，照报。
      ``compile_dead``（log 侧 Emergency stop/No pages 命中）时 zh 侧
      缺席是编译中止的症状非注入洞，收口为 metrics 记账不发 finding。
    - ``marks_coverage``：splice 树（实际编译面）有受钩 env 但零 MARK →
      注入/钩子层洞（demote 改名已在此面消化，不误报）。
    - ``dropped_env``：src 树有、splice 树无的 env —— splice/fixloop
      删元素的 never-silent 记账（BabelDOC #615 规则）。
    """
    findings: list[dict] = []
    metrics: dict = {}
    if zh_txlm is None or not zh_txlm.exists():
        # 合法缺席闸（0928 marks_chain 簇 49/50 实证全是假洞）：
        # (a) 封件 tex 有注入哨兵（``\txlm@out``/TeXlateLayoutMarks）
        #     → 该产物编译期确已注入，txlm 缺席=真链断，照报；
        # (b) 有 tex 无哨兵 → pre-era/soak 臂产物（不注入 marks），
        #     缺席是产物出身事实非缺陷；
        # (c) artifact-only 封件（无 .tex 可验哨兵）→ 退回账本出处
        #     marks_expected（compile metrics inject.layout_marks），
        #     False=编译记录里注入键缺席（pre-era 编译）亦压；
        # (d) 两侧都不可证伪 → 诚实照报。
        if compile_dead:
            metrics["marks_absent_suppressed"] = "compile_dead"
            return [], metrics
        if marks_sentinel is True:
            return [{"sig": "layout:marks_absent", "side": "zh"}], metrics
        if marks_sentinel is False or marks_expected is False:
            metrics["marks_absent_suppressed"] = (
                "pre_era" if marks_sentinel is False else "not_expected"
            )
            return [], metrics
        return [{"sig": "layout:marks_absent", "side": "zh"}], metrics
    zh = parse_txlm(zh_txlm)
    metrics["zh_marks"] = len(zh["marks"])
    metrics["geom"] = zh["geom"]
    if not zh["marks"]:
        if compile_dead:
            metrics["marks_absent_suppressed"] = "compile_dead"
            return findings, metrics
        findings.append(
            {"sig": "layout:marks_absent", "side": "zh", "lines": zh["lines"]}
        )
        return findings, metrics
    base = None
    if base_txlm is not None:
        if base_txlm.exists():
            base = parse_txlm(base_txlm)
            metrics["base_marks"] = len(base["marks"])
            if not base["marks"]:
                base = None
        if base is None:
            # 臂已建（base_dir 传入）却 txlm 缺席/零 mark = 注入/仪表
            # 链断；区别于 base_txlm=None 的「未建对照臂」参数事实
            findings.append({"sig": "layout:marks_absent", "side": "base"})
    # base 臂未建只记 metrics——对照臂编不编是参数选择非缺陷
    metrics.setdefault("base_marks", 0)
    # live-env 口径：fls 开档集=引擎背书的活文件集（整树 rglob 会把
    # 孤儿文件/备选 main 计进期望面），叠文件内死区（enddoc 死尾/
    # \iffalse 死支/def 体/弃料宏参数组）——fls 缺席退回全树口径。
    zh_live = (
        _live_files(zh_txlm.with_suffix(".fls"), splice_dir, splice_dir)
        if splice_dir is not None and splice_dir.is_dir()
        else None
    )
    src_live = (
        _live_files(base_txlm.with_suffix(".fls"), base_dir, src_dir)
        if base_txlm is not None
        and base_dir is not None
        and src_dir is not None
        and src_dir.is_dir()
        else None
    )
    metrics["env_live"] = {"zh": zh_live is not None, "src": src_live is not None}
    # 声明序主键：zh 侧读 splice 树（编译面），base 侧读 src 树
    # （en 原面——build-base 同构）→ demote 改名/缺 b-mark 皆免疫
    zh_decl = (
        env_sequence(splice_dir, files=zh_live)
        if splice_dir is not None and splice_dir.is_dir()
        else None
    )
    base_decl = (
        env_sequence(src_dir, files=src_live)
        if src_dir is not None and src_dir.is_dir()
        else None
    )
    findings.extend(
        compare_marks(
            zh,
            base,
            zh_decl=zh_decl,
            base_decl=base_decl,
            zh_pages=zh_pages,
            base_pages=base_pages,
        )
    )
    emitted = Counter(v["uid"].rsplit("-", 2)[0] for v in zh["marks"].values())
    if splice_dir is not None and splice_dir.is_dir():
        sinv = env_inventory(splice_dir, files=zh_live)
        gaps = {
            e: n for e, n in sinv.items() if e in _MARK_ENVS and emitted.get(e, 0) == 0
        }
        metrics["splice_inventory"] = sinv
        if gaps:
            findings.append({"sig": "layout:marks_coverage", "envs": gaps})
        if src_dir is not None and src_dir.is_dir():
            sinv_src = env_inventory(src_dir, files=src_live)
            dropped = {
                e: n
                for e, n in sinv_src.items()
                if e in _MARK_ENVS and sinv.get(e, 0) == 0
            }
            # demote_wrapfloats 的合法改名：wrap* 消失但目标 env 计数
            # 等量增长 → 改名非丢弃（wrapfloat{T}→T 同样覆盖）
            _demote_tgt = {
                "wrapfigure": "figure",
                "wrapfigure*": "figure*",
                "wraptable": "table",
                "wraptable*": "table*",
            }
            for e in list(dropped):
                tgt = _demote_tgt.get(e)
                if e == "wrapfloat":
                    tgts = ("figure", "figure*", "table", "table*")
                elif tgt:
                    tgts = (tgt,)
                else:
                    continue
                gain = sum(sinv.get(t, 0) - sinv_src.get(t, 0) for t in tgts)
                if gain >= dropped[e]:
                    del dropped[e]
            if dropped:
                findings.append({"sig": "layout:dropped_env", "envs": dropped})
    return findings, metrics
