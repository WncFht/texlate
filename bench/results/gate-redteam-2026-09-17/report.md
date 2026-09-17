# gate-redteam — SEC-1..10 独立绕过测试交付

> 2026-09-17 收口。落地 `e499515`（app.py + test_server_gate.py，+70/-4）。探针 `tmp/gate-redteam/probe1-5.py`（gitignored）。独立红队：2 个确认缺陷已修，绕过矩阵其余全挡住。

## 确认缺陷（已修，scope 内）

### D1 — root_path 部署下整个 mutating 闸被绕过（真实 bypass）

starlette `request.url.path` = `scope["path"]` 含 `root_path`；路由器走 `get_route_path(scope)` 剥掉它。`--root-path /tex`（反代子路径）下 POST `/tex/api/...`：`startswith("/api")` 为 False → 匿名 401、Sec-Fetch-Site/Origin 跨站闸、`Cache-Control: no-store` 三样全跳过，路由却照样命中。实证（probe5）：server 形态匿名 POST translate → **202**（应 401）、匿名 DELETE 达端点、cross-site keyed → 未拦、local 形态 evil-Origin mutation 全 202、`/tex/api/*` 无 no-store。

修复：`get_route_path(request.scope)`（路由同视图）替换 `request.url.path`——app.py:503（gate）+ app.py:526（no_store）+ import app.py:36；docstring 记档 app.py:490。修复后实证：匿名→401、cross-site→403、keyed→202、no-store 恢复。

回归：tests/test_server_gate.py `TestRootPathGate`（test_server_gate.py:296，server/local 两例）。

### D2 — upload 净化名 >255B → write_bytes 抛 ENAMETOOLONG 成 500

`..`/`...`/NFKC-folded 点全被净化闸挡住，但 256B+ 名漏到建目录。修：建行前 `len(safe) > _FILENAME_MAX` → 400——app.py:984 + 常量 app.py:173。回归：`test_overlong_name_400_not_500`（test_server_gate.py:389，256B/300B→400、255B 恰界仍收）。

## 绕过尝试矩阵（tried → blocked）

- **Host**：大小写/尾点/userinfo/双端口/`[::1]junk`/裸 `::1`/X-Forwarded-Host → 全拒或忽略；`Host: ""` 跳过闸（非浏览器可达，INFO）。
- **Origin**：null/缺 scheme/前导空格/`#frag`/`?q`/userinfo/大小写/重复头（first-wins，两序皆验）→ 仅 netloc 全等才放行。
- **Sec-Fetch-Site**：same-origin/same-site/none/cross-site + 大小写 + 重复 → 精确值判定正确。
- **Content-Type**：尾参/大小写/multipart 变体/缺 CT 带 body/重复 CT/boundary 残缺 → 415/400 正确。
- **方法/路径**：HEAD/OPTIONS/GET+body/method-override 头、裸 `/api`、`/apix`、`/api/../` → 边界正确。
- **resolve_auth**：空/多/空白 `X-Texlate-Key`（first-wins；空白 key=独立桶，自洽）、anon 读→写、`tenant_for("")` 隔离 → 一致。
- **upload 名**：`.` `..` `...` 全空白 NFKC-folded 点 NUL `\` 分隔 → 净化后惰性安全；`..`→400 无孤儿目录。
- **share import**：_ARTIFACT_MAX(64)/_INFLATED_MAX(300MB)/_MEMBER_MAX(256MB) 全部 ±1 边界、manifest 声明 vs 实际不符、+1 截断读、key_parts 边（v1000/无 v/内嵌 `|`/traversal arxiv_id）→ 全拒正确；manifest ≤1MB bounded 读无绕。

## INFO 观察（非缺陷，不修）

- `X-Texlate-Key: " "` 被当合法独立租户——自洽隔离，strip 反而可能撞桶。
- `pipeline_ver` 收 `\n`（存 options_json 惰性，不进日志/key 导出面）。
- `/api/share/import` 在事件循环同步 unpack（上限 300MB 有界，DoS 面小）。
- local 形态 `X-Texlate-Base-Url` 可洗 settings key——同机信任面内 moot；server 形态不受影响。

## 自验

ruff check + format 净（app.py、test_server_gate.py）；`pytest -k "gate or server or share or app or byok"` 648 passed / 2 skipped（extra 未装守卫）。leader 复核：202 passed，ruff 净。
