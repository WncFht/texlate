# RDP spike — JS eval inside live Zotero

在真实运行的 Zotero 主窗口（parent process）里执行任意 JS 并取回结果。已验证可行，工具落地为 `zotero/dev/rdp`（bash wrapper）+ `zotero/dev/rdp.mjs`（node ESM，raw TCP，零依赖）。

## 适用条件

- Zotero 9.0.5 / Gecko 140.10.0esr（`/usr/bin/zotero`）。协议是 Firefox Remote Debugging Protocol（RDP）：TCP 上 `<byteLength>:<JSON>` 长度前缀帧。
- 启动需要 `--start-debugger-server <port>`（不出现在 `--help` 里但有效）。我们跑的是 `xvfb-run -a zotero --profile tmp/zotero-dev/rdp-profile -datadir tmp/zotero-dev/zotero-data --start-debugger-server 6100 -ZoteroDebugText`。
- **必须带 `-datadir`**：不带会打开 `~/Zotero`（用户真实数据库）——第一次 spike 就踩了，重启后隔离。
- profile 的 `user.js` 预设了 `devtools.debugger.remote-enabled=true`、`devtools.debugger.prompt-connection=false`（避免连接确认弹窗）。flag 本身已足够起服务，prefs 是双保险。
- 无 DISPLAY → `xvfb-run -a`。
- 传输备选：`-marionette`（2828，同样长度前缀帧）与 `--remote-debugging-port`（WebDriver BiDi/CDP，WebSocket）均未启用——RDP 第一条路就通了，没必要碰。

## 变换方法

客户端链路（每连接重走一次，actor 名带 connN 序号不可缓存）：

```text
<- {"from":"root","applicationType":"browser","testConnectionPrefix":"server1.conn1.","traits":{...}}   (greeting)
-> {"to":"root","type":"listProcesses"}
<- {"processes":[{"actor":"server1.connN.processDescriptorM","id":0,"isParent":true,"traits":{"watcher":true,...}}]}
-> {"to":"server1.connN.processDescriptorM","type":"getTarget"}
<- {"process":{"actor":"server1.connN.parentProcessTarget3","url":"chrome://zotero/content/zoteroPane.xhtml",
    "consoleActor":"server1.connN.consoleActor4","threadActor":"server1.connN.thread2", ...}}
-> {"to":"server1.connN.consoleActor4","type":"evaluateJSAsync","text":"Zotero.version",
    "mappedTraits":{"awaitPromise":true},"eager":false}
<- {"resultID":"...-0","from":"...consoleActor4"}                          (ack)
<- {"type":"evaluationResult","resultID":"...-0","hasException":false,"result":"9.0.5.SOURCE.f0bcd5ae1"}
```

`consoleActor` 的 eval 跑在 `zoteroPane.xhtml` 主窗口上下文：`Zotero`、`ZoteroPane`、`Services` 全是真全局。注意它是 `isBrowsingContext` 的 window target，不是无窗口的 parent-process sandbox——这正是能看到 `Zotero` 的原因。

异步结果：`evaluateJSAsync` **不会** await（`awaitPromise`/`topLevelAwait` 都试过，无效——pending Promise 直接以 grip 返回，0.04s 就回）。promise 的 `<state>`/`<value>` 伪属性只存在于 grip preview，`prototypeAndProperties` 返回空 ownProperties，轮询 actor 没用。解法：把用户代码包进 async IIFE，写 `JSON.stringify({ok,value|error})` 到 `globalThis.__rdp<rand>`，再用第二个 eval 轮询读取（同窗口 globalThis 跨 eval、跨连接都持久）。读回即 `delete`，不留垃圾。超长字符串会成 `longString` grip（`{type:"longString",actor,length,initial}`），用 `{"to":actor,"type":"substring","start":0,"end":length}` 取全文。

表达式 vs 语句：先按 `return (<code>);` 包装，evaluationResult `hasException`+`SyntaxError` 则重发裸语句体（SyntaxError 在 parse 期抛出，无副作用）。两形态下 `await` 均可用（都在 async fn 里）。

## 资源约束

- 服务端事件噪音：`parentProcessTarget` 会推 `frameUpdate` 等事件包，读响应必须按 `type`/`resultID` 过滤，不能读一包就当响应。
- `consoleActor` 不认 `evaluateJS`（已移除/改名），只有 `evaluateJSAsync`；响应分 ack `{resultID}` 与终态 `{type:"evaluationResult"}` 两包。
- `root` 不认 `protocolDescription`；`listTabs` 只回 `{tabs:[]}`，不再附带 browserConsole/parentProcess actors（现代协议走 listProcesses→getTarget）。
- 结果序列化在 eval 侧做（`JSON.stringify`），非 JSON 值 → `"[unserializable: ...]"`；undefined → null。异常走 `{ok:false,error:"Error: msg\n<stack>"}`（Firefox `e.stack` 不含 message，须拼 `String(e)`）。
- 每个 eval 在窗口事件循环里跑；用户代码同步阻塞会卡住轮询 eval——deadline 兜底。
- exit codes：0 成功 / 1 eval 异常或超时 / 2 连接失败。

## 验证证据

实跑输出（Zotero 9.0.5.SOURCE.f0bcd5ae1，profile=tmp/zotero-dev/rdp-profile）：

```text
$ zotero/dev/rdp 'Zotero.version'                        -> {"ok":true,"value":"9.0.5.SOURCE.f0bcd5ae1"}
$ zotero/dev/rdp 'Zotero.Items.getAll ? "have-items" : "no"' -> {"ok":true,"value":"have-items"}
$ zotero/dev/rdp 'typeof ZoteroPane'                     -> {"ok":true,"value":"object"}
$ zotero/dev/rdp 'Zotero.getMainWindow() ? "win-ok":"no"'-> {"ok":true,"value":"win-ok"}
$ zotero/dev/rdp '(async()=>{return 42})()'              -> {"ok":true,"value":42}
$ zotero/dev/rdp 'await new Promise(r=>setTimeout(r,800)).then(()=>"delayed-ok")' -> {"ok":true,"value":"delayed-ok"}
$ zotero/dev/rdp 'var x=7; var y=x*3; return y'          -> {"ok":true,"value":21}
$ zotero/dev/rdp 'throw new Error("boom-test")'          -> {"ok":false,"error":"Error: boom-test\n__v<@debugger eval code:1:47..."} exit=1
$ zotero/dev/rdp --port 9999 '1+1'                       -> {"ok":false,"error":"connect ... ECONNREFUSED"} exit=2
$ zotero/dev/rdp '({lib: Zotero.Libraries.userLibraryID, pane: typeof ZoteroPane})' -> {"ok":true,"value":{"lib":1,"pane":"object"}}
```

## 踩过的死胡同

- `{"to":processDescriptor,"type":"attach"}` → `unrecognizedPacketType`（要用 `getTarget`）。
- `{"to":consoleActor,"type":"evaluateJS"}` → `unrecognizedPacketType`（只有 `evaluateJSAsync`）。
- `listTabs` 空 tabs、无辅助 actors；`protocolDescription` 报错。
- `awaitPromise` mappedTrait、`topLevelAwait` 请求字段均不能让服务端等待 promise；top-level `await` 裸用是 SyntaxError。
- `--start-debugger-server` 在 `--help` 中不列出但生效。
