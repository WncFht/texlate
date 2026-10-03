"""基线图组最小样式件——figure-viz 调色板口径的自包含子集。

只抽两个再生脚本实际用到的面：HUES 4 色 + NEUTRALS 4 色 +
apply_rc("paper") 的 rcParams（serif/CJK 字体栈按已安装面过滤）。
渲染审计 fv.audit 不随归档——属上游 skill 资产，图组已人工审定。
"""

import matplotlib.pyplot as plt
from matplotlib import font_manager

HUES = {
    "vteal": "#4F8FA5",
    "vorange": "#EE995B",
    "vcoral": "#C95B5B",
    "vgold": "#D9A93C",
}

NEUTRALS = {
    "vink": "#3A3F45",
    "vmist": "#D8DBDE",
    "paper": "#FFFFFF",
    "baseline": "#85898F",  # == vgray，参考线/脚注语义别名
}

# font.family 必须带具体清单：泛型别名 "serif" 只解析到单一字体、无逐字形
# 回退，CJK 会渲成豆腐块——西文条目在前、CJK 兜底殿后，apply_rc 按
# font_manager 已安装面过滤（缺失条目由 mpl 静默跳过，不报错）。
_SERIF_STACK = [
    "Times New Roman",
    "Times",
    "STIX Two Text",
    "STIXGeneral",
    "DejaVu Serif",
    "Noto Serif CJK SC",
    "LXGW WenKai",
    "Songti SC",
    "SimSun",
]


def apply_rc(theme: str = "paper") -> str:
    """套用 paper 主题 rcParams；非 "paper" 抛 ValueError。返回主题名。"""
    if theme != "paper":
        msg = f"unknown theme {theme!r}: only 'paper' is archived"
        raise ValueError(msg)
    installed = {f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams.update(
        {
            "figure.facecolor": NEUTRALS["paper"],
            "axes.facecolor": NEUTRALS["paper"],
            "savefig.facecolor": NEUTRALS["paper"],
            "svg.fonttype": "none",
            "axes.edgecolor": NEUTRALS["vink"],
            "axes.linewidth": 0.9,
            "axes.labelcolor": NEUTRALS["vink"],
            "xtick.color": NEUTRALS["vink"],
            "ytick.color": NEUTRALS["vink"],
            "text.color": NEUTRALS["vink"],
            "grid.color": NEUTRALS["vmist"],
            "legend.frameon": False,
            "hatch.color": "white",
            "hatch.linewidth": 1.2,
            "font.family": [n for n in _SERIF_STACK if n in installed],
            "mathtext.fontset": "stix",
        }
    )
    return theme
