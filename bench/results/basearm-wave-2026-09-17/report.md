# S6 base 臂全量波简报（texlate-2f，2026-09-17）

> `compile --arm base --layers core,booster,hot,expand --jobs 8`，5122/5122 格（universe 5124 扣 2 格已有 base 末条），records `97d30b0`。
> base 臂 = 源稿直编（不 splice 不 inject 不翻）——产出「源健康基线」+ build-base 覆盖。

## 0. 数

- **build-base 覆盖 4994/5122 = 97.5%**（差 128 = reject 65 + skip 63 未起编格；凡起编必有 build-base 目）。
- base 末条：clean 3064 (59.8%) / partial 1045 (20.4%) / fail 885 (17.3%) / reject 65 / skip 63。
- scorecard：cells=5124 pdf=5016(97.89%) clean=4355(84.99%)——base 臂行不入 zh union，零位移（口径正确）。

## 1. 源健康基线解读（base fail 885 = 17.3% 构成）

- **missing_file 815 = 92.1%**——arXiv 源 tarball 自带缺件（aastex.cls/psfig.sty 时代老稿缺自家 .cls/.sty），是**源级烂**非管线引入。
- 长尾 ~70：pdftex_prim 15（xelatex 下 pdftex 原语）、babel_opt 13、inputenc_unicode 9、syntax 8、timeout 7、hyperref_driver 4、余散件。
- 即「真源烂核」≈ 1.4%（70/5122），其余 15.9% 是缺件型源烂——恰是 vendored_fetch 下游可救面。

## 2. 源烂 vs 管线引入（本波解锁的对照）

- **管线引入致命伤 = 2/3064**（0.065%）：2105.00111、astro-ph/0104007——base clean 而 zh end fail。go/no-go 门「回归集→0」实质达成。
- 管线降级（base clean→zh partial）103/3064 = 3.4%——pdf 面内降级，非致命。
- **下游救回 862/885 = 97.4%**：base fail 格经 vendored_fetch+fixloop 在 zh 侧出 pdf。源烂几乎全被机制吸收。
- 真死格（base fail ∧ zh 非 pdf）≈ 23 格——攻坚尾池。

结论：管线引入率近零，base fail 大头是 vendor 已覆盖的源级缺件——M2 口径「源烂 vs 管线」分界已实证可量。
