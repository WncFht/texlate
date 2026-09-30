r"""engine._engine_aux — 工程辅助件清场 + 挥发件缓存族 (C5 拆叶)。

TeX 每轮重写/截断的辅助件 (``.aux``/``.toc``/``.log`` 族) 判定与扫除
(``_aux_file_bad``/``_sweep_bad_aux``), 以及进程内 ``_texts`` 缓存对
改盘件不安全的扩展名集 ``_VOLATILE_EXTS`` —— 主循环/兜底/末态三 site
共用同一清场原语。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "_AUX_WRITE_EXTS",
    "_BSLASH",
    "_LBRACE",
    "_RBRACE",
    "_VOLATILE_EXTS",
    "_aux_file_bad",
    "_sweep_bad_aux",
]


#: TeX 每轮重写的读回辅助件 —— 被杀/超时编译留下截断形 (``\citation{``
#: 半行) 驻留 wdir 即毒化后续一切 compile ("File ended while scanning
#: use of \citation"; 1511.06744 实证，既有 aux_scan_eof 签名盖不住
#: \citation 形态)。删可再生件代价至多一遍重排; .bbl/.ind/.bcf 可为
#: e-print 船货 (bbl_regen 靠它), 不在此表。
_AUX_WRITE_EXTS = frozenset(
    {".aux", ".toc", ".lof", ".lot", ".out", ".nav", ".snm", ".vrb"}
)


_LBRACE, _RBRACE, _BSLASH = ord("{"), ord("}"), ord("\\")


def _aux_file_bad(f: Path) -> bool:
    r"""截断辅助件判定: EOF 无尾换行 (半路断行) 或全文花括号不闭合。

    行界齐整的早夭 (尾部整行丢失) 不算毒——缺行重排自生; 毒在断开
    的命令。``\{``/``\}`` 转义不计深; ``\\{`` 极小样本误删健康件
    的代价至多一遍重排, 不腐蚀语义。
    """
    try:
        data = f.read_bytes()
    except OSError:
        return False
    if not data:
        return False
    if not data.endswith(b"\n"):
        return True
    depth = 0
    prev = -1
    for b in data:
        if b == _LBRACE and prev != _BSLASH:
            depth += 1
        elif b == _RBRACE and prev != _BSLASH and depth:
            depth -= 1
        prev = b
    return depth != 0


def _sweep_bad_aux(wdir: Path) -> list[str]:
    """删 wdir 内截断辅助件 (aux/toc/out 族), 返回删除的相对名供审计。"""
    dropped: list[str] = []
    for f in wdir.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in _AUX_WRITE_EXTS:
            continue
        if not _aux_file_bad(f):
            continue
        try:
            f.unlink()
        except OSError:
            continue
        dropped.append(str(f.relative_to(wdir)))
    return dropped


#: 进程内 ``_texts`` 缓存对 TeX 每轮重写/清场件不安全：compile 落盘
#: 重写 ``{stem}.log``/``.aux`` 族、aux-sweep 删截断件，缓存照供旧文，
#: 扫 log/aux 的下游规则吃残影 (2403.00013 实证：r1 早读 ``{stem}.log``
#: 缓存 → r2 全部 misschar/font 规则在 pre-fix log 上判 "no Missing
#: character" 拒修)。``.bbl``/``.bcf`` 可为 e-print 船货且不由 tex
#: compile 重写，不入此集——biber/docstrip 类 run_tool 产物由各调用
#: 方自行 ``ctx.invalidate`` (bib_regen/docstrip 先例)。循环内每个
#: ``eng.compile`` 后必失效此集 (含探针与兜底臂，幂等)。
_VOLATILE_EXTS = _AUX_WRITE_EXTS | {".log"}
