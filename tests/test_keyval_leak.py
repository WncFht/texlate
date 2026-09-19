r"""aipproc 形 ``\author{name}{keyval}`` 第二参保护钉版（keyval-leak 车道）。

机理：aipproc/elsart 系 ``\author`` 的**第二必填参**是 keyval 签名组
（``address={..},email=..``）。未知 cs 探测只吃首参 ``{name}``，keyval 组
裸进 chunk → ``key=`` 键位被译成 ``这是译文=``，splice 后 ``\setkeys``
炸 ``Package keyval Error: key 'aipproc/author/这是译文' unknown``
（failmine2 census：0905.0330/0905.2183/1012.1143/astro-ph/0408494/
0605512/0806.3199 六格——aipproc.cls 缺席把签名掩在 missing_file 下，
段级验证才是正确粒度）。

覆盖点 = ``_keyval_tail_end``（args.py）：protect/unknown/opaque 调用实参
之后续吃键值形 ``{..}``/``[..]`` 组，``_kv_list_shaped`` 判形（任一项
``key=`` 或全项裸键 token）；非键值 ``{散文}`` 组全量回放主流重扫，
译文面不变。``[kv]`` 括号形（ceurart ``\author[..]{n}[orcid=]``）由
test_args_kvdig.py 钉住，本文件只钉花括号第二参形。

负例：``\author{n}{plain prose}`` 第二组非键值 → 回放照常可挖。
每条过公共不变式（``reconstruct == tex`` + 零告警 + 无缝平铺）。
"""

import re

from conftest import ART, check_invariants

from texlate.latex import parse_tex
from texlate.latex.model import ScanResult
from texlate.latex.reconstruct import reconstruct


def scan(body: str, defs: str = "") -> ScanResult:
    tex = ART % (defs, body)
    res = parse_tex(tex)
    check_invariants(res, tex)
    return res


def mock_splice(res: ScanResult) -> str:
    """mock 翻译臂：全部 chunk 换 ``这是译文`` 后 splice。"""
    return reconstruct(res, {c.id: "这是译文" for c in res.chunks})


def test_aipproc_author_second_keyval_arg_absorbed() -> None:
    r"""``\author{name}{address=..,email=..}`` 整调用进保护——键位零泄漏。"""
    res = scan(
        "\\author{J.~Blum}{\n"
        '  address={TU Braunschweig, Institut f\\"ur Physik},\n'
        "  email=j.blum@tu-bs.de\n"
        "}\n"
        "Body prose words after the author block keep flowing here."
    )
    out = mock_splice(res)
    assert "这是译文=" not in out
    assert "address={TU Braunschweig" in out
    assert "email=j.blum@tu-bs.de" in out
    assert "这是译文" in out  # 后文散文照常落占位符


def test_aipproc_author_multi_author_blocks() -> None:
    """连续 ``\\author`` 块逐块吸收（实格文档 3+ 连写）。"""
    res = scan(
        "\\author{A.~One}{address={First Inst},email=a@x.edu}\n"
        "\\author{B.~Two}{address={Second Inst},altaddress={Visiting}}\n"
        "\\author{C.~Three}{address={Third Inst}}\n"
        "Prose paragraph text with enough words to stay diggable."
    )
    out = mock_splice(res)
    assert "{address={First Inst},email=a@x.edu}" in out
    assert "{address={Second Inst},altaddress={Visiting}}" in out
    assert "{address={Third Inst}}" in out
    assert not re.search(r"这是译文\s*=", out)


def test_author_brace_kv_with_comment_lines() -> None:
    r"""keyval 组内 ``%`` 注释行——``_KV_COMMENT_RX`` 剥后判形（2105.00041 lstlean 同族）。"""
    res = scan(
        "\\author{D.~Hei\\ss{}elmann}{\n"
        "  % affiliation block\n"
        "  address={TU Braunschweig},\n"
        "  email=dh@tu-bs.de\n"
        "}\n"
        "Body prose after keeps the paragraph alive and flowing."
    )
    out = mock_splice(res)
    assert "这是译文=" not in out
    assert "address={TU Braunschweig}" in out


def test_author_nonkv_second_group_stays_diggable() -> None:
    r"""负例：``\author{n}{plain prose}`` 第二组非键值形 → 回放进译文面。"""
    res = scan(
        "\\author{Someone}{and a second prose group here}\n"
        "Body prose keeps flowing here with enough words."
    )
    out = mock_splice(res)
    assert "\\author{Someone}" in out
    assert "这是译文" in out  # 散文第二组被译——键值门不误吞


def test_bare_key_list_second_arg_absorbed() -> None:
    """全裸键逗号列第二参（``{draft,final}`` 形）同收——全项裸键 token 判据。"""
    res = scan(
        "\\author{Someone}{draft,final}\n"
        "Body prose keeps flowing here with enough words now."
    )
    out = mock_splice(res)
    assert "{draft,final}" in out
    assert not re.search(r"这是译文\s*[=,\]}]", out)
