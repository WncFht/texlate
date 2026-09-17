# mechanism 标签驱动子集选样 —— 方案评估（texlate-2f，2026-09-17）

> 目标能力：「改了机制 X 的代码/规则 → 跑覆盖 X 的文件子集」接进 stagerun
> 选样面。**方案不修码**，本档给接法推荐 + 改动面清单。

## 1. 现状盘点

### 标签资产（两份，粒度不同）

| 文件 | 粒度 | 量 | 内容 |
|---|---|---|---|
| `bench/corpus_v3/mechanisms.jsonl` | **机制注册表** | 144 条 | mech_id（B##/T##/W## 等族）+ title + kind（found-in-wild 109 / known-trap 34 / suspected 1）+ status（covered 25 / partial 119）+ detection（regex ~65 / feature ~15 / manual ~29 / 混合）+ **examples**（提名 id 表，全表合计 309 id，13 条空）+ evidence（检测规则文本）+ quota |
| `bench/corpus_v3/booster_selection.jsonl` | **逐文件标签** | 200 行 | id + **mech_tags**（多标签，119 distinct：W 族 103 / T 9 / B 7）+ justification + evidence（staging file:line）+ verified（195 true / 5 feature）+ pick_reason（quota:Bxx） |

**覆盖面现实**：逐文件 mech_tags 只有 booster 层 200 格（标签密、verified 高、
多标签常态化）；core/hot/expand 三层**没有逐文件标签**，只能靠
mechanisms.jsonl 的 examples 薄提名（309 id 跨全层）。evidence 规则是
自然语言 regex/feature 描述，非可执行检测器——向未打标层扩覆盖需要
重写检测管线（features.jsonl 在 bench/work_v3 staging 侧未沉淀）。

### stagerun 选样面（stagerun_lib.py:46 `select_ids`）

- `--ids` 显式集（不要求 manifest 成员，`want - have` 也放行）；
- `--n` → `benchlib.pick_sample`（entries ∩ extracted 均匀抽，`rng.sample`
  seed 定序、**无分层无标签感**）；`--only` 子串过滤；默认全 extracted。
- 下游一切按 id 集驱动——**id 集即接口**，选样器本身不需要知道机制。

### 与 records sig 的对应

records 的 `sig` 是运行期诊断签名（missing_file:aastex.cls 等），mech_tags
是语料结构归因标签——**不同本体，不直接 join**；桥是「规则修复 ↔ 机制
覆盖」的声明映射（§3）。

## 2. 接法形态

### 主推：外部 join 产 id 文件，喂现有 --ids（零侵入）

小工具（`bench/py/mech_ids.py`，新文件 ~80 行）：

```
uv run python bench/py/mech_ids.py --mech B01,W45,W76 [--examples-union] \
    [--plus-random N --seed 42] > /tmp/mech-ids.txt
uv run python bench/py/stagerun.py fixloop --dir <run> --rerun --ids $(paste -sd, /tmp/mech-ids.txt)
```

- 查 booster_selection.jsonl（mech_tags ∩ 查询非空）∪ mechanisms.jsonl
  对应条目的 examples → 排序去重 → 输出。
- `--plus-random N` 追加无标签随机对照片（pick_sample 同 seed 语义）——
  修复回归不只看目标机制格（稀疏覆盖层的盲面兜底）。
- **优点**：stagerun 零改动、波次在飞期间绝对安全；id 文件留痕可审计、
  可进 join.txt 口径；与 rerun-wave.sh 的 --ids-file 面直接拼合。

### 备选：`--mechanism <tag>` flag 进 select_ids

stagerun.py:110 加 flag → select_ids 里查标签表。**不推荐一期做**：
标签源是层级的（booster-only），flag 会暗示全层等覆盖，误导出
「跑了机制 X」的假安全感；且 stagerun 是共仓多 lane 热点文件，
选样面改动有撞车成本。等逐层标签补齐（若做）再升级成 flag 不迟——
外部工具的 id 文件输出届时可原样做 flag 的 lookup 后端。

## 3. 与 fixloop 波次的联动（rules.yaml ↔ 机制）

声明式映射提案（rules.yaml 只 append 纪律不变，**需 1d/peer1 认可**）：

```yaml
- id: glyphtounicode_shadow
  mechanisms: [W45, W93]        # 新字段，纯声明不参与匹配逻辑
  ...
```

- 波次落地时 `mech_ids.py --rule glyphtounicode_shadow` 直接导出该跑的
  id 集——「改了哪条规则就跑它声明的机制覆盖」闭环。
- 未声明机制的规则回退到 sig→id join（现有 rerun-wave.sh 路径），
  两路可并行产出取并集。
- 风险：mechanisms 字段是**文档性声明**，标签错配只会导致选样偏差
  不会炸跑——可接受；但要有 lint（mech_ids.py --validate 检查
  引用的 mech_id 都在注册表内）。

## 4. 坑与边界

- **稀疏覆盖**：booster 外三层无逐文件标签——examples 只有 309 id。
  机制 X 在 expand 层可能有大量未标文件：选样面诚实呈现「已标覆盖」，
  不虚构全层覆盖（报告口径注明 coverage=known）。
- **多标签文件**：并集语义天然去重（一文件覆盖 3 个改动机制只跑一遍）。
- **seed 可重现**：标签查集是纯函数（排序去重），无 RNG；--plus-random
  的随机片沿用 pick_sample(seed) 语义可复现。
- **verified=feature 的 5 行**：标签是检测推的未人工核——置信度口径
  在工具输出里单列（默认含，`--verified-only` 可剔）。
- **examples 跨层**：mechanisms.jsonl examples 含非 booster id——并集
  时不过滤层，id 不在 manifest 由 stagerun --ids 的宽口径接住。
- **status=partial 119 条机制**：quota 未满的机制其覆盖本来就是残的，
  选样命中少不代表回归面小——报告里把 quota/status 一并带出。

## 5. 改动面清单（若按主推实施）

| 文件 | 改动 |
|---|---|
| `bench/py/mech_ids.py`（新） | ~80 行：注册表+selection 表加载、tag∩查询、examples 并集、--plus-random、--rule 反查（读 rules.yaml mechanisms 字段）、--validate |
| `src/texlate/compile/fixloop/rules.yaml` | 逐规则可选 `mechanisms:` 字段（append-only 补记，不改动现有键） |
| `bench/py/rerun-wave.sh`（可选） | 加 `--mech` 入口直接调 mech_ids.py 产 ids |
| stagerun.py / stagerun_lib.py | **零改动**（主推方案的核心卖点） |

## 6. 一句话结论

**主推外部 join**（mech_ids.py 产 id 文件喂 --ids）：零侵入、可审计、
与 rerun-wave 面直接拼合；`--mechanism` flag 留作标签全层覆盖后的二期升级。
