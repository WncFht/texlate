// Blender —— PDF 暗色渲染的图元级改色器(Zotero pdf.js fork 同款算法的
// 独立实现,非逐行 vendor:AGPL 规避 + TS 化 + 接我们的主题信号)。
//
// 原理:包住页面的 CanvasRenderingContext2D,在 draw 调用侧改色——
//   fillStyle/strokeStyle setter 拦截:中性色按亮度映到 bg→fg ramp;
//     彩色(chroma>10)走 Lab 空间保色相、chroma×1.2、亮度重定可读带。
//   fillText 前读文字中心处画布实际像素(局部底色感知),彩色高亮框
//     上的字从 {原色,bg,fg} 里挑对比最大者,不会糊。
//   drawImage 逐张分类:整页大图(扫描件)按亮度 invert 或 gradient
//     (白纸黑字扫描件直接纸色化);≤2 色小图(公式截图)近白→bg 近黑
//     →fg 替换;invertImages 档全反;其余(照片/彩图)0.8α 压暗保原色。
//
// 接入点见 pdfTheme.ts(实例级 pdfPage.render patch,免 fork pdf.js)。
// 打印/区域截图类逃生路径在 ctx 上置 skipBlender 即绕过。

interface LabTheme {
    background: string;
    foreground: string;
    invertImages?: boolean;
}

const Matrices = {
    linSRGBtoXYZ: [
        [0.41239079926595934, 0.357584339383878, 0.1804807884018343],
        [0.21263900587151027, 0.715168678767756, 0.07219231536073371],
        [0.01933081871559182, 0.11919477979462598, 0.9505321522496607],
    ],
    XYZtoLinSRGB: [
        [3.2409699419045226, -1.537383177570094, -0.4986107602930034],
        [-0.9692436362808796, 1.8759675015077202, 0.04155505740717559],
        [0.05563007969699366, -0.20397695888897652, 1.0569715142428786],
    ],
    D65toD50: [
        [1.0479298208405488, 0.022946793341019088, -0.05019222954313557],
        [0.029627815688159344, 0.990434484573249, -0.01707382502938514],
        [-0.009243058152591178, 0.015055144896577895, 0.7518742899580008],
    ],
    D50toD65: [
        [0.9554734527042182, -0.023098536874261423, 0.0632593086610217],
        [-0.028369706963208136, 1.0099954580058226, 0.021041398966943008],
        [0.012314001688319899, -0.020507696433477912, 1.3303659366080753],
    ],
    multiply(
        A: number[] | number[][],
        B: number[] | number[][],
    ): number[] | number[][] {
        const m = A.length;
        if (!Array.isArray(A[0])) A = [A as number[]];
        if (!Array.isArray(B[0])) B = (B as number[]).map((x) => [x]);
        const aM = A as number[][];
        const bM = B as number[][];
        const p = bM[0].length;
        const bCols = bM[0].map((_, i) => bM.map((x) => x[i]));
        let product: number[] | number[][] = aM.map((row) =>
            bCols.map((col) =>
                row.reduce((a, c, i) => a + c * (col[i] || 0), 0),
            ),
        );
        if (m === 1) product = product[0] as number[];
        if (p === 1) return (product as number[][]).map((x) => x[0]);
        return product;
    },
};

const sRGB = {
    toXYZ_M: Matrices.multiply(
        Matrices.D65toD50,
        Matrices.linSRGBtoXYZ,
    ) as number[][],
    fromXYZ_M: Matrices.multiply(
        Matrices.XYZtoLinSRGB,
        Matrices.D50toD65,
    ) as number[][],
    D50: [0.3457 / 0.3585, 1.0, (1.0 - 0.3457 - 0.3585) / 0.3585],
    EPS: 216 / 24389,
    EPS3: 24 / 116,
    KAPPA: 24389 / 27,
    toLab(rgb: number[]): number[] {
        return this.XYZtoLab(this.toXYZ(this.toLinear(rgb)));
    },
    toLinear(rgb: number[]): number[] {
        return rgb.map((val) => {
            const sign = val < 0 ? -1 : 1;
            const abs = Math.abs(val);
            if (abs < 0.04045) return val / 12.92;
            return sign * Math.pow((abs + 0.055) / 1.055, 2.4);
        });
    },
    toXYZ(lin: number[]): number[] {
        return Matrices.multiply(this.toXYZ_M, lin) as number[];
    },
    XYZtoLab(xyz: number[]): number[] {
        const f = xyz.map((v, i) => {
            const x = v / this.D50[i];
            return x > this.EPS ? Math.cbrt(x) : (this.KAPPA * x + 16) / 116;
        });
        return [116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])];
    },
    fromLab(lab: number[]): number[] {
        return this.toGamma(this.fromXYZ(this.LabToXYZ(lab)));
    },
    LabToXYZ(lab: number[]): number[] {
        const f1 = (lab[0] + 16) / 116;
        const f0 = lab[1] / 500 + f1;
        const f2 = f1 - lab[2] / 200;
        const xyz = [
            f0 > this.EPS3 ? f0 ** 3 : (116 * f0 - 16) / this.KAPPA,
            lab[0] > 8 ? Math.pow((lab[0] + 16) / 116, 3) : lab[0] / this.KAPPA,
            f2 > this.EPS3 ? f2 ** 3 : (116 * f2 - 16) / this.KAPPA,
        ];
        return xyz.map((v, i) => v * this.D50[i]);
    },
    fromXYZ(xyz: number[]): number[] {
        return Matrices.multiply(this.fromXYZ_M, xyz) as number[];
    },
    toGamma(rgb: number[]): number[] {
        return rgb.map((val) => {
            const sign = val < 0 ? -1 : 1;
            const abs = Math.abs(val);
            if (abs > 0.0031308)
                return sign * (1.055 * Math.pow(abs, 1 / 2.4) - 0.055);
            return 12.92 * val;
        });
    },
};

class Color {
    private _rgb?: number[];
    private _lab?: number[];
    private _hex?: string;
    private _alpha?: number;

    constructor(rgb: number[]);
    constructor(coords: number[], space: "lab");
    constructor(str: string);
    constructor(a: number[] | string, space?: "lab") {
        if (Array.isArray(a)) {
            if (space === "lab") this._lab = a;
            else this._rgb = a;
        } else {
            const str = a.trim();
            if (str.startsWith("#")) {
                const exp =
                    str.length === 4
                        ? "#" + [...str.slice(1)].map((c) => c + c).join("")
                        : str;
                this._hex = exp;
                this._rgb = Color.parseHex(exp);
            } else if (str.startsWith("rgb(")) {
                this._rgb = Color.parseRGB(str);
            } else if (str.startsWith("rgba(")) {
                [this._rgb, this._alpha] = Color.parseRGBA(str);
            }
            // 字符串解析失败的兜底只在字符串路径生效——lab 构造走惰性
            // _rgb??=fromLab,提前填黑会短路换算(gradient 恒黑的根因)
            this._rgb ??= [0, 0, 0];
        }
    }

    get hex(): string {
        this._hex ??= this.toHex();
        return this._hex;
    }
    get rgb(): number[] {
        this._rgb ??= sRGB.fromLab(this._lab!);
        return this._rgb;
    }
    get lab(): number[] {
        this._lab ??= sRGB.toLab(this._rgb!);
        return this._lab;
    }
    get lightness(): number {
        return this.lab[0];
    }
    get chroma(): number {
        const [, a, b] = this.lab;
        return Math.sqrt(a ** 2 + b ** 2);
    }
    get alpha(): number {
        return this._alpha ?? 1;
    }

    deltaE(other: Color): number {
        return Math.sqrt(
            this.lab.reduce(
                (acc, c, i) =>
                    isNaN(c) || isNaN(other.lab[i])
                        ? acc
                        : acc + (other.lab[i] - c) ** 2,
                0,
            ),
        );
    }

    range(other: Color): (p: number) => Color {
        return (p) =>
            new Color(
                this.lab.map((s, i) => {
                    const e = other.lab[i];
                    if (isNaN(s)) return e;
                    if (isNaN(e)) return s;
                    return s + (e - s) * p;
                }),
                "lab",
            );
    }

    toHex(alpha = 1): string {
        let hex = this.rgb.map(Color.compToHex).join("");
        if (alpha !== 1 && !isNaN(alpha)) hex += Color.compToHex(alpha);
        return "#" + hex;
    }

    static parseHex(str: string): number[] {
        const out: number[] = [];
        for (const m of str.matchAll(/[a-f0-9]{2}/gi))
            out.push(parseInt(m[0], 16) / 255);
        return out.slice(0, 3);
    }
    static parseRGB(str: string): number[] {
        return Color.parseRGBA(str.replace("rgb", "rgba"))[0];
    }
    static parseRGBA(str: string): [number[], number] {
        const parts = str.slice(str.indexOf("(") + 1, -1).split(",");
        // rgb() 只有三分量:alpha 缺省=1,否则 NaN 会经 toHex 拼出非法串
        // 被 canvas 静默忽略(保持旧值=默认黑,整页漆黑的根因)
        const alpha = parts.length > 3 ? parseFloat(parts[3]) : 1;
        return [
            parts.slice(0, 3).map((c) => parseInt(c) / 255),
            isNaN(alpha) ? 1 : alpha,
        ];
    }
    static compToHex(c: number): string {
        return Math.round(Math.min(Math.max(c * 255, 0), 255))
            .toString(16)
            .padStart(2, "0");
    }
    static white = new Color([1, 1, 1]);
}

export class Blender {
    pageWidth = 0;
    pageHeight = 0;

    private ctx: CanvasRenderingContext2D;
    private styleCache = new Map<string, Color>();
    private background!: Color;
    private foreground!: Color;
    private gradient!: (p: number) => Color;
    private dark = false;
    private forceInversion = false;
    private fullPageImageDetected = false;
    private hasBackgrounds = false;
    private cachedImage?: ImageData;

    private origFill: (...a: unknown[]) => void;
    private origFillRect: CanvasRenderingContext2D["fillRect"];
    private origStroke: (...a: unknown[]) => void;
    private origStrokeRect: CanvasRenderingContext2D["strokeRect"];
    private origFillText: CanvasRenderingContext2D["fillText"];
    private origDrawImage: (...a: unknown[]) => void;
    private origFillStyle: (v: string | CanvasGradient | CanvasPattern) => void;

    constructor(ctx: CanvasRenderingContext2D, theme: LabTheme) {
        this.ctx = ctx;
        this.setTheme(theme);

        this.origFill = ctx.fill.bind(ctx) as (...a: unknown[]) => void;
        this.origFillRect = ctx.fillRect.bind(ctx);
        this.origStroke = ctx.stroke.bind(ctx) as (...a: unknown[]) => void;
        this.origStrokeRect = ctx.strokeRect.bind(ctx);
        this.origFillText = ctx.fillText.bind(ctx);
        this.origDrawImage = ctx.drawImage.bind(ctx) as (
            ...a: unknown[]
        ) => void;
        this.origFillStyle = this.interceptStyle(ctx, "fillStyle");
        this.interceptStyle(ctx, "strokeStyle");

        ctx.fill = ((...a: unknown[]) => {
            this.origFill(...a);
            delete this.cachedImage;
        }) as typeof ctx.fill;
        ctx.fillRect = (x: number, y: number, w: number, h: number) => {
            this.origFillRect(x, y, w, h);
            delete this.cachedImage;
        };
        ctx.stroke = ((...a: unknown[]) => {
            this.origStroke(...a);
            delete this.cachedImage;
        }) as typeof ctx.stroke;
        ctx.strokeRect = (x: number, y: number, w: number, h: number) => {
            this.origStrokeRect(x, y, w, h);
            delete this.cachedImage;
        };
        ctx.fillText = (
            text: string,
            x: number,
            y: number,
            maxWidth?: number,
        ) => {
            if (typeof ctx.fillStyle !== "string") {
                return this.origFillText(text, x, y, maxWidth);
            }
            ctx.save();
            this.updateTextStyle(text, x, y);
            this.origFillText(text, x, y, maxWidth);
            ctx.restore();
        };
        ctx.drawImage = ((...a: unknown[]) =>
            this.customDrawImage(a)) as typeof ctx.drawImage;
    }

    // 主题换代:不重装拦截器,只换色板——PdfPane 主题切换后既有 ctx 直接续用
    setTheme(theme: LabTheme) {
        this.background = new Color(theme.background);
        this.foreground = new Color(theme.foreground);
        this.gradient = this.background.range(this.foreground);
        this.dark = this.background.lightness < this.foreground.lightness;
        this.forceInversion = !!theme.invertImages;
        this.fullPageImageDetected = false;
        this.styleCache.clear();
    }

    private interceptStyle(
        ctx: CanvasRenderingContext2D,
        prop: "fillStyle" | "strokeStyle",
    ) {
        const proto = Object.getPrototypeOf(ctx) as CanvasRenderingContext2D;
        const descriptor = Object.getOwnPropertyDescriptor(proto, prop)!;
        const originalGet = descriptor.get!;
        const originalSet = descriptor.set!;
        Object.defineProperty(ctx, prop, {
            get: () => originalGet.call(ctx),
            set: (v: string | CanvasGradient | CanvasPattern) => {
                originalSet.call(ctx, v);
                const cur = originalGet.call(ctx);
                const mapped = this.getCanvasStyle(cur);
                if (mapped !== undefined) originalSet.call(ctx, mapped);
            },
            configurable: true,
            enumerable: true,
        });
        return (v: string | CanvasGradient | CanvasPattern) => {
            originalSet.call(ctx, v);
        };
    }

    private updateTextStyle(text: string, x: number, y: number) {
        const style = this.ctx.fillStyle;
        if (!this.hasBackgrounds) return;
        const bg = this.getCanvasColor(text, x, y);
        const mapped = this.getCanvasStyle(style, bg);
        if (mapped !== style) this.origFillStyle(mapped!);
    }

    private getCanvasStyle(
        style: string | CanvasGradient | CanvasPattern,
        bg?: Color,
    ): string | undefined {
        if (typeof style !== "string") return;
        const c = new Color(style);
        const key = c.hex + (bg?.hex || "");
        let out = this.styleCache.get(key);
        if (!out) {
            out = bg ? this.getTextStyle(c, bg) : this.calcStyle(c);
            this.styleCache.set(key, out);
        }
        return out.toHex(c.alpha);
    }

    private calcStyle(color: Color): Color {
        if (color.chroma > 10) {
            if (this.dark) {
                return this.adjustColorForVisibility(
                    this.foreground.hex,
                    color.hex,
                );
            }
            return color;
        }
        const whiteL = Color.white.lightness;
        return this.gradient(1 - color.lightness / whiteL);
    }

    private getTextStyle(color: Color, textBg: Color, minContrast = 30): Color {
        const diffL = (c: Color) => Math.abs(c.lightness - textBg.lightness);
        if (
            this.background.deltaE(textBg) > 2.3 &&
            diffL(color) < minContrast
        ) {
            return [color, this.background, this.foreground].reduce(
                (best, c) => (diffL(c) > diffL(best) ? c : best),
            );
        }
        return color;
    }

    private distinctColors(imageData: ImageData, cutoff: number): number {
        const { data } = imageData;
        const set = new Set<number>();
        for (let i = 0; i < data.length; i += 4) {
            const key =
                (((data[i] & 0xff) << 24) |
                    ((data[i + 1] & 0xff) << 16) |
                    ((data[i + 2] & 0xff) << 8) |
                    0xff) >>>
                0;
            set.add(key);
            if (set.size >= cutoff) return set.size;
        }
        return set.size;
    }

    private neutralRatio(
        imageData: ImageData,
        deviation = 12,
        step = 16,
    ): number {
        const { data } = imageData;
        let neutral = 0;
        let total = 0;
        for (let i = 0; i < data.length; i += 4 * step) {
            if (data[i + 3] < 32) continue;
            total++;
            if (this.isNeutral(data[i], data[i + 1], data[i + 2], deviation))
                neutral++;
        }
        return total ? neutral / total : 0;
    }

    private averageLightness(imageData: ImageData): number {
        const { data } = imageData;
        let sum = 0;
        for (let i = 0; i < data.length; i += 4) {
            let r = data[i];
            let g = data[i + 1];
            let b = data[i + 2];
            if (data[i + 3] < 64) {
                r = 255;
                g = 255;
                b = 255;
            }
            sum = (sum + 2126 * r + 7152 * g + 722 * b) >>> 0;
        }
        return Math.round(sum / (data.length >> 2) / 10000);
    }

    private transformedBBox(
        dx: number,
        dy: number,
        dWidth: number,
        dHeight: number,
    ) {
        const tp = (x: number, y: number) => {
            const m = this.ctx.getTransform();
            return { x: m.a * x + m.c * y + m.e, y: m.b * x + m.d * y + m.f };
        };
        const p1 = tp(dx, dy);
        const p2 = tp(dx + dWidth, dy);
        const p3 = tp(dx, dy + dHeight);
        const p4 = tp(dx + dWidth, dy + dHeight);
        const minX = Math.min(p1.x, p2.x, p3.x, p4.x);
        const maxX = Math.max(p1.x, p2.x, p3.x, p4.x);
        const minY = Math.min(p1.y, p2.y, p3.y, p4.y);
        const maxY = Math.max(p1.y, p2.y, p3.y, p4.y);
        return { width: maxX - minX, height: maxY - minY };
    }

    private customDrawImage(args: unknown[]) {
        this.hasBackgrounds = true;
        delete this.cachedImage;
        const img = args[0] as CanvasImageSource | null;
        if (!img) {
            this.origDrawImage(...args);
            return;
        }
        const [bgR, bgG, bgB] = this.background.rgb.map((e) => e * 255);
        const [fgR, fgG, fgB] = this.foreground.rgb.map((e) => e * 255);
        let sx: number, sy: number, sWidth: number, sHeight: number;
        let dx: number, dy: number, dWidth: number, dHeight: number;
        const iw =
            (img as HTMLImageElement).naturalWidth ||
            (img as HTMLCanvasElement).width;
        const ih =
            (img as HTMLImageElement).naturalHeight ||
            (img as HTMLCanvasElement).height;
        if (args.length === 3) {
            [dx, dy] = args.slice(1) as [number, number];
            sWidth = iw;
            sHeight = ih;
            [sx, sy, dWidth, dHeight] = [0, 0, sWidth, sHeight];
        } else if (args.length === 5) {
            [dx, dy, dWidth, dHeight] = args.slice(1) as [
                number,
                number,
                number,
                number,
            ];
            sWidth = iw;
            sHeight = ih;
            [sx, sy] = [0, 0];
        } else if (args.length === 9) {
            [sx, sy, sWidth, sHeight, dx, dy, dWidth, dHeight] = args.slice(
                1,
            ) as number[] as [
                number,
                number,
                number,
                number,
                number,
                number,
                number,
                number,
            ];
        } else {
            this.origDrawImage(...args);
            return;
        }
        const pageWidth = this.pageWidth || this.ctx.canvas.width;
        const pageHeight = this.pageHeight || this.ctx.canvas.height;
        const { width, height } = this.transformedBBox(dx, dy, dWidth, dHeight);
        const entirePage =
            Math.abs(pageWidth * pageHeight - width * height) <
            pageWidth * pageHeight * 0.25;

        const offCanvas = document.createElement("canvas");
        offCanvas.width = sWidth;
        offCanvas.height = sHeight;
        const offCtx = offCanvas.getContext("2d")!;
        offCtx.drawImage(img, sx, sy, sWidth, sHeight, 0, 0, sWidth, sHeight);
        const imageData = offCtx.getImageData(0, 0, sWidth, sHeight);

        let type: "gradient" | "invert" | "replace" | "overlay" = "overlay";
        if (this.forceInversion) {
            type = "invert";
        } else if (entirePage) {
            const lightness = this.averageLightness(imageData);
            if (!this.fullPageImageDetected) {
                this.fullPageImageDetected = true;
                if (this.dark && lightness >= 150) {
                    type = "invert";
                    this.forceInversion = true;
                }
            }
            if (
                !this.dark &&
                lightness >= 150 &&
                this.neutralRatio(imageData) >= 0.9
            ) {
                type = "gradient";
            }
        } else if (this.distinctColors(imageData, 3) <= 2) {
            type = "replace";
        }

        const data = imageData.data;
        const drawBack = () => {
            if (args.length === 3) this.origDrawImage(offCanvas, dx, dy);
            else if (args.length === 5)
                this.origDrawImage(offCanvas, dx, dy, dWidth, dHeight);
            else
                this.origDrawImage(
                    offCanvas,
                    0,
                    0,
                    sWidth,
                    sHeight,
                    dx,
                    dy,
                    dWidth,
                    dHeight,
                );
        };

        if (type === "gradient") {
            for (let i = 0; i < data.length; i += 4) {
                if (!data[i + 3]) continue;
                const r = data[i];
                const g = data[i + 1];
                const b = data[i + 2];
                if (!this.isNeutral(r, g, b, 12)) continue;
                const br = (r * 0.299 + g * 0.587 + b * 0.114) / 255;
                data[i] = Math.round(bgR + (fgR - bgR) * (1 - br));
                data[i + 1] = Math.round(bgG + (fgG - bgG) * (1 - br));
                data[i + 2] = Math.round(bgB + (fgB - bgB) * (1 - br));
            }
            offCtx.putImageData(imageData, 0, 0);
            drawBack();
        } else if (type === "replace") {
            for (let i = 0; i < data.length; i += 4) {
                const r = data[i];
                const g = data[i + 1];
                const b = data[i + 2];
                const avg = (r + g + b) / 3;
                const neutral = this.isNeutral(r, g, b, 1);
                if (neutral && avg > 200) {
                    data[i] = bgR;
                    data[i + 1] = bgG;
                    data[i + 2] = bgB;
                } else if (neutral && avg < 50) {
                    data[i] = fgR;
                    data[i + 1] = fgG;
                    data[i + 2] = fgB;
                }
            }
            offCtx.putImageData(imageData, 0, 0);
            drawBack();
        } else if (type === "invert") {
            for (let i = 0; i < data.length; i += 4) {
                const invR = 255 - data[i];
                const invG = 255 - data[i + 1];
                const invB = 255 - data[i + 2];
                const br = (invR * 0.299 + invG * 0.587 + invB * 0.114) / 255;
                const factor = (br - 0.5) * 2;
                let oR = invR;
                let oG = invG;
                let oB = invB;
                if (factor > 0) {
                    oR = invR + factor * (fgR - invR);
                    oG = invG + factor * (fgG - invG);
                    oB = invB + factor * (fgB - invB);
                } else if (factor < 0) {
                    const t = -factor;
                    oR = invR + t * (bgR - invR);
                    oG = invG + t * (bgG - invG);
                    oB = invB + t * (bgB - invB);
                }
                data[i] = Math.min(255, Math.max(0, Math.round(oR)));
                data[i + 1] = Math.min(255, Math.max(0, Math.round(oG)));
                data[i + 2] = Math.min(255, Math.max(0, Math.round(oB)));
            }
            offCtx.putImageData(imageData, 0, 0);
            drawBack();
        } else {
            this.ctx.globalCompositeOperation = "source-over";
            this.ctx.globalAlpha = entirePage ? 1 : 0.8;
            this.origDrawImage(...args);
        }
    }

    private isNeutral(r: number, g: number, b: number, dev: number): boolean {
        return (
            Math.abs(r - g) < dev &&
            Math.abs(r - b) < dev &&
            Math.abs(g - b) < dev
        );
    }

    private getCanvasColor(text: string, tx: number, ty: number): Color {
        this.cachedImage ??= this.ctx.getImageData(
            0,
            0,
            this.ctx.canvas.width,
            this.ctx.canvas.height,
        );
        const mtr = this.ctx.measureText(text);
        const dx = mtr.width / 2;
        const dy =
            (mtr.actualBoundingBoxAscent - mtr.actualBoundingBoxDescent) / 2;
        const tfm = this.ctx.getTransform();
        const { x, y } = tfm.transformPoint({ x: tx + dx, y: ty - dy });
        const xi = Math.round(x);
        const yi = Math.round(y);
        const cw = this.ctx.canvas.width;
        const ch = this.ctx.canvas.height;
        if (xi < 0 || yi < 0 || xi >= cw || yi >= ch)
            return new Color([0, 0, 0]);
        const idx = (yi * cw + xi) * 4;
        const d = this.cachedImage.data;
        return new Color([d[idx] / 255, d[idx + 1] / 255, d[idx + 2] / 255]);
    }

    private adjustColorForVisibility(background: string, color: string): Color {
        const bg = new Color(background);
        const fg = new Color(color);
        const [, origA, origB] = fg.lab;
        const origChroma = Math.sqrt(origA ** 2 + origB ** 2);
        const hue = origChroma > 0 ? Math.atan2(origB, origA) : 0;
        const targetL =
            bg.lightness < 50
                ? 50 + (100 - bg.lightness) * 0.3
                : 25 + bg.lightness * 0.3;
        const targetChroma = Math.max(origChroma * 1.2, 20);
        return new Color(
            [
                targetL,
                Math.cos(hue) * targetChroma,
                Math.sin(hue) * targetChroma,
            ],
            "lab",
        );
    }
}

export type { LabTheme as PdfPageTheme };
