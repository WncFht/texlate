// _taskdom —— TaskList 渲染臂（jsdom 专属）。solid-js/web 与组件树顶层
// 求值即触 window（delegateEvents）——node-env 测试（liveFixes 等）只引
// _taskkit，本件仅限带 `// @vitest-environment jsdom` 头的文件 import。

import { render } from "solid-js/web";
import type { TaskSnapshot } from "../api/client";
import TaskList from "../components/TaskList";

/** TaskList 直渲桩：tasks 挂 root（默认 document.body），返回 dispose */
export const renderList = (
    tasks: TaskSnapshot[],
    root: HTMLElement = document.body,
    onOpen: (taskId: string) => void = () => {},
) => render(() => TaskList({ tasks, onOpen }), root);
