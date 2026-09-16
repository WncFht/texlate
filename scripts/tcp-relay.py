#!/usr/bin/env python3
"""tcp-relay.py <lport> <rhost> <rport> — 30 行 asyncio TCP 转发。

用途：让只认 127.0.0.1 的组件（如 validate_base_url 强制非 localhost https
之外的产品链）吃到 tailnet/远端服务。比 ssh -L 轻、比 socat 可控（纯 stdlib）。

例：python3 scripts/tcp-relay.py 13003 100.105.212.52 3003 &
出处：tmp/transcript-mining/484a9c38.md A10。
"""

import asyncio
import sys

LISTEN = ("127.0.0.1", int(sys.argv[1]))
TARGET = (sys.argv[2], int(sys.argv[3]))


async def pipe(r, w):
    try:
        while data := await r.read(65536):
            w.write(data)
            await w.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        w.close()


async def handle(cr, cw):
    sr, sw = await asyncio.open_connection(*TARGET)
    await asyncio.gather(pipe(cr, sw), pipe(sr, cw))


async def main():
    srv = await asyncio.start_server(handle, *LISTEN)
    print(f"relay {LISTEN[0]}:{LISTEN[1]} -> {TARGET[0]}:{TARGET[1]}")
    await srv.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    asyncio.run(main())
