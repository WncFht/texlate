# macOS/iOS Look Up 与选区交互范式——来源清单与公约提炼

> **结论**：选区锚定 UX 的平台范式参照系——调用冗余（手势 + 键盘 + 菜单同达一卡）、点选 + 选区双粒度、内容自适应结果（单词→词典、多词→知识/web）、卡片解剖（短答+more+Open in Dictionary+ 底部类别条+Search Web 逃逸）、数据探测器免选区车道、web 覆盖缺口（Firefox/Electron/canvas PDF 无系统 Look Up、iOS callout 不可扩展）=自研必要性依据。
>
> **状态**：时点证据（2026-09-22 口径）——注记：sel-translate lane 已于 2026-09-23 裁决砍掉；sel-system（选区→命令→菜单/浮条/键位）已落地，本清单是其范式参照之一
> **日期**：2026-09-22

Lane 定位：texlate 阅读器选区锚定 UX 的平台范式参照。

## 主要来源（Apple 官方）

- Apple Mac 使用手册「Look Up」[^apple-lookup-mac]——Mac 上 Look Up：Control-click → “Look Up”菜单项；三指轻点；force click；弹层解剖（短释义 + “more” + Open in Dictionary + Configure Dictionaries + 底部类别条 + 左右轻扫切换）；Siri Suggestions 行内实体提示（描边/链接化条目，点箭头 → Look Up 窗）。
- Apple 支持「Force Touch 手势表」[^apple-force-touch]——“Look up” = force click 文本 或 三指轻点 或 Control-click → Look Up；“Data detection” = force click 日期/地址/航班号/URL → 弹层预览，或悬停描边框 + 点箭头。
- Apple 支持「Mac 键盘快捷键」[^apple-kbd]——`Control-Command-D`：显示或隐藏所选词的释义。
- Apple HIG「Edit menus」[^apple-hig-menus]——编辑菜单：Copy/Select/Select All/Translate/Look Up；iOS 选区上/下方紧凑横条带指针箭头、chevron 展开为竖排；macOS 竖排右键菜单；系统项在前自定义项在后；不适用项置灰；调整位置避免遮挡内容。
- Apple Mac 使用手册「Translate」[^apple-translate-mac]——选中 → Control-click → “Translate [text]” → 带语言菜单的弹层；“Replace with Translation”（仅可编辑文本）。
- Apple 支持「Live Text」[^apple-live-text]——Live Text 菜单项（Copy、Select All、Look Up、Translate、Search Web、Share）；“If you tap Look Up and select just one word, a dictionary appears. If you select more than one word, Siri Suggested Websites and other resources appear.”
- Apple 支持「Writing Tools」[^apple-writing-tools]——Writing Tools（iOS 18.1+/macOS 15.1+）。
- WWDC24 session 10168[^wwdc24-writing-tools]——Writing Tools：iOS 出现在 Cut/Copy/Paste 旁 callout 条；macOS 进右键菜单 + Edit 菜单；原生 text view 选中文本上有悬停 affordance。
- UIKit `UIReferenceLibraryViewController`[^apple-uireflib]——纯词典模态；`dictionaryHasDefinition(forTerm:)` 闸；无 web 结果；用户选区优先走编辑菜单 Look Up。

## 次要来源

- iDownloadBlog Look Up 参考工具文[^idownloadblog-lookup]——Look Up 类别：Dictionary、Wikipedia、Siri Knowledge、Siri Suggested Websites、App Store；Spotlight-suggestions 设置闸控制 web 结果。
- How-To Geek iOS 10 Look Up 文[^howtogeek-ios-lookup]——iOS Look Up：半透明覆盖层，先词典后 iTunes/Wikipedia/web/视频结果；底部“Search Web” → Safari 标签页；结果驻留至“Done”；首用一次性“Continue”披露。
- WebNots iPhone 词典文[^webnots-ios-dict]——iOS“Define”vs“Look Up”怪癖；Manage Dictionaries；扩展选区可词组查询。
- AppleInsider Dictionary 文[^appleinsider-dict]——右键菜单标签是 `Look Up "word"`；默认源 New Oxford American、Writer's Thesaurus、Apple Dictionary、Wikipedia；源顺序决定 Look Up 优先级；应用覆盖右键处失效（Google Docs）。
- Apple Discussions ⌃⌘D 帖[^apple-disc-cmdd]——悬停 URL 上 ⌃⌘D → data-detector 选中整个实体 + 预览；“Look Up only looks up one word at a time”是设计如此。
- Leafy「Look Up word on Mac」[^leafyapp-lookup]——⌃⌘D 需原生 text view；Electron/web 技术应用与浏览器内 PDF 阅读器里缺席。
- Apple Discussions 三指轻点帖[^apple-disc-tap] + Super User 问答[^superuser-lookup-browsers]——三指轻点/右键菜单 Look Up 在 Safari 与 Chrome 均可用，Firefox 坏/缺席（bug 1212527 史）。
- contenteditable.realerror.com 移动选区工具条文档[^realerror-callout]——iOS Safari callout 是系统所有，web 不可扩展；`-webkit-touch-callout:none` 只能抑制；触屏上注意把手过小/重叠问题。
- MacSales macOS Monterey 翻译文[^macsales-translate]——macOS Monterey 系统翻译：右键 → Translate → 弹层带 copy/replace。
- glimpsetranslate（第三方克隆）[^glimpsetranslate]——用 `NSPanel .nonactivatingPanel`（永不抢焦、选区保持）、Esc/点外关闭、Services 菜单 + 全局热键双调用。

## Key conventions extracted（落地参照公约）

1. Invocation redundancy: gesture + keyboard + menu all reach the same popover.
2. Dual granularity: selection-driven (menu) AND point-driven (⌃⌘D/tap on hovered word, no selection needed).
3. Content-adaptive result: single word → dictionary; multiword → knowledge/web categories.
4. Card anatomy: short answer + "more" + "Open in Dictionary" deep link + source config + bottom category strip + "Search Web" escape.
5. Data detectors = implicit lane: system-detected entities get outline/arrow affordance, click → popover, no selection required.
6. Menu ordering: system items first (Copy/Select/Select All), Translate/Look Up after, custom last; dim inapplicable; iOS horizontal compact bar w/ pointer arrow + chevron overflow; macOS vertical.
7. Read-only vs editable divergence: no Cut/Paste/Replace in read-only; Replace-with-Translation only when editable.
8. iOS Look Up sheet persists until "Done"; first-run disclosure panel.
9. Services submenu = sanctioned third-party lane on macOS (app menu + context menu, keybindable).
10. Web coverage gap: system Look Up free only in Safari+Chrome on DOM text; absent Firefox, Electron, canvas PDF; iOS callout non-extensible (suppress-only).

### 参考文献

[^apple-lookup-mac]: Apple. Look up words on Mac（Mac 使用手册）. [support.apple.com/guide/mac-help/look-up-words-mchl3983326c/mac](https://support.apple.com/guide/mac-help/look-up-words-mchl3983326c/mac)

[^apple-force-touch]: Apple. Mac Force Touch 手势表。[support.apple.com/en-us/102309](https://support.apple.com/en-us/102309)

[^apple-kbd]: Apple. Mac keyboard shortcuts. [support.apple.com/en-us/102650](https://support.apple.com/en-us/102650)

[^apple-hig-menus]: Apple. Human Interface Guidelines: Edit menus. [developer.apple.com/design/human-interface-guidelines/edit-menus](https://developer.apple.com/design/human-interface-guidelines/edit-menus/)

[^apple-translate-mac]: Apple. Translate text on Mac（Mac 使用手册）. [support.apple.com/guide/mac-help/translate-text-on-mac-mchldd8b3c15/mac](https://support.apple.com/guide/mac-help/translate-text-on-mac-mchldd8b3c15/mac)

[^apple-live-text]: Apple. Use Live Text on iPhone/iPad（菜单项与 Look Up 粒度说明）. [support.apple.com/en-us/120004](https://support.apple.com/en-us/120004)

[^apple-writing-tools]: Apple. Writing Tools（iOS 18.1+/macOS 15.1+）. [support.apple.com/en-us/121582](https://support.apple.com/en-us/121582)

[^wwdc24-writing-tools]: Apple. WWDC24 Session 10168: Writing Tools. [developer.apple.com/videos/play/wwdc2024/10168](https://developer.apple.com/videos/play/wwdc2024/10168/)

[^apple-uireflib]: Apple. UIReferenceLibraryViewController（UIKit 文档）. [developer.apple.com/documentation/uikit/uireferencelibraryviewcontroller](https://developer.apple.com/documentation/uikit/uireferencelibraryviewcontroller)

[^idownloadblog-lookup]: iDownloadBlog. How to use Mac Look Up reference tool, 2019. [idownloadblog.com](https://www.idownloadblog.com/2019/11/20/mac-look-up-reference-tool/)

[^howtogeek-ios-lookup]: How-To Geek. How to use iOS 10's new Look Up feature. [howtogeek.com](https://www.howtogeek.com/271246/how-to-use-the-ios-10s-new-look-up-feature/)

[^webnots-ios-dict]: WebNots. How to use dictionary in iPhone. [webnots.com](https://www.webnots.com/how-to-use-dictionary-in-iphone/)

[^appleinsider-dict]: AppleInsider. How to use Apple's Dictionary app on its own and in Look Up. [appleinsider.com](https://appleinsider.com/inside/macos/tips/how-to-use-apples-dictionary-app-on-its-own-and-in-look-up)

[^apple-disc-cmdd]: Apple Discussions. ⌃⌘D 与 data-detector 行为帖。[discussions.apple.com/thread/250036919](https://discussions.apple.com/thread/250036919)

[^leafyapp-lookup]: Leafy. Look up word on Mac（原生 text view 依赖）. [leafyapp.uk](https://leafyapp.uk/look-up-word-on-mac)

[^apple-disc-tap]: Apple Discussions. 三指轻点/右键 Look Up 跨浏览器帖。[discussions.apple.com/thread/7658371](https://discussions.apple.com/thread/7658371)

[^superuser-lookup-browsers]: Super User. Look Up 在 Safari/Chrome 可用、Firefox 缺席（bug 1212527）. [superuser.com/questions/1138014](https://superuser.com/questions/1138014)

[^realerror-callout]: contenteditable.realerror.com. Mobile selection toolbar（iOS callout 系统所有不可扩展）. [contenteditable.realerror.com/docs/mobile-selection-toolbar](https://contenteditable.realerror.com/docs/mobile-selection-toolbar/)

[^macsales-translate]: MacSales/OWC. How to use the translation text feature in macOS Monterey. [eshop.macsales.com/blog/79302](https://eshop.macsales.com/blog/79302-how-to-use-the-translation-text-feature-in-macos-monterey/)

[^glimpsetranslate]: smrf1093. glimpsetranslate（NSPanel nonactivating 第三方克隆）. [github.com/smrf1093/glimpsetranslate](https://github.com/smrf1093/glimpsetranslate)
