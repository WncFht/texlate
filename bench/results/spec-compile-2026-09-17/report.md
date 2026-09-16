# spec-compile — docs/08 §3–§6 + docs/10 §B3 vs `src/texlate/compile/` 规格对账（只读）

> 2026-09-17。零代码改动。总评：**核心语义件全部实装且主参数合规格**；drift 集中在「post-spec 机制超前于文本」（upgrade_209/floor 底板/best_effort 打捞/跨引擎臂/warn 驱动修复）与「规格数字全面滞后」（实 52 规则/42 taxonomy/20 命名函数 vs 文本自称 36/37/3）。真「承诺但零物证」极少，无高危死链。

## 对账要点（⚠️ 项）

- §3.2/§3.3 兼容块注入点：impl 三兼容块插**文件顶**（`\PassOptionsToClass` 语义要求），规格「`\begin{document}` 前」过时。
- §3.3 `\documentstyle`：upgrade_209 转换器先行（inject.py:463），「禁止注入」只剩兜底。
- embed_cjk_mappings 实在 `server/worker.py:1017`（非 compile/inject）且 **e2e/cli 路径不调用**——bench/CLI 产 zh PDF 无 ToUnicode。
- target_probe 原形态（译文桩编译）未建；impl 静态声明扫描旁路——落地注记口径合规，正文「探针失败直接进 fixloop」死文。
- Engine caps 两套词表漂移：XelatexEngine.caps 含非 spec 词 `recorder`、缺 `shell_escape`；`cap_available` 原语已实现但 rules.yaml 零消费。
- xelatex `-halt-on-error`：消费方全传 False（刻意对齐 bench），spec 未追记。
- tectonic `-Z search-path` 被 `_TECTONIC_Z_OK` 安全面刻意封锁；`-Z continue-on-errors` 是加注。
- CJK 判据偏离：spec「Missing character==0 或 font table」→ impl pdftotext 字数 ≥20（更严、不同机制）。
- bwrap 实在 engine.py 三件套（注记写 sandbox.py 位置错）；`RouteDecision.reject` 恒 None 死字段（F3 后拒绝走 gate）。
- §5.2 spec 名 `pstricks_dvips_fallback` vs impl `pstricks_dvips_preflight`（gate/0 相位超前）。
- §6 表滞后：fixloop verdict 缺 `reject:<rid>`/`no_main_tex`/`max_rounds`；规则态缺 `validated`+缺席默认 active；记录态 `reject` 与 F3（partial+reject_at）自相矛盾（stagerun 裸 reject vs e2e/worker 两写法并存）。

## 未落地清单（按严重度，全部归 项目体验方式 裁）

1. **规则 status 生命周期零行为约束**（中）：21 条 proposed+3 条 validated 与 active 同序同效上场，回放门③只写 `status_suggested`；spec 入库门槛语义只剩 replay 工具自觉——要么加门要么删承诺。
2. **产品侧 fixloop 接件口径宽于 bench 校准**（中）：B5「onfail 只接 fail」+bench 已校 fail+misschar/error-partial；产品链 e2e.py:865/worker._compile_zh 对任意非 clean（含 warning 级 partial）进 fixloop——warn 驱动规则需要入口，但 partial→fail 回退只靠 floor_restored 兜底，口径未收敛。owner 决策项。
3. fixloop 单轮 120s vs spec/引擎 240s（低-中）。
4. `cap_available` 零消费（低）；5. `RouteDecision.reject` 死字段+worker/e2e 死检查（低）；6. embed_cjk_mappings e2e/cli 缺席（低）；7. 修复器 swe-2-medium vs spec swe-2-max（低，同 spec-xlat #8）；8. target_probe 原形态（备查）；9. shadow 模式缺席（合规不违规）。

## 勘误级（spec 文本滞后）

§5.1「37 patterns/36 rules/3 命名函数」→ 实 42/52/TRANSFORM_FNS 18+REWRITE_FNS 2；`compile/__init__.py` docstring「12 项」→ 13；docs/10 B5:120 onfail 口径；§3.4 探针死文。

## leader 备注

compile/ 归 项目体验方式、活面在飞——清单全部「改不改由 owner 定」。#1/#2 是唯二语义层决策项；#3/#7 一行修；#4/#5 死面清理；其余进 docs/08 追记。§6 表内自相矛盾（F3 两 reject 写法并存）值得顺手收口。
