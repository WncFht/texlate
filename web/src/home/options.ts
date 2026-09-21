// options —— Home 任务选项表单态：opt* 信号簇 + TranslateOptions 收集 +
// multipart 上传字段快照 + per-request BYOK（仅存组件态，提交成功即清，
// 不落 settings）+ 表单行描述（optCommon/optAdv——数据驱动渲染的行表）。
// 自 pages/Home.tsx 拆出（reader/taskActions 模式：纯逻辑工厂，页面只
// 装配）；控件渲染（optControl/optRow）在同簇 OptionsForm.tsx。

import { createSignal } from "solid-js";
import type { ByokHeaders, TranslateOptions } from "../api/client";
import { t } from "../i18n";
import { clampConcurrency, ENGINES, TARGET_LANGS } from "../options";
import { settingsStore } from "../stores/settings";

/** 并发上下限——表单行 min/max 用；collectOptions 夹取走 ../options
 *  clampConcurrency（同界 1..16，漂移即双口径） */
const OPT_CONC_MIN = 1;
const OPT_CONC_MAX = 16;

/** options 表单行描述——label/hint/控件形/信号绑定数据驱动渲染；
 *  adv=true 收进「高级」折叠组，缺省进常用组 */
export type OptRow = {
    label: string;
    /** 函数形可挂响应式值（settings 加载完成前给占位） */
    hint?: string | (() => string);
    get: () => string;
    set: (v: string) => void;
    span2?: boolean;
    adv?: boolean;
} & (
    | {
          kind: "input";
          type?: "text" | "number" | "password";
          placeholder?: () => string;
          min?: number;
          max?: number;
      }
    | {
          kind: "seg";
          /** 空值 pill 的文案；缺省 = 不出空 pill（optSource 恒有值） */
          defaultLabel?: () => string;
          choices: { value: string; label: string }[];
      }
    | { kind: "textarea"; rows?: number }
);

/** upload 的 multipart 字段快照形——options 透传走 JSON 字段；
 *  main/byok 同帧快照——批传中途再改主文件/临时 key 不渗进在飞批 */
export interface UploadFields {
    o: TranslateOptions;
    upOpts: Record<string, unknown>;
    main: string;
    byok: ByokHeaders | undefined;
}

export function createHomeOptions() {
    // 任务选项（默认收起；空值 = 跟随 settings 默认）
    const [optModel, setOptModel] = createSignal("");
    const [optLang, setOptLang] = createSignal("");
    const [optGlossary, setOptGlossary] = createSignal("");
    const [optGuidance, setOptGuidance] = createSignal("");
    const [optConcurrency, setOptConcurrency] = createSignal("");
    const [optEngine, setOptEngine] = createSignal("");
    const [optPrefer, setOptPrefer] = createSignal("");
    // 取源通道：eprint=LaTeX 主链 / html=arXiv HTML 降级链（仅 arxiv 翻译有意义）
    const [optSource, setOptSource] = createSignal("eprint");
    const [optShare, setOptShare] = createSignal("");
    const [optMain, setOptMain] = createSignal("");
    // preamble 前置内容翻译开关（服务端缺省 摘要+标题开/作者关——
    // 这里显式带默认，提交即固定意图，不走 "follow settings" 空值语义）
    const [optFmAbstract, setOptFmAbstract] = createSignal("on");
    const [optFmTitle, setOptFmTitle] = createSignal("on");
    const [optFmAuthor, setOptFmAuthor] = createSignal("off");
    // per-request BYOK：仅存组件 state，提交成功即清，不落 settings
    const [optKey, setOptKey] = createSignal("");

    /** 非空字段收成 TranslateOptions——front_matter 恒显式写（UI 态即
     *  意图），options 恒非空故恒返回对象，「全空 → undefined」不可达 */
    const collectOptions = (): TranslateOptions => {
        const o: TranslateOptions = {};
        const opts: NonNullable<TranslateOptions["options"]> = {};
        if (optModel().trim()) o.model = optModel().trim();
        if (optLang()) o.target_lang = optLang();
        if (optGlossary().trim()) o.glossary = optGlossary().trim();
        if (optGuidance()) opts.context_guidance = optGuidance() === "on";
        const conc = Number(optConcurrency());
        if (optConcurrency() && Number.isFinite(conc)) {
            // Home 侧守卫只排非有限值——sub-1 由 clamp 提到 1（Settings 侧
            // 另行省略 sub-1，两站守卫语义各自保留）
            opts.concurrency = clampConcurrency(conc);
        }
        if (optEngine()) opts.engine = optEngine();
        if (optShare()) opts.share_pack = optShare() === "on";
        const pref = optPrefer();
        if (pref === "reuse" || pref === "fresh") opts.prefer = pref;
        // 默认 eprint 不写字段——服务端按缺省 eprint，存量请求面零变化
        if (optSource() === "html") opts.source = "html";
        // 前置三项恒显式写——UI 态即意图（服务端缺省与此初值一致）
        opts.front_matter = {
            abstract: optFmAbstract() === "on",
            title: optFmTitle() === "on",
            author: optFmAuthor() === "on",
        };
        o.options = opts;
        return o;
    };

    /** 临时 key → X-Texlate-Key 头（空 → undefined，纯 per-request 透传） */
    const byok = (): ByokHeaders | undefined =>
        optKey().trim() ? { apiKey: optKey().trim() } : undefined;

    /** 提交成功即清（失败保留字段值可重试——调用方按结案分支调） */
    const clearKey = () => setOptKey("");

    /** upload 的 multipart 字段快照：options 透传走 JSON 字段——prefer 仅对
     *  arxiv 缓存有意义（server 上传路恒 prefer=fresh）、source 是 arxiv
     *  取源通道同理剔除；glossary 在 options 内传递故上提 */
    const uploadFields = (): UploadFields => {
        const o = collectOptions();
        const upOpts: Record<string, unknown> = { ...o.options };
        delete upOpts.prefer;
        delete upOpts.source;
        if (o.glossary) upOpts.glossary = o.glossary;
        return { o, upOpts, main: optMain().trim(), byok: byok() };
    };

    /** settings 默认值做占位文案（未加载时给通用占位） */
    const def = (k: "model" | "target_lang" | "engine" | "concurrency") => {
        const v = settingsStore.settings()?.[k];
        return v === undefined || v === "" ? "…" : String(v);
    };

    // 表单行表——一次性构建（get/set/hint/placeholder 闭包才是响应式部分；
    // 数组本体不随 settings 重建，For 按引用保行不整组重挂）
    const optRows: OptRow[] = [
        {
            kind: "input",
            label: t.home.optModel,
            get: optModel,
            set: setOptModel,
            placeholder: () => def("model"),
        },
        {
            kind: "seg",
            label: t.home.optLang,
            // 已解析默认值挪 hint——pill 保持「跟随设置」短文案不挤格
            hint: () => `${t.home.optDefault}（${def("target_lang")}）`,
            get: optLang,
            set: setOptLang,
            defaultLabel: () => t.home.optDefault,
            choices: TARGET_LANGS.map((l) => ({ value: l, label: l })),
        },
        {
            kind: "seg",
            label: t.home.optEngine,
            hint: () => `${t.home.optDefault}（${def("engine")}）`,
            get: optEngine,
            set: setOptEngine,
            // en 四 pill 超半格宽，独占整行
            span2: true,
            defaultLabel: () => t.home.optDefault,
            choices: ENGINES.map((en) => ({
                value: en,
                label: en === "auto" ? t.home.engineAuto : en,
            })),
        },
        {
            kind: "input",
            type: "number",
            min: OPT_CONC_MIN,
            max: OPT_CONC_MAX,
            label: t.home.optConcurrency,
            get: optConcurrency,
            set: setOptConcurrency,
            placeholder: () => def("concurrency"),
        },
        {
            kind: "seg",
            label: t.home.optGuidance,
            get: optGuidance,
            set: setOptGuidance,
            defaultLabel: () => t.home.optDefault,
            choices: [
                { value: "on", label: t.home.optOn },
                { value: "off", label: t.home.optOff },
            ],
        },
        {
            kind: "seg",
            adv: true,
            label: t.home.optFmAbstract,
            get: optFmAbstract,
            set: setOptFmAbstract,
            choices: [
                { value: "on", label: t.home.optOn },
                { value: "off", label: t.home.optOff },
            ],
        },
        {
            kind: "seg",
            adv: true,
            label: t.home.optFmTitle,
            get: optFmTitle,
            set: setOptFmTitle,
            choices: [
                { value: "on", label: t.home.optOn },
                { value: "off", label: t.home.optOff },
            ],
        },
        {
            kind: "seg",
            adv: true,
            label: t.home.optFmAuthor,
            hint: t.home.optFmAuthorHint,
            get: optFmAuthor,
            set: setOptFmAuthor,
            choices: [
                { value: "on", label: t.home.optOn },
                { value: "off", label: t.home.optOff },
            ],
        },
        {
            kind: "seg",
            adv: true,
            label: t.home.optPrefer,
            get: optPrefer,
            set: setOptPrefer,
            defaultLabel: () => t.home.optDefault,
            choices: [
                { value: "reuse", label: t.home.preferReuse },
                { value: "fresh", label: t.home.preferFresh },
            ],
        },
        {
            kind: "seg",
            adv: true,
            label: t.home.optSource,
            hint: t.home.optSourceHint,
            get: optSource,
            set: setOptSource,
            choices: [
                { value: "eprint", label: t.home.srcEprint },
                { value: "html", label: t.home.srcHtml },
            ],
        },
        {
            kind: "seg",
            adv: true,
            label: t.home.optShare,
            hint: t.home.optShareHint,
            get: optShare,
            set: setOptShare,
            defaultLabel: () => t.home.optDefault,
            choices: [
                { value: "on", label: t.home.optOn },
                { value: "off", label: t.home.optOff },
            ],
        },
        {
            kind: "input",
            adv: true,
            label: t.home.optMain,
            hint: t.home.optMainHint,
            get: optMain,
            set: setOptMain,
            placeholder: () => "main.tex",
        },
        {
            kind: "textarea",
            adv: true,
            label: t.home.optGlossary,
            hint: t.home.optGlossaryHint,
            get: optGlossary,
            set: setOptGlossary,
            rows: 3,
            span2: true,
        },
        {
            kind: "input",
            type: "password",
            adv: true,
            label: t.home.optKey,
            hint: t.home.optKeyHint,
            get: optKey,
            set: setOptKey,
            span2: true,
        },
    ];

    /** 常用组 = 未标 adv 的行（语言/模型/并发等高频）；其余收「高级」 */
    const optCommon = optRows.filter((r) => !r.adv);
    const optAdv = optRows.filter((r) => r.adv);

    return {
        optModel,
        setOptModel,
        optLang,
        setOptLang,
        optGlossary,
        setOptGlossary,
        optGuidance,
        setOptGuidance,
        optConcurrency,
        setOptConcurrency,
        optEngine,
        setOptEngine,
        optPrefer,
        setOptPrefer,
        optSource,
        setOptSource,
        optShare,
        setOptShare,
        optMain,
        setOptMain,
        optFmAbstract,
        setOptFmAbstract,
        optFmTitle,
        setOptFmTitle,
        optFmAuthor,
        setOptFmAuthor,
        optKey,
        setOptKey,
        collectOptions,
        byok,
        clearKey,
        uploadFields,
        optCommon,
        optAdv,
    };
}

export type HomeOptions = ReturnType<typeof createHomeOptions>;
