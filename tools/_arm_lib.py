"""arm 对照组共用件（lib 件非入口）：driver 写 +0800 当日 ``%H:%M:%S`` 窗、usage 同口径解回 epoch ms。

TZ 契约是 driver/usage 两文件间唯一强耦合点——各写各的时区会静默错窗
（网关 ``logs.time`` 是毫秒 epoch，窗偏一小时整段账全歪）。跨零点
``t1<t0 → +DAY_MS`` 规则在 usage 侧（driver 恒有 epoch 不需要）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

TZ8 = timezone(timedelta(hours=8))
DAY_MS = 86_400_000


def hms(ts: float) -> str:
    """epoch 秒 → +0800 当日 ``%H:%M:%S`` 面。"""
    return datetime.fromtimestamp(ts, TZ8).strftime("%H:%M:%S")


def hms_ms(s: str, day: date) -> int:
    """``%H:%M:%S`` + ``day``（+0800 当日）→ epoch ms。"""
    h, m, sec = map(int, s.split(":"))
    local = datetime(day.year, day.month, day.day, h, m, sec, tzinfo=TZ8)
    return int(local.timestamp() * 1000)
