# TeXlate 插件字符串（zh-CN）。
# 键名约定见 en-US/addon.ftl 头部注释：构建时 scaffold 为每个消息 id
# 加 `texlate-` 前缀。本文件是 getString() 唯一解析来源（initLocale
# 只加载 `texlate-addon.ftl`），故所有编程式字符串集中在此；
# 窗口声明式 l10n 在 mainWindow.ftl，设置面板在 preferences.ftl。

# 条目右键菜单标签——与 mainWindow.ftl 保持一致，getString() 亦可解析。
translate = TeXlate：翻译为中文
open-reader = TeXlate：在阅读器打开

# 设置面板名（Zotero 设置侧栏）与设置对话框标题。
prefs-title = TeXlate
prefs-dialog-title = TeXlate 设置

# 设置对话框字段（modules/prefs.ts SettingsDialogHelper）。
prefs-server-url = 服务器地址
prefs-api-key = API 密钥（可选）
prefs-attach-zh = 附加中文 PDF（zh.pdf）
prefs-attach-en = 附加英文 PDF（en.pdf）
prefs-attach-dual = 附加双语对照 PDF（dual.pdf）
prefs-batch-delay = 批量任务间隔（毫秒）
prefs-poll-interval = 轮询间隔（毫秒）
prefs-poll-timeout = 轮询超时（毫秒）
prefs-status = 连接状态
prefs-check = 检查连接
prefs-checking = 正在检查…
prefs-health-ok = 已连接——服务器版本 { $version }
prefs-health-bad = 响应异常——该地址是 TeXlate 服务器吗？
prefs-health-down = 无法连接服务器——`uvx texlate web` 是否在运行？
prefs-save = 保存
prefs-cancel = 取消

# 进度阶段——modules/poller.ts 的 phaseKey() 按任务阶段（fetching…compiling）
# 或状态（queued 及各终态）取后缀；modules/flow.ts 渲染为「{阶段} {进度}%」。
phase-queued = 排队中
phase-fetching = 获取源码中
phase-parsing = 解析 LaTeX 中
phase-translating = 翻译中
phase-compiling = 编译 PDF 中
phase-done = 已完成
phase-partial = 部分完成
phase-fault = 失败
phase-cancelled = 已取消
phase-interrupted = 已中断
phase-needs_auth = 需要授权

# 翻译流程（modules/flow.ts）——ProgressWindow 行文本。
flow-done = 翻译完成——PDF 已附加到条目。
flow-partial-warn = 任务部分完成——个别段落可能未翻译。
flow-already-translated = 该条目已翻译——请使用「在阅读器打开」查看。
flow-needs-auth = 服务器需要登录——正在打开 { $serverUrl } 进行授权。
flow-attach-failed = 无法附加译文 PDF：{ $detail }
flow-batch-summary = { $failed ->
    [0] 批量翻译完成：{ $total } 个条目全部成功。
   *[other] 批量翻译完成：{ $total } 个中成功 { $ok } 个、失败 { $failed } 个。
}

# 流程错误（ProgressWindow 失败行）。
flow-error-not-regular = 仅支持翻译常规文献条目。
flow-error-no-arxiv-id = 未在该条目上找到 arXiv ID。
flow-error-inflight = 该条目已有翻译任务进行中。
flow-error-server-down = 无法连接 { $serverUrl } 的 TeXlate 服务器——请运行 `uvx texlate web`，或在设置中检查服务器地址。
flow-error-server-unhealthy = TeXlate 服务器已响应，但报告状态异常。
flow-error-invalid-arxiv-id = 服务器拒绝了该 arXiv ID：{ $detail }
flow-error-api = 服务器错误 { $status }：{ $detail }
flow-error-poll-timeout = 等待翻译完成超时。
flow-error-task-fault = 翻译失败：{ $detail }
flow-error-task-cancelled = 翻译任务已取消。
flow-error-task-interrupted = 翻译任务被中断。
flow-error-unexpected = 意外错误：{ $message }
