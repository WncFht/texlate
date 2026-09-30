r"""specs.parsebench.topology — 论文拓扑叶 (parsebench 拆分叶).

非 UTF-8 字节判定 / ``\documentclass`` root 枚举 / 路由标签
(reject,xelatex,minted,non-utf8,no-hyperref) / ``_topology`` ——
analyze_paper v2：roots + reach(res.inputs 口径) + roles +
``non_utf8_realpaths``，身份集一律 ``Path.resolve()`` realpath
(``res.inputs`` 的 resolved 项就是 realpath，abspath 在 symlink 父目录
下会错配成全 orphan)。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs.parsebench.measure import parse_one
from texlate.textutil import decode_tex


def is_non_utf8(path: Path) -> bool:
    """含 0x80+ 字节且 UTF-8 decode 失败 → 非 UTF-8."""
    b = path.read_bytes()
    if not any(x > 0x7F for x in b):
        return False
    try:
        b.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


DOCCLASS_RX = re.compile(
    r"\\(documentclass|documentstyle)\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}",
    re.DOTALL,
)


def find_roots(tex_files: list[Path]) -> list[dict]:
    """剥注释后含 \\documentclass/\\documentstyle 的文件 → 根."""
    roots = []
    for p in sorted(tex_files):
        try:
            tex = decode_tex(p.read_bytes())
        except OSError:
            continue
        m = DOCCLASS_RX.search(benchlib.strip_comments(tex))
        if m:
            roots.append(
                {
                    "file": p,
                    "cmd": m.group(1),
                    "class": m.group(3).strip(),
                    # 选项内可穿插注释剥除后残留的换行 (2308.07483) → 归一化
                    "options": re.sub(r"\s+", " ", m.group(2) or "").strip(),
                }
            )
    return roots


# ---------------------------------------------------------------- 路由标签

RX_EPS_PS = re.compile(
    r"\.eps\b|pstricks|\\begin\{pspicture\}|"
    r"\\usepackage(?:\[[^\]]*\])?\{pst[-a-z]*",
    re.IGNORECASE,
)
RX_MINTED = re.compile(
    r"\\begin\{minted\}|\\inputminted|\\mint(?:inline)?\b|"
    r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*minted"
)
RX_HYPERREF = re.compile(
    r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*hyperref"
)


def paper_tags(roots: list[dict], stripped_blob: str, non_utf8: list) -> list[str]:
    tags = []
    if any(r["cmd"] == "documentstyle" for r in roots):
        tags.append("reject")  # LaTeX 2.09 \documentstyle
    if RX_EPS_PS.search(stripped_blob):
        tags.append("xelatex")  # .eps/pstricks → 非 pdflatex 路由
    if RX_MINTED.search(stripped_blob):
        tags.append("minted")  # 需 -shell-escape
    if non_utf8:
        tags.append("non-utf8")
    if not RX_HYPERREF.search(stripped_blob):
        tags.append("no-hyperref")
    return tags


# ---------------------------------------------------------------- 拓扑


def is_tex(p: Path) -> bool:
    """大小写不敏感 .tex 判定——野语料存在 .TEX 古早文件
    (corpus 实测：0707.2108/pmeyerxi.TEX, 0806.0433/*.TEX)."""
    return p.is_file() and p.suffix.lower() == ".tex"


def rglob_tex(d: Path) -> list[Path]:
    return [p for p in d.rglob("*") if is_tex(p)]


def _topology(
    src: Path, tex_files: list[Path], paper_id: str, timeout_s: int
) -> tuple[dict, dict, dict, set]:
    """analyze_paper v2：roots + reach(res.inputs 口径) + roles + 路由标签。

    返回 (paper_dict, parsed_cache, roles, non_utf8_realpaths)。
    ``parsed_cache`` = {realpath: parse_one 结果}——root 的解析结果直接喂
    file loop 复用（同一次 parse 不跑两遍）。身份集一律 ``Path.resolve()``
    realpath——``res.inputs`` 的 resolved 项就是 realpath，abspath 在
    symlink 父目录下会错配成全 orphan。
    """
    rpaths = {p: str(p.resolve()) for p in tex_files}
    all_files = [p for p in src.rglob("*") if p.is_file()]
    non_utf8_rp = {rpaths[p] for p in tex_files if is_non_utf8(p)}

    roots = find_roots(tex_files)
    stripped_blob = "\n".join(
        benchlib.strip_comments(decode_tex(p.read_bytes())) for p in tex_files
    )

    # reach = 各根 parse 的 res.inputs resolved 集并集 (multi_doc 并集口径)；
    # 根 parse 崩 → 该根只贡献自身（v1 flatten_reach 吞异常同义）。
    reach_by_root: dict[str, set[str]] = {}
    parsed: dict[str, dict] = {}
    covered: set[str] = set()
    for r in roots:
        rp = str(Path(r["file"]).resolve())
        pr = parse_one(r["file"], timeout_s)
        parsed[rp] = pr
        reach = {rp}
        if pr.get("ok"):
            for _pos, name in pr["res"].inputs:
                if os.path.isabs(name):
                    reach.add(name)
        reach_by_root[rp] = reach
        covered |= reach

    primary = None
    if roots:
        # 主文件 = reach 触及最多的根 (multi_doc 的代表), 平手取路径短者
        primary = max(
            roots,
            key=lambda r: (
                len(reach_by_root[str(Path(r["file"]).resolve())]),
                -len(str(r["file"])),
            ),
        )["file"]

    roles: dict[str, str] = {}
    for p in tex_files:
        rel = p.relative_to(src).as_posix()
        rp = rpaths[p]
        if not roots:
            role = "no_root"
        elif rp in reach_by_root:
            role = "root"
        elif rp in covered:
            role = "input_reached"
        else:
            role = "orphan"
        roles[rel] = role

    paper = {
        "id": paper_id,
        "n_tex": len(tex_files),
        "n_files": len(all_files),
        "tex_bytes": sum(p.stat().st_size for p in tex_files),
        "total_bytes": sum(p.stat().st_size for p in all_files),
        "roots": [
            {
                "file": str(r["file"].relative_to(src)),
                "cmd": r["cmd"],
                "class": r["class"],
                "options": r["options"],
            }
            for r in roots
        ],
        "multi_doc": len(roots) > 1,
        "rootless": not roots,
        "primary_root": str(primary.relative_to(src)) if primary else None,
        "docclass": roots[0]["class"] if roots else None,
        "docclass_options": roots[0]["options"] if roots else None,
        "non_utf8_files": [
            p.relative_to(src).as_posix() for p in tex_files if rpaths[p] in non_utf8_rp
        ],
        "tags": paper_tags(roots, stripped_blob, sorted(non_utf8_rp)),
        "orphan_tex": [
            p.relative_to(src).as_posix()
            for p in tex_files
            if roots and rpaths[p] not in covered
        ],
        "roles": roles,
        "covered_n": len(covered),
        "reach_source": "res.inputs",
    }
    return paper, parsed, roles, non_utf8_rp
