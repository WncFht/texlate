// helpers —— 测试共享挂载臂（jsdom 专属：顶层引 solid-js/web，node-env
// 文件勿引；node 侧共用件在 _taskkit.ts，flush/api 模块 mock 工厂也在那）。
// vite include `src/**/*.test.ts` 不会把本文件当测试跑。
//
// 清理走模块级 disposers 桶 + 顶层 afterEach：afterEach 在导入文件的收集期
// 注册、绑到该文件根 suite——勿挪进 mountToBody（it 内注册会绑到过期 suite
// 并逐次叠加）。同 _homekit 约定。

import { render } from "solid-js/web";
import { afterEach } from "vitest";
import type { JSX } from "solid-js";

const disposers: (() => void)[] = [];

/**
 * 挂组件到 document.body 下新 div，disposer 收进桶（afterEach 统一摘），
 * 返回容器元素。document.body.querySelector 照旧可达。
 */
export function mountToBody(node: () => JSX.Element): HTMLDivElement {
    const el = document.createElement("div");
    document.body.appendChild(el);
    disposers.push(render(node, el));
    return el;
}

/** 中途卸载最近一次 mountToBody（卸载即停轮询类用例）——幂等 */
export function unmountLast() {
    disposers.pop()?.();
}

// 顶层 afterEach 逐文件绑定：摘完全部挂载 + 清 body（重复挂载文件安全）
afterEach(() => {
    while (disposers.length) disposers.pop()!();
    if (typeof document !== "undefined") document.body.innerHTML = "";
});
