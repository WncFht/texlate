"""provider 探测传输 + 预设目录 —— ``/v1/models`` 探活与 settings 页清单。

本叶只载传输与目录两件自包含物；``save`` 期的探活编排（TTL 缓存/
``model_warning``/``TEXLATE_MODEL_PROBE`` kill-switch）留在 settings.py
与本叶的 ``list_provider_models`` 协作——测试经
``monkeypatch.setattr(settings, "list_provider_models")`` 钉住该面，
调用方须在 settings 名空间解析本函数。
"""

from __future__ import annotations

from typing import Any

from texlate.textutil import env_raw
from texlate.xlat.client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    PROVIDER_KEY_ENV,
    model_ids_from,
    normalize_base_url,
    provider_for_url,
)

#: ``save`` 期 ``/v1/models`` 探活超时——不可达不阻断保存（M3 smoke B2：
#: 存了 provider 拒收的 model 会持续毒化后续任务，值得警告但不值得硬拒）
_MODEL_PROBE_TIMEOUT_S = 3.0


def list_provider_models(
    base_url: str, api_key: str = "", *, timeout: float = _MODEL_PROBE_TIMEOUT_S
) -> list[str] | None:
    """同步 ``GET {root}/v1/models`` → 模型 id 清单；任何失败 → ``None``。

    ``ChatClient.list_models`` 的同步退化形（openai 方言 Bearer 头，与其
    ``_openai_headers`` 同口径）。``SettingsStore.save`` 是同步路径；探活
    失败面一律收敛 ``None``——离线/不可达 provider 绝不阻断 settings UX。
    """
    import httpx  # noqa: PLC0415 -- 重依赖惰性加载

    root = normalize_base_url(base_url)
    if not root:
        return None
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        resp = httpx.get(
            f"{root}/v1/models",
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )
    except Exception:  # noqa: BLE001 -- 探活失败面收敛 None
        return None
    if not resp.is_success:
        return None
    try:
        data = resp.json()
    except ValueError:
        # JSONDecodeError + 非 UTF-8 体（GBK 错误页等）的
        # UnicodeDecodeError 同属 ValueError——探活失败面收敛 None
        return None
    items = data.get("data") if isinstance(data, dict) else None
    # 非 list → ``model_ids_from`` 回 ``None``——与探活失败面同口径收敛
    return model_ids_from(items)


def provider_presets(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """``GET /api/providers`` 出参：预设清单 + 当前选中态（key 只给 has_api_key）。"""
    conns_url = settings.get("base_url", "")
    presets = [
        {
            "id": "gateway",
            "name": "Local Gateway",
            "base_url": DEFAULT_BASE_URL,
            "model": DEFAULT_MODEL,
            "key_env": PROVIDER_KEY_ENV["gateway"],
        },
        {
            "id": "deepseek",
            "name": "DeepSeek",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "key_env": PROVIDER_KEY_ENV["deepseek"],
        },
        {
            "id": "openai",
            "name": "OpenAI",
            "base_url": "https://api.openai.com",
            "model": "gpt-4o-mini",
            "key_env": PROVIDER_KEY_ENV["openai"],
        },
        {
            "id": "anthropic",
            "name": "Anthropic",
            "base_url": "https://api.anthropic.com",
            "model": "claude-haiku-4-5",
            "key_env": PROVIDER_KEY_ENV["anthropic"],
        },
        {
            "id": "qwen",
            "name": "Alibaba Qwen",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode",
            "model": "qwen-flash",
            "key_env": PROVIDER_KEY_ENV["qwen"],
        },
        {
            "id": "custom",
            "name": "Custom (OpenAI 兼容)",
            "base_url": "",
            "model": "",
            "key_env": PROVIDER_KEY_ENV["custom"],
        },
    ]
    current_provider = provider_for_url(conns_url) if conns_url else ""
    for p in presets:
        p["active"] = p["id"] == current_provider
        p["has_env_key"] = bool(env_raw(p["key_env"]))
    return presets
