// options —— 任务选项共享常量：TARGET_LANGS 与 server TARGET_LANGS 同源
//（zh-CN/zh-TW/en），ENGINES 是 Home/Settings 两处表单共用的引擎集
//（auto=服务端决议；pdflatex 不在此表——仅 TaskList 重试菜单单列）。
// 双份硬编码曾散在 Home.tsx 与 Settings.tsx，漂移即两页口径不一。

/** 目标语言白名单（server TARGET_LANGS 同序） */
export const TARGET_LANGS: string[] = ["zh-CN", "zh-TW", "en"];

/** 编译引擎选项——auto=交给服务端 engine_resolved 决议 */
export const ENGINES: string[] = ["auto", "xelatex", "tectonic"];

/** LLM 网关方言（server API_DIALECTS 同集）——auto=按端点 host 推导 */
export const API_DIALECTS: string[] = [
    "auto",
    "openai",
    "anthropic",
    "responses",
];
