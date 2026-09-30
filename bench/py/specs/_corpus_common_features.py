"""_corpus_common blob 特征叶——成员名解析 / 签名正则面 / blob_features / unpack。

``texlate.arxiv`` 惰性 import 在 ``unpack_blob`` 内（import 期纯 stdlib）。
"""

from __future__ import annotations

import gzip
import hashlib
import io
import re
import tarfile
from collections import Counter
from pathlib import Path

from specs._benchlite import strip_comments

# ---------------------------------------------------------------- blob 特征机器
# （build_corpus_v3 verbatim：特征口径单源——scan_tar 与 extracted 树共用。）
TEXT_EXT = {
    ".tex",
    ".sty",
    ".cls",
    ".bbl",
    ".bib",
    ".txt",
    ".def",
    ".clo",
    ".cfg",
    ".ltx",
    ".dtx",
    ".ins",
    ".fd",
    ".bst",
    ".mf",
    ".mac",
}
DOCCLASS_RX = re.compile(
    r"\\(documentclass|documentstyle)\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}",
    re.DOTALL,
)
INPUT_RX = re.compile(
    r"\\(?:input|include|InputIfFileExists)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}"
)
# deadpkg 名单：净室 stub 族（禁再分发→missing_file 必中）+ vendored 真件族
# （pkg_version_skew/接口漂移高发）+ 残差签名实测族。小写归一，匹配 IGNORECASE。
# revtex 只钉裸名——revtex4/revtex4-2 是 CTAN 现役，\b 边界天然排除。
DEAD_PKGS = {
    "aa",
    "aasms4",
    "aaspp4",
    "aastex",
    "aipproc",
    "aipmod",
    "apjfonts",
    "axodraw",
    "boxedeps",
    "citesort",
    "complexity",
    "diagrams",
    "elsart",
    "emulateapj",
    "epsf",
    "epsfx",
    "eqsecnum",
    "espcrc1",
    "espcrc2",
    "iopart",
    "imsart",
    "jhep3",
    "jheppub",
    "jinstpub",
    "mn2e",
    "moriond",
    "psfig",
    "pst-node",
    "revtex",
    "slashbox",
    "sprocl",
    "svglov3",
    "svjour",
    "svjour3",
    "sw20lart",
    "tcilatex",
    "texsort",
}
DEADPKG_ALT = "|".join(sorted(DEAD_PKGS, key=len, reverse=True)).replace("-", "[-]")
DEADPKG_RX = re.compile(
    r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*?(?:"
    + DEADPKG_ALT
    + r")\b|"
    + r"\\document(?:class|style)\s*(?:\[[^\]]*\])?\s*\{[^}]*?(?:"
    + DEADPKG_ALT
    + r")\b|"
    + r"\\documentstyle\[[^\]]*(?:"
    + DEADPKG_ALT
    + r")\b|"
    + r"\\input\s*\{?[^{}\s]*(?:"
    + DEADPKG_ALT
    + r")\b",
    re.IGNORECASE,
)

FLAG_RX = {
    "minted": re.compile(
        # \mint 定界（W108）：必须是 minted 调用形（[opts]{lang}）——作者常以
        # \def\mint{\int..} 表多重积分，\b 裸匹配会把定义体/积分用法误作 flag
        r"\\begin\{minted\}|\\inputminted|"
        r"\\mint(?:inline)?(?:\[[^\]]*\])?\{[a-zA-Z0-9_+.-]+\}|"
        r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*minted"
    ),
    "pstricks": re.compile(
        r"\\begin\{pspicture\}|\\ps[A-Z]|"
        r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{pst[-a-z]*"
    ),
    "tikz": re.compile(
        r"\\begin\{tikzpicture\}|\\tikz\b|\\usetikzlibrary|"
        r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*tikz"
    ),
    "biblatex": re.compile(
        r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{biblatex|"
        r"\\addbibresource|\\printbibliography"
    ),
    "hyperref": re.compile(
        r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*hyperref|"
        r"\\hypersetup"
    ),
    "amsmath": re.compile(
        r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*amsmath|"
        r"\\begin\{align|\\begin\{equation"
    ),
    "epsfig": re.compile(
        r"\\epsfig\{|\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{epsfig|"
        r"\\includegraphics(?:\[[^\]]*\])?\{[^}]*\.e?ps\}?",
        re.IGNORECASE,
    ),
    # failmine 矿类旗（2026-09-19 扩库）：命中即"现代引擎大概率 missing_file /
    # 走 vendor stub"的论文——名单对齐 fixloop/vendor/{stubs,files} 绝版族 +
    # loop1 残差签名族（aasms4/psfig/pst-node/JHEP3/epsf）。三种命中形态：
    # \usepackage{}/\RequirePackage{}、\documentstyle 选项位、\input X.sty。
    "deadpkg": DEADPKG_RX,
    # 旧式 pdftex 原语直写（unfixable:pdftex_prim:* 族）：现代引擎不认的
    # 原语赋值——只钉赋值形（=\d），读位（\ifnum\pdfoutput）不算病灶。
    "pdftex_prim": re.compile(
        r"\\pdf(?:compresslevel|objcompresslevel|decimaldigits|"
        r"optionalwaysusepdfpagebox|omitcharset|suppressptexinfo)\s*=?|"
        r"\\pdfoutput\s*=\s*\d"
    ),
    # babel 非英语选项族（残差签名 babel_opt:german）：选项位命中即记——
    # 只钉 babel 包，其他包的 german 同名选项不捞。
    "babel_german": re.compile(
        r"\\(?:usepackage|RequirePackage)\[[^\]]*german[^\]]*\]\{babel\}|"
        r"\\usepackage\{babel\}[^\n]*german"
    ),
}
AUTOIGNORE = b"%auto-ignore"

# ---- EVAL 良性形态签名（mechanisms.jsonl EVAL 族；blob_features 簿记进 signatures）----
USEP_RX = re.compile(r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{([^}]*)\}")
# W35 期刊样式以 \usepackage 加载的已知样式包（jheppub 类——2.09 docstyle 选项系同款）
JOURNAL_STY_PKGS = {
    "jheppub",
    "jinstpub",
    "aasms4",
    "aaspp4",
    "sprocl",
    "espcrc2",
    "moriond",
    "aipmod",
    "eqsecnum",
    "emulateapj",
}
# W62 kitchen-sink 异质 DSL 包（证据谱：CJKutf8+skak+xypic+tikz-cd+commath+faktor+nccmath）
DSL_PKGS = {
    "skak",
    "xypic",
    "tikz-cd",
    "commath",
    "faktor",
    "nccmath",
    "chess",
    "amscd",
    "pb-diagram",
    "forest",
    "qtree",
    "xy",
}
# W64 \documentclass 非常规 option 位期刊样式（证据 ecta；同谱补 jhep/jcap/mnras/aastex
# + revtex 期刊/学会位 pra..prx/aps/aip——实测 docclass_opts 谱见 1502.06414）
JOURNAL_OPTS = {
    "ecta",
    "jhep",
    "jcap",
    "mnras",
    "aastex",
    "aps",
    "aip",
    "pra",
    "prb",
    "prc",
    "prd",
    "pre",
    "prl",
    "prx",
    "rmp",
}
# W70 选项错拼判定基线：LaTeX 内核 + 主流类选项白名单（编辑距 ≤1 即疑 typo）
KERNEL_OPTS = {
    "8pt",
    "9pt",
    "10pt",
    "11pt",
    "12pt",
    "14pt",
    "17pt",
    "20pt",
    "a4paper",
    "a5paper",
    "b5paper",
    "letterpaper",
    "legalpaper",
    "executivepaper",
    "landscape",
    "twocolumn",
    "onecolumn",
    "twoside",
    "oneside",
    "draft",
    "final",
    "fleqn",
    "leqno",
    "titlepage",
    "notitlepage",
    "openright",
    "openany",
    "openbib",
    "preprint",
    "preprintnumbers",
    "superscriptaddress",
    "amsmath",
    "amssymb",
    "amsfonts",
    "floatfix",
    "nofootinbib",
    "showkeys",
    "showpacs",
    "longbibliography",
    "reprint",
    "conference",
    "journal",
    "technote",
    "compsoc",
    "peerreview",
    "review",
    "manuscript",
    "screen",
    "referee",
    "english",
    "proc",
    "overfull",
    "numbered",
    "authoryear",
    # 实测语料补录（避免标准类选项误作 typo 候选）:
    # amsart 系 eqno/tags/limits 位
    "reqno",
    "tbtags",
    "centertags",
    "intlimits",
    "nointlimits",
    "sumlimits",
    "nosumlimits",
    "namelimits",
    "nonamelimits",
    # IEEEtran 学会位
    "comsoc",
    "transmag",
    # svjour/aip 系参考文献样式位
    "author-year",
}
ORG_LABEL_RX = re.compile(r"\\label\{sec:org[0-9a-f]{5,9}\}")
EDITOR_LEFT_RX = re.compile(r"\\label\{[a-z]+:enter-label\}|\\textbf\{\}")
PLAIN_OUT_RX = re.compile(
    r"\\(?:headline|footline|output|shipout)\s*(?=[={\\])|\\shipout\b"
)
MANUAL_BF_RX = re.compile(r"\{\\bf[a-z]*\b")
CENTERLINE_RX = re.compile(r"\\centerline\b")
SECTION_RX = re.compile(r"\\(?:sub)*section\*?\s*[{\[]")
XREF_RX = re.compile(r"\\jobname\.xref|\.xref\b")


def _dist1(a: str, b: str) -> bool:
    """a 与 b 编辑距离恰为 1（W70 选项错拼：12pi↔12pt）。"""
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    if la > lb:
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1 :]


def eval_signatures(blob_txt: str) -> dict[str, object]:
    """良性形态签名簿记 → {mech_id: 命中明细}；只在 paper 自身 tex（剥注释后）上看。

    每条对应 mechanisms.jsonl EVAL 族一行——把「长得像故障的良性形态」注记进
    features，供归因/狩猎区分真缺陷与形态签名（W48 协作残留、W88 手排、W70 typo 等）。"""
    sig: dict[str, object] = {}
    pkgs = Counter(
        p.strip()
        for m in USEP_RX.finditer(blob_txt)
        for p in m.group(1).split(",")
        if p.strip()
    )
    if dups := sorted(p for p, c in pkgs.items() if c >= 2):
        sig["W48"] = dups
    if jsty := sorted(pkgs.keys() & JOURNAL_STY_PKGS):
        sig["W35"] = jsty
    if ORG_LABEL_RX.search(blob_txt):
        sig["W39"] = True
    if n := len(EDITOR_LEFT_RX.findall(blob_txt)):
        sig["W60"] = n
    if (dsl := sorted(pkgs.keys() & DSL_PKGS)) and len(dsl) >= 2:
        sig["W62"] = dsl
    dcls_opts = {
        o.strip()
        for m in DOCCLASS_RX.finditer(blob_txt)
        if m.group(1) == "documentclass" and m.group(2)
        for o in m.group(2).split(",")
        if o.strip()
    }
    if jopt := sorted(dcls_opts & JOURNAL_OPTS):
        sig["W64"] = jopt
    if typos := sorted(
        o
        for o in dcls_opts - JOURNAL_OPTS - KERNEL_OPTS
        if any(_dist1(o, k) for k in KERNEL_OPTS)
    ):
        sig["W70"] = typos
    if not SECTION_RX.search(blob_txt) and (
        len(MANUAL_BF_RX.findall(blob_txt)) >= 3
        or len(CENTERLINE_RX.findall(blob_txt)) >= 2
    ):
        sig["W88"] = True
    if outs := sorted({o.strip() for o in PLAIN_OUT_RX.findall(blob_txt)}):
        sig["W93"] = outs
    if XREF_RX.search(blob_txt):
        sig["W106"] = True
    return sig


def looks_like_tar(b: bytes) -> bool:
    if len(b) < 512:
        return False
    if b[257:262] == b"ustar":
        return True
    try:
        chksum = int(b[148:156].split(b"\0", 1)[0].strip() or b"0", 8)
        calc = sum(b[:148]) + 8 * 32 + sum(b[156:512])
    except ValueError:
        return False
    return calc == chksum


def norm_target(raw: str) -> str:
    t = raw.strip().strip("{}").strip('"').strip("'")
    t = t.replace("\\", "/").lstrip("./")
    if not Path(t).suffix:
        t += ".tex"
    return t


def input_depth(tex_by_norm: dict[str, str], roots: list[str]) -> int:
    edges: dict[str, set[str]] = {}
    for path, text in tex_by_norm.items():
        deps = set()
        base = Path(path).parent
        for m in INPUT_RX.finditer(text):
            t = norm_target(m.group(1))
            cands = (str(base / t), t, str(base / Path(t).name))
            hit = next(
                (
                    x
                    for x in (str(Path(x)) if x.startswith("/") else x for x in cands)
                    if x in tex_by_norm
                ),
                None,
            )
            if hit is not None:
                deps.add(hit)
        edges[path] = deps
    starts = roots or list(tex_by_norm)
    best = 0
    for s in starts:
        seen: dict[str, int] = {}
        stack = [(s, 0)]
        while stack:
            node, d = stack.pop()
            if seen.get(node, -1) >= d or d > 32:
                continue
            seen[node] = d
            best = max(best, d)
            stack.extend((nxt, d + 1) for nxt in edges.get(node, ()))
    return best


def member_id(name: str) -> str:
    """'9802/astro-ph9802001.gz' → 'astro-ph/9802001';
    '1201/1201.00012.gz' → '1201.00012'."""
    stem = Path(name).name
    stem = re.sub(r"\.(gz|pdf|tar\.gz)$", "", stem)
    m = re.match(r"([a-z-]+(?:\.[A-Z]{2})?)(\d{7})$", stem)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return stem


def blob_features(name: str, blob: bytes) -> dict:
    """单个 e-print blob → 特征 dict (scan_tar 版 + sha256/stub/staging texts).

    特征口径见 _texts_features: flags=tex 通道 / flags_vendored=sty·cls·bbl 通道
    / flags_commented=剥注释差集 / signatures=EVAL 良性形态簿记。
    """
    rec: dict = {
        "member": name,
        "id": member_id(name),
        "member_bytes": len(blob),
        "blob_sha256": hashlib.sha256(blob).hexdigest(),
    }
    if blob[:5] == b"%PDF-":
        rec["format"] = "pdf"
        return rec
    if blob[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(blob)
        except OSError as e:
            rec["format"] = "error"
            rec["error"] = f"gunzip: {e}"
            return rec
    else:
        data = blob
    if data.lstrip()[:20].startswith(AUTOIGNORE):
        rec["format"] = "stub"
        rec["uncompressed_bytes"] = len(data)
        return rec
    if looks_like_tar(data):
        rec["format"] = "tar"
        try:
            inner = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
            files = [m for m in inner.getmembers() if m.isreg()]
        except tarfile.TarError as e:
            rec["format"] = "error"
            rec["error"] = f"inner tar: {e}"
            return rec
        texts: dict[str, bytes] = {}
        n_tex = 0
        total_bytes = 0
        for m in files:
            total_bytes += m.size
            ext = Path(m.name).suffix.lower()
            if ext == ".tex":
                n_tex += 1
            if ext in TEXT_EXT and m.size < 8 << 20:
                f = inner.extractfile(m)
                if f:
                    texts[m.name.lstrip("./")] = f.read()
        rec["n_total_files"] = len(files)
        rec["n_tex_files"] = n_tex
        rec["uncompressed_bytes"] = total_bytes
    else:
        rec["format"] = "gz"
        rec["n_total_files"] = 1
        head = data.lstrip()[:8]
        is_tex = not head.startswith((b"%!PS", b"%PDF"))
        rec["n_tex_files"] = 1 if is_tex else 0
        if not is_tex:
            rec["gz_payload"] = "ps/pdf"
        rec["uncompressed_bytes"] = len(data)
        texts = {Path(name).name.replace(".gz", ".tex"): data}

    tex_texts: dict[str, str] = {}
    non_utf8 = False
    for p, b in texts.items():
        try:
            s = b.decode("utf-8")
        except UnicodeDecodeError:
            non_utf8 = True
            s = b.decode("utf-8", "replace")
        if Path(p).suffix.lower() == ".tex" or rec["format"] == "gz":
            tex_texts[p] = s
    rec["non_utf8"] = non_utf8
    rec["_texts"] = texts  # staging 用，不落 jsonl
    rec.update(_texts_features(tex_texts, texts))
    return rec


def _texts_features(tex_texts: dict[str, str], texts: dict[str, bytes]) -> dict:
    """tex_texts(剥注释前 tex 文本)+texts(全部文本件)→ 形态特征字段。

    blob_features(scan_tar) 与 fetch-ids extracted 树共用同一计算——特征口径
    单点维护，避免两通道漂移。
    """
    rec: dict = {}
    tex_raw = "\n".join(tex_texts.values())
    sty_raw = "\n".join(
        b.decode("utf-8", "replace")
        for p, b in texts.items()
        if Path(p).suffix.lower() in {".sty", ".cls", ".bbl"}
    )
    blob_txt = strip_comments(tex_raw)
    sty_txt = strip_comments(sty_raw)
    dcls_ms = list(DOCCLASS_RX.finditer(blob_txt))
    rec["docclasses"] = sorted({m.group(3).strip() for m in dcls_ms})
    rec["docstyle"] = any(m.group(1) == "documentstyle" for m in dcls_ms)
    # W80-feat: 2.09 \documentstyle[jheppub,12pt]{article} 的期刊样式本体在 option 位
    rec["docstyle_opts"] = sorted(
        {
            o.strip()
            for m in dcls_ms
            if m.group(1) == "documentstyle" and m.group(2)
            for o in m.group(2).split(",")
            if o.strip()
        }
    )
    rec["docclass_opts"] = sorted(
        {
            o.strip()
            for m in dcls_ms
            if m.group(1) == "documentclass" and m.group(2)
            for o in m.group(2).split(",")
            if o.strip()
        }
    )
    roots = [p for p, t in tex_texts.items() if DOCCLASS_RX.search(strip_comments(t))]
    rec["tex_roots"] = sorted(roots)
    rec["input_depth"] = input_depth(tex_texts, roots)
    # W101: flags 拆 tex/vendored 双通道——sty/cls/bbl 是发行资产，合并扫描会把
    # 宏包自带形态 (如样式文件内嵌 pstricks 钩) 误记为论文自身 flag
    rec["flags"] = sorted(k for k, rx in FLAG_RX.items() if rx.search(blob_txt))
    rec["flags_vendored"] = sorted(k for k, rx in FLAG_RX.items() if rx.search(sty_txt))
    # W109: hunter rg 命中剥注释复核——只活在注释里的命中单列 (raw 有 stripped 无)
    raw_scan = tex_raw + "\n" + sty_raw
    stripped_hits = set(rec["flags"]) | set(rec["flags_vendored"])
    rec["flags_commented"] = sorted(
        {k for k, rx in FLAG_RX.items() if rx.search(raw_scan)} - stripped_hits
    )
    if sig := eval_signatures(blob_txt):
        rec["signatures"] = sig
    return rec


def extracted_features(extract_dir: Path) -> dict:
    """已解压 extracted/ 树 → 同口径特征 dict(fetch-ids 通道的补齐件)。"""
    texts: dict[str, bytes] = {}
    for fp in sorted(extract_dir.rglob("*")):
        if (
            fp.is_file()
            and fp.suffix.lower() in TEXT_EXT
            and fp.stat().st_size < 8 << 20
        ):
            texts[str(fp.relative_to(extract_dir))] = fp.read_bytes()
    tex_texts: dict[str, str] = {}
    non_utf8 = False
    for p, b in texts.items():
        try:
            s = b.decode("utf-8")
        except UnicodeDecodeError:
            non_utf8 = True
            s = b.decode("utf-8", "replace")
        if Path(p).suffix.lower() == ".tex":
            tex_texts[p] = s
    rec = _texts_features(tex_texts, texts)
    rec["non_utf8"] = non_utf8
    return rec


def eligible(f: dict) -> bool:
    return f.get("format") in ("tar", "gz") and (f.get("n_tex_files") or 0) >= 1


def safe_name(name: str) -> str | None:
    p = Path(name.lstrip("./"))
    if p.is_absolute() or ".." in p.parts:
        return None
    return str(p)


def unpack_blob(blob: bytes, fmt: str, dest: Path) -> tuple[int, list[str]]:
    """raw e-print blob → ``dest/extracted/``（归并产品 ``texlate.arxiv`` unpack）。

    sniff 做有上限 gunzip + 魔数复核——``fmt`` 只是扫描侧标注，内容优先、不符
    记 fmt_mismatch 告警；tar 走产品逐成员过滤（容量/setuid/link/casefold/
    stub），单文件 gz 沿用旧命名：tex → ``main.tex``、ps/pdf payload 按真实
    扩展名落盘。非 tar/gz 与解包硬错误 → ``(0, warns)``，不炸批。
    """
    from texlate.arxiv import (  # 惰性——本叶 import 期纯 stdlib 约定
        BlobKind,
        SniffError,
        UnpackError,
        sniff,
        unpack_single,
        unpack_tar,
    )

    if fmt not in ("tar", "gz"):
        return 0, [f"{fmt} member — blob 留存不解包"]
    ext_dir = dest / "extracted"
    ext_dir.mkdir(parents=True, exist_ok=True)
    try:
        s = sniff(blob)
    except SniffError as e:
        return 0, [f"sniff_error:{e}"]
    if s.oversized or s.payload is None:
        return 0, [
            f"inflated_too_large:{s.inflated_size}"
            if s.oversized
            else f"cannot unpack kind={s.kind}"
        ]
    try:
        if s.kind is BlobKind.TAR:
            res = unpack_tar(s.payload, ext_dir)
            if fmt != "tar":
                res.warnings.append("fmt_mismatch:gz->tar")
            return res.n_files, res.warnings
        if s.kind is BlobKind.SINGLE:
            head = s.payload.lstrip()[:8]
            if head.startswith((b"%!PS", b"%PDF")):
                ext = ".ps" if head.startswith(b"%!PS") else ".pdf"
                (ext_dir / f"main{ext}").write_bytes(s.payload)
                return 1, [f"single-gz payload sniffed as {ext}"]
            res = unpack_single(s.payload, ext_dir, stem_hint="main")
            if fmt != "gz":
                res.warnings.append("fmt_mismatch:tar->single")
            return res.n_files, res.warnings
    except UnpackError as e:
        return 0, [f"unpack_error:{e}"]
    return 0, [f"cannot unpack kind={s.kind}"]
