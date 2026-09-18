r"""LaTeX 2.09 ``\documentstyle`` → LaTeX2e ``\documentclass`` 受限升级器。

compat 模式在内核层禁用 ``\usepackage``（探针实证：A 臂 11/11 同签名全灭，
``tmp/latex209-probe/RESULTS.md``）——2.09 文档唯一的 CJK 注入通路是先升级成
2e 形态。本模块只做有界转换：

- 首个非注释 ``\documentstyle[o]{c}`` 改写为 ``\documentclass`` + ``\usepackage``
  拆分。定位走 :func:`texlate.compile.mask.visible_tex` 等长掩码视图——注释与
  verbatim 里的 ``\documentstyle`` 命中不到，且选项段内的穿插注释被掩成空白，
  offset 与原文逐字节对齐，回原文做 span 替换；
- 209 时代类名映射到存续 2e 类（revtex→revtex4-2 等）；未识别类名原样保留，
  缺 ``.cls`` 交 fixloop missing_file → CTAN fetch；
- 选项三路分派：目标类 ``\incompatible@package`` 硬不兼容名（revtex4-2:
  cite/mcite/multicol——loaded 即 ``\ClassError``+``\stop``）剥除记账 →
  内核/目标类内建选项 → 类选项（未知选项进类只是
  "unused global option" warning，错进 ``\usepackage`` 是 missing_file 硬错）；
  已知宏包名或工程随源 ``<opt>.sty`` → ``\usepackage``；默认落类选项。
  multicol 被剥时附 ``\multicols``/``\col@number`` 透传 shim 保正文环境可解析；
- 转换产物尾部附 ``COMPAT_SHIM``——探针实证的 209 内建残留（``\Box`` 系
  latexsym、``\vruleheight``、``\ifoldfss``、``\footheight``、``\tightenlines``、
  ``\@floats``）；
- ``ds@`` 选项机驱动的 style-as-class（ias/jaa/julie，及随源 ``<cls>.sty``/``.cls``
  内检出 ``ds@`` 定义者）不可转——2e 无此分发机制，返回 ``reject`` 状态交
  inject 层按 ``latex209_ds_at`` 拒；
- 改名目标类落盘前做可解析性守卫（盲升闸）：工程树 ``<target>.cls`` 或
  ``kpsewhich`` 双侧均无命中 → 升上去必 missing_file（jpsj3 不在 CTAN），
  按 ``latex209_no_target`` 拒；kpsewhich 缺席/探测失败 fail-open 不阻断。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import TYPE_CHECKING, NamedTuple

from texlate.textutil import (
    DOCSTYLE_DECL_RX,
    DOCSTYLE_RX,
    decode_tex,
    iter_depth0,
)

from .mask import visible_tex

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

#: 选项名/类名的 glob 安全字符集——进 ``root.rglob`` 模式串前必须过闸。
_GLOB_SAFE_RE = re.compile(r"[A-Za-z0-9_.+-]+")

#: 内核级选项：任何类都收，恒留类选项位。
_KERNEL_OPTS = frozenset(
    {
        "10pt",
        "11pt",
        "12pt",
        "letterpaper",
        "legalpaper",
        "executivepaper",
        "a4paper",
        "a5paper",
        "b5paper",
        "landscape",
        "oneside",
        "twoside",
        "onecolumn",
        "twocolumn",
        "draft",
        "final",
        "fleqn",
        "leqno",
        "titlepage",
        "notitlepage",
        "openany",
        "openright",
        "openbib",
        "clock",
        "slide",
    }
)

#: 标准 2e 类——永远真类，不做映射也不做 ds@ 探测。
_STD_CLASSES = frozenset(
    {"article", "report", "book", "letter", "slides", "proc", "minimal", "ltxdoc"}
)


class _ClassSpec(NamedTuple):
    """CLASS_MAP 条目：2e 目标类名 + 类内建选项表 + 209→2e 选项改名表。

    ``options`` 表的路由意义只在抢占宏包白名单冲突（revtex4-2 的 showkeys
    是类内建、同名 showkeys.sty 也存在——类表先判，类选项胜出）；未列名选项
    默认也落类选项，故表只收确定的内建名。
    """

    target: str
    options: frozenset[str] = frozenset()
    rename: Mapping[str, str] = {}


#: 209 时代类名 → 存续 2e 类。revtex 的 209 选项名经 ``rename`` 改写进
#: revtex4-2 词汇表（tighten→tightenlines、floats→floatfix）。
_CLASS_MAP: dict[str, _ClassSpec] = {
    "revtex": _ClassSpec(
        "revtex4-2",
        options=frozenset(
            {
                "aps",
                "aip",
                "jmp",
                "bmf",
                "rmp",
                "prl",
                "pra",
                "prb",
                "prc",
                "prd",
                "pre",
                "prstab",
                "prstper",
                "preprint",
                "reprint",
                "manuscript",
                "superscriptaddress",
                "groupedaddress",
                "unsortedaddress",
                "runinaddress",
                "tightenlines",
                "floatfix",
                "endfloats",
                "longbibliography",
                "nofootinbib",
                "footinbib",
                "bibnotes",
                "nobibnotes",
                "showkeys",
                "showpacs",
            }
        ),
        rename={"tighten": "tightenlines", "floats": "floatfix"},
    ),
    "mn": _ClassSpec(
        "mnras",
        options=frozenset(
            {"referee", "letters", "usegraphicx", "useAMS", "usenatbib", "dcolumn"}
        ),
    ),
    "jpsj": _ClassSpec("jpsj3"),
    "elsart": _ClassSpec(
        "elsarticle",
        options=frozenset(
            {
                "preprint",
                "review",
                "doubleblind",
                "longtitle",
                "1p",
                "3p",
                "5p",
                "authoryear",
                "numbered",
                "number",
                "numbers",
                "sort&compress",
            }
        ),
    ),
    "aipproc": _ClassSpec("aipproc"),
    "amsart": _ClassSpec(
        "amsart",
        options=frozenset(
            {
                "psamsfonts",
                "intlimits",
                "nointlimits",
                "sumlimits",
                "nosumlimits",
                "namelimits",
                "nonamelimits",
                "centertags",
                "notags",
                "reqno",
            }
        ),
    ),
}

#: 209 时代 ``\documentstyle`` 选项位上的真实宏包/随源样式名——这些名字是
#: ``.sty`` 文件，进 ``\usepackage`` 才会真正加载；错留类选项位则静默不加载。
_PKG_OPTS = frozenset(
    {
        # graphics 族（普查高频头：epsfig 83 / epsf 71 / psfig 50）
        "epsf",
        "epsfig",
        "psfig",
        "graphicx",
        "graphics",
        "color",
        "pstricks",
        "rotate",
        # AMS 族
        "amsmath",
        "amstex",
        "amssym",
        "amssymb",
        "amsfonts",
        "amsthm",
        "amscd",
        "diagrams",
        # bib/cite 族
        "natbib",
        "cite",
        "citesort",
        "harvard",
        "apalike",
        "chicago",
        "prabib",
        # 版面/工具
        "epic",
        "eepic",
        "a4",
        "a4wide",
        "dina4",
        "fullpage",
        "times",
        "mathptm",
        "mathptmx",
        "palatino",
        "helvet",
        "multicol",
        "rotating",
        "array",
        "tabularx",
        "multirow",
        "verbatim",
        "moreverb",
        "makeidx",
        "subfigure",
        "supertabular",
        "longtable",
        "float",
        "endnotes",
        "url",
        "ifthen",
        "calc",
        "latexsym",
        "eqsecnum",
        "showkeys",
        "flushrt",
        "hangcaption",
        "nato",
        # AAS/journal 随源惯例（普查高频：aaspp4 13 / aasms4 9；CTAN 有档）
        "aaspp4",
        "aasms4",
        "aas2pp4",
        "aastex",
        "espcrc2",
        "emulateapj",
    }
)

#: 目标类硬不兼容宏包——类内 ``\incompatible@package`` 声明，loaded 即
#: ``\ClassError``+``\stop``（revtex4-2.cls:6453-6455：cite/mcite/multicol 与
#: ltxgrid 输出例程互斥）。命中即从选项剥除——留类选项位成 unused-option
#: warning 失语义，进 ``\usepackage`` 必死；剥除名记入 ``info["stripped"]``。
_INCOMPAT_PKGS: dict[str, frozenset[str]] = {
    "revtex4-2": frozenset({"cite", "mcite", "multicol"}),
}

#: 实证 ds@ 选项机类（随源 .sty 以 ``\ds@<opt>``/``\@namedef{ds@<opt>}`` 分发
#: 选项；2e 无此机制，ias.cls 也不存在——无树可调时按名硬拒）。
_DS_AT_CLASSES = frozenset({"ias", "jaa", "julie"})

#: ``ds@`` 选项分发记号——词首边界锚：``\ds@<opt>`` 命令形态与
#: ``\@namedef{ds@<opt>}``/``\csname ds@<opt>`` 调用形态全收（``\``/``{``/空白
#: 均为非字字符、``d`` 处成界）；``\mids@foo``/``\ods@x`` 这类内嵌子串
#: 前接字母不成界，不误伤。检索面过 ``visible_tex`` 等长遮盖——注释/逐字段里
#: 的 ``ds@`` 字样（``% uses ds@ dispatch``）不计。
_DS_AT_RE = re.compile(r"\bds@")

#: 209 内建残留的 compat 块——随转换产物注入，全部幂等/守护式定义。
COMPAT_SHIM = r"""% texlate: LaTeX 2.09 compatibility shim
\usepackage{latexsym}
\providecommand{\vruleheight}{\vrule height}
\providecommand{\tightenlines}{}
\newif\ifoldfss
\makeatletter
\newif\if@floats
\makeatother
\ifx\footheight\undefined\newlength{\footheight}\fi
% 209 revtex d 列 (decimal) → 兜底为居中列; \newcolumntype 撞已注册列型
% 会报错, 须以 array 内部注册点 \NC@find@<char> 的 \@ifundefined 守护。
% d→c 而非 dcolumn D 列: 胞元含裸 $ 对时 D 列数学包壳翻转出 math 报错。
\makeatletter
\@ifundefined{NC@find@d}{\RequirePackage{array}\newcolumntype{d}{c}}{}
\makeatother"""


#: ``multicols``/``multicols*`` 透传环境——multicol 被剥后正文 ``\begin{multicols}{n}``
#: 仍需可解析（209 revtex 单栏时代作者常用它裹整个正文凑双栏；revtex4-2 的
#: ltxgrid 已接管分页，列数参弃之）。``\newcount\col@number`` 置 0 中和
#: ltxgrid longtable 分支 ``\ifnum\col@number>\@ne`` 的缺数软错。
_MULTICOLS_SHIM = r"""% texlate: multicol incompatible with target class — env passthrough
\makeatletter
\ifx\multicols\@undefined
\newenvironment{multicols}[1]{}{}
\newenvironment{multicols*}[1]{}{}
\newcount\col@number
\fi
\makeatother"""


def _split_opts(optspan: str | None) -> list[str]:
    """从掩码视图选项段提选项名。

    注释字符已被 ``visible_tex`` 掩成空白、真实空白本就该剥——非空白字符即
    选项文本；逗号切分后空段（被整段注释掉的选项）丢弃。
    """
    if not optspan:
        return []
    compact = "".join(c for c in optspan if not c.isspace())
    return [o for o in compact.split(",") if o]


def _ships_style(root: Path | None, name: str) -> bool:
    """工程树内检出随源 ``<name>.sty``——该选项是随稿样式文件，走 usepackage。"""
    if root is None or ".." in name or not _GLOB_SAFE_RE.fullmatch(name):
        return False
    return any(root.rglob(f"{name}.sty"))


def _uses_ds_at(root: Path | None, cls: str) -> bool:
    """随源 ``<cls>.sty``/``<cls>.cls`` 检出 ``ds@`` 选项分发定义。

    检索面为 ``visible_tex`` 遮盖视图——注释/逐字环境内的 ``ds@`` 字样
    不参与判定（真分发形态见 ``_DS_AT_RE`` 注）。
    """
    if root is None or ".." in cls or not _GLOB_SAFE_RE.fullmatch(cls):
        return False
    for cand in root.rglob(f"{cls}.*"):
        if cand.suffix not in {".sty", ".cls"}:
            continue
        try:
            text = decode_tex(cand.read_bytes())
        except OSError:
            continue
        if _DS_AT_RE.search(visible_tex(text)):
            return True
    return False


def _target_resolvable(root: Path | None, target: str) -> bool:
    """改名目标类可解析性——工程树 ``<target>.cls`` 或系统 kpsewhich 命中。

    kpsewhich 缺席/探测失败 fail-open：合法映射目标都在系统 texmf，缺工具
    不阻断（``_kpse_resolve`` 同款语义）；真返回空才判不可解析。
    """
    if (
        root is not None
        and _GLOB_SAFE_RE.fullmatch(target)
        and any(root.rglob(f"{target}.cls"))
    ):
        return True
    kpse = shutil.which("kpsewhich")
    if kpse is None:
        return True
    try:
        proc = subprocess.run(  # noqa: S603 — 固定 argv 无 shell
            [kpse, "--", f"{target}.cls"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _route_opts(
    opts: list[str], spec: _ClassSpec | None, root: Path | None, target: str
) -> tuple[list[str], list[str], list[str], list[str]]:
    """选项三路分派 → ``(class_opts, pkg_opts, shipped_hits, stripped)``。

    判别序：209 选项名先经目标类 ``rename`` 表改写成 2e 词汇，再查目标类
    硬不兼容表（剥除）→ 内核选项 → 目标类内建表 → 宏包白名单/随源
    ``.sty`` → 默认落类选项。
    """
    incompat = _INCOMPAT_PKGS.get(target, frozenset())
    cls_opts: list[str] = []
    pkg_opts: list[str] = []
    shipped: list[str] = []
    stripped: list[str] = []
    for opt in opts:
        o = spec.rename.get(opt, opt) if spec is not None else opt
        if o in incompat:
            stripped.append(o)
        elif o in _KERNEL_OPTS or (spec is not None and o in spec.options):
            cls_opts.append(o)
        elif o in _PKG_OPTS or _ships_style(root, o):
            pkg_opts.append(o)
            if o not in _PKG_OPTS:
                shipped.append(o)
        else:
            cls_opts.append(o)
    return cls_opts, pkg_opts, shipped, stripped


def _primary_docstyle(vis: str) -> re.Match[str] | None:
    r"""首个 brace 深度 0 的 ``\documentstyle``——真声明点。

    深度>0 命中（``\newcommand{\ds}{\documentstyle{..}}`` 宏体、``\ifmain{..}``
    实参）不是声明点——全文搜首个会把 COMPAT_SHIM 塞进 def 体（fuzz I5）。
    """
    return next(iter_depth0(DOCSTYLE_DECL_RX, vis), None)


def upgrade_209(tex: str, *, root: Path | None = None) -> tuple[str, dict]:
    r"""首个深度 0 ``\documentstyle`` 升级为 2e 形态；返回 ``(new_tex, info)``。

    ``root`` 提供工程树（可选）：选项位检出随源 ``<opt>.sty`` 进 ``\usepackage``；
    未映射类名检出随源 ``<cls>.sty/.cls`` 且含 ``ds@`` 定义 → 拒转。
    残余的活 ``\documentstyle`` 记号（宏体/次分支）逐 token 改名
    ``\documentclass``——compat 下二次声明照样非法。

    ``info["status"]`` ∈ ``converted`` / ``reject`` / ``no-docstyle``；``reject``
    时 ``info["reason"]`` 供 inject 层记 ``inject_reject:<reason>``。
    """
    vis = visible_tex(tex)
    m = _primary_docstyle(vis)
    if m is None:
        if next(iter_depth0(DOCSTYLE_RX, vis), None) is not None:
            # 深度 0 裸 ``\documentstyle`` token 在场但配不出 ``[opt]{cls}``
            # 声明（残缺尾、选项段异常）——inject.find_docclass_ends 同深度
            # 口径会把它当缝走到这里，泛 ``latex209`` 落账混进真 209 拒收，
            # 细分签名供归因。深度>0 宏体残影（未闭合花括号内 token）
            # 不进此桶——inject 同深度口径也不会触达。
            return tex, {"status": "reject", "reason": "latex209_no_decl"}
        return tex, {"status": "no-docstyle"}
    cls = m.group(2).strip()
    if not cls:
        return tex, {"status": "no-docstyle"}
    if cls in _DS_AT_CLASSES or (
        cls not in _CLASS_MAP and cls not in _STD_CLASSES and _uses_ds_at(root, cls)
    ):
        return tex, {
            "status": "reject",
            "reason": "latex209_ds_at",
            "class": cls,
        }
    spec = _CLASS_MAP.get(cls)
    target = spec.target if spec is not None else cls
    if target != cls and not _target_resolvable(root, target):
        # 盲升守卫：改名目标类双侧（工程/系统 texmf）不可解析——升上去
        # missing_file 必死（jpsj→jpsj3 类不在 CTAN），拒转记台账。
        return tex, {
            "status": "reject",
            "reason": "latex209_no_target",
            "class": cls,
            "target": target,
        }
    cls_opts, pkg_opts, shipped, stripped = _route_opts(
        _split_opts(m.group(1)), spec, root, target
    )
    lines = [
        f"\\documentclass[{','.join(cls_opts)}]{{{target}}}"
        if cls_opts
        else f"\\documentclass{{{target}}}",
        COMPAT_SHIM,
    ]
    if "multicol" in stripped:
        lines.append(_MULTICOLS_SHIM)
    if pkg_opts:
        # shim 必须先于路由出的 \usepackage——209 时代 .sty 加载时就要见到
        # \footheight/\ifoldfss 等定义（2501.05407 nips.sty 实证）。
        lines.append("\\usepackage{" + ",".join(pkg_opts) + "}")
    new_tex = tex[: m.start()] + "\n".join(lines) + tex[m.end() :]
    # 残余 \documentstyle 记号改名（遮盖视图定位、原文回填，倒序保 offset）。
    vis2 = visible_tex(new_tex)
    for dm in reversed([*DOCSTYLE_RX.finditer(vis2)]):
        new_tex = new_tex[: dm.start()] + "\\documentclass" + new_tex[dm.end() :]
    return new_tex, {
        "status": "converted",
        "orig": tex[m.start() : m.end()],
        "class": cls,
        "target": target,
        "class_opts": cls_opts,
        "pkg_opts": pkg_opts,
        "shipped": shipped,
        "stripped": stripped,
    }
