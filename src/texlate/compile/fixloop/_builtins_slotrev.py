r"""_builtins_slotrev — zh 机位实参 revert (slotrevert lane, task#188)。

机制 (tmp/lane-zhleak/notes.md): segmenter 把未注册机位实参 (csname 体 /
未注册 env 尾随参等) 放上 chunk 翻译字面量面 → zh 化后 splice 写回
机位 → ``Undefined color '这是译文'``/``No counter``/``can't find file``
族。本叶做决定性 revert: ``judge.py`` ``_MACHINE_SLOT_RXS`` + 本叶扩展
表在 ``mask_tex`` 等长遮盖视图 (``_DEAD_TAIL_RX`` 死尾截断同口径) 上
定位机位实参, 对 ``params.baseline_dir`` pristine 树逐文件做 per-kind
序号对齐配对 —— baseline 参纯 ASCII 标识符 ∧ zh 参含 CJK ∧ 两侧
相异 → zh 参位字节换回 baseline 参。``\section{标题}`` 等文位结构上
不在机位表内永不被碰; 某 kind 双侧命中数分歧 → 该 kind 整跳防错位
回写 (LLM 臆造/丢参时错位 revert 比不复原更糟); ``baseline_dir``
缺席/非目录 → False 空转 (standalone precheck 挂点不注入 baseline)。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_bib import _CITE_FAMILY_RE
from texlate.textutil import CJK_RX, CMD_BOUNDARY, mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx

#: ``compile.probe._DEAD_TAIL_RE``/``judge._DEAD_TAIL_RX`` 同口径死尾截断:
#: ``\end{document}``/``\endinput`` 之后同形 token 非活 slot。
_DEAD_TAIL_RX = re.compile(r"\\end\s*\{document\}|\\endinput\b")

#: 同命令相邻实参间空白 (跨行随意); 仅 envarg 尾随参用受限 _GAP。
_ARG = r"\{([^{}\n]*)\}"
_OPT = r"\[[^\]\n]*\]"  # opt 位只吃不捕 (非 revert 面)
_OPTC = r"\[([^\]\n]*)\]"  # opt 位捕获 (revert 面: 计数/包选项/label)
#: envarg 尾随参 gap: 同行空白 + 至多一个换行 —— 空行=\par 截断 arg
#: 扫描 (TeX 无 \long 参扫描语义), 防 ``\begin{env}`` 后散文 ``{word}``
#: 误收。
_GAP = r"[^\S\n]*(?:\n[^\S\n]*)?"

#: 扩展机位表 —— judge ``_MACHINE_SLOT_RXS`` 不盖的机位头族, 逐
#: ``(kind, rx)``; rx 捕获组全为机位实参候选, 同一文件 src/zh 双侧
#: 命中数必须相等否则整 kind 跳。不改 judge 表: verdict 面
#: (``paired_slot_diff``/``machine_slot_audit``) 行为字节级不变。
_SLOTREV_EXTRA_RXS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # \begin{env}[opt]{mand}×≤4 —— 未注册 env 尾随机参
    # (translatedabstract{french}/Mizar{x,Y,A} 实证锚点); opt 位与
    # 尾随 mand 参全收。末臂 ``|_OPTC`` 收 opt-only 站
    # (\begin{tikzpicture}[kv] 类)。
    (
        "envarg",
        re.compile(
            r"\\begin\s*\{[^{}\n]*\}"
            + _GAP
            + r"(?:(?:"
            + _OPTC
            + _GAP
            + r")?"
            + _ARG
            + r"(?:"
            + _GAP
            + _ARG
            + r")?"
            + r"(?:"
            + _GAP
            + _ARG
            + r")?"
            + r"(?:"
            + _GAP
            + _ARG
            + r")?"
            + r"|"
            + _OPTC
            + r")"
        ),
    ),
    # \color/\textcolor/\pagecolor/\rowcolor [model]?{name}
    (
        "color",
        re.compile(
            r"\\(?:color|textcolor|pagecolor|rowcolor)"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
        ),
    ),
    # \colorbox[model]?{color}{text} —— 参0 (text 是散文不碰)
    (
        "colorbox",
        re.compile(r"\\colorbox" + CMD_BOUNDARY + r"\s*(?:" + _OPT + r"\s*)?" + _ARG),
    ),
    # \fcolorbox[model]?{frame}{bg}{text} —— 前两色参
    (
        "fcolorbox",
        re.compile(
            r"\\fcolorbox"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # \definecolor/\providecolor/\xdefinecolor/\preparecolor ——
    # {name}{model}{spec} 三参全机位
    (
        "defcolor",
        re.compile(
            r"\\(?:definecolor|providecolor|xdefinecolor|preparecolor)"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
            + r"\s*"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # \colorlet[model]?{new}{expr} —— 两参
    (
        "colorlet",
        re.compile(
            r"\\colorlet"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # 计数器名参0: \setcounter/\addtocounter/\refstepcounter/\stepcounter/
    # \value/\arabic/\roman/\Roman/\alph/\Alph/\fnsymbol/\usecounter
    (
        "counter",
        re.compile(
            r"\\(?:setcounter|addtocounter|refstepcounter|stepcounter|value|"
            r"arabic|roman|Roman|alph|Alph|fnsymbol|usecounter)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
        ),
    ),
    # \newcounter{name}[within] —— within 也是计数名
    (
        "newcounter",
        re.compile(
            r"\\newcounter" + CMD_BOUNDARY + r"\s*" + _ARG + r"(?:\s*" + _OPTC + r")?"
        ),
    ),
    # \counterwithin/\counterwithout/\numberwithin/\numberwithout {x}{y}
    (
        "counterw",
        re.compile(
            r"\\(?:counterwithin|counterwithout|numberwithin|numberwithout)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # etoolbox \newtoggle/\providetoggle/\toggletrue/\togglefalse —— 名参
    (
        "toggle",
        re.compile(
            r"\\(?:newtoggle|providetoggle|toggletrue|togglefalse)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
        ),
    ),
    # \iftoggle{name}{t}{f} —— 参0 (分支是散文不碰)
    (
        "iftoggle",
        re.compile(r"\\iftoggle" + CMD_BOUNDARY + r"\s*" + _ARG),
    ),
    # \setkeys/\kvsetkeys [opt]?{fam}{list} —— fam 参0 (list 太宽不收)
    (
        "setkeys",
        re.compile(
            r"\\(?:setkeys|kvsetkeys)"
            + CMD_BOUNDARY
            + r"\*?\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
        ),
    ),
    # kv 头族 [opt]?{kv-list}: opt 与整 kv 参都按原子 revert (kv 串
    # 逗号等号在 ident 白名单内; 含散文值 ⇒ 空格破 ident 自动不碰)
    (
        "kv",
        re.compile(
            r"\\(?:hypersetup|pgfkeys|pgfqkeys|psset|tikzset|forestset|"
            r"tcbset|lstset|sisetup|ctexset|xeCJKsetup|setlist|"
            r"captionsetup|subcaptionsetup|geometry|newgeometry|"
            r"ExecuteOptions|ProcessOptions|ProcessOptionsX|"
            r"ExecuteBibliographyOptions|DeclareKeys|SetKeys)"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPTC
            + r"\s*)?"
            + _ARG
        ),
    ),
    # expl3 \keys_set:nn/\keys_define:nn {module}{kv} —— 双机位参
    (
        "expl3kv",
        re.compile(
            r"\\(?:keys_set:nn|keys_define:nn|keys_precompile:nnN?)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # \footnote/\footnotemark/\footnotetext [n] —— opt 标号机参
    # (mand 参是散文不碰)
    (
        "footopt",
        re.compile(
            r"\\(?:footnote|footnotemark|footnotetext)" + CMD_BOUNDARY + r"\s*" + _OPTC
        ),
    ),
    # \usepackage/\RequirePackage*/\documentclass/\documentstyle/
    # \LoadClass* [opt]?{name} —— opt+名两参 (还原实名供 static_precheck
    # 装包扫描收)
    (
        "pkg",
        re.compile(
            r"\\(?:usepackage|RequirePackage|RequirePackageWithOptions|"
            r"documentclass|documentstyle|LoadClass|LoadClassWithOptions)"
            + CMD_BOUNDARY
            + r"\*?\s*(?:"
            + _OPTC
            + r"\s*)?"
            + _ARG
        ),
    ),
    # \PassOptionsToPackage/\PassOptionsToClass {opts}{pkg}
    (
        "passopt",
        re.compile(
            r"\\PassOptionsTo(?:Package|Class)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # \newenvironment/\renewenvironment/\provideenvironment/\newtheorem/
    # \newcolumntype/\NewEnviron/\RenewEnviron/\DeclareFloatingEnvironment
    # —— 声明名参0 (后随 [n]/{before}/{after}/{Text} 散文位不碰)
    (
        "envdecl",
        re.compile(
            r"\\(?:newenvironment|renewenvironment|provideenvironment|"
            r"newtheorem|newcolumntype|NewEnviron|RenewEnviron|"
            r"DeclareFloatingEnvironment)" + CMD_BOUNDARY + r"\*?\s*" + _ARG
        ),
    ),
    # \newglossaryentry/\newacronym/\lstdefinelanguage —— 键/名参0
    (
        "decl",
        re.compile(
            r"\\(?:newglossaryentry|newacronym|lstdefinelanguage)"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
        ),
    ),
    # babel/polyglossia 语言名: \selectlanguage/\setdefaultlanguage/
    # \setmainlanguage/\setotherlanguage/\setotherlanguages/
    # \foreignlanguage [opt]?{lang} —— foreignlanguage 参1 散文不碰
    (
        "lang",
        re.compile(
            r"\\(?:selectlanguage|setdefaultlanguage|setmainlanguage|"
            r"setotherlanguage|setotherlanguages|foreignlanguage)"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPTC
            + r"\s*)?"
            + _ARG
        ),
    ),
    # fontspec 族 —— 字体名参 (loose ident 许空格/'/()/&);
    # \newfontfamily\cs{Font} 间置 \cs 经 (?:\\[a-zA-Z@]+\s*)? 收
    (
        "font",
        re.compile(
            r"\\(?:setmainfont|setsansfont|setmonofont|setmathrm|"
            r"setmathsf|setmathtt|setboldmathrm|setoperatorfont|"
            r"setCJKmainfont|setCJKsansfont|setCJKmonofont|fontspec|"
            r"newfontfamily|newfontface|defaultfontfeatures|"
            r"addfontfeatures|addfontfeature)"
            + CMD_BOUNDARY
            + r"\s*(?:\\[a-zA-Z@]+\s*)?(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
        ),
    ),
    # \bibliographystyle{style}
    (
        "bibstyle",
        re.compile(r"\\bibliographystyle" + CMD_BOUNDARY + r"\s*" + _ARG),
    ),
    # \usetikzlibrary/\usepgflibrary/\usepgfganttlibrary/\usepgfplotslibrary
    (
        "libs",
        re.compile(
            r"\\use(?:tikzlibrary|pgflibrary|pgfganttlibrary|pgfplotslibrary)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
        ),
    ),
    # 单参机名族: \pagenumbering/\pagestyle/\thispagestyle/\theoremstyle/
    # \mathversion/\citestyle + beamer \use*theme 族
    (
        "name",
        re.compile(
            r"\\(?:pagenumbering|pagestyle|thispagestyle|theoremstyle|"
            r"mathversion|citestyle|usetheme|usecolortheme|usefonttheme|"
            r"useoutertheme|useinnertheme)"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
        ),
    ),
    # 文件路径单参族: \InputIfFileExists/\IfFileExists/\ProvidesFile/
    # \ProvidesPackage/\ProvidesClass/\ProvidesExplPackage/
    # \lstinputlisting/\verbatiminput/\VerbatimInput/\includeverbatim/
    # \includepdf/\includesvg/\includeonly/\includestandalone/
    # \externaldocument/\tikzsetnextfilename/\nobibliography
    (
        "filearg",
        re.compile(
            r"\\(?:InputIfFileExists|IfFileExists|ProvidesFile|"
            r"ProvidesPackage|ProvidesClass|ProvidesExplPackage|"
            r"lstinputlisting|verbatiminput|VerbatimInput|includeverbatim|"
            r"includepdf|includesvg|includeonly|includestandalone|"
            r"externaldocument|tikzsetnextfilename|nobibliography)"
            + CMD_BOUNDARY
            + r"\*?\s*"
            + _ARG
        ),
    ),
    # \import/\subimport/\includefrom/\subincludefrom/\inputminted {dir}{file}
    (
        "import",
        re.compile(
            r"\\(?:import|subimport|includefrom|subincludefrom|inputminted)"
            + CMD_BOUNDARY
            + r"\*?\s*"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # \addcontentsline/\addtocontents {toc}{level/entry} —— 前两机位参
    # (tocline 文本参不碰)
    (
        "tocline",
        re.compile(
            r"\\(?:addcontentsline|addtocontents)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # \url/\href/\nolinkurl/\email/\doi/\orcidlink 参0 (href 参1 散文不碰)
    (
        "url",
        re.compile(
            r"\\(?:url|href|nolinkurl|email|doi|orcidlink)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
        ),
    ),
    # \hyperref[label]{text} —— opt label (text 散文不碰)
    (
        "hyperref",
        re.compile(r"\\hyperref" + CMD_BOUNDARY + r"\s*" + _OPTC),
    ),
    # 交叉引用扩展族 (judge ref 行只盖 label/ref/eqref/pageref/autoref):
    # \cref/\Cref/\crefrange/\cpageref/\vref/\vpageref/\nameref/\refeq/
    # \subref/\itemref/\footref/\thmref —— 键参0
    (
        "refx",
        re.compile(
            r"\\(?:cref|Cref|crefrange|Crefrange|cpageref|vref|vpageref|"
            r"nameref|refeq|subref|itemref|footref|thmref)"
            + CMD_BOUNDARY
            + r"\*?\s*(?:"
            + _OPT
            + r"\s*)*"
            + _ARG
        ),
    ),
    # glossaries/acronym 引用族 —— 键参0 (\glssee 参1 也是键表但随行)
    (
        "gls",
        re.compile(
            r"\\(?:ac|acs|acf|acl|acp|acrfull|acrshort|acrlong|acrshortpl|"
            r"acrlongpl|acrfullpl|gls|glspl|Gls|Glspl|glslink|glsdisp|"
            r"glssee|glsadd|glsdesc|glsxtrshort|glsxtrlong|glsxtrfull)"
            + CMD_BOUNDARY
            + r"\*?\s*(?:"
            + _OPT
            + r"\s*)*"
            + _ARG
        ),
    ),
    # minted \mintinline/\mint/\newmintinline/\newmint {lang} —— 语言名参
    (
        "mint",
        re.compile(
            r"\\(?:mintinline|mint|newmintinline|newmint)"
            + CMD_BOUNDARY
            + r"\*?\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
        ),
    ),
    # \newfloat{name}{placement}{ext} (float 包) —— 三参全机位
    (
        "newfloat",
        re.compile(
            r"\\newfloat" + CMD_BOUNDARY + r"\s*" + _ARG + r"\s*" + _ARG + r"\s*" + _ARG
        ),
    ),
)

#: 严格 ident 白名单 —— 机位实参 (键/名/路径/kv 串/csv) 的字符域。
_IDENT_STRICT_RX = re.compile(r"[A-Za-z0-9@._/:+*!,=~-]+")
#: 宽松 ident —— 仅 font kind: 字体名含空格/'/()/& ("Times New Roman")。
_IDENT_LOOSE_RX = re.compile(r"[A-Za-z0-9@._/:+*!,=~ '()&-]+")
_IDENT_LOOSE_KINDS = frozenset({"font"})

#: note 面站点/分歧条目封顶 (与 judge._MACHINE_SLOT_MAX 同量级)。
_NOTE_CAP = 20


def _is_ident(arg: str, kind: str) -> bool:
    """机位标识符谓词: font 类用宽松名单 (字体名含空格), 其余严格。"""
    rx = _IDENT_LOOSE_RX if kind in _IDENT_LOOSE_KINDS else _IDENT_STRICT_RX
    return rx.fullmatch(arg) is not None


def _slot_spans(
    src: str, rxs: tuple[tuple[str, re.Pattern[str]], ...]
) -> list[tuple[str, int, int]]:
    r"""单文件源文机位命中 → ``(kind, start, end)`` 序对 (原文 offset)。

    ``judge._slot_args`` 同口径的 ``mask_tex`` 视图 + 死尾截断, 每 match
    全部非 None 捕获组各自入列, 但保留位置供回写 —— arg 切片区间为
    ``src[start:end]``。
    """
    view = mask_tex(src)
    dead = _DEAD_TAIL_RX.search(view)
    if dead is not None:
        view = view[: dead.start()]
    hits: list[tuple[str, int, int]] = []
    for kind, rx in rxs:
        for m in rx.finditer(view):
            hits.extend(
                (kind, m.start(i), m.end(i))
                for i, g in enumerate(m.groups(), start=1)
                if g is not None
            )
    return hits


def _by_kind(hits: list[tuple[str, int, int]]) -> dict[str, list[tuple[int, int]]]:
    """命中按 kind 归桶, 桶内保文档序 (表行序→finditer 序)。"""
    d: dict[str, list[tuple[int, int]]] = {}
    for kind, s, e in hits:
        d.setdefault(kind, []).append((s, e))
    return d


def _revert_file(
    src: str, zh: str, rxs: tuple[tuple[str, re.Pattern[str]], ...]
) -> tuple[str, int, list[str]]:
    r"""单文件 src/zh 配对 revert → ``(新 zh 文本, 改写数, 分歧项)``。

    per-kind 序号对齐: k-th zh 命中 ↔ k-th src 命中; 三条件全中才改 —
    双侧相异 ∧ zh 参含 CJK ∧ src 参纯 ident (ASCII 白名单)。改集按
    起始位降序右→左应用, 同位/重叠第二刀跳 (envarg↔restatable 等同位
    多行扫重)。kind 双侧命中数分歧 → 该 kind 整跳记入 ``分歧项``。
    """
    src_by = _by_kind(_slot_spans(src, rxs))
    zh_by = _by_kind(_slot_spans(zh, rxs))
    if not zh_by:
        return zh, 0, []
    edits: list[tuple[int, int, str]] = []
    skipped: list[str] = []
    kinds = list(zh_by) + [k for k in src_by if k not in zh_by]
    for kind in kinds:
        ss, zs = src_by.get(kind, []), zh_by.get(kind, [])
        if len(ss) != len(zs):
            skipped.append(f"{kind}({len(ss)}!={len(zs)})")
            continue
        for (s0, s1), (z0, z1) in zip(ss, zs, strict=True):
            sarg, zarg = src[s0:s1], zh[z0:z1]
            if sarg == zarg or not CJK_RX.search(zarg) or not _is_ident(sarg, kind):
                continue
            edits.append((z0, z1, sarg))
    n = 0
    floor = len(zh) + 1
    for z0, z1, sarg in sorted(edits, key=lambda t: (-t[0], -t[1])):
        if z1 > floor:
            continue
        zh = zh[:z0] + sarg + zh[z1:]
        floor = z0
        n += 1
    return zh, n, skipped


def _full_rxs() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """机位全表: judge ``_MACHINE_SLOT_RXS`` + cite 族 + 本叶扩展行。"""
    from texlate.compile.judge import (  # noqa: PLC0415  # 延迟: fixloop 链重
        _MACHINE_SLOT_RXS,
    )

    return (*_MACHINE_SLOT_RXS, ("cite", _CITE_FAMILY_RE), *_SLOTREV_EXTRA_RXS)


def _revert_tree(
    ctx: LoopCtx, base_root: Path, rxs: tuple[tuple[str, re.Pattern[str]], ...]
) -> tuple[list[str], list[str], int]:
    """逐 ``*.tex`` 与 baseline 同名件配对 revert → (件条目, 分歧项, 改数)。"""
    reverted: list[str] = []
    skipped: list[str] = []
    n_args = 0
    for f in ctx.tex_files((".tex",)):
        rel = f.relative_to(ctx.wdir).as_posix()
        zh = ctx.read(f)
        if zh is None:
            continue
        try:
            src = (base_root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if src == zh:
            continue
        new_text, n, sk = _revert_file(src, zh, rxs)
        skipped.extend(f"{rel}:{s}" for s in sk)
        if n:
            ctx.write(f, new_text)
            reverted.append(f"{rel}×{n}")
            n_args += n
    return reverted, skipped, n_args


def slot_arg_revert(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""把 zh 化机位实参按 ``params.baseline_dir`` pristine 树配对还原。

    precheck 位一次性跑 (L2 resplice 之后的首个耐写入点): 逐 ``*.tex``
    与 baseline 同名件做 per-kind 序号对齐配对, ``src`` 参为纯 ASCII
    标识符而 ``zh`` 参含 CJK → zh 参位换回 src 字节 (``ctx.write``
    记账写)。空转判据自证幂等 —— 机位参无 CJK 即不重扫写。
    """
    del eng, payload
    base_dir = params.get("baseline_dir")
    if not base_dir:
        return False, "no baseline_dir param"
    base_root = Path(str(base_dir))
    if not base_root.is_dir():
        return False, f"baseline_dir not a directory: {base_root}"
    reverted, skipped, n_args = _revert_tree(ctx, base_root, _full_rxs())
    if not reverted:
        note = "no zh machine-slot args to revert"
        if skipped:
            note += f"; divergent: {', '.join(skipped[:_NOTE_CAP])}"
        return False, note
    note = f"reverted {n_args} args in {len(reverted)} files: "
    note += ", ".join(reverted[:_NOTE_CAP])
    if len(reverted) > _NOTE_CAP:
        note += f" +{len(reverted) - _NOTE_CAP} files"
    if skipped:
        note += f"; divergent: {', '.join(skipped[:_NOTE_CAP])}"
    return True, note
