"""``latex.api`` v1/v2 env 分派钉：``TEXLATE_NO_EXPAND`` → v1 字节 scanner 臂。

``parse_tex``/``parse_file`` 的双臂分派是 v2 默认路径（``Gullet``+
``Segmenter``）与 v1 对照臂的切换闸（api.py ``env_flag(_NO_EXPAND)``）——
env 名或真值词漂移会静默换臂，此处钉死分派方向与返回值透传。
"""

from pathlib import Path

import pytest

from texlate.latex import api

_TEX = "\\documentclass{article}\n\\begin{document}\nHello.\n\\end{document}\n"


def _spy_arms(monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], object]:
    """把 api 四个分派落点换成记账 spy；返回 (命中序, 哨兵返回值)。"""
    hits: list[str] = []
    sentinel = object()

    def v1_tex(_tex: str) -> object:
        hits.append("tex_v1")
        return sentinel

    def v2_tex(_tex: str) -> object:
        hits.append("tex_v2")
        return sentinel

    def v1_file(_path: object, **_kw: object) -> object:
        hits.append("file_v1")
        return sentinel

    def v2_scan(_g: object) -> object:
        hits.append("file_v2")
        return sentinel

    monkeypatch.setattr(api, "parse_tex_v1", v1_tex)
    monkeypatch.setattr(api, "parse_tex_v2", v2_tex)
    monkeypatch.setattr(api, "parse_file_v1", v1_file)
    monkeypatch.setattr(api, "scan_v2", v2_scan)
    return hits, sentinel


def test_no_expand_env_routes_to_v1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``TEXLATE_NO_EXPAND=1`` → ``parse_tex``/``parse_file`` 双双走 v1 臂。"""
    monkeypatch.setenv("TEXLATE_NO_EXPAND", "1")
    hits, sentinel = _spy_arms(monkeypatch)
    main = tmp_path / "main.tex"
    main.write_text(_TEX, encoding="utf-8")

    assert api.parse_tex(_TEX) is sentinel
    assert api.parse_file(main) is sentinel
    assert hits == ["tex_v1", "file_v1"]


@pytest.mark.parametrize("val", [None, "0", "false"])
def test_default_routes_to_v2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, val: str | None
) -> None:
    """env 缺席/假值（``0``/``false``）→ 默认 v2 ``Gullet``+``Segmenter`` 臂。"""
    if val is None:
        monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)
    else:
        monkeypatch.setenv("TEXLATE_NO_EXPAND", val)
    hits, sentinel = _spy_arms(monkeypatch)
    main = tmp_path / "main.tex"
    main.write_text(_TEX, encoding="utf-8")

    assert api.parse_tex(_TEX) is sentinel
    assert api.parse_file(main) is sentinel
    assert hits == ["tex_v2", "file_v2"]
