"""kernel._cli_cache — cache 子动词叶 (kernel.cli 拆分叶, §3.9).

``bench cache`` 的三动词: status (桶数/字节/上限 + malformed)、
evict (LRU 向目标字节或 TEXLATE_CACHE_CAP_GB 上限)、rebuild
(vault/state -> 桶: 重放 xlat-state 结果过 segment_key)。

门面回引名单见 ``kernel.cli._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import json

from kernel import cache as cachemod
from kernel._cli_common import (
    EXIT_OK,
    EXIT_REFUSED,
    _err,
    _parse_size,
    _pre_write,
    _print_json,
)


def _cmd_cache_status(_args) -> int:
    _print_json(cachemod.status())
    return EXIT_OK


def _cmd_cache_evict(args) -> int:
    _pre_write()
    if args.to_free is None:
        removed = cachemod.cap_evict()
    else:
        try:
            target = _parse_size(args.to_free)
        except ValueError as exc:
            _err(str(exc))
            return EXIT_REFUSED
        removed = cachemod.evict(target)
    print(f"evicted {len(removed)} bucket(s):")
    for p in removed:
        print(f"  {p}")
    return EXIT_OK


def _cmd_cache_rebuild(args) -> int:
    _pre_write()
    glossary = None
    if args.glossary_json is not None:
        try:
            glossary = json.loads(args.glossary_json)
        except ValueError as exc:
            _err(f"--glossary-json: {exc}")
            return EXIT_REFUSED
    res = cachemod.rebuild_from_vault(
        prompt_version=args.prompt_version,
        base_url=args.base_url,
        model=args.model,
        lang=args.lang,
        glossary=glossary,
        context=args.context,
        dry=args.dry,
        progress=print,
    )
    _print_json(res)
    return EXIT_OK
