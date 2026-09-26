# 阅读主题配对调研：chrome 主题 × 纸面配色 业界做法

> **触发**：亮奶油顶栏 + 纯黑纸面脱配截图（用户实证）；顶栏 ◐+纸面 select 双控件并存。
> **方法**：4 路并行调研（电子书阅读器 / PDF 阅读器 / 网页阅读模式 / 设计规范），全部 web 源。
> **状态**：**已落地**——单控件驱动整面裁决已实装：chrome 主题 light/dark/onedark + 纸面 paper/dark/onedark 配对（`stores/settings.ts` paperTheme），旧 `texlate-theme=light` 迁移为 `paper`；PDF 侧经 Blender 图元级改色跟随（`reader/pdfTheme.ts`）
> **日期**：2026-09-22

## 一句话结论

**没有人把「应用主题」和「纸面配色」作为两个平级控件同时摆在阅读工具栏**——业界分两个家族：沉浸式阅读器单控件驱动整面（chrome+gutter 跟随纸面），桌面 PDF 工具双轴分裂（页面重着色藏 Accessibility 深设置）。texlate 是沉浸式学术阅读器（全局 nav 在阅读态隐藏），属于第一家族——双轴并存正是截图脱配的根源。

## 三条硬规则（跨家族共识）

1. **页边距/gutter = 纸面色，无一例外**（电子书家族铁律；桌面 PDF 工具里 gutter 跟 chrome 不跟纸面，sioyek 唯一暴露成第三配置面）。没人把暗纸框在亮框里。
2. **chrome 亮度 ≤ 内容亮度**——Apple HIG「chrome recedes, base 比 elevated 暗」、Fluent「darker = less important」。
3. **PDF 暗化永远归在「页面/阅读主题」轴**，不归 app 主题轴（Google Scholar 阅读器/ReadCube/Zotero/Edge 一致）。

## 电子书阅读器（immersive 家族）

| 产品                | 主题                                                                | chrome 行为                                                     | 控制面                        |
| ------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------- | ----------------------------- |
| Apple Books iOS16+  | Original/Quiet/Paper/Bold/Calm/Focus，**主题族锁死亮暗变体对**随 OS | Aa 菜单本身被主题染色；整屏含边距取主题色——脱配构造性不可能     | Aa → Themes & Settings，2 tap |
| Kindle app          | 白/Sepia/浅绿/黑                                                    | **双轴**：页色独立，chrome 跟系统深色——允许脱配（我们同款问题） | Aa 菜单，2 tap                |
| Kindle e-ink        | Dark Mode 一键反色                                                  | 整屏反色，单轴构造                                              | quick setting                 |
| Google Play Books   | Light/Sepia/Dark                                                    | chrome 跟系统+Material You 动态色；页色独立                     | Display options，2 tap        |
| KOReader            | 无预设，Night Mode=整帧缓冲反色                                     | 文档+UI 一起翻，单轴构造                                        | 菜单/手势；AutoWarmth 定时    |
| Moon+ Reader        | 10+ 主题，Day/Night 双 profile 全自定义                             | 阅读 toolbar 一键切 day/night；app UI 主题另设                  | 1 tap                         |
| 微信读书            | 白/护眼绿/纸皮黄/黑                                                 | 页边距沉浸=纸面；全局深色独立设置+跟随系统                      | 书内设置页 2-3 tap            |
| Kobo                | 设备 Dark Mode 整屏反色；app 有 Light/Sepia/Dark/Charcoal           | 设备单轴；app 页色独立                                          | 阅读菜单                      |
| Onyx Boox NeoReader | Style→Mode→Dark                                                     | 页级控制，系统 UI 无全局深色——无法脱配                          | 3 tap                         |

## PDF 阅读器（workspace 家族——双轴分裂派）

| 产品                | 页面重着色                                                                                                        | chrome/gutter                                                           | 控制面                                         |
| ------------------- | ----------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | ---------------------------------------------- |
| Acrobat             | Preferences>Accessibility>Replace Document Colors（预设+自选 bg/fg）                                              | Display Theme 另设；**gutter 跟 UI 主题不跟页色**                       | 两个不同深设置                                 |
| PDF Expert          | Day/Night/Sepia 预设                                                                                              | chrome 跟系统；gutter 跟系统                                            | 阅读内 view settings                           |
| Foxit               | 同 Acrobat（Accessibility 重着色）                                                                                | UI skin 另设                                                            | 深设置                                         |
| Xodo                | Color Modes=Day/Night/Sepia+色轮自选 bg/fg；另有 Invert Colors 可存全局                                           | chrome 另设                                                             | toolbar>View Mode / View tab                   |
| Edge PDF            | toolbar Page colors 下拉；高对比跟 OS 无障碍                                                                      | chrome 跟浏览器主题                                                     | 工具栏下拉（不埋）                             |
| Okular              | Invert/Recolor/B&W/Invert Luma sRGB（保色相亮度反）                                                               | **gutter=第三色**，UseCustomBackgroundColor 手动设                      | Configure>Accessibility                        |
| Evince/GNOME Papers | Night Mode 二元反色                                                                                               | chrome 跟 GTK；gutter 中性灰不动                                        | 窗口菜单                                       |
| sioyek              | toggle_dark_mode/custom_color；dark_mode_contrast 压白                                                            | gutter 每模式独立配置（background_color vs dark_mode_background_color） | 配置+键，无 GUI                                |
| Zotero 7            | 「Use Dark Mode for Content」反色 PDF（pdf.js pageColors，图 dim 不反）                                           | reader canvas 跟 reader 主题；app 主题跟 OS                             | **reader View 菜单内**，per-doc 逃生口         |
| macOS Preview       | 无页面重着色                                                                                                      | 全跟系统                                                                | —                                              |
| MuPDF               | I 反色；-B/-C 双色 tint（默认米色纸！）                                                                           | 无 chrome 概念；gutter 固定深灰                                         | 键/flag                                        |
| pdf.js stock        | viewerCssTheme(auto/light/dark) 与 forcePageColors 两条**完全独立** pref；pageColors 默认吃系统 Canvas/CanvasText | gutter 跟 chrome；暗 OS 默认=暗 chrome+白页=脱配出厂态                  | 构造期 pref，无运行时切换（要 rebuild viewer） |

## 网页阅读模式 / 稍后读 / 学术阅读器

- **浏览器阅读模式**（Firefox/Safari/Edge Immersive/Chrome Reading Mode）：一个控件（Aa/齿轮）刷满内容面，细条 toolbar 保持中性——靠最小化 chrome 而非配对规避脱配。Firefox 129 加了 Custom 自选三色（高级逃生口）。Auto 随 OS 成标配。
- **稍后读**（Pocket/Instapaper/Matter/Readwise Reader）：单外观控件驱动全应用（chrome+文档一起）。
- **学术阅读器**：Google Scholar PDF 阅读器暗化 PDF 画布本身（viewer 内 toggle）；ReadCube 有 Inverted Dark（chrome+页一起）；Semantic Reader/SciSpace/Distill/arXiv Vanity 不染 PDF；Hypothes.is 侧栏恒亮；ar5iv 亮/暗钮+随 OS。
- **唯一 per-document 持久化**：Google Docs Page color（存进文档本身）。

## 设计规范

- **Apple HIG**：「Dark Mode puts the focus on the content areas…surrounding chrome recedes」；base/elevated 双级，拟物内容（打印预览）可保亮而 chrome 转暗。
- **Fluent**：darker=recedes；双层（base 命令层 vs content 层）。
- **Material**：暗面推荐 #121212 非纯黑（elevation 靠白叠层，纯黑上读不出）。
- **纯黑 vs 深灰**：XDA 实测 AMOLED 省电差 <1% 可忽略；UX Movement 散光 halation 论证深灰更优；**但低视/OLED 用户确需纯黑——保留为选项不做默认**（我们的 `dark`=#17140f 本就是深灰，`black` 作选项，恰合）。
- **gutter=第三面**：sioyek 一等配置；惯例=至少与 chrome 同暗。
- **可访问性**：W3C 低视需求要全色谱自选 bg/fg（个体最优差异巨大）→ 色板而非二元；WCAG 文本 4.5:1。
- **控件惯例**：「Aa」是阅读设置主导 affordance；双轴按 scope 分（书内 Aa=页面色 / 系统级=app 外观）；阅读内 chrome 常随页主题。

## 裁决建议（据此）

1. **阅读器内单一外观控件**：撤 reader toolbar 的 ThemeToggle，纸面 select 升格为「外观/阅读主题」——选定即驱动整面（纸面+gutter+toolbar+卡片+译文 pane）。
2. **chrome 跟随纸面**：按色板 `{background,foreground}` 派生全套 token（--paper/--paper-2/--panel/--ink*/--line*/--shadow*/color-scheme）内联覆写在 `.reader` 根——脱配构造性不可能（Apple Books 模式）。
3. **`none`=逃生口**：原样透传页面+chrome 回退跟 app 主题（pdf.js/Zotero 经典组合：暗 chrome+白页仍可显式到达，但不再是默认陷阱）。
4. **`auto` 语义不变**：跟 app 主题成对（暗→暖黑对，亮→原色对）。
5. **控件形态 v1 保留 select**（同级于 Zotero appearance popup/Edge 下拉）；v2 可升 Aa 式色板浮层。
