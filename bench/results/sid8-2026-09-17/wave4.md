# wave-4 — vendored_fetch 机制 + mn2e doc-only 重定位

Commit: `7f1defd` (feat(fixloop): vendored_fetch action + doc-only usertree relocate)

## 机制件 (已提交)

- **rules.yaml `vendored_fetch` @ order 11.5**: `missing_file`+`payload_required`,
  `builtin_transform`, xelatex native / tectonic same, risk 低。序位 =
  install_file(10) CTAN 真包先 → 本规则 vendor 件 → legacy_pkg_shim(12) 内建
  shim 兜底。`Rule.order` 改 float 支持小数插位 (原 `int()` 会静默截断
  11.5→11 与 babel_lang_ldf_install 平级)。
- **builtins.py `vendored_fetch()`**: basename 查
  `src/texlate/compile/fixloop/vendor/{files,stubs}/` (files 真件优先于
  stubs), payload 相对径平铺 wdir (`sub/x.sty` → `wdir/sub/x.sty`),
  `..`/绝对/NUL 闸在 builtin 内, 未收件 → decline (自闸, 不耗条件原语)。
  `params.dir` 可覆盖件根 (测试 fixture 用)。
- **compile/engine.py `_relocate_doc_only`**: mn2e.cls 类缺口 —— mnras 包
  把 cls 归档在 `doc/latex/mnras/LEGACY/` (文档树不在 TEXINPUTS), tlmgr
  usermode 与 CTAN overlay=tree 都落同一位, probe 恒 miss。装后复核抽成
  `_post_install_verify`, 新增第三兜底: `home/doc` rglob basename 恰一命中
  → copy 进 `tex/latex/` → `ls-R` 在场则 mktexlsr → kpsewhich 复核。
  多命中歧义不猜 (decline)。

## 测试

`tests/test_fixloop_wave4_vendor.py` 12 pins 全绿: 规则注册/排序 (11.5 小数
位实证)、files>stubs 优先、相对径落位、穿越闸 6 形、decline; relocate
唯一命中搬迁/无 doc 树/多命中拒/复核 miss 报 False。
`test_fixloop_yamlish.py` 规则计数 68→69。fixloop+engine 全扫 509 passed。

## sub 交付

- **stub-smoke** (`bench/results/stubsmoke-2026-09-17/report.txt`): 21 件
  xelatex 最小档实测 —— 16 clean / 2 degraded (axodraw stub arity 与上游
  不符 1-pt 族+EBox 族; iopams host-bound 属正常) / **2 blocker**:
  imsart.cls `\aug` providecommand×newenvironment 自撞; iopart.cls 缺伴生
  `iopart1{0,2}.clo`。另 svglov3.clo `@`-cs 直 `\input` caveat (低危)、
  aastex62 依赖 revtex4-1 需目标环境在场 (备忘)。
- **citekey-verify** (`bench/results/citekeyverify-2026-09-17/report.txt`):
  wave-2 citekey_sanitize 11 格复核 —— 10/11 正确点火双侧重写+幂等;
  1404.0089 正确 no-op (亚型是 `\doi{..._7}` 非 cite key, scout 已标);
  1907.03795/2009.11106 复跑到 rc=0 出 PDF。

## 在飞

- **e8 验收 pair**: 修 imsart/iopart blocker + axodraw arity 重切 → 平移
  `cbucket-vendored-inventory/{files,stubs}/` → `src/.../fixloop/vendor/`。
  落地后我做端到端点火复核 + 统一 commit。
- 41 队尾两件已立 task: #53 taxonomy_cat 进 records; #54 rules.yaml
  `mechanisms:` 声明式字段 + schema validate (mech_ids.py 消费)。
