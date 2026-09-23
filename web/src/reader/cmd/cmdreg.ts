// cmdreg —— 命令注册表内核（sel-system Wave B 基座）。
// 移植 exp/ss-cmdreg/cmdreg.ts，按落地规格扩展：
//   Command = {id,title,when,enableWhen,keys,sec,bar,run(ctx)}
//   - when       : VS Code 风字符串谓词——数据非闭包，可序列化/可静态审计；
//                  注册即编译，坏语法在注册期爆而非用户右键时爆。
//   - enableWhen : 「disabled 不 hidden」面（menu-spec 的 chunk.retx
//                  seq∈pending 语义）；缺省=启用。
//   - sec        : 菜单分段（sel/cite/math/chunk/pane/…自由扩展）——入口按
//                  段间插分隔线，段内保持注册序。
//   - bar        : FloatBar 候选标记（true=划词条可收）。
//   Registry: register/unregister/eval(ctx) + enabled/visible/byKey/run。
//   whenKeys(src) 抽静态引用键，auditWhenKeys(cmds, ctxKeys) 做
//   whenKeys⊆ctxKeys 审计（防拼写漂移——谓词键必须全部由快照供给）。
//
// when 语法（VS Code when-clause 子集）：
//   expr    := orExpr
//   orExpr  := andExpr ('||' andExpr)*
//   andExpr := unary  ('&&' unary)*
//   unary   := '!' unary | cmp
//   cmp     := primary (('=='|'!=') literal)?
//   primary := '(' expr ')' | key
//   literal := '...' | "..." | true | false
// key 在 ctx 中真值判定（JS truthy）；未提供的键 = falsy。

/** 上下文袋：谓词读的扁平键值集（hitctx.flattenCtx 产出）。 */
export type Ctx = Record<string, unknown>;

// ---------------------------------------------------------------- when 求值

type Tok =
    | { t: "key"; v: string }
    | { t: "lit"; v: string | boolean }
    | { t: "op"; v: "!" | "&&" | "||" | "==" | "!=" }
    | { t: "lp" }
    | { t: "rp" };

type Ast =
    | { k: "key"; v: string }
    | { k: "not"; a: Ast }
    | { k: "and" | "or"; a: Ast; b: Ast }
    | { k: "eq" | "ne"; a: Ast; b: string | boolean };

const TOKEN_RE =
    /\s*(?:(==|!=|&&|\|\||!)|([()])|('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|true|false)|([A-Za-z_][A-Za-z0-9_.-]*))/y;

function lex(src: string): Tok[] {
    const toks: Tok[] = [];
    let i = 0;
    while (i < src.length) {
        TOKEN_RE.lastIndex = i;
        const m = TOKEN_RE.exec(src);
        if (!m || m.index !== i)
            throw new Error(`when: bad token at ${i} in ${JSON.stringify(src)}`);
        i = TOKEN_RE.lastIndex;
        if (m[1])
            toks.push({
                t: "op",
                v: m[1] as "!" | "&&" | "||" | "==" | "!=",
            });
        else if (m[2] === "(") toks.push({ t: "lp" });
        else if (m[2] === ")") toks.push({ t: "rp" });
        else if (m[3] !== undefined) {
            const s = m[3];
            toks.push({
                t: "lit",
                v:
                    s === "true"
                        ? true
                        : s === "false"
                          ? false
                          : s.slice(1, -1).replace(/\\(.)/g, "$1"),
            });
        } else toks.push({ t: "key", v: m[4]! });
    }
    return toks;
}

function parse(src: string): Ast {
    const toks = lex(src);
    let p = 0;
    const peek = () => toks[p];
    const eat = () => toks[p++];
    const orExpr = (): Ast => {
        let a = andExpr();
        while (peek()?.t === "op" && (peek() as { v: string }).v === "||") {
            eat();
            a = { k: "or", a, b: andExpr() };
        }
        return a;
    };
    const andExpr = (): Ast => {
        let a = unary();
        while (peek()?.t === "op" && (peek() as { v: string }).v === "&&") {
            eat();
            a = { k: "and", a, b: unary() };
        }
        return a;
    };
    const unary = (): Ast => {
        const t = peek();
        if (t?.t === "op" && t.v === "!") {
            eat();
            return { k: "not", a: unary() };
        }
        return cmp();
    };
    const cmp = (): Ast => {
        const a = primary();
        const t = peek();
        if (t?.t === "op" && (t.v === "==" || t.v === "!=")) {
            eat();
            const l = eat();
            if (l?.t !== "lit")
                throw new Error(
                    `when: ${t.v} needs literal, got ${JSON.stringify(l)}`,
                );
            return { k: t.v === "==" ? "eq" : "ne", a, b: l.v };
        }
        return a;
    };
    const primary = (): Ast => {
        const t = eat();
        if (!t) throw new Error("when: unexpected end");
        if (t.t === "key") return { k: "key", v: t.v };
        if (t.t === "lp") {
            const a = orExpr();
            const r = eat();
            if (r?.t !== "rp") throw new Error("when: missing )");
            return a;
        }
        throw new Error(`when: unexpected ${JSON.stringify(t)}`);
    };
    const ast = orExpr();
    if (p !== toks.length)
        throw new Error(`when: trailing tokens in ${JSON.stringify(src)}`);
    return ast;
}

function ev(a: Ast, ctx: Ctx): boolean {
    switch (a.k) {
        case "key":
            return !!ctx[a.v];
        case "not":
            return !ev(a.a, ctx);
        case "and":
            return ev(a.a, ctx) && ev(a.b, ctx);
        case "or":
            return ev(a.a, ctx) || ev(a.b, ctx);
        case "eq":
            return eqVal(a.a, ctx) === a.b;
        case "ne":
            return eqVal(a.a, ctx) !== a.b;
    }
}
const eqVal = (a: Ast, ctx: Ctx) =>
    a.k === "key" ? (ctx[a.v] as string | boolean) : ev(a, ctx);

/** when 源码 → 编译后谓词。缓存：菜单/键位/面板入口共享同一编译面。 */
const whenCache = new Map<string, (ctx: Ctx) => boolean>();
export const whenCacheSize = () => whenCache.size;

/** 编译 when 源串（坏语法抛错）。求值：evalWhen(src, ctx)。 */
export function compileWhen(src: string): (ctx: Ctx) => boolean {
    let f = whenCache.get(src);
    if (!f) {
        const ast = parse(src);
        f = (ctx) => ev(ast, ctx);
        whenCache.set(src, f);
    }
    return f;
}

/** 一次性求值入口——等价 compileWhen(src)(ctx)。 */
export function evalWhen(src: string, ctx: Ctx): boolean {
    return compileWhen(src)(ctx);
}

/** 静态审计用：抽出 when 表达式引用的全部 ctx 键。 */
export function whenKeys(src: string): string[] {
    const out: string[] = [];
    const walk = (a: Ast) => {
        if (a.k === "key") out.push(a.v);
        else if (a.k === "not") walk(a.a);
        else if (a.k === "and" || a.k === "or") {
            walk(a.a);
            walk(a.b);
        } else walk(a.a);
    };
    walk(parse(src));
    return out;
}

// ---------------------------------------------------------------- 命令表

export interface Command<C extends Ctx = Ctx> {
    id: string;
    /** 菜单/浮条显示名——落地形态 = i18n key（如 "menu.sel.copy"），
        由宿主经 t() 解析；menu-spec 的双语串存 MENU_LABELS。 */
    title: string;
    /** when 谓词源串（可见性闸）；省略 = 恒可见（全局命令） */
    when?: string;
    /** 启用谓词（可选）——可见但禁用态：menu-spec「disabled 不 hidden」 */
    enableWhen?: string;
    /** 键位 chord（"ctrl+f"/"alt+arrowleft"/"s"）；菜单 hint + byKey 分派 */
    keys?: string[];
    /** 菜单分段 id（"sel"/"cite"/"math"/"chunk"/"pane"…）；段间插分隔线 */
    sec?: string;
    /** FloatBar 候选——true 且启用时浮条可收（取启用 sec 序前 N 个） */
    bar?: boolean;
    run(ctx: C): void | Promise<void>;
}

export class Registry<C extends Ctx = Ctx> {
    private cmds: Command<C>[] = [];
    private byId = new Map<string, Command<C>>();

    register(cmd: Command<C>): this {
        if (this.byId.has(cmd.id))
            throw new Error(`cmdreg: duplicate id ${cmd.id}`);
        // 注册即编译——坏 when 在启动期爆，不在用户右键时爆
        if (cmd.when !== undefined) compileWhen(cmd.when);
        if (cmd.enableWhen !== undefined) compileWhen(cmd.enableWhen);
        this.cmds.push(cmd);
        this.byId.set(cmd.id, cmd);
        return this;
    }
    registerAll(cmds: Command<C>[]): this {
        for (const c of cmds) this.register(c);
        return this;
    }
    /** 摘命令（Wave C lane 动态挂载/卸载用）。返回是否曾有此 id。 */
    unregister(id: string): boolean {
        const c = this.byId.get(id);
        if (!c) return false;
        this.byId.delete(id);
        this.cmds = this.cmds.filter((x) => x !== c);
        return true;
    }

    /** when 通过（可见）的命令集，注册序。 */
    visible(ctx: C): Command<C>[] {
        return this.cmds.filter(
            (c) => c.when === undefined || compileWhen(c.when)(ctx),
        );
    }
    /** when+enableWhen 双过（可执行）的命令集，注册序。 */
    enabled(ctx: C): Command<C>[] {
        return this.visible(ctx).filter((c) => this.isEnabled(c, ctx));
    }
    /** 单命令启用判定（visible 之上叠 enableWhen）。 */
    isEnabled(cmd: Command<C>, ctx: C): boolean {
        return (
            cmd.enableWhen === undefined || compileWhen(cmd.enableWhen)(ctx)
        );
    }
    /** eval(ctx)：谓词层对外统一求值口——返回「可见集」。 */
    eval(ctx: C): Command<C>[] {
        return this.visible(ctx);
    }
    get(id: string): Command<C> | undefined {
        return this.byId.get(id);
    }

    /** 键位分派：chord 命中且 when+enableWhen 通过的第一条（注册序优先） */
    byKey(chord: string, ctx: C): Command<C> | undefined {
        for (const c of this.cmds) {
            if (!c.keys?.includes(chord)) continue;
            if (c.when !== undefined && !compileWhen(c.when)(ctx)) continue;
            if (!this.isEnabled(c, ctx)) continue;
            return c;
        }
        return undefined;
    }

    async run(id: string, ctx: C): Promise<boolean> {
        const c = this.byId.get(id);
        if (!c) return false;
        if (c.when !== undefined && !compileWhen(c.when)(ctx)) return false;
        if (!this.isEnabled(c, ctx)) return false;
        await c.run(ctx);
        return true;
    }
    /** 不查 when/enableWhen 的强执（入口已过滤场景省一次求值） */
    async runUnchecked(id: string, ctx: C): Promise<boolean> {
        const c = this.byId.get(id);
        if (!c) return false;
        await c.run(ctx);
        return true;
    }

    get size(): number {
        return this.cmds.length;
    }
    all(): readonly Command<C>[] {
        return this.cmds;
    }
}

// ---------------------------------------------------------------- 静态审计

/**
 * whenKeys⊆ctxKeys 审计：命令表每条 when/enableWhen 引用的谓词键必须全部
 * 由 ctx 快照供给——拼写漂移（`cite.tagretKind`）在启动期被抓而非静默恒假。
 * @returns 违例列表 [{id, clause, keys}]；空数组 = 通过。
 */
export function auditWhenKeys(
    cmds: readonly Command[],
    ctxKeys: readonly string[],
): { id: string; clause: string; keys: string[] }[] {
    const produced = new Set(ctxKeys);
    const bad: { id: string; clause: string; keys: string[] }[] = [];
    for (const c of cmds) {
        for (const clause of ["when", "enableWhen"] as const) {
            const src = c[clause];
            if (src === undefined) continue;
            const missing = [...new Set(whenKeys(src))].filter(
                (k) => !produced.has(k),
            );
            if (missing.length)
                bad.push({ id: c.id, clause, keys: missing });
        }
    }
    return bad;
}
