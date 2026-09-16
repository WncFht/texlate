# share-live2 — share 完成钩真链 live 冒烟（mock translator，零网关）

> 2026-09-16。对象：`746e87f` 的 `_maybe_share_pack`/`_share_pack_try`。HTTP→queue→worker→_stage_compile 全真路径，三臂全 PASS。证据：server.log、3 份 submit 响应、index.jsonl、pack-manifest.json、逐任务 events-*.json。

## 起法

```sh
TEXLATE_DATA_DIR=/tmp/share-live2-data TEXLATE_SHARE_DIR=/tmp/share-live2-share TEXLATE_TRANSLATOR=mock uv run texlate web --port 8797
```

预热 `/tmp/share-live2-data/src-cache/`（拷 cond-mat/0408438v1、0707.0110v1 既往缓存）→ AcquireStatus.HIT 零网络。

## 三臂判决

1. **upload_tex + opt-in** → done，设计内跳过实证：seq29 `share pack: 任务无 arxiv_id（不参与共享寻址），跳过打包`；share 目录保持空。
2. **arxiv + opt-in** → done；share 目录得 `e9467c99….share.zip`（276320 B）+ index.jsonl 恰 1 行。包 = manifest+zh-src.zip+zh.pdf+dual.json（done 全量包），worker 侧 `unpack_share` 回验过才落行。index key_parts：`arxiv_id="cond-mat/0408438"`（无版基名）+`version="v1"`（钉版）——normalize_arxiv_id 拆分符合预期；`url`=文件名相对形、`contributor`="c-9b4c…"（每包随机）。
3. **arxiv 无 option** → done；share 目录/index 零扰动，无 share-pack 日志行。

三任务 0 warning 事件；server.log 零 error/traceback/warning。

## 结论

钩行为与 test_share_hook.py 规格端到端一致。现场：`/tmp/share-live2-data/`、`/tmp/share-live2-share/` 留盘可查；:8797 已停。
