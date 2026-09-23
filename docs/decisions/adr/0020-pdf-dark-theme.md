# ADR-0020 PDF 页面主题化：Zotero Blender 图元改色 + getPage 实例补丁（免 fork）

> **状态**：现行
> **日期**：2026-09-21（初次裁决）

## 上下文

阅读器暗色化要求 PDF canvas 里的**像素**跟随 `data-theme`——CSS token 换肤动不了绘制产物。四条候选路线经独立实验台实测对比（4 PDF × 6 页 × 4 管线）：CSS `invert+hue-rotate` 合成层滤镜（+0ms 但彩色近似、图片负片化）、pdf.js 原生 `pageColors`（SVG 双色调滤镜，+1.2–2.9ms/页但 chroma 全灭，且 pdfslick 4.0.2 有把 `pageColors` 漏出主 `viewerOptions` 的 bug）、Zotero 式 Blender 图元拦截（10–63ms/页但彩色保 hue、图像分类分治、文字局部底色感知）。用户裁决「不管短期做最好」→ 取长径方案。

## 裁决

- **Blender 独立实现**：`web/src/reader/blender.ts`——Zotero pdf.js fork 同款算法的 license-clean TS 重写（不 vendor 其 AGPL 代码，与 ADR-0001/0017 许可隔离同构）。中性色按亮度映 `--paper`→`--ink` Lab ramp；彩色（chroma>10）保 hue、chroma×1.2、亮度重定 50–75 带；`fillText` 局部底色感知（ΔE>2.3 时 {原色,bg,fg} 挑最大对比）；`drawImage` 四路分类（整页扫描件 invert/gradient、≤2 色图 replace、照片 0.8α overlay）；`ctx.skipBlender` 为逃生口。
- **免 fork 接入**：`web/src/reader/pdfTheme.ts`——不碰 pdf.js 原型也不全局补丁 `getContext`，在 `document.getPage` 实例级拦 `render()`（viewer/缩略图/懒取页共享同一 PDFPageProxy 产线，一处补丁全覆盖）；pdf.js 6.x `params.canvas`/`canvasContext` 双签名兼容取值。
- **主题管线**：`resolvedTheme` 信号 = `documentElement[data-theme]` 的 MutationObserver（applyTheme 落点即信号源，auto 档系统翻转同轨）；色板从 `--paper`/`--ink` computed 现取——palette 调参 PDF 侧自动跟随。切换 = `pageView.reset({keepTextLayer})` + `viewer.update()` 原位重渲 + 缩略图 `forceRendering` 排队；亮色槽为 null（原样透传），日后 sepia 只扩槽位表。
- **否决**：CSS-filter 路线（图片负片、彩色近似、无分类能力，降级为「其余方案全灭时的零成本兜底」存档于调研件）；pdf.js `pageColors`（双色调灭 chroma + pdfslick 丢参 bug 需另修，原生路线无工程优势）。

## 理由

- 效果矩阵里 Blender 是唯一同时满足「中性色精确落板、彩色 Lab 保 hue、图像不毁、扫描件可纸化、文字局部对比自适应」的路线——学术 PDF 的彩色引用链/图表/公式截图正是论文负载的高频面。
- 成本可控：每页一次性 ~10ms（文本页）至 ~60ms（图片页 getImageData 回读尖峰），缩放/滚动重渲摊销；主题切换 ~26ms 与各管线同量级（成本在 reset+重渲调度不在改色）。
- 免 fork 保住升级面：pdf.js/pdfslick 保持 unmodified 依赖，补丁只在实例方法上——fork 是把薄壳做成承重墙（同 ADR-0016 壳薄原则）。
- 证据：`docs/research/product/2026-09-21-pdf-dark-rendering.md`（算法拆解 + 性能矩阵 + 三个实证接入坑）；实验台 `tmp/pdf-theme-lab/`；验证脚本 `web/scripts/blender_verify.mjs`。

## 现状

实现落在 `web/src/reader/blender.ts`（改色器）+ `web/src/reader/pdfTheme.ts`（信号/补丁/重渲接线）+ `PdfPane.tsx`（`waitPages` 处 `patchPdfDocument` + view 补扫、主题 effect）+ `styles/pdfjs.css`（仅留 `--page-bg-color` 防 reset 间隙闪白）。实测口径：`blender_verify.mjs` PASS（亮 245 → 暗 29 物理像素，回切复原）。

## 追加裁决（2026-09-22）：色板即阅读主题——chrome 跟随纸面

**触发**：亮 app + 纯黑纸面实证脱配（奶油顶栏+页缝框住黑页）；顶栏 ◐（app 主题）与纸面 select 双控件并存。4 路生态调研（`docs/research/product/2026-09-22-reader-theme-pairing.md`，电子书/PDF 阅读器/网页阅读模式/设计规范）结论：沉浸式阅读器单控件驱动整面（Apple Books/微信读书/Readwise/KOReader），chrome 亮度 ≤ 内容亮度是 HIG/Fluent 明文，gutter 是第三面至少与 chrome 同暗（sioyek）；双轴分裂的只有桌面 PDF 工作区派（Acrobat/Okular/pdf.js），正是脱配产出来源。

**裁决**：

- **阅读器内单一外观控件**：撤 reader toolbar 的 ThemeToggle（全局 nav 那枚留管非阅读面），纸面 select 更名「外观」(`t.reader.appearance`)——色板选定即整面换色。
- **chrome 跟随纸面派生**：`pdfTheme.ts` `readerChromeVars()` 按色板 `{background,foreground}` 用 `color-mix` 派生 `--paper/--paper-2/--panel/--ink*/--line*/--ring` 内联覆写在 `.reader` 根（`applyReaderChrome`，Reader.tsx 根 effect——`currentPdfTheme` 的信号读即依赖，paperTheme 与系统翻转自动重放）。accent/阴影不派生，按色板 WCAG 亮度归类取 base.css 已校准的亮/暗套；`color-scheme` 同步。比例取自 base.css 实测反推（暗：paper-2≈4%fg、panel≈7%fg、line≈17%、line-strong≈26%、ink-2=70%fg、ink-3=57%fg；亮：paper-2≈5%fg、panel=80%白、line≈11%、line-strong≈21%、ink-2=66%、ink-3=56%）。
- **`none`=逃生口**：原色页面+chrome 回退跟 app 主题（不落覆写）——暗 chrome+白纸经典组合仍可显式到达，但不再是默认陷阱；`auto` 语义不变（跟 app 成对，暗档读 token 故 chrome≈app 暗套）。
- **`.reader { background: var(--paper) }`**——缝隙/亚像素漏底与纸面同源。

**理由**：色相同源派生使脱配构造性不可能（One Dark 得蓝灰 chrome、羊皮纸得暖奶油 chrome）；逃生口保留 pdf.js/Zotero 式「暗界面+白纸」显式可达性；控件面与 Apple Books Aa/Zotero appearance popup/Edge Page colors 同级（单控件在阅读器内）。

**验证**：`web/scripts/theme_verify.mjs` **9/9 PASS**——light-app+black 整面近黑、light-app+onedark 蓝灰、light-app+sepia 暖奶油、dark-app+none 精确落 app 暗 token（逃生口）、auto 两档、◐ 钮消失、外观 select 在位、零 console 错。

## 二次追加裁决（2026-09-22）：全面合并——色板轴吞并主题轴

**触发**：阅读器内配对落地后，「主题」（亮/暗/系统）与「外观」（8 档色板）双轴并存——同一应用两套配色心智，且阅读器内配对与阅读器外脱配并存。用户裁决「全面合并」：不做双配色，色板轴成为全站唯一外观轴。

**裁决**：

- **`texlate-theme` 轴整体退役**：`settingsStore.theme/setTheme/applyTheme/THEME_COLOR`、`darkQuery` 监听、Settings 页主题 Segmented、topnav ThemeToggle 组件（`ThemeToggle.tsx` 删除，`.theme-toggle` CSS 摘除）全部移除；localStorage 旧键迁移——无 `texlate-paper-theme` 时 `light→paper`（锁定暖纸=旧亮 chrome 原值）、`dark→dark`（锁定暖黑=旧暗对），`auto`/缺失→`auto`；index.html 预置脚本同口径。
- **`applyPaletteChrome(documentElement)` 是全站 chrome 唯一写者**（App 根 effect）：落 `data-theme` 明暗归类 + 色板派生 token 内联覆写 + `meta[name=theme-color]`；首绘由 index.html 预置先行（命名暗槽直暗、auto/none/未知听 OS），首次调用不挂过渡，之后键变才 `.theme-anim` 200ms。
- **信号源换代**：`resolvedTheme`（data-theme MutationObserver）退役，换 `osDark`（matchMedia change 监听）——`data-theme` 从「权威态」降级为 `chromeClass()` 的输出物；`currentPdfTheme`/`chromeClass` 两路信号读收敛为 paperTheme+osDark。
- **`chromeClass()` 明暗归类**：命名槽按自身纸面 WCAG 亮度（`relLum(bg)<0.5`→dark），auto/none 听 OS；命名槽锁定成对不听 OS（暗 OS + paper 槽 = 亮对）。
- **`baseTokensFor(cls)`**：auto-暗档取 base.css 暗 token 原值时，先同步「摘内联覆写→翻 data-theme→computed 读→还原」再缓存——否则命名槽覆写会被误读为 base（如 black→auto 串台读到 #000）；同 task 内无绘制无闪烁。
- **`none` 语义微调**：从「恒原色透传（chrome 跟 app 主题）」变为「原纸 + OS chrome」——逃生口职责不变（暗 OS 下白纸+暗界面仍显式可达），只是跟随对象从已删除的 theme 轴换成 OS。
- **UI 文案**：阅读器/设置两处同一「外观」控件（8 档）；`auto` 档文案「跟随主题」→「跟随系统」；设置页主题行删除。

**理由**：双轴是桌面 PDF 工作区派（Acrobat/Okular/pdf.js）的形态，恰好是上一轮脱配的产出来源；texlate 是沉浸式阅读器，单控件驱动整面（Apple Books/微信读书/Readwise/KOReader）才是同族心智。合并后「界面该有几种颜色」的答案变成「色板有几档就有几套」——8 档 = 8 套成对 {纸面,chrome}。

**验证**：`web/scripts/theme_verify.mjs` 重写（OS 走 playwright `colorScheme` context，色板经 `addInitScript` 首绘前预置）**15/15 PASS**——OS亮+auto 原纸亮 chrome、OS暗+auto 暖黑对、OS暗+none 逃生口、OS暗+paper 命名槽锁亮不听 OS、black/onedark/sepia 整面配对、旧键迁移双向、onedark 下非阅读页 topnav 蓝灰深（全局面同色实证）、设置页 8 档 select 在位且无亮暗 Segmented、topnav 无主题钮、零 console 错。
