# selfimp skeleton — 假设/想法储备池

> 每轮 Phase C 车道假设从这里取；rejected 假设留档防重复派。新条目必须本机验证过（有证据指针），上游搬运要标出处。状态：`open` / `adopted` / `rejected:<原因>` / `blocked:<依赖>`。

## open

- `C5-batch-amortize`：BATCH_MAX_CHARS 2000→~8000ch，prompt 摊销 68%→<40%。证据：xlatbench cost-model（review-2026-09-18 §3）。blocked:A1 计时落盘后裁决。
- `M8-lowscore-rexlat`：judge<3 chunk 换 swe-2-high 重翻闭环。blocked:A2 基线。
- `prose-recall-opaque`：`_handle_unknown_cs`/`_handle_argspec_cs` `[[CMD]]` 探针臂同型蒸发散文参（1803.00127 实证）；复用 `_opaque_arg_prose` 判据。注意 args.py 冻结窗（37 遗产核实）。
- `missing-file-x23`：first_error 大头 missing_file×23 → vendor/stubs 扩面或 tlmgr usertree 热包预装。
- `loader-withoptions`：RequirePackageWithOptions/LoadClassWithOptions 召回缺口（w2 裁决：刻意子集外真缺口，wave-3 项）。
- `passoptions-class-misfile`：PassOptionsToClass 类名误入 packages 集（normalize .sty 探测恒 miss，预先存在缺口）。
- `stale-stub-shadowing`：fixloop precheck「文件已在」跳过重投 → 旧 noop stub 遮蔽新真 stub（1907.03745 实证，37 移交）。修法=注入件指纹+precheck 比对。
- `en-residue-rexlat-redline`：EN 残留率 >X% 进 L2 重翻红线（repair_l2.py，untranslated_spans 主因缩写/专名，en_residue 免费信号）。

## rejected（留档防重派）

- M1 公共缓存 registry — 2026-09-18 用户裁决否决。
- Electron 客户端 — 同上否决。
- 横向扩库 →10k/50k — review-2026-09-18 §4：边际已塌，只定点扩盲区。
- parse_tex_v1(None) 严格化对齐 v2 — w2 结案：保持不对称各有据。
- LOADER 词表逐字节全并 — w2 裁决：各站刻意子集，真缺口只有 *WithOptions 两站（见 open）。

## blocked（等依赖）

- C5/C6 见上。qualbench judge 协议面改动 → texlate-80 车道，本池只提需求单。
