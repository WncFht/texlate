"""ops.status_panel 模板叶 —— PAGE 单页 html/css 骨架
（status_panel.py 拆分叶）。

门面回引名单见 ``ops.status_panel._LEAF_EXPORTS``。
"""

from __future__ import annotations

PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="{refresh}">
<title>texlate 状态面板</title>
<style>
body {{ font: 14px/1.5 -apple-system,"Segoe UI","Noto Sans CJK SC",
       "PingFang SC",sans-serif; margin: 1.2em auto; max-width: 1180px;
       padding: 0 1em; color: #1f2328; background: #fff; }}
h1 {{ font-size: 1.15em; margin: 0 0 .15em; }}
h2 {{ font-size: 1em; margin: 1.2em 0 .35em; color: #0550ae;
     border-bottom: 1px solid #e5e7ea; padding-bottom: .15em; }}
code, pre {{ font-family: ui-monospace,"SF Mono",monospace;
           font-size: .92em; }}
pre {{ background: #f6f8fa; border: 1px solid #d8dce0; border-radius: 6px;
      padding: .55em .75em; overflow-x: auto; margin: 0; }}
a {{ color: #0969da; }}
.meta {{ color: #656d76; font-size: .85em; }}
.chips {{ display: flex; flex-wrap: wrap; gap: .6em; margin: .8em 0 .4em; }}
.chip {{ border: 1px solid #d8dce0; border-radius: 8px; padding: .45em .8em;
        background: #fff; min-width: 9em;
        box-shadow: 0 1px 2px #00000008; }}
.chip .k {{ font-size: .72em; color: #656d76; }}
.chip .v {{ font-size: 1.3em; font-weight: 650; font-variant-numeric:
           tabular-nums; }}
.chip .s {{ font-size: .75em; color: #656d76; }}
.chip.good .v {{ color: {c_clean}; }}
.chip.bad .v {{ color: {c_fail}; }}
.cap {{ font-size: .8em; color: #656d76; margin: .7em 0 .25em; }}
.prow {{ margin: .35em 0; font-size: .93em; }}
.stack {{ display: flex; height: 14px; border-radius: 7px; overflow: hidden;
         background: #eef1f4; margin: .25em 0 .15em; }}
.seg {{ height: 100%; }}
.legend {{ font-size: .8em; color: #444; display: flex; gap: 1.1em;
          flex-wrap: wrap; }}
.lg i {{ display: inline-block; width: .75em; height: .75em;
        border-radius: 2px; margin-right: .3em; vertical-align: -1px; }}
.two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0 2em; }}
.strip {{ display: flex; flex-wrap: wrap; gap: 2px; margin: .2em 0; }}
.strip i {{ width: 14px; height: 14px; border-radius: 3px; }}
.hrow {{ display: flex; align-items: center; gap: .6em; margin: .12em 0; }}
.hl {{ width: 21em; font-size: .85em; overflow: hidden;
      text-overflow: ellipsis; white-space: nowrap; }}
.hb {{ flex: 1; height: 11px; background: #eef1f4; border-radius: 5px;
      overflow: hidden; }}
.hf {{ height: 100%; }}
.hn {{ width: 10em; font-size: .82em; color: #444;
      font-variant-numeric: tabular-nums; }}
.gatebar {{ position: relative; height: 20px; background: #eef1f4;
           border-radius: 6px; margin: .4em 0 .2em; overflow: hidden; }}
.gfill {{ height: 100%; background: linear-gradient(90deg,#2da44e99,#2da44e); }}
.gmark {{ position: absolute; top: 0; bottom: 0; width: 2px;
         background: {c_fail}; }}
.gtxt {{ position: absolute; left: .6em; top: 1px; font-size: .78em;
        color: #fff; text-shadow: 0 0 3px #0006; }}
table {{ border-collapse: collapse; font-size: .86em; width: 100%; }}
th {{ text-align: left; color: #656d76; font-weight: 600; font-size: .8em;
     border-bottom: 1px solid #d8dce0; padding: .25em .7em .25em 0; }}
td {{ padding: .22em .7em .22em 0; border-bottom: 1px solid #eef1f4;
     vertical-align: middle; }}
.bdg {{ display: inline-block; border: 1px solid; border-radius: 9px;
       padding: 0 .55em; font-size: .78em; line-height: 1.5; }}
.mb {{ display: inline-block; width: 8em; height: 8px; background: #eef1f4;
      border-radius: 4px; overflow: hidden; vertical-align: middle; }}
.mf {{ height: 100%; background: {c_info}; }}
.mbn {{ font-size: .82em; color: #444; margin-left: .4em; }}
.msrow {{ display: flex; align-items: stretch; gap: .4em; margin: .3em 0; }}
.ms {{ border: 1px solid #d8dce0; border-radius: 8px; padding: .4em .9em;
      min-width: 6.5em; }}
.ms .msn {{ font-weight: 700; font-size: 1.05em; }}
.ms .mss {{ font-size: .8em; color: #656d76; }}
.ms .msx {{ font-size: .78em; margin-top: .2em; }}
.ms-done {{ background: #f0fff4; border-color: #2da44e55; }}
.ms-done .msn {{ color: {c_clean}; }}
.ms-act {{ background: #fff8e6; border-color: #d4a72c88; }}
.ms-act .msn {{ color: {c_part}; }}
.ms-pend {{ color: #8b949e; }}
.msarr {{ align-self: center; color: #8b949e; }}
</style></head><body>
<h1>texlate 状态面板</h1>
<div class="meta">生成于 {now} · 每 {refresh}s 自刷 · 数据缓存 ≤60s ·
只读 · <a href="http://127.0.0.1:8765/">产品阅读器 :8765</a></div>
{chips}
{body}
</body></html>
"""
