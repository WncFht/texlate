r"""compile.normalize_bbl — bundled .bbl 书目替换叶 (compile.normalize 域缝叶)。

工程附现成 .bbl 而 .bib 缺失时 ``\bibliography{x}`` → ``\input{x.bbl}``；
revtex 系 ``\auto@bib`` end-doc 探测用 ``_AUTOBIB_DISARM`` csname 形
解除（fixloop ``bbl_stub_rewrite`` 同义）。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from texlate.textutil import CMD_BOUNDARY, decode_tex, safe_is_file

from .mask import visible_tex

# logger 名钉死拆分前模块名——消息面 (record.name) 不变。
log = logging.getLogger("texlate.compile.normalize")


# ---------------------------------------------------------------- 11. bundled .bbl
## REVIEW(bblmath): emit-site 修复（非 yaml 规则）——revtex 系（revtex4-x /
## emulateapj / aastex）`\bibliography` 顺带 `\auto@bib@empty` 解除 end-doc
## `\auto@bib` 探测；裸 `\input` 丢失该解除后 `\test@bbl@sw` 在 \vbox 中把
## `\bibitem` 必需组 cite key 当正文排印（_ / & / $ → Missing$ →
## invalid-in-math 级联；探测为真再三读 → 重复书目 / Lonely \item /
## env_mismatch）。`\input` 改写同时补上等价解除；`\@ifundefined` 使
## 非 revtex 工程为零操作。
## csname 形零字面 `@` —— `\bibliography` 站可落在已 tokenize 的 def
## 体内 (2105.11398 `\newcommand{\showbib}` 实证：旧 `\makeatletter`
## `\@ifundefined` 形在 @=12 预读体里成 `\@`+裸字母 → 调用点 vmode
## spacefactor 炸), csname 任意 catcode 同读 (同 builtins.bib)。
## 名扫段内每个 `@` 都写 `\string@`: doc 激活 @ (`\MakeShortVerb{\@}`
## → @=13) 时裸 @ token 在 \ifcsname/\csname 名扫里被当 active cs
## 展开 → Missing \endcsname (1107.0063 实证); \string 直接取记号
## 产 catcode-12 字面 @ 字符，@=11/12/13 三态同名同读。
_AUTOBIB_DISARM = (
    r"\ifcsname auto\string@bib\endcsname"
    r"\expandafter\let\csname auto\string@bib\expandafter\endcsname"
    r"\csname \string@empty\endcsname\fi"
)


def use_bundled_bibliography(text: str, path: Path, cwd: Path | None = None) -> str:
    r"""当工程附现成 .bbl 而 .bib 缺失时，`\bibliography{x}` → `\input{x.bbl}`。

    定位走 ``visible_tex``（verbatim 体遮盖）——``without_comments`` 只遮
    注释，lstlisting 里展示的 ``\bibliography{x}`` 示例会被真改写。
    ``cwd`` 为编译工作目录（main 所在目录）：`.bib` 存在性判定与
    `\input` 目标名都以它为基准（kpathsea `.` 口径）；缺省退回声明文件目录。
    多只 `\bibliography`（multibib/chapterbib）只替换首个缺库者——单份
    .bbl 只能填一个书目位，二次替换会重复排版整个 thebibliography。
    已注入过 ``\input{<该 .bbl>}``（含 ``./`` 前缀、引号形与裸名形）时
    整体不再改——工程级幂等，防逐跑把后续缺库 ``\bibliography`` 再换
    一遍累加重复书目。
    """
    base = cwd or path.parent
    bbl = path.with_suffix(".bbl")
    try:
        usable = bbl.is_file() and r"\begin{thebibliography}" in decode_tex(
            bbl.read_bytes()
        )
    except OSError:
        # bbl 在但读不动（EACCES 等）只弃书目步——放任上抛会让调用方逐文件
        # OSError 兜底连坐丢掉转码/引擎手术
        log.debug("bbl 读失败，跳过书目替换: %s", bbl)
        return text
    if not usable:
        return text
    target = Path(os.path.relpath(bbl, base)).as_posix()
    if target.startswith(".."):
        return text  # openin_any=p 拒 ../ 引用——不可达的 .bbl 不改写
    visible = visible_tex(text)
    # 开闭符号相关：{...} 只许 } 收、"..." 只许 " 收——失配对（\input{x.bbl"）
    # 在 TeX 里读不出本 bbl（\@iinput 扫描错），不算已填充。
    # 裸名形 \input x.bbl：文件名扫描止于空白/控制序列/~/&/%（}$#^_'" 等
    # catcode≤12 字符反而是名字成分——latex 实证）；(?![^\s\\~&%]) 要求
    # target 后接终结符，挡 main.bblx 前缀撞名。CMD_BOUNDARY 防把
    # \inputmain 类控制词误当 \input。
    t = re.escape(target)
    alts = [
        r"\{\s*(?:\./)?" + t + r"\s*\}",
        r'"(?:\./)?' + t + r'"',
    ]
    # 裸名形仅当 target 自身不含终结符才可达——target 带空白/~/&/% 时
    # TeX 扫名提前收束读不到全名（``\input sub dir/x.bbl`` 只读 ``sub``），
    # braced/quoted 形不受此限（评审批六：空白 target 裸名曾误报已填充）
    if not re.search(r"[\s\\~&%]", target):
        alts.append(r"(?:\./)?" + t + r"(?![^\s\\~&%])")
    if re.search(
        r"\\input" + CMD_BOUNDARY + r"\s*(?:" + "|".join(alts) + r")",
        visible,
    ):
        return text  # 书目位已由本 .bbl 填充——再换只会重复排版
    for match in re.finditer(r"\\bibliography\s*\{([^}]+)\}", visible):
        for v in match[1].split(","):
            name = v.strip()
            name = name if name.endswith(".bib") else name + ".bib"
            ref = Path(name)
            # openin_any=p 拒绝对路径与 .. 引用——盘上在也编译够不着，按缺席计
            if ref.is_absolute() or ".." in ref.parts or not safe_is_file(base / name):
                return (
                    text[: match.start()]
                    + _AUTOBIB_DISARM
                    + "\n"
                    + r"\input{"
                    + target
                    + "}"
                    + text[match.end() :]
                )
    return text
