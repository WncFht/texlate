"""fuzz 公共骨架——种子 RNG / soup 表驱动 / xfail 钉 / findings 台账写出。

从 ``test_fuzz_glossary`` / ``test_fuzz_xlat_client`` / ``test_fuzz_judge`` /
``test_fuzz_engine`` / ``test_fuzz_xlat_retry`` 五个既有 fuzz 文件抽取的
共享件（只抽不写回——既有文件保持原样）。约定：

- 全量确定性：一切随机源走 ``fuzz_rng(seed)``（``random.Random`` 包装，
  ``# noqa: S311`` 集中在此处一次），种子常量名 ``_SEED_*``、迭代量
  ``_FUZZ_ITERS`` 由各测试文件自报——复现路径 = 同 seed 重跑。
- soup 表驱动：``soup_join``/``soup_pick`` 把「随机敌意输入」收敛成
  「从字符/片段汤里按概率拼」，汤表本身留在各测试文件（``#:`` 注释记档）。
- 缺陷钉：``xfail_confirmed`` 产 ``pytest.mark.xfail(strict=True)``——
  钉的是**期望契约**，修复落地 XPASS 转红即拆钉信号；观察钉不用它
  （观察钉是普通断言，pin 当前行为防误读）。
- findings 台账：``write_findings`` 统一写出 ``tmp/*-fuzz/findings.txt``
  的既有格式（lane/id/severity/repro/file:line 口径）。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path


def fuzz_rng(seed: int) -> random.Random:
    """确定性 RNG——``random.Random(seed)`` 的唯一来源（S311 豁免集中点）。"""
    return random.Random(seed)  # noqa: S311 -- 确定性种子复现，非密码学


def soup_pick(rng: random.Random, soup: Sequence[str]) -> str:
    """从 soup 表等权取一片——汤表即概率分布本身（重复条目加权）。"""
    return soup[rng.randrange(len(soup))]


def soup_join(
    rng: random.Random,
    soup: Sequence[str],
    lo: int,
    hi: int,
    sep: str = "",
) -> str:
    """从 soup 表随机取 ``lo..hi`` 片拼接——敌意输入汤的标准构造。"""
    return sep.join(soup_pick(rng, soup) for _ in range(rng.randint(lo, hi)))


def short(s: object, n: int = 80) -> str:
    """断言语料回显——repr + 截断，失败信息里放得下。"""
    r = repr(s)
    return r if len(r) <= n else r[: n - 3] + "..."


def xfail_confirmed(reason: str) -> pytest.MarkDecorator:
    """CONFIRMED 缺陷钉——``xfail(strict=True)`` 钉期望契约。

    修复落地后 XPASS 转红 = 拆钉信号；观察钉（pin 当前行为）不用此件。
    """
    return pytest.mark.xfail(reason=reason, strict=True)


def assert_deterministic(
    fn: Callable[[], object],
    *,
    key: Callable[[object], object] | None = None,
    rounds: int = 2,
) -> object:
    """同输入连跑 ``rounds`` 次投影恒等——确定性不变量断言件。

    ``key`` 是投影函数（默认恒等）——被测返回无 ``__eq__`` 语义的
    结果容器时（如 ``ScanResult`` 内含无 eq 字段），传投影取可比较面。
    返回首轮投影值供调用方继续断言。
    """
    proj: Callable[[object], object] = key or (lambda x: x)
    first = proj(fn())
    for _ in range(rounds - 1):
        assert proj(fn()) == first
    return first


@dataclass(frozen=True)
class Finding:
    """单条 findings 台账记录。

    ``fid`` 台账号（``"D1"``/``"S1"``），``title`` 单行标题，
    ``body`` 多行细节（repro/reachability/建议修法），``status`` 尾标
    （``""`` / ``" [FIXED]"`` / ``" [NEW]"`` 等原样后缀）。
    """

    fid: str
    title: str
    body: str = ""
    status: str = ""


def _block(text: str, indent: str = "    ") -> str:
    """多行 body 统一缩进——台账行内块格式。"""
    return "\n".join(indent + ln if ln.strip() else "" for ln in text.splitlines())


def write_findings(  # noqa: PLR0913 -- 台账每 kwarg 即一节，拆 dataclass 反而多一层簿记
    path: Path,
    *,
    title: str,
    scope: str,
    test_file: str,
    status: str,
    confirmed: Sequence[Finding] = (),
    observed: Sequence[str] = (),
    notes: Sequence[str] = (),
    extra_sections: Sequence[tuple[str, str]] = (),
    scratch: str = "",
) -> None:
    """写 ``tmp/*-fuzz/findings.txt`` 台账——沿用 glossary-fuzz 既有格式。

    头块（scope/testfile/status/ruff）→ NOTES → CONFIRMED DEFECTS（
    ``D#  title`` + 缩进 body）→ OBSERVED QUIRKS（bullet）→ 自定义节 →
    scratch 尾注。``confirmed`` 空表时 CONFIRMED 节写 ``(none)``。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    head = f"{title} — 2026-09-17"
    lines = [
        head,
        "=" * len(head),
        f"Scope: {scope}",
        f"Test file: {test_file}",
        f"Status: {status}",
        "ruff check + ruff format --check: clean.",
        "",
    ]
    for note in notes:
        lines += ["NOTE:", _block(note), ""]
    lines += [
        "CONFIRMED DEFECTS (all pinned xfail-strict; D# matches test-file ledger)",
        "-" * 75,
        "",
    ]
    if confirmed:
        for f in confirmed:
            lines.append(f"{f.fid}  {f.title}{f.status}")
            if f.body:
                lines.append(_block(f.body))
            lines.append("")
    else:
        lines += ["(none)", ""]
    if observed:
        lines += [
            "OBSERVED QUIRKS (pinned as behavior, not defects)",
            "-" * 49,
        ]
        lines += [f"- {ob}" for ob in observed]
        lines.append("")
    for head, body in extra_sections:
        lines += [head, "-" * len(head), body, ""]
    if scratch:
        lines += [f"Scratch: {scratch} (probes + repro scripts; gitignored)", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
