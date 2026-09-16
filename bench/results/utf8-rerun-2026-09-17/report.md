# utf8 partial 全集复验（texlate-2f）

> 链：`compile --arm zh --rerun --ids <545>`（30 格抽样 → 515 格全集）+
> 残格解剖后 `parse → xlat(mock) → compile` 定点链 11 格。
> 时点：post-`0c4e4b8`（judge 红线 invalid_utf8 按产生者归因）+
> post-`673d8ce`（normalize 四臂：`_sanitize_ps_comments`/`_transcode_support_files` 等）。
> 口径：compile.jsonl 末条（arm=zh）+ fixloop.jsonl 末条（有则以 fixloop 为准）。

## 0. 结果

- **545/545 仍全出 pdf**（复验前全为 `warn:invalid_utf8` partial——本波是
  clean 口径增量，不动 union pdf）。
- **compile 末条 clean 387/545（71%）**——抽样 30→22 clean（73%）与全集一致；
  invalid_utf8 票 sig 从 545 → **残 5**（见 §2）。
- **end-state clean 373**（14 格 compile:clean 背 fixloop
  acceptable/best_effort 旧末条，scorecard 取 fixloop——仍计 pdf 不计 clean）。
- 残 partial 172 格全部倒到其他 sig（`errors>3`/undefined_cs/illegal_unit/
  syntax/other 等族面，非 utf8 属地），invalid_utf8 残仅 5 格且机理已解剖。

| 口径 | 前 | 后 |
|---|---|---|
| 545 格 compile:clean | 0 | 387 |
| 545 格 sig=warn:invalid_utf8 | 545 | 5 |
| 全集 clean（scorecard） | 2516 | **2905**（57.42%） |
| 全集 union pdf | 4526 | 4527（89.48%，差 **+27**） |

clean 增量拆分：本波 545 格池 0→373 end-state clean（+373）；全集
+389 中其余 +16 及 pdf +1 系共仓同期他线落地（records 共享文件，
非本波产出）。

## 1. 残 16 格解剖 → 11 格当场回收

全集复跑后仍有 16 格末条背 `warn:invalid_utf8`。逐格 log+字节级解剖：
全部命中在 `\includegraphics{*.eps}` 触发的 graphicx `%%BoundingBox`
逐行扫描——警告票面 "at line N" 是**主 .tex 的 includegraphics 行号**，
坏字节在 EPS 件内。

| 桶 | 格数 | 机理 | 处置 |
|---|---|---|---|
| zh 树过期（sanitize 臂未上过） | 11 | `%%For:`/`%%CreationDate:` 等**注释行** latin-1/Shift-JIS/GBK 字节；这些格 parse 于 sanitize 臂落地前，compile rerun 只 copytree(zh→splice) 不重 normalize | `parse --rerun → xlat mock --rerun → compile --rerun` 链已跑：**11/11 翻 clean** |
| atend-bbox 全扫 + 数据行坏字节 | 5 | `%%BoundingBox: (atend)` 强制全件扫描，坏字节在 `(...)` PS 字符串**数据行**（如 `(=8.2\xd710) show` 的 latin-1 `×`）——`_sanitize_ps_comments` 刻意不动（字节即语义，改写改变渲染字形） | §3 提案 P-E；当前属设计内残余 |

11 格回收清单：0707.4363 0806.2434 0806.3306 1206.0374 1206.5536
1608.02259 1608.07013 1803.00145 1803.00178 1803.09023 1907.10343。
（1608.07013 混合桶：头行 `%%BoundingBox: 20 20 592 303` 在 line 5 实值
→ 扫描早停，深层数据行坏字节本就读不到；warn 全由头注释行贡献，
sanitize 后即愈。）

5 格 atend 残余：2211.13055 2403.00138 hep-ph/0408170 hep-ph/0605095
hep-ph/9901226——全部 `%%BoundingBox: (atend)` + 数据行坏字节。

## 2. 复验记录

- 抽样 30 格 compile：22 clean / 8 partial（hyperref_driver×2、syntax、
  other、undefined_cs、missing-char-level cat=clean×4），0 invalid_utf8。
- 全集 515 格 compile：354 clean / 161 partial（多 record 格以末条计）。
- 11 格定点链：parse 11/11 ok（zh 重建后 eps 注释行坏字节=0，实测
  `_sanitize_ps_comments` 输出 diff 存在且 compile 时 zh 树已是净字节）；
  xlat mock 全 ok（source-drift 触发 chunk 重译，ph=0）；compile 11/11 clean。
- 5 格 atend 残余逐格复核：坏行全部 `(...) show` PS 字符串或非注释数据行，
  sanitize 设计内豁免。

## 3. 提案（normalize 臂扩展 → 1d，不直写）

**P-E atend BoundingBox 头注改写**：EPS 头 `%%BoundingBox: (atend)` 且
trailer 存实值 `%%BoundingBox: x y w h` 时，把头行改写为实值——
graphicx/xetex 扫描在头行命中即停，深层数据行坏字节不再入扫。
零语义差（bbox 数值同源搬运，trailer 原行保留无害）。回收本批 5 格 +
同形态潜伏池。落点：`_sanitize_ps_comments` 姊妹臂或同函数内二次 pass。
注意只改 `(atend)` 占位行——无 trailer 实值的件不可造值。

## 4. 过门算术

utf8 波性质 = **clean 口径机械增量**（545 格复验前已全出 pdf）：
clean 2516→2905（+389，其中本波 +373），超出预告 ~2870——差额系
§1 定点链 11 格（zh 树过期桶，复验中现剖现收）与口径修正。
union pdf 4527/5059=89.48%，距门 **+27**——缺口主力不变：
fixable-data ~18 + no_main_tex fixable-detect 12
（待 1d P-A/B/C 落地后定点复验）。
