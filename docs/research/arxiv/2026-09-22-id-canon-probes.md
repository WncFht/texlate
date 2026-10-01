# canon 规范化实证：arxiv.org 301 实录、官方规则与 manifest 普查

> **结论**：canon 契约（`docs/spec/arxiv-id-canon.md`）的远端行为底座——arxiv.org 对旧形带 class、大写 archive、大写 `V` 一律 301 到去类小写形，新旧形 seq 位数跨时代互认；本仓 manifest 14,398 个 id 中 slash 旧形全为裸 `archive/NNNNNNN` 拼写（无 class 形），canon 剥 class+ 小写化后与存量落库形天然同键。
>
> **状态**：时点证据（2026-09-22 口径）
> **日期**：2026-09-22

## 1. arxiv.org 301/404 实录

ux-research 现场对 arxiv.org 的探针实录（判例 = canon 剥离序各步的远端依据）：

```
arxiv.org/abs/math.GT/0309136          301 → abs/math/0309136
arxiv.org/abs/q-bio.GN/0611042         301 → abs/q-bio/0611042
arxiv.org/abs/physics.atom-ph/9801001  301 → abs/physics/9801001
arxiv.org/abs/cond-mat.mes-hall/9701001 301 → abs/cond-mat/9701001
arxiv.org/abs/Hep-Th/9901001           301 → abs/hep-th/9901001
arxiv.org/abs/HEP-TH/9901001           301 → abs/hep-th/9901001
arxiv.org/abs/2301.00001V2             301 → abs/2301.00001v2
arxiv.org/abs/math.GT/0309136v2        301 → abs/math/0309136v2
arxiv.org/abs/0704.00001               301 → abs/0704.0001   (跨时代位数互认)
arxiv.org/abs/1501.0001                301 → abs/1501.00001
doi.org/10.48550/arXiv.2301.00001      302 → abs/2301.00001
doi.org/10.48550/arXiv.hep-th/9901001  302 → abs/hep-th/9901001
arxiv.org/abs/cs/0501001               200 ; abs/stat/0501001 404 (stat 无旧形)
```

要点：class 剥离（`math.GT`→`math`、`cond-mat.mes-hall`→`cond-mat`）与 archive 小写化由服务端 301 背书——canon 本地规范化与远端终态一致；`0704.00001`↔`0704.0001`、`1501.0001`↔`1501.00001` 互认说明 seq 位数不是身份成分，canon 不做按时代位数闸（收 superset）；`stat/0501001` 404 说明旧形窗闸有真实拒收面（stat 2004 年才建站，无旧形 id）。

## 2. 官方标识符规则

arXiv 官方标识符文档[^arxiv-id-help]口径：新形 `YYMM.NNNNN`（0704–1412 四位 seq、1501+ 五位、YY 07–99 可延至 06=2106）；旧形 `archive(.CLASS)?/YYMMNNN`（9107–0703，class 两位大写如 `math.GT`/`cs.SE`/`nlin.CD`；`cond-mat`/`physics` 的 class 仅元数据不进标识符——但服务端仍 301 收）；版本 `v`+≥1 位数字，无版本指最新版。

## 3. 本仓 manifest 普查

2026-09-22 时点本仓 manifest 14,398 个 id 的双形分布：

- slash 旧形 3,050 条**全为裸 `archive/NNNNNNN`**——无一条带 class 拼写（canon 剥 class 后与存量同键，不产生分裂面）。
- flat `--` 形 4 条（safe_id 存储拼写回流），含 `.bak-mock` 残尾 2 条——canon 刻意不洗此类残尾，留给 triage 当分裂信号暴露。

## 4. 取证 → 落地链路

- 参考实现与验收用例组：ux-research 现场 spike（`canon.py` 参考实现 + `canon_test.py`/`url_forms.py`/`norm_spike.py` 形态表与 44 对抗探针）→ 产品侧落 `arxiv/fetch.py::canon` 单源 + `tests/test_arxiv_canon.py`（30 形态表全收 + 对抗面必拒 + 幂等/壳不变式）+ `web/src/arxidcanon.ts::canonStrip` JS 镜像。
- 落地工单：misc-pack M2（`dev/projects/ux-impl-2026-09-22/` 包内实现文档）——canon 收编同时改了 dedup 键口径（`math.GT/0309136` 与 `math/0309136` 自此同 task/cache 键，存量异键不迁移）。
- scan 面单源化：`ARXIV_ID_FIND_RX` 同文件内导出（classful 容忍形 ∪ 新形），`bibexport.extract_ids` 已消费，bench 侧已知消费点待接线（spec §6 挂账）。

### 参考文献

[^arxiv-id-help]: arXiv. arXiv Identifier（官方标识符规则）. [info.arxiv.org/help/arxiv_identifier.html](https://info.arxiv.org/help/arxiv_identifier.html)
