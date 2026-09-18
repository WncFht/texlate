r"""Segmenter——``next_expanded()`` token 流的消费者（M1 接线，S1 骨架）。

契约见 ``docs/research/latex/segmenter-integration.md``。要点：

- **vtex**：叙事序虚拟文本。一切 piece/chunk/span 用 vtex 坐标；
  ``file_texts[fid][a:b]`` 经 :meth:`Segmenter._cover_to` 追加映射，
  间隙字节（注释/折叠空白）随覆盖自动进 vtex——Mouth 吞注释后
  identity 不破的机制。
- **run 双轨**：``_run`` 项 = ``(surface, ident, vspan)``——surface 进
  chunk.content/译文面；ident 进 identity 面（gen=0 项 = vtex 切片、
  ph 项 = token 自身、展开组 = ``[[EXPAND_n]]``）。
- **chunk identity**：run 含展开组时 ``ph_map["[[CHUNK_k]]"]`` 登记为
  identity 串——``expand()`` 的 ``trans → ph_map → content`` 优先级
  自动回原文（docs/07 §9 伪码同序），零 schema 变更。
- **展开组**：``gen>0`` 连续同 ``origin`` token 为一组；组内 gen=0
  arg token（pos 落调用区间内）同属。surface 正常流过分段，identity
  收拢为一个 ``[[EXPAND_n]]``。

S1 骨架：主循环 + 覆盖账本 + run 双轨 + math/env/verbatim/verb/cite-ref
保护子集 + scope 回报。
S2 分派移植：v1 ``_dispatch_cmd`` 19 行逐行 token 化——``_args_tok``
（argspec s/o/d/m/e 全字母 + 单 token/零宽缺省）、chunk-arg 子扫、
``\\href`` 拆分、PROTECT_BLOCK/``\\item``/BOUNDARY_TAIL/未知命令保护、
``\\[``/``\\(`` 定界数学、``\\end{document}`` 截停、in_arg 环境路径、
env_begin/end 宏端点配对。``\\if`` 界标档回放、F12 墓标在 S4。
"""

from __future__ import annotations

from texlate.latex.gullet import (
    Gullet,
)
from texlate.latex.model import (
    ScanResult,
    ScanState,
)
from texlate.latex.placeholder import (
    PlaceholderIssuer,
)

from ._common import (
    _doc_begin_of,
)
from .args import _Args
from .core import _Core
from .env import _Env
from .group import _Group
from .mainloop import _MainLoop
from .pending import _Pending

__all__ = ["Segmenter", "parse_tex_v2", "scan_v2"]


class Segmenter(_Core, _Group, _Pending, _MainLoop, _Env, _Args):
    r"""token 流 → pieces/chunks。单遍正向、绝不抛异常（铁律 1）。"""


def scan_v2(g: Gullet) -> ScanResult:
    r"""v2 产品核：消费 ``g`` 的展开流 → ``ScanResult``。

    ``res.macros`` = gullet scope 链（平表 MacroTable 退役）；
    ``res.inputs`` = (vpos, path) 输入事件流（解析成功 = 绝对路径，
    漏网 = 原始文件名——``missing_input`` warning 同步登记）；
    ``gullet.warnings`` 尾并入（pos 已 fid 化前缀）。
    """
    state = ScanState(
        issuer=PlaceholderIssuer(),
        ph_map={},
        chunks=[],
        macros=g.macros,
        inputs=[],
        warnings=[],
    )
    # 源文自带 [[X_n]] 形字面 → 签发避让（v1 parse_tex 同检）：采样在
    # ``Segmenter.scan`` 主循环按 file_texts 懒增长增量进行——fid-0 与
    # ``\input`` 后进栈的子文件同规（先签发后加载的碰撞只剩告警）。
    seg = Segmenter(state)
    seg.scan(
        g,
        g.file_texts,
        doc_begin=_doc_begin_of(g.file_texts[0]) if g.file_texts else -1,
    )
    return ScanResult(
        protected_tex="".join(p.text for p in seg.pieces),
        chunks=state.chunks,
        ph_map=state.ph_map,
        macros=state.macros,
        pieces=seg.pieces,
        inputs=state.inputs,
        warnings=[*state.warnings, *g.warnings],
        vtex=seg.vt.text(),
        ph_reserved=state.ph_reserved,
    )


def parse_tex_v2(tex: str) -> ScanResult:
    r"""``parse_tex`` 的 token 流版：内存源 Gullet。

    无路径无 root——``\\input`` 恒不解析。产品文件入口是
    ``api.parse_file``。
    """
    return scan_v2(Gullet(tex))
