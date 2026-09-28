// follow —— 「跟手」数学原语组（motion-web references/handfeel.md §1/§3/§7
// 移植，全部写成帧率无关形式）。症状 → 用哪个：
//   「跟手但总差一点」——追移动目标稳态滞后 = speed/k，expFollow 的
//       targetVel（lead 项）精确抵消，不是把 k 调大（那会丢了柔软本身）。
//   「一抖一抖」——滤波后写入的量下一帧被滤波器拉回：一个量只能有
//       一个滤波器一个目标，修正项要烘进 target，不能写在滤波输出上。
//   「手感随帧率变」——x += d*0.1 在 30/60/120fps 是三个不同滤波器；
//       必须用 1-exp(-k·dt)（expFollow）或显式 ODE 步进（Spring）。
//   「四平八稳/落地没分量」——lerp 单调减速读作「滑」，欠阻尼弹簧
//       （Spring zeta<1）过冲后回稳读作「跳」。
//   「落点不该过冲」——UI chrome/相机/面板用临界阻尼（zeta=1）：照样
//       有滞后和落定，但零过冲，过冲的 UI 读作 bug。
//   「幽灵步进」——触控板松手后 ~1s 惯性 wheel 事件会再触发一次离散步进：
//       WheelGuard 累积阈值 + 触发后冷却期吃掉动量尾。
// 契约：dt 一律秒且调用方钳到 ≤1/30（tab 恢复的长帧直接丢，不要喂给
// 滤波器——exp/ODE 都只能保证「常规帧率下」轨迹一致）。
// 接线状态：待用集成面（reader/anim.ts __saAnim 探针配套原语层），勿按
// 死码清——当前无在线调用点：scroll sync 瞬时落位是正确语义、两个 wheel
// 处理是连续转发不是离散步进、cursor 走键盘。出现上表症状时再取。

/** §7.1+§7.2——帧率无关一阶跟随 + 移动目标 lead 补偿。
    k 是 1/s 的「紧度」不是每帧比例：跟随 4.5、回中 2.2、地平线 0.35
    （~3s 落定）是 motion-web 实测参考档。targetVel 非 0 时
    aim = target + targetVel/k——离散步进下抵消稳态滞后。 */
export function expFollow(
    x: number,
    target: number,
    k: number,
    dt: number,
    targetVel = 0,
): number {
    return x + (target + targetVel / k - x) * (1 - Math.exp(-k * dt));
}

/** §1/§7.4——阻尼比参数化弹簧（半隐式欧拉）。
    a = k·(target − x) − c·v，c = 2ζ√k：
      ζ<1 欠阻尼——过冲回弹，落地有分量（§1，ζ≈0.3–0.6）；
      ζ=1 临界——最快无过冲落定，UI chrome/姿态/缩放用这个（§7.4，
          k=120 ≈0.09s 到 63%，k=200 ≈0.14s 适合 scale）；
      ζ>1 过阻尼——慢爬，几乎不用。
    v 存内部状态——同一个量一个弹簧一个目标（§7.3）。 */
export class Spring {
    private v = 0;

    constructor(
        private x = 0,
        public k = 120,
        public zeta = 1,
    ) {}

    /** 推进一步并返回新值。dt 秒，调用方钳 ≤1/30。 */
    step(target: number, dt: number): number {
        const c = 2 * this.zeta * Math.sqrt(this.k);
        this.v += (this.k * (target - this.x) - c * this.v) * dt;
        this.x += this.v * dt;
        return this.x;
    }

    get value(): number {
        return this.x;
    }

    get velocity(): number {
        return this.v;
    }

    /** 瞬移到 x 并清零速度——重绑目标时用，不让旧速度污染新轨迹。 */
    snap(x: number): void {
        this.x = x;
        this.v = 0;
    }
}

/** §3——滚轮动量守卫：把连续 wheel delta 折成「一手势一步」。
    触控板惯性在松手后还发 ~1s 的衰减事件流，裸 offset += deltaY 会把
    动量尾当成第二次手势。用法：wheel 事件 feed(deltaY_px, now_ms)，
    返回 ±1 时执行一步；每个 rAF 调 tick() 让未达阈值的残留衰减。 */
export class WheelGuard {
    private acc = 0;
    private lockedUntil = 0;

    constructor(
        /** 累积多少 px 触发一步（~90px ≈ 一齿格） */
        private threshold = 90,
        /** 触发后锁定期 ms——整个动量尾都喂不进第二步 */
        private lockMs = 600,
        /** 每 rAF 帧残留衰减系数 */
        private decay = 0.92,
    ) {}

    /** 喂一条 wheel delta（已换算 px），返回 1/-1=触发一步，0=未触发
        或锁定期吞掉。 */
    feed(delta: number, now: number): -1 | 0 | 1 {
        if (now < this.lockedUntil) return 0;
        if (Math.sign(delta) !== Math.sign(this.acc)) this.acc = 0;
        this.acc += delta;
        if (Math.abs(this.acc) < this.threshold) return 0;
        const dir = this.acc > 0 ? 1 : -1;
        this.acc = 0;
        this.lockedUntil = now + this.lockMs;
        return dir;
    }

    /** 每 rAF 帧调用——未达阈值的旧累积衰减，防隔了几秒的 delta
        拼出新一步。 */
    tick(): void {
        this.acc *= this.decay;
    }

    reset(): void {
        this.acc = 0;
        this.lockedUntil = 0;
    }
}
