r"""主文件定位与 ``\input`` 闭包 —— inject.py C4 拆分出叶。

概念归属：主 .tex 发现启发式（``find_main_tex`` 候选过滤+排序）、空池归因
（``classify_no_main`` P-D 细分）、``\input``/``\include`` 传递闭包遍历
（``_walk_inputs``/``_resolve_input``）与 ``filecontents`` 自解包虚拟成员表
（``_filecontents_bodies``/``_resolve_virtual``——成员物理不在包内但编译时
TeX 落盘再 ``\input``）。公共名经 ``compile.inject`` 门面回引，import 面守恒。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from texlate.textutil import (
    BEGIN_DOC_RX,
    DOCCLASS_DECL_RX,
    DOCCLASS_ONLY_RX,
    DOCCLASS_RX,
    DOCSTYLE_RX,
    INPUT_BARE_RX,
    INPUT_BRACED_RX,
    clean_decl_name,
    mask_tex,
    safe_is_file,
    safe_resolve,
)

from .mask import visible_tex
from .normalize import _read_tex
from .transcode import _iter_files

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

#: 可作主入口的 TeX 源后缀（mask.py TEX_SOURCE_SUFFIXES 的子集——
#: .sty/.cls 等是被装载件不作 main 候选；.ltx 是合法主档形态）。
#: tuple 保序：``_resolve_input`` 无扩展名补全按 kpathsea 序先 .tex 后 .ltx。
_MAIN_TEX_SUFFIXES = (".tex", ".ltx")

#: ``_body_mass``/``_walk_inputs`` 闭包走查文件数上界——分数只是排序键，
#: 够分胜负即可，病态工程（数千 .tex）不拖死选取。
_MASS_FILE_CAP = 1024

#: ``filecontents`` 环境成员抽取：``\begin{filecontents[*]}{name}`` 写的文件
#: 物理不在包内，但编译时 TeX 会把它落到工作目录再 ``\input``——自解包形态
#: （1502.06414 index_preprint.tex：50+ 成员包真 doc，外层尾行 ``\input{index}``）。
#: 遮盖视图把环境连 begin 行整体抹平，抽取必须在 ``keep_verbatim`` 视图做：
#: 注释内的伪 ``\begin{filecontents}`` 已被抹掉，成员体原样保留。
_FILECONTENTS_BEGIN_RX = re.compile(
    r"\\begin\s*\{(filecontents[^}\s]*)\}\s*(?:\[[^\]]*\])?\s*\{([^{}]+)\}"
)

#: 虚拟成员表上界——自解包包体可含数十成员（sty/cls/def），tex 族成员
#: 才有闭包意义；超界即病态输入，成员表截断。
_VIRTUAL_MEMBER_CAP = 256

#: 排序键名加成白名单——``main.tex``/``paper.tex``/``ms.tex`` 是约定主档名。
_PREF_BASENAMES = ("main.tex", "paper.tex", "ms.tex")

#: 附件/存档件名指纹（``_-``/``.`` 词元边界，逐路径段匹配）：supp/appendix/si
#: 补充材料族 + old/archive/backup 版本存档族。整件附件档与薄壳编排 main
#: 同十进制量级桶时文件大小会反选——2303.16206 ``supp.tex`` 压
#: ``iclr2023_conference.tex`` 壳、2503.16248 ``old-main.tex`` 压
#: ``00_main.tex`` 壳、2609.19320 ``SI_Appendix.tex`` 压 ``root.tex`` 实证；
#: 命中者沉底先于名加成裁决。短词元（si/sm/app/old/bak）只收边界整词——
#: ``simulation``/``application`` 类真文档名不误伤。
_AUX_NAME_RX = re.compile(
    r"(?:^|[_\-.])(?:supp\w*|si|sm|esm|appendi\w*|app|support\w*|"
    r"rebuttal|response|reply|old|archive\w*|backup|bak|prev\w*|obsolete)"
    r"(?:[_\-.]|$)",
    re.IGNORECASE,
)

#: ``\title`` 参数的附件自报指纹：整题即 "Supplementary Material" 类，或
#: 尾段以 ``-``/``:`` 等分隔后接 supplement/appendix 族词
#: （2303.16206 ``supp.tex`` 题 "… - Supplementary"）。中段裸词不算——
#: "Dietary Supplement …" 类真论文题不误伤。
_AUX_TITLE_RX = re.compile(
    r"(?:^\s*(?:supplement(?:ary|s|al)?|supporting\s+information|"
    r"appendi(?:x|ces))(?:\s+(?:material|information|document|file|online))?"
    r"\s*\.?\s*$"
    r"|[-–—:;(\[]\s*(?:supplement(?:ary|s|al)?|supporting\s+information|"
    r"appendi(?:x|ces))[\w\s,.-]*$)",
    re.IGNORECASE,
)

#: ``\title`` 参数抽取（一层嵌套内的前 400 字符面——附件判定只看题头）。
_TITLE_ARG_RX = re.compile(
    r"\\title\*?\s*(?:\[[^\]]*\])?\s*\{((?:[^{}]|\{[^{}]*\}){0,400})"
)


def _norm_virtual_key(name: str) -> str | None:
    r"""``filecontents`` 名 → 规范包内相对路径；逃逸/绝对/噪声 → ``None``。"""
    name = name.strip().strip('"').strip()
    if not name or name.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", name):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _filecontents_bodies(kept: str) -> dict[str, str]:
    r"""``keep_verbatim`` 视图上的 filecontents 成员表：名 → 体文本。

    ``kept`` 是 ``mask_tex(raw, keep_verbatim=True)`` 产物——注释已抹、
    逐字族环境（含 filecontents 体）原样。重复写同名成员先写者胜
    （filecontents 不覆盖已存在文件，TeX 语义同款）。
    """
    out: dict[str, str] = {}
    for m in _FILECONTENTS_BEGIN_RX.finditer(kept):
        end = re.compile(r"\\end\{" + re.escape(m.group(1)) + r"\}").search(
            kept, m.end()
        )
        key = _norm_virtual_key(m.group(2))
        if key is not None and key not in out:
            out[key] = kept[m.end() : end.start() if end else len(kept)]
        if len(out) >= _VIRTUAL_MEMBER_CAP:
            break
    return out


def _iter_input_args(vis: str) -> Iterator[tuple[re.Match[str], str | None]]:
    r"""``\input`` 族 braced+bare 两形命中流：``(match, clean_decl_name(arg))``。

    ``_walk_inputs``/probe ``_scan_inputs``/inject ``_input_hop_targets``
    同款扫描——``match["verb"]`` 留给消费方判 ``\InputIfFileExists``
    optional 与 ``\include`` 分流；噪声名（控制序列/括号/注释符）以
    ``None`` 原样 yield，由消费方跳过。
    """
    for match in (
        *INPUT_BRACED_RX.finditer(vis),
        *INPUT_BARE_RX.finditer(vis),
    ):
        yield match, clean_decl_name(match["arg"])


def _input_names(name: str) -> Iterator[str]:
    r"""``\input``/``\include`` 声明名 → 候选文件名流（kpathsea 序）。

    无扩展名按 ``_MAIN_TEX_SUFFIXES`` 序补 ``.tex``/``.ltx``，有扩展名
    原样单发；后缀不在 ``_MAIN_TEX_SUFFIXES`` 者滤除（``.bbl``/``.sty``
    等非 tex 目标不进闭包）。``_resolve_input``/``_resolve_virtual``
    共用此候选名策略，两跳的基域各自保有（磁盘 Path vs 虚拟表键）。
    """
    names = [name] if Path(name).suffix else [name + ext for ext in _MAIN_TEX_SUFFIXES]
    for fname in names:
        if Path(fname).suffix.lower() in _MAIN_TEX_SUFFIXES:
            yield fname


def _resolve_virtual(
    root: Path, decl_dir: Path, name: str, virtual: Mapping[str, str]
) -> tuple[Path, str] | None:
    r"""``\input`` 目标 → filecontents 虚拟成员 ``(pseudo_path, body)``。

    磁盘解析缺席后的二探（``_resolve_input`` 同口径：无扩展名补 ``.tex``
    /``.ltx``，声明目录→工程根两跳）。pseudo_path 是该文件编译时会被
    filecontents 落盘的合成位（root 下成员名）——``seen`` 键与嵌套
    ``\input`` 基准目录沿用真路径语义，不落盘。
    """
    try:
        decl_rel = decl_dir.relative_to(root).as_posix()
    except ValueError:
        decl_rel = ""
    if decl_rel == ".":
        decl_rel = ""
    for fname in _input_names(name):
        for base in (decl_rel, ""):
            key = f"{base}/{fname}" if base else fname
            body = virtual.get(key)
            if body is not None:
                return root / key, body
    return None


def _resolve_input(root: Path, decl_dir: Path, name: str) -> Path | None:
    r"""``\input``/``\include`` 目标 → 本地 .tex/.ltx（声明目录→工程根两跳，kpathsea 序）。

    无扩展名按 ``_MAIN_TEX_SUFFIXES`` 序补 ``.tex``/``.ltx``；解析到非
    tex 主档后缀（``.bbl``/``.sty`` 等）或越出工程根的目标不计入 body 量。
    （probe.py ``_find_local`` 是刻意的单跳 cwd-only 口径——引擎 cwd 即
    main 目录；本函数为闭包遍历保声明目录→根两跳，二者不同源。）
    """
    for fname in _input_names(name):
        for base in (decl_dir, root):
            # ``\input`` 参数是文档可控面——巨名 ENAMETOOLONG、symlink loop
            # RuntimeError、NUL ValueError 按不可解析处理（consistency-audit）。
            cand = safe_resolve(base / fname)
            if cand is not None and safe_is_file(cand) and cand.is_relative_to(root):
                return cand
    return None


def _walk_inputs(
    root: Path,
    seeds: list[tuple[Path, str]],
    virtual: Mapping[str, str] | None = None,
    text_cache: Mapping[Path, str] | None = None,
) -> Iterator[tuple[Path, str]]:
    r"""``\input``/``\include`` 传递闭包遍历：产出 ``(resolved_path, visible_text)``。

    从 ``(decl_file, visible_text)`` 种子出发，在遮盖视图上扫描 input 族
    目标（注释/verbatim 内的 ``\input`` 不参与），逐文件解析可存在的本地
    .tex（``_resolve_input`` 口径：声明目录→工程根两跳、越出工程根不计）。
    ``virtual`` 非空时磁盘缺席再探 filecontents 虚拟成员（自解包形态）。
    ``text_cache`` 非空时 ``resolved path → 遮盖文本`` 命中即免
    ``_read_tex`` 读件/解码/遮盖整链——``find_main_tex``
    全树扫描产物直供，消逐候选×逐文件的重复盘读（decode/mask 本体已有
    内容键 memo，真收益是 I/O 消重与 >512 件/>2MB 件树的 lru_cache
    挤兑免疫）；表外件（tar 伪装、扫描时 OSError、扫描后新建）回落
    实时读路径。环引由 visited 集收，规模上界 ``_MASS_FILE_CAP``。
    """
    vmap: Mapping[str, str] = virtual if virtual is not None else {}
    seen = {src for src, _vis in seeds}
    queue = list(seeds)
    while queue and len(seen) <= _MASS_FILE_CAP:
        src, vis = queue.pop()
        for _match, name in _iter_input_args(vis):
            if name is None:
                continue
            tgt = _resolve_input(root, src.parent, name)
            if tgt is None and vmap:
                hit = _resolve_virtual(root, src.parent, name, vmap)
                if hit is not None and hit[0] not in seen:
                    tgt, body = hit
                    seen.add(tgt)
                    sub = visible_tex(body)
                    queue.append((tgt, sub))
                    yield tgt, sub
                    continue
            if tgt is None or tgt in seen:
                continue
            seen.add(tgt)
            sub: str | None = None
            if text_cache is not None:
                sub = text_cache.get(tgt)
            if sub is None:
                raw = _read_tex(tgt)  # 不可读/tar 伪装件 → None（同闸）
                if raw is None:
                    continue
                sub = visible_tex(raw)
            queue.append((tgt, sub))
            yield tgt, sub


def _closure_has_document(
    root: Path,
    main: Path,
    text: str,
    virtual: Mapping[str, str] | None = None,
    text_cache: Mapping[Path, str] | None = None,
) -> bool:
    r"""``\begin{document}`` 在本体或 ``\input`` 传递闭包任一文件中可见。

    编排壳 main（``\documentclass`` + ``\input{body}``，bd 落在被拉入的
    子文件——cs/0408015 ``main.tex→body.tex``、2105.00092
    ``main.tex→begin.tex`` 形态）按本谓词收为候选；闭包文件与本体同在
    遮盖视图判定，注释掉的 bd/``\input`` 不计。``virtual`` 提供
    filecontents 虚拟成员表（自解包形态）时磁盘缺席再探虚拟文件。
    """
    if BEGIN_DOC_RX.search(text):
        return True
    return any(
        BEGIN_DOC_RX.search(sub)
        for _tgt, sub in _walk_inputs(root, [(main, text)], virtual, text_cache)
    )


def _closure_has_docclass(
    root: Path,
    main: Path,
    text: str,
    virtual: Mapping[str, str] | None = None,
    text_cache: Mapping[Path, str] | None = None,
) -> bool:
    r"""``\documentclass``/``\documentstyle`` 在本体或 ``\input`` 闭包可见。

    W99 形态：docclass 写在被 ``\input`` 拉入的 helper 里（0905.2435
    ``body.tex`` ``\input seki-deckblatt-3`` → helper 内
    ``\documentclass[twoside,12pt]{\whatSEKIDOCUMENTCLASS}`` 宏参类名），
    主文件本体零声明但 TeX 编译照常——候选识别与 bd 同口径走闭包。
    """
    if DOCCLASS_RX.search(text):
        return True
    return any(
        DOCCLASS_RX.search(sub)
        for _tgt, sub in _walk_inputs(root, [(main, text)], virtual, text_cache)
    )


def _body_mass(
    root: Path,
    main: Path,
    body: str,
    virtual: Mapping[str, str] | None = None,
    text_cache: Mapping[Path, str] | None = None,
) -> int:
    r"""``\begin{document}`` 后实质 body 量：可见非空白字符数 + ``\input`` 闭包。

    standalone 图档也能凑齐 ``document`` 环境但 body 与正文章节脱节——
    裸 body 长度分不出「1K 的 ``\include`` 编排壳」与「1.5K 的 tikz 图」，
    故按「这篇 document 实际拉进多少 .tex 内容」计：本体 body 可见非空白
    字符 + body 内 ``\input``/``\include`` 可解析目标的传递闭包逐文件
    同口径计数（1803.02985 E 桶：thesis.tex 本体 ~0.7K/闭包 ~400K，
    standalone 图 body ~1.5K/闭包 0）。环引由 visited 集收，规模上界
    ``_MASS_FILE_CAP``。
    """
    mass = len(re.sub(r"\s", "", body))
    for _tgt, sub in _walk_inputs(root, [(main, body)], virtual, text_cache):
        mass += len(re.sub(r"\s", "", sub))
    return mass


def find_main_tex(root: Path) -> Path | None:  # noqa: C901, PLR0912 — 候选过滤 + 排序启发式平铺即算法本体
    r"""定位主 .tex：最浅、最像正文的 `\documentclass`+`\begin{document}` 文件。

    候选门槛：`\documentclass`/`\documentstyle` 必须在文件本体（遮盖视图），
    `\begin{document}` 允许落在本体的 `\input`/`\include` 传递闭包内——
    编排壳 main 只拉子文件、bd 在下游（cs/0408015、2105.00092 形态）。

    排序：附件/存档件沉底（路径段词元命中 supp/appendix/archive 族或
    ``\title`` 自报附件——同量级桶平时文件大小会让整件 supp/old 档
    压过薄壳编排 main：2303.16206/2503.16248/2609.19320 实证）→
    main/paper/ms 名（只在候选最浅层生效——子目录 ``main.tex`` 不再
    全局抢槽，2210.03294 ``4Num_Example/main.tex`` 实证）→ 英文正文
    优先（多语种版本不靠 UTF-8 字节数
    排序——多字节文字系统性吃亏；名先于语种——译后 splice 树主档变
    CJK 众数，语种档会把真 main 输给 standalone 英文表档，
    ds209diag #191 四格误选实证）→ 模板参档后置（``\documentclass``
    的 ``[...]`` 里含控制序列 = 类文档模板算选项，如 aipguide
    ``[\optionlist]{aipproc}``；真论文写字面选项——1206.0565 类发行
    捆绑包中 guide/check 档 body 量比正主还大，需在深度/量级前挡下）
    → 目录深度 → 实质 body 量级
    （`\begin{document}` 后可见字符 + `\input` 闭包的十进制位数——
    standalone 图档/document 薄壳与真 main 分野，1803.02985 E 桶修法；
    只仲裁量级差，近等值回退文件大小，避免 `ver1/`、`old/`、diff 档
    这类版本目录副本被几个百分点翻盘）→ 文件大小。
    """
    resolved = root.resolve()
    scanned: list[tuple[Path, str, str]] = []
    kept_views: list[str] = []
    for p in sorted(_iter_files(root, _MAIN_TEX_SUFFIXES)):
        raw = _read_tex(p)
        if raw is None:
            continue  # 不可读件/tar 伪装件——成员文本可含 bd/dc 假信号且改写即腐蚀 blob
        scanned.append((p.resolve(), p.relative_to(root).as_posix(), visible_tex(raw)))
        if "filecontents" in raw:
            kept_views.append(mask_tex(raw, keep_verbatim=True))
    virtual: dict[str, str] = {}
    for kept in kept_views:
        for key, body in _filecontents_bodies(kept).items():
            virtual.setdefault(key, body)

    # 闭包走查的 ``resolved path → 遮盖文本`` 预取表——扫描已读/解码/遮盖
    # 的件命中即免再走 read_bytes→decode→mask（各候选闭包会重扫同批
    # ``\input`` 目标）；表外件回落 ``_walk_inputs`` 实时读路径，口径不变。
    text_cache = {p: text for p, _rel, text in scanned}

    candidates = []
    bodies = {}
    tpl: dict[str, bool] = {}
    aux: dict[str, bool] = {}

    def _admit(rel: str, text: str) -> None:
        candidates.append(rel)
        # 与 _closure_has_document 的 ``\\begin\s*\{document\}`` 同口径——
        # ``\begin {document}``（空白合法）字面 split 切不到，body 量被
        # 前导区虚抬。
        bodies[rel] = BEGIN_DOC_RX.split(text, maxsplit=1)[-1]
        dc = DOCCLASS_DECL_RX.search(text)
        tpl[rel] = bool(dc and dc.group(2) and "\\" in dc.group(2))
        parts = Path(rel).parts
        tm = _TITLE_ARG_RX.search(text)
        aux[rel] = bool(
            _AUX_NAME_RX.search(Path(rel).stem)
            or any(_AUX_NAME_RX.search(seg) for seg in parts[:-1])
            or (tm and _AUX_TITLE_RX.search(tm.group(1)))
        )

    for p, rel, text in scanned:
        if not DOCCLASS_RX.search(text):
            continue
        if not _closure_has_document(resolved, p, text, virtual, text_cache):
            continue
        _admit(rel, text)
    if not candidates:
        # W99 二遍（纯增量——只把 ``<none>`` 翻成 main，不搅动已有池序）：
        # docclass 可经 ``\input`` 闭包供给（helper 文件/W99 宏参类名，
        # 或 filecontents 虚拟成员）——本体无声明但 bd+dc 双闭包齐者入池。
        for p, rel, text in scanned:
            if not (
                BEGIN_DOC_RX.search(text)
                or INPUT_BRACED_RX.search(text)
                or INPUT_BARE_RX.search(text)
            ):
                continue  # 无 bd 也无 input 边 → 闭包双判定必空
            if not _closure_has_document(resolved, p, text, virtual, text_cache):
                continue
            if not _closure_has_docclass(resolved, p, text, virtual, text_cache):
                continue
            _admit(rel, text)
    if not candidates:
        return None

    def language_rank(path: str) -> bool:
        body = bodies[path]
        letters = sum(c.isalpha() for c in body)
        latin = len(re.findall(r"[A-Za-z]", body))
        return letters > 0 and latin < letters / 2

    masses = {
        rel: _body_mass(
            resolved,
            (resolved / rel).resolve(),
            bodies[rel],
            virtual,
            text_cache,
        )
        for rel in candidates
    }

    # 名加成只计候选最浅层——任意深度 ``main.tex`` 全局抢名槽会让示例/
    # 实验子目录的薄档压过根层真 main（2210.03294 ``4Num_Example/main.tex``
    # 压 ``EoS_iclr2023.tex`` 壳实证）。
    pref_depth = min(len(Path(rel).parts) for rel in candidates)

    candidates.sort(
        key=lambda p: (
            aux[p],
            not (Path(p).name in _PREF_BASENAMES and len(Path(p).parts) <= pref_depth),
            language_rank(p),
            tpl[p],
            len(Path(p).parts),
            -len(str(masses[p])),
            -(root / p).stat().st_size,
        )
    )
    return root / candidates[0]


#: ``classify_no_main`` 的 plain-TeX/AMS-TeX 指纹：``\magnification``/``\magstep``
#: /``\bye``/``\font\<cs>`` 装载原语、裸 ``\end``（负向断言挡 ``\end{env}``）、
#: ``\input`` 的 209 前宏包名（attr 报告 §1.2 实测集 + gr-qc/9901068 补）。
#: 只在无 dc/ds 的空池上判定——LaTeX 工程到不了这层，指纹误伤面天然有界。
_PLAIN_TEX_RE = re.compile(
    r"\\magnification\b|\\magstep\b|\\bye\b|\\font\\|\\end\b(?!\s*\{)"
    r"|\\input\s*\{?\s*(?:harvmac|phyzzx|amstex|amsppt|epsf|jytex|mn|texinfo)\b"
)


def classify_no_main(root: Path) -> str | None:
    r"""``find_main_tex`` 空池归因：确认不可修的上游形态 → 子码；存疑 → ``None``。

    P-D 细分（bench/results/no-main-tex-attr-2026-09-17/report.md §3）——
    全树 ``*.tex`` 遮盖视图（注释/verbatim 内命中不算）上归桶：

    - ``"latex209"``：无 ``\documentclass`` 但有 ``\documentstyle``——209 时代
      池（amsppt 顶物 ``\endtopmatter \document`` 形态；与 route 的
      ``latex209_suspect`` 同族，upgrade_209 是旁路）。
    - ``"plain_tex"``：dc/ds/bd 三无但有 plain-TeX/AMS-TeX 指纹
      （``_PLAIN_TEX_RE``：装载原语 + 209 前 ``\input`` 宏包名）——
      xelatex/tectonic 路由下本不可编，拒绝正确。
    - ``"garbage"``：无任何可判 TeX/LaTeX 结构——HTML/DVI 伪装 .tex、撤稿
      stub、无 driver 残片断、零 ``.tex`` 树。
    - ``None``：可见 ``\documentclass`` 或 ``\begin{document}`` 但链路未闭——
      可能是检测缺口或真散件，票面留 ``no_main_tex`` 不归上游。

    消费方记 ``no_main_tex:<sub>``（stagerun errors payload、fixloop verdict
    后缀、worker/e2e reason 后缀）；``None`` 时票面不变。
    """
    has_ds = has_bd = plain = False
    for p in _iter_files(root, _MAIN_TEX_SUFFIXES):
        raw = _read_tex(p)
        if raw is None:
            continue  # 不可读件/tar 伪装件——成员文本不供 dc/ds/bd/指纹判据
        vis = visible_tex(raw)
        if DOCCLASS_ONLY_RX.search(vis):
            return None
        has_ds |= DOCSTYLE_RX.search(vis) is not None
        has_bd |= BEGIN_DOC_RX.search(vis) is not None
        plain |= _PLAIN_TEX_RE.search(vis) is not None
    if has_ds:
        return "latex209"
    if has_bd:
        return None
    if plain:
        return "plain_tex"
    return "garbage"
