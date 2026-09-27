"""tar 伪装件测试公共骨架——``_tar_blob`` 内存构造 tar blob。

``test_bininject_gate``/``test_inject_targate``/``test_latex_targate``/
``test_probe_targate`` tar-gate 簇逐文件复刻的同构助手归此一处（沿用
``_segkit``/``_fixloopkit``/``_fuzzkit`` 抽取先例）。

注意：空 ``members`` 回落的默认成员文本是 bininject 臂的
``\\documentclass{article}`` + ``\\begin{document}`` +
``member \\usepackage{inputenc}`` 形态——姊妹闸各自的默认成员
（``_DOC``/``_MEMBER_TEX``）与本默认不同，采纳方须显式传 members
（``_tar_blob(*members or ((name, data),))`` 式包装），不可裸调
``_tar_blob()`` 指望各自的默认成员。
"""

from __future__ import annotations

import io
import tarfile


def _tar_blob(*members: tuple[str, bytes], fmt: int = tarfile.USTAR_FORMAT) -> bytes:
    """tar blob——成员文本默认含 ``\\begin{document}``（``has_document`` 命中形态）。

    ``*members``/``fmt`` 签名即 tar-gate 簇四文件同形助手的收敛形。
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=fmt) as tf:
        for name, data in members or (
            (
                "inner/doc.tex",
                (
                    b"\\documentclass{article}\n\\begin{document}\n"
                    b"member \\usepackage{inputenc}\n\\end{document}\n"
                ),
            ),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()
