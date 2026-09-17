# math--0408287 异常格追记（verdict=clean / status=partial 分歧）

**结论：数据缝，非判定缝。** wave roster 同时含 `math--0408287`[462] 与 `math/0408287`[465]——同一 paper 的双拼写 id，`benchlib.safe_id`（`/`→`--`）把两者映射到同一 wid `work/math--0408287/`；jobs=8 下两格并发，一方 `--rerun` 的 `rmtree(splice)+copytree(zh→splice)` 窗口（elsart.cls 暂缺）正好罩住另一方 post 复判 → 记录 `missing_file:elsart.cls`，pdf_bytes=74332 与降级 `.fixloop-entry.pdf` 同字节即此瞬态快照；盘上终态（elsart.cls 在位、main.pdf=74162 clean）为后写完方所留。fixloop/post 逻辑本身无 bug。

**波及面：** 本波 492 id 中 14 对 wid 撞名（astro-ph×7、hep-ex/hep-ph×3、hep-th、math、nucl-th）；唯 math 对出 status 分裂，nucl-th 对 fixloop verdict 分歧（`unfixable:env_undefined` vs `clean`）疑同染；其余靠双格内容同源、写近幂等而未显形——属侥幸非安全。

**修不修：要修，但不在 fixloop/post。** 属 stagerun 调度层：按 `safe_id` 归一去重或同 wid 串行即可；语料侧 `--`/`/` 双拼写 entry 亦值得登记去重（同 paper 占两格）。
