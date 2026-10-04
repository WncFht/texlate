r"""xelatex 编译头尾段共享件 + 输入覆盖出货闸（``engine/_xelatex`` 二级缝叶）。

``_prepare_main``/``_harvest`` 是 ``compile()`` 头/尾段两引擎共用件
（tectonic 经 ``._xelatex`` 门面回取同名件）；``_enddoc_scan``/
``_input_covers_enddoc`` 是 ``_harvest`` 内嵌的出货闸——编译输入须
吃活到 ``\end{document}``。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Final

    from texlate.compile.engine._base import CompRes

from texlate.compile.deps import compiled_dependencies
from texlate.compile.engine._base import _checked_main
from texlate.compile.mask import visible_tex

#: ``\\endinput`` 执行豁免形——``\\let\\cs\\endinput``/``\\def\\cs{..}``
#: 把它存进宏体不执行 (pstricks ``\\let\\PSTricksLoaded\\endinput`` 实证);
#: 行头查赋值系 cs 即足，真截停的 ``\\endinput`` 行内无赋值前件。
_ENDINPUT_DEF_RX: Final = re.compile(
    r"\\(?:let|def|gdef|edef|xdef|newcommand|renewcommand|providecommand)\b"
)

#: 出货闸输入覆盖 (qc-impl 批二，2026-09-28): masked 视图深度 0 扫描——首个
#: ``\end{document}`` = 输入吃活到收束；先到的顶层 ``\endinput`` = 输入
#: 被截停 (其后全部死代码——``\end{document}`` 在尾也吃不到，0906.4725
#: 型文献表腰斩件)。``\end{document}`` 之后的 live 尾巴不算伤：TeX
#: 本就忽视，作者草稿尾注常见。
_ENDDOC_RX: Final = re.compile(r"\\end\s*\{\s*document\s*\}")
_ENDINPUT_RX: Final = re.compile(r"\\endinput(?![a-zA-Z@])")
#: ``\input{name}``/``\include{name}`` 两形态：花括号与裸名 (plain 风)。
#: 花括号形先匹配 (``\input{sub/a}`` 与 ``\input sub/a`` 同收)。
_INCLUDE_SRC_RX: Final = re.compile(
    r"\\(?:input|include)(?![a-zA-Z@])\s*(?:\{([^}]+)\}|([^\s{}\\]+))"
)
#: ``\input`` 链跟进深度顶——main_wrapper_promote 的 wrapper→真身一跳
#: 足够，再深即病态链。
_ENDDOC_MAX_DEPTH: Final = 2


def _enddoc_scan(masked: str) -> tuple[int | None, int]:
    r"""Masked 视图扫描 → (``\end{document}`` pos, 截停 pos)。

    ``\end{document}`` 任意深度都执行 (分组不阻执行), 命中即收束;
    ``\endinput`` 仅深度0 且非赋值右值时计——包内宏体存储形不截停。
    返回 ``(None, cut)``: ``cut`` = 截停位置或 ``len``。
    """
    depth = 0
    i, n = 0, len(masked)
    while i < n:
        ch = masked[i]
        if ch == "{":
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
        elif ch == "\\":
            m = _ENDDOC_RX.match(masked, i)
            if m is not None:
                return i, n
            m = _ENDINPUT_RX.match(masked, i)
            if m is not None and depth == 0:
                head = masked[masked.rfind("\n", 0, i) + 1 : i]
                if not _ENDINPUT_DEF_RX.search(head):
                    return None, i
        i += 1
    return None, n


def _input_covers_enddoc(path: Path, _depth: int = 0) -> bool:
    r"""编译输入覆盖闸。

    ``path`` (含 ``\input`` 链 ≤``_ENDDOC_MAX_DEPTH`` 层) 能吃活到
    ``\end{document}`` 即 covered。主件顶层先见 ``\endinput`` → 其后
    输入全死, 只跟进截停点之前的 ``\input``/``\include``——wrapper
    main 把 ``\end{document}`` 放真身件是本闸存在的原因。
    读不动/链断 = 不覆盖。
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    masked = visible_tex(text)
    end_pos, cut = _enddoc_scan(masked)
    if end_pos is not None:
        return True
    if _depth >= _ENDDOC_MAX_DEPTH:
        return False
    for inc in _INCLUDE_SRC_RX.finditer(masked, 0, cut):
        name = (inc.group(1) or inc.group(2) or "").strip()
        if not name:
            continue
        cand = path.parent / name
        if not cand.suffix:
            cand = cand.with_suffix(".tex")
        if cand.is_file() and _input_covers_enddoc(cand, _depth + 1):
            return True
    return False


def _prepare_main(
    wdir: Path,
    main: str,
    outdir: Path | None,
    *,
    default_subdir: str = "",
    extra_stale: Iterable[str] = (),
) -> tuple[Path, Path, str, Path, Path, Path]:
    """compile() 头段共享件：main 校验 + out 落点解析/mkdir + 陈旧产物清理。

    ``default_subdir`` = ``outdir`` 缺席时 ``cwd`` 下的引擎默认子目录
    （tectonic ``_tect_out``；xelatex 产物落 main 旁、留空）。``extra_stale``
    收相对 ``out`` 的追加清档名，``{stem}`` 占位按 main 词干展开（xelatex
    ``"{stem}.fls"``、tectonic ``"dependencies.mk"``）。返回
    ``(main_path, cwd, stem, out, pdf, log)``——源树目录镜像等引擎私有
    步骤留在调用方。
    """
    main_path = _checked_main(wdir, main)
    cwd = main_path.parent
    stem = main_path.stem
    out = (outdir or (cwd / default_subdir if default_subdir else cwd)).resolve()
    out.mkdir(parents=True, exist_ok=True)
    pdf, log = out / f"{stem}.pdf", out / f"{stem}.log"
    for stale in (pdf, log, *(out / name.format(stem=stem) for name in extra_stale)):
        stale.unlink(missing_ok=True)
    return main_path, cwd, stem, out, pdf, log


def _harvest(  # noqa: PLR0913, PLR0917 — compile() 尾段共享件，参数面即两引擎差异缝
    res: CompRes,
    wdir: Path,
    main: str,
    out: Path,
    pdf: Path,
    log: Path,
    log_text: str,
) -> None:
    """compile() 尾段共享件：log_text/log_path/pdf/ok/workdir/deps 归位。

    ``log_text`` 由调用方早读——各引擎 ``.log``→``LogInfo`` 解析段发散
    （xelatex ``parse_log(log_text or stdout_tail)`` + driver-fatal 打捞 +
    ``log_truncated``；tectonic 空 .log 退 stdout_tail + ``error:`` 标记
    兜底），读盘随解析段留在原地。本函数只归位字段，且须在
    ``_salvage_driver_fatal`` 之后调用：``_driver_fatal`` 的 ``has_pdf``
    门按归位前字段评估（编译时序上恒 False——``res.pdf`` 此刻未落位即
    「呈失败相」，fatal 行打捞不因已出 pdf 被闸掉）。
    """
    res.log_text = log_text
    res.log_path = log if log.exists() else None
    res.pdf = pdf if pdf.exists() else None
    res.pdf_bytes = pdf.stat().st_size if pdf.exists() else 0
    res.ok = not res.timed_out and res.rc is not None and res.rc >= 0
    res.workdir = wdir
    res.deps = compiled_dependencies(wdir, main, out, res.engine)
    # 出货闸 (qc-impl 批二，2026-09-28): 编译输入须吃活到 ``\end{document}``——
    # ``log_truncated`` 只盖 halt_on_error 趟中截死; 输入件残 (无收尾
    # token) 与顶层 ``\endinput`` 截停在 best_effort 下静默出残 pdf。
    # 两引擎同闸 (tectonic 拼写即 ``wdir/main``, _checked_main 上游已过)。
    res.input_truncated = not _input_covers_enddoc(Path(os.path.normpath(wdir / main)))
