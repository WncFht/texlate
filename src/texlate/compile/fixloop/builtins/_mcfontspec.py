r"""builtins._mcfontspec — fontspec_clone_sub 度量克隆名替换 (C5 拆叶)。

``fontspec_missing|<name>`` 真缺字体 → 归一化茎 (``_font_stem`` +
``_WEIGHT_TAIL_RE`` + ``_FONT_FILE_RE``) 查 ``_CLONE_TABLE`` → 文件形名
替换 + 文件名绑定 keyval (``_FONTSPEC_FILEBIND_KEYS``) 剥除。站点正则
``_NAME_SITE_RE``/``_FAM_SITE_RE`` 双形并收, ``_split_kv``/
``_strip_filebind_opts``/``_clone_fix_text`` 同叶。``_is_live`` 经本叶
回引。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins._mcfallback import _FONT_FILE_RE
from texlate.compile.fixloop.builtins.common import _is_live, _splice
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import Engine

__all__ = [
    "_CLONE_TABLE",
    "_FAM_SITE_RE",
    "_FONTSPEC_FAM_CS",
    "_FONTSPEC_FILEBIND_KEYS",
    "_FONTSPEC_NAME_CS",
    "_FS_OPT",
    "_NAME_SITE_RE",
    "_WEIGHT_TAIL_RE",
    "_clone_fix_text",
    "_font_stem",
    "_is_live",
    "_split_kv",
    "_strip_filebind_opts",
    "fontspec_clone_sub",
]


# ════════════════════════════════════════════════════════════════
# fontspec_clone_sub: fontspec_missing 名查找缺字体 → 度量克隆/同件文件形替换
# ════════════════════════════════════════════════════════════════

#: ``-<weight>`` 字重尾剥除 —— payload "Tinos-Regular" 与源 ``{Tinos}``、
#: "Amiri-Regular" 与 ``{Amiri-Regular.ttf}`` 归一到同茎。
_WEIGHT_TAIL_RE = re.compile(
    r"-(?:regular|bold|italic|bolditalic|light|medium|thin|black|semibold|"
    r"extralight|extrabold|heavy|demibold|ultralight|normal|book|oblique|"
    r"boldoblique|italicbold)$",
    re.IGNORECASE,
)


def _font_stem(name: str) -> str:
    """``fontspec`` 引用名归一化: 剥文件扩展名 + ``-<weight>`` 尾 + 空白 → casefold 茎。"""
    n = _FONT_FILE_RE.sub("", name.strip())
    n = _WEIGHT_TAIL_RE.sub("", n)
    return re.sub(r"\s+", " ", n).strip().casefold()


#: 默认克隆表 (``params.clone_table`` 覆盖): 归一化茎 → **文件形**替换名。
#: 家族名在 fixloop 面不可探测 (``run_tool`` 无 FONTCONFIG_FILE 注入,
#: fc-list 对 texmf 字族恒盲), 文件形经 ``eng.probe_file`` kpathsea 同
#: fontspec 文件查找同一通路; 字体名写入站点后 fontspec 对文件形名
#: 自动同目录补全字重 (texgyretermes/Tinos/NotoSerif 实测 verbatim)。
#: Amiri 不收 —— TL 内外皆无度量克隆, 强替发错字体声明 (车道裁决 unfixable)。
_CLONE_TABLE: dict[str, str] = {
    # URW Nimbus 系与 TeX Gyre 同源度量克隆; nimbus 只发 TFM/pfb, fontspec 面无件。
    "nimbus roman": "texgyretermes-regular.otf",
    "nimbus sans": "texgyreheros-regular.otf",
    "nimbus mono ps": "texgyrecursor-regular.otf",
    # 同件在 texmf truetype 树 —— 文件形引用绕 fontconfig 直中,
    # ``Path = fonts/...`` 捆绑键剥除后保作者字体 (2609.20064 anthology-ch.cls)。
    "tinos": "Tinos-Regular.ttf",
    "notoserif": "NotoSerif-Regular.ttf",
}

#: 文件名绑定 keyval —— 换字体名后仍指原档, 整键剥除 (``Path``/``Extension``
#: 定位原档; ``*Font`` 把各字重绑到原档文件名)。其余键 (Scale/Ligatures/
#: Numbers/FakeBold…) 为渲染语义, 换字体后仍成立 → 保留。
_FONTSPEC_FILEBIND_KEYS = frozenset(
    {
        "path",
        "extension",
        "uprightfont",
        "boldfont",
        "italicfont",
        "bolditalicfont",
        "slantedfont",
        "boldslantedfont",
        "smallcapsfont",
        "swashfont",
    }
)

#: fontspec 声明 cs 面 —— 与 rules/50-font.yaml font_name_substitute 同族
#: (裸名形) + 带族名实形 (``\newfontfamily\cs``/``\babelfont[lang]{fam}``)。
_FONTSPEC_NAME_CS = (
    "setmainfont",
    "setsansfont",
    "setmonofont",
    "setromanfont",
    "setmathrm",
    "setmathfont",
    "fontspec",
    "setfontfamily",
    "setCJKmainfont",
    "setCJKsansfont",
    "setCJKmonofont",
)
_FONTSPEC_FAM_CS = (
    "newfontfamily",
    "newfontface",
    "setfontface",
    "newCJKfontfamily",
    "babelfont",
)

#: 可括号选项组 (keyval 内不收方括号 —— 非嵌套足够)。
_FS_OPT = r"\[[^\[\]]*\]"

#: ``\cs[opt]{name}[opt]`` / ``\cs{name}[opt]`` —— fontspec 前后双序并收。
_NAME_SITE_RE = re.compile(
    r"\\(?P<cs>" + "|".join(_FONTSPEC_NAME_CS) + r")(?![a-zA-Z@])"
    r"(?P<pre>\s*" + _FS_OPT + r")?\s*"
    r"\{(?P<name>[^{}]+)\}"
    r"(?P<post>\s*" + _FS_OPT + r")?"
)

#: ``\cs[opt]{fam|cs}[opt]{name}[opt]`` —— 族名实参形。
_FAM_SITE_RE = re.compile(
    r"\\(?P<cs>" + "|".join(_FONTSPEC_FAM_CS) + r")(?![a-zA-Z@])"
    r"(?P<pre>\s*" + _FS_OPT + r")?\s*"
    r"(?P<fam>\{[^{}]*\}|\\[a-zA-Z@]+)"
    r"(?P<mid>\s*" + _FS_OPT + r")?\s*"
    r"\{(?P<name>[^{}]+)\}"
    r"(?P<post>\s*" + _FS_OPT + r")?"
)


def _split_kv(inner: str) -> list[str]:
    """``keyval`` 顶层逗号切分 (花括内逗号不切)。"""
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in inner:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _strip_filebind_opts(opt: str | None) -> str:
    r"""``[k=v, ...]`` 组剥文件名绑定键 → 重建 ``[..]``; 空组/缺席 → ``""``。"""
    if not opt or "[" not in opt:
        return ""
    inner = opt[opt.index("[") + 1 : opt.rindex("]")]
    kept = [
        kv.strip()
        for kv in _split_kv(inner)
        if kv.strip()
        and kv.split("=", 1)[0].strip().casefold() not in _FONTSPEC_FILEBIND_KEYS
    ]
    return "[" + ", ".join(kept) + "]" if kept else ""


def _clone_fix_text(t: str, resolve: Callable[[str], str | None]) -> tuple[str, int]:
    """单文件 fontspec 站点逐替换 → (新文本, 改写站点数)。

    遮盖视图命中且匹配体完整未遮 (``_live_matches`` 同判据); 茎 ∈ 表
    且 ``resolve(stem)`` 得可 kpathsea 命中的文件形名 → 名替换 +
    前后 ``[..]`` 组剥 ``_FONTSPEC_FILEBIND_KEYS``。一轮扫全表 (不只
    payload 茎) —— 同稿多缺名字体同轮收敛。
    """
    masked = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    for rx, is_fam in ((_NAME_SITE_RE, False), (_FAM_SITE_RE, True)):
        for m in rx.finditer(masked):
            if not _is_live(m, masked, t):
                continue
            sub = resolve(_font_stem(m["name"]))
            if sub is None:
                continue
            pre = _strip_filebind_opts(m["pre"])
            post = _strip_filebind_opts(m["post"])
            rep = "\\" + m["cs"] + pre
            if is_fam:
                rep += m["fam"] + _strip_filebind_opts(m["mid"])
            rep += "{" + sub + "}" + post
            if rep != m[0]:
                edits.append((m.start(), m.end(), rep))
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def fontspec_clone_sub(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``fontspec`` 名查找字体真缺 → 表驱动文件形名替换 + 文件名绑定键剥除 (fontfb-A)。

    ``fontspec_missing|X`` 里 install_sysfont 装不上 (payload 是家族名/
    无 filemap 档) 与 font_name_substitute 无差别换 Latin Modern 之间
    的精确臂: 度量克隆表逐茎替换 —— Nimbus 系 → TeX Gyre 同源克隆,
    Tinos/NotoSerif → texmf truetype 同件文件形名 (``Path = fonts/…``
    捆绑键剥除后保作者字体)。克隆件经 ``eng.probe_file`` 实证可达才
    动笔, 全灭 → decline 落回 31 号 LM 臂; payload 茎不在表 → decline
    (Amiri 无克隆不收 = 车道裁决 unfixable, 不发错字体声明)。
    """
    table = {
        _font_stem(str(k)): str(v)
        for k, v in (params.get("clone_table") or _CLONE_TABLE).items()
    }
    if not payload or _font_stem(payload) not in table:
        return False, f"payload {payload!r} has no clone-table entry"
    memo: dict[str, str | None] = {}

    def _resolve(stem: str) -> str | None:
        if stem not in memo:
            cand = table.get(stem)
            memo[stem] = cand if cand and eng.probe_file(cand) else None
        return memo[stem]

    if _resolve(_font_stem(payload)) is None:
        return False, f"clone for {payload!r} not resolvable via kpathsea"
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    n_sites = 0
    n_files = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt, n = _clone_fix_text(t, _resolve)
        if n and nt != t:
            ctx.write(f, nt)
            n_sites += n
            n_files += 1
    if not n_sites:
        return False, f"no fontspec sites named {payload!r} in fileset"
    return True, f"clone-substituted {n_sites} fontspec site(s) in {n_files} file(s)"
