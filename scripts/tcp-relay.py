#!/usr/bin/env python3
"""tcp-relay.py <lport> <rhost> <rport> — 微型 asyncio TCP 转发（纯 stdlib）。

用途：让只认 127.0.0.1 的组件（如 validate_base_url 强制非 localhost https
之外的产品链）吃到 tailnet/远端服务。比 ssh -L 轻、比 socat 可控。

例：python3 scripts/tcp-relay.py 13003 100.105.212.52 3003 &
出处：tmp/transcript-mining/484a9c38.md A10。
"""

import asyncio
import sys

ARGC = 4
LISTEN: tuple[str, int]
TARGET: tuple[str, int]


async def pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
    """单向泵：r → w，对端耗尽或断连即收。"""
    try:
        while data := await r.read(65536):
            w.write(data)
            await w.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        w.close()


async def handle(cr: asyncio.StreamReader, cw: asyncio.StreamWriter) -> None:
    """每连接：起上行连接，双向泵汇合。"""
    try:
        sr, sw = await asyncio.open_connection(*TARGET)
    except OSError:
        cw.close()  # 上游不可达时释放客户端连接，避免挂到客户端读超时
        return
    await asyncio.gather(pipe(cr, sw), pipe(sr, cw))


async def main() -> None:
    """起监听并永久服务。"""
    srv = await asyncio.start_server(handle, *LISTEN)
    sys.stderr.write(f"relay {LISTEN[0]}:{LISTEN[1]} -> {TARGET[0]}:{TARGET[1]}\n")
    await srv.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) != ARGC:
        sys.exit(__doc__)
    try:
        LISTEN = ("127.0.0.1", int(sys.argv[1]))
        TARGET = (sys.argv[2], int(sys.argv[3]))
    except ValueError:
        sys.exit(__doc__)
    asyncio.run(main())
