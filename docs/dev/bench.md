# 运行与维护评测

评测契约见 [benchmark.md](../spec/benchmark.md)，存储、并发与付费保护见 [bench-trizone.md](../spec/bench-trizone.md)，语料口径见 [corpus.md](../spec/corpus.md) 与 `bench/corpus/MANIFEST.md`。

## 入口与环境

统一入口为 `bench/py/bench`。kernel 和纯 stdlib 动词可直接使用 `python3`；引用 `texlate.*` 的 spec 使用项目 uv 环境：

```sh
python3 bench/py/bench --help
uv run python bench/py/bench spec --help
uv run python bench/py/bench run --help
```

qualbench 的评审请求经 `TEXLATE_BASE_URL`/`TEXLATE_API_KEY` 指向网关，`TEXLATE_QUALBENCH_SLOTS` 调评审并发（默认 2）；聚合网关以裸模型名回显带 provider 前缀的请求时不算降级。

先查询目标 spec 的参数与 stage，再选择样本、seed、层和运行臂。`mock` 验证结构链，`real` 会调用实际模型；免费冒烟通过不构成付费调用授权。`bench plan` 用于审阅去重与执行计划，付费保护仍由内核裁决。

## 数据与解释

代码仓保存机制、manifest、提名集与陷阱；载荷位于 `TEXLATE_BENCH_ROOT`。ledger 是追加事件账，index 可由账本重建；runs 保存执行证据，vault 保存付费产物，lake 保存免费载荷。不要把付费字节当可重建缓存。

不同 stage 的终态不能互换。xlat 完成不保证完整中文 PDF，compile 成功不保证版面正确，fixloop 尝试率与救回率必须注明分母。质检分档见 [layoutqc.md](../spec/layoutqc.md)。

同一论文跨 variant 或世代可能是不同格。汇总应明确 id、版本、variant、stage 和历史取值方法；dedup 行是复用记录，不能重复计入真实执行次数。概率样本与定向补强不能直接混池估计总体。

## 回放与清理

先定位 run、格和错误签名，再在副本上复现。原文和译文基线分开，修复后记录受影响样本、负例与新旧检测器版本。只修改副本不能证明历史账本已回灌；报告要区分原始运行、补跑与离线重评。

瘦身和 prune 前先确认工件的再生成本、保留等级与 vault 覆盖。先核对目录归属和释放量，再执行精确目标操作；硬链接不按表面文件大小简单相加。历史 compile-fail splice 曾遮蔽后续修复，去重状态必须结合生产者与有效字节核验，见 [存储决策](../../.agents/notes/implemented/architecture/2026-09-21-评测账本与资产.md)。

`scripts/bench-backup.sh` 与配套 systemd 样例备份账本和元数据；vault 载荷不包含在这种最小 tar 中，需独立备份并核对恢复。迁移前备份与尚未导入的唯一付费产物不能参与普通轮转。

## 实验留痕

实验报告保留源码版本、样本清单、配置、测量方法、结果与限制。原始大载荷留在评测存储，仓内保留复算所需的轻量数据和生成源。最新已记录的端到端实验见 [端到端评测](../research/2026-10-16-端到端评测.md)，历史读数不能当当前 HEAD 的验收。
