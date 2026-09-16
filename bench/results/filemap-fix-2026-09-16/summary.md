# filemap 面三件修复留痕 (task #98, 2026-09-16)

范围: `src/texlate/compile/fixloop/` (engine.py / ctan.py / builtins.py / rules.yaml) + `tests/test_fixloop_filemap.py` (新) + `tests/test_fixloop_f1f2.py` (追加)。不动 `src/texlate/compile/engine.py` (别的 session 活动窗口)。

## 1. xelatex 的 filemap.overrides 盲区

### 根因

`engine.py::_wire_engine` 开头 `ctx.engine_name != "tectonic"` 即 return —— rules.yaml `filemap.overrides` (basename→TL 包手工映射, 显式 null=已知噪声短路) 只经 `CtanFetcher` 注入 tectonic 通路。xelatex 通路 (`XelatexEngine.install_file` → `self.filemap` → usertree/tlmgr 安装) 完全看不到映射, `binhex.tex→kastrup` 这类条目在 xelatex 下失效。

附带同根缺陷: `CtanFetcher(index=注入索引)` 时 `overrides` 只在惰性建索引分支被套入, bench 现场注入共享索引则静默丢失。

### 修法 (单点, 全通路生效)

- `engine.py` 新增 `_wire_filemap_overrides(eng, overrides, ctx)`: 实例遮蔽 `eng.filemap` —— basename 命中 overrides 先答 (str→`[v]`, 其他→`[]` 短路), 未中委派原查询。`_wire_engine` 在引擎分支判断之前调用, xelatex/tectonic 同享。
  - 次序保证: overrides → 既有查询。bench 两处 (`e2e_real_bench.py::pipe_fix_condition`, `stagerun.py::_fixloop_one`) 的既有 `eng.filemap = idx.query` 遮蔽发生在 `fixloop()` 之前, 包装自然组合在其外层; worker 的 `_RecEngine` 与 bench `_NoSandbox` 均 `__setattr__` 透传, 遮蔽落在真引擎实例上。
  - `install_file` 内部 `self.filemap` 调用解析到实例属性 → usertree/tlmgr 通路同口生效, 无需改 `compile/engine.py`。
  - 幂等: `overrides_wrapped` 标记防重入叠包; `eng.filemap` 不可写时降级为 advisory 不阻塞。
- `ctan.py::CtanFetcher.index` property: 每次访问都 `self._index.overrides.update(self.overrides)` —— 注入索引同样套映射 (幂等 update, 无额外开销)。

### 前后对照

| 场景 | 前 | 后 |
|---|---|---|
| xelatex 缺 `binhex.tex` | filemap 索引无 .tex → `no package provides`, overrides 不查 | overrides 先答 `kastrup` → tlmgr usermode 装包 |
| xelatex 噪声名 (null 条目) | 每轮 tlmgr/索引往返 | `[]` 短路 |
| bench `eng.filemap = idx.query` 现场 | overrides 够不到 | overrides 包在 idx.query 外层 |
| `CtanFetcher(index=...)` | overrides 静默丢 | 注入索引同样生效 |

## 2. INDEX_EXTS ↔ OVERLAY_EXTS 解耦 (.tex/.rtx)

### 根因

`ctan.py` `OVERLAY_EXTS = INDEX_EXTS - {".pfb"}` 把「可索引」与「可平铺」焊死: `.tex` 不进索引则 `binhex.tex`/`epsf.tex`/`tikzlibrary*.code.tex` 类缺名无法反查真包; 进索引则会被 `ctan_fetch` basename 平铺进 cwd —— 撞名遮蔽工程自身 `.tex` 源文件, 不可接受。

### 修法

- `INDEX_EXTS += .tex, .rtx`; 新增 `_RUNFILES_ONLY_EXTS = {.tex, .rtx}` —— `from_tlpdb` 只从 `runfiles` 段收录这两个后缀 (docfiles/srcfiles 的同名 .tex 量大且 kpsewhich 本就跑不到, 收录只喂噪声候选)。
- `OVERLAY_EXTS = INDEX_EXTS - {.pfb, .tex, .rtx}` —— 可索引不可平铺。
- 新增 `_overlay_gate(fname)` helper (顺带解 `ctan_fetch` C901 复杂度超限): `.tex/.rtx` 命中给专属 advisory "只索引不平铺 (撞名遮蔽风险); 修复走 usertree/tlmgr 通路", 其余非平铺后缀维持原 "不在 TeX 输入层" 口径。

### 前后对照

| 场景 | 前 | 后 |
|---|---|---|
| `binhex.tex` 反查 | 索引缺席 → 只能 overrides | runfiles 段收录 `kastrup` 可反查 |
| tectonic `ctan_fetch("x.tex")` | "不在 TeX 输入层" (误导) | "只索引不平铺" 明确指向 usertree 通路 |
| tar 包内 `.tex` 成员 flat 投放 | — (不索引够不到) | `_member_relpath` 按 OVERLAY_EXTS 拒落 |
| docfiles/srcfiles `.tex` | — | 不收录 (段限定) |

注意: 已有 `~/.texlate/cache/filemap.json` 是旧代索引 (无 .tex 条目) —— overrides 先拦截不受影响; 非 override 的 .tex 缺名反查需删缓存重建 (下次冷启动 ensure 自动重拉)。

## 3. cs_targeted_fix glue-残骸前缀拆分 (结论: 做)

### 证据

n100 undefined_cs 归因: 24/24 payload 是 splice/join 合并残骸 —— cs+后 token 粘连 (`\itemFSU` ← `\item` + 首词 `FSU`)。显式 cs_table 修了 24 条已知个案后, replay-baseline 仍零星冒新残骸 (`\rmPT`, hep-lat--0111009) —— 是有穷头表 × 开放残余的类别, 不是一次性清单, 通用规则成立。`@` 含名 (`\Hy@pdfmajorversion` ×5) 是包内私有 cs 版本偏斜, 不属此类, 明确排除。

### 设计 (FP 有界)

`builtins.py::_split_glued_cs` + `cs_targeted_fix` 表外 fallback (合成 `cs_map` 项走既有改写链):

- 头表 `_SPLIT_HEADS` 只收语料实证过的 11 个粘连头 (linebreak/item/nabla/Delta/hline/frac/par/dd/bf/it/rm); `in` 头前缀面太热 (int/indent/input/index 真宏云集) 留在显式表。
- 残余门: 大写起首 (语料主型: 首词首字母大写) 或 ≤4 字符 —— 挡住 `parbox`/`fraction` 类同前缀真宏的大部分。
- `_SPLIT_GUARD` 双保险: part/para/parbox/parskip/itemize/itemsep/ddot/ddots/fraction 显式不拆。
- `@` 含名不拆; 显式 cs_table 条目优先 (citep→usepackage 不会被 cite+p 拆)。
- 自限: 拆分结果 `head rest` 中 head 已是真宏, 改写经编译验证; 若新 payload 恰为裸头 (`\dd`) 无残余不拆 → 落 guess 终止, 不自旋。
- rules.yaml `cs_targeted_fix` 新增 `split_heads`/`split_guard` 参数位 (默认 None → 用内置表, 语料扩张时可覆盖不改码)。

### 前后对照

| payload | 前 | 后 |
|---|---|---|
| `rmPT` (表外新残骸) | not in table → guess | `{\rm PT mode}` 拆开编译验证 |
| `itemSIGMA`/`hlineABC` | 同上 | `\item SIGMA` / `\hline ABC` |
| `parbox`/`ddot`/`itemize` | guess | 仍 guess (guard, 不误拆) |
| `Hy@pdfmajorversion` | guess | 仍 guess (@ 私有 cs) |
| `citep` | usepackage natbib | 不变 (显式表优先) |

## 验证

- `uv run pytest tests/test_fixloop_filemap.py tests/test_fixloop_f1f2.py tests/test_fixloop_logparse.py -q` — 全绿 (9 新 + f1f2 追加 15 + logparse 回归)。
- `uv run pytest tests/ -q` — 1876 passed; 唯一 fail `test_xlat_prompts.py::test_env_judge_prompt_fewshot` (ENV_JUDGE_TEMPERATURE 0.01 vs 0.0) 属 xlat 侧在途改动, 非本单范围。
- `uv run ruff check` 触及文件全过 (select=ALL)。
- `load_ruleset()` 实载验证: `split_heads`/`split_guard`/overrides 段解析正常。
