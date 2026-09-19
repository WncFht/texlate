// Home —— arXiv 输入 + 文件上传 + 任务列表（活动任务进度走 SSE）。

import {
    createEffect,
    createSignal,
    For,
    type JSX,
    onCleanup,
    onMount,
    Show,
} from "solid-js";
import {
    api,
    ApiError,
    landingHash,
    type DiscoverHit,
    type DiscoverPaper,
    type Health,
    type TranslateOptions,
} from "../api/client";
import { taskStore } from "../stores/tasks";
import { settingsStore } from "../stores/settings";
import TaskList from "../components/TaskList";
import { ENGINES, TARGET_LANGS } from "../options";
import { t } from "../i18n";

const ARXIV_RE =
    /^(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z][a-zA-Z]+)?\/\d{7}(?:v\d+)?)$/i;

/** 上传客户端预检（U14）：80MB 上限 + 扩展名白名单——早于 XHR 失败给出本地错 */
const MAX_UPLOAD_BYTES = 80 * 1024 * 1024;
const UPLOAD_EXT = /\.(pdf|tex|tar|gz|tgz|zip|docx|epub)$/i;

/** 首页三路拉取的 TTL——reader 往返重挂载不再每趟全量重拉（手动刷新不受门） */
const HOME_TTL_MS = 30_000;
let lastRefreshAt = 0;
let lastHealthAt = 0;
let lastFeedAt = 0;

/** options 表单行描述——label/hint/控件形/信号绑定数据驱动渲染；
 *  adv=true 收进「高级」折叠组，缺省进常用组 */
type OptRow = {
    label: string;
    hint?: string;
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
          kind: "select";
          /** 空值 option 的文案；缺省 = 不出空 option（optSource 恒有值） */
          defaultLabel?: () => string;
          choices: { value: string; label: string }[];
      }
    | { kind: "textarea"; rows?: number }
);

/** 单 options 行的控件部分——label/span 由调用点统一渲染 */
const optControl = (row: OptRow): JSX.Element => {
    if (row.kind === "select") {
        return (
            <select
                value={row.get()}
                onChange={(e) => row.set(e.currentTarget.value)}
            >
                {row.defaultLabel && (
                    <option value="">{row.defaultLabel()}</option>
                )}
                <For each={row.choices}>
                    {(c) => <option value={c.value}>{c.label}</option>}
                </For>
            </select>
        );
    }
    if (row.kind === "textarea") {
        return (
            <textarea
                rows={row.rows ?? 3}
                value={row.get()}
                onInput={(e) => row.set(e.currentTarget.value)}
            />
        );
    }
    return (
        <input
            type={row.type ?? "text"}
            min={row.min}
            max={row.max}
            autocomplete={row.type === "password" ? "off" : undefined}
            value={row.get()}
            placeholder={row.placeholder?.()}
            onInput={(e) => row.set(e.currentTarget.value)}
        />
    );
};

// 服务端 normalize_arxiv_id 的轻量版：剥 arXiv: 前缀、各路径段 URL、
// 尾部斜杠与 .pdf，再按新/旧 id 形白名单判
export function parseArxivId(raw: string): string | null {
    const s = raw.trim().replace(/^arxiv\s*:\s*/i, "");
    const bare = s.replace(/\.pdf$/i, "");
    if (ARXIV_RE.test(bare)) return bare;
    const m = s.match(
        /arxiv\.org\/(?:abs|pdf|html|src|e-print|format)\/+([^\s?#]+?)\/*?(?:\.pdf)?(?:[?#].*)?$/i,
    );
    return m && ARXIV_RE.test(m[1]) ? m[1] : null;
}

export default function Home(props: {
    nav(to: string): void;
    /** #/arxiv/{id} 深链——预填输入框 + 聚焦翻译钮，不自动提交 */
    arxivId?: string;
}) {
    const [arxivId, setArxivId] = createSignal("");
    const [busy, setBusy] = createSignal(false);
    const [error, setError] = createSignal("");
    // id 解析失败态：aria-invalid 只标格式错，服务端错误不占位
    const [idBad, setIdBad] = createSignal(false);
    const [dragOn, setDragOn] = createSignal(false);
    // 上传进度：uploading=文件提交在飞（区别于 translate 的 busy）；
    // upPct=-1 哨兵 = 尚无进度事件（lengthComputable=false 时恒如此）→ 不定态
    const [uploading, setUploading] = createSignal(false);
    const [upPct, setUpPct] = createSignal(-1);
    const [health, setHealth] = createSignal<Health | null>(null);
    const [healthPending, setHealthPending] = createSignal(true);
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
    // discover：alphaXiv 机会型增强——feed 卡 + 输入框快搜建议。
    // 上游挂 → feed=null 且 feedFailed=true，整块不渲染（不影响主流程）
    const [feed, setFeed] = createSignal<DiscoverPaper[] | null>(null);
    const [feedFailed, setFeedFailed] = createSignal(false);
    // hits=null=未发起/已关；[]=搜过无匹配——三态驱动下拉显隐
    const [hits, setHits] = createSignal<DiscoverHit[] | null>(null);
    // 键盘导航 active 项（-1=无；↓↑ 与悬停同写一份，鼠标键盘不分裂）
    const [activeHit, setActiveHit] = createSignal(-1);
    /** 下拉开/关唯一出口——hits 变即复位 active */
    const setSuggest = (v: DiscoverHit[] | null) => {
        setHits(v);
        setActiveHit(-1);
    };
    let searchTimer = 0;
    // seq 防慢响应盖新查询（旧响应落地时输入早已变）
    let searchSeq = 0;
    let fileInput!: HTMLInputElement;
    // 在飞请求不随卸载取消（幂等键保证服务端只收一单）——但落地后不得再
    // openRes 劫持用户已切走的路由；alive 守一切提交后副作用
    let alive = true;
    onCleanup(() => {
        alive = false;
    });

    // 健康复查：不健康态 30s 一拍自动复测（服务重启后页面自愈，不用手刷）；
    // ok 即停摆不空打端点。手动「重试」钮走同一路径。
    let healthTimer = 0;
    const checkHealth = async () => {
        try {
            setHealth(await api.health());
        } catch {
            setHealth(null);
        }
        setHealthPending(false);
        window.clearInterval(healthTimer);
        healthTimer = health()?.ok
            ? 0
            : window.setInterval(() => void checkHealth(), 30_000);
    };

    /** alphaXiv 热榜——机会型：502/超时静默，整块 section 不渲染 */
    const loadFeed = async () => {
        try {
            const res = await api.discoverFeed({
                sort: "Hot",
                interval: "7 Days",
                pageSize: 12,
            });
            if (alive) setFeed(res.papers ?? []);
        } catch {
            if (alive) setFeedFailed(true);
        }
    };

    /**
     * 输入即搜：300ms 防抖打 alphaxiv 快搜。只在输入「不像 arXiv id」时
     * 发起——能解析成 id 的输入是待提交态不是检索态。
     */
    const onIdInput = (v: string) => {
        setArxivId(v);
        // 格式错提示随编辑即消——用户在改，错误就不该挂着
        if (idBad()) {
            setIdBad(false);
            setError("");
        }
        window.clearTimeout(searchTimer);
        const q = v.trim();
        if (!q || parseArxivId(q)) {
            searchSeq++;
            setSuggest(null);
            return;
        }
        searchTimer = window.setTimeout(() => {
            const seq = ++searchSeq;
            api.discoverSearch(q)
                .then((res) => {
                    if (alive && seq === searchSeq) setSuggest(res);
                })
                .catch(() => {
                    if (alive && seq === searchSeq) setSuggest(null);
                });
        }, 300);
    };

    /** 建议行点击/Enter 选中 → 回填输入框（用户确认后再提交）；「翻译」直达深链 */
    const pickHit = (h: DiscoverHit) => {
        if (h.paperId) setArxivId(h.paperId);
        setSuggest(null);
    };

    /**
     * 建议下拉键盘契约：↓↑ 在选项间环绕移动 active 项，Enter 选中回填，
     * Esc 关下拉。列表合上或未出条时全键放行（Enter 走表单提交）。
     */
    const onSuggestKey = (e: KeyboardEvent) => {
        const list = hits();
        if (e.key === "Escape") {
            if (list !== null) {
                e.preventDefault();
                setSuggest(null);
            }
            return;
        }
        if (!list?.length) return;
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            const n = list.length;
            const next =
                e.key === "ArrowDown"
                    ? (activeHit() + 1) % n
                    : (activeHit() - 1 + n) % n;
            setActiveHit(next);
            document
                .getElementById(`ax-sug-${next}`)
                ?.scrollIntoView({ block: "nearest" });
            return;
        }
        if (e.key === "Enter" && activeHit() >= 0) {
            e.preventDefault();
            pickHit(list[activeHit()]);
        }
    };

    /** 卡 id 取 universal_paper_id（arXiv id），缺席回 canonical_id */
    const cardId = (p: DiscoverPaper) =>
        p.universal_paper_id || p.canonical_id || "";

    const cardDesc = (p: DiscoverPaper) =>
        p.feed_description ||
        p.paper_summary?.feedDescription ||
        p.paper_summary?.summary ||
        "";

    const cardVisits = (p: DiscoverPaper) => {
        const v = p.metrics?.visits_count;
        return v?.last_7_days ?? v?.all;
    };

    onMount(() => {
        const now = Date.now();
        if (now - lastRefreshAt > HOME_TTL_MS) {
            lastRefreshAt = now;
            void taskStore.refresh();
        }
        if (!settingsStore.loaded()) void settingsStore.refresh();
        if (now - lastHealthAt > HOME_TTL_MS) {
            lastHealthAt = now;
            void checkHealth();
        }
        if (now - lastFeedAt > HOME_TTL_MS) {
            lastFeedAt = now;
            void loadFeed();
        }
    });
    onCleanup(() => {
        window.clearInterval(healthTimer);
        window.clearTimeout(searchTimer);
    });

    /** health.compilers 可用数/总数（值 truthy 视为可用） */
    const compilersStat = () => {
        const c = health()?.compilers;
        if (!c) return "";
        const keys = Object.keys(c);
        return `${keys.filter((k) => c[k]).length}/${keys.length}`;
    };

    const open = (taskId: string) => props.nav(`#/reader/${taskId}`);
    // 202 落地：reader_url 仅产 dual.json 的 kind 下发，缺席（docx/epub）
    // 回 task_id——#/reader/:id 即任务详情面，终态自动落产物下载面板
    const openRes = (res: Parameters<typeof landingHash>[0]) =>
        props.nav(landingHash(res));

    /** 非空字段收成 TranslateOptions；全空返回 undefined（不附带 body 字段） */
    const collectOptions = (): TranslateOptions | undefined => {
        const o: TranslateOptions = {};
        const opts: NonNullable<TranslateOptions["options"]> = {};
        if (optModel().trim()) o.model = optModel().trim();
        if (optLang()) o.target_lang = optLang();
        if (optGlossary().trim()) o.glossary = optGlossary().trim();
        if (optGuidance()) opts.context_guidance = optGuidance() === "on";
        const conc = Number(optConcurrency());
        if (optConcurrency() && Number.isFinite(conc)) {
            opts.concurrency = Math.max(1, Math.min(16, Math.floor(conc)));
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
        if (Object.keys(opts).length) o.options = opts;
        return o.model || o.target_lang || o.glossary || o.options
            ? o
            : undefined;
    };

    /** 临时 key → X-Texlate-Key 头（空 → undefined，纯 per-request 透传） */
    const byok = () =>
        optKey().trim() ? { apiKey: optKey().trim() } : undefined;

    const submit = async () => {
        // 输入框 Enter 触发隐式提交不走 disabled 按钮——busy 门防重入
        if (busy()) return;
        const id = parseArxivId(arxivId());
        if (!id) {
            setError(t.home.invalidId);
            setIdBad(true);
            return;
        }
        setError("");
        setBusy(true);
        try {
            const res = await api.translate(id, collectOptions(), byok());
            if (!alive) return;
            setOptKey("");
            openRes(res);
        } catch (e) {
            if (!alive) return;
            // 409：同 cache_key 已有活动任务 → 直接跳过去
            if (e instanceof ApiError && e.status === 409) {
                const existing =
                    e.taskId ?? e.detail.match(/t_[0-9a-f]{16}/)?.[0];
                if (existing) {
                    open(existing);
                    return;
                }
            }
            setError(e instanceof Error ? e.message : String(e));
        } finally {
            setBusy(false);
        }
    };

    // #/arxiv/{id} 深链：预填输入框 + 聚焦翻译钮待用户拍板——分享链接落到
    // 别人浏览器不该白烧任务。lastDeep 记已消费的值防同值重聚焦；
    // 清空（离开深链）复位，回到同 id 可再预填
    let submitBtn!: HTMLButtonElement;
    let lastDeep: string | undefined;
    createEffect(() => {
        const a = props.arxivId;
        if (!a) {
            lastDeep = undefined;
            return;
        }
        if (a === lastDeep) return;
        lastDeep = a;
        setArxivId(a);
        submitBtn?.focus();
    });

    /** 客户端预检——返回错误文案或 null 放行（.share.zip 走 .zip 白名单） */
    const precheck = (f: File): string | null => {
        if (f.size > MAX_UPLOAD_BYTES) return t.home.uploadTooBig;
        if (!UPLOAD_EXT.test(f.name)) return t.home.uploadBadExt;
        return null;
    };

    /** upload 的 multipart 字段快照：options 透传走 JSON 字段——prefer 仅对
     *  arxiv 缓存有意义（server 上传路恒 prefer=fresh）、source 是 arxiv
     *  取源通道同理剔除；glossary 在 options 内传递故上提 */
    const uploadFields = () => {
        const o = collectOptions();
        const upOpts: Record<string, unknown> = { ...o?.options };
        delete upOpts.prefer;
        delete upOpts.source;
        if (o?.glossary) upOpts.glossary = o.glossary;
        return { o, upOpts };
    };

    /** 单文件提交：.share.zip 是社区缓存包走 share/import（包内 manifest
     *  自描述），其余走 api.upload（main 指定主文件） */
    const uploadOne = (
        f: File,
        snap: ReturnType<typeof uploadFields>,
        onProgress: (loaded: number, total: number) => void,
    ) => {
        const { o, upOpts } = snap;
        if (f.name.toLowerCase().endsWith(".share.zip")) {
            return api.shareImport(
                f,
                Object.keys(upOpts).length ? upOpts : undefined,
                byok(),
                onProgress,
            );
        }
        const main = optMain().trim();
        const fields =
            o || main
                ? {
                      model: o?.model,
                      target_lang: o?.target_lang,
                      main: main || undefined,
                      options: upOpts,
                  }
                : undefined;
        return api.upload(f, fields, byok(), onProgress);
    };

    const onUpProgress = (loaded: number, total: number) =>
        setUpPct(Math.min(100, Math.round((loaded / total) * 100)));

    /** 单件执行体：precheck + 状态翻转 + uploadOne——upload/uploadBatch 共用。
     *  成功回 ``{res}``，失败回 ``{err}`` 文案（单件路 setError、批路汇总）。 */
    const runOne = async (
        f: File,
        snap: ReturnType<typeof uploadFields>,
    ): Promise<
        { res: Awaited<ReturnType<typeof uploadOne>> } | { err: string }
    > => {
        const bad = precheck(f);
        if (bad) return { err: `${f.name}：${bad}` };
        setError("");
        setBusy(true);
        setUploading(true);
        setUpPct(-1);
        try {
            return { res: await uploadOne(f, snap, onUpProgress) };
        } catch (e) {
            return {
                err: `${f.name}：${e instanceof Error ? e.message : String(e)}`,
            };
        } finally {
            setBusy(false);
            setUploading(false);
        }
    };

    const upload = async (file: File, land = true) => {
        if (busy()) return;
        const r = await runOne(file, uploadFields());
        if (!alive) return;
        if ("err" in r) {
            setError(r.err);
            return;
        }
        setOptKey("");
        if (land) openRes(r.res);
    };

    /**
     * 多文件批传（U14）：顺序提交不并发——单文件落地阅读器照旧，
     * 批量模式不抢路由，全跑完 refresh 让新任务行自己冒出来。
     * 单文件失败不阻断后续；错误汇总到 error 行。
     */
    const uploadBatch = async (files: File[]) => {
        if (files.length === 1) {
            await upload(files[0]);
            return;
        }
        const errs: string[] = [];
        // 与单文件路同一套 multipart 字段——整批一次快照（中途改选项不影响在飞批）
        const snap = uploadFields();
        for (const f of files) {
            const r = await runOne(f, snap);
            if ("err" in r) errs.push(r.err);
            if (!alive) return;
        }
        setOptKey("");
        if (errs.length) setError(errs.join("；"));
        void taskStore.refresh();
    };

    /** settings 默认值做占位文案（未加载时给通用占位） */
    const def = (k: "model" | "target_lang" | "engine" | "concurrency") => {
        const v = settingsStore.settings()?.[k];
        return v === undefined || v === "" ? "…" : String(v);
    };

    const optRows: OptRow[] = [
        {
            kind: "input",
            label: t.home.optModel,
            get: optModel,
            set: setOptModel,
            placeholder: () => def("model"),
        },
        {
            kind: "select",
            label: t.home.optLang,
            get: optLang,
            set: setOptLang,
            defaultLabel: () => `${t.home.optDefault}（${def("target_lang")}）`,
            choices: TARGET_LANGS.map((l) => ({ value: l, label: l })),
        },
        {
            kind: "select",
            label: t.home.optEngine,
            get: optEngine,
            set: setOptEngine,
            defaultLabel: () => `${t.home.optDefault}（${def("engine")}）`,
            choices: ENGINES.map((en) => ({
                value: en,
                label: en === "auto" ? t.home.engineAuto : en,
            })),
        },
        {
            kind: "input",
            type: "number",
            min: 1,
            max: 16,
            label: t.home.optConcurrency,
            get: optConcurrency,
            set: setOptConcurrency,
            placeholder: () => def("concurrency"),
        },
        {
            kind: "select",
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
            kind: "select",
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
            kind: "select",
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
            kind: "select",
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
            kind: "select",
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
            kind: "select",
            adv: true,
            label: t.home.optSource,
            get: optSource,
            set: setOptSource,
            choices: [
                { value: "eprint", label: t.home.srcEprint },
                { value: "html", label: t.home.srcHtml },
            ],
        },
        {
            kind: "select",
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

    /** 单行 label+控件渲染——两组共用 */
    const optRow = (row: OptRow) => (
        <label classList={{ span2: !!row.span2 }}>
            <span>
                {row.label}
                <Show when={row.hint}>
                    <em class="muted">{row.hint}</em>
                </Show>
            </span>
            {optControl(row)}
        </label>
    );

    /** 整页拖放上传：仅拦截文件拖拽（文本拖入输入框不受影响） */
    let dragDepth = 0;
    const hasFile = (e: DragEvent) =>
        [...(e.dataTransfer?.types ?? [])].includes("Files");

    return (
        <main
            class="home"
            classList={{ "drop-on": dragOn() }}
            onDragEnter={(e) => {
                if (!hasFile(e)) return;
                e.preventDefault();
                dragDepth++;
                setDragOn(true);
            }}
            onDragOver={(e) => {
                if (hasFile(e)) e.preventDefault();
            }}
            onDragLeave={() => {
                if (--dragDepth <= 0) {
                    dragDepth = 0;
                    setDragOn(false);
                }
            }}
            onDrop={(e) => {
                if (!hasFile(e)) return;
                e.preventDefault();
                dragDepth = 0;
                setDragOn(false);
                const files = [...(e.dataTransfer?.files ?? [])];
                if (!files.length) return;
                if (busy()) {
                    setError(t.home.dropBusy);
                    return;
                }
                void uploadBatch(files);
            }}
        >
            <section class="hero">
                <h1 class="wordmark">
                    {t.appName} <span class="tagline">{t.tagline}</span>
                </h1>
                <form
                    class="arxiv-form"
                    onSubmit={(e) => {
                        e.preventDefault();
                        void submit();
                    }}
                >
                    <div class="arxiv-field">
                        <input
                            class="arxiv-input"
                            placeholder={t.home.arxivPlaceholder}
                            aria-label={t.home.arxivLabel}
                            aria-invalid={idBad()}
                            role="combobox"
                            aria-autocomplete="list"
                            aria-expanded={hits() !== null}
                            aria-controls="ax-suggest"
                            aria-activedescendant={
                                activeHit() >= 0
                                    ? `ax-sug-${activeHit()}`
                                    : undefined
                            }
                            autocapitalize="off"
                            value={arxivId()}
                            onInput={(e) => onIdInput(e.currentTarget.value)}
                            onBlur={() => setSuggest(null)}
                            onKeyDown={onSuggestKey}
                            spellcheck={false}
                        />
                        <Show when={hits() !== null}>
                            <ul
                                class="ax-suggest"
                                id="ax-suggest"
                                role="listbox"
                            >
                                <Show
                                    when={hits()!.length}
                                    fallback={
                                        <li
                                            class="ax-suggest-empty"
                                            role="presentation"
                                        >
                                            {t.home.axSearchEmpty}
                                        </li>
                                    }
                                >
                                    <For each={hits()!}>
                                        {(h, i) => (
                                            <li role="presentation">
                                                {/* mousedown 抢在 blur 前——阻止焦点转移
                                                    保住 click；blur 本身管「点外面关」 */}
                                                <button
                                                    type="button"
                                                    id={`ax-sug-${i()}`}
                                                    role="option"
                                                    aria-selected={
                                                        activeHit() === i()
                                                    }
                                                    class="ax-suggest-item"
                                                    classList={{
                                                        on: activeHit() === i(),
                                                    }}
                                                    onPointerEnter={() =>
                                                        setActiveHit(i())
                                                    }
                                                    onMouseDown={(e) =>
                                                        e.preventDefault()
                                                    }
                                                    onClick={() => pickHit(h)}
                                                >
                                                    <span class="ax-suggest-title">
                                                        {h.title ?? h.paperId}
                                                    </span>
                                                    <Show when={h.snippet}>
                                                        <span class="ax-suggest-snippet">
                                                            {h.snippet}
                                                        </span>
                                                    </Show>
                                                </button>
                                                <button
                                                    type="button"
                                                    class="btn-ghost ax-suggest-go"
                                                    onMouseDown={(e) =>
                                                        e.preventDefault()
                                                    }
                                                    onClick={() =>
                                                        props.nav(
                                                            `#/arxiv/${h.paperId}`,
                                                        )
                                                    }
                                                >
                                                    {t.home.translate}
                                                </button>
                                            </li>
                                        )}
                                    </For>
                                </Show>
                            </ul>
                        </Show>
                    </div>
                    <button
                        type="submit"
                        class="btn-primary"
                        disabled={busy()}
                        ref={(el) => (submitBtn = el)}
                    >
                        {busy() && !uploading()
                            ? t.home.submitting
                            : t.home.translate}
                    </button>
                    <button
                        type="button"
                        class="btn-ghost"
                        disabled={busy()}
                        onClick={() => fileInput?.click()}
                    >
                        {uploading() ? t.home.uploading : t.home.upload}
                    </button>
                    <input
                        ref={(el) => (fileInput = el)}
                        type="file"
                        hidden
                        multiple
                        accept=".pdf,.tex,.tar,.gz,.tgz,.zip,.docx,.epub"
                        onChange={(e) => {
                            const files = [...(e.currentTarget.files ?? [])];
                            if (files.length) void uploadBatch(files);
                            e.currentTarget.value = "";
                        }}
                    />
                </form>
                <Show when={error()}>
                    <p class="form-error" role="alert">
                        {error()}
                    </p>
                </Show>
                <Show when={uploading()}>
                    <div class="up-progress">
                        <div
                            class="up-bar"
                            classList={{ indet: upPct() < 0 || upPct() >= 100 }}
                            role="progressbar"
                            aria-label={t.home.upload}
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-valuenow={
                                upPct() >= 0 && upPct() < 100
                                    ? upPct()
                                    : undefined
                            }
                        >
                            <i
                                style={{
                                    width:
                                        upPct() < 0 || upPct() >= 100
                                            ? "35%"
                                            : `${upPct()}%`,
                                }}
                            />
                        </div>
                        <span class="up-label" aria-live="polite">
                            {/* 100% = 字节已送完、服务端建单中——回不定态防「卡 100%」错觉 */}
                            {upPct() >= 100
                                ? t.home.processing
                                : upPct() >= 0
                                  ? t.home.uploadPct.replace(
                                        "{n}",
                                        String(upPct()),
                                    )
                                  : t.home.uploading}
                        </span>
                    </div>
                </Show>
                <p class="muted upload-formats">
                    {t.home.formats}
                    <span class="drop-hint">{t.home.dropHint}</span>
                </p>
                <details class="task-opts">
                    <summary>{t.home.options}</summary>
                    <div class="opts-grid">
                        <For each={optCommon}>{optRow}</For>
                    </div>
                    <details class="opts-adv">
                        <summary>{t.home.optsAdvanced}</summary>
                        <div class="opts-grid">
                            <For each={optAdv}>{optRow}</For>
                        </div>
                    </details>
                </details>
                <p
                    class="health"
                    role="status"
                    classList={{
                        checking: healthPending(),
                        bad: !healthPending() && !health()?.ok,
                    }}
                >
                    <i class="dot" />
                    {healthPending()
                        ? t.home.healthChecking
                        : health()?.ok
                          ? t.home.healthOk
                          : t.home.healthBad}
                    <Show when={!healthPending() && health()?.ok}>
                        <span class="muted">
                            v{health()!.version ?? "?"} · {t.home.compilers}{" "}
                            {compilersStat()}
                        </span>
                    </Show>
                    <Show when={!healthPending() && !health()?.ok}>
                        <button
                            type="button"
                            class="btn-ghost health-retry"
                            onClick={() => {
                                setHealthPending(true);
                                void checkHealth();
                            }}
                        >
                            {t.home.retry}
                        </button>
                    </Show>
                </p>
            </section>

            <section class="home-tasks">
                <h2>
                    {t.home.tasks}
                    <Show
                        when={
                            taskStore.state.loaded &&
                            taskStore.state.tasks.length > 0
                        }
                    >
                        <span class="task-count">
                            {taskStore.state.tasks.length}
                        </span>
                    </Show>
                </h2>
                <Show when={taskStore.state.loadError}>
                    {(err) => (
                        <p class="form-error">
                            {t.home.loadFailed}：{err()}{" "}
                            <button
                                type="button"
                                class="btn-ghost"
                                onClick={() => void taskStore.refresh()}
                            >
                                {t.home.retry}
                            </button>
                        </p>
                    )}
                </Show>
                <Show
                    when={taskStore.state.loaded}
                    fallback={
                        <div class="skel-rows" aria-hidden="true">
                            <i />
                            <i />
                            <i />
                        </div>
                    }
                >
                    <TaskList tasks={taskStore.state.tasks} onOpen={open} />
                </Show>
            </section>

            {/* alphaXiv 热榜——机会型增强：上游失败/空结果整块不渲染。
                降级为列表下方横滚条，不抢自己任务的版面 */}
            <Show when={!feedFailed() && (feed()?.length ?? 0) > 0}>
                <section class="home-discover">
                    <h2>
                        {t.home.axTitle}
                        <span class="muted ax-via">{t.home.axVia}</span>
                    </h2>
                    <div class="ax-grid">
                        <For each={feed()!}>
                            {(p) => {
                                const id = cardId(p);
                                const visits = cardVisits(p);
                                return (
                                    <article class="ax-card">
                                        <Show when={p.image_url}>
                                            <img
                                                class="ax-thumb"
                                                src={p.image_url}
                                                alt=""
                                                loading="lazy"
                                                onError={(e) => {
                                                    e.currentTarget.style.display =
                                                        "none";
                                                }}
                                            />
                                        </Show>
                                        <h3 class="ax-card-title">{p.title}</h3>
                                        <Show when={cardDesc(p)}>
                                            <p class="ax-card-desc">
                                                {cardDesc(p)}
                                            </p>
                                        </Show>
                                        <div class="ax-card-foot">
                                            <Show when={visits != null}>
                                                <span class="muted">
                                                    {t.home.axViews.replace(
                                                        "{n}",
                                                        String(visits),
                                                    )}
                                                </span>
                                            </Show>
                                            <Show when={id}>
                                                <span class="ax-foot-actions">
                                                    <button
                                                        type="button"
                                                        class="btn-ghost ax-go"
                                                        onClick={() =>
                                                            props.nav(
                                                                `#/arxiv/${id}`,
                                                            )
                                                        }
                                                    >
                                                        {t.home.translate}
                                                    </button>
                                                    <a
                                                        class="ax-link"
                                                        href={`https://www.alphaxiv.org/abs/${id}`}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                    >
                                                        alphaXiv ↗
                                                    </a>
                                                </span>
                                            </Show>
                                        </div>
                                    </article>
                                );
                            }}
                        </For>
                    </div>
                </section>
            </Show>
        </main>
    );
}
