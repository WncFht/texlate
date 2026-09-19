# 2026-09-19 select 弹层方案调研

## 背景与问题

web/ 现有 10 处原生 `<select>`（Settings 8、Home 1、Toolbar zoom 1）。弹层是浏览器 OS 级控件、不在 DOM 里——CSS 只能渗透 `font` 继承与 `color-scheme`。实测（Chromium/Linux，两主题截图 tmp/theme-audit/sel-open-*.png）：选中项是 Chrome 默认亮蓝底（亮色 #2e6de0 实底 / 暗色浅蓝），全站唯一蓝色元素；直角、无圆角阴影、无 checkmark。纯 CSS `option` 样式跨浏览器无解（`option:checked` 在 Chromium 弹层不生效，Firefox 仅部分）。

## 支持矩阵（2026-09-19 时点）

| 引擎 | `appearance: base-select` | 备注 |
|---|---|---|
| Chrome/Edge | 135+（2025-03 稳定） | Finch 实验已收尾转正 |
| Safari | 27（2026-09 随系统发布） | UA 默认含圆角/阴影/checkmark/暗色 |
| Firefox | 149+ 分支已落地，藏 `dom.select.customizable_select.enabled` | 2026-09-07 立 bug 2069977 拟 Nightly 默认开启，预计 Release 2027 Q1–Q2 |
| anchor positioning | Chrome 125+/Safari 26+/Firefox 147+ | 三引擎齐；Firefox 不支持 `position-try-order`，用 flip-* 配方 |

MDN/BCD 的"不支持"标注滞后于实装——有开发者实测 Firefox 150.0.1 开启 flag 后可用[^bcd-issue]。

## 三条候选路线评估

### A. `appearance: base-select` 渐进增强（推荐）

`select, ::picker(select) { appearance: base-select }` 后弹层进 top-layer 变 DOM 可样式化：`::picker(select)` 面板、`option` padding/hover/`:checked`、`::checkmark`、`::picker-icon`、`optgroup`、`select:open`、top-layer 动画、anchor 定位全开[^chrome-blog][^mdn]。不支持浏览器原样渲染原生弹层，零回退代价——`@supports (appearance: base-select)` 门内收全部皮肤。产物即终态：Firefox 转正后无需改动。代价：Firefox 用户在转正前仍见原生蓝（不差于现状）；mobile 端失去 OS 滚轮选择器（换一致体验，Settings 场景可接受）。注意 `multiple`/`size` 不支持、select 内禁放可交互元素[^chrome-rfc]。

### B. Kobalte Select（@kobalte/core）

SolidJS 标准答案：WAI-ARIA listbox 全套（typeahead/方向键/焦点管理/modal）、隐藏原生 select 做表单集成、Floating UI 定位参数齐全（flip/sameWidth/fitViewport）、分组/描述/错误文案/虚拟滚动[^kobalte]。维护活跃（0.13.14 @ 2026-09-07，2.0 alpha 在飞，MIT）。代价：依赖树 + 10 处调用点重写 + 皮肤自绘；平台转正后多一次"留依赖还是迁回原生"的决策——正是要避免的重复开发。且同 A 一样丢移动端 OS 选择器。

### C. 手搓 listbox（popover + anchor positioning）

仓库已有 `menuNav.ts` ARIA 菜单契约（roving/Home/End/Escape/外点收/ArrowDown 开）。补 listbox 变体即可复用，但 typeahead、`aria-activedescendant`、scroll-into-view、读屏通告都要自己写对——一次开发换来永久维护，与诉求相反。同样丢移动端 OS 选择器。

### 死路

- `josepharhar/customizable-select-polyfill`：Chromium 实现者本人的 2025-05 周末实验，1 star、无 license、停更，不可用[^polyfill]。
- 纯 CSS `option` 样式：跨浏览器无解[^so-option]。

## 决策：两段式

1. **控件选型修正**：≤4 项固定枚举改 Segmented（guidance 2、engine/targetLang/lang 3、dialect/concurrency ≤4–8）——恒可见信息不该藏进弹层；沿用主题切换同款组件。
2. **真·长列表打弹层**：provider/model/zoom 挂 `.tx-select`，`@supports (appearance: base-select)` 门内全皮肤：panel 用 `--panel`+`--line-strong`+圆角+`--shadow-pop`，option hover 用 `--paper-2`，`:checked` 用 `--cinnabar` 左条 + `::checkmark`，`::picker-icon` 换成设计内 chevron，定位回退用 `flip-block/flip-inline`（避 Firefox `position-try-order` 缺口）[^jake]。

预期工作量：CSS ~120 行单文件 + Settings/Home 控件替换，无新依赖、无 JS。

### 参考文献

[^chrome-blog]: Google. The <select> element can now be customized with CSS. Chrome for Developers 2025. [developer.chrome.com](https://developer.chrome.com/blog/a-customizable-select)
[^mdn]: MDN. Customizable select elements. [developer.mozilla.org](https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Forms/Customizable_select)
[^chrome-rfc]: Google. Request for developer feedback: customizable select. [developer.chrome.com](https://developer.chrome.com/blog/rfc-customizable-select)
[^webkit27]: WebKit. WebKit Features for Safari 27.0. [webkit.org](https://webkit.org/blog/18325/webkit-features-for-safari-27-0/)
[^wwdc26]: WebKit. News from WWDC26: WebKit in Safari 27 beta. [webkit.org](https://webkit.org/blog/17967/news-from-wwdc26-webkit-in-safari-27-beta/)
[^fx-base]: Mozilla. Bug 1974787 — appearance: base-select (Firefox 149, pref-gated). [bugzilla.mozilla.org](https://bugzilla.mozilla.org/show_bug.cgi?id=1974787)
[^fx-nightly]: Mozilla. Bug 2069977 — Enable base select in Nightly（2026-09-07 立案）. [bugzilla.mozilla.org](https://bugzilla.mozilla.org/show_bug.cgi?id=2069977)
[^fx-anchor]: Mozilla. Bug 1988225 — Anchor positioning enabled by default（Firefox 147）. [bugzilla.mozilla.org](https://bugzilla.mozilla.org/show_bug.cgi?id=1988225)
[^bcd-issue]: mdn/browser-compat-data issue 29593 — Firefox 150.0.1 flag-on 实测兼容. [github.com](https://github.com/mdn/browser-compat-data/issues/29593)
[^jake]: Jake Archibald. The Goldilocks customizable select height 2026. [jakearchibald.com](https://jakearchibald.com/2026/goldilocks-select-height/)
[^kobalte]: Kobalte. Select component docs. [kobalte.dev](https://kobalte.dev/docs/core/components/select)
[^polyfill]: josepharhar/customizable-select-polyfill. [github.com](https://github.com/josepharhar/customizable-select-polyfill)
[^so-option]: Stack Overflow. How to style the <option> with only CSS. [stackoverflow.com](https://stackoverflow.com/questions/8430279/how-to-style-the-option-with-only-css)
