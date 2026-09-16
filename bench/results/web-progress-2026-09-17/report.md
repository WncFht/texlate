# web-progress — 上传进度条实装（XHR progress 通道）

> 2026-09-17 收口。scope：`web/` 5 改 + 2 新测试文件。leader 复核：diff 逐 hunk 对账一致，tsc/eslint 由 agent 自验（--max-warnings 0），vitest 3 文件 17/17 leader 复跑绿。

## 机制

- `client.ts`：`UploadProgress` 类型 + `xhrRequest<T>()`——fetch 无上传进度事件，带 onProgress 的 multipart 提交走 XHR（`xhr.upload.onprogress`→loaded/total，仅 lengthComputable 发）。**响应解析口径与 `request()` 全等**：JSON 错误体→`ApiError(detail/code/task_id)`，网络失败/abort→`TypeError`（保 createRequest「未决留 idem key」语义）。`createRequest` 第 4 参 onProgress——有参走 XHR、无参走 fetch，Idempotency-Key 生成/复用/结案逻辑不变。`api.upload`/`api.shareImport` 可选第 4 参向后兼容。
- `Home.tsx`：`uploading`/`upPct` 两 signal；upload 与 shareImport 两路都传 onProgress（loaded/total→%）；`</form>` 后 `<Show>` 渲 `.up-progress`（条+`t.home.uploadPct` 文案），finally 结案隐藏；translate 路径不受影响。
- `i18n/zh.ts`：`t.home.uploadPct = "上传中… {n}%"`（{n} 占位与 TaskList time 模板同款 replace）。
- `styles/app.css`：`.up-progress/.up-bar/.up-label`，沿用 tp-bar 的 --cinnabar/--paper-2。
- `mock-api.ts` 无需改：XHR progress 是浏览器传输层事件，mock 经 `req.on("data")` 正常消费。

## 测试

- `uploadProgress.test.ts`（client 层 7 例）：FakeXHR 桩——onprogress 回调、fetch 未被调、non-computable 过滤、BYOK/Idem-Key 经 setRequestHeader、未决重发复用同 key、422→ApiError、无 onProgress 仍走 fetch。
- `homeUploadProgress.test.ts`（UI 层 4 例）：进度驱动 .up-bar 宽度+文案、结案隐藏、share.zip 路带 progress 参、translate 不出条。
- `homeByokUpload.test.ts` 三处断言适配第 4 参（expect.any(Function)）。

## 限制

未做浏览器实测（无 dev server 环境）——机制由 vitest 覆盖，真实上传时浏览器按 body 流速发 progress 事件。UI 验证待有人工环境补。
