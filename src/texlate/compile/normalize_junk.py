r"""compile.normalize_junk — bundled 垃圾件 stub 叶 (compile.normalize 域缝叶)。

``JUNK_FILE_STUBS`` 名单件逐名覆写为 stub（``\input`` 目标须保持存在故
覆写不删）；``JUNK_FILE_MARKERS`` 垃圾签名护栏——同名无签名按撞名真件
放行，中立化只护真实输入不反噬真件本体。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from .transcode import _iter_files

if TYPE_CHECKING:
    from pathlib import Path

# logger 名钉死拆分前模块名——消息面 (record.name) 不变。
log = logging.getLogger("texlate.compile.normalize")

#: 源包 bundled 的已知垃圾件——内容非论文（自检/交互工具），翻译臂会当正文
#: parse/splice 腐蚀（1109.2354/1206.0565 ``splice/aipcheck.tex:82`` 实证），
#: 裸编译则 ``\typein`` 挂交互终端读（hep-ph/0111248 early_eof）。覆写为
#: stub 而非删除——``\input`` 目标须保持存在。stub 体与 fixloop
#: ``rules/90-shim-legacy.yaml`` ``legacy_pkg_shim`` 的 aipcheck.tex 条目同文。
JUNK_FILE_STUBS: Final[dict[str, str]] = {
    # aipproc/REVTeX4 版本自检件（~18 处 \typein + \def\next#1/#2/#3 魔术）。
    "aipcheck.tex": (
        "% AIP \\input{aipcheck} 版本自检件 —— 纯 \\typeout, 无排版语义\n\\endinput\n"
    ),
}

#: 垃圾件自证签名——同名件须命中任一签名才按垃圾件覆写（名撞护栏）。
#: 名单名是 bundled 构件名（类发行物），逐名匹配假定「该名即垃圾件」；
#: 同树真件撞名时凭签名区分——真件不可能携带垃圾件的 RCS 自名版本戳、
#: 自检横幅或 ``\typein`` 交互原语（corpus 四件实证：v1.4/v1.9 三件
#: 均带齐三签名）。签名按原始字节做子串匹配（ASCII 标记，编码无关）。
#: 无签名件视为撞名真件放行——中立化只护真实输入，不得反噬真件本体；
#: 签名缺省的名单条目回落逐名无条件覆写（旧契约，名单作者自证）。
JUNK_FILE_MARKERS: Final[dict[str, tuple[bytes, ...]]] = {
    "aipcheck.tex": (
        b"$Id: aipcheck.tex",  # RCS 自名版本戳
        b"Testing for potential problems with this class",  # 自检横幅
        b"\\typein",  # 交互终端读原语——裸编译挂点的本体
    ),
}


# ---------------------------------------------------------------- 13. bundled 垃圾件 stub
def _neutralize_junk_files(root: Path, stats: dict[str, object]) -> None:
    r"""``JUNK_FILE_STUBS`` 名单件逐名覆写为 stub；覆写件记 ``stats["junk_stubbed"]``。

    覆写不删——``\input``/``\include`` 引用目标须保持存在；逐名匹配不限
    目录深度（bundled 件可落任意子目录）。已就位者跳过——幂等不重复记。
    ``JUNK_FILE_MARKERS`` 带签名条目加一道名撞护栏：同名但不含任一垃圾
    签名的文件按撞名真件放行——覆写会毁掉真件本体（同名 ≠ 同垃圾）。
    """
    hits = []
    for path in sorted(_iter_files(root, None)):
        stub = JUNK_FILE_STUBS.get(path.name)
        if stub is None:
            continue
        try:
            blob = path.read_bytes()
            if blob == stub.encode("utf-8"):
                continue
            markers = JUNK_FILE_MARKERS.get(path.name, ())
            if markers and not any(m in blob for m in markers):
                # 同名无垃圾签名——撞名真件，不覆写（fixloop ``_inject_write``
                # foreign 闸同款口径：外来件永不覆写）
                log.debug("归一化跳过撞名真件 %s（无垃圾签名）", path)
                continue
            path.write_text(stub, encoding="utf-8")
        except OSError:
            continue
        hits.append(path.relative_to(root).as_posix())
    if hits:
        stats["junk_stubbed"] = hits
