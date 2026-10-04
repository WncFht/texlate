# TeXlate 主窗口字符串（zh-CN）。
# 由 hooks.ts 的 insertFTLIfNeeded 注入每个 Zotero 主窗口；
# MenuManager menuitem 的 l10nID 经窗口 DOM l10n 在此解析。
# 与 addon.ftl 保持一致，getString() 调用方可解析同名标签。
# 菜单标签必须用 .label 属性形式——裸 value 被 DOM l10n 落进
# textContent，XUL menu/menuitem 不渲染 textContent（label 恒空）。
# 同约定见 zotero.ftl 的 menu-* 消息。

menu =
    .label = TeXlate
translate =
    .label = TeXlate：翻译为中文
open-reader =
    .label = TeXlate：在阅读器打开

# 条目面板任务区——collapsible-section 头部走 .label，
# 侧轨 toolbarbutton 走 .tooltiptext（裸 value 都不渲染，同 menu 约定）。
taskpane =
    .label = TeXlate 任务
taskpane-sidenav =
    .tooltiptext = TeXlate 任务
