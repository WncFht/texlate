// arxidcanon —— arXiv id canon 管线单源（中立叶：stores/reader/home 三层
// 共用，不属任一层，stores←reader 反向 import 禁区不经此）。
// 规格 = arxiv-id-canon-spec §2 剥离序（与服务端 arxiv/fetch.canon 同口径
// 的 JS 镜像）：trim → safe_id `--`→`/` 回流 → 锚定前缀循环剥至不动点 →
// ?# 截断 → 尾件剥（/、空白、[class] 尾注、扩展名循环）→ vN 钉版提取 →
// 旧形 class 剥壳 + archive 小写。
// 两口径：
//   宽松（canonStrip 缺省）——匹配键用：arxiv.org 臂 host `[\w.-]*` 收尾
//     不挡寄生域；只剥尾 /。坏输入只是匹配不上，宁宽不漏。
//   严格（canonStrip strict=true）——提交校验用：子域必须点界
//     （`[\w.-]+\.` 的 . 挡死 notarxiv.org 寄生域）+ ar5iv/alphaxiv 白名单
//     臂（scheme 必带、动词限 abs|pdf|html——/overview 等未实证动词不收）；
//     首尾 / 全剥。仍比服务端窄是刻意的——怪输入留给服务端 400。
// 消费面：stores/tasks.canonArxivKey、reader/citations.canonRefId（同键
// 两名）、home/search.parseArxivId（严格臂 + era 闸/vN 校验叠层）。
// 校验非本层职责——canonStrip 只做剥壳，坏输入剥完仍非 id，era/形判由
// 调用方叠（search.ts 的 YYMM 闸；服务端 normalize_arxiv_id 收口）。

// 前缀剥壳组（循环至不动点——`arXiv:10.48550/arXiv.…` 链式前缀逐层剥）。
const PREFIX_RXS_LOOSE: readonly RegExp[] = [
    /^(?:https?:\/\/)?[\w.-]*arxiv\.org\/(?:abs|pdf|src|e-print|html|format)\/+/i,
    /^https?:\/\/(?:dx\.|www\.)?doi\.org\//i,
    /^doi:\s*/i,
    /^10\.48550\/arxiv\./i,
    /^oai\s*:\s*arxiv\.org\s*:\s*/i,
    /^arxiv\s*[:.]\s*/i,
];
const PREFIX_RXS_STRICT: readonly RegExp[] = [
    /^(?:https?:\/\/)?(?:[\w.-]+\.)?arxiv\.org\/(?:abs|pdf|src|e-print|html|format)\/+/i,
    /^https?:\/\/(?:[\w.-]+\.)?(?:ar5iv|alphaxiv)\.org\/(?:abs|pdf|html)\/+/i,
    /^https?:\/\/(?:dx\.|www\.)?doi\.org\//i,
    /^doi:\s*/i,
    /^10\.48550\/ar[Xx]iv\./,
    /^oai\s*:\s*arxiv\.org\s*:\s*/i,
    /^arxiv\s*[:.]\s*/i,
];

// 尾件剥壳组（两口径同组）
const TAILNOTE_RX = /\s*\[[^\]]{1,20}\]\s*$/; // [cs.CL] 引用尾注
const EXT_RX = /\.(?:pdf|ps|eps|dvi|gz|tgz|tar\.gz)$/i; // 下载扩展名尾（循环剥：x.tar.gz 逐层）
const VER_RX = /^(.+?)[vV](\d{1,3})$/; // 版本尾 vN（4 位+/裸 v 不吃）
// 旧形剥 class：archive(.CLASS)?/NNNNNNN → archive/NNNNNNN + archive 小写
const CLASS_RX = /^([-a-zA-Z]+)(?:\.[A-Za-z][A-Za-z-]*)?\/(\d{7})$/;

export interface CanonStrip {
    /** canon base——钉版已剥、旧形 class 已除、archive 段小写（其余大小写
        保原——匹配键的整串小写归 canonArxivKey 收口） */
    base: string;
    /** 钉版号（无 vN 尾 → null；"v03"→3、"V"→v 归一由调用方重组实现） */
    ver: number | null;
}

/**
 * canon 剥壳共用段。strict=true 换严格前缀组 + 首尾 / 同剥（提交校验
 * 口径）；缺省宽松（匹配键口径）。剥壳只管形态归一——ver 合法性
 * （v0 拒）、id 形判、era 闸全是调用方叠层。
 */
export function canonStrip(raw: string, strict = false): CanonStrip {
    // 存储拼写回流：`--` 不可能出现在合法 id 内，unfold 无歧义
    let s = raw.trim().replace(/--/g, "/");
    // 前缀循环至不动点（URL/DOI/OAI/arXiv: 可叠套）
    const pfx = strict ? PREFIX_RXS_STRICT : PREFIX_RXS_LOOSE;
    for (;;) {
        const prev = s;
        for (const rx of pfx) s = s.replace(rx, "");
        if (s === prev) break;
    }
    s = s.replace(/[?#].*$/, "");
    s = strict ? s.trim().replace(/^\/+|\/+$/g, "") : s.replace(/[\s/]+$/, "");
    s = s.replace(TAILNOTE_RX, "");
    for (;;) {
        const t = s.replace(EXT_RX, "");
        if (t === s) break;
        s = t;
    }
    let ver: number | null = null;
    const vm = VER_RX.exec(s);
    if (vm) {
        ver = Number(vm[2]);
        s = vm[1];
    }
    const cm = CLASS_RX.exec(s);
    if (cm) s = `${cm[1].toLowerCase()}/${cm[2]}`;
    return { base: s, ver };
}

/**
 * arXiv id 匹配键（双侧归一比对专用）：宽松口径剥壳 + 整串小写。
 * taskByArxiv / canonRefId / preflight 三处同键——服务端落库 arxiv_id
 * 的历史行保留 class 与大小写、canon.base 是新形，两侧都过本函数才比，
 * 两种落库形同键。坏输入只是匹配不上（不抛错）。
 */
export function canonArxivKey(raw: string | null | undefined): string {
    if (raw == null) return "";
    return canonStrip(raw).base.toLowerCase();
}
