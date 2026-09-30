r"""_qmetrics — S5 质量面代理指标共享库（quality_proxies.py 的叶化吸收）。

三族指标的纯计算面，供 soak xlat/compile 内联接线与 quality rescore
spec 复用；不带 benchlib/stagerun_lib 驱动胶（iter_jsonl/latest_by
就地小函数替代），不带路径布局知识——state/build 目录由调用方解析
（v2 = vault.restore 物化树，旧 stagerun = work/{id}/ 嵌套）。

- ``leak_*``：送译 chunk ``source`` 命中 ``specs._leak.LEAK_PATTERNS``
  六族展开残留正则的比率（正则单源——勿复制防口径漂移）。两臂同义，
  leak 是上游 parse/gullet 质量面。
- ``term_*``：仅 ``TERM_ARMS`` 臂的术语表一致率；术语集口径 =
  cat_group → terms/index.yaml category csv + default.csv +
  Glossary.doc_filter（user 层哨兵禁用防跨机漂移，local 层保留——
  它是语料属性）；优先消费 run 时持久化的 term_dict.json（真实注入
  表），缺席才按 rebuild 口径重建（假设一致率代理）。非 TERM_ARMS
  臂 term_* 键置 null 而非缺键——下游按臂过滤依赖形状恒定。
- ``landmark``：PDF named-dest 按 ``align._category`` 分桶 ÷ 编译树
  结构期望数；``coverage`` 分子只含已插桩五类，``other`` 桶不进
  （1907.03768 实测 43 个 other dest 会把全锚丢失掩盖成 0.70）。

code_deps（私有 API 钉入 fp code 分量）：src/texlate/align.py
（``_category``/``extract_landmarks``）、src/texlate/xlat/glossary.py
（``_TERM_BOUNDARY``/``LOCAL_GLOSSARY_NAME``/``Glossary``/``TermEntry``/
``load_table``）、specs/_leak.py（LEAK_PATTERNS）。
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from specs import _bootstrap

_bootstrap.ensure()

from specs._benchlite import iter_jsonl
from specs._leak import LEAK_PATTERNS  # 六族正则单源——勿复制防口径漂移

# 刻意私有 API 依赖（code_deps 声明钉死）：
from texlate.align import _category, extract_landmarks
from texlate.textutil import safe_is_file
from texlate.xlat.glossary import (
    _TERM_BOUNDARY,
    LOCAL_GLOSSARY_NAME,  # noqa: F401 — 刻意再导出（spec 侧 local 层锚名）
    Glossary,
    TermEntry,
    load_table,
)

CORPUS = Path(__file__).resolve().parents[2] / "corpus"

#: 术语指标只对真 LLM 臂有意义（mock/sabotage/perturb 译文是 echo/扰动占位）。
TERM_ARMS = frozenset({"real"})

#: 术语重建时禁用用户层——机器相关的 ~/.texlate/glossary.yaml 会让跨机
#: 后算口径漂移；local 层（论文自带 glossary.local.yaml）保留，它是语料属性。
_NO_USER_GLOSSARY = Path("/__texlate_bench_no_user_glossary__.yaml")


def _latest_by(rows, key):
    """末条胜去重（benchlib.latest_by 的最小语义——插入序 dict 覆写）。"""
    out = {}
    for r in rows:
        out[key(r)] = r
    return out


def _iter_jsonl(path: Path):
    """OSError 容忍（缺席/截尾）+ 坏行跳过——benchlib.iter_jsonl 薄转。"""
    try:
        yield from iter_jsonl(path)
    except OSError:
        return


def load_cat_groups(manifest_paths=None) -> dict:
    """manifest*.jsonl → {canon_id: cat_group}；缺省 glob corpus/manifest*.jsonl。

    canon 归一经 idnorm.canon_id（raw/canon 两形混存兼容——mixed-id-forms
    教训）；manifest 集是 repo tracked 语料属性，不进 cell fp（口径漂移
    无指纹痕迹——已接受的 dossier 风险）。
    """
    from kernel import idnorm

    if manifest_paths is None:
        manifest_paths = sorted(CORPUS.glob("manifest*.jsonl"))
    out: dict[str, str] = {}
    for mp in manifest_paths:
        for row in _iter_jsonl(Path(mp)):
            if not isinstance(row, dict) or not row.get("id"):
                continue
            res = idnorm.canon_id(str(row["id"]))
            key = res.idc if res.ok and res.idc else str(row["id"])
            cg = row.get("cat_group")
            out[key] = str(cg) if cg else ""
    return out


# ---------------------------------------------------------------- 结构期望计数
# 剥注释后对编译树 *.tex(+*.bbl) 计数。编号公式 env 不带 *（* 形无编号不产生
# dest）；float env 含 * 形（figure* 仍出 hyperref 锚）。section 系含 \appendix
# 以外的全体节令（\appendix 无标题参，不产 dest）。
_COMMENT_RX = re.compile(r"(?<!\\)%.*")
_EXPECTED_TEX_RX = {
    "section": re.compile(
        r"\\(?:section|subsection|subsubsection|paragraph|subparagraph|chapter|part)"
        r"\*?\s*[\[{]"
    ),
    "figtable": re.compile(
        r"\\begin\s*\{\s*(?:figure|table|figtable|sidewaysfigure|sidewaystable"
        r"|wrapfigure|wraptable)\*?\s*\}"
    ),
    "equation": re.compile(
        r"\\begin\s*\{\s*(?:equation|align|gather|multline|eqnarray|flalign"
        r"|alignat|dmath)\s*\}"
    ),
    "footnote": re.compile(r"\\footnote\s*[\[{]"),
}
_BIBITEM_RX = re.compile(r"\\bibitem\b")
#: hyperref/书签类包在场判定——n_dests==0 时区分「从未产锚」与「锚全丢」。
_HYPERREF_RX = re.compile(
    r"\\(?:usepackage|RequirePackage)(?:\s*\[[^\]]*\])?\s*\{[^}]*"
    r"(?:hyperref|bookmark|hypcap)[^}]*\}"
)


def _strip_comments(text: str) -> str:
    return "\n".join(_COMMENT_RX.sub("", line) for line in text.splitlines())


def expected_landmarks(tex_root: Path) -> dict | None:
    """编译树结构期望计数 + hyperref 在场标记；root 缺席/零文件 → None。"""
    if not tex_root.is_dir():
        return None
    counts = dict.fromkeys(_EXPECTED_TEX_RX, 0)
    counts["cite"] = 0
    n_files = 0
    hyperref = False
    for fp in sorted(tex_root.rglob("*")):
        if fp.suffix.lower() not in (".tex", ".bbl") or not fp.is_file():
            continue
        try:
            text = _strip_comments(fp.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        n_files += 1
        hyperref = hyperref or bool(_HYPERREF_RX.search(text))
        for cat, rx in _EXPECTED_TEX_RX.items():
            counts[cat] += len(rx.findall(text))
        counts["cite"] += len(_BIBITEM_RX.findall(text))
    if not n_files:
        return None
    return {"counts": counts, "hyperref": hyperref, "n_files": n_files}


def landmark_metrics(pdf: Path, tex_root: Path | None) -> dict:
    """pdf 锚点分桶计数 + 期望数 + 各类存活比（期望 0 → None，不捏造 1.0）。

    ``coverage`` = 已插桩类别（section/figtable/equation/cite/footnote）的
    dests 合计 ÷ 期望合计——``other`` 桶（theorem./item./自定义名）不进
    分子，防止非标准 dest 名把存活率顶高（1907.03768 实测 43 个 other
    dest 会把全锚丢失掩盖成 0.70）。
    """
    lm = extract_landmarks(pdf)
    dests: dict[str, int] = {}
    for name in lm["dests"]:
        cat = _category(name)
        dests[cat] = dests.get(cat, 0) + 1
    exp_doc = expected_landmarks(tex_root) if tex_root else None
    expected = exp_doc["counts"] if exp_doc else None
    density: dict[str, float | None] = {}
    for cat in sorted(set(dests) | set(expected or {})):
        exp = (expected or {}).get(cat, 0)
        density[cat] = round(dests.get(cat, 0) / exp, 4) if exp else None
    n_expected = sum(expected.values()) if expected else 0
    n_dests = sum(dests.values())
    matched = sum(dests.get(c, 0) for c in _EXPECTED_TEX_RX) + dests.get("cite", 0)
    return {
        "pdf": pdf.name,
        "npages": lm["npages"],
        "n_dests": n_dests,
        "dests": dict(sorted(dests.items())),
        "expected": expected,
        "n_expected": n_expected,
        "hyperref": exp_doc["hyperref"] if exp_doc else None,
        "density": dict(sorted(density.items())),
        "coverage": round(matched / n_expected, 4) if n_expected else None,
        "density_all": round(n_dests / n_expected, 4) if n_expected else None,
    }


# ---------------------------------------------------------------- leak / term
def scan_leak(pairs: list[tuple[str, str]]) -> dict:
    """``(chunk_id, source)`` → parsebench 同口径六族泄漏扫描。"""
    hits = dict.fromkeys(LEAK_PATTERNS, 0)
    leaked = 0
    examples = []
    for cid, src in pairs:
        found = [name for name, rx in LEAK_PATTERNS.items() if rx.search(src)]
        if not found:
            continue
        leaked += 1
        for f in found:
            hits[f] += 1
        if len(examples) < 5:
            examples.append({"chunk_id": cid, "leaks": found})
    n = len(pairs)
    return {
        "leak_n": leaked,
        "leak_total": n,
        "leak_rate": round(leaked / n, 4) if n else None,
        "leak_hits": hits,
        "leak_examples": examples,
    }


@functools.cache
def _term_base(cat_group: str) -> Glossary:
    """cat_group → 非 local 层基底 Glossary（user 禁层 + category + default）。

    index.yaml/category csv/default.csv 在同 cat_group 下恒定——原逐篇
    ``Glossary.load`` 全量重读是纯磁盘+解析重复；每组缓存一份，逐篇只剩
    local 层叠加 + doc_filter。thread executor 下进程内共享正确。
    """
    return Glossary.load(
        user_path=_NO_USER_GLOSSARY,
        categories=(cat_group,) if cat_group else (),
    )


def rebuild_term_dict(
    cat_group: str | None, sources: list[str], local_path: Path | None
) -> dict[str, str]:
    """重建 server 口径注入术语集（doc_filter 后），缺席层自动跳过。

    层序保持 ``Glossary.load`` 的「先写者胜」优先级：local（论文自带）
    高于 category/default——故逐篇先写 local 表，基底词经 ``setdefault``
    只补空缺，绝不压 local。
    """
    terms: dict[str, TermEntry] = {}
    if local_path is not None and safe_is_file(local_path):
        for en, zh in load_table(local_path).items():
            terms.setdefault(en, TermEntry(en, zh, "local"))
    for en, entry in _term_base(cat_group or "").terms.items():
        terms.setdefault(en, entry)
    return Glossary(terms=terms).doc_filter(sources)


def score_terms(pairs: list[tuple[str, str, str]], term_dict: dict[str, str]) -> dict:
    """``(chunk_id, source, translation)`` → 逐 chunk 术语命中核算。

    applicable = 已交付 chunk 的 source 命中术语 en 的 (chunk,term) 对数；
    hit = 对应 translation 含 zh。``term_misses`` 截 10 条供归因。
    """
    compiled = [
        (
            en,
            zh,
            re.compile(_TERM_BOUNDARY.format(re.escape(en)), re.IGNORECASE | re.ASCII),
        )
        for en, zh in term_dict.items()
    ]
    applicable = hit = 0
    misses = []
    for cid, src, zh_out in pairs:
        for en, zh, rx in compiled:
            if not rx.search(src):
                continue
            applicable += 1
            if zh in zh_out:
                hit += 1
            elif len(misses) < 10:
                misses.append({"en": en, "zh": zh, "chunk_id": cid})
    return {
        "term_applicable": applicable,
        "term_hit": hit,
        "term_hit_rate": round(hit / applicable, 4) if applicable else None,
        "term_misses": misses,
        "term_dict_size": len(term_dict),
    }


# ---------------------------------------------------------------- state 读取
def _state_pairs(state_path: Path) -> list[tuple[str, dict]]:
    """state.json ``results[]`` → ``(chunk_id, row)`` 末条胜（续跑重试幂等）。"""
    doc = json.loads(state_path.read_text(encoding="utf-8", errors="replace"))
    rows = doc.get("results") or []
    keyed = [r for r in rows if isinstance(r, dict) and r.get("chunk_id")]
    return list(_latest_by(keyed, lambda r: str(r.get("chunk_id"))).items())


def xlat_metrics(
    state_dir: Path,
    arm: str,
    cat_group: str | None,
    local_glossary: Path | None,
    *,
    term_dict: dict | None = None,
    allow_rebuild: bool = True,
) -> tuple[dict | None, str | None]:
    """state 目录 → (translate 子树 patch, 缺失原因)。

    ``state_dir`` 由调用方解析（v2 = vault.restore 物化的
    ``state.{arm}[@{variant}]/``；state.json/term_dict.json 在目录根）。

    term 口径优先级（dossier：wired run 的真实注入表 > 假设重建表）：

    - ``term_dict``（state 目录内持久化 term_dict.json 读出）在场 →
      直接 score_terms——测「实际注入的一致率」；
    - 缺席且 ``allow_rebuild`` → rebuild_term_dict 重建——「若按 server
      口径注入应一致」的假设代理；
    - 缺席且禁重建 → term_* null + ``term_note=rebuild_disabled``。
    非 ``TERM_ARMS`` 臂恒 null 键（形状恒定）。
    """
    state_path = state_dir / "state.json"
    if not state_path.is_file():
        return None, "state_missing"
    try:
        dedup = _state_pairs(state_path)
    except (json.JSONDecodeError, OSError) as e:
        return None, f"state_bad:{type(e).__name__}"
    pairs = [(cid, str(r.get("source") or "")) for cid, r in dedup]
    patch = scan_leak(pairs)
    if arm in TERM_ARMS:
        delivered = [
            (cid, str(r.get("source") or ""), str(r.get("translation") or ""))
            for cid, r in dedup
            if r.get("status") in ("ok", "partial") and r.get("translation")
        ]
        try:
            if term_dict is not None:
                td = {str(k): str(v) for k, v in dict(term_dict).items()}
            elif allow_rebuild:
                td = rebuild_term_dict(
                    cat_group, [s for _c, s, _t in delivered], local_glossary
                )
            else:
                td = None
            if td is None:
                patch.update(
                    {
                        "term_applicable": None,
                        "term_hit": None,
                        "term_hit_rate": None,
                        "term_misses": [],
                        "term_dict_size": None,
                        "term_note": "rebuild_disabled",
                    }
                )
            else:
                patch.update(score_terms(delivered, td))
        except Exception as e:
            # 观测件不毁账（soak 同款 suppress——重建失败记 note 不落 error 格）
            patch.update(
                {
                    "term_applicable": None,
                    "term_hit": None,
                    "term_hit_rate": None,
                    "term_misses": [],
                    "term_dict_size": None,
                    "term_note": f"rebuild_failed:{type(e).__name__}",
                }
            )
    else:
        patch.update(
            {
                "term_applicable": None,
                "term_hit": None,
                "term_hit_rate": None,
                "term_misses": [],
                "term_dict_size": None,
            }
        )
    return {"translate": patch}, None


def compile_metrics(
    build_dir: Path, main_rel: str | None
) -> tuple[dict | None, str | None]:
    """已物化的编译树目录 → (landmark 子树 patch, 缺失原因)。

    pdf 定位链：main_rel 词干.pdf → 顶层最新 mtime *.pdf 兜底（旧
    _compile_metrics 同名逻辑；arm→目录名映射在 v2 由 vault credential
    取代，调用方解析）。
    """
    if not build_dir.is_dir():
        return None, "build_missing"
    pdf = None
    if main_rel:
        cand = build_dir / (Path(main_rel).stem + ".pdf")
        if cand.is_file():
            pdf = cand
    if pdf is None:
        pdfs = [p for p in build_dir.glob("*.pdf") if p.is_file()]
        if pdfs:
            pdf = max(pdfs, key=lambda p: p.stat().st_mtime)
    if pdf is None:
        return None, "no_pdf"
    try:
        return {"landmark": landmark_metrics(pdf, build_dir)}, None
    except Exception as e:
        return None, f"landmark_bad:{type(e).__name__}"
