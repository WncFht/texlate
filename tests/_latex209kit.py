"""latex209 测试公共件——``_target_resolvable`` 放行桩 + ``\\documentstyle`` 壳 convert。

收养方式（沿用 ``_fuzzkit``/``_fixloopkit`` 先例）：

- ``from _latex209kit import target_always_resolvable``——imported fixture
  在收养模块内注册、保持原 autouse 语义（test-level 再打桩仍可覆盖）。
- ``convert(body)``——``\\documentstyle{article}`` + body 壳直驱
  ``upgrade_209``（仅服务 docstyle 壳口径统一的消费方；异 docstyle/
  options/root= 调用点照直调 ``upgrade_209``）。

不放 conftest autouse：``upgrade_209`` 真闸 ``_target_resolvable`` 的
fails-open 语义另有消费文件依赖（test_fixloop_revtex209/
test_fixloop_gate209/test_compile_inject/test_fuzz_inject/
test_fixloop_revtex3/test_fixloop_rules）。
"""

from __future__ import annotations

import pytest

from texlate.compile import latex209_main
from texlate.compile.latex209 import upgrade_209


@pytest.fixture(autouse=True)
def target_always_resolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    """改名目标类默认放行——原各文件同体 autouse 钉桩归一处。"""
    monkeypatch.setattr(latex209_main, "_target_resolvable", lambda *_a: True)


def convert(body: str) -> tuple[str, dict]:
    """``\\documentstyle{article}`` 壳 + body → ``upgrade_209``。"""
    tex = "\\documentstyle{article}\n\\begin{document}\n" + body + "\n\\end{document}\n"
    return upgrade_209(tex)
