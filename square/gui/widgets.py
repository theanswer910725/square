"""界面小部件：截图图标、窗口图标与悬停提示。"""
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageDraw

# CustomTkinter 官方仓库自带的 Windows 图标（256×256，含透明通道）
ICON_ICO = Path(__file__).with_name("assets") / "CustomTkinter_icon_Windows.ico"


def set_window_icon(win):
    """设置窗口/任务栏图标。

    必须在窗口首次显示之前调用：Windows 任务栏按钮会缓存窗口第一次映射时的
    图标，窗口显示后再改通常不刷新，仍旧显示 python 默认图标。
    """
    try:
        win.iconbitmap(str(ICON_ICO))
    except Exception:
        pass


def make_scan_icon(size=16, scale=4, color="#1f2328"):
    """极简线性「截图」图标：四角取景框。按 scale 倍绘制，缩小后边缘干净。"""
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = max(1, int(round(1.4 * scale)))
    m = int(round(1.5 * scale))
    ln = int(round(size * scale * 0.34))
    hi = s - m - 1
    for x, y, dx, dy in ((m, m, 1, 1), (hi, m, -1, 1),
                         (m, hi, 1, -1), (hi, hi, -1, -1)):
        d.line([(x, y), (x + dx * ln, y)], fill=color, width=w)
        d.line([(x, y), (x, y + dy * ln)], fill=color, width=w)
    return img


class Tooltip:
    """轻量悬停提示（CTk 本身没有 tooltip）"""

    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, _=None):
        if self.tip or not self.widget.winfo_ismapped():
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2 - 26
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tip = tk.Toplevel(self.widget)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tk.Label(tip, text=self.text, bg="#2b2f36", fg="#ffffff",
                 font=("Microsoft YaHei UI", 12), padx=6, pady=2).pack()
        tip.geometry(f"+{x}+{y}")
        self.tip = tip

    def _hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None
