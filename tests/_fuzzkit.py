"""fuzz 公共骨架——种子 RNG / soup 表驱动 / xfail 钉 / findings 台账写出。

从 ``test_fuzz_glossary`` / ``test_fuzz_xlat_client`` / ``test_fuzz_judge`` /
``test_fuzz_engine`` / ``test_fuzz_xlat_retry`` 五个既有 fuzz 文件抽取的
共享件（只抽不写回——既有文件保持原样）。约定：

- 全量确定性：一切随机源走 ``fuzz_rng(seed)``（``random.Random`` 包装，
  ``# noqa: S311`` 集中在此处一次）；种子/迭代量写法各文件自便——
  命名常量 ``_SEED_*``/``_FUZZ_ITERS*`` 或内联日期戳字面量皆可——
  复现路径 = 同 seed 重跑。
- soup 表驱动：``soup_join``/``soup_pick`` 把「随机敌意输入」收敛成
  「从字符/片段汤里按概率拼」，汤表本身留在各测试文件（``#:`` 注释记档）。
- 缺陷钉约定：CONFIRMED 钉产 ``pytest.mark.xfail(strict=True)``——
  钉的是**期望契约**，修复落地 XPASS 转红即拆钉信号；观察钉不用它
  （观察钉是普通断言，pin 当前行为防误读）。
- findings 台账：``write_findings`` 统一写出 ``tmp/*-fuzz/findings.txt``
  的既有格式（lane/id/severity/repro/file:line 口径）。
- zip/jsonl 构造件：``zip_bytes``（``(成员名, 字节)`` 对写 zip——
  ``dict.items()`` 直喂、重复名可表达）、``write_jsonl_rows``（父目录先建
  + 逐行 str 原样/``json.dumps(ensure_ascii=False)`` 写 JSONL）。
- pipeline 伪件：``RecordingTranslator``——录制型 translator（入参入账、
  marker→异常有序派发、slots 应答、批/独员路由旋钮），预设应答件
  ``echo_reply``/``strip_feedback_reply``/``zh_prefix_reply``/``zh_lines_reply``。
"""

from __future__ import annotations

import datetime
import io
import json
import random
import re
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from pathlib import Path
    from typing import Any


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
    date: str | None = None,
) -> None:
    """写 ``tmp/*-fuzz/findings.txt`` 台账——沿用 glossary-fuzz 既有格式。

    头块（scope/testfile/status/ruff）→ NOTES → CONFIRMED DEFECTS（
    ``D#  title`` + 缩进 body）→ OBSERVED QUIRKS（bullet）→ 自定义节 →
    scratch 尾注。``confirmed`` 空表时 CONFIRMED 节写 ``(none)``；节头
    随 ``Finding.status`` 派生——全空才写 ``all pinned xfail-strict``，
    否则写逐条尾标口径（``[FIXED]``/``[NEW]`` 等后缀已非钉语义）。
    ``date`` 缺省取当天——台账头随重跑日滚动，不烙历史戳。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    head = f"{title} — {date or datetime.datetime.now(datetime.UTC).date().isoformat()}"
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
        (
            "CONFIRMED DEFECTS (all pinned xfail-strict; D# matches test-file ledger)"
            if all(not f.status for f in confirmed)
            else "CONFIRMED DEFECTS (status suffix per entry; D# matches test-file ledger)"
        ),
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


# ---------------------------------------------------------------- zip/jsonl 构造件


def zip_bytes(members: Iterable[tuple[str, bytes]]) -> bytes:
    """``(成员名, 字节)`` 序列写 zip——``dict.items()`` 直喂, 重复名亦可表达。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, blob in members:
            z.writestr(name, blob)
    return buf.getvalue()


def write_jsonl_rows(path: Path, rows: Iterable[object]) -> None:
    """``rows`` 逐行写 JSONL——str 原样、其余 ``json.dumps(ensure_ascii=False)``；父目录先建。

    与 ``benchlib.write_jsonl(fh, rec)`` 不同型——那边是句柄+单条记录，
    本件是 path+整表（mkdir 超集）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False))
            f.write("\n")


# ---------------------------------------------------------------- pipeline 录制伪件

_NUM_LINE_RX = re.compile(r"^\[\d+\]")
_NUM_SPLIT_RX = re.compile(r"^(\[\d+\])\s?(.*)$", re.DOTALL)
#: `[n] keep: ids |` 名单前缀——协议元数据不是待译内容；回显侧剥掉
#: 同 mock._MOCK_NUM_RX 口径（留着会被 `zh:` 前缀弄成非段首 echo、
#: _strip_keep_echo 够不到、名单 token 变 extra-ph 全体退单翻）
_KEEP_REST_RX = re.compile(r"^keep:(?:[ \t]*\[\[[A-Z][A-Z_]*_?\d*\]\])+[ \t]*\|?[ \t]*")


def echo_reply(user: str) -> str:
    """恒等回显——``user`` 原样返回。"""
    return user


def strip_feedback_reply(user: str) -> str:
    """剥 ``[previous_validation_error]`` 反馈后缀后回显（xlat 臂缺省口径）。"""
    return user.split("\n\n[previous_validation_error]", maxsplit=1)[0]


def zh_prefix_reply(user: str) -> str:
    """``zh:`` 前缀回显（residual 臂独员缺省口径）。"""
    return f"zh:{user}"


def zh_lines_reply(user: str) -> str:
    """``[n] rest`` 逐行回 ``[n] zh:rest``；不匹配行原样透传（residual 臂批缺省）。

    ``[n] keep: ids | rest`` 的名单前缀剥掉再挂 ``zh:``——真实模型不回显
    协议元数据（prompts 条款明令），伪件同理才不构成假退单翻。
    """
    return "\n".join(
        f"{m.group(1)} zh:{_KEEP_REST_RX.sub('', m.group(2))}"
        if (m := _NUM_SPLIT_RX.match(ln))
        else ln
        for ln in user.split("\n")
    )


class RecordingTranslator:
    """录制型 translator——``XlatPipeline`` translator 协议的共享伪件。

    行为只看 ``user`` 文本，与 asyncio 调度序无关。旋钮：

    - ``markers``：有序 ``(marker, exc)`` 对——``marker in user`` 即 ``raise exc``；
      序列序 = 派发优先级（xlat 臂 AUTH→E500→E5XX→CRASH，residual 臂追加 KI）。
    - ``record``：``"dict"`` 全入参入账（system/user/temperature/max_tokens/rf），
      ``"user"`` 只记 ``user`` 串。
    - ``slots_fill``：``response_format`` 请求 → slots JSON 每槽回该值；
      ``None`` = 不走 slots 分支（rf 请求落到批/独员路由——batch 臂语义）。
    - ``batch_match``：批请求判据——``"prefix"`` = ``user.startswith("[1]")``；
      ``"lines"`` = 非空行全 match ``^\\[\\d+\\]``。两变体语义不同，不并。
    - ``single_fn``/``batch_fn``：独员/批应答钩子，缺省 ``echo_reply``；
      变体预设件见 ``strip_feedback_reply``/``zh_prefix_reply``/``zh_lines_reply``。
    """

    def __init__(  # noqa: PLR0913 -- 每 kwarg 钉一臂语义变体，拆 config 只多一层簿记
        self,
        *,
        record: str = "dict",
        markers: Iterable[tuple[str, BaseException]] = (),
        slots_fill: str | None = "槽译",
        batch_match: str = "prefix",
        single_fn: Callable[[str], str] | None = None,
        batch_fn: Callable[[str], str] | None = None,
    ) -> None:
        """knob 全 keyword-only——调用点显式声明各臂语义。"""
        if record not in ("dict", "user"):
            msg = f"record must be 'dict' or 'user', got {record!r}"
            raise ValueError(msg)
        if batch_match not in ("prefix", "lines"):
            msg = f"batch_match must be 'prefix' or 'lines', got {batch_match!r}"
            raise ValueError(msg)
        self.calls: list[Any] = []
        self._record = record
        self._markers = list(markers)
        self._slots_fill = slots_fill
        self._batch_match = batch_match
        self.single_fn = single_fn or echo_reply
        self.batch_fn = batch_fn or echo_reply

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """入账 → marker 派发 → slots → 批/独员路由。"""
        if self._record == "dict":
            self.calls.append(
                {
                    "system": system,
                    "user": user,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "rf": response_format,
                }
            )
        else:
            self.calls.append(user)
        for marker, exc in self._markers:
            if marker in user:
                raise exc
        if response_format is not None and self._slots_fill is not None:
            payload = json.loads(user)
            slots = payload.get("slots") or {}
            return json.dumps(
                dict.fromkeys(slots, self._slots_fill), ensure_ascii=False
            )
        if self._is_batch(user):
            return self.batch_fn(user)
        return self.single_fn(user)

    def _is_batch(self, user: str) -> bool:
        """批请求判据——``"prefix"``/``"lines"`` 两变体语义不同，不并。"""
        if self._batch_match == "lines":
            lines = user.split("\n")
            return bool(lines) and all(
                _NUM_LINE_RX.match(ln) for ln in lines if ln.strip()
            )
        return user.startswith("[1]")
