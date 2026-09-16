# recode-ext — normalize.py recode 扩面交付

> 2026-09-17 收口。落地 `8d120db`（normalize.py + test_compile_normalize.py，+150/-2）。自验 test_compile_normalize 73 绿、`-k "normalize or compile or engine or judge"` 338 passed/1 skipped、ruff 双净。

## 实证底账（与任务假设有出入）

- bundled `.sty/.cls/.def` recode **HEAD 已在位**：三者皆在 `TEX_SOURCE_SUFFIXES`（mask.py:19），主循环 `decode_tex_with`→写回 UTF-8 同口径。loop1 `warn:invalid_utf8` 真凶是**系统件**（`~/texmf` algorithm.sty `Rog\xe9rio`、algorithm2e.sty `Schr\xf6der`），已由 `_shadow_broken_system_packages` + engine `warnings_sys` 归因降级覆盖。
- `.eps` 数据行坏字节不被扫：xelatex 探针实锤 bbox 头行即停；`(atend)` 强全扫已由 `_resolve_atend_bbox` 覆盖。
- 真缺口：`.epsi`/`.epsf`/`.mps` 落 `_transcode_one` catch-all **整件文本转码**——数据行高字节被改写腐件（字节即语义破纪律），DOS-二进 .epsi 仅靠 NUL 闸侥幸兜住。corpus_v3 全量 48 件皆 `%!PS` 文本形态，2 件真实非 UTF-8 均在注释行。

## 修复清单

- `PS_GRAPHIC_SUFFIXES` `{.eps,.ps}` → `{.eps,.epsf,.epsi,.mps,.ps}`：三件归 PS 臂（注释行逐行净化 + `%%Begin*` 数据段保护 + atend 实值搬头 + DOS 魔数整件跳过），docstring 附 corpus 实证。
- 新台账 `dos_eps_skipped`；PS 分支 DOS 魔数早退落台账——原先静默早退零痕迹，现 worker 日志可见，残余警告由引擎 sys_warn 降级承接。

## 新测试（+6）

bundled sty/cls/def recode（真实字节形态）、recode 幂等、净 UTF-8 不动、`.epsi` 注释净化+数据行逐字节保留（钉死新旧分派分界）、`.epsf/.mps` 路由、DOS-.epsi 二进跳过落台账（fixture 刻意无 NUL，证明魔数闸独立兜住）。

## 未修（理由） / 外部路由

- `_transcode_one` NUL 闸不加严：「宁可多转」是文档化取舍，latin-1→UTF-8 无损；后缀表+NUL+DOS 魔数三层已兜明显二进。
- `.def/.clo/.fd` 系统件隐式加载不走 `\usepackage` 采集面：docstring 明示不追，warnings_sys 降级兜 judge 侧。
- **→fixloop scope**：`builtins.py` `_EPS_EXTS/_GRAPHIC_EXTS` 缺 `.epsi/.epsf`；`restore_support_from_src` 逐字节复原 baseline 时非 UTF-8 件坏字节回流（若扩到 sty/cls/def 应同口径 recode）；`dos_eps_skipped` 台账不通 judge——工程二进件残余警告仍计 `warnings_hit`，「降 notes」若要覆盖需 engine/judge 侧消费。

## 对 144 格的预期收益

直接救格 ≈0：loop1 354 条 warn:invalid_utf8 无一格带非 UTF-8 `.epsi` 族，bundled sty/cls/def 早已转码。本改动是**收口**而非救援：消 catch-all 误转码腐件风险类 + 2 件真实非 UTF-8 PS 变体归正道 + 可归因台账。invalid_utf8 桶实际剩余留 `--recode` 复判波后评估。
