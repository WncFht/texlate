"""``logsetup.SECRET_LOG_PATTERNS`` ↔ ``xlat._errors._SECRET_PATTERNS`` 覆盖护栏。

logsetup 是日志底座不反引 ``xlat``（拖 httpx/asyncio/ssl 全栈），两表
并存、注释声称日志表是基表全覆盖超集——本无测试钉住这条不变量。
每条基表 regex 至少一条代表串命中（基表新加形态而无样串即红——提醒
补样串+核日志表），且样串同被日志表命中、``scrub`` 抹除到位。
"""

from __future__ import annotations

import pytest

from texlate.logsetup import SECRET_LOG_PATTERNS, scrub
from texlate.xlat._errors import _SECRET_PATTERNS

#: 基表每条形态的代表串（``sk-`` 基表两档分开采样）。
_SAMPLES: list[str] = [
    "Authorization: Bearer abc.def-ghi",  # Bearer\s+\S+
    "key = sk-abcdefghij12345",  # sk-[A-Za-z0-9_-]{8,}
    "key = sk-ant-api03-xyz",  # sk-ant-[A-Za-z0-9_-]{4,}
    "token AIza0123456789abcd",  # AIza[0-9A-Za-z_-]{10,}
    "api_key=supersecret",  # api[_-]?key=
    "x-api-key: supersecret",  # x-api-key:
    "token=tok123456",  # token=
]


def test_log_table_covers_every_base_pattern() -> None:
    """基表每条 regex 的命中串，日志表须同样命中（两表漂移即红）。"""
    for base_rx in _SECRET_PATTERNS:
        hits = [s for s in _SAMPLES if base_rx.search(s)]
        assert hits, f"基表形态无代表串（新增形态须补 _SAMPLES）: {base_rx.pattern}"
        for s in hits:
            assert any(rx.search(s) for rx in SECRET_LOG_PATTERNS), (
                f"日志表漏抓基表命中串 {s!r}（基表形态 {base_rx.pattern}）"
            )


@pytest.mark.parametrize("sample", _SAMPLES)
def test_scrub_redacts_samples(sample: str) -> None:
    """每条代表串经 ``scrub`` 抹成 ``***`` 且无残留命中。"""
    out = scrub(sample)
    assert "***" in out
    for rx in SECRET_LOG_PATTERNS:
        assert not rx.search(out)
