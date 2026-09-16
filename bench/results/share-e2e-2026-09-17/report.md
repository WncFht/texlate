# share-e2e — share 闭环真实端到端冒烟（45/45 PASS）

> 2026-09-17 收口。验证型零代码改动。基线 `pytest tests/test_share*.py` 116/116 绿；自建 `tmp/share-e2e/share_e2e.py`（双 TestClient 独立 data_dir+SourceCache 同 FakeFetcher，共享 MockTranslator 实例数调用增量断言零 token + sqlite 只读直查取证）——**45/45 pass，无 crash 无 500**。

## 矩阵（全 PASS）

- **A 产包**：真 arxiv done → `POST share/pack` 200 `{share_key,url,bytes}`；bundle+index.jsonl 同落；幂等重打不加行；404/409 守卫确定性复现。
- **B 字节级**：unpack 回验 manifest/key_parts/share_key 全符+三产物字节==+sha256 对账；`../evil.txt` zip-slip 免疫静默忽略；组分不符/缺产物 ShareError。
- **C 隐式命中（核心）**：share dir 整拷模拟托管同步→消费端同 id+model→done+**mock.calls 增量 0+tokens=0**+kind 仍 arxiv+产物五件套+dual 全块有 zh+`options.share` 审计载荷+`reuse_hit=share:{key}` 落库+拒自包 422+chunks 全 ok。
- **D partial 包**（无 zh.pdf）：manifest 两件→隐式命中照常零 token，zh.pdf 本地重编。
- **E 错误面**：corrupt/行在包不在/index url 含 `../`（last-wins 生效）/format 篡改/key_parts 篡改/异 model miss/对账零命中摘标记→全优雅回退自译；部分对账→1 ok+1 share_miss+1 fallback→partial 零 token+`error.share={matched:1,dropped:1,missed:1,extra:0}` 可直读。
- **F import**：合法包 kind=share 全链零 token+dual 回灌+拒自包 422；非 zip/format 不符/缺 dual→400 share_invalid；零命中→partial+reject_at=share_verify（显式不回退，与隐式不对称是刻意的）。
- **G 库层**：`|` 组分拒绝、version `3==v3` 归一、末位 pipeline_ver 许 `|`、index 缺席→None。
- **H 完成钩**：`options.share_pack=true`→done 自动产包落 index→拷贝→隐式命中零 token（钩→index→命中全环闭合）。
- **追加探针**：伪造 `options.share`/`reuse_hit`→`_clean_task_options` 摘除、无伪标记落库、事后可自包——审计载荷不可伪造。

## 发现（非阻断）

1. [低·设计] index_lookup 任一 malformed 行 raise → catch 归 miss——**一行坏 JSON 毒死全索引**（坏行在场期间所有合法键查不到，修行即恢复）。本地单写者影响小；index 若汇聚多源=单点全停，spec 值得留一句。
2. [低·测试] `share_dir()` 读 `TEXLATE_SHARE_DIR` env——conftest `_ENV_KEYS` 未含。**已被 test-hygiene 在飞的 TEXLATE_ 前缀扫描覆盖**，无需补。
3. [信息] 复跑注意：脚本自清工作区用子目录（初版 rmtree 自身目录已修）。

## 结论

share 闭环（完成钩产包→index→隐式命中零 token / import 显式消费 / 错误面全降级）**真实可用，与宣称一致**。现场 `tmp/share-e2e/`（可重跑）。
