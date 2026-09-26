# PDF 暗色渲染方案调研与实测：CSS filter / pdf.js pageColors / Zotero Blender

> **结论**：选 **Zotero Blender 同款图元级改色**（`web/src/reader/blender.ts` 独立实现），免 fork 接入走 `document.getPage` 实例补丁（`web/src/reader/pdfTheme.ts`）。CSS-filter 与 pdf.js pageColors 两条备选已实验否决；否决理由见 §4 效果矩阵与 ADR-0020。
> **状态**：**已落地**（Blender 图元改色 + getPage 实例补丁当日实装，ADR-0020；MutationObserver 驱动全页原位重渲）
> **日期**：2026-09-21

## 1. 问题与候选

阅读器暗色化不是 UI 换肤问题——PDF canvas 是绘制产物，`data-theme` 换 CSS token 动不了 canvas 里的像素。候选四条路线：

| 路线              | 机制                                                                       | 代表                              |
| ----------------- | -------------------------------------------------------------------------- | --------------------------------- |
| CSS filter        | 合成层 `invert + hue-rotate` 后处理                                        | Chrome 扩展 Dark Reader、旧实现   |
| pdf.js pageColors | 渲染后 SVG 滤镜 `feComponentTransfer` 离散重映射（fg→bg 六阶 ramp 双色调） | pdf.js ≥5.x 原生 `addHCMFilter`   |
| Blender           | 渲染期拦 `fillStyle/strokeStyle/fillText/drawImage` 逐图元改色（Lab 空间） | Zotero reader（pdf.js fork 内置） |
| 服务端重排        | 编译期注入配色                                                             | 不在候选（破坏产物钉版语义）      |

## 2. Zotero Blender 算法拆解

Zotero 的 pdf.js fork 在每个页面 ctx 实例上 `defineProperty` 拦 `fillStyle`/`strokeStyle` setter，并重写 `fillText`/`drawImage`（bundle 位置：`pdf-build/pdf.mjs` Blender@10570、Color@10369；主题表 `reader.js` DEFAULT_THEMES@30717）：

- **中性色**（chroma ≤ 10）：按亮度映射到 `background.range(foreground)`——Lab 空间 bg→fg 渐变函数，白→纸色、黑→墨色、灰线性插值。
- **彩色**（chroma > 10）：Lab 空间保 hue 角，chroma×1.2，亮度重定到 50–75 可读带（暗主题下）；亮主题原样透传。
- **文字局部感知**：`hasBackgrounds` 时 `fillText` 先 `getImageData` 读文字中心处画布实际像素；局部底色与全局 bg 偏差 ΔE>2.3 且对比不足时，从 {原色，bg, fg} 挑亮度差最大者——彩色高亮框上的字不糊。
- **drawImage 四路分类**（逐张判定）：
    - ≥75% 页面积 + 亮色图 + 暗主题 → invert 反色并 latch（扫描件整页反）；
    - 亮主题 + ≥90% 中性像素 → gradient 纸色化（白纸黑字扫描图直接融入纸色）；
    - ≤2 种 distinct 颜色 → replace（公式截图：近白→bg、近黑→fg）；
    - 其余（照片/彩图）→ `globalAlpha=0.8` 压暗保原色。
- **逃生口**：ctx 上置 `skipBlender` 即绕过（打印/截图路径用）。
- 主题切换 = 换色板 + `pageView.reset()` + `pdfViewer.update()` 原位重渲，非双缓冲。

主题模型是 {background, foreground, invertImages?} 槽位表，亮/暗/sepia 等并列——我们目前只用 dark 槽，light = null（原样透传，白底论文即本色）。

## 3. pdf.js 6.3 pageColors 机制（备选实测对象）

`pageColors: {background, foreground}` 渲染参数走 `addHCMFilter`：SVG `feComponentTransfer` 挂 256 项离散 sRGB→linear 解码表 → `feColorMatrix` 0.2126/0.7152/0.0722 灰度化 → 6 阶 fg→bg ramp。应用方式：`ctx.filter = url(#id)` + `ctx.drawImage(自身)` 的后处理 pass（`#drawFilter()`）。**本质是双色调**——灰度化后 chroma 信息全灭，彩色矢量/图片统一压进两色 ramp。

**pdfslick 4.0.2 bug**：`pageColors` 选项传给了 `PDFThumbnailViewer` 但从主 `viewerOptions` 里漏掉（`@pdfslick/core` index.js ~2555 行）——即缩略图吃得到、主视区吃不到，原生路线必须自行 patch 或绕开 pdfslick 直传 render 参数。

## 4. 实验：效果 × 性能矩阵

实验台 `tmp/pdf-theme-lab/`（playwright 驱动，4 PDF × 6 页 × 4 变体，`renderOnce` 口径，~1300×1700px 页）：

| 变体    | 机制                                                                   | 每页增量                                                              | 效果判定                                                                                          |
| ------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| none    | 基线渲染 12–18ms                                                       | —                                                                     | 白底原色                                                                                          |
| css     | `filter: invert(0.94) hue-rotate(180deg) sepia(0.18) brightness(0.96)` | **+0ms**（合成层免费）                                                | 彩色近似保 hue（hue-rotate 在 sRGB 是近似）；图片负片化不可接受；无分类能力                       |
| hcm     | pageColors → `addHCMFilter`                                            | **+1.2–2.9ms**/页（后处理 pass）                                      | 精确落色板但双色调：彩色全灭；pdfslick bug 需另修                                                 |
| hcmcss  | pageColors + 外圈 CSS filter 补                                        | +0ms 增量（复用 hcm pass）                                            | 同上，仍双色调                                                                                    |
| blender | 图元拦截 + Lab 改色 + 图像分类                                         | **10–63ms**/页（图片页 getImageData 回读尖峰：实测 21 次回读 = 39ms） | 中性色精确落板；彩色 Lab 保 hue；图像按类分治（照片保色/扫描件反色/公式图替换）；文字局部底色感知 |

主题切换耗时四管线同量级（~26ms ≈ 2 rAF）——切换成本在 reset+ 重渲调度，不在改色算法本身。

**效果排序**：blender > css ≈ hcmcss > hcm。blender 是唯一「彩色不丢、图片不毁、扫描件可纸化」的路线；代价是每页一次 ~10ms 级的 CPU 改色（图片密集页到 60ms 尖峰，一次性成本，缩放/滚动重渲摊销）。

## 5. 免 fork 接入的三个实证坑

1. **钩点**：`PDFPageProxy` 不从 pdf.min.mjs 导出 → 原型补丁不可行；`HTMLCanvasElement.getContext` 全局补丁会把 Blender 自身分析 canvas 与 pdf.js 内部 scratch canvas 也套住（递归 + ~330ms 冷启动膨胀）。正解是**实例级 `pdfPage.render` 补丁**；再升级为 **`document.getPage` 补丁**——viewer/缩略图/懒取页共享同一 PDFPageProxy 产线，根除「`_pages[i].pdfPage` 懒赋值晚于扫描时机」的时序洞（实测：`_pages` 就位时 `pdfPage` 字段尚空，view 级扫描全漏）。
2. **render 参数签名漂移**：pdf.js 6.x 主路是 `params.canvas`（元素，内部自取 `getContext("2d")`），`params.canvasContext` 为旧签名——拦 `canvasContext` 读空是首发事故根因；`canvas.getContext("2d")` 返回同一 ctx 实例，拿来即套。
3. **Color 实现两坑**（TS 重写时引入，均经实测定因）：
    - `new Color(labArray,"lab")` 后兜底 `_rgb ??= [0,0,0]` 无条件执行 → lab 色全部压黑（gradient 恒黑、整页漆黑的根因）——兜底必须只在字符串解析路径生效；
    - `rgb(r,g,b)` 三分量串 `parseRGBA` 读 `parts[3]` 得 NaN → `toHex` 拼出 `#RRGGBBNaN` 非法串被 canvas 静默忽略（fillStyle 保持默认黑）——alpha 缺省必须归一为 1。

## 6. 性能账与取舍

- 每页一次性 ~10ms（文本页）至 ~60ms（图片页回读尖峰）；`willReadFrequently` 无法经实例补丁预设到 viewer canvas（ctx 由 pdf.js 内部先建），接受 ≤2 次/页的回读成本。
- 相对 CSS-filter 的 +0ms 是多花的钱——买到的是彩色 Lab 保 hue（hue-rotate 的 sRGB 近似色偏不可比）、图像四路分治、文字局部对比自适应，以及未来 sepia/自定义主题槽的同构扩展位。
- 缩略图与主视区共享 `getPage` 补丁产线，零额外接线。

证据件：实验台 `tmp/pdf-theme-lab/`（lab.mjs/blender.mjs/patch_test*.mjs/shots/）；线上验证脚本 `web/scripts/blender_verify.mjs`（PASS 口径：亮基线 avg 245 → 暗 avg 29/91.7% 暗像素 → 回切复原 245，canvas `getImageData` 物理像素断言排除 CSS 假阳性）。Zotero bundle 解包留痕 `tmp/zotero-reader/`。
