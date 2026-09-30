"""env/选项开关与小件纯函数域（自 ``_common`` 出叶）。

``_env_timeout``/``opt_bool``/``COMPILE_TIMEOUT`` 是 env+settings 读入面
（nan/inf/非正/超限回默认，explicit > env 三层链单源在
``textutil.osutil.opt_switch``）；``_scrub_deep`` 是事件载荷落盘前的
递归 secret 抹除；``_translate_progress``/``_tgt_lang``/
``_glossary_option`` 是 translate 段的进度映射/语言名/术语选项裁决。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from texlate.server.settings import (
    COMPILE_TIMEOUT_MAX_S,
    DEFAULT_COMPILE_TIMEOUT_S,
    scrub,
)
from texlate.server.worker._common_const import PROGRESS
from texlate.textutil import env_float
from texlate.textutil.osutil import ENV_COMPILE_TIMEOUT, opt_switch

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from texlate.server.worker._common_ctx import TaskCtx

#: env 超时值 24h 封顶——更大属配置错误；单源在 settings
#: （``COMPILE_TIMEOUT_MAX_S``），本别名保 ``worker.__init__`` 再出口旧名
_ENV_TIMEOUT_MAX_S = COMPILE_TIMEOUT_MAX_S


def _env_timeout(name: str, default: float) -> float:
    """``TEXLATE_*`` 秒数 env 读入——nan/inf/非正/超限一律回默认。"""
    v = env_float(name, default)
    return v if 0.0 < v <= _ENV_TIMEOUT_MAX_S else default


def opt_bool(options: dict[str, Any], key: str, env_on: Callable[[], bool]) -> bool:
    """options[key] 显式值 > env_on()——worker 开关统一 explicit 优先（e2e 同式）。

    薄壳——三层链与 ``"0"/"false"/"no"/"off"`` 字符串 false 系归一化单源
    在 ``textutil.osutil.opt_switch``；env_on 是「开」语义零参 callable
    （NO_ 系 env 由调用侧取反喂入）。
    """
    return opt_switch(options, key, env_on)


#: 编译超时（docs/spec/compile.md 默认值；server 路径无 --timeout flag）——
#: 全链优先级 ``TEXLATE_COMPILE_TIMEOUT`` env > settings.json
#: ``compile_timeout`` > 240s，``create_app`` 装配时解析透传；本常量
#: 兜非 app 构造方（测试/内嵌直 new PipelineWorker 不走 settings）
COMPILE_TIMEOUT = _env_timeout(ENV_COMPILE_TIMEOUT, DEFAULT_COMPILE_TIMEOUT_S)


def _scrub_deep(value: Any, api_key: str) -> Any:  # noqa: ANN401 -- JSON 形状递归天然 Any
    """递归抹 JSON-able 结构里字符串的 secret 形态（事件载荷落盘前调用）。"""
    if isinstance(value, str):
        return scrub(value, api_key)
    if isinstance(value, (list, tuple)):
        return [_scrub_deep(v, api_key) for v in value]
    if isinstance(value, dict):
        return {
            _scrub_deep(k, api_key): _scrub_deep(v, api_key) for k, v in value.items()
        }
    return value


def _translate_progress(done: int, total: int) -> int:
    """按 done/total 线性映射 translating 段进度（25→85）。"""
    lo, hi = PROGRESS["translating"]
    return min(hi, lo + int((hi - lo) * done / max(1, total)))


def _tgt_lang(target_lang: str) -> str:
    """``zh-CN/zh-TW/en`` → prompt 语言名。"""
    return {"zh-TW": "Traditional Chinese", "en": "English"}.get(target_lang, "Chinese")


def _glossary_option(ctx: TaskCtx, cfg: Mapping[str, Any]) -> str:
    """生效 ``glossary`` 选项：``config.glossary``（settings 透传）> ``options.glossary``。"""
    return str(cfg.get("glossary") or ctx.options().get("glossary") or "")
