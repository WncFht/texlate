#!/usr/bin/env node
// Evaluate JavaScript inside a running Zotero's main-window (parent process)
// context over the Firefox Remote Debugging Protocol (RDP, raw TCP, no deps).
//
// Actor chain (Firefox 140 / Zotero 9):
//   connect -> root greeting
//   to=root            type=listProcesses   -> processes[].actor (processDescriptor, isParent)
//   to=processDescriptor type=getTarget     -> process.{actor=parentProcessTarget, consoleActor}
//   to=consoleActor    type=evaluateJSAsync -> {resultID} then {type:"evaluationResult"}
//
// The consoleActor evaluates inside chrome://zotero/content/zoteroPane.xhtml —
// `Zotero`, `ZoteroPane`, `Services` etc. are real globals there.
// evaluateJSAsync never awaits promises, so async results are returned via a
// globalThis slot that a polling eval reads back (verified on Zotero 9.0.5).
//
// Usage: rdp.mjs [--port 6100] [--timeout 30] '<js>'
//   stdout: {"ok":true,"value":<json>}   exit 0
//   stderr: {"ok":false,"error":<msg>}   exit 1 (eval/timeout) | exit 2 (conn)
//
// 骨架四字段（头注释即上文机制段，此处按 skeleton 口径归档）：
//   适用条件 — Zotero 带 --start-debugger-server <port> 启动 + profile
//     prefs 开 remote-enabled/prompt-connection=false（dev 工具已 seed）；
//   变换方法 — 上列 actor 链 + evaluateJSAsync + globalThis 槽轮询；
//   资源约束 — 服务端事件噪音按 type/resultID 过滤；longString grip 走
//     substring 取全文；eval 在窗口事件循环跑，用户代码阻塞由 deadline 兜底；
//   验证证据 — dev/research/rdp.md 实跑输出与死胡同清单。

import net from "node:net";

const args = process.argv.slice(2);
let port = 6100;
let timeoutSec = 30;
let code = null;
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--port") port = Number(args[++i]);
  else if (args[i] === "--timeout") timeoutSec = Number(args[++i]);
  else if (args[i] === "-h" || args[i] === "--help") {
    console.log("usage: rdp [--port 6100] [--timeout 30] '<js>'");
    process.exit(0);
  } else if (code === null) code = args[i];
  else code += " " + args[i];
}
if (code === null) {
  console.error("usage: rdp [--port 6100] [--timeout 30] '<js>'");
  process.exit(2);
}
const deadline = Date.now() + timeoutSec * 1000;
const left = () => deadline - Date.now();

const fail = (msg, xit) => {
  console.error(JSON.stringify({ ok: false, error: String(msg) }));
  process.exit(xit);
};
const done = (value) => {
  console.log(JSON.stringify({ ok: true, value }));
  process.exit(0);
};

const sock = net.connect({ host: "127.0.0.1", port });
let buf = Buffer.alloc(0);
const inbox = [];
let onMsg = null;

sock.on("error", (e) => fail(`connect 127.0.0.1:${port}: ${e.message}`, 2));
sock.on("end", () => fail("connection closed", 2));
sock.on("data", (chunk) => {
  buf = Buffer.concat([buf, chunk]);
  for (;;) {
    const i = buf.indexOf(0x3a); // ':' — RDP frame = <byteLen>:<json>
    if (i < 0) return;
    const n = parseInt(buf.subarray(0, i).toString("ascii"), 10);
    if (Number.isNaN(n) || n < 0) return fail("bad RDP frame header", 2);
    if (buf.length < i + 1 + n) return;
    let msg;
    try {
      msg = JSON.parse(buf.subarray(i + 1, i + 1 + n).toString("utf8"));
    } catch (e) {
      return fail(`bad RDP frame json: ${e.message}`, 2);
    }
    buf = buf.subarray(i + 1 + n);
    if (onMsg) {
      const f = onMsg;
      onMsg = null;
      f(msg);
    } else inbox.push(msg);
  }
});

const nextMsg = () =>
  inbox.length
    ? Promise.resolve(inbox.shift())
    : new Promise((res, rej) => {
        onMsg = res;
        setTimeout(
          () => rej(new Error("timeout waiting for packet")),
          Math.max(left(), 1),
        ).unref?.();
      });

function send(pkt) {
  const b = Buffer.from(JSON.stringify(pkt), "utf8");
  sock.write(Buffer.concat([Buffer.from(`${b.length}:`), b]));
}

async function rpc(pkt, match) {
  send(pkt);
  for (;;) {
    const m = await nextMsg();
    if (match(m)) return m;
    if (m.error) throw new Error(`${m.error}: ${m.message || ""}`);
  }
}

await new Promise((res, rej) => {
  sock.once("connect", res);
  sock.once("error", rej);
  setTimeout(
    () => rej(new Error("connect timeout")),
    Math.min(5000, Math.max(left(), 1)),
  ).unref?.();
}).catch((e) => fail(`connect 127.0.0.1:${port}: ${e.message}`, 2));

try {
  await nextMsg(); // root greeting

  const lp = await rpc({ to: "root", type: "listProcesses" }, (m) =>
    Array.isArray(m.processes),
  );
  const pd = lp.processes.find((p) => p.isParent) || lp.processes[0];
  const gt = await rpc({ to: pd.actor, type: "getTarget" }, (m) => m.process);
  const ca = gt.process.consoleActor;

  const evalJS = (text) =>
    rpc(
      {
        to: ca,
        type: "evaluateJSAsync",
        text,
        mappedTraits: { awaitPromise: true },
        eager: false,
      },
      (m) => m.type === "evaluationResult",
    );

  const uid = `__rdp${process.pid.toString(36)}${Math.random().toString(36).slice(2, 10)}`;
  const key = JSON.stringify(uid);
  const wrap = (inner) =>
    `(async()=>{try{var __v=await (async()=>{${inner}\n})();` +
    `try{globalThis[${key}]=JSON.stringify({ok:true,value:__v===undefined?null:__v})}` +
    `catch(e2){globalThis[${key}]=JSON.stringify({ok:true,value:"[unserializable: "+e2+"]"})}}` +
    `catch(e){globalThis[${key}]=JSON.stringify({ok:false,error:String(e)+(e&&e.stack?"\\n"+e.stack:"")})}` +
    `return "queued"})()`;

  // Try expression form first; on SyntaxError fall back to statement body.
  let r = await evalJS(wrap(`return (\n${code}\n);`));
  if (r.hasException && /SyntaxError/.test(r.exceptionMessage || "")) {
    r = await evalJS(wrap(code));
  }
  if (r.hasException) fail(r.exceptionMessage || "eval exception", 1);
  if (r.error) fail(`${r.error}: ${r.message || ""}`, 1);

  const poll = `(()=>{var r=globalThis[${key}];if(r!==undefined)delete globalThis[${key}];return r})()`;
  for (;;) {
    if (left() <= 0) fail(`timeout after ${timeoutSec}s`, 1);
    const p = await evalJS(poll);
    let v = p.result;
    if (v && v.type === "longString") {
      const sub = await rpc(
        { to: v.actor, type: "substring", start: 0, end: v.length },
        (m) => typeof m.substring === "string",
      );
      v = sub.substring;
    }
    if (v && v.type === "undefined") v = undefined;
    if (v !== undefined && v !== null) {
      let parsed;
      try {
        parsed = JSON.parse(v);
      } catch {
        parsed = { ok: true, value: v };
      }
      if (parsed.ok) done(parsed.value);
      fail(parsed.error || "eval failed", 1);
    }
    await new Promise((r2) => setTimeout(r2, 150));
  }
} catch (e) {
  fail(e.message || e, 1);
}
