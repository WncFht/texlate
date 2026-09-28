"""静态路由表 —— ``route_project``/``engine_for`` + 签名集（``engine.py`` 拆分叶）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple, cast

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any, Final

    from ._base import Engine

from texlate.compile.mask import visible_tex
from texlate.compile.transcode import _iter_files
from texlate.textutil import DOCSTYLE_RX, decode_tex_with

from ._tectonic import TectonicEngine
from ._xelatex import XelatexEngine


# ================================================================ 静态路由表
@dataclass
class RouteDecision:
    """`route_project` 产物：引擎优先序 + 拒绝/降级原因。"""

    engines: list[str]  # 优先序，如 ["tectonic", "xelatex"]
    # 保留槽位：latex209 无条件拒已移 fixloop gate，route 现恒 None；
    # worker/e2e 的死检查即此槽位的预留消费点，留作将来"编译前必拒"语义。
    reject: str | None = None
    reasons: list[str] = field(default_factory=list)
    non_utf8: bool = False  # 非 UTF-8 源（需 iconv 预处理提示）
    latex209_suspect: bool = False  # \documentstyle 检出：降级为试编标记


#: pstricks/位图字体信号的名集单源——route_project 的文本签名与 probe 的
#: 声明依赖名查表共用（audit wave2 双表合一：probe.py 导入此处常量）。
#: pstricks 家族语义 = 精确名 ``pstricks`` + 前缀 ``pstricks-``/``pst-``
#: （pst-node/pst-plot/… 与 pstricks-add 全覆盖——probe 侧旧实现漏
#: pstricks-add，切名集后补齐）。
PSTRICKS_PKG_NAMES: Final = frozenset({"pstricks"})
PST_PKG_PREFIXES: Final = ("pstricks-", "pst-")
BITMAP_FONT_PKG_NAMES: Final = frozenset(
    {"bbm", "bbmfonts", "dsfont", "bbold", "yfonts", "wasy", "wasysym"}
)

#: 高置信 pstricks 依赖签名（visible_tex 遮蔽视图上匹配）：包名元素级
#: 精确（pstricks / pstricks-add / pst-* 家族——元素边界防 `{notpstricks}`
#: 类子串误中）+ `pspicture` 环境 + `\psset` 配置宏（vendored/传递装载的
#: 兜底信号，0905.2435/0905.4369 实证）。裸 `\psline`/`\psframe` 族不收——
#: polyfill 守卫与自定义宏残影假命中（corpus 全扫零独立命中；新口径
#: 68 vs 旧 61，反增收 `{amsmath,pstricks}` 非首元素声明）。
#: 交替支单源：本叶 ``_PSTRICKS_RE`` 与 fixloop ``_FAMILY_TOKENS``
#: （``@pstricks``——30-route.yaml 两规则外置行锚后嵌入）共用；两侧均按
#: ``sorted(-len, s)`` 定序拼交替，口径零漂移。
PSTRICKS_SIG_ALTS: Final = frozenset(
    {
        (
            r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*"
            r"\{[^}]*?\b(?:pstricks(?:-\w+)?|pst-\w+)\b"
        ),
        r"\\begin\s*\{pspicture\*?\}",
        r"\\pspicture\b",
        r"\\psset\b",
    }
)
_PSTRICKS_RE = re.compile("|".join(sorted(PSTRICKS_SIG_ALTS, key=lambda s: (-len(s), s))))
_MINTED_FROZEN_RE = re.compile(r"frozencache")
#: ``frozencache`` 须与 minted 装载共现才翻 tectonic 优先（§4.2
#: "frozencache + minted"）——散文裸提 ``frozencache`` 词不构成信号。
_MINTED_PKG_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{[^}]*\bminted2?\b"
)
_BITMAP_FONT_PKGS = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{[^}]*\b("
    + "|".join(sorted(BITMAP_FONT_PKG_NAMES))
    + r")\b"
)
#: dvips 原语插图 ``\special{psfile=..}``——xdvipdfmx/tectonic 均不渲染，
#: 无双引擎可行路径，检出只注记不改引擎序（probe.py 同款口径）。
_PSFILE_SPECIAL_RE = re.compile(r"\\special\s*\{\s*psfile\b")


class _RouteSigs(NamedTuple):
    """route_project 静态信号集——文件面布尔 + 文本签名布尔。"""

    eps: bool
    mf: bool
    pstricks: bool
    minted_frozen: bool
    bitmap_fonts: bool
    psfile_special: bool


def _route_sigs(exts: set[str], blob_vis: str) -> _RouteSigs:
    """文件后缀集 + 遮盖视图 blob → 静态路由信号集。"""
    return _RouteSigs(
        eps=".eps" in exts,
        mf=".mf" in exts,
        pstricks=bool(_PSTRICKS_RE.search(blob_vis)),
        minted_frozen=bool(
            _MINTED_FROZEN_RE.search(blob_vis) and _MINTED_PKG_RE.search(blob_vis)
        ),
        bitmap_fonts=bool(_BITMAP_FONT_PKGS.search(blob_vis)),
        psfile_special=bool(_PSFILE_SPECIAL_RE.search(blob_vis)),
    )


def _apply_route_sigs(
    sigs: _RouteSigs,
    engines: list[str],
    latex209_suspect: list[str],
    reasons: list[str],
    *,
    non_utf8: bool,
) -> list[str]:
    """信号集 → 引擎优先序重排 + reasons 追加；返回重排后引擎序。"""
    if sigs.eps or sigs.pstricks:
        # E2 硬墙：xdvipdfmx 不支持 EPS/PS → 跳过 tectonic
        engines = sorted(engines, key=lambda e: 0 if e == "xelatex" else 1)
        reasons.append(
            f"eps_files={sigs.eps} pstricks={sigs.pstricks} → xelatex 优先"
            "（tectonic xdvipdfmx 硬墙）"
        )
    elif sigs.minted_frozen:
        engines = sorted(engines, key=lambda e: 0 if e == "tectonic" else 1)
        reasons.append("minted frozencache → tectonic 优先（bundle v2.6 兼容）")
    if sigs.bitmap_fonts:
        reasons.append("bbm/dsfont 类位图字体包 → tectonic 高风险，失败换 xelatex")
    if sigs.psfile_special:
        reasons.append(
            "\\special{psfile} dvips 原语插图 → xelatex/tectonic 均不渲染"
            "（图件将缺，无双引擎可行路径）"
        )
    if sigs.mf:
        reasons.append(
            "包内 .mf METAFONT 源 → tectonic 无 mf 链"
            "（xelatex 视 mktexfm 配置；真字体需求时字形必缺）"
        )
    if latex209_suspect:
        reasons.append(
            f"latex209_suspect: {', '.join(latex209_suspect)} "
            "\\documentstyle → 试编不定死（fixloop gate 兜底拒）"
        )
    if non_utf8:
        reasons.append("非 UTF-8 源 → 需 iconv 转码预处理或 inputenc 路注")
    return engines


def route_project(root: Path, *, prefer: str = "tectonic") -> RouteDecision:
    r"""静态预检路由（docs/spec/compile.md 表）：编译前即可决策的引擎分配。

    - `\documentstyle` → `latex209_suspect` 降级标记，**不再无条件 reject**
      （TL2026 实测 ~23% FP：cond-mat/9703223 等真 2.09 源编出 clean——
      先试编，fixloop `latex209_reject` gate 在真 2.09 错时兜底拒；
      inject 层仍按原样拒，两类 reject 在账本里分流）
    - `*.eps` / pstricks / pspicture → 跳过 tectonic 直走 xelatex（E2 硬墙）
    - frozencache + minted → tectonic 优先（bundle v2.6 兼容 v2 缓存）
    - bbm/dsfont 位图字体包 → tectonic 高风险标记（失败后换 xelatex）
    - 非 UTF-8 源 → 标记（iconv 预处理或 inputenc 路注，由调用方处理）
    """
    vis: dict[Path, str] = {}
    non_utf8 = False
    exts: set[str] = set()
    # ``_iter_files``（os.walk followlinks=False + 软链豁免）而非 rglob——
    # rglob 跟随目录符号链且无环检测，unpack 放行的 in-tree symlink 环
    # （``sub -> .``）会炸 RecursionError/挂死（normalize.py:567 同款教训）；
    # skip_hidden=False 保 rglob 原口径的隐藏目录覆盖。
    for p in _iter_files(root, None, skip_hidden=False):
        suffix = p.suffix.lower()
        exts.add(suffix)  # 全文件面后缀集（_route_sigs 的 eps/mf 信号源）
        if suffix != ".tex":
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue  # 不可读文件不参与路由信号（竞态删除/权限位）
        text, verdict = decode_tex_with(raw)
        # 判定族非 UTF-8 或 strict-utf8 截尾——与旧 raw.decode("utf-8")
        # 探测同口径（utf-8-sig/utf-16 等 BOM 族按判定名归位）。
        non_utf8 = non_utf8 or (
            verdict.encoding not in ("utf-8", "utf-8-sig")
            or "truncated utf-8 tail" in verdict.note
        )
        vis[p] = visible_tex(text)
    blob_vis = "\n".join(vis.values())

    # --- \documentstyle → latex209_suspect 标记（任何文件里出现都算）
    latex209_suspect = [
        str(p.relative_to(root)) for p, v in vis.items() if DOCSTYLE_RX.search(v)
    ]

    reasons: list[str] = []
    sigs = _route_sigs(exts, blob_vis)
    engines = (
        ["xelatex", "tectonic"] if prefer == "xelatex" else ["tectonic", "xelatex"]
    )
    engines = _apply_route_sigs(
        sigs, engines, latex209_suspect, reasons, non_utf8=non_utf8
    )
    return RouteDecision(
        engines=engines,
        reject=None,
        reasons=reasons,
        non_utf8=non_utf8,
        latex209_suspect=bool(latex209_suspect),
    )


#: 引擎名白名单（``auto`` 路由 + 两台真机）——settings ``ENGINES`` 与
#: http ``_ENGINE_NAMES`` 入参闸的单一事实源；``engine_for`` 只构造真机。
ENGINE_NAMES: Final = frozenset({"auto", "xelatex", "tectonic"})


def engine_for(name: str, **kwargs: object) -> Engine:
    """按名构造引擎实例（kwargs 原样透传 ctor，错配键由引擎 ctor TypeError 拒）。"""
    if name == "xelatex":
        return XelatexEngine(**cast("dict[str, Any]", kwargs))
    if name == "tectonic":
        return TectonicEngine(**cast("dict[str, Any]", kwargs))
    msg = f"未知引擎 {name!r}"
    raise ValueError(msg)
