# Design Context：从已有上下文出发

**这是这个 skill 最重要的 one thing。**

好的 hi-fi 设计一定是从已有 design context 长出来的。**凭空做 hi-fi 是 last resort，一定会产出 generic 的作品**。所以每次设计任务开始，先问：有没有可以参考的东西？

## 什么是 Design Context

按优先级从高到低：

### 1. 用户的 Design System/UI Kit

用户自己产品已有的组件库、色彩 token、字型规范、icon 系统。**最完美的情况**。

### 2. 用户的 Codebase

如果用户给了代码库，里面就有活生生的组件实现。Read 那些组件文件：

- `theme.ts` / `colors.ts` / `tokens.css` / `_variables.scss`
- 具体的组件（Button.tsx、Card.tsx）
- Layout scaffold（App.tsx、MainLayout.tsx）
- Global stylesheets

**读代码抄 exact values**：hex codes、spacing scale、font stack、border radius。不要凭记忆重画。

### 3. 用户已发布的产品

如果用户有上线的产品但没给代码，用 Playwright 或让用户提供截图。

```bash
# 用Playwright截图一个公开URL
npx playwright screenshot https://example.com screenshot.png --viewport-size=1920,1080
```

让你看到真实的视觉 vocabulary。

### 4. 品牌指南/Logo/已有素材

用户可能有：Logo 文件、品牌色规范、营销物料、slide 模板。这些都是 context。

### 5. 竞品参考

用户说"像 XX 网站那样"——让他提供 URL 或截图。**不要**凭你训练数据里的模糊印象做。

### 6. 已知的 design system（fallback）

如果以上都没有，用公认的设计系统作为 base：

- Apple HIG
- Material Design 3
- Radix Colors（配色）
- shadcn/ui（组件）
- Tailwind 默认 palette

明确告诉用户你用的什么，让他知道这是起点不是定稿。

## 获取 Context 的流程

### Step 1：问用户

任务开始时的必问清单（来自`workflow.md`）：

```markdown
1. 你有现成的 design system/UI kit/组件库吗？在哪？
2. 有品牌指南、色彩/字体规范吗？
3. 可以给我现有产品的截图或 URL 吗？
4. 有 codebase 我可以读吗？
```

### Step 2：用户说"没有"时，帮他找

别直接放弃。尝试：

```markdown
让我看看有没有线索：

- 你之前的项目有相关设计吗？
- 公司的 marketing 网站用什么色彩/字型？
- 你产品的 Logo 什么风格？能给我一张吗？
- 有什么你欣赏的产品作为参考？
```

### Step 3：Read 所有能找到的 context

如果用户给了 codebase 路径，你读：

1. **先 list 文件结构**：找 style/theme/component 相关的文件
2. **读 theme/token 文件**：lift 具体的 hex/px values
3. **读 2-3 个代表性组件**：看视觉 vocabulary（hover state、shadow、border、padding node pattern）
4. **读 global stylesheet**：基础重置、font loading
5. **如果有 Figma 链接/截图**：看图，但**更相信代码**

**重要**：**不要**看了一眼就凭印象做。读下来有 30+ 个具体 values 才真的 lift 到了。

### Step 4：Vocalize 你要用的系统

看完 context 后，告诉用户你要用的系统：

```markdown
根据你的 codebase 和产品截图，我提炼的设计系统：

**色彩**

- Primary: #C27558（从 tokens.css）
- Background: #FDF9F0
- Text: #1A1A1A
- Muted: #6B6B6B

**字型**

- Display: Instrument Serif（从 global.css 的@font-face）
- Body: Geist Sans
- Mono: JetBrains Mono

**Spacing**（来自你的 scale 系统）

- 4, 8, 12, 16, 24, 32, 48, 64

**Shadow pattern**

- `0 1px 2px rgba(0,0,0,0.04)`（subtle card）
- `0 10px 40px rgba(0,0,0,0.1)`（elevated modal）

**Border-radius**

- 小组件 4px，卡片 12px，按钮 8px

**component vocabulary**

- Button：filled primary，outlined secondary，ghost tertiary，全部圆角 8px
- Card：白色背景，subtle shadow，无 border

我按这套系统开始做。确认没问题？
```

用户确认后再动手。

## 凭空做设计（没 Context 时的 fallback）

**强烈警告**：这种情况下的产出质量会显著下降。明确告诉用户。

```markdown
你没有 design context，我就只能基于通用直觉做。
产出会是"看起来 OK 但缺乏独特性"的东西。
你愿意继续，还是先补一些参考材料？
```

用户执意要你做，按这个顺序做决策：

### 1. 选一个 aesthetic direction

不要给 generic 结果。挑一个明确方向：

- brutally minimal
- editorial/magazine
- brutalist/raw
- organic/natural
- luxury/refined
- playful/toy
- retro-futuristic
- soft/pastel

告诉用户你选了哪个。

### 2. 选一个 known design system 作为骨架

- 用 Radix Colors 做配色（https://www.radix-ui.com/colors）
- 用 shadcn/ui 做组件 vocabulary（https://ui.shadcn.com）
- 用 Tailwind spacing scale（4 的倍数）

### 3. 选有特点的字体配对

不要用 Inter/Roboto。建议组合（从 Google Fonts 白嫖）：

- Instrument Serif + Geist Sans
- Cormorant Garamond + Inter Tight
- Bricolage Grotesque + Söhne（付费）
- Fraunces + Work Sans（注意 Fraunces 已经被 AI 用烂）
- JetBrains Mono + Geist Sans（technical feel）

### 4. 每个关键决策都有 reasoning

不要默默选。在 HTML 的 comment 里写：

```html
<!--
Design decisions:
- Primary color: warm terracotta (oklch 0.65 0.18 25) — fits the "editorial" direction  
- Display: Instrument Serif for humanist, literary feel
- Body: Geist Sans for cleanness contrast
- No gradients — committed to minimal, no AI slop
- Spacing: 8px base, golden ratio friendly (8/13/21/34)
-->
```

## Import 策略（用户给了 codebase）

如果用户说"import 这个 codebase 做参考"：

### 小型（<50 文件）

全部 Read，把 context 内化。

### 中型（50-500 文件）

Focus 在：

- `src/components/` 或 `components/`
- 所有 styles/tokens/theme 相关的文件
- 2-3 个代表性的整页组件（Home.tsx、Dashboard.tsx）

### 大型（>500 文件）

让用户指明 focus：

- "我要做 settings 页面" → 读现有的 settings 相关
- "我要做一个新的 feature" → 读整体 shell + 最接近的参考
- 不求全，求准

## 和 Figma/设计稿的配合

如果用户给了 Figma 链接：

- **不要**期望你能直接"转 Figma 为 HTML"——那需要额外工具
- Figma 链接通常不公开可访问
- 让用户：导出为**截图**发给你 + 告诉你具体的 color/spacing values

如果只给了 Figma 截图，告诉用户：

- 我能看到视觉，但取不到精确 values
- 关键数字（hex、px）请告诉我，或者 export as code（Figma 支持）

## 最后的提醒

**一个项目的设计质量上限，由你拿到的 context 质量决定**。

花 10 分钟收集 context，比花 1 小时凭空画 hi-fi 更有价值。

**遇到没 context 的情况，优先问用户要，而不是硬上**。
