r"""builtins._gfxm_assets — 缺图占位资产数据叶 (gfx_missing 拆分)。

文本 EPS + 二进制 PNG/PDF/JPEG 四件占位 (同构 200x150 灰底+边框+
对角线, Title/COM 段留「图缺」痕)——``_gfxm_stub`` 按 payload 扩展名
分发, xetex image-sniff 认格式字节故 EPS 文本不可冒充二进制族。
"""

from __future__ import annotations

import base64

__all__ = [
    "_EPS_PLACEHOLDER",
    "_JPEG_PLACEHOLDER",
    "_PDF_PLACEHOLDER",
    "_PNG_PLACEHOLDER",
]


# ════════════════════════════════════════════════════════════════
# missing_file 的 PS 族图档真缺件 → wdir 落占位 EPS (failmine3 #164a)
# ════════════════════════════════════════════════════════════════


#: 最小合法 EPS 占位：epsfig/graphics 两系 bbox 解析都吃 ``%%BoundingBox``,
#: xdvipdfmx 走内嵌 gs 蒸馏 (沙箱 ``-no-shell-escape`` 下仍通——epsprobe
#: 实测 ``File: ph.eps Graphic file (type eps)`` 载入出 PDF); tectonic 侧
#: .eps 是 ps_image 墙，占位件是真 EPS 可由 eps_to_pdf(15) 的 gs 照常转换。
#: 边框 + 对角线让读者可辨「图缺」占位而非空白; 200x150bp 近常见插图比例，
#: 调用点 ``width=``/``scale=`` 照常缩放。
_EPS_PLACEHOLDER = (
    "%!PS-Adobe-3.0 EPSF-3.0\n"
    "%%BoundingBox: 0 0 200 150\n"
    "%%Title: fixloop placeholder (graphic absent from e-print)\n"
    "%%EndComments\n"
    "0.55 setgray 1.2 setlinewidth\n"
    "newpath 0 0 moveto 200 0 lineto 200 150 lineto 0 150 lineto closepath stroke\n"
    "newpath 0 0 moveto 200 150 lineto stroke\n"
    "newpath 200 0 moveto 0 150 lineto stroke\n"
    "%%EOF\n"
)


# ════════════════════════════════════════════════════════════════
# xetex 图形域二进制占位 (failmine4-covgap: "Unable to load picture or
# PDF file" 臂 6 格) —— 扩展名决定 xetex image-sniff 路径，EPS 文本写进
# .png/.jpg/.pdf 件名被格式探测拒载，须真格式字节。三件同构 200x150
# 灰底 + 边框 + 对角线 (EPS 占位的像素版), Title/COM 段同痕可辨「图缺」。
# 字节产物经 identify/pdfinfo/gs 结构验证 + xetex \includegraphics
# 真编译实证; 生成器曾存档 covgap 车道 (PNG zlib 程序化
# 合成 / PDF 手写 xref / JPEG magick 生成 + 手注 COM 段)。
# ════════════════════════════════════════════════════════════════


#: 200x150 RGB PNG (zlib IDAT, tEXt Title 留痕)。
_PNG_PLACEHOLDER = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAMgAAACWCAIAAAAUvlBOAAAAN3RFWHRUaXRsZQBmaXhsb29wIHBs"
    "YWNlaG9sZGVyIChncmFwaGljIGFic2VudCBmcm9tIGUtcHJpbnQpfeIzqwAAA4JJREFUeNrt3UFu"
    "4zAMBVDdH3PIHGV2RafINLEjSiL5/qpAF7E+X9HEsezxRyQgQwWyAtZD5Faew/r+Cx3JbVVfP4/v"
    "mNiSD1U9h4WXfELqBSy25LaqF7DYknuqXsPCS+6ReAsWW3IVw7uw2JJLDC7Awgupq07GJStsURUC"
    "iy2qomDhhVQgLLaoioLFFlVRsPBCKhAWW1RFwWKLqihYeCEVCIut5qoCYbHVWVUsLLx6kloEi62G"
    "qhbBYqubqnWw8OpDagMstpqo2gCLrQ6q9sDCqzapzbDYql3yTlhsFa53Myy8qlZ6BCy26pV5Ciy2"
    "itV4ECy8KlV3HCy2apR2Iiy2CtR1KCy8sld0NCy28pZzOiy2ktaSABZeGatIA4utXCVkgsVWouUn"
    "g9WWV7olp4TVzVbGxWaF1cdW0mUmhlWeV+qlpYdV1Vb2RVWAVc9WgeUUgVVsHmVmMcr8uRd4X1Jp"
    "EMP/EYcNVrU5Ff7wMUp+Yk/0ZW3V8odTQQ4PrArzK/+1QQtYjyN3sHQofPjSjSqwss614RUZo9Xl"
    "TRtv69Ot5OG6OarAyjTvttdSt4b1WHKv887FDjsUPJgDrNN52aYG1nwQVIE1nwVVYE32gRRY86FQ"
    "BdZ8W1SBNZkXUmDNt0UVWPNtUQVWCC9dgQUWWHlUqQssb97BcroBLKrYAiuEFF5gxapiC6xYImyB"
    "FSgDL7CiQLAFVhQFtmz/sv0LrISDt2G13eKXjbynLTcFqfyiYLUYsNsYUcUWWAkn6laRVLEFVrYR"
    "1rblAQIOEqyiA/PIE6occFdYHisHlsFUtlUHVrGR1BiHh41bFFg9Pq7XeL+YFVaT89d5R5MPVsMr"
    "BTIOaDjrY8ndYTW/2DfXmHLAsvUlUQlpYFGVq4ocsKhKV8jpsJBKWs7RsKjKW9G5sKhKXdSJsJAq"
    "UNpxsKiqUd1ZsKgqU+ApsJAqVuYRsKiqV+l+WFSVLHYnLKQKl7wNFlW1q94Di6rytlbDQqoJr6Ww"
    "qOpjax0sqlrZWgELqYa8wmFR1dNWLCyq2tqKgoVUc14hsKhiaz4sqtiaDAspvObDooqt+bCoYmsy"
    "LKTwmg+LKrbmw6KKrcmwkMJrPiyq2JoPiyq2LlF5DQspuYThLVhUyVUSr2FRJTdg/AYLKbnN67+w"
    "qJJPbD2HRZV8aOsnLKRkCq9/YFEls2w9hyUyJWBJSP4CIWwCxuF8Zi8AAAAASUVORK5CYII="
)
#: 单页 PDF 1.4 (5 obj, MediaBox[0 0 200 150], 边框+X stream, Info/Title)。


_PDF_PLACEHOLDER = base64.b64decode(
    "JVBERi0xLjQKJSBmaXhsb29wIHBsYWNlaG9sZGVyIChncmFwaGljIGFic2VudCBmcm9tIGUtcHJp"
    "bnQpCjEgMCBvYmoKPDwvVHlwZS9DYXRhbG9nL1BhZ2VzIDIgMCBSPj4KZW5kb2JqCjIgMCBvYmoK"
    "PDwvVHlwZS9QYWdlcy9LaWRzWzMgMCBSXS9Db3VudCAxPj4KZW5kb2JqCjMgMCBvYmoKPDwvVHlw"
    "ZS9QYWdlL1BhcmVudCAyIDAgUi9NZWRpYUJveFswIDAgMjAwIDE1MF0vQ29udGVudHMgNCAwIFIv"
    "UmVzb3VyY2VzPDw+Pj4+CmVuZG9iago0IDAgb2JqCjw8L0xlbmd0aCA2Nj4+CnN0cmVhbQowLjU1"
    "IGcgMS41IHcKMSAxIDE5OCAxNDggcmUgUwoxIDEgbSAxOTkgMTQ5IGwgUwoxOTkgMSBtIDEgMTQ5"
    "IGwgUwplbmRzdHJlYW0KZW5kb2JqCjUgMCBvYmoKPDwvVGl0bGUoZml4bG9vcCBwbGFjZWhvbGRl"
    "cikvUHJvZHVjZXIoZml4bG9vcCk+PgplbmRvYmoKeHJlZgowIDYKMDAwMDAwMDAwMCA2NTUzNSBm"
    "IAowMDAwMDAwMDYxIDAwMDAwIG4gCjAwMDAwMDAxMDYgMDAwMDAgbiAKMDAwMDAwMDE1NyAwMDAw"
    "MCBuIAowMDAwMDAwMjUxIDAwMDAwIG4gCjAwMDAwMDAzNjQgMDAwMDAgbiAKdHJhaWxlcgo8PC9T"
    "aXplIDYvUm9vdCAxIDAgUi9JbmZvIDUgMCBSPj4Kc3RhcnR4cmVmCjQyOQolJUVPRgo="
)
#: 200x150 灰阶 baseline JPEG (SOI 后手注 FF FE COM 段留痕)。


_JPEG_PLACEHOLDER = base64.b64decode(
    "/9j//gAzZml4bG9vcCBwbGFjZWhvbGRlciAoZ3JhcGhpYyBhYnNlbnQgZnJvbSBlLXByaW50Kf/g"
    "ABBKRklGAAEBAAABAAEAAP/bAEMACAYGBwYFCAcHBwkJCAoMFA0MCwsMGRITDxQdGh8eHRocHCAk"
    "LicgIiwjHBwoNyksMDE0NDQfJzk9ODI8LjM0Mv/AAAsIAJYAyAEBIgD/xAAYAAEBAQEBAAAAAAAA"
    "AAAAAAAABwYFA//EACkQAQAAAwgDAQEAAgMAAAAAAAABAwQCBQcXM1R0sZOU0QYREmFxgeH/2gAI"
    "AQEAAD8A8/2n7So/MVcIxhUTrM6dMswhZnxs/wCP8j/6yucM3aVftx+GcM3aVftx+GcM3aVftx+G"
    "cM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVf"
    "tx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM"
    "3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+NV+L/AGlR+nq4xhCok2ZM6XZjC1Pj"
    "a/y/sY/GVxh16bkTu4JaAAAAAAAKlg9r1XIk9xMYdem5E7uCWgAAAAAACpYPa9VyJPcTGHXpuRO7"
    "gloAAAAAAAqWD2vVciT3Exh16bkTu4JaAAAAAAAKlg9r1XIk9xMYdem5E7uCWgAAAAAACpYPa9Vy"
    "JPcTGHXpuRO7gloAAAAAAAqWD2vVciT3Exh16bkTu4JaAAAAAAAKlg9r1XIk9xMYdem5E7uCWgAA"
    "AAAACpYPa9VyJPcTGHXpuRO7gloAAAAAAAqWD2vVciT3Exh16bkTu4JaAAAAAAAKlg9r1XIk9xMY"
    "dem5E7uCWgAAAAAACpYPa9VyJPcTGHXpuRO7gloAAAAAAAqWD2vVciT3Exh16bkTu4JaAAAAAAAK"
    "lg9r1XIk9xMYdem5E7uCWgAAAAAACpYPa9VyJPcTGHXpuRO7gloAAAAAAAqWD2vVciT3Exh16bkT"
    "u4JaAAAAAAAKlg9r1XIk9xMYdem5E7uCWgAAAAAACpYPa9VyJPcVJv38NJvyst2q2VTz7FibbtS4"
    "WrduH8/sf9f8QcnKi6NhSeWYZUXRsKTyzDKi6NhSeWYZUXRsKTyzDKi6NhSeWYZUXRsKTyzDKi6N"
    "hSeWYZUXRsKTyzDKi6NhSeWYZUXRsKTyzDKi6NhSeWYZUXRsKTyzDKi6NhSeWYZUXRsKTyzDKi6N"
    "hSeWY6txfhpNxVVm3QyqeTZtTLFqZCzbtx/v8j/v/t//2Q=="
)
