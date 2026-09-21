#!/usr/bin/env python3
r"""defect_ledger.py — 缺陷台账机读化：fuzz findings + 人工总账 → jsonl/md 调度底账。

输入（只读）：
  tmp/{glossary,client,judge,engine}-fuzz/findings.txt    老四波 fuzz 台账（文本格式）
  tmp/{arxiv,validate}-fuzz/findings.jsonl                新波 jsonl 台账（B9/B8）
  tmp/fuzz-{texlog,xlat-batch}/findings.jsonl             新波 jsonl 台账（B10/B11，
    xlat-batch 同目录老波 findings.txt 由 jsonl 取代——同条目机读版，不重复收）
  docs/log/roadmap-2026-09-17/inputs/defect-ledger.md 人工总账（P0/P1/P2 + 核销表）
  tests/test_fuzz_*.py  活钉扫描（status 运行态判定；texlog+align/validate 一 lane 合扫两文件）

status 口径：pinned=开口项（活钉或未修台账项）、fixed=已核销/钉已拆/已标
[FIXED]、wontfix=观测行为钉（裁决非缺陷，勿修——修了绿钉转红）。

status 判定优先级（txt findings 条目）：
  1. 头部 marker：`[FIXED]`→fixed、`[..PENDING..]`→pinned、`[WONTFIX]`→wontfix
  2. xfail 装饰块内引用在 → pinned（红钉仍红）
  3. assert 区开钉信号（`PIN:`/`待修` 注释）→ pinned（绿钉仍在）
  4. 任意区「已修/FIXED/修复/回归」信号 → fixed（回归守卫/台账已翻）
  5. CONFIRMED 无任何引用 → fixed（钉已拆）；PLAUSIBLE 无引用 → pinned（裁决未落）

jsonl 波 status 对账（条目自带 status/pin_kind/pin_refs 台账声明）：
  钉扫描是运行态事实、台账 status 是声明——扫描出 xfail/open → pinned、
  fixedsig → fixed 压台账自述；扫描静默时台账自述生效（status=partial 归一
  pinned）；声明 vs 扫描冲突、pin_refs 行号漂移/无 token 锚，记 --check
  「台账 vs 钉扫描」对账差，不报错不拦。

pin_kind：xfail-strict=红钉、assert=绿钉（钉现行缺陷行为）、regression=
修后回归守卫引用、doc=仅 docstring 台账、none=无引用。

用法：
  python3 bench/py/report/defect_ledger.py --json           # 全量条目 jsonl → stdout
  python3 bench/py/report/defect_ledger.py --md             # markdown 表 → stdout（可贴回总账）
  python3 bench/py/report/defect_ledger.py --check          # 对账报告（条数/无钉 CONFIRMED）
  python3 bench/py/report/defect_ledger.py --write          # jsonl 落 tmp/defect-ledger/ledger.jsonl
  python3 bench/py/report/defect_ledger.py --json --out P   # 另写一份到 P

纯 stdlib，系统 python3 直跑（不 import texlate.*）。
status_panel 接入提案（status_panel.py 非本 lane owned，未实装）：
  新增 sec_defects() collector 读 ``tmp/defect-ledger/ledger.jsonl``——
  逐行 json.loads 的现成模式见 tasks()/n200_stats()；渲染 status==pinned
  按 lane 分组的计数+表即可。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LEDGER_MD = REPO / "docs/log/roadmap-2026-09-17/inputs/defect-ledger.md"
DEFAULT_OUT = REPO / "tmp" / "defect-ledger" / "ledger.jsonl"
DATE = "2026-09-17"

# lane → 测试文件组 / ID token / 归属 / 燃烧批 lane；fmt=jsonl 走逐行 json 台账
# （texlog+align/validate 一 lane 两测试文件合扫；xlat-residual 的 findings 目录下
# 另有老波 findings.txt——jsonl 为同条目机读版，优先 jsonl 不重复收）
LANE_META = {
    "glossary": {
        "tests": ["tests/test_fuzz_glossary.py"],
        "tok": r"D\d+",
        "owner": "xlat",
        "burn": "B2",
    },
    "client": {
        "tests": ["tests/test_fuzz_xlat_client.py"],
        "tok": r"[CP]\d+",
        "owner": "xlat",
        "burn": "B3",
    },
    "judge": {
        "tests": ["tests/test_fuzz_judge.py"],
        "tok": r"J\d+[ab]?|O\d+",
        "owner": "compile",
        "burn": "B4",
    },
    "engine": {
        "tests": ["tests/test_fuzz_engine.py"],
        "tok": r"D\d+",
        "owner": "compile",
        "burn": "B5",
    },
    "arxiv": {
        "tests": ["tests/test_fuzz_arxiv.py"],
        "tok": r"[DP]\d+",
        "owner": "arxiv",
        "burn": "B9",
        "fmt": "jsonl",
        "findings": "tmp/arxiv-fuzz/findings.jsonl",
    },
    "validate": {
        "tests": ["tests/test_fuzz_validate.py", "tests/test_fuzz_validate_l2.py"],
        "tok": r"[DPQ]\d+",
        "owner": "validate",
        "burn": "B8",
        "fmt": "jsonl",
        "findings": "tmp/validate-fuzz/findings.jsonl",
    },
    "texlog+align": {
        "tests": ["tests/test_fuzz_texlog.py", "tests/test_fuzz_align.py"],
        "tok": r"[DPQ]\d+",
        "owner": "texlate",
        "burn": "B10",
        "fmt": "jsonl",
        "findings": "tmp/fuzz-texlog/findings.jsonl",
    },
    "xlat-residual": {
        "tests": ["tests/test_fuzz_xlat_residual.py"],
        "tok": r"[DPO]\d+",
        "owner": "xlat",
        "burn": "B11",
        "fmt": "jsonl",
        "findings": "tmp/fuzz-xlat-batch/findings.jsonl",
    },
}
LANE_ORDER = [
    "glossary",
    "client",
    "judge",
    "engine",
    "arxiv",
    "validate",
    "texlog+align",
    "xlat-residual",
    "ledger-code",
    "ledger-scout",
    "ledger-cleared",
]


def _findings_path(lane: str) -> Path:
    meta = LANE_META[lane]
    return REPO / meta.get("findings", f"tmp/{lane}-fuzz/findings.txt")


# 手工对账期望（findings.txt 自述数，以文件实内容为准）
EXPECT = {
    ("glossary", "CONFIRMED"): 9,
    ("client", "CONFIRMED"): 7,
    ("client", "PLAUSIBLE"): 12,
    ("judge", "CONFIRMED"): 4,
    ("judge", "OBSERVED"): 5,
    ("engine", "CONFIRMED"): 9,
    ("engine", "TESTBUG"): 7,
}

# findings 文本缺 per-item site 时的符号级落点（运行态找 def 行，防漂移）
GLOSSARY_SYM = {
    "D1": ("src/texlate/repair.py", "resolve_glossary_path"),
    "D2": ("src/texlate/repair.py", "resolve_glossary_path"),
    "D9": ("src/texlate/repair.py", "resolve_glossary_path"),
    "D3": ("src/texlate/xlat/glossary.py", "flatten_terms"),
    "D4": ("src/texlate/xlat/glossary.py", "load_index"),
    "D5": ("src/texlate/xlat/glossary.py", "load_csv"),
    "D6": ("src/texlate/xlat/glossary.py", "load_csv"),
    "D7": ("src/texlate/xlat/placeholders.py", "sort_key"),
    "D8": ("src/texlate/xlat/glossary.py", "load"),
}
SEV_OVERRIDE = {
    ("glossary", "D4"): "P2",
    ("glossary", "D6"): "P2",
}  # findings 标 潜伏/quirk

_SITE_RE = re.compile(r"([\w./-]+\.py):(\d+)")
_OPEN_SIG_RE = re.compile(r"PIN:|待修|缺陷待修")
# 「D# 回归」/「D# 回归守卫」是新波钉转回归守卫的标记语——与「已修/修复」同效；
# 老四波测试文件里「回归+token」行均同时含「修复」，加词不改变老 lane 判定。
_FIXED_SIG_RE = re.compile(r"已修|FIXED|修复|回归")
# xfail 装饰起点：老波直写 pytest.mark.xfail，新波经 _fuzzkit.xfail_confirmed 包
_XFAIL_LINE_RE = re.compile(r"pytest\.mark\.xfail|@xfail_confirmed\b")
_SEARCH_ROOTS = ["src", "tests", "bench/py", "web/src", "scripts"]
_file_cache: dict[str, str | None] = {}

# jsonl 台账声明归一：partial=部分修复（钉仍在）归 pinned；合法集外值记 warning
_STATUS_NORM = {"partial": "pinned"}
_VALID_STATUS = {"pinned", "fixed", "wontfix"}
_VALID_PIN_KIND = {"xfail-strict", "assert", "regression", "doc", "none"}
_PIN_REF_RE = re.compile(r"^([\w./-]+\.py):(\d+)$")


def resolve_file(tok: str) -> str | None:
    """把 `x.py`/`dir/x.py` 解析成仓内路径；basename 经限定根 rglob 反查。"""
    tok = tok.lstrip("./")
    if tok in _file_cache:
        return _file_cache[tok]
    res: str | None = None
    if (REPO / tok).is_file():
        res = tok
    else:
        name = Path(tok).name
        hits = []
        for root in _SEARCH_ROOTS:
            r = REPO / root
            if r.is_dir():
                hits += [p for p in r.rglob(name) if p.is_file()]
        if hits:
            tail = tok.replace("\\", "/")
            exact = [p for p in hits if p.relative_to(REPO).as_posix().endswith(tail)]
            pick = min(exact or hits, key=lambda p: len(p.parts))
            res = pick.relative_to(REPO).as_posix()
    _file_cache[tok] = res
    return res


def find_def(rel: str, symbol: str) -> str | None:
    """文件里 `def symbol` / `symbol =` 的行号 → `file:line`。"""
    path = REPO / rel
    if not path.is_file():
        return None
    pat = re.compile(
        rf"^\s*(?:async\s+)?def\s+{re.escape(symbol)}\b|^{re.escape(symbol)}\s*="
    )
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if pat.match(line):
            return f"{rel}:{n}"
    return None


def site_from(text: str) -> str | None:
    """取文本里第一个能解析到仓内文件的 `x.py:NN`（无行号则退 bare `x.py`）。"""
    for m in _SITE_RE.finditer(text):
        f = resolve_file(m.group(1))
        if f:
            return f"{f}:{m.group(2)}"
    for m in re.finditer(r"([\w./-]+\.py)\b", text):
        f = resolve_file(m.group(1))
        if f:
            return f
    return None


def slice_section(text: str, start: str, ends: list[str]) -> str:
    lines = text.splitlines()
    i = next((n for n, ln in enumerate(lines) if re.search(start, ln)), None)
    if i is None:
        return ""
    j = next(
        (
            n
            for n, ln in enumerate(lines[i + 1 :], i + 1)
            if any(re.search(e, ln) for e in ends)
        ),
        len(lines),
    )
    return "\n".join(lines[i + 1 : j])


def split_entries(sec: str, id_re: str) -> list[tuple[str, str]]:
    """`ID␣+标题` 起头的缺陷条目切块 → [(id, 全文体)]。

    条目体行一律缩进，行首 `ID␣` 只可能是新条目头；ID 双位时作者
    用单空格对齐（P10/P11/P12），故接受 1+ 空白。
    """
    out, cur, buf = [], None, []
    for line in sec.splitlines():
        m = re.match(rf"^({id_re})[ \t]+(\S.*)", line)
        if m:
            if cur:
                out.append((cur, "\n".join(buf)))
            cur, buf = m.group(1), [line]
        elif cur:
            buf.append(line)
    if cur:
        out.append((cur, "\n".join(buf)))
    return out


def split_bullets(sec: str) -> list[str]:
    """`- ` 起头的 bullet 切块（跨行续行拍平成一行）。"""
    out, buf = [], []
    for line in sec.splitlines():
        if re.match(r"^- ", line):
            if buf:
                out.append(" ".join(buf))
            buf = [line[2:].strip()]
        elif buf:
            buf.append(line.strip())
    if buf:
        out.append(" ".join(buf))
    return [re.sub(r"\s+", " ", b).strip() for b in out if b.strip()]


def _norm_tok(lane: str, tok: str) -> str:
    return re.sub(r"([A-Z]\d+)[ab]$", r"\1", tok) if lane == "judge" else tok


def _add_ref(
    refs: dict[str, dict[str, list[str]]],
    lane: str,
    rel: str,
    tok: str,
    kind: str,
    lineno: int,
) -> None:
    slot = refs.setdefault(_norm_tok(lane, tok), {}).setdefault(kind, [])
    ref = f"{rel}:{lineno}"
    if ref not in slot:
        slot.append(ref)


def scan_refs(lane: str) -> dict[str, dict[str, list[str]]]:
    """扫 lane 测试文件组 → {id: {xfail/open/fixedsig/doc/mention: [file:line]}}。

    - xfail：@pytest.mark.xfail / @xfail_confirmed 装饰块内引用（红钉仍红）
    - open：代码区 `PIN:`/`待修` 注释引用（绿钉钉现行缺陷）
    - fixedsig：任意区「已修/FIXED/修复/回归」引用（回归守卫/已翻台账）
    - doc：模块 docstring 台账区引用（历史记录）
    - mention：其余代码区引用（中性，不计入钉判定）

    多测试文件 lane（texlog+align）合扫两文件钉位；ref 自带文件前缀。
    """
    meta = LANE_META[lane]
    refs: dict[str, dict[str, list[str]]] = {}
    for rel in meta["tests"]:
        path = REPO / rel
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        doc_end = -1
        if lines and re.match(r'^(?:[rbuf]+)?"""', lines[0].strip()):
            if lines[0].count('"""') >= 2:
                doc_end = 0
            else:
                for n in range(1, len(lines)):
                    if '"""' in lines[n]:
                        doc_end = n
                        break
        i = 0
        while i < len(lines):
            line = lines[i]
            if _XFAIL_LINE_RE.search(line):
                j = i
                while j < len(lines) and not re.search(r"\bdef\s", lines[j]):
                    j += 1
                for tok in set(re.findall(meta["tok"], "\n".join(lines[i : j + 1]))):
                    _add_ref(refs, lane, rel, tok, "xfail", i + 1)
                i = j + 1
                continue
            for tok in set(re.findall(meta["tok"], line)):
                if _FIXED_SIG_RE.search(line):
                    _add_ref(refs, lane, rel, tok, "fixedsig", i + 1)
                elif i <= doc_end:
                    _add_ref(refs, lane, rel, tok, "doc", i + 1)
                elif _OPEN_SIG_RE.search(line):
                    _add_ref(refs, lane, rel, tok, "open", i + 1)
                else:
                    _add_ref(refs, lane, rel, tok, "mention", i + 1)
            i += 1
    return refs


def _pin_kind(rinfo: dict[str, list[str]] | None) -> str:
    if not rinfo:
        return "none"
    if rinfo.get("xfail"):
        return "xfail-strict"
    if rinfo.get("open"):
        return "assert"
    if rinfo.get("fixedsig"):
        return "regression"
    if rinfo.get("doc"):
        return "doc"
    return "none"


def _pin_refs(rinfo: dict[str, list[str]] | None) -> list[str]:
    """钉引用出参：xfail 全量 + open 截 4 + fixedsig 截 2（ref 已带文件前缀）。"""
    if not rinfo:
        return []
    out = list(rinfo.get("xfail", []))
    out += rinfo.get("open", [])[:4]
    out += rinfo.get("fixedsig", [])[:2]
    return out


def _scan_status(rinfo: dict[str, list[str]] | None) -> str | None:
    """钉扫描运行态：活钉 → pinned、fixedsig → fixed、无钉证据 → None。"""
    if not rinfo:
        return None
    if rinfo.get("xfail") or rinfo.get("open"):
        return "pinned"
    if rinfo.get("fixedsig"):
        return "fixed"
    return None


def _mk(lane, eid, sev, grade, status, site, owner, summary, **kw) -> dict:
    return {
        "lane": lane,
        "id": eid,
        "severity": sev,
        "grade": grade,
        "status": status,
        "pin_kind": kw.get("pin_kind", "none"),
        "site": site or "",
        "pin_refs": kw.get("pin_refs", []),
        "owner": owner,
        "burn": kw.get("burn", ""),
        "summary": re.sub(r"\s+", " ", summary).strip(),
        "fix_ref": kw.get("fix_ref", ""),
        "fix_note": kw.get("fix_note", ""),
        "source": kw.get("source", ""),
    }


def _head_marker(body: str) -> str | None:
    """条目中首个含 FIXED/PENDING/WONTFIX 的 `[...]` marker → status。

    marker 位置不拘：glossary/judge 在标题行尾，engine 在条目体中段。
    `【...】` 全角括号与 `["x"]` 类字面不会误命中（关键词过滤）。
    """
    m = re.search(r"\[([^\]]*(?:FIXED|PENDING|WONTFIX|OBSERVED|已修)[^\]]*)\]", body)
    if not m:
        return None
    tag = m.group(1).upper()
    if "PENDING" in tag or "WIP" in tag:
        return "pinned"
    if "WONTFIX" in tag or "OBSERVED" in tag:
        return "wontfix"
    return "fixed"


def parse_findings(lane: str, refs: dict[str, dict[str, list[str]]]) -> list[dict]:
    path = _findings_path(lane)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    meta = LANE_META[lane]
    src = path.relative_to(REPO).as_posix()
    out: list[dict] = []

    def entry(eid: str, body: str, grade: str) -> dict:
        header = body.splitlines()[0]
        title = re.sub(rf"^{re.escape(eid)}\s+", "", header).strip()
        title = re.sub(
            r"\s*\[[^\]]*(FIXED|PENDING|WONTFIX|OBSERVED)[^\]]*\]", "", title
        )
        site = site_from(body)
        if lane == "glossary" and eid in GLOSSARY_SYM:
            site = find_def(*GLOSSARY_SYM[eid]) or site
        sev = SEV_OVERRIDE.get((lane, eid)) or ("P1" if grade == "CONFIRMED" else "P2")
        rinfo = refs.get(eid)
        kind = _pin_kind(rinfo)
        fix_note = ""
        if fm := re.search(r"→\s*修：([^\n]+)", body):
            fix_note = fm.group(1).strip()
        marked = _head_marker(body)
        if grade == "OBSERVED":
            status = "wontfix"
        elif grade == "TESTBUG":
            status = "fixed"
        elif marked:
            status = marked
        elif rinfo and (rinfo.get("xfail") or rinfo.get("open")):
            status = "pinned"
        elif rinfo and rinfo.get("fixedsig"):
            status = "fixed"
        elif grade == "PLAUSIBLE":
            status = "pinned"  # 裁决未落——留着调度
        else:  # CONFIRMED 无任何活钉 → 钉已拆 = fixed
            status = "fixed"
        return _mk(
            lane,
            eid,
            sev,
            grade,
            status,
            site,
            meta["owner"],
            title,
            pin_kind=kind,
            pin_refs=_pin_refs(rinfo),
            burn=meta["burn"],
            fix_note=fix_note,
            source=src,
        )

    if lane == "glossary":
        for eid, body in split_entries(
            slice_section(text, r"CONFIRMED DEFECTS", [r"^OBSERVED QUIRKS"]), r"D\d+"
        ):
            out.append(entry(eid, body, "CONFIRMED"))
        for n, b in enumerate(
            split_bullets(slice_section(text, r"^OBSERVED QUIRKS", [r"^COVERAGE MAP"])),
            1,
        ):
            grade = "PLAUSIBLE" if "PLAUSIBLE" in b else "OBSERVED"
            out.append(entry(f"Q{n}", b, grade))
    elif lane == "client":
        for eid, body in split_entries(
            slice_section(text, r"CONFIRMED DEFECTS", [r"^PLAUSIBLE / OBSERVED"]),
            r"C\d+",
        ):
            out.append(entry(eid, body, "CONFIRMED"))
        for eid, body in split_entries(
            slice_section(text, r"^PLAUSIBLE / OBSERVED", [r"^COVERAGE MAP"]), r"P\d+"
        ):
            out.append(entry(eid, body, "PLAUSIBLE"))
    elif lane == "judge":
        for eid, body in split_entries(
            slice_section(text, r"CONFIRMED 缺陷", [r"观测语义钉"]), r"J\d+"
        ):
            out.append(entry(eid, body, "CONFIRMED"))
        for eid, body in split_entries(
            slice_section(text, r"观测语义钉", [r"探针笔记"]), r"O\d+"
        ):
            out.append(entry(eid, body, "OBSERVED"))
    elif lane == "engine":
        for eid, body in split_entries(
            slice_section(text, r"CONFIRMED 缺陷账", [r"测试自体 bug"]), r"D\d+"
        ):
            out.append(entry(eid, body, "CONFIRMED"))
        for n, b in enumerate(
            split_bullets(slice_section(text, r"测试自体 bug", [r"覆盖摘要"])), 1
        ):
            out.append(entry(f"T{n}", b, "TESTBUG"))
    return out


def _grade_fallback(grade: str) -> str:
    """无钉无声明时的兜底——同 txt 波口径（CONFIRMED 钉已拆、PLAUSIBLE 裁决未落）。"""
    return {"OBSERVED": "wontfix", "TESTBUG": "fixed", "PLAUSIBLE": "pinned"}.get(
        grade, "fixed" if grade == "CONFIRMED" else "pinned"
    )


_file_len_cache: dict[str, int] = {}


def _test_file_len(rel: str) -> int:
    if rel not in _file_len_cache:
        path = REPO / rel
        _file_len_cache[rel] = (
            len(path.read_text(encoding="utf-8").splitlines()) if path.is_file() else 0
        )
    return _file_len_cache[rel]


def parse_findings_jsonl(
    lane: str, refs: dict[str, dict[str, list[str]]], recon: dict
) -> list[dict]:
    """jsonl 台账逐行解析——条目自带 status/pin_kind/pin_refs 声明。

    运行态钉扫描压台账自述（xfail/open→pinned、fixedsig→fixed）；扫描静默
    时声明生效。声明 vs 扫描冲突、pin_refs 漂移/越界/指 lane 外记
    recon["disc"]；坏 json 行/缺字段记 recon["warn"] 继续，不炸全表。
    """
    meta = LANE_META[lane]
    path = _findings_path(lane)
    src = path.relative_to(REPO).as_posix()
    out: list[dict] = []
    if not path.is_file():
        recon["warn"].append(f"{lane}: findings 缺席 {src}")
        return out
    lines = path.read_text(encoding="utf-8").splitlines()
    recon["jsonl_lines"][lane] = sum(1 for ln in lines if ln.strip())
    test_set = set(meta["tests"])
    for lineno, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError as e:
            recon["warn"].append(f"{src}:{lineno} 坏 json 行（{e.msg}）——跳过")
            continue
        if not isinstance(d, dict):
            recon["warn"].append(f"{src}:{lineno} 非 object 行——跳过")
            continue
        eid = str(d.get("id") or "").strip()
        if not eid:
            recon["warn"].append(f"{src}:{lineno} 缺 id——跳过")
            continue
        grade = str(d.get("grade") or "LEDGER").strip() or "LEDGER"
        raw_status = d.get("status")
        raw_status = raw_status.strip() if isinstance(raw_status, str) else ""
        declared = _STATUS_NORM.get(raw_status, raw_status) or None
        if declared is not None and declared not in _VALID_STATUS:
            recon["warn"].append(
                f"{src}:{lineno} {eid} 未知 status={raw_status}——按无声明"
            )
            declared = None
        rinfo = refs.get(eid)
        status = _scan_status(rinfo) or declared or _grade_fallback(grade)

        decl_kind = d.get("pin_kind")
        decl_kind = decl_kind.strip() if isinstance(decl_kind, str) else ""
        if decl_kind and decl_kind not in _VALID_PIN_KIND:
            recon["warn"].append(
                f"{src}:{lineno} {eid} 未知 pin_kind={decl_kind}——按无声明"
            )
            decl_kind = ""
        decl_refs: list[str] = []
        raw_refs = d.get("pin_refs")
        if isinstance(raw_refs, list):
            for r in raw_refs:
                if isinstance(r, str) and _PIN_REF_RE.match(r):
                    decl_refs.append(r)
                else:
                    recon["warn"].append(
                        f"{src}:{lineno} {eid} pin_refs 项畸形 {r!r}——丢弃"
                    )
        elif raw_refs:
            recon["warn"].append(f"{src}:{lineno} {eid} pin_refs 非 list——按空")

        if rinfo:
            kind, pr = _pin_kind(rinfo), _pin_refs(rinfo)
        else:
            kind, pr = decl_kind or "none", decl_refs

        # 台账声明 vs 钉扫描对账差（扫描=运行态事实，声明=台账自述）
        if raw_status and raw_status != status:
            recon["disc"].append(
                f"{lane}/{eid} status 台账={raw_status} → 运行态={status}"
            )
        if decl_kind and decl_kind != kind:
            recon["disc"].append(
                f"{lane}/{eid} pin_kind 台账={decl_kind} → 扫描={kind}"
            )
        if set(decl_refs) != set(pr):
            stale = sorted(set(decl_refs) - set(pr)) or "∅"
            fresh = sorted(set(pr) - set(decl_refs)) or "∅"
            recon["disc"].append(
                f"{lane}/{eid} pin_refs 漂移 台账独有={stale} 扫描独有={fresh}"
            )
        elif rinfo is None and decl_refs:
            recon["disc"].append(
                f"{lane}/{eid} pin_refs {decl_refs} token 零锚"
                "——行号漂移或非 token 锚，未能证实"
            )
        for r in decl_refs:
            m = _PIN_REF_RE.match(r)
            if not m:
                continue
            f, ln = m.group(1), int(m.group(2))
            if f not in test_set:
                recon["disc"].append(
                    f"{lane}/{eid} ref {r} 不在 lane 测试文件组 {sorted(test_set)}"
                )
            elif (n := _test_file_len(f)) and ln > n:
                recon["disc"].append(f"{lane}/{eid} ref {r} 越界（{f} 现 {n} 行）")

        out.append(
            _mk(
                lane,
                eid,
                str(d.get("severity") or ""),
                grade,
                status,
                str(d.get("site") or ""),
                str(d.get("owner") or meta["owner"]),
                str(d.get("summary") or ""),
                pin_kind=kind,
                pin_refs=pr,
                burn=str(d.get("burn") or meta["burn"]),
                fix_ref=str(d.get("fix_ref") or ""),
                fix_note=str(d.get("fix_note") or ""),
                source=f"{src}#L{lineno}",
            )
        )
    return out


_MD_FIELD_RES = {
    "site": re.compile(r"\*\*位置\*\*：([^。\n]+)"),
    "summary": re.compile(r"\*\*现象\*\*：([^。\n]+)"),
    "sev": re.compile(r"严重度\*\*：\**(?:~~)?\**(P[012])"),
    "owner": re.compile(r"归属\*\*：([^。·\n*]+)"),
}
_FIX_RE = re.compile(r"已核销.{0,60}?([0-9a-f]{7,9})(?![0-9a-f])")
_PAREN_FIX_RE = re.compile(r"（`?([0-9a-f]{7,9})`?[+0-9a-f` ]*）")


def _clean(s: str) -> str:
    return s.replace("~~", "").replace("**", "").strip()


def _fix_ref(text: str) -> str:
    if m := _FIX_RE.search(text):
        return m.group(1)
    if m := _PAREN_FIX_RE.search(text):
        return m.group(1)
    return ""


def _owner_from_site(site: str) -> str:
    """site 路径推归属面：src/texlate/<mod>/ → <mod>；tests/bench → 同名。"""
    m = re.match(r"src/texlate/(\w+)/", site)
    if m:
        return m.group(1)
    if m := re.match(r"(\w+)/", site):
        return {"src": "texlate"}.get(m.group(1), m.group(1))
    return ""


def _ledger_bullet(text: str, lane: str, eid: str, sev_default: str, src: str) -> dict:
    struck = "~~" in text or "已核销" in text
    site_raw = _clean(m.group(1)) if (m := _MD_FIELD_RES["site"].search(text)) else ""
    summary = (
        _clean(m.group(1))
        if (m := _MD_FIELD_RES["summary"].search(text))
        else _clean(text)
    )
    sev = m.group(1) if (m := _MD_FIELD_RES["sev"].search(text)) else sev_default
    owner = _clean(m.group(1)) if (m := _MD_FIELD_RES["owner"].search(text)) else ""
    pin = "assert" if re.search(r"tests/test_\w+\.py|现状钉|xfail", text) else "doc"
    site = site_from(site_raw) or site_from(text) or ""
    if not site and site_raw and not re.search(r"\w+\.\w{2,4}\b", site_raw):
        summary = f"{site_raw}——{summary}"  # 位置是描述而非路径时并入 summary 不丢信息
    elif not site and site_raw:
        site = site_raw  # 形似路径但解析不到（如未来文件名），原样留档
    return _mk(
        lane,
        eid,
        sev,
        "LEDGER",
        "fixed" if struck else "pinned",
        site,
        owner or _owner_from_site(site),
        summary,
        pin_kind=pin,
        fix_ref=_fix_ref(text),
        source=src,
    )


def parse_ledger() -> list[dict]:
    text = LEDGER_MD.read_text(encoding="utf-8")
    src = LEDGER_MD.relative_to(REPO).as_posix()
    out: list[dict] = []

    sec11 = slice_section(text, r"^### 1\.1", [r"^### 1\.2"])
    for n, b in enumerate(split_bullets(sec11), 1):
        out.append(_ledger_bullet(b, "ledger-code", f"code-{n}", "P1", f"{src}#1.1"))

    sec12 = slice_section(text, r"^### 1\.2", [r"^### 1\.3"])
    for n, b in enumerate(split_bullets(sec12), 1):
        e = _ledger_bullet(b, "ledger-code", f"lat-{n}", "P2", f"{src}#1.2")
        e["pin_kind"] = "doc"  # 未钉观察——文档化 latent
        if "非 defect" in b or "不计" in b:
            e["status"] = "wontfix"
        out.append(e)

    out.append(
        _mk(
            "ledger-code",
            "doc-1",
            "P2",
            "LEDGER",
            "pinned",
            "tests/test_fuzz_inject.py",
            "tests/docs",
            "陈旧 pin 文档债：test_fuzz_inject I1-I9 / test_fuzz_xlat / test_app_endpoints / "
            "test_fuzz_mask / test_fuzz_logpipe 头注仍称已修缺陷在钉",
            source=f"{src}#1.3",
        )
    )

    sec21 = slice_section(text, r"^### 2\.1", [r"^### 2\.2"])
    for n, b in enumerate(split_bullets(sec21), 1):
        out.append(
            _ledger_bullet(b, "ledger-scout", f"scout-p1-{n}", "P1", f"{src}#2.1")
        )

    sec22 = slice_section(text, r"^### 2\.2", [r"^### 2\.3", r"^## 3\."])
    for n, b in enumerate(split_bullets(sec22), 1):
        e = _ledger_bullet(b, "ledger-scout", f"scout-p2-{n}", "P2", f"{src}#2.2")
        e["summary"] = _clean(b.split("|")[0])
        if not e["owner"]:
            mo = re.search(r"→\s*(\S+)\s*$", b)
            e["owner"] = mo.group(1) if mo else ""
        out.append(e)

    sec3 = slice_section(text, r"^## 3\.", [r"^## 4\."])
    m = re.search(
        r"retry\.py 新 fuzz 波（`(\w+)`，(\d+) 钉）挂出 (\d+) CONFIRMED \+ (\d+) PLAUSIBLE ([^，。\n]+)",
        sec3,
    )
    if m:
        out.append(
            _mk(
                "ledger-code",
                "retry-wave",
                "P1",
                "LEDGER",
                "pinned",
                "src/texlate/xlat/retry.py",
                "xlat",
                f"retry.py fuzz 波（{m.group(1)}，{m.group(2)} 钉）：{m.group(3)} CONFIRMED + "
                f"{m.group(4)} PLAUSIBLE {_clean(m.group(5))} 待修——明细 report-2026-09-17-final.md §4",
                pin_kind="assert",
                source=f"{src}#3",
            )
        )

    sec4 = slice_section(text, r"^## 4\.", [r"^## \d"])
    fam_text = " ".join(
        ln.strip() for ln in sec4.splitlines() if ln.strip() and not ln.startswith("#")
    )
    fam_text = fam_text.split("——")[0]  # 剥掉尾部「pin 清零机制运转良好」评注
    for n, fam in enumerate((x.strip() for x in re.split(r"、", fam_text)), 1):
        if not fam:
            continue
        out.append(
            _mk(
                "ledger-cleared",
                f"cleared-{n}",
                "",
                "LEDGER",
                "fixed",
                "",
                "",
                fam,
                fix_ref=_fix_ref(fam),
                source=f"{src}#4",
            )
        )
    return out


def collect() -> tuple[list[dict], dict]:
    """→ (entries, recon)；recon = {warn, disc, jsonl_lines} 供 --check 对账。"""
    recon: dict = {"warn": [], "disc": [], "jsonl_lines": {}}
    refs = {lane: scan_refs(lane) for lane in LANE_META}
    entries: list[dict] = []
    for lane, meta in LANE_META.items():
        if meta.get("fmt") == "jsonl":
            entries += parse_findings_jsonl(lane, refs[lane], recon)
        else:
            entries += parse_findings(lane, refs[lane])
    entries += parse_ledger()
    return entries, recon


def _id_key(eid: str) -> tuple:
    m = re.match(r"([A-Za-z-]*?)(\d+)$", eid)
    return (m.group(1), int(m.group(2))) if m else (eid, 0)


def sort_entries(entries: list[dict]) -> list[dict]:
    sev_rank = {"P0": 0, "P1": 1, "P2": 2}
    st_rank = {"pinned": 0, "wontfix": 1, "fixed": 2}
    return sorted(
        entries,
        key=lambda e: (
            LANE_ORDER.index(e["lane"]) if e["lane"] in LANE_ORDER else 9,
            st_rank.get(e["status"], 3),
            sev_rank.get(e["severity"], 3),
            _id_key(e["id"]),
        ),
    )


def render_md(entries: list[dict]) -> str:
    n: dict[str, int] = {}
    for e in entries:
        n[e["status"]] = n.get(e["status"], 0) + 1
    lines = [
        (
            f"> generated：`python3 bench/py/report/defect_ledger.py --md`（{DATE}；"
            f"源=老四波 findings.txt + 新四波 findings.jsonl + 本文件 §1–§4 + tests/ 活钉扫描）"
        ),
        (
            f"> 条目：pinned {n.get('pinned', 0)} · wontfix {n.get('wontfix', 0)} · "
            f"fixed {n.get('fixed', 0)} · 合计 {len(entries)}；"
            f"jsonl 全文 `tmp/defect-ledger/ledger.jsonl`（`--write` 生成）"
        ),
        "",
        "| lane | id | sev | status | pin | site | owner | summary |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in sort_entries(entries):
        cells = [
            e["lane"],
            e["id"],
            e["severity"] or "-",
            e["status"],
            e["pin_kind"],
            f"`{e['site']}`" if e["site"] else "-",
            e["owner"] or "-",
            e["summary"].replace("|", "\\|")[:90],
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_check(entries: list[dict], recon: dict) -> str:
    lines = ["== defect-ledger 对账 ==", ""]
    by_lane: dict[str, list[dict]] = {}
    for e in entries:
        by_lane.setdefault(e["lane"], []).append(e)
    for lane in LANE_ORDER:
        es = by_lane.get(lane, [])
        if not es:
            continue
        grades: dict[str, int] = {}
        stat: dict[str, int] = {}
        for e in es:
            grades[e["grade"]] = grades.get(e["grade"], 0) + 1
            stat[e["status"]] = stat.get(e["status"], 0) + 1
        row = f"{lane:<15} parsed={len(es):<3} grade={grades} status={stat}"
        if (want := recon["jsonl_lines"].get(lane)) is not None:
            row += f"  jsonl自述={want} {'OK' if len(es) == want else 'MISMATCH'}"
        lines.append(row)
    lines.append("")
    mismatches = []
    for (lane, grade), want in sorted(EXPECT.items()):
        got = sum(1 for e in entries if e["lane"] == lane and e["grade"] == grade)
        flag = "OK" if got == want else "MISMATCH"
        if got != want:
            mismatches.append(f"{lane}/{grade}: {got} != {want}")
        lines.append(f"  {lane}/{grade}: parsed={got} 期望={want} {flag}")
    for lane, want in sorted(recon["jsonl_lines"].items()):
        got = len(by_lane.get(lane, []))
        flag = "OK" if got == want else "MISMATCH"
        if got != want:
            mismatches.append(f"{lane}/jsonl: {got} != {want}")
        lines.append(f"  {lane}/jsonl: parsed={got} 自述={want} {flag}")
    open_conf = [
        e for e in entries if e["grade"] == "CONFIRMED" and e["status"] == "pinned"
    ]
    fixed_conf = [
        e for e in entries if e["grade"] == "CONFIRMED" and e["status"] == "fixed"
    ]
    lines += [
        "",
        f"CONFIRMED：pinned {len(open_conf)} · fixed {len(fixed_conf)}",
        "仍开 CONFIRMED（燃烧批调度对象）：",
    ]
    for e in open_conf:
        lines.append(
            f"  {e['lane']}/{e['id']} [{e['pin_kind']}] {e['site']} {e['summary'][:70]}"
        )
    nopin = [
        e
        for e in entries
        if e["grade"] == "CONFIRMED" and e["pin_kind"] in ("none", "doc")
    ]
    nfix = sum(1 for e in nopin if e["status"] == "fixed")
    lines += [
        "",
        (
            f"无钉 CONFIRMED（pin_kind=none/doc）：{len(nopin)}"
            f"（fixed {nfix} · 非fixed {len(nopin) - nfix}"
            "——fixed 为钉已拆正态不逐条列）"
        ),
    ]
    for e in nopin:
        if e["status"] != "fixed":
            lines.append(
                f"  可疑 {e['lane']}/{e['id']} [{e['status']}] {e['site']}"
                f" {e['summary'][:60]}"
            )
    conflicts = [
        e
        for e in entries
        if e["grade"] == "CONFIRMED"
        and e["status"] == "fixed"
        and e["pin_kind"] in ("xfail-strict", "assert")
    ]
    if conflicts:
        lines += ["", "状态冲突（fixed 判但仍有活钉引用，人工核）："]
        for e in conflicts:
            lines.append(f"  {e['lane']}/{e['id']} pin_refs={e['pin_refs']}")
    lines += ["", "台账 status vs 钉扫描 对账差（扫描=运行态事实，不报错只列账）："]
    if recon["disc"]:
        lines += [f"  {d}" for d in recon["disc"]]
    else:
        lines.append("  无")
    if recon["warn"]:
        lines += ["", "warnings:"]
        lines += [f"  {w}" for w in recon["warn"]]
    for meta in LANE_META.values():
        for rel in meta["tests"]:
            tf = REPO / rel
            lines.append(f"  pin-scan {rel}: {'ok' if tf.is_file() else 'MISSING'}")
    if mismatches:
        lines += ["", "MISMATCH: " + "; ".join(mismatches)]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="缺陷台账机读化 → jsonl/md")
    ap.add_argument("--json", action="store_true", help="jsonl → stdout")
    ap.add_argument("--md", action="store_true", help="markdown 表 → stdout")
    ap.add_argument("--check", action="store_true", help="对账报告 → stdout")
    ap.add_argument(
        "--write", action="store_true", help=f"jsonl 落 {DEFAULT_OUT.relative_to(REPO)}"
    )
    ap.add_argument("--out", metavar="P", help="jsonl 另写到 P")
    args = ap.parse_args()
    if not (args.json or args.md or args.check or args.write or args.out):
        ap.print_help()
        return 2

    entries, recon = collect()
    payload = "".join(
        json.dumps(e, ensure_ascii=False) + "\n" for e in sort_entries(entries)
    )

    rc = 0
    if args.check:
        report = render_check(entries, recon)
        print(report)
        if "MISMATCH:" in report:
            rc = 1
    else:
        for w in recon["warn"]:
            print(f"warn: {w}", file=sys.stderr)
    if args.md:
        print(render_md(entries))
    if args.json:
        sys.stdout.write(payload)
    for dest in ([DEFAULT_OUT] if args.write else []) + (
        [Path(args.out)] if args.out else []
    ):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(payload, encoding="utf-8")
        print(f"wrote {dest}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
