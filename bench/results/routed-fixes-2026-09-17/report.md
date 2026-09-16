# routed-fixes — 审计路由小件包（Fetcher 门面 + unpack_share 原子化）

> 2026-09-17 收口。落地：fetch/share/测试 `39c671f`；cli.py `with Fetcher()` 换用被 1d 的 `9d5ce9d` 顺带收走（同台提交含 parse_file fifo guard——cli-audit 路由的 TOCTOU 修复）。`pytest test_share+test_arxiv_fetch+test_cli` 108 passed/1 skipped；ruff 双净。

## 修复 1：Fetcher 资源门面（arxiv/fetch.py）

- `fetch.py:28` `Self` 进 typing import（运行时 import，对齐 l1.py 惯例）。
- `fetch.py:247-257` 新增 `close()`（委托 `self.client.close()`，httpx close 幂等）+ `__enter__`/`__exit__`（`*_exc: object` 签名对齐 `validate/l1.py:330-336` 惯例）。
- `cli.py:114-125` `_acquire` 改 `with Fetcher() as fetcher:`，消除 `fetcher.client.close()` reach-into。`_resolve_source`（cli.py:377）经 `_acquire` 间接受益，全仓无其它 `.client` 穿透点。

## 修复 2：unpack_share 部分写出清理（share.py）

- 选型 **temp-dir-in-dest + 校验后 rename**（比 track-and-delete 更严——后者救不回"已被覆写的用户同名文件"，本方案校验失败时 dest 零字节变动）。
- `share.py:399-419`：产物先写 `dest/.{dest.name}.XXXX`（mkdtemp `dir=dest`——同目录必同设备免跨设备 rename 坑）；全量对账过后逐件 `Path.replace`（原子覆写同名旧件）；`finally` rmtree(tmp)；`fresh` dest 失败路径顺手 rmdir 空壳。docstring 同步删「由调用方清理」旧契约。
- `_extract_verified` 签名未动，只改调用方传 tmp。

## 新测试（+5）

- `test_fetcher_close_idempotent` / `test_fetcher_context_manager`（test_arxiv_fetch.py）。
- `_tampered_last_artifact` helper——末位 dual.json 同长换内容（size 对账过、sha256 开火）构造中途失败点。
- `test_unpack_mid_failure_no_residue`（新 dest 失败整个收走）/ `test_unpack_mid_failure_preserves_existing_dest`（既有 dest 用户文件+同名旧成员原样保留）/ `test_unpack_replaces_and_cleans_tmp`（成功路径旧件被换、无 tmp 残留）。

## 外部路由（leader 处理）

1. **worker.py:1475 Fetcher 泄漏**：`_fetch_arxiv` 里 `self._fetcher or Fetcher(RateLimiter(...))`——生产路径每任务新建 Fetcher 从不 close，连接池随任务数泄漏。修时注意 ownership：注入的 `self._fetcher` 不能关，只关自建实例。→ worker 域（leader 记 backlog，worker-audit 在飞）。
2. **worker.py:1967 在飞残缺**：`self._invalidate_splice(ctx, pre_rows)` 被调用但方法未定义，15 例测试红（test_share_apply/test_share_wire）——worker-audit 在飞半成品，已通知其尽早补齐/回退以免全仓 suite 持续红。
